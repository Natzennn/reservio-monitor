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
                "disable_web_page_preview": True,
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


def load_events(page):
    body_text = normalize_text(page.locator("body").inner_text(timeout=20000))

    if "POKAŻ NADCHODZĄCE WYDARZENIA" in body_text:
        click_button_if_exists(page, "POKAŻ NADCHODZĄCE WYDARZENIA")

    # Próbujemy doczytać dalsze wydarzenia, jeśli pojawi się taki przycisk.
    for _ in range(10):
        page.wait_for_timeout(1500)

        try:
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(1000)
        except Exception:
            pass

        body_text = normalize_text(page.locator("body").inner_text(timeout=20000))

        if "POKAŻ WSZYSTKIE WYDARZENIA" in body_text:
            clicked = click_button_if_exists(page, "POKAŻ WSZYSTKIE WYDARZENIA")
            if not clicked:
                break
            continue

        if "POKAŻ WIĘCEJ" in body_text:
            clicked = click_button_if_exists(page, "POKAŻ WIĘCEJ")
            if not clicked:
                break
            continue

        break


def extract_events_from_dom(page):
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

            const dateRegex = /^(poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela),\\s+(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\\s+\\d{1,2},\\s+\\d{4}$/i;

            const availabilityRegex = /\\b\\d+\\s*(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)\\b/i;

            const timeRegex = /\\b\\d{1,2}:\\d{2}\\s*-\\s*\\d{1,2}:\\d{2}\\b/;

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
                if (/^\\d+$/.test(lower)) return true;
                if (/^\\d+\\s*zł$/i.test(line)) return true;
                if (dateRegex.test(line)) return true;
                if (timeRegex.test(line)) return true;
                if (availabilityRegex.test(line)) return true;

                const noise = [
                    "szczegóły",
                    "pokaż szczegóły",
                    "zarezerwuj",
                    "pełne obłożenie",
                    "zaloguj się",
                    "z powrotem",
                    "strona główna",
                    "wydarzenia",
                    "szukaj",
                    "wybierz dzień",
                    "obsługiwane przez",
                    "reservio",
                    "copyright",
                    "wszelkie prawa zastrzeżone",
                    "masz własny biznes",
                    "wypróbuj reservio",
                    "pokaż nadchodzące wydarzenia",
                    "pokaż wszystkie wydarzenia",
                    "pokaż więcej"
                ];

                return noise.some(x => lower.includes(x));
            }

            function visibleLines(el) {
                return clean(el.innerText)
                    .split("\\n")
                    .map(clean)
                    .filter(Boolean);
            }

            function findDateForRow(row) {
                const rowTop = row.getBoundingClientRect().top + window.scrollY;

                const dateNodes = Array.from(document.querySelectorAll("h1,h2,h3,h4,div,span"))
                    .filter(isVisible)
                    .map(el => {
                        const text = clean(el.innerText);
                        const lines = text.split("\\n").map(clean).filter(Boolean);

                        if (lines.length !== 1) return null;
                        if (!dateRegex.test(lines[0])) return null;

                        return {
                            text: lines[0],
                            top: el.getBoundingClientRect().top + window.scrollY
                        };
                    })
                    .filter(Boolean)
                    .filter(item => item.top <= rowTop + 5)
                    .sort((a, b) => b.top - a.top);

                if (dateNodes.length > 0) {
                    return dateNodes[0].text;
                }

                return "Data nieznana";
            }

            function findBestEventRow(startEl) {
                let el = startEl;

                while (el && el !== document.body) {
                    const text = clean(el.innerText);
                    const lines = text.split("\\n").map(clean).filter(Boolean);

                    const hasAvailability = availabilityRegex.test(text);
                    const hasTime = timeRegex.test(text);
                    const isFull = /pełne obłożenie/i.test(text);

                    if (hasAvailability && hasTime && !isFull && lines.length <= 12) {
                        return el;
                    }

                    el = el.parentElement;
                }

                return null;
            }

            const allVisible = Array.from(document.querySelectorAll("body *")).filter(isVisible);

            const availabilityNodes = allVisible.filter(el => {
                const text = clean(el.innerText);
                if (!text) return false;
                if (!availabilityRegex.test(text)) return false;
                if (/pełne obłożenie/i.test(text)) return false;
                return true;
            });

            const rows = [];

            for (const node of availabilityNodes) {
                const row = findBestEventRow(node);

                if (!row) continue;

                if (!rows.includes(row)) {
                    rows.push(row);
                }
            }

            const found = [];

            for (const row of rows) {
                const text = clean(row.innerText);
                const lines = text.split("\\n").map(clean).filter(Boolean);

                if (/pełne obłożenie/i.test(text)) continue;

                const availability = lines.find(line => availabilityRegex.test(line)) || "";
                const time = lines.find(line => timeRegex.test(line)) || "Godzina nieznana";

                let title = "";

                for (const line of lines) {
                    if (isNoise(line)) continue;
                    title = line;
                    break;
                }

                if (!title) {
                    title = "Wydarzenie nieznane";
                }

                const eventDate = findDateForRow(row);

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

        # Nie wysyłamy śmieci bez daty, żeby uniknąć fałszywych alertów.
        if date_text == "Data nieznana":
            print(
                f"Pominięto event bez daty: {time_text} | {title_text} | {availability_text}",
                flush=True,
            )
            continue

        clean_events.append(
            f"{date_text} | {time_text} | {title_text} | {availability_text}"
        )

    return clean_events


def extract_events_from_text_fallback(page):
    """
    Awaryjny parser tekstowy.
    Używany tylko, jeśli parser DOM nic nie znalazł.
    Idzie linia po linii i nie miesza pełnych wydarzeń z wolnymi.
    """

    text = normalize_text(page.locator("body").inner_text(timeout=20000))

    lines = [
        normalize_text(line)
        for line in text.splitlines()
        if normalize_text(line)
    ]

    date_regex = re.compile(
        r"^(poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela),\s+"
        r"(sty|lut|mar|kwi|maj|cze|lip|sie|wrz|paź|paz|lis|gru)\s+"
        r"\d{1,2},\s+\d{4}$",
        re.IGNORECASE,
    )

    time_regex = re.compile(
        r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b"
    )

    availability_regex = re.compile(
        r"\b\d+\s*(?:"
        r"wolne miejsce|wolne miejsca|wolnych miejsc|"
        r"miejsce dostępne|miejsca dostępne|miejsc dostępnych"
        r")\b",
        re.IGNORECASE,
    )

    noise = {
        "tanie treningi strzelectwa dynamicznego",
        "przemysław",
        "z powrotem",
        "strona główna",
        "/",
        "wydarzenia",
        "szukaj...",
        "pokaż szczegóły",
        "wybierz dzień",
        "obsługiwane przez",
        "reservio business",
        "kalendarz wydarzeń | tanie treningi strzelectwa dynamicznego",
    }

    found = []

    current_date = None
    current_title = None
    current_time = None
    current_availability = None
    current_is_full = False

    def flush_event():
        nonlocal current_title, current_time, current_availability, current_is_full

        if (
            current_date
            and current_title
            and current_time
            and current_availability
            and not current_is_full
        ):
            found.append(
                f"{current_date} | {current_time} | {current_title} | {current_availability}"
            )

        current_title = None
        current_time = None
        current_availability = None
        current_is_full = False

    for line in lines:
        lower = line.lower()

        if date_regex.match(line):
            flush_event()
            current_date = line
            continue

        if "w tym dniu nie ma żadnych wydarzeń" in lower:
            flush_event()
            continue

        if lower in noise:
            continue

        if lower.startswith("© copyright"):
            continue

        if "masz własny biznes" in lower:
            continue

        if lower in ["pon.", "wt.", "śr.", "czw.", "pt.", "sob.", "niedz."]:
            continue

        if re.fullmatch(r"\d+", line):
            continue

        if re.fullmatch(r"\d+\s*zł", line, re.IGNORECASE):
            continue

        if "pełne obłożenie" in lower:
            current_is_full = True
            continue

        if time_regex.search(line):
            current_time = line
            continue

        if availability_regex.search(line):
            current_availability = line
            continue

        if current_date and not current_title:
            current_title = line
            continue

    flush_event()

    unique = []
    seen = set()

    for event in found:
        key = event.lower()

        if key not in seen:
            seen.add(key)
            unique.append(event)

    return unique


def scan_ttsd():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        page = browser.new_page(
            viewport={
                "width": 1400,
                "height": 1800,
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

        load_events(page)

        page.wait_for_timeout(3000)

        print("Wyciągam pojedyncze wydarzenia z DOM...", flush=True)
        events = extract_events_from_dom(page)

        if not events:
            print("DOM nic nie znalazł. Uruchamiam fallback tekstowy...", flush=True)
            events = extract_events_from_text_fallback(page)

        unique = []
        seen = set()

        for event in events:
            key = event.lower()

            if key not in seen:
                seen.add(key)
                unique.append(event)

        if unique:
            for event in unique:
                print(f"Znaleziono: {event}", flush=True)
        else:
            print("Brak wolnych miejsc.", flush=True)

        browser.close()

        return unique


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
