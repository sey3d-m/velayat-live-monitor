#!/usr/bin/env python3
"""Static, public, privacy-filtered lifelong archive for Velayat Monitor.

Supported sources: diagnostic program_report.json, Monitor Sheets webhook rows
(JSON/CSV/JSONL exports), existing v1 feed. Never publishes private transcript,
internal editorial reviews, viewer names, credentials or raw import files.
"""
import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_SCHEMA = 2
MAX_TEXT = 12000
DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def clean(value, maxlen=MAX_TEXT):
    if value is None: return ''
    value = str(value)
    value = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', ' ', value)
    return value.strip()[:maxlen]


def safe_text(value, limit=MAX_TEXT):
    """Minimal sanitization: editors MUST review public summaries in sensitive cases."""
    value = clean(value, limit)
    value = re.sub(r'[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}', '[ایمیل حذف شد]', value)
    value = re.sub(r'(?<![\w])@[A-Za-z0-9_]{4,}', '[شناسه حذف شد]', value)
    normalized = value.translate(DIGITS)
    patterns = [r'(?<!\d)09\d{9}(?!\d)', r'(?<!\d)(?:\+98|0098)[\s-]?9\d{9}(?!\d)']
    locations = []
    for pat in patterns:
        locations.extend((m.start(), m.end()) for m in re.finditer(pat, normalized))
    for a, b in sorted(set(locations), reverse=True):
        value = value[:a] + '[شماره حذف شد]' + value[b:]
    return value


def obj(value, default=None):
    if isinstance(value, (dict, list)): return value
    if isinstance(value, str):
        try: return json.loads(value.strip())
        except (json.JSONDecodeError, ValueError): pass
    return default


def seconds(value):
    try: return max(0, min(int(float(value)), 21600))
    except (TypeError, ValueError, OverflowError): return 0


def short_list(value, limit=15):
    data = obj(value, [])
    if not isinstance(data, list): return []
    return data[:limit]


def date_slot(data):
    date = clean(data.get('scheduled_date'), 10)
    slot = clean(data.get('start'), 5)
    rid = clean(data.get('report_id'), 90)
    if rid:
        m = re.match(r'^(\d{4}-\d{2}-\d{2})_(?:persian|fa)_(\d{2})(\d{2})$', rid)
        if m:
            date = date or m.group(1)
            slot = slot or m.group(2) + ':' + m.group(3)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date): return None
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', slot): return None
    return date, slot


def public_program(data):
    """Convert monitor diagnostic or Google Sheets exported payload to safe public data."""
    if not isinstance(data, dict): return None
    nested = obj(data.get('payload'), None)
    if isinstance(nested, dict): data = nested
    network = clean(data.get('network'), 24)
    if network not in ('persian', 'fa'): return None  # enforce Persian-only imports
    if data.get('analysis_available') is False: return None
    dt = date_slot(data)
    if not dt: return None
    date, slot = dt
    analysis = obj(data.get('analysis'), {})
    if not isinstance(analysis, dict): analysis = {}
    def field(k): return analysis.get(k) if analysis.get(k) not in (None, '') else data.get(k)
    answered = field('audience_questions')
    if answered is None: answered = data.get('answered_questions', [])
    questions = []
    for i, q in enumerate(short_list(answered, 2000)):
        if not isinstance(q, dict): continue
        question = safe_text(q.get('question'), 700)
        answer = safe_text(q.get('answer_summary') or q.get('answer'), 2400)
        if not question or not answer: continue
        start, end = seconds(q.get('start_sec')), seconds(q.get('end_sec'))
        if end < start: end = start
        s = q.get('source_type') or q.get('source') or 'unknown'
        if s not in ('phone', 'message', 'unknown'): s = 'unknown'
        # Stable hash prevents duplicates even when row ordering changes.
        # Names/cities may be published only when explicitly present in the
        # broadcaster's original audience Q&A report. No inference from context.
        audience_name = safe_text(q.get('audience_name') or q.get('name'), 100)
        if audience_name in ('نامشخص','ناشناس','-'): audience_name = ''
        city = safe_text(q.get('city') or q.get('audience_city'), 80)
        if city in ('نامشخص','ناشناس','-'): city = ''
        # A response starts after the question; this is a rough broadcast-clock
        # position, not the exact second when the expert began answering.
        hh, mm = map(int, slot.split(':'))
        answer_time = (datetime(2000, 1, 1, hh, mm) + timedelta(seconds=start)).strftime('%H:%M')
        answer_time_end = (datetime(2000, 1, 1, hh, mm) + timedelta(seconds=end)).strftime('%H:%M')
        fingerprint = hashlib.sha256((question + '\n' + answer).encode('utf-8')).hexdigest()[:12]
        questions.append({'id': f'{date}-{slot.replace(":", "")}-{fingerprint}',
            'question': question, 'answer': answer, 'start_sec': start,
            'end_sec': end, 'source': s, 'status': 'answered',
            'audience_name': audience_name, 'city': city,
            'answer_time_approx': answer_time, 'answer_time_end_approx': answer_time_end})
    # Artificial duplicates in export sources are folded by ID.
    questions = list({q['id']: q for q in questions}.values())
    points = []
    for p in short_list(field('key_points'), 200):
        if isinstance(p, str): p = {'title': p}
        if not isinstance(p, dict): continue
        title = safe_text(p.get('title') or p.get('text'), 450)
        if title:
            points.append({'title': title, 'start_sec': seconds(p.get('start_sec')), 'end_sec': seconds(p.get('end_sec'))})
    clips = []
    for clip in short_list(field('viral_clips'), 30):
        if not isinstance(clip, dict): continue
        title = safe_text(clip.get('media_title'), 200)
        if title: clips.append({'title': title, 'start_sec': seconds(clip.get('start_sec')), 'end_sec': seconds(clip.get('end_sec'))})
    raw_tags = field('hashtags')
    if isinstance(raw_tags, str):
        raw_tags = obj(raw_tags, [x for x in re.split(r'[,،\s]+', raw_tags) if x])
    tags = [safe_text(x, 60) for x in (raw_tags if isinstance(raw_tags, list) else [])[:20] if isinstance(x, str)]
    summary = safe_text(field('summary'), 9000)
    return {'id': f'persian-{date}-{slot.replace(":", "")}', 'date_iso': date,
        'date': clean(data.get('date'), 35), 'day': clean(data.get('day'), 30),
        'start': slot, 'end': clean(data.get('end'), 5),
        'program': safe_text(data.get('program') or data.get('program_name'), 150),
        'program_title': safe_text(field('program_title'), 250),
        'topic': safe_text(field('topic'), 250),
        'host': safe_text(field('host'), 90), 'expert': safe_text(field('expert'), 90),
        'summary': summary, 'key_points': points, 'hashtags': tags, 'clips': clips,
        'quality': 'partial' if data.get('status') == 'PARTIAL' or obj(data.get('transcription'), {}).get('transcript_incomplete') is True else 'complete',
        'questions': questions}


