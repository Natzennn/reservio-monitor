import requests
import os
import time

URL = "https://ttsd.reservio.com/events"

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

response = requests.get(
    URL,
    headers={
        "User-Agent": "Mozilla/5.0"
    },
    timeout=20
)

text = response.text[:3500]

notify(
    "TTSD TEST:\n\n"
    + text
)

while True:
    print("Test działa.")
    time.sleep(60)
