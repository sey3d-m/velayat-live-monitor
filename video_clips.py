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
from clip_settings import load_clip_settings

PRIVATE_DIR = Path("private_live_video")
RECORDING = PRIVATE_DIR / "programme_preview.mp4"
CAPTION_LIMIT = 900


def enabled(network=None):
    """Clip enablement is independent of all existing report channels."""
    c = load_clip_settings()
    network = network or os.getenv("NETWORK", "persian").lower()
    return (c["enabled"] and c["networks"].get(network, False)
            and os.getenv("ENABLE_BALE_VIDEO_CLIPS", "true").lower() not in ("false", "off", "0"))


def playback_speed():
    """Honor panel setting. Explicit environment override is for diagnostics only."""
    c = load_clip_settings()
    raw = os.getenv("BALE_CLIP_PLAYBACK_SPEED", "").strip()
    try:
        speed = float(raw) if raw else float(c["speed"])
    except ValueError:
        speed = float(c["speed"])
    return speed if speed in (0.75, 1.0, 1.25, 1.5) else float(c["speed"])


async def capture_video(media_url, duration):
    """Independent, low-bitrate recording; never blocks the primary audio capture."""
    if not enabled():
        return None
    PRIVATE_DIR.mkdir(exist_ok=True)
    RECORDING.unlink(missing_ok=True)
    settings = load_clip_settings()
    width = 1920 if settings["quality"] == "1080p" else 1280
    # Improve the actual recording, not just the exported MP4. Preserve 25 fps.
    rate = "4200k" if width == 1920 else "1350k"
    buffer = "8400k" if width == 1920 else "2700k"
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-reconnect", "1", "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", media_url, "-map", "0:v:0", "-map", "0:a:0?",
        "-t", str(duration),
        "-vf", f"fps=25,scale=w={width}:h=-2:force_original_aspect_ratio=decrease,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-crf", "27", "-maxrate", rate, "-bufsize", buffer,
        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0",
        "-af", "aresample=async=1:first_pts=0",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2", "-ar", "44100",
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


def transcript_candidates(timed_transcript, duration, *, min_seconds=18, max_seconds=100):
    """Group actually transcribed adjacent speech into complete eligible scenes.

    Prior versions stopped assembling speech at 50 seconds, then the delivery
    filter rejected every selection shorter than the operator's 60-second
    minimum. A long programme could therefore yield only one usable clip.
    """
    rows = []
    pattern = r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\n]+)"
    for match in re.finditer(pattern, timed_transcript or ""):
        start, end = _seconds(match.group(1)), _seconds(match.group(2))
        speech = compact_text(match.group(3), 420)
        if end <= start or start >= duration or len(speech) < 18:
            continue
        rows.append((start, min(end, duration), speech))
    rows.sort(key=lambda row: (row[0], row[1]))
    # Keep a coherent 55+ sec excerpt under legacy defaults, or respect the
    # configured minimum for actual published clips. Never invent missing speech.
    desired = min(max_seconds, max(min_seconds, 55))
    candidates = []
    for pos, (start, end, speech) in enumerate(rows):
        # A coarse transcript row may cover several minutes. Cutting its
        # first 105 seconds would assign unrelated text to the resulting video.
        if end - start > max_seconds:
            continue
        parts = [speech]
        stop = min(end, start + max_seconds, duration)
        for nxt_start, nxt_end, nxt_text in rows[pos + 1:]:
            if stop - start >= desired:
                break
            if nxt_start > stop + 10 or nxt_start - start >= max_seconds:
                break
            if nxt_end <= stop:
                continue
            parts.append(nxt_text)
            stop = min(nxt_end, start + max_seconds, duration)
        if stop - start < min_seconds:
            continue
        whole = compact_text(" ".join(parts), 370)
        question = re.search(r"[^.!؟?]{12,100}[؟?]", whole)
        title = compact_text(question.group(0) if question else speech, 90)
        cue = any(k in whole for k in (
            "چرا", "آیا", "چگونه", "شبهه", "پاسخ", "پرسش",
            "حقیقت", "اشتباه", "مهم", "سؤال", "دلیل"))
        if not cue:
            continue  # Routine text is not automatically a publishable clip.
        candidates.append(_clip_candidate(
            start, stop, title,
            "بخشی از گفت‌وگوی برنامه درباره: " + title,
            "medium" if cue else "low", origin="transcript",
            why="پرسش یا پاسخ مستقیم" if cue else "گزیده متن زمان‌دار",
        ))
    return candidates


