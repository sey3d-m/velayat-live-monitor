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
from pasokhnama_live_editor import rewrite, grounded_topic

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
PROGRESS = {"segments_captured": 0, "segments_transcribed": 0, "editor_attempts": 0, "editor_withheld": 0, "topics_published": 0, "last_audio_at": None}

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
        "progress": dict(PROGRESS),
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
    # Return only PRIVATE raw text for the grounded on-air editor.
    # Never publish uncorrected speech-recognition text to the live feed.
    return text[:1800]

def seconds_until_program(now=None):
    """Align the independent feed with the Tehran program clock, not early dispatch."""
    tehran = ZoneInfo("Asia/Tehran")
    local = now or datetime.now(tehran)
    on_date = DATE if re.fullmatch(r"\d{4}-\d{2}-\d{2}", DATE) else local.date().isoformat()
    slot_clock = datetime.fromisoformat(on_date + "T" + SLOT + ":00").replace(tzinfo=tehran)
    return (slot_clock - local).total_seconds()

def main():
    if not SESSION.isdigit() or not TOKEN or not STREAM or not re.fullmatch(r"\d\d:\d\d", SLOT):
        raise SystemExit("Missing or invalid isolated-run configuration")
    print('Pasokhnama: independent Persian capture runner preparing model', flush=True)
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("PASOKHNAMA_WHISPER_MODEL", "small"),
                         device="cpu", compute_type="int8", cpu_threads=2, num_workers=1)
    editor_key = os.environ.get("GEMINI_API_KEY", "")
    if not editor_key:
        print("Pasokhnama: no existing editor key; raw ASR will stay private.", flush=True)
    pending_speech = []
    published_titles = set()
    # Upstream scheduling dispatches about 15 minutes early. Do not mislabel
    # the previous broadcast as the next Persian program.
    delta = seconds_until_program()
    if delta > 1800 or delta < -1500:
        print(f"Pasokhnama: outside allowed broadcast window ({delta:.0f}s); skip to avoid wrong program.", flush=True)
        return
    if delta > 2:
        print(f"Pasokhnama: model prewarmed, awaiting official Tehran slot ({delta:.0f}s).", flush=True)
        time.sleep(delta)
    # Publish status only after the target program has actually begun.
    if not publish("starting"):
        return
    print('Pasokhnama: scheduled show started; segmented FFmpeg capture running', flush=True)
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
                        PROGRESS["segments_captured"] += 1
                        PROGRESS["last_audio_at"] = utcnow()
                        transcript = caption(model, part, number)
                        if transcript:
                            PROGRESS["segments_transcribed"] += 1
                            pending_speech.append(transcript)
                        # Try two contiguous segments first; if context is too
                        # noisy, retry once with four. No invented religious rules.
                        if len(pending_speech) in (2, 4):
                            source = "\n".join(pending_speech)
                            PROGRESS["editor_attempts"] += 1
                            try:
                                edited = rewrite(source, editor_key)
                            except RuntimeError as ex:
                                print("Pasokhnama editor unavailable:", str(ex), flush=True)
                                edited = None
                            # Public OBS only accepts subject-only descriptions.
                            if edited and edited.get("scope") != "topic_only":
                                edited = None
                            if not edited:
                                PROGRESS["editor_withheld"] += 1
                                edited = grounded_topic(source)
                                if edited:
                                    print("Pasokhnama: used literal-keyword grounded headline, no claimed ruling.", flush=True)
                            if edited and edited["title"] not in published_titles:
                                item = {**edited, "id": f"{SESSION}-{number}",
                                        "sequence": number, "updated_at": utcnow(),
                                        "speaker": None}
                                published_titles.add(edited["title"])
                                ITEMS.append(item)
                                PROGRESS["topics_published"] += 1
                                if not publish("live"):
                                    break
                                print(f"Pasokhnama: published safe Persian headline for segment {number}", flush=True)
                                pending_speech.clear()
                            elif len(pending_speech) >= 4:
                                pending_speech.clear()
                        # Even if nothing is safe for on-air use, expose honest
                        # progress counts instead of a permanently stale "starting".
                        if number % 2 == 1 and not ITEMS:
                            if not publish("reviewing"):
                                break
                            print("Pasokhnama: received audio, awaiting confident topic, segments=", PROGRESS["segments_captured"], flush=True)
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
