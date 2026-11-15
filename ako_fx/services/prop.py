"""Paper challenge lifecycle with atomic wallet settlement and manual review gates."""
import calendar
import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from ako_fx.store import transfer, audit, Error, balance
from .prop_rules import PLANS, LEGACY_PLANS, VERSION, SOURCES, CONFLICTS, MANUAL_CHECKS

DAY=86400

def now(): return int(time.time())

def admin(user):
    if user['role']!='admin': raise Error('Admin access required',403)

def contract(db,aid):
    row=db.execute('SELECT * FROM prop_contracts WHERE account_id=?',(aid,)).fetchone()
    return dict(row) if row else None

def rules(c): return json.loads(c['rules_json'])

def day_at(timestamp,rule): return datetime.fromtimestamp(timestamp,ZoneInfo(rule['broker_timezone'])).date().isoformat()

def realized(db,aid): return balance(db,'account:'+aid)+balance(db,'reserve:'+aid)

def positions(db,aid): return db.execute("SELECT * FROM positions WHERE account_id=? AND status='open'",(aid,)).fetchall()

def event(db,c,kind,payload):
    encoded=json.dumps(payload,sort_keys=True)
    # Keep one observation of each kind per cycle; historical breaches cannot disappear after recovery.
    previous=db.execute('SELECT payload FROM prop_events WHERE account_id=? AND cycle=? AND kind=?',(c['account_id'],c['cycle'],kind)).fetchall()
    if previous and kind!='manual_violation':
        if kind!='floating_risk' or payload.get('stop_evidence') or any(not json.loads(row[0]).get('stop_evidence') for row in previous): return
    eid=uuid.uuid4().hex
    db.execute('INSERT INTO prop_events VALUES(?,?,?,?,?,?)',(eid,c['account_id'],c['cycle'],kind,encoded,now()))
    audit(db,'system','prop.'+kind,c['account_id'])

