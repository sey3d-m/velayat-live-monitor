Velayat Live Monitor v3.4 - Quota Safe

رفع خطای 429 مدل gemini-3.5-transcribe در Free Tier:
- تقسیم صوت به قطعات 4 دقیقه‌ای
- فاصله حداقل 65 ثانیه بین شروع درخواست‌های Transcribe
- Retry خودکار برای 429 و رعایت retry time اعلام‌شده توسط Google
- ذخیره متن بعد از هر قطعه
- حذف فایل موقت Gemini بعد از هر قطعه
- حفظ نام برنامه، آمار در انتهای پیام و ارسال TXT به بله
- زمان‌بندی: Runner ده دقیقه زودتر، ضبط از ساعت رسمی
- timeout: 110 دقیقه

فایل‌های velayat_monitor.py، requirements.txt و .github/workflows/velayat-monitor.yml را جایگزین کنید. Secrets و Apps Script را تغییر ندهید.
