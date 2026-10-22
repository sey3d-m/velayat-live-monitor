"""Record low-bitrate live video and deliver short editorial clips to Bale."""
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path

import requests

PRIVATE_DIR = Path("private_live_video")
RECORDING = PRIVATE_DIR / "programme_preview.mp4"

def enabled():
    return os.getenv("ENABLE_BALE_VIDEO_CLIPS", "true").lower() not in ("false", "off", "0")

async def capture_video(media_url, duration):
    """Independent live H.264/AAC recording; audio transcription is never blocked."""
    if not enabled():
        return None
    PRIVATE_DIR.mkdir(exist_ok=True)
    RECORDING.unlink(missing_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-reconnect", "1", "-reconnect_streamed", "1",
           "-reconnect_delay_max", "5", "-i", media_url,
           "-map", "0:v:0", "-map", "0:a:0?", "-t", str(duration),
           "-vf", "scale=w=640:h=-2:force_original_aspect_ratio=decrease,fps=12",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-b:v", "250k", "-maxrate", "300k", "-bufsize", "600k",
           "-c:a", "aac", "-b:a", "40k", "-ac", "1", "-ar", "24000",
           "-movflags", "+faststart", "-y", str(RECORDING)]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stderr=asyncio.subprocess.PIPE,
                                                    stdout=asyncio.subprocess.DEVNULL)
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print("Clip recorder FFmpeg: " + stderr.decode("utf8", "replace")[-500:], file=sys.stderr)
    except Exception as exc:
        print(f"Clip recorder unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
    return RECORDING if RECORDING.exists() and RECORDING.stat().st_size > 10000 else None

def select_segments(clips, duration, limit=2):
    """Respect transcription timestamps; avoid invalid, overlapping or overly long clips."""
    ranked = sorted(clips, key=lambda c: {"high": 0, "medium": 1, "low": 2}.get(
        str(getattr(c, "priority", "medium")), 2))
    chosen = []
    for item in ranked:
        try:
            start = max(0, int(getattr(item, "start_sec")))
            end = min(int(duration), int(getattr(item, "end_sec")))
        except (ValueError, TypeError, AttributeError):
            continue
        if end - start < 15:
            continue
        end = min(end, start + 100)
        if any(start < b and end > a for a, b, _ in chosen):
            continue
        title = re.sub(r"\\s+", " ", str(getattr(item, "media_title", "برشی از برنامه"))).strip()[:100]
        chosen.append((start, end, title or "برشی از برنامه"))
        if len(chosen) >= limit:
            break
    return chosen

def make_clip(source, start, end, index):
    """Stream-copy from already compressed H.264/AAC whenever possible."""
    dest = PRIVATE_DIR / f"clip_{index:02}.mp4"
    dest.unlink(missing_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
           "-ss", str(start), "-i", str(source), "-t", str(end - start),
           "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
           "-movflags", "+faststart", "-y", str(dest)]
    run = subprocess.run(cmd, capture_output=True, timeout=120)
    if run.returncode != 0 or not dest.exists() or dest.stat().st_size < 5000:
        raise RuntimeError("Clip generation failed: " + run.stderr.decode("utf8", "replace")[-200:])
    return dest

def send_bale_clips(source, suggestions, duration, token, chat_id, program):
    """Two short MP4 files, each normally 2-4MB. No raw recording leaves the runner."""
    errors, sent = [], []
    if not enabled():
        return {"status": "disabled", "sent": sent, "errors": errors}
    if not source or not Path(source).exists():
        return {"status": "unavailable", "sent": sent, "errors": ["live_video_unavailable"]}
    selections = select_segments(suggestions, duration)
    if not selections:
        return {"status": "unavailable", "sent": sent, "errors": ["no_valid_editorial_clips"]}
    for idx, (start, end, title) in enumerate(selections, 1):
        try:
            path = make_clip(source, start, end, idx)
            if path.stat().st_size > 45 * 1024 * 1024:
                raise RuntimeError("Clip exceeds safety upload size cap")
            caption = (f"🎬 تقطیع دیدبان | {program}\\n"
                       f"📌 {title}\\n"
                       f"⏱ {start//60:02}:{start%60:02} تا {end//60:02}:{end%60:02} (تقریبی)")
            with path.open("rb") as handle:
                r = requests.post(
                    f"https://tapi.bale.ai/bot{token}/sendVideo",
                    data={"chat_id": chat_id, "caption": caption[:900],
                          "supports_streaming": "true"},
                    files={"video": (path.name, handle, "video/mp4")},
                    timeout=120)
            if r.status_code != 200 or r.json().get("ok") is not True:
                raise RuntimeError(f"Bale sendVideo rejected video (HTTP {r.status_code})")
            sent.append({"start_sec": start, "end_sec": end, "title": title,
                         "size_bytes": path.stat().st_size})
        except Exception as exc:
            errors.append(f"clip_{idx}: {type(exc).__name__}: {exc}")
            print(errors[-1], file=sys.stderr)
    return {"status": "sent" if sent and not errors else "partial" if sent else "failed",
            "sent": sent, "errors": errors}

def cleanup():
    for path in (PRIVATE_DIR / "clip_01.mp4", PRIVATE_DIR / "clip_02.mp4", RECORDING):
        path.unlink(missing_ok=True)
