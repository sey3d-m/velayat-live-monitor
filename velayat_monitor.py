#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Velayat Live Monitor v4.1.1

Shared engine for Persian, Azeri, Arabic and Hausa channels.
Key design goals:
- Do not lose the recording if Gemini Live Transcribe disconnects or exhausts quota.
- Keep the existing rich Persian report.
- Produce a simpler, stricter Persian content-review report for Azeri/Arabic/Hausa.
- Keep temporary audio only on the GitHub runner and delete it after processing.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import jdatetime
import requests
from google import genai
from google.genai import types
from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Runtime constants / environment
# -----------------------------------------------------------------------------

VERSION = "4.1.1"
TEHRAN = ZoneInfo("Asia/Tehran")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "").strip()
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual").strip() or "manual"

NETWORK = os.environ.get("NETWORK", "persian").strip().lower()
PROGRAM_SLOT = os.environ.get("PROGRAM_SLOT", "").strip()
SCHEDULED_DATE = os.environ.get("SCHEDULED_DATE", "").strip()  # YYYY-MM-DD, Tehran date

# Keep backward compatibility with the existing Persian STREAM_URL secret.
PERSIAN_STREAM_URL = (
    os.environ.get("PERSIAN_STREAM_URL", "").strip()
    or os.environ.get("STREAM_URL", "").strip()
)
AZERI_STREAM_URL = os.environ.get("AZERI_STREAM_URL", "").strip()
ARABIC_STREAM_URL = os.environ.get("ARABIC_STREAM_URL", "").strip()
HAUSA_STREAM_URL = os.environ.get("HAUSA_STREAM_URL", "").strip()

TRANSCRIPT_FILE = Path("program_transcript.txt")
TIMED_TRANSCRIPT_FILE = Path("program_transcript_timed.txt")
REPORT_FILE = Path("program_report.json")
AUDIO_BACKUP_FILE = Path("program_audio_backup.flac")

# Dedicated Live Transcription model documented by Google.
LIVE_MODEL = "gemini-3.5-transcribe-live"

# Keep each session safely below the documented 10-minute Transcribe Live limit.
LIVE_SESSION_SECONDS = 8 * 60 + 30
LIVE_BACKOFF_SECONDS = [30, 60, 120, 240]
MAX_LIVE_FAILURES_BEFORE_DISABLE = len(LIVE_BACKOFF_SECONDS) + 1
LIVE_RECEIVER_DRAIN_SECONDS = 8

PCM_SAMPLE_RATE = 16000
PCM_BYTES_PER_SAMPLE = 2
PCM_CHUNK_MS = 100
PCM_CHUNK_BYTES = int(
    PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE * (PCM_CHUNK_MS / 1000)
)

# Bounded queue is deliberate: Gemini may be unavailable for minutes. We never
# allow a blocked network consumer to stall FFmpeg and the backup recording.
LIVE_QUEUE_MAX_CHUNKS = 3600  # about 6 minutes of 100 ms chunks (~11.5 MB)

# Analysis hotfix v4.1.1:
# Use high-throughput Flash-Lite models and at most one request per model.
# This preserves the existing report schemas/prompts while preventing a single
# program from generating up to 12 full-transcript analysis requests.
# The two model quotas are separate enough that the second can act as a light
# fallback, but we never loop aggressively when the project is rate-limited.
ANALYSIS_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
]
ANALYSIS_ATTEMPTS_PER_MODEL = 1
ANALYSIS_FALLBACK_DELAY_SECONDS = 8

# Local emergency STT. Small multilingual is chosen for CPU practicality on a
# standard GitHub-hosted runner. Override with WHISPER_MODEL if desired.
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small").strip() or "small"


# -----------------------------------------------------------------------------
# Network configuration
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class NetworkConfig:
    key: str
    label_fa: str
    language_fa: str
    bcp47: str
    whisper_language: str
    report_mode: Literal["persian_full", "international_review"]
    slots: dict[str, tuple[str, str]]
    default_stream_url: str


NETWORKS: dict[str, NetworkConfig] = {
    "persian": NetworkConfig(
        key="persian",
        label_fa="شبکه ولایت فارسی",
        language_fa="فارسی",
        bcp47="fa-IR",
        whisper_language="fa",
        report_mode="persian_full",
        slots={
            "18:00": ("18:00", "19:00"),
            "19:30": ("19:30", "20:30"),
            "21:00": ("21:00", "22:00"),
        },
        default_stream_url="",
    ),
    "azeri": NetworkConfig(
        key="azeri",
        label_fa="شبکه ولایت آذری",
        language_fa="آذری",
        bcp47="az-AZ",
        whisper_language="az",
        report_mode="international_review",
        slots={
            "16:30": ("16:30", "17:30"),
            "18:00": ("18:00", "19:00"),
        },
        default_stream_url="https://nl.livekadeh.com/hls2/vilayet.m3u8",
    ),
    "arabic": NetworkConfig(
        key="arabic",
        label_fa="شبکه ولایت عربی",
        language_fa="عربی",
        bcp47="ar-EG",
        whisper_language="ar",
        report_mode="international_review",
        slots={"21:00": ("21:00", "22:00")},
        default_stream_url="https://nl.livekadeh.com/hls2/alwilayah_tv.m3u8",
    ),
    "hausa": NetworkConfig(
        key="hausa",
        label_fa="شبکه ولایت هوسا",
        language_fa="هوسا",
        bcp47="ha-NG",
        whisper_language="ha",
        report_mode="international_review",
        # 24:00 is represented as 00:00 on the next Gregorian/Tehran day.
        slots={"22:30": ("22:30", "00:00")},
        default_stream_url="https://nl.livekadeh.com/hls2/alwilayah.tv.hausa.m3u8",
    ),
}

