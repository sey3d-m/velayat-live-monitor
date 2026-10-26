"""Isolated, admin-only Bale webhook. No monitor, clipping or dubbing imports."""
from __future__ import annotations

import base64
import copy
import hmac
import json
import os
import re
import sys
import tempfile
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import patch

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import didban_calendar_bot as bot
import didban_bot_keyboards as kb
import extra_schedule as cal

REPO = "sey3d-m/velayat-live-monitor"
CALENDAR_PATHS = ("config/didban_extra_programs.json", "docs/data/extra-programs.json")
EMPTY_CALENDAR = '{"version":1,"programs":[]}'


class ServiceError(Exception):
    pass


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ServiceError("Missing secure setting: " + name)
    return value


def gh(method, path, data=None):
    token = env("DIDBAN_EDITOR_GITHUB_TOKEN")
    try:
        response = requests.request(
            method, f"https://api.github.com/repos/{REPO}/{path}",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"},
            json=data, timeout=7)
    except requests.RequestException:
        raise ServiceError("ارتباط GitHub برقرار نیست.") from None
    if response.status_code >= 400:
        if response.status_code in (409, 422):
            raise ServiceError("تداخل تغییرات GitHub؛ دوباره تلاش کنید.")
        raise ServiceError("GitHub HTTP " + str(response.status_code))
    try:
        return response.json()
    except ValueError:
        raise ServiceError("پاسخ GitHub معتبر نیست.") from None


def remote_calendar():
    contents = []
    for path in CALENDAR_PATHS:
        entry = gh("GET", f"contents/{path}?ref=main")
        try:
            contents.append(base64.b64decode(entry["content"]).decode("utf-8"))
        except (KeyError, ValueError, UnicodeError):
            raise ServiceError("فایل تقویم قابل خواندن نیست.") from None
    try:
        first, mirror = (json.loads(item) for item in contents)
    except ValueError:
        raise ServiceError("ساختار JSON تقویم نامعتبر است.") from None
    if first != mirror or first.get("version") != 1:
        raise ServiceError("تقویم اصلی و نمایشی هماهنگ نیستند.")
    return contents[0]


def publish_calendar(previous, changed, update_id):
    head = gh("GET", "git/ref/heads/main")["object"]["sha"]
    current = remote_calendar()
    if json.loads(current) != json.loads(previous):
        raise ServiceError("نسخه تقویم تغییر کرده؛ فرمان را مجدداً بررسی کنید.")
    parent = gh("GET", "git/commits/" + head)
    tree = gh("POST", "git/trees", {
        "base_tree": parent["tree"]["sha"],
        "tree": [{"path": path, "mode": "100644", "type": "blob", "content": changed}
                 for path in CALENDAR_PATHS]})
    new = gh("POST", "git/commits", {
        "message": f"Apply confirmed editor calendar update {update_id}",
        "tree": tree["sha"], "parents": [head]})
    # A non-fast-forward update is rejected; never overwrite an unrelated push.
    gh("PATCH", "git/refs/heads/main", {"sha": new["sha"], "force": False})


def bale(method, payload):
    token = env("DIDBAN_CONTROL_BOT_TOKEN")
    try:
        response = requests.post(
            f"https://tapi.bale.ai/bot{token}/{method}", json=payload, timeout=7)
    except requests.RequestException:
        raise ServiceError("ارسال پیام در بله ناموفق بود.") from None
    if response.status_code != 200:
        raise ServiceError("Bale HTTP " + str(response.status_code))
    try:
        good = response.json().get("ok") is True
    except ValueError:
        good = False
    if not good:
        raise ServiceError("بله پاسخ را تأیید نکرد.")


def allowed_admins():
    source = env("DIDBAN_CONTROL_ADMIN_IDS")
    parts = [x for x in re.split(r"[,،\s]+", source) if x]
    if not all(x.isdecimal() for x in parts):
        raise ServiceError("Invalid admin allowlist")
    return {int(x) for x in parts}


def normalize(update):
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        label = callback.get("data")
        if not isinstance(label, str) or len(label) > 200:
            return None, None
        return {"update_id": update.get("update_id"),
                "message": {
                    "chat": (callback.get("message") or {}).get("chat") or {},
                    "from": callback.get("from") or {},
                    "text": label}}, callback.get("id")
    return update, None


def apply_editor(state, update, content, admins, token, save):
    with tempfile.TemporaryDirectory() as work:
        original = Path(work) / "calendar.json"
        mirror = Path(work) / "mirror.json"
        original.write_text(content, encoding="utf-8")
        # Reuse the existing tested button and calendar state machine.
        with patch.object(cal, "CONFIG", original), patch.object(cal, "MIRROR", mirror):
            reply = bot.handle_message(state, token, admins, update)
            result = original.read_text(encoding="utf-8")
            if json.loads(result) != json.loads(content):
                cal.validate_records(json.loads(result)["programs"])
                save(content, result, update["update_id"])
            sender = (update.get("message") or {}).get("from") or {}
            uid = sender.get("id")
            authorized = type(uid) is int and uid in admins
            key = bot.session_key(token, uid) if authorized else None
            board = kb.keyboard_for(state, key, authorized)
            return [reply[0], reply[1], board] if reply else None


def database():
    import psycopg
    return psycopg.connect(env("DIDBAN_EDITOR_DATABASE_URL"), connect_timeout=5)


