/* Pasokhnama V4 — static frontend; reads ONLY sanitized JSON, no API secrets. */
(() => {
'use strict';
const $=id=>document.getElementById(id), page=document.body.dataset.page;
const params=new URL(location.href).searchParams;
const demo=params.get('demo')==='1'||location.protocol==='file:';
const defaultConfig={refresh_seconds:90,tv_card_count:5,tv_max_chars:150,tv_position:'right',tv_width_px:560,tv_font_px:19,brand_color:'#c9ad74',logo_url:'',stale_minutes:120,question_priority:1.2,show_timecode:true,show_audience:false,enable_questions:true,enable_expert_content:true};
const labels={question_answer:'پرسش و پاسخ',audience_question:'پرسش مخاطب',expert_point:'نکته علمی',expert_topic:'محور بحث کارشناس',expert_reference:'مستندات بحث',expert_summary:'جمع‌بندی کارشناس'};
const icons={question_answer:'؟',audience_question:'؟',expert_point:'✦',expert_topic:'▤',expert_reference:'◈',expert_summary:'◎'};
const fa=v=>String(v??'').replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[d]);
const norm=v=>String(v??'').replace(/[يى]/g,'ی').replace(/ك/g,'ک').replace(/[\u064B-\u065F]/g,'').toLowerCase().trim();
const clip=(s,n)=>{let v=String(s??'');return v.length>n?v.slice(0,n).trim()+'…':v};
const secs=t=>t===null||t===undefined?'':fa(`${String(Math.floor(Number(t)/60)).padStart(2,'0')}:${String(Math.floor(Number(t)%60)).padStart(2,'0')}`);
const dateText=iso=>iso?fa(iso.replace(/-/g,'/')):'—';
const prettyDate=date=>{if(!date)return 'ثبت نشده';try{return new Intl.DateTimeFormat('fa-IR',{timeZone:'Asia/Tehran',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(date))}catch(_){return 'نامشخص'}};
const el=(tag,cls='',text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const qs=(sel)=>document.querySelector(sel);
/* The demonstration uses the public, recorded archive. Never invent viewer details. */
function demoFromArchive(archivePrograms){
  const ordered=(archivePrograms||[]).filter(p=>p&&p.id&&p.date_iso).slice().sort((a,b)=>
    (b.date_iso+' '+(b.start||'')).localeCompare(a.date_iso+' '+(a.start||'')));
  const questions=[],topics=[];
  for(const p of ordered){
    const common={network:'velayat_farsi',program_id:p.id,program_title:p.program_title||p.program||'برنامه شبکه ولایت',expert_name:p.expert&&p.expert!=='نامشخص'?p.expert:null,program_date:p.date_iso,program_start_time:p.start||'',source:'didban_archive',verification_status:'source_report',broadcast_eligible:false,confidence:0,evidence_excerpt:''};
    for(const q of (p.questions||[])){
      if(!q||!q.question||!q.answer)continue;
      questions.push({...common,id:q.id||p.id+'-q-'+questions.length,content_type:'question_answer',title:q.question,summary:q.answer,question:q.question,answer:q.answer,audience_name:q.audience_name||'',audience_city:q.city||q.audience_city||'',start_timecode:q.start_sec??null,end_timecode:q.end_sec??null,estimated_answer_time:q.answer_time_approx||null});
    }
    for(const point of (p.key_points||[])){
      if(!point||!point.title)continue;
      topics.push({...common,id:p.id+'-topic-'+(point.start_sec??topics.length),content_type:'expert_topic',title:point.title,summary:point.title,question:null,answer:null,audience_name:'',audience_city:'',start_timecode:point.start_sec??null,end_timecode:point.end_sec??null,estimated_answer_time:null});
    }
  }
  const named=questions.filter(q=>q.audience_name);
  const selectedQuestions=[],seenPrograms=new Set();
  for(const q of named.concat(questions)){
    if(seenPrograms.has(q.program_id))continue;
    selectedQuestions.push(q);seenPrograms.add(q.program_id);
    if(selectedQuestions.length>=3)break;
  }
  const selectedTopics=[],seenTopics=new Set();
  for(const topic of topics){
    if(seenPrograms.has(topic.program_id)||seenTopics.has(topic.program_id))continue;
    selectedTopics.push(topic);seenTopics.add(topic.program_id);
    if(selectedTopics.length>=2)break;
  }
  if(selectedTopics.length<2)for(const topic of topics){
    if(selectedTopics.some(x=>x.id===topic.id))continue;
    selectedTopics.push(topic);if(selectedTopics.length>=2)break;
  }
  return [selectedQuestions[0],selectedTopics[0],selectedQuestions[1],selectedTopics[1],selectedQuestions[2]].filter(Boolean);
}
let config={...defaultConfig},programs=[],items=[],live=null,index=null,shown=12,mode='content',modalId=null,loading=false,good=false;
function clamp(v,min,max,fallback){if(v===null||v===undefined||v==='')return fallback;const n=Number(v);return Number.isFinite(n)?Math.min(max,Math.max(min,n)):fallback}
function validated(raw){const c={...defaultConfig,...raw};c.refresh_seconds=clamp(c.refresh_seconds,60,120,90);c.tv_card_count=clamp(c.tv_card_count,4,6,5);c.tv_max_chars=clamp(c.tv_max_chars,70,300,150);c.stale_minutes=clamp(c.stale_minutes,10,240,120);c.tv_font_px=clamp(c.tv_font_px,14,36,19);c.tv_width_px=clamp(c.tv_width_px,350,900,560);c.question_priority=clamp(c.question_priority,.1,3,1.2);if(!['right','left','bottom'].includes(c.tv_position))c.tv_position='right';if(!/^#[0-9a-f]{6}$/i.test(c.brand_color))c.brand_color=defaultConfig.brand_color;return c}
async function fetchData(path){const res=await fetch(path+'?_='+Date.now(),{cache:'no-store'});if(!res.ok)throw Error('HTTP '+res.status+' '+path);return res.json()}
async function getConfig(){let local={};try{local=JSON.parse(localStorage.getItem('pasokhnama-v4-settings')||'{}')}catch(_){}let remote={};if(location.protocol!=='file:'){try{remote=await fetchData('data/config.json')}catch(e){console.warn('config:',e.message)}}return validated({...remote,...local})}
async function loadData(){config=await getConfig();if(demo){
  // This URL is a historical demonstration, not the live broadcast source.
  config.show_audience=true;config.enable_questions=true;config.enable_expert_content=true;
  let meta=null;
  try {
    meta=await fetchData('data/index.json');
    if(Array.isArray(meta?.years)&&meta.years.length){
      const yearFiles=meta.years.filter(y=>/^archive-20[0-9]{2}[.]json$/.test(y.path));
      const archives=await Promise.all(yearFiles.map(y=>fetchData('data/'+y.path)));
      programs=archives.flatMap(a=>Array.isArray(a.programs)?a.programs:[]);
      programs.sort((a,b)=>(b.date_iso+' '+(b.start||'')).localeCompare(a.date_iso+' '+(a.start||'')));
      items=demoFromArchive(programs);
    }
  }catch(err){console.warn('Archive demo fallback:',err.message)}
  if(!items.length){
    const sample=await fetchData('data/demo-showcase.json');
    programs=Array.isArray(sample.programs)?sample.programs:[];
    items=Array.isArray(sample.items)?sample.items:[];
    meta={updated_at:sample.updated_at};
  }
  live={program_id:programs[0]?.id||null,program_title:'منتخبی از برنامه‌های شبکه ولایت',expert_name:'',last_analysis_at:null,last_report_published_at:meta?.updated_at,items};
  index=meta;return
}
const [pindex,cindex,liveData]=await Promise.all([fetchData('data/index.json'),fetchData('data/content-index.json'),fetchData('data/live.json')]);
if(!Array.isArray(pindex.years)||!Array.isArray(cindex.years))throw Error('bad index');
const validName=(file,prefix)=>new RegExp('^'+prefix+'-20\\d\\d\\.json$').test(file);
const archives=await Promise.all(pindex.years.filter(x=>validName(x.path,'archive')).map(x=>fetchData('data/'+x.path)));
const content=await Promise.all(cindex.years.filter(x=>validName(x.path,'content')).map(x=>fetchData('data/'+x.path)));
programs=archives.flatMap(a=>Array.isArray(a.programs)?a.programs:[]).filter(p=>p.id&&p.date_iso);
items=content.flatMap(a=>Array.isArray(a.items)?a.items:[]).filter(i=>i.network==='velayat_farsi'&&i.program_id&&i.content_type&&i.title);
programs.sort((a,b)=>`${b.date_iso} ${b.start}`.localeCompare(`${a.date_iso} ${a.start}`));
items.sort((a,b)=> (`${b.program_date||''} ${b.program_start_time||''}`).localeCompare(`${a.program_date||''} ${a.program_start_time||''}`) || (Number(b.start_timecode||0)-Number(a.start_timecode||0)));
live=liveData;index=pindex}
function programOf(item){return programs.find(p=>p.id===item.program_id)}
function toast(text){const n=$('notice');if(!n)return;n.textContent=text;n.hidden=false;setTimeout(()=>n.hidden=true,2500)}
function visibleText(text){return String(text??'')}
function status(item){return ['approved','evidence_based'].includes(item.verification_status)?'دارای تأیید منبع':'خلاصه گزارش خودکار · نیازمند بررسی'}
function fillSelect(id,values,preserve=true){const node=$(id),previous=preserve?node.value:'all';const options=[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fa'));node.replaceChildren(new Option('همه '+({ 'program-filter':'برنامه‌ها','expert-filter':'کارشناسان','year-filter':'سال‌ها'}[id]||'موارد'),'all'));for(const x of options)node.append(new Option(x,x));node.value=[...node.options].some(o=>o.value===previous)?previous:'all'}
function filtered(){const search=norm($('query').value),type=$('type-filter').value,pName=$('program-filter').value,expert=$('expert-filter').value,year=$('year-filter').value;
if(mode==='programs')return programs.filter(p=>(pName==='all'||p.program===pName)&&(expert==='all'||p.expert===expert)&&(year==='all'||p.date_iso?.startsWith(year))&&(!search||norm([p.program,p.program_title,p.summary,p.topic,p.expert,...(p.key_points||[]).map(x=>x.title)].join(' ')).includes(search)));
return items.filter(i=>(type==='all'||i.content_type===type)&&(pName==='all'||i.program_title===pName)&&(expert==='all'||i.expert_name===expert)&&(year==='all'||i.program_date?.startsWith(year))&&(!search||norm([i.title,i.summary,i.question,i.answer,i.expert_name,i.program_title,i.audience_name,i.audience_city].join(' ')).includes(search)))}
function card(item){const c=el('article','content-card');c.dataset.kind=item.content_type;
const top=el('div','content-meta-top'),kind=el('span','kind-chip '+item.content_type,`${icons[item.content_type]||'✦'} ${labels[item.content_type]||'مطلب علمی'}`),st=el('span','status-chip '+(item.broadcast_eligible?'approved':''),status(item));top.append(kind,st,el('time','content-date',dateText(item.program_date)));
const title=el('h3','',item.title),desc=el('p','',item.summary||'—'),foot=el('div','content-footer');foot.append(el('span','',item.program_title||'شبکه ولایت'),el('span','',item.expert_name?'کارشناس: '+item.expert_name:'گوینده تأیید نشده'));
if(item.start_timecode!==null&&item.start_timecode!==undefined)foot.append(el('span','',secs(item.start_timecode)));
const b=el('button','','جزئیات و اشتراک‌گذاری ←');b.type='button';b.onclick=()=>openDetails(item);foot.append(b);c.append(top,title,desc,foot);return c}
function programCard(p){const c=el('article','content-card');const top=el('div','content-meta-top');top.append(el('span','kind-chip','پرونده برنامه'),el('time','content-date',dateText(p.date_iso)));const title=el('h3','',p.program_title||p.program||'برنامه شبکه ولایت');const desc=el('p','',p.summary||'برای این برنامه خلاصه‌ای در آرشیو ثبت نشده است.');const foot=el('div','content-footer');foot.append(el('span','',p.program||'—'),el('span','',p.expert||'کارشناس ثبت نشده'));const btn=el('button','','مشاهده مباحث این برنامه ←');btn.onclick=()=>{mode='content';document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.mode==='content'));$('program-filter').value=p.program;shown=12;renderCards();document.getElementById('archive').scrollIntoView({block:'start',behavior:'smooth'})};foot.append(btn);c.append(top,title,desc,foot);return c}
function renderCards(){const result=filtered(),target=$('cards');target.replaceChildren();$('found-count').textContent=fa(result.length)+' '+(mode==='programs'?'برنامه':'مطلب');if(!result.length)target.append(el('div','empty-list','موردی با این شرایط وجود ندارد. برای مشاهده نمونه آرشیوی، آدرس را با ?demo=1 باز کنید.'));
for(const item of result.slice(0,shown))target.append(mode==='programs'?programCard(item):card(item));$('more').hidden=result.length<=shown}
function renderAudience(){ $('metric-content').textContent=fa(items.length);$('metric-programs').textContent=fa(programs.length);$('metric-questions').textContent=fa(items.filter(i=>i.content_type==='question_answer').length);$('last-update').textContent=prettyDate(index?.updated_at);
fillSelect('program-filter',programs.map(p=>p.program));fillSelect('expert-filter',programs.map(p=>p.expert).concat(items.map(i=>i.expert_name)));fillSelect('year-filter',programs.map(p=>(p.date_iso||'').slice(0,4)));
const active=live?.program_id?programs.find(p=>p.id===live.program_id):null;const p=active||programs[0];$('side-program').textContent=p?.program||'هنوز برنامه‌ای ثبت نشده';$('side-summary').textContent=clip(p?.summary||'در انتظار ورود اطلاعات معتبر برنامه‌ها ...',185);$('side-expert').textContent=p?.expert||'نامشخص';$('side-time').textContent=prettyDate(live?.last_analysis_at||live?.last_report_published_at);
$('side-status').textContent=fresh(live)?'گزارش تازه دریافت شده':'آخرین مطالب ثبت‌شده';
renderCards();if(demo){$('side-status').textContent='برگرفته از آرشیو واقعی؛ خلاصه خودکار نیازمند بازبینی'}const direct=params.get('item');if(direct&&!modalId){const i=items.find(x=>x.id===direct);if(i)openDetails(i,false)}}
function openDetails(item,update=true){modalId=item.id;$('modal-category').textContent=labels[item.content_type]||'مطلب علمی';$('modal-title').textContent=item.title;$('modal-body').textContent=item.summary||item.answer||'—';const evidence=$('modal-evidence');evidence.hidden=!item.evidence_excerpt;evidence.textContent=item.evidence_excerpt?'شاهد ثبت‌شده: '+item.evidence_excerpt:'';const meta=$('modal-meta');meta.replaceChildren();for(const s of [item.program_title,item.expert_name&&'کارشناس: '+item.expert_name,dateText(item.program_date),item.estimated_answer_time&&'حدود ساعت '+fa(item.estimated_answer_time),status(item),item.start_timecode!==null&&item.start_timecode!==undefined&&'زمان در برنامه: '+secs(item.start_timecode)])if(s)meta.append(el('span','',s));$('modal').hidden=false;document.body.style.overflow='hidden';if(update){const u=new URL(location.href);u.searchParams.set('item',item.id);history.replaceState(null,'',u)}$('modal-close').focus()}
function closeDetails(){modalId=null;$('modal').hidden=true;document.body.style.overflow='';const u=new URL(location.href);u.searchParams.delete('item');history.replaceState(null,'',u)}
function fresh(l){if(demo)return true;if(!(l?.last_analysis_at||l?.last_report_published_at)||!l?.program_date||!l?.program_start_time)return false;
const checked=Date.parse(l.last_analysis_at||l.last_report_published_at);const started=Date.parse(`${l.program_date}T${l.program_start_time}:00+03:30`);const now=Date.now();return Number.isFinite(checked)&&Number.isFinite(started)&&now-checked>=-600000&&now-checked<config.stale_minutes*60000&&now-started>=-7200000&&now-started<8*3600000}
function tvItem(item){
const kind=item.content_type,qa=kind==='question_answer';
const c=el('article','tv-card kind-'+kind);c.dataset.id=item.id;
const top=el('div','tv-card-top');top.append(el('span','',`${icons[kind]||'✦'} ${labels[kind]||'مطلب علمی'}`));
if(demo&&item.program_title)top.append(el('span','tv-card-origin',clip(item.program_title,24)));
if(config.show_timecode&&item.start_timecode!==null&&item.start_timecode!==undefined)top.append(el('time','',secs(item.start_timecode)));
c.append(top);
if(qa){
  const title=el('h2','tv-question');title.append(el('span','tv-qa-label','سؤال: '),document.createTextNode(clip(item.question||item.title,145)));c.append(title);
  const answer=el('p','tv-answer');answer.append(el('b','tv-qa-label','پاسخ: '),document.createTextNode(clip(item.answer||item.summary,260)));c.append(answer);
  if(demo||config.show_audience){
    const viewer=el('div','tv-viewer-line');
    viewer.append(el('span','', 'بیننده: '+(item.audience_name||'نام ثبت نشده')));
    viewer.append(el('span','', 'شهر: '+(item.audience_city||'ثبت نشده')));
    c.append(viewer);
  }
}else{
  c.append(el('h2','',clip(item.title,125)));
  if(item.summary&&item.summary!==item.title)c.append(el('p','',clip(item.summary,config.tv_max_chars)));
}
return c}
function renderOverlay(){const stage=qs('.overlay-stage'),panel=$('tv-panel');const pos=params.get('pos')||config.tv_position;stage.classList.remove('position-left','position-bottom');if(pos==='left'||pos==='bottom')stage.classList.add('position-'+pos);
panel.style.setProperty('--tv-width',clamp(params.get('width'),350,900,config.tv_width_px)+'px');panel.style.setProperty('--tv-font',config.tv_font_px+'px');panel.style.setProperty('--tv-accent',config.brand_color);
const icon=$('tv-panel').querySelector('.tv-logo');if(config.logo_url&&/^(https:\/\/|assets\/)[a-z\d_./-]+$/i.test(config.logo_url)){const im=el('img');im.src=config.logo_url;im.alt='نشان شبکه';icon.replaceChildren(im);icon.classList.add('has-image')}
const isFresh=!demo&&fresh(live);const latest=live?.items||[];let matching=latest.filter(i=>(demo||i.broadcast_eligible)&&i.network==='velayat_farsi');
matching=matching.filter(i=>i.content_type.startsWith('question')||i.content_type==='audience_question'?config.enable_questions:config.enable_expert_content);
if(!demo)matching.sort((a,b)=>Number(b.start_timecode||0)-Number(a.start_timecode||0));const count=clamp(params.get('count'),4,6,config.tv_card_count);
const ranked=matching.slice().sort((a,b)=>{const aw=a.content_type==='question_answer'?config.question_priority:1,bw=b.content_type==='question_answer'?config.question_priority:1;return bw-aw||Number(b.start_timecode||0)-Number(a.start_timecode||0)});
const chosen=demo?matching.slice(0,Math.min(6,params.has('count')?count:(window.innerHeight>=850?5:4))):ranked.slice(0,count).sort((a,b)=>Number(b.start_timecode||0)-Number(a.start_timecode||0));
$('tv-program').textContent=live?.program_title||'شبکه ولایت فارسی';$('tv-expert').textContent=demo?'برگرفته از گزارش‌های ثبت‌شده دیدبان':live?.expert_name?'کارشناس: '+live.expert_name:'محورهای علمی برنامه';$('tv-live-tag').textContent=demo?'منتخب آرشیو واقعی':isFresh?'گزارش تازه ثبت‌شده':'آخرین مطالب ثبت‌شده';$('tv-live-tag').classList.toggle('fresh',isFresh);$('tv-updated').textContent=(demo?'آخرین ثبت آرشیو: ':live?.last_analysis_at?'آخرین تحلیل: ':'آخرین انتشار گزارش: ')+prettyDate(live?.last_analysis_at||live?.last_report_published_at);$('tv-count').textContent=fa(chosen.length)+(demo?' مطلب آرشیوی':' مطلب');$('demo-label').hidden=!demo;
const target=$('tv-cards'),prev=[...target.children].map(x=>x.dataset?.id).filter(Boolean);target.replaceChildren();if(!chosen.length){target.append(el('div','tv-empty',live?.program_id?'محتوای دارای تأیید کافی برای نمایش کارشناسی هنوز ثبت نشده است.':'در انتظار نخستین گزارش معتبر دیدبان …'));return}for(const item of chosen){const c=tvItem(item);if(!prev.includes(item.id)&&prev.length)c.classList.add('new-card');target.append(c)}}
function wireAudience(){for(const id of ['query','type-filter','program-filter','expert-filter','year-filter'])$(id).addEventListener(id==='query'?'input':'change',()=>{shown=12;renderCards()});document.querySelectorAll('.tab').forEach(btn=>btn.onclick=()=>{mode=btn.dataset.mode;shown=12;document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t===btn));renderCards()});$('more').onclick=()=>{shown+=12;renderCards()};$('modal-close').onclick=closeDetails;qs('.modal-shade').onclick=closeDetails;document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modalId)closeDetails()});$('copy-link').onclick=async()=>{try{await navigator.clipboard.writeText(location.href);toast('لینک مستقیم کپی شد')}catch(_){toast('مرورگر اجازه کپی نداد')}};$('share').onclick=async()=>{if(navigator.share){try{await navigator.share({url:location.href,title:$('modal-title').textContent})}catch(_){}}else{$('copy-link').click()}}}
const fields={'s-refresh':'refresh_seconds','s-count':'tv_card_count','s-length':'tv_max_chars','s-position':'tv_position','s-color':'brand_color','s-font':'tv_font_px','s-stale':'stale_minutes','s-width':'tv_width_px','s-priority':'question_priority','s-logo':'logo_url','s-timecodes':'show_timecode','s-audience':'show_audience','s-qa':'enable_questions','s-topics':'enable_expert_content'};
function valuesFromSettings(){const raw={};for(const [id,name]of Object.entries(fields)){const node=$(id);raw[name]=node.type==='checkbox'?node.checked:node.type==='number'?Number(node.value):node.value}return validated(raw)}
function wireSettings(){for(const [id,key]of Object.entries(fields)){const e=$(id);e[e.type==='checkbox'?'checked':'value']=config[key]??''}
$('save-settings').onclick=()=>{config=valuesFromSettings();localStorage.setItem('pasokhnama-v4-settings',JSON.stringify(config));$('settings-feedback').textContent='تنظیمات برای همین مرورگر ذخیره شد. برای نصب سراسری از دکمه دریافت JSON استفاده کنید.'};
$('export-settings').onclick=()=>{const data=JSON.stringify(valuesFromSettings(),null,2);const b=new Blob([data],{type:'application/json'}),url=URL.createObjectURL(b),a=el('a');a.href=url;a.download='config.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),3000);$('settings-feedback').textContent='فایل JSON تهیه شد. پس از بررسی، آن را در docs/data/config.json مخزن جایگزین کنید.'}}
async function loop(){if(loading)return;loading=true;try{await loadData();good=true;if(page==='audience')renderAudience();else if(page==='overlay')renderOverlay();else if(page==='settings'&&!document.body.dataset.ready){wireSettings();document.body.dataset.ready='1'}}catch(error){console.warn('Pasokhnama:',error);if(!good){if(page==='audience')$('cards').replaceChildren(el('div','empty-list','ارتباط با داده‌های آرشیو برقرار نشد. صفحه را بعداً دوباره بررسی کنید.'));if(page==='overlay')$('tv-cards').replaceChildren(el('div','tv-empty','اتصال به خروجی دیدبان برقرار نیست.'))}}finally{loading=false;if(page!=='settings')setTimeout(loop,config.refresh_seconds*1000)}}
if(page==='audience')wireAudience();loop();
})();
