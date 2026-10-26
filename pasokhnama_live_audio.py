#!/usr/bin/env python3
"""Optional, capped, Gemini audio transcription fallback for Pasokhnama only.

No change to Didban's live monitor. Uses its existing Gemini key and never
logs raw audio, the API key, or private speech. This is NOT proof of accuracy.
"""
from __future__ import annotations
import base64
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL = os.environ.get("PASOKHNAMA_AUDIO_MODEL", "gemini-3.5-flash-lite")
PROMPT = (
    "این یک بخش کوتاه از صوت زنده شبکه فارسی است. فقط گفتار فارسی را "
    "که واقعاً شنیده می‌شود به فارسی درست و روان پیاده‌سازی کن. "
    "هیچ حکم شرعی، تفسیر، عنوان، توضیح اضافه، نام، نقل‌قول، جمله یا "
    "عبارت حدسی به متن اضافه نکن. اگر فقط موسیقی یا کلام نامفهوم "
    "وجود دارد، خروجی را خالی برگردان. فقط متن رونوشت؛ بدون مقدمه."
)


def transcribe_audio(wav: Path, api_key: str, *, model: str = MODEL,
                     timeout: int = 70) -> str:
    if not api_key:
        return ""
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
        raise ValueError("Invalid audio transcription model")
    if not wav.is_file() or wav.stat().st_size < 60000:
        return ""
    with tempfile.TemporaryDirectory(prefix="pasokhnama_audio_") as tmp:
        mp3 = Path(tmp) / "clip.mp3"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
             "-i", str(wav), "-vn", "-ar", "16000", "-ac", "1",
             "-c:a", "libmp3lame", "-b:a", "32k", "-y", str(mp3)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
        raw = mp3.read_bytes()
    if len(raw) > 850_000:
        return ""
    payload = {
        "contents": [{"role": "user", "parts": [
            {"text": PROMPT},
            {"inlineData": {
                "mimeType": "audio/mpeg",
                "data": base64.b64encode(raw).decode("ascii"),
            }},
        ]}],
        "generationConfig": {"temperature": 0},
    }
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + model + ":generateContent",
        data=json.dumps(payload, ensure_ascii=False).encode("utf8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read(140000))
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 75 or sum("\u0600" <= x <= "\u06ff" for x in text) < 55:
            return ""
        return text[:2300]
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Audio transcription HTTP status " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError, TypeError) as exc:
        raise RuntimeError("Audio transcription unavailable: " + type(exc).__name__) from None
