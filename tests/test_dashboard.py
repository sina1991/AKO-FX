import json
import unittest
import test_acceptance as base
from ako_fx.store import transaction,init

class Dashboard(unittest.TestCase):
    setUp=base.Acceptance.setUp
    tearDown=base.Acceptance.tearDown
    call=base.Acceptance.call
    error=base.Acceptance.error
    def get(self,**kw):return self.call('GET','/api/dashboard/layout',**kw)
    def save(self,layout,revision=0,**kw):return self.call('POST','/api/dashboard/layout',{'revision':revision,'layout':layout},**kw)
    def layout(self):return {'items':{'wallet':{'title':'کیف پول شخصی','color':'#aabbcc','background':'#142536','font_size':18,'size':'wide','pinned':True,'collapsed':False,'locked':False,'hidden':False,'order':10}},'slots':[{'id':'slot-123456abcdef','kind':'note','text':'یادداشت خصوصی من\n<script>alert(1)</script>'}],'saved':[]}
    def test_defaults_owner_scope_and_restart(self):
        self.assertEqual(self.get(),{'revision':0,'layout':{'items':{},'slots':[],'saved':[]}})
        saved=self.save(self.layout());self.assertEqual(saved['revision'],1)
        self.assertEqual(self.get()['layout'],self.layout())
        self.assertEqual(self.get(token=self.admin_token)['revision'],0)
        init();self.assertEqual(self.get()['layout'],self.layout())
    def test_idempotent_save_does_not_increment_twice(self):
        key='dashboard-idempotency'
        a=self.save(self.layout(),key=key);b=self.save(self.layout(),key=key)
        self.assertEqual(a,b);self.assertEqual(self.get()['revision'],1)
    def test_stale_tab_cannot_overwrite(self):
        self.save(self.layout());old=self.layout();old['items']['wallet']['title']='stale tab'
        self.error(409,'POST','/api/dashboard/layout',{'revision':0,'layout':old})
        self.assertEqual(self.get()['layout'],self.layout())
    def test_appearance_deletion_never_changes_money_or_account(self):
        self.call('POST','/api/broker/accounts',{})
        with transaction() as db:
            before=[db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('accounts','entries','balances','users')]
        value=self.layout();value['items']['wallet']['hidden']=True;self.save(value)
        with transaction() as db:
            after=[db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('accounts','entries','balances','users')]
        self.assertEqual(before,after)
    def test_auth_and_wrong_domain_role(self):
        self.error(401,'GET','/api/dashboard/layout',token='wrong')
        self.error(404,'GET','/api/dashboard/layout',role='broker')
        value=self.layout();value['user_id']=self.admin['id']
        self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
    def test_css_and_html_payloads_cannot_enter_style(self):
        for patch in ({'color':'url(https://evil)'},{'foreground':'red; position:fixed'},{'background':'#abc; color:red'},{'font_size':1000},{'hidden':1},{'onclick':'fetch(...)'},{'order':True},{'title':'a'*101}):
            value=self.layout();value['items']['wallet'].update(patch)
            self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
        self.assertEqual(self.get()['revision'],0)
    def test_note_bounds_duplicate_and_unknown_type(self):
        for change in ('long','duplicate','kind','binding'):
            value=self.layout()
            if change=='long':value['slots'][0]['text']='x'*2001
            if change=='duplicate':value['slots'].append(value['slots'][0].copy())
            if change=='kind':value['slots'][0]['kind']='script'
            if change=='binding':value['slots'][0]['source']='wallet'
            self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
    def test_admin_bindings_are_role_scoped(self):
        value={'items':{},'slots':[{'id':'slot-123456abcdef','kind':'mirror','source':'admin-funding'}]}
        self.error(403,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
        self.assertEqual(self.save(value,token=self.admin_token)['layout']['slots'][0]['source'],'admin-funding')
    def test_source_cycles_and_injection_are_rejected(self):
        for source in ('slot-abcdef123456','javascript:alert(1)','wallet; DROP TABLE users'):
            value={'items':{},'slots':[{'id':'slot-123456abcdef','kind':'mirror','source':source}]}
            self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
    def test_saved_layouts_validated_and_normalized(self):
        value=self.layout();value['saved']=[{'name':'  first  ','layout':{}}]
        saved=self.save(value)['layout'];self.assertEqual(saved['saved'][0],{'name':'first','layout':{'items':{},'slots':[]}})
        value['saved'].append({'name':'first','layout':{}})
        self.error(400,'POST','/api/dashboard/layout',{'revision':1,'layout':value})
    def test_custom_slot_and_template_limits(self):
        value={'items':{},'slots':[{'id':f'slot-{i:012x}','kind':'note','text':''} for i in range(25)]}
        self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
        value={'items':{},'slots':[],'saved':[{'name':str(i),'layout':{}} for i in range(6)]}
        self.error(400,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
    def test_dashboard_payload_quota(self):
        slots=[{'id':f'slot-{i:012x}','kind':'note','text':'آ'*2000} for i in range(24)]
        value={'items':{},'slots':slots,'saved':[{'name':'large','layout':{'items':{},'slots':slots}}]}
        self.error(413,'POST','/api/dashboard/layout',{'revision':0,'layout':value})
    def test_http_layout_limit_is_scoped_and_new_assets_are_served(self):
        import threading,urllib.request,urllib.error
        from ako_fx.server import Server
        server=Server(('127.0.0.1',0),'all');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base_url='http://127.0.0.1:'+str(server.server_port)
        try:
            for path in ('/workspace.js','/workspace.css'):
                with urllib.request.urlopen(base_url+path) as response:self.assertEqual(response.status,200)
            value={'items':{},'slots':[{'id':f'slot-{i:012x}','kind':'note','text':'آ'*2000} for i in range(6)]}
            body=json.dumps({'revision':0,'layout':value},ensure_ascii=False).encode()
            self.assertGreater(len(body),16384)
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token,'Idempotency-Key':'large-layout-http-key'}
            request=urllib.request.Request(base_url+'/api/dashboard/layout',data=body,headers=headers)
            with urllib.request.urlopen(request) as response:self.assertEqual(json.load(response)['revision'],1)
            request=urllib.request.Request(base_url+'/api/wallet/requests',data=body,headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as e:urllib.request.urlopen(request)
            self.assertEqual(e.exception.code,413)
        finally:server.shutdown();server.server_close();thread.join()
    def test_revision_must_be_integer_not_bool(self):
        self.error(400,'POST','/api/dashboard/layout',{'revision':False,'layout':{}})

if __name__=='__main__':unittest.main()
