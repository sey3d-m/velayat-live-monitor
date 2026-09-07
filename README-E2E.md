# Velayat Live Monitor — End-to-End Test

This stage tests the complete path:
Live stream -> FFmpeg -> Gemini 3.5 Transcribe -> Gemini Flash analysis -> Google Apps Script Web App -> Google Sheet.

Upload these files to repository root:
- e2e_test.py
- requirements.txt

Upload workflow to:
- .github/workflows/test-e2e.yml

Then run **Test Full Velayat Pipeline** from GitHub Actions.
