import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
import requests
from faster_whisper import WhisperModel
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

TRANSCRIPT_FILE = Path("program_transcript.txt")
REPORT_FILE = Path("program_report.json")
AUDIO_DIR = Path("audio_segments")

MAX_CAPTURE_SECONDS = 3595

WHISPER_MODEL_NAME = os.environ.get("WHISPER_MODEL", "small").strip()
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip()
SEGMENT_SECONDS = 300

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

WHISPER_PROMPT = (
    "شبکه جهانی ولایت، زمزم احکام، آفتاب و سایه‌ها، پرسمان اعتقادی، "
    "امت اسلام، بیان امیر، فائزون، فرکانس تاریکی، پرسمان مذاهب، "
    "کانون مهر، پیام تاریخ، پرسمان قرآنی، چراغ، پرسمان تاریخی، "
    "گامی به سوی ظهور، حیات قرآنی، اهل‌بیت، امیرالمؤمنین، حضرت زهرا، "
    "امام زمان، حضرت مهدی، مهدویت، شیعه، اهل‌سنت، قرآن کریم، نهج‌البلاغه"
)

class AudienceQuestion(BaseModel):
    source_type: Literal["phone", "message", "unknown"] = Field(
        description="phone برای تماس تلفنی، message برای پیام، در غیر این صورت unknown"
    )
    audience_name: str = Field(description="نام مخاطب یا «نامشخص»")
    question: str
    answer_summary: str

class ProgramAnalysis(BaseModel):
    expert: str = Field(description="نام کارشناس یا «نامشخص»")
    topic: str
    summary: str
    key_points: list[str]
    audience_questions: list[AudienceQuestion]

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
        fail("Invalid PROGRAM_SLOT. Allowed: 18:00, 19:30, 21:00")

def persian_day_name(dt: datetime) -> str:
    return {
        0: "دوشنبه",
        1: "سه شنبه",
        2: "چهارشنبه",
        3: "پنجشنبه",
        4: "جمعه",
        5: "شنبه",
        6: "یکشنبه",
    }[dt.weekday()]

def today_at(now: datetime, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)

def get_program_info():
    now = datetime.now(TEHRAN)
    day = persian_day_name(now)

    if day == "جمعه":
        fail("جمعه برنامه‌ای در کنداکتور رصد تعریف نشده است.")

    start_s, end_s = SLOTS[PROGRAM_SLOT]
    start_dt = today_at(now, start_s)
    end_dt = today_at(now, end_s)

    if now >= end_dt:
        fail(
            f"نوبت {PROGRAM_SLOT} مربوط به «{PROGRAMS[day][PROGRAM_SLOT]}» است، "
            f"اما اجرا بعد از پایان رسمی برنامه ({end_s}) آغاز شده است."
        )

    return {
        "day": day,
        "slot": PROGRAM_SLOT,
        "start": start_s,
        "end": end_s,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "program": PROGRAMS[day][PROGRAM_SLOT],
    }

def wait_until_start(info):
    now = datetime.now(TEHRAN)
    if now < info["start_dt"]:
        wait_seconds = int((info["start_dt"] - now).total_seconds())
        print(
            f"Runner and Whisper are ready; waiting {wait_seconds}s "
            f"until official start {info['start']} Tehran..."
        )
        time.sleep(wait_seconds)

def resolve_stream_url(url: str) -> str:
    if "youtube.com" not in url.lower() and "youtu.be" not in url.lower():
        return url

    last_error = ""
    for attempt in range(1, 6):
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-g", url],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            urls = [x.strip() for x in result.stdout.splitlines() if x.strip()]
            if urls:
                return urls[0]

        last_error = result.stderr.strip()
        print(last_error, file=sys.stderr)
        if attempt < 5:
            time.sleep(15)

    fail("Could not resolve live stream. " + last_error)

def prepare_audio_dir():
    AUDIO_DIR.mkdir(exist_ok=True)
    for old in AUDIO_DIR.glob("segment_*.mp3"):
        old.unlink()

