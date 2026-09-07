# Test All Velayat Connections

This diagnostic workflow tests all current production connections in about 1-3 minutes:

1. GitHub Secrets
2. Google Apps Script Web App GET
3. Live stream resolution with yt-dlp
4. FFmpeg audio capture (60 seconds)
5. Gemini 3.5 Transcribe
6. Gemini 3.7 Flash analysis
7. Google Sheet POST
8. Bale bot sendMessage
9. Google Sheet BOT_STATUS update

Upload:
- `test_all_connections.py` to repository root.
- `.github/workflows/test-all-connections.yml` to the workflow directory.

Run:
Actions -> Test All Velayat Connections -> Run workflow

Success marker:
`ALL CONNECTIONS OK`
