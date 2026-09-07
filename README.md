# Velayat Live Monitor — Test Stage

This package performs a 60-second test:

1. GitHub Actions starts an Ubuntu runner.
2. FFmpeg captures 60 seconds from the live stream.
3. Gemini 3.5 Transcribe converts the Persian audio to text.
4. transcript.txt and the temporary test audio are uploaded as an Actions artifact.

Required repository secrets:
- GEMINI_API_KEY
- STREAM_URL

This is only the test stage.
