"""Evidence-aware second pass for concrete scholarly claims in Persian TV.

A model conclusion is never marked source-verified merely because the model
supplied a book title. Verified excerpts require an allowlisted Shi'a webpage
present in the API's grounding metadata AND a matching fetched quotation.
"""
import html
import json
import os
import re
import sys
from urllib.parse import urlsplit
import requests
from google.genai import types

RESEARCH_MODEL = os.getenv("SCHOLARLY_REVIEW_MODEL","gemini-3.8-flash").strip()
SHIA_DOMAINS = (
    "al-islam.org", "hadith.inoor.ir", "noorlib.ir", "lib.eshia.ir",
    "shiaonlinelibrary.com", "makarem.ir", "sistani.org",
    "wikishia.net", "islamquest.net", "hawzah.net",
)
# Web results from an allowed domain are not automatically reliable scholarship:
# they still require a relevant direct quote, and editorial review.
MAX_QUOTE_BYTES = 190000

def enabled():
    return os.getenv("ENABLE_SCHOLARLY_REVIEW","true").lower() not in ("0","false","off")

def safe_url(url):
    if not isinstance(url,str) or len(url)>1800:
        return False
    try:
        x=urlsplit(url)
        host=(x.hostname or "").lower().rstrip(".")
        return (x.scheme=="https" and not x.username and not x.password
                and x.port in (None,443) and
                any(host==d or host.endswith("."+d) for d in SHIA_DOMAINS))
    except ValueError:
        return False

def normalize(text):
    text=html.unescape(str(text or "")).replace("ي","ی").replace("ك","ک")
    text=re.sub(r"[\u064b-\u065f\u0670\u200c\u200d]","",text)
    return re.sub(r"[^\w]+","",text).lower()

def retrieve_exact_quote(url, quote):
    """No redirects: never fetch an arbitrary model-controlled URL."""
    if not safe_url(url) or len(normalize(quote)) < 18:
        return False
    try:
        with requests.get(url,timeout=8,allow_redirects=False,stream=True,
                          headers={"User-Agent":"VelayatSourceCheck/1.0"}) as r:
            if r.status_code!=200 or "text/html" not in r.headers.get("Content-Type",""):
                return False
            data=bytearray()
            for block in r.iter_content(16384):
                data.extend(block)
                if len(data)>MAX_QUOTE_BYTES:
                    break
            text=data.decode(r.encoding or "utf-8","replace")
        text=re.sub(r"<(script|style)\b[^>]*>.*?</\1>"," ",text,flags=re.I|re.S)
        text=re.sub(r"<[^>]+>"," ",text)
        return normalize(quote) in normalize(text)
    except requests.RequestException:
        return False

def grounding_urls(response):
    urls=set()
    for candidate in (getattr(response,"candidates",None) or []):
        meta=getattr(candidate,"grounding_metadata",None)
        if meta is None:
            continue
        for item in (getattr(meta,"grounding_chunks",None) or []):
            web=getattr(item,"web",None)
            url=getattr(web,"uri",None)
            if safe_url(url):
                urls.add(url.rstrip("/"))
    return urls

def source_prompt(issue, transcript):
    return """وظیفه: داوری مستند درباره یک ادعای مشخص مطرح‌شده در برنامه شبکه ولایت، بر اساس
متون شیعی امامیه. جست‌وجوی واقعی در منابع را انجام بده. نام کتاب، جلد، صفحه،
حدیث، سند، عبارت عربی و URL را هرگز از حافظه جعل نکن.
اول مشخص کن گوینده دقیقاً چه ادعایی کرده؛ ضبط ممکن است خطای پیاده‌سازی داشته باشد.
اگر نسبت ادعا به شخص از رونوشت روشن نیست، ذکر کن.
در اولویت از متن اصلی حدیث/قرآن، آثار حدیثی معتبر امامیه، سپس آثار محققان شیعی بهره ببر.
بین صحت وجود نقل در منبع، اعتبار سند، و درستی برداشت از آن فرق بگذار؛
صرف یافتن روایت به معنی تصحیح سند یا تأیید کل ادعا نیست.
نتیجه باید مشخص و استدلالی باشد، اما اگر منبع کافی پیدا نکردی صریحاً بگو.
از پیوندهای واقعی که جست‌وجو برگردانده استفاده کن. فقط JSON بده با کلیدهای:
claim_quote (عبارت ادعا از رونوشت)، assessment (داوری تحلیلی مفصل اما فشرده)،
recommended_correction (صورت علمی دقیق‌تر)، source_title (نام مأخذ)،
source_url (نشانی مستقیم متن شیعی)، source_quote (عبارت عیناً درج‌شده در همان صفحه)،
confidence (high/medium/low).
توجه: تأیید منبع در نرم‌افزار جداگانه و سخت‌گیرانه انجام می‌شود.
موضوع مورد اعتراض:
""" + str(issue)[:750] + "\nقسمت مربوط از متن برنامه:\n" + transcript[:4000]