PERSIAN_PROGRAMS = {
    "شنبه": {
        "18:00": "زمزم احکام",
        "19:30": "آفتاب و سایه‌ها",
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
    "سه‌شنبه": {
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

PERSIAN_CUSTOM_VOCABULARY = [
    "شبکه جهانی ولایت",
    "زمزم احکام",
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
    "اهل‌بیت",
    "امیرالمؤمنین",
    "حضرت زهرا",
    "امام زمان",
    "حضرت مهدی",
    "مهدویت",
    "اهل‌سنت",
    "قرآن کریم",
    "نهج‌البلاغه",
]


# -----------------------------------------------------------------------------
# Structured models
# -----------------------------------------------------------------------------

class TimedText(BaseModel):
    text: str
    start_sec: int
    end_sec: int


@dataclass
class AudioChunk:
    data: bytes
    start_sec: float
    end_sec: float


class AudienceQuestion(BaseModel):
    source_type: Literal["phone", "message", "unknown"]
    audience_name: str = "نامشخص"
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


class PersianContentIssue(BaseModel):
    status: Literal["اشکال روشن", "نیازمند بررسی", "ضعف در پاسخ"]
    issue: str
    start_sec: int
    end_sec: int


class HostIssue(BaseModel):
    issue_type: Literal[
        "ورود بیش از حد",
        "سؤال نابجا",
        "قطع سخن کارشناس",
        "طولانی‌گویی",
        "القای پاسخ",
        "تکرار غیرضروری",
        "سایر",
    ]
    note: str
    start_sec: int
    end_sec: int


class PersianProgramAnalysis(BaseModel):
    host: str = "نامشخص"
    expert: str = "نامشخص"
    program_title: str
    topic: str
    hashtags: list[str]
    summary: str
    key_points: list[KeyPoint]
    audience_questions: list[AudienceQuestion]
    viral_clips: list[ViralClip]
    expert_content_review: list[PersianContentIssue]
    host_review: list[HostIssue]


ReviewCategory = Literal[
    "خطای factual / واقعی",
    "اشکال اعتقادی",
    "ضعف استدلال",
    "تعارض احتمالی با خط‌مشی شبکه",
    "ریسک رسانه‌ای",
    "نیازمند بررسی بیشتر",
]


class CriticalReviewIssue(BaseModel):
    category: ReviewCategory
    severity: Literal["high", "medium", "low"]
    status: Literal["اشکال روشن", "نیازمند بررسی", "ضعف در پاسخ", "ریسک محتوایی"]
    issue: str
    reason: str


class InternationalProgramAnalysis(BaseModel):
    program_name: str = Field(
        description="نام برنامه فقط اگر از متن/تیتراژ/معرفی روشن است؛ وگرنه نامشخص"
    )
    host: str = Field(
        description="نام مجری فقط اگر روشن است؛ وگرنه نامشخص"
    )
    expert: str = Field(
        description="نام کارشناس یا مهمان فقط اگر روشن است؛ وگرنه نامشخص"
    )
    program_title: str
    topic: str
    hashtags: list[str]
    summary: str
    key_points: list[str]
    content_review: list[CriticalReviewIssue]


@dataclass
class TranscriptionMeta:
    source: str
    live_failures: list[str]
    fallback_used: bool
    transcript_incomplete: bool
    queue_dropped_chunks: int
    audio_capture_seconds: int
    requested_capture_seconds: int
    ffmpeg_return_code: int | None
    note: str = ""


@dataclass
class CaptureState:
    dropped_chunks: int = 0
    produced_chunks: int = 0
    end_seen: bool = False
    last_audio_end_sec: float = 0.0
    ffmpeg_return_code: int | None = None


# -----------------------------------------------------------------------------
# Utilities / validation
# -----------------------------------------------------------------------------

def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise RuntimeError(message)


def persian_day_name(dt: datetime) -> str:
    return {
        0: "دوشنبه",
        1: "سه‌شنبه",
        2: "چهارشنبه",
        3: "پنجشنبه",
        4: "جمعه",
        5: "شنبه",
        6: "یکشنبه",
    }[dt.weekday()]


def parse_scheduled_start_date() -> date:
    if not SCHEDULED_DATE:
        return datetime.now(TEHRAN).date()
    try:
        return datetime.strptime(SCHEDULED_DATE, "%Y-%m-%d").date()
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid SCHEDULED_DATE={SCHEDULED_DATE}; expected YYYY-MM-DD"
        ) from exc


def local_datetime_for(d: date, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=TEHRAN)


def get_stream_url(cfg: NetworkConfig) -> str:
    overrides = {
        "persian": PERSIAN_STREAM_URL,
        "azeri": AZERI_STREAM_URL,
        "arabic": ARABIC_STREAM_URL,
        "hausa": HAUSA_STREAM_URL,
    }
    return overrides.get(cfg.key, "") or cfg.default_stream_url


def check_required_settings() -> NetworkConfig:
    if NETWORK not in NETWORKS:
        fail(f"Invalid NETWORK={NETWORK}. Allowed: {', '.join(NETWORKS)}")

    cfg = NETWORKS[NETWORK]

    missing = []
    for name, value in [
        ("GEMINI_API_KEY", GEMINI_API_KEY),
        ("SHEETS_WEBHOOK_URL", SHEETS_WEBHOOK_URL),
        ("WEBHOOK_SECRET", WEBHOOK_SECRET),
        ("BALE_BOT_TOKEN", BALE_BOT_TOKEN),
        ("BALE_CHAT_ID", BALE_CHAT_ID),
        ("PROGRAM_SLOT", PROGRAM_SLOT),
    ]:
        if not value:
            missing.append(name)
    if cfg.key == "persian" and not get_stream_url(cfg):
        missing.append("STREAM_URL (Persian stream)")
    if missing:
        fail("Missing required settings/secrets: " + ", ".join(missing))

    if PROGRAM_SLOT not in cfg.slots:
        fail(
            f"Invalid PROGRAM_SLOT={PROGRAM_SLOT} for {NETWORK}. "
            f"Allowed: {', '.join(cfg.slots)}"
        )

    return cfg


def get_program_info(cfg: NetworkConfig) -> dict:
    start_date = parse_scheduled_start_date()
    start_s, end_s = cfg.slots[PROGRAM_SLOT]
    start_dt = local_datetime_for(start_date, start_s)

    # Midnight-ending shows (Hausa 22:30-24:00) use 00:00 next day.
    if end_s == "00:00":
        end_dt = local_datetime_for(start_date + timedelta(days=1), end_s)
        display_end = "24:00"
    else:
        end_dt = local_datetime_for(start_date, end_s)
        display_end = end_s

    day = persian_day_name(start_dt)
    if day == "جمعه":
        fail("جمعه هیچ برنامه‌ای برای رصد تعریف نشده است.")

    now = datetime.now(TEHRAN)
    if now >= end_dt:
        fail(
            f"اجرای {NETWORK}/{PROGRAM_SLOT} بعد از پایان رسمی برنامه "
            f"({display_end}) آغاز شده است."
        )

    if now < start_dt:
        wait_seconds = int((start_dt - now).total_seconds())
        print(
            f"Runner آماده است؛ {wait_seconds} ثانیه تا شروع رسمی "
            f"{start_s} تهران منتظر می‌ماند..."
        )
        time.sleep(wait_seconds)

    if cfg.key == "persian":
        program = PERSIAN_PROGRAMS.get(day, {}).get(PROGRAM_SLOT, "نامشخص")
    else:
        program = "نامشخص"

    return {
        "network": cfg.key,
        "network_label": cfg.label_fa,
        "language": cfg.language_fa,
        "day": day,
        "scheduled_date": start_date.isoformat(),
        "slot": PROGRAM_SLOT,
        "start": start_s,
        "end": display_end,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "program": program,
    }


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
    return ""  # unreachable


def sec_to_hhmmss(sec: int | float) -> str:
    sec = max(0, int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def clean_hashtag(tag: str) -> str:
    tag = str(tag or "").strip().replace(" ", "_")
    if not tag:
        return ""
    return tag if tag.startswith("#") else "#" + tag


def jalali_date_for(d: date) -> str:
    j = jdatetime.date.fromgregorian(date=d)
    return f"{j.year:04d}/{j.month:02d}/{j.day:02d}"


def jalali_date_for_info(info: dict) -> str:
    return jalali_date_for(date.fromisoformat(info["scheduled_date"]))


def normalize_name(value: str | None) -> str:
    value = (value or "").strip()
    if not value or value.lower() in {"unknown", "n/a", "none", "null"}:
        return "نامشخص"
    return value


# -----------------------------------------------------------------------------
# FFmpeg capture: live PCM + independent local FLAC backup
# -----------------------------------------------------------------------------

async def start_ffmpeg_capture(media_url: str, capture_seconds: int):
    AUDIO_BACKUP_FILE.unlink(missing_ok=True)

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
        "-reconnect_at_eof",
        "1",
        "-reconnect_delay_max",
        "5",
        "-i",
        media_url,
        # Output 1: PCM for opportunistic Gemini Live transcription.
        "-map",
        "0:a:0",
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
        # Output 2: independent compressed local backup for recovery.
        "-map",
        "0:a:0",
        "-t",
        str(capture_seconds),
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(PCM_SAMPLE_RATE),
        "-c:a",
        "flac",
        "-y",
        str(AUDIO_BACKUP_FILE),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    if process.stdout is None:
        fail("FFmpeg stdout pipe was not created.")
    return process


def _queue_put_nonblocking(queue: asyncio.Queue, item, state: CaptureState) -> None:
    try:
        queue.put_nowait(item)
        return
    except asyncio.QueueFull:
        pass

    # Drop the oldest queued audio instead of blocking FFmpeg. The local FLAC
    # remains complete and will be used for recovery at the end.
    try:
        old = queue.get_nowait()
        if old is not None:
            state.dropped_chunks += 1
    except asyncio.QueueEmpty:
        pass

    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        if item is not None:
            state.dropped_chunks += 1


async def pcm_producer(process, queue: asyncio.Queue, state: CaptureState):
    buffer = bytearray()
    byte_cursor = 0
    try:
        while True:
            data = await process.stdout.read(8192)
            if not data:
                break
            buffer.extend(data)

            while len(buffer) >= PCM_CHUNK_BYTES:
                chunk = bytes(buffer[:PCM_CHUNK_BYTES])
                del buffer[:PCM_CHUNK_BYTES]
                start_sec = byte_cursor / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
                byte_cursor += len(chunk)
                end_sec = byte_cursor / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
                state.produced_chunks += 1
                state.last_audio_end_sec = end_sec
                _queue_put_nonblocking(
                    queue,
                    AudioChunk(data=chunk, start_sec=start_sec, end_sec=end_sec),
                    state,
                )

        if buffer:
            start_sec = byte_cursor / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
            byte_cursor += len(buffer)
            end_sec = byte_cursor / (PCM_SAMPLE_RATE * PCM_BYTES_PER_SAMPLE)
            state.produced_chunks += 1
            state.last_audio_end_sec = end_sec
            _queue_put_nonblocking(
                queue,
                AudioChunk(data=bytes(buffer), start_sec=start_sec, end_sec=end_sec),
                state,
            )
    finally:
        return_code = await process.wait()
        state.ffmpeg_return_code = return_code
        state.end_seen = True
        if return_code != 0:
            _queue_put_nonblocking(
                queue,
                RuntimeError(f"FFmpeg live capture ended with code {return_code}."),
                state,
            )
        _queue_put_nonblocking(queue, None, state)


# -----------------------------------------------------------------------------
# Gemini Live transcription (opportunistic; never owns the recording lifecycle)
# -----------------------------------------------------------------------------

class LiveTiming:
    def __init__(self) -> None:
        self.current_audio_sec = 0.0
        self.previous_final_end = 0


async def receive_live_transcripts(
    session,
    output_parts: list[TimedText],
    timing: LiveTiming,
):
    async for response in session.receive():
        content = getattr(response, "server_content", None)
        if not content:
            continue
        final_item = getattr(content, "input_transcription", None)
        text = (getattr(final_item, "text", "") or "").strip() if final_item else ""
        if not text:
            continue

        end_sec = max(timing.previous_final_end, int(timing.current_audio_sec))
        start_sec = timing.previous_final_end
        output_parts.append(
            TimedText(text=text, start_sec=start_sec, end_sec=end_sec)
        )
        timing.previous_final_end = end_sec
        print(
            f"[Live Final {sec_to_hhmmss(start_sec)}-"
            f"{sec_to_hhmmss(end_sec)}] {text[:160]}"
        )


def live_config_for(cfg: NetworkConfig):
    kwargs = {
        "language_codes": [cfg.bcp47],
        "mode": "SMART",
    }
    if cfg.key == "persian":
        kwargs["custom_vocabulary"] = PERSIAN_CUSTOM_VOCABULARY

    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(**kwargs),
    )


async def run_live_session(
    client,
    cfg: NetworkConfig,
    queue: asyncio.Queue,
    all_parts: list[TimedText],
) -> Literal["rotate", "end"]:
    session_started_audio_sec: float | None = None
    timing = LiveTiming()
    if all_parts:
        timing.previous_final_end = all_parts[-1].end_sec

    async with client.aio.live.connect(
        model=LIVE_MODEL,
        config=live_config_for(cfg),
    ) as session:
        receiver_task = asyncio.create_task(
            receive_live_transcripts(session, all_parts, timing)
        )
        result: Literal["rotate", "end"] = "rotate"
        try:
            while True:
                item = await queue.get()
                if item is None:
                    result = "end"
                    break
                if isinstance(item, Exception):
                    raise item
                if not isinstance(item, AudioChunk):
                    continue

                if session_started_audio_sec is None:
                    session_started_audio_sec = item.start_sec
                timing.current_audio_sec = item.end_sec

                await session.send_realtime_input(
                    audio=types.Blob(
                        data=item.data,
                        mime_type=f"audio/pcm;rate={PCM_SAMPLE_RATE}",
                    )
                )

                if item.end_sec - session_started_audio_sec >= LIVE_SESSION_SECONDS:
                    result = "rotate"
                    break

            try:
                await session.send_realtime_input(audio_stream_end=True)
            except Exception:
                # Closing a failed/expiring session is best-effort.
                pass

            try:
                await asyncio.wait_for(
                    receiver_task,
                    timeout=LIVE_RECEIVER_DRAIN_SECONDS,
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

    return result


async def live_transcription_consumer(
    client,
    cfg: NetworkConfig,
    queue: asyncio.Queue,
    state: CaptureState,
) -> tuple[list[TimedText], list[str], bool]:
    all_parts: list[TimedText] = []
    errors: list[str] = []
    consecutive_failures = 0
    live_disabled = False

    while True:
        if live_disabled:
            # Drain until capture ends so the bounded queue cannot retain memory.
            item = await queue.get()
            if item is None:
                break
            continue

        try:
            outcome = await run_live_session(client, cfg, queue, all_parts)
            consecutive_failures = 0
            write_transcripts(all_parts)
            if outcome == "end":
                break
        except Exception as exc:
            consecutive_failures += 1
            msg = (
                f"Live Transcribe failure {consecutive_failures}: "
                f"{type(exc).__name__}: {exc}"
            )
            errors.append(msg)
            print(msg, file=sys.stderr)
            write_transcripts(all_parts)

            if consecutive_failures >= MAX_LIVE_FAILURES_BEFORE_DISABLE:
                live_disabled = True
                print(
                    "Gemini Live disabled for the remainder of this program; "
                    "local FLAC recovery will be used.",
                    file=sys.stderr,
                )
                continue

            # Four retry delays are honored exactly: 30, 60, 120, 240 seconds.
            delay = LIVE_BACKOFF_SECONDS[consecutive_failures - 1]
            print(f"Retrying Gemini Live in {delay} seconds...", file=sys.stderr)
            await asyncio.sleep(delay)

    return all_parts, errors, live_disabled


# -----------------------------------------------------------------------------
# Transcript persistence / local recovery
# -----------------------------------------------------------------------------

def write_transcripts(parts: list[TimedText]) -> None:
    ordered = sorted(parts, key=lambda x: (x.start_sec, x.end_sec))
    plain = "\n\n".join(x.text.strip() for x in ordered if x.text.strip()).strip()
    timed = "\n".join(
        f"[{sec_to_hhmmss(x.start_sec)} - {sec_to_hhmmss(x.end_sec)}] "
        f"{x.text.strip()}"
        for x in ordered
        if x.text.strip()
    ).strip()
    TRANSCRIPT_FILE.write_text(plain, encoding="utf-8")
    TIMED_TRANSCRIPT_FILE.write_text(timed, encoding="utf-8")


def local_whisper_transcribe(cfg: NetworkConfig) -> list[TimedText]:
    if not AUDIO_BACKUP_FILE.exists() or AUDIO_BACKUP_FILE.stat().st_size < 1024:
        raise RuntimeError("Local audio backup is missing or empty.")

    print(
        f"Starting faster-whisper fallback: model={WHISPER_MODEL}, "
        f"language={cfg.whisper_language}"
    )
    from faster_whisper import WhisperModel  # lazy import; costly only on fallback

    threads = max(2, min(4, os.cpu_count() or 2))
    model = WhisperModel(
        WHISPER_MODEL,
        device="cpu",
        compute_type="int8",
        cpu_threads=threads,
    )
    segments, info = model.transcribe(
        str(AUDIO_BACKUP_FILE),
        language=cfg.whisper_language,
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True,
    )

    parts: list[TimedText] = []
    for segment in segments:
        text = (segment.text or "").strip()
        if not text:
            continue
        parts.append(
            TimedText(
                text=text,
                start_sec=max(0, int(segment.start)),
                end_sec=max(0, int(segment.end)),
            )
        )

    if not parts:
        raise RuntimeError("faster-whisper returned an empty transcript.")

    print(
        "faster-whisper completed | detected_language="
        f"{getattr(info, 'language', 'unknown')}"
    )
    return parts


async def capture_and_transcribe(
    client,
    cfg: NetworkConfig,
    media_url: str,
    capture_seconds: int,
) -> tuple[str, str, TranscriptionMeta]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=LIVE_QUEUE_MAX_CHUNKS)
    state = CaptureState()
    process = await start_ffmpeg_capture(media_url, capture_seconds)
    producer_task = asyncio.create_task(pcm_producer(process, queue, state))
    consumer_task = asyncio.create_task(
        live_transcription_consumer(client, cfg, queue, state)
    )

    live_parts: list[TimedText] = []
    live_errors: list[str] = []
    live_disabled = False
    producer_error: Exception | None = None

    try:
        try:
            await producer_task
        except Exception as exc:
            producer_error = exc
            print(f"FFmpeg producer error: {exc}", file=sys.stderr)

        try:
            live_parts, live_errors, live_disabled = await consumer_task
        except Exception as exc:
            live_errors.append(f"Live consumer fatal: {type(exc).__name__}: {exc}")
            print(live_errors[-1], file=sys.stderr)

        need_local_recovery = bool(
            live_errors
            or live_disabled
            or state.dropped_chunks
            or producer_error
            or (state.ffmpeg_return_code not in (None, 0))
            or not live_parts
        )

        final_parts = live_parts
        source = "gemini-live"
        fallback_used = False
        incomplete = False
        note_parts: list[str] = []

        if need_local_recovery:
            fallback_used = True
            try:
                # Full-file recovery is safer than attempting to splice uncertain
                # gaps from a failed WebSocket stream.
                final_parts = await asyncio.to_thread(local_whisper_transcribe, cfg)
                source = f"faster-whisper/{WHISPER_MODEL}"
                note_parts.append(
                    "Gemini Live دچار وقفه شد؛ متن نهایی از فایل صوتی موقت محلی بازسازی شد."
                )
            except Exception as exc:
                print(f"Local Whisper fallback failed: {exc}", file=sys.stderr)
                source = "gemini-live-partial"
                incomplete = True
                note_parts.append(
                    "بازیابی محلی نیز ناموفق بود و متن موجود ممکن است ناقص باشد."
                )
                if not final_parts:
                    # Preserve the run as an explicit partial result rather than
                    # silently inventing a transcript.
                    final_parts = [
                        TimedText(
                            text="⚠️ پیاده‌سازی این بخش ناقص است.",
                            start_sec=0,
                            end_sec=max(0, capture_seconds),
                        )
                    ]

        write_transcripts(final_parts)
        plain = TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()
        timed = TIMED_TRANSCRIPT_FILE.read_text(encoding="utf-8").strip()

        if not plain:
            incomplete = True
            plain = "⚠️ پیاده‌سازی این بخش ناقص است."
            timed = f"[00:00 - {sec_to_hhmmss(capture_seconds)}] {plain}"
            TRANSCRIPT_FILE.write_text(plain, encoding="utf-8")
            TIMED_TRANSCRIPT_FILE.write_text(timed, encoding="utf-8")

        actual_seconds = max(0, int(round(state.last_audio_end_sec)))
        if actual_seconds + 5 < capture_seconds:
            incomplete = True
            note_parts.append(
                f"ضبط صوت زودتر از زمان مورد انتظار پایان یافت: {actual_seconds} از {capture_seconds} ثانیه."
            )

        meta = TranscriptionMeta(
            source=source,
            live_failures=live_errors,
            fallback_used=fallback_used,
            transcript_incomplete=incomplete,
            queue_dropped_chunks=state.dropped_chunks,
            audio_capture_seconds=actual_seconds,
            requested_capture_seconds=capture_seconds,
            ffmpeg_return_code=state.ffmpeg_return_code,
            note=" ".join(note_parts).strip(),
        )
        return plain, timed, meta
    finally:
        # Keep the temporary FLAC until analysis/delivery has finished. The outer
        # main cleanup removes it, so a later failure can never publish it as an artifact.
        try:
            if process.returncode is None:
                process.kill()
                await process.wait()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Analysis prompts
# -----------------------------------------------------------------------------

def persian_analysis_prompt(timed_transcript: str, info: dict) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوایی و سردبیر رسانه‌ای شبکه جهانی ولایت.

نام برنامه طبق کنداکتور رسمی: {info['program']}
روز: {info['day']}
زمان رسمی برنامه: {info['start']} تا {info['end']} به وقت تهران

متن زیر دارای تایم تقریبی نسبت به ابتدای برنامه است. تایم‌ها برای تدوین‌اند و ممکن است چند ثانیه خطا داشته باشند.

وظایف:
1. host: نام مجری فقط اگر از متن روشن است؛ وگرنه «نامشخص».
2. expert: نام کارشناس فقط اگر روشن است؛ وگرنه «نامشخص».
3. program_title: یک تیتر کلی رسانه‌ای برای کل برنامه؛ کوتاه، دقیق و غیرتحریف‌آمیز.
4. topic: موضوع اصلی برنامه، کوتاه و دقیق.
5. hashtags: ۳ تا ۷ هشتگ فارسی؛ حتماً یک هشتگ نام برنامه و حداقل یک هشتگ موضوعی.
6. summary: خلاصه جامع و فشرده کل گفت‌وگو.
7. key_points: ۵ تا ۸ محور اصلی با title و start_sec/end_sec.
8. audience_questions:
   - فقط سؤال واقعی مخاطب که پاسخ گرفته است؛ سؤال مجری را مخاطب حساب نکن.
   - source_type = phone/message/unknown.
   - نام مخاطب فقط اگر صریحاً گفته شده؛ وگرنه «نامشخص».
   - start_sec از شروع سؤال تا end_sec پایان پاسخ کارشناس.
9. viral_clips: ۲ تا ۵ بخش مناسب تقطیع، با تیتر جذاب ولی غیرتحریف‌آمیز و بازه زمانی.
10. expert_content_review:
   - «اشکال روشن» فقط وقتی خطا/تناقض از خود متن روشن است.
   - اگر داوری به منبع بیرونی نیاز دارد، «نیازمند بررسی».
   - اگر پاسخ ناقص یا مبهم است، «ضعف در پاسخ».
   - هر مورد تایم داشته باشد؛ اگر مورد معناداری نیست آرایه خالی.
11. host_review: فقط موارد واقعی و قابل استناد مانند ورود بیش از حد، سؤال نابجا، قطع سخن، طولانی‌گویی، القای پاسخ یا تکرار غیرضروری؛ هر مورد تایم داشته باشد.
12. ادعاهای سیاسی، تاریخی یا مذهبی تأییدنشده را به عنوان واقعیت قطعی بازنویسی نکن.
13. همه خروجی‌ها فارسی باشند.

متن زمان‌دار:
--------------------
{timed_transcript}
--------------------
"""


def international_analysis_prompt(
    transcript: str,
    cfg: NetworkConfig,
    info: dict,
) -> str:
    return f"""
نقش شما: تحلیل‌گر محتوایی شبکه جهانی ولایت. زبان برنامه «{cfg.language_fa}» است، اما تمام خروجی این تحلیل باید فارسی باشد.

شبکه: {cfg.label_fa}
زمان رسمی: {info['start']} تا {info['end']} به وقت تهران

قواعد استخراج هویت برنامه:
- program_name، host و expert را فقط وقتی بنویس که از معرفی، تیتراژ یا گفت‌وگو با اطمینان مناسب قابل تشخیص است.
- اگر نام روشن نیست، دقیقاً «نامشخص» بنویس. حدس نزن.
- اسامی خاص را خراب ترجمه نکن؛ در صورت نیاز صورت اصلی را حفظ کن.

خروجی عمومی:
- یک تیتر کلی دقیق و غیرتحریف‌آمیز، موضوع اصلی، ۳ تا ۷ هشتگ فارسی، خلاصه جامع، و ۵ تا ۸ محور اصلی بدون تایم‌کد.

چارچوب ارزیابی محتوایی:
این رسانه خط‌مشی داخلی اعلام‌شده‌ای دارد که خود را رسانه‌ای شیعی امامی با رویکرد تقریب مذاهب، مرتبط با فضای رسمی جمهوری اسلامی ایران، حامی گفتمان مقاومت اسلامی و مرتبط با دفتر آیت‌الله مکارم شیرازی معرفی می‌کند. این توصیف فقط «خط‌مشی داخلی اعلام‌شده رسانه» است و نباید به عنوان اثبات صحت هیچ ادعای سیاسی، تاریخی یا مذهبی تلقی شود.

برای content_review فقط موارد مشخص و قابل توضیح را ثبت کن و برای هر مورد category، severity، status، issue و reason بده:
- صحت اعتقادی از منظر مبانی رایج امامیه اثناعشری؛ در موارد اختلافی یا نیازمند منبع، قطعی حکم نده.
- تفکیک نقد علمی مذاهب از توهین، تحقیر، تکفیر بی‌ضابطه یا ادبیات تحریک‌آمیز علیه اهل‌سنت یا مقدسات آنان.
- نسبت دادن فتوا یا سخن به آیت‌الله مکارم، مراجع، علما، اهل‌بیت یا شخصیت‌های تاریخی بدون منبع معتبر را «نیازمند بررسی» بدان.
- آیات، روایات، ترجمه‌ها و استنادهای تاریخی را تا حدی که از خود متن روشن است بررسی کن؛ اگر راستی‌آزمایی بیرونی لازم است «نیازمند بررسی» ثبت کن.
- پاسخ ناقص، مبهم یا فاقد دلیل کافی را «ضعف در پاسخ» و category «ضعف استدلال» ثبت کن.
- ادعاهای سیاسی، خبری، جنگی، نظامی، تلفات، آمار یا عملیات بدون منبع را واقعیت قطعی تلقی نکن و به عنوان «نیازمند بررسی» علامت بزن.
- همسویی یا تعارض سیاسی را فقط به صورت توصیفی با «خط‌مشی اعلام‌شده رسانه» مقایسه کن؛ همسویی را دلیل صحت و تعارض را دلیل کذب ندان.
- اطلاعات نظامی/امنیتی/عملیاتی حساس، نفرت‌پراکنی، دعوت به خشونت، تعمیم قومی/مذهبی/نژادی، اتهام خیانت/جاسوسی/کفر بدون دلیل، افشای داده خصوصی، ریسک حقوقی/حیثیتی و ادعاهای تخصصی پزشکی/علمی/اقتصادی/حقوقی بی‌منبع را به عنوان ریسک محتوایی مشخص کن.
- category فقط یکی از این شش مقدار باشد:
  1) خطای factual / واقعی
  2) اشکال اعتقادی
  3) ضعف استدلال
  4) تعارض احتمالی با خط‌مشی شبکه
  5) ریسک رسانه‌ای
  6) نیازمند بررسی بیشتر
