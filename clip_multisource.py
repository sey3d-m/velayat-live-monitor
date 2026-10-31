"""Additional Didban clip sources with independent selection and a safe output cap.

The existing viral-only report and legacy clip mode remain unchanged.
"""
from __future__ import annotations
from types import SimpleNamespace

CATEGORY_QUOTAS = {"viral": 3, "question": 3, "topic": 4}
MAX_CLIPS = 10


def field(item, name, default=None):
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def build_candidates(analysis):
    items = []
    for viral in field(analysis, "viral_clips", []) or []:
        items.append(SimpleNamespace(
            start_sec=field(viral, "start_sec"), end_sec=field(viral, "end_sec"),
            media_title=field(viral, "media_title", ""),
            caption=field(viral, "caption", "") or field(viral, "angle", ""),
            angle=field(viral, "angle", ""),
            priority=field(viral, "priority", "high"),
            origin="viral", why_viral=field(viral, "why_viral", ""),
        ))
    for q in field(analysis, "audience_questions", []) or []:
        items.append(SimpleNamespace(
            start_sec=field(q, "start_sec"), end_sec=field(q, "end_sec"),
            media_title=field(q, "question", ""),
            caption=field(q, "answer_summary", ""),
            angle=field(q, "answer_summary", ""),
            priority="medium", origin="question",
            why_viral="پرسش مخاطب و پاسخ کارشناس",
        ))
    for point in field(analysis, "key_points", []) or []:
        items.append(SimpleNamespace(
            start_sec=field(point, "start_sec"), end_sec=field(point, "end_sec"),
            media_title=field(point, "title", ""),
            caption="محور اصلی گفت‌وگو: " + str(field(point, "title", "")),
            angle=field(point, "title", ""),
            priority="medium", origin="topic",
            why_viral="بخش محوری برنامه",
        ))
    return items


def select_mixed_segments(items, duration, *, maximum=MAX_CLIPS,
                          min_seconds=30, max_seconds=1800):
    """Select distinct whole intervals from viral/Q&A/topic report entries.

    Unverified timecodes are not guessed, shortened, or extended. Categories
    have separate quotas so viral suggestions cannot crowd out Q&A and topics.
    """
    maximum = max(1, min(MAX_CLIPS, int(maximum)))
    groups = {"viral": [], "question": [], "topic": []}
    for item in items:
        category = field(item, "origin", "")
        if category not in groups:
            continue
        try:
            start, end = int(field(item, "start_sec")), int(field(item, "end_sec"))
        except (ValueError, TypeError):
            continue
        title = " ".join(str(field(item, "media_title", "")).split())[:110]
        if not title or start < 0 or end > duration + 2:
            continue
        if not (min_seconds <= end - start <= max_seconds):
            continue
        groups[category].append((start, end, title, category))

    chosen = []
    def add(item):
        a, b, title, origin = item
        for x, y, old_title, _ in chosen:
            if old_title == title:
                return False
            # Prevent duplicate or partially overlapping published clips.
            if a < y + 2 and b > x - 2:
                return False
        chosen.append(item)
        return True

    # Prioritize credible high-interest clips, then genuine viewer Q&A,
    # then the main substantive axes of the broadcast.
    for category in ("viral", "question", "topic"):
        accepted = 0
        for item in groups[category]:
            if len(chosen) >= maximum or accepted >= CATEGORY_QUOTAS[category]:
                break
            if add(item):
                accepted += 1

    # Backfill remaining slots from all source types, while respecting overlap.
    if len(chosen) < maximum:
        for category in ("viral", "question", "topic"):
            for item in groups[category]:
                if len(chosen) >= maximum:
                    break
                add(item)
    return [(a, b, title) for a, b, title, _ in chosen]
