"""Deterministic tests: time zones, recurrence, cancellation and unchanged slots."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import extra_schedule as es


class ExtraCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.json"
        self.mirror = self.root / "mirror.json"
        self.cfg.write_text(json.dumps({"version": 1, "programs": []}))
        self.p1 = patch.object(es, "CONFIG", self.cfg)
        self.p2 = patch.object(es, "MIRROR", self.mirror)
        self.p1.start()
        self.p2.start()

    def tearDown(self):
        self.p2.stop()
        self.p1.stop()
        self.tmp.cleanup()

    def add(self, **kw):
        env = dict(
            EXTRA_ACTION="add", EXTRA_ID="testshow", EXTRA_TITLE="ویژه برنامه تولیدی",
            EXTRA_START="14:00", EXTRA_END="15:00", EXTRA_FREQUENCY="daily",
            EXTRA_FROM_DATE="2026-10-26", EXTRA_UNTIL_DATE="2026-11-30",
            EXTRA_WEEKDAYS="",
        )
        env.update(kw)
        with patch.dict(os.environ, env):
            es.manage_from_env()
        return es.load()[0]

    def update(self, action):
        with patch.dict(os.environ, {"EXTRA_ACTION": action, "EXTRA_ID": "testshow"}):
            es.manage_from_env()

    def test_one_time_and_persian_date(self):
        self.add(EXTRA_FREQUENCY="once", EXTRA_FROM_DATE="1405-08-05", EXTRA_UNTIL_DATE="")
        only = es.parse_day("1405-08-05")
        self.assertTrue(es.is_due_on(es.load()[0], only))
        self.assertFalse(es.is_due_on(es.load()[0], only + timedelta(days=1)))
        self.assertEqual(es.parse_day("1405/08/05"), only)

    def test_daily_range_and_pause_resume_delete(self):
        self.add()
        d = date(2026, 10, 27)
        self.assertEqual(es.get_extra("testshow", d)["title"], "ویژه برنامه تولیدی")
        self.update("pause")
        with self.assertRaises(ValueError):
            es.get_extra("testshow", d)
        self.assertEqual(json.loads(self.mirror.read_text())["programs"][0]["enabled"], False)
        self.update("resume")
        self.assertTrue(es.is_due_on(es.load()[0], d))
        self.update("delete")
        self.assertEqual(es.load(), [])

    def test_weekly_named_days(self):
        self.add(EXTRA_FREQUENCY="weekly", EXTRA_WEEKDAYS="شنبه,دوشنبه")
        program = es.load()[0]
        self.assertTrue(es.is_due_on(program, date(2026, 10, 26)))  # Monday
        self.assertFalse(es.is_due_on(program, date(2026, 10, 27))) # Tuesday
        self.assertTrue(es.is_due_on(program, date(2026, 10, 31)))  # Saturday

    def test_monthly_is_jalali_not_gregorian(self):
        self.add(EXTRA_FREQUENCY="monthly", EXTRA_FROM_DATE="1405-08-05",
                 EXTRA_UNTIL_DATE="1405-10-25")
        p = es.load()[0]
        self.assertEqual(p["month_day"], 5)
        d = es.parse_day("1405-09-05")
        self.assertTrue(es.is_due_on(p, d))
        self.assertFalse(es.is_due_on(p, d + timedelta(days=1)))

    def test_due_window_and_midnight(self):
        self.add(EXTRA_START="23:55", EXTRA_END="00:55")
        now = datetime(2026, 10, 27, 0, 2, tzinfo=ZoneInfo("Asia/Tehran"))
        due = es.get_due(now)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["scheduled_date"], "2026-10-26")
        self.assertEqual(due[0]["identity"], "[extra:testshow:2026-10-26]")

    def test_requires_end_date_for_recurring(self):
        with self.assertRaisesRegex(ValueError, "end date"):
            self.add(EXTRA_UNTIL_DATE="")

    def test_rejects_overlong_window(self):
        with self.assertRaisesRegex(ValueError, "15–180"):
            self.add(EXTRA_START="14:00", EXTRA_END="19:00")

    def test_disallow_unregistered_or_duplicate_id(self):
        self.add()
        with self.assertRaises(ValueError):
            self.add()
        with self.assertRaisesRegex(ValueError, "Unknown"):
            es.get_extra("another_id", date(2026, 10, 27))


if __name__ == "__main__":
    unittest.main()
