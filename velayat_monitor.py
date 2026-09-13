import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
import requests
from google import genai
from google.genai import types
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

# One official program is 60 minutes.
MAX_CAPTURE_SECONDS = 3595

# Gemini Live Transcribe supports up to 10 minutes per session.
# We rotate safely at 9 minutes:
# one 60-minute program => normally 7 Live sessions.
LIVE_MODEL = "gemini-3.5-transcribe-live"
LIVE_SESSION_SECONDS = 9 * 60

# Raw PCM: mono, 16-bit, 16kHz.
PCM_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2
PCM_CHUNK_MS = 100
PCM_CHUNK_BYTES = int(
    PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE * (PCM_CHUNK_MS / 1000)
)
LIVE_SESSION_MAX_CHUNKS = int(
    LIVE_SESSION_SECONDS * 1000 / PCM_CHUNK_MS
)

# One retry per session if WebSocket/Live API fails.
# Keeping this small also avoids unnecessarily consuming Live session quota.
LIVE_SESSION_MAX_ATTEMPTS = 2

# Analysis fallbacks. These are separate from the Live Transcribe model.
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
        description="نام مخاطب فقط اگر صریحاً گفته شده؛ وگرنه «نامشخص»"
    )
    question: str
    answer_summary: str


class ProgramAnalysis(BaseModel):
    expert: str = Field(
        description="نام کارشناس فقط اگر از متن روشن است؛ وگرنه «نامشخص»"
    )
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
        fail(
            f"Invalid PROGRAM_SLOT={PROGRAM_SLOT}. "
            "Allowed values: 18:00, 19:30, 21:00"
        )


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
    return now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )


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

    if now < start_dt:
        wait_seconds = int((start_dt - now).total_seconds())
        print(
            f"Runner آماده است؛ {wait_seconds} ثانیه تا شروع رسمی "
            f"{start_s} تهران منتظر می‌ماند..."
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
    if "youtube.com" not in url.lower() and "youtu.be" not in url.lower():
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


async def start_ffmpeg_pcm(media_url: str, capture_seconds: int):
    """
    FFmpeg خروجی خام PCM 16kHz/mono/s16le را مستقیم به Python می‌دهد.
    هیچ فایل صوتی دائمی ساخته نمی‌شود.
    """
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
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
        str(PCM_SAMPLE_RATE),
        "-acodec",
        "pcm_s16le",
        "-f",
        "s16le",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    if process.stdout is None:
        fail("FFmpeg stdout pipe was not created.")

    return process


async def pcm_producer(process, queue: asyncio.Queue):
    """
    صدای زنده را پیوسته از FFmpeg می‌خواند و در صف قرار می‌دهد.
    این صف باعث می‌شود هنگام تعویض Session چند ثانیه صدا از دست نرود.
    """
    buffer = bytearray()

    try:
        while True:
            data = await process.stdout.read(8192)

            if not data:
                break

            buffer.extend(data)

            while len(buffer) >= PCM_CHUNK_BYTES:
                chunk = bytes(buffer[:PCM_CHUNK_BYTES])
                del buffer[:PCM_CHUNK_BYTES]
                await queue.put(chunk)

        if buffer:
            await queue.put(bytes(buffer))

    finally:
        return_code = await process.wait()

        if return_code != 0:
            await queue.put(
                RuntimeError(
                    f"FFmpeg live capture ended with code {return_code}."
                )
            )

        await queue.put(None)


def write_transcript(parts: list[str]):
    text = "\n\n".join(
        part.strip()
        for part in parts
        if part and part.strip()
    ).strip()

    TRANSCRIPT_FILE.write_text(text, encoding="utf-8")


async def receive_live_transcripts(session, temp_parts: list[str]):
    """
    فقط input_transcription نهایی را نگه می‌داریم.
    interim برای جلوگیری از تکرار داخل TXT ذخیره نمی‌شود.
    """
    async for response in session.receive():
        content = response.server_content

        if not content:
            continue

        final_item = content.input_transcription

        if final_item and final_item.text:
            text = final_item.text.strip()

            if text:
                temp_parts.append(text)
                print(f"[Live Final] {text[:180]}")


async def run_one_live_session(
    client: genai.Client,
    queue: asyncio.Queue,
    session_number: int,
    already_buffered: list[bytes] | None = None,
    end_already_seen: bool = False,
):
    """
    یک Session حداکثر 9 دقیقه‌ای.

    در Retry:
    - صوت همان Session از buffer دوباره فرستاده می‌شود.
    - متن Attempt ناموفق Commit نمی‌شود تا تکراری ایجاد نشود.
    """
    session_audio = list(already_buffered or [])
    end_seen = end_already_seen
    last_error = None

    for attempt in range(1, LIVE_SESSION_MAX_ATTEMPTS + 1):
        temp_parts: list[str] = []

        try:
            print(
                f"Opening Live Transcribe session {session_number} "
                f"(attempt {attempt}/{LIVE_SESSION_MAX_ATTEMPTS})..."
            )

            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(
                    language_codes=["fa-IR"],
                    custom_vocabulary=CUSTOM_VOCABULARY,
                    mode="SMART",
                ),
            )

            async with client.aio.live.connect(
                model=LIVE_MODEL,
                config=config,
            ) as session:
                receiver_task = asyncio.create_task(
                    receive_live_transcripts(
                        session,
                        temp_parts,
                    )
                )

                try:
                    # در Retry، صوتی که قبلاً در همین Session مصرف شده
                    # با سرعت واقعی دوباره ارسال می‌شود.
                    replay_count = len(session_audio)

                    if replay_count:
                        print(
                            f"Replaying {replay_count} buffered PCM chunks "
                            f"for session {session_number}..."
                        )

                    for chunk in session_audio[:replay_count]:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=chunk,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                        await asyncio.sleep(PCM_CHUNK_MS / 1000)

                    # اگر Session از قبل به پایان فایل نرسیده، ادامه صوت زنده
                    # از queue گرفته می‌شود.
                    while (
                        len(session_audio) < LIVE_SESSION_MAX_CHUNKS
                        and not end_seen
                    ):
                        item = await queue.get()

                        if item is None:
                            end_seen = True
                            break

                        if isinstance(item, Exception):
                            raise item

                        session_audio.append(item)

                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=item,
                                mime_type="audio/pcm;rate=16000",
                            )
                        )

                    # پایان این قطعه/Session را به Gemini اعلام می‌کنیم.
                    await session.send_realtime_input(
                        audio_stream_end=True
                    )

                    # چند ثانیه برای Final transcription باقی‌مانده.
                    try:
                        await asyncio.wait_for(
                            receiver_task,
                            timeout=8,
                        )
                    except asyncio.TimeoutError:
                        receiver_task.cancel()
                        try:
                            await receiver_task
                        except asyncio.CancelledError:
                            pass

                except Exception:
                    receiver_task.cancel()
                    try:
                        await receiver_task
                    except BaseException:
                        pass
                    raise

            # Session با موفقیت تمام شد.
            print(
                f"Live session {session_number} completed; "
                f"{len(temp_parts)} finalized transcript segments received."
            )

            return {
                "audio": session_audio,
                "end_seen": end_seen,
                "texts": temp_parts,
            }

        except Exception as exc:
            last_error = exc
            print(
                f"Live session {session_number} attempt {attempt} failed: {exc}",
                file=sys.stderr,
            )

            if attempt < LIVE_SESSION_MAX_ATTEMPTS:
                wait_seconds = 20
                print(
                    f"Retrying Live session {session_number} "
                    f"after {wait_seconds}s..."
                )
                await asyncio.sleep(wait_seconds)

    raise RuntimeError(
        f"Live Transcribe session {session_number} failed after "
        f"{LIVE_SESSION_MAX_ATTEMPTS} attempts. Last error: {last_error}"
    )


