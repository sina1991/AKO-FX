"""CI fixture journey against the installed containers through real verified HTTPS."""
import http.client
import json
from pathlib import Path
import socket
import ssl
import sys
import uuid

HOST='x.30na.test'

class LoopbackHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw=socket.create_connection(('127.0.0.1',self.port),timeout=self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)

def request(path,body=None,token='',port=8443):
    connection=LoopbackHTTPS(HOST,port,timeout=15,context=ssl.create_default_context())
    try:
        connection.request('POST' if body is not None else 'GET',path,
            body=json.dumps(body) if body is not None else None,
            headers={'Content-Type':'application/json','Host':f'{HOST}:{port}',
                     'Origin':f'https://{HOST}:{port}','Authorization':'Bearer '+token,
                     'Idempotency-Key':uuid.uuid4().hex})
        response=connection.getresponse();raw=response.read()
        assert response.status==200,(path,response.status,raw)
        return raw if port==443 else json.loads(raw)
    finally: connection.close()

def main():
    assert request('/',port=443)==b'existing-30na-fixture'
    assert request('/health')['mode']=='DEMO_ONLY'
    token=request('/api/auth/login',{'email':'ci@example.com','password':'CI-only-password-12345'})['token']
    if sys.argv[1]=='seed':
        credit=request('/api/wallet/requests',{'amount':'2000'},token)
        request('/api/admin/funding/'+credit['id'],{'status':'approved'},token)
        account=request('/api/broker/accounts',{},token)['id']
        request('/api/broker/accounts/'+account+'/transfers',{'amount':'500','direction':'deposit'},token)
        position=request('/api/broker/accounts/'+account+'/positions',{'symbol':'EURUSD','side':'buy','quantity':100},token)['id']
        request('/api/admin/scenario',{'scenario':'up'},token)
        assert request('/api/broker/positions/'+position+'/close',{},token)['pnl_cents']==550
        request('/api/prop/purchases',{'plan_id':'b-10000'},token)
    assert request('/api/wallet',token=token)['balance_cents']==140200
    assert len(request('/api/accounts',token=token)['accounts'])==2
    state=json.loads(Path('/etc/ako-fx/install.json').read_text())
    assert state['stage']=='complete'
    assert state['port']==8443 and state['backend_port']==9080
    print('Installed HTTPS journey passed: '+sys.argv[1])

if __name__=='__main__':main()
