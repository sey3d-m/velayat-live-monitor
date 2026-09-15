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
TIMED_TRANSCRIPT_FILE = Path("program_transcript_timed.txt")
REPORT_FILE = Path("program_report.json")

MAX_CAPTURE_SECONDS = 3595
LIVE_MODEL = "gemini-3.5-transcribe-live"
LIVE_SESSION_SECONDS = 9 * 60
PCM_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2
PCM_CHUNK_MS = 100
PCM_CHUNK_BYTES = int(PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE * (PCM_CHUNK_MS / 1000))
LIVE_SESSION_MAX_CHUNKS = int(LIVE_SESSION_SECONDS * 1000 / PCM_CHUNK_MS)
LIVE_SESSION_MAX_ATTEMPTS = 2

ANALYSIS_MODELS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
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
    "شبکه جهانی ولایت","زمزم احکام","آفتاب و سایه ها","آفتاب و سایه‌ها",
    "پرسمان اعتقادی","امت اسلام","بیان امیر","فائزون","فرکانس تاریکی",
    "پرسمان مذاهب","کانون مهر","پیام تاریخ","پرسمان قرآنی","چراغ",
    "پرسمان تاریخی","گامی به سوی ظهور","حیات قرآنی","اهل بیت","اهل‌بیت",
    "امیرالمؤمنین","حضرت زهرا","امام زمان","حضرت مهدی","مهدویت","شیعه",
    "اهل سنت","اهل‌سنت","قرآن کریم","نهج البلاغه","نهج‌البلاغه",
]

class TimedText(BaseModel):
    text: str
    start_sec: int
    end_sec: int

class AudienceQuestion(BaseModel):
    source_type: Literal["phone", "message", "unknown"]
    audience_name: str
    question: str
    answer_summary: str
    start_sec: int
    end_sec: int

class KeyPoint(BaseModel):
    title: str
    start_sec: int
    end_sec: int

class ViralClip(BaseModel):
    media_title: str
    angle: str
    why_viral: str
    start_sec: int
    end_sec: int
    priority: Literal["high", "medium", "low"]

class ContentIssue(BaseModel):
    status: Literal["اشکال روشن", "نیازمند بررسی", "ضعف در پاسخ"]
    issue: str
    start_sec: int
    end_sec: int

class HostIssue(BaseModel):
    issue_type: Literal[
        "ورود بیش از حد","سؤال نابجا","قطع سخن کارشناس",
        "طولانی‌گویی","القای پاسخ","تکرار غیرضروری","سایر"
    ]
    note: str
    start_sec: int
    end_sec: int

class ProgramAnalysis(BaseModel):
    host: str = Field(
        description="نام مجری فقط اگر از متن روشن است؛ وگرنه «نامشخص»"
    )
    expert: str
    program_title: str = Field(
        description="تیتر کلی و رسانه‌ای برای کل برنامه؛ کوتاه، دقیق و غیرتحریف‌آمیز"
    )
    topic: str
    hashtags: list[str]
    summary: str
    key_points: list[KeyPoint]
    audience_questions: list[AudienceQuestion]
    viral_clips: list[ViralClip]
    expert_content_review: list[ContentIssue]
    host_review: list[HostIssue]

def fail(message: str):
    print(f"ERROR: {message}", file=sys.stderr)
    raise RuntimeError(message)

def check_required_settings():
    missing = []
    for name, value in [
        ("STREAM_URL", STREAM_URL),("GEMINI_API_KEY", GEMINI_API_KEY),
        ("SHEETS_WEBHOOK_URL", SHEETS_WEBHOOK_URL),("WEBHOOK_SECRET", WEBHOOK_SECRET),
        ("BALE_BOT_TOKEN", BALE_BOT_TOKEN),("BALE_CHAT_ID", BALE_CHAT_ID),
        ("PROGRAM_SLOT", PROGRAM_SLOT),
    ]:
        if not value:
            missing.append(name)
    if missing:
        fail("Missing required settings/secrets: " + ", ".join(missing))
    if PROGRAM_SLOT not in SLOTS:
        fail(f"Invalid PROGRAM_SLOT={PROGRAM_SLOT}. Allowed values: 18:00, 19:30, 21:00")