def start_segmented_capture(media_url: str, capture_seconds: int):
    prepare_audio_dir()

    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
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
        "-f",
        "segment",
        "-segment_time",
        str(SEGMENT_SECONDS),
        "-reset_timestamps",
        "1",
        str(AUDIO_DIR / "segment_%03d.mp3"),
    ]

    print(
        f"Starting live capture: {capture_seconds}s, "
        f"{SEGMENT_SECONDS}s segments."
    )
    return subprocess.Popen(cmd)

def transcribe_file_local(model: WhisperModel, path: Path) -> str:
    segments, _ = model.transcribe(
        str(path),
        language="fa",
        beam_size=5,
        vad_filter=True,
        initial_prompt=WHISPER_PROMPT,
        condition_on_previous_text=True,
    )

    pieces = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            pieces.append(text)

    return " ".join(pieces).strip()

def save_transcript(parts: list[str]):
    text = "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()
    TRANSCRIPT_FILE.write_text(text, encoding="utf-8")

def local_transcription_worker(
    model: WhisperModel,
    capture_process,
    transcript_parts: list[str],
    worker_error: list[Exception],
):
    processed = set()

    try:
        while True:
            files = sorted(AUDIO_DIR.glob("segment_*.mp3"))
            capture_done = capture_process.poll() is not None

            ready = files if capture_done else files[:-1]

            for path in ready:
                if path.name in processed:
                    continue

                print(f"Local Whisper transcribing {path.name}...")
                text = transcribe_file_local(model, path)

                if text:
                    transcript_parts.append(text)
                    save_transcript(transcript_parts)

                processed.add(path.name)

                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

                print(f"Completed {path.name}; transcript checkpoint saved.")

            if capture_done:
                files = sorted(AUDIO_DIR.glob("segment_*.mp3"))
                remaining = [p for p in files if p.name not in processed]
                if not remaining:
                    break

            time.sleep(2)

    except Exception as exc:
        worker_error.append(exc)

def capture_and_transcribe_local(
    model: WhisperModel,
    media_url: str,
    capture_seconds: int,
) -> str:
    transcript_parts: list[str] = []
    worker_error: list[Exception] = []

    process = start_segmented_capture(media_url, capture_seconds)

    worker = threading.Thread(
        target=local_transcription_worker,
        args=(model, process, transcript_parts, worker_error),
        daemon=True,
    )
    worker.start()

    return_code = process.wait()
    worker.join()

    if return_code != 0:
        fail(f"FFmpeg live capture failed with code {return_code}.")

    if worker_error:
        fail(f"Local Whisper transcription failed: {worker_error[0]}")

    transcript = (
        TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
        if TRANSCRIPT_FILE.exists()
        else ""
    )

    if not transcript:
        fail("Local Whisper returned an empty transcript.")

    print(f"Local transcription complete: {len(transcript)} characters.")
    return transcript

def analysis_prompt(transcript: str, info) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوای برنامه‌های زنده شبکه جهانی ولایت.

نام برنامه طبق کنداکتور رسمی: {info["program"]}
روز: {info["day"]}
زمان رسمی برنامه: {info["start"]} تا {info["end"]} به وقت تهران

متن زیر با سامانه تبدیل گفتار به متن محلی تهیه شده است و ممکن است در بعضی
اسامی یا علائم نگارشی خطاهای جزئی داشته باشد.

قواعد:
1. فقط از همین متن استفاده کن.
2. summary باید مهم‌ترین استدلال‌ها، توضیحات، پاسخ‌ها و نتیجه‌گیری‌ها را پوشش دهد.
3. key_points پنج تا هشت محور اصلی و غیرتکراری باشند.
4. فقط سؤال مخاطبانی را ثبت کن که واقعاً مطرح شده و کارشناس به آن پاسخ داده است.
5. سؤال مجری را سؤال مخاطب حساب نکن.
6. source_type: phone / message / unknown.
7. نام مخاطب فقط اگر صریحاً گفته شده؛ وگرنه «نامشخص».
8. برای هر سؤال، خلاصه دقیق پاسخ کارشناس را بنویس.
9. بخش مستقلی با عنوان «شبهات» نساز.
10. همه خروجی‌ها فارسی باشند.

