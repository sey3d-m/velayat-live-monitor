# پاسخ‌نما ۴.۰ — Pasokhnama V4.0 — Velayat Persian Smart Live Content

## توضیح مهم درباره دامنه این نسخه

این بسته یک **افزونه عملیاتی و قابل اجرا روی GitHub Pages برای سامانه فعلی دیدبان** است. از ZIP نسخه ۳ توسعه یافته و موتور اصلی `velayat_monitor.py`، ضبط HLS، زمان‌بندی ضبط، کلیدهای Gemini و ارسال بله را **تغییر نمی‌دهد**. خروجی‌های گزارش واقعی که دیدبان از قبل می‌سازد پس از تکمیل همان اجرای موجود به آرشیو پاسخ‌نما وارد می‌شوند.

نسخه ۴ **پخش زنده صوت را مستقلاً تحلیل نمی‌کند**. به‌روزرسانی صفحه هر ۶۰ تا ۱۲۰ ثانیه با تحلیل صوت هر ۶۰ تا ۱۲۰ ثانیه یکسان نیست. GitHub Actions برای اجرای مبتنی بر cron به‌صورت رسمی حداقل فاصلهٔ **۵ دقیقه** دارد و اجرای آن ممکن است با تأخیر انجام شود. برنامه دیدبان کنونی تحلیل را پس از اتمام بلوک ضبط/پردازش عرضه می‌کند. برای تحلیل واقعاً پیوسته در فواصل ۱ تا ۲ دقیقه باید زیرساخت تحلیل قطعه‌ای با ذخیره‌ساز/پردازنده دائمی یا runner دائم و زمان‌کد منبع در مرحله بعد اضافه شود.

## فایل‌های مهم

| مسیر | نقش |
|---|---|
| `publish_site_data.py` | ناشناس‌سازی و انتقال آرشیو قدیمی، تولید هم‌زمان فیدهای V3 و V4 |
| `smart_content.py` | دسته‌بندی، استانداردسازی و پالایش شواهد علمی؛ جداسازی گوینده و کنترل اجازه انتشار تلویزیونی |
| `analyze_transcript_v4.py` | **اختیاری**: استخراج نکات علمی از متن پیاده‌سازی موجود با Gemini؛ بدون ضبط یا STT تکراری |
| `import_bale_history.py` | ورود سابقه واقعی فایل‌های استخراج‌شده کانال بله؛ بدون استفاده از getUpdates |
| `docs/index.html` | صفحه عمومی با جست‌وجو و فیلتر |
| `docs/overlay.html` | پنل تلویزیونی شفاف با چهار تا شش کارت |
| `docs/settings.html` | ویرایشگر تنظیمات محلی و صادرکننده JSON |
| `docs/data/config.json` | تنظیمات سراسری قابل انتشار در GitHub Pages |
| `docs/data/content-index.json`, `content-YYYY.json` | آرشیو موضوعی نسخه ۴ |
| `docs/data/live.json` | آخرین محتوای دارای مجوز نمایش تلویزیونی |
| `docs/data/archive-YYYY.json`, `index.json` | آرشیو برنامه‌های قبلی بدون محدودیت ۳۶ مورد |
| `.github/workflows/publish-dashboard.yml` | پس از موفقیت اجرای خود دیدبان، بایگانی و Pages را منتشر می‌کند |
| `.github/workflows/import-history.yml` | ورود تاریخچه از صادرکننده خصوصی در GitHub |

## نصب روی مخزن دیدبان (بدون تغییر موتور)