def build_clip_candidates(analysis, timed_transcript, duration, *,
                          transcript_min_seconds=18, transcript_max_seconds=100):
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
    # Do not manufacture clips from generic key-point summaries. They
    # lack sufficiently specific boundaries for editorial publication.
    # These candidates are only based on words that occurred in the transcript.
    # AI-quality candidates naturally outrank generic transcript excerpts.
    candidates.extend(transcript_candidates(
        timed_transcript, duration, min_seconds=transcript_min_seconds,
        max_seconds=transcript_max_seconds,
    ))
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


def _topic_words(text):
    """Conservative Persian topic words, excluding generic editorial boilerplate."""
    normal = (text or "").replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
    stop = {
        "درباره", "بررسی", "بخشی", "برنامه", "گفتگو", "گفتگوی", "کارشناس",
        "موضوع", "پاسخ", "پرسش", "چگونه", "چرایی", "مهم", "چرا",
        "این", "آن", "است", "هست", "های", "برای", "اما", "آیا",
        "در", "به", "از", "که", "با", "را", "یک", "چه", "هم",
        "می", "شود", "کرد", "دارد", "دارند", "دربارۀ",
    }
    return {w for w in re.findall(r"[\wآ-ی]{4,}", normal)
            if len(w) >= 4 and w not in stop and not w.isdigit()}


