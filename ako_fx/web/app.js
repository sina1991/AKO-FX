'use strict';
let token='',user=null,availableSymbols=['EURUSD','GBPUSD','USDJPY'];
const $=id=>document.getElementById(id);
const amount=c=>(c/100).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function message(text,error=false){$('message').textContent=text;$('message').className=error?'error':'';}
async function api(path,data){const opts={headers:{'Content-Type':'application/json','Authorization':'Bearer '+token}};if(data!==undefined){opts.method='POST';opts.body=JSON.stringify(data);opts.headers['Idempotency-Key']=crypto.randomUUID();}let r;try{r=await fetch(path,opts);}catch(e){throw Error('ارتباط قطع شد. پیش از تکرار، وضعیت حساب را به‌روزرسانی کنید.');}const body=await r.json();if(!r.ok)throw Error(body.error||'خطای درخواست');return body;}
async function action(fn){document.querySelectorAll('button').forEach(b=>b.disabled=true);try{await fn();message('عملیات انجام شد.');}catch(e){message(e.message,true);}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false);}}
function button(text,fn){const b=node('button',text);b.type='button';b.onclick=()=>action(fn);return b;}
function field(form,name,label,type='text',value='',required=true){const l=node('label',label),i=document.createElement('input');i.name=name;i.type=type;i.required=required;i.value=value;if(type==='number'){i.min='0.0001';i.step='.0001';}l.append(i);form.append(l);return i;}
function select(form,name,items){const s=document.createElement('select');s.name=name;items.forEach(([v,t])=>{const o=node('option',t);o.value=v;s.append(o);});form.append(s);return s;}
function rows(id,items,render){$(id).replaceChildren();if(!items.length)$(id).append(node('p','هنوز موردی ثبت نشده است.','muted'));items.forEach(x=>{const r=node('div',undefined,'row');render(r,x);$(id).append(r);});}
$('authform').onsubmit=e=>{e.preventDefault();const f=new FormData(e.target),kind=e.submitter.value;action(async()=>{const payload={email:f.get('email'),password:f.get('password')};if(kind==='register')await api('/api/auth/register',payload);const r=await api('/api/auth/login',payload);token=r.token;user=r.user;e.target.reset();await refresh();});};
$('logout').onclick=()=>action(async()=>{await api('/api/auth/logout',{});token='';user=null;$('auth').hidden=false;$('dashboard').hidden=true;$('logout').hidden=true;});
$('refresh').onclick=()=>action(refresh);
$('fundingform').onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/wallet/requests',{amount:e.target.amount.value});e.target.reset();await refresh();});};
$('newaccount').onclick=()=>action(async()=>{await api('/api/broker/accounts',{});await refresh();});
const requestLabels={transition:'درخواست مرحله بعد',payout:'درخواست برداشت دمو',refund20:'درخواست ریفاند ۲۰٪',extend:'درخواست تمدید',reset:'درخواست ریست',growth:'درخواست رشد',merge:'درخواست ادغام'};
function renderAccount(a,all){
 const c=node('article',undefined,'card');
 c.append(node('h3',(a.kind==='prop'?'30nA-Prop':'30nA-Broker')+' · '+a.status),node('small',a.id),node('p','آزاد: '+amount(a.balance_cents)+' · رزرو: '+amount(a.reserved_cents)+' · Equity: '+amount(a.equity_cents)));
 if(a.kind==='broker'){
  const f=document.createElement('form');field(f,'amount','مبلغ انتقال','number');select(f,'direction',[['deposit','از کیف پول به Broker'],['withdraw','از Broker به کیف پول']]);f.append(node('button','انتقال اعتبار'));
  f.onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/broker/accounts/'+a.id+'/transfers',{amount:f.amount.value,direction:f.direction.value});await refresh();});};c.append(f);
 }else{
  const p=a.prop;
  if(p.legacy)c.append(node('p','حساب قدیمی؛ قوانین نسخه پیشین حفظ شده است.'));
  else{
   c.append(node('p','کلاس '+p.class+' · مرحله '+(p.stage===3?'حساب فاند دمو':p.stage)+' · روز معاملاتی '+p.trading_days+'/'+p.min_trading_days),
    node('p','هدف: '+(p.target_bps===null?'بدون هدف مرحله‌ای':p.target_bps/100+'٪')+' · کف روزانه: '+amount(p.daily_floor_cents)+' · کف کلی: '+amount(p.total_floor_cents)),node('small',p.rules_version+' · '+p.broker_timezone));
   if(p.deadline)c.append(node('p','پایان مهلت: '+new Date(p.deadline*1000).toLocaleString('fa-IR')));
   if(p.breach_reason)c.append(node('p','علت توقف: '+p.breach_reason,'error'));
   if(p.review_flags.length)c.append(node('p','موارد نیازمند بررسی: '+p.review_flags.map(x=>x.kind).join('، '),'error'));
   if(!['failed','expired','closed'].includes(a.status)){
    (p.stage===3?['payout',...(p.refund20_completed?[]:['refund20']),'growth','reset']:['transition',...(p.class==='A'?['extend']:[]),'reset']).forEach(kind=>c.append(button(requestLabels[kind],async()=>{await api('/api/prop/accounts/'+a.id+'/requests',{kind});await refresh();})));
    const candidates=all.filter(x=>x.id!==a.id&&x.prop&&!x.prop.legacy&&x.prop.stage===3&&x.prop.class===p.class&&x.status==='active');
    if(p.stage===3&&candidates.length){const f=document.createElement('form');select(f,'other',candidates.map(x=>[x.id,x.id]));f.append(node('button','درخواست ادغام'));f.onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/prop/accounts/'+a.id+'/requests',{kind:'merge',other_account_id:f.other.value});await refresh();});};c.append(f);}
   }
   p.requests.forEach(r=>c.append(node('p',(requestLabels[r.kind]||r.kind)+' · '+r.status+(r.reason?' · '+r.reason:''),'muted')));
  }
  c.append(button('بررسی وضعیت ارزیابی',async()=>{await api('/api/prop/accounts/'+a.id+'/evaluate',{});await refresh();}));
 }
 if(a.status==='active'){
  const f=document.createElement('form');select(f,'symbol',availableSymbols.map(s=>[s,s]));select(f,'side',[['buy','buy'],['sell','sell']]);
  const q=field(f,'quantity',a.prop&&!a.prop.legacy?'تعداد واحد · اهرم طبق گروه نماد':'تعداد واحد (بدون اهرم)','number','1');q.min='1';q.step='1';q.max=a.prop&&!a.prop.legacy?'1000000000':'100000';
  field(f,'stop_loss','Stop Loss اختیاری','number','',false);field(f,'take_profit','Take Profit اختیاری','number','',false);
  f.append(node('button','باز کردن معامله دمو'));f.onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/broker/accounts/'+a.id+'/positions',{symbol:f.symbol.value,side:f.side.value,quantity:Number(f.quantity.value),stop_loss:f.stop_loss.value||null,take_profit:f.take_profit.value||null});await refresh();});};c.append(f);
 }
 a.positions.forEach(p=>{const r=node('div',undefined,'row');r.append(node('span',p.symbol+' · '+p.side+' · '+p.quantity+' · '+p.status+' · PnL: '+amount(p.status==='open'?p.unrealized_pnl_cents:p.pnl)));if(p.status==='open'){
  r.append(button('بستن',async()=>{await api('/api/broker/positions/'+p.id+'/close',{});await refresh();}));
  const f=document.createElement('form');field(f,'stop_loss','Stop Loss جدید','number','',false);field(f,'take_profit','Take Profit جدید','number','',false);f.append(node('button','ثبت SL/TP'));f.onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/broker/positions/'+p.id+'/protection',{stop_loss:f.stop_loss.value||null,take_profit:f.take_profit.value||null});await refresh();});};r.append(f);
 }c.append(r);});return c;
}
async function refresh(){
 user=await api('/api/me');const [wallet,accounts,plans,quotes]=await Promise.all([api('/api/wallet'),api('/api/accounts'),api('/api/prop/plans'),api('/api/broker/quotes')]);availableSymbols=Object.keys(quotes.prices);
 $('auth').hidden=true;$('dashboard').hidden=false;$('logout').hidden=false;$('identity').textContent=user.email+' · '+user.role;$('balance').textContent=amount(wallet.balance_cents);
 rows('requests',wallet.requests,(r,x)=>r.append(node('span',amount(x.amount)+' · '+x.status)));rows('ledger',wallet.ledger,(r,x)=>r.append(node('span',amount(x.delta)+' · '+x.kind)));
 $('plans').replaceChildren();plans.plans.forEach(p=>{const c=node('article',undefined,'card');c.append(node('h3',p.name),node('p','سرمایه آزمایشی: '+amount(p.capital_cents)),node('p','هزینه: '+amount(p.fee_cents)+' DEMO-USD'),node('p','هدف مراحل: '+p.stage_targets_bps.map(x=>x/100+'٪').join(' / ')+' · حداقل '+p.min_trading_days+' روز در هر مرحله'),node('p','Drawdown روزانه ۵٪ · کلی ۱۲٪ · ریسک شناور '+p.floating_risk_bps/100+'٪'),node('p',p.class==='A'?'مهلت: ۳۰ و ۶۰ روز از اولین معامله':'مهلت چالش: نامحدود'),button('خرید با اعتبار آزمایشی',async()=>{await api('/api/prop/purchases',{plan_id:p.id});await refresh();}));$('plans').append(c);});
 $('accounts').replaceChildren();accounts.accounts.forEach(a=>$('accounts').append(renderAccount(a,accounts.accounts)));
 $('admin').hidden=user.role!=='admin';if(user.role==='admin'){
  const [funding,audit,reviews,allProp]=await Promise.all([api('/api/admin/funding'),api('/api/admin/audit'),api('/api/admin/prop/requests'),api('/api/admin/prop/accounts')]);
  rows('allpropaccounts',allProp.accounts,(r,x)=>r.append(node('p',x.email+' · '+x.id+' · '+x.status)));
  rows('adminrequests',funding.requests,(r,x)=>{r.append(node('p',x.email+' · '+amount(x.amount)+' · '+x.status));if(x.status==='pending')['approved','rejected'].forEach(s=>r.append(button(s==='approved'?'تأیید':'رد',async()=>{await api('/api/admin/funding/'+x.id,{status:s});await refresh();})));});
  rows('audit',audit.events,(r,x)=>r.append(node('small',new Date(x.created*1000).toLocaleString('fa-IR')+' · '+x.action+' · '+x.actor)));
  rows('propreviews',reviews.requests,(r,x)=>{
   r.append(node('h3',x.email+' · '+(requestLabels[x.kind]||x.kind)+' · '+x.status),node('small',x.account_id));
   if(x.account.review_flags.length)r.append(node('p','پرچم‌ها: '+x.account.review_flags.map(v=>v.kind).join('، '),'error'));
   if(x.status!=='pending'){r.append(node('p',x.reason||''));return;}
   const f=document.createElement('form');field(f,'reason','دلیل تصمیم و شواهد بررسی');const checks={};
   const checkNames={identity:'تأیید هویت دمو و شرط ۱۸ سال',ownership:'مالکیت و نبود هویت مشترک',no_external_copying:'رعایت محدودیت کپی ترید و اشتراک',no_automated_trading:'نبود ربات معامله‌گر',no_trading_vps:'نبود اجرای معامله از VPS کاربر',market_integrity:'بررسی سوءاستفاده بازار و HFT'};
   reviews.required_checks.forEach(k=>{const l=node('label',checkNames[k]||k),input=document.createElement('input');input.type='checkbox';l.prepend(input);checks[k]=input;f.append(l);});
   const sl=document.createElement('input');sl.type='checkbox';const slLabel=node('label','تأیید مستند استثنای اسلیپیج (فقط با شواهد Stop)');slLabel.prepend(sl);f.append(slLabel);
   const ack=document.createElement('input');ack.type='checkbox';const ackLabel=node('label','تأیید آگاهانه تعارض منبع برای ریست A پس از تمدید');ackLabel.prepend(ack);f.append(ackLabel);
   select(f,'decision',[['approve','تأیید'],['reject','رد درخواست'],['reset','ریست به علت نقض قابل ریست'],['fail','رد و پایان حساب']]);f.append(node('button','ثبت تصمیم'));
   f.onsubmit=e=>{e.preventDefault();action(async()=>{const values={};Object.entries(checks).forEach(([k,v])=>values[k]=v.checked);await api('/api/admin/prop/requests/'+x.id,{decision:f.decision.value,reason:f.reason.value,checks:values,slippage_exempt:sl.checked,source_conflict_ack:ack.checked});await refresh();});};r.append(f);
  });
 }
}
['up','down','reset'].forEach(s=>$('scenario-'+s).onclick=()=>action(async()=>{const r=await api('/api/admin/scenario',{scenario:s});$('quotes').textContent=Object.entries(r.prices).map(([k,v])=>k+': '+v/r.price_scale).join(' | ');await refresh();}));
$('propzoneform').onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/admin/prop/settings',{broker_timezone:e.target.zone.value});await refresh();});};

$('propflagform').onsubmit=e=>{e.preventDefault();action(async()=>{await api('/api/admin/prop/accounts/'+e.target.account.value+'/flag',{reason:e.target.reason.value,action:e.target.operation.value});await refresh();});};