def consume(raw):
    update_id = raw.get("update_id")
    if type(update_id) is not int or update_id < 0:
        return None
    update, callback_id = normalize(raw)
    if update is None:
        return None
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    uid, chat_id = sender.get("id"), chat.get("id")
    if chat.get("type") != "private" or type(uid) is not int or type(chat_id) is not int:
        return None
    token = env("DIDBAN_CONTROL_BOT_TOKEN")
    admins = allowed_admins()
    key = bot.session_key(token, uid)
    with database() as db:
        with db.transaction():
            # Exactly one editor update is executed at a time across all workers.
            db.execute("SELECT pg_advisory_xact_lock(7241961)")
            existing = db.execute(
                "SELECT response FROM didban_editor_updates WHERE update_id=%s",
                (update_id,)).fetchone()
            if existing:
                return existing[0], callback_id, update_id
            saved = db.execute(
                "SELECT state FROM didban_editor_sessions WHERE session_key=%s",
                (key,)).fetchone()
            sessions = {key: saved[0]} if saved else {}
            state = {"version": 1, "last_update_id": 0, "sessions": sessions}
            cached = db.execute(
                "SELECT content FROM didban_editor_cache WHERE singleton=TRUE"
            ).fetchone()
            calendar_content = cached[0] if cached else EMPTY_CALENDAR
            github_ready = False
            try:
                calendar_content = remote_calendar()
                github_ready = True
                db.execute(
                    "INSERT INTO didban_editor_cache(singleton,content) VALUES(TRUE,%s) "
                    "ON CONFLICT(singleton) DO UPDATE SET content=EXCLUDED.content",
                    (calendar_content,))
            except ServiceError:
                pass  # Menu, help and cancel must stay independent from GitHub.
            before = copy.deepcopy(state)

            def save(original, changed, ident):
                if not github_ready:
                    raise ServiceError("GitHub در دسترس نیست؛ تقویم تغییر نکرد.")
                publish_calendar(original, changed, ident)

            try:
                reply = apply_editor(state, update, calendar_content, admins, token, save)
                # If GitHub is down AND there is no cached schedule, don't
                # incorrectly report an empty program calendar as authoritative.
                text = message.get("text", "")
                if (not github_ready and not cached and
                    text in ("📋 برنامه‌ها", "📅 تقویم هفته", "⏸ توقف برنامه",
                             "▶️ فعال‌سازی برنامه", "🗑 حذف برنامه",
                             "📆 لغو یک نوبت", "🔄 بازگرداندن نوبت")):
                    reply = [chat_id, "⚠️ تقویم فعلاً قابل بازیابی نیست؛ دوباره تلاش کنید.",
                             kb.keyboard_for(state, key, uid in admins)]
            except ServiceError as error:
                state = before
                reply = [chat_id, "⚠️ " + str(error) + "؛ مجدداً تلاش کنید.",
                         kb.keyboard_for(state, key, uid in admins)]
            if key in state["sessions"]:
                db.execute(
                    "INSERT INTO didban_editor_sessions(session_key,state) VALUES(%s,%s::jsonb) "
                    "ON CONFLICT(session_key) DO UPDATE SET state=EXCLUDED.state",
                    (key, json.dumps(state["sessions"][key], ensure_ascii=False)))
            else:
                db.execute("DELETE FROM didban_editor_sessions WHERE session_key=%s", (key,))
            db.execute(
                "INSERT INTO didban_editor_updates(update_id,response) VALUES(%s,%s::jsonb)",
                (update_id, json.dumps(reply, ensure_ascii=False)))
    return reply, callback_id, update_id


def deliver(result):
    if result is None:
        return
    reply, callback_id, update_id = result
    if callback_id:
        try:
            bale("answerCallbackQuery", {"callback_query_id": callback_id})
        except ServiceError:
            pass
    if reply is None:
        return
    with database() as db:
        sent = db.execute(
            "SELECT sent_at FROM didban_editor_updates WHERE update_id=%s",
            (update_id,)).fetchone()
        if sent and sent[0] is not None:
            return
    chat_id, message, keyboard = reply
    bale("sendMessage", {
        "chat_id": chat_id, "text": message[:3900], "reply_markup": keyboard})
    with database() as db:
        db.execute("UPDATE didban_editor_updates SET sent_at=now() WHERE update_id=%s",
                   (update_id,))
        db.commit()


class handler(BaseHTTPRequestHandler):
    def output(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        configured = all(os.environ.get(name) for name in (
            "DIDBAN_CONTROL_BOT_TOKEN", "DIDBAN_CONTROL_ADMIN_IDS",
            "DIDBAN_EDITOR_WEBHOOK_SECRET", "DIDBAN_EDITOR_GITHUB_TOKEN",
            "DIDBAN_EDITOR_DATABASE_URL"))
        self.output(200 if configured else 503,
                    {"service": "didban-editor", "configured": bool(configured)})

    def do_POST(self):
        secret = os.environ.get("DIDBAN_EDITOR_WEBHOOK_SECRET", "")
        header = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secret or not hmac.compare_digest(header, secret):
            self.output(403, {"ok": False})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 65536:
                self.output(413, {"ok": False})
                return
            update = json.loads(self.rfile.read(size))
            if not isinstance(update, dict):
                self.output(400, {"ok": False})
                return
            deliver(consume(update))
            self.output(200, {"ok": True})
        except Exception:
            # 503 requests redelivery. Do not expose URL, token, payload or
            # exception details in client responses or diagnostic logs.
            self.output(503, {"ok": False, "retry": True})