async def transcribe_live_program(
    client: genai.Client,
    media_url: str,
    capture_seconds: int,
):
    """
    از ابتدا تا انتهای برنامه:
    FFmpeg -> PCM زنده -> Gemini Live Transcribe

    Sessionها 9 دقیقه‌ای هستند تا از سقف 10 دقیقه عبور نکنیم.
    یک ساعت معمولاً در 7 Session تمام می‌شود.
    """
    queue = asyncio.Queue()

    process = await start_ffmpeg_pcm(
        media_url,
        capture_seconds,
    )

    producer_task = asyncio.create_task(
        pcm_producer(process, queue)
    )

    all_transcript_parts: list[str] = []
    session_number = 1
    end_seen = False

    try:
        while not end_seen:
            result = await run_one_live_session(
                client=client,
                queue=queue,
                session_number=session_number,
            )

            all_transcript_parts.extend(result["texts"])
            end_seen = result["end_seen"]

            # بعد از هر Session متن روی دیسک ذخیره می‌شود.
            write_transcript(all_transcript_parts)

            print(
                f"Transcript checkpoint saved after session {session_number}."
            )

            session_number += 1

        await producer_task

    except Exception:
        if process.returncode is None:
            process.kill()
            await process.wait()

        if not producer_task.done():
            producer_task.cancel()

        try:
            await producer_task
        except BaseException:
            pass

        # هر مقداری که تا اینجا موفق بوده حفظ می‌شود.
        write_transcript(all_transcript_parts)
        raise

    transcript = TRANSCRIPT_FILE.read_text(
        encoding="utf-8"
    ).strip()

    if not transcript:
        fail("Live Transcribe returned an empty transcript.")

    print(
        f"Live transcription complete: "
        f"{len(transcript)} characters, "
        f"{session_number - 1} sessions."
    )

    return transcript


