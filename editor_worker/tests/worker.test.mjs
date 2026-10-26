import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import worker,{stepDialog,internals} from '../worker.mjs';
const {validate,mutationRecords,parseDay,isDue} = internals;
const future=n=>new Date(Date.now()+n*86400000).toISOString().slice(0,10);
class D1DB {
  constructor(){this.db=new DatabaseSync(':memory:');this.db.exec(fs.readFileSync(new URL('../schema.sql',import.meta.url),'utf8'));}
  prepare(sql){let db=this.db,args=[];return {bind(...values){args=values;return this;},async first(){return db.prepare(sql).get(...args)||null;},async run(){const ret=db.prepare(sql).run(...args);return {meta:{changes:ret.changes}};}};}
}
function mockEnv(db=new D1DB()){
 const store={records:[],sent:[],failGit:false,head:'c0',commits:{c0:{tree:{sha:'t0'}}},trees:{},changed:0};
 const original=globalThis.fetch;
 const env={DB:db,BALE_EDITOR_BOT_TOKEN:'test-private-editor-token',EDITOR_ADMIN_IDS:'12345',WEBHOOK_PATH_SECRET:'A'.repeat(48),GITHUB_TOKEN:'test-restricted-token',GITHUB_REPO:'sey3d-m/velayat-live-monitor'};
 globalThis.fetch=async(url,init={})=>{
  const p=new URL(url).pathname,method=init.method||'GET',body=init.body&&String(init.body).startsWith('{')?JSON.parse(init.body):{};
  const result=(json,status=200)=>new Response(JSON.stringify(json),{status,headers:{'Content-Type':'application/json'}});
  if(url.includes('tapi.bale.ai')){if(p.endsWith('/sendMessage'))store.sent.push(Object.fromEntries(new URLSearchParams(init.body)));return result({ok:true,result:true});}
  if(store.failGit)return result({message:'disabled'},503);
  if(p.endsWith('/git/ref/heads/main')&&method==='GET')return result({object:{sha:store.head}});
  if(p.endsWith('/git/refs/heads/main')&&method==='PATCH') {store.head=body.sha;store.records=structuredClone(store.trees[store.commits[body.sha].tree.sha]);store.changed++;return result({ref:'refs/heads/main'});}
  if(p.includes('/git/commits/')&&method==='GET')return result(store.commits[p.split('/').pop()]||{tree:{sha:'t0'}});
  if(p.endsWith('/git/commits')&&method==='POST'){const sha='c'+Object.keys(store.commits).length;store.commits[sha]={tree:{sha:body.tree}};return result({sha});}
  if(p.endsWith('/git/trees')&&method==='POST'){const a=JSON.parse(body.tree[0].content);const b=JSON.parse(body.tree[1].content);assert.deepEqual(a,b);const sha='t'+(Object.keys(store.trees).length+1);store.trees[sha]=a.programs;return result({sha});}
  if(p.includes('/contents/')){
   const data=JSON.stringify({version:1,programs:store.records},null,2)+'\n';
   return result({content:Buffer.from(data).toString('base64')});
  }
  throw Error(`Unexpected request ${method} ${p}`);
 };
 return {env,store,restore(){globalThis.fetch=original;}};
}
function upd(id,text,user=12345){return {update_id:id,message:{message_id:id,chat:{type:'private',id:user},from:{id:user},text}};}
async function send(env,u){return worker.fetch(new Request(`https://test.workers.dev/bale/${env.WEBHOOK_PATH_SECRET}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(u)}),env);}
const p=(id,title='تست',start='12:00',end='13:00',frequency='once',from_date=future(3))=>({id,title,start,end,frequency,from_date,until_date:'',weekdays:[],month_day:0,enabled:true});

test('conflict with fixed slot rejects but safe hours validate',()=>{
 let d=future(1);while(new Date(d+'T00:00:00Z').getUTCDay()===5)d=future(Math.ceil((Date.parse(d+'T00:00:00Z')-Date.now())/86400000)+1);
 assert.throws(()=>validate([p('extraA','تست','18:30','19:00','once',d)]),/تداخل/);
 assert.doesNotThrow(()=>validate([p('extraB','تست','13:00','14:00','once',d)]));
});
test('Gregorian and Persian dates consistent',()=>{
 assert.equal(parseDay('۱۴۰۵-۰۱-۰۱'),'2026-03-21');
 assert.equal(parseDay('2026-10-26'),'2026-10-26');
 assert.throws(()=>parseDay('2026-02-30'),/نامعتبر/);
 assert.throws(()=>parseDay('1405-13-02'),/نامعتبر/);
});
test('dialog supports all main buttons and stateful wizard',()=>{
 for(const action of ['⏸ توقف برنامه','▶️ فعال‌سازی برنامه','🗑 حذف برنامه','📆 لغو یک نوبت','🔄 بازگرداندن نوبت'])assert.ok(stepDialog(action,null,[p('newA')],100).reply);
 let r=stepDialog('➕ افزودن برنامه',null,[],500);
 for(const input of ['📺 گفت‌وگوی علمی','🕘 06','⏱ 00','🕘 07','⏱ 00','🔹 یک‌بار']){r=stepDialog(input,r.session,[],500);}
 assert.equal(r.session.step,'from_date');
 r=stepDialog('📆 '+future(3),r.session,[],500);
 assert.equal(r.session.step,'confirm');
 let confirm=stepDialog('✅ تأیید نهایی',r.session,[],500);
 assert.equal(confirm.mutation.action,'add');
 assert.equal(confirm.mutation.payload.id,'show500');
 assert.deepEqual(stepDialog('❌ انصراف',r.session,[],500).session,null);
 assert.deepEqual(stepDialog('🏠 منوی اصلی',r.session,[],500).session,null);
});
test('do not mutate stale or fixed slots via action',()=>{
 const programs=[p('testA')];
 assert.equal(mutationRecords(programs,'pause',{id:'testA'}).records[0].enabled,false);
 assert.equal(mutationRecords(programs,'pause',{id:'testA'}).records[0].enabled,false);
 assert.equal(programs[0].enabled,true);
 assert.throws(()=>mutationRecords(programs,'add',{...p('testB', 'تداخل برنامه', '12:30','13:00')}),/تداخل/);
});
test('webhook end-to-end: authorization, persistence, no duplicate responses, offline menus',async()=>{
 const m=mockEnv();try{
  let r=await send(m.env,upd(100,'/start'));assert.equal(r.status,200);assert.equal(m.store.sent.length,1);
  assert.ok(m.store.sent[0].reply_markup.includes('keyboard'));
  r=await send(m.env,upd(100,'/start'));assert.equal(r.status,200);assert.equal(m.store.sent.length,1);
  r=await send(m.env,upd(101,'🆔 شناسه من',6789));assert.equal(r.status,200);assert.match(m.store.sent.at(-1).text,/6789/);
  r=await send(m.env,upd(102,'🗑 حذف برنامه',6789));assert.equal(r.status,200);assert.equal(m.store.sent.length,2);
  r=await send(m.env,upd(103,'➕ افزودن برنامه'));assert.equal(r.status,200);let state=m.env.DB.db.prepare('SELECT json FROM sessions WHERE user_id=?').get('12345');assert.equal(JSON.parse(state.json).step,'title');
  r=await send(m.env,upd(104,'❌ انصراف'));assert.equal(r.status,200);assert.equal(JSON.parse(m.env.DB.db.prepare('SELECT json FROM sessions WHERE user_id=?').get('12345').json),null);
  m.store.failGit=true;r=await send(m.env,upd(105,'📋 برنامه‌ها'));assert.equal(r.status,200);assert.match(m.store.sent.at(-1).text,/هیچ برنامه/);
 }finally{m.restore();}
});
test('webhook real simulated add commit only after confirmation and no replay',async()=>{
 const m=mockEnv();try{
  let seq=['➕ افزودن برنامه','📺 برنامه تولیدی','🕘 06','⏱ 00','🕘 07','⏱ 00','🔹 یک‌بار','📆 '+future(3)];
  for(let i=0;i<seq.length;i++)assert.equal((await send(m.env,upd(200+i,seq[i]))).status,200);
  assert.equal(m.store.changed,0);assert.equal(m.store.records.length,0);
  assert.equal((await send(m.env,upd(208,'✅ تأیید نهایی'))).status,200);
  assert.equal(m.store.changed,1);assert.equal(m.store.records.length,1);
  assert.equal((await send(m.env,upd(208,'✅ تأیید نهایی'))).status,200);
  assert.equal(m.store.changed,1);
  assert.match(m.store.sent.at(-1).text,/GitHub ثبت و تأیید/);
  assert.equal((await send(m.env,upd(209,'📋 برنامه‌ها'))).status,200);
  assert.match(m.store.sent.at(-1).text,/show200/);
 }finally{m.restore();}
});
test('GitHub outage does not falsely mark calendar update as success',async()=>{
 const m=mockEnv();try{
  m.store.failGit=true;
  const seq=['➕ افزودن برنامه','📺 برنامه تولیدی','🕘 06','⏱ 00','🕘 07','⏱ 00','🔹 یک‌بار','📆 '+future(3),'✅ تأیید نهایی'];
  for(let i=0;i<seq.length;i++)assert.equal((await send(m.env,upd(300+i,seq[i]))).status,200);
  assert.equal(m.store.changed,0);
  assert.doesNotMatch(m.store.sent.at(-1).text,/تغییر در GitHub ثبت و تأیید شد/);
  assert.match(m.store.sent.at(-1).text,/ثبت نشد/);
 }finally{m.restore();}
});
