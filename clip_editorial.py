"""Non-disruptive editorial refinements for already selected Didban clips.

No change to the report, selection ranking, delivery destination or dubbing.
The functions are optional and fall back to the original verified timecodes.
"""
import re
import subprocess

STOPWORDS = {
    "بررسی", "درباره", "گفتگو", "برنامه", "پرسش", "پاسخ", "موضوع",
    "ایشان", "توضیح", "توضیحات", "قسمت", "بخشی", "چگونه", "برای",
    "خواهد", "استدلال", "سوال", "سؤال", "چرا", "آیا", "واقعاً",
    "سخنان", "اشاره", "کرده", "شده", "می‌شود", "می‌کند",
}


def polish_title(raw):
    """Improve generic openings without making new factual claims."""
    title = re.sub(r"\s+", " ", str(raw or "")).strip()
    candidate = re.sub(
        r"^(?:نگاهی به|بررسی موضوع|گفت[‌ ]?وگو درباره|بحثی درباره)\s*[:：،-]?\s*",
        "", title).strip()
    if len(candidate) >= 12:
        title = candidate
    if re.match(r"^(?:چرا|آیا|چگونه|چطور)\s", title) and not title.endswith(("؟", "?")):
        title += "؟"
    return title[:110].rstrip(" ،؛.")


def topic_hashtags(title, description, suggested):
    """Derive hashtags from the actual chosen clip, not the whole programme."""
    subject = (str(title or "") + " " + str(description or "")).replace("ي", "ی").replace("ك", "ک")
    natural = subject.replace("\u200c", " ")
    tags = []
    for phrase, tag in (
        ("امام علی", "#امام_علی"), ("حدیث غدیر", "#حدیث_غدیر"),
        ("امام زمان", "#امام_زمان"), ("اهل بیت", "#اهل_بیت"),
        ("قرآن کریم", "#قرآن_کریم"),
    ):
        if phrase in natural:
            tags.append(tag)
    for source in suggested or []:
        tag = str(source).strip().lstrip("#").replace("_", " ")
        if len(tag) >= 4 and tag in natural:
            tags.append("#" + tag.replace(" ", "_"))
    words = re.findall(r"[\wآ-ی]{4,}", str(title or "").replace("\u200c", " "))
    for word in words:
        if word not in STOPWORDS and not word.isdigit():
            tags.append("#" + word)
    if not tags:
        tags.extend(suggested or [])
    seen = []
    for tag in tags:
        tag = "#" + re.sub(r"[^\w\u200c]", "", str(tag).lstrip("#").replace(" ", "_"))
        if len(tag) >= 5 and tag not in seen:
            seen.append(tag)
        if len(seen) >= 4:
            break
    return seen


def _silences(source, offset, seconds):
    if seconds <= 0:
        return [], []
    cmd = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info",
        "-ss", f"{offset:.3f}", "-t", f"{seconds:.3f}",
        "-i", str(source), "-vn",
        "-af", "asetpts=PTS-STARTPTS,silencedetect=noise=-32dB:d=0.45",
        "-f", "null", "-",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=45)
        if proc.returncode:
            return [], []
        log = proc.stderr.decode("utf-8", "replace")
        return ([float(v) for v in re.findall(r"silence_start:\s*([\d.]+)", log)],
                [float(v) for v in re.findall(r"silence_end:\s*([\d.]+)", log)])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return [], []


def snap_to_pauses(source, start, end, recording_duration, max_seconds):
    """Widen cuts toward natural speech pauses only when verified by audio.

    Never shorten speech, change content selection, or exceed safe duration.
    For music/noisy speech without detectable pauses the original cut survives.
    """
    if start < 0 or end <= start or end > recording_duration + 0.1:
        return start, end
    head_offset = max(0, start - 12.0)
    _, ends = _silences(source, head_offset, min(13., recording_duration - head_offset))
    earlier = [head_offset + value for value in ends
               if start - 10. <= head_offset + value <= start + 0.05]
    new_start = max(earlier) if earlier else start

    tail_offset = max(0, end - 1.)
    starts, _ = _silences(source, tail_offset, min(10., recording_duration - tail_offset))
    later = [tail_offset + value for value in starts
             if end - 0.05 <= tail_offset + value <= min(recording_duration, end + 8.)]
    new_end = min(later) if later else end
    if new_end - new_start > max_seconds:
        return start, end
    if (new_start, new_end) != (start, end):
        print(f"Verified speech pause alignment: {start:.2f}-{end:.2f} -> "
              f"{new_start:.2f}-{new_end:.2f}", flush=True)
    return new_start, new_end