def persian_day_name(dt: datetime) -> str:
    return {0:"دوشنبه",1:"سه شنبه",2:"چهارشنبه",3:"پنجشنبه",4:"جمعه",5:"شنبه",6:"یکشنبه"}[dt.weekday()]

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
        fail(f"نوبت {PROGRAM_SLOT} مربوط به «{PROGRAMS[day][PROGRAM_SLOT]}» است، اما اجرا بعد از پایان رسمی برنامه ({end_s}) آغاز شده است.")
    if now < start_dt:
        wait_seconds = int((start_dt - now).total_seconds())
        print(f"Runner آماده است؛ {wait_seconds} ثانیه تا شروع رسمی {start_s} تهران منتظر می‌ماند...")
        time.sleep(wait_seconds)
    return {"day":day,"slot":PROGRAM_SLOT,"start":start_s,"end":end_s,"start_dt":start_dt,"end_dt":end_dt,"program":PROGRAMS[day][PROGRAM_SLOT]}

def resolve_stream_url(url: str) -> str:
    if "youtube.com" not in url.lower() and "youtu.be" not in url.lower():
        return url
    last_error = ""
    for attempt in range(1, 6):
        result = subprocess.run(
            ["yt-dlp","--no-playlist","-f","bestaudio/best","-g",url],
            capture_output=True,text=True,check=False
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

def sec_to_hhmmss(sec: int) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def clean_hashtag(tag: str) -> str:
    tag = tag.strip().replace(" ", "_")
    return tag if tag.startswith("#") else "#" + tag

async def start_ffmpeg_pcm(media_url: str, capture_seconds: int):
    process = await asyncio.create_subprocess_exec(
        "ffmpeg","-nostdin","-hide_banner","-loglevel","warning",
        "-reconnect","1","-reconnect_streamed","1","-reconnect_delay_max","5",
        "-i",media_url,"-t",str(capture_seconds),"-vn","-ac","1","-ar",str(PCM_SAMPLE_RATE),
        "-acodec","pcm_s16le","-f","s16le","pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    if process.stdout is None:
        fail("FFmpeg stdout pipe was not created.")
    return process

async def pcm_producer(process, queue: asyncio.Queue):
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
            await queue.put(RuntimeError(f"FFmpeg live capture ended with code {return_code}."))
        await queue.put(None)

def write_transcripts(parts: list[TimedText]):
    plain = "\n\n".join(x.text.strip() for x in parts if x.text.strip()).strip()
    timed = "\n".join(
        f"[{sec_to_hhmmss(x.start_sec)} - {sec_to_hhmmss(x.end_sec)}] {x.text.strip()}"
        for x in parts if x.text.strip()
    ).strip()
    TRANSCRIPT_FILE.write_text(plain, encoding="utf-8")
    TIMED_TRANSCRIPT_FILE.write_text(timed, encoding="utf-8")

async def receive_live_transcripts(session, temp_parts: list[TimedText], program_monotonic_start: float):
    previous_end = max(0, int(time.monotonic() - program_monotonic_start))
    async for response in session.receive():
        content = response.server_content
        if not content:
            continue
        final_item = content.input_transcription
        if final_item and final_item.text:
            text = final_item.text.strip()
            if not text:
                continue
            end_sec = max(previous_end, int(time.monotonic() - program_monotonic_start))
            start_sec = previous_end
            temp_parts.append(TimedText(text=text,start_sec=start_sec,end_sec=end_sec))
            previous_end = end_sec
            print(f"[Live Final {sec_to_hhmmss(start_sec)}-{sec_to_hhmmss(end_sec)}] {text[:160]}")

async def run_one_live_session(client, queue, session_number, program_monotonic_start, already_buffered=None, end_already_seen=False):
    session_audio = list(already_buffered or [])
    end_seen = end_already_seen
    last_error = None

    for attempt in range(1, LIVE_SESSION_MAX_ATTEMPTS + 1):
        temp_parts = []
        try:
            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(
                    language_codes=["fa-IR"],
                    custom_vocabulary=CUSTOM_VOCABULARY,
                    mode="SMART",
                ),
            )
            async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
                receiver_task = asyncio.create_task(
                    receive_live_transcripts(session,temp_parts,program_monotonic_start)
                )
                try:
                    replay_count = len(session_audio)
                    for chunk in session_audio[:replay_count]:
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk,mime_type="audio/pcm;rate=16000")
                        )
                        await asyncio.sleep(PCM_CHUNK_MS / 1000)

                    while len(session_audio) < LIVE_SESSION_MAX_CHUNKS and not end_seen:
                        item = await queue.get()
                        if item is None:
                            end_seen = True
                            break
                        if isinstance(item, Exception):
                            raise item
                        session_audio.append(item)
                        await session.send_realtime_input(
                            audio=types.Blob(data=item,mime_type="audio/pcm;rate=16000")
                        )

                    await session.send_realtime_input(audio_stream_end=True)

                    try:
                        await asyncio.wait_for(receiver_task, timeout=8)
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

            return {"audio":session_audio,"end_seen":end_seen,"texts":temp_parts}

        except Exception as exc:
            last_error = exc
            print(f"Live session {session_number} attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < LIVE_SESSION_MAX_ATTEMPTS:
                await asyncio.sleep(20)

    raise RuntimeError(
        f"Live Transcribe session {session_number} failed after "
        f"{LIVE_SESSION_MAX_ATTEMPTS} attempts. Last error: {last_error}"
    )

async def transcribe_live_program(client, media_url, capture_seconds):
    queue = asyncio.Queue()
    program_monotonic_start = time.monotonic()
    process = await start_ffmpeg_pcm(media_url, capture_seconds)
    producer_task = asyncio.create_task(pcm_producer(process, queue))
    all_parts = []
    session_number = 1
    end_seen = False

    try:
        while not end_seen:
            result = await run_one_live_session(
                client,queue,session_number,program_monotonic_start
            )
            all_parts.extend(result["texts"])
            end_seen = result["end_seen"]
            write_transcripts(all_parts)
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
        write_transcripts(all_parts)
        raise

    plain = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
    timed = TIMED_TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
    if not plain:
        fail("Live Transcribe returned an empty transcript.")
    return plain, timed

def analysis_prompt(timed_transcript: str, info) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوایی و سردبیر رسانه‌ای شبکه جهانی ولایت.

نام برنامه طبق کنداکتور رسمی: {info["program"]}
روز: {info["day"]}
زمان رسمی برنامه: {info["start"]} تا {info["end"]} به وقت تهران

متن زیر دارای تایم تقریبی نسبت به ابتدای برنامه است. تایم‌ها برای تدوین‌اند و ممکن است چند ثانیه خطا داشته باشند.

وظایف:
1. host: نام مجری فقط اگر از متن روشن است؛ وگرنه «نامشخص».
2. expert: نام کارشناس فقط اگر روشن است؛ وگرنه «نامشخص».
3. program_title: یک تیتر کلی رسانه‌ای برای کل برنامه بنویس؛ کوتاه، جذاب، دقیق و بدون اغراق یا تحریف.
4. topic: موضوع اصلی برنامه، کوتاه و دقیق.
5. hashtags: ۳ تا ۷ هشتگ فارسی؛ حتماً یک هشتگ نام برنامه و حداقل یک هشتگ موضوعی.
6. summary: خلاصه مباحث برنامه؛ جامع، فشرده و ناظر به کل گفت‌وگو.
7. key_points: ۵ تا ۸ محور اصلی با title و start_sec/end_sec.
8. audience_questions:
   - فقط سؤال واقعی مخاطب که پاسخ گرفته.
   - سؤال مجری را سؤال مخاطب حساب نکن.
   - source_type = phone/message/unknown.
   - نام مخاطب فقط اگر صریحاً گفته شده.
   - start_sec = شروع سؤال و end_sec = پایان پاسخ کارشناس.
9. viral_clips:
   - جدا از محورهای اصلی، ۲ تا ۵ بخش مناسب وایرال/ترند پیشنهاد کن.
   - media_title باید تیتر رسانه‌ای جذاب ولی غیرتحریف‌آمیز باشد.
   - angle و why_viral کوتاه باشند.
   - start_sec/end_sec بازه پیشنهادی تقطیع باشد.
   - ترجیحاً ۳۰ ثانیه تا ۳ دقیقه، مگر ضرورت محتوایی.
10. expert_content_review:
   - نقد کوتاه و حرفه‌ای از محتوای کارشناس، مخصوصاً پاسخ به مخاطبان.
   - «اشکال روشن» فقط وقتی خطا یا تناقض از خود متن روشن است.
   - اگر نیازمند منبع بیرونی است status = «نیازمند بررسی».
   - اگر پاسخ ناقص/مبهم است status = «ضعف در پاسخ».
   - هر مورد تایم داشته باشد.
   - اگر اشکال معناداری نیست آرایه خالی.
11. host_review:
   - فقط موارد واقعی و قابل استناد: ورود بیش از حد، سؤال نابجا، قطع سخن، طولانی‌گویی، القای پاسخ، تکرار غیرضروری.
   - هر مورد تایم داشته باشد.
   - اگر مشکل معناداری نیست آرایه خالی.
12. هیچ داوری مذهبی/تاریخی/سیاسی را بدون اطمینان به صورت «اشتباه قطعی» اعلام نکن.
13. همه خروجی‌ها فارسی باشند.

متن زمان‌دار:
--------------------
{timed_transcript}
--------------------
"""

def analyze_transcript_with_retry(client, timed_transcript, info):
    prompt = analysis_prompt(timed_transcript, info)
    errors = []

    for model in ANALYSIS_MODELS:
        for attempt, delay in enumerate(ANALYSIS_RETRY_DELAYS, start=1):
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    response_format={
                        "type":"text",
                        "mime_type":"application/json",
                        "schema":ProgramAnalysis.model_json_schema(),
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

    fail("همه تلاش‌های تحلیل Gemini ناموفق بودند. متن کامل برنامه حفظ شده است.\n" + "\n".join(errors[-6:]))

def jalali_date_for_today() -> str:
    now = datetime.now(TEHRAN)
    j = jdatetime.date.fromgregorian(date=now.date())
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"

def build_stats(analysis: ProgramAnalysis):
    phone = sum(x.source_type == "phone" for x in analysis.audience_questions)
    message = sum(x.source_type == "message" for x in analysis.audience_questions)
    unknown = sum(x.source_type == "unknown" for x in analysis.audience_questions)
    names = []
    for x in analysis.audience_questions:
        if x.audience_name and x.audience_name != "نامشخص" and x.audience_name not in names:
            names.append(x.audience_name)
    return {
        "phone_count":phone,
        "message_count":message,
        "unknown_count":unknown,
        "total_count":len(analysis.audience_questions),
        "audience_names":names,
    }

def answered_questions_payload(analysis):
    return [x.model_dump() for x in analysis.audience_questions]

def make_report_payload(info, analysis, stats, analysis_model, bot_status):
    gregorian = datetime.now(TEHRAN).strftime("%Y-%m-%d")
    report_id = f"{gregorian}_{info['start'].replace(':','')}_{info['program'].replace(' ','_')}"
    return {
        "secret":WEBHOOK_SECRET,
        "report_id":report_id,
        "date":jalali_date_for_today(),
        "day":info["day"],
        "start":info["start"],
        "end":info["end"],
        "program":info["program"],
        "host":analysis.host,
        "expert":analysis.expert,
        "program_title":analysis.program_title,
        "topic":analysis.topic,
        "summary":analysis.summary,
        "key_points":[x.model_dump() for x in analysis.key_points],
        "phone_question_count":stats["phone_count"],
        "message_question_count":stats["message_count"],
        "unknown_question_count":stats["unknown_count"],
        "total_question_count":stats["total_count"],
        "audience_names":stats["audience_names"],
        "answered_questions":answered_questions_payload(analysis),
        "questions":[x.question for x in analysis.audience_questions],
        "analysis_model":analysis_model,
        "status":"COMPLETED",
        "bot_status":bot_status,
    }

def post_to_sheet(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        SHEETS_WEBHOOK_URL,data=body,
        headers={"Content-Type":"application/json; charset=utf-8"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("ok") is not True:
        fail("Google Sheet webhook rejected report: " + str(result))
    return result

def source_label(source_type: str) -> str:
    return {"phone":"تلفنی","message":"پیام/پیامک","unknown":"نوع ارتباط نامشخص"}.get(source_type,"نامشخص")

def format_bale_part1(info, analysis: ProgramAnalysis) -> str:
    """
    بخش اول: مشخصات اصلی + خلاصه + محورهای زمان‌دار
    """
    hashtags = " ".join(clean_hashtag(x) for x in analysis.hashtags)

    lines = [
        "📌 بخش اول | خلاصه برنامه‌های زنده شبکه ولایت",
        "",
        f"🗓 تاریخ: {jalali_date_for_today()}",
        f"📺 نام برنامه: {info['program']}",
        f"📰 تیتر کلی: {analysis.program_title}",
        f"🎙 مجری: {analysis.host}",
        f"👤 کارشناس: {analysis.expert}",
        f"🕒 زمان برنامه: {info['start']} تا {info['end']} به وقت تهران",
        f"🎯 موضوع: {analysis.topic}",
        f"🏷 هشتگ‌ها: {hashtags}",
        "",
        "📝 خلاصه مباحث برنامه:",
        analysis.summary,
    ]

    if analysis.key_points:
        lines += ["", "🔹 محورهای اصلی با تایم:"]
        for i, x in enumerate(analysis.key_points, 1):
            lines.append(
                f"{i}. {x.title}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا "
                f"{sec_to_hhmmss(x.end_sec)}"
            )

    return "\n".join(lines)


def format_bale_part2(info, analysis: ProgramAnalysis, stats) -> str:
    """
    بخش دوم: سؤال‌ها + وایرال + نقد کارشناس + نقد مجری + آمار
    """
    lines = [
        "📌 بخش دوم | تحلیل تکمیلی برنامه‌های زنده شبکه ولایت",
        "",
        f"📺 برنامه: {info['program']}",
        f"📰 تیتر کلی: {analysis.program_title}",
    ]

    if analysis.audience_questions:
        lines += ["", "❓ سؤالات مخاطبان و چکیده پاسخ:"]
        for i, x in enumerate(analysis.audience_questions, 1):
            audience = (
                f" – {x.audience_name}"
                if x.audience_name != "نامشخص"
                else ""
            )
            lines.append(
                f"{i}. [{source_label(x.source_type)}{audience}] "
                f"{x.question}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا "
                f"{sec_to_hhmmss(x.end_sec)}\n"
                f"   ↳ پاسخ: {x.answer_summary}"
            )
    else:
        lines += [
            "",
            "❓ سؤالات مخاطبان:",
            "در این برنامه سؤال پاسخ‌داده‌شده‌ای از مخاطبان شناسایی نشد.",
        ]

    if analysis.viral_clips:
        lines += ["", "🚀 پیشنهادهای وایرال و تقطیع رسانه‌ای:"]
        for i, x in enumerate(analysis.viral_clips, 1):
            priority = {
                "high": "بالا",
                "medium": "متوسط",
                "low": "پایین",
            }.get(x.priority, x.priority)

            lines.append(
                f"{i}. «{x.media_title}»\n"
                f"   🎬 سوژه: {x.angle}\n"
                f"   ⏱ تقطیع: {sec_to_hhmmss(x.start_sec)} تا "
                f"{sec_to_hhmmss(x.end_sec)}\n"
                f"   📈 ظرفیت وایرال: {priority} — {x.why_viral}"
            )
    else:
        lines += [
            "",
            "🚀 پیشنهادهای وایرال:",
            "بخش شاخصی با ظرفیت واضح برای تقطیع وایرال شناسایی نشد.",
        ]

    lines += ["", "🧠 ارزیابی کوتاه محتوای کارشناس:"]
    if analysis.expert_content_review:
        for i, x in enumerate(analysis.expert_content_review, 1):
            lines.append(
                f"{i}. [{x.status}] {x.issue}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا "
                f"{sec_to_hhmmss(x.end_sec)}"
            )
    else:
        lines.append(
            "اشکال محتوایی معناداری در متن شناسایی نشد."
        )

    lines += ["", "🎙 ارزیابی کوتاه اجرای مجری:"]
    if analysis.host_review:
        for i, x in enumerate(analysis.host_review, 1):
            lines.append(
                f"{i}. [{x.issue_type}] {x.note}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا "
                f"{sec_to_hhmmss(x.end_sec)}"
            )
    else:
        lines.append(
            "مورد معناداری از ورود نامناسب، سؤال نابجا یا طولانی‌گویی مجری شناسایی نشد."
        )

    lines += [
        "",
        "📊 آمار مخاطبان:",
        f"☎️ سؤالات تلفنی پاسخ‌داده‌شده: {stats['phone_count']}",
        f"💬 سؤالات پیام/پیامکی پاسخ‌داده‌شده: {stats['message_count']}",
    ]

    if stats["unknown_count"]:
        lines.append(
            f"❔ نوع ارتباط نامشخص: {stats['unknown_count']}"
        )

    lines.append(
        f"✅ مجموع سؤالات مخاطبان که پاسخ داده شد: "
        f"{stats['total_count']}"
    )

    return "\n".join(lines)


def split_message(text: str, limit: int = 3900):
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n",0,limit)
        if cut < 1000:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    return chunks

def send_bale_message(text: str):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
    for chunk in split_message(text):
        body = json.dumps({"chat_id":BALE_CHAT_ID,"text":chunk},ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,data=body,
            headers={"Content-Type":"application/json; charset=utf-8"},
            method="POST"
        )
        with urllib.request.urlopen(req,timeout=30) as response:
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
        f"{jalali_date_for_today().replace('/','-')}_"
        f"{info['start'].replace(':','-')}.txt"
    )
    caption = (
        f"📄 متن کامل پیاده‌شده برنامه «{info['program']}»\n"
        f"🗓 {jalali_date_for_today()} | 🕒 {info['start']} تا {info['end']}"
    )
    with TRANSCRIPT_FILE.open("rb") as handle:
        response = requests.post(
            url,data={"chat_id":BALE_CHAT_ID,"caption":caption},
            files={"document":(upload_name,handle,"text/plain; charset=utf-8")},
            timeout=180,
        )
    try:
        result = response.json()
    except Exception:
        fail(f"Bale sendDocument returned HTTP {response.status_code}: {response.text[:500]}")
    if response.status_code != 200 or result.get("ok") is not True:
        fail("Bale rejected transcript TXT: " + str(result))

def update_bot_status(report_id: str, status: str):
    try:
        post_to_sheet({
            "secret":WEBHOOK_SECRET,
            "report_id":report_id,
            "update_only":True,
            "bot_status":status,
        })
    except Exception as exc:
        print(f"Could not update BOT_STATUS: {exc}", file=sys.stderr)

def send_bale_error(message: str):
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return
    try:
        url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
        text = f"⚠️ خطای سامانه رصد شبکه ولایت\n\n{message}\n\nRun ID: {GITHUB_RUN_ID}"
        body = json.dumps({"chat_id":BALE_CHAT_ID,"text":text[:3900]},ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,data=body,
            headers={"Content-Type":"application/json; charset=utf-8"},
            method="POST"
        )
        urllib.request.urlopen(req,timeout=20).read()
    except Exception:
        pass

def main():
    check_required_settings()
    info = get_program_info()

    now = datetime.now(TEHRAN)
    remaining = int((info["end_dt"] - now).total_seconds())
    if remaining <= 0:
        fail("No recording time remains for this program.")
    capture_seconds = min(remaining,MAX_CAPTURE_SECONDS)

    client = genai.Client(api_key=GEMINI_API_KEY)
    media_url = resolve_stream_url(STREAM_URL)

    transcript, timed_transcript = asyncio.run(
        transcribe_live_program(client,media_url,capture_seconds)
    )

    analysis, used_model = analyze_transcript_with_retry(
        client,timed_transcript,info
    )
    stats = build_stats(analysis)

    REPORT_FILE.write_text(
        json.dumps({
            "date":jalali_date_for_today(),
            "day":info["day"],
            "program":info["program"],
            "host":analysis.host,
            "expert":analysis.expert,
            "program_title":analysis.program_title,
            "topic":analysis.topic,
            "hashtags":analysis.hashtags,
            "summary":analysis.summary,
            "key_points":[x.model_dump() for x in analysis.key_points],
            "statistics":stats,
            "analysis_model":used_model,
            "transcription_model":LIVE_MODEL,
            "audience_questions":answered_questions_payload(analysis),
            "viral_clips":[x.model_dump() for x in analysis.viral_clips],
            "expert_content_review":[x.model_dump() for x in analysis.expert_content_review],
            "host_review":[x.model_dump() for x in analysis.host_review],
        },ensure_ascii=False,indent=2),
        encoding="utf-8",
    )

    payload = make_report_payload(info,analysis,stats,used_model,"PENDING")
    post_to_sheet(payload)

    try:
        send_bale_message(format_bale_part1(info,analysis))
        send_bale_message(format_bale_part2(info,analysis,stats))
        send_bale_transcript_file(info)
        update_bot_status(payload["report_id"],"SENT")
    except Exception:
        update_bot_status(payload["report_id"],"FAILED")
        raise

    print("VELAYAT LIVE MONITOR v3.9 TWO-PART REPORT: SUCCESS")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        send_bale_error(str(exc))
        raise
