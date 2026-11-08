"""Safety tests for the standalone public WilAI FTPS package."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_wilai_public.py"
SPEC = importlib.util.spec_from_file_location("build_wilai_public", SCRIPT)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class PublicPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.docs = self.root / "docs"
        (self.docs / "atlas").mkdir(parents=True)
        (self.docs / "data").mkdir()
        (self.docs / "wilai").mkdir()
        (self.docs / "wilai" / "index.html").write_text("Home", encoding="utf-8")
        (self.docs / "atlas" / "index.html").write_text("Atlas", encoding="utf-8")
        (self.docs / "atlas" / "atlas-pro.js").write_text("//public", encoding="utf-8")
        (self.docs / "atlas" / "atlas-pro.css").write_text("body{}", encoding="utf-8")
        (self.docs / "atlas" / "overrides.json").write_text('{"schema":1}', encoding="utf-8")
        (self.docs / "atlas" / "private.json").write_text('{"not_public":true}', encoding="utf-8")
        (self.docs / "atlas" / ".env").write_text("DONT_COPY", encoding="utf-8")
        (self.docs / "data" / "private.json").write_text('{"secret":true}', encoding="utf-8")
        self.write_index([{"path": "archive-2026.json"}])
        (self.docs / "data" / "content-index.json").write_text(json.dumps({
            "years": [{"path": "content-2026.json"}]}), encoding="utf-8")
        (self.docs / "data" / "archive-2026.json").write_text('{"programs":[]}', encoding="utf-8")
        (self.docs / "data" / "content-2026.json").write_text('{"items":[]}', encoding="utf-8")
        self.original_source, self.original_target = builder.SOURCE, builder.TARGET
        builder.SOURCE = self.docs
        builder.TARGET = self.root / "out"
        self.addCleanup(self.restore)

    def restore(self):
        builder.SOURCE, builder.TARGET = self.original_source, self.original_target

    def write_index(self, years):
        (self.docs / "data" / "index.json").write_text(
            json.dumps({"years": years}), encoding="utf-8")

    def test_only_public_files_are_copied(self):
        counts = builder.build()
        self.assertEqual(counts["data_files"], 4)
        self.assertTrue((builder.TARGET / "index.html").is_file())
        self.assertTrue((builder.TARGET / "atlas" / "atlas-pro.js").is_file())
        self.assertFalse((builder.TARGET / "data" / "private.json").exists())
        self.assertFalse((builder.TARGET / "atlas" / ".env").exists())
        self.assertFalse((builder.TARGET / "atlas" / "private.json").exists())

    def test_reject_unexpected_archive_path(self):
        self.write_index([{"path": "../private.json"}])
        with self.assertRaises(ValueError):
            builder.build()

    def test_refuse_overwrite_of_existing_package(self):
        builder.TARGET.mkdir()
        with self.assertRaises(ValueError):
            builder.build()


if __name__ == "__main__":
    unittest.main()
