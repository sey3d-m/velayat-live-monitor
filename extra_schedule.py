"""Independent scheduling of EXTRA Persian broadcast windows.

Existing fixed program slots, analysis, Bale reports, clip selection and
Bengali dubbing are untouched. Public schedule JSON holds no secrets.
Dates accept Iranian solar YYYY-MM-DD or Gregorian YYYY-MM-DD (year >= 1700).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CONFIG = Path(__file__).resolve().parent / "config" / "didban_extra_programs.json"
MIRROR = Path(__file__).resolve().parent / "docs" / "data" / "extra-programs.json"
TEHRAN = ZoneInfo("Asia/Tehran")
WEEKDAYS = {
    "دوشنبه": 0, "سه‌شنبه": 1, "سه شنبه": 1,
    "چهارشنبه": 2, "پنجشنبه": 3, "جمعه": 4,
    "شنبه": 5, "یکشنبه": 6,
}


def parse_day(value: str) -> date:
    value = value.strip().replace("/", "-")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Date must be YYYY-MM-DD (Jalali or Gregorian)")
    year, month, day = map(int, value.split("-"))
    if year < 1700:
        import jdatetime
        return jdatetime.date(year, month, day).togregorian()
    return date(year, month, day)


def jalali_day(day: date):
    import jdatetime
    return jdatetime.date.fromgregorian(date=day)


def parse_hhmm(value: str) -> tuple[int, int]:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("Time must be HH:MM in Tehran time")
    return tuple(map(int, value.split(":")))


def duration_minutes(start: str, end: str) -> int:
    sh, sm = parse_hhmm(start)
    eh, em = parse_hhmm(end)
    length = (eh * 60 + em - sh * 60 - sm) % 1440
    if not (15 <= length <= 180):
        raise ValueError("Program length must be 15–180 minutes")
    return length


def validate_records(records: list[dict]) -> list[dict]:
    """Validate everything before writing the calendar; reject conflicts."""
    if len(records) > 150:
        raise ValueError("Calendar has too many extra programs")
    seen = set()
    for p in records:
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,39}", p["id"]):
            raise ValueError("Bad program ID")
        if p["id"] in seen:
            raise ValueError("Duplicate program ID")
        seen.add(p["id"])
        if type(p["enabled"]) is not bool:
            raise ValueError("enabled must be Boolean")
        if not isinstance(p["title"], str) or not p["title"].strip() or len(p["title"]) > 120:
            raise ValueError("Invalid program title")
        duration_minutes(p["start"], p["end"])
        if p["frequency"] not in ("once", "daily", "weekly", "monthly"):
            raise ValueError("Unknown recurrence")
        if not isinstance(p.get("weekdays", []), list) or not all(
            type(x) is int and x in range(7) for x in p.get("weekdays", [])
        ):
            raise ValueError("Invalid weekdays")
        if p["frequency"] == "weekly" and not p["weekdays"]:
            raise ValueError("Weekly schedule requires weekdays")
        start_d = parse_day(p["from_date"])
        if p.get("until_date") and parse_day(p["until_date"]) < start_d:
            raise ValueError("End date precedes start")
        if p["frequency"] == "once" and p.get("until_date") and parse_day(p["until_date"]) != start_d:
            raise ValueError("One-time schedule has one date")
        if p["frequency"] == "monthly":
            day = int(p.get("month_day", 0))
            if day not in range(1, 32):
                raise ValueError("Invalid Jalali month day")
        # Finite recurrence bounds keep conflict verification exact and
        # prevent stale permanent entries if a production show is cancelled.
        last = parse_day(p.get("until_date") or p["from_date"])
        if (last - start_d).days > 370:
            raise ValueError("Maximum calendar horizon is 370 days")
    # Check ALL occurrences, including adjacent-day overnight programs.
    # Nonoverlap with the three original Persian windows is a hard invariant.
    active = [p for p in records if p["enabled"]]
    if active:
        earliest = min(parse_day(p["from_date"]) for p in active)
        latest = max(parse_day(p.get("until_date") or p["from_date"]) for p in active)
        fixed = (("18:00", "19:00"), ("19:30", "20:30"), ("21:00", "22:00"))
        entries: list[tuple[datetime, datetime, str]] = []
        for day_index in range((latest - earliest).days + 1):
            day = earliest + timedelta(days=day_index)
            if day.weekday() != 4:  # Fixed broadcasts do not run Friday.
                for start_time, end_time in fixed:
                    h, m = parse_hhmm(start_time)
                    eh, em = parse_hhmm(end_time)
                    entries.append((datetime.combine(day, datetime.min.time()).replace(
                        hour=h, minute=m),
                        datetime.combine(day, datetime.min.time()).replace(
                        hour=eh, minute=em), "fixed Persian schedule"))
            for p in active:
                if not is_due_on(p, day):
                    continue
                sh, sm = parse_hhmm(p["start"])
                start_time = datetime.combine(day, datetime.min.time()).replace(
                    hour=sh, minute=sm)
                finish = start_time + timedelta(minutes=duration_minutes(p["start"], p["end"]))
                entries.append((start_time, finish, p["id"]))
        entries.sort(key=lambda entry: (entry[0], entry[1], entry[2]))
        for previous, current in zip(entries, entries[1:]):
            if current[0] < previous[1]:
                raise ValueError(
                    f"Broadcast time conflict: {previous[2]} and {current[2]} "
                    f"on {current[0].date()} at {current[0].strftime('%H:%M')}"
                )
    return records


def load() -> list[dict]:
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    if raw.get("version") != 1 or not isinstance(raw.get("programs"), list):
        raise ValueError("Invalid extra schedule file")
    return validate_records(raw["programs"])


def is_due_on(p: dict, day: date) -> bool:
    if not p["enabled"]:
        return False
    start = parse_day(p["from_date"])
    if day < start or (p.get("until_date") and day > parse_day(p["until_date"])):
        return False
    f = p["frequency"]
    if f == "once":
        return day == start
    if f == "daily":
        return True
    if f == "weekly":
        return day.weekday() in p["weekdays"]
    return jalali_day(day).day == p["month_day"]


def get_extra(extra_id: str, day: date) -> dict:
    for p in load():
        if p["id"] == extra_id:
            if not is_due_on(p, day):
                raise ValueError(f"Additional slot {extra_id} is paused or not on {day}")
            return p
    raise ValueError(f"Unknown additional slot {extra_id}")


def get_due(now: datetime | None = None) -> list[dict]:
    now = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)
    due = []
    for p in load():
        for day in (now.date() - timedelta(days=1), now.date(), now.date() + timedelta(days=1)):
            if not is_due_on(p, day):
                continue
            hour, minute = parse_hhmm(p["start"])
            start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TEHRAN)
            # Dispatch slightly before the broadcast; tolerate moderate cron lag.
            seconds = (start - now).total_seconds()
            if -12 * 60 <= seconds <= 12 * 60:
                due.append({
                    "id": p["id"], "title": p["title"], "slot": p["start"],
                    "scheduled_date": day.isoformat(),
                    "identity": f"[extra:{p['id']}:{day.isoformat()}]",
                })
    return due


def weekdays_from_text(value: str, from_day: date) -> list[int]:
    if not value.strip():
        return [from_day.weekday()]
    result = []
    for x in re.split(r"[,،]", value):
        token = x.strip()
        if token in WEEKDAYS:
            result.append(WEEKDAYS[token])
        elif token in ("0","1","2","3","4","5","6"):
            result.append(int(token))
        else:
            raise ValueError(f"Unknown weekday: {token}")
    return sorted(set(result))


def manage_from_env() -> None:
    action = os.environ["EXTRA_ACTION"].strip()
    ident = os.environ["EXTRA_ID"].strip()
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{1,39}", ident):
        raise ValueError("Use an ID in Latin letters/digits (example: newshow1)")
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    records = load()
    match = next((p for p in records if p["id"] == ident), None)
    if action == "add":
        if match:
            raise ValueError("ID already exists. Pause or remove it first.")
        title = os.environ.get("EXTRA_TITLE", "").strip()
        first = os.environ.get("EXTRA_FROM_DATE", "").strip()
        start_day = parse_day(first)
        freq = os.environ.get("EXTRA_FREQUENCY", "").strip()
        if freq not in ("once", "daily", "weekly", "monthly"):
            raise ValueError("Choose an allowed recurrence")
        ending = os.environ.get("EXTRA_UNTIL_DATE", "").strip()
        if freq != "once" and not ending:
            raise ValueError("Recurring events must have an explicit end date")
        p = {
            "id": ident, "title": title,
            "start": os.environ.get("EXTRA_START", ""),
            "end": os.environ.get("EXTRA_END", ""),
            "frequency": freq, "from_date": first.replace("/", "-"),
            "until_date": ending.replace("/", "-") if ending else "",
            "weekdays": weekdays_from_text(os.environ.get("EXTRA_WEEKDAYS", ""), start_day) if freq == "weekly" else [],
            "month_day": jalali_day(start_day).day if freq == "monthly" else 0,
            "enabled": True,
        }
        records.append(p)
    elif action in ("pause", "resume", "delete"):
        if not match:
            raise ValueError("No matching program ID")
        if action == "delete":
            records.remove(match)
        else:
            match["enabled"] = action == "resume"
    else:
        raise ValueError("Unsupported operation")
    validate_records(records)  # Reject collisions before touching any file.
    raw["programs"] = records
    new_text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    CONFIG.write_text(new_text, encoding="utf-8")
    MIRROR.parent.mkdir(parents=True, exist_ok=True)
    MIRROR.write_text(new_text, encoding="utf-8")
    print(f"Extra schedule updated: {action} {ident}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("due", "manage", "check"))
    args = parser.parse_args()
    if args.operation == "manage":
        manage_from_env()
    elif args.operation == "check":
        print(f"Valid records: {len(load())}")
    else:
        print(json.dumps(get_due(), ensure_ascii=False))
