from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_state = None


def notify(text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text
            },
            timeout=20
        )
    except Exception as e:
        print("Błąd Telegram:", e, flush=True)


def has_available_place(text):
    matches = re.findall(
        r"\d+\s+(miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
        text.lower()
    )

    return len(matches) > 0


def get_page_text(page):
    try:
        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=30000
        )
    except Exception as e:
        print("Goto warning:", e, flush=True)

    try:
        page.wait_for_timeout(10000)
        return page.inner_text("body").lower()
    except Exception as e:
        print("Błąd odczytu tekstu:", e, flush=True)
        return ""


notify("✅ Reservio monitor uruchomiony na Railway.")

while True:
    try:
        print("Start pętli Playwright...", flush=True)

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu"
                ]
            )

            page = browser.new_page()

            while True:
                try:
                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{now}] Sprawdzam stronę...", flush=True)

                    text = get_page_text(page)

                    current_state = has_available_place(text)

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
                    print("Błąd w sprawdzaniu:", e, flush=True)

                    try:
                        page.close()
                    except:
                        pass

                    page = browser.new_page()

                time.sleep(CHECK_EVERY_SECONDS)

    except Exception as e:
        print("Duży błąd Playwright, restart za 30 sekund:", e, flush=True)
        time.sleep(30)
