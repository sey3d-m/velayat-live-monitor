# Velayat Live Monitor v3.4 Timestamp
# Replace the repository root file: velayat_monitor.py

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
import requests
from google import genai
from pydantic import BaseModel, Field

TEHRAN = ZoneInfo("Asia/Tehran")

STREAM_URL = os.environ.get("STREAM_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "").strip()
PROGRAM_SLOT = os.environ.get("PROGRAM_SLOT", "").strip()
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual")

AUDIO_FILE = Path("program_audio.mp3")
TRANSCRIPT_FILE = Path("program_transcript.txt")
SMART_TRANSCRIPT_FILE = Path("program_transcript_smart.txt")
REPORT_FILE = Path("program_report.json")
CHUNK_DIR = Path("timestamp_chunks")

MAX_CAPTURE_SECONDS = 3595
TIMESTAMP_CHUNK_SECONDS = 1500
RESOLVE_BEFORE_START_SECONDS = 90

ANALYSIS_MODELS = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
ANALYSIS_RETRY_DELAYS = [15, 30, 60]

SLOTS = {
    "18:00": ("18:00", "19:00"),
    "19:30": ("19:30", "20:30"),
    "21:00": ("21:00", "22:00"),
}

PROGRAMS = {
    "شنبه": {"18:00": "زمزم احکام", "19:30": "آفتاب و سایه ها", "21:00": "پرسمان اعتقادی"},
    "یکشنبه": {"18:00": "امت اسلام", "19:30": "بیان امیر", "21:00": "فائزون"},
    "دوشنبه": {"18:00": "زمزم احکام", "19:30": "فرکانس تاریکی", "21:00": "پرسمان مذاهب"},
    "سه شنبه": {"18:00": "کانون مهر", "19:30": "پیام تاریخ", "21:00": "پرسمان قرآنی"},
    "چهارشنبه": {"18:00": "زمزم احکام", "19:30": "چراغ", "21:00": "پرسمان اعتقادی"},
    "پنجشنبه": {"18:00": "پرسمان تاریخی", "19:30": "گامی به سوی ظهور", "21:00": "حیات قرآنی"},
}

CUSTOM_VOCABULARY = [
    "شبکه جهانی ولایت", "زمزم احکام", "آفتاب و سایه ها", "آفتاب و سایه‌ها",
    "پرسمان اعتقادی", "امت اسلام", "بیان امیر", "فائزون",
    "فرکانس تاریکی", "پرسمان مذاهب", "کانون مهر", "پیام تاریخ",
    "پرسمان قرآنی", "چراغ", "پرسمان تاریخی", "گامی به سوی ظهور",
    "حیات قرآنی", "اهل‌بیت", "امیرالمؤمنین", "حضرت زهرا",
    "امام زمان", "حضرت مهدی", "مهدویت", "شیعه", "اهل‌سنت",
    "قرآن کریم", "نهج‌البلاغه",
]


class TimedKeyPoint(BaseModel):
    start_offset_seconds: float
    end_offset_seconds: float
    text: str


class AudienceQuestion(BaseModel):
    source_type: Literal["phone", "message", "unknown"]
    audience_name: str
    start_offset_seconds: float
    end_offset_seconds: float
    question: str
    answer_summary: str


class ProgramAnalysis(BaseModel):
    program_start_detected: bool
    program_start_offset_seconds: float
    program_start_evidence: str
    expert: str
    topic: str
    summary: str
    key_points: list[TimedKeyPoint]
    audience_questions: list[AudienceQuestion]


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    raise RuntimeError(message)


def check_required_settings():
    missing = []
    for name, value in [
        ("STREAM_URL", STREAM_URL),
        ("GEMINI_API_KEY", GEMINI_API_KEY),
        ("SHEETS_WEBHOOK_URL", SHEETS_WEBHOOK_URL),
        ("WEBHOOK_SECRET", WEBHOOK_SECRET),
        ("BALE_BOT_TOKEN", BALE_BOT_TOKEN),
        ("BALE_CHAT_ID", BALE_CHAT_ID),
        ("PROGRAM_SLOT", PROGRAM_SLOT),
    ]:
        if not value:
            missing.append(name)
    if missing:
        fail("Missing required settings/secrets: " + ", ".join(missing))
    if PROGRAM_SLOT not in SLOTS:
        fail(f"Invalid PROGRAM_SLOT={PROGRAM_SLOT}")


def persian_day_name(dt):
    return {
        0: "دوشنبه", 1: "سه شنبه", 2: "چهارشنبه",
        3: "پنجشنبه", 4: "جمعه", 5: "شنبه", 6: "یکشنبه",
    }[dt.weekday()]


def today_at(now, hhmm):
    h, m = map(int, hhmm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


def wait_until(target):
    while True:
        seconds = (target - datetime.now(TEHRAN)).total_seconds()
        if seconds <= 0:
            return
        print(f"Waiting {int(seconds)} seconds until {target.strftime('%H:%M:%S')} Tehran...")
        time.sleep(min(seconds, 30))


def get_program_info():
    now = datetime.now(TEHRAN)
    day = persian_day_name(now)
    if day == "جمعه":
        fail("جمعه برنامه‌ای در کنداکتور رصد تعریف نشده است.")
    start_s, end_s = SLOTS[PROGRAM_SLOT]
    start_dt = today_at(now, start_s)
    end_dt = today_at(now, end_s)
    if now >= end_dt:
        fail(f"Run بعد از پایان برنامه {PROGRAMS[day][PROGRAM_SLOT]} اجرا شده است.")
    return {
        "day": day,
        "slot": PROGRAM_SLOT,
        "start": start_s,
        "end": end_s,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "program": PROGRAMS[day][PROGRAM_SLOT],
    }


def jalali_date_for_today():
    now = datetime.now(TEHRAN)
    j = jdatetime.date.fromgregorian(date=now.date())
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"


def parse_offset(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip()
    if text.endswith("s"):
        text = text[:-1]
    try:
        return float(text)
    except Exception:
        return 0.0


def fmt_clock(dt, seconds=False):
    return dt.strftime("%H:%M:%S" if seconds else "%H:%M")


def fmt_elapsed(value):
    value = max(0, int(round(value)))
    h = value // 3600
    m = (value % 3600) // 60
    s = value % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def absolute_time(recording_start, offset):
    return recording_start + timedelta(seconds=max(0.0, offset))


def timed_label(recording_start, start_offset, end_offset, program_start_offset, detected):
    start_offset = max(0.0, start_offset)
    end_offset = max(start_offset, end_offset)
    a = absolute_time(recording_start, start_offset)
    b = absolute_time(recording_start, end_offset)
    clock = f"{fmt_clock(a)}–{fmt_clock(b)}"
    if not detected:
        return clock
    if end_offset < program_start_offset:
        return f"{clock} | پیش از شروع واقعی برنامه"
    rs = max(0.0, start_offset - program_start_offset)
    re = max(0.0, end_offset - program_start_offset)
    return f"{clock} | {fmt_elapsed(rs)}–{fmt_elapsed(re)}"


def resolve_stream_url(url):
    if "youtube.com" not in url.lower() and "youtu.be" not in url.lower():
        return url
    last_error = ""
    for attempt in range(1, 6):
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-g", url],
            capture_output=True, text=True, check=False,
        )
        if result.returncode == 0:
            urls = [x.strip() for x in result.stdout.splitlines() if x.strip()]
            if urls:
                return urls[0]
        last_error = result.stderr.strip()
        if attempt < 5:
            time.sleep(15)
    fail("Could not resolve live stream. " + last_error)


def prepare_stream(info):
    now = datetime.now(TEHRAN)
    if now < info["start_dt"]:
        resolve_at = info["start_dt"] - timedelta(seconds=RESOLVE_BEFORE_START_SECONDS)
        if now < resolve_at:
            wait_until(resolve_at)
    media_url = resolve_stream_url(STREAM_URL)
    if datetime.now(TEHRAN) < info["start_dt"]:
        wait_until(info["start_dt"])
    return media_url


def capture_audio(media_url, info):
    recording_start = datetime.now(TEHRAN)
    remaining = int((info["end_dt"] - recording_start).total_seconds())
    if remaining <= 0:
        fail("No recording time remains.")
    capture_seconds = min(remaining, MAX_CAPTURE_SECONDS)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-reconnect", "1", "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5", "-i", media_url,
            "-t", str(capture_seconds), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "libmp3lame", "-b:a", "32k", str(AUDIO_FILE),
        ],
        check=False,
    )
    if result.returncode != 0 or not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 5000:
        fail("FFmpeg failed to capture valid audio.")
    return recording_start


