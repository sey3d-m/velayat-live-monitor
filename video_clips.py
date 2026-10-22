"""Capture compact live MP4 and publish two properly synchronized Bale highlights.

Never upload the full private recording. Individual selections are re-encoded
at exact boundaries so the first decoded video frame is playable immediately.
"""
import asyncio
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

PRIVATE_DIR = Path("private_live_video")
RECORDING = PRIVATE_DIR / "programme_preview.mp4"
CAPTION_LIMIT = 900


def enabled():
    return os.getenv("ENABLE_BALE_VIDEO_CLIPS", "true").lower() not in ("false", "off", "0")


def playback_speed():
    """Apply the same playback rate to picture and speech to preserve A/V sync."""
    try:
        value = float(os.getenv("BALE_CLIP_PLAYBACK_SPEED", "1.5"))
    except ValueError:
        return 1.5
    return value if value in (1.0, 1.5) else 1.5


async def capture_video(media_url, duration):
    """Independent, low-bitrate recording; never blocks the primary audio capture."""
    if not enabled():
        return None
    PRIVATE_DIR.mkdir(exist_ok=True)
    RECORDING.unlink(missing_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", media_url, "-map", "0:v:0", "-map", "0:a:0?",
        "-t", str(duration),
        # 12 fps produced visibly jerky movement; 24 fps is a compromise
        # between natural motion, runner CPU, and small files.
        "-vf", "fps=24,scale=w=640:h=-2:force_original_aspect_ratio=decrease,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-crf", "31", "-maxrate", "650k", "-bufsize", "1300k",
        "-g", "48", "-keyint_min", "48", "-sc_threshold", "0",
        # Resynchronize audio when the live input timestamps are discontinuous.
        "-af", "aresample=async=1:first_pts=0",
        "-c:a", "aac", "-b:a", "48k", "-ac", "1", "-ar", "24000",
        "-movflags", "+faststart", "-y", str(RECORDING),
    ]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stderr=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            print("Clip recorder FFmpeg: " + stderr.decode("utf8", "replace")[-500:],
                  file=sys.stderr)
    except Exception as exc:
        print(f"Clip recorder unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
    return RECORDING if RECORDING.exists() and RECORDING.stat().st_size > 10000 else None


def select_segments(clips, duration, limit=2):
    """Select two nonoverlapping coherent excerpts, capped at 100 source seconds."""
    ranked = sorted(clips, key=lambda c: {
        "high": 0, "medium": 1, "low": 2
    }.get(str(getattr(c, "priority", "medium")), 2))
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
        title = re.sub(r"\s+", " ", str(getattr(item, "media_title",
                                                "برشی از برنامه"))).strip()[:100]
        chosen.append((start, end, title or "برشی از برنامه"))
        if len(chosen) >= limit:
            break
    return chosen


def make_clip(source, start, end, index):
    """Decode from accurate seek, then re-encode from timestamp zero.

    Copying encoded streams at an arbitrary start can yield silent/unplayable
    B/P pictures until the next keyframe, while the audio plays normally.
    Both tracks are sped up by the same amount; atempo retains speech pitch.
    """
    PRIVATE_DIR.mkdir(exist_ok=True)
    dest = PRIVATE_DIR / f"clip_{index:02}.mp4"
    dest.unlink(missing_ok=True)
    speed = playback_speed()
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-i", str(source), "-t", str(end - start),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"setpts=(PTS-STARTPTS)/{speed},fps=24,setsar=1",
        "-af", f"atempo={speed},asetpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-crf", "31", "-maxrate", "650k", "-bufsize", "1300k",
        "-g", "48", "-c:a", "aac", "-b:a", "48k",
        "-ar", "24000", "-ac", "1",
        "-movflags", "+faststart", "-avoid_negative_ts", "make_zero",
        "-y", str(dest),
    ]
    run = subprocess.run(cmd, capture_output=True, timeout=180)
    if run.returncode != 0 or not dest.exists() or dest.stat().st_size < 5000:
        raise RuntimeError("Clip encoding failed: " +
                           run.stderr.decode("utf8", "replace")[-250:])
    return dest


def compact_text(value, max_chars=360):
    """Remove escaped literal newlines and excessive whitespace from model text."""
    value = str(value or "").replace("\\n", " ").replace("\n", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_chars].rstrip(" ،؛.")


def normalize_hashtag(value):
    tag = compact_text(value, 85).lstrip("#").replace(" ", "_")
    tag = re.sub(r"[^\w\u200c]", "", tag, flags=re.UNICODE)
    return "#" + tag if tag else ""


