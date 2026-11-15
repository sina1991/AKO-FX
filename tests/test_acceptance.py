import concurrent.futures
import contextlib
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from unittest.mock import patch
from ako_fx.application import dispatch
from ako_fx.server import Server
from ako_fx.services.identity import register
from ako_fx.store import Error, connect, init, money, transaction

class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'AKO_DB':self.tmp.name+'/demo.db'})
        self.env.start(); init()
        with transaction() as db:
            self.admin=register(db,{'email':'admin@example.com','password':'Admin-password-123'},'admin')
        self.admin_token=self.call('POST','/api/auth/login',{'email':'admin@example.com','password':'Admin-password-123'})['token']
        self.user=self.call('POST','/api/auth/register',{'email':'user@example.com','password':'User-password-123','role':'admin'})
        self.token=self.call('POST','/api/auth/login',{'email':'user@example.com','password':'User-password-123'})['token']
    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()
    def call(self,method,path,data=None,token=None,key=None,role='all'):
        return dispatch(method,path,data or {},self.token if token is None and hasattr(self,'token') else token or '',key or uuid.uuid4().hex,role)
    def error(self,status,*args,**kwargs):
        with self.assertRaises(Error) as caught: self.call(*args,**kwargs)
        self.assertEqual(caught.exception.status,status)
    def funded(self,value='1000'):
        request=self.call('POST','/api/wallet/requests',{'amount':value})
        self.call('POST','/api/admin/funding/'+request['id'],{'status':'approved'},token=self.admin_token)
        return request
    def broker(self,value='1000'):
        self.funded(value)
        aid=self.call('POST','/api/broker/accounts')['id']
        self.call('POST','/api/broker/accounts/'+aid+'/transfers',{'amount':value,'direction':'deposit'})
        return aid
    def legacy_prop(self):
        from ako_fx.services.prop import legacy_purchase
        with transaction() as db: return legacy_purchase(db,self.user,'starter')
    def test_authorization_and_identity(self):
        self.assertEqual(self.user['role'],'user')
        self.error(401,'GET','/api/wallet',token='bad')
        self.error(403,'GET','/api/admin/funding')
        self.error(403,'POST','/api/admin/scenario',{'scenario':'up'})
        self.error(404,'GET','/api/wallet',role='broker')
        self.assertEqual(self.call('POST','/api/auth/login',{'email':'user@example.com','password':'incorrect'})['status'],401)
        self.call('POST','/api/auth/logout')
        self.error(401,'GET','/api/me')
    def test_funding_idempotency_and_rejection(self):
        key=uuid.uuid4().hex
        a=self.call('POST','/api/wallet/requests',{'amount':'500'},key=key)
        self.assertEqual(a,self.call('POST','/api/wallet/requests',{'amount':'500'},key=key))
        self.error(409,'POST','/api/wallet/requests',{'amount':'501'},key=key)
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],0)
        path='/api/admin/funding/'+a['id']
        self.call('POST',path,{'status':'rejected'},token=self.admin_token)
        self.error(409,'POST',path,{'status':'approved'},token=self.admin_token)
        self.funded('750.25')
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],75025)
    def test_money_validation(self):
        for v in [True,None,{},[],0,-1,'NaN','Infinity','0.001','10000000.01']:
            with self.subTest(v=v),self.assertRaises(Error): money(v)
        self.assertEqual(money('1.23'),123)
    def test_transfer_atomicity_and_owner_isolation(self):
        aid=self.broker('100')
        self.error(409,'POST','/api/broker/accounts/'+aid+'/transfers',{'amount':'101','direction':'withdraw'})
        self.assertEqual(self.call('GET','/api/accounts')['accounts'][0]['balance_cents'],10000)
        self.error(404,'POST','/api/broker/accounts/'+aid+'/transfers',{'amount':'1','direction':'withdraw'},token=self.admin_token)
        self.call('POST','/api/broker/accounts/'+aid+'/transfers',{'amount':'40','direction':'withdraw'})
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],4000)
    def test_profit_loss_and_reserves(self):
        aid=self.broker()
        opened=self.call('POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':100})
        self.error(409,'POST','/api/broker/accounts/'+aid+'/transfers',{'amount':'1','direction':'withdraw'})
        self.call('POST','/api/admin/scenario',{'scenario':'up'},token=self.admin_token)
        a=self.call('GET','/api/accounts')['accounts'][0]
        self.assertEqual(a['equity_cents'],100550)
        closed=self.call('POST','/api/broker/positions/'+opened['id']+'/close')
        self.assertEqual(closed['pnl_cents'],550)
        self.error(409,'POST','/api/broker/positions/'+opened['id']+'/close')
        short=self.call('POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'sell','quantity':100})
        self.call('POST','/api/admin/scenario',{'scenario':'up'},token=self.admin_token)
        self.assertEqual(self.call('POST','/api/broker/positions/'+short['id']+'/close')['pnl_cents'],-550)
        a=self.call('GET','/api/accounts')['accounts'][0]
        self.assertEqual((a['balance_cents'],a['reserved_cents']),(100000,0))
    def test_prop_fee_capital_and_terminal_failure(self):
        self.funded('1000')
        bought=self.legacy_prop()
        aid=bought['id']
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],90000)
        self.error(409,'POST','/api/broker/accounts/'+aid+'/transfers',{'amount':'1','direction':'withdraw'})
        self.call('POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':6000})
        for _ in range(4): self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        account=self.call('GET','/api/accounts')['accounts'][0]
        self.assertEqual(account['status'],'failed')
        self.assertEqual(account['reserved_cents'],0)
        self.assertTrue(all(p['status']=='closed' for p in account['positions']))
        self.call('POST','/api/admin/scenario',{'scenario':'reset'},token=self.admin_token)
        self.assertEqual(self.call('POST','/api/prop/accounts/'+aid+'/evaluate')['status'],'failed')
        self.error(409,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1})
    def test_prop_pass_requires_realized_target(self):
        self.funded('1000'); aid=self.legacy_prop()['id']
        pid=self.call('POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':6000})['id']
        for _ in range(4): self.call('POST','/api/admin/scenario',{'scenario':'up'},token=self.admin_token)
        self.assertEqual(self.call('GET','/api/accounts')['accounts'][0]['status'],'active')
        self.call('POST','/api/broker/positions/'+pid+'/close')
        self.assertEqual(self.call('GET','/api/accounts')['accounts'][0]['status'],'passed')
    def test_concurrent_approval_and_conservation(self):
        req=self.call('POST','/api/wallet/requests',{'amount':'100'})
        def approve(_):
            try: return self.call('POST','/api/admin/funding/'+req['id'],{'status':'approved'},token=self.admin_token)
            except Error as e: return e.status
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(approve,range(6)))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],10000)
        with transaction() as db:
            self.assertEqual(db.execute('SELECT SUM(delta) FROM entries').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT SUM(amount) FROM balances').fetchone()[0],0)
            self.assertFalse(db.execute('SELECT tx_id FROM entries GROUP BY tx_id HAVING SUM(delta)<>0').fetchall())
            with self.assertRaises(sqlite3.IntegrityError): db.execute('DELETE FROM entries')
    def test_restart_and_session_expiry(self):
        self.funded(); init()
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],100000)
        with transaction() as db: db.execute('UPDATE sessions SET expires=0')
        self.error(401,'GET','/api/me')
    def test_login_throttle_persists(self):
        for _ in range(10): self.call('POST','/api/auth/login',{'email':'user@example.com','password':'wrong'})
        self.assertEqual(self.call('POST','/api/auth/login',{'email':'user@example.com','password':'User-password-123'})['status'],429)
    def test_http_security_and_static(self):
        server=Server(('127.0.0.1',0),'all')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(url+'/') as r:
                self.assertIn(b'AKO',r.read()); self.assertIn("default-src 'self'",r.headers['Content-Security-Policy'])
            req=urllib.request.Request(url+'/api/wallet/requests',data=b'{"amount":"100"}',headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token,'Origin':'https://evil.example','Idempotency-Key':uuid.uuid4().hex})
            with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
            self.assertEqual(err.exception.code,403)
            req=urllib.request.Request(url+'/api/wallet/requests',data=b'[]',headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as err: urllib.request.urlopen(req)
            self.assertEqual(err.exception.code,400)
        finally: server.shutdown();server.server_close();thread.join()


class MultiService(unittest.TestCase):
    def test_gateway_routes_independent_process_surfaces(self):
        import ako_fx.server as module
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'AKO_DB':tmp+'/services.db'}):
            init(); servers=[];threads=[];ports={}
            try:
                for role in ('identity','wallet','broker','prop','gateway'):
                    server=Server(('127.0.0.1',0),role); servers.append(server)
                    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start();threads.append(thread)
                    ports[role]=server.server_port
                with patch.dict(module.PORTS,{k:v for k,v in ports.items() if k!='gateway'}):
                    base='http://127.0.0.1:'+str(ports['gateway'])
                    def req(path,data=None,token=''):
                        request=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'Idempotency-Key':uuid.uuid4().hex})
                        with urllib.request.urlopen(request) as response: return json.load(response)
                    req('/api/auth/register',{'email':'gateway@example.com','password':'Gateway-password-123'})
                    token=req('/api/auth/login',{'email':'gateway@example.com','password':'Gateway-password-123'})['token']
                    self.assertEqual(req('/api/wallet',token=token)['balance_cents'],0)
                    self.assertIn('id',req('/api/broker/accounts',{},token))
                    self.assertEqual(len(req('/api/prop/plans',token=token)['plans']),14)
                    self.assertEqual(req('/api/accounts',token=token)['accounts'][0]['kind'],'broker')
            finally:
                for server in servers: server.shutdown();server.server_close()
                for thread in threads: thread.join()

if __name__=='__main__': unittest.main()
