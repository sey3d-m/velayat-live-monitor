import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
from google import genai
from pydantic import BaseModel, Field


TEHRAN = ZoneInfo("Asia/Tehran")

STREAM_URL = os.environ.get("STREAM_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "").strip()

# IMPORTANT: Workflow always sends an explicit slot.
PROGRAM_SLOT = os.environ.get("PROGRAM_SLOT", "").strip()
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual")

AUDIO_FILE = Path("program_audio.mp3")
TRANSCRIPT_FILE = Path("program_transcript.txt")
REPORT_FILE = Path("program_report.json")

# Slightly below one hour, to stay safely inside a 60-minute transcription request.
MAX_CAPTURE_SECONDS = 3595

# Analysis model: retry the primary model and then move to fallbacks.
# If Google changes model availability later, only this list needs editing.
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
    "شنبه": {
        "18:00": "زمزم احکام",
        "19:30": "آفتاب و سایه ها",
        "21:00": "پرسمان اعتقادی",
    },
    "یکشنبه": {
        "18:00": "امت اسلام",
        "19:30": "بیان امیر",
        "21:00": "فائزون",
    },
    "دوشنبه": {
        "18:00": "زمزم احکام",
        "19:30": "فرکانس تاریکی",
        "21:00": "پرسمان مذاهب",
    },
    "سه شنبه": {
        "18:00": "کانون مهر",
        "19:30": "پیام تاریخ",
        "21:00": "پرسمان قرآنی",
    },
    "چهارشنبه": {
        "18:00": "زمزم احکام",
        "19:30": "چراغ",
        "21:00": "پرسمان اعتقادی",
    },
    "پنجشنبه": {
        "18:00": "پرسمان تاریخی",
        "19:30": "گامی به سوی ظهور",
        "21:00": "حیات قرآنی",
    },
}

CUSTOM_VOCABULARY = [
    "شبکه جهانی ولایت",
    "زمزم احکام",
    "آفتاب و سایه ها",
    "آفتاب و سایه‌ها",
    "پرسمان اعتقادی",
    "امت اسلام",
    "بیان امیر",
    "فائزون",
    "فرکانس تاریکی",
    "پرسمان مذاهب",
    "کانون مهر",
    "پیام تاریخ",
    "پرسمان قرآنی",
    "چراغ",
    "پرسمان تاریخی",
    "گامی به سوی ظهور",
    "حیات قرآنی",
    "اهل بیت",
    "اهل‌بیت",
    "امیرالمؤمنین",
    "حضرت زهرا",
    "امام زمان",
    "حضرت مهدی",
    "مهدویت",
    "شیعه",
    "اهل سنت",
    "اهل‌سنت",
    "قرآن کریم",
    "نهج البلاغه",
    "نهج‌البلاغه",
]


class AudienceQuestion(BaseModel):
    source_type: Literal["phone", "message", "unknown"] = Field(
        description=(
            "phone فقط وقتی تماس تلفنی/پشت خط بودن روشن است؛ "
            "message فقط وقتی پیام/پیامک روشن است؛ "
            "در غیر این صورت unknown"
        )
    )
    audience_name: str = Field(
        description=(
            "نام مخاطب فقط اگر در متن صریحاً گفته شده؛ "
            "در غیر این صورت «نامشخص»"
        )
    )
    question: str = Field(
        description="صورت کوتاه و دقیق سؤال مخاطب که کارشناس به آن پاسخ داده است"
    )
    answer_summary: str = Field(
        description="خلاصه 1 تا 3 جمله‌ای از پاسخ کارشناس به همان سؤال"
    )


class ProgramAnalysis(BaseModel):
    expert: str = Field(
        description=(
            "نام کارشناس یا کارشناسان فقط بر اساس معرفی روشن متن؛ "
            "در غیر این صورت «نامشخص»"
        )
    )
    topic: str = Field(
        description="عنوان کوتاه و دقیق موضوع اصلی برنامه"
    )
    summary: str = Field(
        description=(
            "خلاصه محتوایی جامع از کل برنامه با تمرکز بر استدلال‌ها، "
            "توضیحات و پاسخ‌های علمی؛ حدود 1000 تا 1800 نویسه"
        )
    )
    key_points: list[str] = Field(
        description="5 تا 8 محور اصلی محتوایی و غیرتکراری برنامه"
    )
    audience_questions: list[AudienceQuestion] = Field(
        description=(
            "تمام سؤال‌های مخاطبان که واقعاً در برنامه مطرح شده "
            "و کارشناس به آن‌ها پاسخ داده است"
        )
    )


