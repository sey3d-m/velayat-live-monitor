"""Offline tests for new Didban modules. No real streaming or Gemini calls."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock
from types import SimpleNamespace

import visual_review as v
import scholarly_review as s


class VisualReviewTests(unittest.TestCase):
    def test_sample_interval_bounds_work(self):
        self.assertEqual(v.interval_for(120),65)
        self.assertGreaterEqual(v.interval_for(7200),65)
        self.assertLessEqual((7200 // v.interval_for(7200)),100)

    def test_select_six_diverse_frames(self):
        frames=[{"offset_sec":i*80,"path":Path(f"frame{i}.jpg")} for i in range(60)]
        selected=v.select_frames(frames,"[00:02:00 - 00:03:00] گفت‌وگوی محتوایی در مورد حدیث")
        self.assertEqual(len(selected),6)
        self.assertLess(selected[0]["offset_sec"],selected[-1]["offset_sec"])

    def test_no_raw_file_paths_in_report(self):
        val={"status":"reviewed","frames":[{"path":Path("secret.jpg"),"offset_sec":25,"visible_role":"نامشخص"}]}
        out=v.report_metadata(val)
        self.assertNotIn("path",out["frames"][0])

    def test_base_audio_not_blocked_when_visual_disabled(self):
        async def audio():
            return "speech","timed","metadata"
        with patch.dict("os.environ",{"ENABLE_VISUAL_REVIEW":"false"}):
            got=asyncio.run(v.capture_audio_and_frames(audio,"unused",60))
        self.assertEqual(got,("speech","timed","metadata",[]))


class ScholarlyReviewTests(unittest.TestCase):
    def test_allowlist_protects_source_fetch(self):
        self.assertTrue(s.safe_url("https://al-islam.org/example"))
        self.assertTrue(s.safe_url("https://hadith.inoor.ir/example"))
        self.assertFalse(s.safe_url("http://al-islam.org/example"))
        self.assertFalse(s.safe_url("https://al-islam.org.evil.test/page"))
        self.assertFalse(s.safe_url("https://127.0.0.1/private"))
        self.assertFalse(s.safe_url("https://example.net/source"))

    def test_grounding_filter(self):
        web1=SimpleNamespace(web=SimpleNamespace(uri="https://al-islam.org/a"))
        web2=SimpleNamespace(web=SimpleNamespace(uri="https://random.example/c"))
        meta=SimpleNamespace(grounding_chunks=[web1,web2])
        response=SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=meta)])
        self.assertEqual(s.grounding_urls(response),{"https://al-islam.org/a"})

    def test_only_matching_quote_is_verified(self):
        body="<html><body>قال رسول الله في هذا الحديث: النص المطلوب موجود هنا بتمامه.</body></html>"
        fake=MagicMock()
        fake.status_code=200
        fake.headers={"Content-Type":"text/html; charset=utf-8"}
        fake.encoding="utf-8"
        fake.iter_content.return_value=[body.encode("utf8")]
        fake.__enter__=Mock(return_value=fake)
        fake.__exit__=Mock(return_value=None)
        with patch.object(s.requests,"get",return_value=fake):
            self.assertTrue(s.retrieve_exact_quote("https://al-islam.org/a","النص المطلوب موجود هنا بتمامه"))
            self.assertFalse(s.retrieve_exact_quote("https://al-islam.org/a","این نقل قول در منبع وجود ندارد"))

    def test_unsupported_source_never_counts_as_verified(self):
        self.assertFalse(s.retrieve_exact_quote("https://not-shia.example/a","عبارتی نسبتاً طولانی و غیرقابل اعتماد"))

    def test_no_specific_claims(self):
        client=Mock()
        with patch.dict("os.environ",{"ENABLE_SCHOLARLY_REVIEW":"true"}):
            result=s.research_claims(client,"",[])
        self.assertEqual(result["items"],[])
        client.models.generate_content.assert_not_called()

    def test_scholarly_report_distinguishes_evidence(self):
        result={"items":[{"start_sec":120,"claim":"ادعای آزمون","assessment":"بررسی محتوایی",
            "recommended_correction":"اصلاح پیشنهادی","status":"unverified",
            "verification_note":"استناد کافی موجود نیست","source_title":"", "source_url":"","source_quote":""}]}
        message=s.format_bale_scholarly(result,"برنامه آزمایشی")
        self.assertIn("هیچ شاهد متنی",message)
        self.assertNotIn("📖 منبع بازیابی‌شده",message)


if __name__=="__main__":
    unittest.main()
