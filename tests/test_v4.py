import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from publish_site_data import public_program
from smart_content import extract_content,publish_content
from analyze_transcript_v4 import normalize_segments,segments


def source():
    return {'network':'persian','scheduled_date':'2026-10-12','start':'20:00','program':'برنامه نمونه',
      'analysis':{'expert':'استاد نمونه','audience_questions':[
          {'question':'پرسش نمونه اول','answer_summary':'پاسخ ثبت‌شده نمونه','start_sec':600},
          {'question':'پرسش بدون پاسخ','answer_summary':''}],
        'key_points':[{'title':'محور آزمایشی','start_sec':90}],
        'expert_segments':[
          {'content_type':'expert_point','title':'نکته دقیق نمونه','summary':'این فقط ادعای نمونه با شاهد است',
           'speaker_role':'expert','speaker_verified':True,'evidence_excerpt':'گوینده این جمله را از روی متن خوانده است',
           'confidence':.92,'start_sec':135},
          {'content_type':'expert_reference','title':'استناد آزمایشی','summary':'ارجاع مثال است',
           'speaker_role':'host','verification_status':'approved', 'evidence_excerpt':'منبع فرضی'},
          {'content_type':'expert_point','title':'سلام به بینندگان','summary':'حاشیه غیر علمی',
           'speaker_role':'expert','verification_status':'approved'}]}}

class V4Tests(unittest.TestCase):
    def test_diarization_and_show_only_confirmed(self):
        raw=source();p=public_program(raw)
        items=extract_content(raw,p)
        self.assertEqual(len(items),4)
        self.assertEqual(sum(i['broadcast_eligible'] for i in items),1)
        self.assertEqual(items[-1]['title'],'نکته دقیق نمونه')
        self.assertIsNone(items[0]['audience_name'])
        self.assertIsNone(items[0]['expert_name'])
        self.assertTrue(any(i['content_type']=='audience_question' for i in items))
    def test_no_cross_network(self):
        raw=source();raw['network']='arabic'
        self.assertIsNone(public_program(raw))
    def test_approval_override_does_not_publish_host(self):
        raw=source();raw['analysis']['expert_segments'][0]['speaker_role']='host'
        raw['analysis']['expert_segments'][0]['verification_status']='approved'
        items=extract_content(raw,public_program(raw))
        self.assertFalse(any(i['broadcast_eligible'] for i in items))
    def test_approved_manual_speaker_role(self):
        raw=source();raw['analysis']['expert_segments'][0].update({'speaker_verified':False,'verification_status':'approved'})
        items=extract_content(raw,public_program(raw))
        self.assertEqual(sum(i['broadcast_eligible'] for i in items),1)
    def test_content_persistence_and_live_protection(self):
        raw=source();p=public_program(raw)
        with tempfile.TemporaryDirectory() as t:
            out=Path(t);publish_content([p],[raw],out,live_program=p)
            published=json.loads((out/'live.json').read_text())
            self.assertEqual(len(published['items']),1)
            self.assertEqual(published['items'][0]['content_type'],'expert_point')
            publish_content([p],[raw],out,live_program=None)
            self.assertEqual(len(json.loads((out/'live.json').read_text())['items']),1)
            all_items=json.loads((out/'content-2026.json').read_text())['items']
            self.assertEqual(len(all_items),4)
            self.assertEqual(len({i['id'] for i in all_items}),4)
    def test_non_fabrication_source_excerpt(self):
        content='کارشناس: این جمله علمی را بیان می‌کنم.'
        proposed=[{'content_type':'expert_point','title':'نکته','summary':'خلاصه','speaker_role':'expert',
          'evidence_excerpt':'جمله ساختگی','confidence':1}]
        self.assertEqual(normalize_segments(content,proposed),[])
        proposed[0]['evidence_excerpt']='این جمله علمی را بیان می‌کنم.'
        validated=normalize_segments(content,proposed)
        self.assertEqual(len(validated),1)
        self.assertTrue(validated[0]['speaker_verified'])
    def test_timed_excerpt_timecode(self):
        content='[00:04:30 - 00:04:50] کارشناس: نمونه متن علمی به عنوان شاهد قطعی.'
        proposed=[{'content_type':'expert_point','title':'تیتر نمونه','summary':'توضیح نمونه',
                   'evidence_excerpt':'نمونه متن علمی به عنوان شاهد قطعی.','speaker_role':'expert','confidence':.92}]
        found=normalize_segments(content,proposed)
        self.assertEqual((found[0]['start_sec'],found[0]['end_sec']),(270,290))
        self.assertTrue(found[0]['speaker_verified'])
    def test_chunks_bounded(self):
        chunked=segments('الف'*50000,max_chunks=2)
        self.assertEqual(len(chunked),2)

if __name__=='__main__':unittest.main()
