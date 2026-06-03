from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

BASE_URL = "https://ttsd.reservio.com/events"
CHECK_EVERY_SECONDS = 180
PAGE_WAIT_MS = 7000

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
            r"\b\d+\s*(?:wolne miejsce|wolne miejsca|wolnych miejsc)\b",
            text,
            re.IGNORECASE,
        )
    )


def click_show_upcoming(page):
    """
    Klika 'POKAŻ NADCHODZĄCE WYDARZENIA' możliwie najpewniej.
    """

    print("Szukam przycisku POKAŻ NADCHODZĄCE WYDARZENIA...", flush=True)

    selectors = [
        'text="POKAŻ NADCHODZĄCE WYDARZENIA"',
        'button:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'a:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'div:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'span:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first()

            if locator.count() > 0:
                print(f"Znaleziono selector: {selector}", flush=True)

                try:
                    locator.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                locator.click(timeout=10000, force=True)

                print("Kliknięto POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)

                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass

                page.wait_for_timeout(PAGE_WAIT_MS)
                return True

        except Exception as e:
            print(f"Nie udało się kliknąć przez selector {selector}: {e}", flush=True)

    print("Nie udało się kliknąć przycisku POKAŻ NADCHODZĄCE WYDARZENIA", flush=True)
    return False


def parse_events_from_text(full_text):
    full_text = normalize_text(full_text)
    lines = [line.strip() for line in full_text.splitlines() if line.strip()]

    found = []

    for idx, line in enumerate(lines):
        if has_free_places(line):
            start = max(0, idx - 5)
            end = min(len(lines), idx + 6)

            block_lines = lines[start:end]
            block_text = " | ".join(block_lines)
            block_lower = block_text.lower()

            if "pełne obłożenie" in block_lower:
                continue

            if "zarezerwuj" not in block_lower:
                # czasami ZAREZERWUJ jest kilka linii niżej, więc bierzemy większy kontekst
                start2 = max(0, idx - 8)
                end2 = min(len(lines), idx + 12)
                block_lines = lines[start2:end2]
                block_text = " | ".join(block_lines)
                block_lower = block_text.lower()

            if "zarezerwuj" in block_lower:
                found.append(block_text)

    unique = []
    seen = set()

    for item in found:
        key = item.lower()

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def parse_events_from_li(page):
    found = []

    event_items = page.locator("li")
    count = event_items.count()

    print(f"Liczba elementów li: {count}", flush=True)

    for i in range(count):
        try:
            text = event_items.nth(i).inner_text(timeout=5000)
            text = normalize_text(text)
            text_lower = text.lower()

            if has_free_places(text) and "zarezerwuj" in text_lower and "pełne obłożenie" not in text_lower:
                clean_text = " | ".join(
                    line.strip()
                    for line in text.splitlines()
                    if line.strip()
                )

                found.append(clean_text)

        except Exception:
            pass

    unique = []
    seen = set()

    for item in found:
        key = item.lower()

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


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

        page.wait_for_timeout(PAGE_WAIT_MS)

        before_text = normalize_text(page.locator("body").inner_text(timeout=20000))

        print("========== TEKST PRZED KLIKNIĘCIEM ==========", flush=True)
        print(before_text[:2500], flush=True)
        print("========== KONIEC TEKSTU PRZED ==========", flush=True)

        click_show_upcoming(page)

        after_text = normalize_text(page.locator("body").inner_text(timeout=20000))

        print("========== TEKST PO KLIKNIĘCIU ==========", flush=True)
        print(after_text[:5000], flush=True)
        print("========== KONIEC TEKSTU PO ==========", flush=True)

        if has_free_places(after_text):
            print("W tekście strony wykryto wolne miejsca.", flush=True)
        else:
            print("W tekście strony NIE wykryto wolnych miejsc.", flush=True)

        events_from_li = parse_events_from_li(page)
        events_from_text = parse_events_from_text(after_text)

        events_found.extend(events_from_li)
        events_found.extend(events_from_text)

        # usuwanie duplikatów
        unique = []
        seen = set()

        for event in events_found:
            key = event.lower()

            if key not in seen:
                seen.add(key)
                unique.append(event)

        browser.close()

    return unique


def main():
    global last_found

    print("Bot startuje...", flush=True)
    notify("✅ Reservio monitor uruchomiony.")

    while True:
        try:
            print(f"[{datetime.now()}] Start skanowania...", flush=True)

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
