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

    def test_default_two_diverse_frames(self):
        frames=[{"offset_sec":i*80,"path":Path(f"frame{i}.jpg")} for i in range(60)]
        with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": ""}):
            selected=v.select_frames(frames,"[00:02:00 - 00:03:00] گفت‌وگوی محتوایی")
        self.assertEqual(len(selected),2)
        self.assertGreater(selected[1]["offset_sec"]-selected[0]["offset_sec"],1200)

    def test_optional_three_frames_and_invalid_setting(self):
        frames=[{"offset_sec":i*80,"path":Path(f"frame{i}.jpg")} for i in range(60)]
        with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": "3"}):
            selected=v.select_frames(frames,"")
        self.assertEqual(len(selected),3)
        self.assertEqual(len({x["offset_sec"] for x in selected}),3)
        with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": "20"}):
            self.assertEqual(v.report_image_count(),2)

    def test_short_recording_limits_to_available_unique_frames(self):
        frame={"offset_sec":0,"path":Path("frame.jpg")}
        with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": "3"}):
            self.assertEqual(len(v.select_frames([frame],"")),1)
            self.assertEqual(len(v.select_frames([frame,frame],"")),2)

    def test_minutes_display_in_photo_caption(self):
        self.assertEqual(v.format_offset_minutes(910),"15 دقیقه")
        self.assertEqual(v.format_offset_minutes(3445),"57 دقیقه")
        self.assertEqual(v.format_offset_minutes(0),"0 دقیقه")

        with tempfile.TemporaryDirectory() as tmp:
            frame_path=Path(tmp)/"frame.jpg"
            frame_path.write_bytes(b"test-image")
            frames=[{"path":frame_path,"offset_sec":910,"observation":"پوشش مرتب",
                     "assessment":"کادر مناسب","recommendation":"کنترل نور"}]
            reply=Mock(status_code=200)
            reply.json.return_value={"ok":True}
            with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": "2"}), \
                 patch("requests.post", return_value=reply) as post:
                errors=v.send_bale_photos({"frames":frames},"test-token","test-chat","فرکانس تاریکی")
            self.assertEqual(errors,[])
            self.assertEqual(post.call_count,1)
            caption=post.call_args.kwargs["data"]["caption"]
            self.assertIn("15 دقیقه",caption)
            self.assertIn("پوشش مرتب",caption)
            self.assertIn("کنترل نور",caption)
            self.assertNotIn("نقشِ قابل مشاهده",caption)
            self.assertNotIn("تشخیص گوینده",caption)
            self.assertNotIn("ثانیه",caption)

    def test_bale_does_not_send_more_than_configured_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames=[]
            for i in range(5):
                f=Path(tmp)/f"frame{i}.jpg"
                f.write_bytes(b"image")
                frames.append({"path":f,"offset_sec":i*60,"observation":"مشاهده",
                               "assessment":"مناسب","recommendation":"حفظ وضعیت"})
            reply=Mock(status_code=200)
            reply.json.return_value={"ok":True}
            with patch.dict("os.environ", {"VISUAL_REPORT_IMAGE_COUNT": "2"}), \
                 patch("requests.post", return_value=reply) as post:
                errors=v.send_bale_photos({"frames":frames},"token","chat","برنامه")
            self.assertEqual(errors,[])
            self.assertEqual(post.call_count,2)

    def test_no_raw_file_paths_in_report(self):
        val={"status":"reviewed","frames":[{"path":Path("secret.jpg"),"offset_sec":25,"visible_role":"نامشخص"}]}
        out=v.report_metadata(val)
        self.assertNotIn("path",out["frames"][0])

    def test_base_audio_not_blocked_when_visual_disabled(self):
        async def audio():
            return "speech","timed","metadata"
        with patch.dict("os.environ",{"ENABLE_VISUAL_REVIEW":"false", "ENABLE_BALE_VIDEO_CLIPS":"false"}):
            got=asyncio.run(v.capture_audio_and_frames(audio,"unused",60))
        self.assertEqual(got,("speech","timed","metadata",[],None))


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

    def test_grounding_google_redirect_is_resolved_only_to_allowed_site(self):
        response=MagicMock()
        response.headers={"Location":"https://al-islam.org/a"}
        response.__enter__.return_value=response
        with patch.object(s.requests,"get",return_value=response) as get:
            url=s.resolve_grounding_source("https://vertexaisearch.cloud.google.com/grounding-api-redirect/example")
        self.assertEqual(url,"https://al-islam.org/a")
        self.assertFalse(s.resolve_grounding_source("https://untrusted.test/redirect"))
        get.assert_called_once()

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
