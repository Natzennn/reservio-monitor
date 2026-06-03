from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import requests
import os
import time
import re
import json
import hashlib
from datetime import datetime, date


URL = os.environ.get("RESERVIO_URL", "https://ttsd.reservio.com/events")

CHECK_EVERY_SECONDS = int(os.environ.get("CHECK_EVERY_SECONDS", "60"))
SCAN_MONTHS_AHEAD = int(os.environ.get("SCAN_MONTHS_AHEAD", "3"))

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

STATE_FILE = "last_alert_state.json"


POLISH_MONTHS = {
    "styczeń": 1,
    "stycznia": 1,
    "sty": 1,

    "luty": 2,
    "lutego": 2,
    "lut": 2,

    "marzec": 3,
    "marca": 3,
    "mar": 3,

    "kwiecień": 4,
    "kwietnia": 4,
    "kwi": 4,

    "maj": 5,
    "maja": 5,

    "czerwiec": 6,
    "czerwca": 6,
    "cze": 6,

    "lipiec": 7,
    "lipca": 7,
    "lip": 7,

    "sierpień": 8,
    "sierpnia": 8,
    "sie": 8,

    "wrzesień": 9,
    "września": 9,
    "wrz": 9,

    "październik": 10,
    "października": 10,
    "pazdziernik": 10,
    "pazdziernika": 10,
    "paź": 10,
    "paz": 10,

    "listopad": 11,
    "listopada": 11,
    "lis": 11,

    "grudzień": 12,
    "grudnia": 12,
    "gru": 12,
}


AVAILABILITY_RE = re.compile(
    r"(?P<count>\d+)\s+"
    r"(?P<label>"
    r"miejsce dostępne|"
    r"miejsca dostępne|"
    r"miejsc dostępnych|"
    r"wolne miejsce|"
    r"wolne miejsca|"
    r"wolnych miejsc"
    r")",
    re.IGNORECASE,
)

TIME_RE = re.compile(
    r"(?P<time>\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2})"
)

FULL_RE = re.compile(
    r"pełne obłożenie|brak miejsc|wyprzedane",
    re.IGNORECASE,
)


def add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1

    days_in_month = [
        31,
        29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
        31,
        30,
        31,
        30,
        31,
        31,
        30,
        31,
        30,
        31,
    ]

    day = min(d.day, days_in_month[month - 1])
    return date(year, month, day)


def normalize_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def notify(text: str):
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=20,
    )

    if response.status_code >= 400:
        raise Exception(f"Telegram error {response.status_code}: {response.text}")


def load_last_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_last_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Nie udało się zapisać state: {e}", flush=True)


