from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime, date, timedelta

BASE_URL = "https://test1874.reservio.com/events"

CHECK_EVERY_SECONDS = 180  # co ile sekund robić pełne skanowanie
SCAN_DAYS_AHEAD = 90       # ile dni do przodu sprawdzać
PAGE_WAIT_MS = 5000

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
    """Test Telegrama po starcie."""
    notify(
        "🚨 TEST Reservio: mechanizm powiadomień działa.\n\n"
        "To jest tylko test, nie prawdziwe wolne miejsce.\n\n"
        f"{BASE_URL}"
    )


def build_day_url(day):
    return f"{BASE_URL}?day={day.strftime('%Y-%m-%d')}"


def parse_available_events(full_text, checked_day):
    """
    Szuka wolnych miejsc w tekście strony.

    Wykrywa między innymi:
    - 1 miejsce dostępne
    - 2 miejsca dostępne
    - 5 miejsc dostępnych
    - 1 wolne miejsce
    - 2 wolne miejsca
    - dostępne miejsca

    Ignoruje:
    - Pełne obłożenie
    - W tym dniu nie ma żadnych wydarzeń
    """

    lines = [line.strip() for line in full_text.splitlines() if line.strip()]
    found_events = []

    availability_regex = re.compile(
        r"("
        r"\b\d+\s+(?:miejsce dostępne|miejsca dostępne|miejsc dostępnych)\b"
        r"|"
        r"\b\d+\s+(?:wolne miejsce|wolne miejsca|wolnych miejsc)\b"
        r"|"
        r"\bdostępne miejsca\b"
        r"|"
        r"\bwolne miejsca\b"
        r")",
        re.IGNORECASE,
    )

    full_text_lower = full_text.lower()

    if "pełne obłożenie" in full_text_lower and not availability_regex.search(full_text):
        return []

    for idx, line in enumerate(lines):
        if availability_regex.search(line):
            start = max(0, idx - 6)
            end = min(len(lines), idx + 4)

            context = lines[start:end]
            event_details = " | ".join(context)

            found_events.append(
                f"{checked_day.strftime('%Y-%m-%d')} | {event_details}"
            )

    unique_events = []
    seen = set()

    for event in found_events:
        normalized = event.lower()

        if normalized not in seen:
            seen.add(normalized)
            unique_events.append(event)

    return unique_events


def scan_calendar_once():
    """
    Skanuje cały kalendarz przez URL ?day=YYYY-MM-DD.
    Nie klika przycisków w kalendarzu.
    """

    all_found_events = []
    today = date.today()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        page = browser.new_page()

        for offset in range(SCAN_DAYS_AHEAD + 1):
            checked_day = today + timedelta(days=offset)
            url = build_day_url(checked_day)

            try:
                print(f"Sprawdzam dzień: {checked_day.strftime('%Y-%m-%d')}", flush=True)

                page.goto(
                    url,
                    wait_until="commit",
                    timeout=60000,
                )

                page.wait_for_timeout(PAGE_WAIT_MS)

                full_text = page.locator("body").inner_text(timeout=20000)

                events = parse_available_events(full_text, checked_day)

                if events:
                    print(f"Znaleziono wolne miejsca dla {checked_day.strftime('%Y-%m-%d')}", flush=True)

                    for event in events:
                        all_found_events.append(event)
                else:
                    print(f"Brak miejsc dla {checked_day.strftime('%Y-%m-%d')}", flush=True)

            except Exception as e:
                print(f"Błąd przy dniu {checked_day.strftime('%Y-%m-%d')}: {e}", flush=True)

        browser.close()

    return all_found_events


def main():
    global last_found_details

    notify("✅ Reservio monitor uruchomiony.")
    test_notification()

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] Start pełnego skanowania kalendarza...", flush=True)

            events = scan_calendar_once()

            if events:
                current_details = "\n".join(events)

                print("Dostępne: True", flush=True)
                print(current_details, flush=True)

                if current_details != last_found_details:
                    message = (
                        "🚨 Reservio: wykryto dostępne miejsce!\n\n"
                        f"{current_details}\n\n"
                        f"{BASE_URL}"
                    )

                    notify(message)
                    last_found_details = current_details

                else:
                    print("Te same miejsca już były zgłoszone — nie wysyłam ponownie.", flush=True)

            else:
                print("Dostępne: False", flush=True)
                last_found_details = None

            print("Zakończono pełne skanowanie kalendarza.", flush=True)

        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
