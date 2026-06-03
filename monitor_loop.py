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


def click_button_if_exists(page, text):
    selectors = [
        f'button:has-text("{text}")',
        f'a:has-text("{text}")',
        f'text="{text}"',
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first

            if locator.count() > 0 and locator.is_visible():
                print(f"Klikam: {text}", flush=True)

                try:
                    locator.scroll_into_view_if_needed(timeout=5000)
                except Exception:
                    pass

                locator.click(timeout=10000, force=True)
                page.wait_for_timeout(WAIT_MS)
                return True

        except Exception as e:
            print(f"Nie udało się kliknąć {text} przez {selector}: {e}", flush=True)

    return False


def extract_events_from_dom(page):
    """
    Czyta tylko pojedyncze kafelki wydarzeń, a nie całe kontenery strony.
    Dzięki temu nie miesza 'Pełne obłożenie' z innym eventem, który ma miejsca.
    """

    events = page.evaluate(
        """
        () => {
            function clean(text) {
                return (text || "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/\\u202f/g, " ")
                    .replace(/\\u2009/g, " ")
                    .replace(/\\u200b/g, "")
                    .trim();
            }

            const availabilityRegex = /\\b\\d+\\s*(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)\\b/i;
            const timeRegex = /\\b\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}\\b/;
            const dateRegex = /^(Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela),\\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\\s+\\d{1,2},\\s+\\d{4}$/i;

            function isVisible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();

                return (
                    style.display !== "none" &&
                    style.visibility !== "hidden" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            }

            function isNoise(line) {
                const lower = line.toLowerCase();

                if (!lower || lower === "/") return true;
                if (/^\\d+\\s*zł$/i.test(line)) return true;
                if (/^\\d+$/i.test(line)) return true;

                const noise = [
                    "szczegóły",
                    "pokaż szczegóły",
                    "zarezerwuj",
                    "pełne obłożenie",
                    "zaloguj się",
                    "strona główna",
                    "wydarzenia",
                    "obsługiwane przez",
                    "copyright",
                    "wszelkie prawa zastrzeżone",
                    "masz własny biznes",
                    "wypróbuj reservio",
                    "pokaż nadchodzące wydarzenia",
                    "pokaż wszystkie wydarzenia"
                ];

                return noise.some(x => lower.includes(x));
            }

            function findDateForEvent(row) {
                // 1. Szukamy daty w najbliższym większym elemencie listy.
                let parent = row.parentElement;

                while (parent) {
                    const headings = Array.from(parent.querySelectorAll("h1,h2,h3,h4"))
                        .map(h => clean(h.innerText))
                        .filter(Boolean);

                    for (const heading of headings) {
                        if (dateRegex.test(heading)) {
                            return heading;
                        }
                    }

                    parent = parent.parentElement;
                }

                // 2. Fallback: szukamy daty w poprzednich elementach na stronie.
                const all = Array.from(document.querySelectorAll("h1,h2,h3,h4,div,li"))
                    .filter(isVisible);

                const rowTop = row.getBoundingClientRect().top + window.scrollY;
                let bestDate = "";

                for (const el of all) {
                    const txt = clean(el.innerText);

                    if (!dateRegex.test(txt)) continue;

                    const elTop = el.getBoundingClientRect().top + window.scrollY;

                    if (elTop <= rowTop) {
                        bestDate = txt;
                    }
                }

                return bestDate || "Data nieznana";
            }

            // Kandydaci: linki do szczegółów wydarzeń i małe bloki listy.
            const candidates = Array.from(document.querySelectorAll("a[href*='/events/'], li, div"))
                .filter(isVisible);

            const rows = [];

            for (const el of candidates) {
                const text = clean(el.innerText);

                if (!text) continue;
                if (!availabilityRegex.test(text)) continue;
                if (/pełne obłożenie/i.test(text)) continue;

                const lines = text.split("\\n").map(clean).filter(Boolean);

                // Odrzucamy wielkie kontenery, które mieszają kilka wydarzeń.
                if (lines.length > 12) continue;

                // Odrzucamy rodziców, jeśli mają mniejsze dziecko z dostępnością.
                const childWithAvailability = Array.from(el.children).some(child => {
                    const childText = clean(child.innerText);
                    return childText && childText !== text && availabilityRegex.test(childText);
                });

                if (childWithAvailability) continue;

                rows.push(el);
            }

            const found = [];

            for (const row of rows) {
                const text = clean(row.innerText);
                const lines = text.split("\\n").map(clean).filter(Boolean);

                const availability = lines.find(line => availabilityRegex.test(line)) || "";
                const time = lines.find(line => timeRegex.test(line)) || "Godzina nieznana";

                let title = "";

                for (const line of lines) {
                    if (dateRegex.test(line)) continue;
                    if (availabilityRegex.test(line)) continue;
                    if (timeRegex.test(line)) continue;
                    if (isNoise(line)) continue;

                    title = line;
                    break;
                }

                if (!title) title = "Wydarzenie nieznane";

                const eventDate = findDateForEvent(row);

                found.push({
                    date: eventDate,
                    time,
                    title,
                    availability
                });
            }

            const unique = [];
            const seen = new Set();

            for (const event of found) {
                const key = `${event.date}|${event.time}|${event.title}|${event.availability}`.toLowerCase();

                if (!seen.has(key)) {
                    seen.add(key);
                    unique.push(event);
                }
            }

            return unique;
        }
        """
    )

    clean_events = []

    for event in events:
        date_text = normalize_text(event.get("date", "Data nieznana"))
        time_text = normalize_text(event.get("time", "Godzina nieznana"))
        title_text = normalize_text(event.get("title", "Wydarzenie nieznane"))
        availability_text = normalize_text(event.get("availability", ""))

        if not availability_text:
            continue

        clean_events.append(
            f"{date_text} | {time_text} | {title_text} | {availability_text}"
        )

    return clean_events


def scan_ttsd():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 1600,
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
            click_button_if_exists(page, "POKAŻ NADCHODZĄCE WYDARZENIA")

        # Jeżeli pojawi się przycisk pokazania wszystkich wydarzeń, klikamy.
        for _ in range(3):
            text = normalize_text(page.locator("body").inner_text(timeout=20000))

            if "POKAŻ WSZYSTKIE WYDARZENIA" in text:
                clicked = click_button_if_exists(page, "POKAŻ WSZYSTKIE WYDARZENIA")

                if not clicked:
                    break
            else:
                break

        page.wait_for_timeout(3000)

        print("Wyciągam pojedyncze wydarzenia z DOM...", flush=True)

        events = extract_events_from_dom(page)

        if events:
            for event in events:
                print(f"Znaleziono: {event}", flush=True)
        else:
            print("Brak wolnych miejsc.", flush=True)

        browser.close()

        return events


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
