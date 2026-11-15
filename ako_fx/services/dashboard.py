"""Owner-scoped layout only. Never changes trading accounts or ledger entries."""
import json
import re
from ako_fx.store import Error, audit

EMPTY={'items':{},'slots':[],'saved':[]}
KEY=re.compile(r'^(?:wallet|broker-launcher|market-prices|credit-requests|ledger|prop-review|quotes-panel|admin-funding|admin-audit|plans-panel|accounts-panel|(?:account|position|funding|review):[a-f0-9]{32}|plan:[ab]-[0-9]{4,6}|slot-[a-f0-9]{12})$')
STYLE_FIELDS={'title','color','background','foreground','size','collapsed','pinned','locked','hidden','order','font_size'}

def text(value,maximum,field):
    if not isinstance(value,str) or len(value)>maximum: raise Error('Invalid dashboard '+field)
    return value

def style(value):
    if not isinstance(value,dict) or set(value)-STYLE_FIELDS: raise Error('Invalid slot appearance')
    for k,v in value.items():
        if k=='title': text(v,100,'title')
        elif k in ('color','background','foreground'):
            if not isinstance(v,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',v): raise Error('Invalid slot color')
        elif k=='size':
            if v not in ('normal','wide','compact'): raise Error('Invalid slot size')
        elif k in ('collapsed','pinned','locked','hidden'):
            if type(v)!=bool: raise Error('Slot flags must be boolean')
        elif k=='order':
            if type(v)!=int or not -10000<=v<=10000: raise Error('Invalid slot order')
        elif k=='font_size':
            if type(v)!=int or not 12<=v<=24: raise Error('Invalid font size')
    return value

def body(value,role):
    if not isinstance(value,dict) or set(value)-{'items','slots'}: raise Error('Invalid dashboard layout')
    items=value.get('items',{});slots=value.get('slots',[])
    if not isinstance(items,dict) or len(items)>200 or not isinstance(slots,list) or len(slots)>24:
        raise Error('Dashboard supports 200 appearance entries and 24 custom slots')
    for k,v in items.items():
        if not isinstance(k,str) or not KEY.fullmatch(k): raise Error('Invalid slot key')
        style(v)
    seen=set()
    for s in slots:
        if not isinstance(s,dict) or set(s)-{'id','kind','source','text'}: raise Error('Invalid custom slot')
        sid=s.get('id','')
        if not isinstance(sid,str) or not re.fullmatch('slot-[a-f0-9]{12}',sid) or sid in seen:
            raise Error('Invalid or duplicate custom slot id')
        seen.add(sid)
        if s.get('kind')=='note':
            if 'source' in s: raise Error('A note cannot bind a source')
            text(s.get('text',''),2000,'note text')
        elif s.get('kind')=='mirror':
            source=s.get('source','')
            if not isinstance(source,str) or not KEY.fullmatch(source) or source.startswith('slot-') or 'text' in s:
                raise Error('Invalid source binding')
            if role!='admin' and source in ('prop-review','quotes-panel','admin-funding','admin-audit'):
                raise Error('Admin slot binding requires admin access',403)
        else: raise Error('Custom slot must be note or mirror')
    return {'items':items,'slots':slots}

def validate(value,role):
    if not isinstance(value,dict) or set(value)-{'items','slots','saved'}: raise Error('Invalid dashboard settings')
    current=body({k:v for k,v in value.items() if k!='saved'},role)
    saved=value.get('saved',[])
    if not isinstance(saved,list) or len(saved)>5: raise Error('At most five saved layouts are supported')
    names=set();normalized=[]
    for item in saved:
        if not isinstance(item,dict) or set(item)!={'name','layout'}: raise Error('Invalid saved layout')
        name=text(item['name'],60,'layout name').strip()
        if not name or name in names: raise Error('Layout names must be nonempty and unique')
        names.add(name);normalized.append({'name':name,'layout':body(item['layout'],role)})
    current['saved']=normalized
    if len(json.dumps(current,ensure_ascii=False).encode())>98304: raise Error('Dashboard settings exceed 96 KiB',413)
    return current

def load(db,user):
    row=db.execute('SELECT revision,config FROM dashboard_layouts WHERE user_id=?',(user['id'],)).fetchone()
    return {'revision':row['revision'] if row else 0,'layout':json.loads(row['config']) if row else json.loads(json.dumps(EMPTY))}

def save(db,user,data):
    if not isinstance(data,dict) or set(data)!={'revision','layout'} or type(data.get('revision'))!=int or data['revision']<0:
        raise Error('Expected revision and layout')
    layout=validate(data['layout'],user['role'])
    previous=load(db,user)
    if data['revision']!=previous['revision']: raise Error('Layout changed in another tab; refresh before editing',409)
    revision=previous['revision']+1
    db.execute('INSERT INTO dashboard_layouts(user_id,revision,config) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,config=excluded.config',
        (user['id'],revision,json.dumps(layout,ensure_ascii=False)))
    audit(db,user['id'],'dashboard.layout.save',str(revision))
    return {'revision':revision,'layout':layout}