def merge(old, new):
    if not isinstance(old, dict): return new
    # Don't erase previous rich content with empty fields from a partial import.
    for key in ('summary','program_title','topic','program','date','day','end','expert','host'):
        if not new.get(key) and old.get(key): new[key] = old[key]
    for key in ('questions','key_points','hashtags','clips'):
        if not new.get(key) and old.get(key): new[key] = old[key]
    # Keep rich audience metadata recovered from Bale even if a newer monitor
    # re-runs the same program and does not include the city field.
    if old.get('questions') and new.get('questions'):
        lookup = {(q.get('question','').strip(), q.get('start_sec')):q for q in old['questions']}
        present = {(q.get('question','').strip(),q.get('start_sec')) for q in new['questions']}
        for q in new['questions']:
            historic = lookup.get((q.get('question','').strip(),q.get('start_sec')))
            if historic:
                for key in ('audience_name','city','answer_time_approx','answer_time_end_approx'):
                    if not q.get(key) and historic.get(key):q[key]=historic[key]
        for key,q in lookup.items():
            if key not in present:new['questions'].append(q)
    if old.get('quality') == 'complete' and new.get('quality') == 'partial': new['quality'] = 'complete'
    return new


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def ingest(programs, out_dir):
    by_year = {}
    for program in programs:
        if not isinstance(program, dict) or not program.get('id') or not program.get('date_iso'): continue
        year = program['date_iso'][:4]
        if not re.fullmatch(r'20\d\d', year): continue
        by_year.setdefault(year, []).append(program)
    count = 0
    for year, arriving in by_year.items():
        path = out_dir / f'archive-{year}.json'
        existing = obj(path.read_text(encoding='utf-8'), {}) if path.exists() else {}
        records = {p['id']: p for p in existing.get('programs', []) if isinstance(p, dict) and p.get('id')}
        for p in arriving:
            records[p['id']] = merge(records.get(p['id']), p)
            count += 1
        sorted_records = sorted(records.values(), key=lambda p: (p.get('date_iso',''), p.get('start','')), reverse=True)
        atomic_json(path, {'schema_version': DATA_SCHEMA, 'year': year, 'programs': sorted_records})
    refresh_index(out_dir)
    return count