def transcribe_smart(client):
    uploaded = client.files.upload(file=str(AUDIO_FILE))
    try:
        interaction = client.interactions.create(
            model="gemini-3.5-transcribe",
            input=[{"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}],
            generation_config={
                "transcription_config": {
                    "language_codes": ["fa-IR"],
                    "custom_vocabulary": CUSTOM_VOCABULARY,
                    "mode": "smart",
                }
            },
        )
        text = (interaction.output_text or "").strip()
        if not text:
            fail("Empty smart transcript.")
        SMART_TRANSCRIPT_FILE.write_text(text, encoding="utf-8")
        return text
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception as exc:
            print(f"Gemini file cleanup warning: {exc}", file=sys.stderr)


def split_audio():
    if CHUNK_DIR.exists():
        shutil.rmtree(CHUNK_DIR)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(AUDIO_FILE), "-f", "segment",
            "-segment_time", str(TIMESTAMP_CHUNK_SECONDS),
            "-reset_timestamps", "1", "-c", "copy",
            str(CHUNK_DIR / "chunk_%03d.mp3"),
        ],
        check=False,
    )
    if result.returncode != 0:
        fail("Could not split audio.")
    chunks = sorted(CHUNK_DIR.glob("chunk_*.mp3"))
    if not chunks:
        fail("No timestamp chunks created.")
    return chunks