def fail(message: str):
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
        fail(
            f"Invalid PROGRAM_SLOT={PROGRAM_SLOT}. "
            "Allowed values: 18:00, 19:30, 21:00"
        )


def persian_day_name(dt: datetime) -> str:
    # Monday=0 ... Sunday=6
    names = {
        0: "دوشنبه",
        1: "سه شنبه",
        2: "چهارشنبه",
        3: "پنجشنبه",
        4: "جمعه",
        5: "شنبه",
        6: "یکشنبه",
    }
    return names[dt.weekday()]


def today_at(now: datetime, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


def get_program_info():
    """
    FIX #1:
    Never guess the slot from current time.
    The Workflow gives PROGRAM_SLOT explicitly.

    If GitHub starts a scheduled run a few minutes late, we still know exactly
    which program this run belongs to and record the remaining portion until
    the official end time.
    """
    now = datetime.now(TEHRAN)
    day = persian_day_name(now)

    if day == "جمعه":
        fail("جمعه برنامه‌ای در کنداکتور رصد تعریف نشده است.")

    if day not in PROGRAMS:
        fail(f"No program schedule configured for {day}.")

    start_s, end_s = SLOTS[PROGRAM_SLOT]
    start_dt = today_at(now, start_s)
    end_dt = today_at(now, end_s)

    if now >= end_dt:
        fail(
            f"نوبت {PROGRAM_SLOT} مربوط به «{PROGRAMS[day][PROGRAM_SLOT]}» "
            f"است، اما GitHub بعد از پایان رسمی برنامه ({end_s}) اجرا شده است."
        )

    if now < start_dt:
        # This can happen on a manual run before the selected slot.
        wait_seconds = int((start_dt - now).total_seconds())
        print(
            f"Manual run started early. Waiting {wait_seconds} seconds "
            f"until {start_s} Tehran..."
        )
        time.sleep(wait_seconds)

    return {
        "day": day,
        "slot": PROGRAM_SLOT,
        "start": start_s,
        "end": end_s,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "program": PROGRAMS[day][PROGRAM_SLOT],
    }


def resolve_stream_url(url: str) -> str:
    lower = url.lower()

    if "youtube.com" not in lower and "youtu.be" not in lower:
        return url

    last_error = ""

    for attempt in range(1, 6):
        print(f"Resolving YouTube live stream (attempt {attempt}/5)...")

        result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "-f",
                "bestaudio/best",
                "-g",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            urls = [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            ]
            if urls:
                return urls[0]

        last_error = result.stderr.strip()
        print(last_error, file=sys.stderr)

        if attempt < 5:
            time.sleep(15)

    fail("Could not resolve live stream. " + last_error)


def capture_audio(media_url: str, info):
    now = datetime.now(TEHRAN)
    remaining = int((info["end_dt"] - now).total_seconds())

    if remaining <= 0:
        fail("No recording time remains for this program.")

    capture_seconds = min(remaining, MAX_CAPTURE_SECONDS)

    print(
        f"Recording «{info['program']}» from now until {info['end']} Tehran "
        f"({capture_seconds} seconds)..."
    )

    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-i",
            media_url,
            "-t",
            str(capture_seconds),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(AUDIO_FILE),
        ],
        check=False,
    )

    if result.returncode != 0:
        fail("FFmpeg failed to capture the live audio.")

    if not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 5000:
        fail("Captured audio file is missing or unexpectedly small.")

    print(f"Audio saved: {AUDIO_FILE.stat().st_size} bytes")


