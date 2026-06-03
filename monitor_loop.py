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
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def normalize_text(text):
    return text.replace("\xa0", " ").replace("\u202f", " ").replace("\u200b", "").strip()


def has_free_places(text):
    return bool(
        re.search(
            r"\d+\s*(?:wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
            text,
            re.IGNORECASE,
        )
    )


def click_show_upcoming(page):
    selectors = [
        'button:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'a:has-text("POKAŻ NADCHODZĄCE WYDARZENIA")',
        'text="POKAŻ NADCHODZĄCE WYDARZENIA"',
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                locator.scroll_into_view_if_needed(timeout=5000)
                locator.click(timeout=10000, force=True)
                page.wait_for_timeout(WAIT_MS)
                return True
        except Exception:
            continue
    return False


def extract_events_from_dom(page):
    """Wyciąga datę, godzinę, tytuł i dostępność każdego wydarzenia."""
    events = page.evaluate(
        """
        () => {
            function normalize(text) {
                return (text||"").replace(/\\u00a0/g," ").replace(/\\u202f/g," ").replace(/\\u200b/g,"").trim();
            }
            const dateRegex = /^(Poniedziałek|Wtorek|Środa|Czwartek|Piątek|Sobota|Niedziela),/i;
            const availabilityRegex = /\\d+\\s*(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)/i;
            const timeRegex = /\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}/;

            const nodes = Array.from(document.querySelectorAll("h1, h2, h3, h4, li, div"));
            let currentDate = "";
            const found = [];

            for (const node of nodes) {
                if (!node.offsetParent) continue; // widoczny

                const text = normalize(node.innerText);
                if (!text) continue;

                const lines = text.split("\\n").map(normalize).filter(Boolean);

                if (lines.length === 1 && dateRegex.test(lines[0])) {
                    currentDate = lines[0];
                    continue;
                }

                if (!lines.some(l => availabilityRegex.test(l))) continue;

                for (let l of lines) {
                    if (availabilityRegex.test(l)) {
                        const availability = l;
                        const timeLine = lines.find(t => timeRegex.test(t)) || "Godzina nieznana";
                        const titleLine = lines.find(t => !availabilityRegex.test(t) && !timeRegex.test(t) && t.toLowerCase() !== currentDate.toLowerCase()) || "Wydarzenie nieznane";

                        found.push({date: currentDate||"Data nieznana", time: timeLine, title: titleLine, availability});
                        break;
                    }
                }
            }

            return found;
        }
        """
    )

    clean_events = []
    for e in events:
        clean_events.append(f"{e['date']} | {e['time']} | {e['title']} | {e['availability']}")
    return clean_events


def scan_ttsd():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width":1400,"height":1200}, user_agent="Mozilla/5.0")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(WAIT_MS)

        body_text = normalize_text(page.locator("body").inner_text(timeout=20000))
        if "POKAŻ NADCHODZĄCE WYDARZENIA" in body_text:
            click_show_upcoming(page)
        page.wait_for_timeout(3000)

        events = extract_events_from_dom(page)
        browser.close()
        return events


notify("✅ TTSD monitor uruchomiony.")
print("Start TTSD monitora.", flush=True)

while True:
    try:
        print(f"[{datetime.now()}] Sprawdzam TTSD...", flush=True)
        events = scan_ttsd()

        if events:
            current_alert = "\n".join(f"• {event}" for event in events)
            print("Dostępne: True", flush=True)
            print(current_alert, flush=True)

            if current_alert != last_alert:
                notify(f"🚨 TTSD: wykryto wolne miejsca!\n\n{current_alert}\n\n{URL}")
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
