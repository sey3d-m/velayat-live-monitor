import unittest
from publish_site_data import update_feed


def sample_report():
    return {
        'network': 'persian', 'analysis_available': True,
        'scheduled_date': '2026-10-11', 'date': '۱۴۰۵/۰۷/۱۹',
        'day': 'یکشنبه', 'start': '21:00', 'end': '22:00',
        'program': 'پرسمان اعتقادی', 'status': 'COMPLETED',
        'secret': 'DO_NOT_PUBLISH', 'analysis': {
            'program_title': 'نمونه', 'topic': 'موضوع', 'expert': 'کارشناس', 'host': 'مجری',
            'audience_questions': [
                {'source_type': 'phone', 'audience_name': 'نام شخصی',
                 'question': 'آیا مثال قابل پاسخ است؟', 'answer_summary': 'بله، توضیح داده شده است.',
                 'start_sec': 50, 'end_sec': 102},
                {'source_type': 'message', 'audience_name': 'شخص دوم',
                 'question': 'پرسش بدون جواب', 'answer_summary': '',
                 'start_sec': 200, 'end_sec': 300},
            ]},
        'transcription': {'transcript_incomplete': False},
    }


class PublisherTests(unittest.TestCase):
    def test_extracts_only_answered_no_secret_or_names(self):
        result, done = update_feed({'programs': []}, sample_report())
        self.assertTrue(done)
        self.assertEqual(len(result['programs'][0]['questions']), 1)
        import json
        exposed = json.dumps(result, ensure_ascii=False)
        self.assertNotIn('DO_NOT_PUBLISH', exposed)
        self.assertNotIn('نام شخصی', exposed)
        self.assertNotIn('پرسش بدون جواب', exposed)

    def test_non_persian_skipped(self):
        report = sample_report()
        report['network'] = 'arabic'
        initial = {'programs': []}
        out, done = update_feed(initial, report)
        self.assertFalse(done)
        self.assertIs(out, initial)

    def test_failed_analysis_skipped(self):
        report = sample_report()
        report['analysis_available'] = False
        _, done = update_feed({'programs': []}, report)
        self.assertFalse(done)

    def test_rerun_replaces_same_program(self):
        original = sample_report()
        feed, _ = update_feed({'programs': []}, original)
        original['analysis']['audience_questions'][0]['answer_summary'] = 'خلاصه اصلاح‌شده'
        updated, _ = update_feed(feed, original)
        self.assertEqual(len(updated['programs']), 1)
        self.assertEqual(updated['programs'][0]['questions'][0]['answer'], 'خلاصه اصلاح‌شده')

    def test_remove_contact_information(self):
        report = sample_report()
        report['analysis']['audience_questions'][0]['question'] = 'با شماره ۰۹۱۲۳۴۵۶۷۸۹ تماس بگیرید'
        report['analysis']['audience_questions'][0]['answer_summary'] = 'ایمیل someone@example.org'
        result, _ = update_feed({'programs': []}, report)
        item = result['programs'][0]['questions'][0]
        self.assertIn('[شماره حذف شد]', item['question'])
        self.assertIn('[نشانی حذف شد]', item['answer'])


if __name__ == '__main__':
    unittest.main()