def transcript_window(timed, seconds):
    """Narrow by timestamp when possible; avoid forwarding unrelated dialogue."""
    lines=timed.splitlines()
    matches=[]
    for line in lines:
        x=re.search(r"\[(\d\d):(\d\d):(\d\d)\s*-\s*(\d\d):(\d\d):(\d\d)\]",line)
        if x:
            t=int(x[1])*3600+int(x[2])*60+int(x[3])
            if abs(t-seconds)<=140:
                matches.append(line)
    return "\n".join(matches)[:4000] if matches else timed[:4000]

def assess_single_claim(client, issue, timed):
    statement=str(getattr(issue,"issue",issue))[:750]
    offset=int(getattr(issue,"start_sec",0) or 0)
    prompt=source_prompt(statement,transcript_window(timed,offset))
    output={"claim":statement,"start_sec":offset,"status":"unverified",
            "assessment":"","recommended_correction":"","source_title":"",
            "source_url":"","source_quote":"","confidence":"low",
            "verification_note":"مدرک شیعی قابل انطباق با متن اصلی بازیابی نشده است."}
    try:
        response=client.models.generate_content(
            model=RESEARCH_MODEL,contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ))
        raw=(response.text or "").strip()
        raw=raw.removeprefix(chr(96)*3+"json").removesuffix(chr(96)*3).strip()
        values=json.loads(raw)
        if not isinstance(values,dict):
            raise ValueError("research response is not a JSON object")
        output["claim"]=str(values.get("claim_quote") or statement)[:700]
        output["assessment"]=str(values.get("assessment") or "")[:1500]
        output["recommended_correction"]=str(values.get("recommended_correction") or "")[:900]
        output["confidence"]=values.get("confidence") if values.get("confidence") in ("low","medium","high") else "low"
        url=str(values.get("source_url") or "").strip().rstrip("/")
        quote=str(values.get("source_quote") or "").strip()[:750]
        # The model's own citation alone does not count as independent evidence.
        if url and url in grounding_urls(response) and retrieve_exact_quote(url,quote):
            output.update({"source_title":str(values.get("source_title") or "متن شیعی")[:220],
                "source_url":url,"source_quote":quote,"status":"retrieved_evidence",
                "verification_note":"عبارت استنادی در صفحه شیعیِ بازیابی‌شده یافت شد؛ اعتبار سند و استنباط همچنان نیازمند داوری علمی است."})
        elif safe_url(url):
            output["verification_note"]="منبع پیشنهادی یا عبارت نقل‌شده در صفحه قابل تأیید ماشینی نبود؛ هیچ استناد قطعی ثبت نشد."
    except Exception as exc:
        output["verification_note"]=f"جست‌وجوی علمی خودکار ناموفق بود ({type(exc).__name__})؛ ادعا همچنان نیازمند داوری مستند است."
        print(f"Scholarly verification failed: {type(exc).__name__}: {exc}",file=sys.stderr)
    return output

def research_claims(client, timed, issues):
    if not enabled():
        return {"status":"disabled","items":[]}
    limit=min(4,max(1,int(os.getenv("MAX_SCHOLARLY_CLAIMS","3"))))
    concrete=[x for x in issues if getattr(x,"start_sec",None) is not None
              and "تحلیل خودکار" not in str(getattr(x,"issue",""))][:limit]
    results=[assess_single_claim(client,issue,timed) for issue in concrete]
    return {"status":"researched" if results else "no_specific_claims",
            "items":results, "checked_count":len(results),
            "method":"Google Search grounding + allowlisted Shi'a page + exact quote check"}


def format_bale_scholarly(result, program):
    lines=[f"📚 دیدبان | راستی‌آزمایی علمی محتوای {program}",
           "ادعاها با جست‌وجوی منبع شیعی بررسی شده‌اند؛ یافتن متن، تصحیح سند یا تأیید استنباط نیست."]
    if not result.get("items"):
        lines.append("مورد مشخصی برای پژوهش دومرحله‌ای استخراج نشد.")
    for i,x in enumerate(result.get("items",[]),1):
        lines.extend(["",f"{i}) ⏱ {x['start_sec']} ثانیه | ادعا: {x['claim']}",
          f"🔍 نظر تحلیلی: {x['assessment'] or 'تحلیل پژوهشی ناموفق بود.'}",
          f"📝 اصلاح پیشنهادی: {x['recommended_correction'] or 'اصلاحی مستند احراز نشد.'}"])
        if x["status"]=="retrieved_evidence":
            lines.extend([f"📖 منبع بازیابی‌شده: {x['source_title']}",
                          f"🔗 {x['source_url']}",f"📜 عبارت منبع: {x['source_quote']}"])
        else:
            lines.append("⚠️ هیچ شاهد متنی از منابع شیعی در این بررسی به‌طور مستقل تأیید نشد.")
        lines.append("ℹ️ "+x["verification_note"])
    return "\n".join(lines)
