"""Tests for new operator configuration and report/clip channel isolation."""
import unittest
from clip_settings import load_clip_settings
from unittest.mock import patch, MagicMock
import video_clips

class PanelTests(unittest.TestCase):
    def test_operator_defaults(self):
        c=load_clip_settings()
        self.assertEqual(c["count_per_program"], 4)
        self.assertEqual(c["destination"], "@live_vtv")
        self.assertEqual(c["speed"], 1.0)
        self.assertEqual(c["max_seconds"], 1800)
    def test_other_networks_disabled(self):
        self.assertTrue(video_clips.enabled("persian"))
        for n in ("azeri","arabic","hausa"):
            self.assertFalse(video_clips.enabled(n))
    def test_real_long_segments(self):
        from types import SimpleNamespace
        a=SimpleNamespace(start_sec=15,end_sec=260,media_title="نمونه بلند",priority="high")
        result=video_clips.select_segments([a],500,limit=4,min_seconds=60,max_seconds=300)
        self.assertEqual(result[0][1],260)
if __name__=="__main__":
    unittest.main()