- severity: high / medium / low.
- status:
  * «اشکال روشن» فقط وقتی خطا یا تناقض از خود برنامه روشن است.
  * «نیازمند بررسی» وقتی تحقیق بیرونی لازم است.
  * «ضعف در پاسخ» برای نقص استدلال یا پاسخ.
  * «ریسک محتوایی» برای خطر رسانه‌ای/حقوقی/امنیتی/تحریک‌آمیز.
- اگر هیچ مورد مهمی پیدا نشد content_review را آرایه خالی برگردان.
- انگیزه یا نیت افراد را حدس نزن و منبعی را جعل نکن.

متن برنامه:
--------------------
{transcript}
--------------------
"""


def _analysis_error_kind(exc: Exception) -> str:
    """Return a compact diagnostic category without changing report behavior."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if (
        "429" in text
        or "resource_exhausted" in text
        or "resource has been exhausted" in text
        or "quota" in text
        or "rate limit" in text
        or "rate_limit" in text
    ):
        return "RATE_LIMIT"
    if "503" in text or "unavailable" in text or "high demand" in text:
        return "SERVICE_UNAVAILABLE"
    if "500" in text or "internal" in text:
        return "SERVER_ERROR"
    if "validationerror" in text or "validation error" in text:
        return "VALIDATION_ERROR"
    if "typeerror" in text:
        return "TYPE_ERROR"
    return "OTHER"


