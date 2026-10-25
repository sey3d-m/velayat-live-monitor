"""No-network tests for staging exactly the two successfully published viral clips."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bengali_instant_dispatch as bn


class ViralHandoffTests(unittest.TestCase):
    def test_not_enabled_without_toggle(self):
        with patch.dict(os.environ, {"NETWORK": "persian", "ENABLE_BN_DUB_INSTANT": "false"}):
            self.assertFalse(bn.enabled())

    def test_only_persian(self):
        with patch.dict(os.environ, {"NETWORK": "arabic", "ENABLE_BN_DUB_INSTANT": "true"}):
            self.assertFalse(bn.enabled())

    def test_stages_only_first_two_published_report_clips(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            mp4 = root / "clip.mp4"
            mp4.write_bytes(b"a" * 20000)
            env = {"NETWORK": "persian", "ENABLE_BN_DUB_INSTANT": "true",
                   "GITHUB_RUN_ID": "112"}
            with patch.dict(os.environ, env), \
                 patch.object(bn, "STAGE_ROOT", root / "bengali_stage"):
                for i, (start, end, title) in enumerate([
                    (947, 1330, "غدیر و نامه به معاویه"),
                    (1330, 2229, "روایت ابن عباس"),
                ], 1):
                    self.assertTrue(bn.enqueue_after_sent(
                        mp4, index=i, program="بیان امیر", expert="کارشناس",
                        title=title, date="۱۴۰۵/۰۸/۰۳",
                        start=start, end=end))
                self.assertFalse(bn.enqueue_after_sent(
                    mp4, index=3, program="بیان امیر", expert="کارشناس",
                    title="سوژه سوم", date="۱۴۰۵/۰۸/۰۳",
                    start=2311, end=2530))
                for i, expected_start in [(1, 947), (2, 1330)]:
                    stage = root / "bengali_stage" / f"clip_{i:02}"
                    data = json.loads((stage / "manifest.json").read_text())
                    self.assertEqual(data["destination"], "@double_vtv")
                    self.assertEqual(data["source"], "@live_vtv")
                    self.assertEqual(data["clips"][0]["start_sec"], expected_start)
                    self.assertEqual(data["clip_index"], i)
                    self.assertTrue((stage / f"source_{i:02}.mp4").is_file())
                self.assertFalse((root / "bengali_stage" / "clip_03").exists())

    def test_no_publish_before_successful_video_exists(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"NETWORK": "persian", "ENABLE_BN_DUB_INSTANT": "true",
                                         "GITHUB_RUN_ID": "123"}), \
                 patch.object(bn, "STAGE_ROOT", Path(folder) / "stage"):
                result = bn.enqueue_after_sent(
                    Path(folder) / "missing.mp4", index=1, program="پرسمان",
                    expert="", title="", date="", start=0, end=80)
                self.assertFalse(result)
                self.assertFalse((Path(folder) / "stage").exists())


if __name__ == "__main__":
    unittest.main()
