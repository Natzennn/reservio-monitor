from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime, date, timedelta

BASE_URL = "https://ttsd.reservio.com/events"

CHECK_EVERY_SECONDS = 180
SCAN_DAYS_AHEAD = 90
PAGE_WAIT_MS = 7000

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

last_found_details = None


POLISH_MONTHS = {
    "sty": 1,
    "stycznia": 1,
    "lut": 2,
    "lutego": 2,
    "mar": 3,
    "marca": 3,
    "kwi": 4,
    "kwietnia": 4,
    "maj": 5,
    "maja": 5,
    "cze": 6,
    "czerwca": 6,
    "lip": 7,
    "lipca": 7,
    "sie": 8,
    "sierpnia": 8,
    "wrz": 9,
    "września": 9,
    "paz": 10,
    "paź": 10,
    "października": 10,
    "lis": 11,
    "listopada": 11,
    "gru": 12,
    "grudnia": 12,
}


def notify(text):
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


def normalize_text(text):
    return (
        text.replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u200b", "")
    )


def parse_polish_event_date(line):
    """
    Obsługuje np.:
    Sobota, cze 13, 2026
    Środa, cze 03, 2026
    """

    pattern = re.compile(
        r"^(?:poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela),\s+"
        r"([a-ząćęłńóśźż]+)\s+(\d{1,2}),\s+(\d{4})$",
        re.IGNORECASE,
    )

    match = pattern.search(line.strip())
    if not match:
        return None

    month_name = match.group(1).lower()
    day_number = int(match.group(2))
    year_number = int(match.group(3))

    month_number = POLISH_MONTHS.get(month_name)
    if not month_number:
        return None

    return date(year_number, month_number, day_number)


def click_upcoming_events_if_needed(page):
    """
    Na tej stronie Reservio parametr ?day= może zostać zignorowany.
    Jeśli pojawia się przycisk 'POKAŻ NADCHODZĄCE WYDARZENIA',
    klikamy go, żeby załadować realną listę wydarzeń.
    """

    possible_buttons = [
        "POKAŻ NADCHODZĄCE WYDARZENIA",
        "Pokaż nadchodzące wydarzenia",
        "NADCHODZĄCE WYDARZENIA",
        "Pokaż więcej",
        "POKAŻ WIĘCEJ",
    ]

    for button_text in possible_buttons:
        try:
            button = page.get_by_text(button_text, exact=False).first()

            if button.count() > 0 and button.is_visible():
                print(f"Klikam przycisk: {button_text}", flush=True)
                button.click(timeout=10000)
                page.wait_for_timeout(PAGE_WAIT_MS)
                return True

        except Exception:
            pass

    return False


def click_load_more_until_done(page, max_clicks=10):
    """
    Jeżeli Reservio pokazuje kolejne wydarzenia po kliknięciu
    'Pokaż więcej' albo podobnego przycisku, klikamy kilka razy.
    """

    for _ in range(max_clicks):
        clicked = False

        for button_text in [
            "POKAŻ WIĘCEJ",
            "Pokaż więcej",
            "WIĘCEJ",
            "Pokaż następne",
            "NASTĘPNE",
        ]:
            try:
                button = page.get_by_text(button_text, exact=False).first()

                if button.count() > 0 and button.is_visible():
                    print(f"Klikam dodatkowy przycisk: {button_text}", flush=True)
                    button.click(timeout=10000)
                    page.wait_for_timeout(PAGE_WAIT_MS)
                    clicked = True
                    break

            except Exception:
                pass

        if not clicked:
            break


def parse_available_events_from_visible_text(full_text):
    """
    Parser pod widok ze screena:

    Sobota, cze 13, 2026
    Pistolet w samoobronie (CCW) [FSO]
    10:00 - 12:00 • 2 wolne miejsca • Dominik
    120 zł
    ZAREZERWUJ
    """

    full_text = normalize_text(full_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    today = date.today()
    max_day = today + timedelta(days=SCAN_DAYS_AHEAD)

    found_events = []
    current_event_date = None
    current_block = []

    def flush_block():
        nonlocal current_block, current_event_date

        if not current_block or not current_event_date:
            current_block = []
            return

        if current_event_date < today or current_event_date > max_day:
            current_block = []
            return

        block_text = " | ".join(current_block)
        block_lower = block_text.lower()

        has_free_places = re.search(
            r"\b\d+\s*(?:wolne miejsce|wolne miejsca|wolnych miejsc)\b",
            block_lower,
            re.IGNORECASE,
        )

        has_reserve_button = "zarezerwuj" in block_lower

        if has_free_places and has_reserve_button and "pełne obłożenie" not in block_lower:
            found_events.append(
                f"{current_event_date.strftime('%Y-%m-%d')} | {block_text}"
            )

        current_block = []

    for line in lines:
        parsed_date = parse_polish_event_date(line)

        if parsed_date:
            flush_block()
            current_event_date = parsed_date
            current_block = [line]
            continue

        if current_event_date:
            current_block.append(line)

            if line.upper() == "ZAREZERWUJ":
                flush_block()
                current_block = [f"Data: {current_event_date.strftime('%Y-%m-%d')}"]

    flush_block()

    unique_events = []
    seen = set()

    for event in found_events:
        normalized = event.lower()

        if normalized not in seen:
            seen.add(normalized)
            unique_events.append(event)

    return unique_events


def scan_calendar_once():
    all_found_events = []

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

        try:
            print(f"Otwieram stronę: {BASE_URL}", flush=True)

            page.goto(
                BASE_URL,
                wait_until="commit",
                timeout=60000,
            )

            page.wait_for_timeout(PAGE_WAIT_MS)

            click_upcoming_events_if_needed(page)
            click_load_more_until_done(page)

            full_text = page.locator("body").inner_text(timeout=20000)
            full_text = normalize_text(full_text)

            print("========== DEBUG TEKST STRONY ==========", flush=True)
            print(full_text[:5000], flush=True)
            print("========== KONIEC DEBUG ==========", flush=True)

            events = parse_available_events_from_visible_text(full_text)

            if events:
                for event in events:
                    print(f"Znaleziono: {event}", flush=True)
                    all_found_events.append(event)
            else:
                print("Nie znaleziono wolnych miejsc w widocznym tekście.", flush=True)

        finally:
            browser.close()

    return all_found_events


def main():
    global last_found_details

    notify("✅ Reservio monitor uruchomiony.")

    while True:
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{now}] Start skanowania wydarzeń 3 miesiące do przodu...", flush=True)

            events = scan_calendar_once()

            if events:
                current_details = "\n".join(events)

                print("Dostępne: True", flush=True)
                print(current_details, flush=True)

                if current_details != last_found_details:
                    message = (
                        "🚨 Reservio: wykryto wolne miejsce!\n\n"
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

            print("Zakończono skanowanie.", flush=True)

        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
