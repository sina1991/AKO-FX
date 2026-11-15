"""Versioned facts from official class rules. Values are DEMO ONLY.

Business facts are paraphrased; no legal terms or branding are reproduced.
Account snapshots never change when the source site or catalogue changes.
"""
import copy

VERSION='sgb-reference-2026-11-15-v1'
SOURCES={
    'A':'https://sarmayegozarebartar.com/rulesca/',
    'B':'https://sarmayegozarebartar.com/rulescb/',
    'general':'https://sarmayegozarebartar.com/select-the-rules/',
    'prices_A':'https://sarmayegozarebartar.com/plan-a/',
    'prices_B':'https://sarmayegozarebartar.com/plan-b/',
}
SIZES=(1000,2500,5000,10000,25000,50000,100000,200000)
FEES={'A':(15,30,55,88,157,314),'B':(17,35,60,98,174,329,522,999)}

def catalogue():
    result=[]
    for cls in ('A','B'):
        for capital,fee in zip(SIZES,FEES[cls]):
            result.append({'id':f'{cls.lower()}-{capital}','name':f'AKO Demo {cls} · ${capital:,}',
                'class':cls,'capital_cents':capital*100,'fee_cents':fee*100,
                'rules_version':VERSION,'stage_targets_bps':[800,400] if cls=='A' else [1000,500],
                'min_trading_days':5 if cls=='A' else 3,
                'stage_days':[30,60] if cls=='A' else [None,None],
                'daily_loss_bps':500,'total_loss_bps':1200,
                'floating_risk_bps':200 if capital>=100000 else 300,
                'max_active_accounts':2,'max_initial_allocation_cents':25000000,
                'first_payout_days':21,'first_payout_trading_days':7 if cls=='A' else 10,
                'payout_tiers_bps':[8000,8500] if cls=='A' else [7500,8000,9000],
                'refund_pass_bps':2000,'refund_first_payout_bps':10000,'refund_request_days':45,
                'growth_bps':4000,'growth_months':3,'growth_profit_bps':800,
                'growth_cap_cents':(1000000 if cls=='A' else 2000000)*100,
                'inactivity_days':30,'tick_seconds':30,'tick_profit_limit_bps':2000,
                'forex_leverage':100,'leverage_by_asset':{'forex':100,'metals':100,'crypto':10,'oil':20,'dow':50,'other_indices':100},'news_trading':True,'overnight_holding':True,
                'weekend_orders':False,'source_urls':SOURCES})
    return copy.deepcopy(result)

PLANS=catalogue()
LEGACY_PLANS=[{'id':'starter','name':'Legacy Demo Starter','fee_cents':10000,'capital_cents':1000000},
              {'id':'advanced','name':'Legacy Demo Advanced','fee_cents':25000,'capital_cents':2500000}]
MANUAL_CHECKS=('identity','ownership','no_external_copying','no_automated_trading','no_trading_vps','market_integrity')
CONFLICTS=[
    {'id':'A-extension-reset','handling':'manual_acknowledgement',
     'detail':'The A page both permits reset after extension and states loss of account after an unsuccessful extension.'},
    {'id':'growth-class-priority','handling':'class_specific_rules',
     'detail':'Use A cap 1m and B cap 2m from class-specific pages, rather than the generic homepage cap.'},
    {'id':'broker-timezone','handling':'explicit_snapshot',
     'detail':'AKO default UTC inferred from Tehran offset examples; admin may set an IANA timezone for future purchases.'},
    {'id':'target-before-minimum-days','handling':'minimum_volume_until_days_met',
     'detail':'Permit additional days until minimum days, following the explicit minimum-volume exception.'},
    {'id':'boundary-equality','handling':'drawdown_touch_is_breach',
     'detail':'Drawdown equality breaches; floating risk and tick-profit limits breach only when strictly exceeded.'},
    {'id':'merge-history','handling':'manual_review_conservative_history',
     'detail':'Merged accounts retain the lower payout count and later eligibility dates; the source does not specify this detail.'},
]
