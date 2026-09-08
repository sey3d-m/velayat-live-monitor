Velayat Live Monitor v3.1 COMPLETE FIX

این بسته شامل خود فایل‌های اجرایی کامل است:

1) velayat_monitor.py
2) requirements.txt
3) .github/workflows/velayat-monitor.yml

اصلاح خطای اول:
No active program slot found
- Workflow نوبت دقیق 18:00 / 19:30 / 21:00 را مستقیم به Python می‌دهد.
- Python دیگر نوبت برنامه را از ساعت فعلی حدس نمی‌زند.
- اگر GitHub چند دقیقه دیر شروع کند، همان برنامه صحیح تا ساعت پایان ضبط می‌شود.

اصلاح خطای دوم:
Gemini high demand / 500 / 503
- مدل تحلیل چند بار Retry می‌شود.
- در صورت ادامه خطا، مدل Flash جایگزین امتحان می‌شود.
- transcript قبل از تحلیل ذخیره می‌شود.
- حتی اگر تحلیل نهایی شکست بخورد، فایل program_transcript.txt در Artifact باقی می‌ماند.

نحوه جایگزینی:
- velayat_monitor.py را در ریشه Repository جایگزین کنید.
- requirements.txt را جایگزین کنید.
- .github/workflows/velayat-monitor.yml را جایگزین کنید.
- Commit changes بزنید.
- Secretها را تغییر ندهید.

تست دستی:
Actions > Velayat Live Monitor > Run workflow
و Slot مناسب را انتخاب کنید.
اگر خارج از بازه برنامه تست کنید و زمان پایان آن Slot گذشته باشد، سیستم عمداً خطا می‌دهد تا برنامه اشتباهی ضبط نشود.
