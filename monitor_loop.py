from playwright.sync_api import sync_playwright
import requests
import os
import time
from datetime import datetime

BASE_URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 180
SCAN_DAYS_AHEAD = 90
PAGE_WAIT_MS = 6000

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

last_found = None

def notify(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Brak TELEGRAM_TOKEN albo CHAT_ID", flush=True)
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=20
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)

def scan_events():
    events_found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1400,"height":1200})
        page.goto(BASE_URL, wait_until="commit", timeout=60000)
        page.wait_for_timeout(PAGE_WAIT_MS)

        # kliknij "POKAŻ NADCHODZĄCE WYDARZENIA", jeśli jest
        try:
            show_upcoming = page.get_by_text("POKAŻ NADCHODZĄCE WYDARZENIA", exact=False).first()
            if show_upcoming.count() > 0 and show_upcoming.is_visible():
                show_upcoming.click(timeout=10000)
                page.wait_for_timeout(PAGE_WAIT_MS)
        except Exception:
            pass

        # pobierz wszystkie li elementy wydarzeń
        event_items = page.locator("li")
        count = event_items.count()
        for i in range(count):
            try:
                text = event_items.nth(i).inner_text(timeout=5000)
                text_lower = text.lower()
                if "wolne miejsce" in text_lower and "zarezerwuj" in text_lower:
                    clean_text = " | ".join(line.strip() for line in text.splitlines() if line.strip())
                    events_found.append(clean_text)
            except Exception:
                pass

        browser.close()
    return events_found

def main():
    global last_found
    notify("✅ Reservio monitor uruchomiony")

    while True:
        try:
            print(f"[{datetime.now()}] Start skanowania...", flush=True)
            events = scan_events()

            if events:
                current = "\n".join(events)
                print("Dostępne: True", flush=True)
                print(current, flush=True)
                if current != last_found:
                    notify(f"🚨 Wykryto wolne miejsca:\n\n{current}\n\n{BASE_URL}")
                    last_found = current
            else:
                print("Dostępne: False", flush=True)
                last_found = None

            print("Zakończono skanowanie.", flush=True)
        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
