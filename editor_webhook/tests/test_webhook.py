"""Offline contract checks. NO Bale token, GitHub writes or live webhook."""
import base64
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
cal = types.ModuleType("extra_schedule")
cal.CONFIG = Path("unused")
cal.MIRROR = Path("unused")
cal.validate_records = lambda records: records
kb = types.ModuleType("didban_bot_keyboards")
kb.keyboard_for = lambda state, key, auth: {"keyboard": [[{"text": "menu"}]]}
bot = types.ModuleType("didban_calendar_bot")
bot.session_key = lambda token, sender: "test-key"
bot.normal = lambda value: value.strip()
bot.handle_message = lambda state, token, admins, update: (12, "ok")

with patch.dict(sys.modules, {
    "extra_schedule": cal, "didban_bot_keyboards": kb, "didban_calendar_bot": bot
}):
    spec = importlib.util.spec_from_file_location(
        "webhook_under_test", ROOT / "api" / "index.py")
    svc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(svc)


class EditorWebhookTests(unittest.TestCase):
    def test_callback_query_is_supported(self):
        event = {"update_id": 9, "callback_query": {
            "id": "callback-a", "data": "📋 برنامه‌ها",
            "from": {"id": 12},
            "message": {"chat": {"type": "private", "id": 12}}}}
        update, callback_id = svc.normalize(event)
        self.assertEqual(callback_id, "callback-a")
        self.assertEqual(update["message"]["text"], "📋 برنامه‌ها")

    def test_untrusted_post_is_rejected(self):
        fake = Mock()
        fake.headers = {}
        with patch.dict(svc.os.environ, {
            "DIDBAN_EDITOR_WEBHOOK_SECRET": "secret"
        }):
            svc.handler.do_POST(fake)
        fake.output.assert_called_once_with(403, {"ok": False})

    def test_cannot_accept_diverged_calendar_files(self):
        def remote(method, path, data=None):
            programs = [1] if "docs/data/" in path else []
            encoded = base64.b64encode(
                json.dumps({"version": 1, "programs": programs}).encode())
            return {"content": encoded.decode()}
        with patch.object(svc, "gh", remote):
            with self.assertRaises(svc.ServiceError):
                svc.remote_calendar()

    def test_calendar_mutation_is_one_git_commit(self):
        calls = []
        prev = '{"version":1,"programs":[]}'
        def fake(method, path, data=None):
            calls.append((method, path, data))
            if path == "git/ref/heads/main":
                return {"object": {"sha": "head"}}
            if path == "git/commits/head":
                return {"tree": {"sha": "old-tree"}}
            if path == "git/trees":
                return {"sha": "new-tree"}
            if path == "git/commits":
                return {"sha": "new-head"}
            return {}
        with patch.object(svc, "gh", fake), patch.object(svc, "remote_calendar", return_value=prev):
            svc.publish_calendar(prev, '{"version":1,"programs":[1]}', 999)
        tree = [p for method, path, p in calls
                if method == "POST" and path == "git/trees"][0]
        self.assertEqual(set(row["path"] for row in tree["tree"]), set(svc.CALENDAR_PATHS))
        ref = [p for method, path, p in calls if method == "PATCH"][0]
        self.assertIs(ref["force"], False)

    def test_conflicting_remote_change_rejected_before_writing(self):
        calls = []
        def fake(method, path, data=None):
            calls.append((method, path))
            return {"object": {"sha": "head"}}
        with patch.object(svc, "gh", fake), patch.object(svc, "remote_calendar",
                 return_value='{"version":1,"programs":[1]}'):
            with self.assertRaises(svc.ServiceError):
                svc.publish_calendar('{"version":1,"programs":[]}', "{}", 11)
        self.assertEqual(len(calls), 1)

    def test_engine_uses_temporary_calendar(self):
        with patch.object(svc.bot, "handle_message", return_value=(12, "ok")):
            result = svc.apply_editor({"sessions": {}}, {"update_id": 22, "message": {
                "from": {"id": 12}}}, svc.EMPTY_CALENDAR, {12}, "fake",
                lambda *args: self.fail("Unexpected GitHub mutation"))
        self.assertEqual(result[1], "ok")


if __name__ == "__main__":
    unittest.main()
