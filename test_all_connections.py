import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

from google import genai


STREAM_URL = os.environ.get("STREAM_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "").strip()
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual")

TEST_SECONDS = int(os.environ.get("TEST_SECONDS", "60"))

AUDIO_FILE = Path("all_connections_audio.mp3")
TRANSCRIPT_FILE = Path("all_connections_transcript.txt")
REPORT_FILE = Path("all_connections_report.json")


def ok(label, detail=""):
    msg = f"✅ {label}"
    if detail:
        msg += f": {detail}"
    print(msg)


def fail(label, detail=""):
    msg = f"❌ {label}"
    if detail:
        msg += f": {detail}"
    print(msg, file=sys.stderr)
    raise RuntimeError(msg)


def check_required_secrets():
    required = {
        "STREAM_URL": STREAM_URL,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "SHEETS_WEBHOOK_URL": SHEETS_WEBHOOK_URL,
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
        "BALE_BOT_TOKEN": BALE_BOT_TOKEN,
        "BALE_CHAT_ID": BALE_CHAT_ID,
    }

    missing = [name for name, value in required.items() if not value]

    if missing:
        fail("GitHub Secrets", "Missing: " + ", ".join(missing))

    ok("GitHub Secrets", "all required secrets exist")


def test_webapp_get():
    try:
        with urllib.request.urlopen(
            SHEETS_WEBHOOK_URL,
            timeout=30,
        ) as response:
            text = response.read().decode("utf-8")

        data = json.loads(text)

        if data.get("ok") is not True:
            fail("Apps Script Web App GET", text)

        ok(
            "Apps Script Web App GET",
            data.get("service", "reachable"),
        )

    except Exception as exc:
        fail("Apps Script Web App GET", repr(exc))


def resolve_stream_url():
    lower = STREAM_URL.lower()

    if "youtube.com" not in lower and "youtu.be" not in lower:
        ok("Stream URL", "direct stream URL")
        return STREAM_URL

    result = subprocess.run(
        [
            "yt-dlp",
            "--no-playlist",
            "-f",
            "bestaudio/best",
            "-g",
            STREAM_URL,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        fail("yt-dlp / Live Stream", "could not resolve stream")

    urls = [
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    ]

    if not urls:
        fail("yt-dlp / Live Stream", "no playable URL returned")

    ok("yt-dlp / Live Stream", "playable audio stream resolved")
    return urls[0]


def capture_audio(media_url):
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-i",
            media_url,
            "-t",
            str(TEST_SECONDS),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(AUDIO_FILE),
        ],
        check=False,
    )

    if result.returncode != 0:
        fail("FFmpeg", "capture failed")

    if not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 1000:
        fail("FFmpeg", "audio file is missing or too small")

    ok(
        "FFmpeg",
        f"{TEST_SECONDS}s audio captured ({AUDIO_FILE.stat().st_size} bytes)",
    )


def transcribe_with_gemini(client):
    try:
        uploaded = client.files.upload(file=str(AUDIO_FILE))

        interaction = client.interactions.create(
            model="gemini-3.5-transcribe",
            input=[
                {
                    "type": "audio",
                    "uri": uploaded.uri,
                    "mime_type": uploaded.mime_type,
                }
            ],
            generation_config={
                "transcription_config": {
                    "language_codes": ["fa-IR"],
                    "custom_vocabulary": [
                        "شبکه جهانی ولایت",
                        "پرسمان اعتقادی",
                        "پرسمان تاریخی",
                        "پرسمان قرآنی",
                        "زمزم احکام",
                        "چراغ",
                        "فائزون",
                        "گامی به سوی ظهور",
                        "اهل‌بیت",
                        "امیرالمؤمنین",
                    ],
                    "mode": "smart",
                }
            },
        )

        transcript = (interaction.output_text or "").strip()

        if not transcript:
            fail("Gemini Transcribe", "empty transcript")

        TRANSCRIPT_FILE.write_text(transcript, encoding="utf-8")

        ok(
            "Gemini Transcribe",
            f"{len(transcript)} characters transcribed",
        )

        return transcript

    except Exception as exc:
        fail("Gemini Transcribe", repr(exc))


def analyze_with_gemini(client, transcript):
    prompt = f"""
این یک تست فنی سامانه رصد برنامه زنده شبکه جهانی ولایت است.

از متن زیر فقط این سه مورد را استخراج کن:
1. یک موضوع کوتاه
2. یک خلاصه 2 تا 4 جمله‌ای
3. حداکثر 3 محور محتوایی

پاسخ را فقط به صورت JSON با کلیدهای
topic
summary
key_points
برگردان.

متن:
----------------
{transcript}
----------------
"""

    try:
        interaction = client.interactions.create(
            model="gemini-3.7-flash",
            input=prompt,
        )

        raw = (interaction.output_text or "").strip()

        if not raw:
            fail("Gemini Analysis", "empty analysis")

        # Tolerant extraction for test use.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()

        try:
            data = json.loads(cleaned)
        except Exception:
            data = {
                "topic": "تست تحلیل محتوایی",
                "summary": raw[:1200],
                "key_points": ["خروجی تحلیل Gemini دریافت شد"],
            }

        ok("Gemini Analysis", "analysis response received")
        return data

    except Exception as exc:
        fail("Gemini Analysis", repr(exc))


def post_test_report_to_sheet(analysis):
    report_id = f"ALL_CONNECTIONS_TEST_{GITHUB_RUN_ID}"

    payload = {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id,
        "date": "TEST",
        "day": "آزمایشی",
        "start": "TEST",
        "end": "TEST",
        "program": "تست جامع همه اتصال‌ها",
        "expert": "آزمایشی",
        "topic": analysis.get("topic", "تست اتصال"),
        "summary": analysis.get(
            "summary",
            "تست جامع اتصال GitHub، لایو، Gemini، Google Sheet و بله."
        ),
        "key_points": analysis.get(
            "key_points",
            ["تست جامع اتصال سامانه"]
        ),
        "phone_question_count": 0,
        "message_question_count": 0,
        "unknown_question_count": 0,
        "total_question_count": 0,
        "audience_names": [],
        "questions": [],
        "answered_questions": [],
        "bot_status": "TEST_PENDING",
        "status": "TEST_ALL_CONNECTIONS",
    }

    REPORT_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=45,
        ) as response:
            text = response.read().decode("utf-8")

        data = json.loads(text)

        if data.get("ok") is not True:
            fail("Google Sheets POST", text)

        ok(
            "Google Sheets POST",
            f"report_id={report_id}",
        )

        return report_id

    except Exception as exc:
        fail("Google Sheets POST", repr(exc))


