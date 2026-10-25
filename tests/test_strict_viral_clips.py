"""Report-driven editorial clips must match published content and timecodes."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import video_clips


def report_rows():
    values = [
        (947, 1330, "چرا امام علی (ع) در نامه‌نگاری با معاویه به غدیر استناد نکرد؟"),
        (1330, 2229, "روایت تکان‌دهنده ابن‌عباس از بی‌قراری شبانه امیرالمؤمنین (ع)"),
        (2311, 2530, "شباهت جنگ روانی ۱۴۰۰ سال پیش با شرایط امروز رسانه‌ای"),
        (3505, 4211, "چرا امام علی (ع) پیشنهاد ابقای معاویه را قاطعانه رد کرد؟"),
    ]
    return [SimpleNamespace(start_sec=start, end_sec=end, media_title=title,
                            angle="سوژه اختصاصی", caption="متن واقعی پیشنهاد رسانه‌ای",
                            priority="high", why_viral="پیشنهاد ویژه")
            for start, end, title in values]


class StrictViralReportTests(unittest.TestCase):
    def test_exact_report_ranges_include_long_and_adjacent_clips(self):
        selected = video_clips.select_report_segments(
            report_rows(), 4500, limit=4, min_seconds=30, max_seconds=1800)
        self.assertEqual([(a, b) for a, b, _ in selected],
                         [(947, 1330), (1330, 2229), (2311, 2530), (3505, 4211)])

    def test_unverified_alignment_does_not_publish_random_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, audio = Path(tmp) / "video.mp4", Path(tmp) / "audio.flac"
            src.write_bytes(b"a" * 11000)
            audio.write_bytes(b"a" * 11000)
            with patch.object(video_clips, "align_video_to_audio", return_value=None), \
                 patch.object(video_clips, "make_clip") as encode:
                result = video_clips.send_bale_clips(
                    src, report_rows(), 4500, "token", "old-report-id",
                    "بیان امیر", strict_report=True, audio_reference=audio)
                self.assertEqual(result["status"], "unavailable")
                self.assertIn("unverified_audio_video_timeline", result["errors"])
                encode.assert_not_called()

    def test_four_report_clips_use_synced_seek_and_original_captions(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, audio = Path(tmp) / "video.mp4", Path(tmp) / "audio.flac"
            out = Path(tmp) / "clip.mp4"
            src.write_bytes(b"v" * 11000)
            audio.write_bytes(b"a" * 11000)
            out.write_bytes(b"c" * 11000)
            success = SimpleNamespace(status_code=200, json=lambda: {"ok": True})
            with patch.object(video_clips, "align_video_to_audio", return_value=-7.5), \
                 patch.object(video_clips, "probe_duration", return_value=4500), \
                 patch.object(video_clips, "make_clip", return_value=out) as encoder, \
                 patch.object(video_clips.requests, "post", return_value=success) as send, \
                 patch("bengali_instant_dispatch.enqueue_after_sent"):
                result = video_clips.send_bale_clips(
                    src, report_rows(), 4500, "token", "existing-reports",
                    "بیان امیر", expert="کارشناس", date="۱۴۰۵/۰۸/۰۳",
                    strict_report=True, audio_reference=audio)
            self.assertEqual(result["status"], "sent")
            self.assertEqual(len(result["sent"]), 4)
            self.assertEqual(result["av_offset_seconds"], -7.5)
            self.assertEqual(
                [(round(c.args[1], 1), round(c.args[2], 1)) for c in encoder.call_args_list],
                [(939.5, 1322.5), (1322.5, 2221.5),
                 (2303.5, 2522.5), (3497.5, 4203.5)])
            self.assertEqual([item["title"] for item in result["sent"]],
                             [item.media_title for item in report_rows()])
            self.assertEqual(send.call_count, 4)
            for ix, call in enumerate(send.call_args_list):
                caption = call.kwargs["data"]["caption"]
                self.assertEqual(call.kwargs["data"]["chat_id"], "@live_vtv")
                self.assertIn(report_rows()[ix].media_title[:40], caption)
                self.assertIn("متن واقعی پیشنهاد رسانه‌ای", caption)
            self.assertIn("01:10:11", send.call_args_list[3].kwargs["data"]["caption"])

    def test_selector_never_truncates_or_generates_substitutes(self):
        rows = report_rows() + [
            SimpleNamespace(start_sec=4400, end_sec=4700, media_title="خارج از برنامه")]
        result = video_clips.select_report_segments(
            rows, 4500, limit=12, min_seconds=30, max_seconds=1800)
        self.assertEqual(len(result), 4)
        self.assertEqual(result[1][1] - result[1][0], 899)


if __name__ == "__main__":
    unittest.main()
