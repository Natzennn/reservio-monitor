from playwright.sync_api import sync_playwright
import requests
import os
import time

URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_state = None

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text
        },
        timeout=20
    )

def get_page_text():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        page = browser.new_page()

        page.goto(
            URL,
            wait_until="networkidle",
            timeout=60000
        )

        text = page.inner_text("body")

        browser.close()

        return text.lower()

notify("✅ Reservio Playwright monitor uruchomiony.")

while True:
    try:
        text = get_page_text()

        current_state = "brak dostępnych miejsc" not in text

        if current_state != last_state:
            if current_state:
                notify(
                    "🚨 Reservio: wykryto dostępne miejsce!\n"
                    + URL
                )
            else:
                notify(
                    "❌ Reservio: brak dostępnych miejsc.\n"
                    + URL
                )

            last_state = current_state

        print("Sprawdzono Reservio.")

    except Exception as e:
        print("Błąd:", e)

    time.sleep(CHECK_EVERY_SECONDS)
