/** Didban editor-only Bale webhook, Cloudflare Workers Free + D1.
 * No video, monitoring, recording, clipping, dubbing or main timetable execution.
 * Deploy separately. DO NOT switch Bale from polling until real verification.
 */
const MAIN = [
  ['➕ افزودن برنامه', '📋 برنامه‌ها'], ['📅 تقویم هفته', '⏸ توقف برنامه'],
  ['▶️ فعال‌سازی برنامه','🗑 حذف برنامه'], ['📆 لغو یک نوبت','🔄 بازگرداندن نوبت'],
  ['ℹ️ راهنما','🆔 شناسه من']
];
const HOME='🏠 منوی اصلی', CANCEL='❌ انصراف', CONFIRM='✅ تأیید نهایی';
const DAYS=['شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه'];
const SELECT={'⏸ توقف برنامه':'pause','▶️ فعال‌سازی برنامه':'resume','🗑 حذف برنامه':'delete','📆 لغو یک نوبت':'skip','🔄 بازگرداندن نوبت':'unskip'};
const FREQ={'🔹 یک‌بار':'once','🔁 روزانه':'daily','📅 هفتگی':'weekly','🗓 ماهانه':'monthly'};
const STARTS=['00','05','10','15','20','25','30','35','40','45','50','55'];
const PAGE=12;
const jfmt = new Intl.DateTimeFormat('en-US-u-ca-persian',{timeZone:'UTC',year:'numeric',month:'numeric',day:'numeric'});
const tfmt = new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Tehran',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
const ascii=x=>String(x).replace(/[۰-۹٠-٩]/g,c=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c)>=0?'۰۱۲۳۴۵۶۷۸۹'.indexOf(c):'٠١٢٣٤٥٦٧٨٩'.indexOf(c)));
const norm=x=>ascii(x||'').trim().replace(/\s+/g,' ').replace(/ي/g,'ی').replace(/ك/g,'ک');
const dateStr=d=>new Date(d).toISOString().slice(0,10);
const addDays=(d,n)=>dateStr(Date.parse(d+'T00:00:00Z')+86400000*n);
const between=(d,a,b)=> d>=a && d<=b;
const jan=(d)=>Object.fromEntries(jfmt.formatToParts(new Date(d+'T00:00:00Z')).filter(p=>['day','month','year'].includes(p.type)).map(p=>[p.type,Number(p.value)]));
function jalaliToISO(year,month,day){
  // Monotone binary search uses the runtime's official Persian calendar implementation.
  let lo=Math.floor(Date.UTC(year+620,0,1)/86400000), hi=Math.floor(Date.UTC(year+623,0,1)/86400000);
  const target=year*10000+month*100+day;
  while(lo<hi){const mid=(lo+hi)>>1; const p=jan(dateStr(mid*86400000)); const k=p.year*10000+p.month*100+p.day;if(k<target)lo=mid+1;else hi=mid;}
  const iso=dateStr(lo*86400000), found=jan(iso);
  if(found.year!==year||found.month!==month||found.day!==day)throw Error('تاریخ شمسی نامعتبر است.');
  return iso;
}
function parseDay(s){const a=ascii(s).replace(/\//g,'-'); if(!/^\d{4}-\d{2}-\d{2}$/.test(a))throw Error('تاریخ باید YYYY-MM-DD باشد.');const [y,m,d]=a.split('-').map(Number);if(y<1700)return jalaliToISO(y,m,d); const dt=new Date(a+'T00:00:00Z');if(Number.isNaN(+dt)||dateStr(dt)!==a)throw Error('تاریخ نامعتبر است.');return a;}
function hhmm(s){if(!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(s||''))throw Error('ساعت نامعتبر است.');return Number(s.slice(0,2))*60+Number(s.slice(3));}
function duration(start,end){const v=(hhmm(end)-hhmm(start)+1440)%1440;if(v<15||v>180)throw Error('مدت برنامه باید بین ۱۵ و ۱۸۰ دقیقه باشد.');return v;}
function tehranNow(){const p=Object.fromEntries(tfmt.formatToParts(new Date()).filter(p=>p.type!=='literal').map(p=>[p.type,p.value]));return {day:`${p.year}-${p.month}-${p.day}`,minute:Number(p.hour)*60+Number(p.minute)};}
const weekday = day=>new Date(day+'T00:00:00Z').getUTCDay();
function isDue(p,d){if(!p.enabled||p.skip_dates?.includes(d)||d<parseDay(p.from_date)||d>parseDay(p.until_date||p.from_date))return false;
 if(p.frequency==='once')return d===parseDay(p.from_date);
 if(p.frequency==='daily')return true;
 if(p.frequency==='weekly')return p.weekdays.includes((weekday(d)+6)%7); // Monday=0
 if(p.frequency==='monthly')return jan(d).day===p.month_day;
 return false;
}
function validate(records){if(!Array.isArray(records)||records.length>150)throw Error('تقویم بیش از حد مجاز برنامه دارد.');const ids=new Set();let earliest=null,latest=null;
 for(const p of records){if(!/^[A-Za-z][A-Za-z0-9_-]{1,39}$/.test(p.id)||ids.has(p.id))throw Error('شناسه نامعتبر یا تکراری است.');ids.add(p.id);
  if(typeof p.title!=='string'||!p.title.trim()||p.title.length>120)throw Error('عنوان برنامه نامعتبر است.'); if(typeof p.enabled!=='boolean')throw Error('وضعیت برنامه نامعتبر است.');
  duration(p.start,p.end);if(!['once','daily','weekly','monthly'].includes(p.frequency))throw Error('نوع تکرار نامعتبر است.');
  const first=parseDay(p.from_date),last=parseDay(p.until_date||p.from_date);
  if(last<first||(Date.parse(last)-Date.parse(first))/86400000>370)throw Error('بازه برنامه نامعتبر یا بیش از ۳۷۰ روز است.');
  if(p.frequency==='once'&&last!==first)throw Error('برنامه یک‌باره تاریخ پایان متفاوت دارد.');
  if(!Array.isArray(p.weekdays)||p.weekdays.some(x=>!Number.isInteger(x)||x<0||x>6)||p.frequency==='weekly'&&!p.weekdays.length)throw Error('روزهای هفتگی نامعتبرند.');
  if(p.frequency==='monthly'&&(!Number.isInteger(p.month_day)||p.month_day<1||p.month_day>31))throw Error('روز ماهانه نامعتبر است.');
  if(p.skip_dates!==undefined&&(!Array.isArray(p.skip_dates)||p.skip_dates.length>60||new Set(p.skip_dates).size!==p.skip_dates.length||p.skip_dates.some(x=>parseDay(x)!==x||!between(x,first,last))))throw Error('نوبت لغوشده نامعتبر است.');
  if(p.enabled){if(earliest===null||first<earliest)earliest=first;if(latest===null||last>latest)latest=last;}
 }
 if(!earliest)return records;
 const slots=[];for(let d=earliest;d<=latest;d=addDays(d,1)){
  const t=Date.parse(d+'T00:00:00Z')/60000;
  if(weekday(d)!==5)for(const [start,end] of [[1080,1140],[1170,1230],[1260,1320]])slots.push([t+start,t+end,'ثابت']);
  for(const p of records)if(isDue(p,d)){const st=t+hhmm(p.start);slots.push([st,st+duration(p.start,p.end),p.id]);}
 }
 slots.sort((a,b)=>a[0]-b[0]||a[1]-b[1]);for(let i=1;i<slots.length;i++)if(slots[i][0]<slots[i-1][1])throw Error(`تداخل برنامه‌ها: ${slots[i-1][2]} و ${slots[i][2]}`);
 return records;
}
function buttons(rows){return {keyboard:rows.map(row=>row.map(text=>({text}))),resize_keyboard:true,one_time_keyboard:false};}
const pageButtons=(options,page,size=PAGE)=>{let v=options.slice(page*size,(page+1)*size);let rows=[];for(let i=0;i<v.length;i+=2)rows.push(v.slice(i,i+2));let nav=[];if(page>0)nav.push('⬅️ صفحه قبل');if((page+1)*size<options.length)nav.push('➡️ صفحه بعد');if(nav.length)rows.push(nav);rows.push([HOME,CANCEL]);return rows;};
const programName=p=>`📺 ${p.id} · ${p.title.slice(0,20)}`;
function filtered(records,action){if(action==='pause'||action==='skip')return records.filter(p=>p.enabled);if(action==='resume')return records.filter(p=>!p.enabled);if(action==='unskip')return records.filter(p=>p.skip_dates?.length);return records;}
function datesFor(p,action,today){if(action==='unskip')return (p.skip_dates||[]).filter(d=>d>=today).sort();let start=parseDay(p.from_date);if(start<today)start=today;const end=parseDay(p.until_date||p.from_date);const result=[];for(let d=start;d<=end&&result.length<370;d=addDays(d,1))if(isDue(p,d))result.push(d);return result;}
function keyboard(session,records){if(!session)return buttons(MAIN);const {mode,step,data={},page=0}=session;
 if(step==='confirm')return buttons([[CONFIRM,CANCEL],[HOME]]);
 if(mode==='pick')return buttons(pageButtons(filtered(records,data.action).map(programName),page));
 if(['skip','unskip'].includes(mode)&&step==='date')return buttons(pageButtons(datesFor(records.find(p=>p.id===data.id)||{from_date:'2099-01-01',until_date:'2099-01-01',enabled:false},mode,tehranNow().day).map(d=>'📆 '+d),page));
 if(mode==='add'){
  if(step==='title')return buttons([['📺 ویژه‌برنامه مناسبتی','📺 برنامه تولیدی'],['📺 گفت‌وگوی علمی','✍️ عنوان دلخواه'],[HOME,CANCEL]]);
  if(step==='start'||step==='end'){
   if(data[`${step}_hour`]===undefined){let r=[];for(let h=0;h<24;h+=4)r.push(Array.from({length:4},(_,i)=>`🕘 ${String(h+i).padStart(2,'0')}`));return buttons([...r,['✍️ ساعت دلخواه',HOME,CANCEL]]);}
   return buttons([[...STARTS.slice(0,4).map(m=>'⏱ '+m)],[...STARTS.slice(4,8).map(m=>'⏱ '+m)],[...STARTS.slice(8).map(m=>'⏱ '+m)],['✍️ ساعت دلخواه',HOME,CANCEL]]);
  }
  if(step==='frequency')return buttons([['🔹 یک‌بار','🔁 روزانه'],['📅 هفتگی','🗓 ماهانه'],[HOME,CANCEL]]);
  if(step==='weekdays')return buttons([...Array.from({length:4},(_,i)=>DAYS.slice(i*2,i*2+2).map(d=>(data.days||[]).includes(d)?'✅ '+d:'▫️ '+d)),['✅ پایان انتخاب روزها'],[HOME,CANCEL]]);
  if(step==='from_date'){
   let start=addDays(tehranNow().day,(data.datePage||0)*14);let d=Array.from({length:14},(_,i)=>'📆 '+addDays(start,i));return buttons(pageButtons(d,0,14).filter(r=>!r.includes(HOME)).concat([['⬅️ ۱۴ روز قبل','➡️ ۱۴ روز بعد'],['✍️ تاریخ دلخواه',HOME,CANCEL]]));
  }
  if(step==='until_date')return buttons([['🗓 ۷ روز','🗓 ۳۰ روز'],['🗓 ۹۰ روز','🗓 ۱۸۰ روز'],['✍️ تاریخ دلخواه',HOME,CANCEL]]);
 }
 return buttons(MAIN);
}
function showPrograms(records){if(!records.length)return 'هیچ برنامه اضافی ثبت نشده است. سه نوبت ثابت بدون تغییرند.';return 'برنامه‌های اضافی شبکه فارسی:\n'+records.slice(0,60).map(p=>`• ${p.id} | ${p.title}\n  ${p.start}–${p.end} | ${p.frequency} | ${p.from_date} تا ${p.until_date||p.from_date} | ${p.enabled?'فعال':'متوقف'}`).join('\n').slice(0,3600);}
function week(records){let today=tehranNow().day, lines=[];for(let n=0;n<7;n++){const d=addDays(today,n);for(const p of records)if(isDue(p,d))lines.push(`• ${d} | ${p.start}–${p.end} | ${p.title}`);}return lines.length?'برنامه‌های هفت روز آینده (تهران):\n'+lines.join('\n').slice(0,3500):'هیچ برنامه اضافی در هفت روز آینده ثبت نشده است.';}
function nextQuestion(step){return ({title:'نام برنامه را انتخاب کنید.',start:'ساعت شروع را انتخاب کنید.',end:'ساعت پایان را انتخاب کنید.',frequency:'نوع تکرار را انتخاب کنید.',from_date:'تاریخ اولین اجرا را انتخاب کنید.',until_date:'مدت برنامه را انتخاب کنید.',weekdays:'روزهای هفته را انتخاب کنید و پایان را بزنید.'})[step]||'گزینه موردنظر را انتخاب کنید.';}
function currentDraft(data,records){const start=parseDay(data.from_date);const today=tehranNow();if(start<today.day)throw Error('تاریخ شروع نباید گذشته باشد.');if(start===today.day&&hhmm(data.start)<today.minute+20)throw Error('شروع امروز باید حداقل ۲۰ دقیقه بعد باشد.');
 const end=data.frequency==='once'?'':data.until_date;if(data.frequency!=='once'&&!end)throw Error('تاریخ پایان لازم است.');
 const p={id:data.id,title:data.title,start:data.start,end:data.end,frequency:data.frequency,from_date:data.from_date,until_date:end,weekdays:data.frequency==='weekly'?(data.days||[]).map(x=>({'دوشنبه':0,'سه‌شنبه':1,'چهارشنبه':2,'پنجشنبه':3,'جمعه':4,'شنبه':5,'یکشنبه':6})[x]).sort():[],month_day:data.frequency==='monthly'?jan(start).day:0,enabled:true};validate([...records,p]);return p;
}
function preview(action,data){if(action==='add')return `پیش‌نمایش ثبت برنامه:\nشناسه: ${data.id}\nعنوان: ${data.title}\nساعت تهران: ${data.start}–${data.end}\nتکرار: ${data.frequency}\nشروع: ${data.from_date}\nپایان: ${data.until_date||'همان روز'}\nبرای ثبت «تأیید نهایی» را بزنید.`;return `عملیات ${action} برای ${data.id}${data.day?' در '+data.day:''}.\nآیا تأیید می‌کنید؟`;}
/** Pure dialogue handler (no writes). Confirms return a mutation for GitHub. */
export function stepDialog(text, session, programs=[],updateId=0){const v=norm(text), now=Date.now();let s=session&&now-session.updatedAt<45*60000?structuredClone(session):null;
 const out=(reply,ns=s,mutation=null)=>({reply,session:ns,keyboard:keyboard(ns,programs),mutation});
 const fresh=(mode,step,data={})=>({mode,step,data,page:0,updatedAt:now});
 if(v==='/start'||v===HOME||v==='/menu'||v==='منو')return out('منوی مدیریت خصوصی دیدبان آماده است. گزینه را انتخاب کنید.',null);
 if(v===CANCEL||v==='انصراف')return out('درخواست لغو شد. تقویم تغییر نکرد.',null);
 if(v==='🆔 شناسه من')return out('شناسه حساب بله شما را از پیام جداگانه دریافت می‌کنید.');
 if(v==='ℹ️ راهنما'||v==='/help')return out('فقط برنامه‌های اضافی قابل تغییرند. سه برنامه ثابت شبکه دست‌نخورده باقی می‌مانند. افزودن/لغو/حذف فقط پس از تأیید نهایی ثبت می‌شود. ساعت‌ها به وقت تهران‌اند.');
 if(v==='📋 برنامه‌ها')return out(showPrograms(programs));if(v==='📅 تقویم هفته')return out(week(programs));
 if(v==='➕ افزودن برنامه')return out(nextQuestion('title'),fresh('add','title',{id:`show${updateId}`}));
 if(SELECT[v]){const action=SELECT[v],items=filtered(programs,action);if(!items.length)return out('در حال حاضر برنامه‌ای برای این عملیات وجود ندارد.',null);return out('برنامه موردنظر را با دکمه انتخاب کنید:',fresh('pick','select',{action}));}
 if(!s)return out('گزینه ناشناخته است؛ از منوی اصلی انتخاب کنید.',null);
 s.updatedAt=now;
 if(s.step==='confirm'&&v===CONFIRM){const action=s.mode,data=s.data;let payload=action==='add'?currentDraft(data,programs):{id:data.id,day:data.day};return out('درخواست ثبت در GitHub ارسال می‌شود.',null,{action,payload});}
 if(s.mode==='pick'&&s.step==='select'){
  const items=filtered(programs,s.data.action);if(v==='➡️ صفحه بعد'||v==='⬅️ صفحه قبل'){s.page=Math.max(0,Math.min(Math.floor((items.length-1)/PAGE),s.page+(v==='➡️ صفحه بعد'?1:-1)));return out('برنامه را انتخاب کنید:',s);}
  const selected=items.slice(s.page*PAGE,(s.page+1)*PAGE).find(p=>v===programName(p));if(!selected)return out('از دکمه‌های برنامه‌ها استفاده کنید.',s);
  if(['skip','unskip'].includes(s.data.action)){const available=datesFor(selected,s.data.action,tehranNow().day);if(!available.length)return out('نوبت آینده‌ای برای این عملیات وجود ندارد.',null);return out('تاریخ نوبت را انتخاب کنید:',fresh(s.data.action,'date',{id:selected.id}));}
  const ns=fresh(s.data.action,'confirm',{id:selected.id});return out(preview(ns.mode,ns.data),ns);
 }
 if(['skip','unskip'].includes(s.mode)&&s.step==='date'){
  const p=programs.find(p=>p.id===s.data.id);if(!p)return out('برنامه دیگر وجود ندارد؛ منو را باز کنید.',null);
  const dates=datesFor(p,s.mode,tehranNow().day);
  if(v==='➡️ صفحه بعد'||v==='⬅️ صفحه قبل'){s.page=Math.max(0,Math.min(Math.floor((dates.length-1)/PAGE),s.page+(v==='➡️ صفحه بعد'?1:-1)));return out('تاریخ را انتخاب کنید:',s);}
  const d=v.startsWith('📆 ')?v.slice(3).trim():v;if(!dates.slice(s.page*PAGE,(s.page+1)*PAGE).includes(d))return out('تاریخ را با دکمه انتخاب کنید.',s);
  s.step='confirm';s.data.day=d;return out(preview(s.mode,s.data),s);
 }
 if(s.mode!=='add')return out('برای تأیید، دکمه تأیید نهایی را انتخاب کنید.',s);
 const d=s.data,step=s.step;
 try {
  let next=step;
  if(step==='title'){
   if(v==='✍️ عنوان دلخواه')return out('نام دلخواه را بنویسید.',s);
   const title=v.startsWith('📺 ')?v.slice(3):v;if(title.length<3||title.length>120||title.includes('|'))throw Error('عنوان باید ۳ تا ۱۲۰ نویسه باشد.');d.title=title;next='start';
  }else if(step==='start'||step==='end'){
   const key=step+'_hour';if(v==='✍️ ساعت دلخواه'){delete d[key];return out('ساعت را با قالب 14:00 بفرستید.',s);}
   if(/^🕘 \d{2}$/.test(v)){d[key]=Number(v.slice(-2));return out('دقیقه را انتخاب کنید.',s);}
   let value=v;if(/^⏱ \d{2}$/.test(v)&&d[key]!==undefined){value=String(d[key]).padStart(2,'0')+':'+v.slice(-2);}hhmm(value);delete d[key];d[step]=value;
   if(step==='end')duration(d.start,d.end);next=step==='start'?'end':'frequency';
  }else if(step==='frequency'){
   const freq=FREQ[v];if(!freq)throw Error('نوع تکرار را از دکمه‌ها انتخاب کنید.');d.frequency=freq;next='from_date';
  }else if(step==='from_date'){
   if(v==='➡️ ۱۴ روز بعد'||v==='⬅️ ۱۴ روز قبل'){d.datePage=Math.max(0,Math.min(25,(d.datePage||0)+(v.startsWith('➡️')?1:-1)));return out('تاریخ را انتخاب کنید.',s);}
   if(v==='✍️ تاریخ دلخواه')return out('تاریخ شمسی یا میلادی را به قالب YYYY-MM-DD بنویسید.',s);
   const picked=v.startsWith('📆 ');const choice=picked?v.slice(3).trim():v;const from=addDays(tehranNow().day,(d.datePage||0)*14);if(picked&&!between(choice,from,addDays(from,13)))throw Error('این تاریخ در صفحه فعلی نیست.');
   d.from_date=parseDay(choice);next=d.frequency==='once'?'confirm':d.frequency==='weekly'?'weekdays':'until_date';
  }else if(step==='weekdays'){
   if(v==='✅ پایان انتخاب روزها'){if(!(d.days||[]).length)throw Error('حداقل یک روز انتخاب کنید.');next='until_date';}
   else if(/^(▫️|✅) /.test(v)){let day=v.slice(2).trim();if(!DAYS.includes(day))throw Error('روز نامعتبر است.');d.days=d.days||[];d.days=d.days.includes(day)?d.days.filter(x=>x!==day):[...d.days,day];return out('روزهای هفته را انتخاب کنید و سپس پایان را بزنید.',s);}
   else throw Error('روز هفته را انتخاب کنید.');
  }else if(step==='until_date'){
   if(v==='✍️ تاریخ دلخواه')return out('تاریخ پایان را به قالب YYYY-MM-DD بفرستید.',s);
   const days={'🗓 ۷ روز':7,'🗓 ۳۰ روز':30,'🗓 ۹۰ روز':90,'🗓 ۱۸۰ روز':180}[v];d.until_date=days?addDays(parseDay(d.from_date),days):parseDay(v);next='confirm';
  }else throw Error('مرحله نامعتبر است.');
  if(next==='confirm')currentDraft(d,programs);
  s.step=next;return out(next==='confirm'?preview('add',d):nextQuestion(next),s);
 } catch(err){return out(`⚠️ اطلاعات قابل ثبت نیست: ${err.message}\n${nextQuestion(step)}`,s);}
}
function mutationRecords(records,action,payload){const data=structuredClone(records),i=data.findIndex(p=>p.id===payload.id),p=data[i];
 if(action==='add'){if(i>=0){if(JSON.stringify(p)===JSON.stringify(payload))return {records:data,already:true};throw Error('شناسه از قبل موجود است.');}data.push(payload);}
 else{if(i<0){if(action==='delete')return {records:data,already:true};throw Error('برنامه یافت نشد.');}
  if(action==='delete')data.splice(i,1);
  else if(action==='pause'||action==='resume')p.enabled=action==='resume';
  else if(action==='skip'||action==='unskip'){
   const d=parseDay(payload.day);if(d!==payload.day||!between(d,parseDay(p.from_date),parseDay(p.until_date||p.from_date)))throw Error('تاریخ نوبت نامعتبر است.');
   const skips=new Set(p.skip_dates||[]);if(action==='skip')skips.add(d);else skips.delete(d);p.skip_dates=[...skips].sort();
  }else throw Error('عملیات غیرمجاز است.');
 }
 validate(data);return {records:data,already:JSON.stringify(data)===JSON.stringify(records)};
}
async function github(env,path,method='GET',body){const r=await fetch(`https://api.github.com/repos/${env.GITHUB_REPO||'sey3d-m/velayat-live-monitor'}/${path}`,{method,headers:{Authorization:`Bearer ${env.GITHUB_TOKEN}`,Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'didban-editor-only'},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok)throw Error(`ارتباط GitHub با خطای HTTP ${r.status} مواجه شد.`);return r.json();}
function decodeB64(x){const bytes=Uint8Array.from(atob(x.replace(/\s/g,'')),c=>c.charCodeAt(0));return new TextDecoder().decode(bytes);}
async function gitRecords(env){const base=await github(env,'contents/config/didban_extra_programs.json?ref=main');const mirror=await github(env,'contents/docs/data/extra-programs.json?ref=main');const content=decodeB64(base.content), other=decodeB64(mirror.content);if(content!==other)throw Error('تقویم اصلی و نسخه نمایشی همسان نیستند؛ تغییر متوقف شد.');const parsed=JSON.parse(content);if(parsed.version!==1||!Array.isArray(parsed.programs))throw Error('ساختار تقویم نامعتبر است.');validate(parsed.programs);return parsed.programs;}
async function commitCalendar(env,action,payload,updateId){if(!env.GITHUB_TOKEN)throw Error('مجوز GitHub در تنظیمات سرویس ثبت نشده است.');
 // At most two attempts for unrelated concurrent main-branch advances.
 for(let attempt=0;attempt<2;attempt++){
  const baseRef=await github(env,'git/ref/heads/main');const parent=baseRef.object.sha;
  const parentCommit=await github(env,'git/commits/'+parent);
  const read=await github(env,`contents/config/didban_extra_programs.json?ref=${parent}`);
  const mirror=await github(env,`contents/docs/data/extra-programs.json?ref=${parent}`);
  const txt=decodeB64(read.content),m=decodeB64(mirror.content);if(txt!==m)throw Error('اختلاف فایل‌های تقویم؛ ثبت تغییر متوقف شد.');const raw=JSON.parse(txt);if(raw.version!==1||!Array.isArray(raw.programs))throw Error('ساختار تقویم نامعتبر است.');
  validate(raw.programs);const result=mutationRecords(raw.programs,action,payload);
  if(result.already)return {already:true,sha:parent,records:result.records};
  const changed=JSON.stringify({...raw,programs:result.records},null,2)+'\n';
  const tree=await github(env,'git/trees','POST',{base_tree:parentCommit.tree.sha,tree:[
   {path:'config/didban_extra_programs.json',mode:'100644',type:'blob',content:changed},
   {path:'docs/data/extra-programs.json',mode:'100644',type:'blob',content:changed}]});
  const commit=await github(env,'git/commits','POST',{message:`Didban editor ${action} ${payload.id} [bale-update:${updateId}]`,tree:tree.sha,parents:[parent]});
  try{await github(env,'git/refs/heads/main','PATCH',{sha:commit.sha,force:false});}
  catch(e){if(attempt===0&&/HTTP 409|HTTP 422/.test(e.message))continue;throw e;}
  const head=await github(env,'git/ref/heads/main');if(head.object.sha!==commit.sha){ // another legitimate commit may have followed: verify source, not head identity.
   const current=await gitRecords(env);const after=mutationRecords(current,action,payload);if(!after.already)throw Error('ثبت نهایی تقویم قابل تأیید نیست.');
  }
  return {already:false,sha:commit.sha,records:result.records};
 }
 throw Error('تقویم همزمان تغییر کرد؛ دوباره تأیید کنید.');
}
async function bale(env,method,payload){const url=`https://tapi.bale.ai/bot${env.BALE_EDITOR_BOT_TOKEN}/${method}`;const form=new URLSearchParams();for(const [k,v] of Object.entries(payload))form.set(k,typeof v==='string'?v:JSON.stringify(v));const resp=await fetch(url,{method:'POST',body:form});if(!resp.ok)throw Error(`API بله HTTP ${resp.status}`);const json=await resp.json();if(json.ok!==true)throw Error(`بله درخواست ${method} را نپذیرفت.`);return json;}
const boolConfig=e=>!!(e.DB&&e.BALE_EDITOR_BOT_TOKEN&&e.WEBHOOK_PATH_SECRET&&e.EDITOR_ADMIN_IDS);
function textResponse(body,status=200){return new Response(body,{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'}});}
const ok=()=>textResponse('{"ok":true}');
async function processUpdate(update,env){const message=update.message??update.callback_query?.message??null;
 const actor=update.callback_query?.from??update.message?.from??null;
 if(!actor||!message||message.chat?.type!=='private'||!Number.isInteger(actor.id)||message.chat.id!==actor.id)return {ignored:true};
 const text=update.callback_query?update.callback_query.data:message.text;if(typeof text!=='string')return {ignored:true};
 const authorized=String(env.EDITOR_ADMIN_IDS||'').split(/[,،\s]+/).filter(Boolean).includes(String(actor.id));
 if(!authorized){const v=norm(text);if(v==='🆔 شناسه من')return {reply:`شناسه عددی حساب بله شما: ${actor.id}`,chat_id:actor.id,keyboard:buttons([['🆔 شناسه من','ℹ️ راهنما']])};if(v==='/start')return {reply:'این ربات خصوصی است و دسترسی مدیریت ندارید. شناسه حساب خود را از دکمه «شناسه من» دریافت کنید.',chat_id:actor.id,keyboard:buttons([['🆔 شناسه من','ℹ️ راهنما']])};return {ignored:true};}
 if(norm(text)==='🆔 شناسه من')return {reply:`شناسه عددی حساب بله شما: ${actor.id}`,chat_id:actor.id,keyboard:buttons(MAIN)};
 const data=await env.DB.prepare('SELECT json,version FROM sessions WHERE user_id=?').bind(String(actor.id)).first();const session=data?JSON.parse(data.json):null;
 const previous=await env.DB.prepare('SELECT json,updated_ms FROM cache WHERE id=1').first();
 const records=previous&&previous.updated_ms>Date.now()-20000?JSON.parse(previous.json):await gitRecords(env).catch(()=>null);
 // Menus and wizard can work offline with last known snapshot, but mutation must never use stale data.
 let programs=records;
 if(programs!==null)await env.DB.prepare('INSERT INTO cache (id,json,updated_ms) VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json,updated_ms=excluded.updated_ms').bind(JSON.stringify(records),Date.now()).run();
 if(programs===null){let row=await env.DB.prepare('SELECT json FROM cache WHERE id=1').first();programs=row?JSON.parse(row.json):[];}
 const result=stepDialog(text,session,programs,update.message?.message_id||update.update_id);
 if(result.mutation){
  try{const status=await commitCalendar(env,result.mutation.action,result.mutation.payload,update.update_id);await env.DB.prepare('INSERT INTO cache (id,json,updated_ms) VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET json=excluded.json,updated_ms=excluded.updated_ms').bind(JSON.stringify(status.records),Date.now()).run();return {reply:`✅ ${status.already?'عملیات از قبل اعمال شده است':'تغییر در GitHub ثبت و تأیید شد'}؛ شناسه: ${result.mutation.payload.id}\n${status.sha.slice(0,10)}`,chat_id:actor.id,keyboard:buttons(MAIN),newSession:null,prevVersion:data?.version??0,callback_id:update.callback_query?.id};}
  catch(e){return {reply:`⚠️ تغییر ثبت نشد یا تأیید آن ممکن نبود. ${e.message}\nپس از رفع مشکل، تأیید نهایی را دوباره انتخاب کنید.`,chat_id:actor.id,keyboard:keyboard(session,programs),newSession:session,prevVersion:data?.version??0,callback_id:update.callback_query?.id};}
 }
 return {reply:result.reply,chat_id:actor.id,keyboard:result.keyboard,newSession:result.session,prevVersion:data?.version??0,callback_id:update.callback_query?.id};
}
async function receive(req,env){if(!boolConfig(env))return textResponse('{"error":"not configured"}',503);
 const secret=env.WEBHOOK_PATH_SECRET;if(typeof secret!=='string'||secret.length<32)return textResponse('{"error":"bad secret config"}',503);
 // Bale does not consistently document an authenticated header; a random path + allowlist is mandatory.
 if(new URL(req.url).pathname!==`/bale/${secret}`)return textResponse('{"error":"not found"}',404);
 if(req.method!=='POST')return textResponse('{"error":"method"}',405);
 if(Number(req.headers.get('content-length'))>100000)return textResponse('{"error":"too large"}',413);
 let u;try{u=await req.json()}catch{return textResponse('{"error":"invalid json"}',400)}
 if(!Number.isSafeInteger(u.update_id)||u.update_id<0)return textResponse('{"error":"invalid update"}',400);
 const id=u.update_id,now=Date.now();
 await env.DB.prepare('INSERT OR IGNORE INTO updates (update_id,status,lease_ms) VALUES (?,\'processing\',?)').bind(id,now).run();
 let record=await env.DB.prepare('SELECT * FROM updates WHERE update_id=?').bind(id).first();
 if(record.status==='done')return ok();
 if(record.status==='processing'&&record.lease_ms!==now){
  if(record.lease_ms>now-30000)return textResponse('{"error":"still processing"}',503);
  const lock=await env.DB.prepare('UPDATE updates SET lease_ms=? WHERE update_id=? AND lease_ms=? AND status=\'processing\'').bind(now,id,record.lease_ms).run();if(lock.meta.changes!==1)return textResponse('{"error":"busy"}',503);
 }
 if(record.status==='processing'){
  let result;try{result=await processUpdate(u,env)}catch(e){
   // Unknown transient failures are retryable. Do not mark updates handled prematurely.
   await env.DB.prepare('UPDATE updates SET lease_ms=0 WHERE update_id=?').bind(id).run();return textResponse('{"error":"temporary failure"}',503);
  }
  if(result.ignored){await env.DB.prepare('UPDATE updates SET status=\'done\' WHERE update_id=?').bind(id).run();return ok();}
  // Only one sender/one session version can advance in a given step.
  if(result.newSession!==undefined){const uid=String(result.chat_id),ver=result.prevVersion;
   if(ver===0){const row=await env.DB.prepare('INSERT OR IGNORE INTO sessions(user_id,json,version) VALUES (?,?,1)').bind(uid,JSON.stringify(result.newSession)).run();if(row.meta.changes!==1){await env.DB.prepare('UPDATE updates SET lease_ms=0 WHERE update_id=?').bind(id).run();return textResponse('{"error":"concurrent conversation"}',503);}}
   else{const row=await env.DB.prepare('UPDATE sessions SET json=?,version=version+1 WHERE user_id=? AND version=?').bind(JSON.stringify(result.newSession),uid,ver).run();if(row.meta.changes!==1){await env.DB.prepare('UPDATE updates SET lease_ms=0 WHERE update_id=?').bind(id).run();return textResponse('{"error":"concurrent conversation"}',503);}}
  }
  await env.DB.prepare('UPDATE updates SET status=\'ready\',chat_id=?,reply=?,markup=?,callback_id=? WHERE update_id=?').bind(String(result.chat_id),result.reply,JSON.stringify(result.keyboard),result.callback_id||null,id).run();
  record=await env.DB.prepare('SELECT * FROM updates WHERE update_id=?').bind(id).first();
 }
 if(record.status!=='ready')return textResponse('{"error":"retry later"}',503);
 try{
  if(record.callback_id)await bale(env,'answerCallbackQuery',{callback_query_id:record.callback_id}).catch(()=>{});
  await bale(env,'sendMessage',{chat_id:record.chat_id,text:record.reply.slice(0,3900),reply_markup:record.markup});
  await env.DB.prepare('UPDATE updates SET status=\'done\',reply=NULL,markup=NULL WHERE update_id=?').bind(id).run();return ok();
 }catch(e){return textResponse('{"error":"message delivery failed"}',503);}
}
export default {async fetch(request,env){const pathname=new URL(request.url).pathname;
 if(pathname==='/health'&&request.method==='GET')return textResponse(JSON.stringify({status:boolConfig(env)?'configured':'unconfigured',purpose:'editor-webhook-only'}));
 return receive(request,env);
}};
export const internals={validate,parseDay,isDue,mutationRecords,keyboard,jalaliToISO,duration};