def duration(path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        capture_output=True, text=True, check=False,
    )
    return float(result.stdout.strip())


def extract_words(interaction):
    words = []
    for step in getattr(interaction, "steps", []) or []:
        for content in getattr(step, "content", []) or []:
            for a in getattr(content, "annotations", []) or []:
                if getattr(a, "type", None) == "word_info":
                    text = str(getattr(a, "text", "") or "").strip()
                    if text:
                        words.append({
                            "text": text,
                            "speaker": str(getattr(a, "speaker", "") or "").strip(),
                            "start": parse_offset(getattr(a, "start_offset", 0)),
                            "end": parse_offset(getattr(a, "end_offset", 0)),
                        })
    return words


def transcribe_timestamp_chunk(client, chunk, base_offset):
    uploaded = client.files.upload(file=str(chunk))
    try:
        interaction = client.interactions.create(
            model="gemini-3.5-transcribe",
            input=[{"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}],
            generation_config={
                "transcription_config": {
                    "language_codes": ["fa-IR"],
                    "mode": {
                        "type": "verbatim",
                        "diarization_mode": "speaker",
                        "timestamp_granularities": ["word"],
                    },
                }
            },
        )
        words = extract_words(interaction)
        if not words:
            fail(f"No timestamps for {chunk.name}")
        for w in words:
            w["start"] += base_offset
            w["end"] += base_offset
        return words
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception as exc:
            print(f"Gemini file cleanup warning: {exc}", file=sys.stderr)


def transcribe_timestamps(client):
    all_words = []
    base = 0.0
    for chunk in split_audio():
        all_words.extend(transcribe_timestamp_chunk(client, chunk, base))
        base += duration(chunk)
    return all_words


def words_to_segments(words, max_seconds=24.0):
    segments = []
    current = None
    for w in words:
        if current is None:
            current = {
                "start": w["start"], "end": w["end"],
                "speaker": w["speaker"], "parts": [w["text"]],
            }
            continue
        speaker_changed = w["speaker"] and current["speaker"] and w["speaker"] != current["speaker"]
        too_long = w["end"] - current["start"] >= max_seconds
        long_pause = w["start"] - current["end"] >= 2.5
        if speaker_changed or too_long or long_pause:
            segments.append({
                "start": current["start"], "end": current["end"],
                "speaker": current["speaker"], "text": " ".join(current["parts"]),
            })
            current = {
                "start": w["start"], "end": w["end"],
                "speaker": w["speaker"], "parts": [w["text"]],
            }
        else:
            current["parts"].append(w["text"])
            current["end"] = w["end"]
    if current:
        segments.append({
            "start": current["start"], "end": current["end"],
            "speaker": current["speaker"], "text": " ".join(current["parts"]),
        })
    return segments


def timestamp_text_for_analysis(segments):
    return "\n".join(
        f"[{s['start']:.1f}s-{s['end']:.1f}s {s['speaker']}] {s['text']}"
        for s in segments
    )


def save_initial_transcript(info, recording_start, segments):
    lines = [
        "شبکه جهانی ولایت",
        f"نام برنامه: {info['program']}",
        f"تاریخ: {jalali_date_for_today()}",
        f"زمان رسمی: {info['start']} تا {info['end']}",
        f"شروع ضبط: {fmt_clock(recording_start, True)}",
        "شروع واقعی برنامه: در مرحله تحلیل تعیین می‌شود",
        "",
    ]
    for s in segments:
        a = absolute_time(recording_start, s["start"])
        b = absolute_time(recording_start, s["end"])
        lines += [
            f"[{fmt_clock(a, True)}–{fmt_clock(b, True)} | +{fmt_elapsed(s['start'])}–+{fmt_elapsed(s['end'])}] [{s['speaker']}]",
            s["text"],
            "",
        ]
    TRANSCRIPT_FILE.write_text("\n".join(lines), encoding="utf-8")


def make_analysis_prompt(smart, timestamped, info):
    return f"""
نام برنامه رسمی: {info['program']}
زمان رسمی: {info['start']} تا {info['end']}

START DETECTION:
شروع واقعی برنامه را از روی آغاز واقعی مجری پیدا کن؛ مانند بسم الله، سلام و خوشامدگویی،
معرفی همین برنامه، موضوع یا کارشناس. تیزر، آگهی، قرآن، صدای شبکه و برنامه قبلی شروع برنامه نیست.
اگر آغاز واقعی در فایل دیده نمی‌شود، program_start_detected=false و offset=0؛ زمان ساختگی نساز.

TIMING:
تمام start_offset_seconds/end_offset_seconds باید از timestampهای متن زمان‌دار گرفته شوند
و بر حسب ثانیه از ابتدای فایل ضبط‌شده باشند.
برای هر محور اصلی بازه زمانی واقعی آن را بده.
برای هر سؤال مخاطب، بازه سؤال + پاسخ کارشناس را بده.
سؤال مجری را سؤال مخاطب محسوب نکن.

source_type:
phone تماس تلفنی؛ message پیام/پیامک؛ unknown اگر نوع ارتباط روشن نیست.
نام مخاطب فقط اگر صریحاً گفته شده است.
نام کارشناس را حدس نزن.
خلاصه علمی، محتوایی و جامع باشد.
بخش جداگانه «شبهات» تولید نکن.

SMART TRANSCRIPT:
{smart}

TIMESTAMPED VERBATIM:
{timestamped}
"""


def analyze(client, smart, timestamped, info):
    prompt = make_analysis_prompt(smart, timestamped, info)
    errors = []
    for model in ANALYSIS_MODELS:
        for attempt, delay in enumerate(ANALYSIS_RETRY_DELAYS, 1):
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": ProgramAnalysis.model_json_schema(),
                    },
                )
                raw = (interaction.output_text or "").strip()
                return ProgramAnalysis.model_validate_json(raw), model
            except Exception as exc:
                errors.append(f"{model}/{attempt}: {exc}")
                if attempt < len(ANALYSIS_RETRY_DELAYS):
                    time.sleep(delay)
    fail("Analysis failed after retries.\n" + "\n".join(errors[-6:]))


