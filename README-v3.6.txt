Velayat Live Monitor v3.6 - Live Transcribe

این نسخه مشکل معماری v3.4 را حل می‌کند:
در v3.4 بعد از پایان برنامه، فایل یک‌ساعته به 15 قطعه 4 دقیقه‌ای تقسیم و سپس Transcribe می‌شد.
این کار برای سه برنامه روزانه درخواست‌های زیادی به gemini-3.5-transcribe می‌فرستاد و Free Tier به limit=25 برخورد کرد.

v3.6:
- از gemini-3.5-transcribe-live استفاده می‌کند.
- صدا همزمان با پخش شبکه به Gemini Live فرستاده می‌شود.
- PCM خام: mono / 16-bit / 16kHz.
- قطعات ارسال شبکه‌ای: 100ms.
- هر Live Session حداکثر 9 دقیقه است تا زیر سقف رسمی 10 دقیقه بماند.
- یک برنامه یک‌ساعته معمولاً 7 Session خواهد داشت.
- transcript.txt بعد از هر Session ذخیره می‌شود.
- در پایان برنامه تقریباً کل متن آماده است و فقط تحلیل نهایی، Sheet و Bale باقی می‌ماند.
- گزارش بله شامل نام برنامه و آمار در انتها است.
- TXT متن کامل نیز به بله ارسال می‌شود.
- فایل صوتی دائمی ذخیره نمی‌شود.

فایل‌هایی که باید جایگزین شوند:
1) velayat_monitor.py
2) requirements.txt

فایل‌های زیر را تغییر ندهید:
- .github/workflows/velayat-monitor.yml نسخه v3.5
- Google Apps Script Scheduler نسخه v3.5
- Secrets
- Apps Script Web App / doPost

نکته:
Free Tier رایگان است اما سهمیه دارد. این نسخه تعداد Sessionهای Transcribe را شدیداً کم می‌کند، ولی اگر همان Gemini Project توسط سامانه‌های دیگر مصرف شود یا Google سهمیه را تغییر دهد، هیچ کد رایگانی نمی‌تواند 429 را به طور مطلق ناممکن کند.

بعد از جایگزینی:
- Commit changes
- اجرای خودکار همچنان توسط Apps Script انجام می‌شود.
- نیازی به نصب Trigger جدید نیست.
