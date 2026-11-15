/* AKO-FX workspace: menus and visual slots. Financial actions use original controls. */
'use strict';
window.AkoWorkspace=class {
 constructor(hooks){
  this.hooks=hooks;this.owner=null;this.revision=0;this.layout={items:{},slots:[],saved:[]};this.registry=new Map();this.history=[];this.busy=false;this.origin=null;this.longPress=null;
  this.menu=document.createElement('div');this.menu.id='workspace-menu';this.menu.className='workspace-menu';this.menu.setAttribute('role','menu');this.menu.setAttribute('aria-label','منوی اسلات');this.menu.hidden=true;document.body.append(this.menu);
  this.dialog=document.createElement('dialog');this.dialog.id='workspace-dialog';this.dialog.className='workspace-dialog';document.body.append(this.dialog);
  document.addEventListener('contextmenu',e=>{if(!this.active()||e.target.closest('input,textarea,select,[contenteditable],a'))return;e.preventDefault();this.open(e.clientX,e.clientY,e.target.closest('[data-slot-key]'));});
  document.addEventListener('keydown',e=>{if(!this.active())return;if(e.key==='Escape'){if(!this.menu.hidden){e.preventDefault();this.close(true);}return;}if(e.key==='ContextMenu'||e.shiftKey&&e.key==='F10'){if(e.target.closest('input,textarea,select,[contenteditable]'))return;e.preventDefault();const el=e.target.closest('[data-slot-key]');const r=(el||document.getElementById('workspace-tools')).getBoundingClientRect();this.open(r.left,r.top+24,el);}});
  this.menu.addEventListener('keydown',e=>{const items=[...this.menu.querySelectorAll('[role=menuitem]:not(:disabled)')];let i=items.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End','Tab'].includes(e.key)){e.preventDefault();if(e.key==='Tab'){this.close(true);return;}i=e.key==='Home'?0:e.key==='End'?items.length-1:(i+(e.key==='ArrowUp'?-1:1)+items.length)%items.length;items[i]?.focus();}});
  document.addEventListener('pointerdown',e=>{if(!this.menu.contains(e.target))this.close();if(e.pointerType==='touch'&&this.active()&&!e.target.closest('input,textarea,select,button,a')){const x=e.clientX,y=e.clientY;this.longPress={x,y,timer:setTimeout(()=>{this.open(x,y,e.target.closest('[data-slot-key]'));this.longPress=null;},650)};}});
  document.addEventListener('pointermove',e=>{if(this.longPress&&Math.hypot(e.clientX-this.longPress.x,e.clientY-this.longPress.y)>12)this.cancelPress();});
  document.addEventListener('pointerup',()=>this.cancelPress());document.addEventListener('pointercancel',()=>this.cancelPress());
  window.addEventListener('resize',()=>this.close());window.addEventListener('scroll',e=>{if(!this.menu.contains(e.target)&&!this.dialog.contains(e.target))this.close();},true);
  this.dialog.addEventListener('close',()=>this.focusOrigin());
 }
 active(){return !!this.owner&&!document.getElementById('dashboard').hidden;}
 cancelPress(){if(this.longPress)clearTimeout(this.longPress.timer);this.longPress=null;}
 async load(user,force=false){if(this.owner===user.id&&!force)return;this.clear();const response=await this.hooks.api('/api/dashboard/layout');this.owner=user.id;this.revision=response.revision;this.layout=response.layout;this.user=user;}
 clear(){this.close();if(this.dialog.open)this.dialog.close();this.dialog.replaceChildren();this.menu.replaceChildren();this.owner=null;this.user=null;this.origin=null;this.originKey=null;this.registry.clear();this.history=[];this.layout={items:{},slots:[],saved:[]};this.revision=0;document.getElementById('custom-slots')?.replaceChildren();}
 focusOrigin(){if(!this.owner)return;const current=this.origin?.isConnected?this.origin:this.registry.get(this.originKey)?.el?.querySelector(':scope > .slot-chrome .slot-menu-trigger')||document.querySelector('#workspace-tools button');current?.focus();}
 close(focus=false){this.menu.hidden=true;for(const b of document.querySelectorAll('.slot-menu-trigger'))b.setAttribute('aria-expanded','false');if(focus)this.focusOrigin();}
 style(key){return this.layout.items[key]||{};}
 async change(fn,{force=false}={}){
  if(this.busy)throw Error('ذخیره چیدمان در حال انجام است.');
  this.busy=true;const before=structuredClone(this.layout),next=structuredClone(this.layout);
  try{fn(next);const saved=await this.hooks.api('/api/dashboard/layout',{revision:this.revision,layout:next});this.history.push(before);if(this.history.length>10)this.history.shift();this.layout=saved.layout;this.revision=saved.revision;this.render();}
  catch(error){if(error.message.includes('another tab')){const saved=await this.hooks.api('/api/dashboard/layout');this.layout=saved.layout;this.revision=saved.revision;this.render();throw Error('چیدمان در تب دیگری تغییر کرده بود. آخرین نسخه دریافت شد؛ تغییر را دوباره انجام دهید.');}throw error;}
  finally{this.busy=false;}
 }
 update(key,patch){if(this.style(key).locked&&patch.locked!==false)throw Error('ابتدا قفل چیدمان اسلات را باز کنید.');return this.change(layout=>{layout.items[key]={...(layout.items[key]||{}),...patch};});}
 async undo(){if(!this.history.length)return;const previous=this.history.at(-1);await this.change(l=>{Object.assign(l,structuredClone(previous));});this.history.splice(-2);}
 run(fn){this.close();return this.hooks.action(fn);}
 element(tag,text,cls){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;}
 button(text,fn){const b=this.element('button',text);b.type='button';b.onclick=fn;return b;}
 modal(title,build){this.close();if(this.dialog.open)this.dialog.close();this.dialog.replaceChildren();this.dialog.append(this.element('h2',title));const form=document.createElement('form');this.dialog.append(form);build(form);const cancel=this.button('انصراف',()=>this.dialog.close());cancel.className='secondary';form.append(cancel);this.dialog.showModal();form.querySelector('input,textarea,select,button')?.focus();}
 input(form,label,value,{multiline=false,type='text',maxLength=100}={}){const l=this.element('label',label),i=document.createElement(multiline?'textarea':'input');if(!multiline)i.type=type;i.value=value||'';i.maxLength=maxLength;l.append(i);form.append(l);return i;}
 submit(form,text,fn){const b=this.element('button',text);b.type='submit';form.append(b);form.onsubmit=e=>{e.preventDefault();this.run(async()=>{try{await fn();this.dialog.close();}catch(error){let alert=form.querySelector('[role=alert]');if(!alert){alert=this.element('p',undefined,'error');alert.setAttribute('role','alert');form.append(alert);}alert.textContent=error.message;throw error;}});};}
 confirm(title,description,fn){this.modal(title,f=>{f.append(this.element('p',description));this.submit(f,'تأیید',fn);});}
 textDialog(title,label,value,save,multiline=false){this.modal(title,f=>{const input=this.input(f,label,value,{multiline,maxLength:multiline?2000:100});this.submit(f,'ذخیره',()=>save(input.value));});}
 copy(text){if(navigator.clipboard?.writeText)return navigator.clipboard.writeText(text);this.modal('متن قابل کپی',f=>{const input=this.input(f,'متن را انتخاب و کپی کنید',text,{multiline:true,maxLength:2000});input.readOnly=true;});}
 sourceEntry(key){const custom=this.layout.slots.find(s=>s.id===key);return this.registry.get(custom?.kind==='mirror'?custom.source:key);}
 actions(key){const entry=this.sourceEntry(key);if(!entry)return[];return [...entry.el.querySelectorAll('button')].filter(b=>!b.classList.contains('slot-menu-trigger')&&b.closest('[data-slot-key]')===entry.el).map(b=>({label:b.textContent.trim(),disabled:b.disabled,fn:()=>{this.reveal(entry.key);b.scrollIntoView({block:'center'});const form=b.closest('form');if(form){form.querySelector('input,select,textarea')?.focus();if(!form.reportValidity())return;}b.click();}}));}
 reveal(key){const entry=this.registry.get(key);if(!entry)return;entry.el.hidden=false;entry.el.classList.remove('slot-is-collapsed');entry.el.scrollIntoView({behavior:'smooth',block:'center'});entry.el.focus();}
 createNote(){this.textDialog('افزودن اسلات یادداشت','متن یادداشت','',text=>this.change(l=>{const id='slot-'+crypto.randomUUID().replaceAll('-','').slice(0,12);l.slots.push({id,kind:'note',text});l.items[id]={title:'یادداشت',color:'#53e0b0'};}),true);}
 duplicate(key){const slot=this.layout.slots.find(s=>s.id===key);const source=slot?.kind==='mirror'?slot.source:key;return this.change(l=>{const id='slot-'+crypto.randomUUID().replaceAll('-','').slice(0,12);l.slots.push(slot?.kind==='note'?{id,kind:'note',text:slot.text}:{id,kind:'mirror',source});l.items[id]={...this.style(key),title:(this.style(key).title||this.registry.get(key)?.title||'اسلات')+' · کپی',locked:false,hidden:false,collapsed:false};});}
 remove(key){const custom=this.layout.slots.find(s=>s.id===key);this.confirm('حذف اسلات از چیدمان',custom?.kind==='note'?'این یادداشت از چیدمان حذف می‌شود. برای بازگرداندن می‌توانید از واگردانی استفاده کنید.':'این عمل فقط نمایش اسلات را حذف می‌کند؛ حساب، معامله و دفترکل باقی می‌مانند.',()=>{if(this.style(key).locked)throw Error('ابتدا قفل چیدمان را باز کنید.');return this.change(l=>{if(custom){l.slots=l.slots.filter(s=>s.id!==key);delete l.items[key];}else l.items[key]={...(l.items[key]||{}),hidden:true};});});}
 move(key,direction){const el=this.registry.get(key)?.el;if(!el)return;const siblings=[...el.parentElement.children].filter(x=>x.dataset.slotKey);const index=siblings.indexOf(el),other=siblings[index+direction];if(!other||this.style(other.dataset.slotKey).locked)return;return this.change(l=>{const ordered=[...siblings];[ordered[index],ordered[index+direction]]=[ordered[index+direction],ordered[index]];ordered.forEach((node,i)=>{l.items[node.dataset.slotKey]={...(l.items[node.dataset.slotKey]||{}),order:i*10};});});}
 palette(key){const s=this.style(key);this.modal('رنگ‌بندی و اندازه اسلات',f=>{const color=this.input(f,'رنگ کادر',s.color||'#53e0b0',{type:'color'});const background=this.input(f,'رنگ زمینه',s.background||'#121d2c',{type:'color'});const foreground=this.input(f,'رنگ نوشته',s.foreground||'#edf3fa',{type:'color'});const font=this.input(f,'اندازه نوشته (۱۲ تا ۲۴)',String(s.font_size||15),{type:'number'});font.min='12';font.max='24';font.required=true;const size=document.createElement('select');[['normal','عادی'],['wide','تمام عرض'],['compact','فشرده']].forEach(([v,t])=>{const o=this.element('option',t);o.value=v;o.selected=v===(s.size||'normal');size.append(o);});f.append(this.element('label','اندازه اسلات'),size);this.submit(f,'ذخیره ظاهر',()=>this.update(key,{color:color.value,background:background.value,foreground:foreground.value,font_size:Number(font.value),size:size.value}));});}
 restore(){const hidden=Object.entries(this.layout.items).filter(([k,v])=>v.hidden);this.modal('بازیابی اسلات‌های حذف‌شده',f=>{if(!hidden.length)f.append(this.element('p','اسلات حذف‌شده‌ای وجود ندارد.'));hidden.forEach(([key])=>f.append(this.button(this.registry.get(key)?.title||key,()=>this.run(async()=>{await this.update(key,{hidden:false});this.dialog.close();}))));});}
 saveTemplate(){this.modal('ذخیره چیدمان',f=>{const name=this.input(f,'نام چیدمان','');name.required=true;name.maxLength=60;this.submit(f,'ذخیره چیدمان',()=>this.change(l=>{const title=name.value.trim();if(!title)throw Error('نام چیدمان لازم است.');const snapshot={items:structuredClone(l.items),slots:structuredClone(l.slots)};const existing=l.saved.find(s=>s.name===title);if(existing)existing.layout=snapshot;else l.saved.push({name:title,layout:snapshot});}));});}
 templates(){this.modal('چیدمان‌های ذخیره‌شده',f=>{if(!this.layout.saved.length)f.append(this.element('p','هنوز چیدمانی ذخیره نشده است.'));this.layout.saved.forEach(item=>{const row=this.element('div',undefined,'workspace-template-row');row.append(this.element('span',item.name),this.button('بارگذاری',()=>this.confirm('بارگذاری چیدمان',item.name+' جای چیدمان فعلی قرار می‌گیرد؛ واگردانی در همین ورود ممکن است.',()=>this.change(l=>{l.items=structuredClone(item.layout.items);l.slots=structuredClone(item.layout.slots);}))),this.button('حذف قالب',()=>this.run(async()=>{await this.change(l=>{l.saved=l.saved.filter(s=>s.name!==item.name);});this.dialog.close();})));f.append(row);});});}
 commands(key){const entry=this.sourceEntry(key);const path=entry?.el.dataset.apiPath||'/api/dashboard/layout';const command='python3 -m ako_fx.cli GET '+path;this.modal('مشاهده / Terminal',f=>{f.append(this.element('p','این دستور فقط اطلاعات مجاز همین کاربر را از API می‌خواند.'));const area=this.input(f,'دستور Terminal',command,{multiline:true,maxLength:2000});area.readOnly=true;f.append(this.button('کپی دستور',()=>this.run(()=>this.copy(command))));});}
 open(x,y,el){
  if(!this.active()||this.dialog.open||this.hooks.busy?.())return;this.close();this.originKey=el?.dataset.slotKey;this.origin=el?.querySelector(':scope > .slot-chrome .slot-menu-trigger')||document.activeElement;
  this.menu.replaceChildren();const key=el?.dataset.slotKey,entry=key?this.registry.get(key):null,s=key?this.style(key):{};
  const header=this.element('div',entry?(s.title||entry.title):'فضای کاری AKO-FX','workspace-menu-title');this.menu.append(header);
  const add=(label,fn,disabled=false,cls='')=>{const b=this.button(label,()=>{this.close();fn();});b.setAttribute('role','menuitem');b.disabled=disabled||this.busy;b.className=cls;this.menu.append(b);};
  const run=fn=>()=>this.run(fn);
  if(entry){
   const actions=this.actions(key);if(actions.length){this.menu.append(this.element('small','عملیات همین بخش'));actions.forEach(a=>add(a.label,a.fn,a.disabled));}
   const source=this.sourceEntry(key);if(source&&/^(account|position|funding|review):/.test(source.key))add('کپی شناسه مورد',run(()=>this.copy(source.key.split(':')[1])));
   this.menu.append(this.element('small','اسلات و چیدمان'));
   add(s.collapsed?'بازکردن اسلات':'جمع‌کردن اسلات',run(()=>this.update(key,{collapsed:!s.collapsed})),s.locked);
   add(s.pinned?'برداشتن Pin':'Pin در ابتدای گروه',run(()=>this.update(key,{pinned:!s.pinned})),s.locked);
   add(s.locked?'بازکردن قفل چیدمان':'قفل چیدمان',run(()=>this.update(key,{locked:!s.locked})));
   add('تغییر نام',()=>this.textDialog('تغییر نام اسلات','نام',s.title||entry.title,title=>this.update(key,{title})),s.locked);
   add('رنگ‌بندی و اندازه',()=>this.palette(key),s.locked);
   add('جابه‌جایی به بالا / قبل',run(()=>this.move(key,-1)),s.locked);
   add('جابه‌جایی به پایین / بعد',run(()=>this.move(key,1)),s.locked);
   add('Duplicate نمایشی',run(()=>this.duplicate(key)),s.locked);
   const custom=this.layout.slots.find(v=>v.id===key);if(custom?.kind==='note')add('ویرایش یادداشت',()=>this.textDialog('ویرایش یادداشت','متن',custom.text,text=>this.change(l=>{l.slots.find(v=>v.id===key).text=text;}),true),s.locked);
   add('کپی شناسه اسلات',run(()=>this.copy(key)));
   add('دستور Terminal / اطلاعات',()=>this.commands(key));
   add('بازنشانی ظاهر این اسلات',run(()=>this.change(l=>{delete l.items[key];})),s.locked);
   add('حذف اسلات از چیدمان',()=>this.remove(key),s.locked,'workspace-danger');
  }
  this.menu.append(this.element('small','فضای کاری'));
  add('به‌روزرسانی اطلاعات',()=>document.getElementById('refresh').click());
  add('رفتن به کیف پول',()=>this.reveal('wallet'));
  add('رفتن به حساب‌ها',()=>this.reveal('accounts-panel'));
  add('رفتن به پلن‌های Prop',()=>this.reveal('plans-panel'));
  add('نمایش قیمت‌های مصنوعی',()=>this.reveal('market-prices'));
  add('افزودن یادداشت',()=>this.createNote());
  add('افزودن اسلات از بخش‌ها',()=>this.modal('انتخاب بخش برای اسلات جدید',f=>{[...this.registry.values()].filter(v=>!v.key.startsWith('slot-')&&!v.key.startsWith('position:')&&!v.key.startsWith('funding:')&&!v.key.startsWith('review:')).forEach(v=>f.append(this.button(v.title,()=>this.run(async()=>{await this.duplicate(v.key);this.dialog.close();}))));}));
  add('بازیابی اسلات‌های حذف‌شده',()=>this.restore());add('ذخیره چیدمان',()=>this.saveTemplate());add('بارگذاری / حذف چیدمان',()=>this.templates());
  add('خروج از حساب',()=>document.getElementById('logout').click());
  add('واگردانی آخرین تغییر',run(()=>this.undo()),!this.history.length);
  add('بازخوانی چیدمان از سرور',run(async()=>{const data=await this.hooks.api('/api/dashboard/layout');this.layout=data.layout;this.revision=data.revision;this.render();}));
  add('بازنشانی ظاهر همه اسلات‌ها',()=>this.confirm('بازنشانی ظاهر','رنگ، اندازه و چیدمان اسلات‌ها بازنشانی می‌شوند؛ یادداشت‌ها و حساب‌ها باقی می‌مانند.',()=>this.change(l=>{l.items={};})));
  this.menu.hidden=false;this.menu.style.left='0px';this.menu.style.top='0px';const rect=this.menu.getBoundingClientRect();this.menu.style.left=Math.max(8,Math.min(x,innerWidth-rect.width-8))+'px';this.menu.style.top=Math.max(8,Math.min(y,innerHeight-rect.height-8))+'px';
  el?.querySelector(':scope > .slot-chrome .slot-menu-trigger')?.setAttribute('aria-expanded','true');this.menu.querySelector('[role=menuitem]:not(:disabled)')?.focus();
 }
 mount(el,index){
  const key=el.dataset.slotKey;const oldBody=el.querySelector(':scope > .slot-body');let body=oldBody;
  const title=el.dataset.slotTitle||el.querySelector('h3')?.textContent||key;el.dataset.slotTitle=title;el.classList.add('workspace-slot');el.tabIndex=0;
  if(!body){body=this.element('div',undefined,'slot-body');while(el.firstChild)body.append(el.firstChild);el.append(body);}
  el.querySelector(':scope > .slot-chrome')?.remove();const chrome=this.element('div',undefined,'slot-chrome'),caption=this.element('span',this.style(key).title||title,'slot-caption'),menu=this.button('⋮',e=>{const r=e.currentTarget.getBoundingClientRect();this.open(r.left,r.bottom,el);});menu.className='slot-menu-trigger';menu.setAttribute('aria-label','منوی '+title);menu.setAttribute('aria-haspopup','menu');menu.setAttribute('aria-expanded','false');chrome.append(caption,menu);el.prepend(chrome);
  const s=this.style(key);el.hidden=!!s.hidden;el.classList.toggle('slot-is-collapsed',!!s.collapsed);el.classList.toggle('slot-is-pinned',!!s.pinned);el.classList.toggle('slot-is-locked',!!s.locked);el.dataset.slotSize=s.size||'normal';
  for(const [prop,value] of [['--slot-color',s.color||'#26374b'],['--slot-background',s.background||''],['--slot-foreground',s.foreground||''],['--slot-font',s.font_size?s.font_size+'px':'']]){if(value)el.style.setProperty(prop,value);else el.style.removeProperty(prop);}
  if(!el.dataset.slotBaseOrder)el.dataset.slotBaseOrder=String(index+1);this.registry.set(key,{key,el,title,base:Number(el.dataset.slotBaseOrder)});
 }
 render(){
  if(!this.active())return;this.close();this.registry.clear();const custom=document.getElementById('custom-slots');custom.replaceChildren();
  [...document.querySelectorAll('#dashboard [data-slot-key]')].filter(el=>!el.closest('#custom-slots')&&(this.user.role==='admin'||!el.closest('#admin'))).forEach((el,i)=>this.mount(el,i));
  this.layout.slots.forEach((slot,i)=>{
   const el=this.element('article',undefined,'card custom-slot');el.dataset.slotKey=slot.id;el.dataset.slotTitle=slot.kind==='note'?'یادداشت':'نمای '+(this.registry.get(slot.source)?.title||'بخش');
   if(slot.kind==='note')el.append(this.element('p',slot.text||'برای نوشتن، از منوی اسلات «ویرایش یادداشت» را انتخاب کنید.','slot-note'));
   else{const source=this.registry.get(slot.source);if(source){const preview=(source.el.querySelector(':scope > .slot-body')||source.el).cloneNode(true);preview.querySelectorAll('button,form,input,select,textarea,.slot-chrome').forEach(v=>v.remove());for(const v of [preview,...preview.querySelectorAll('*')])for(const a of ['id','data-slot-key','data-slot-title','data-native-slot','tabindex','style'])v.removeAttribute(a);preview.classList.add('slot-preview');el.append(preview,this.button('رفتن به بخش اصلی',()=>this.reveal(slot.source)));}else el.append(this.element('p','بخش اصلی در این حساب یا نقش در دسترس نیست.'));}
   custom.append(el);this.mount(el,1000+i);
  });
  const groups=new Map();for(const e of this.registry.values()){const p=e.el.parentElement;if(!groups.has(p))groups.set(p,[]);groups.get(p).push(e);}
  for(const [parent,entries] of groups){const ordered=[...entries].sort((a,b)=>Number(!!this.style(b.key).pinned)-Number(!!this.style(a.key).pinned)||(this.style(a.key).order??a.base)-(this.style(b.key).order??b.base));const markers=entries.map(e=>{const marker=document.createComment('slot');parent.replaceChild(marker,e.el);return marker;});markers.forEach((m,i)=>m.replaceWith(ordered[i].el));}
  const tools=document.getElementById('workspace-tools');tools.hidden=false;tools.replaceChildren(this.element('span','راست‌کلیک روی هر اسلات · Shift+F10 · منوی ⋮'),this.button('منوی فضای کاری',e=>{const r=e.currentTarget.getBoundingClientRect();this.open(r.left,r.bottom,null);}),this.button('+ یادداشت',()=>this.createNote()));
  const hidden=Object.values(this.layout.items).filter(v=>v.hidden).length;if(hidden)tools.append(this.button('بازیابی '+hidden+' اسلات حذف‌شده',()=>this.restore()));
 }
};
