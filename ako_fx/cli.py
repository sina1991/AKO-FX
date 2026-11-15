"""All public API operations are accessible without direct database access."""
import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

def main():
    p=argparse.ArgumentParser(description='AKO-FX DEMO_ONLY API client')
    p.add_argument('--url',default=os.environ.get('AKO_URL','http://127.0.0.1:8080'))
    p.add_argument('--token',default=os.environ.get('AKO_TOKEN',''))
    p.add_argument('--key',default=None,help='Reuse the same key to retry a mutation safely')
    p.add_argument('method',choices=['GET','POST','login'])
    p.add_argument('path',help='API path, or email for login')
    p.add_argument('--data',default='{}',help='JSON object; do not put passwords in shell history')
    a=p.parse_args()
    parsed=urlsplit(a.url)
    if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
        p.error('Remote connections require HTTPS')
    if a.method=='login':
        payload={'email':a.path,'password':getpass.getpass('Password: ')}
        method='POST'; path='/api/auth/login'
    else:
        payload=json.loads(a.data); method=a.method; path=a.path
    if not path.startswith('/api/') and path!='/health': p.error('Use an /api/ path or /health')
    key=a.key or uuid.uuid4().hex
    if method=='POST' and not path.startswith('/api/auth/'):
        print('Idempotency-Key: '+key,file=sys.stderr)
    req=urllib.request.Request(a.url.rstrip('/')+path,data=json.dumps(payload,ensure_ascii=False).encode() if method=='POST' else None,headers={'Content-Type':'application/json','Authorization':'Bearer '+a.token,'Idempotency-Key':key},method=method)
    try:
        with urllib.request.urlopen(req,timeout=20) as response: print(json.dumps(json.load(response),indent=2,ensure_ascii=False))
    except urllib.error.HTTPError as e:
        print(e.read().decode(),file=sys.stderr); sys.exit(1)
    except urllib.error.URLError as e:
        print('Connection failed: '+str(e.reason),file=sys.stderr); sys.exit(1)

if __name__=='__main__': main()