def state_hash(events):
    raw = json.dumps(events, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_polish_date_from_text(text: str):
    text = normalize_text(text.lower())

    patterns = [
        # czerwca 13, 2026
        r"\b(?P<month>[a-ząćęłńóśźż]+)\s+(?P<day>\d{1,2}),\s*(?P<year>\d{4})\b",

        # 13 czerwca 2026
        r"\b(?P<day>\d{1,2})\s+(?P<month>[a-ząćęłńóśźż]+)\s+(?P<year>\d{4})\b",

        # 13 cze 2026
        r"\b(?P<day>\d{1,2})\s+(?P<month>[a-ząćęłńóśźż]{3})\s+(?P<year>\d{4})\b",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            month_name = m.group("month").strip().lower()
            month = POLISH_MONTHS.get(month_name)

            if not month:
                continue

            try:
                return date(
                    int(m.group("year")),
                    month,
                    int(m.group("day")),
                )
            except ValueError:
                continue

    return None


def parse_next_event_fallback_date(page_text: str):
    text = normalize_text(page_text.lower())

    m = re.search(
        r"następne wydarzenie odbędzie się\s+(.+?)(?:\.|\n)",
        text,
        re.IGNORECASE,
    )

    if not m:
        return None

    return parse_polish_date_from_text(m.group(1))


def format_event_date(d: date):
    months = {
        1: "sty",
        2: "lut",
        3: "mar",
        4: "kwi",
        5: "maj",
        6: "cze",
        7: "lip",
        8: "sie",
        9: "wrz",
        10: "paź",
        11: "lis",
        12: "gru",
    }

    return f"{months[d.month]} {d.day}, {d.year}"


def clean_title(line: str):
    line = normalize_text(line)

    junk = [
        "Szczegóły",
        "Rezerwuj",
        "Pełne obłożenie",
        "Obsługiwane przez",
        "Copyright",
    ]

    for item in junk:
        line = line.replace(item, "")

    return normalize_text(line)


def is_probably_title(line: str):
    line = normalize_text(line)

    if not line:
        return False

    lowered = line.lower()

    bad_fragments = [
        "reservio",
        "obsługiwane przez",
        "copyright",
        "pełne obłożenie",
        "brak wydarzeń",
        "pokaż nadchodzące",
        "w tym dniu",
        "szczegóły",
        "rezerwuj",
        "zarezerwuj",
    ]

    if any(x in lowered for x in bad_fragments):
        return False

    if AVAILABILITY_RE.search(line):
        return False

    if TIME_RE.search(line):
        return False

    if parse_polish_date_from_text(line):
        return False

    return len(line) >= 3


def extract_available_events_from_text(page_text: str, fallback_date=None):
    text = normalize_text(page_text)
    lines = [normalize_text(x) for x in text.splitlines()]
    lines = [x for x in lines if x]

    events = []
    current_date = fallback_date

    for i, line in enumerate(lines):
        found_date = parse_polish_date_from_text(line)

        if found_date:
            current_date = found_date

        time_match = TIME_RE.search(line)

        if not time_match:
            continue

        block_lines = lines[i:i + 8]
        block_text = " | ".join(block_lines)

        if FULL_RE.search(block_text):
            continue

        availability_match = AVAILABILITY_RE.search(block_text)

        if not availability_match:
            continue

        event_date = current_date or fallback_date

        title = None
        for candidate in lines[i + 1:i + 5]:
            if is_probably_title(candidate):
                title = clean_title(candidate)
                break

        if not title:
            title = "Wydarzenie"

        count = int(availability_match.group("count"))
        availability_label = availability_match.group(0).strip()

        events.append(
            {
                "date": event_date.isoformat() if event_date else None,
                "date_display": format_event_date(event_date) if event_date else "data nieznana",
                "time": normalize_text(time_match.group("time")),
                "title": title,
                "spots": count,
                "availability": availability_label,
            }
        )

    return dedupe_events(events)


def dedupe_events(events):
    seen = set()
    result = []

    for event in events:
        key = (
            event.get("date"),
            event.get("time"),
            event.get("title"),
            event.get("availability"),
        )

        if key in seen:
            continue

        seen.add(key)
        result.append(event)

    return result


def event_in_horizon(event, today, horizon):
    raw_date = event.get("date")

    if not raw_date:
        # Lepiej zgłosić niż przegapić termin, ale w wiadomości będzie "data nieznana".
        return True

    try:
        d = date.fromisoformat(raw_date)
    except ValueError:
        return True

    return today <= d <= horizon


def click_if_visible(page, selectors, label):
    for selector in selectors:
        try:
            locator = page.locator(selector)

            if locator.count() == 0:
                continue

            first = locator.first

            if first.is_visible(timeout=1500):
                first.click(timeout=5000)
                print(f"Kliknięto: {label} przez selector: {selector}", flush=True)
                page.wait_for_timeout(5000)
                return True

        except Exception as e:
            print(f"Nie kliknięto {label} przez {selector}: {e}", flush=True)

    return False


def click_show_upcoming(page):
    selectors = [
        "text=/POKAŻ NADCHODZĄCE WYDARZENIA/i",
        "text=/Pokaż nadchodzące wydarzenia/i",
        "text=/nadchodzące wydarzenia/i",
        "button:has-text('POKAŻ NADCHODZĄCE WYDARZENIA')",
        "button:has-text('Pokaż nadchodzące wydarzenia')",
        "a:has-text('POKAŻ NADCHODZĄCE WYDARZENIA')",
        "a:has-text('Pokaż nadchodzące wydarzenia')",
    ]

    return click_if_visible(page, selectors, "POKAŻ NADCHODZĄCE WYDARZENIA")


def click_next_period(page):
    selectors = [
        "button[aria-label*='Następny']",
        "button[aria-label*='następny']",
        "button[aria-label*='Next']",
        "a[aria-label*='Następny']",
        "a[aria-label*='następny']",
        "a[aria-label*='Next']",

        "button:has-text('Następny')",
        "a:has-text('Następny')",
        "button:has-text('Dalej')",
        "a:has-text('Dalej')",

        "[data-testid*='next']",
        "[class*='next'] button",
        "[class*='Next'] button",
    ]

    return click_if_visible(page, selectors, "następny okres")


def get_visible_page_text(page):
    try:
        return page.inner_text("body", timeout=15000)
    except Exception:
        return ""


def scan_reservio_once():
    today = datetime.now().date()
    horizon = add_months(today, SCAN_MONTHS_AHEAD)

    all_events = []
    all_texts = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        context = browser.new_context(
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            viewport={"width": 1440, "height": 1600},
        )

        page = context.new_page()

        print(f"Wchodzę na: {URL}", flush=True)
        print(f"Skanuję od {today.isoformat()} do {horizon.isoformat()}", flush=True)

        page.goto(
            URL,
            wait_until="commit",
            timeout=60000,
        )

        page.wait_for_timeout(8000)

        first_text = get_visible_page_text(page)
        all_texts.append(first_text)

        fallback_date = parse_next_event_fallback_date(first_text)

        if fallback_date:
            print(f"Fallback data z komunikatu: {fallback_date.isoformat()}", flush=True)

        click_show_upcoming(page)

        # Pierwszy odczyt po kliknięciu "pokaż nadchodzące"
        text = get_visible_page_text(page)
        all_texts.append(text)

        found = extract_available_events_from_text(
            text,
            fallback_date=fallback_date,
        )
        all_events.extend(found)

        # Najważniejsze: przechodzimy kolejne widoki do 3 miesięcy do przodu.
        # Limit 16 jest celowo większy niż 3 miesiące, bo Reservio może mieć widoki tygodniowe.
        for step in range(16):
            if not click_next_period(page):
                print("Brak przycisku następnego okresu albo nie dało się kliknąć.", flush=True)
                break

            text = get_visible_page_text(page)
            all_texts.append(text)

            fallback_date = parse_next_event_fallback_date(text) or fallback_date

            found = extract_available_events_from_text(
                text,
                fallback_date=fallback_date,
            )

            all_events.extend(found)

            dated_events = [
                e for e in all_events
                if e.get("date")
            ]

            if dated_events:
                max_seen_date = max(date.fromisoformat(e["date"]) for e in dated_events)
                print(f"Najdalsza znaleziona data: {max_seen_date.isoformat()}", flush=True)

                if max_seen_date >= horizon:
                    print("Osiągnięto horyzont 3 miesięcy.", flush=True)
                    break

        context.close()
        browser.close()

    all_events = dedupe_events(all_events)

    in_horizon = [
        e for e in all_events
        if event_in_horizon(e, today, horizon)
    ]

    in_horizon.sort(
        key=lambda e: (
            e.get("date") or "9999-99-99",
            e.get("time") or "",
            e.get("title") or "",
        )
    )

    print(f"Wszystkie wykryte wolne eventy: {len(all_events)}", flush=True)
    print(f"Wolne eventy w horyzoncie {SCAN_MONTHS_AHEAD} mies.: {len(in_horizon)}", flush=True)

    return in_horizon, today, horizon


def build_message(events, today, horizon):
    if not events:
        return None

    lines = [
        f"🚨 Reservio: wykryto wolne miejsca!",
        "",
        f"Zakres skanowania: {today.isoformat()} → {horizon.isoformat()}",
        "",
    ]

    for event in events:
        lines.append(
            f"• {event['date_display']} | "
            f"{event['time']} | "
            f"{event['title']} | "
            f"{event['availability']}"
        )

    lines.extend(
        [
            "",
            URL,
        ]
    )

    return "\n".join(lines)


def main():
    notify(
        "✅ Reservio monitor uruchomiony.\n"
        f"Skanuję terminy do {SCAN_MONTHS_AHEAD} miesięcy do przodu.\n"
        f"{URL}"
    )

    last_state = load_last_state()

    while True:
        try:
            print("=" * 60, flush=True)
            print("Start sprawdzania Reservio...", flush=True)

            events, today, horizon = scan_reservio_once()
            message = build_message(events, today, horizon)

            current_hash = state_hash(events)

            if events:
                if last_state.get("hash") != current_hash:
                    notify(message)
                    last_state = {
                        "hash": current_hash,
                        "last_sent_at": datetime.now().isoformat(timespec="seconds"),
                        "events_count": len(events),
                    }
                    save_last_state(last_state)
                    print("Wysłano nowy alert Telegram.", flush=True)
                else:
                    print("Wolne miejsca nadal są takie same — nie wysyłam duplikatu.", flush=True)
            else:
                print("Brak wolnych miejsc w zakresie 3 miesięcy.", flush=True)

                # Resetujemy hash, żeby gdy miejsca znikną i pojawią się ponownie,
                # bot wysłał nowy alert.
                if last_state.get("hash"):
                    last_state = {}
                    save_last_state(last_state)

            print("Koniec sprawdzania.", flush=True)

        except Exception as e:
            print(f"Błąd głównej pętli: {e}", flush=True)

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
