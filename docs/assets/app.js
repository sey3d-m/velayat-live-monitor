/* Pasokhnama: public-only, read-only view of sanitized Velayat Monitor results.
   No secrets or Gemini keys in this script. */
(() => {
  'use strict';
  const page = document.body.dataset.page;
  const url = new URL(location.href);
  const isDemo = url.searchParams.get('demo') === '1' || location.protocol === 'file:';
  const feedUrl = isDemo ? 'data/demo.json' : 'data/feed.json';
  const REFRESH_MS = 60_000;
  const OVERLAY_ROTATE_MS = 14_000;
  const OVERLAY_MAX_AGE_HOURS = 4;
  const fa = n => String(n ?? '').replace(/\d/g, x => '۰۱۲۳۴۵۶۷۸۹'[x]);
  const normalize = str => String(str ?? '').replace(/[\u064A\u0649]/g, 'ی').replace(/\u0643/g,'ک').replace(/[\u064B-\u065F]/g,'').trim().toLowerCase();
  const sourceName = s => ({ phone: 'تماس تلفنی', message: 'پیام مخاطب', unknown: 'پرسش مخاطب' })[s] || 'پرسش مخاطب';
  const byId = id => document.getElementById(id);
  const newEl = (tag, className, content) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (content !== undefined) el.textContent = content;
    return el;
  };
  const secs = n => {
    n = Math.max(0, Number(n) || 0);
    return fa(`${Math.floor(n/60).toString().padStart(2,'0')}:${Math.floor(n%60).toString().padStart(2,'0')}`);
  };
  const timestamp = iso => {
    if (!iso) return 'هنوز منتشر نشده است';
    try { return new Intl.DateTimeFormat('fa-IR',{timeZone:'Asia/Tehran',month:'long',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(iso)) + ' به وقت تهران'; }
    catch (_) { return 'زمان انتشار نامشخص'; }
  };
  const demoFallback = {
    updated_at:'2026-10-11T17:35:00+00:00',source:'DEMO',programs:[{
      id:'demo-1',date:'۱۴۰۵/۰۷/۱۹',date_iso:'2026-10-11',day:'یکشنبه',start:'21:00',end:'22:00',program:'فائزون',expert:'کارشناس برنامه',host:'مجری برنامه',topic:'گفت‌وگوی اعتقادی',quality:'complete',questions:[
        {id:'demo-q1',question:'منظور از واژه مولا در حدیث غدیر چیست؟',answer:'در این پاسخ نمونه، به کاربرد واژه مولا و قرائن مرتبط با حدیث غدیر اشاره می‌شود.',start_sec:1164,end_sec:1298,source:'phone',status:'answered'},
        {id:'demo-q2',question:'چگونه اعتبار روایت‌های تاریخی را بررسی کنیم؟',answer:'در این نمونه آزمایشی، مراجعه به منابع اولیه و بررسی سند و قرائن توصیه می‌شود.',start_sec:1620,end_sec:1750,source:'message',status:'answered'}
      ]
    }]
  };
  let feed = { programs: [] };
  let allEntries = [];
  let listLimit = 8;
  let currentItem = null;
  let overlayIndex = 0;
  let overlaySignature = '';

  async function loadFeed() {
    try {
      const res = await fetch(feedUrl + '?t=' + Date.now(), {cache:'no-store'});
      if (!res.ok) throw Error('HTTP ' + res.status);
      const data = await res.json();
      if (!data || !Array.isArray(data.programs)) throw Error('ساختار داده نامعتبر');
      feed = data;
      if (page === 'audience') audienceRender();
      if (page === 'overlay') overlayRender(true);
    } catch (err) {
      if (isDemo) {
        feed = demoFallback;
        if (page === 'audience') audienceRender();
        if (page === 'overlay') overlayRender(true);
      } else if (page === 'audience') {
        byId('feed-status').textContent = 'ارتباط با خروجی عمومی دیدبان برقرار نشد. داده‌های قبلی در صورت وجود همچنان قابل مشاهده‌اند.';
      } else if (!feed.programs.length) {
        showOverlayWaiting('ارتباط با آرشیو برقرار نیست');
      }
      console.warn('Pasokhnama feed fetch:', err);
    }
  }

  function flatten() {
    return (feed.programs || []).flatMap(p => (p.questions || [])
      .filter(q => q && q.question && q.answer && q.status === 'answered')
      .map(q => ({ ...q, programInfo:p })));
  }

  function audienceRender() {
    allEntries = flatten();
    const dataPrograms = feed.programs || [];
    byId('total-questions').textContent = fa(allEntries.length);
    byId('total-programs').textContent = fa(dataPrograms.length);
    byId('updated-at').textContent = timestamp(feed.updated_at);
    const status = byId('feed-status');
    if (isDemo) {
      status.classList.add('demo-notice');
      status.textContent = 'حالت نمایشی فعال است: تمامی پرسش‌ها، پاسخ‌ها و آمار این صفحه ساختگی و صرفاً برای بررسی طراحی هستند.';
    } else if (!feed.updated_at) {
      status.textContent = 'صفحه متصل است؛ هنوز گزارشی برای انتشار دریافت نشده است. پس از پایان نخستین برنامه، داده‌ها خودکار ظاهر می‌شوند.';
    } else {
      status.textContent = '';
    }
    const newest = dataPrograms[0];
    byId('latest-program-name').textContent = newest?.program || 'هنوز گزارشی منتشر نشده است';
    byId('latest-program-meta').textContent = newest ? [newest.day,newest.date,fa(newest.start)].filter(Boolean).join(' · ') : '—';
    byId('latest-program-expert').textContent = newest && newest.expert && newest.expert !== 'نامشخص' ? 'کارشناس: ' + newest.expert : 'پاسخ‌ها پس از پایان تحلیل ثبت می‌شوند';
    const select = byId('program-select');
    const previous = select.value;
    select.replaceChildren(new Option('همه برنامه‌ها','all'));
    [...new Set(dataPrograms.map(p=>p.program).filter(Boolean))].forEach(name => select.add(new Option(name,name)));
    select.value = [...select.options].some(o=>o.value === previous) ? previous : 'all';
    renderList();
  }

  function renderList() {
    const search = normalize(byId('search-input').value);
    const targetProgram = byId('program-select').value;
    const items = allEntries.filter(item => {
      const p = item.programInfo;
      return (targetProgram === 'all' || p.program === targetProgram) &&
        (!search || normalize([item.question,item.answer,p.program,p.topic,p.expert].join(' ')).includes(search));
    });
    byId('result-count').textContent = fa(items.length) + ' نتیجه';
    const list = byId('question-list');
    list.replaceChildren();
    if (!items.length) {
      const empty = newEl('div','empty-state');
      empty.append(newEl('div','empty-icon','؟'),newEl('h3','',search ? 'پرسشی با این عبارت پیدا نشد' : 'پرسشی برای نمایش وجود ندارد'),
        newEl('p','',search ? 'عبارت دیگری جست‌وجو کنید یا فیلتر برنامه را تغییر دهید.' : 'با انتشار گزارش جدید دیدبان، پرسش‌های پاسخ‌داده‌شده اینجا قرار می‌گیرند.'));
      list.append(empty);
    }
    items.slice(0,listLimit).forEach(item => {
      const card = newEl('article','question-card');
      const top = newEl('div','question-top');
      top.append(newEl('span','program-tag',item.programInfo.program || 'برنامه شبکه ولایت'),newEl('span','answered-tag','✓ پاسخ استخراج شد'));
      const headline = newEl('h3','',item.question);
      const preview = newEl('p','answer-preview',item.answer);
      const bottom = newEl('div','question-bottom');
      const meta = newEl('div','question-meta');
      meta.append(newEl('span','',item.programInfo.date || ''),newEl('span','',sourceName(item.source)),newEl('span','',secs(item.start_sec)));
      const open = newEl('button','open-answer','مشاهده پاسخ ←');
      open.type = 'button';
      open.addEventListener('click',()=>openDetail(item));
      bottom.append(meta,open);
      card.append(top,headline,preview,bottom);
      list.append(card);
    });
    byId('load-more').hidden = items.length <= listLimit;
  }

  function openDetail(item) {
    currentItem = item;
    const p = item.programInfo;
    byId('modal-program').textContent = [p.program,p.date,p.expert && p.expert !== 'نامشخص' ? 'کارشناس: '+p.expert : ''].filter(Boolean).join(' · ');
    byId('modal-title').textContent = item.question;
    byId('modal-answer').textContent = item.answer;
    byId('modal-timestamp').textContent = 'زمان تقریبی در برنامه: ' + secs(item.start_sec) + ' تا ' + secs(item.end_sec);
    byId('detail-modal').hidden = false;
    byId('detail-modal').setAttribute('aria-hidden','false');
    document.body.style.overflow = 'hidden';
    byId('modal-close').focus();
  }
  function closeDetail() {
    byId('detail-modal').hidden = true;
    byId('detail-modal').setAttribute('aria-hidden','true');
    document.body.style.overflow = '';
  }
  function setupAudience() {
    byId('search-input').addEventListener('input',()=>{listLimit=8;renderList();});
    byId('program-select').addEventListener('change',()=>{listLimit=8;renderList();});
    byId('load-more').addEventListener('click',()=>{listLimit+=8;renderList();});
    byId('modal-close').addEventListener('click',closeDetail);
    byId('detail-modal').addEventListener('click',e=>{if(e.target.dataset.close) closeDetail();});
    document.addEventListener('keydown',e=>{if(e.key === 'Escape' && !byId('detail-modal').hidden) closeDetail();});
    byId('copy-answer').addEventListener('click', async () => {
      if (!currentItem) return;
      const text = 'پرسش: '+currentItem.question+'\nپاسخ (خلاصه خودکار): '+currentItem.answer+'\nبرنامه: '+currentItem.programInfo.program;
      try { await navigator.clipboard.writeText(text); byId('copy-answer').textContent='رونوشت تهیه شد ✓'; }
      catch (_) { byId('copy-answer').textContent='رونوشت در این مرورگر ممکن نیست'; }
      setTimeout(()=>byId('copy-answer').textContent='رونوشت پرسش و پاسخ',2500);
    });
  }

  function showOverlayWaiting(phrase='در انتظار انتشار پاسخ تازه ...') {
    byId('tv-question-tag').textContent = 'وضعیت سامانه';
    byId('tv-answer-label').textContent = 'آخرین وضعیت';
    byId('tv-question').textContent = phrase;
    byId('tv-answer-text').textContent = 'پاسخ‌ها پس از تکمیل پردازش برنامه به‌طور خودکار منتشر می‌شوند.';
    byId('tv-program').textContent = 'شبکه جهانی ولایت فارسی';
    byId('tv-counter').textContent = 'آرشیو خودکار دیدبان';
  }
  function overlayRender(reset) {
    const items = flatten();
    if (isDemo) byId('tv-demo').hidden = false;
    const published = feed.updated_at ? new Date(feed.updated_at).getTime() : NaN;
    const fresh = isDemo || (Number.isFinite(published) && (Date.now() - published) < OVERLAY_MAX_AGE_HOURS * 3_600_000 && (Date.now() - published) > -3_600_000);
    if (!items.length || !fresh) {
      showOverlayWaiting(!items.length ? 'در انتظار نخستین پاسخ ثبت‌شده ...' : 'در انتظار پاسخ تازه از برنامه‌ها ...');
      return;
    }
    const signature = String(feed.updated_at);
    if (reset && signature !== overlaySignature) {
      overlayIndex = 0;
      overlaySignature = signature;
    }
    const item = items[overlayIndex % Math.min(items.length,6)];
    byId('tv-question-tag').textContent = '●  پرسش مخاطب';
    byId('tv-answer-label').textContent = 'خلاصه پاسخ کارشناس ✓';
    byId('tv-question').textContent = item.question;
    byId('tv-answer-text').textContent = item.answer;
    byId('tv-program').textContent = [item.programInfo.program,item.programInfo.date].filter(Boolean).join(' | ');
    byId('tv-counter').textContent = fa(overlayIndex % Math.min(items.length,6) + 1) + ' / ' + fa(Math.min(items.length,6));
  }

  if (page === 'audience') setupAudience();
  loadFeed();
  setInterval(loadFeed, REFRESH_MS);
  if (page === 'overlay') setInterval(()=>{overlayIndex += 1;overlayRender(false);},OVERLAY_ROTATE_MS);
})();