1. **ابتدا از شاخه سالم GitHub یک نسخه پشتیبان بگیرید** یا یک branch جدید به نام `pasokhnama-v4` بسازید. فایل ZIP را از حالت فشرده خارج کنید.
2. محتویات ZIP را با حفظ پوشه‌های `docs/`، `tests/`، `.github/workflows/` در **ریشه** مخزن `velayat-live-monitor` کپی کنید. در فایل‌های هم‌نام **فقط افزونه‌های پاسخ‌نما** را جایگزین کنید. فایل `velayat_monitor.py` نباید بازنویسی شود.
3. نخست روی branch آزمایشی تست کنید. برای راه‌اندازی اولیه GitHub Pages، در `Settings → Pages → Build and deployment → Source` گزینه `GitHub Actions` را انتخاب کنید.
4. در `Settings → Actions → General → Workflow permissions` سطح `Read and write permissions` را فعال کنید؛ GitHub Pages هم باید اجازهٔ انتشار داشته باشد.
5. در `Actions → Publish Q&A Dashboard → Run workflow` انتشار دستی را یک‌بار اجرا کنید. اگر نام واقعی گردش‌کار دیدبان دیگر `Velayat Live Monitor` باشد، مقدار `workflows` در فایل `publish-dashboard.yml` را فقط با نام دقیق workflow موجود تنظیم کنید.
6. مسیر عمومی: `https://USERNAME.github.io/velayat-live-monitor/`؛ تلویزیون: `https://USERNAME.github.io/velayat-live-monitor/overlay.html`؛ تنظیمات: `.../settings.html`.
7. برای حالت آزمایشی **کاملاً ساختگی** و بدون خطر نسبت‌دادن محتوا: `?demo=1` را انتهای آدرس اصلی یا تلویزیونی بگذارید.
8. پس از اطمینان از سالم‌ماندن دیدبان و Pages، branch را با شاخه اصلی ادغام کنید. برگشت: revert commit مربوط به پاسخ‌نما / استفاده از branch پشتیبان.

> هیچ توکن، صوت اصلی یا متن کامل خام مکالمه در `docs/` قرار ندهید. `docs/` محل انتشار عمومی است؛ فایل‌های خام بله/Sheets و `/tmp/pasokhnama-v4-structured.json` فقط باید در محیط خصوصی پردازش شوند.

## کارکرد خودکار فعلی

- اگر یک Artifact شامل `program_report.json` با الگوی `velayat-persian-*` پس از پایان workflow دیدبان وجود داشته باشد، همان داده بدون تغییر در دیدبان خوانده می‌شود.
- پرسش‌های موجود در گزارش، مطالب محوری برنامه و سوابق تاریخی به‌صورت **محتوای منسوب به گزارش** قابل جست‌وجو می‌شوند؛ این موارد تا زمان احراز انتساب صدا، خودبه‌خود «گفته قطعی کارشناس» قلمداد نمی‌شوند.
- بخش `analysis.expert_segments` در صورت موجود بودن می‌تواند «نکته علمی»، «محور بحث»، «استناد» و «جمع‌بندی» را استخراج کند. مواردی با `speaker_role=host/unknown` حذف می‌شوند.
- برای **پخش تلویزیونی خودکار** هر رکورد باید یا `verification_status=approved` (تأیید انسانی) داشته باشد، یا شاهد متنی معتبر، `confidence≥0.85`، نقش صریح `speaker_role=expert` و پرچم معتبر `speaker_verified=true`. در غیر این صورت همچنان در آرشیو با نشان «نیازمند بررسی» باقی می‌ماند و روی تلویزیون به‌عنوان سخن کارشناس نمایش نمی‌یابد.
- نام و شهر مخاطب در **فید جدید نسخه ۴** فقط با `public_consent=true` در رکورد ورودی وارد JSON می‌شود. این حکم، آرشیو قدیمی V3 را که از قبل منتشر شده پاک نمی‌کند؛ داده‌های قبلی را برای انطباق حریم خصوصی جداگانه بازبینی کنید.
- اگر خروجی جدید وجود نداشته باشد، نمای تلویزیون زمان آخرین تحلیل و عنوان «آخرین مطالب ثبت‌شده» را نشان می‌دهد؛ اطلاعات قدیمی را محتوای زنده معرفی نمی‌کند. تغییر برنامه باعث مخلوط شدن پرونده‌های جداگانه نمی‌شود.