def save_final_transcript(info, recording_start, segments, analysis):
    detected = analysis.program_start_detected
    start0 = max(0.0, analysis.program_start_offset_seconds)

    if detected:
        actual = absolute_time(recording_start, start0)
        actual_text = f"{fmt_clock(actual, True)} (مبدأ تایمر 00:00:00)"
    else:
        actual_text = "شناسایی نشد؛ تایمر نسبی اعمال نشده است"

    lines = [
        "شبکه جهانی ولایت",
        f"نام برنامه: {info['program']}",
        f"تاریخ: {jalali_date_for_today()}",
        f"زمان رسمی: {info['start']} تا {info['end']}",
        f"شروع ضبط: {fmt_clock(recording_start, True)}",
        f"شروع واقعی برنامه: {actual_text}",
        f"نشانه شروع: {analysis.program_start_evidence}",
        f"کارشناس: {analysis.expert}",
        f"موضوع: {analysis.topic}",
        "",
        "متن کامل زمان‌دار",
        "زمان اول = ساعت واقعی | زمان دوم = تایمر از شروع واقعی برنامه",
        "",
    ]
    for s in segments:
        label = timed_label(recording_start, s["start"], s["end"], start0, detected)
        lines += [f"[{label}] [{s['speaker']}]", s["text"], ""]
    TRANSCRIPT_FILE.write_text("\n".join(lines), encoding="utf-8")


def build_stats(analysis):
    phone = sum(q.source_type == "phone" for q in analysis.audience_questions)
    message = sum(q.source_type == "message" for q in analysis.audience_questions)
    unknown = sum(q.source_type == "unknown" for q in analysis.audience_questions)
    names = []
    for q in analysis.audience_questions:
        if q.audience_name != "نامشخص" and q.audience_name not in names:
            names.append(q.audience_name)
    return {
        "phone_count": phone, "message_count": message,
        "unknown_count": unknown, "total_count": len(analysis.audience_questions),
        "audience_names": names,
    }


