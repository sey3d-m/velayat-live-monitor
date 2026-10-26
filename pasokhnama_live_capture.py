#!/usr/bin/env python3
"""Isolated public live-caption producer. Never imports or modifies Didban."""
import base64
from concurrent.futures import ThreadPoolExecutor
import shutil
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
from pasokhnama_live_audio import transcribe_audio

REPO = "sey3d-m/velayat-live-monitor"
DATA_BRANCH = "pasokhnama-live-data"
DATA_PATH = "state/live.json"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SESSION = os.environ.get("GITHUB_RUN_ID", "")
SLOT = os.environ.get("PROGRAM_SLOT", "")
STREAM = os.environ.get("STREAM_URL", "")
DATE = os.environ.get("PROGRAM_DATE", "")
CHUNK_SECONDS = 24
MAX_SECONDS = min(90, max(5, int(os.environ.get("PASOKHNAMA_MAX_MINUTES", "70")))) * 60
STARTED = datetime.now(timezone.utc).isoformat()
ITEMS = []
MAX_ITEMS = 5
PROGRESS = {"segments_captured": 0, "segments_transcribed": 0, "editor_attempts": 0, "editor_withheld": 0, "topics_published": 0, "audio_ai_calls": 0, "audio_ai_success": 0, "last_audio_at": None}

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

def edit_batch(source, editor_key, audio_path=None):
    """Edit one NEW speech window off the capture loop; never publish raw ASR."""
    try:
        edited = rewrite(source, editor_key)
    except (RuntimeError, ValueError) as exc:
        print("Pasokhnama editor unavailable:", str(exc), flush=True)
        edited = None
    if edited and edited.get("scope") != "topic_only":
        edited = None
    withheld = edited is None
    if not edited:
        edited = grounded_topic(source)
        if edited:
            print("Pasokhnama: literal grounded headline fallback, no claimed ruling.", flush=True)
    audio_called = False
    audio_success = False
    if not edited and audio_path is not None and editor_key:
        audio_called = True
        try:
            clearer = transcribe_audio(audio_path, editor_key)
            if clearer:
                audio_success = True
                try:
                    edited = rewrite(clearer, editor_key)
                except (RuntimeError, ValueError) as exc:
                    print("Audio-based editorial unavailable:", str(exc), flush=True)
                    edited = None
                if edited and edited.get("scope") != "topic_only":
                    edited = None
                if not edited:
                    edited = grounded_topic(clearer)
                if edited:
                    edited["editor_mode"] = "audio_grounded_topic"
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
            print("Optional direct audio bypass unavailable:", type(exc).__name__, flush=True)
    return edited, withheld, audio_called, audio_success


def similar_previous(item, previous):
    """Avoid republishing equivalent points while allowing different arguments."""
    def words(value):
        return set(re.findall(r"[\u0600-\u06ff]{3,}", value))
    title = words(item["title"])
    summary = words(item["summary"])
    for old in previous[-12:]:
        other_title, other_summary = words(old["title"]), words(old["summary"])
        if item["title"] == old["title"]:
            return True
        if title and other_title and summary and other_summary:
            title_overlap = len(title & other_title) / len(title | other_title)
            summary_overlap = len(summary & other_summary) / len(summary | other_summary)
            if title_overlap >= 0.86 and summary_overlap >= 0.82:
                return True
    return False


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
    # Preserve Tehran program alignment; never mislabel the previous broadcast.
    delta = seconds_until_program()
    if delta > 1800 or delta < -1500:
        print(f"Pasokhnama: outside allowed broadcast window ({delta:.0f}s); skip.", flush=True)
        return
    if delta > 2:
        print(f"Pasokhnama: prewarmed, awaiting official Tehran slot ({delta:.0f}s).", flush=True)
        time.sleep(delta)
    if not publish("starting"):
        return
    print('Pasokhnama: scheduled show started; incremental capture running', flush=True)
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
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pasokhnama-editor")
        editor_future = None
        editor_sequence = -1
        editor_audio = None
        editor_submitted_at = None
        no_topic_batches = 0
        number = 0
        try:
            while time.monotonic() - started < MAX_SECONDS:
                # Only the capture thread writes state/live.json. Gemini runs
                # separately; no concurrent editor jobs and no racing commits.
                if editor_future is not None and editor_future.done():
                    try:
                        edited, withheld, audio_called, audio_success = editor_future.result()
                        PROGRESS["editor_withheld"] += int(withheld)
                        PROGRESS["audio_ai_calls"] += int(audio_called)
                        PROGRESS["audio_ai_success"] += int(audio_success)
                        if edited and not similar_previous(edited, ITEMS):
                            item = {**edited, "id": f"{SESSION}-{editor_sequence}",
                                    "sequence": editor_sequence, "updated_at": utcnow(),
                                    "speaker": None}
                            ITEMS.append(item)
                            PROGRESS["topics_published"] += 1
                            no_topic_batches = 0
                            if not publish("live"):
                                break
                            if editor_submitted_at is not None:
                                print(f"Pasokhnama: transcript-to-published-state {time.monotonic()-editor_submitted_at:.1f}s", flush=True)
                            print(f"Pasokhnama: published specific point for segment {editor_sequence}", flush=True)
                        else:
                            no_topic_batches += 1
                    except Exception as exc:
                        no_topic_batches += 1
                        PROGRESS["editor_withheld"] += 1
                        print("Pasokhnama editorial result withheld:", type(exc).__name__, flush=True)
                    finally:
                        if editor_audio is not None:
                            editor_audio.unlink(missing_ok=True)
                        editor_future = None
                        editor_audio = None
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
                        # Process the newest complete 24s window if speech is
                        # sufficient; aggregate at most two when speech is short.
                        # Never retranscribe the entire program.
                        if editor_future is None and pending_speech:
                            source = "\n".join(pending_speech[-2:])
                            if len(source) >= 140:
                                editor_sequence = number
                                # Preserve the existing optional capped direct
                                # audio recovery after repeated failed batches.
                                if (no_topic_batches >= 2 and editor_key
                                        and PROGRESS["audio_ai_calls"] < 3):
                                    editor_audio = root / f"editor-audio-{number:04}.wav"
                                    shutil.copyfile(part, editor_audio)
                                else:
                                    editor_audio = None
                                PROGRESS["editor_attempts"] += 1
                                editor_submitted_at = time.monotonic()
                                editor_future = executor.submit(
                                    edit_batch, source, editor_key, editor_audio)
                                pending_speech.clear()
                        # If the API is slower than speech, retain only the
                        # newest small window instead of a growing stale queue.
                        if len(pending_speech) > 2:
                            pending_speech = pending_speech[-2:]
                        if number % 2 == 1:
                            if not publish("live" if ITEMS else "reviewing"):
                                break
                            print("Pasokhnama: segments=", PROGRESS["segments_captured"],
                                  "titles=", PROGRESS["topics_published"], flush=True)
                    except Exception as exc:
                        print(f"Chunk {number} skipped: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
                    part.unlink(missing_ok=True)
                    number += 1
                    continue
                if proc.poll() is not None:
                    print(f"FFmpeg terminated unexpectedly: exit={proc.returncode}", flush=True)
                    break
                time.sleep(1)
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
            # No stale editor task may write after this run has ended.
            executor.shutdown(wait=True, cancel_futures=True)
            if editor_audio is not None:
                editor_audio.unlink(missing_ok=True)
            try:
                publish("ended")
            except Exception as exc:
                print(f"Final status could not be written: {type(exc).__name__}", flush=True)

if __name__ == "__main__":
    main()