### استخراج اختیاری مطالب علمی از رونوشت موجود دیدبان

پیش‌فرض **خاموش** است تا هزینه اضافی/API و بار پردازش ایجاد نشود. اگر Artifact واقعی دیدبان شامل `program_transcript_timed.txt` یا `program_transcript.txt` (یا نام قدیمی `transcript.txt`) است و می‌خواهید از همان متن موجود خلاصه علمی اضافه تولید شود:

- `Settings → Secrets and variables → Actions → Secrets`: کلید `PASOKHNAMA_GEMINI_API_KEY` را ثبت کنید (از کلید دیدبان لازم نیست استفاده شود).
- `Settings → Secrets and variables → Actions → Variables`: مقدار `PASOKHNAMA_SMART_ANALYSIS` را برابر `true` بگذارید.
- از آن پس در گردش‌کار **انتشار پاسخ‌نما**، نه در موتور دیدبان، `analyze_transcript_v4.py` اجرا می‌شود. در نبود `transcript.txt` یا خطای API، داده پایه بدون تغییر منتشر می‌شود. خواندن رونوشت باعث STT یا ضبط دوباره نمی‌شود؛ اما فراخوانی اضافی Gemini دارد.
- اگر رونوشت برچسب قابل اتکای گوینده ندارد، تشخیص کارشناس هنوز قطعی نیست: خلاصه‌های مدل به تلویزیون راه پیدا نمی‌کنند تا تأیید انسانی یا گوینده‌سنجی قابل اعتماد انجام شود.

نمونه اجرای محلی با رونوشت از پیش موجود:

```bash
GEMINI_API_KEY=YOUR_PRIVATE_KEY python analyze_transcript_v4.py --report path/to/program_report.json --transcript path/to/transcript.txt --out /tmp/v4-report.json
python publish_site_data.py --report path/to/program_report.json --expert-file /tmp/v4-report.json --out-dir docs/data
```

**کلید را در GitHub/کد/اسکرین‌شات منتشر نکنید.** فرمان نمونه از shell متغیر محیطی می‌خواند و در GitHub باید از Secrets استفاده شود.

## افزودن تاریخچه واقعی از کانال بله

صفحه `https://ble.ir/monitoring_velayat` یک منبع عمومی برای مشاهده است، اما API ربات بله تاریخچه کامل قدیمی را صرفاً از طریق لینک صفحه در اختیار نمی‌گذارد. برای ورود کامل، متن پیام‌های قبلی کانال یا خروجی رسمی/قانونی پیام‌ها باید در دسترس باشد. هر دو «بخش اول» و «بخش دوم» گزارش‌ها را ارائه کنید تا گزارش‌های هم‌نام اشتباه ترکیب نشوند.

```bash
python import_bale_history.py --input path/to/bale-history.txt --output /tmp/bale-reports.json
python publish_site_data.py --import-file /tmp/bale-reports.json --out-dir docs/data
```

همچنین CSV/JSON/JSONL Google Sheets قابل ورود است. بررسی کنید ردیف‌ها به شبکه `persian` یا `fa` تعلق دارند. **بدون صادرات سوابق، تاریخچه گذشته خودبه‌خود وارد نمی‌شود**. اگر از GitHub Import workflow استفاده می‌کنید، طبق نسخه ۳ یک URL خصوصی HTTPS در `HISTORY_EXPORT_URL` و در صورت نیاز توکن در `HISTORY_EXPORT_TOKEN` لازم است.

## نمونه ورودی بخش علمی V4

شکل نمونه زیر **رکورد نمایشی غیرواقعی** است؛ در نمونهٔ توزیع‌شده داخل `examples/schema-only.json` به‌گونه‌ای علامت‌گذاری شده که قابل انتشار اتفاقی نباشد.