def create_contract(db,user,plan,*,stage=1):
    aid=uuid.uuid4().hex;t=now();rule=dict(plan)
    rule['broker_timezone']=db.execute("SELECT value FROM prop_settings WHERE key='broker_timezone'").fetchone()[0]
    db.execute('INSERT INTO accounts(id,user_id,kind,initial_balance) VALUES(?,?,?,?)',(aid,user['id'],'prop',plan['capital_cents']))
    transfer(db,'demo:issuer','account:'+aid,plan['capital_cents'],'prop.capital')
    db.execute('''INSERT INTO prop_contracts(account_id,plan_id,class,rules_json,fee_cents,created,stage,phase_created,broker_day,day_start_balance,funded_at)
 VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(aid,plan['id'],plan['class'],json.dumps(rule,sort_keys=True),plan['fee_cents'],t,stage,t,day_at(t,rule),plan['capital_cents'],t if stage==3 else None))
    return aid

def purchase(db,user,data):
    plan=next((p for p in PLANS if p['id']==data.get('plan_id')),None)
    if not plan: raise Error('Choose an A/B plan from /api/prop/plans; legacy plans are no longer sold',404)
    sweep(db,user['id'])
    rows=db.execute("SELECT initial_balance FROM accounts WHERE user_id=? AND kind='prop' AND status NOT IN ('failed','closed','expired','passed')",(user['id'],)).fetchall()
    if len(rows)>=2 or sum(r['initial_balance'] for r in rows)+plan['capital_cents']>25000000:
        raise Error('Maximum two active Prop accounts and 250000 DEMO-USD initial allocation per user',409)
    transfer(db,'wallet:'+user['id'],'demo:prop-fees',plan['fee_cents'],'prop.purchase')
    aid=create_contract(db,user,plan)
    audit(db,user['id'],'prop.purchase:'+plan['id'],aid)
    return {'id':aid,'kind':'prop','status':'active','stage':1,'plan':plan,'rules_version':VERSION}

def legacy_purchase(db,user,plan_id):
    """Offline migration fixture only; never routed to the public purchase API."""
    p=next(p for p in LEGACY_PLANS if p['id']==plan_id);aid=uuid.uuid4().hex
    transfer(db,'wallet:'+user['id'],'demo:prop-fees',p['fee_cents'],'prop.purchase.legacy')
    db.execute('INSERT INTO accounts(id,user_id,kind,initial_balance) VALUES(?,?,?,?)',(aid,user['id'],'prop',p['capital_cents']))
    transfer(db,'demo:issuer','account:'+aid,p['capital_cents'],'prop.capital.legacy')
    return {'id':aid}

def fail(db,account,c,reason,status='failed'):
    from .broker import settle,quotes
    for p in positions(db,account['id']): settle(db,p,quotes(db))
    db.execute('UPDATE accounts SET status=? WHERE id=?',(status,account['id']))
    db.execute('UPDATE prop_contracts SET breach_reason=? WHERE account_id=?',(reason,account['id']))
    db.execute("UPDATE prop_requests SET status='rejected',decided=?,reason=? WHERE account_id=? AND status='pending'",(now(),'Automatic account closure: '+reason,account['id']))
    event(db,c,reason,{'status':status})
    return status

def assess(db,account):
    from .broker import equity
    c=contract(db,account['id'])
    if not c: return None
    if account['status'] not in ('active','awaiting_review'): return account['status']
    rule=rules(c);t=now();value=equity(db,account['id']);book=realized(db,account['id'])
    current_day=day_at(t,rule)
    if current_day!=c['broker_day']:
        db.execute('UPDATE prop_contracts SET broker_day=?,day_start_balance=? WHERE account_id=?',(current_day,book,account['id']))
        c['broker_day']=current_day;c['day_start_balance']=book
    if min(value,book)*10000<=account['initial_balance']*(10000-rule['total_loss_bps']):
        return fail(db,account,c,'total_drawdown')
    if min(value,book)*10000<=c['day_start_balance']*(10000-rule['daily_loss_bps']):
        return fail(db,account,c,'daily_drawdown')
    anchor=c['last_trade'] or c['phase_created']
    if t>=anchor+rule['inactivity_days']*DAY:
        return fail(db,account,c,'inactivity','expired')
    milestone=db.execute("SELECT created FROM prop_events WHERE account_id=? AND cycle=? AND kind='phase_target_met'",(account['id'],c['cycle'])).fetchone()
    if c['stage']<3 and max(book,value)*10000>=account['initial_balance']*(10000+rule['stage_targets_bps'][c['stage']-1]):
        event(db,c,'target_touched',{'book':book,'equity':value})
    if c['deadline'] is not None and t>=c['deadline'] and not milestone:
        from .broker import settle,quotes
        for p in positions(db,account['id']): settle(db,p,quotes(db))
        # A reset/extension is a reviewed request; never silently choose between conflicting clauses.
        if account['status']!='awaiting_review': db.execute("UPDATE accounts SET status='awaiting_review' WHERE id=?",(account['id'],))
        event(db,c,'deadline_reached',{'deadline':c['deadline']})
        return 'awaiting_review'
    if book>0 and value*10000<book*(10000-rule['floating_risk_bps']):
        from .broker import quotes
        marks=quotes(db);stops=[];crossed=False
        for p in positions(db,account['id']):
            m=db.execute('SELECT stop_price FROM trade_meta WHERE position_id=?',(p['id'],)).fetchone()
            if not m or m[0] is None: stops.append(None);continue
            loss=max(0,(p['entry_price']-m[0] if p['side']=='buy' else m[0]-p['entry_price'])*p['quantity']//100)
            stops.append(loss)
            crossed=crossed or (marks[p['symbol']]<m[0] if p['side']=='buy' else marks[p['symbol']]>m[0])
        sl_evidence=bool(stops) and all(v is not None for v in stops) and sum(v or 0 for v in stops)*10000<=book*rule['floating_risk_bps'] and crossed
        event(db,c,'floating_risk',{'book':book,'equity':value,'stop_evidence':sl_evidence})
    if c['stage']<3:
        target=rule['stage_targets_bps'][c['stage']-1]
        days=db.execute('SELECT COUNT(*) FROM prop_days WHERE account_id=? AND cycle=?',(account['id'],c['cycle'])).fetchone()[0]
        if book*10000>=account['initial_balance']*(10000+target) and not positions(db,account['id']) and days>=rule['min_trading_days']:
            event(db,c,'phase_target_met',{'book':book,'trading_days':days})
            db.execute("UPDATE accounts SET status='awaiting_review' WHERE id=?",(account['id'],))
            return 'awaiting_review'
    return account['status']

def sweep(db,uid=None):
    query="SELECT * FROM accounts WHERE kind='prop' AND status IN ('active','awaiting_review')"
    values=()
    if uid: query+=' AND user_id=?';values=(uid,)
    for a in db.execute(query,values).fetchall():
        if contract(db,a['id']): assess(db,dict(a))

def market_open(t):
    dt=datetime.fromtimestamp(t,timezone.utc);wd=dt.weekday()
    return not (wd==5 or wd==4 and dt.hour>=22 or wd==6 and dt.hour<22)

def before_trade(db,user,aid):
    from .broker import owned
    account=owned(db,user,aid);c=contract(db,aid)
    if not c: return None
    assess(db,account)
    account=owned(db,user,aid)
    if account['status']!='active': raise Error('Prop account is locked for review or has ended',409)
    if db.execute("SELECT 1 FROM prop_requests WHERE (account_id=? OR json_extract(payload,'$.other_account_id')=?) AND status='pending' AND kind!='refund20'",(aid,aid)).fetchone():
        raise Error('Trading is frozen while a Prop request is pending',409)
    if not market_open(now()): raise Error('Prop orders are unavailable while the reference Forex market is closed',409)
    return c

def opened(db,aid,pid,reserved,stop,take):
    c=contract(db,aid);t=now()
    db.execute('INSERT INTO trade_meta(position_id,opened,reserved_cents,stop_price,take_price,cycle) VALUES(?,?,?,?,?,?)',(pid,t,reserved,stop,take,c['cycle'] if c else 0))
    if not c: return
    rule=rules(c);deadline=c['deadline'];first=c['first_trade']
    if first is None:
        first=t
        if c['stage']<3 and rule['stage_days'][c['stage']-1]: deadline=t+rule['stage_days'][c['stage']-1]*DAY
    db.execute('UPDATE prop_contracts SET first_trade=?,last_trade=?,deadline=? WHERE account_id=?',(first,t,deadline,aid))
    db.execute('INSERT OR IGNORE INTO prop_days VALUES(?,?,?)',(aid,c['cycle'],day_at(t,rule)))

def closed(db,p,profit):
    t=now();db.execute('UPDATE trade_meta SET closed=? WHERE position_id=?',(t,p['id']))
    c=contract(db,p['account_id'])
    if c:
        db.execute('UPDATE prop_contracts SET last_trade=? WHERE account_id=?',(t,p['account_id']))

def price(value):
    if value in (None,''): return None
    try:
        d=Decimal(str(value))*10000
        if not d.is_finite() or d<=0 or d>100000000000 or d!=int(d): raise Error('Price must be positive with at most four decimals')
        return int(d)
    except (InvalidOperation,ValueError,TypeError): raise Error('Invalid stop/take price')

def check_stops(entry,side,stop,take):
    if stop is not None and (stop>=entry if side=='buy' else stop<=entry): raise Error('Stop loss is on the wrong side of the entry price')
    if take is not None and (take<=entry if side=='buy' else take>=entry): raise Error('Take profit is on the wrong side of the entry price')

def on_quotes(db):
    from .broker import quotes,settle
    prices=quotes(db)
    # Preserve the floating-risk observation BEFORE SL/TP fills remove exposure.
    sweep(db)
    for p in db.execute("SELECT p.*,m.stop_price,m.take_price FROM positions p JOIN trade_meta m ON m.position_id=p.id WHERE p.status='open'").fetchall():
        mark=prices[p['symbol']];buy=p['side']=='buy'
        stop=p['stop_price'] is not None and (mark<=p['stop_price'] if buy else mark>=p['stop_price'])
        take=p['take_price'] is not None and (mark>=p['take_price'] if buy else mark<=p['take_price'])
        if stop or take:
            if contract(db,p['account_id']) and not market_open(now()): continue
            if stop and mark!=p['stop_price']: db.execute('UPDATE trade_meta SET slippage=1 WHERE position_id=?',(p['id'],))
            settle(db,p,prices)
    sweep(db)

def view(db,account):
    c=contract(db,account['id'])
    if not c: return {'rules_version':'legacy-0.1','stage':None,'legacy':True}
    from .broker import equity
    r=rules(c);days=db.execute('SELECT COUNT(*) FROM prop_days WHERE account_id=? AND cycle=?',(account['id'],c['cycle'])).fetchone()[0]
    return {'rules_version':r['rules_version'],'class':c['class'],'stage':c['stage'],'cycle':c['cycle'],
        'plan_id':c['plan_id'],'broker_timezone':r['broker_timezone'],'trading_days':days,
        'min_trading_days':r['min_trading_days'] if c['stage']<3 else r['first_payout_trading_days'],
        'deadline':c['deadline'],'first_trade':c['first_trade'],'funded_at':c['funded_at'],
        'payout_count':c['payout_count'],'breach_reason':c['breach_reason'],
        'refund20_completed':bool(c['refund20']),'refund100_completed':bool(c['refund100']),
        'target_bps':r['stage_targets_bps'][c['stage']-1] if c['stage']<3 else None,
        'daily_floor_cents':(c['day_start_balance']*9500+9999)//10000,
        'total_floor_cents':(account['initial_balance']*8800+9999)//10000,
        'balance_cents':realized(db,account['id']),'equity_cents':equity(db,account['id']),
        'rules':r,'review_flags':review_flags(db,c,account),
        'requests':[dict(row) for row in db.execute('SELECT id,kind,status,created,reason,result FROM prop_requests WHERE account_id=? ORDER BY created DESC',(account['id'],))]}

def evaluate(db,user,aid,data):
    from .broker import owned
    account=owned(db,user,aid)
    if account['kind']!='prop': raise Error('Prop account required')
    if not contract(db,aid):
        from .broker import assess,equity
        status=assess(db,account)
        return {'id':aid,'status':status,'equity_cents':equity(db,aid),'rules_version':'legacy-0.1'}
    assess(db,account)
    account=owned(db,user,aid)
    audit(db,user['id'],'prop.evaluate',aid)
    return {'id':aid,'status':account['status'],'prop':view(db,account)}

def review_flags(db,c,account):
    flags=[dict(row) for row in db.execute('SELECT kind,payload FROM prop_events WHERE account_id=? AND cycle=? AND kind IN (\'floating_risk\',\'manual_violation\')',(account['id'],c['cycle']))]
    short=db.execute('''SELECT COALESCE(SUM(p.pnl),0) FROM positions p JOIN trade_meta m ON m.position_id=p.id
 WHERE p.account_id=? AND m.cycle=? AND p.status='closed' AND p.pnl>0 AND m.closed-m.opened<30''',(account['id'],c['cycle'])).fetchone()[0]
    r=rules(c)
    base=account['initial_balance']*r['stage_targets_bps'][c['stage']-1]//10000 if c['stage']<3 else max(0,realized(db,account['id'])-account['initial_balance'])
    if short*10000>base*r['tick_profit_limit_bps']:
        flags.append({'kind':'tick_scalping','payload':json.dumps({'short_profit_cents':short,'reference_cents':base})})
    return flags

def ensure_flat(db,aid):
    if positions(db,aid): raise Error('Close all positions before this request',409)

def eligible(db,account,c,kind,submitted=None):
    r=rules(c);t=now();book=realized(db,account['id']);initial=account['initial_balance'];stage=c['stage']
    if account['status'] in ('failed','expired'): raise Error('Account has ended; no payout or refund is available',409)
    if account['status']=='closed' and kind!='refund20': raise Error('Closed account is unavailable',409)
    if kind not in ('transition','payout','refund20','reset','extend','growth','merge'): raise Error('Unknown Prop request kind')
    ensure_flat(db,account['id'])
    days=db.execute('SELECT COUNT(*) FROM prop_days WHERE account_id=? AND cycle=?',(account['id'],c['cycle'])).fetchone()[0]
    if kind=='transition':
        if stage==3 or book*10000<initial*(10000+r['stage_targets_bps'][stage-1]) or days<r['min_trading_days']:
            raise Error('Stage target and minimum trading days must both be met',409)
        met=db.execute("SELECT created FROM prop_events WHERE account_id=? AND cycle=? AND kind='phase_target_met'",(account['id'],c['cycle'])).fetchone()
        if c['deadline'] and t>=c['deadline'] and not (met and met[0]<c['deadline']): raise Error('Stage deadline has passed; request reset or eligible extension',409)
    elif kind=='payout':
        if stage!=3 or book<=initial or c['first_trade'] is None: raise Error('A funded-demo account with realized profit is required',409)
        if c['payout_count']==0:
            if t<c['first_trade']+21*DAY or days<r['first_payout_trading_days']: raise Error('First payout requires 21 days and the class minimum trading days',409)
        elif t<(c['last_payout'] or 0)+(7 if c['class']=='B' and c['payout_count']>=6 else 14)*DAY:
            raise Error('Payout interval has not elapsed',409)
    elif kind=='refund20':
        if c['funded_at'] is None or c['refund20'] or (submitted if submitted is not None else t)>c['funded_at']+45*DAY or c['fee_cents']<=0:
            raise Error('20% refund is unavailable or outside its 45-day request window',409)
    elif kind in ('reset','extend'):
        expired=c['deadline'] is not None and t>=c['deadline']
        flagged=bool(review_flags(db,c,account))
        if kind=='reset' and c['class']=='A' and flagged and c['stage']<3:
            touched=db.execute("SELECT 1 FROM prop_events WHERE account_id=? AND cycle=? AND kind='target_touched'",(account['id'],c['cycle'])).fetchone()
            if not touched: raise Error('A rule-violation reset requires the stage target to have been touched',409)
        if kind=='extend':
            if c['class']!='A' or stage!=1 or c['extension_used'] or not expired or book<=initial or days<5 or flagged:
                raise Error('A extension requires phase 1, expired profitable account, 5 days, no violations, and no previous extension',409)
        elif not flagged and not (c['class']=='A' and stage<3 and expired and book>initial and days>=5):
            raise Error('Reset requires review flags or an eligible expired A challenge',409)
    elif kind=='growth':
        if stage!=3 or not c['last_payout'] or t<add_months(c['last_growth'] or c['funded_at'],3):
            raise Error('Growth requires a funded account, completed payout and three calendar months',409)
        history=db.execute('SELECT COALESCE(SUM(gross),0) FROM prop_payouts WHERE account_id=? AND created>=?',(account['id'],c['last_growth'] or c['funded_at'])).fetchone()[0]
        if history*10000<initial*800 or book!=initial or initial*140//100>r['growth_cap_cents']:
            raise Error('Growth needs 8% paid profit, all current profit paid out and space below the class cap',409)
    elif kind=='merge':
        if stage!=3 or book!=initial or not c['last_payout']: raise Error('Merge requires funded accounts after full profit payout',409)

def add_months(timestamp,months):
    d=datetime.fromtimestamp(timestamp,timezone.utc);m=d.month-1+months;y=d.year+m//12;m=m%12+1
    return int(d.replace(year=y,month=m,day=min(d.day,calendar.monthrange(y,m)[1])).timestamp())

def request(db,user,aid,data):
    from .broker import owned
    account=owned(db,user,aid);c=contract(db,aid)
    if not c: raise Error('This is a legacy account; new A/B request workflows do not apply',409)
    assess(db,account);account=owned(db,user,aid);c=contract(db,aid)
    kind=data.get('kind');eligible(db,account,c,kind)
    payload={}
    if kind=='merge':
        other=data.get('other_account_id')
        if not isinstance(other,str) or other==aid: raise Error('Choose a different owned account to merge')
        second=owned(db,user,other);other_c=contract(db,other)
        if not other_c or other_c['class']!=c['class']: raise Error('Only funded accounts in the same class can merge',409)
        assess(db,second);second=owned(db,user,other);other_c=contract(db,other)
        eligible(db,second,other_c,'merge')
        if db.execute("SELECT 1 FROM prop_requests WHERE account_id=? AND status='pending'",(other,)).fetchone(): raise Error('Other account already has a pending request',409)
        payload={'other_account_id':other}
    if db.execute("SELECT 1 FROM prop_requests WHERE status='pending' AND (account_id=? OR json_extract(payload,'$.other_account_id')=?)",(aid,aid)).fetchone(): raise Error('An account can have only one pending request',409)
    rid=uuid.uuid4().hex
    db.execute('INSERT INTO prop_requests(id,account_id,kind,payload,created) VALUES(?,?,?,?,?)',(rid,aid,kind,json.dumps(payload),now()))
    audit(db,user['id'],'prop.request.'+kind,rid)
    return {'id':rid,'status':'pending','kind':kind,'review_flags':review_flags(db,c,account)}

def rebase(db,aid,target,kind):
    book=realized(db,aid)
    if book>target: transfer(db,'account:'+aid,'demo:issuer',book-target,kind)
    elif book<target: transfer(db,'demo:issuer','account:'+aid,target-book,kind)

def restart(db,account,c,stage):
    ensure_flat(db,account['id']);t=now();r=rules(c)
    rebase(db,account['id'],account['initial_balance'],'prop.phase-reset')
    db.execute("UPDATE accounts SET status='active' WHERE id=?",(account['id'],))
    db.execute('''UPDATE prop_contracts SET stage=?,cycle=cycle+1,phase_created=?,first_trade=NULL,last_trade=NULL,
 deadline=NULL,extension_used=0,broker_day=?,day_start_balance=?,breach_reason=NULL,
 funded_at=CASE WHEN ?=3 THEN COALESCE(funded_at,?) ELSE funded_at END WHERE account_id=?''',
 (stage,t,day_at(t,r),account['initial_balance'],stage,t,account['id']))

def payout_share(c):
    if c['class']=='B': return 7500 if c['payout_count']==0 else 8000 if c['payout_count']<6 else 9000
    # Calendar month of the funded account, not a hard-coded 60-day approximation.
    return 8500 if now()>=add_months(c['funded_at'],2) else 8000

def settle_request(db,user,req,account,c,data):
    kind=req['kind'];aid=account['id'];t=now();initial=account['initial_balance']
    if kind=='transition': restart(db,account,c,c['stage']+1);return {'stage':c['stage']+1,'account_id':aid}
    if kind=='reset':
        if c['class']=='A' and c['extension_used'] and data.get('source_conflict_ack') is not True:
            raise Error('A reset after extension has contradictory source wording; explicit admin acknowledgement is required',409)
        restart(db,account,c,c['stage']);return {'stage':c['stage'],'reset':True}
    if kind=='extend':
        db.execute("UPDATE accounts SET status='active' WHERE id=?",(aid,))
        db.execute('UPDATE prop_contracts SET deadline=deadline+?,extension_used=1 WHERE account_id=?',(10*DAY,aid))
        return {'extended_days':10}
    if kind=='refund20':
        amount=c['fee_cents']*20//100
        transfer(db,'demo:issuer','wallet:'+account['user_id'],amount,'prop.refund20')
        db.execute('UPDATE prop_contracts SET refund20=1 WHERE account_id=?',(aid,))
        return {'demo_refund_cents':amount}
    if kind=='payout':
        gross=realized(db,aid)-initial;share=payout_share(c);net=gross*share//10000
        transfer(db,'account:'+aid,'demo:prop-profit-share',gross,'prop.payout-profit')
        if net: transfer(db,'demo:issuer','wallet:'+account['user_id'],net,'prop.payout-demo')
        db.execute('INSERT INTO prop_payouts VALUES(?,?,?,?,?)',(req['id'],aid,gross,net,t))
        refund=0
        if c['payout_count']==0 and not c['refund100'] and c['fee_cents']:
            refund=c['fee_cents'];transfer(db,'demo:issuer','wallet:'+account['user_id'],refund,'prop.refund100')
        db.execute('UPDATE prop_contracts SET payout_count=payout_count+1,last_payout=?,refund100=1,cycle=cycle+1,day_start_balance=?,broker_day=? WHERE account_id=?',(t,initial,day_at(t,rules(c)),aid))
        return {'gross_cents':gross,'demo_net_cents':net,'share_bps':share,'demo_refund_cents':refund}
    if kind=='growth':
        target=initial*140//100
        transfer(db,'demo:issuer','account:'+aid,target-initial,'prop.growth')
        db.execute('UPDATE accounts SET initial_balance=? WHERE id=?',(target,aid))
        db.execute('UPDATE prop_contracts SET last_growth=?,day_start_balance=?,broker_day=? WHERE account_id=?',(t,target,day_at(t,rules(c)),aid))
        return {'capital_cents':target}
    if kind=='merge':
        from .broker import owned
        payload=json.loads(req['payload'])
        # Ownership is checked explicitly against the current source account owner.
        other=db.execute('SELECT * FROM accounts WHERE id=? AND user_id=?',(payload['other_account_id'],account['user_id'])).fetchone()
        if not other: raise Error('Other account is not available',409)
        other=dict(other);oc=contract(db,other['id'])
        if not oc or oc['class']!=c['class']: raise Error('Merge class mismatch',409)
        eligible(db,other,oc,'merge')
        if review_flags(db,oc,other): raise Error('Other merge account has unresolved rule flags',409)
        total=initial+other['initial_balance'];plan=rules(c)
        if total>plan['growth_cap_cents']: raise Error('Merged capital exceeds class cap',409)
        plan.update(id='merged-'+c['class'].lower(),capital_cents=total,fee_cents=0,floating_risk_bps=200 if total>=10000000 else 300)
        dest=create_contract(db,{'id':account['user_id']},plan,stage=3)
        db.execute('UPDATE prop_contracts SET payout_count=?,funded_at=?,first_trade=?,last_payout=? WHERE account_id=?',
            (min(c['payout_count'],oc['payout_count']),max(c['funded_at'],oc['funded_at']),max(c['first_trade'] or t,oc['first_trade'] or t),max(c['last_payout'] or t,oc['last_payout'] or t),dest))
        for source in (aid,other['id']):
            rebase(db,source,0,'prop.merge-retire')
            db.execute("UPDATE accounts SET status='closed' WHERE id=?",(source,))
        return {'account_id':dest,'capital_cents':total}
    raise Error('Unsupported request')

def decide(db,user,rid,data):
    admin(user)
    req=db.execute('SELECT * FROM prop_requests WHERE id=?',(rid,)).fetchone()
    if not req: raise Error('Request not found',404)
    req=dict(req)
    if req['status']!='pending': raise Error('Request already decided',409)
    decision=data.get('decision');reason=data.get('reason')
    if decision not in ('approve','reject','reset','fail') or not isinstance(reason,str) or not 8<=len(reason)<=1000:
        raise Error('Decision and a reason of 8..1000 characters are required')
    account=dict(db.execute('SELECT * FROM accounts WHERE id=?',(req['account_id'],)).fetchone());c=contract(db,account['id'])
    if decision=='reject': result={'rejected':True}
    elif decision=='fail':
        result={'status':fail(db,account,c,'manual_violation')}
    else:
        checks=data.get('checks',{})
        if not isinstance(checks,dict) or any(checks.get(k) is not True for k in MANUAL_CHECKS):
            raise Error('Complete all manual identity, ownership and trading-policy checks before approval',409)
        eligible(db,account,c,req['kind'],submitted=req['created'])
        flags=review_flags(db,c,account)
        risk=[f for f in flags if f['kind']=='floating_risk']
        manual=[f for f in flags if f['kind']=='manual_violation']
        slippage_ok=data.get('slippage_exempt') is True and risk and all(json.loads(f['payload']).get('stop_evidence') for f in risk)
        if decision=='approve' and req['kind']!='reset' and (manual or risk and not slippage_ok or any(f['kind']=='tick_scalping' for f in flags)):
            raise Error('Review flags require reset/failure, or a documented stop-slippage exception',409)
        if decision=='reset' or req['kind']=='reset':
            if not flags and req['kind']!='reset': raise Error('Review reset requires an observed rule flag',409)
            if c['stage']==3 and any(f['kind'] in ('floating_risk','manual_violation') for f in flags) and not slippage_ok:
                result={'status':fail(db,account,c,'funded_risk_violation')}
            else:
                reset_req=dict(req,kind='reset');result=settle_request(db,user,reset_req,account,c,data)
        else: result=settle_request(db,user,req,account,c,data)
    result['review_evidence']={'checks':data.get('checks',{}),'slippage_exempt':data.get('slippage_exempt') is True,'source_conflict_ack':data.get('source_conflict_ack') is True}
    status='rejected' if decision in ('reject','fail') or result.get('status')=='failed' else 'approved'
    db.execute('UPDATE prop_requests SET status=?,decided=?,reviewer=?,reason=?,result=? WHERE id=?',(status,now(),user['id'],reason,json.dumps(result),rid))
    audit(db,user['id'],'prop.review.'+decision,rid)
    return {'id':rid,'status':status,'result':result}

def admin_requests(db,user):
    admin(user)
    result=[]
    for row in db.execute('''SELECT r.*,a.user_id,u.email FROM prop_requests r JOIN accounts a ON a.id=r.account_id JOIN users u ON u.id=a.user_id ORDER BY r.created DESC LIMIT 500'''):
        item=dict(row);a=dict(db.execute('SELECT * FROM accounts WHERE id=?',(row['account_id'],)).fetchone())
        item['account']=view(db,a);result.append(item)
    return {'requests':result,'required_checks':MANUAL_CHECKS,'source_conflicts':CONFLICTS}

def flag(db,user,aid,data):
    admin(user);c=contract(db,aid)
    if not c: raise Error('Versioned Prop account not found',404)
    reason=data.get('reason')
    if not isinstance(reason,str) or not 8<=len(reason)<=1000: raise Error('A documented reason is required')
    event(db,c,'manual_violation',{'reason':reason,'reviewer':user['id']})
    action=data.get('action','record')
    if action not in ('record','fail','fail_owner'): raise Error('Action must be record, fail or fail_owner')
    affected=[]
    if action!='record':
        account=dict(db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone())
        targets=db.execute("SELECT * FROM accounts WHERE user_id=? AND kind='prop' AND status IN ('active','awaiting_review')",(account['user_id'],)).fetchall() if action=='fail_owner' else [account]
        for a in targets:
            target_c=contract(db,a['id'])
            if target_c:
                fail(db,dict(a),target_c,'manual_violation');affected.append(a['id'])
        audit(db,user['id'],'prop.confirmed-violation.'+action,aid)
    return {'flagged':True,'closed_accounts':affected}

def settings(db,user,data):
    admin(user);zone=data.get('broker_timezone')
    if not isinstance(zone,str) or len(zone)>100: raise Error('IANA broker_timezone is required')
    try: ZoneInfo(zone)
    except (ZoneInfoNotFoundError,ValueError): raise Error('Unknown timezone')
    db.execute("UPDATE prop_settings SET value=? WHERE key='broker_timezone'",(zone,))
    audit(db,user['id'],'prop.settings.timezone',zone)
    return {'broker_timezone':zone,'applies_to':'future purchases only'}


def admin_accounts(db,user):
    admin(user)
    rows=db.execute("SELECT a.*,u.email FROM accounts a JOIN users u ON u.id=a.user_id WHERE a.kind='prop' ORDER BY a.rowid DESC LIMIT 500").fetchall()
    return {'accounts':[dict(dict(a),prop=view(db,dict(a))) for a in rows]}