def send_bale_test_message(report_id, analysis):
    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"

    text = (
        "✅ تست جامع سامانه رصد شبکه ولایت موفق بود\n\n"
        "اتصال‌های زیر بررسی شدند:\n"
        "• GitHub Actions و Secrets\n"
        "• لینک لایو و yt-dlp\n"
        "• FFmpeg\n"
        "• Gemini Transcribe\n"
        "• Gemini Analysis\n"
        "• Google Apps Script Web App\n"
        "• Google Sheet\n"
        "• ربات بله\n\n"
        f"📌 موضوع تست: {analysis.get('topic', 'تست اتصال')}\n"
        f"🆔 Report ID: {report_id}"
    )

    body = json.dumps(
        {
            "chat_id": BALE_CHAT_ID,
            "text": text,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            response_text = response.read().decode("utf-8")

        result = json.loads(response_text)

        if result.get("ok") is not True:
            fail("Bale Bot", response_text)

        ok("Bale Bot", "test message sent")

    except Exception as exc:
        fail("Bale Bot", repr(exc))


def update_sheet_bot_status(report_id):
    payload = {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id,
        "update_only": True,
        "bot_status": "TEST_SENT",
    }

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            text = response.read().decode("utf-8")

        data = json.loads(text)

        if data.get("ok") is not True:
            fail("Google Sheets BOT_STATUS update", text)

        ok("Google Sheets BOT_STATUS update", "TEST_SENT")

    except Exception as exc:
        fail("Google Sheets BOT_STATUS update", repr(exc))


def main():
    print("===============================================")
    print("VELAYAT LIVE MONITOR - ALL CONNECTIONS TEST")
    print("===============================================")

    check_required_secrets()
    test_webapp_get()

    media_url = resolve_stream_url()
    capture_audio(media_url)

    client = genai.Client(api_key=GEMINI_API_KEY)

    transcript = transcribe_with_gemini(client)
    analysis = analyze_with_gemini(client, transcript)

    report_id = post_test_report_to_sheet(analysis)
    send_bale_test_message(report_id, analysis)
    update_sheet_bot_status(report_id)

    print("")
    print("===============================================")
    print("✅ ALL CONNECTIONS OK")
    print("===============================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("")
        print("===============================================", file=sys.stderr)
        print(f"❌ TEST FAILED: {exc}", file=sys.stderr)
        print("===============================================", file=sys.stderr)
        raise
