from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

URL = "https://ttsd.reservio.com/events"

CHECK_EVERY_SECONDS = 180
WAIT_MS = 5000

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_alert = None


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
        .strip()
    )


def has_available_places(text):
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


def is_time_line(text):
    return bool(
        re.search(
            r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b",
            text,
        )
    )


def is_available_line(text):
    return has_available_places(text)


def is_noise_line(text):
    lower = normalize_text(text).lower()

    noise_phrases = [
        "tanie treningi strzelectwa dynamicznego",
        "zaloguj się",
        "strona główna",
        "wydarzenia",
        "obsługiwane przez",
        "copyright",
        "wszelkie prawa zastrzeżone",
        "masz własny biznes",
        "wypróbuj reservio",
        "kalendarz wydarzeń",
        "przejrzyj wydarzenia",
        "szczegóły",
        "pełne obłożenie",
        "brak wydarzeń",
        "pokaż nadchodzące wydarzenia",
    ]

    if lower in ["/", ""]:
        return True

    return any(phrase in lower for phrase in noise_phrases)


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

                try:
                    locator.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                locator.click(timeout=10000, force=True)

                print("Kliknięto: POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)
                page.wait_for_timeout(WAIT_MS)
                return True

        except Exception as e:
            print(f"Nie udało się kliknąć przez selector {selector}: {e}", flush=True)

    print("Nie znaleziono przycisku POKAŻ NADCHODZĄCE WYDARZENIA.", flush=True)
    return False


def clean_event_text(raw_lines):
    clean_lines = []

    for line in raw_lines:
        line = normalize_text(line)

        if not line:
            continue

        if is_noise_line(line):
            continue

        clean_lines.append(line)

    return clean_lines


def parse_events_from_text(full_text):
    """
    Parser pod TTSD.

    Z tekstu typu:
    Szczegóły
    10:00 - 12:00
    Pistolet w samoobronie (CCW) [FSO]
    2 miejsc dostępnych

    robi:
    10:00 - 12:00 | Pistolet w samoobronie (CCW) [FSO] | 2 miejsc dostępnych
    """

    full_text = normalize_text(full_text)
    lines = [normalize_text(line) for line in full_text.splitlines() if normalize_text(line)]

    found = []

    for idx, line in enumerate(lines):
        if not is_available_line(line):
            continue

        availability = line

        time_line = None
        title_line = None

        # Szukamy godziny najbliżej przed linią z dostępnością
        for j in range(idx - 1, max(-1, idx - 8), -1):
            candidate = lines[j]

            if is_time_line(candidate):
                time_line = candidate
                break

        # Szukamy tytułu między godziną a dostępnością
        if time_line:
            time_index = lines.index(time_line)

            for j in range(time_index + 1, idx):
                candidate = lines[j]

                if is_noise_line(candidate):
                    continue

                if is_time_line(candidate):
                    continue

                if is_available_line(candidate):
                    continue

                title_line = candidate
                break

        # Fallback, gdyby nie udało się znaleźć tytułu po godzinie
        if not title_line:
            for j in range(idx - 1, max(-1, idx - 8), -1):
                candidate = lines[j]

                if is_noise_line(candidate):
                    continue

                if is_time_line(candidate):
                    continue

                if is_available_line(candidate):
                    continue

                title_line = candidate
                break

        if not time_line:
            time_line = "Godzina nieznana"

        if not title_line:
            title_line = "Wydarzenie nieznane"

        event_text = f"{time_line} | {title_line} | {availability}"
        found.append(event_text)

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
        print(body_text[:2000], flush=True)
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
            current_alert = "\n".join(f"• {event}" for event in events)

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
