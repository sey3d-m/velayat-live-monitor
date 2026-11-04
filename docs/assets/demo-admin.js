
/* Pasokhnama: browser-only drafts and GitHub-approved publishing. */
(function(){
'use strict';
const API='https://api.github.com/repos/sey3d-m/velayat-live-monitor/contents/docs/pasokhnama-presentation.json';
const PUB='pasokhnama-presentation.json';
const def={narration:'detailed',card_count:5,show_header:true,show_footer:true,show_badge:true,show_count:true,
show_answer:true,show_summary:true,show_name:true,show_city:true,show_program:true,show_expert:false,
show_timecode:true,show_missing_metadata:true,panel_width_px:530,panel_height_pct:96,position:'right',
vertical:'center',offset_x_px:12,offset_y_px:8,font_px:18,font_family:'Vazirmatn',card_gap_px:8,
panel_radius_px:20,panel_padding_px:11,title_limit:150,body_limit:265,accent_color:'#caa769',
background_color:'#091c34',text_color:'#ffffff',opacity_pct:96,density:'balanced',apply_live_visual:false};
const groups=[
 ['شیوه نگارش و جزئیات',[
  ['narration','نحوه نمایش مطلب','select',[['detailed','تفصیلی با سؤال و پاسخ'],['brief','کلی و خلاصه']]],
  ['card_count','تعداد باکس‌ها','number',1,12],
  ['title_limit','حداکثر حروف عنوان','number',20,2000],
  ['body_limit','حداکثر حروف پاسخ','number',30,4000],
  ['show_answer','نمایش پاسخ','check'],['show_summary','نمایش توضیحات علمی','check'],
  ['show_name','نمایش نام بیننده','check'],['show_city','نمایش شهر بیننده','check'],
  ['show_missing_metadata','نمایش «ثبت نشده» برای اطلاعات خالی','check'],
  ['show_program','نمایش عنوان برنامه در باکس','check'],
  ['show_expert','نمایش نام کارشناس','check'],['show_timecode','نمایش زمان‌کد','check']]],
 ['اندازه و جایگاه',[
  ['position','موقعیت افقی','select',[['right','راست'],['left','چپ'],['center','وسط']]],
  ['vertical','موقعیت عمودی','select',[['top','بالا'],['center','وسط'],['bottom','پایین']]],
  ['panel_width_px','عرض (پیکسل)','number',300,1600],
  ['panel_height_pct','ارتفاع (درصد)','number',20,100],
  ['offset_x_px','فاصله افقی از لبه','number',0,100],
  ['offset_y_px','فاصله عمودی از لبه','number',0,100],
  ['card_gap_px','فاصله بین باکس‌ها','number',0,28],
  ['panel_padding_px','حاشیه داخلی باکس‌ها','number',0,35],
  ['panel_radius_px','گردی گوشه‌ها','number',0,60],
  ['density','تراکم صفحه','select',[['compact','فشرده'],['balanced','معمولی'],['spacious','باز']]]]],
 ['تایپوگرافی و ظاهر',[
  ['font_px','اندازه عنوان کارت','number',11,36],
  ['font_family','نوع قلم','select',[['Vazirmatn','وزیرمتن'],['Tahoma','تاهوما'],['Arial','آریال']]],
  ['accent_color','رنگ تأکیدی','color'],['background_color','رنگ زمینه','color'],
  ['text_color','رنگ عنوان','color'],['opacity_pct','تیرگی زمینه (%)','number',30,100],
  ['show_header','نمایش سربرگ','check'],['show_footer','نمایش پاصفحه','check'],
  ['show_badge','نمایش وضعیت','check'],['show_count','نمایش تعداد مطالب','check']]],
 ['دامنه انتشار',[
  ['apply_live_visual','اعمال فقط ظاهر جدید روی نمایش زنده (نه محتوای دمو)','check']]]];
const $=id=>document.getElementById(id);
const editor=()=>window.PasokhnamaEditor;
const draft=()=>editor()?.getState?.()||null;
const settings=()=>Object.assign({},def,draft()?.settings||{});
const previewMode=new URLSearchParams(location.search).get('preview')==='1';
const controls=new Map();
let frame=null,reviewed=false,publishing=false,loaded=false,expectedRelease=null,started=false;
let reviewEl,buttonEl,tokenEl,statusEl;
function notify(msg,variant){
 if(!statusEl)return;
 statusEl.textContent=msg;
 statusEl.className='admin-status'+(variant?' '+variant:'');
}
function field(spec){
 const [key,label,type,a,b]=spec;
 const lab=document.createElement('label'),node=document.createElement(type==='select'?'select':'input');
 node.dataset.setting=key;
 lab.className=type==='check'?'admin-checkbox':'admin-field';
 if(type==='check'){
  node.type='checkbox';lab.append(node,document.createTextNode(label));
 }else{
  const cap=document.createElement('span');cap.textContent=label;lab.append(cap,node);
  if(type==='number'){node.type='number';node.min=a;node.max=b;node.step='1';}
  else if(type==='color')node.type='color';
  else for(const [val,desc]of a){const opt=document.createElement('option');opt.value=val;opt.textContent=desc;node.append(opt);}
 }
 if(key==='apply_live_visual')lab.classList.add('warning','full');
 controls.set(key,node);
 node.addEventListener(type==='check'||type==='select'?'change':'input',()=>{
  if(key==='apply_live_visual'&&node.checked&&!confirm('آیا فقط تغییر ظاهر نمای زنده را نیز تأیید می‌کنید؟ داده‌های زنده دست‌نخورده می‌مانند.')){node.checked=false;return;}
  const next=settings(),old=next[key];
  if(type==='check')next[key]=node.checked;
  else if(type==='number'){
   if(node.value==='')return;
   const n=Number(node.value);if(!Number.isFinite(n))return;
   next[key]=Math.min(Number(b),Math.max(Number(a),n));
  }else next[key]=node.value;
  if(next[key]!==old)editor().updateSettings(next);
 });
 return lab;
}
function buildControls(){
 const root=document.createElement('section');root.className='panel';root.id='advanced-controls';
 const head=document.createElement('div');head.className='panel-title';
 const title=document.createElement('h2');title.textContent='تنظیمات کامل ظاهر و نگارش';head.append(title);root.append(head);
 for(const [name,specs]of groups){
  const heading=document.createElement('div');heading.className='admin-section-title';heading.textContent=name;root.append(heading);
  const grid=document.createElement('div');grid.className='admin-grid';
  specs.forEach(spec=>grid.append(field(spec)));root.append(grid);
 }
 const note=document.createElement('div');note.className='admin-safe';
 note.textContent='تنظیمات محتوایی و باکس‌ها فقط برای لینک دمو اعمال می‌شود؛ حتی در حالت تنظیم ظاهری زنده، متن دمو وارد گزارش‌های تأییدشده نمی‌شود.';
 root.append(note);
 const parent=document.querySelector('.controls');parent.insertBefore(root,parent.children[1]);
}
function buildPublish(){
 const section=document.createElement('section');section.className='panel admin-publication';section.id='publisher';
 section.innerHTML='<div class="panel-title"><h2>تأیید و انتشار روی لینک اصلی</h2><span class="count" id="release-info">بارگیری نسخه منتشرشده...</span></div>'+
 '<p class="subtle">هر تغییری را ابتدا در پیش‌نمایش واقعی بررسی کنید. انتشار با مجوز گیت‌هاب، تنها فایل ارائه را به‌روزرسانی می‌کند.</p>'+
 '<label class="admin-checkbox full" style="margin-top:12px"><input type="checkbox" id="review-confirm"> پیش‌نمایش را کنترل کردم و انتشار این نسخه را تأیید می‌کنم.</label>'+
 '<label class="field"><span>توکن محدود GitHub (فقط در حافظه موقت)</span><input type="password" autocomplete="off" spellcheck="false" id="gh-token" placeholder="github_pat_..."></label>'+
 '<p class="subtle">یک <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener noreferrer" style="color:#146b96;text-decoration:underline">توکن Fine-grained</a> فقط برای مخزن <b>sey3d-m/velayat-live-monitor</b> با دسترسی <b>Contents: Read and write</b> ایجاد کنید. توکن را در گفتگو ارسال نکنید؛ در مرورگر ذخیره نخواهد شد.</p>'+
 '<div class="publish-actions"><button type="button" class="btn primary" id="publish-approved" disabled>انتشار نسخه تأییدشده</button><button type="button" class="btn" id="load-approved">بارگیری نسخه منتشرشده</button></div>'+
 '<div class="admin-status" id="publish-status" role="status">نسخه اصلی تا تأیید و انتشار تغییر نمی‌کند.</div>'+
 '<div class="admin-banner">آدرس دمو: <a href="overlay.html?demo=1" target="_blank" rel="noopener">overlay.html?demo=1</a> · آدرس زنده: <a href="overlay.html" target="_blank" rel="noopener">overlay.html</a></div>';
 document.querySelector('.controls').insertBefore(section,$('feedback'));
 reviewEl=$('review-confirm');buttonEl=$('publish-approved');tokenEl=$('gh-token');statusEl=$('publish-status');
 reviewEl.onchange=()=>{reviewed=reviewEl.checked;buttonEl.disabled=!reviewed||publishing;};
 buttonEl.onclick=publish;
 $('load-approved').onclick=async()=>{
  if(!confirm('پیش‌نویس محلی با نسخه منتشرشده جایگزین شود؟'))return;
  try{
   const raw=await loadPublished();
   editor().replaceState(raw);sync();
   notify('نسخه منتشرشده به محیط ویرایش بازگردانده شد.','success');
  }catch(e){notify('بازیابی ناموفق بود: '+e.message,'error');}
 };
}
function sync(){
 const s=settings();
 for(const [key,node]of controls){
  if(document.activeElement===node)continue;
  if(node.type==='checkbox')node.checked=Boolean(s[key]);
  else node.value=s[key]??'';
 }
}
function previewSend(){
 if(frame?.contentWindow&&draft())
  frame.contentWindow.postMessage({type:'PASOKHNAMA_EDITOR_DRAFT',presentation:draft()},location.origin);
}
function installFrame(){
 const zone=document.querySelector('.preview-zone');frame=document.createElement('iframe');
 frame.className='admin-preview-frame';frame.title='پیش‌نمایش دقیق پاسخ‌نما';
 frame.src='overlay.html?demo=1&editor_preview=1';
 zone.replaceChildren(frame);frame.addEventListener('load',previewSend);
 window.addEventListener('message',event=>{
  if(event.origin===location.origin&&event.source===frame.contentWindow&&event.data?.type==='PASOKHNAMA_PREVIEW_READY')previewSend();
 });
}
async function loadPublished(){
 const res=await fetch(PUB+'?_='+Date.now(),{cache:'no-store'});
 if(!res.ok)throw Error('HTTP '+res.status);
 const value=await res.json();if(!Array.isArray(value.cards)||!value.header)throw Error('فایل نامعتبر است.');
 expectedRelease=String(value.release_id||'');loaded=true;
 if($('release-info'))$('release-info').textContent='انتشار: '+expectedRelease;
 return value;
}
function encodeUnicode(text){
 const bytes=new TextEncoder().encode(text);let binary='';
 for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
 return btoa(binary);
}
function decodeUnicode(text){
 const chars=atob(String(text).replace(/\s/g,''));
 return new TextDecoder().decode(Uint8Array.from(chars,c=>c.charCodeAt(0)));
}
async function gitRequest(method,token,body){
 const res=await fetch(API,{
  method,cache:'no-store',
  headers:{Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','Authorization':'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},
  ...(body?{body:JSON.stringify(body)}:{})
 });
 const value=await res.json().catch(()=>null);
 if(!res.ok)throw Error((value?.message||'GitHub HTTP '+res.status)+' ('+res.status+')');
 return value;
}
async function verifyPublished(id){
 for(let i=0;i<22;i++){
  await new Promise(resolve=>setTimeout(resolve,3500));
  try{
   const response=await fetch(PUB+'?_='+Date.now(),{cache:'no-store'});
   if(response.ok&&(await response.json()).release_id===id)return true;
  }catch(_){}
 }
 return false;
}
async function publish(){
 if(publishing||!reviewed)return;
 const token=tokenEl.value.trim(),current=draft();
 if(!token){notify('توکن محدود GitHub را وارد کنید؛ این توکن جایی ذخیره نمی‌شود.','error');return;}
 if(!current?.header||!Array.isArray(current.cards)||!current.cards.length||current.cards.length>30){
  notify('باید بین یک تا سی باکس معتبر در پیش‌نویس موجود باشد.','error');return;
 }
 const s=settings();
 if(s.apply_live_visual&& !confirm('تغییر چیدمان نمای زنده را نیز انتخاب کرده‌اید. ادامه می‌دهید؟'))return;
 if(!confirm('پیش‌نمایش تأییدشده روی آدرس اصلی پاسخ‌نما منتشر شود؟'))return;
 publishing=true;buttonEl.disabled=true;notify('در حال احراز دسترسی و بررسی نسخه جاری گیت‌هاب ...');
 try{
  if(!loaded)await loadPublished();
  const remote=await gitRequest('GET',token);
  if(!remote.sha||!remote.content)throw Error('اطلاعات فایل از گیت‌هاب دریافت نشد.');
  const remoteData=JSON.parse(decodeUnicode(remote.content));
  if(String(remoteData.release_id||'')!==expectedRelease)
   throw Error('نسخه جدیدتری در گیت‌هاب ثبت شده است. ابتدا آخرین نسخه را بارگیری کنید.');
  const id='release-'+new Date().toISOString().replace(/[-:.TZ]/g,'');
  const publication={schema_version:2,release_id:id,published_at:new Date().toISOString(),edited:true,
   header:current.header,settings:s,cards:current.cards.slice(0,30)};
  const content=JSON.stringify(publication,null,2)+'\n';
  if(content.length>150000)throw Error('حجم نسخه از حد مجاز بیشتر است.');
  const result=await gitRequest('PUT',token,{branch:'main',message:'Publish reviewed Pasokhnama presentation '+id,sha:remote.sha,content:encodeUnicode(content)});
  if(!result?.commit?.sha)throw Error('تأیید ثبت گیت‌هاب دریافت نشد.');
  expectedRelease=id;loaded=true;tokenEl.value='';
  if($('release-info'))$('release-info').textContent='انتشار: '+id;
  notify('در گیت‌هاب ثبت شد. در حال بررسی استقرار سایت...');
  const deployed=await verifyPublished(id);
  notify(deployed?'نسخه جدید روی لینک اصلی دمو منتشر شده است.':'نسخه در GitHub ثبت شد، اما انتشار عمومی هنوز تأیید نشده است. وضعیت Actions را بررسی کنید.',deployed?'success':'');
 }catch(error){notify('انتشار کامل نشد: '+error.message+'. نسخه پیش‌نویس محفوظ است.','error');}
 finally{publishing=false;reviewed=false;reviewEl.checked=false;buttonEl.disabled=true;}
}
function start(){
 if(started||!editor()?.isReady?.())return;started=true;
 installFrame();
 if(!previewMode){
  buildControls();buildPublish();sync();
  loadPublished().catch(e=>notify('خواندن نسخه منتشرشده ناموفق بود: '+e.message,'error'));
  window.addEventListener('pasokhnama:change',()=>{
   sync();reviewed=false;reviewEl.checked=false;buttonEl.disabled=true;previewSend();
  });
  $('full').onclick=()=>window.open('demo-editor.html?preview=1','_blank','noopener');
  $('json-file').addEventListener('change',()=>setTimeout(sync,120));
  $('reset').addEventListener('click',()=>setTimeout(sync,350));
 }else window.addEventListener('pasokhnama:change',previewSend);
 previewSend();
}
window.addEventListener('pasokhnama:ready',start);
if(editor()?.isReady?.())start();
})();
