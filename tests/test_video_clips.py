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


if __name__ == "__main__":
    unittest.main()
