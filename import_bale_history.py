#!/usr/bin/env python3
"""Import **existing** Persian Velayat Bale *text reports* into the dashboard.

This is an offline importer. It does NOT call Bale's Bot API and does not claim
that getUpdates exposes old channel history. Input: exported JSON/JSONL/TXT
messages, preserving message bodies; no credentials or direct account login.
Output: structured report JSON for publish_site_data.py, never raw messages.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys

FA_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
SEP = r'\s*(?:تا|الی|–|-)\s*'
PART1 = re.compile(r'📌\s*بخش اول\s*\|\s*خلاصه برنامه[‌\s-]*های زنده شبکه ولایت')
PART2 = re.compile(r'📌\s*بخش دوم\s*\|\s*تحلیل تکمیلی برنامه[‌\s-]*های زنده شبکه ولایت')
QUESTION = re.compile(r'^\s*([\d۰-۹]+)\.\s*\[([^]]+)\]\s*(.+?)\s*$')
TIMERANGE = re.compile(r'⏱\s*(\d\d?:\d\d(?::\d\d)?)' + SEP + r'(\d\d?:\d\d(?::\d\d)?)')
HEADER = re.compile(r'^[\s\u200f\u200e]*(?:📌|📝|🔹|❓|🚀|🧠|🎙|📊|⚠️)')
KNOWN_CITIES = ('قم','تهران','مشهد','اصفهان','شیراز','تبریز','اهواز','کرج','یزد','کرمان','رشت','اراک','قزوین','ساری','بابل','زنجان','کاشان','همدان','سنندج','کرمانشاه','بندرعباس','بوشهر','بیرجند','اردبیل','خرم‌آباد','خرم آباد','گرگان','ارومیه','زاهدان','دزفول','نجف','کربلا','بغداد','کابل','هرات','مزارشریف','مزار شریف','دوحه','دبی','دوشنبه','لندن','اسلام‌آباد','اسلام آباد')
CITIES_RX = re.compile(r'(?<!\w)(?:از شهر|اهل شهر|ساکن شهر|ساکن|اهل|از)\s+(' + '|'.join(re.escape(x) for x in sorted(KNOWN_CITIES,key=len,reverse=True)) + r')(?!\w)')
EXPLICIT_CITY_RX = re.compile(r'(?<!\w)(?:از شهر|ساکن شهر|اهل شهر)\s+([آ-ی\u200c]{2,25})(?=[\s،.؛!?]|$)')


def digit(text): return str(text or '').translate(FA_DIGITS)
def trimmed(text): return str(text or '').strip().replace('\r\n','\n')
def value(lines, key):
    for line in lines:
        m = re.search(r'^\s*(?:[🗓📺📰🎙👤🕒🎯🏷]\s*)?' + re.escape(key) + r'\s*:\s*(.*?)\s*$', line)
        if m: return m.group(1).strip()
    return ''


def j2g(jy,jm,jd):
    # Well-established Jalali arithmetic conversion; validate with datetime.
    jy, jm, jd = jy-979, jm-1, jd-1
    j_day_no=365*jy+(jy//33)*8+((jy%33)+3)//4
    for n in (31,31,31,31,31,31,30,30,30,30,30,29)[:jm]: j_day_no+=n
    j_day_no+=jd
    g_day_no=j_day_no+79
    gy=1600+400*(g_day_no//146097); g_day_no%=146097
    leap=True
    if g_day_no>=36525:
        g_day_no-=1; gy+=100*(g_day_no//36524); g_day_no%=36524
        if g_day_no>=365: g_day_no+=1
        else: leap=False
    gy+=4*(g_day_no//1461);g_day_no%=1461
    if g_day_no>=366:
        leap=False;g_day_no-=1;gy+=g_day_no//365;g_day_no%=365
    mdays=[31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31]
    for month,days in enumerate(mdays,1):
        if g_day_no<days:return datetime(gy,month,g_day_no+1).date().isoformat()
        g_day_no-=days
    raise ValueError('invalid Jalali day')


def parse_date(text):
    text=digit(text)
    m=re.search(r'(?<!\d)(1[34]\d\d)[/\-.](0?[1-9]|1[0-2])[/\-.]([0-2]?\d|3[01])(?!\d)',text)
    if m:
        y,mo,d=map(int,m.groups())
        try:return j2g(y,mo,d)
        except(ValueError,OverflowError):return None
    m=re.search(r'(?<!\d)(20\d\d)[/\-.](0?[1-9]|1[0-2])[/\-.]([0-2]?\d|3[01])(?!\d)',text)
    if m:
        try:return datetime(*map(int,m.groups())).date().isoformat()
        except ValueError:return None
    return None


def parse_time(text):
    m=re.search(r'([0-2]?\d):([0-5]\d)',digit(text))
    if not m or int(m.group(1))>23:return ''
    return f'{int(m.group(1)):02}:{m.group(2)}'


def parse_seconds(stamp):
    vals=digit(stamp).split(':')
    try:
        n=list(map(int,vals))
        if len(n)==3 and n[1]<60 and n[2]<60:return n[0]*3600+n[1]*60+n[2]
        if len(n)==2 and n[1]<60:return n[0]*60+n[1]
    except ValueError:pass
    return 0


def message_datetime(obj):
    for k in ('date','datetime','timestamp','sent_at','created_at'):
        raw=obj.get(k)
        if isinstance(raw,(int,float)):
            try:return datetime.fromtimestamp(raw,timezone.utc).isoformat()
            except (OverflowError,ValueError,OSError):pass
        if isinstance(raw,str):
            try:return datetime.fromisoformat(raw.replace('Z','+00:00')).isoformat()
            except ValueError:pass
    return None


def load_messages(path):
    raw=path.read_text(encoding='utf-8-sig')
    if path.suffix.lower()=='.txt' or (not raw.lstrip().startswith(('{','[')) and ('📌' in raw or 'بخش اول' in raw)):
        # Bale reports have distinctive headings; splitting retains both in order.
        segments=re.split(r'(?=📌\s*بخش\s*(?:اول|دوم)\s*\|)',raw)
        return [{'text':s.strip()} for s in segments if (PART1.search(s) or PART2.search(s))]
    if path.suffix.lower() in ('.jsonl','.ndjson'):
        records=[json.loads(line) for line in raw.splitlines() if line.strip()]
    else:
        records=json.loads(raw)
        if isinstance(records,dict):
            for key in ('messages','result','updates','rows','data','items'):
                if isinstance(records.get(key),list):records=records[key];break
            else:records=[records]
    extracted=[]
    for r in records:
        if isinstance(r,str):
            extracted.append({'text':r,'posted_at':None});continue
        if not isinstance(r,dict):continue
        entry=r.get('channel_post') or r.get('message') or r.get('edited_channel_post') or r
        if not isinstance(entry,dict):continue
        body=entry.get('text') or entry.get('caption') or entry.get('body') or ''
        if isinstance(body,list):body=''.join(x if isinstance(x,str) else x.get('text','') for x in body)
        if isinstance(body,str) and body.strip():
            extracted.append({'text':body,'posted_at':message_datetime(entry) or message_datetime(r),
                'message_id':entry.get('message_id',entry.get('id'))})
    # The Velayat broadcaster chunks Bale posts around 3900 chars. Re-join a
    # likely continuation when it immediately follows a nearly-full report
    # chunk. Never join a new report's own Part1/Part2 heading.
    joined=[]
    for item in extracted:
        text=item['text']
        if joined and not (PART1.search(text) or PART2.search(text)):
            prev=joined[-1]
            could_contain_report=bool(PART1.search(prev['text']) or PART2.search(prev['text']))
            maybe_split=len(prev['text'].split('\n')[-1])>=3500 or len(prev['text'])>=3500
            timely=True
            if prev.get('posted_at') and item.get('posted_at'):
                try:
                    d1=datetime.fromisoformat(prev['posted_at']);d2=datetime.fromisoformat(item['posted_at'])
                    timely=0 <= (d2-d1).total_seconds() <= 240
                except(ValueError,TypeError):timely=False
            if could_contain_report and maybe_split and timely:
                prev['text']+='\n'+text
                continue
        joined.append(item)
    return [x for x in joined if PART1.search(x['text']) or PART2.search(x['text'])]


def extract_summary(lines):
    start=next((i for i,s in enumerate(lines) if 'خلاصه مباحث برنامه' in s),None)
    if start is None:return ''
    result=[]
    for s in lines[start+1:]:
        if HEADER.match(s) and ('محورهای اصلی' in s or 'بخش دوم' in s or 'پیاده‌سازی این بخش ناقص' in s):break
        result.append(s)
    return '\n'.join(result).strip()[:9000]


def points_from(lines):
    start=next((i for i,s in enumerate(lines) if 'محورهای اصلی با تایم' in s),None)
    if start is None:return []
    points=[]
    for line in lines[start+1:]:
        if HEADER.match(line):break
        m=re.match(r'^\s*([\d۰-۹]+)\.\s*(.+)\s*$',line)
        if m:points.append({'title':m.group(2).strip(),'start_sec':0,'end_sec':0})
        elif TIMERANGE.search(digit(line)) and points:
            t=TIMERANGE.search(digit(line));points[-1].update(start_sec=parse_seconds(t.group(1)),end_sec=parse_seconds(t.group(2)))
    return points


def parse_part1(msg):
    lines=trimmed(msg['text']).splitlines()
    title=value(lines,'تیتر کلی')
    program=value(lines,'نام برنامه')
    dtstr=value(lines,'تاریخ')
    date=parse_date(dtstr)
    times=value(lines,'زمان برنامه')
    slot=parse_time(times)
    end=parse_time(times.split('تا')[-1]) if 'تا' in times else ''
    if not date or not slot or not program:return None
    return {'network':'persian','scheduled_date':date,'date':dtstr,'start':slot,'end':end,
        'program':program,'analysis':{'program_title':title,'topic':value(lines,'موضوع'),
        'host':value(lines,'مجری'),'expert':value(lines,'کارشناس'),
        'summary':extract_summary(lines),'key_points':points_from(lines),
        'hashtags':value(lines,'هشتگ‌ها').split(), 'audience_questions':[]},
        '_posted_at':msg.get('posted_at')}


def safe_name_city(label, question):
    """Read ONLY names and cities explicitly present in audience self-identification."""
    parts=re.split(r'\s*[–—-]\s*',label,maxsplit=1)
    source_label=parts[0]
    source='phone' if 'تلفنی' in source_label else 'message' if ('پیام' in source_label or 'پیامک' in source_label) else 'unknown'
    name=parts[1].strip() if len(parts)>1 else ''
    city=''
    for string in (name,question):
        match=EXPLICIT_CITY_RX.search(string) or CITIES_RX.search(string)
        if match:
            city=match.group(1);break
    if name:
        name=EXPLICIT_CITY_RX.sub('',name)
        name=CITIES_RX.sub('',name).strip(' ،؛-–')
        name=re.sub(r'^(?:آقا(?:ی)?|خانم)\s*[:،]?\s*','',name).strip()
    if name in ('نامشخص','ناشناس','-','ـ'):name=''
    return source,name,city


def parse_part2(msg):
    lines=trimmed(msg['text']).splitlines()
    questions=[]
    inside=False
    i=0
    while i<len(lines):
        line=lines[i]
        if 'سؤالات مخاطبان و چکیده پاسخ' in line:inside=True;i+=1;continue
        if inside and HEADER.match(line) and ('پیشنهادهای وایرال' in line or 'ارزیابی کوتاه' in line or 'آمار مخاطبان' in line):break
        m=QUESTION.match(line) if inside else None
        if not m:i+=1;continue
        label, question=m.group(2).strip(),m.group(3).strip()
        i+=1;start=end=0; answer=[];answering=False
        while i<len(lines):
            line=lines[i]
            if QUESTION.match(line) or (HEADER.match(line) and ('پیشنهادهای وایرال' in line or 'ارزیابی کوتاه' in line or 'آمار مخاطبان' in line)):break
            t=TIMERANGE.search(digit(line))
            if t and not answering:start=parse_seconds(t.group(1));end=parse_seconds(t.group(2))
            elif '↳ پاسخ:' in line:
                answering=True;answer.append(line.split('↳ پاسخ:',1)[-1].strip())
            elif answering and line.strip():answer.append(line.strip())
            i+=1
        answer_text=' '.join(answer).strip()
        if question and answer_text:
            source,name,city=safe_name_city(label,question)
            questions.append({'question':question,'answer_summary':answer_text,
                'source_type':source,'audience_name':name or 'نامشخص',
                'city':city,'start_sec':start,'end_sec':max(start,end),
                'message_id':msg.get('message_id')})
    return {'program':value(lines,'برنامه'),'title':value(lines,'تیتر کلی'), 'questions':questions,
            'posted_at':msg.get('posted_at')}


def normalized(x):return re.sub(r'[\W_]+','',digit(x or '').replace('ي','ی').replace('ك','ک')).lower()


def merge_from_bale(messages):
    programs=[]; orphan=0; skipped=0
    for msg in messages:
        body=trimmed(msg.get('text',''))
        if PART1.search(body):
            item=parse_part1(msg)
            if item:programs.append(item)
            else:skipped+=1
        elif PART2.search(body):
            p2=parse_part2(msg)
            candidates=[p for p in programs if normalized(p['program'])==normalized(p2['program']) and
                        (not p2['title'] or normalized(p['analysis']['program_title'])==normalized(p2['title']))]
            # Recent, prior Part1 preferred. Never assign to unrelated broadcasts.
            if candidates:
                p=candidates[-1]
                existing=p['analysis']['audience_questions']
                ids={(normalized(q['question']),q['start_sec']) for q in existing}
                for q in p2['questions']:
                    key=(normalized(q['question']),q['start_sec'])
                    if key not in ids:existing.append(q);ids.add(key)
            else:orphan+=1
    return programs,orphan,skipped


def main():
    a=argparse.ArgumentParser(description='Convert existing Bale Persian reports into public-archive import records.')
    a.add_argument('--input',action='append',required=True,help='Exported .txt, .json, or .jsonl message archive')
    a.add_argument('--output',required=True,help='Temporary structured report JSON (not raw channel messages)')
    args=a.parse_args()
    messages=[]
    for path in args.input:messages.extend(load_messages(Path(path)))
    programs,orphan,skipped=merge_from_bale(messages)
    if not programs:
        print('No valid Persian Part1 messages with explicit date, program and time found.',file=sys.stderr)
        return 2
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    Path(args.output).write_text(json.dumps({'reports':programs},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Persian Bale messages: {len(messages)}; programs: {len(programs)}; QA: {sum(len(p["analysis"]["audience_questions"]) for p in programs)}; unmatched Part2: {orphan}; invalid Part1: {skipped}')
    if orphan:print('WARNING: Some Part2 reports were not matched; supply the corresponding Part1 messages.',file=sys.stderr)
    return 0
if __name__=='__main__':raise SystemExit(main())
