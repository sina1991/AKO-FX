"""Optional real-browser acceptance. Requires playwright and Chromium."""
import os
import tempfile
import threading
from datetime import datetime,timezone
from unittest.mock import patch
from playwright.sync_api import sync_playwright, expect
from ako_fx.server import Server
from ako_fx.services.identity import register
from ako_fx.store import init, transaction

def run():
    clock=[int(datetime(2026,11,16,12,tzinfo=timezone.utc).timestamp())]
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'AKO_DB':tmp+'/ui.db'}), patch('ako_fx.services.prop.now',side_effect=lambda:clock[0]):
        init()
        with transaction() as db: register(db,{'email':'admin@example.com','password':'Admin-password-123'},'admin')
        server=Server(('127.0.0.1',0),'all'); thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(executable_path=os.environ.get('AKO_CHROMIUM'),headless=True,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1440,'height':1000})
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto('http://127.0.0.1:'+str(server.server_port))
                def login(email,password,register=False):
                    page.locator('#authform input[name=email]').fill(email)
                    page.locator('#authform input[name=password]').fill(password)
                    page.locator('#authform button[value='+('register' if register else 'login')+']').click()
                    page.locator('#dashboard').wait_for(state='visible')
                    page.locator('#refresh').wait_for(state='visible')
                    expect(page.locator('#refresh')).to_be_enabled()
                def idle(): expect(page.locator('#refresh')).to_be_enabled()
                login('trader@example.com','Trader-password-123',True)
                page.locator('#fundingform input').fill('2000')
                page.locator('#fundingform button').click();idle()
                assert 'pending' in page.locator('#requests').inner_text()
                page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                login('admin@example.com','Admin-password-123')
                page.locator('#adminrequests button').filter(has_text='تأیید').click();idle()
                assert 'approved' in page.locator('#adminrequests').inner_text()
                page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                login('trader@example.com','Trader-password-123')
                assert '2,000.00' in page.locator('#balance').inner_text()
                page.locator('#newaccount').click();idle()
                page.locator('#accounts form').first.locator('input').fill('500')
                page.locator('#accounts form').first.locator('button').click();idle()
                assert '500.00' in page.locator('#accounts').inner_text()
                page.locator('#accounts form').nth(1).locator('button').click();idle()
                page.locator('#accounts button').filter(has_text='بستن').click();idle()
                page.locator('#plans button').filter(has_text='خرید با اعتبار آزمایشی').first.click();idle()
                assert page.locator('#accounts article').count()==2
                # Exercise the A stage-1 lifecycle through UI, using a fixture clock only.
                for day in range(5):
                    if day: clock[0]+=86400
                    card=page.locator('#accounts article').filter(has_text='30nA-Prop')
                    card.locator('input[name=quantity]').fill('2000' if day==4 else '1')
                    card.locator('button').filter(has_text='باز کردن معامله دمو').click();idle()
                    if day==4:
                        page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                        login('admin@example.com','Admin-password-123')
                        page.locator('#scenario-up').click();idle()
                        page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                        login('trader@example.com','Trader-password-123')
                    clock[0]+=31
                    page.locator('#accounts article').filter(has_text='30nA-Prop').locator('button').filter(has_text='بستن').click();idle()
                card=page.locator('#accounts article').filter(has_text='30nA-Prop')
                assert 'awaiting_review' in card.inner_text()
                card.locator('button').filter(has_text='درخواست مرحله بعد').click();idle()
                page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                login('admin@example.com','Admin-password-123')
                review=page.locator('#propreviews .row').first
                review.locator('input[name=reason]').fill('Verified paper identity and all policy checks')
                for check in review.locator('input[type=checkbox]').all()[:6]:check.check()
                review.locator('button').filter(has_text='ثبت تصمیم').click();idle()
                page.locator('#logout').click();page.locator('#auth').wait_for(state='visible');idle()
                login('trader@example.com','Trader-password-123')
                assert 'مرحله 2' in page.locator('#accounts article').filter(has_text='30nA-Prop').inner_text()
                page.set_viewport_size({'width':390,'height':844})
                assert page.locator('html').evaluate('(el) => el.scrollWidth <= window.innerWidth')
                assert not errors,errors
                browser.close()
                print('Browser PASS: registration, funding request, admin approval, wallet, broker deposit, open/close, prop purchase, five trading days, target lock, manual stage approval, mobile overflow, JS errors')
        finally: server.shutdown();server.server_close();thread.join()

if __name__=='__main__': run()
