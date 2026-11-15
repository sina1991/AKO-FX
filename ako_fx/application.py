from ako_fx import __version__
import hashlib
import re
from ako_fx.store import Error, transaction, once
from ako_fx.services import identity, wallet, broker, prop

ROLES={'identity','wallet','broker','prop','all'}

def route(method,path):
    if path.startswith('/api/auth/') or path=='/api/me': return 'identity'
    if path.startswith('/api/wallet') or path.startswith('/api/admin/'): return 'wallet'
    if path.startswith('/api/prop'): return 'prop'
    if path.startswith('/api/broker') or path=='/api/accounts': return 'broker'
    raise Error('Route not found',404)

def dispatch(method,path,data,token='',key='',role='all'):
    if method=='GET' and path=='/health':
        return {'status':'ok','mode':'DEMO_ONLY','version':__version__,'role':role}
    service=route(method,path)
    if role!='all' and role!=service:
        raise Error('Route not served by this service',404)
    if path not in ('/api/auth/register','/api/auth/login'):
        # Persist rule breaches even if a following rejected operation rolls back.
        with transaction() as preflight:
            caller=identity.authenticate(preflight,token)
            prop.sweep(preflight,None if caller['role']=='admin' and path.startswith('/api/admin/prop') else caller['id'])
    with transaction() as db:
        if method=='POST' and path=='/api/auth/register': return identity.register(db,data)
        if method=='POST' and path=='/api/auth/login': return identity.login(db,data)
        user=identity.authenticate(db,token)
        if method=='POST' and path=='/api/auth/logout':
            db.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
            return {'logged_out':True}
        if method=='GET':
            if path=='/api/me': return user
            if path=='/api/wallet': return wallet.snapshot(db,user)
            if path=='/api/accounts': return {'accounts':broker.accounts(db,user)}
            if path=='/api/prop/plans': return {'plans':prop.PLANS,'rules_version':prop.VERSION}
            if path=='/api/prop/rules': return {'version':prop.VERSION,'sources':prop.SOURCES,'conflicts':prop.CONFLICTS,'manual_checks':prop.MANUAL_CHECKS}
            if path=='/api/admin/prop/accounts': return prop.admin_accounts(db,user)
            if path=='/api/admin/prop/requests': return prop.admin_requests(db,user)
            if path=='/api/broker/quotes': return {'mode':'SYNTHETIC_SCENARIO_DEMO','price_scale':10000,'prices':broker.quotes(db),'leverage':broker.LEVERAGE}
            if path=='/api/admin/funding':
                if user['role']!='admin': raise Error('Admin access required',403)
                return {'requests':[dict(r) for r in db.execute('SELECT f.*,u.email FROM funding f JOIN users u ON u.id=f.user_id ORDER BY f.rowid DESC LIMIT 500')]}
            if path=='/api/admin/audit':
                if user['role']!='admin': raise Error('Admin access required',403)
                return {'events':[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 500')]}
        if method=='POST':
            def execute():
                if path=='/api/admin/prop/settings': return prop.settings(db,user,data)
                match=re.fullmatch(r'/api/admin/prop/requests/([a-f0-9]{32})',path)
                if match: return prop.decide(db,user,match[1],data)
                match=re.fullmatch(r'/api/admin/prop/accounts/([a-f0-9]{32})/flag',path)
                if match: return prop.flag(db,user,match[1],data)
                match=re.fullmatch(r'/api/prop/accounts/([a-f0-9]{32})/requests',path)
                if match: return prop.request(db,user,match[1],data)
                match=re.fullmatch(r'/api/broker/positions/([a-f0-9]{32})/protection',path)
                if match: return broker.protection(db,user,match[1],data)
                if path=='/api/admin/scenario': return broker.scenario(db,user,data)
                if path=='/api/wallet/requests': return wallet.request_credit(db,user,data)
                if path=='/api/broker/accounts': return broker.create(db,user,data)
                if path=='/api/prop/purchases': return prop.purchase(db,user,data)
                match=re.fullmatch(r'/api/admin/funding/([a-f0-9]{32})',path)
                if match: return wallet.decide(db,user,match[1],data)
                match=re.fullmatch(r'/api/broker/accounts/([a-f0-9]{32})/(transfers|positions)',path)
                if match:
                    fn=broker.move if match[2]=='transfers' else broker.open_position
                    return fn(db,user,match[1],data)
                match=re.fullmatch(r'/api/broker/positions/([a-f0-9]{32})/close',path)
                if match: return broker.close_position(db,user,match[1],data)
                match=re.fullmatch(r'/api/prop/accounts/([a-f0-9]{32})/evaluate',path)
                if match: return prop.evaluate(db,user,match[1],data)
                raise Error('Route not found',404)
            return once(db,user['id'],key,method+' '+path,data,execute)
        raise Error('Route not found',404)
