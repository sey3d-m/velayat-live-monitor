#!/usr/bin/env python3
"""OPTIONAL V4 transcript-to-expert-segment model adaptor.

This script does NOT transcribe audio, change Didban, or independently verify the
voice. Run only with existing private transcript and GEMINI_API_KEY. In the
absence of trusted transcript speaker labels, all output remains unverified and
is NEVER eligible for automatic television publication.
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from publish_site_data import obj, public_program, safe_text

PROMPT='''شما ویراستار استخراج محتوای مستند شبکه ولایت فارسی هستید. از همین رونوشت و فقط همین رونوشت، حداکثر ۱۰ نکته علمی برجسته استخراج کنید. فقط سخن علمی صریح کارشناس، نه مجری؛ اگر نقش گوینده روشن نیست speaker_role را unknown بگذارید. سلام، شوخی، دعا، معرفی، تبلیغ، سخنان حاشیه‌ای و تکرار مجری را حذف کنید. نقل‌قول یا نام کتاب/آیه/روایت را اختراع نکنید. evidence_excerpt باید عیناً عبارتی از رونوشت باشد. متن‌ها را فارسی، دقیق و کوتاه بنویسید. برای هر مورد JSON شامل content_type یکی از expert_point/expert_topic/expert_reference/expert_summary، title، summary، evidence_excerpt، speaker_role، confidence (0 تا 1) بسازید. چنانچه مطلبی قطعی نیست آن را حذف کنید. JSON یک شیء با کلید expert_segments باشد؛ هیچ متن اضافه‌ای ننویسید.'''

def segments(text, size=16000, overlap=650, max_chunks=8):
    if not text.strip():return []
    arr=[]; pos=0
    while pos<len(text) and len(arr)<max_chunks:
        end=min(len(text),pos+size)
        arr.append(text[pos:end])
        if end==len(text):break
        pos=end-overlap
    return arr

def gemini_analyze(transcript,api_key,model):
    url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
    prompt=PROMPT+'\n\n<رونوشت>\n'+transcript+'\n</رونوشت>'
    payload={'contents':[{'role':'user','parts':[{'text':prompt}]}],
     'generationConfig':{'temperature':0.1,'responseMimeType':'application/json'}}
    request_data=json.dumps(payload,ensure_ascii=False).encode('utf8')
    last=None
    for attempt in range(3):
        req=urllib.request.Request(url,data=request_data,method='POST',headers={
            'Content-Type':'application/json','x-goog-api-key':api_key})
        try:
            with urllib.request.urlopen(req,timeout=70) as res:
                decoded=json.loads(res.read(250000).decode('utf8'))
            answer=decoded.get('candidates',[{}])[0].get('content',{}).get('parts',[{}])[0].get('text','{}')
            parsed=json.loads(answer)
            if not isinstance(parsed,dict) or not isinstance(parsed.get('expert_segments'),list):return []
            return parsed['expert_segments']
        except urllib.error.HTTPError as err:
            last=err
            if err.code not in (429,500,502,503,504):break
        except (OSError,ValueError,IndexError,KeyError) as err:last=err
        if attempt<2:time.sleep(2**attempt)
    raise RuntimeError('Gemini transcript analysis failed; original monitor is unchanged') from last

def normalize_segments(text,proposed):
    # Evidence must be an EXACT substring of original to avoid invented citations.
    normalized=[];used=set()
    for record in proposed:
        if not isinstance(record,dict):continue
        excerpt=str(record.get('evidence_excerpt') or '').strip()
        role=str(record.get('speaker_role') or 'unknown').lower()
        title=safe_text(record.get('title'),180)
        summary=safe_text(record.get('summary'),900)
        kind=record.get('content_type')
        if kind not in ('expert_point','expert_topic','expert_reference','expert_summary'):continue
        if not excerpt or excerpt not in text or not title or not summary:continue
        if role!='expert':continue # presenter/unknown must never enter public expert archive
        key=(kind,re.sub(r'\W+','',title))
        if key in used:continue
        used.add(key)
        try:conf=float(record.get('confidence',0))
        except(TypeError,ValueError):conf=0
        before=text[max(0,text.index(excerpt)-55):text.index(excerpt)]
        # The source explicitly labels the speaker; a model guess alone is NOT enough.
        is_labeled=bool(re.search(r'(?:\[expert\]|\[کارشناس\]|کارشناس\s*[:：])[^\n]{0,40}$',before,re.I))
        # Existing TIMED transcript markers are the only basis for timecodes.
        time_start=time_end=None
        stamps=list(re.finditer(r'\[(\d{2}:\d{2}:\d{2})\s*-\s*(\d{2}:\d{2}:\d{2})\]',text[:text.index(excerpt)]))
        if stamps:
            last=stamps[-1]
            def as_seconds(value):
                h,m,sec=map(int,value.split(':'))
                return h*3600+m*60+sec
            time_start=as_seconds(last.group(1))
            time_end=as_seconds(last.group(2))
        normalized.append({'content_type':kind,'title':title,'summary':summary,
            'evidence_excerpt':safe_text(excerpt,450),'speaker_role':'expert',
            'speaker_verified':is_labeled,'confidence':min(1,max(0,conf)),
            'start_sec':time_start, 'end_sec':time_end,
            'verification_status':'pending'})
    return normalized

def main():
    ap=argparse.ArgumentParser(description='Optional AI analysis of an already transcribed Persian Didban program')
    ap.add_argument('--report',required=True)
    ap.add_argument('--transcript',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--model',default=os.environ.get('PASOKHNAMA_GEMINI_MODEL','gemini-2.5-flash'))
    ap.add_argument('--max-chunks',type=int,default=8)
    args=ap.parse_args()
    api_key=os.environ.get('GEMINI_API_KEY','')
    if not api_key:sys.exit('GEMINI_API_KEY missing; no external analysis performed.')
    raw=obj(Path(args.report).read_text(encoding='utf8'),{})
    if not isinstance(raw,dict) or not public_program(raw):sys.exit('Report is not a valid Persian Velayat program.')
    text=Path(args.transcript).read_text(encoding='utf8')
    blocks=segments(text,max_chunks=max(1,min(args.max_chunks,30)))
    candidates=[]
    for chunk in blocks:
        try:candidates.extend(normalize_segments(chunk,gemini_analyze(chunk,api_key,args.model)))
        except RuntimeError as exc:print(str(exc),file=sys.stderr) # never jeopardize Didban
    payload=raw.get('payload') if isinstance(raw.get('payload'),dict) else raw
    analysis=payload.get('analysis')
    if not isinstance(analysis,dict):analysis={};payload['analysis']=analysis
    analysis['expert_segments']=candidates
    # Output *temporary private* structured report. Do not commit transcript.
    p=Path(args.out);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(raw,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'Validated segments: {len(candidates)}; transcript chunks analyzed: {len(blocks)}.')
    if len(text)>16000*len(blocks):print('WARNING: transcript truncation due to --max-chunks',file=sys.stderr)

if __name__=='__main__':main()
