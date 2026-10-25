"""Safety regression tests for the independent Bengali handoff (no network/ML)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bengali_dubbing
import bengali_dubbing_export


class BengaliExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patcher = patch("bengali_dubbing_export.SOURCE", self.root / "private_live_video")
        self.patcher2 = patch("bengali_dubbing_export.OUT", self.root / "bengali_dub_input")
        self.patcher.start()
        self.patcher2.start()
        (self.root / "private_live_video").mkdir()
        self.old_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.patcher2.stop()
        self.patcher.stop()
        self.tmp.cleanup()

    def _report(self, destination_count=2):
        clips = []
        for n in range(1, destination_count + 1):
            filename = f"clip_{n:02}.mp4"
            (self.root / "private_live_video" / filename).write_bytes(b"v" * 20000)
            clips.append({"filename": filename, "title": f"موضوع {n}",
                          "start_sec": n * 100, "end_sec": n * 100 + 60})
        data = {"network": "persian", "run_id": "1234", "date": "1405/08/02",
                "program": "پرسمان", "analysis": {"expert": "کارشناس"},
                "video_clips": {"sent": clips}}
        (self.root / "program_report.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_export_two_only(self):
        self._report(4)
        with patch.dict(os.environ, {"ENABLE_BN_DUB_EXPORT": "true"}):
            self.assertTrue(bengali_dubbing_export.export_for_dubbing())
        manifest = json.loads((self.root / "bengali_dub_input" / "manifest.json").read_text())
        self.assertEqual(manifest["count"], 2)
        self.assertEqual(manifest["destination"], "@double_vtv")
        self.assertEqual(len(manifest["clips"]), 2)
        self.assertTrue((self.root / "bengali_dub_input" / "source_02.mp4").exists())

    def test_skip_if_only_one_persian_clip_sent(self):
        self._report(1)
        with patch.dict(os.environ, {"ENABLE_BN_DUB_EXPORT": "true"}):
            self.assertFalse(bengali_dubbing_export.export_for_dubbing())
        self.assertFalse((self.root / "bengali_dub_input" / "manifest.json").exists())

    def test_export_disabled_by_default(self):
        self._report(2)
        with patch.dict(os.environ, {"ENABLE_BN_DUB_EXPORT": "false"}):
            self.assertFalse(bengali_dubbing_export.export_for_dubbing())

    def test_reject_path_traversal(self):
        self._report(2)
        data = json.loads((self.root / "program_report.json").read_text())
        data["video_clips"]["sent"][0]["filename"] = "../secret.mp4"
        (self.root / "program_report.json").write_text(json.dumps(data))
        with patch.dict(os.environ, {"ENABLE_BN_DUB_EXPORT": "true"}):
            with self.assertRaises(ValueError):
                bengali_dubbing_export.export_for_dubbing()


class BengaliDubbingSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patcher = patch.object(bengali_dubbing, "SOURCE_DIR", self.root)
        self.patcher.start()
        for n in (1, 2):
            (self.root / f"source_{n:02}.mp4").write_bytes(b"0" * 20000)
        self.manifest = {"schema": 1, "run_id": "321",
                         "network": "persian", "source": "@live_vtv",
                         "destination": "@double_vtv", "count": 2,
                         "clips": [{"filename": "source_01.mp4"},
                                   {"filename": "source_02.mp4"}]}

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_verified_manifest(self):
        with patch.dict(os.environ, {"ORIGIN_RUN_ID": "321"}):
            self.assertEqual(
                bengali_dubbing.validate_manifest(self.manifest)["count"], 2)

    def test_single_report_viral_clip_can_be_dubbed(self):
        self.manifest["count"] = 1
        self.manifest["clip_index"] = 1
        self.manifest["clips"] = [{"filename": "source_01.mp4",
            "start_sec": 947, "end_sec": 1330,
            "title_fa": "استناد به غدیر"}]
        with patch.dict(os.environ, {"BN_EXPECT_COUNT": "1", "ORIGIN_RUN_ID": "321"}):
            self.assertEqual(bengali_dubbing.validate_manifest(self.manifest)["clips"][0]["end_sec"], 1330)

    def test_second_long_viral_clip_can_be_dubbed(self):
        self.manifest["count"] = 1
        self.manifest["clip_index"] = 2
        self.manifest["clips"] = [{"filename": "source_02.mp4",
            "start_sec": 1330, "end_sec": 2229, "title_fa": "روایت ابن عباس"}]
        with patch.dict(os.environ, {"BN_EXPECT_COUNT": "1"}):
            self.assertEqual(bengali_dubbing.validate_manifest(self.manifest)["clips"][0]["end_sec"], 2229)

    def test_duplicate_manifest_file_is_rejected(self):
        self.manifest["clips"][1]["filename"] = "source_01.mp4"
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            bengali_dubbing.validate_manifest(self.manifest)

    def test_reject_incorrect_channel(self):
        self.manifest["destination"] = "@live_vtv"
        with self.assertRaises(ValueError):
            bengali_dubbing.validate_manifest(self.manifest)

    def test_reject_different_run(self):
        with patch.dict(os.environ, {"ORIGIN_RUN_ID": "999"}):
            with self.assertRaises(ValueError):
                bengali_dubbing.validate_manifest(self.manifest)

    def test_reject_non_two(self):
        self.manifest["clips"].pop()
        with self.assertRaises(ValueError):
            bengali_dubbing.validate_manifest(self.manifest)


if __name__ == "__main__":
    unittest.main()
