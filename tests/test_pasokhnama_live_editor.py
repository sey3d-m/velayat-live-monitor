"""Offline safety checks for TV editorial rewriting; no external API needed."""
import json
import unittest
from unittest.mock import patch
from pasokhnama_live_editor import validate, rewrite

SPEECH = (
    "اگر نماز ظهر و عصر را با هم می‌خوانید برای نماز ظهر اذان می‌گویید "
    "و برای هر کدام از نماز ظهر و عصر یک اقامه جداگانه گفته می‌شود. "
    "اگر هم نماز مغرب و عشا با هم خوانده شود حکم اذان و اقامه بررسی می‌شود."
)
EVIDENCE = "برای هر کدام از نماز ظهر و عصر یک اقامه جداگانه گفته می‌شود"
VALID = {
    "publish": True,
    "scope": "topic_only",
    "title": "بررسی اذان و اقامه هنگام خواندن نماز ظهر و عصر",
    "summary": "در این بخش موضوع گفتن اذان و اقامه هنگام خواندن نماز ظهر و عصر پشت سر هم مطرح شده است. گفت‌وگو به نحوه گفتن اذان و اقامه برای نمازهای روزانه مربوط است.",
    "evidence_excerpt": EVIDENCE,
    "confidence": 0.94,
}

class EditorialTests(unittest.TestCase):
    def test_grounded_title_and_formatted_copy(self):
        result = validate(SPEECH, VALID)
        self.assertEqual(result["kind"], "edited_transcript")
        self.assertEqual(result["title"], VALID["title"])
        self.assertEqual(result["verification_status"], "machine_edited_unverified")

    def test_rejects_no_publish_and_bad_evidence(self):
        self.assertIsNone(validate(SPEECH, {**VALID, "publish": False}))
        self.assertIsNone(validate(SPEECH, {**VALID, "evidence_excerpt": "موضوعی که هرگز بیان نشده است"}))

    def test_rejects_false_confidence_or_invented_numbers(self):
        self.assertIsNone(validate(SPEECH, {**VALID, "confidence": 0.5}))
        self.assertIsNone(validate(SPEECH, {**VALID, "summary": VALID["summary"] + " 12345"}))

    def test_topic_only_preserves_subject_without_invented_rulings(self):
        topic = {
            "publish": True,
            "scope": "topic_only",
            "title": "بررسی اذان و اقامه هنگام خواندن نمازهای روزانه",
            "summary": "در این بخش موضوع اذان و اقامه در نمازهای روزانه و نحوه خواندن نماز ظهر و عصر در کنار هم مطرح شده و درباره آن گفت‌وگو صورت گرفته است.",
            "evidence_excerpt": EVIDENCE,
            "confidence": 0.86,
        }
        edited = validate(SPEECH, topic)
        self.assertIsNotNone(edited)
        self.assertEqual(edited["scope"], "topic_only")
        self.assertIsNone(validate(SPEECH, {
            **topic, "summary": "در این بخش گفته شد که این نماز واجب است و هرگز نباید تغییر کند."
        }))

    def test_religious_explanation_and_unsupported_fatwa_blocked(self):
        self.assertIsNone(validate(SPEECH, {
            **VALID, "scope": "explanation",
            "title": "حکم قطعی اذان برای نماز ظهر و عصر",
        }))
        self.assertIsNone(validate(SPEECH, {
            **VALID, "summary": "در این بخش گفته شد که برای تمام نمازهای نافله اذان و اقامه مستحب است و می‌توان این کار را به‌صورت همیشگی انجام داد.",
        }))

    def test_does_not_publish_raw_text_without_key(self):
        self.assertIsNone(rewrite(SPEECH * 2, ""))

    def test_rejects_malformed_provider_response(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit): return b'{"candidates":[{"content":{"parts":[{"text":"not-json"}]}}]}'
        with patch("pasokhnama_live_editor.urllib.request.urlopen", return_value=Reply()):
            with self.assertRaises(RuntimeError):
                rewrite(SPEECH * 2, "test-token")

    def test_accepts_guarded_provider_response(self):
        class Reply:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, _limit):
                result=json.dumps(VALID,ensure_ascii=False)
                return json.dumps({"candidates":[{"content":{"parts":[{"text":result}]}}]}).encode()
        with patch("pasokhnama_live_editor.urllib.request.urlopen", return_value=Reply()):
            self.assertEqual(rewrite(SPEECH * 2, "test-token")["title"], VALID["title"])

if __name__ == "__main__":
    unittest.main()