def grounded_clip_candidates(suggestions, timed_transcript, duration, *,
                             min_seconds, max_seconds):
    """Do not publish AI-proposed cuts when timed speech cannot corroborate them.

    Reject coarse transcript blocks as false precision: a topic somewhere in
    a six-minute block does not prove that the suggested 90-second video
    actually discusses it.
    """
    pattern = r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\n]+)"
    rows = []
    for m in re.finditer(pattern, timed_transcript or ""):
        start, end = _seconds(m.group(1)), _seconds(m.group(2))
        if 0 <= start < end <= duration + 10:
            rows.append((start, end, _topic_words(m.group(3))))
    if not rows:
        print("Clip verification: no timestamped speech; skip uncertain clips",
              file=sys.stderr)
        return []
    safe = []
    for item in suggestions:
        try:
            start = int(item.start_sec)
            end = int(item.end_sec)
        except (AttributeError, TypeError, ValueError):
            continue
        if start < 0 or end > duration or not min_seconds <= end - start <= max_seconds:
            continue
        terms = _topic_words(compact_text(getattr(item, "media_title", ""), 140))
        if not terms:
            continue
        # A clip within one enormous transcription paragraph cannot be tied
        # to a precise sentence, even when its topic appears in that paragraph.
        corroborated = False
        for row_start, row_end, source_words in rows:
            intersection = min(end, row_end) - max(start, row_start)
            if intersection < min(12, (end - start) // 3):
                continue
            if row_end - row_start > max(165, max_seconds * 1.5):
                continue
            common = terms & source_words
            if len(common) >= (2 if len(terms) >= 4 else 1):
                corroborated = True
                break
        if corroborated:
            safe.append(item)
        else:
            print("Clip rejected: transcript does not substantiate title or timing "
                  f"({start}-{end}s)", file=sys.stderr)
    print(f"Clip evidence: {len(safe)}/{len(suggestions)} verified", flush=True)
    return safe


def select_segments(clips, duration, limit=2, min_seconds=15, max_seconds=100):
    """Editorial ranking; preserve distinct, useful non-overlapping scenes."""
    ranked = []
    for item in clips:
        try:
            start = max(0, int(getattr(item, "start_sec")))
            end = min(int(duration), int(getattr(item, "end_sec")))
        except (ValueError, TypeError, AttributeError):
            continue
        if end - start < min_seconds:
            continue
        end = min(end, start + max_seconds)
        title = compact_text(getattr(item, "media_title", ""), 100)
        if not title:
            continue
        # A longer coherent excerpt wins an exact quality tie.
        ranked.append((-_viral_score(item, start, end), -(end - start),
                       start, end, title))
    ranked.sort()
    chosen = []
    # First seek distinct headings, then permit different nonoverlapping
    # scenes with the same generic heading if that is all the model supplied.
    for distinct_titles in (True, False):
        for _negative_score, _negative_length, start, end, title in ranked:
            if any(start < b + 4 and end + 4 > a for a, b, _ in chosen):
                continue
            if distinct_titles and any(title == existing_title
                                       for _, _, existing_title in chosen):
                continue
            chosen.append((start, end, title))
            if len(chosen) >= limit:
                return chosen
    return chosen


def make_clip(source, start, end, index):
    """Decode from accurate seek, then re-encode from timestamp zero.

    Copying encoded streams at an arbitrary start can yield silent/unplayable
    B/P pictures until the next keyframe, while the audio plays normally.
    Both tracks use the same configurable playback rate; default is natural 1x.
    """
    PRIVATE_DIR.mkdir(exist_ok=True)
    dest = PRIVATE_DIR / f"clip_{index:02}.mp4"
    dest.unlink(missing_ok=True)
    settings = load_clip_settings()
    speed = playback_speed()
    width = 1920 if settings["quality"] == "1080p" else 1280
    # Allow longer selections, but aim below Bale's configured upload budget.
    seconds = max(1, end - start)
    total_bits = settings["max_upload_mb"] * 1024 * 1024 * 8 * 0.93
    audio_bps = settings["audio_bitrate_kbps"] * 1000
    video_bps = max(180_000, int(total_bits / seconds - audio_bps))
    video_bps = min(video_bps, 4_000_000 if width == 1920 else 650_000)
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-ss", str(start), "-t", str(seconds), "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"setpts=(PTS-STARTPTS)/{speed},fps=25,scale=w={width}:h=-2:force_original_aspect_ratio=decrease,setsar=1",
        "-af", f"atempo={speed},asetpts=PTS-STARTPTS",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-crf", str(settings["crf"]), "-maxrate", str(video_bps),
        "-bufsize", str(video_bps * 2),
        "-g", "50", "-c:a", "aac",
        "-b:a", f"{settings['audio_bitrate_kbps']}k",
        "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart", "-avoid_negative_ts", "make_zero",
        "-y", str(dest),
    ]
    run = subprocess.run(cmd, capture_output=True, timeout=max(180, seconds * 5))
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
        f"🎙 نام کارشناس: {expert}",
        f"📺 نام برنامه: {program}",
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
                    expert="نامشخص", date="", hashtags=None, timed_transcript=None):
    """Send clips ONLY to the configured clip-only Bale channel."""
    errors, sent = [], []
    settings = load_clip_settings()
    target_count = settings["count_per_program"]
    # Do not use the legacy BALE_CHAT_ID argument: that is for report delivery.
    clip_chat_id = settings["destination"]
    if not enabled():
        return {"status": "disabled", "sent": sent, "errors": errors}
    if not source or not Path(source).exists():
        return {"status": "unavailable", "sent": sent,
                "errors": ["live_video_unavailable"]}
    if timed_transcript is not None:
        suggestions = grounded_clip_candidates(
            suggestions, timed_transcript, duration,
            min_seconds=settings["min_seconds"],
            max_seconds=settings["max_seconds"],
        )
    else:
        # Preserve existing direct/test usage but never trim an overlong
        # suggestion to an arbitrary unrelated sub-interval.
        suggestions = [
            item for item in suggestions
            if 0 < int(getattr(item, "end_sec", 0)) -
            int(getattr(item, "start_sec", 0)) <= settings["max_seconds"]
        ]
    selections = select_segments(
        suggestions, duration, limit=max(12, target_count * 3),
        min_seconds=settings["min_seconds"], max_seconds=settings["max_seconds"],
    )
    print(f"Clip plan: {len(selections)} eligible excerpts, target={target_count}, "
          f"destination={clip_chat_id}, available={len(suggestions)}", flush=True)
    if not selections:
        return {"status": "unavailable", "sent": sent,
                "errors": ["no_valid_editorial_clips"], "target": target_count,
                "selected_count": 0, "candidate_count": len(suggestions)}

    for start, end, title in selections:
        if len(sent) >= target_count:
            break
        idx = len(sent) + len(errors) + 1
        try:
            path = make_clip(source, start, end, idx)
            if path.stat().st_size > settings["max_upload_mb"] * 1024 * 1024:
                raise RuntimeError("Clip exceeds configured upload size cap")
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
                            data={"chat_id": clip_chat_id, "caption": caption,
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
            # Never wait for the second clip or for program completion.
            try:
                from bengali_instant_dispatch import enqueue_after_sent
                enqueue_after_sent(path, index=len(sent), program=program,
                                   expert=expert, date=date, title=title,
                                   start=start, end=end)
            except Exception as bn_exc:
                print(f"Bengali handoff skipped: {bn_exc}", file=sys.stderr)
            print(f"Clip sent {len(sent)}/{target_count} to {clip_chat_id}: "
                  f"{start}-{end} seconds, {path.stat().st_size} bytes",
                  flush=True)
        except Exception as exc:
            errors.append(f"clip_{idx}: {type(exc).__name__}: {exc}")
            print(errors[-1], file=sys.stderr)

    complete = len(sent) == target_count
    return {"status": "sent" if complete else
            "partial" if sent else "failed", "sent": sent,
            "errors": [] if complete else errors,
            "warnings": errors if complete else [],
            "target": target_count, "selected_count": len(selections),
            "candidate_count": len(suggestions), "destination": clip_chat_id}


def cleanup():
    for path in PRIVATE_DIR.glob("clip_*.mp4"):
        path.unlink(missing_ok=True)
    RECORDING.unlink(missing_ok=True)
