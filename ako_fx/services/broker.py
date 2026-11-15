import uuid
from ako_fx.store import Error, money, transfer, balance, audit

# Synthetic demo quote units, NOT executable FX or converted JPY market prices.
MARKS={'EURUSD':11000,'GBPUSD':12500,'USDJPY':1500000,'XAUUSD':20000000,'XAGUSD':250000,'BTCUSD':600000000,'USOIL':700000,'UKOIL':750000,'US30':400000000,'NAS100':200000000}
LEVERAGE={s:(10 if s=='BTCUSD' else 20 if s in ('USOIL','UKOIL') else 50 if s=='US30' else 100) for s in MARKS}

def quotes(db):
    return {r['symbol']:r['price'] for r in db.execute('SELECT * FROM quotes')}

def reserved_for(symbol,quantity):
    # Maximum synthetic notional within scenario bounds; covers both long and short losses.
    return (MARKS[symbol]*3*quantity+199)//200

def pnl(position,prices):
    difference=prices[position['symbol']]-position['entry_price']
    if position['side']=='sell': difference=-difference
    return difference*position['quantity']//100

def equity(db,aid):
    prices=quotes(db)
    floating=sum(pnl(p,prices) for p in db.execute("SELECT * FROM positions WHERE account_id=? AND status='open'",(aid,)))
    return balance(db,'account:'+aid)+balance(db,'reserve:'+aid)+floating

def owned(db,user,aid):
    row=db.execute('SELECT * FROM accounts WHERE id=? AND user_id=?',(aid,user['id'])).fetchone()
    if not row: raise Error('Account not found',404)
    return dict(row)

def create(db,user,data):
    aid=uuid.uuid4().hex
    db.execute('INSERT INTO accounts(id,user_id,kind) VALUES(?,?,?)',(aid,user['id'],'broker'))
    audit(db,user['id'],'broker.create',aid)
    return {'id':aid,'kind':'broker','status':'active'}

def move(db,user,aid,data):
    account=owned(db,user,aid)
    if account['kind']!='broker' or account['status']!='active': raise Error('Transfers require an active broker account',409)
    if db.execute("SELECT 1 FROM positions WHERE account_id=? AND status='open'",(aid,)).fetchone():
        raise Error('Close positions before transferring',409)
    amount=money(data.get('amount'))
    direction=data.get('direction')
    wallet='wallet:'+user['id']; target='account:'+aid
    if direction=='deposit': source,dest=wallet,target
    elif direction=='withdraw': source,dest=target,wallet
    else: raise Error('Direction must be deposit or withdraw')
    tx=transfer(db,source,dest,amount,'broker.'+direction)
    audit(db,user['id'],'broker.'+direction,aid)
    return {'transaction_id':tx,'balance_cents':balance(db,target)}

def open_position(db,user,aid,data):
    from . import prop
    c=prop.before_trade(db,user,aid)
    account=owned(db,user,aid)
    if account['status']!='active': raise Error('Account is not active',409)
    symbol=data.get('symbol'); side=data.get('side'); quantity=data.get('quantity')
    if not isinstance(symbol,str) or symbol not in MARKS or side not in ('buy','sell') or type(quantity)!=int or not 1<=quantity<=(1000000000 if c else 100000):
        raise Error('Choose a listed symbol, buy/sell, and a positive integer quantity within the account limit')
    price=quotes(db)[symbol]
    denominator=100*LEVERAGE[symbol]
    reserved=(price*quantity+denominator-1)//denominator if c else reserved_for(symbol,quantity)
    stop=prop.price(data.get('stop_loss'));take=prop.price(data.get('take_profit'))
    prop.check_stops(price,side,stop,take)
    transfer(db,'account:'+aid,'reserve:'+aid,reserved,'demo.open')
    pid=uuid.uuid4().hex
    db.execute('INSERT INTO positions(id,account_id,symbol,side,quantity,entry_price) VALUES(?,?,?,?,?,?)',(pid,aid,symbol,side,quantity,price))
    prop.opened(db,aid,pid,reserved,stop,take)
    audit(db,user['id'],'position.open',pid)
    return {'id':pid,'entry_price_units':price,'price_scale':10000,'reserved_cents':reserved,'status':'open'}

