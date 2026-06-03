from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime, date, timedelta

BASE_URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 180
SCAN_DAYS_AHEAD = 90
PAGE_WAIT_MS = 5000

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
last_found_details = None

def notify(text):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Brak TELEGRAM_TOKEN albo CHAT_ID.", flush=True)
        return
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20,
        )
        if not response.ok:
            print(f"Błąd Telegram HTTP {response.status_code}: {response.text}", flush=True)
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)

def normalize_text(text):
    return text.replace("\xa0"," ").replace("\u202f"," ").replace("\u200b","")

def parse_available_events(full_text, checked_day):
    full_text = normalize_text(full_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    found_events = []

    availability_regex = re.compile(
        r"\b\d+\s*(?:wolne miejsce|wolne miejsca|wolnych miejsc)\b", re.IGNORECASE
    )

    current_block = []
    current_date = checked_day

    for line in lines:
        if availability_regex.search(line) or "ZAREZERWUJ" in line:
            current_block.append(line)
        elif current_block:
            block_text = " | ".join(current_block)
            found_events.append(f"{current_date.strftime('%Y-%m-%d')} | {block_text}")
            current_block = []

    if current_block:
        block_text = " | ".join(current_block)
        found_events.append(f"{current_date.strftime('%Y-%m-%d')} | {block_text}")

    return found_events

def scan_calendar_once():
    all_found_events = []
    today = date.today()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width":1400,"height":1200})

        page.goto(BASE_URL, wait_until="commit", timeout=60000)
        page.wait_for_timeout(PAGE_WAIT_MS)
        full_text = page.locator("body").inner_text(timeout=20000)
        full_text = normalize_text(full_text)

        for offset in range(SCAN_DAYS_AHEAD + 1):
            checked_day = today + timedelta(days=offset)
            events = parse_available_events(full_text, checked_day)
            if events:
                for event in events:
                    all_found_events.append(event)

        browser.close()
    return all_found_events

def main():
    global last_found_details
    notify("✅ Reservio monitor uruchomiony.")

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] Start skanowania 3 miesięcy do przodu...", flush=True)

            events = scan_calendar_once()

            if events:
                current_details = "\n".join(events)
                print("Dostępne: True", flush=True)
                print(current_details, flush=True)
                if current_details != last_found_details:
                    notify(f"🚨 Reservio: wykryto wolne miejsce!\n\n{current_details}\n\n{BASE_URL}")
                    last_found_details = current_details
                else:
                    print("Te same miejsca już były zgłoszone — nie wysyłam ponownie.", flush=True)
            else:
                print("Dostępne: False", flush=True)
                last_found_details = None

            print("Zakończono skanowanie.", flush=True)
        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)

if __name__ == "__main__":
    main()
