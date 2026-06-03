from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime, date, timedelta

URL = "https://ttsd.reservio.com/events"

CHECK_EVERY_SECONDS = 180
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


def has_free_places(text):
    text = normalize_text(text).lower()

    return bool(
        re.search(
            r"\b\d+\s*(?:"
            r"wolne miejsce|wolne miejsca|wolnych miejsc|"
            r"miejsce dostępne|miejsca dostępne|miejsc dostępnych"
            r")\b",
            text,
            re.IGNORECASE,
        )
    )


def click_show_upcoming(page):
    print("Szukam przycisku: POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)

    selectors = [
        'button:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'a:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'text="POKAŻ NADCHODZĄCE WYDARZENIA"',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first

            if locator.count() > 0 and locator.is_visible():
                print(f"Znaleziono przycisk przez selector: {selector}", flush=True)
                locator.scroll_into_view_if_needed(timeout=5000)
                locator.click(timeout=10000, force=True)

                print("Kliknięto: POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)
                page.wait_for_timeout(WAIT_MS)
                return True

        except Exception as e:
            print(f"Nie udało się kliknąć przez selector {selector}: {e}", flush=True)

    print("Nie znaleziono przycisku POKAŻ NADCHODZĄCE WYDARZENIA.", flush=True)
    return False


def parse_events_from_text(full_text):
    """
    Parser dopasowany do TTSD po kliknięciu:
    widzi np.
    10:00 - 12:00
    Pistolet w samoobronie (CCW) [FSO]
    2 miejsc dostępnych
    """

    full_text = normalize_text(full_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    found = []

    for idx, line in enumerate(lines):
        if has_free_places(line):
            start = max(0, idx - 8)
            end = min(len(lines), idx + 8)

            block = lines[start:end]
            block_text = " | ".join(block)
            block_lower = block_text.lower()

            if "pełne obłożenie" in block_lower:
                # czasami "pełne obłożenie" dotyczy poprzedniego eventu,
                # więc nie odrzucamy od razu całego wyniku;
                # bierzemy mniejszy kontekst wokół dostępności
                start = max(0, idx - 4)
                end = min(len(lines), idx + 4)
                block = lines[start:end]
                block_text = " | ".join(block)
                block_lower = block_text.lower()

            found.append(block_text)

    unique = []
    seen = set()

    for item in found:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)

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

        page.wait_for_timeout(3000)

        text = normalize_text(page.locator("body").inner_text(timeout=20000))

        print("========== TEKST PO KLIKNIĘCIU ==========", flush=True)
        print(text[:5000], flush=True)
        print("========== KONIEC TEKSTU PO KLIKNIĘCIU ==========", flush=True)

        events = parse_events_from_text(text)

        if events:
            for event in events:
                print(f"Znaleziono: {event}", flush=True)
                found.append(event)
        else:
            print("Brak wolnych miejsc.", flush=True)

        browser.close()

    return found


notify("✅ TTSD monitor uruchomiony.")
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
