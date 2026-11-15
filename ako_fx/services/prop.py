import uuid
from ako_fx.store import transfer, audit, Error, balance

PLANS=[{'id':'starter','name':'Demo Starter','fee_cents':10000,'capital_cents':1000000,'profit_target_bps':1000,'max_loss_bps':1000},
       {'id':'advanced','name':'Demo Advanced','fee_cents':25000,'capital_cents':2500000,'profit_target_bps':1000,'max_loss_bps':1000}]

def purchase(db,user,data):
    plan=next((p for p in PLANS if p['id']==data.get('plan_id')),None)
    if not plan:
        raise Error('Unknown plan',404)
    aid=uuid.uuid4().hex
    transfer(db,'wallet:'+user['id'],'demo:prop-fees',plan['fee_cents'],'prop.purchase')
    db.execute('INSERT INTO accounts(id,user_id,kind,initial_balance) VALUES(?,?,?,?)',(aid,user['id'],'prop',plan['capital_cents']))
    transfer(db,'demo:issuer','account:'+aid,plan['capital_cents'],'prop.capital')
    audit(db,user['id'],'prop.purchase:'+plan['id'],aid)
    return {'id':aid,'kind':'prop','status':'active','plan':plan}

def evaluate(db,user,aid,data):
    from .broker import owned
    account=owned(db,user,aid)
    if account['kind']!='prop':
        raise Error('Prop account required')
    from .broker import equity, assess
    status=assess(db,account)
    audit(db,user['id'],'prop.evaluate',aid)
    return {'id':aid,'status':status,'equity_cents':equity(db,aid),'initial_balance_cents':account['initial_balance']}