def format_bale_caption(*, title, expert, program, date, description,
                        hashtags, start, end):
    """Human-readable editorial metadata, with genuine newlines for Bale."""
    title = compact_text(title, 110) or "گزیده برنامه"
    program = compact_text(program, 80) or "شبکه ولایت فارسی"
    expert = compact_text(expert, 95) or "نامشخص"
    date = compact_text(date, 24) or "نامشخص"
    description = compact_text(description, 370)
    if not description:
        description = f"در این بخش از برنامه «{program}»، موضوع «{title}» مطرح و بررسی می‌شود."

    tags = []
    for candidate in [f"#{program.replace(' ', '_')}", *(hashtags or []),
                      "#شبکه_ولایت"]:
        tag = normalize_hashtag(candidate)
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= 6:
            break

    head = [
        f"🎬 تیتر: {title}",
        f"🎙 کارشناس: {expert}",
        f"📺 برنامه: {program}",
        f"📅 تاریخ: {date}",
        "",
        f"📝 کپشن: {description}",
        "",
        f"⏱ بازه برنامه: {start//60:02}:{start%60:02} تا {end//60:02}:{end%60:02} (تقریبی)",
        " ".join(tags),
    ]
    result = "\n".join(head)
    if len(result) > CAPTION_LIMIT:
        # Keep all essential metadata and hashtags; trim only the description.
        overflow = len(result) - CAPTION_LIMIT
        description = description[:max(0, len(description) - overflow - 3)].rstrip() + "..."
        head[5] = f"📝 کپشن: {description}"
        result = "\n".join(head)
    return result[:CAPTION_LIMIT]


def description_for(suggestions, start, title):
    """Match selected source interval to its editorial caption, not the viral score."""
    for item in suggestions:
        try:
            match = int(getattr(item, "start_sec")) == start
        except (TypeError, ValueError, AttributeError):
            continue
        if match and compact_text(getattr(item, "media_title", ""), 100) == title:
            return compact_text(getattr(item, "caption", ""), 370) or compact_text(
                getattr(item, "angle", ""), 370)
    return ""


def send_bale_clips(source, suggestions, duration, token, chat_id, program, *,
                    expert="نامشخص", date="", hashtags=None):
    """Send two synchronized MP4 clips with title, expert, program, date and caption."""
    errors, sent = [], []
    if not enabled():
        return {"status": "disabled", "sent": sent, "errors": errors}
    if not source or not Path(source).exists():
        return {"status": "unavailable", "sent": sent,
                "errors": ["live_video_unavailable"]}
    selections = select_segments(suggestions, duration)
    if not selections:
        return {"status": "unavailable", "sent": sent,
                "errors": ["no_valid_editorial_clips"]}

    for idx, (start, end, title) in enumerate(selections, 1):
        try:
            path = make_clip(source, start, end, idx)
            if path.stat().st_size > 45 * 1024 * 1024:
                raise RuntimeError("Clip exceeds safety upload size cap")
            caption = format_bale_caption(
                title=title, expert=expert, program=program, date=date,
                description=description_for(suggestions, start, title),
                hashtags=hashtags, start=start, end=end,
            )
            last_error = None
            for attempt in range(2):
                try:
                    with path.open("rb") as handle:
                        response = requests.post(
                            f"https://tapi.bale.ai/bot{token}/sendVideo",
                            data={"chat_id": chat_id, "caption": caption,
                                  "supports_streaming": "true"},
                            files={"video": (path.name, handle, "video/mp4")},
                            timeout=120,
                        )
                    if response.status_code != 200 or response.json().get("ok") is not True:
                        raise RuntimeError(
                            f"Bale sendVideo rejected video (HTTP {response.status_code})")
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    print(f"Bale clip {idx} attempt {attempt+1} failed: {exc}",
                          file=sys.stderr)
                    if attempt == 0:
                        time.sleep(2)
            if last_error:
                raise last_error
            sent.append({
                "start_sec": start, "end_sec": end, "title": title,
                "size_bytes": path.stat().st_size, "speed": playback_speed(),
            })
        except Exception as exc:
            errors.append(f"clip_{idx}: {type(exc).__name__}: {exc}")
            print(errors[-1], file=sys.stderr)

    return {"status": "sent" if sent and not errors else
            "partial" if sent else "failed", "sent": sent, "errors": errors}


def cleanup():
    for path in (PRIVATE_DIR / "clip_01.mp4", PRIVATE_DIR / "clip_02.mp4", RECORDING):
        path.unlink(missing_ok=True)
