import uuid
from ako_fx.store import Error, money, transfer, audit, balance

def request_credit(db,user,data):
    amount=money(data.get('amount'))
    uid=uuid.uuid4().hex
    db.execute('INSERT INTO funding(id,user_id,amount) VALUES(?,?,?)',(uid,user['id'],amount))
    audit(db,user['id'],'funding.request',uid)
    return {'id':uid,'amount_cents':amount,'status':'pending'}

def decide(db,user,request_id,data):
    if user['role']!='admin':
        raise Error('Admin access required',403)
    status=data.get('status')
    if status not in ('approved','rejected'):
        raise Error('Status must be approved or rejected')
    row=db.execute('SELECT * FROM funding WHERE id=?',(request_id,)).fetchone()
    if not row:
        raise Error('Funding request not found',404)
    if row['status']!='pending':
        raise Error('Funding request already decided',409)
    if status=='approved':
        transfer(db,'demo:issuer','wallet:'+row['user_id'],row['amount'],'demo-credit')
    db.execute('UPDATE funding SET status=? WHERE id=?',(status,request_id))
    audit(db,user['id'],'funding.'+status,request_id)
    return {'id':request_id,'status':status}

def snapshot(db,user):
    uid=user['id']
    return {'currency':'DEMO-USD','balance_cents':balance(db,'wallet:'+uid),
        'requests':[dict(r) for r in db.execute('SELECT * FROM funding WHERE user_id=? ORDER BY rowid DESC',(uid,))],
        'ledger':[dict(r) for r in db.execute('SELECT e.tx_id,e.delta,t.kind,t.created FROM entries e JOIN transactions t ON t.id=e.tx_id WHERE e.account=? ORDER BY e.id DESC LIMIT 200',('wallet:'+uid,))]}
