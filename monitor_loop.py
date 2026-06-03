from playwright.sync_api import sync_playwright
import requests
import os
import time
from datetime import datetime, timedelta

BASE_URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 180
SCAN_DAYS_AHEAD = 90

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
last_found = None

def notify(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Brak TELEGRAM_TOKEN albo CHAT_ID")
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    except Exception as e:
        print(f"Błąd Telegram: {e}")

def scan_events():
    events_found = []
    today = datetime.today().date()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1400, "height":1200})
        page.goto(BASE_URL, wait_until="commit", timeout=60000)
        page.wait_for_timeout(5000)  # poczekaj aż JS wyrenderuje

        # pobieramy wszystkie li w widoku listy wydarzeń
        event_items = page.locator("li").all()
        for item in event_items:
            text = item.inner_text().lower()
            if "wolne miejsca" in text and "zarezerwuj" in text:
                # wyciągnij datę z bloku
                date_line = next((line for line in text.split("\n") if any(month in line for month in ["sty","lut","mar","kwi","maj","cze","lip","sie","wrz","paz","lis","gru"])), "")
                events_found.append(f"{date_line} | {text}")

        browser.close()
    return events_found

def main():
    global last_found
    notify("✅ Reservio monitor uruchomiony")

    while True:
        try:
            print(f"[{datetime.now()}] Sprawdzam wydarzenia...")
            events = scan_events()
            if events:
                current = "\n".join(events)
                if current != last_found:
                    notify(f"🚨 Wykryto wolne miejsca:\n{current}\n{BASE_URL}")
                    last_found = current
                print("Znalezione wydarzenia:\n", current)
            else:
                print("Brak wolnych miejsc.")
                last_found = None
        except Exception as e:
            print(f"Błąd głównej pętli: {e}")
        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