def transcribe_audio(client: genai.Client) -> str:
    print("Uploading audio to Gemini Transcribe...")

    uploaded = client.files.upload(file=str(AUDIO_FILE))

    interaction = client.interactions.create(
        model="gemini-3.5-transcribe",
        input=[
            {
                "type": "audio",
                "uri": uploaded.uri,
                "mime_type": uploaded.mime_type,
            }
        ],
        generation_config={
            "transcription_config": {
                "language_codes": ["fa-IR"],
                "custom_vocabulary": CUSTOM_VOCABULARY,
                "mode": "smart",
            }
        },
    )

    transcript = (interaction.output_text or "").strip()

    if not transcript:
        fail("Gemini Transcribe returned an empty transcript.")

    # IMPORTANT:
    # Save transcript BEFORE analysis. If analysis fails later, this file still
    # exists and GitHub uploads it as an artifact because the upload step is
    # configured with if: always().
    TRANSCRIPT_FILE.write_text(transcript, encoding="utf-8")
    print(f"Transcription complete: {len(transcript)} characters")

    return transcript


def analysis_prompt(transcript: str, info) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوای برنامه‌های زنده شبکه جهانی ولایت.

نام برنامه طبق کنداکتور: {info["program"]}
روز: {info["day"]}
زمان رسمی برنامه: {info["start"]} تا {info["end"]} به وقت تهران

وظیفه:
از متن کامل پیاده‌شده، گزارش محتوایی دقیق برنامه و سؤال‌های مخاطبان را استخراج کن.

قواعد:
1. فقط از همین متن استفاده کن؛ هیچ اطلاعاتی را حدس نزن.
2. تمرکز اصلی روی محتوای برنامه باشد.
3. summary باید مهم‌ترین استدلال‌ها، توضیحات، پاسخ‌ها و نتیجه‌گیری‌ها را پوشش دهد.
4. key_points محورهای اصلی محتوا باشند.
5. در audience_questions فقط سؤال مخاطبانی را ثبت کن که واقعاً مطرح شده و کارشناس پاسخ داده است.
6. سؤال‌های خود مجری را به عنوان سؤال مخاطب ثبت نکن.
7. source_type:
   - phone: تماس تلفنی یا پشت خط بودن مخاطب روشن است.
   - message: پیام/پیامک مخاطب روشن است.
   - unknown: مخاطب بودن روشن است ولی نوع ارتباط روشن نیست.
8. audience_name را فقط اگر نام مخاطب در متن گفته شده ثبت کن؛ وگرنه «نامشخص».
9. answer_summary خلاصه دقیق پاسخ کارشناس به همان سؤال باشد.
10. هیچ بخش مستقلی با عنوان «شبهات» تولید نکن.
11. اگر مخاطب چند سؤال مستقل پرسیده و هرکدام پاسخ گرفته، جدا ثبت کن.
12. همه خروجی‌ها فارسی باشند.

