from playwright.sync_api import sync_playwright
import requests
import os
import time
from datetime import datetime

BASE_URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 180

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

last_found = None


def notify(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Brak TELEGRAM_TOKEN albo CHAT_ID", flush=True)
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg,
            },
            timeout=20,
        )

        if not response.ok:
            print(f"Błąd Telegram HTTP {response.status_code}: {response.text}", flush=True)

    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def scan_events():
    events_found = []

    print("Uruchamiam Playwright...", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 1200,
            }
        )

        print(f"Otwieram stronę: {BASE_URL}", flush=True)

        page.goto(
            BASE_URL,
            wait_until="commit",
            timeout=60000,
        )

        print("Strona otwarta, czekam na JS...", flush=True)

        page.wait_for_timeout(8000)

        body_text = page.locator("body").inner_text(timeout=20000)
        body_text = body_text.replace("\xa0", " ")

        print("========== DEBUG POCZĄTEK TEKSTU ==========", flush=True)
        print(body_text[:3000], flush=True)
        print("========== DEBUG KONIEC TEKSTU ==========", flush=True)

        if "wolne miejsce" in body_text.lower() or "wolne miejsca" in body_text.lower():
            print("W tekście strony wykryto frazę: wolne miejsce / wolne miejsca", flush=True)
        else:
            print("W tekście strony NIE wykryto frazy wolne miejsce / wolne miejsca", flush=True)

        event_items = page.locator("li")
        count = event_items.count()

        print(f"Liczba elementów li: {count}", flush=True)

        for i in range(count):
            try:
                text = event_items.nth(i).inner_text(timeout=5000)
                text = text.replace("\xa0", " ")
                text_lower = text.lower()

                if (
                    ("wolne miejsce" in text_lower or "wolne miejsca" in text_lower)
                    and "zarezerwuj" in text_lower
                    and "pełne obłożenie" not in text_lower
                ):
                    clean_text = " | ".join(
                        line.strip()
                        for line in text.splitlines()
                        if line.strip()
                    )

                    events_found.append(clean_text)

            except Exception:
                pass

        browser.close()

    return events_found


def main():
    global last_found

    print("Bot startuje...", flush=True)
    notify("✅ Reservio monitor uruchomiony.")

    while True:
        try:
            print(f"[{datetime.now()}] Sprawdzam wydarzenia...", flush=True)

            events = scan_events()

            if events:
                current = "\n\n".join(events)

                print("Dostępne: True", flush=True)
                print(current, flush=True)

                if current != last_found:
                    notify(
                        "🚨 Reservio: wykryto wolne miejsca!\n\n"
                        f"{current}\n\n"
                        f"{BASE_URL}"
                    )

                    last_found = current
                else:
                    print("Te same miejsca już były zgłoszone — nie wysyłam ponownie.", flush=True)

            else:
                print("Dostępne: False", flush=True)
                last_found = None

            print("Zakończono skanowanie.", flush=True)

        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
