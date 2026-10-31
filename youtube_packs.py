"""Independent TEXT-ONLY YouTube editorial packs for Persian Didban programmes.

No changes to reports, transcripts, clips, dashboards or original Bale destinations.
All edit timecodes are drawn from the existing structured programme analysis.
A single optional Gemini request improves wording; failure yields factual drafts.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

DESTINATION = "@vtv_youtube"
MIN_PACKS = 4
MAX_MESSAGE_CHARS = 3700
MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class EditSegment:
    number: int
    source: str
    start_sec: int
    end_sec: int
    topic: str
    evidence: str


class YouTubeDraft(BaseModel):
    number: int
    title_options: list[str] = Field(default_factory=list)
    thumbnail_text: str = ""
    description_fa: str = ""
    english_summary: str = ""
    main_points: list[str] = Field(default_factory=list)
    seo_keywords: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    pinned_comment: str = ""


class YouTubeBatch(BaseModel):
    packs: list[YouTubeDraft]


def enabled(network: str = "persian") -> bool:
    return (network == "persian"
            and os.getenv("ENABLE_YOUTUBE_PACKS", "true").strip().lower()
            not in ("0", "false", "off", "no"))


def _clean(value: Any, limit: int = 1200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _clock(s: int) -> str:
    s = max(0, int(s))
    return f"{s // 3600:02}:{(s % 3600) // 60:02}:{s % 60:02}"


def _field(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _transcribed_rows(text: str) -> list[tuple[int, int, str]]:
    rows = []
    pattern = r"\[(\d{2}:\d{2}(?::\d{2})?)\s*-\s*(\d{2}:\d{2}(?::\d{2})?)\]\s*([^\n]+)"
    def secs(clock):
        nums = [int(x) for x in clock.split(":")]
        return nums[-1] + 60 * nums[-2] + (3600 * nums[-3] if len(nums) == 3 else 0)
    for match in re.finditer(pattern, text or ""):
        start, end = secs(match.group(1)), secs(match.group(2))
        if 0 <= start < end:
            rows.append((start, end, _clean(match.group(3), 900)))
    return rows


def _local_evidence(rows, start, end, limit=2100):
    evidence = [speech for a, b, speech in rows
                if max(a, start) < min(b, end) and speech]
    return _clean(" ".join(evidence), limit)


def build_edit_plan(analysis: Any, timed_transcript: str,
                    duration: int, minimum: int = MIN_PACKS) -> list[EditSegment]:
    """Select independent grounded ranges; never invent timestamps or references.

    Key points are preferred for independent YouTube videos, then real answered
    audience questions and viral excerpts. Coarse transcript rows are NOT used
    to manufacture edit boundaries.
    """
    if duration <= 0:
        return []
    rows = _transcribed_rows(timed_transcript)
    raw = []
    groups = (
        ("محور اصلی", _field(analysis, "key_points", []) or [], "title", "title"),
        ("پرسش و پاسخ", _field(analysis, "audience_questions", []) or [],
         "question", "answer_summary"),
        ("سوژه وایرال", _field(analysis, "viral_clips", []) or [],
         "media_title", "caption"),
    )
    for kind, items, title_field, detail_field in groups:
        for item in items:
            try:
                start, end = int(_field(item, "start_sec")), int(_field(item, "end_sec"))
            except (TypeError, ValueError):
                continue
            title = _clean(_field(item, title_field), 170)
            if not title or start < 0 or end > duration + 2 or end <= start:
                continue
            # Only complete, editorially practical videos. Do not cut an arbitrary
            # part of a longer segment and pretend it is a clean speech boundary.
            if not 30 <= end - start <= 1800:
                continue
            evidence = _local_evidence(rows, start, end)
            if not evidence:
                detail = _field(item, detail_field, "")
                evidence = _clean(detail, 650)
            if not evidence:
                continue
            raw.append((kind, start, end, title, evidence))

    chosen: list[tuple[str, int, int, str, str]] = []
    for item in raw:
        kind, start, end, title, evidence = item
        # A second pack must have a substantially different passage.
        if any(max(0, min(end, b) - max(start, a)) >=
               0.35 * min(end - start, b - a) for _, a, b, _, _ in chosen):
            continue
        if any(_clean(title, 70) == _clean(t, 70) for _, _, _, t, _ in chosen):
            continue
        chosen.append(item)
        if len(chosen) >= max(minimum, 4):
            break
    return [EditSegment(i, k, a, b, t, e)
            for i, (k, a, b, t, e) in enumerate(chosen, 1)]


def _fallback_draft(segment: EditSegment, analysis: Any) -> YouTubeDraft:
    title = segment.topic
    summary = _clean(segment.evidence, 1150)
    expert = _clean(_field(analysis, "expert", "نامشخص"), 80)
    name = expert if expert and expert != "نامشخص" else "کارشناس برنامه"
    return YouTubeDraft(
        number=segment.number,
        title_options=[title, "پشت پرده یک پرسش مهم: " + title,
                       title + " | بررسی مستند در شبکه ولایت"],
        thumbnail_text=title[:60],
        description_fa=(f"در این بخش از برنامه، {name} به موضوع «{title}» می‌پردازد. "
                        f"متن و محور گفت‌وگو: {summary}\n\n"
                        "این ویدیو بخشی از گفت‌وگو است؛ ادعاها و استدلال‌ها را "
                        "در متن کامل و با مراجعه به منابع مطرح‌شده در برنامه بررسی کنید."),
        english_summary=(f"This Persian-language discussion examines: {title}. "
                         "It presents the speaker's arguments and questions; "
                         "viewers are encouraged to review the full discussion "
                         "and verify references in context."),
        main_points=[title],
        seo_keywords=[_clean(_field(analysis, "topic", ""), 100), title],
        hashtags=list(_field(analysis, "hashtags", []) or [])[:5],
        pinned_comment="مهم‌ترین پرسش یا نقد مستند شما درباره این بحث چیست؟",
    )


def _prompt(segments: list[EditSegment], analysis: Any, programme: str) -> str:
    payload = [{"number": s.number, "source": s.source, "topic": s.topic,
                "from": _clock(s.start_sec), "to": _clock(s.end_sec),
                "transcript_evidence": s.evidence} for s in segments]
    return (
        "شما سردبیر حرفه‌ای بسته‌بندی یوتیوب شبکه ولایت هستید. "
        "صرفاً برای هر ورودی زیر یک بسته مستقل فارسی/انگلیسی بساز. "
        "دقیقاً به تعداد ورودی‌ها خروجی بده و number را بی‌تغییر نگه دار. "
        "هر بسته فقط درباره همان بازه باشد، نه کل برنامه. "
        "title_options: سه تیتر جذاب و چالش‌برانگیز اما کاملاً دقیق، بدون جعل و قطعیت‌بخشی به ادعاها. "
        "thumbnail_text: تیتر کوتاه برای تدوینگر، فقط متن (هیچ تصویری تولید نکن). "
        "description_fa: توضیحات روان، مبسوط، چندبخشی، ویژه یوتیوب (حدود 200 تا 350 واژه اگر شواهد کافی باشد). "
        "english_summary: یک خلاصه طبیعی انگلیسی 80 تا 140 واژه درباره بحث همان قطعه، "
        "نه ترجمه ماشینی و نه ادعای اثبات‌نشده. "
        "main_points: سه تا شش محور اختصاصی و واقعی همین بازه. "
        "seo_keywords: پنج تا ده کلیدواژه واقعی. hashtags: 4 تا 8 هشتگ مناسب فارسی. "
        "pinned_comment: پرسش مشخص برای گفت‌وگوی مخاطبان. "
        "قواعد قطعی: تنها شواهد داده‌شده مجازند؛ هر کتاب، نقل، آیه، نام شخص و رخداد "
        "را فقط وقتی در شواهد آمده نام ببر؛ نقل‌قول و منبع نساز؛ "
        "نام کارشناس اگر نامشخص است جعل نکن. "
        "رویدادهای اختلافی را «به روایت/از منظر گوینده» توضیح بده. "
        "هیچ زمانی در خروجی تولید نکن؛ زمان‌های قطعی توسط نرم‌افزار افزوده می‌شوند. "
        "اگر شواهد کم است، متن کوتاه‌تر و دقیق‌تر باشد؛ از حشو خودداری کن.\n"
        f"نام برنامه: {programme}\n"
        f"کارشناس طبق گزارش: {_clean(_field(analysis, 'expert', 'نامشخص'))}\n"
        f"موضوع کلی: {_clean(_field(analysis, 'topic', ''), 250)}\n"
        f"بازه‌ها و شواهد زمان‌دار: {json.dumps(payload, ensure_ascii=False)}"
    )


def generate_drafts(client: Any, analysis: Any, segments: list[EditSegment],
                    programme: str) -> tuple[list[YouTubeDraft], str]:
    """At most ONE extra model request; fail closed to source-based text drafts."""
    fallbacks = {s.number: _fallback_draft(s, analysis) for s in segments}
    if not segments:
        return [], "no_verified_segments"
    if client is None or os.getenv("YOUTUBE_PACKS_AI", "true").lower() in ("0", "false", "off"):
        return list(fallbacks.values()), "fallback_no_ai"
    try:
        interaction = client.interactions.create(
            model=os.getenv("YOUTUBE_PACKS_MODEL", MODEL),
            input=_prompt(segments, analysis, programme),
            response_format={"type": "text", "mime_type": "application/json",
                             "schema": YouTubeBatch.model_json_schema()},
        )
        batch = YouTubeBatch.model_validate_json(interaction.output_text or "{}")
        by_id = {draft.number: draft for draft in batch.packs
                 if draft.number in fallbacks}
        final = []
        for seg in segments:
            draft = by_id.get(seg.number)
            if not draft or not draft.description_fa.strip() or not draft.title_options:
                draft = fallbacks[seg.number]
            # AI has no authority to change timecodes, or add unsupported segments.
            final.append(draft)
        return final, "ai"
    except Exception as exc:
        print(f"YouTube packs generation fallback: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return list(fallbacks.values()), "fallback_model_error"


def _tags(tags: list[str]) -> str:
    seen = []
    for raw in tags:
        tag = _clean(raw, 65).lstrip("#").replace(" ", "_")
        tag = re.sub(r"[^\w\u200c]", "", tag)
        if len(tag) >= 3 and ("#" + tag) not in seen:
            seen.append("#" + tag)
    return " ".join(seen[:10])


def format_pack(segment: EditSegment, draft: YouTubeDraft, *,
                programme: str, date: str, expert: str) -> str:
    """The editorial timecodes are source-derived, not generated by Gemini."""
    titles = [t for t in (_clean(t, 125) for t in draft.title_options) if t][:3]
    titles = titles or [segment.topic]
    axes = "\n".join("- " + _clean(x, 230) for x in draft.main_points[:8] if _clean(x))
    keywords = "، ".join(_clean(k, 75) for k in draft.seo_keywords[:10] if _clean(k))
    return (
        f"🎬 پک یوتیوب {segment.number} | {programme}\n"
        f"📅 تاریخ برنامه: {date}\n"
        f"🎙 کارشناس: {expert}\n"
        f"🏷 دسته استخراج: {segment.source}\n"
        f"✂️ دستور تدوین: شروع {_clock(segment.start_sec)} | پایان {_clock(segment.end_sec)}"
        f" | مدت {_clock(segment.end_sec - segment.start_sec)}\n"
        "⚠️ زمان‌ها نسبت به آغاز برنامه هستند و باید روی فایل اصلی تطبیق شوند.\n\n"
        "🔥 سه تیتر پیشنهادی:\n"
        + "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
        + f"\n\n🖼 متن پیشنهادی کاور (صرفاً متن): {_clean(draft.thumbnail_text, 85)}"
        + f"\n\n📝 توضیحات آماده یوتیوب:\n{draft.description_fa.strip()}"
        + f"\n\n🌐 English summary:\n{draft.english_summary.strip()}"
        + f"\n\n📌 محورهای اصلی همین قطعه:\n{axes}"
        + f"\n\n🔎 کلیدواژه‌های سئو: {keywords}"
        + f"\n\n💬 نظر سنجی / کامنت پین‌شده:\n{draft.pinned_comment.strip()}"
        + "\n\n📣 برای پیگیری بحث، ویدیو را ببینید، دیدگاه مستندتان را بنویسید "
          "و کانال را دنبال کنید."
        + f"\n\n{_tags(draft.hashtags)}"
    )


def _chunks(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut < 500:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip()
    return chunks


def send_text_packs(token: str, segments: list[EditSegment],
                    drafts: list[YouTubeDraft], *, programme: str,
                    date: str, expert: str, chat_id: str = DESTINATION) -> dict:
    """Send ONLY sendMessage, never video, image, document or main report output."""
    if not token or not segments:
        return {"status": "unavailable", "sent": 0, "expected": MIN_PACKS,
                "errors": ["no_token_or_verified_sections"]}
    if chat_id != DESTINATION:
        raise ValueError("YouTube packs may only be sent to @vtv_youtube")
    by_id = {x.number: x for x in drafts}
    sent, errors = 0, []
    endpoint = f"https://tapi.bale.ai/bot{token}/sendMessage"
    for segment in segments:
        draft = by_id.get(segment.number)
        if draft is None:
            errors.append(f"pack_{segment.number}: missing draft")
            continue
        message = format_pack(segment, draft, programme=programme, date=date, expert=expert)
        chunks = _chunks(message)
        try:
            for index, chunk in enumerate(chunks, 1):
                content = (f"📄 بخش {index}/{len(chunks)} | پک {segment.number}\n"
                           + chunk) if len(chunks) > 1 else chunk
                payload = json.dumps({"chat_id": chat_id, "text": content},
                                     ensure_ascii=False).encode("utf-8")
                for attempt in range(2):
                    try:
                        request = urllib.request.Request(
                            endpoint, data=payload, method="POST",
                            headers={"Content-Type": "application/json; charset=utf-8"})
                        with urllib.request.urlopen(request, timeout=30) as response:
                            result = json.loads(response.read().decode("utf-8"))
                        if result.get("ok") is not True:
                            raise RuntimeError("Bale sendMessage rejected pack")
                        break
                    except Exception:
                        if attempt == 1:
                            raise
                        time.sleep(2)
                time.sleep(0.2)
            sent += 1
        except Exception as exc:
            errors.append(f"pack_{segment.number}: {type(exc).__name__}: {exc}")
    return {"status": ("sent" if sent == len(segments) and sent >= MIN_PACKS else
                       "partial" if sent else "failed"),
            "sent": sent, "expected": max(MIN_PACKS, len(segments)),
            "errors": errors, "destination": chat_id}


def produce_youtube_packs(client: Any, analysis: Any, timed_transcript: str,
                          duration: int, token: str, *, programme: str,
                          date: str, expert: str) -> dict:
    segments = build_edit_plan(analysis, timed_transcript, duration)
    if not segments:
        return {"status": "unavailable", "sent": 0, "expected": MIN_PACKS,
                "errors": ["no_verified_edit_intervals"]}
    drafts, generation = generate_drafts(client, analysis, segments, programme)
    result = send_text_packs(token, segments, drafts, programme=programme,
                             date=date, expert=expert)
    result["generation"] = generation
    result["edit_intervals"] = [
        {"start_sec": s.start_sec, "end_sec": s.end_sec, "topic": s.topic}
        for s in segments]
    if len(segments) < MIN_PACKS:
        result.setdefault("errors", []).append("fewer_than_four_verified_topics")
    return result