def settle(db,position,prices):
    from . import prop
    aid=position['account_id']; profit=pnl(position,prices)
    meta=db.execute('SELECT reserved_cents FROM trade_meta WHERE position_id=?',(position['id'],)).fetchone()
    reserved=meta['reserved_cents'] if meta else reserved_for(position['symbol'],position['quantity'])
    transfer(db,'reserve:'+aid,'account:'+aid,reserved,'demo.close')
    if profit>0: transfer(db,'demo:issuer','account:'+aid,profit,'demo.profit')
    elif profit<0:
        deficit=-profit-balance(db,'account:'+aid)
        if deficit>0:
            # Demo gap protection: no debt is ever assigned to a user wallet.
            transfer(db,'demo:issuer','account:'+aid,deficit,'demo.gap-protection')
        transfer(db,'account:'+aid,'demo:losses',-profit,'demo.loss')
    db.execute("UPDATE positions SET status='closed',exit_price=?,pnl=? WHERE id=?",(prices[position['symbol']],profit,position['id']))
    prop.closed(db,position,profit)
    return profit

def close_position(db,user,pid,data):
    position=db.execute('SELECT * FROM positions WHERE id=?',(pid,)).fetchone()
    if not position: raise Error('Position not found',404)
    account=owned(db,user,position['account_id'])
    from . import prop
    if prop.contract(db,account['id']) and not prop.market_open(prop.now()): raise Error('Prop market is closed',409)
    if position['status']!='open': raise Error('Position already closed',409)
    profit=settle(db,position,quotes(db))
    if account['kind']=='prop': assess(db,account)
    audit(db,user['id'],'position.close',pid)
    return {'id':pid,'status':'closed','pnl_cents':profit}

def assess(db,account):
    from . import prop
    if account['kind']=='prop' and prop.contract(db,account['id']): return prop.assess(db,account)
    if account['kind']!='prop' or account['status']!='active': return account['status']
    value=equity(db,account['id']); initial=account['initial_balance']
    has_open=db.execute("SELECT 1 FROM positions WHERE account_id=? AND status='open'",(account['id'],)).fetchone()
    status='failed' if value*100<=initial*90 else 'passed' if value*100>=initial*110 and not has_open else 'active'
    if status!='active':
        for position in db.execute("SELECT * FROM positions WHERE account_id=? AND status='open'",(account['id'],)).fetchall():
            settle(db,position,quotes(db))
        db.execute('UPDATE accounts SET status=? WHERE id=?',(status,account['id']))
        audit(db,'system','prop.'+status,account['id'])
    return status

def scenario(db,user,data):
    if user['role']!='admin': raise Error('Admin access required',403)
    name=data.get('scenario')
    if name not in ('up','down','reset'): raise Error('Scenario must be up, down or reset')
    from . import prop
    prop.sweep(db)
    for symbol,price in quotes(db).items():
        base=MARKS[symbol]
        target=base if name=='reset' else price+(base//20 if name=='up' else -(base//20))
        target=max(base//2,min(base*3//2,target))
        db.execute('UPDATE quotes SET price=? WHERE symbol=?',(target,symbol))
    prop.on_quotes(db)
    for account in db.execute("SELECT * FROM accounts WHERE kind='prop' AND status='active'").fetchall(): assess(db,dict(account))
    audit(db,user['id'],'scenario.'+name,'global-demo-market')
    return {'prices':quotes(db),'scenario':name,'price_scale':10000}

def accounts(db,user):
    result=[]
    prices=quotes(db)
    for row in db.execute('SELECT * FROM accounts WHERE user_id=? ORDER BY rowid DESC',(user['id'],)):
        a=dict(row)
        a['balance_cents']=balance(db,'account:'+a['id'])
        a['reserved_cents']=balance(db,'reserve:'+a['id'])
        a['equity_cents']=equity(db,a['id'])
        if a['kind']=='prop':
            from . import prop
            a['prop']=prop.view(db,a)
        a['positions']=[]
        for p in db.execute('SELECT * FROM positions WHERE account_id=?',(a['id'],)):
            item=dict(p); item['unrealized_pnl_cents']=pnl(p,prices) if p['status']=='open' else 0
            a['positions'].append(item)
        result.append(a)
    return result


def protection(db,user,pid,data):
    from . import prop
    p=db.execute('SELECT * FROM positions WHERE id=?',(pid,)).fetchone()
    if not p: raise Error('Position not found',404)
    owned(db,user,p['account_id'])
    if p['status']!='open': raise Error('Position is closed',409)
    prop.before_trade(db,user,p['account_id'])
    stop=prop.price(data.get('stop_loss'));take=prop.price(data.get('take_profit'))
    prop.check_stops(quotes(db)[p['symbol']],p['side'],stop,take)
    if not db.execute('SELECT 1 FROM trade_meta WHERE position_id=?',(pid,)).fetchone():
        prop.opened(db,p['account_id'],pid,reserved_for(p['symbol'],p['quantity']),stop,take)
    else: db.execute('UPDATE trade_meta SET stop_price=?,take_price=? WHERE position_id=?',(stop,take,pid))
    audit(db,user['id'],'position.protection',pid)
    return {'id':pid,'stop_price_units':stop,'take_price_units':take,'price_scale':10000}
