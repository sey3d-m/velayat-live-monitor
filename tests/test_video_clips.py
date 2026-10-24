"""No-network guardrails for compressed live-program clips."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import video_clips


def clip(start, end, priority="high", title="نمونه"):
    return SimpleNamespace(start_sec=start, end_sec=end, priority=priority, media_title=title)


class ClipTests(unittest.TestCase):
    def test_prioritizes_high(self):
        rows = [clip(180, 225, "low"), clip(20, 60, "high")]
        self.assertEqual(video_clips.select_segments(rows, 300)[0][:2], (20, 60))

    def test_limits_to_two(self):
        rows = [clip(0, 30), clip(60, 90), clip(130, 190)]
        self.assertEqual(len(video_clips.select_segments(rows, 300)), 2)

    def test_rejects_short_invalid_or_overlapping(self):
        rows = [clip(0, 30), clip(15, 45), clip(50, 55), clip(-5, 25)]
        self.assertEqual(video_clips.select_segments(rows, 90), [(0, 30, "نمونه")])

    def test_maximum_length_100_seconds(self):
        self.assertEqual(video_clips.select_segments([clip(20, 450)], 500)[0][1], 120)

    def test_clamps_to_recorded_duration(self):
        self.assertEqual(video_clips.select_segments([clip(80, 140)], 110)[0][:2], (80, 110))

    def test_disabled_mode(self):
        with patch.dict("os.environ", {"ENABLE_BALE_VIDEO_CLIPS": "false"}):
            self.assertFalse(video_clips.enabled())

    def test_unavailable_is_not_success(self):
        with patch.dict("os.environ", {"ENABLE_BALE_VIDEO_CLIPS": "true"}):
            result = video_clips.send_bale_clips(None, [clip(0, 30)], 90, "t", "c", "p")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["sent"], [])


    def test_complete_caption_has_real_newlines(self):
        caption = video_clips.format_bale_caption(
            title="آیا باران به اذن امام زمان است؟",
            expert="حجت‌الاسلام نمونه", program="گامی به سوی ظهور",
            date="۱۴۰۵/۰۷/۳۰", description="دیدگاه‌های مختلف درباره این موضوع بررسی می‌شود.",
            hashtags=["#مهدویت", "#ظهور"], start=660, end=760,
        )
        for part in ("🎬 تیتر:", "🎙 کارشناس:", "📺 برنامه:",
                     "📅 تاریخ:", "📝 کپشن:", "#مهدویت", "11:00", "12:40"):
            self.assertIn(part, caption)
        self.assertIn("\n", caption)
        self.assertNotIn("\\n", caption)
        self.assertLessEqual(len(caption), 900)

    def test_clip_specific_description(self):
        row = clip(10, 40, title="عنوان")
        row.caption = "توضیح اختصاصی این بخش"
        row.angle = "خلاصه کلی"
        self.assertEqual(video_clips.description_for([row], 10, "عنوان"),
                         "توضیح اختصاصی این بخش")

    def test_caption_works_without_ai_description(self):
        caption = video_clips.format_bale_caption(
            title="موضوع", expert="نامشخص", program="گامی به سوی ظهور",
            date="1405/08/01", description="",
            hashtags=[], start=0, end=60)
        self.assertIn("در این بخش از برنامه", caption)
        self.assertIn("#گامی_به_سوی_ظهور", caption)

    def test_speed_defaults_to_1_0(self):
        with patch.dict("os.environ", {"BALE_CLIP_PLAYBACK_SPEED": ""}):
            self.assertEqual(video_clips.playback_speed(), 1.0)

    def test_precise_trim_reencodes_video_and_audio_together(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            with patch.object(video_clips, "PRIVATE_DIR", Path(d)), \
                 patch("video_clips.subprocess.run") as process:
                def fake_ffmpeg(cmd, **kwargs):
                    (Path(d) / "clip_01.mp4").write_bytes(b"0" * 6000)
                    return SimpleNamespace(returncode=0, stderr=b"")
                process.side_effect = fake_ffmpeg
                video_clips.make_clip("input.mp4", 50, 110, 1)
                cmd = process.call_args.args[0]
        self.assertNotIn("copy", cmd)
        self.assertIn("libx264", cmd)
        self.assertIn("atempo=1.5,asetpts=PTS-STARTPTS", cmd)
        self.assertTrue(any("setpts=(PTS-STARTPTS)/1.5,fps=25,scale=" in arg for arg in cmd))
        self.assertLess(cmd.index("-t"), cmd.index("-i"))
        self.assertEqual(cmd[cmd.index("-t") + 1], "60")

    def test_real_ffmpeg_healthy_first_frame_and_synchronized_tracks(self):
        import json
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg unavailable on this host")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "source.mp4"
            create = subprocess.run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000",
                "-t", "5", "-c:v", "libx264", "-preset", "ultrafast",
                "-g", "48", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(src)
            ], capture_output=True, timeout=45)
            if create.returncode:
                self.skipTest("Host FFmpeg cannot create H.264/AAC: " +
                              create.stderr.decode("utf8", "replace")[-250:])
            with patch.object(video_clips, "PRIVATE_DIR", Path(d)), \
                 patch.dict("os.environ", {"BALE_CLIP_PLAYBACK_SPEED": "1.5"}):
                dest = video_clips.make_clip(src, 1, 4, 1)
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,duration", "-of", "json", str(dest)
            ], capture_output=True, text=True, check=True, timeout=30)
            streams = json.loads(probe.stdout)["streams"]
            track_durations = {s["codec_type"]: float(s["duration"])
                               for s in streams if s.get("duration")}
            self.assertIn("audio", track_durations)
            self.assertIn("video", track_durations)
            self.assertAlmostEqual(track_durations["video"], 2.0, delta=0.15)
            self.assertAlmostEqual(track_durations["audio"],
                                   track_durations["video"], delta=0.2)
            frames = subprocess.run([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "frame=key_frame,best_effort_timestamp_time",
                "-of", "json", str(dest),
            ], capture_output=True, text=True, check=True, timeout=30)
            first = json.loads(frames.stdout)["frames"][0]
            self.assertEqual(first["key_frame"], 1)
            self.assertLess(float(first["best_effort_timestamp_time"]), 0.1)



    def test_candidate_ranking_picks_two_different_high_impact_topics(self):
        first = clip(25, 85, "high", "چرا ظهور به تأخیر می‌افتد؟")
        first.why_viral = "پرسش عمومی و پاسخ روشنگر"
        duplicate = clip(30, 80, "high", "چرا ظهور به تأخیر می‌افتد؟")
        third = clip(180, 250, "high", "پاسخ به یک شبهه مهم")
        fourth = clip(300, 370, "low", "مرور کلی برنامه")
        chosen = video_clips.select_segments(
            [fourth, duplicate, third, first], 500, limit=2)
        self.assertEqual(len(chosen), 2)
        self.assertEqual({chosen[0][0], chosen[1][0]}, {25, 180})

    def test_from_keypoints_when_only_one_viral_suggestion(self):
        viral = clip(20, 75, "high", "آیا این سخن درست است؟")
        viral.why_viral = "تبیین یک مسئله"
        keypoint = SimpleNamespace(
            start_sec=170, end_sec=235, title="بررسی پاسخ کارشناسی درباره مهدویت")
        analysis = SimpleNamespace(
            viral_clips=[viral], key_points=[keypoint], audience_questions=[])
        candidates = video_clips.build_clip_candidates(analysis, "", 300)
        self.assertEqual(len(video_clips.select_segments(candidates, 300)), 2)

    def test_transcript_only_fallback_yields_two_actual_nonfiction_clips(self):
        timed = (
            "[00:00 - 00:30] چرا در روایات از این موضوع سخن گفته می‌شود و دلیل آن چیست؟\n"
            "[00:31 - 01:02] در این بحث توضیح کارشناسی مطرح می‌شود و پاسخ ادامه می‌یابد.\n"
            "[02:20 - 02:45] آیا این اختلاف در تفسیر متون وجود دارد و چگونه باید بررسی کرد؟\n"
            "[02:46 - 03:18] برای روشن شدن این مسئله چند نکته به عنوان توضیح آمده است."
        )
        analysis = SimpleNamespace(
            viral_clips=[], key_points=[], audience_questions=[])
        candidates = video_clips.build_clip_candidates(analysis, timed, 250)
        chosen = video_clips.select_segments(candidates, 250)
        self.assertEqual(len(chosen), 2)
        self.assertTrue(all(any(
            candidate.start_sec == start and candidate.media_title == title
            for candidate in candidates) for start, _end, title in chosen))
        self.assertTrue(all(start < end for start, end, _ in chosen))

    def test_bale_uses_alternative_after_failure_and_clip_only_channel(self):
        import tempfile
        from pathlib import Path
        candidates = [
            clip(0, 60, "high", "موضوع اول؟"),
            clip(90, 150, "high", "موضوع دوم؟"),
            clip(180, 240, "medium", "موضوع سوم؟"),
            clip(275, 335, "low", "موضوع چهارم؟"),
        ]
        with tempfile.TemporaryDirectory() as d:
            source = Path(d) / "src.mp4"
            source.write_bytes(b"x" * 5000)
            output = Path(d) / "clip.mp4"
            output.write_bytes(b"x" * 6000)
            def encoder(_src, start, end, index):
                if start == 0:
                    raise RuntimeError("first candidate cannot be encoded")
                return output
            reply = SimpleNamespace(status_code=200, json=lambda: {"ok": True})
            with patch.object(video_clips, "make_clip", side_effect=encoder), \
                 patch("video_clips.requests.post", return_value=reply) as sent:
                result = video_clips.send_bale_clips(
                    source, candidates, 400, "token", "chat", "برنامه",
                    expert="کارشناس", date="۱۴۰۵/۰۸/۰۱", hashtags=["#مهدویت"])
            self.assertEqual(result["status"], "partial")
            self.assertEqual(len(result["sent"]), 3)
            self.assertEqual(sent.call_count, 3)
            self.assertEqual({x["start_sec"] for x in result["sent"]}, {90, 180, 275})
            self.assertEqual(sent.call_args.kwargs["data"]["chat_id"], "@live_vtv")

    def test_no_transcript_no_ai_does_not_fabricate_viral_speech(self):
        empty = SimpleNamespace(
            viral_clips=[], key_points=[], audience_questions=[])
        self.assertEqual(video_clips.build_clip_candidates(empty, "", 3600), [])


if __name__ == "__main__":
    unittest.main()
