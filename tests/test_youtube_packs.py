"""Offline regression tests: isolated YouTube text packs and mixed clip plans."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import clip_multisource
import youtube_packs


def item(start, end, title, **kwargs):
    return SimpleNamespace(start_sec=start, end_sec=end, title=title, **kwargs)


def example_analysis():
    topics = [
        item(0, 100, "محور تاریخی آغاز جنگ جمل"),
        item(110, 220, "نقش بیعت در مشروعیت"),
        item(230, 340, "نقد نظریه عدالت صحابه"),
        item(350, 460, "بررسی گزارش های تاریخی حوأب"),
        item(470, 590, "رفتار امام علی پس از نبرد"),
    ]
    questions = [SimpleNamespace(start_sec=600, end_sec=680,
                                 question="علت مخالفت طلحه و زبیر چه بود؟",
                                 answer_summary="کارشناس به زمینه سیاسی پرداخت.")]
    viral = [SimpleNamespace(start_sec=700, end_sec=780,
                             media_title="چرا جنگ جمل رخ داد؟",
                             caption="بحث درباره زمینه جنگ",
                             angle="پرسش تاریخی",
                             why_viral="بحث جذاب",
                             priority="high")]
    return SimpleNamespace(key_points=topics, audience_questions=questions,
                           viral_clips=viral, topic="جنگ جمل",
                           expert="استاد نمونه", hashtags=["#جنگ_جمل"])


class YouTubeAndMixTests(unittest.TestCase):

    def test_plan_has_four_separate_real_time_ranges(self):
        analysis = example_analysis()
        transcript = "".join(
            f"[{a//60:02}:{a%60:02} - {b//60:02}:{b%60:02}] متن مربوط به موضوع واقعی و توضیح منبع \n"
            for a, b in [(0, 100), (110, 220), (230, 340), (350, 460),
                         (470, 590), (600, 680), (700, 780)])
        plan = youtube_packs.build_edit_plan(analysis, transcript, 900)
        self.assertEqual(len(plan), 4)
        self.assertEqual([s.start_sec for s in plan], [0, 110, 230, 350])
        self.assertTrue(all(s.end_sec > s.start_sec for s in plan))
        self.assertTrue(all(s.evidence for s in plan))

    def test_youtube_ai_failure_does_not_break_fallback(self):
        analysis = example_analysis()
        plan = youtube_packs.build_edit_plan(analysis, "", 900)
        self.assertEqual(len(plan), 4)
        drafts, mode = youtube_packs.generate_drafts(None, analysis, plan, "پرسمان تاریخی")
        self.assertEqual(mode, "fallback_no_ai")
        self.assertEqual(len(drafts), 4)
        text = youtube_packs.format_pack(
            plan[0], drafts[0], programme="پرسمان تاریخی",
            date="۱۴۰۵/۰۸/۰۹", expert="استاد نمونه")
        for expected in ("🎬 پک یوتیوب", "✂️ دستور تدوین", "00:00:00",
                         "00:01:40", "English summary", "هشتگ"):
            if expected == "هشتگ":
                self.assertIn("#جنگ_جمل", text)
            else:
                self.assertIn(expected, text)

    def test_only_text_sent_to_dedicated_channel(self):
        analysis = example_analysis()
        plan = youtube_packs.build_edit_plan(analysis, "", 900)
        drafts, _ = youtube_packs.generate_drafts(None, analysis, plan, "برنامه")
        requests_seen = []
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"ok":true}'
        def fake_urlopen(request, timeout=30):
            self.assertTrue(request.full_url.endswith("/sendMessage"))
            payload = json.loads(request.data.decode("utf8"))
            self.assertEqual(payload["chat_id"], "@vtv_youtube")
            self.assertEqual(set(payload), {"chat_id", "text"})
            requests_seen.append(payload)
            return Response()
        with patch("youtube_packs.urllib.request.urlopen", side_effect=fake_urlopen), \
             patch("youtube_packs.time.sleep"):
            result = youtube_packs.send_text_packs(
                "dummy", plan, drafts, programme="برنامه", date="امروز",
                expert="کارشناس")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["sent"], 4)
        self.assertGreaterEqual(len(requests_seen), 4)

    def test_invalid_or_missing_timecodes_are_never_fabricated(self):
        ana = SimpleNamespace(key_points=[item(-1, 90, "نامعتبر"),
                                           item(15, 100, "معتبر"),
                                           item(40, 110, "همپوشان")],
                              audience_questions=[], viral_clips=[])
        plan = youtube_packs.build_edit_plan(ana, "", 120)
        self.assertLessEqual(len(plan), 1)

    def test_multisource_clip_selection_with_category_diversity(self):
        analysis = example_analysis()
        candidates = clip_multisource.build_candidates(analysis)
        mix = clip_multisource.select_mixed_segments(candidates, 900, maximum=8)
        self.assertEqual(len(mix), 7)
        self.assertIn((700, 780, "چرا جنگ جمل رخ داد؟"), mix)
        self.assertIn((600, 680, "علت مخالفت طلحه و زبیر چه بود؟"), mix)
        self.assertTrue(any(title == "محور تاریخی آغاز جنگ جمل"
                            for _, _, title in mix))

    def test_max_mixed_clips_is_ten_and_overlaps_not_reposted(self):
        ana = example_analysis()
        ana.viral_clips.append(SimpleNamespace(
            start_sec=710, end_sec=795, media_title="همپوشانی همان سوژه",
            caption="تکرار", priority="high"))
        rows = clip_multisource.build_candidates(ana)
        mix = clip_multisource.select_mixed_segments(rows, 900, maximum=99)
        self.assertLessEqual(len(mix), clip_multisource.MAX_CLIPS)
        self.assertFalse(any(title == "همپوشانی همان سوژه" for _, _, title in mix))


if __name__ == "__main__":
    unittest.main()