def analysis_prompt(transcript: str, info) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوای برنامه‌های زنده شبکه جهانی ولایت.

نام برنامه طبق کنداکتور رسمی: {info["program"]}
روز: {info["day"]}
زمان رسمی برنامه: {info["start"]} تا {info["end"]} به وقت تهران

وظیفه:
از متن کامل پیاده‌شده، گزارش محتوایی دقیق برنامه و سؤال‌های مخاطبان را استخراج کن.

قواعد:
1. فقط از همین متن استفاده کن و چیزی را حدس نزن.
2. summary باید مهم‌ترین استدلال‌ها، توضیحات، پاسخ‌ها و نتیجه‌گیری‌ها را پوشش دهد.
3. key_points پنج تا هشت محور اصلی و غیرتکراری باشند.
4. فقط سؤال مخاطبانی را ثبت کن که واقعاً مطرح شده و کارشناس به آن پاسخ داده است.
5. سؤال مجری را سؤال مخاطب حساب نکن.
6. source_type:
   - phone: تماس تلفنی یا پشت خط بودن روشن است.
   - message: پیام/پیامک روشن است.
   - unknown: مخاطب روشن است ولی نوع ارتباط روشن نیست.
7. نام مخاطب فقط اگر صریحاً گفته شده؛ وگرنه «نامشخص».
8. برای هر سؤال، خلاصه دقیق پاسخ کارشناس را بنویس.
9. هیچ بخش مستقلی با عنوان «شبهات» تولید نکن.
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
        for attempt, delay in enumerate(
            ANALYSIS_RETRY_DELAYS,
            start=1,
        ):
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

                return (
                    ProgramAnalysis.model_validate_json(raw),
                    model,
                )

            except Exception as exc:
                errors.append(
                    f"{model} attempt {attempt}: {exc}"
                )
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
    return [
        item.model_dump()
        for item in analysis.audience_questions
    ]


def make_report_payload(
    info,
    analysis,
    stats,
    analysis_model,
    bot_status,
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
        "answered_questions": answered_questions_payload(
            analysis
        ),
        "questions": [
            item.question
            for item in analysis.audience_questions
        ],
        "analysis_model": analysis_model,
        "status": "COMPLETED",
        "bot_status": bot_status,
    }


def post_to_sheet(payload):
    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=45,
    ) as response:
        result = json.loads(
            response.read().decode("utf-8")
        )

    if result.get("ok") is not True:
        fail(
            "Google Sheet webhook rejected report: "
            + str(result)
        )

    return result


def source_label(source_type: str) -> str:
    return {
        "phone": "تلفنی",
        "message": "پیام/پیامک",
        "unknown": "نوع ارتباط نامشخص",
    }.get(source_type, "نامشخص")


