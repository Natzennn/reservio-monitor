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


def extract_events_from_dom(page):
    """
    Pobiera wydarzenia z DOM w kolejności widocznej na stronie.
    Dzięki temu łapie też datę dnia, np.:
    Sobota, cze 13, 2026
    """

    events = page.evaluate(
        """
        () => {
            const dateRegex = /^(Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela),\\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\\s+\\d{1,2},\\s+\\d{4}$/i;

            const availabilityRegex = /\\b\\d+\\s*(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)\\b/i;

            const timeRegex = /\\b\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}\\b/;

            function cleanText(text) {
                return (text || "")
                    .replace(/\\u00a0/g, " ")
                    .replace(/\\u202f/g, " ")
                    .replace(/\\u2009/g, " ")
                    .replace(/\\u200b/g, "")
                    .trim();
            }

            function isVisible(el) {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();

                return (
                    style &&
                    style.visibility !== "hidden" &&
                    style.display !== "none" &&
                    rect.width > 0 &&
                    rect.height > 0
                );
            }

            function isNoise(line) {
                const lower = line.toLowerCase();

                const noise = [
                    "szczegóły",
                    "pełne obłożenie",
                    "zaloguj się",
                    "strona główna",
                    "wydarzenia",
                    "obsługiwane przez",
                    "copyright",
                    "wszelkie prawa zastrzeżone",
                    "masz własny biznes",
                    "wypróbuj reservio",
                    "pokaż nadchodzące wydarzenia"
                ];

                if (lower === "/" || lower === "") return true;

                return noise.some(x => lower.includes(x));
            }

            const nodes = Array.from(document.querySelectorAll("h1, h2, h3, h4, li, div"));

            let currentDate = "";
            const found = [];

            for (const node of nodes) {
                if (!isVisible(node)) continue;

                const text = cleanText(node.innerText);
                if (!text) continue;

                const lines = text
                    .split("\\n")
                    .map(cleanText)
                    .filter(Boolean);

                if (lines.length === 1 && dateRegex.test(lines[0])) {
                    currentDate = lines[0];
                    continue;
                }

                if (!availabilityRegex.test(text)) continue;

                // Bierzemy tylko realne bloki eventów, nie wielki body/container.
                if (lines.length > 20) continue;

                const availabilityLine = lines.find(line => availabilityRegex.test(line)) || "";
                const timeLine = lines.find(line => timeRegex.test(line)) || "Godzina nieznana";

                let titleLine = "";

                for (const line of lines) {
                    if (isNoise(line)) continue;
                    if (dateRegex.test(line)) continue;
                    if (availabilityRegex.test(line)) continue;
                    if (timeRegex.test(line)) continue;
                    if (/^\\d+\\s*zł$/i.test(line)) continue;
                    if (/^\\d+$/i.test(line)) continue;

                    titleLine = line;
                    break;
                }

                if (!titleLine) titleLine = "Wydarzenie nieznane";

                found.push({
                    date: currentDate || "Data nieznana",
                    time: timeLine,
                    title: titleLine,
                    availability: availabilityLine
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

        print("Wyciągam wydarzenia z DOM...", flush=True)

        events = extract_events_from_dom(page)

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
