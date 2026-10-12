#!/usr/bin/env python3
"""Pasokhnama V4: evidence-first normalizer. No audio capture; no invented facts.

Inputs are existing Didban report records, Bale-derived reports, or optional
*structured expert segments* produced upstream. The output is public, so raw
transcripts, private reporter fields and unapproved model drafts never leave here.
"""
from __future__ import annotations
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from publish_site_data import safe_text, clean, seconds, obj, date_slot

TYPES = {'question_answer', 'audience_question', 'expert_point', 'expert_topic', 'expert_reference', 'expert_summary'}
TITLES = {'question_answer':'پرسش و پاسخ', 'audience_question':'پرسش مخاطب',
          'expert_point':'نکته علمی', 'expert_topic':'محور بحث کارشناس',
          'expert_reference':'مستندات بحث', 'expert_summary':'جمع‌بندی کارشناس'}
BAN_NON_SCIENTIFIC = re.compile(r'^(سلام|عرض ادب|ممنون|خوش آمدید|وقت بخیر|شب بخیر|خداحافظ|سپاسگزارم|تشکر از|بیننده عزیز|تماس بعدی)', re.I)


def normalized(s):
    return re.sub(r'[^\w]+','',str(s or '').replace('ي','ی').replace('ك','ک')).lower()


def absolute_time(start, offset):
    if not start or not re.fullmatch(r'\d\d:\d\d', str(start)): return None
    hh, mm = map(int, start.split(':'))
    return (datetime(2000,1,1,hh,mm)+timedelta(seconds=seconds(offset))).strftime('%H:%M')


def unwrap(source):
    if not isinstance(source,dict):return {}
    inner=obj(source.get('payload'))
    return inner if isinstance(inner,dict) else source


def make_item(program, kind, title, summary, *, q=None, seg=None, index=0, source='didban'):
    q=q or {};seg=seg or {}
    title=safe_text(title, 180)
    summary=safe_text(summary, 1200)
    excerpt=safe_text(seg.get('evidence_excerpt') or q.get('evidence_excerpt'), 450)
    if not title or (kind not in ('audience_question','expert_topic') and not summary):return None
    if BAN_NON_SCIENTIFIC.search(title):return None
    start=seg.get('start_sec',q.get('start_sec'))
    end=seg.get('end_sec',q.get('end_sec'))
    start = seconds(start) if start is not None else None
    end = seconds(end) if end is not None else None
    if start is not None and end is not None and end<start:end=start
    try: confidence=float(seg.get('confidence',q.get('confidence',0)))
    except (ValueError,TypeError):confidence=0
    confidence=min(1,max(0,confidence))
    given_status=str(seg.get('verification_status') or q.get('verification_status') or '').lower()
    explicit_role=str(seg.get('speaker_role') or q.get('answer_speaker_role') or '').lower()
    accepted_manual=given_status in ('approved','verified','human_approved')
    # Do not assume model output is speaker-verified: requires evidence + explicit role.
    evidenced=(len(excerpt)>=15 and confidence>=.85 and explicit_role=='expert'
              and (seg.get('speaker_verified') is True or q.get('speaker_verified') is True))
    approved=accepted_manual or evidenced
    allow_public_audience=seg.get('public_consent') is True or q.get('public_consent') is True
    status='approved' if accepted_manual else ('evidence_based' if evidenced else 'source_report')
    is_qa=kind in ('question_answer','audience_question')
    fingerprint=hashlib.sha256((program['id']+'|'+kind+'|'+normalized(title)+'|'+str(start or '')).encode()).hexdigest()[:18]
    # Existing Bale/Didban summaries can be searched, but are not automatically
    # attributed to a verified expert on live television.
    clock=absolute_time(program.get('start'),start) if start is not None else None
    return {'id':fingerprint, 'network':'velayat_farsi', 'program_id':program['id'],
      'program_title':program.get('program',''), 'expert_name':(program.get('expert') or None) if approved else None,
      'content_type':kind, 'display_label':TITLES[kind], 'title':title, 'summary':summary,
      'question':safe_text(q.get('question'),700) or (title if is_qa else None),
      'answer':safe_text(q.get('answer_summary') or q.get('answer'),1200) or (summary if kind=='question_answer' else None),
      'audience_name':(safe_text(q.get('audience_name') or q.get('name'),80) or None) if allow_public_audience else None,
      'audience_city':(safe_text(q.get('city') or q.get('audience_city'),70) or None) if allow_public_audience else None,
      'program_date':program.get('date_iso'), 'program_start_time':program.get('start'),
      'start_timecode':start, 'end_timecode':end,
      'estimated_answer_time':clock if is_qa else None,
      'source':source,'source_message_id':seg.get('source_message_id') or q.get('message_id'),
      'evidence_excerpt':excerpt if approved else '', # never expose unverified raw extracts
      'confidence':round(confidence,3), 'verification_status':status,
      'broadcast_eligible':bool(approved and (kind!='audience_question' or status=='approved')),
      'created_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
      'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds')}


