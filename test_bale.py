import json
import os
import sys
import urllib.request
import urllib.error

BALE_BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
BALE_CHAT_ID = os.environ.get("BALE_CHAT_ID", "").strip()

def fail(message):
    print("ERROR:", message, file=sys.stderr)
    raise SystemExit(1)

def main():
    if not BALE_BOT_TOKEN:
        fail("BALE_BOT_TOKEN secret is missing.")

    if not BALE_CHAT_ID:
        fail("BALE_CHAT_ID secret is missing.")

    url = f"https://tapi.bale.ai/bot{BALE_BOT_TOKEN}/sendMessage"

    text = (
        "✅ تست اتصال سامانه رصد شبکه ولایت\n\n"
        "ارتباط GitHub Actions با ربات بله با موفقیت برقرار شد.\n\n"
        "📡 Velayat Live Monitor"
    )

    payload = {
        "chat_id": BALE_CHAT_ID,
        "text": text
    }

    body = json.dumps(
        payload,
        ensure_ascii=False
    ).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30
        ) as response:
            response_text = response.read().decode("utf-8")

    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode(
            "utf-8",
            errors="replace"
        )
        print("HTTP ERROR:", exc.code)
        print(error_body)
        raise

    print("Bale response:")
    print(response_text)

    result = json.loads(response_text)

    if result.get("ok") is not True:
        fail(
            "Bale API returned an error: " +
            json.dumps(result, ensure_ascii=False)
        )

    print("SUCCESS: Test message sent to Bale.")

if __name__ == "__main__":
    main()
