from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

last_found_details = None


def notify(text):
    """Wysyła powiadomienie na Telegram."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Brak TELEGRAM_TOKEN albo CHAT_ID w zmiennych środowiskowych.", flush=True)
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": text,
            },
            timeout=20,
        )

        if not response.ok:
            print(f"Błąd Telegram HTTP {response.status_code}: {response.text}", flush=True)

    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def test_notification():
    """Tymczasowy test wysyłania alertu Telegram."""
    notify(
        "🚨 TEST Reservio: wykryto dostępne miejsce!\n\n"
        "Przykładowe szkolenie | 10 czerwca 2026 | 12:00 | 1 miejsce dostępne\n\n"
        f"{URL}"
    )


def get_page_text():
    """Pobiera tekst strony po wyrenderowaniu JS przez Playwright."""
    last_error = None

    for attempt in range(3):
        browser = None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox"],
                )

                page = browser.new_page()

                page.goto(
                    URL,
                    wait_until="commit",
                    timeout=60000,
                )

                page.wait_for_timeout(8000)

                text = page.locator("body").inner_text(timeout=20000)

                browser.close()
                return text

        except Exception as e:
            last_error = e
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)

            try:
                if browser:
                    browser.close()
            except Exception:
                pass

            time.sleep(5)

    raise Exception(f"Nie udało się załadować strony po 3 próbach: {last_error}")


def parse_available_events(full_text):
    """
    Wykrywa dostępne miejsca i zwraca sensowny opis wydarzeń.
    Szuka fraz typu:
    - 1 miejsce dostępne
    - 2 miejsca dostępne
    - 5 miejsc dostępnych
    """
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    found_events = []

    availability_regex = re.compile(
        r"\b\d+\s+(?:miejsce dostępne|miejsca dostępne|miejsc dostępnych)\b",
        re.IGNORECASE,
    )

    for idx, line in enumerate(lines):
        if availability_regex.search(line):
            start = max(0, idx - 4)
            end = min(len(lines), idx + 2)

            context = lines[start:end]
            event_details = " | ".join(context)

            found_events.append(event_details)

    # Usuwamy duplikaty, zachowując kolejność
    unique_events = []
    seen = set()

    for event in found_events:
        normalized = event.lower()
        if normalized not in seen:
            seen.add(normalized)
            unique_events.append(event)

    return unique_events


def main():
    global last_found_details

    notify("✅ Reservio monitor uruchomiony.")
    # Tymczasowy test powiadomienia
    test_notification()

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] Sprawdzam stronę...", flush=True)

            text = get_page_text()
            events = parse_available_events(text)

            if events:
                current_details = "\n".join(events)
                print("Dostępne: True", flush=True)
                print(current_details, flush=True)

                if current_details != last_found_details:
                    message = (
                        "🚨 Reservio: wykryto dostępne miejsce!\n\n"
                        f"{current_details}\n\n"
                        f"{URL}"
                    )
                    notify(message)
                    last_found_details = current_details
                else:
                    print("Te same miejsca już były zgłoszone — nie wysyłam ponownie.", flush=True)

            else:
                print("Dostępne: False", flush=True)
                last_found_details = None

            print("Sprawdzono Reservio.", flush=True)

        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
