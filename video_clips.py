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


def _seconds(timestamp):
    parts = [int(part) for part in timestamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def _clip_candidate(start, end, title, description="", priority="low", *,
                    origin="transcript", why=""):
    from types import SimpleNamespace
    return SimpleNamespace(
        start_sec=start, end_sec=end, media_title=title,
        caption=description, angle=description, priority=priority,
        why_viral=why, origin=origin,
    )


def transcript_candidates(timed_transcript, duration):
    """Find real, timed speech excerpts; never synthesize a claim or quotation."""
    rows = []
    pattern = r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\n]+)"
    for match in re.finditer(pattern, timed_transcript or ""):
        start, end = _seconds(match.group(1)), _seconds(match.group(2))
        speech = compact_text(match.group(3), 420)
        if end <= start or start >= duration or len(speech) < 18:
            continue
        rows.append((start, min(end, duration), speech))
    candidates = []
    for pos, (start, end, speech) in enumerate(rows):
        # Group successive transcription lines into a coherent 35-80 second scene.
        parts = [speech]
        stop = end
        for nxt_start, nxt_end, nxt_text in rows[pos + 1:]:
            if nxt_start > stop + 10 or nxt_start - start >= 75:
                break
            parts.append(nxt_text)
            stop = min(nxt_end, start + 80, duration)
            if stop - start >= 50:
                break
        if stop - start < 18:
            continue
        whole = compact_text(" ".join(parts), 370)
        # The title is an *actual spoken excerpt*, not a claim invented by AI.
        question = re.search(r"[^.!؟?]{12,100}[؟?]", whole)
        title = compact_text(question.group(0) if question else speech, 90)
        cue = any(k in whole for k in (
            "چرا", "آیا", "چگونه", "شبهه", "پاسخ", "پرسش",
            "حقیقت", "اشتباه", "مهم", "سؤال", "دلیل"))
        candidates.append(_clip_candidate(
            start, stop, title,
            "بخشی از گفت‌وگوی برنامه درباره: " + title,
            "medium" if cue else "low", origin="transcript",
            why="پرسش یا پاسخ مستقیم" if cue else "گزیده متن زمان‌دار",
        ))
    return candidates


def build_clip_candidates(analysis, timed_transcript, duration):
    """Best AI highlights first; recover from missing/overlapping AI suggestions.

    Audience questions and key points are derived from existing structured
    analysis. Actual timestamped speech provides the last fallback.
    """
    candidates = list(getattr(analysis, "viral_clips", []) or [])
    for question in getattr(analysis, "audience_questions", []) or []:
        title = compact_text(getattr(question, "question", ""), 100)
        answer = compact_text(getattr(question, "answer_summary", ""), 350)
        if len(title) >= 10:
            candidates.append(_clip_candidate(
                question.start_sec, question.end_sec, title, answer,
                "medium", origin="audience_question",
                why="سؤال واقعی مخاطب و پاسخ کارشناسی",
            ))
    for point in getattr(analysis, "key_points", []) or []:
        title = compact_text(getattr(point, "title", ""), 100)
        if len(title) >= 12:
            candidates.append(_clip_candidate(
                point.start_sec, point.end_sec, title,
                "بررسی محور «" + title + "» در گفت‌وگوی برنامه",
                "low", origin="key_point",
            ))
    # These candidates are only based on words that occurred in the transcript.
    # AI-quality candidates naturally outrank generic transcript excerpts.
    candidates.extend(transcript_candidates(timed_transcript, duration))
    return candidates


def _viral_score(item, start, end):
    priority = str(getattr(item, "priority", "low"))
    points = {"high": 100, "medium": 65, "low": 25}.get(priority, 25)
    title = compact_text(getattr(item, "media_title", ""), 110)
    explanation = compact_text(getattr(item, "why_viral", ""), 160)
    if any(cue in title for cue in ("؟", "?", "چرا", "آیا", "چگونه", "حقیقت", "اشتباه", "شبهه", "پاسخ")):
        points += 14
    if len(explanation) >= 14:
        points += 8
    if 35 <= end - start <= 95:
        points += 7
    return points


def select_segments(clips, duration, limit=2):
    """Editorial ranking; preserve two distinct, useful non-overlapping scenes."""
    ranked = []
    for item in clips:
        try:
            start = max(0, int(getattr(item, "start_sec")))
            end = min(int(duration), int(getattr(item, "end_sec")))
        except (ValueError, TypeError, AttributeError):
            continue
        if end - start < 15:
            continue
        end = min(end, start + 100)
        title = compact_text(getattr(item, "media_title", ""), 100)
        if not title:
            continue
        ranked.append((-_viral_score(item, start, end), start, end, title))
    ranked.sort()
    chosen = []
    for _negative_score, start, end, title in ranked:
        # Distinct scenes, no repetitive overlapping cuts or identical headings.
        if any(start < b + 4 and end + 4 > a for a, b, _ in chosen):
            continue
        if any(title == existing_title for _, _, existing_title in chosen):
            continue
        chosen.append((start, end, title))
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
        "-ss", str(start), "-t", str(end - start), "-i", str(source),
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
    selections = select_segments(suggestions, duration, limit=8)
    if not selections:
        return {"status": "unavailable", "sent": sent,
                "errors": ["no_valid_editorial_clips"]}

    for start, end, title in selections:
        if len(sent) >= 2:
            break
        idx = len(sent) + 1
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
            for attempt in range(3):
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
                    if attempt < 2:
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

    # Recovered failures that were followed by another successful candidate
    # should stay in diagnostics, but they must not turn two delivered clips into
    # a failed session.
    return {"status": "sent" if len(sent) == 2 else
            "partial" if sent else "failed", "sent": sent, "errors": errors,
            "target": 2, "selected_count": len(selections)}


def cleanup():
    for path in (PRIVATE_DIR / "clip_01.mp4", PRIVATE_DIR / "clip_02.mp4", RECORDING):
        path.unlink(missing_ok=True)
