import csv
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publish_site_data import public_program, ingest, main, safe_text, read_records

class ArchiveTests(unittest.TestCase):
    def test_diagnostic_all_sections_and_private_discarded(self):
        data = {
            'network':'persian','scheduled_date':'2026-10-11', 'start':'21:00',
            'program':'پرسمان اعتقادی','date':'۱۴۰۵/۰۷/۱۹','status':'COMPLETED',
            'secret':'secret value never published','analysis':{
                'program_title':'تیتر نمونه', 'topic':'غدیر', 'summary':'خلاصه برنامه',
                'hashtags':['#غدیر'], 'expert':'کارشناس', 'host':'مجری',
                'key_points':[{'title':'محور اول','start_sec':20,'end_sec':70}],
                'audience_questions':[{'question':'تماس با 09123456789','answer_summary':'پاسخ درباره abc@test.com','start_sec':50,'end_sec':87,'source_type':'phone','audience_name':'نام مخاطب'}],
                'viral_clips':[{'media_title':'کلیپ اول','start_sec':40,'end_sec':70}],
                'expert_content_review':[{'issue':'مطلب داخلی نباید عمومی شود'}],
                'host_review':[{'note':'نقد مجری نباید عمومی شود'}]
            }
        }
        pub = public_program(data)
        self.assertEqual(pub['summary'],'خلاصه برنامه')
        self.assertEqual(len(pub['key_points']),1)
        self.assertEqual(len(pub['clips']),1)
        self.assertEqual(len(pub['questions']),1)
        flat=json.dumps(pub,ensure_ascii=False)
        self.assertNotIn('secret value',flat)
        self.assertNotIn('مطلب داخلی',flat)
        self.assertIn('نام مخاطب',flat) # User requested publication when explicitly recorded
        self.assertNotIn('09123456789',flat)
        self.assertNotIn('abc@test.com',flat)

    def test_import_past_sheet_csv_and_merge_duplicate(self):
        row={'network':'persian','report_id':'2024-05-03_persian_1830','program':'برنامه قدیمی',
             'summary':'گزارش گذشته', 'key_points':'[{"title":"محور قدیمی","start_sec":32,"end_sec":65}]',
             'answered_questions':'[{"question":"سؤال قدیمی","answer_summary":"پاسخ قدیمی","start_sec":5,"end_sec":20}]'}
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sheet.csv';out=Path(td)/'docs'/'data'
            with p.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
            old=public_program(next(read_records(p)))
            self.assertEqual(old['date_iso'],'2024-05-03')
            self.assertEqual(old['start'],'18:30')
            self.assertEqual(old['questions'][0]['answer'],'پاسخ قدیمی')
            ingest([old,old],out)
            self.assertEqual(json.loads((out/'index.json').read_text())['total_programs'],1)
            self.assertEqual(json.loads((out/'index.json').read_text())['total_questions'],1)

    def test_unbounded_archive_multiple_years(self):
        with tempfile.TemporaryDirectory() as td:
            source=[]
            for year in range(2014,2027):
                for i in range(38):
                    p=public_program({'network':'persian','scheduled_date':f'{year}-01-{i%28+1:02d}',
                         'start':f'{i//2%24:02d}:{(i%2)*30:02d}','program':'پرسش','summary':'خلاصه'})
                    source.append(p)
            ingest(source,Path(td))
            index=json.loads((Path(td)/'index.json').read_text())
            self.assertEqual(index['total_programs'],len(source))
            self.assertEqual(len(index['years']),13)

    def test_unanswered_not_falsely_labeled(self):
        p=public_program({'scheduled_date':'2025-04-21','start':'18:00','network':'persian',
            'analysis':{'audience_questions':[{'question':'بی پاسخ','answer_summary':''}]}})
        self.assertEqual(p['questions'],[])
        self.assertIsNone(public_program({'scheduled_date':'2025-04-21','start':'18:00','network':'arabic'}))

if __name__ == '__main__':unittest.main()