متن برنامه:
--------------------
{transcript}
--------------------
"""


def analyze_transcript_with_retry(
    client: genai.Client,
    transcript: str,
    info,
) -> tuple[ProgramAnalysis, str]:
    """
    FIX #2:
    Retry temporary Gemini errors and then move to fallback Flash models.
    A temporary 500/503/high-demand error no longer immediately kills the run.
    """

    prompt = analysis_prompt(transcript, info)
    errors = []

    for model in ANALYSIS_MODELS:
        for attempt, delay in enumerate(ANALYSIS_RETRY_DELAYS, start=1):
            try:
                print(
                    f"Analyzing with {model} "
                    f"(attempt {attempt}/{len(ANALYSIS_RETRY_DELAYS)})..."
                )

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

                if not raw:
                    raise RuntimeError("empty analysis response")

                analysis = ProgramAnalysis.model_validate_json(raw)

                print(f"Analysis succeeded with model: {model}")
                return analysis, model

            except Exception as exc:
                error_text = f"{model} attempt {attempt}: {exc}"
                errors.append(error_text)
                print(error_text, file=sys.stderr)

                # Last attempt for this model -> immediately move to fallback.
                if attempt < len(ANALYSIS_RETRY_DELAYS):
                    print(f"Waiting {delay} seconds before retry...")
                    time.sleep(delay)

        print(f"Moving to fallback model after failures on {model}...")

    fail(
        "همه مدل‌های تحلیل Gemini پس از Retry ناموفق بودند. "
        "متن کامل برنامه در Artifact حفظ شده است.\n"
        + "\n".join(errors[-6:])
    )


def jalali_date_for_today() -> str:
    now = datetime.now(TEHRAN)
    j = jdatetime.date.fromgregorian(date=now.date())
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"


def build_stats(analysis: ProgramAnalysis):
    phone = 0
    message = 0
    unknown = 0
    names = []

    for item in analysis.audience_questions:
        if item.source_type == "phone":
            phone += 1
        elif item.source_type == "message":
            message += 1
        else:
            unknown += 1

        name = item.audience_name.strip()
        if name and name != "نامشخص" and name not in names:
            names.append(name)

    return {
        "phone_count": phone,
        "message_count": message,
        "unknown_count": unknown,
        "total_count": len(analysis.audience_questions),
        "audience_names": names,
    }


def answered_questions_payload(analysis: ProgramAnalysis):
    return [
        {
            "source_type": item.source_type,
            "audience_name": item.audience_name,
            "question": item.question,
            "answer_summary": item.answer_summary,
        }
        for item in analysis.audience_questions
    ]


def make_report_payload(
    info,
    analysis: ProgramAnalysis,
    stats,
    analysis_model: str,
    bot_status: str,
):
    gregorian = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    report_id = (
        f"{gregorian}_{info['start'].replace(':', '')}_"
        f"{info['program'].replace(' ', '_')}"
    )

    return {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id,
        "date": jalali_date_for_today(),
        "day": info["day"],
        "start": info["start"],
        "end": info["end"],
        "program": info["program"],
        "expert": analysis.expert,
        "topic": analysis.topic,
        "summary": analysis.summary,
        "key_points": analysis.key_points,
        "phone_question_count": stats["phone_count"],
        "message_question_count": stats["message_count"],
        "unknown_question_count": stats["unknown_count"],
        "total_question_count": stats["total_count"],
        "audience_names": stats["audience_names"],
        "answered_questions": answered_questions_payload(analysis),
        "questions": [
            item.question
            for item in analysis.audience_questions
        ],
        "analysis_model": analysis_model,
        "status": "COMPLETED",
        "bot_status": bot_status,
    }


def post_to_sheet(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        response_text = response.read().decode("utf-8")

    result = json.loads(response_text)

    if result.get("ok") is not True:
        fail(
            "Google Sheet webhook rejected report: "
            + json.dumps(result, ensure_ascii=False)
        )

    print("Google Sheet response:", result)
    return result


def source_label(source_type: str) -> str:
    return {
        "phone": "تلفنی",
        "message": "پیام/پیامک",
        "unknown": "نوع ارتباط نامشخص",
    }.get(source_type, "نامشخص")


def format_bale_message(info, analysis: ProgramAnalysis, stats) -> str:
    lines = [
        "📺 گزارش محتوایی برنامه زنده شبکه جهانی ولایت",
        "",
        f"🗓 تاریخ: {jalali_date_for_today()}",
        f"📌 برنامه: {info['program']}",
        f"👤 کارشناس: {analysis.expert}",
        f"🕒 زمان: {info['start']} تا {info['end']} به وقت تهران",
        f"🎯 موضوع: {analysis.topic}",
        "",
        "📝 خلاصه محتوایی برنامه:",
        analysis.summary,
    ]

    if analysis.key_points:
        lines.extend(["", "🔹 محورهای اصلی محتوا:"])
        for index, item in enumerate(analysis.key_points, 1):
            lines.append(f"{index}. {item}")

    lines.extend([
        "",
        "📊 آمار پاسخ‌گویی به مخاطبان:",
        f"☎️ سؤالات تلفنی پاسخ‌داده‌شده: {stats['phone_count']}",
        f"💬 سؤالات پیام/پیامکی پاسخ‌داده‌شده: {stats['message_count']}",
    ])

    if stats["unknown_count"]:
        lines.append(
            f"❔ سؤالات مخاطبان با نوع ارتباط نامشخص: "
            f"{stats['unknown_count']}"
        )

    lines.append(
        f"✅ مجموع سؤالات مخاطبان که پاسخ داده شد: "
        f"{stats['total_count']}"
    )

    if stats["audience_names"]:
        lines.extend([
            "",
            "👥 نام مخاطبان شناسایی‌شده:",
            "، ".join(stats["audience_names"][:12]),
        ])

    if analysis.audience_questions:
        lines.extend([
            "",
            "❓ سؤالات مخاطبان و چکیده پاسخ کارشناس:"
        ])

        for index, item in enumerate(analysis.audience_questions, 1):
            audience = (
                f" – {item.audience_name}"
                if item.audience_name != "نامشخص"
                else ""
            )

            lines.append(
                f"{index}. [{source_label(item.source_type)}{audience}] "
                f"{item.question}"
            )
            lines.append(f"   ↳ پاسخ: {item.answer_summary}")

    lines.extend([
        "",
        "🤖 رصد و تحلیل خودکار برنامه زنده"
    ])

    return "\n".join(lines)


def split_message(text: str, limit: int = 3900):
    if len(text) <= limit:
        return [text]

    chunks = []
    current = ""

    for line in text.split("\n"):
        candidate = current + "\n" + line if current else line

        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(line) <= limit:
            current = line
        else:
            for i in range(0, len(line), limit):
                part = line[i:i + limit]
                if len(part) == limit:
                    chunks.append(part)
                else:
                    current = part

    if current:
        chunks.append(current)

    return chunks


def send_bale_message(text: str):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"

    for index, chunk in enumerate(split_message(text), 1):
        body = json.dumps(
            {
                "chat_id": BALE_CHAT_ID,
                "text": chunk,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8"
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok") is not True:
            fail(
                "Bale API rejected message: "
                + json.dumps(result, ensure_ascii=False)
            )

        time.sleep(1)

    print("Report sent to Bale successfully.")


def update_bot_status(report_id: str, status: str):
    try:
        post_to_sheet({
            "secret": WEBHOOK_SECRET,
            "report_id": report_id,
            "update_only": True,
            "bot_status": status,
        })
    except Exception as exc:
        print(
            f"Could not update BOT_STATUS in Google Sheet: {exc}",
            file=sys.stderr,
        )


def send_bale_error(message: str):
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return

    try:
        url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
        text = (
            "⚠️ خطای سامانه رصد شبکه ولایت\n\n"
            f"{message}\n\n"
            f"Run ID: {GITHUB_RUN_ID}"
        )

        body = json.dumps(
            {
                "chat_id": BALE_CHAT_ID,
                "text": text[:3900],
            },
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8"
            },
            method="POST",
        )

        urllib.request.urlopen(request, timeout=20).read()

    except Exception as exc:
        print(
            f"Could not send Bale error notification: {exc}",
            file=sys.stderr,
        )


def main():
    check_required_settings()
    info = get_program_info()

    print(
        json.dumps(
            {
                "day": info["day"],
                "program": info["program"],
                "start": info["start"],
                "end": info["end"],
                "slot": info["slot"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    client = genai.Client(api_key=GEMINI_API_KEY)

    media_url = resolve_stream_url(STREAM_URL)
    capture_audio(media_url, info)

    transcript = transcribe_audio(client)

    analysis, used_model = analyze_transcript_with_retry(
        client,
        transcript,
        info,
    )

    stats = build_stats(analysis)

    report_preview = {
        "date": jalali_date_for_today(),
        "day": info["day"],
        "program": info["program"],
        "expert": analysis.expert,
        "topic": analysis.topic,
        "summary": analysis.summary,
        "key_points": analysis.key_points,
        "statistics": stats,
        "analysis_model": used_model,
        "audience_questions": answered_questions_payload(analysis),
    }

    REPORT_FILE.write_text(
        json.dumps(
            report_preview,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    pending_payload = make_report_payload(
        info,
        analysis,
        stats,
        used_model,
        bot_status="PENDING",
    )

    post_to_sheet(pending_payload)
    report_id = pending_payload["report_id"]

    try:
        send_bale_message(
            format_bale_message(info, analysis, stats)
        )
        update_bot_status(report_id, "SENT")
    except Exception:
        update_bot_status(report_id, "FAILED")
        raise

    print("VELAYAT LIVE MONITOR v3.1: SUCCESS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        send_bale_error(str(exc))
        raise