def format_bale_message(
    info,
    analysis: ProgramAnalysis,
    stats,
) -> str:
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

        for i, item in enumerate(
            analysis.key_points,
            1,
        ):
            lines.append(f"{i}. {item}")

    if analysis.audience_questions:
        lines += [
            "",
            "❓ سؤالات مخاطبان و چکیده پاسخ کارشناس:",
        ]

        for i, item in enumerate(
            analysis.audience_questions,
            1,
        ):
            audience = (
                f" – {item.audience_name}"
                if item.audience_name != "نامشخص"
                else ""
            )

            lines.append(
                f"{i}. "
                f"[{source_label(item.source_type)}{audience}] "
                f"{item.question}"
            )
            lines.append(
                f"   ↳ پاسخ: {item.answer_summary}"
            )

    else:
        lines += [
            "",
            "❓ سؤالات مخاطبان:",
            "در این برنامه سؤال پاسخ‌داده‌شده‌ای از مخاطبان شناسایی نشد.",
        ]

    # آمار مخاطبان طبق درخواست کاربر در انتهای پیام.
    lines += [
        "",
        "📊 آمار مخاطبان:",
        (
            "☎️ سؤالات تلفنی پاسخ‌داده‌شده: "
            f"{stats['phone_count']}"
        ),
        (
            "💬 سؤالات پیام/پیامکی پاسخ‌داده‌شده: "
            f"{stats['message_count']}"
        ),
    ]

    if stats["unknown_count"]:
        lines.append(
            "❔ نوع ارتباط نامشخص: "
            f"{stats['unknown_count']}"
        )

    lines.append(
        "✅ مجموع سؤالات مخاطبان که پاسخ داده شد: "
        f"{stats['total_count']}"
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
    url = (
        f"https://tapi.bale.ai/"
        f"bot{BALE_BOT_TOKEN}/sendMessage"
    )

    for chunk in split_message(text):
        body = json.dumps(
            {
                "chat_id": BALE_CHAT_ID,
                "text": chunk,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8"
            },
            method="POST",
        )

        with urllib.request.urlopen(
            req,
            timeout=30,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

        if result.get("ok") is not True:
            fail(
                "Bale rejected report message: "
                + str(result)
            )

        time.sleep(1)


def send_bale_transcript_file(info):
    if not TRANSCRIPT_FILE.exists():
        fail("Transcript TXT file does not exist.")

    url = (
        f"https://tapi.bale.ai/"
        f"bot{BALE_BOT_TOKEN}/sendDocument"
    )

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
            f"Bale sendDocument returned "
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    if (
        response.status_code != 200
        or result.get("ok") is not True
    ):
        fail(
            "Bale rejected transcript TXT: "
            + str(result)
        )


def update_bot_status(
    report_id: str,
    status: str,
):
    try:
        post_to_sheet({
            "secret": WEBHOOK_SECRET,
            "report_id": report_id,
            "update_only": True,
            "bot_status": status,
        })
    except Exception as exc:
        print(
            f"Could not update BOT_STATUS: {exc}",
            file=sys.stderr,
        )


def send_bale_error(message: str):
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return

    try:
        url = (
            f"https://tapi.bale.ai/"
            f"bot{BALE_BOT_TOKEN}/sendMessage"
        )

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

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8"
            },
            method="POST",
        )

        urllib.request.urlopen(
            req,
            timeout=20,
        ).read()

    except Exception:
        pass


def main():
    check_required_settings()
    info = get_program_info()

    now = datetime.now(TEHRAN)
    remaining = int(
        (info["end_dt"] - now).total_seconds()
    )

    if remaining <= 0:
        fail("No recording time remains for this program.")

    capture_seconds = min(
        remaining,
        MAX_CAPTURE_SECONDS,
    )

    print(
        f"Starting LIVE transcription for "
        f"«{info['program']}»; "
        f"capture_seconds={capture_seconds}"
    )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    media_url = resolve_stream_url(
        STREAM_URL
    )

    # تفاوت اصلی v3.6:
    # Transcribe همزمان با پخش/ضبط انجام می‌شود.
    transcript = asyncio.run(
        transcribe_live_program(
            client=client,
            media_url=media_url,
            capture_seconds=capture_seconds,
        )
    )

    # بعد از پایان برنامه فقط تحلیل نهایی باقی می‌ماند.
    analysis, used_model = (
        analyze_transcript_with_retry(
            client,
            transcript,
            info,
        )
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
                "transcription_model": LIVE_MODEL,
                "audience_questions": (
                    answered_questions_payload(
                        analysis
                    )
                ),
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
        send_bale_message(
            format_bale_message(
                info,
                analysis,
                stats,
            )
        )

        send_bale_transcript_file(info)

        update_bot_status(
            payload["report_id"],
            "SENT",
        )

    except Exception:
        update_bot_status(
            payload["report_id"],
            "FAILED",
        )
        raise

    print(
        "VELAYAT LIVE MONITOR "
        "v3.6 LIVE TRANSCRIBE: SUCCESS"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            f"FATAL ERROR: {exc}",
            file=sys.stderr,
        )
        send_bale_error(str(exc))
        raise
