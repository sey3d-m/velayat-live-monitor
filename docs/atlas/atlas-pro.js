
/* Velayat Atlas Pro — read-only extension for the existing Didban atlas.
   No AI model, audio, overlay, scheduler or production workflow is called. */
(function(){
'use strict';
var S={group:'',episode:'',selected:'root',graphSearch:'',sQuery:'',sProgram:'',sExpert:'',sDate:'',sType:'all',sView:'cards',sSort:'relevance',rQuery:'',draft:{},published:{},publishedPhotos:{},preview:false,archiveReport:null};
var NS='http://www.w3.org/2000/svg',stage=null,world=null,animation=0,nodeViews=[],linkViews=[],model=null,cam={x:0,y:0,k:1},drag=null,quiet=matchMedia('(prefers-reduced-motion: reduce)').matches;
var motionResume=null;
var allowed=['topic','summary','expert','host','hashtags','key_points','clips','questions'];
var originals={graphSection:graphSection,drawGraph:drawGraph,resetGraph:resetGraph,render:render,timeline:timeline,episodeDetails:episodeDetails};
function E(x){return esc(x)}
function N(x){return String(x||'').replace(/[\u064b-\u065f\u0670]/g,'').replace(/[يى]/g,'ی').replace(/ك/g,'ک').replace(/[\u200c\u200d]/g,' ').replace(/[_#ـ]/g,' ').toLowerCase().replace(/\s+/g,' ').trim()}
function tokens(x){return N(x).split(' ').filter(Boolean)}
function safeUrl(x){try{var u=new URL(x,location.href);return u.protocol==='https:'||u.protocol==='http:'?u.href:''}catch(e){return ''}}
function fmt(n){return Number(n||0).toLocaleString('fa-IR')}
function when(p){return String(p.date_iso||p.date||'')+' '+String(p.start||'')}
function count(p){return programs.filter(x=>name(x)===p).length}
function unique(xs){return [...new Set(xs.filter(Boolean))]}
function detailHash(x){return '#/episode/'+encodeURIComponent(x)}
function actionBtn(text,fun,cls){return '<button class="atlas-btn '+(cls||'')+'" onclick="'+fun+'">'+E(text)+'</button>'}
function installNavigation(){
 var side=document.getElementById('rail');if(!side||side.dataset.atlasPro)return;side.dataset.atlasPro='1';
 var bottom=side.querySelector('.rail-bottom');
 [['search','⌕','جست‌وجوی جامع'],['research','◉','میز پژوهش و برنامه‌سازی'],['editor','✎','مدیریت و اصلاحات']].forEach(function(x){var b=document.createElement('button');b.className='nav';b.dataset.view=x[0];b.innerHTML='<span class="emoji">'+x[1]+'</span>'+x[2];b.onclick=function(){go('#/'+x[0])};side.insertBefore(b,bottom)});
}
function changeMode(m){S.group=m||'';S.episode='';S.selected=m?'p:'+m:'root';mountGraph()}
function atlasGraphSection(){
 var total=programs.length,groupCount=groupShows().length;
 return section('نقشه زنده ارتباطات علمی','منظومه پویا و چندلایه: مسیر حرکت داده از شبکه ولایت به برنامه‌ها، قسمت‌ها، کارشناسان، محورها و پرسش‌های واقعی',
 '<button class="button small" onclick="go(\'#/search\')">⌕ جست‌وجوی تخصصی در اطلس</button>')+
 '<section class="atlas-panel" id="graphAnchor"><div class="atlas-head"><div><h3>◈ منظومه زنده دانش ولایت</h3><p>برای گسترش ارتباطات، گره‌ها را انتخاب کنید؛ جریان‌های نورانی حرکت داده را نشان می‌دهند.</p></div><div class="atlas-actions">'+
 actionBtn('◉ شبکه کامل','atlasSelectRoot()')+
 (S.graphSearch?actionBtn('× حذف فیلتر موضوعی','atlasClearGraphQuery()'):'')+
 actionBtn('⌕ جست‌وجوی موضوعی','atlasGraphTopic()')+
 '<button class="atlas-btn atlas-movement-control" id="atlasMotionControl" onclick="atlasToggleMotion()" aria-pressed="'+(!quiet)+'">'+(quiet?'▶ آغاز حرکت':'Ⅱ توقف حرکت')+'</button>'+
 actionBtn('＋','atlasZoom(1.16)')+actionBtn('−','atlasZoom(.86)')+actionBtn('⤢','atlasReset()')+actionBtn('⛶ تمام‌صفحه','atlasFullscreen()')+
 '</div></div><div class="atlas-graph-layout"><div class="atlas-stage" id="atlasStage"><div class="motion-glow" aria-hidden="true"></div><svg id="atlasSvg" viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid meet" aria-label="نقشه پویا و تعاملی ارتباطات علمی ولایت" role="img"><g id="atlasWorld"></g></svg><div class="atlas-visual-stat"><span class="atlas-live-indicator"></span><span id="atlasLiveStats">'+fmt(groupCount)+' برنامه · '+fmt(total)+' قسمت</span></div><div class="atlas-pins">🟡 شبکه و مجموعه · 🟢 قسمت · 🔵 کارشناس · ✦ محور · بنفش: پرسش</div></div><aside class="atlas-inspector" id="atlasInspector"></aside></div></section>';
}
function svg(tag,attrs,parent){var el=document.createElementNS(NS,tag);Object.keys(attrs||{}).forEach(k=>el.setAttribute(k,attrs[k]));(parent||world).appendChild(el);return el}
function edge(a,b,why){return {a:a,b:b,why:why}}
function partID(p){return 'e:'+p.id}
function buildGraph(){
 var nodes=[],edges=[],map=new Map(),root={id:'root',kind:'root',label:'شبکه جهانی ولایت',sub:'مرجع علمی دیدبان',x:600,y:346,r:70};
 nodes.push(root);map.set(root.id,root);
 function add(n){if(!map.has(n.id)){nodes.push(n);map.set(n.id,n)}return n}
 var gs=groupShows().map(x=>({name:x[0],items:x[1]}));
 if(!S.group){
  var linked=S.graphSearch?new Set(results(S.graphSearch,{}).map(x=>x.program)):null;var arr=gs.filter(g=>!linked||linked.has(g.name));
  arr.forEach(function(g,i){
   var a=2*Math.PI*i/Math.max(1,arr.length)-Math.PI/2,ring=i%2===0?242:290;
   add({id:'p:'+g.name,kind:'program',label:g.name,sub:fmt(g.items.length)+' قسمت',x:600+Math.cos(a)*ring*1.53,y:345+Math.sin(a)*ring,r:23,group:g.name});
   edges.push(edge('root','p:'+g.name,'مجموعه واقعی برنامه‌ها'));
  });
  // Cross-program lines require independently recorded, non-generic shared tags.
  var ignored=new Set(['شبکه جهانی ولایت','شبکه ولایت','ولایت','فاطمیه','برنامه زنده','ولایت فارسی','شبکه','برنامه']);
  var gsTags=arr.map(function(g){return new Set(g.items.flatMap(p=>specificTags(p)).map(N).filter(t=>t.length>3&&!ignored.has(t)))});
  var tagFreq=new Map();gsTags.forEach(tags=>tags.forEach(t=>tagFreq.set(t,(tagFreq.get(t)||0)+1)));
  var semantic=[];
  for(var i=0;i<arr.length;i++)for(var j=i+1;j<arr.length;j++){
   var overlap=[...gsTags[i]].filter(t=>gsTags[j].has(t)&&tagFreq.get(t)<=Math.max(3,Math.round(arr.length*.35)));
   if(overlap.length)semantic.push({a:arr[i].name,b:arr[j].name,why:overlap.slice(0,3),weight:overlap.length});
  }
  semantic.sort((a,b)=>b.weight-a.weight);
  semantic.slice(0,12).forEach(function(x){var e=edge('p:'+x.a,'p:'+x.b,'کلیدواژه ثبت‌شده مشترک: '+x.why.join('، '));e.semantic=true;edges.push(e)});
  return {nodes:nodes,edges:edges,map:map};
 }
 var group=gs.find(g=>g.name===S.group);if(!group){S.group='';return buildGraph()}
 root.x=1035;root.y=345;root.r=48;
 add({id:'p:'+group.name,kind:'program',label:group.name,sub:fmt(group.items.length)+' قسمت',x:810,y:345,r:39,group:group.name});
 edges.push(edge('root','p:'+group.name,'برنامه زیرمجموعه شبکه ولایت'));
 var epItems=group.items.slice(0,8);
 epItems.forEach(function(p,i){var a=-Math.PI/2+2*Math.PI*i/Math.max(epItems.length,1);
  var x=540+Math.cos(a)*175,y=350+Math.sin(a)*210;
  add({id:partID(p),kind:'episode',label:p.topic||p.program_title||p.date,sub:(p.date||p.date_iso||'')+' · '+(p.start||''),x:x,y:y,r:20,p:p});
  edges.push(edge('p:'+group.name,partID(p),'قسمت این مجموعه'));
 });
 if(!S.episode)return {nodes:nodes,edges:edges,map:map};
 var one=get(S.episode);if(!one)return {nodes:nodes,edges:edges,map:map};
 var eid=partID(one),en=map.get(eid);
 if(!en){en=add({id:eid,kind:'episode',label:one.topic||name(one),sub:one.date||one.date_iso,x:510,y:330,r:30,p:one});edges.push(edge('p:'+group.name,eid,'قسمت این مجموعه'))}
 en.x=505;en.y=350;en.r=32;
 var who=expert(one);
 if(who&&who!=='کارشناس نامشخص'){
  add({id:'x:'+who,kind:'expert',label:who,sub:'کارشناس این قسمت',x:435,y:90,r:23,who:who});
  edges.push(edge(eid,'x:'+who,'نام کارشناس در گزارش'));
 }
 var tps=topics(one).slice(0,7);
 tps.forEach(function(t,i){var ang=(i/(Math.max(1,tps.length-1)))*Math.PI+Math.PI/2;
  var x=375+Math.cos(ang)*270,y=345+Math.sin(ang)*235;
  add({id:'t:'+one.id+':'+i,kind:'topic',label:t.title,sub:hhmm(t.start_sec),x:x,y:y,r:14,p:one,t:t});
  edges.push(edge(eid,'t:'+one.id+':'+i,'محور زمان‌دار این قسمت'));
 });
 qa(one).slice(0,2).forEach(function(q,i){
  add({id:'q:'+one.id+':'+i,kind:'qa',label:q.question,sub:'پرسش ثبت‌شده',x:310,y:110+i*95,r:15,p:one,q:q});
  edges.push(edge(eid,'q:'+one.id+':'+i,'پرسش ثبت‌شده در همین قسمت'));
 });
 return {nodes:nodes,edges:edges,map:map};
}
function labelShort(s,n){s=String(s||'');return s.length>n?s.slice(0,n-1)+'…':s}
function mountGraph(){
 stage=document.getElementById('atlasStage');if(!stage)return;
 if(animation)cancelAnimationFrame(animation);animation=0;nodeViews=[];linkViews=[];cam={x:0,y:0,k:1};drag=null;
 world=document.getElementById('atlasWorld');if(!world)return;world.replaceChildren();model=buildGraph();
 var svgEl=document.getElementById('atlasSvg');
 var space=svg('g',{},world);
 // A reproducible star field with no data-dependent decorative connections.
 for(var j=0;j<48;j++){
  var sx=(j*191.37+67)%1200,sy=(j*89.47+35)%700;
  svg('circle',{class:'atlas-space-point',cx:sx,cy:sy,r:((j%4)+1)*.62,opacity:.12+(j%5)*.07},space);
 }
 var nebula=svg('g',{},world);
 [110,240,358,480].forEach(function(rad,i){svg('ellipse',{class:'atlas-grid-orbit',cx:600,cy:345,rx:rad,ry:rad*.65,'stroke-dasharray':i%2?'5 13':'3 10'},nebula)});
 svg('circle',{class:'atlas-nebula',cx:600,cy:345,r:182},nebula);
 var glow=svg('g',{},world),links=svg('g',{},world),signals=svg('g',{},world),nodesLayer=svg('g',{},world);
 model.edges.forEach(function(l,i){
  var halo=svg('path',{class:'atlas-link-halo'},glow);
  var path=svg('path',{class:'atlas-edge'},links);
  var signal=svg('circle',{class:'atlas-signal'+(i%3===0?' warm':''),r:i%3===0?3.6:2.7,opacity:quiet?0:.92},signals);
  linkViews.push({edge:l,el:path,halo:halo,signal:signal,index:i});
 });
 var glyph={root:'و',program:'◈',episode:'▶',expert:'♙',topic:'✦',qa:'؟'};
 model.nodes.forEach(function(n,i){
  var g=svg('g',{class:'atlas-node entering '+n.kind+(S.selected===n.id?' active':''),role:'button',tabindex:0,'aria-label':n.kind+' '+n.label},nodesLayer);
  if(n.kind==='root'){
   svg('circle',{class:'orbital',cx:0,cy:0,r:n.r+22,'stroke-dasharray':'4 8'},g);
   svg('circle',{class:'orbital',cx:0,cy:0,r:n.r+12,'stroke-dasharray':'2 7'},g);
  }else svg('circle',{class:'orbital',cx:0,cy:0,r:n.r+6,opacity:.55},g);
  svg('circle',{class:'primary',cx:0,cy:0,r:n.r},g);
  var glyphY=n.kind==='root'?10:5;
  var t0=svg('text',{class:'glyph','text-anchor':'middle',y:glyphY},g);t0.textContent=glyph[n.kind]||'◈';
  if(n.kind!=='root')svg('circle',{class:'active-dot',cx:n.r*.7,cy:-n.r*.65,r:Math.max(2,Math.min(3.3,n.r/6))},g);
  var t=svg('text',{class:'nlabel','text-anchor':'middle',y:n.r+21},g);t.textContent=labelShort(n.label,n.kind==='root'?30:27);
  var sub=svg('text',{class:'nsub','text-anchor':'middle',y:n.r+37},g);sub.textContent=labelShort(n.sub||'',28);
  g.style.animationDelay=Math.min(480,i*40)+'ms';
  g.addEventListener('click',function(ev){ev.stopPropagation();if(drag&&drag.moved)return;atlasPick(n.id)});
  g.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();atlasPick(n.id)}});
  nodeViews.push({n:n,el:g,i:i,x:n.x,y:n.y});
 });
 svgEl.onpointerdown=function(ev){if(ev.button!==0||ev.target.closest('.atlas-node'))return;drag={x:ev.clientX,y:ev.clientY,ox:cam.x,oy:cam.y,moved:false,id:ev.pointerId};svgEl.setPointerCapture(ev.pointerId);svgEl.classList.add('dragging')};
 svgEl.onpointermove=function(ev){if(!drag)return;var dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;cam.x=drag.ox+dx*1200/Math.max(1,svgEl.clientWidth);cam.y=drag.oy+dy*700/Math.max(1,svgEl.clientHeight);setCamera()};
 svgEl.onpointerup=svgEl.onpointercancel=function(){drag=null;svgEl.classList.remove('dragging')};
 svgEl.onwheel=function(ev){ev.preventDefault();cam.k=Math.max(.55,Math.min(2.8,cam.k*(ev.deltaY<0?1.10:.91)));setCamera()};
 svgEl.ondblclick=function(ev){if(!ev.target.closest('.atlas-node')){cam.k=Math.min(2.8,cam.k*1.3);setCamera()}};
 inspect();
 // Visible organic movement + directional light moving along factual edges.
 var started=0,lastFrame=-1000;
 function frame(t){
  if(document.getElementById('atlasWorld')!==world){animation=0;return}
  if(!started)started=t;
  if(document.hidden){animation=0;motionResume=function(){if(document.getElementById('atlasWorld')===world&&!quiet&&!animation){animation=requestAnimationFrame(frame)}};return}
  if(t-lastFrame<27&&!quiet){animation=requestAnimationFrame(frame);return}lastFrame=t;
  var age=t-started,positions=new Map();
  nodeViews.forEach(function(o){
   var n=o.n,i=o.i,isRoot=n.kind==='root';
   var a=quiet?0:(t/2400+i*1.55);
   var amt=isRoot?0:(n.kind==='program'?13:(n.kind==='episode'?10:7.5));
   var dx=Math.sin(a)*amt+Math.sin(t/5700+i*.93)*amt*.33;
   var dy=Math.cos(t/3100+i*1.21)*amt*.75+Math.sin(t/6600+i*.47)*amt*.25;
   var fade=quiet?1:Math.max(0,Math.min(1,(age-i*42)/850));
   var ease=1-Math.pow(1-fade,3);
   var initX=S.group?810:600,initY=345;
   var px=initX+(n.x+dx-initX)*ease,py=initY+(n.y+dy-initY)*ease;
   var sc=.72+.28*ease;
   o.x=px;o.y=py;positions.set(n.id,{x:px,y:py});
   o.el.setAttribute('transform','translate('+px.toFixed(2)+' '+py.toFixed(2)+') scale('+sc.toFixed(3)+')');
  });
  linkViews.forEach(function(o){
   var pa=positions.get(o.edge.a),pb=positions.get(o.edge.b);if(!pa||!pb)return;
   var mx=(pa.x+pb.x)/2,my=(pa.y+pb.y)/2,curve=Math.max(-28,Math.min(28,(pb.x-pa.x)*.07));
   var pathD='M '+pa.x.toFixed(2)+' '+pa.y.toFixed(2)+' Q '+(mx+curve).toFixed(2)+' '+(my-21).toFixed(2)+' '+pb.x.toFixed(2)+' '+pb.y.toFixed(2);
   o.el.setAttribute('d',pathD);o.halo.setAttribute('d',pathD);
   var hot=S.selected===o.edge.a||S.selected===o.edge.b;
   o.el.setAttribute('class','atlas-edge'+(o.edge.semantic?' semantic':'')+(hot?' highlight':''));
   o.halo.setAttribute('opacity',hot?'.9':'.35');
   if(quiet){o.signal.setAttribute('opacity','0');return}
   var progress=((t/3600)+(o.index*.19))%1;
   try{var dlen=o.el.getTotalLength(),point=o.el.getPointAtLength(dlen*progress);
    o.signal.setAttribute('cx',point.x.toFixed(2));o.signal.setAttribute('cy',point.y.toFixed(2));
    o.signal.setAttribute('opacity',hot?1:.82);
   }catch(e){o.signal.setAttribute('opacity',0)}
  });
  if(!quiet)animation=requestAnimationFrame(frame);else animation=0;
 }
 motionResume=function(){if(document.getElementById('atlasWorld')===world&&!animation&&!quiet)animation=requestAnimationFrame(frame)};
 frame(performance.now());
}

function setCamera(){if(world)world.setAttribute('transform','translate('+cam.x+' '+cam.y+') translate(600 350) scale('+cam.k+') translate(-600 -350)')}
function atlasPick(id){
 var n=model&&model.map.get(id);if(!n)return;
 S.selected=id;
 if(n.kind==='root'){S.group='';S.episode='';mountGraph();return}
 if(n.kind==='program'){S.group=n.group;S.episode='';mountGraph();return}
 if(n.kind==='episode'){S.episode=n.p.id;mountGraph();return}
 inspect();
 nodeViews.forEach(function(o){o.el.classList.toggle('active',o.n.id===id)});
}
function inspect(){
 var el=document.getElementById('atlasInspector');if(!el||!model)return;var n=model.map.get(S.selected)||model.map.get('root');
 if(!n){el.innerHTML='محتوایی برای این انتخاب وجود ندارد';return}
 var type='',meta='',desc='',buttons='';
 if(n.kind==='root'){type='مرکز اطلس';meta=fmt(programs.length)+' قسمت · '+fmt(groupShows().length)+' مجموعه برنامه';desc='تمام برنامه‌ها و پیوندهای اطلس از آرشیو فعلی دیدبان استخراج می‌شوند. برای مشاهده زیرشاخه‌ها یک برنامه را انتخاب کنید.';buttons=actionBtn('جست‌وجوی موضوعی','go(\'#/search\')')}
 if(n.kind==='program'){var a=programs.filter(p=>name(p)===n.group);type='مجموعه برنامه';meta=fmt(a.length)+' قسمت · '+fmt(unique(a.map(expert)).length)+' کارشناس';var relations=model.edges.filter(e=>e.semantic&&(e.a===n.id||e.b===n.id));desc='قسمت‌های ثبت‌شده و محورهای هر قسمت را می‌توانید بررسی کنید.'+(relations.length?'\nپیوندهای محتوایی مستند: '+relations.map(e=>e.why).join('؛ '):'');meta+=' · '+fmt(relations.length)+' ارتباط عرضی ثبت‌شده';buttons=actionBtn('پرونده اختصاصی مجموعه','go(\'#/show/'+encodeURIComponent(n.group)+'\')','active')}
 if(n.kind==='episode'){var p=n.p;type='قسمت برنامه';meta=(p.date||p.date_iso||'')+' · '+(p.start||'')+' · '+expert(p);desc=p.summary||'متن خلاصه موجود نیست';buttons=actionBtn('پرونده و خط زمانی','go(\''+detailHash(p.id)+'\')','active')}
 if(n.kind==='expert'){type='کارشناس';meta=fmt(programs.filter(p=>expert(p)===n.who).length)+' قسمت ثبت‌شده';desc='اتصال این کارشناس به برنامه از نام درج‌شده در گزارش دیدبان استخراج شده است.';buttons=actionBtn('جست‌وجوی کارشناس','atlasSearchFor('+JSON.stringify(n.who).replace(/"/g,'&quot;')+')')}
 if(n.kind==='topic'){type='محور علمی زمان‌دار';meta=hhmm(n.t.start_sec)+' — '+hhmm(n.t.end_sec);desc=n.t.title;buttons=actionBtn('مشاهده در قسمت','go(\''+detailHash(n.p.id)+'\')','active')}
 if(n.kind==='qa'){type='پرسش مخاطب';meta=n.p.date||n.p.date_iso||'';desc=n.q.question+'\n'+(n.q.answer||'پاسخ ثبت نشده');buttons=actionBtn('مشاهده پرونده','go(\''+detailHash(n.p.id)+'\')')}
 el.innerHTML='<span class="ins-crumb">اطلس / '+E(type)+'</span><h3>'+E(n.label)+'</h3><div class="ins-meta">'+E(meta)+'</div><p>'+E(desc).replace(/\n/g,'<hr style="border:0;border-top:1px solid #375363">')+'</p><div class="ins-links">'+buttons+'</div><div class="atlas-warning">ارتباطات تنها بر اساس فیلدهای ثبت‌شده در خروجی دیدبان نمایش داده شده‌اند؛ صحت علمی متن، مستقل از گزارش، تأیید نشده است.</div>';
}
window.atlasPick=atlasPick;
window.atlasSelectRoot=function(){S.group='';S.episode='';S.selected='root';mountGraph()};
window.atlasClearGraphQuery=function(){S.graphSearch='';S.group='';S.episode='';S.selected='root';mountGraph()};
window.atlasGraphTopic=function(){go('#/search');setTimeout(function(){var e=document.getElementById('atlasQuery');if(e)e.focus()},60)};
window.atlasZoom=function(n){cam.k=Math.max(.58,Math.min(2.5,cam.k*n));setCamera()};
window.atlasReset=function(){cam={x:0,y:0,k:1};setCamera()};

window.atlasToggleMotion=function(){
 quiet=!quiet;
 var btn=document.getElementById('atlasMotionControl');
 if(btn){btn.textContent=quiet?'▶ آغاز حرکت':'Ⅱ توقف حرکت';btn.setAttribute('aria-pressed',String(!quiet));btn.classList.toggle('active',!quiet)}
 if(animation){cancelAnimationFrame(animation);animation=0}
 mountGraph();
};
document.addEventListener('visibilitychange',function(){if(!document.hidden&&typeof motionResume==='function')motionResume()});

window.atlasFullscreen=function(){var e=document.getElementById('graphAnchor');if(!e)return;e.classList.toggle('atlas-view-full');setTimeout(setCamera,50)};
window.atlasSearchFor=function(s){S.sQuery=s;go('#/search')};
graphSection=atlasGraphSection;
drawGraph=function(){mountGraph()};
resetGraph=function(){mountGraph()};
function searchable(){
 var list=[];programs.forEach(function(p){
  list.push({kind:'episode',id:p.id,pid:p.id,program:name(p),expert:expert(p),date:when(p),title:p.topic||name(p),body:p.summary||'',searchText:[p.host,p.date,p.date_iso,p.start,(p.hashtags||[]).join(' '),(p.clips||[]).map(c=>c.title).join(' '),(p.key_points||[]).map(t=>t.title).join(' '),(p.questions||[]).map(t=>t.question+' '+t.answer).join(' ')].join(' '),start:null});
 });
 content.forEach(function(c){if(!c.program_id||!get(c.program_id))return;
  if(c.content_type!=='expert_topic'&&c.content_type!=='question_answer')return;
  var p=get(c.program_id);
  list.push({kind:c.content_type==='question_answer'?'qa':'topic',id:c.id,pid:p.id,program:name(p),expert:expert(p),date:when(p),title:c.title||c.question||'',body:c.answer||c.summary||'',start:c.start_timecode,content:c});
 });
 return list;
}
function score(r,q){
 var ts=tokens(q);if(!ts.length)return 1;
 var title=N(r.title),prog=N(r.program),person=N(r.expert),body=N(r.body+' '+(r.searchText||'')),s=0;
 ts.forEach(function(t){if(title.includes(t))s+=11;if(prog.includes(t))s+=8;if(person.includes(t))s+=8;if(body.includes(t))s+=3});
 if(ts.every(t=>(title+' '+prog+' '+person+' '+body).includes(t)))s+=12;else return 0;
 if(N(r.title)===N(q))s+=28;
 return s;
}
function results(q,filters){
 var a=searchable().map(function(r){return Object.assign({},r,{score:score(r,q)})}).filter(r=>r.score);
 filters=filters||{};
 if(filters.program)a=a.filter(r=>r.program===filters.program);
 if(filters.type&&filters.type!=='all')a=a.filter(r=>r.kind===filters.type);
 if(filters.sort==='date')a.sort((a,b)=>b.date.localeCompare(a.date));
 else a.sort((a,b)=>b.score-a.score||b.date.localeCompare(a.date));
 return a;
}
function hilite(t,q){var txt=String(t||''),parts=tokens(q).filter(x=>x.length>=2);if(!parts.length)return E(txt);
 var idx=-1,len=0,normed=N(txt);for(var term of parts){var j=normed.indexOf(term);if(j>=0&&(idx<0||j<idx)){idx=j;len=term.length}}
 if(idx<0)return E(txt);
 return E(txt.slice(0,idx))+'<mark>'+E(txt.slice(idx,idx+len))+'</mark>'+E(txt.slice(idx+len));
}
function resultCard(r){
 var kind={episode:'پرونده قسمت',topic:'محور بحث',qa:'پرسش و پاسخ'}[r.kind];
 var code=Number.isFinite(Number(r.start))&&r.start!==null?'<span class="timecode">'+hhmm(r.start)+'</span>':'';
 return '<article class="atlas-result"><small>'+E(kind)+' · '+E(r.program)+' · '+E(r.date)+' '+code+'</small><b>'+hilite(r.title,S.sQuery)+'</b><p>'+hilite((r.body||'خلاصه‌ای ثبت نشده است.').slice(0,420),S.sQuery)+'</p><small>کارشناس: '+E(r.expert)+'</small><div class="result-actions">'+actionBtn('مشاهده قسمت','go(\''+detailHash(r.pid)+'\')','active')+'</div></article>';
}
function searchPage(){
 var suggestions=unique(programs.flatMap(x=>specificTags(x)).filter(x=>x.length>3)).slice(0,9);
 return '<section class="atlas-searchhero"><h2>جست‌وجوی جامع دانش ولایت</h2><p>در عنوان، برنامه، کارشناس، خلاصه، محورهای زمان‌دار و پرسش‌های نمایه‌شده دیدبان جست‌وجو کنید.</p>'+
 '<input id="atlasQuery" class="atlas-input" placeholder="مثلاً: غدیر، مصحف فاطمه، دکتر کرمی، نه گفتن به فرزند..." value="'+E(S.sQuery)+'" oninput="atlasSearchInput(this.value)" aria-label="عبارت جست‌وجو">'+
 '<div class="atlas-search-row"><select class="atlas-select" aria-label="فیلتر مجموعه برنامه" onchange="atlasSearchFilter(\'program\',this.value)"><option value="">همه برنامه‌ها</option>'+
 groupShows().map(g=>'<option value="'+E(g[0])+'" '+(g[0]===S.sProgram?'selected':'')+'>'+E(g[0])+'</option>').join('')+'</select>'+
 '<select class="atlas-select" aria-label="نوع نتیجه" onchange="atlasSearchFilter(\'type\',this.value)">'+[['all','تمام انواع'],['episode','قسمت'],['topic','محور'],['qa','پرسش و پاسخ']].map(x=>'<option value="'+x[0]+'" '+(S.sType===x[0]?'selected':'')+'>'+x[1]+'</option>').join('')+'</select>'+
 '<select class="atlas-select" aria-label="کارشناس" onchange="atlasSearchFilter(\'expert\',this.value)"><option value="">همه کارشناسان</option>'+unique(programs.map(expert)).map(x=>'<option value="'+E(x)+'" '+(S.sExpert===x?'selected':'')+'>'+E(x)+'</option>').join('')+'</select>'+ 
 '<input type="date" class="atlas-select" aria-label="فیلتر تاریخ میلادی" value="'+E(S.sDate)+'" onchange="atlasSearchFilter(\'date\',this.value)">'+
 '<select class="atlas-select" aria-label="مرتب‌سازی" onchange="atlasSearchFilter(\'sort\',this.value)"><option value="relevance" '+(S.sSort==='relevance'?'selected':'')+'>مرتبط‌ترین</option><option value="date" '+(S.sSort==='date'?'selected':'')+'>جدیدترین</option></select></div>'+
 '<div class="atlas-sug">'+suggestions.map(x=>'<button onclick="atlasSearchSuggestion(this.textContent)">'+E(x.replace(/_/g,' '))+'</button>').join('')+'</div></section>'+
 '<div class="atlas-toolbar"><span class="atlas-count" id="atlasResultCount"></span><div class="atlas-actions">'+actionBtn('نمای کارت','atlasView(\'cards\')',S.sView==='cards'?'active':'')+actionBtn('نمای پژوهشی','atlasView(\'list\')',S.sView==='list'?'active':'')+actionBtn('نمای شبکه نتایج','atlasGraphFromSearch()')+actionBtn('کپی جست‌وجو','atlasCopySearch()')+'</div></div><div id="atlasResultList" class="atlas-result-grid"></div>';
}
function populateSearch(){
 var container=document.getElementById('atlasResultList');if(!container)return;
 var rs=results(S.sQuery,{program:S.sProgram,type:S.sType,sort:S.sSort});if(S.sExpert)rs=rs.filter(x=>x.expert===S.sExpert);if(S.sDate)rs=rs.filter(x=>x.date.startsWith(S.sDate));
 container.className='atlas-result-grid '+(S.sView==='list'?'list':'');
 var countNode=document.getElementById('atlasResultCount');if(countNode)countNode.textContent=fmt(rs.length)+' نتیجه در آرشیو فعلی';
 container.innerHTML=rs.length?rs.slice(0,160).map(resultCard).join(''):'<div class="empty">برای این عبارت در آرشیو فعلی نتیجه‌ای وجود ندارد.</div>';
 if(rs.length>160)container.insertAdjacentHTML('beforeend','<div class="muted">۱۶۰ نتیجه نخست نمایش داده شده است؛ جست‌وجو را دقیق‌تر کنید.</div>');
}
window.atlasGraphFromSearch=function(){if(!S.sQuery.trim())return toast('ابتدا عبارت جست‌وجو را وارد کنید');S.graphSearch=S.sQuery;S.group='';S.episode='';S.selected='root';go('#/');setTimeout(function(){document.getElementById('graphAnchor')?.scrollIntoView({behavior:'smooth'})},80)};
window.atlasSearchInput=function(v){S.sQuery=v;populateSearch()};
window.atlasSearchSuggestion=function(v){S.sQuery=v;document.getElementById('atlasQuery').value=v;populateSearch()};
window.atlasSearchFilter=function(k,v){if(k==='program')S.sProgram=v;if(k==='expert')S.sExpert=v;if(k==='date')S.sDate=v;if(k==='type')S.sType=v;if(k==='sort')S.sSort=v;populateSearch()};
window.atlasView=function(v){S.sView=v;populateSearch();document.querySelectorAll('.atlas-toolbar button').forEach(b=>b.classList.toggle('active',b.textContent.includes(v==='cards'?'کارت':'پژوهشی')))};
window.atlasCopySearch=function(){var url=location.origin+location.pathname+(S.sQuery?'?q='+encodeURIComponent(S.sQuery):'')+'#/search'; if(navigator.clipboard)navigator.clipboard.writeText(url).then(()=>toast('آدرس این صفحه کپی شد'));else prompt('نشانی',url)};
function showPage(group){var ps=programs.filter(x=>name(x)===group),ex=unique(ps.map(expert)),tags=new Map();ps.forEach(p=>(p.hashtags||[]).forEach(t=>tags.set(t,(tags.get(t)||0)+1)));var tt=[...tags.entries()].sort((a,b)=>b[1]-a[1]).slice(0,14);return '<div class="atlas-searchhero"><small>اطلس ولایت / مجموعه برنامه</small><h2>'+E(group)+'</h2><p>'+fmt(ps.length)+' قسمت ثبت‌شده · '+fmt(ex.length)+' کارشناس · آخرین قسمت: '+E(ps[0]?.date||'—')+'</p><div class="atlas-sug">'+ex.map(x=>'<button onclick="atlasSearchFor(this.textContent)">'+E(x)+'</button>').join('')+'</div></div><section class="block"><h2>موضوعات و کلیدواژه‌های پرتکرار</h2><div class="chips">'+tt.map(x=>'<span class="chip">'+E(x[0])+' · '+fmt(x[1])+'</span>').join('')+'</div></section><section class="block"><h2>آرشیو قسمت‌های این مجموعه</h2><div class="atlas-inline-list">'+ps.map(p=>'<button class="atlas-row" onclick="go(\''+detailHash(p.id)+'\')">'+E(p.topic||'بدون عنوان')+' · '+E(p.date||p.date_iso)+' · '+E(expert(p))+' · '+fmt((p.key_points||[]).length)+' محور</button>').join('')+'</div></section>';}
function researchPage(){
 return '<section class="atlas-searchhero"><h2>میز پژوهش و برنامه‌سازی</h2><p>بررسی سابقه پرداخت رسانه‌ای یک موضوع، بر پایه محورها، پرسش‌ها و برنامه‌های واقعی دیدبان.</p>'+
 '<input class="atlas-input" id="atlasResearchInput" placeholder="موضوع برنامه آینده را وارد کنید؛ مانند حدیث ثقلین" value="'+E(S.rQuery)+'" oninput="atlasResearchInput(this.value)">'+
 '<div class="atlas-sug"><button onclick="atlasResearchExport()">دریافت پرونده پژوهشی</button><button onclick="window.print()">چاپ پرونده</button></div></section><div id="atlasResearchOutput"></div>';
}
function researchModel(q){
 var r=results(q,{sort:'relevance'}),episodes=unique(r.map(x=>x.pid)).map(get).filter(Boolean),groups=unique(episodes.map(name)),experts=unique(episodes.map(expert)),qs=r.filter(x=>x.kind==='qa'),axes=r.filter(x=>x.kind==='topic');
 return {r:r,episodes:episodes,groups:groups,experts:experts,qs:qs,axes:axes};
}
function researchHtml(q,m){
 if(!q.trim())return '<div class="empty">یک موضوع وارد کنید تا سوابق واقعی طرح آن بررسی شود.</div>';
 if(!m.r.length)return '<div class="empty">برای این موضوع در آرشیو فعلی سابقه‌ای ثبت نشده است؛ این نتیجه به معنی مطرح‌نشدن موضوع در تمام پخش‌های شبکه نیست.</div>';
 var byCount=function(xs){var a=new Map();xs.forEach(x=>a.set(x,(a.get(x)||0)+1));return [...a.entries()].sort((a,b)=>b[1]-a[1])};
 return '<div class="atlas-research-grid">'+[['قسمت‌های مرتبط',m.episodes.length],['کارشناسان مرتبط',m.experts.length],['پرسش‌وپاسخ مرتبط',m.qs.length],['محورهای ثبت‌شده',m.axes.length],['مجموعه برنامه',m.groups.length],['تازه‌ترین تاریخ',m.episodes.slice().sort((a,b)=>when(b).localeCompare(when(a)))[0]?.date||'—']].map(x=>'<div class="atlas-kpi"><strong>'+E(x[1])+'</strong><span>'+E(x[0])+'</span></div>').join('')+'</div>'+
 '<section class="block"><h2>برنامه‌ها و کارشناسان دارای سابقه</h2><p>برنامه‌ها: '+E(byCount(m.episodes.map(name)).map(x=>x[0]+' ('+fmt(x[1])+')').join('، '))+'</p><p>کارشناسان: '+E(byCount(m.episodes.map(expert)).map(x=>x[0]+' ('+fmt(x[1])+')').join('، '))+'</p></section>'+
 '<section class="block"><h2>محورهای طرح‌شده در برنامه‌ها</h2><div class="atlas-inline-list">'+(m.axes.length?m.axes.slice(0,40).map(x=>'<button class="atlas-row" onclick="go(\''+detailHash(x.pid)+'\')">'+E(x.title)+' · '+E(x.program)+' · '+(x.start!==null?hhmm(x.start):'بدون زمان‌کد')+'</button>').join(''):'<div class="muted">محور جداگانه‌ای در نمایه یافت نشد.</div>')+'</div></section>'+
 '<section class="block"><h2>پرسش‌های پیشین</h2><div class="atlas-inline-list">'+(m.qs.length?m.qs.slice(0,35).map(x=>'<button class="atlas-row" onclick="go(\''+detailHash(x.pid)+'\')">'+E(x.title)+'</button>').join(''):'<div class="muted">پرسش مرتبط در نمایه فعلی ثبت نشده است.</div>')+'</div></section>'+
 '<section class="block"><h2>قسمت‌های قابل مراجعه برای برنامه‌سازی</h2><div class="atlas-inline-list">'+m.episodes.slice(0,40).map(p=>'<button class="atlas-row" onclick="go(\''+detailHash(p.id)+'\')">'+E(name(p))+' · '+E(p.topic||'')+' · '+E(p.date||p.date_iso||'')+' · '+E(expert(p))+'</button>').join('')+'</div></section>'+
 '<p class="atlas-warning">این پرونده تنها تجمیع داده‌های موجود است؛ درباره کیفیت علمی پاسخ‌ها یا جامعیت کل آرشیو داوری نمی‌کند.</p>';
}
function populateResearch(){var el=document.getElementById('atlasResearchOutput');if(el)el.innerHTML=researchHtml(S.rQuery,researchModel(S.rQuery))}
window.atlasResearchInput=function(v){S.rQuery=v;populateResearch()};
window.atlasResearchExport=function(){var m=researchModel(S.rQuery);var payload={subject:S.rQuery,generated_at:new Date().toISOString(),source:'Velayat Live Monitor public archive',episodes:m.episodes.map(p=>({id:p.id,program:name(p),date:p.date_iso,title:p.topic,expert:expert(p),url:location.origin+location.pathname+detailHash(p.id)})),axes:m.axes.map(x=>({title:x.title,pid:x.pid,start:x.start})),questions:m.qs.map(x=>({question:x.title,pid:x.pid}))};saveFile('atlas-research.json',JSON.stringify(payload,null,2),'application/json')};
function patchFor(id){return Object.assign({},S.published[id]||{},S.preview?(S.draft[id]||{}):{})}
function applyEdits(){if(!programs.length)return;programs=programs.map(function(p){var patch=patchFor(p.id),out=Object.assign({},p);allowed.forEach(k=>{if(Object.prototype.hasOwnProperty.call(patch,k)&&((Array.isArray(patch[k]))||typeof patch[k]==='string'))out[k]=patch[k]});return out})}
function draftLoad(){try{return JSON.parse(localStorage.getItem('atlas-public-drafts-v1')||'{}')}catch(e){return {}}}
S.draft=draftLoad();try{S.sQuery=new URLSearchParams(location.search).get('q')||''}catch(e){}
async function loadPublished(){try{var u=new URL('../atlas/overrides.json',location.href);var r=await fetch(u.href,{cache:'no-store'});if(!r.ok)return;var d=await r.json();if(d&&d.schema===1&&d.episodes&&typeof d.episodes==='object'){S.published=d.episodes;S.publishedPhotos=d.expert_photos||{};if(d.expert_photos&&typeof d.expert_photos==='object'){Object.entries(d.expert_photos).forEach(function(x){var url=safeUrl(x[1]);if(url&&url.startsWith('https://'))photos[photoKey(x[0])]=url})}applyEdits();render()}}catch(e){/* no published overrides is supported */}}
function editorPage(){
 var options=programs.map(p=>'<option value="'+E(p.id)+'">'+E(name(p))+' · '+E(p.date||p.date_iso)+' · '+E((p.topic||'').slice(0,65))+'</option>').join('');
 return '<section class="atlas-searchhero"><h2>میز مدیریت محتوای اطلس</h2><p>اصلاح عنوان و خلاصه، بازبینی پیش‌نویس، بررسی آرشیو و تهیه بسته انتشار. داده اصلی دیدبان دست‌نخورده می‌ماند.</p>'+
 '<p class="atlas-warning">نسخه عمومی GitHub Pages قابلیت احراز هویت مدیر و نوشتن امن ندارد. تغییرات این صفحه ابتدا پیش‌نویس محلی هستند؛ برای انتشار پایدار، فایل خروجی را پس از بازبینی در مخزن GitHub ثبت کنید. هیچ کلید یا توکنی در این صفحه وارد نکنید.</p></section>'+
 '<div class="atlas-editor-card"><h2>ویرایش پرونده قسمت</h2><label>انتخاب قسمت موجود</label><select class="atlas-input" id="atlasEditSelect" onchange="atlasLoadEditor()">'+options+'</select>'+
 '<label>عنوان و موضوع اصلی</label><input class="atlas-input" id="atlasEditTopic">'+
 '<label>نام کارشناس</label><input class="atlas-input" id="atlasEditExpert">'+
 '<label>نام مجری</label><input class="atlas-input" id="atlasEditHost">'+
 '<label>خلاصه برنامه</label><textarea class="atlas-input" id="atlasEditSummary"></textarea>'+ 
 '<label>برچسب‌ها (با ویرگول جدا شوند)</label><input class="atlas-input" id="atlasEditTags">'+
 '<label>محورهای زمان‌دار (آرایه JSON)</label><textarea class="atlas-input" id="atlasEditAxes"></textarea>'+
 '<label>پرسش‌وپاسخ‌ها (آرایه JSON)</label><textarea class="atlas-input" id="atlasEditQas"></textarea>'+
 '<label>تقطیع‌های پیشنهادی (آرایه JSON)</label><textarea class="atlas-input" id="atlasEditClips"></textarea>'+
 '<div class="atlas-search-row">'+actionBtn('ذخیره پیش‌نویس','atlasSaveDraft()','active')+actionBtn('پیش‌نمایش اصلاحات','atlasPreviewDraft()')+actionBtn('لغو پیش‌نمایش','atlasStopPreview()')+actionBtn('خروجی قابل انتشار','atlasExportPatch()')+'</div><p class="muted" id="atlasDraftCount"></p></div>'+
 '<section class="atlas-editor-card"><h2>ورود و بررسی آرشیو تاریخی</h2><p class="muted">فایل JSON یا CSV را فقط در همین مرورگر بررسی کنید. فایل TXT بدون ساختار، خودکار به برنامه یا پرسش تبدیل نمی‌شود.</p><input type="file" class="atlas-input" id="atlasImportFile" accept=".json,.csv,.txt,application/json,text/csv,text/plain" onchange="atlasInspectArchive(this)"><div id="atlasImportReport" class="muted"></div></section>'+
 '<section class="atlas-editor-card"><h2>انتشار پایدار و کنترل نسخه</h2><p>بسته خروجی را پس از بازبینی در <b>docs/atlas/overrides.json</b> ادغام کنید. این فایل جدا از خروجی‌های دیدبان است و با هر به‌روزرسانی برنامه‌ها پاک نمی‌شود.</p><a class="button" href="https://github.com/sey3d-m/velayat-live-monitor/edit/main/docs/atlas/overrides.json" target="_blank" rel="noopener noreferrer">بازکردن فایل اصلاحات در گیت‌هاب</a><p class="muted">برای سطح مدیریت امن و انتشار یک‌مرحله‌ای، یک سرویس مجزا با احراز هویت و ثبت تغییرات لازم است؛ در نسخه ایستا این قابلیت فعال نیست.</p></section>';
}
window.atlasLoadEditor=function(){
 var id=document.getElementById('atlasEditSelect')?.value,p=get(id);if(!p)return;var vals=Object.assign({},S.published[id]||{},S.draft[id]||{});
 [['Topic','topic'],['Expert','expert'],['Host','host'],['Summary','summary']].forEach(function(x){var e=document.getElementById('atlasEdit'+x[0]);if(e)e.value=vals[x[1]]??p[x[1]]??''});
 document.getElementById('atlasEditTags').value=(vals.hashtags??p.hashtags??[]).join('، ');
 [['Axes','key_points'],['Qas','questions'],['Clips','clips']].forEach(function(x){document.getElementById('atlasEdit'+x[0]).value=JSON.stringify(vals[x[1]]??p[x[1]]??[],null,2)});
 var c=document.getElementById('atlasDraftCount');if(c)c.textContent=fmt(Object.keys(S.draft).length)+' پرونده دارای پیش‌نویس';
};
window.atlasSaveDraft=function(){
 var id=document.getElementById('atlasEditSelect')?.value;if(!id)return;var patch={topic:document.getElementById('atlasEditTopic').value.trim(),expert:document.getElementById('atlasEditExpert').value.trim(),host:document.getElementById('atlasEditHost').value.trim(),summary:document.getElementById('atlasEditSummary').value.trim()};
 patch.hashtags=document.getElementById('atlasEditTags').value.split(/[,،]/).map(x=>x.trim()).filter(Boolean);
 for(var row of [['Axes','key_points'],['Qas','questions'],['Clips','clips']]){try{var parsed=JSON.parse(document.getElementById('atlasEdit'+row[0]).value.trim()||'[]');if(!Array.isArray(parsed))throw Error('آرایه لازم است');patch[row[1]]=parsed}catch(e){return toast('فرمت JSON بخش '+row[0]+' معتبر نیست: '+e.message)}}
 S.draft[id]=patch;try{localStorage.setItem('atlas-public-drafts-v1',JSON.stringify(S.draft));toast('پیش‌نویس در مرورگر ذخیره شد')}catch(e){toast('امکان ذخیره پیش‌نویس در مرورگر نیست')}window.atlasLoadEditor();
};
window.atlasPreviewDraft=function(){S.preview=true;applyEdits();toast('پیش‌نمایش فعال است؛ هنوز در سایت منتشر نشده است')};
window.atlasStopPreview=function(){S.preview=false;toast('پیش‌نمایش خاموش شد؛ برای بازیابی داده اولیه صفحه را تازه‌سازی کنید')};
window.atlasExportPatch=function(){
 var payload={schema:1,updated_at:new Date().toISOString(),episodes:Object.assign({},S.published,S.draft),expert_photos:S.publishedPhotos};
 saveFile('velayat-atlas-overrides.json',JSON.stringify(payload,null,2),'application/json');
 toast('بسته اصلاحات برای بازبینی و انتشار دریافت شد');
};
window.atlasInspectArchive=async function(input){
 var f=input.files?.[0],out=document.getElementById('atlasImportReport');if(!f||!out)return;
 if(f.size>12e6){out.textContent='حجم فایل بیش از حد مجاز بررسی مرورگر است.';return}
 var raw=await f.text(),rows=[];
 try{
  if(/\.json$/i.test(f.name)){var v=JSON.parse(raw);rows=Array.isArray(v)?v:Array.isArray(v.programs)?v.programs:Array.isArray(v.items)?v.items:[]}
  else if(/\.csv$/i.test(f.name)){var lines=raw.replace(/\r/g,'').split('\n').filter(Boolean),fields=lines.shift().split(',');rows=lines.map(l=>{var vs=l.split(','),o={};fields.forEach((k,i)=>o[k.trim()]=vs[i]);return o})}
  else{out.innerHTML='<div class="atlas-warning">متن فاقد ساختار JSON/CSV است؛ برای جلوگیری از تولید داده ساختگی، نمایه‌سازی خودکار انجام نشد.</div>';return}
  var seen=new Set(programs.map(x=>x.id)),ids=new Set(),dup=0,conflict=0,missing=0;
  rows.forEach(function(r){var id=String(r.id||'');if(!id)missing++;else if(seen.has(id)||ids.has(id))dup++;if(id&&seen.has(id)){var old=get(id);if(r.summary&&old?.summary&&N(r.summary)!==N(old.summary))conflict++}if(id)ids.add(id)});
  S.archiveReport={source:f.name,count:rows.length,duplicates:dup,conflicts:conflict,missing:missing};
  out.innerHTML='<p>بررسی فایل «'+E(f.name)+'»: '+fmt(rows.length)+' ردیف؛ '+fmt(dup)+' شناسه تکراری؛ '+fmt(conflict)+' اختلاف خلاصه؛ '+fmt(missing)+' ردیف فاقد شناسه.</p><div class="atlas-warning">فایل صرفاً بررسی شد و هنوز وارد آرشیو عمومی نشده است. ردیف‌ها باید از نظر اعتبار، مجوز انتشار و تکرار ارزیابی شوند.</div>';
 }catch(e){out.textContent='فایل قابل پردازش نیست: '+e.message}
};

function atlasTimeSpan(x){
 var a=Number(x.start_sec),b=Number(x.end_sec);
 return (Number.isFinite(a)&&Number.isFinite(b)&&b>a)?Math.max(0,b-a):0;
}
function atlasTimelineDetail(p,kind,i){
 var x=kind==='qa'?qa(p)[i]:topics(p)[i];if(!x)return '<p>مورد انتخابی در گزارش موجود نیست.</p>';
 var a=Number(x.start_sec),b=Number(x.end_sec),time=Number.isFinite(a)&&a>=0?hhmm(a):'زمان ثبت نشده',d=atlasTimeSpan(x);
 var title=kind==='qa'?x.question:x.title,desc=kind==='qa'?(x.answer||'پاسخی در گزارش موجود نیست'):'عنوان این محور مطابق گزارش ساختاریافته دیدبان است؛ متن کامل این بخش در آرشیو عمومی فعلی ثبت نشده است.';
 return '<span class="eyebrow">'+(kind==='qa'?'◉ پرسش و پاسخ ثبت‌شده':'✦ محور علمی انتخاب‌شده')+'</span>'+
 '<strong>'+E(title||'بدون عنوان')+'</strong>'+
 '<p>'+E(desc)+'</p><div class="atlas-time-key"><span>⏱ '+E(time)+(d?' — '+hhmm(b):'')+'</span>'+
 (d?'<span>مدت: '+hhmm(d)+'</span>':'')+'<span>منبع: گزارش خودکار دیدبان</span></div>';
}
function timelinePlus(p){
 var axes=topics(p),questions=qa(p);
 var valid=axes.filter(x=>atlasTimeSpan(x)),qtime=questions.filter(x=>Number.isFinite(Number(x.start_sec))&&Number(x.start_sec)>=0);
 var total=Math.max(3600,...axes.map(x=>Number(x.end_sec)||0),...questions.map(x=>Number(x.end_sec)||0));
 var palette=[['#198b80','#17616b'],['#38669f','#1d6081'],['#438b6d','#24675d'],['#987a43','#6a5531'],['#556fa9','#405586'],['#6c7897','#315a75'],['#5b8c87','#30717c']];
 var ticks=[0,.25,.5,.75,1].map(x=>'<span>'+hhmm(Math.round(total*x))+'</span>').join('');
 var segments=axes.map(function(x,i){
  if(!atlasTimeSpan(x))return '';
  var s=Math.max(0,Number(x.start_sec)),b=Math.max(s,Number(x.end_sec));
  var left=(s/total*100),width=Math.max(.4,Math.min(100-left,(b-s)/total*100)),c=palette[i%palette.length];
  return '<button class="atlas-time-segment '+(i===0?'selected':'')+'" data-atlas-idx="'+i+'" style="left:'+left.toFixed(3)+'%;width:'+width.toFixed(3)+'%;--seg1:'+c[0]+';--seg2:'+c[1]+'" onclick="atlasTimelineSelect('+i+')" title="'+E(x.title)+' · '+hhmm(s)+' تا '+hhmm(b)+'" aria-label="محور '+(i+1)+': '+E(x.title)+'"><span>'+(width>13?E(x.title):'')+'</span></button>';
 }).join('');
 var markers=questions.map(function(x,i){
  var s=Number(x.start_sec);if(!Number.isFinite(s)||s<0)return '';
  var left=Math.max(0,Math.min(99,s/total*100));
  return '<button class="atlas-time-qa" style="left:'+left.toFixed(3)+'%" onclick="atlasTimelineQA('+i+')" title="'+E(x.question)+'" aria-label="پرسش مخاطب: '+E(x.question)+'">؟</button>';
 }).join('');
 var chapters=axes.map(function(x,i){
  var time=Number.isFinite(Number(x.start_sec))&&x.start_sec!==undefined?hhmm(x.start_sec):'—';
  var end=atlasTimeSpan(x)?hhmm(x.end_sec):'—';
  return '<button class="atlas-chapter '+(i===0?'active':'')+'" data-atlas-idx="'+i+'" onclick="atlasTimelineSelect('+i+')" aria-label="انتخاب محور '+(i+1)+'"><span class="atlas-chapter-num">'+fmt(i+1)+'</span><span class="atlas-chapter-copy"><span class="atlas-chapter-title">'+E(x.title)+'</span><span class="atlas-chapter-range">'+time+' — '+end+'</span></span></button>';
 }).join('');
 var firstStart=Number(axes[0]?.start_sec)||0;
 return '<section class="atlas-time-shell" id="atlasTimeline" data-program="'+E(p.id)+'">'+
 '<div class="atlas-time-head"><div><span class="atlas-time-eyebrow">VELAYAT / SCIENTIFIC TIME NAVIGATOR</span><h3>نقشه زمانی گفت‌وگو</h3><p class="atlas-time-description">نقاط زمانی دقیقِ ثبت‌شده برای این قسمت؛ هر بخش و پرسش را انتخاب کنید.</p></div>'+
 '<div class="atlas-time-total">◷ '+hhmm(total)+' <span style="direction:rtl;color:#a9c6c6;font-size:10px">بازه نمایش</span></div></div>'+
 '<div class="atlas-time-ruler">'+ticks+'</div>'+
 '<div class="atlas-time-track" aria-label="خط زمانی محورها"><div class="atlas-time-row">'+segments+'</div>'+markers+
 '<span id="atlasTimelinePlayhead" class="atlas-time-playhead" style="left:'+(firstStart/total*100).toFixed(2)+'%"></span></div>'+
 '<div class="atlas-time-bottom"><div class="atlas-time-key"><span><i style="background:#56b8ae"></i>محور علمی</span><span><i style="background:#c392e6;border-radius:100%"></i>پرسش مخاطب</span><span>'+fmt(valid.length)+' محور زمان‌دار / '+fmt(qtime.length)+' پرسش زمان‌دار</span></div>'+
 '<div class="atlas-time-navigation"><button onclick="atlasTimelineStep(-1)">❮ محور قبل</button><button onclick="atlasTimelineStep(1)">محور بعد ❯</button></div></div>'+
 '<div class="atlas-chapter-head"><b>فصل‌های این برنامه</b><small>'+fmt(axes.length)+' محور از گزارش دیدبان</small></div>'+
 '<div class="atlas-chapter-grid">'+chapters+'</div>'+
 '<div id="atlasTimelineInsight" class="atlas-time-detail">'+atlasTimelineDetail(p,'topic',0)+'</div>'+
 '<p class="atlas-time-legend-note">عنوان‌ها و زمان‌کدها از گزارش موجود استخراج شده‌اند. انتخاب یک بخش به‌معنای وجود ویدیوی قابل پخش در همان لحظه نیست.</p></section>';
}
window.atlasTimelineSelect=function(i){
 var el=document.getElementById('atlasTimeline');if(!el)return;
 var p=get(el.dataset.program),axes=p&&topics(p);if(!p||!axes?.[i])return;
 i=Number(i);currentTopic=i;
 var total=Math.max(3600,...axes.map(x=>Number(x.end_sec)||0),...qa(p).map(x=>Number(x.end_sec)||0));
 var info=document.getElementById('atlasTimelineInsight');if(info)info.innerHTML=atlasTimelineDetail(p,'topic',i);
 var head=document.getElementById('atlasTimelinePlayhead');
 if(head)head.style.left=(Math.max(0,Number(axes[i].start_sec)||0)/total*100).toFixed(2)+'%';
 el.querySelectorAll('.atlas-chapter').forEach(x=>x.classList.toggle('active',Number(x.dataset.atlasIdx)===i));
 el.querySelectorAll('.atlas-time-segment').forEach(x=>x.classList.toggle('selected',Number(x.dataset.atlasIdx)===i));
 el.querySelectorAll('.atlas-time-qa').forEach(x=>x.classList.remove('selected'));
};
window.atlasTimelineQA=function(i){
 var el=document.getElementById('atlasTimeline');if(!el)return;var p=get(el.dataset.program),q=p&&qa(p)[i];if(!q)return;
 var info=document.getElementById('atlasTimelineInsight');if(info)info.innerHTML=atlasTimelineDetail(p,'qa',i);
 var total=Math.max(3600,...topics(p).map(x=>Number(x.end_sec)||0),...qa(p).map(x=>Number(x.end_sec)||0));
 var head=document.getElementById('atlasTimelinePlayhead');if(head)head.style.left=(Math.max(0,Number(q.start_sec)||0)/total*100).toFixed(2)+'%';
 el.querySelectorAll('.atlas-time-segment').forEach(x=>x.classList.remove('selected'));
 el.querySelectorAll('.atlas-chapter').forEach(x=>x.classList.remove('active'));
 el.querySelectorAll('.atlas-time-qa').forEach(x=>x.classList.remove('selected'));
 var button=el.querySelectorAll('.atlas-time-qa')[qa(p).slice(0,i+1).filter(x=>Number.isFinite(Number(x.start_sec))&&Number(x.start_sec)>=0).length-1];
 if(button)button.classList.add('selected');
};
window.atlasTimelineStep=function(direction){
 var el=document.getElementById('atlasTimeline');if(!el)return;
 var p=get(el.dataset.program);if(!p)return;
 var axes=topics(p);if(!axes.length)return;
 var current=el.querySelector('.atlas-chapter.active');
 var i=current?Number(current.dataset.atlasIdx):0;
 window.atlasTimelineSelect(Math.min(axes.length-1,Math.max(0,i+direction)));
};
timeline=timelinePlus;

render=function(){
 applyEdits();
 var hash=decodeURIComponent(location.hash||'#/');
 if(hash.startsWith('#/show/')){var gp=hash.slice(7);document.getElementById('app').innerHTML=showPage(gp);document.getElementById('bread').textContent=gp;document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('on',x.dataset.view==='programs'));return;}
 if(hash==='#/search'||hash==='#/research'||hash==='#/editor'){
  var view=hash.slice(2),title={search:'جست‌وجوی جامع',research:'میز پژوهش و برنامه‌سازی',editor:'مدیریت اطلس'}[view];
  document.getElementById('app').innerHTML=view==='search'?searchPage():view==='research'?researchPage():editorPage();
  var bread=document.getElementById('bread');if(bread)bread.textContent=title;
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('on',x.dataset.view===view));
  if(view==='search')populateSearch();if(view==='research')populateResearch();if(view==='editor')window.atlasLoadEditor();
  return;
 }
 originals.render(); // resetGraph in the original renderer mounts the upgraded graph exactly once
};
installNavigation();
window.addEventListener('keydown',function(ev){if(ev.key==='Escape'){var p=document.querySelector('.atlas-view-full');if(p)window.atlasFullscreen()}});
loadPublished();
if(programs.length)render();
})();