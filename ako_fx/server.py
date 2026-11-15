import argparse
import json
import logging
import os
import socket
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from ako_fx.application import dispatch, route
from ako_fx.store import Error, init, transaction

LOG=logging.getLogger('ako')
WEB=Path(__file__).resolve().parent/'web'
PORTS={'identity':8101,'wallet':8102,'broker':8103,'prop':8104}

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.0'
    def log_message(self, fmt, *args):
        LOG.info('%s %s',self.command,self.path.split('?')[0])
    def reply(self,status,result,ctype='application/json; charset=utf-8'):
        body=result if isinstance(result,bytes) else json.dumps(result,ensure_ascii=False).encode()
        self.send_response(status)
        for k,v in {'Content-Type':ctype,'Content-Length':str(len(body)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items(): self.send_header(k,v)
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def handle_request(self):
        self.connection.settimeout(10)
        path=self.path.split('?')[0]
        try:
            if self.headers.get('Transfer-Encoding'):
                raise Error('Transfer-Encoding is unsupported')
            if self.command=='POST':
                origin=self.headers.get('Origin')
                if origin:
                    from urllib.parse import urlsplit
                    if urlsplit(origin).netloc!=self.headers.get('Host'):
                        raise Error('Cross-origin request rejected',403)
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    raise Error('Content-Type must be application/json',415)
            if self.command=='GET' and self.server.role in ('all','gateway') and path in ('/','/app.js','/style.css','/workspace.js','/workspace.css'):
                filename={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/workspace.js':'workspace.js','/workspace.css':'workspace.css'}[path]
                ctype={'index.html':'text/html; charset=utf-8','app.js':'application/javascript; charset=utf-8','style.css':'text/css; charset=utf-8','workspace.js':'application/javascript; charset=utf-8','workspace.css':'text/css; charset=utf-8'}[filename]
                return self.reply(200,(WEB/filename).read_bytes(),ctype)
            raw_length=self.headers.get('Content-Length','0')
            if not raw_length.isdecimal(): raise Error('Invalid Content-Length')
            length=int(raw_length)
            if length>(131072 if path=='/api/dashboard/layout' else 16384): raise Error('Request too large',413)
            raw=self.rfile.read(length) if length else b'{}'
            if len(raw)!=length and length: raise Error('Incomplete request')
            data=json.loads(raw)
            if not isinstance(data,dict): raise Error('JSON object required')
            token=self.headers.get('Authorization','')
            token=token[7:] if token.startswith('Bearer ') else ''
            if self.server.role=='gateway' and path!='/health':
                service=route(self.command,path)
                host=os.environ.get('AKO_'+service.upper()+'_HOST','127.0.0.1')
                url='http://'+host+':'+str(PORTS[service])+path
                headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'Idempotency-Key':self.headers.get('Idempotency-Key','')}
                req=urllib.request.Request(url,data=raw if self.command=='POST' else None,headers=headers,method=self.command)
                try:
                    with urllib.request.urlopen(req,timeout=15) as response:
                        return self.reply(response.status,response.read())
                except urllib.error.HTTPError as e:
                    return self.reply(e.code,e.read())
                except (urllib.error.URLError,TimeoutError):
                    raise Error('Domain service unavailable',503)
            result=dispatch(self.command,path,data,token,self.headers.get('Idempotency-Key',''),self.server.role)
            status=result.pop('status') if 'error' in result and isinstance(result.get('status'),int) else 200
            self.reply(status,result)
        except Error as e: self.reply(e.status,{'error':str(e)})
        except (json.JSONDecodeError,UnicodeDecodeError,ValueError): self.reply(400,{'error':'Invalid JSON or request'})
        except (TimeoutError,socket.timeout): self.reply(408,{'error':'Request timeout'})
        except Exception:
            LOG.exception('Request failed')
            self.reply(500,{'error':'Internal server error'})

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,role):
        self.role=role
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(address,Handler)
    def get_request(self):
        connection,address=super().get_request()
        connection.settimeout(10)
        return connection,address
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try: super().process_request(request,address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self,request,address):
        try: super().process_request_thread(request,address)
        finally: self.slots.release()

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',type=int)
    parser.add_argument('--service',choices=['all','gateway',*PORTS],default='all')
    args=parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    init()
    server=Server((args.host,args.port or PORTS.get(args.service,8080)),args.service)
    stop=threading.Event()
    def rule_clock():
        from ako_fx.services.prop import sweep
        while not stop.wait(15):
            try:
                with transaction() as db: sweep(db)
            except Exception: LOG.exception('Prop deadline monitor failed')
    monitor=None
    if args.service in ('wallet','all'):
        monitor=threading.Thread(target=rule_clock,name='prop-deadlines',daemon=True)
        monitor.start()
    LOG.info('AKO-FX DEMO_ONLY service=%s address=%s',args.service,server.server_address)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        stop.set()
        if monitor: monitor.join(timeout=5)
        server.server_close()

if __name__=='__main__': main()
