import os
import subprocess
import sys
from pathlib import Path

from google import genai

TEST_SECONDS = int(os.getenv("TEST_SECONDS", "60"))
STREAM_URL = os.environ.get("STREAM_URL", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

AUDIO_FILE = Path("test_audio.mp3")
TRANSCRIPT_FILE = Path("transcript.txt")


def fail(message: str):
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve_stream_url(url: str) -> str:
    lower = url.lower()

    if "youtube.com" in lower or "youtu.be" in lower:
        print("YouTube URL detected; resolving live audio with yt-dlp...")
        result = subprocess.run(
            ["yt-dlp", "--no-playlist", "-f", "bestaudio/best", "-g", url],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
            fail("yt-dlp could not resolve the YouTube live stream.")

        urls = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not urls:
            fail("yt-dlp returned no playable stream URL.")

        return urls[0]

    return url


def capture_audio(media_url: str):
    print(f"Capturing {TEST_SECONDS} seconds of audio...")

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
        fail("FFmpeg could not capture audio from the stream.")

    if not AUDIO_FILE.exists() or AUDIO_FILE.stat().st_size < 1000:
        fail("Audio file was not created or is unexpectedly small.")

    print(f"Audio captured successfully: {AUDIO_FILE.stat().st_size} bytes")


def transcribe_audio():
    print("Uploading audio to Gemini 3.5 Transcribe...")

    client = genai.Client(api_key=GEMINI_API_KEY)
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
                "mode": "SMART",
            }
        },
    )

    transcript = (interaction.output_text or "").strip()

    if not transcript:
        fail("Gemini returned an empty transcription.")

    TRANSCRIPT_FILE.write_text(transcript, encoding="utf-8")

    print("\n========== TRANSCRIPT ==========\n")
    print(transcript)
    print("\n===============================\n")
    print("Transcript saved to transcript.txt")


def main():
    if not STREAM_URL:
        fail("STREAM_URL secret is missing.")

    if not GEMINI_API_KEY:
        fail("GEMINI_API_KEY secret is missing.")

    media_url = resolve_stream_url(STREAM_URL)
    capture_audio(media_url)
    transcribe_audio()


if __name__ == "__main__":
    main()