def structured_analysis_with_retry(client, prompt: str, schema_model):
    """
    Run the existing structured analysis with a quota-safe retry policy.

    v4.1 used four Flash models and retried each model up to three times, so a
    single long program could resend the full transcript as many as 12 times.
    v4.1.1 keeps the same prompt, schema and fallback report, but makes at most
    one request to each of two Flash-Lite models (2 requests total).
    """
    errors: list[str] = []

    for model_index, model in enumerate(ANALYSIS_MODELS):
        for attempt in range(1, ANALYSIS_ATTEMPTS_PER_MODEL + 1):
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema_model.model_json_schema(),
                    },
                )
                raw = (interaction.output_text or "").strip()
                if not raw:
                    raise RuntimeError("empty analysis response")
                return schema_model.model_validate_json(raw), model, errors
            except Exception as exc:
                kind = _analysis_error_kind(exc)
                message = (
                    f"{model} attempt {attempt} [{kind}]: "
                    f"{type(exc).__name__}: {exc}"
                )
                errors.append(message)
                print(message, file=sys.stderr)

        # Do not hammer the API. Wait briefly before trying the one fallback
        # model. There is no repeated retry loop on the same model.
        if model_index < len(ANALYSIS_MODELS) - 1:
            time.sleep(ANALYSIS_FALLBACK_DELAY_SECONDS)

    return None, "UNAVAILABLE", errors


