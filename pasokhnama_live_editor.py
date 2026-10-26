#!/usr/bin/env python3
"""Fail-closed Persian TV copy editor for isolated Pasokhnama captions.

Uses EXISTING optional GEMINI_API_KEY. An edited caption is NOT a scholarly
verification, verified speaker quote, or source citation. Ambiguous speech
and missing API/quota yield no television item rather than invented facts.
"""
from __future__ import annotations
import json
import os
import re
import urllib.error
import urllib.request

MODEL = os.environ.get("PASOKHNAMA_EDIT_MODEL", "gemini-3.5-flash-lite")
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models/"
MAX_SOURCE = 2600
PROMPT = """نقش: دبیر علمی فارسیِ پاسخ‌نمای زنده شبکه ولایت؛ خروجی، بازنویسی ماشینی و تأییدنشده است.
منبع منحصر‌به‌فرد تو رونوشت کوتاه و احتمالاً خطادار تشخیص گفتار است.

کار اصلی:
- موضوع را به جای «فضائل اهل‌بیت» یا «بررسی ابعاد مختلف»، به یک نکته کوچک و
  مشخص در همین قطعه محدود کن: پرسش جزئی، ادعای مطرح‌شده، نوع استدلال، شاهد
  واقعاً نام‌برده‌شده و نتیجه‌ای که خود گوینده واقعاً بیان کرده است.
- اگر چند بحث مستقل وجود دارد، دقیق‌ترین و جدیدترین نکته روشن را انتخاب کن؛
  مطالب نامرتبطِ قبلی یا پیش‌بینی ادامه سخن را اضافه نکن.
- تیتر کوتاه و دقیق باشد و کلیدواژه متمایز همان ادعا/استدلال را داشته باشد؛
  از تیترهای کلی «بررسی فضائل...»، «گفت‌وگو درباره موضوعات...» پرهیز کن.
- خلاصه ۴۰ تا ۷۰ واژه در صورت وجود داده کافی، حداکثر ۳۹۰ نویسه و مناسب آنتن.
  ساختار پیشنهادی: نکته مشخص، سخن/استدلال گوینده با نسبت‌دادن روشن، شاهد
  لفظاً موجود در رونوشت، و نتیجه محدود همان بخش.
- هر ادعای تاریخی، کلامی، فقهی و تفسیری را فقط به عنوان «به گفته کارشناس»،
  «در این بخش مطرح شد» یا «کارشناس استدلال می‌کند» گزارش کن؛ آن را به
  صورت حقیقت تأییدشده، پاسخ قطعی یا فتوای مستقل بازنویسی نکن.
- برای مباحث دینی همیشه scope=topic_only؛ این scope مانع گزارش جزئیات
  قابل اتکای گفتار در قالب نقل غیرمستقیم نیست، اما مانع تأیید صحت آن است.
  برای گفتار غیرعلمی/غیردینیِ کاملاً روشن scope=explanation مجاز است.
- عنوان scope=topic_only باید با «بررسی»، «پرسش درباره» یا «گفت‌وگو درباره»
  و خلاصه با «در این بخش» یا «در گفت‌وگو» آغاز شود.
- تنها در صورت ذکر آشکار در خود رونوشت، نام آیه/سوره، کتاب، راوی، شخص،
  عدد یا نقل‌قول را گزارش کن. آدرس آیه/شماره حدیث/نام کتاب را حدس نزن.
  نام نامطمئن، کلمات مبهم یا حکم حدسی را حذف کن و جزئیات مطمئن را نگه دار.
- متن طبیعی و دقیق فارسی، املا و نیم‌فاصله صحیح، بدون زبان کلیشه‌ای باشد.
  نقل‌قول مستقیم فقط اگر کاملاً قابل اطمینان است؛ اصولاً نقل غیرمستقیم را ترجیح بده.
- evidence_excerpt باید حداقل ۲۰ نویسه و عیناً تکه‌ای پیوسته از رونوشت باشد
  که نکته اصلی خروجی را پشتیبانی کند. اگر شاهد کافی نیست publish=false.
- هیچ پاسخ، نتیجه، تفسیر، منبع، نام، فتوا یا ادعای بیرون از رونوشت نساز.
- پرسش بی‌پاسخ را فقط به صورت پرسش گزارش کن.
- خروجی تیتر ۱۲ تا ۸۰ نویسه و متن ۷۰ تا ۳۹۰ نویسه، confidence واقع‌بینانه.
- فقط JSON، بدون توضیح اضافی:
{"publish":true,"scope":"topic_only","title":"...","summary":"...","evidence_excerpt":"...","confidence":0.0}
یا در صورت نامفهوم بودن:
{"publish":false,"scope":"topic_only","title":"","summary":"","evidence_excerpt":"","confidence":0.0}

رونوشت:
"""


