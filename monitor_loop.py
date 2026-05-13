from playwright.sync_api import sync_playwright
import requests
import os
import time
import re

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

        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        page = browser.new_page()

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(5000)

        text = page.inner_text("body")

        browser.close()

        return text.lower()


notify("✅ Reservio Playwright monitor uruchomiony.")


while True:
    try:
        print("Sprawdzam stronę...", flush=True)

        text = get_page_text()

        available_matches = re.findall(
            r"\d+\s+(miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
            text
        )

        current_state = len(available_matches) > 0

        print("Dostępne:", current_state, flush=True)

        if current_state != last_state:

            if current_state:
                notify(
                    "🚨 Reservio: wykryto dostępne miejsce!\n"
                    + URL
                )

            last_state = current_state

        print("Sprawdzono Reservio.", flush=True)

    except Exception as e:
        print("Błąd:", e, flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