متن کامل برنامه:
--------------------
{transcript}
--------------------
"""

def analyze_transcript_with_retry(client, transcript, info):
    prompt = analysis_prompt(transcript, info)
    errors = []

    for model in ANALYSIS_MODELS:
        for attempt, delay in enumerate(ANALYSIS_RETRY_DELAYS, start=1):
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
                if not raw:
                    raise RuntimeError("empty analysis response")

                return ProgramAnalysis.model_validate_json(raw), model

            except Exception as exc:
                errors.append(f"{model} attempt {attempt}: {exc}")
                print(errors[-1], file=sys.stderr)

                if attempt < len(ANALYSIS_RETRY_DELAYS):
                    time.sleep(delay)

    fail(
        "همه تلاش‌های تحلیل Gemini ناموفق بودند. "
        "متن کامل برنامه حفظ شده است.\n"
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

        if (
            item.audience_name
            and item.audience_name != "نامشخص"
            and item.audience_name not in names
        ):
            names.append(item.audience_name)

    return {
        "phone_count": phone,
        "message_count": message,
        "unknown_count": unknown,
        "total_count": len(analysis.audience_questions),
        "audience_names": names,
    }

def answered_questions_payload(analysis):
    return [item.model_dump() for item in analysis.audience_questions]

def make_report_payload(info, analysis, stats, analysis_model, bot_status):
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
        "questions": [item.question for item in analysis.audience_questions],
        "analysis_model": analysis_model,
        "status": "COMPLETED",
        "bot_status": bot_status,
    }

def post_to_sheet(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))

    if result.get("ok") is not True:
        fail("Google Sheet webhook rejected report: " + str(result))

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
        f"📺 نام برنامه: {info['program']}",
        f"👤 کارشناس: {analysis.expert}",
        f"🕒 زمان برنامه: {info['start']} تا {info['end']} به وقت تهران",
        f"🎯 موضوع: {analysis.topic}",
        "",
        "📝 خلاصه محتوایی برنامه:",
        analysis.summary,
    ]

    if analysis.key_points:
        lines += ["", "🔹 محورهای اصلی محتوا:"]
        for i, item in enumerate(analysis.key_points, 1):
            lines.append(f"{i}. {item}")

    if analysis.audience_questions:
        lines += ["", "❓ سؤالات مخاطبان و چکیده پاسخ کارشناس:"]
        for i, item in enumerate(analysis.audience_questions, 1):
            audience = (
                f" – {item.audience_name}"
                if item.audience_name != "نامشخص"
                else ""
            )
            lines.append(
                f"{i}. [{source_label(item.source_type)}{audience}] "
                f"{item.question}"
            )
            lines.append(f"   ↳ پاسخ: {item.answer_summary}")
    else:
        lines += [
            "",
            "❓ سؤالات مخاطبان:",
            "در این برنامه سؤال پاسخ‌داده‌شده‌ای از مخاطبان شناسایی نشد.",
        ]

    lines += [
        "",
        "📊 آمار مخاطبان:",
        f"☎️ سؤالات تلفنی پاسخ‌داده‌شده: {stats['phone_count']}",
        f"💬 سؤالات پیام/پیامکی پاسخ‌داده‌شده: {stats['message_count']}",
    ]

    if stats["unknown_count"]:
        lines.append(f"❔ نوع ارتباط نامشخص: {stats['unknown_count']}")

    lines.append(
        f"✅ مجموع سؤالات مخاطبان که پاسخ داده شد: {stats['total_count']}"
    )

    return "\n".join(lines)

def split_message(text: str, limit: int = 3900):
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        cut = text.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit

        chunks.append(text[:cut])
        text = text[cut:].lstrip()

    return chunks

def send_bale_message(text: str):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"

    for chunk in split_message(text):
        body = json.dumps(
            {"chat_id": BALE_CHAT_ID, "text": chunk},
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok") is not True:
            fail("Bale rejected report message: " + str(result))

        time.sleep(1)

def send_bale_transcript_file(info):
    if not TRANSCRIPT_FILE.exists():
        fail("Transcript TXT file does not exist.")

    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendDocument"

    upload_name = (
        "velayat_transcript_"
        f"{jalali_date_for_today().replace('/', '-')}_"
        f"{info['start'].replace(':', '-')}.txt"
    )

    caption = (
        f"📄 متن کامل پیاده‌شده برنامه «{info['program']}»\n"
        f"🗓 {jalali_date_for_today()} | "
        f"🕒 {info['start']} تا {info['end']}"
    )

    with TRANSCRIPT_FILE.open("rb") as handle:
        response = requests.post(
            url,
            data={
                "chat_id": BALE_CHAT_ID,
                "caption": caption,
            },
            files={
                "document": (
                    upload_name,
                    handle,
                    "text/plain; charset=utf-8",
                )
            },
            timeout=180,
        )

    try:
        result = response.json()
    except Exception:
        fail(
            f"Bale sendDocument returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    if response.status_code != 200 or result.get("ok") is not True:
        fail("Bale rejected transcript TXT: " + str(result))

def update_bot_status(report_id: str, status: str):
    try:
        post_to_sheet({
            "secret": WEBHOOK_SECRET,
            "report_id": report_id,
            "update_only": True,
            "bot_status": status,
        })
    except Exception as exc:
        print(f"Could not update BOT_STATUS: {exc}", file=sys.stderr)

def send_bale_error(message: str):
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return

    try:
        url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
        text = (
            "⚠️ خطای سامانه رصد شبکه ولایت\n\n"
            f"{message}\n\nRun ID: {GITHUB_RUN_ID}"
        )

        body = json.dumps(
            {"chat_id": BALE_CHAT_ID, "text": text[:3900]},
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )

        urllib.request.urlopen(req, timeout=20).read()

    except Exception:
        pass

def main():
    check_required_settings()
    info = get_program_info()

    print(
        f"Loading local Whisper model: {WHISPER_MODEL_NAME} "
        f"(compute={WHISPER_COMPUTE_TYPE})..."
    )
    whisper_model = WhisperModel(
        WHISPER_MODEL_NAME,
        device="cpu",
        compute_type=WHISPER_COMPUTE_TYPE,
        cpu_threads=4,
        num_workers=1,
    )
    print("Local Whisper model is ready.")

    wait_until_start(info)

    now = datetime.now(TEHRAN)
    remaining = int((info["end_dt"] - now).total_seconds())

    if remaining <= 0:
        fail("No recording time remains for this program.")

    capture_seconds = min(remaining, MAX_CAPTURE_SECONDS)

    media_url = resolve_stream_url(STREAM_URL)

    transcript = capture_and_transcribe_local(
        whisper_model,
        media_url,
        capture_seconds,
    )

    client = genai.Client(api_key=GEMINI_API_KEY)

    analysis, used_model = analyze_transcript_with_retry(
        client,
        transcript,
        info,
    )

    stats = build_stats(analysis)

    REPORT_FILE.write_text(
        json.dumps(
            {
                "date": jalali_date_for_today(),
                "day": info["day"],
                "program": info["program"],
                "expert": analysis.expert,
                "topic": analysis.topic,
                "summary": analysis.summary,
                "key_points": analysis.key_points,
                "statistics": stats,
                "analysis_model": used_model,
                "transcription_engine": (
                    f"faster-whisper/{WHISPER_MODEL_NAME}/cpu-int8"
                ),
                "audience_questions": answered_questions_payload(analysis),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    payload = make_report_payload(
        info,
        analysis,
        stats,
        used_model,
        "PENDING",
    )

    post_to_sheet(payload)

    try:
        send_bale_message(format_bale_message(info, analysis, stats))
        send_bale_transcript_file(info)
        update_bot_status(payload["report_id"], "SENT")
    except Exception:
        update_bot_status(payload["report_id"], "FAILED")
        raise

    print("VELAYAT LIVE MONITOR v3.7 LOCAL WHISPER: SUCCESS")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        send_bale_error(str(exc))
        raise
