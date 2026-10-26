"""Buttons for the Bale calendar administrator (no independent credentials/permissions).

Uses only persistent reply keyboards: tapping sends ordinary text through the
existing private-admin allowlist and confirmation logic. With 5-min polling,
callback-query buttons would leave a loading spinner; reply buttons do not.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import extra_schedule as calendar

MAIN = [
    ["➕ افزودن برنامه", "📋 برنامه‌ها"],
    ["📅 تقویم هفته", "⏸ توقف برنامه"],
    ["▶️ فعال‌سازی برنامه", "🗑 حذف برنامه"],
    ["📆 لغو یک نوبت", "🔄 بازگرداندن نوبت"],
    ["ℹ️ راهنما", "🆔 شناسه من"],
]
PUBLIC = [["🆔 شناسه من", "ℹ️ راهنما"]]
CANCEL = "❌ انصراف"
HOME = "🏠 منوی اصلی"
CONFIRM = "✅ تأیید نهایی"

MENU_COMMANDS = {
    "➕ افزودن برنامه": "افزودن",
    "📋 برنامه‌ها": "برنامه‌ها",
    "📅 تقویم هفته": "تقویم هفته",
    "ℹ️ راهنما": "راهنما",
    "🆔 شناسه من": "شناسه من",
    "⏸ توقف برنامه": "__choose_pause",
    "▶️ فعال‌سازی برنامه": "__choose_resume",
    "🗑 حذف برنامه": "__choose_delete",
    "📆 لغو یک نوبت": "__choose_skip",
    "🔄 بازگرداندن نوبت": "__choose_unskip",
    HOME: "__home",
    CANCEL: "انصراف",
    CONFIRM: "تایید",
}
FREQUENCIES = [
    ["🔹 یک‌بار", "🔁 روزانه"],
    ["📅 هفتگی", "🗓 ماهانه"],
    [HOME, CANCEL],
]
FREQUENCY_TEXT = {
    "🔹 یک‌بار": "یک‌بار", "🔁 روزانه": "روزانه",
    "📅 هفتگی": "هفتگی", "🗓 ماهانه": "ماهانه",
}
TITLE_PRESETS = [
    ["📺 ویژه‌برنامه مناسبتی", "📺 برنامه تولیدی"],
    ["📺 گفت‌وگوی علمی", "✍️ عنوان دلخواه"],
    [HOME, CANCEL],
]
TIME_MINUTES = [
    [f"⏱ {n:02d}" for n in range(i, i + 20, 5)]
    for i in range(0, 60, 20)
]
WEEKDAYS = ["شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه"]
WEEKDAY_DONE = "✅ پایان انتخاب روزها"
DATE_PRESETS = [["📅 امروز", "📅 فردا"], ["📅 ۳ روز بعد", "📅 ۷ روز بعد"], ["✍️ تاریخ دلخواه", HOME, CANCEL]]
END_PRESETS = [["🗓 ۷ روز", "🗓 ۳۰ روز"], ["🗓 ۹۰ روز", "🗓 ۱۸۰ روز"], ["✍️ تاریخ دلخواه", HOME, CANCEL]]
NEXT = "➡️ صفحه بعد"
PREVIOUS = "⬅️ صفحه قبل"
PAGE_SIZE = 12


def rows(values: list[str], per_row: int = 3) -> list[list[str]]:
    return [values[i:i+per_row] for i in range(0, len(values), per_row)]


def program_choices(action: str) -> list[dict]:
    records = calendar.load()
    if action == "pause":
        return [p for p in records if p["enabled"]]
    if action == "resume":
        return [p for p in records if not p["enabled"]]
    if action == "skip":
        return [p for p in records if p["enabled"]]
    if action == "unskip":
        return [p for p in records if p.get("skip_dates")]
    return records


def program_label(p: dict) -> str:
    return f"📺 {p['id']} · {p['title'][:20]}"


def possible_dates(program: dict, action: str) -> list[str]:
    now = datetime.now(ZoneInfo("Asia/Tehran")).date()
    if action == "unskip":
        return sorted(
            [d for d in program.get("skip_dates", []) if calendar.parse_day(d) >= now]
        )
    start = max(now, calendar.parse_day(program["from_date"]))
    end = min(
        now + timedelta(days=370),
        calendar.parse_day(program.get("until_date") or program["from_date"])
    )
    if start > end:
        return []
    return [
        day.isoformat()
        for days in range((end - start).days + 1)
        if calendar.is_due_on(program, day := start + timedelta(days=days))
    ]


def current_choices(sess: dict) -> list[str]:
    mode, step = sess.get("mode"), sess.get("step")
    if mode == "pick" and step == "select":
        return [program_label(p) for p in program_choices(sess["data"]["action"])]
    if mode in ("skip", "unskip") and step == "date":
        record = next(
            (p for p in calendar.load() if p["id"] == sess["data"]["id"]), None)
        return possible_dates(record, mode) if record else []
    return []


def keyboard_for(state: dict, key: str | None, authorized: bool) -> dict:
    if not authorized:
        board = PUBLIC
    else:
        sess = state.get("sessions", {}).get(key) if key else None
        board = MAIN
        if sess:
            step, mode = sess.get("step"), sess.get("mode")
            data = sess.get("data", {})
            if step == "confirm":
                board = [[CONFIRM, CANCEL], [HOME]]
            elif mode == "pick" and step == "select":
                candidates = current_choices(sess)
                page = max(0, int(sess.get("page", 0)))
                chunk = candidates[page * PAGE_SIZE:(page+1) * PAGE_SIZE]
                board = rows(chunk, 2)
                navigation = ([PREVIOUS] if page > 0 else []) + (
                    [NEXT] if (page+1)*PAGE_SIZE < len(candidates) else [])
                if navigation:
                    board.append(navigation)
                board.append([HOME, CANCEL])
            elif mode in ("skip", "unskip") and step == "date":
                choices = current_choices(sess)
                page = max(0, int(sess.get("page", 0)))
                chunk = choices[page * PAGE_SIZE:(page+1)*PAGE_SIZE]
                board = rows(["📆 " + day for day in chunk], 3)
                navigation = ([PREVIOUS] if page > 0 else []) + (
                    [NEXT] if (page+1)*PAGE_SIZE < len(choices) else [])
                if navigation:
                    board.append(navigation)
                board.append([HOME, CANCEL])
            elif mode == "add" and step == "title":
                board = TITLE_PRESETS
            elif mode == "add" and step in ("start", "end"):
                if data.get(f"{step}_hour") is None:
                    board = rows([f"🕘 {h:02d}" for h in range(24)], 4)
                else:
                    board = TIME_MINUTES.copy()
                board.append(["✍️ ساعت دلخواه", HOME, CANCEL])
            elif mode == "add" and step == "frequency":
                board = FREQUENCIES
            elif mode == "add" and step == "from_date":
                board = DATE_PRESETS
            elif mode == "add" and step == "until_date":
                board = END_PRESETS
            elif mode == "add" and step == "weekdays":
                selected = set(data.get("weekday_selected", []))
                board = rows(
                    [("✅ " if day in selected else "▫️ ") + day for day in WEEKDAYS],
                    2,
                ) + [[WEEKDAY_DONE], [HOME, CANCEL]]
    return {"keyboard": [[{"text": item} for item in row] for row in board],
            "resize_keyboard": True,
            "one_time_keyboard": False}


def preset_date(message: str, from_date: str | None = None) -> str | None:
    # Input passes through didban_calendar_bot.normal(): Persian digits become ASCII.
    # The keyboard itself still shows Persian digits for a natural Bale UX.
    message = message.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    today = datetime.now(ZoneInfo("Asia/Tehran")).date()
    value = {
        "📅 امروز": 0, "📅 فردا": 1, "📅 3 روز بعد": 3, "📅 7 روز بعد": 7
    }.get(message)
    if value is not None:
        return (today + timedelta(days=value)).isoformat()
    days = {"🗓 7 روز": 7, "🗓 30 روز": 30,
            "🗓 90 روز": 90, "🗓 180 روز": 180}.get(message)
    if days is not None and from_date:
        return (calendar.parse_day(from_date) + timedelta(days=days)).isoformat()
    return None
