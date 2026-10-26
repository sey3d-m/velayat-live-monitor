#!/usr/bin/env python3
"""Isolated public live-caption producer. Never imports or modifies Didban."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib import request, error

REPO = "sey3d-m/velayat-live-monitor"
DATA_BRANCH = "pasokhnama-live-data"
DATA_PATH = "state/live.json"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SESSION = os.environ.get("GITHUB_RUN_ID", "")
SLOT = os.environ.get("PROGRAM_SLOT", "")
STREAM = os.environ.get("STREAM_URL", "")
DATE = os.environ.get("PROGRAM_DATE", "")
CHUNK_SECONDS = 35
MAX_SECONDS = min(90, max(5, int(os.environ.get("PASOKHNAMA_MAX_MINUTES", "70")))) * 60
STARTED = datetime.now(timezone.utc).isoformat()
ITEMS = []
MAX_ITEMS = 5

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def github(method, data=None):
    url = f"https://api.github.com/repos/{REPO}/contents/{DATA_PATH}?ref={DATA_BRANCH}"
    if method == "PUT":
        url = url.split("?")[0]
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = request.Request(url, body, method=method, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
        "User-Agent": "pasokhnama-live-producer",
    })
    with request.urlopen(req, timeout=25) as res:
        return json.loads(res.read(500_000))

def publish(status):
    if not TOKEN:
        raise RuntimeError("GITHUB_TOKEN is missing")
    payload = {
        "version": 1,
        "status": status,
        "network": "velayat_farsi",
        "session": SESSION,
        "program": f"برنامه شبکه ولایت فارسی | {SLOT} (تهران)",
        "program_date": DATE or datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat(),
        "started_at": STARTED,
        "updated_at": utcnow(),
        "items": ITEMS[-MAX_ITEMS:],
    }
    for attempt in range(4):
        try:
            prev = github("GET")
            old = json.loads(base64.b64decode(prev["content"]))
            # An older concurrently running program may never replace newer live data.
            if old.get("session") != SESSION and (old.get("started_at") or "") > STARTED:
                print("A newer session owns the live feed; ending this publisher.")
                return False
            github("PUT", {
                "message": "Update isolated Pasokhnama live transcript",
                "branch": DATA_BRANCH,
                "sha": prev["sha"],
                "content": base64.b64encode((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()).decode(),
            })
            print(f"Published {status} items={len(ITEMS)} to separate data branch.")
            return True
        except (error.HTTPError, error.URLError) as exc:
            print(f"Publication attempt {attempt+1} failed: {getattr(exc, 'code', type(exc).__name__)}")
            if attempt == 3:
                raise
            time.sleep(3 * (attempt + 1))
    return False

def caption(model, path, sequence):
    segments, info = model.transcribe(str(path), language="fa", beam_size=2,
                                      best_of=2, vad_filter=True, condition_on_previous_text=False)
    text = " ".join(s.text.strip() for s in segments)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(?<!\d)(?:\+?\d[\d\s-]{8,}\d)(?!\d)", "[شماره حذف شد]", text)
    persian = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
    if persian < 25 or len(text) < 55:
        return None
    # Not a verified quote, speaker identity or religious citation.
    # Always visibly label as unverified automatic transcription.
    excerpt = text[:295].rsplit(" ", 1)[0]
    if len(excerpt) < 55:
        return None
    return {
        "id": f"{SESSION}-{sequence}",
        "title": "گزیده خودکار از گفت‌وگوی در حال پخش",
        "summary": excerpt + ("…" if len(text) > len(excerpt) else ""),
        "kind": "automatic_transcript",
        "verification_status": "unverified",
        "speaker": None,
        "sequence": sequence,
        "updated_at": utcnow(),
    }

def main():
    if not SESSION.isdigit() or not TOKEN or not STREAM or not re.fullmatch(r"\d\d:\d\d", SLOT):
        raise SystemExit("Missing or invalid isolated-run configuration")
    print('Pasokhnama: local Persian speech capture process launching', flush=True)
    # Publish a new session only when the input is validated.
    if not publish("starting"):
        return
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("PASOKHNAMA_WHISPER_MODEL", "small"),
                         device="cpu", compute_type="int8", cpu_threads=2, num_workers=1)
    print('Pasokhnama: Whisper model loaded; starting segmented FFmpeg capture', flush=True)
    with tempfile.TemporaryDirectory(prefix="pasokhnama_") as temp:
        root = Path(temp)
        cmd = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", STREAM, "-map", "0:a:0", "-vn",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
            "-reset_timestamps", "1", "-segment_format", "wav",
            str(root / "segment-%04d.wav"),
        ]
        started = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        number = 0
        try:
            while time.monotonic() - started < MAX_SECONDS:
                part = root / f"segment-{number:04}.wav"
                next_part = root / f"segment-{number+1:04}.wav"
                if next_part.exists() and part.exists() and part.stat().st_size > 60_000:
                    try:
                        item = caption(model, part, number)
                        if item:
                            ITEMS.append(item)
                            if not publish("live"):
                                break
                    except Exception as ex:
                        print(f"Chunk {number} skipped: {type(ex).__name__}: {str(ex)[:100]}")
                    part.unlink(missing_ok=True)
                    number += 1
                    continue
                if proc.poll() is not None:
                    print(f"FFmpeg terminated unexpectedly: exit={proc.returncode}")
                    break
                time.sleep(3)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
            # Do not publish a truncated, unfinished final segment.
            try:
                publish("ended")
            except Exception as ex:
                print(f"Final status could not be written: {type(ex).__name__}")

if __name__ == "__main__":
    main()
