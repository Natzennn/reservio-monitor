import requests
import os
import time

URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_message = None

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )

def check_available():
    response = requests.get(
        URL,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    html = response.text.lower()

    if "dostępn" in html:
        return True

    return False

notify("✅ Monitor TTSD uruchomiony.")

while True:
    try:
        available = check_available()

        if available:
            message = "🚨 TTSD: wykryto dostępne miejsce!\n" + URL

            if message != last_message:
                notify(message)
                last_message = message

        else:
            last_message = None

        print("Sprawdzono TTSD.")

    except Exception as e:
        print("Błąd:", e)

    time.sleep(CHECK_EVERY_SECONDS)