def clean(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = value.replace("ي", "ی").replace("ك", "ک")
    return value


def validate(source: str, result: object) -> dict | None:
    """Never present ungrounded or unstructured LLM output on television."""
    if not isinstance(result, dict) or result.get("publish") is not True:
        return None
    title = clean(result.get("title"))
    summary = clean(result.get("summary"))
    evidence = str(result.get("evidence_excerpt") or "").strip()
    try:
        confidence = float(result.get("confidence", 0))
    except (ValueError, TypeError):
        return None
    scope = result.get("scope", "explanation")
    if scope not in ("explanation", "topic_only"):
        return None
    # Religious rulings or attributed scholarly claims need verification,
    # not merely linguistic rewriting of noisy speech recognition.
    religious_topic = re.search(
        r"نماز|اذان|اقامه|غسل|وضو|خمس|روزه|زکات|احکام|فقه|حرام|حلال|"
        r"روایت|حدیث|قرآن|آیه|سوره|امام|اهل\s*بیت|شیعه|سنی|ولایت|غدیر|"
        r"پیامبر|رسول|مهدی|زیارت|دعا|عاشورا|فاطمه|توحید|شرک", source)
    if religious_topic and scope != "topic_only":
        return None
    if not (0.78 if scope == "topic_only" else 0.85) <= confidence <= 1.0:
        return None
    if not (12 <= len(title) <= 80 and (70 if scope == "topic_only" else 85) <= len(summary) <= 390):
        return None
    if scope == "topic_only":
        if not title.startswith(("بررسی", "پرسش درباره", "گفت‌وگو درباره")):
            return None
        if not summary.startswith(("در این بخش", "در گفت‌وگو")):
            return None
        if any(claim in summary for claim in (
            "واجب است", "واجب‌اند", "حرام است", "حلال است", "جایز است",
            "مستحب است", "مستحب‌اند", "لازم نیست", "اشکالی ندارد",
            "باید انجام", "ضروری است", "می‌توان", "می‌شود انجام داد",
            "صحیح است", "باطل است", "نجس است", "پاک است", "نیاز نیست",
        )):
            return None
    if len(evidence) < 20 or evidence not in source:
        return None
    if any(x in title + summary for x in ("<script", "</", "###", "http://", "https://")):
        return None
    if set(re.findall(r"\d+", title + " " + summary)) - set(re.findall(r"\d+", source)):
        return None
    if re.search(r"(?:سوره\s+\S+|آیه\s+\d+|روایت\s+از\s+\S+)", title + " " + summary):
        if not re.search(r"سوره|آیه|روایت", source):
            return None
    return {
        "title": title,
        "summary": summary,
        "kind": "edited_transcript",
        "scope": scope,
        "verification_status": "machine_edited_unverified",
        "editor_confidence": round(confidence, 3),
    }


# The deterministic safety net identifies ONLY literal topics in the ASR.
# It never tries to derive religious rules, quotations or scholarly answers.
KNOWN_TOPICS = (
    ("اذان و اقامه", ("اذان", "اقامه")),
    ("نماز شب", ("نماز شب",)),
    ("نماز جماعت", ("نماز جماعت", "جماعت")),
    ("نماز", ("نماز",)),
    ("احکام طهارت", ("وضو", "غسل", "نجاست", "نجس", "پاکی")),
    ("روزه", ("روزه", "روزه‌")),
    ("خمس و زکات", ("خمس", "زکات")),
    ("زیارت", ("زیارت", "زائر", "حرم")),
    ("امام حسین و عاشورا", ("عاشورا", "امام حسین", "کربلا")),
    ("حضرت عباس", ("حضرت عباس", "ابوالفضل", "عباس")),
    ("امام زمان", ("امام زمان", "مهدوی", "ظهور")),
    ("ولایت و غدیر", ("غدیر", "ولایت")),
    ("قرآن و تفسیر", ("قرآن", "تفسیر")),
    ("حدیث و روایت", ("حدیث", "روایت")),
    ("اعتقادات اسلامی", ("توحید", "امامت", "نبوت", "معاد")),
    ("گفت‌وگوی مذاهب اسلامی", ("مذاهب", "شیعه", "اهل سنت", "وهابیت")),
    ("خانواده و ازدواج", ("ازدواج", "خانواده", "همسر", "طلاق")),
    ("تربیت و اخلاق", ("اخلاق", "تربیت", "حجاب")),
)


def grounded_topic(source: str) -> dict | None:
    """Last-resort, explicitly generic TV headline; requires repeated source terms.

    Never claims religious/medical/legal correctness. Nothing guessed if speech
    has no stable literal recognizable topic.
    """
    cleaned = clean(source)
    if len(cleaned) < 150 or sum("\u0600" <= ch <= "\u06ff" for ch in cleaned) < 90:
        return None
    matches = []
    for topic, terms in KNOWN_TOPICS:
        count = sum(cleaned.count(term) for term in terms)
        if count >= 2:
            matches.append((count, topic))
    if not matches:
        return None
    # Prefer more precise topics over the umbrella of "نماز" where possible.
    matches.sort(key=lambda pair: (pair[0], len(pair[1])), reverse=True)
    topic = matches[0][1]
    title = "گفت‌وگو درباره " + topic
    summary = (
        "در این بخش از برنامه، موضوع «" + topic
        + "» در گفت‌وگو مطرح شده است. عنوان بر اساس واژه‌های تشخیص‌داده‌شده "
          "از صوت تهیه شده و به معنای تأیید جزئیات مطالب یا اعلام حکم شرعی نیست."
    )
    return {
        "title": title, "summary": summary,
        "kind": "edited_transcript", "scope": "topic_only",
        "verification_status": "machine_edited_unverified",
        "editor_mode": "grounded_topic_fallback",
        "editor_confidence": 0.0,
    }


def rewrite(source: str, api_key: str, model: str = MODEL, timeout: int = 35) -> dict | None:
    """Return edited caption or None. Never publish a raw ASR fallback."""
    source = source.strip()[:MAX_SOURCE]
    if not api_key or len(source) < 140:
        return None
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", model):
        raise ValueError("Invalid editor model name")
    request_body = {
        "contents": [{"role": "user", "parts": [{"text": PROMPT + source}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    req = urllib.request.Request(
        API_ROOT + model + ":generateContent",
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read(120000).decode("utf-8"))
        candidates = data.get("candidates") or []
        if not candidates:
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        answer = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return validate(source, json.loads(answer))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Persian editor provider HTTP status " + str(exc.code)) from None
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("Persian editor output unavailable: " + type(exc).__name__) from None
