import contextlib
import json
from datetime import datetime,timezone
import unittest
from unittest.mock import patch
import test_acceptance as base
from ako_fx.services import prop,broker
from ako_fx.services.prop_rules import MANUAL_CHECKS,VERSION
from ako_fx.store import Error,transaction,transfer,init

class PropRules(unittest.TestCase):
    call=base.Acceptance.call
    error=base.Acceptance.error
    funded=base.Acceptance.funded
    def setUp(self):
        base.Acceptance.setUp(self)
        self.t=int(datetime(2026,11,16,12,tzinfo=timezone.utc).timestamp())
        self.clock=patch.object(prop,'now',side_effect=lambda:self.t);self.clock.start()
        self.funded('10000')
    def tearDown(self):
        self.clock.stop();base.Acceptance.tearDown(self)
    def buy(self,plan='b-10000'):
        return self.call('POST','/api/prop/purchases',{'plan_id':plan})['id']
    def account(self,aid):
        return next(a for a in self.call('GET','/api/accounts')['accounts'] if a['id']==aid)
    def c(self,aid):
        with transaction() as db:return prop.contract(db,aid)
    def profit(self,aid,cents):
        with transaction() as db:transfer(db,'demo:issuer','account:'+aid,cents,'test.fixture-profit')
    def days(self,aid,count):
        with transaction() as db:
            c=prop.contract(db,aid)
            for n in range(count):db.execute('INSERT OR IGNORE INTO prop_days VALUES(?,?,?)',(aid,c['cycle'],f'2026-11-{n+1:02}'))
    def fund_phase(self,aid):
        with transaction() as db:
            c=prop.contract(db,aid);a=dict(db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone())
            prop.restart(db,a,c,3)
    def opened(self,aid,quantity=100,**kw):
        return self.call('POST','/api/broker/accounts/'+aid+'/positions',dict(symbol='EURUSD',side='buy',quantity=quantity,**kw))['id']
    def close(self,pid):
        self.t+=31
        return self.call('POST','/api/broker/positions/'+pid+'/close')
    def req(self,aid,kind,**kwargs):
        return self.call('POST','/api/prop/accounts/'+aid+'/requests',dict(kind=kind,**kwargs))['id']
    def approve(self,rid,decision='approve',**kwargs):
        return self.call('POST','/api/admin/prop/requests/'+rid,dict(decision=decision,reason='Fixture review checked',checks={k:True for k in MANUAL_CHECKS},**kwargs),token=self.admin_token)
    def payout_ready(self,aid):
        self.fund_phase(aid)
        with transaction() as db:
            db.execute('UPDATE prop_contracts SET first_trade=?,last_trade=? WHERE account_id=?',(self.t-21*prop.DAY,self.t,aid))
        self.days(aid,10);self.profit(aid,10000)
    def test_catalogue_exact_classes_and_prices(self):
        data=self.call('GET','/api/prop/plans')['plans']
        self.assertEqual(len(data),14)
        self.assertEqual([p['fee_cents'] for p in data if p['class']=='A'],[1500,3000,5500,8800,15700,31400])
        self.assertEqual([p['fee_cents'] for p in data if p['class']=='B'],[1700,3500,6000,9800,17400,32900,52200,99900])
        self.error(404,'POST','/api/prop/purchases',{'plan_id':'starter'})
    def test_purchase_is_atomic_and_snapshot_is_versioned(self):
        before=self.call('GET','/api/wallet')['balance_cents'];aid=self.buy('a-10000')
        a=self.account(aid);self.assertEqual(a['prop']['rules_version'],VERSION)
        self.assertEqual(a['prop']['target_bps'],800)
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],before-8800)
        self.assertIsNone(self.c(aid)['deadline'])
        self.call('POST','/api/admin/prop/settings',{'broker_timezone':'Asia/Tehran'},token=self.admin_token)
        self.assertEqual(self.account(aid)['prop']['broker_timezone'],'UTC')
        second=self.buy('b-1000');self.assertEqual(self.account(second)['prop']['broker_timezone'],'Asia/Tehran')
    def test_max_accounts_and_total_allocation(self):
        self.buy('b-200000')
        self.error(409,'POST','/api/prop/purchases',{'plan_id':'b-100000'})
        self.buy('a-50000')
        self.error(409,'POST','/api/prop/purchases',{'plan_id':'a-1000'})
    def test_deadline_starts_on_first_trade_A_B_unlimited(self):
        a=self.buy('a-1000');b=self.buy('b-1000')
        self.t+=2*prop.DAY
        p=self.opened(a);self.close(p)
        self.assertEqual(self.c(a)['deadline'],self.c(a)['first_trade']+30*prop.DAY)
        p=self.opened(b);self.close(p)
        self.assertIsNone(self.c(b)['deadline'])
    def test_same_day_and_overnight_count_open_date_only(self):
        aid=self.buy();p=self.opened(aid);self.t+=prop.DAY;self.close(p)
        self.assertEqual(self.account(aid)['prop']['trading_days'],1)
        p=self.opened(aid);self.close(p);p=self.opened(aid);self.close(p)
        self.assertEqual(self.account(aid)['prop']['trading_days'],2)
    def test_daily_drawdown_equality_and_persistence_on_rejected_order(self):
        aid=self.buy();self.opened(aid,10000)
        # Exactly a 5% book/equity loss at the next quote is a permanent failure.
        with transaction() as db:db.execute("UPDATE quotes SET price=10500 WHERE symbol='EURUSD'")
        self.error(409,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1})
        a=self.account(aid);self.assertEqual(a['status'],'failed');self.assertEqual(a['prop']['breach_reason'],'daily_drawdown')
        self.assertEqual(a['reserved_cents'],0)
    def test_total_drawdown_static_floor_after_profit(self):
        aid=self.buy();self.profit(aid,20000)
        self.assertEqual(self.account(aid)['prop']['total_floor_cents'],880000)
        with transaction() as db:
            transfer(db,'account:'+aid,'demo:losses',140000,'test.fixture-loss')
            db.execute('UPDATE prop_contracts SET day_start_balance=900000 WHERE account_id=?',(aid,))
        self.assertEqual(self.account(aid)['prop']['breach_reason'],'total_drawdown')
    def test_midnight_uses_balance_not_positive_or_negative_floating_equity(self):
        aid=self.buy();self.opened(aid,1000)
        self.call('POST','/api/admin/scenario',{'scenario':'up'},token=self.admin_token)
        self.t+=prop.DAY
        a=self.account(aid)
        self.assertEqual(a['prop']['daily_floor_cents'],950000)
        self.assertGreater(a['equity_cents'],1000000)
        self.call('POST','/api/admin/scenario',{'scenario':'reset'},token=self.admin_token)
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        self.t+=prop.DAY
        self.assertEqual(self.account(aid)['prop']['daily_floor_cents'],950000)
    def test_target_needs_days_and_admin_not_automatic_pass(self):
        aid=self.buy();self.profit(aid,100000)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'transition'})
        self.days(aid,3)
        self.assertEqual(self.account(aid)['status'],'awaiting_review')
        rid=self.req(aid,'transition')
        self.error(403,'POST','/api/admin/prop/requests/'+rid,{'decision':'approve','reason':'Bad caller review'})
        self.error(409,'POST','/api/admin/prop/requests/'+rid,{'decision':'approve','reason':'Incomplete checks'},token=self.admin_token)
        self.approve(rid)
        a=self.account(aid);self.assertEqual(a['prop']['stage'],2);self.assertEqual(a['balance_cents'],1000000)
        self.assertEqual(a['prop']['trading_days'],0)
        self.error(409,'POST','/api/admin/prop/requests/'+rid,{'decision':'approve','reason':'Duplicate decision'},token=self.admin_token)
    def test_two_phases_with_real_trades_and_separate_days(self):
        aid=self.buy()
        for stage,quantity in ((1,20000),(2,10000)):
            for day in range(3):
                p=self.opened(aid,quantity if day==2 else 1)
                if day==2:self.call('POST','/api/admin/scenario',{'scenario':'up'},token=self.admin_token)
                self.close(p)
                if day<2:self.t+=prop.DAY
            rid=self.req(aid,'transition');self.approve(rid)
        a=self.account(aid);self.assertEqual(a['prop']['stage'],3);self.assertEqual(a['status'],'active')
        self.assertIsNone(a['prop']['target_bps']);self.assertEqual(a['balance_cents'],1000000)
    def test_floating_risk_3_and_2_percent_is_reviewed(self):
        small=self.buy('b-10000');large=self.buy('b-100000')
        self.opened(small,6000);self.opened(large,40000)
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        self.assertIn('floating_risk',[f['kind'] for f in self.account(small)['prop']['review_flags']])
        self.assertIn('floating_risk',[f['kind'] for f in self.account(large)['prop']['review_flags']])
        self.assertEqual(self.account(large)['prop']['rules']['floating_risk_bps'],200)
    def test_optional_stops_fill_on_synthetic_gap_and_record_evidence(self):
        aid=self.buy();pid=self.opened(aid,6000,stop_loss='1.0533')
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        a=self.account(aid);self.assertEqual(a['positions'][0]['status'],'closed')
        risk=next(f for f in a['prop']['review_flags'] if f['kind']=='floating_risk')
        self.assertTrue(json.loads(risk['payload'])['stop_evidence'])
        with transaction() as db:self.assertEqual(db.execute('SELECT slippage FROM trade_meta WHERE position_id=?',(pid,)).fetchone()[0],1)
    def test_tick_scalp_strict_boundary(self):
        aid=self.buy()
        with transaction() as db:
            db.execute("INSERT INTO positions VALUES('tick',?,'EURUSD','buy',1,11000,'closed',11001,20000)",(aid,))
            db.execute("INSERT INTO trade_meta VALUES('tick',100,129,1,NULL,NULL,0,1)")
        self.assertNotIn('tick_scalping',[f['kind'] for f in self.account(aid)['prop']['review_flags']])
        with transaction() as db:db.execute("UPDATE positions SET pnl=20001 WHERE id='tick'")
        self.assertIn('tick_scalping',[f['kind'] for f in self.account(aid)['prop']['review_flags']])
        with transaction() as db:db.execute("UPDATE trade_meta SET closed=130 WHERE position_id='tick'")
        self.assertNotIn('tick_scalping',[f['kind'] for f in self.account(aid)['prop']['review_flags']])
    def test_payout_requires_time_days_and_no_open_positions(self):
        aid=self.buy();self.fund_phase(aid);self.profit(aid,10000)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'payout'})
        self.payout_ready(aid);pid=self.opened(aid)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'payout'})
        self.close(pid);rid=self.req(aid,'payout')
        self.error(409,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1})
        self.assertEqual(self.approve(rid)['result']['share_bps'],7500)
    def test_payout_full_profit_refund_and_once_only(self):
        aid=self.buy();self.payout_ready(aid);before=self.call('GET','/api/wallet')['balance_cents']
        rid=self.req(aid,'payout');key='payout-review-idempotent'
        data={'decision':'approve','reason':'All policy checks confirmed','checks':{k:True for k in MANUAL_CHECKS}}
        a=self.call('POST','/api/admin/prop/requests/'+rid,data,token=self.admin_token,key=key)
        b=self.call('POST','/api/admin/prop/requests/'+rid,data,token=self.admin_token,key=key)
        self.assertEqual(a,b)
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents']-before,7500+9800)
        self.assertEqual(self.account(aid)['balance_cents'],1000000)
        self.assertEqual(self.c(aid)['payout_count'],1)
    def test_payout_tiers_and_calendar_month_A(self):
        aid=self.buy('a-10000');self.payout_ready(aid);c=self.c(aid)
        self.assertEqual(prop.payout_share(c),8000)
        self.t=prop.add_months(c['funded_at'],2)
        self.assertEqual(prop.payout_share(c),8500)
        for number,expected in ((0,7500),(1,8000),(5,8000),(6,9000)):
            self.assertEqual(prop.payout_share({'class':'B','payout_count':number}),expected)
    def test_refund20_deadline_and_no_duplicate(self):
        aid=self.buy();self.fund_phase(aid);rid=self.req(aid,'refund20')
        self.assertEqual(self.approve(rid)['result']['demo_refund_cents'],1960)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'refund20'})
        other=self.buy('a-1000');self.fund_phase(other);self.t+=46*prop.DAY
        self.error(409,'POST','/api/prop/accounts/'+other+'/requests',{'kind':'refund20'})
    def test_weekend_holding_allowed_but_orders_blocked(self):
        aid=self.buy();pid=self.opened(aid)
        self.t=int(datetime(2026,11,21,12,tzinfo=timezone.utc).timestamp())
        self.error(409,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1})
        self.error(409,'POST','/api/broker/positions/'+pid+'/close')
        self.assertEqual(self.account(aid)['positions'][0]['status'],'open')
    def test_inactivity_survives_rejected_operation(self):
        aid=self.buy();self.t+=30*prop.DAY+1
        self.error(409,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1})
        self.assertEqual(self.account(aid)['status'],'expired')
    def test_A_extend_only_phase_one_once_after_deadline(self):
        aid=self.buy('a-10000');self.profit(aid,1000);self.days(aid,5)
        with transaction() as db:db.execute('UPDATE prop_contracts SET first_trade=?,last_trade=?,deadline=? WHERE account_id=?',(self.t-30*prop.DAY,self.t,self.t,aid))
        rid=self.req(aid,'extend');self.approve(rid)
        self.assertEqual(self.c(aid)['deadline'],self.t+10*prop.DAY)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'extend'})
        self.t+=10*prop.DAY
        rid=self.req(aid,'reset')
        self.error(409,'POST','/api/admin/prop/requests/'+rid,{'decision':'approve','reason':'Review source contradiction','checks':{k:True for k in MANUAL_CHECKS}},token=self.admin_token)
        self.approve(rid,source_conflict_ack=True)
        self.assertEqual(self.account(aid)['balance_cents'],1000000)
    def test_growth_and_merge_are_reviewed_with_rebased_floor(self):
        aid=self.buy();self.payout_ready(aid)
        with transaction() as db:
            prop.rebase(db,aid,1000000,'test.fixture-reset')
            db.execute('UPDATE prop_contracts SET funded_at=?,last_trade=?,last_payout=? WHERE account_id=?',(self.t-100*prop.DAY,self.t,self.t,aid))
            db.execute('INSERT INTO prop_payouts VALUES(?,?,?,?,?)',('paid-profit',aid,80000,60000,self.t-5*prop.DAY))
        rid=self.req(aid,'growth');self.approve(rid)
        self.assertEqual(self.account(aid)['initial_balance'],1400000)
        self.assertEqual(self.account(aid)['prop']['total_floor_cents'],1232000)
        second=self.buy();self.fund_phase(second)
        with transaction() as db:
            db.execute('UPDATE prop_contracts SET first_trade=?,last_trade=?,last_payout=? WHERE account_id=?',(self.t,self.t,self.t,second))
        rid=self.req(aid,'merge',other_account_id=second)
        dest=self.approve(rid)['result']['account_id']
        self.assertEqual(self.account(aid)['status'],'closed');self.assertEqual(self.account(second)['status'],'closed')
        self.assertEqual(self.account(dest)['initial_balance'],2400000)
        with transaction() as db:self.assertEqual(db.execute('SELECT SUM(delta) FROM entries').fetchone()[0],0)
    def test_review_ownership_and_state(self):
        aid=self.buy();self.error(404,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'transition'},token=self.admin_token)
        self.error(403,'POST','/api/admin/prop/settings',{'broker_timezone':'UTC'})
        self.error(400,'POST','/api/admin/prop/settings',{'broker_timezone':'invalid/zone'},token=self.admin_token)
        with transaction() as db:old=prop.contract(db,aid)['rules_json']
        init()
        self.assertEqual(self.c(aid)['rules_json'],old)
    def test_funded_intentional_risk_cannot_be_reset_via_approve(self):
        aid=self.buy();self.fund_phase(aid)
        pid=self.opened(aid,6000)
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        self.close(pid)
        rid=self.req(aid,'reset')
        result=self.approve(rid)
        self.assertEqual(result['result']['status'],'failed')
        self.assertEqual(self.account(aid)['status'],'failed')
    def test_confirmed_identity_violation_can_close_all_owned_prop_accounts(self):
        a=self.buy();b=self.buy('a-1000')
        self.call('POST','/api/admin/prop/accounts/'+a+'/flag',{'reason':'Confirmed identity-sharing fixture','action':'fail_owner'},token=self.admin_token)
        self.assertEqual(self.account(a)['status'],'failed');self.assertEqual(self.account(b)['status'],'failed')
        self.error(403,'GET','/api/admin/prop/accounts')
    def test_refund_request_submitted_in_time_can_be_approved_later(self):
        aid=self.buy();self.fund_phase(aid)
        self.t+=44*prop.DAY
        with transaction() as db:db.execute('UPDATE prop_contracts SET last_trade=? WHERE account_id=?',(self.t,aid))
        rid=self.req(aid,'refund20');self.t+=2*prop.DAY
        self.assertEqual(self.approve(rid)['result']['demo_refund_cents'],1960)
    def test_target_met_before_A_deadline_can_be_reviewed_after_it(self):
        aid=self.buy('a-10000');self.days(aid,5)
        with transaction() as db:db.execute('UPDATE prop_contracts SET deadline=?,last_trade=? WHERE account_id=?',(self.t+60,self.t,aid))
        self.profit(aid,80000);self.account(aid)
        self.t+=61;rid=self.req(aid,'transition');self.approve(rid)
        self.assertEqual(self.account(aid)['prop']['stage'],2)
    def test_A_stage_two_gets_sixty_days(self):
        aid=self.buy('a-10000')
        with transaction() as db:
            a=dict(db.execute('SELECT * FROM accounts WHERE id=?',(aid,)).fetchone());prop.restart(db,a,prop.contract(db,aid),2)
        self.opened(aid)
        self.assertEqual(self.c(aid)['deadline'],self.t+60*prop.DAY)
    def test_adverse_gap_never_creates_wallet_debt(self):
        aid=self.buy();before=self.call('GET','/api/wallet')['balance_cents']
        self.opened(aid,900000)
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        a=self.account(aid);self.assertEqual(a['status'],'failed')
        self.assertGreaterEqual(a['balance_cents'],0)
        self.assertEqual(self.call('GET','/api/wallet')['balance_cents'],before)
        with transaction() as db:self.assertEqual(db.execute('SELECT SUM(delta) FROM entries').fetchone()[0],0)
    def test_representative_asset_leverage_and_all_optional_stops(self):
        aid=self.buy()
        for symbol,leverage in broker.LEVERAGE.items():
            opened=self.call('POST','/api/broker/accounts/'+aid+'/positions',{'symbol':symbol,'side':'buy','quantity':1})
            expected=(broker.MARKS[symbol]+100*leverage-1)//(100*leverage)
            self.assertEqual(opened['reserved_cents'],expected)
            self.close(opened['id'])
    def test_A_risk_reset_needs_target_touch(self):
        aid=self.buy('a-10000');pid=self.opened(aid,6000)
        self.call('POST','/api/admin/scenario',{'scenario':'down'},token=self.admin_token)
        self.close(pid)
        self.error(409,'POST','/api/prop/accounts/'+aid+'/requests',{'kind':'reset'})
    def test_small_account_risk_equality_is_allowed_but_excess_is_recorded(self):
        aid=self.buy();self.opened(aid,6000)
        with transaction() as db:db.execute("UPDATE quotes SET price=10500 WHERE symbol='EURUSD'")
        self.assertNotIn('floating_risk',[x['kind'] for x in self.account(aid)['prop']['review_flags']])
        with transaction() as db:db.execute("UPDATE quotes SET price=10499 WHERE symbol='EURUSD'")
        self.assertIn('floating_risk',[x['kind'] for x in self.account(aid)['prop']['review_flags']])
    def test_stop_validation_and_update(self):
        aid=self.buy();self.error(400,'POST','/api/broker/accounts/'+aid+'/positions',{'symbol':'EURUSD','side':'buy','quantity':1,'stop_loss':'1.2'})
        pid=self.opened(aid)
        self.call('POST','/api/broker/positions/'+pid+'/protection',{'stop_loss':'1.09','take_profit':'1.2'})
        with transaction() as db:self.assertEqual(db.execute('SELECT stop_price FROM trade_meta WHERE position_id=?',(pid,)).fetchone()[0],10900)
        self.error(404,'POST','/api/broker/positions/'+pid+'/protection',{'stop_loss':'1.08'},token=self.admin_token)

if __name__=='__main__':unittest.main()