```json
{
  "network": "persian", "scheduled_date": "YYYY-MM-DD", "start": "HH:MM",
  "program": "عنوان واقعی برنامه", "analysis": {
    "expert": "نام واقعی کارشناس", "expert_segments": [
      {
        "content_type": "expert_point", "title": "عنوان مستند واقعی",
        "summary": "چکیده واقعی", "speaker_role": "expert",
        "evidence_excerpt": "عبارت عیناً آمده در رونوشت",
        "speaker_verified": true, "confidence": 0.93,
        "start_sec": 180, "end_sec": 240,
        "verification_status": "pending"
      }
    ]
  }
}
```

برای مجوز پس از بازبینی انسانی، `verification_status` را `approved` کنید. داده‌های حساس یا نامطمئن را قبل از تولید JSON عمومی بررسی کنید.

## تنظیمات و خروجی OBS / vMix

در `docs/settings.html` می‌توان تعداد کارت (۴ تا ۶)، فاصله تازه‌سازی (۶۰ تا ۱۲۰ ثانیه)، قلم، رنگ، محل قرارگیری، طول خلاصه، فعال بودن گروه‌ها و نمایش تایم‌کد را تنظیم کرد. این صفحه روی GitHub Pages احراز هویت ندارد، پس **تنها ویرایشگر محلی** است: برای تنظیم سراسری، فایل JSON خروجی را پس از بررسی در `docs/data/config.json` مخزن ذخیره کنید.

آدرس نمونه‌ها:

- `overlay.html?demo=1&count=6` — ۶ آیتم آزمایشی با پس‌زمینه شفاف
- `overlay.html?pos=left` — جانمایی سمت چپ
- `overlay.html?pos=bottom&count=6` — چینش در پایین تصویر
- `overlay.html?width=620&count=4` — عرض و تعداد دلخواه در محدوده مجاز

منبع مرورگر OBS و vMix پس‌زمینه شفاف دارد؛ اندازه پنجره Browser Source را متناسب با خروجی تلویزیون (مثلاً ۶۲۰×۱۰۸۰) تنظیم کنید. فونت Vazirmatn از Google Fonts بارگیری می‌شود؛ در نبود دسترسی، از Tahoma/Arial استفاده خواهد شد.

برای اجرای محلی:

```bash
python -m http.server 8000 --directory docs
```

آدرس: `http://localhost:8000/?demo=1` (داده واقعی نیازمند فایل‌های index/content/live معتبر در `docs/data` است).

## آزمون‌ها و محدودیت‌ها

```bash
python -m unittest discover -s tests -v
python tests/browser_smoke.py      # اختیاری، به Chromium و Playwright نیاز دارد
```

این بسته مستقلاً HLS را باز نکرده، به حساب بله وارد نشده، جریان زنده تلویزیون را ضبط نکرده، سرویس Gemini خارجی را اجرا نکرده و بدون دسترسی نوشتن به GitHub نتوانسته است نسخه را روی مخزن اصلی منتشر کند. بنابراین **موفقیت اجرای واقعی GitHub و تولید محتوای ۲ دقیقه‌ای روی آنتن هنوز تست میدانی نشده است**. جزئیات در `REPORT-V4-TESTS.md` است.

## معیارهای سلامت و بازگشت

- `velayat_monitor.py` و گردش‌کار اصلی ضبط/بله/Gemini تغییر نکرده‌اند.
- همان داده نسخه ۳ برای کاربران قدیمی همچنان در `archive-YYYY.json` حفظ می‌شود.
- در نمایش تلویزیونی فقط موارد با `broadcast_eligible=true` قرار می‌گیرند؛ موارد دیگر قابل جست‌وجو با نشان احتیاط هستند.
- پس از هر import ناموفق، فایل‌های قبلی حذف نمی‌شوند. برای رفع تداخل انتشار، هر دو workflow از گروه قفل انتشار `publish-qa-dashboard` استفاده می‌کنند.
- ابتدا انتشار را در یک branch آزمایشی و سپس در Pages واقعی ببینید؛ در صورت اشکال commit نسخه ۴ را revert کنید.
