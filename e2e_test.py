import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

import jdatetime
from google import genai
from pydantic import BaseModel, Field

STREAM_URL = os.environ.get("STREAM_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
SHEETS_WEBHOOK_URL = os.environ.get("SHEETS_WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
TEST_SECONDS = int(os.environ.get("TEST_SECONDS", "300"))
GITHUB_RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual")

AUDIO_FILE = Path("e2e_test_audio.mp3")
TRANSCRIPT_FILE = Path("e2e_transcript.txt")
REPORT_FILE = Path("e2e_report.json")

CUSTOM_VOCABULARY = [
    "شبکه جهانی ولایت", "زمزم احکام", "آفتاب و سایه ها", "آفتاب و سایه‌ها",
    "پرسمان اعتقادی", "امت اسلام", "بیان امیر", "فائزون", "فرکانس تاریکی",
    "پرسمان مذاهب", "کانون مهر", "پیام تاریخ", "پرسمان قرآنی", "چراغ",
    "پرسمان تاریخی", "گامی به سوی ظهور", "حیات قرآنی", "اهل بیت", "اهل‌بیت",
    "امیرالمؤمنین", "حضرت زهرا", "فاطمه زهرا", "امام زمان", "مهدویت",
    "شیعه", "اهل سنت", "اهل‌سنت", "سلفیه", "وهابیت", "قرآن کریم",
    "نهج البلاغه", "نهج‌البلاغه"
]

class ProgramAnalysis(BaseModel):
    expert: str = Field(description="نام کارشناس فقط اگر از متن قابل تشخیص است؛ در غیر این صورت نامشخص")
    topic: str = Field(description="عنوان کوتاه و دقیق موضوع اصلی")
    summary: str = Field(description="خلاصه محتوایی منسجم فارسی")
    key_points: list[str] = Field(description="محورهای اصلی و مستقل برنامه")
    questions: list[str] = Field(description="پرسش‌ها یا شبهات صریح مطرح‌شده؛ در غیر این صورت آرایه خالی")

def fail(message: str):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)

def check_secrets():
    missing = [name for name, value in [
        ("STREAM_URL", STREAM_URL),
        ("GEMINI_API_KEY", GEMINI_API_KEY),
        ("SHEETS_WEBHOOK_URL", SHEETS_WEBHOOK_URL),
        ("WEBHOOK_SECRET", WEBHOOK_SECRET),
    ] if not value]
    if missing:
        fail("Missing secrets: " + ", ".join(missing))

def resolve_stream_url(url: str) -> str:
    if "youtube.com" in url.lower() or "youtu.be" in url.lower():
        print("YouTube URL detected. Resolving live audio URL...")
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-g", url],
            capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            fail("yt-dlp could not resolve the live stream.")
        urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not urls:
            fail("yt-dlp returned no playable URL.")
        return urls[0]
    return url

def capture_audio(media_url: str):
    print(f"Capturing {TEST_SECONDS} seconds from the live stream...")
    result = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        "-i", media_url, "-t", str(TEST_SECONDS), "-vn", "-ac", "1",
        "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(AUDIO_FILE)
    ], check=False)
    if result.returncode != 0:
        fail("FFmpeg could not capture the stream.")
    if not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 1000:
        fail("Audio file was not created or is unexpectedly small.")
    print("Audio captured successfully:", AUDIO_FILE.stat().st_size, "bytes")

def transcribe_audio(client: genai.Client) -> str:
    print("Uploading audio to Gemini 3.5 Transcribe...")
    uploaded = client.files.upload(file=str(AUDIO_FILE))
    interaction = client.interactions.create(
        model="gemini-3.5-transcribe",
        input=[{"type": "audio", "uri": uploaded.uri, "mime_type": uploaded.mime_type}],
        generation_config={"transcription_config": {
            "language_codes": ["fa-IR"],
            "custom_vocabulary": CUSTOM_VOCABULARY,
            "mode": "smart"
        }},
    )
    transcript = (interaction.output_text or "").strip()
    if not transcript:
        fail("Gemini returned an empty transcription.")
    TRANSCRIPT_FILE.write_text(transcript, encoding="utf-8")
    print("Transcription completed. Characters:", len(transcript))
    return transcript

def analyze_transcript(client: genai.Client, transcript: str) -> ProgramAnalysis:
    print("Analyzing transcript with Gemini Flash...")
    prompt = f'''شما تحلیل‌گر محتوای برنامه‌های زنده شبکه جهانی ولایت هستید.
فقط بر اساس متن زیر تحلیل کنید و هیچ نام، موضوع، نقل‌قول یا ادعایی را حدس نزنید.

قواعد:
1. اگر نام کارشناس صریحاً قابل تشخیص نیست، expert را «نامشخص» بنویس.
2. topic یک عنوان کوتاه و دقیق برای موضوع غالب همین بخش باشد.
3. summary خلاصه‌ای منسجم و بی‌طرف از مطالب واقعاً مطرح‌شده باشد.
4. key_points محورهای مستقل و بدون تکرار باشند.
5. questions فقط پرسش‌ها یا شبهات واقعاً مطرح‌شده باشند؛ اگر نیست آرایه خالی.
6. همه خروجی‌ها فارسی باشند.

متن برنامه:
----------------
{transcript}
----------------
'''
    interaction = client.interactions.create(
        model="gemini-3.7-flash",
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ProgramAnalysis.model_json_schema(),
        },
    )
    output = (interaction.output_text or "").strip()
    if not output:
        fail("Gemini analysis returned an empty response.")
    try:
        analysis = ProgramAnalysis.model_validate_json(output)
    except Exception as exc:
        print("Raw analysis output:")
        print(output)
        fail(f"Could not parse structured analysis: {exc}")
    print("Analysis completed.")
    return analysis

def persian_date() -> str:
    return jdatetime.datetime.now().strftime("%Y/%m/%d")

def send_to_sheet(analysis: ProgramAnalysis):
    print("Sending final report to Google Sheet...")
    report_id = f"E2E_TEST_{GITHUB_RUN_ID}"
    payload = {
        "secret": WEBHOOK_SECRET,
        "report_id": report_id,
        "date": persian_date(),
        "day": "آزمایشی",
        "start": "TEST",
        "end": "TEST",
        "program": "تست کامل سامانه",
        "expert": analysis.expert,
        "topic": analysis.topic,
        "summary": analysis.summary,
        "key_points": analysis.key_points,
        "questions": analysis.questions,
        "status": "TEST_E2E"
    }
    REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        SHEETS_WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            response_text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        print("HTTP ERROR:", exc.code)
        print(exc.read().decode("utf-8", errors="replace"))
        raise
    print("Webhook response:")
    print(response_text)
    try:
        result = json.loads(response_text)
    except json.JSONDecodeError:
        fail("Google Web App did not return valid JSON.")
    if result.get("ok") is not True:
        fail("Google Sheet rejected report: " + json.dumps(result, ensure_ascii=False))
    print("Report saved successfully. Row:", result.get("row"))

def main():
    check_secrets()
    client = genai.Client(api_key=GEMINI_API_KEY)
    media_url = resolve_stream_url(STREAM_URL)
    capture_audio(media_url)
    transcript = transcribe_audio(client)
    analysis = analyze_transcript(client, transcript)
    print("\n========== ANALYSIS ==========")
    print(analysis.model_dump_json(indent=2))
    print("==============================\n")
    send_to_sheet(analysis)
    print("END-TO-END TEST SUCCESSFUL")

if __name__ == "__main__":
    main()
