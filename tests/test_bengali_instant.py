"""Network-free tests of the immediate Bengali handoff."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bengali_instant_dispatch as bn


class ImmediateHandoffTests(unittest.TestCase):
    def test_not_enabled_without_toggle(self):
        with patch.dict(os.environ, {"NETWORK": "persian", "ENABLE_BN_DUB_INSTANT": "false"}):
            self.assertFalse(bn.enabled())

    def test_only_persian(self):
        with patch.dict(os.environ, {"NETWORK": "arabic", "ENABLE_BN_DUB_INSTANT": "true"}):
            self.assertFalse(bn.enabled())

    def test_immediately_enqueue_each_of_first_two(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "clip.mp4"
            video.write_bytes(b"a" * 20000)
            captured = []
            def fake_transfer(stage, artifact, run_id, index):
                manifest = json.loads((stage / "manifest.json").read_text(encoding="utf8"))
                assert (stage / f"source_{index:02}.mp4").exists()
                captured.append((artifact, manifest["destination"], index,
                                 manifest["count"]))
            env = {"NETWORK": "persian", "ENABLE_BN_DUB_INSTANT": "true",
                   "GITHUB_RUN_ID": "112", "GITHUB_TOKEN": "example-test-token"}
            with patch.dict(os.environ, env):
                with patch.object(bn, "_transfer_and_trigger", side_effect=fake_transfer):
                    for i in (1, 2):
                        self.assertTrue(bn.enqueue_after_sent(
                            video, index=i, program="پرسمان", expert="کارشناس",
                            title="پرسش اعتقادی", date="1405", start=30, end=100))
                    self.assertFalse(bn.enqueue_after_sent(
                        video, index=3, program="پرسمان", expert="کارشناس",
                        title="پرسش اعتقادی", date="1405", start=30, end=100))
                    bn.drain_pending(timeout=10)
            self.assertEqual(len(captured), 2)
            self.assertEqual(set(t[0] for t in captured),
                             {"bengali-clip-112-1", "bengali-clip-112-2"})
            self.assertTrue(all(t[1] == "@double_vtv" and t[3] == 1 for t in captured))


if __name__ == "__main__":
    unittest.main()
