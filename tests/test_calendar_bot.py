"""Offline safety tests for the administrator-only Bale schedule control bot."""
import json
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import extra_schedule as cal
import didban_calendar_bot as bot


class CalendarBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.cfg = self.folder / "calendar.json"
        self.mirror = self.folder / "mirror.json"
        self.botstate = self.folder / "bot_state.json"
        self.cfg.write_text('{"version": 1, "programs": []}', encoding="utf-8")
        self.patches = [patch.object(cal, "CONFIG", self.cfg),
                        patch.object(cal, "MIRROR", self.mirror),
                        patch.object(bot, "STATE", self.botstate)]
        for p in self.patches:
            p.start()
        self.state = {"version": 1, "last_update_id": 0, "sessions": {}}
        self.key = bot.session_key("test-token", 12345)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def command(self, text, id=100):
        return bot.process_admin_command(self.state, self.key, id, text)

    def add_once(self):
        day = (datetime.now(bot.TEHRAN).date() + timedelta(days=2)).isoformat()
        self.command("افزودن")
        for text in ["برنامه تولیدی", "13:00", "14:00", "یک‌بار", day]:
            reply = self.command(text)
        self.assertIn("تایید", reply)
        self.assertEqual(cal.load(), [])
        self.assertIn("ثبت شد", self.command("تایید"))
        return "show100", day

    def test_admin_private_only_no_unauthorized_writes(self):
        update = {"update_id": 100, "message": {
            "chat": {"type": "private", "id": 12345},
            "from": {"id": 12345}, "text": "افزودن"}}
        self.assertIsNone(bot.handle_message(self.state, "test-token", set(), update))
        self.assertFalse(self.state["sessions"])
        update["message"]["text"] = "شناسه من"
        self.assertEqual(
            bot.handle_message(self.state, "test-token", set(), update),
            (12345, "شناسه عددی حساب بله شما: 12345")
        )
        update["message"]["chat"]["type"] = "channel"
        self.assertIsNone(bot.handle_message(self.state, "test-token", {12345}, update))

    def test_conversation_confirmation_and_pause_resume_delete(self):
        ident, day = self.add_once()
        self.assertEqual(len(cal.load()), 1)
        self.assertEqual(cal.load()[0]["id"], ident)
        self.assertEqual(cal.load()[0]["title"], "برنامه تولیدی")
        self.assertIn(ident, self.command("برنامه‌ها"))
        self.assertIn("تایید", self.command(f"لغو {ident}"))
        self.assertTrue(cal.load()[0]["enabled"])  # No mutation before confirmation
        self.command("تایید")
        self.assertFalse(cal.load()[0]["enabled"])
        self.command(f"فعال {ident}")
        self.command("تایید")
        self.assertTrue(cal.load()[0]["enabled"])
        self.command(f"حذف {ident}")
        self.command("انصراف")
        self.assertEqual(len(cal.load()), 1)
        self.command(f"حذف {ident}")
        self.command("تایید")
        self.assertEqual(cal.load(), [])

    def test_skip_only_one_occurrence(self):
        ident, day = self.add_once()
        self.assertIn("تایید", self.command(f"لغو نوبت {ident} {day}"))
        self.command("تایید")
        self.assertFalse(cal.is_due_on(cal.load()[0], date.fromisoformat(day)))
        self.assertTrue(cal.load()[0]["enabled"])
        self.command(f"برگرداندن نوبت {ident} {day}")
        self.command("تایید")
        self.assertTrue(cal.is_due_on(cal.load()[0], date.fromisoformat(day)))

    def test_fixed_slot_conflict_fails_without_corrupting_calendar(self):
        # Find the next Monday for the 18:00 fixed Persian program.
        d = datetime.now(bot.TEHRAN).date() + timedelta(days=1)
        while d.weekday() != 0:
            d += timedelta(days=1)
        self.command("افزودن")
        for text in ["برنامه هم‌پوشان", "18:05", "18:50", "یک‌بار"]:
            self.command(text)
        error = self.command(d.isoformat())
        self.assertIn("قابل ثبت نیست", error)
        self.assertEqual(cal.load(), [])
        self.assertEqual(json.loads(self.cfg.read_text())["programs"], [])

    def test_button_main_menu_and_private_security(self):
        menu = bot.kb.keyboard_for(self.state, self.key, True)
        labels = [c["text"] for row in menu["keyboard"] for c in row]
        for label in ("➕ افزودن برنامه", "📋 برنامه‌ها", "📅 تقویم هفته",
                      "⏸ توقف برنامه", "▶️ فعال‌سازی برنامه",
                      "🗑 حذف برنامه", "📆 لغو یک نوبت",
                      "🔄 بازگرداندن نوبت"):
            self.assertIn(label, labels)
        unauthorized = bot.kb.keyboard_for(self.state, None, False)
        noaccess = [c["text"] for row in unauthorized["keyboard"] for c in row]
        self.assertNotIn("🗑 حذف برنامه", noaccess)
        self.assertIn("🆔 شناسه من", noaccess)

    def test_tap_only_registration_and_no_mutation_before_confirm(self):
        self.assertIn("نام", self.command("➕ افزودن برنامه"))
        keyboard = bot.kb.keyboard_for(self.state, self.key, True)
        self.assertIn("📺 برنامه تولیدی", str(keyboard))
        self.assertIn("ساعت", self.command("📺 برنامه تولیدی"))
        self.assertIn("دقیقه", self.command("🕘 06"))
        self.assertIn("پایان", self.command("⏱ 00"))
        self.assertIn("دقیقه", self.command("🕘 07"))
        self.assertIn("تکرار", self.command("⏱ 00"))
        self.assertIn("تاریخ", self.command("🔁 روزانه"))
        self.assertIn("تاریخ", self.command("📅 ۳ روز بعد"))
        self.assertIn("پیش‌نمایش", self.command("🗓 ۳۰ روز"))
        self.assertEqual(cal.load(), [])
        self.assertIn("ثبت شد", self.command("✅ تأیید نهایی"))
        registered = cal.load()[0]
        self.assertEqual(registered["start"], "06:00")
        self.assertEqual(registered["end"], "07:00")
        self.assertEqual(registered["frequency"], "daily")
        self.assertTrue(bot.kb.keyboard_for(self.state, self.key, True)["keyboard"])

    def test_picker_buttons_pause_resume_and_cancel(self):
        ident, _ = self.add_once()
        response = self.command("⏸ توقف برنامه")
        self.assertIn("انتخاب", response)
        button = bot.kb.program_label(cal.load()[0])
        self.assertIn("تایید", self.command(button))
        self.assertTrue(cal.load()[0]["enabled"])
        self.assertIn("لغو", self.command("❌ انصراف"))
        self.assertTrue(cal.load()[0]["enabled"])
        self.command("⏸ توقف برنامه")
        self.command(button)
        self.assertIn("ثبت شد", self.command("✅ تأیید نهایی"))
        self.assertFalse(cal.load()[0]["enabled"])
        self.command("▶️ فعال‌سازی برنامه")
        self.command(button)
        self.command("✅ تأیید نهایی")
        self.assertTrue(cal.load()[0]["enabled"])
        self.command("🗑 حذف برنامه")
        self.command(button)
        self.command("✅ تأیید نهایی")
        self.assertEqual(cal.load(), [])

    def test_button_cancel_single_occurrence_and_restore(self):
        ident, day = self.add_once()
        self.assertIn("انتخاب", self.command("📆 لغو یک نوبت"))
        self.assertIn("تاریخ", self.command(bot.kb.program_label(cal.load()[0])))
        self.assertIn("تایید", self.command("📆 " + day))
        self.assertTrue(cal.is_due_on(cal.load()[0], date.fromisoformat(day)))
        self.command("✅ تأیید نهایی")
        self.assertFalse(cal.is_due_on(cal.load()[0], date.fromisoformat(day)))
        self.command("🔄 بازگرداندن نوبت")
        self.command(bot.kb.program_label(cal.load()[0]))
        self.command("📆 " + day)
        self.command("✅ تأیید نهایی")
        self.assertTrue(cal.is_due_on(cal.load()[0], date.fromisoformat(day)))

    def test_weekly_weekdays_toggle_buttons_and_home(self):
        self.command("➕ افزودن برنامه")
        for step in ("📺 گفت‌وگوی علمی", "🕘 06", "⏱ 00",
                     "🕘 07", "⏱ 00", "📅 هفتگی", "📅 ۷ روز بعد"):
            self.command(step)
        out = self.command("▫️ شنبه")
        self.assertIn("روز", out)
        self.assertIn("شنبه", self.state["sessions"][self.key]["data"]["weekdays"])
        self.command("▫️ دوشنبه")
        selected = self.state["sessions"][self.key]["data"]["weekdays"]
        self.assertIn("دوشنبه", selected)
        self.command("✅ پایان انتخاب روزها")
        self.assertIn("پیش‌نمایش", self.command("🗓 ۳۰ روز"))
        self.assertEqual(cal.load(), [])
        self.assertIn("لغو", self.command("🏠 منوی اصلی"))
        self.assertEqual(cal.load(), [])

    def test_disabled_registry_and_no_secret_storage(self):
        ident, _ = self.add_once()
        bot.save_state(self.state)
        data = self.botstate.read_text()
        self.assertNotIn("12345", data)
        self.assertNotIn("test-token", data)
        self.assertEqual(ident, cal.load()[0]["id"])


if __name__ == "__main__":
    unittest.main()