def refresh_index(out_dir):
    years = []
    for file in sorted(out_dir.glob('archive-20??.json'), reverse=True):
        archive = obj(file.read_text(encoding='utf-8'), {})
        programs = archive.get('programs', [])
        if not isinstance(programs, list): continue
        years.append({'year': file.stem[-4:], 'path': file.name,
            'program_count': len(programs), 'question_count': sum(len(x.get('questions',[])) for x in programs)})
    atomic_json(out_dir / 'index.json', {'schema_version':DATA_SCHEMA,
       'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
       'years': years, 'total_programs':sum(x['program_count'] for x in years),
       'total_questions':sum(x['question_count'] for x in years),
       'source':'Velayat Live Monitor – public archive'})


def read_records(path):
    suffix = path.suffix.lower()
    if suffix == '.csv':
        with path.open(encoding='utf-8-sig', newline='') as fh:
            yield from csv.DictReader(fh)
    elif suffix in ('.jsonl', '.ndjson'):
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip(): yield json.loads(line)
    elif suffix == '.json':
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
        if isinstance(raw, list): yield from raw
        elif isinstance(raw, dict):
            if isinstance(raw.get('programs'), list): yield from raw['programs']
            elif isinstance(raw.get('rows'), list): yield from raw['rows']
            elif isinstance(raw.get('reports'), list): yield from raw['reports']
            else: yield raw
    else: raise ValueError('Only .csv, .json or .jsonl files are supported')


def main():
    ap = argparse.ArgumentParser(description='Create public year-sharded archive; no secrets exported')
    ap.add_argument('--report', action='append', default=[], help='Current program_report.json')
    ap.add_argument('--import-file', action='append', default=[], help='Historical JSON/CSV/JSONL exports')
    ap.add_argument('--migrate-feed', default='', help='Old v1 public feed.json (up to 36 entries)')
    ap.add_argument('--out-dir', default='docs/data')
    ap.add_argument('--expert-file', action='append', default=[], help='Optional structured V4 expert segments with program metadata')
    args = ap.parse_args()
    out = Path(args.out_dir)
    collected = []
    extracted_sources = []
    latest_current = None
    latest_analysis_at = None
    for rawpath in args.report + args.import_file + args.expert_file:
        path = Path(rawpath)
        if not path.exists(): raise FileNotFoundError(path)
        for data in read_records(path):
            public = public_program(data)
            if public:
                collected.append(public)
                extracted_sources.append(data)
                if rawpath in args.report or rawpath in args.expert_file:
                    latest_current = public
                    candidate = data.get('analysis_completed_at') or data.get('completed_at') or data.get('processed_at')
                    if not candidate and isinstance(obj(data.get('payload')),dict):
                        nested = obj(data.get('payload'))
                        candidate = nested.get('analysis_completed_at') or nested.get('completed_at')
                    if isinstance(candidate,str):
                        try:
                            parsed = datetime.fromisoformat(candidate.replace('Z','+00:00'))
                            latest_analysis_at = parsed.astimezone(timezone.utc).isoformat(timespec='seconds') if parsed.tzinfo else None
                        except ValueError: latest_analysis_at = None
                    else: latest_analysis_at = None
    if args.migrate_feed:
        path = Path(args.migrate_feed)
        if path.exists():
            for p in read_records(path):
                if isinstance(p, dict) and p.get('date_iso') and p.get('id'):
                    # Old feed is already public/sanitized and may not contain summary.
                    p.setdefault('summary','')
                    p.setdefault('key_points',[])
                    p.setdefault('hashtags',[])
                    p.setdefault('clips',[])
                    existing_archive = out / ('archive-' + p['date_iso'][:4] + '.json')
                    existing_ids = set()
                    if existing_archive.exists():
                        previous = obj(existing_archive.read_text(encoding='utf-8'), {})
                        existing_ids = {x.get('id') for x in previous.get('programs', [])}
                    if p['id'] not in existing_ids:
                        collected.append(p)
                        extracted_sources.append({'analysis': {'audience_questions': [dict(q, answer_summary=q.get('answer','')) for q in p.get('questions',[])], 'key_points':p.get('key_points',[])}})
    changed = ingest(collected, out)
    # Build V4 search and TV feeds without changing the existing Didban engine.
    # Restore previously archived V3 program records that no longer have raw reports.
    from smart_content import publish_content
    included = {p['id'] for p in collected}
    for archive_file in out.glob('archive-20??.json'):
        for p in obj(archive_file.read_text(encoding='utf-8'),{}).get('programs',[]):
            if not isinstance(p,dict) or p.get('id') in included: continue
            raw = {'analysis': {'audience_questions': [dict(q, answer_summary=q.get('answer',''))
                      for q in p.get('questions',[])], 'key_points':p.get('key_points',[])}}
            extracted_sources.append(raw)
            collected.append(p)
            included.add(p['id'])
    publish_content(collected, extracted_sources, out, live_program=latest_current, last_analysis_at=latest_analysis_at)
    print(f'Public archive: imported {changed} records; {len(list(out.glob("archive-20??.json")))} years')

if __name__ == '__main__': main()