def question_payload(analysis, recording_start):
    return [
        {
            "source_type": q.source_type,
            "audience_name": q.audience_name,
            "time_range": timed_label(
                recording_start, q.start_offset_seconds, q.end_offset_seconds,
                analysis.program_start_offset_seconds, analysis.program_start_detected,
            ),
            "question": q.question,
            "answer_summary": q.answer_summary,
        }
        for q in analysis.audience_questions
    ]


def post_to_sheet(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("ok") is not True:
        fail("Google Sheet rejected report: " + str(result))
    return result


def make_sheet_payload(info, analysis, stats, model, recording_start, bot_status):
    report_id = (
        f"{datetime.now(TEHRAN).strftime('%Y-%m-%d')}_"
        f"{info['start'].replace(':', '')}_{info['program'].replace(' ', '_')}"
    )
    actual_start = (
        fmt_clock(absolute_time(recording_start, analysis.program_start_offset_seconds), True)
        if analysis.program_start_detected else "شناسایی نشد"
    )
    return {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id,
        "date": jalali_date_for_today(),
        "day": info["day"],
        "start": info["start"],
        "end": info["end"],
        "program": info["program"],
        "actual_program_start": actual_start,
        "expert": analysis.expert,
        "topic": analysis.topic,
        "summary": analysis.summary,
        "key_points": [
            {
                "time_range": timed_label(
                    recording_start, k.start_offset_seconds, k.end_offset_seconds,
                    analysis.program_start_offset_seconds, analysis.program_start_detected,
                ),
                "text": k.text,
            }
            for k in analysis.key_points
        ],
        "phone_question_count": stats["phone_count"],
        "message_question_count": stats["message_count"],
        "unknown_question_count": stats["unknown_count"],
        "total_question_count": stats["total_count"],
        "audience_names": stats["audience_names"],
        "questions": [q.question for q in analysis.audience_questions],
        "answered_questions": question_payload(analysis, recording_start),
        "analysis_model": model,
        "status": "COMPLETED",
        "bot_status": bot_status,
    }


def source_label(value):
    return {"phone": "تلفنی", "message": "پیام/پیامک", "unknown": "نوع ارتباط نامشخص"}.get(value, "نامشخص")


def format_bale_message(info, analysis, stats, recording_start):
    start0 = analysis.program_start_offset_seconds
    detected = analysis.program_start_detected
    actual = (
        f"{fmt_clock(absolute_time(recording_start, start0), True)} (مبدأ 00:00:00)"
        if detected else "شناسایی نشد"
    )
    lines = [
        "📺 گزارش محتوایی برنامه زنده شبکه جهانی ولایت",
        "",
        f"🗓 تاریخ: {jalali_date_for_today()}",
        f"📺 نام برنامه: {info['program']}",
        f"👤 کارشناس: {analysis.expert}",
        f"🕒 زمان رسمی: {info['start']} تا {info['end']}",
        f"▶️ شروع واقعی برنامه: {actual}",
        f"🎯 موضوع: {analysis.topic}",
        "",
        "📝 خلاصه محتوایی برنامه:",
        analysis.summary,
        "",
        "🔹 محورهای اصلی محتوا:",
    ]
    for i, k in enumerate(analysis.key_points, 1):
        label = timed_label(recording_start, k.start_offset_seconds, k.end_offset_seconds, start0, detected)
        lines.append(f"{i}. [{label}] {k.text}")

    if analysis.audience_questions:
        lines += ["", "❓ سؤالات مخاطبان و چکیده پاسخ کارشناس:"]
        for i, q in enumerate(analysis.audience_questions, 1):
            label = timed_label(recording_start, q.start_offset_seconds, q.end_offset_seconds, start0, detected)
            name = f" – {q.audience_name}" if q.audience_name != "نامشخص" else ""
            lines.append(f"{i}. [{source_label(q.source_type)}{name} | {label}] {q.question}")
            lines.append(f"   ↳ پاسخ: {q.answer_summary}")

    lines += [
        "",
        "📊 آمار مخاطبان:",
        f"☎️ سؤالات تلفنی پاسخ‌داده‌شده: {stats['phone_count']}",
        f"💬 سؤالات پیام/پیامکی پاسخ‌داده‌شده: {stats['message_count']}",
    ]
    if stats["unknown_count"]:
        lines.append(f"❔ نوع ارتباط نامشخص: {stats['unknown_count']}")
    lines.append(f"✅ مجموع سؤالات پاسخ‌داده‌شده: {stats['total_count']}")
    return "\n".join(lines)


def split_message(text, limit=3900):
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = current + "\n" + line if current else line
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = line
    if current:
        chunks.append(current)
    return chunks


def send_bale_message(text):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
    for chunk in split_message(text):
        body = json.dumps({"chat_id": BALE_CHAT_ID, "text": chunk}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
        if result.get("ok") is not True:
            fail("Bale rejected message: " + str(result))
        time.sleep(1)


def send_bale_transcript(info):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendDocument"
    caption = (
        f"📄 متن کامل زمان‌دار برنامه «{info['program']}»\n"
        f"🗓 {jalali_date_for_today()} | 🕒 {info['start']} تا {info['end']}"
    )
    filename = (
        f"velayat_timestamped_transcript_"
        f"{jalali_date_for_today().replace('/', '-')}_"
        f"{info['start'].replace(':', '-')}.txt"
    )
    with TRANSCRIPT_FILE.open("rb") as handle:
        response = requests.post(
            url,
            data={"chat_id": BALE_CHAT_ID, "caption": caption},
            files={"document": (filename, handle, "text/plain; charset=utf-8")},
            timeout=180,
        )
    result = response.json()
    if response.status_code != 200 or result.get("ok") is not True:
        fail("Bale rejected transcript file: " + str(result))


def update_bot_status(report_id, status):
    try:
        post_to_sheet({
            "secret": WEBHOOK_SECRET,
            "report_id": report_id,
            "update_only": True,
            "bot_status": status,
        })
    except Exception as exc:
        print(f"BOT_STATUS update warning: {exc}", file=sys.stderr)


def send_bale_error(message):
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return
    try:
        url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
        text = f"⚠️ خطای سامانه رصد شبکه ولایت\n\n{message}\n\nRun ID: {GITHUB_RUN_ID}"
        body = json.dumps({"chat_id": BALE_CHAT_ID, "text": text[:3900]}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=20).read()
    except Exception:
        pass


def main():
    check_required_settings()
    info = get_program_info()

    # در Workflow v3.3 runner زودتر بالا می‌آید.
    # URL حدود 90 ثانیه قبل آماده می‌شود و ضبط از ساعت رسمی شروع می‌شود.
    media_url = prepare_stream(info)
    recording_start = capture_audio(media_url, info)

    client = genai.Client(api_key=GEMINI_API_KEY)

    # خروجی اول: متن دقیق Smart
    smart = transcribe_smart(client)

    # خروجی دوم: کلمات زمان‌دار، در قطعات زیر 30 دقیقه
    words = transcribe_timestamps(client)
    segments = words_to_segments(words)

    # حتی اگر Analysis شکست بخورد، یک TXT زمان‌دار اولیه باقی می‌ماند.
    save_initial_transcript(info, recording_start, segments)

    timestamped = timestamp_text_for_analysis(segments)
    analysis, model = analyze(client, smart, timestamped, info)

    # بازنویسی TXT با مبدأ واقعی برنامه
    save_final_transcript(info, recording_start, segments, analysis)

    stats = build_stats(analysis)

    REPORT_FILE.write_text(
        json.dumps(
            {
                "program": info["program"],
                "expert": analysis.expert,
                "topic": analysis.topic,
                "actual_program_start": (
                    fmt_clock(
                        absolute_time(recording_start, analysis.program_start_offset_seconds), True
                    )
                    if analysis.program_start_detected else "شناسایی نشد"
                ),
                "key_points": [
                    {
                        "time_range": timed_label(
                            recording_start, k.start_offset_seconds, k.end_offset_seconds,
                            analysis.program_start_offset_seconds, analysis.program_start_detected,
                        ),
                        "text": k.text,
                    }
                    for k in analysis.key_points
                ],
                "audience_questions": question_payload(analysis, recording_start),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = make_sheet_payload(
        info, analysis, stats, model, recording_start, "PENDING"
    )
    post_to_sheet(payload)

    try:
        send_bale_message(format_bale_message(info, analysis, stats, recording_start))
        send_bale_transcript(info)
        update_bot_status(payload["report_id"], "SENT")
    except Exception:
        update_bot_status(payload["report_id"], "FAILED")
        raise

    print("VELAYAT LIVE MONITOR v3.4 TIMESTAMP: SUCCESS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        send_bale_error(str(exc))
        raise
