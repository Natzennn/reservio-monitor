from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime, date, timedelta

URL = "https://ttsd.reservio.com/events"

CHECK_EVERY_SECONDS = 180
WEEKS_TO_SCAN = 14
WAIT_MS = 5000

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_alert = None


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
    "paź": 10,
    "paz": 10,
    "października": 10,
    "lis": 11,
    "listopada": 11,
    "gru": 12,
    "grudnia": 12,
}


def notify(text):
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


def parse_polish_date(line):
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


def has_free_places(text):
    text = normalize_text(text).lower()

    return bool(
        re.search(
            r"\b\d+\s*(?:wolne miejsce|wolne miejsca|wolnych miejsc)\b",
            text,
            re.IGNORECASE,
        )
    )


def click_show_upcoming(page):
    """
    Klika 'POKAŻ NADCHODZĄCE WYDARZENIA'.
    Używa współrzędnych, podobnie jak Twój działający monitor Veloart.
    """

    print("Szukam przycisku: POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)

    try:
        button = page.get_by_text("POKAŻ NADCHODZĄCE WYDARZENIA", exact=False).first()

        if button.count() > 0 and button.is_visible():
            box = button.bounding_box(timeout=10000)

            if box:
                page.mouse.click(
                    box["x"] + box["width"] / 2,
                    box["y"] + box["height"] / 2,
                )

                print("Kliknięto: POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)
                page.wait_for_timeout(WAIT_MS)
                return True

    except Exception as e:
        print(f"Nie udało się kliknąć POKAŻ NADCHODZĄCE WYDARZENIA: {e}", flush=True)

    print("Nie znaleziono przycisku POKAŻ NADCHODZĄCE WYDARZENIA.", flush=True)
    return False


def click_next_week(page):
    """
    Klika prawą strzałkę w .calendar-nav.
    To jest podejście podobne do Twojego click_previous_month z Veloart.
    """

    try:
        nav = page.locator(".calendar-nav").bounding_box(timeout=10000)

        if not nav:
            raise Exception("Nie znaleziono .calendar-nav")

        page.mouse.click(
            nav["x"] + nav["width"] - 25,
            nav["y"] + nav["height"] / 2,
        )

        print("Kliknięto następny tydzień.", flush=True)
        page.wait_for_timeout(WAIT_MS)
        return True

    except Exception as e:
        print(f"Nie udało się kliknąć następnego tygodnia przez .calendar-nav: {e}", flush=True)

    # Fallback na typowe przyciski
    selectors = [
        'button[aria-label*="Next"]',
        'button[aria-label*="Następ"]',
        'a[aria-label*="Next"]',
        'a[aria-label*="Następ"]',
        'button:has-text(">")',
        'a:has-text(">")',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first()

            if locator.count() > 0 and locator.is_visible():
                locator.click(timeout=10000, force=True)
                print(f"Kliknięto następny tydzień przez selector: {selector}", flush=True)
                page.wait_for_timeout(WAIT_MS)
                return True

        except Exception:
            pass

    print("Nie udało się kliknąć następnego tygodnia.", flush=True)
    return False


def parse_visible_events(full_text):
    """
    Parser pod widok TTSD:

    Sobota, cze 13, 2026
    Pistolet w samoobronie (CCW) [FSO]
    10:00 - 12:00 • 2 wolne miejsca • Dominik
    120 zł
    ZAREZERWUJ
    """

    full_text = normalize_text(full_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    today = date.today()
    max_date = today + timedelta(days=90)

    found_events = []

    current_date = None
    current_block = []

    def flush_block():
        nonlocal current_block, current_date

        if not current_date or not current_block:
            current_block = []
            return

        if current_date < today or current_date > max_date:
            current_block = []
            return

        block_text = " | ".join(current_block)
        block_lower = block_text.lower()

        if (
            has_free_places(block_text)
            and "zarezerwuj" in block_lower
            and "pełne obłożenie" not in block_lower
        ):
            found_events.append(
                f"{current_date.strftime('%Y-%m-%d')} | {block_text}"
            )

        current_block = []

    for line in lines:
        parsed_date = parse_polish_date(line)

        if parsed_date:
            flush_block()
            current_date = parsed_date
            current_block = [line]
            continue

        if current_date:
            current_block.append(line)

            if line.upper() == "ZAREZERWUJ":
                flush_block()

    flush_block()

    unique = []
    seen = set()

    for event in found_events:
        key = event.lower()

        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique


def scan_ttsd():
    found = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 1200,
            },
            user_agent="Mozilla/5.0",
        )

        print(f"Otwieram stronę: {URL}", flush=True)

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000,
        )

        page.wait_for_timeout(8000)

        body_text = normalize_text(page.locator("body").inner_text(timeout=20000))

        print("========== TEKST STARTOWY ==========", flush=True)
        print(body_text[:2500], flush=True)
        print("========== KONIEC TEKSTU STARTOWEGO ==========", flush=True)

        if "POKAŻ NADCHODZĄCE WYDARZENIA" in body_text:
            click_show_upcoming(page)

        for week_index in range(WEEKS_TO_SCAN):
            print(f"Skanuję tydzień {week_index + 1}/{WEEKS_TO_SCAN}", flush=True)

            page.wait_for_timeout(3000)

            text = normalize_text(page.locator("body").inner_text(timeout=20000))

            print("========== FRAGMENT TEKSTU TYGODNIA ==========", flush=True)
            print(text[:3000], flush=True)
            print("========== KONIEC FRAGMENTU ==========", flush=True)

            events = parse_visible_events(text)

            if events:
                for event in events:
                    print(f"Znaleziono: {event}", flush=True)
                    found.append(event)
            else:
                print("Brak wolnych miejsc w tym tygodniu.", flush=True)

            if week_index < WEEKS_TO_SCAN - 1:
                clicked = click_next_week(page)

                if not clicked:
                    print("Nie mogę przejść dalej. Kończę skanowanie.", flush=True)
                    break

        browser.close()

    unique = []
    seen = set()

    for event in found:
        key = event.lower()

        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique


notify("✅ TTSD monitor uruchomiony. Skanuję 3 miesiące do przodu.")
print("Start TTSD monitora.", flush=True)

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Sprawdzam TTSD...", flush=True)

        events = scan_ttsd()

        if events:
            current_alert = "\n\n".join(events)

            print("Dostępne: True", flush=True)
            print(current_alert, flush=True)

            if current_alert != last_alert:
                notify(
                    "🚨 TTSD: wykryto wolne miejsca!\n\n"
                    f"{current_alert}\n\n"
                    f"{URL}"
                )

                last_alert = current_alert
            else:
                print("Te same miejsca już były zgłoszone — nie wysyłam ponownie.", flush=True)

        else:
            print("Dostępne: False", flush=True)
            last_alert = None

        print("Sprawdzono TTSD.", flush=True)

    except Exception as e:
        print(f"Błąd TTSD: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
