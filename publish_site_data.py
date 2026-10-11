#!/usr/bin/env python3
"""Publish only public, anonymized Q&A data from existing Velayat Monitor JSON.

This adapter does not change STT, analysis, Gemini, Sheets, Bale or scheduling.
No webhook secrets, transcripts or internal review findings enter the public feed.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_PROGRAMS = 36
MAX_QUESTIONS_PER_PROGRAM = 100
MAX_STRING = 1200


def clean(value, limit=MAX_STRING):
    if not isinstance(value, str):
        return ""
    return re.sub(r"[\x00-\x1f\x7f]", " ", value).strip()[:limit]


def redact_contacts(value):
    """Best-effort contact removal; not a substitute for editorial review."""
    value = clean(value)
    # Convert Arabic and Persian numerals only for detection, then replace the
    # matching original span so the rest of the quotation stays unchanged.
    value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[نشانی حذف شد]", value)
    value = re.sub(r"(?<!\w)@[A-Za-z0-9_]{5,}(?!\w)", "[شناسه حذف شد]", value)
    digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    for pat in (r"(?<!\d)09\d{9}(?!\d)", r"(?<!\d)(?:\+98|0098)[-\s]?9\d{9}(?!\d)"):
        mapped = value.translate(digits)
        matches = list(re.finditer(pat, mapped))
        for match in reversed(matches):
            value = value[:match.start()] + "[شماره حذف شد]" + value[match.end():]
    return value


def bound_sec(value):
    if isinstance(value, bool):
        return 0
    try:
        n = int(value)
    except (ValueError, TypeError, OverflowError):
        return 0
    return max(0, min(21600, n))


def program_from_report(data):
    if data.get("network") != "persian":
        return None
    if data.get("analysis_available") is False:
        return None
    analysis = data.get("analysis") or {}
    questions = analysis.get("audience_questions")
    if not isinstance(questions, list):
        return None

    date_iso = clean(data.get("scheduled_date", ""), 10)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_iso):
        return None
    slot = clean(data.get("start", ""), 5)
    if not re.fullmatch(r"\d\d:\d\d", slot):
        return None

    qs = []
    for i, item in enumerate(questions[:MAX_QUESTIONS_PER_PROGRAM]):
        if not isinstance(item, dict):
            continue
        question = redact_contacts(clean(item.get("question"), 450))
        answer = redact_contacts(clean(item.get("answer_summary"), 1250))
        # The monitor's Persian schema contains answered questions only.
        # Never label an absent or blank answer as answered.
        if not question or not answer:
            continue
        start = bound_sec(item.get("start_sec"))
        end = bound_sec(item.get("end_sec"))
        if end < start:
            end = start
        source = item.get("source_type", "unknown")
        if source not in ("phone", "message", "unknown"):
            source = "unknown"
        qs.append({
            "id": f"{date_iso}-{slot.replace(':', '')}-{i+1}",
            "question": question,
            "answer": answer,
            "start_sec": start,
            "end_sec": end,
            "source": source,
            "status": "answered",
        })

    return {
        "id": f"persian-{date_iso}-{slot.replace(':', '')}",
        "date": clean(data.get("date"), 24),
        "date_iso": date_iso,
        "day": clean(data.get("day"), 24),
        "start": slot,
        "end": clean(data.get("end"), 5),
        "program": clean(data.get("program"), 100),
        "program_title": clean(analysis.get("program_title"), 180),
        "topic": clean(analysis.get("topic"), 180),
        "host": clean(analysis.get("host"), 90),
        "expert": clean(analysis.get("expert"), 90),
        "quality": "partial" if data.get("status") == "PARTIAL" or (data.get("transcription") or {}).get("transcript_incomplete") else "complete",
        "questions": qs,
    }


def update_feed(existing, report):
    program = program_from_report(report)
    if program is None:
        return existing, False
    rows = [x for x in existing.get("programs", []) if isinstance(x, dict) and x.get("id") != program["id"]]
    rows.append(program)
    rows.sort(key=lambda p: (p.get("date_iso", ""), p.get("start", "")), reverse=True)
    result = {
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "Velayat Live Monitor",
        "programs": rows[:MAX_PROGRAMS],
    }
    return result, True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", default="docs/data/feed.json")
    args = parser.parse_args()
    src, dst = Path(args.report), Path(args.output)
    if not src.exists():
        print("No report found. Existing feed remains unchanged.")
        return
    report = json.loads(src.read_text(encoding="utf-8"))
    existing = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {"programs": []}
    feed, changed = update_feed(existing, report)
    if not changed:
        print("Non-Persian or unusable report. Public feed unchanged.")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Updated public feed: {len(feed['programs'])} programs, latest {feed['programs'][0]['id']}")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"PUBLISH ERROR: {exc}", file=sys.stderr)
        raise
