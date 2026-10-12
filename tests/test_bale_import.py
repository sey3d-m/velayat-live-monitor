import sys
import json
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from import_bale_history import parse_date,merge_from_bale,load_messages
from publish_site_data import public_program,ingest

PART1='''📌 بخش اول | خلاصه برنامه‌های زنده شبکه ولایت

🗓 تاریخ: ۱۴۰۵/۰۷/۱۹
📺 نام برنامه: پرسمان اعتقادی
📰 تیتر کلی: گفت‌وگویی درباره حدیث غدیر
🎙 مجری: مجری نمونه
👤 کارشناس: کارشناس نمونه
🕒 زمان برنامه: ۲۱:۰۰ تا ۲۲:۰۰ به وقت تهران
🎯 موضوع: تاریخ و حدیث
🏷 هشتگ‌ها: #غدیر #شبکه_ولایت

📝 خلاصه مباحث برنامه:
گزارش آزمایشی، غیرواقعی و ساختگی برای آزمون تبدیل پیام‌ها.

🔹 محورهای اصلی با تایم:
1. بررسی یک موضوع فرضی
   ⏱ 00:09:00 تا 00:16:00
2. دیدگاه‌ها درباره یک پرسش
   ⏱ 00:17:00 تا 00:24:00
'''
PART2='''📌 بخش دوم | تحلیل تکمیلی برنامه‌های زنده شبکه ولایت

📺 برنامه: پرسمان اعتقادی
📰 تیتر کلی: گفت‌وگویی درباره حدیث غدیر

❓ سؤالات مخاطبان و چکیده پاسخ:
1. [تلفنی – آقای رضا از قم] پرسش نمونه درباره متن یک روایت چیست؟
   ⏱ 00:19:30 تا 00:22:10
   ↳ پاسخ: خلاصه پاسخ فرضی در یک جمله.
2. [پیام/پیامک] پرسش نمونه دوم چیست؟
   ⏱ 00:35:00 تا 00:38:00
   ↳ پاسخ: پاسخ دوم آزمایشی است.

🚀 پیشنهادهای وایرال و تقطیع رسانه‌ای:
1. مثال
'''

class BaleArchiveTests(unittest.TestCase):
 def test_jalali(self):
  self.assertEqual(parse_date('۱۴۰۵/۰۷/۱۹'),'2026-10-11')
  self.assertEqual(parse_date('1405/01/01'),'2026-03-21')
 def test_pair_and_privacy(self):
  programs,orphan,skipped=merge_from_bale([{'text':PART1},{'text':PART2}])
  self.assertEqual((orphan,skipped),(0,0))
  self.assertEqual(len(programs),1)
  pub=public_program(programs[0]);self.assertEqual(len(pub['questions']),2)
  q=pub['questions'][0]
  self.assertEqual(q['audience_name'],'رضا')
  self.assertEqual(q['city'],'قم')
  self.assertEqual(q['answer_time_approx'],'21:19')
  self.assertEqual(q['answer_time_end_approx'],'21:22')
  self.assertEqual(pub['summary'],'گزارش آزمایشی، غیرواقعی و ساختگی برای آزمون تبدیل پیام‌ها.')
  self.assertEqual(pub['key_points'][0]['start_sec'],540)
  self.assertEqual(pub['date_iso'],'2026-10-11')
  self.assertFalse(pub['questions'][1]['city'])
 def test_only_persian(self):
  _,orphan,_=merge_from_bale([{'text':'📌 بخش اول | خلاصه برنامه‌های زنده شبکه ولایت اردو'}])
  self.assertEqual(orphan,0)
 def test_json_export_and_dedup(self):
  with tempfile.TemporaryDirectory() as d:
   file=Path(d)/'messages.json'
   file.write_text(json.dumps({'messages':[{'text':PART1},{'text':PART2}]},ensure_ascii=False))
   records=load_messages(file)
   self.assertEqual(len(records),2)
   p,_orphan,_=merge_from_bale(records)
   out=Path(d)/'docs/data'
   pub=public_program(p[0]);ingest([pub],out);ingest([pub],out)
   archive=json.loads((out/'archive-2026.json').read_text())
   self.assertEqual(len(archive['programs']),1)
   self.assertEqual(len(archive['programs'][0]['questions']),2)

if __name__=='__main__':unittest.main()