def fallback_persian_analysis(info: dict) -> PersianProgramAnalysis:
    return PersianProgramAnalysis(
        host="نامشخص",
        expert="نامشخص",
        program_title=f"{info['program']} — تحلیل خودکار در دسترس نبود",
        topic="نیازمند بررسی دستی",
        hashtags=[f"#{info['program'].replace(' ', '_')}", "#نیازمند_بررسی"],
        summary=(
            "⚠️ متن برنامه ثبت شده است، اما تحلیل هوشمند به دلیل خطای سرویس یا "
            "محدودیت سهمیه انجام نشد. برای جمع‌بندی محتوایی، متن پیوست باید دستی بررسی شود."
        ),
        key_points=[],
        audience_questions=[],
        viral_clips=[],
        expert_content_review=[
            PersianContentIssue(
                status="نیازمند بررسی",
                issue="تحلیل خودکار محتوا در این Run تکمیل نشد.",
                start_sec=0,
                end_sec=0,
            )
        ],
        host_review=[],
    )


def fallback_international_analysis() -> InternationalProgramAnalysis:
    return InternationalProgramAnalysis(
        program_name="نامشخص",
        host="نامشخص",
        expert="نامشخص",
        program_title="تحلیل خودکار برنامه در دسترس نبود",
        topic="نیازمند بررسی دستی",
        hashtags=["#شبکه_ولایت", "#نیازمند_بررسی"],
        summary=(
            "⚠️ متن برنامه ثبت شده است، اما تحلیل هوشمند به دلیل خطای سرویس یا "
            "محدودیت سهمیه تکمیل نشد. متن پیوست برای بررسی دستی محفوظ است."
        ),
        key_points=[],
        content_review=[
            CriticalReviewIssue(
                category="نیازمند بررسی بیشتر",
                severity="high",
                status="نیازمند بررسی",
                issue="ارزیابی محتوایی خودکار این Run تکمیل نشد.",
                reason="سرویس تحلیل هوشمند در دسترس نبود یا سهمیه آن پاسخ نداد.",
            )
        ],
    )


