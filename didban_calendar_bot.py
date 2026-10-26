"""Private, admin-only Bale chat commands for Didban's *extra* program calendar.

No access to program capture, analysis, clipping, dubbing, or the three fixed
broadcast windows. Runs in the existing five-minute calendar dispatcher.
No webhook is ever removed, and an unset allowlist permits no mutations.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import extra_schedule as calendar

STATE = Path(__file__).resolve().parent / "config" / "didban_calendar_bot_state.json"
REPLIES = Path("/tmp/didban-calendar-bot-replies.json")
TEHRAN = ZoneInfo("Asia/Tehran")
PROMPT = (
    "مدیریت تقویم دیدبان:\n"
    "«افزودن» — ثبت برنامه با گفت‌وگوی مرحله‌ای\n"
    "«برنامه‌ها» — فهرست نوبت‌های اضافی\n"
    "«تقویم هفته» — نوبت‌های هفت روز آینده\n"
    "«لغو ID» — توقف برنامه، «فعال ID» — ادامه\n"
    "«لغو نوبت ID تاریخ» — حذف فقط همان جلسه\n"
    "«برگرداندن نوبت ID تاریخ» — بازگردانی همان جلسه\n"
    "«حذف ID» — حذف کامل، «انصراف» — لغو فرمان\n"
    "«شناسه من» — دریافت شناسه عددی مدیر\n"
    "ساعت‌ها به وقت تهران و تاریخ‌ها شمسی یا میلادی است.\n"
    "تغییر نهایی فقط پس از «تایید» انجام می‌شود."
)
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
STEPS = ("title", "start", "end", "frequency", "from_date", "until_date", "weekdays")


def normal(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(PERSIAN_DIGITS).strip()).replace("ي", "ی").replace("ك", "ک")


def load_state() -> dict:
    if not STATE.exists():
        return {"version": 1, "last_update_id": 0, "sessions": {}}
    data = json.loads(STATE.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("Unrecognized bot state")
    return data


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def session_key(token: str, sender_id: int) -> str:
    # User IDs are neither stored nor committed in plaintext.
    return hashlib.sha256(f"{token}::didban:{sender_id}".encode()).hexdigest()[:32]


def allowed_ids() -> set[int]:
    env = os.getenv("DIDBAN_CONTROL_ADMIN_IDS", "")
    result = set()
    for item in re.split(r"[,،\s]+", env):
        if not item:
            continue
        if not item.isdecimal():
            raise ValueError("DIDBAN_CONTROL_ADMIN_IDS must contain numeric IDs only")
        result.add(int(item))
    return result


def bale_api(token: str, method: str, body: dict) -> dict:
    try:
        response = requests.post(
            f"https://tapi.bale.ai/bot{token}/{method}", data=body, timeout=25,
        )
    except requests.RequestException:
        # The transport exception can embed the URL containing the bot token.
        raise RuntimeError(f"Bale {method} connection failed (credentials redacted)") from None
    # Don't reveal token-containing URLs in raised exceptions or logs.
    if response.status_code != 200:
        raise RuntimeError(f"Bale method {method} returned HTTP {response.status_code}")
    data = response.json()
    if data.get("ok") is not True:
        raise RuntimeError(f"Bale method {method} returned unsuccessful response")
    return data


def validate_draft(data: dict) -> dict:
    """Use exactly the same schema/validator as the GitHub schedule form."""
    start_day = calendar.parse_day(data.get("from_date", ""))
    frequency = data.get("frequency", "")
    if frequency not in ("once", "daily", "weekly", "monthly"):
        raise ValueError("تکرار باید یک‌بار، روزانه، هفتگی یا ماهانه باشد.")
    last_text = data.get("until_date", "") if frequency != "once" else ""
    if frequency != "once" and not last_text:
        raise ValueError("برای برنامه تکراری تاریخ پایان لازم است.")
    today = datetime.now(TEHRAN).date()
    if start_day < today:
        raise ValueError("تاریخ شروع نباید گذشته باشد.")
    hour, minute = calendar.parse_hhmm(data.get("start", ""))
    calendar.duration_minutes(data.get("start", ""), data.get("end", ""))
    if start_day == today:
        proposed = datetime(start_day.year, start_day.month, start_day.day,
                            hour, minute, tzinfo=TEHRAN)
        if proposed < datetime.now(TEHRAN) + timedelta(minutes=20):
            raise ValueError("نوبت امروز باید دست‌کم ۲۰ دقیقه بعد باشد.")
    wd = (calendar.weekdays_from_text(data.get("weekdays", ""), start_day)
          if frequency == "weekly" else [])
    p = {
        "id": data["id"], "title": data["title"].strip(),
        "start": data["start"], "end": data["end"], "frequency": frequency,
        "from_date": data["from_date"], "until_date": last_text,
        "weekdays": wd,
        "month_day": calendar.jalali_day(start_day).day if frequency == "monthly" else 0,
        "enabled": True,
    }
    calendar.validate_records(calendar.load() + [p])
    return p


def write_calendar(action: str, ident: str, p: dict | None = None) -> None:
    config = calendar.CONFIG
    raw = json.loads(config.read_text(encoding="utf-8"))
    records = raw["programs"]
    match = next((item for item in records if item["id"] == ident), None)
    if action == "add":
        if match:
            raise ValueError("شناسه از قبل وجود دارد.")
        if p is None:
            raise ValueError("اطلاعات برنامه ناقص است.")
        records.append(p)
    else:
        if match is None:
            raise ValueError("برنامه‌ای با این شناسه وجود ندارد.")
        if action == "delete":
            records.remove(match)
        elif action in ("pause", "resume"):
            match["enabled"] = action == "resume"
        elif action in ("skip", "unskip"):
            if not p or "day" not in p:
                raise ValueError("تاریخ نوبت مشخص نشده است.")
            d = calendar.parse_day(p["day"]).isoformat()
            if d not in {day.isoformat() for day in (
                calendar.parse_day(match["from_date"]) + timedelta(days=n)
                for n in range((calendar.parse_day(match.get("until_date") or match["from_date"]) -
                                calendar.parse_day(match["from_date"])).days + 1)
            )}:
                raise ValueError("تاریخ خارج از بازه برنامه است.")
            if action == "skip":
                match.setdefault("skip_dates", [])
                if d not in match["skip_dates"]:
                    match["skip_dates"].append(d)
                    match["skip_dates"].sort()
            else:
                match["skip_dates"] = [x for x in match.get("skip_dates", []) if x != d]
        else:
            raise ValueError("عملیات ناشناخته است.")
    calendar.validate_records(records)  # atomic validation before disk updates
    raw["programs"] = records
    content = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    config.write_text(content, encoding="utf-8")
    calendar.MIRROR.parent.mkdir(parents=True, exist_ok=True)
    calendar.MIRROR.write_text(content, encoding="utf-8")


def short_list() -> str:
    records = calendar.load()
    if not records:
        return "هیچ برنامه تولیدی اضافی ثبت نشده است. سه نوبت ثابت تغییری نکرده‌اند."
    parts = ["تقویم برنامه‌های اضافی شبکه فارسی:"]
    for p in records[:60]:
        status = "فعال" if p["enabled"] else "متوقف"
        parts.append(
            f"• {p['id']} | {p['title']}\n  {p['start']}–{p['end']} "
            f"| {p['frequency']} | {p['from_date']} تا "
            f"{p.get('until_date') or p['from_date']} | {status}"
        )
    return "\n".join(parts)[:3900]


def week_list() -> str:
    today = datetime.now(TEHRAN).date()
    rows = ["برنامه‌های هفت روز آینده (تهران):"]
    for n in range(7):
        d = today + timedelta(days=n)
        matching = [p for p in calendar.load() if calendar.is_due_on(p, d)]
        for p in matching:
            rows.append(f"• {calendar.jalali_day(d)} | {p['start']}–{p['end']} "
                        f"| {p['title']} ({p['id']})")
    return "\n".join(rows)[:3900] if len(rows) > 1 else "برنامه اضافی در هفت روز آینده ثبت نشده است."


def ask_next(data: dict, step: str) -> str:
    if step == "title": return "نام دقیق برنامه تولیدی چیست؟"
    if step == "start": return "ساعت شروع به وقت تهران؟ مثال: 14:00"
    if step == "end": return "ساعت پایان؟ مثال: 15:00"
    if step == "frequency": return "تکرار؟ یکی از: یک‌بار / روزانه / هفتگی / ماهانه"
    if step == "from_date": return "تاریخ اولین اجرا؟ مثال: 1405-08-06"
    if step == "until_date": return "تاریخ آخرین اجرا؟ مثال: 1405-09-30"
    if step == "weekdays": return "روزهای هفته را بنویسید، مثال: شنبه، دوشنبه"
    raise ValueError("Invalid wizard step")


def confirm_text(operation: str, data: dict) -> str:
    if operation == "add":
        extra = (f" | روزها: {data.get('weekdays')}" if data["frequency"] == "weekly"
                 else "")
        return (f"پیش‌نمایش ثبت برنامه:\nشناسه: {data['id']}\n"
                f"عنوان: {data['title']}\n"
                f"ساعت تهران: {data['start']}–{data['end']}\n"
                f"تکرار: {data['frequency']}{extra}\n"
                f"شروع: {data['from_date']}\n"
                f"پایان: {data.get('until_date') or 'همان روز'}\n"
                "برای ثبت «تایید» و برای لغو «انصراف» را بفرستید.")
    suffix = f" در تاریخ {data['day']}" if data.get("day") else ""
    return (f"درخواست {operation} برای برنامه «{data['id']}»{suffix}.\n"
            "برای اجرای تغییر «تایید» و برای بازگشت «انصراف» را بفرستید.")


def start_add(state: dict, key: str, message_id: int) -> str:
    state["sessions"][key] = {
        "mode": "add", "step": "title",
        "data": {"id": f"show{message_id}"}, "updated_at": int(time.time()),
    }
    return ask_next({}, "title")


def process_admin_command(state: dict, key: str, message_id: int, text: str) -> str:
    sessions = state["sessions"]
    sess = sessions.get(key)
    now = int(time.time())
    if sess and now - sess["updated_at"] > 45 * 60:
        sessions.pop(key, None)
        sess = None
    msg = normal(text)
    if msg in ("انصراف", "/cancel", "لغو درخواست"):
        sessions.pop(key, None)
        return "درخواست نیمه‌کاره لغو شد؛ تقویم تغییر نکرد."
    if msg in ("برنامه‌ها", "برنامه ها", "لیست", "فهرست", "/list"):
        return short_list()
    if msg in ("تقویم", "تقویم هفته", "این هفته", "/week"):
        return week_list()
    if msg in ("راهنما", "/help", "/start"):
        return PROMPT
    if msg in ("افزودن", "ثبت برنامه", "برنامه جدید", "/add"):
        return start_add(state, key, message_id)

    match_once = re.fullmatch(
        r"(لغو نوبت|حذف نوبت|برگرداندن نوبت|بازگرداندن نوبت)\s+([a-zA-Z][a-zA-Z0-9_-]{1,39})\s+(\d{4}[-/]\d{2}[-/]\d{2})",
        msg,
    )
    if match_once:
        action = ("skip" if match_once.group(1) in ("لغو نوبت", "حذف نوبت")
                  else "unskip")
        ident = match_once.group(2)
        cal_date = calendar.parse_day(match_once.group(3)).isoformat()
        if ident not in {p["id"] for p in calendar.load()}:
            return "شناسه برنامه یافت نشد. «برنامه‌ها» را بفرستید."
        sessions[key] = {
            "mode": action, "step": "confirm",
            "data": {"id": ident, "day": cal_date},
            "updated_at": now,
        }
        return confirm_text(action, sessions[key]["data"])

    found = re.fullmatch(r"(لغو|توقف|فعال|فعال‌سازی|فعال سازی|حذف|/pause|/resume|/delete)\s+([a-zA-Z][a-zA-Z0-9_-]{1,39})", msg)
    if found:
        action = {"لغو": "pause", "توقف": "pause", "/pause": "pause",
                  "فعال": "resume", "فعال‌سازی": "resume", "فعال سازی": "resume",
                  "/resume": "resume", "حذف": "delete", "/delete": "delete"}[found.group(1)]
        ident = found.group(2)
        if ident not in {p["id"] for p in calendar.load()}:
            return "چنین شناسه‌ای در تقویم وجود ندارد. «برنامه‌ها» را بفرستید."
        if action == "resume":
            sample = next(p for p in calendar.load() if p["id"] == ident)
            calendar.validate_records([dict(p, enabled=True) if p["id"] == ident else p
                                       for p in calendar.load()])
        sessions[key] = {
            "mode": action, "step": "confirm",
            "data": {"id": ident}, "updated_at": now,
        }
        return confirm_text(action, {"id": ident})

    if msg in ("تایید", "تأیید", "/confirm"):
        if not sess or sess["step"] != "confirm":
            return "درخواست آماده تأییدی وجود ندارد. ابتدا «افزودن» یا «لغو شناسه» را بفرستید."
        action, data = sess["mode"], sess["data"]
        if action == "add":
            p = validate_draft(data)  # re-check current schedule against conflicts
            write_calendar("add", p["id"], p)
        else:
            write_calendar(action, data["id"], data)
        sessions.pop(key, None)
        return ("✅ تغییر تقویم ثبت شد؛ نوبت‌های ثابت، گزارش، تقطیع و دوبله بدون تغییرند.\n"
                f"عملیات: {action} | شناسه: {data['id']}")

    if not sess or sess["mode"] != "add":
        return "دستور شناخته نشد.\n" + PROMPT

    data = sess["data"]
    step = sess["step"]
    try:
        if step == "title":
            if not 3 <= len(msg) <= 120 or "|" in msg:
                raise ValueError("عنوان باید ۳ تا ۱۲۰ کاراکتر باشد.")
            data["title"] = msg
            next_step = "start"
        elif step in ("start", "end"):
            calendar.parse_hhmm(msg)
            data[step] = msg
            if step == "end":
                calendar.duration_minutes(data["start"], data["end"])
            next_step = "end" if step == "start" else "frequency"
        elif step == "frequency":
            aliases = {"یک بار": "once", "یک‌بار": "once", "once": "once",
                       "روزانه": "daily", "daily": "daily",
                       "هفتگی": "weekly", "weekly": "weekly",
                       "ماهانه": "monthly", "monthly": "monthly"}
            if msg not in aliases:
                raise ValueError("یکی از «یک‌بار / روزانه / هفتگی / ماهانه» را وارد کنید.")
            data["frequency"] = aliases[msg]
            next_step = "from_date"
        elif step == "from_date":
            calendar.parse_day(msg)
            data["from_date"] = msg.replace("/", "-")
            next_step = ("weekdays" if data["frequency"] == "weekly"
                         else "until_date" if data["frequency"] != "once" else "confirm")
        elif step == "until_date":
            calendar.parse_day(msg)
            data["until_date"] = msg.replace("/", "-")
            next_step = "confirm"
        elif step == "weekdays":
            calendar.weekdays_from_text(msg, calendar.parse_day(data["from_date"]))
            data["weekdays"] = msg
            next_step = "until_date"
        else:
            return PROMPT
        if next_step == "confirm":
            validate_draft(data)
            sess["step"] = "confirm"
            sess["updated_at"] = now
            return confirm_text("add", data)
        sess["step"] = next_step
        sess["updated_at"] = now
        return ask_next(data, next_step)
    except (ValueError, KeyError, TypeError) as exc:
        return f"⚠️ اطلاعات قابل ثبت نیست: {exc}\n{ask_next(data, step)}"


def handle_message(state: dict, token: str, admin_ids: set[int], update: dict) -> tuple[int, str] | None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    if chat.get("type") != "private" or sender.get("is_bot"):
        return None
    chat_id = chat.get("id")
    uid = sender.get("id")
    if not isinstance(uid, int) or not isinstance(chat_id, int):
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    normalized = normal(text)
    if normalized in ("شناسه من", "آیدی من", "/id"):
        return chat_id, f"شناسه عددی حساب بله شما: {uid}"
    if uid not in admin_ids:
        if normalized in ("/start", "/help"):
            return chat_id, ("این ربات برای مدیریت خصوصی دیدبان است. "
                             "برای فعال‌سازی مدیریت، ابتدا «شناسه من» را ارسال کنید "
                             "و شناسه را در تنظیمات امن GitHub ثبت کنید.")
        return None
    key = session_key(token, uid)
    try:
        return chat_id, process_admin_command(state, key, int(update["update_id"]), text)
    except (ValueError, KeyError) as exc:
        return chat_id, f"⚠️ هیچ تغییری اعمال نشد: {exc}"


def poll() -> None:
    token = os.getenv("DIDBAN_CONTROL_BOT_TOKEN", "").strip()
    if not token:
        print("Calendar bot disabled: no dedicated token configured")
        return
    admin_ids = allowed_ids()
    state = load_state()
    webhook = bale_api(token, "getWebhookInfo", {}).get("result", {})
    if isinstance(webhook, dict) and webhook.get("url"):
        raise RuntimeError("Calendar bot has active webhook; refusing getUpdates or webhook removal")
    data = bale_api(token, "getUpdates",
                    {"offset": str(int(state["last_update_id"]) + 1), "limit": "100", "timeout": "0"})
    replies = []
    for update in sorted(data.get("result", []), key=lambda v: v.get("update_id", 0)):
        ident = update.get("update_id")
        if type(ident) is not int or ident <= state["last_update_id"]:
            continue
        answer = handle_message(state, token, admin_ids, update)
        if answer:
            replies.append({"chat_id": answer[0], "message": answer[1]})
        state["last_update_id"] = ident
    if replies:
        REPLIES.write_text(json.dumps(replies, ensure_ascii=False), encoding="utf-8")
    if data.get("result"):
        save_state(state)
    print(f"Calendar bot processed {len(data.get('result', []))} updates; {len(replies)} replies")


def reply() -> None:
    token = os.getenv("DIDBAN_CONTROL_BOT_TOKEN", "").strip()
    if not token or not REPLIES.exists():
        return
    for row in json.loads(REPLIES.read_text(encoding="utf-8")):
        bale_api(token, "sendMessage", {"chat_id": str(row["chat_id"]), "text": row["message"][:4000]})
    REPLIES.unlink(missing_ok=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("poll", "reply"):
        raise SystemExit("usage: didban_calendar_bot.py poll|reply")
    {"poll": poll, "reply": reply}[sys.argv[1]]()
