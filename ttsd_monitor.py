import requests
import os
import time

URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )

response = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)

text = response.text[:3000]

notify("TEST TTSD - bot widzi taki kod strony:\n\n" + text[:3500])

while True:
    print("Test zakończony.")
    time.sleep(CHECK_EVERY_SECONDS)