# -----------------------------------------------------------------------------
# Report / stats / Bale formatting
# -----------------------------------------------------------------------------

def build_stats(analysis: PersianProgramAnalysis):
    phone = sum(x.source_type == "phone" for x in analysis.audience_questions)
    message = sum(x.source_type == "message" for x in analysis.audience_questions)
    unknown = sum(x.source_type == "unknown" for x in analysis.audience_questions)
    names: list[str] = []
    for x in analysis.audience_questions:
        n = normalize_name(x.audience_name)
        if n != "نامشخص" and n not in names:
            names.append(n)
    return {
        "phone_count": phone,
        "message_count": message,
        "unknown_count": unknown,
        "total_count": len(analysis.audience_questions),
        "audience_names": names,
    }


def answered_questions_payload(analysis: PersianProgramAnalysis):
    return [x.model_dump() for x in analysis.audience_questions]


def severity_fa(value: str) -> str:
    return {"high": "بالا", "medium": "متوسط", "low": "پایین"}.get(value, value)


def source_label(source_type: str) -> str:
    return {
        "phone": "تلفنی",
        "message": "پیام/پیامک",
        "unknown": "نوع ارتباط نامشخص",
    }.get(source_type, "نامشخص")


def format_bale_persian_part1(
    info: dict,
    analysis: PersianProgramAnalysis,
    tmeta: TranscriptionMeta,
) -> str:
    hashtags = " ".join(filter(None, (clean_hashtag(x) for x in analysis.hashtags)))
    lines = [
        "📌 بخش اول | خلاصه برنامه‌های زنده شبکه ولایت",
        "",
        f"🗓 تاریخ: {jalali_date_for_info(info)}",
        f"📺 نام برنامه: {info['program']}",
        f"📰 تیتر کلی: {analysis.program_title}",
        f"🎙 مجری: {normalize_name(analysis.host)}",
        f"👤 کارشناس: {normalize_name(analysis.expert)}",
        f"🕒 زمان برنامه: {info['start']} تا {info['end']} به وقت تهران",
        f"🎯 موضوع: {analysis.topic}",
        f"🏷 هشتگ‌ها: {hashtags}",
        "",
        "📝 خلاصه مباحث برنامه:",
        analysis.summary,
    ]
    if tmeta.transcript_incomplete:
        lines += ["", "⚠️ پیاده‌سازی این بخش ناقص است."]

    if analysis.key_points:
        lines += ["", "🔹 محورهای اصلی با تایم:"]
        for i, x in enumerate(analysis.key_points, 1):
            lines.append(
                f"{i}. {x.title}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا {sec_to_hhmmss(x.end_sec)}"
            )
    return "\n".join(lines)