def extract_content(raw, program, source='didban'):
    """Use only specifically present content. Legacy program key_points are report-based."""
    if not program or program.get('id','').startswith('arabic'):return []
    raw=unwrap(raw)
    ana=obj(raw.get('analysis'),{})
    if not isinstance(ana,dict):ana={}
    items=[]
    # Public V3 QA are retained as reported summaries, not verified live quotes.
    raw_qs=ana.get('audience_questions')
    if raw_qs is None:raw_qs=obj(raw.get('answered_questions'),[])
    raw_qs=obj(raw_qs,[]) if not isinstance(raw_qs,list) else raw_qs
    indexed_public=program.get('questions',[])
    for idx,q in enumerate(raw_qs if isinstance(raw_qs,list) else []):
        if not isinstance(q,dict):continue
        question=safe_text(q.get('question'),700)
        answer=safe_text(q.get('answer_summary') or q.get('answer'),1200)
        if not question:continue
        kind='question_answer' if answer else 'audience_question'
        merged=dict(q)
        if idx < len(indexed_public):
            # Explicitly stored program-side name/city survive Bale merging.
            merged['audience_name']=merged.get('audience_name') or indexed_public[idx].get('audience_name')
            merged['city']=merged.get('city') or indexed_public[idx].get('city')
        item=make_item(program,kind,question,answer or 'پاسخ هنوز در گزارش ثبت نشده است.',q=merged,source=source)
        if item:items.append(item)
    # The historical key_points don't identify their actual speaker; preserve
    # them as report-derived topics (not evidence-verified speech).
    points=ana.get('key_points') if ana.get('key_points') is not None else obj(raw.get('key_points'),[])
    if not isinstance(points,list):points=[]
    for p in points:
        if isinstance(p,str):p={'title':p}
        if not isinstance(p,dict):continue
        title=safe_text(p.get('title') or p.get('text'),180)
        if not title:continue
        item=make_item(program,'expert_topic',title,
                       p.get('summary') or title,
                       seg={**p, 'speaker_role':'unknown', 'speaker_verified':False},source=source)
        if item:items.append(item)
    # V4 explicit scientific segments. Can be authored by a trusted validated
    # diarized pipeline or submitted after editorial review.
    expert_segments=ana.get('expert_segments') if ana.get('expert_segments') is not None else raw.get('expert_segments',[])
    if not isinstance(expert_segments,list):expert_segments=[]
    for seg in expert_segments:
        if not isinstance(seg,dict):continue
        role=str(seg.get('speaker_role') or '').lower()
        if role in ('host','presenter','anchor','unknown','audience','caller'):continue
        if role!='expert':continue
        kind=seg.get('content_type') or 'expert_point'
        if kind not in TYPES or kind.startswith(('question_','audience_')):continue
        title=seg.get('title')
        summary=seg.get('summary')
        if not title or not summary:continue
        item=make_item(program,kind,title,summary,seg=seg,source=source)
        if item:items.append(item)
    # Deduplicate near-exact content preserving stronger evidence first.
    unique={}
    for item in items:
        item['source_reported_at']=raw.get('_posted_at')
        # Start time is excluded for near-duplicate texts in the same program.
        key=item['content_type']+'|'+normalized(item['title'])
        prev=unique.get(key)
        if not prev or (item['broadcast_eligible'] and not prev['broadcast_eligible']):unique[key]=item
    return list(unique.values())


def merge_item(old, fresh):
    if not old:return fresh
    if old.get('verification_status')=='approved' and fresh.get('verification_status')!='approved':
        fresh=dict(old)
    if old.get('audience_name') and not fresh.get('audience_name'):fresh['audience_name']=old['audience_name']
    if old.get('audience_city') and not fresh.get('audience_city'):fresh['audience_city']=old['audience_city']
    fresh['created_at']=old.get('created_at') or fresh['created_at']
    return fresh


def publish_content(programs, raw_sources, out_dir, live_program=None, last_analysis_at=None):
    """Idempotent append; never truncates previous years, no raw/private fields."""
    by_year={}
    for raw,program in zip(raw_sources,programs):
        for item in extract_content(raw,program,source='bale' if raw.get('_posted_at') else 'didban'):
            by_year.setdefault(item['program_date'][:4],[]).append(item)
    for year,arrival in by_year.items():
        path=out_dir/f'content-{year}.json'
        old=obj(path.read_text(encoding='utf-8'),{}) if path.exists() else {}
        entries={x['id']:x for x in old.get('items',[]) if isinstance(x,dict) and x.get('id')}
        for item in arrival:entries[item['id']]=merge_item(entries.get(item['id']),item)
        ordered=sorted(entries.values(),key=lambda x:(x.get('program_date') or '',x.get('program_start_time') or '',x.get('start_timecode') or 0),reverse=True)
        atomic_write(path,{'schema_version':4,'year':year,'items':ordered})
    paths=sorted(out_dir.glob('content-20??.json'),reverse=True)
    index=[]
    for path in paths:
        data=obj(path.read_text(encoding='utf-8'),{})
        records=data.get('items',[])
        index.append({'year':path.stem[-4:],'path':path.name,'count':len(records)})
    atomic_write(out_dir/'content-index.json',{'schema_version':4,
      'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
      'years':index,'total_items':sum(i['count'] for i in index)})
    # Only a current program and evidence-based/approved content are on TV.
    candidate=[]
    if live_program:
        path=out_dir/f'content-{live_program["date_iso"][:4]}.json'
        entries=obj(path.read_text(encoding='utf-8'),{}).get('items',[]) if path.exists() else []
        candidate=[x for x in entries if x.get('program_id')==live_program['id'] and x.get('broadcast_eligible')]
        candidate.sort(key=lambda x:x.get('start_timecode') if x.get('start_timecode') is not None else -1,reverse=True)
    if not live_program:
        return  # A manual deployment without a report must not erase the last successful analysis.
    atomic_write(out_dir/'live.json',{'schema_version':4,'program_id':live_program['id'] if live_program else None,
       'program_title':live_program.get('program','') if live_program else '',
       'program_date':live_program.get('date_iso') if live_program else None,
       'program_start_time':live_program.get('start') if live_program else None,
       'expert_name':live_program.get('expert') if live_program else None,
       'last_analysis_at':last_analysis_at,
       'last_report_published_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'items':candidate[:40]})


def atomic_write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    tmp.replace(path)
