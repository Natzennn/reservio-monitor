import requests
import hashlib
import os
import time

URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text
        },
        timeout=20
    )

def get_hash():
    response = requests.get(
        URL,
        timeout=20,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    html = response.text

    important = []

    for line in html.splitlines():
        line_lower = line.lower()

        if "dostępn" in line_lower:
            important.append(line.strip())

    content = "\n".join(important)

    return hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

old_hash = None

notify("✅ Monitor TTSD uruchomiony.")

while True:
    try:
        current_hash = get_hash()

        if old_hash and old_hash != current_hash:
            notify(
                "🚨 Wykryto wolne miejsce na TTSD!\n"
                + URL
            )

        old_hash = current_hash

        print("Sprawdzono TTSD.")

    except Exception as e:
        print("Błąd:", e)

    time.sleep(CHECK_EVERY_SECONDS)
