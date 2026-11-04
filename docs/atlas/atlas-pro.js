
/* Velayat Atlas Pro — read-only extension for the existing Didban atlas.
   No AI model, audio, overlay, scheduler or production workflow is called. */
(function(){
'use strict';
var S={group:'',episode:'',selected:'root',graphSearch:'',sQuery:'',sProgram:'',sType:'all',sView:'cards',sSort:'relevance',rQuery:'',draft:{},published:{},preview:false,archiveReport:null};
var NS='http://www.w3.org/2000/svg',stage=null,world=null,animation=0,nodeViews=[],linkViews=[],model=null,cam={x:0,y:0,k:1},drag=null,quiet=matchMedia('(prefers-reduced-motion: reduce)').matches;
var allowed=['topic','summary','expert','host','hashtags','key_points','clips'];
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
 return section('نقشه زنده ارتباطات علمی','از شبکه ولایت تا مجموعه‌برنامه، قسمت، کارشناس، محور و پرسش؛ تمام پیوندها از داده موجود ساخته شده‌اند',
 '<button class="button small" onclick="go(\'#/search\')">⌕ جست‌وجوی همه محتوا</button>')+
 '<section class="atlas-panel" id="graphAnchor"><div class="atlas-head"><div><h3>منظومه هوشمند ولایت</h3><p>برنامه را انتخاب کنید؛ سپس وارد قسمت و محور علمی شوید</p></div><div class="atlas-actions">'+
 actionBtn('نمای کل','atlasSelectRoot()')+(S.graphSearch?actionBtn('پاک‌کردن فیلتر','atlasClearGraphQuery()'):'')+actionBtn('موضوعات مرتبط','atlasGraphTopic()')+
 actionBtn('＋','atlasZoom(1.16)')+actionBtn('−','atlasZoom(.86)')+
 actionBtn('⤢','atlasReset()')+actionBtn('⛶ تمام‌صفحه','atlasFullscreen()')+
 '</div></div><div class="atlas-graph-layout"><div class="atlas-stage" id="atlasStage"><svg id="atlasSvg" viewBox="0 0 1200 700" aria-label="نقشه تعاملی ارتباطات علمی ولایت" role="img"><g id="atlasWorld"></g></svg><div class="atlas-pins">◉ مرکز شبکه · ◇ برنامه · ● قسمت · ✦ محور | حرکت و بزرگ‌نمایی با ماوس</div></div><aside class="atlas-inspector" id="atlasInspector"></aside></div></section>';
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
 if(animation)cancelAnimationFrame(animation);animation=0;nodeViews=[];linkViews=[];cam={x:0,y:0,k:1};
 world=document.getElementById('atlasWorld');if(!world)return;world.replaceChildren();model=buildGraph();
 var ring=svg('g',{},world);[110,230,355].forEach(r=>svg('circle',{class:'atlas-grid-orbit',cx:600,cy:345,r:r},ring));
 var layer=svg('g',{},world),nodesLayer=svg('g',{},world);
 model.edges.forEach(function(l){var path=svg('path',{class:'atlas-edge'},layer);linkViews.push({edge:l,el:path})});
 model.nodes.forEach(function(n,i){
  var g=svg('g',{class:'atlas-node '+n.kind+(S.selected===n.id?' active':''),role:'button',tabindex:0,'aria-label':n.kind+' '+n.label},nodesLayer);
  svg('circle',{class:'primary',cx:0,cy:0,r:n.r},g);
  if(n.kind==='root'){svg('circle',{cx:0,cy:0,r:61,fill:'none',stroke:'#e9c48266','stroke-dasharray':'3 9'},g)}
  var t=svg('text',{class:'nlabel','text-anchor':'middle',y:n.r+18},g);t.textContent=labelShort(n.label,n.kind==='root'?30:24);
  var sub=svg('text',{class:'nsub','text-anchor':'middle',y:n.r+33},g);sub.textContent=labelShort(n.sub||'',28);
  g.addEventListener('click',function(ev){ev.stopPropagation();if(drag&&drag.moved)return;atlasPick(n.id)});
  g.addEventListener('keydown',function(ev){if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();atlasPick(n.id)}});
  nodeViews.push({n:n,el:g,i:i});
 });
 var svgEl=document.getElementById('atlasSvg');
 svgEl.onpointerdown=function(ev){if(ev.button!==0||ev.target.closest('.atlas-node'))return;drag={x:ev.clientX,y:ev.clientY,ox:cam.x,oy:cam.y,moved:false,id:ev.pointerId};svgEl.setPointerCapture(ev.pointerId);svgEl.classList.add('dragging')};
 svgEl.onpointermove=function(ev){if(!drag)return;var dx=ev.clientX-drag.x,dy=ev.clientY-drag.y;if(Math.abs(dx)+Math.abs(dy)>4)drag.moved=true;cam.x=drag.ox+dx*1200/Math.max(1,svgEl.clientWidth);cam.y=drag.oy+dy*700/Math.max(1,svgEl.clientHeight);setCamera()};
 svgEl.onpointerup=svgEl.onpointercancel=function(){drag=null;svgEl.classList.remove('dragging')};
 svgEl.onwheel=function(ev){ev.preventDefault();cam.k=Math.max(.58,Math.min(2.5,cam.k*(ev.deltaY<0?1.09:.91)));setCamera()};
 inspect();
 function frame(t){if(!document.getElementById('atlasStage')||document.getElementById('atlasWorld')!==world){animation=0;return}
  nodeViews.forEach(function(o){var wobble=quiet?0:(o.n.kind==='root'?0:Math.sin(t/1300+o.i*1.4)*2.7);o.el.setAttribute('transform','translate('+o.n.x+' '+(o.n.y+wobble)+')');});
  linkViews.forEach(function(o){var a=model.map.get(o.edge.a),b=model.map.get(o.edge.b);if(a&&b){var dyA=quiet?0:Math.sin(t/1300+model.nodes.indexOf(a)*1.4)*2.7,dyB=quiet?0:Math.sin(t/1300+model.nodes.indexOf(b)*1.4)*2.7;
   o.el.setAttribute('d','M'+a.x+' '+(a.y+dyA)+' L'+b.x+' '+(b.y+dyB));
   o.el.setAttribute('class','atlas-edge'+((S.selected===o.edge.a||S.selected===o.edge.b)?' highlight':''));
  }});
  if(!quiet)animation=requestAnimationFrame(frame);
 }
 frame(0);
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
 if(n.kind==='program'){var a=programs.filter(p=>name(p)===n.group);type='مجموعه برنامه';meta=fmt(a.length)+' قسمت · '+fmt(unique(a.map(expert)).length)+' کارشناس';desc='قسمت‌های ثبت‌شده در این مجموعه و محورهای هر قسمت را می‌توانید بررسی کنید.';buttons=actionBtn('مشاهده همه قسمت‌ها','go(\'#/programs\')')}
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
 '<select class="atlas-select" aria-label="مرتب‌سازی" onchange="atlasSearchFilter(\'sort\',this.value)"><option value="relevance" '+(S.sSort==='relevance'?'selected':'')+'>مرتبط‌ترین</option><option value="date" '+(S.sSort==='date'?'selected':'')+'>جدیدترین</option></select></div>'+
 '<div class="atlas-sug">'+suggestions.map(x=>'<button onclick="atlasSearchSuggestion(this.textContent)">'+E(x.replace(/_/g,' '))+'</button>').join('')+'</div></section>'+
 '<div class="atlas-toolbar"><span class="atlas-count" id="atlasResultCount"></span><div class="atlas-actions">'+actionBtn('نمای کارت','atlasView(\'cards\')',S.sView==='cards'?'active':'')+actionBtn('نمای پژوهشی','atlasView(\'list\')',S.sView==='list'?'active':'')+actionBtn('نمای شبکه نتایج','atlasGraphFromSearch()')+actionBtn('کپی جست‌وجو','atlasCopySearch()')+'</div></div><div id="atlasResultList" class="atlas-result-grid"></div>';
}
function populateSearch(){
 var container=document.getElementById('atlasResultList');if(!container)return;
 var rs=results(S.sQuery,{program:S.sProgram,type:S.sType,sort:S.sSort});
 container.className='atlas-result-grid '+(S.sView==='list'?'list':'');
 var countNode=document.getElementById('atlasResultCount');if(countNode)countNode.textContent=fmt(rs.length)+' نتیجه در آرشیو فعلی';
 container.innerHTML=rs.length?rs.slice(0,160).map(resultCard).join(''):'<div class="empty">برای این عبارت در آرشیو فعلی نتیجه‌ای وجود ندارد.</div>';
 if(rs.length>160)container.insertAdjacentHTML('beforeend','<div class="muted">۱۶۰ نتیجه نخست نمایش داده شده است؛ جست‌وجو را دقیق‌تر کنید.</div>');
}
window.atlasGraphFromSearch=function(){if(!S.sQuery.trim())return toast('ابتدا عبارت جست‌وجو را وارد کنید');S.graphSearch=S.sQuery;S.group='';S.episode='';S.selected='root';go('#/');setTimeout(function(){document.getElementById('graphAnchor')?.scrollIntoView({behavior:'smooth'})},80)};
window.atlasSearchInput=function(v){S.sQuery=v;populateSearch()};
window.atlasSearchSuggestion=function(v){S.sQuery=v;document.getElementById('atlasQuery').value=v;populateSearch()};
window.atlasSearchFilter=function(k,v){if(k==='program')S.sProgram=v;if(k==='type')S.sType=v;if(k==='sort')S.sSort=v;populateSearch()};
window.atlasView=function(v){S.sView=v;populateSearch();document.querySelectorAll('.atlas-toolbar button').forEach(b=>b.classList.toggle('active',b.textContent.includes(v==='cards'?'کارت':'پژوهشی')))};
window.atlasCopySearch=function(){var url=location.href; if(navigator.clipboard)navigator.clipboard.writeText(url).then(()=>toast('آدرس این صفحه کپی شد'));else prompt('نشانی',url)};
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
S.draft=draftLoad();
async function loadPublished(){try{var u=new URL('../atlas/overrides.json',location.href);var r=await fetch(u.href,{cache:'no-store'});if(!r.ok)return;var d=await r.json();if(d&&d.schema===1&&d.episodes&&typeof d.episodes==='object'){S.published=d.episodes;applyEdits();render()}}catch(e){/* no published overrides is supported */}}
function editorPage(){
 var options=programs.map(p=>'<option value="'+E(p.id)+'">'+E(name(p))+' · '+E(p.date||p.date_iso)+' · '+E((p.topic||'').slice(0,65))+'</option>').join('');
 return '<section class="atlas-searchhero"><h2>میز مدیریت محتوای اطلس</h2><p>اصلاح عنوان و خلاصه، بازبینی پیش‌نویس، بررسی آرشیو و تهیه بسته انتشار. داده اصلی دیدبان دست‌نخورده می‌ماند.</p>'+
 '<p class="atlas-warning">نسخه عمومی GitHub Pages قابلیت احراز هویت مدیر و نوشتن امن ندارد. تغییرات این صفحه ابتدا پیش‌نویس محلی هستند؛ برای انتشار پایدار، فایل خروجی را پس از بازبینی در مخزن GitHub ثبت کنید. هیچ کلید یا توکنی در این صفحه وارد نکنید.</p></section>'+
 '<div class="atlas-editor-card"><h2>ویرایش پرونده قسمت</h2><label>انتخاب قسمت موجود</label><select class="atlas-input" id="atlasEditSelect" onchange="atlasLoadEditor()">'+options+'</select>'+
 '<label>عنوان و موضوع اصلی</label><input class="atlas-input" id="atlasEditTopic">'+
 '<label>نام کارشناس</label><input class="atlas-input" id="atlasEditExpert">'+
 '<label>نام مجری</label><input class="atlas-input" id="atlasEditHost">'+
 '<label>خلاصه برنامه</label><textarea class="atlas-input" id="atlasEditSummary"></textarea>'+
 '<div class="atlas-search-row">'+actionBtn('ذخیره پیش‌نویس','atlasSaveDraft()','active')+actionBtn('پیش‌نمایش اصلاحات','atlasPreviewDraft()')+actionBtn('لغو پیش‌نمایش','atlasStopPreview()')+actionBtn('خروجی قابل انتشار','atlasExportPatch()')+'</div><p class="muted" id="atlasDraftCount"></p></div>'+
 '<section class="atlas-editor-card"><h2>ورود و بررسی آرشیو تاریخی</h2><p class="muted">فایل JSON یا CSV را فقط در همین مرورگر بررسی کنید. فایل TXT بدون ساختار، خودکار به برنامه یا پرسش تبدیل نمی‌شود.</p><input type="file" class="atlas-input" id="atlasImportFile" accept=".json,.csv,.txt,application/json,text/csv,text/plain" onchange="atlasInspectArchive(this)"><div id="atlasImportReport" class="muted"></div></section>'+
 '<section class="atlas-editor-card"><h2>انتشار پایدار و کنترل نسخه</h2><p>بسته خروجی را پس از بازبینی در <b>docs/atlas/overrides.json</b> ادغام کنید. این فایل جدا از خروجی‌های دیدبان است و با هر به‌روزرسانی برنامه‌ها پاک نمی‌شود.</p><a class="button" href="https://github.com/sey3d-m/velayat-live-monitor/edit/main/docs/atlas/overrides.json" target="_blank" rel="noopener noreferrer">بازکردن فایل اصلاحات در گیت‌هاب</a><p class="muted">برای سطح مدیریت امن و انتشار یک‌مرحله‌ای، یک سرویس مجزا با احراز هویت و ثبت تغییرات لازم است؛ در نسخه ایستا این قابلیت فعال نیست.</p></section>';
}
window.atlasLoadEditor=function(){
 var id=document.getElementById('atlasEditSelect')?.value,p=get(id);if(!p)return;var vals=patchFor(id);
 [['Topic','topic'],['Expert','expert'],['Host','host'],['Summary','summary']].forEach(function(x){var e=document.getElementById('atlasEdit'+x[0]);if(e)e.value=vals[x[1]]??p[x[1]]??''});
 var c=document.getElementById('atlasDraftCount');if(c)c.textContent=fmt(Object.keys(S.draft).length)+' پرونده دارای پیش‌نویس';
};
window.atlasSaveDraft=function(){
 var id=document.getElementById('atlasEditSelect')?.value;if(!id)return;var patch={topic:document.getElementById('atlasEditTopic').value.trim(),expert:document.getElementById('atlasEditExpert').value.trim(),host:document.getElementById('atlasEditHost').value.trim(),summary:document.getElementById('atlasEditSummary').value.trim()};
 S.draft[id]=patch;try{localStorage.setItem('atlas-public-drafts-v1',JSON.stringify(S.draft));toast('پیش‌نویس در مرورگر ذخیره شد')}catch(e){toast('امکان ذخیره پیش‌نویس در مرورگر نیست')}window.atlasLoadEditor();
};
window.atlasPreviewDraft=function(){S.preview=true;applyEdits();toast('پیش‌نمایش فعال است؛ هنوز در سایت منتشر نشده است')};
window.atlasStopPreview=function(){S.preview=false;toast('پیش‌نمایش خاموش شد؛ برای بازیابی داده اولیه صفحه را تازه‌سازی کنید')};
window.atlasExportPatch=function(){
 var payload={schema:1,updated_at:new Date().toISOString(),episodes:Object.assign({},S.published,S.draft)};
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
function timelinePlus(p){
 var seg=originals.timeline(p),q=qa(p).filter(x=>Number.isFinite(Number(x.start_sec))&&Number(x.start_sec)>=0);
 var durationMax=Math.max(3600,...topics(p).map(t=>+t.end_sec||0),...q.map(t=>+t.end_sec||0));
 var dots=q.map(x=>'<span class="atlas-qa-marker" style="right:'+(Math.min(99,Math.max(0,Number(x.start_sec)/durationMax*100)))+'%" title="'+E(x.question)+'"></span>').join('');
 seg=seg.replace(/(<div class="time-track"[^>]*>)/,'$1'+dots);
 return '<div class="atlas-timeline-key">قطعات سبز: محورهای گفتگو · نشان بنفش: پرسش مخاطب · زمان‌ها از گزارش دیدبان</div>'+seg;
}
timeline=timelinePlus;
render=function(){
 applyEdits();
 var hash=decodeURIComponent(location.hash||'#/');
 if(hash==='#/search'||hash==='#/research'||hash==='#/editor'){
  var view=hash.slice(2),title={search:'جست‌وجوی جامع',research:'میز پژوهش و برنامه‌سازی',editor:'مدیریت اطلس'}[view];
  document.getElementById('app').innerHTML=view==='search'?searchPage():view==='research'?researchPage():editorPage();
  var bread=document.getElementById('bread');if(bread)bread.textContent=title;
  document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('on',x.dataset.view===view));
  if(view==='search')populateSearch();if(view==='research')populateResearch();if(view==='editor')window.atlasLoadEditor();
  return;
 }
 originals.render();
 if(hash==='#/'||hash==='#')mountGraph();
};
installNavigation();
window.addEventListener('keydown',function(ev){if(ev.key==='Escape'){var p=document.querySelector('.atlas-view-full');if(p)window.atlasFullscreen()}});
loadPublished();
if(programs.length)render();
})();