def format_bale_persian_part2(
    info: dict,
    analysis: PersianProgramAnalysis,
    stats: dict,
) -> str:
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
                if normalize_name(x.audience_name) != "نامشخص"
                else ""
            )
            lines.append(
                f"{i}. [{source_label(x.source_type)}{audience}] {x.question}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا {sec_to_hhmmss(x.end_sec)}\n"
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
            lines.append(
                f"{i}. «{x.media_title}»\n"
                f"   🎬 سوژه: {x.angle}\n"
                f"   ⏱ تقطیع: {sec_to_hhmmss(x.start_sec)} تا {sec_to_hhmmss(x.end_sec)}\n"
                f"   📈 ظرفیت وایرال: {severity_fa(x.priority)} — {x.why_viral}"
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
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا {sec_to_hhmmss(x.end_sec)}"
            )
    else:
        lines.append("اشکال محتوایی معناداری در متن شناسایی نشد.")

    lines += ["", "🎙 ارزیابی کوتاه اجرای مجری:"]
    if analysis.host_review:
        for i, x in enumerate(analysis.host_review, 1):
            lines.append(
                f"{i}. [{x.issue_type}] {x.note}\n"
                f"   ⏱ {sec_to_hhmmss(x.start_sec)} تا {sec_to_hhmmss(x.end_sec)}"
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
        lines.append(f"❔ نوع ارتباط نامشخص: {stats['unknown_count']}")
    lines.append(
        f"✅ مجموع سؤالات مخاطبان که پاسخ داده شد: {stats['total_count']}"
    )
    return "\n".join(lines)


def format_bale_international(
    info: dict,
    cfg: NetworkConfig,
    analysis: InternationalProgramAnalysis,
    tmeta: TranscriptionMeta,
) -> str:
    hashtags = " ".join(filter(None, (clean_hashtag(x) for x in analysis.hashtags)))
    lines = [
        f"📡 رصد {cfg.label_fa}",
        "",
        f"🗓 تاریخ: {jalali_date_for_info(info)}",
        f"🌐 شبکه / زبان: {cfg.label_fa} / {cfg.language_fa}",
        f"📺 نام برنامه: {normalize_name(analysis.program_name)}",
        f"📰 تیتر کلی: {analysis.program_title}",
        f"🎙 مجری: {normalize_name(analysis.host)}",
        f"👤 کارشناس / مهمان: {normalize_name(analysis.expert)}",
        f"🕒 زمان برنامه: {info['start']} تا {info['end']} به وقت تهران",
        f"🎯 موضوع اصلی: {analysis.topic}",
        f"🏷 هشتگ‌ها: {hashtags}",
        "",
        "📝 خلاصه مباحث برنامه:",
        analysis.summary,
    ]

    if tmeta.transcript_incomplete:
        lines += ["", "⚠️ پیاده‌سازی این بخش ناقص است."]

    lines += ["", "🔹 محورهای اصلی برنامه:"]
    if analysis.key_points:
        for i, item in enumerate(analysis.key_points, 1):
            lines.append(f"{i}. {item}")
    else:
        lines.append("محور قابل اتکایی به‌صورت خودکار استخراج نشد.")

    lines += ["", "🧠 ارزیابی محتوایی برنامه:"]
    if analysis.content_review:
        for i, item in enumerate(analysis.content_review, 1):
            lines.append(
                f"{i}. [{item.status} | {item.category} | اهمیت {severity_fa(item.severity)}]\n"
                f"   {item.issue}\n"
                f"   ↳ چرا: {item.reason}"
            )
    else:
        lines.append("✅ مورد محتوایی مهم یا خط قرمز قابل توجهی شناسایی نشد.")

    alerts = [
        item for item in analysis.content_review
        if item.severity in {"high", "medium"}
        or item.status in {"اشکال روشن", "نیازمند بررسی", "ریسک محتوایی"}
    ]
    lines += ["", "⚠️ موارد نیازمند بررسی / اشکالات محتوایی / خط قرمزها:"]
    if alerts:
        for i, item in enumerate(alerts, 1):
            lines.append(
                f"{i}. [{item.category} | اهمیت {severity_fa(item.severity)}] {item.issue}"
            )
    else:
        lines.append("مورد مهمی برای پیگیری فوری شناسایی نشد.")

    return "\n".join(lines)


def split_message(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < 1000:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip()
    return chunks


def send_bale_message(text: str) -> None:
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
    for chunk_index, chunk in enumerate(split_message(text), start=1):
        body = json.dumps(
            {"chat_id": BALE_CHAT_ID, "text": chunk},
            ensure_ascii=False,
        ).encode("utf-8")
        last_error: Exception | None = None
        for attempt, delay in enumerate([5, 15, 30], start=1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if result.get("ok") is not True:
                    raise RuntimeError("Bale rejected report message: " + str(result))
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                print(
                    f"Bale message chunk {chunk_index} attempt {attempt} failed: {exc}",
                    file=sys.stderr,
                )
                if attempt < 3:
                    time.sleep(delay)
        if last_error is not None:
            raise RuntimeError(
                f"Bale report delivery failed after retries: {last_error}"
            )
        time.sleep(1)


def send_bale_transcript_file(info: dict, cfg: NetworkConfig) -> None:
    if not TRANSCRIPT_FILE.exists():
        fail("Transcript TXT file does not exist.")

    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendDocument"
    upload_name = (
        f"velayat_{cfg.key}_transcript_"
        f"{jalali_date_for_info(info).replace('/', '-')}_"
        f"{info['start'].replace(':', '-')}.txt"
    )
    program_label = info["program"]
    if cfg.key != "persian":
        program_label = cfg.label_fa

    caption = (
        f"📄 متن کامل پیاده‌شده | {program_label}\n"
        f"🗓 {jalali_date_for_info(info)} | "
        f"🕒 {info['start']} تا {info['end']}"
    )
    last_error: Exception | None = None
    for attempt, delay in enumerate([5, 15, 30], start=1):
        try:
            with TRANSCRIPT_FILE.open("rb") as handle:
                response = requests.post(
                    url,
                    data={"chat_id": BALE_CHAT_ID, "caption": caption},
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
            except Exception as exc:
                raise RuntimeError(
                    f"Bale sendDocument returned HTTP {response.status_code}: "
                    f"{response.text[:500]}"
                ) from exc
            if response.status_code != 200 or result.get("ok") is not True:
                raise RuntimeError("Bale rejected transcript TXT: " + str(result))
            return
        except Exception as exc:
            last_error = exc
            print(f"Bale TXT attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < 3:
                time.sleep(delay)
    raise RuntimeError(f"Bale TXT delivery failed after retries: {last_error}")


# -----------------------------------------------------------------------------
# Google Sheet payload
# -----------------------------------------------------------------------------

def report_id_for(info: dict, cfg: NetworkConfig) -> str:
    return (
        f"{info['scheduled_date']}_{cfg.key}_"
        f"{info['start'].replace(':', '')}"
    )


def post_to_sheet(payload: dict):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt, delay in enumerate([5, 15, 30], start=1):
        try:
            req = urllib.request.Request(
                SHEETS_WEBHOOK_URL,
                data=body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=45) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("ok") is not True:
                raise RuntimeError("Google Sheet webhook rejected report: " + str(result))
            return result
        except Exception as exc:
            last_error = exc
            print(f"Sheet attempt {attempt} failed: {exc}", file=sys.stderr)
            if attempt < 3:
                time.sleep(delay)
    raise RuntimeError(f"Google Sheet delivery failed after retries: {last_error}")


def update_bot_status(report_id: str, status: str) -> None:
    try:
        post_to_sheet(
            {
                "secret": WEBHOOK_SECRET,
                "report_id": report_id,
                "update_only": True,
                "bot_status": status,
            }
        )
    except Exception as exc:
        print(f"Could not update BOT_STATUS: {exc}", file=sys.stderr)


def make_common_payload(
    info: dict,
    cfg: NetworkConfig,
    tmeta: TranscriptionMeta,
    analysis_model: str,
    status: str,
    bot_status: str,
) -> dict:
    return {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id_for(info, cfg),
        "network": cfg.key,
        "language": cfg.language_fa,
        "date": jalali_date_for_info(info),
        "day": info["day"],
        "start": info["start"],
        "end": info["end"],
        "analysis_model": analysis_model,
        "transcription_source": tmeta.source,
        "transcript_incomplete": tmeta.transcript_incomplete,
        "live_failures": tmeta.live_failures,
        "capture_seconds": tmeta.audio_capture_seconds,
        "requested_capture_seconds": tmeta.requested_capture_seconds,
        "ffmpeg_return_code": tmeta.ffmpeg_return_code,
        "transcription_note": tmeta.note,
        "status": status,
        "bot_status": bot_status,
    }


def make_persian_payload(
    info: dict,
    cfg: NetworkConfig,
    analysis: PersianProgramAnalysis,
    stats: dict,
    tmeta: TranscriptionMeta,
    analysis_model: str,
    status: str,
    bot_status: str,
) -> dict:
    payload = make_common_payload(
        info, cfg, tmeta, analysis_model, status, bot_status
    )
    payload.update(
        {
            "program": info["program"],
            "host": normalize_name(analysis.host),
            "expert": normalize_name(analysis.expert),
            "program_title": analysis.program_title,
            "topic": analysis.topic,
            "summary": analysis.summary,
            "key_points": [x.model_dump() for x in analysis.key_points],
            "content_review": [
                x.model_dump() for x in analysis.expert_content_review
            ],
            "phone_question_count": stats["phone_count"],
            "message_question_count": stats["message_count"],
            "unknown_question_count": stats["unknown_count"],
            "total_question_count": stats["total_count"],
            "audience_names": stats["audience_names"],
            "answered_questions": answered_questions_payload(analysis),
            "questions": [x.question for x in analysis.audience_questions],
        }
    )
    return payload


def make_international_payload(
    info: dict,
    cfg: NetworkConfig,
    analysis: InternationalProgramAnalysis,
    tmeta: TranscriptionMeta,
    analysis_model: str,
    status: str,
    bot_status: str,
) -> dict:
    payload = make_common_payload(
        info, cfg, tmeta, analysis_model, status, bot_status
    )
    payload.update(
        {
            "program": normalize_name(analysis.program_name),
            "host": normalize_name(analysis.host),
            "expert": normalize_name(analysis.expert),
            "program_title": analysis.program_title,
            "topic": analysis.topic,
            "summary": analysis.summary,
            "key_points": analysis.key_points,
            "content_review": [x.model_dump() for x in analysis.content_review],
            "phone_question_count": 0,
            "message_question_count": 0,
            "unknown_question_count": 0,
            "total_question_count": 0,
            "audience_names": [],
            "answered_questions": [],
            "questions": [],
        }
    )
    return payload


# -----------------------------------------------------------------------------
# Diagnostics / error notification
# -----------------------------------------------------------------------------

def write_report_file(data: dict) -> None:
    REPORT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_bale_error(message: str) -> None:
    if not BALE_BOT_TOKEN or not BALE_CHAT_ID:
        return
    try:
        url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"
        text = (
            "⚠️ خطای سامانه رصد شبکه ولایت\n\n"
            f"Network: {NETWORK}\nSlot: {PROGRAM_SLOT}\n"
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


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    cfg = check_required_settings()
    info = get_program_info(cfg)

    now = datetime.now(TEHRAN)
    remaining = int((info["end_dt"] - now).total_seconds())
    if remaining <= 0:
        fail("No recording time remains for this program.")

    # Leave a small margin so FFmpeg exits before workflow timeout bookkeeping.
    capture_seconds = max(1, remaining - 3)

    client = genai.Client(api_key=GEMINI_API_KEY)
    media_url = resolve_stream_url(get_stream_url(cfg))

    transcript, timed_transcript, tmeta = asyncio.run(
        capture_and_transcribe(client, cfg, media_url, capture_seconds)
    )

    analysis_available = True
    analysis_errors: list[str] = []

    if cfg.report_mode == "persian_full":
        analysis, used_model, analysis_errors = structured_analysis_with_retry(
            client,
            persian_analysis_prompt(timed_transcript, info),
            PersianProgramAnalysis,
        )
        if analysis is None:
            analysis_available = False
            analysis = fallback_persian_analysis(info)

        analysis.host = normalize_name(analysis.host)
        analysis.expert = normalize_name(analysis.expert)
        stats = build_stats(analysis)
    else:
        analysis, used_model, analysis_errors = structured_analysis_with_retry(
            client,
            international_analysis_prompt(transcript, cfg, info),
            InternationalProgramAnalysis,
        )
        if analysis is None:
            analysis_available = False
            analysis = fallback_international_analysis()

        analysis.program_name = normalize_name(analysis.program_name)
        analysis.host = normalize_name(analysis.host)
        analysis.expert = normalize_name(analysis.expert)
        stats = None

    status = (
        "PARTIAL"
        if (tmeta.transcript_incomplete or not analysis_available)
        else "COMPLETED"
    )

    diagnostic = {
        "version": VERSION,
        "run_id": GITHUB_RUN_ID,
        "network": cfg.key,
        "language": cfg.language_fa,
        "date": jalali_date_for_info(info),
        "day": info["day"],
        "scheduled_date": info["scheduled_date"],
        "start": info["start"],
        "end": info["end"],
        "program": (
            info["program"]
            if cfg.key == "persian"
            else normalize_name(analysis.program_name)
        ),
        "analysis_model": used_model,
        "analysis_available": analysis_available,
        "analysis_errors": analysis_errors,
        "transcription": {
            "live_model": LIVE_MODEL,
            "final_source": tmeta.source,
            "fallback_used": tmeta.fallback_used,
            "transcript_incomplete": tmeta.transcript_incomplete,
            "queue_dropped_chunks": tmeta.queue_dropped_chunks,
            "capture_seconds": tmeta.audio_capture_seconds,
            "requested_capture_seconds": tmeta.requested_capture_seconds,
            "ffmpeg_return_code": tmeta.ffmpeg_return_code,
            "live_failures": tmeta.live_failures,
            "note": tmeta.note,
        },
        "status": status,
        "analysis": analysis.model_dump(),
    }
    write_report_file(diagnostic)

    if cfg.report_mode == "persian_full":
        payload = make_persian_payload(
            info,
            cfg,
            analysis,
            stats,
            tmeta,
            used_model,
            status,
            "PENDING",
        )
    else:
        payload = make_international_payload(
            info,
            cfg,
            analysis,
            tmeta,
            used_model,
            status,
            "PENDING",
        )

    delivery = {
        "sheet": "PENDING",
        "bale_report": "PENDING",
        "bale_transcript": "PENDING",
        "errors": [],
    }

    sheet_ok = False
    try:
        post_to_sheet(payload)
        sheet_ok = True
        delivery["sheet"] = "SENT"
    except Exception as exc:
        delivery["sheet"] = "FAILED"
        delivery["errors"].append(f"sheet: {type(exc).__name__}: {exc}")
        print(
            "Google Sheet delivery failed; Bale delivery will still continue.",
            file=sys.stderr,
        )

    try:
        if cfg.report_mode == "persian_full":
            send_bale_message(format_bale_persian_part1(info, analysis, tmeta))
            send_bale_message(format_bale_persian_part2(info, analysis, stats))
        else:
            send_bale_message(format_bale_international(info, cfg, analysis, tmeta))
        delivery["bale_report"] = "SENT"
    except Exception as exc:
        delivery["bale_report"] = "FAILED"
        delivery["errors"].append(f"bale_report: {type(exc).__name__}: {exc}")
        print(delivery["errors"][-1], file=sys.stderr)

    try:
        # TXT is attempted independently even if the formatted Bale message failed.
        send_bale_transcript_file(info, cfg)
        delivery["bale_transcript"] = "SENT"
    except Exception as exc:
        delivery["bale_transcript"] = "FAILED"
        delivery["errors"].append(f"bale_transcript: {type(exc).__name__}: {exc}")
        print(delivery["errors"][-1], file=sys.stderr)

    if sheet_ok:
        bot_status = (
            "SENT"
            if delivery["bale_report"] == "SENT" and delivery["bale_transcript"] == "SENT"
            else "FAILED"
        )
        update_bot_status(payload["report_id"], bot_status)

    diagnostic["delivery"] = delivery
    if delivery["errors"]:
        diagnostic["delivery_status"] = "PARTIAL"
    else:
        diagnostic["delivery_status"] = "COMPLETED"
    write_report_file(diagnostic)

    # Bale is the primary operator-facing output. If either Bale channel fails,
    # mark the workflow failed after preserving transcript/report artifacts.
    if delivery["bale_report"] != "SENT" or delivery["bale_transcript"] != "SENT":
        raise RuntimeError("; ".join(delivery["errors"]) or "Bale delivery failed")

    print(
        f"VELAYAT LIVE MONITOR v{VERSION} SUCCESS | network={cfg.key} "
        f"slot={PROGRAM_SLOT} status={status} transcript={tmeta.source} "
        f"sheet={delivery['sheet']}"
    )


if __name__ == "__main__":
    try:
        main()
        AUDIO_BACKUP_FILE.unlink(missing_ok=True)
    except Exception as exc:
        print(f"FATAL ERROR: {exc}", file=sys.stderr)
        send_bale_error(str(exc))
        AUDIO_BACKUP_FILE.unlink(missing_ok=True)
        raise
