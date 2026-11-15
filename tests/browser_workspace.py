"""Real Chromium checks of right-click menus, owner layouts and financial isolation."""
import json
import os
import tempfile
import threading
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
from ako_fx.server import Server
from ako_fx.store import init,transaction
from ako_fx.services.identity import register


def run():
 with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AKO_DB':tmp+'/workspace.db'}):
  init()
  with transaction() as db:
   register(db,{'email':'one@example.com','password':'Workspace-password-123'})
   register(db,{'email':'two@example.com','password':'Workspace-password-123'})
  server=Server(('127.0.0.1',0),'all');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('AKO_CHROMIUM'),headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    url='http://127.0.0.1:'+str(server.server_port)
    page.goto(url)
    def idle():expect(page.locator('#refresh')).to_be_enabled()
    def login(email):
     page.locator('#authform input[name=email]').fill(email)
     page.locator('#authform input[name=password]').fill('Workspace-password-123')
     page.locator('#authform button[value=login]').click()
     page.locator('#dashboard').wait_for(state='visible');idle()
    def slot(key):return page.locator('[data-slot-key="'+key+'"]')
    def menu(key='wallet'):
     slot(key).locator(':scope > .slot-chrome .slot-caption').click(button='right')
     expect(page.locator('#workspace-menu')).to_be_visible()
    def choose(name):page.locator('#workspace-menu').get_by_role('menuitem',name=name,exact=True).click()
    def global_menu():page.locator('#workspace-tools').get_by_role('button',name='منوی فضای کاری',exact=True).click()
    def confirm():page.locator('#workspace-dialog').get_by_role('button',name='تأیید',exact=True).click();idle()
    def save_text(value):
     page.locator('#workspace-dialog input').fill(value)
     page.locator('#workspace-dialog').get_by_role('button',name='ذخیره',exact=True).click();idle()
    login('one@example.com')
    menu();expect(page.locator('#workspace-menu').get_by_role('menuitem',name='ثبت درخواست برای ادمین',exact=True)).to_be_visible()
    page.keyboard.press('Escape')
    expect(slot('wallet').locator(':scope > .slot-chrome button')).to_be_focused()
    # Native input editing menus remain native; right-click must not send a command.
    page.locator('#fundingform input').click(button='right')
    expect(page.locator('#workspace-menu')).to_be_hidden();page.keyboard.press('Escape')
    with transaction() as db:assert db.execute('SELECT COUNT(*) FROM funding').fetchone()[0]==0
    menu();choose('تغییر نام');save_text('کیف پول آبی من')
    expect(slot('wallet').locator(':scope > .slot-chrome')).to_contain_text('کیف پول آبی من')
    menu();choose('رنگ‌بندی و اندازه')
    page.locator('#workspace-dialog input[type=color]').nth(0).evaluate("el=>el.value='#aa3366'")
    page.locator('#workspace-dialog input[type=color]').nth(1).evaluate("el=>el.value='#153047'")
    page.locator('#workspace-dialog input[type=number]').fill('18')
    page.locator('#workspace-dialog select').select_option('wide')
    page.locator('#workspace-dialog').get_by_role('button',name='ذخیره ظاهر',exact=True).click();idle()
    assert slot('wallet').evaluate("el=>getComputedStyle(el).getPropertyValue('--slot-color').trim()")=='#aa3366'
    assert slot('wallet').get_attribute('data-slot-size')=='wide'
    menu();choose('جمع‌کردن اسلات');idle();expect(slot('wallet').locator(':scope > .slot-body')).to_be_hidden()
    menu();choose('بازکردن اسلات');idle();expect(slot('wallet').locator(':scope > .slot-body')).to_be_visible()
    menu();choose('قفل چیدمان');idle();menu()
    expect(page.locator('#workspace-menu').get_by_role('menuitem',name='حذف اسلات از چیدمان',exact=True)).to_be_disabled()
    choose('بازکردن قفل چیدمان');idle()
    menu();choose('Duplicate نمایشی');idle()
    assert page.locator('#custom-slots > article').count()==1
    assert page.locator('#custom-slots form').count()==0
    page.locator('#workspace-tools').get_by_role('button',name='+ یادداشت',exact=True).click()
    secret='<img src=x onerror=alert(1)>\nیادداشت خصوصی اول'
    page.locator('#workspace-dialog textarea').fill(secret)
    page.locator('#workspace-dialog').get_by_role('button',name='ذخیره',exact=True).click();idle()
    expect(page.locator('#custom-slots .slot-note')).to_have_text(secret)
    assert page.locator('#custom-slots img').count()==0
    global_menu();choose('ذخیره چیدمان')
    page.locator('#workspace-dialog input').fill('چیدمان من')
    page.locator('#workspace-dialog').get_by_role('button',name='ذخیره چیدمان',exact=True).click();idle()
    # Delete hides a slot and leaves actual accounts/ledger unchanged.
    menu();choose('حذف اسلات از چیدمان');confirm();expect(slot('wallet')).to_be_hidden()
    global_menu();choose('بازیابی اسلات‌های حذف‌شده')
    page.locator('#workspace-dialog').get_by_role('button',name='کیف پول',exact=True).click();idle()
    expect(slot('wallet')).to_be_visible()
    note=page.locator('#custom-slots .slot-note').locator('..').locator('..')
    note_key=note.get_attribute('data-slot-key')
    assert note_key
    menu(note_key);choose('حذف اسلات از چیدمان');confirm()
    assert page.locator('#custom-slots .slot-note').count()==0
    global_menu();choose('واگردانی آخرین تغییر');idle()
    expect(page.locator('#custom-slots .slot-note')).to_have_text(secret)
    menu();choose('تغییر نام');save_text('نام موقت')
    global_menu();choose('بارگذاری / حذف چیدمان')
    page.locator('#workspace-dialog').get_by_role('button',name='بارگذاری',exact=True).click();confirm()
    expect(slot('wallet').locator(':scope > .slot-chrome')).to_contain_text('کیف پول آبی من')
    # Read-only Terminal preview contains no bearer token or credentials.
    menu();choose('دستور Terminal / اطلاعات')
    expect(page.locator('#workspace-dialog textarea')).to_have_value('python3 -m ako_fx.cli GET /api/wallet')
    page.locator('#workspace-dialog').get_by_role('button',name='انصراف',exact=True).click()
    menu();choose('جابه‌جایی به پایین / بعد');idle()
    assert slot('wallet').evaluate("el=>el.parentElement.querySelector('[data-slot-key]').dataset.slotKey")=='broker-launcher'
    menu();choose('Pin در ابتدای گروه');idle()
    assert slot('wallet').evaluate("el=>el.parentElement.querySelector('[data-slot-key]').dataset.slotKey")=='wallet'
    slot('wallet').focus();page.keyboard.press('Shift+F10');expect(page.locator('#workspace-menu')).to_be_visible();page.keyboard.press('Escape')
    page.reload();login('one@example.com')
    expect(slot('wallet').locator(':scope > .slot-chrome')).to_contain_text('کیف پول آبی من')
    expect(page.locator('#custom-slots .slot-note')).to_have_text(secret)
    # Three-dot alternative and viewport-clamped menu on a small screen.
    page.set_viewport_size({'width':390,'height':844})
    slot('wallet').locator(':scope > .slot-chrome button').click()
    rect=page.locator('#workspace-menu').bounding_box()
    assert rect['x']>=0 and rect['y']>=0 and rect['x']+rect['width']<=390 and rect['y']+rect['height']<=844
    page.keyboard.press('Escape')
    assert page.locator('html').evaluate('(el)=>el.scrollWidth<=innerWidth')
    page.locator('#logout').click();page.locator('#auth').wait_for(state='visible')
    login('two@example.com')
    assert page.locator('#custom-slots > article').count()==0
    assert secret not in page.locator('body').inner_text()
    assert 'کیف پول آبی من' not in slot('wallet').inner_text()
    with transaction() as db:
     assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0]==0
     assert db.execute('SELECT COUNT(*) FROM entries').fetchone()[0]==0
     assert db.execute('SELECT COUNT(*) FROM funding').fetchone()[0]==0
     assert db.execute('SELECT COUNT(*) FROM dashboard_layouts').fetchone()[0]==1
    assert not errors,errors
    browser.close()
    print('Workspace Browser PASS: context actions, native input menus, rename/color/size, collapse/lock, mirror/note, save/load, delete/restore/undo, order/pin, keyboard, mobile, persistence and owner/financial isolation')
  finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':run()
