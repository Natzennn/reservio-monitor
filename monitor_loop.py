from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

# Twoje tokeny sesyjne
COOKIE_TA = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIzMDM0YTM1Ni1jMTNiLTRiNGEtYmY0Zi1jOGRhMjkwODRiYmYiLCJqdGkiOiIxNGViZWQyOWIxNzI4ZmRhOWQxYTAyZmYxNTcxNzUxNTQ4NWQ1YzRhOWU1MGE5ZmE0ZmY0ZWFiM2ZiYTQwOTkzMGNmM2I4MzM0ZGU3OTI0NiIsImlhdCI6MTc4MDE3MzM1MS40MDQxODYsIm5iZiI6MTc4MDE3MzM1MS40MDQxOTMsImV4cCI6MTc4MDE3Njk1MS4yMTA2MDcsInN1YiI6IjQzNzM2NzgiLCJzY29wZXMiOlsidXNlciIsImNsaWVudCIsImFkbWluIiwibWFya2V0pmapaW5nUmVxdWVzdCJdfQ.nS5A2ypEH1bgp_9KxaTUTlArIj3CD50yfz2E3h2awP41HzsfwwnAcKB8ZBcEtx8_XscqFvFowdAPX2oVe_CW-c8UAITskyprGK2bz5IZuBsG3NLref3qHlcYvcdWJcEqLNzAAnOEqnbANWaJ9vDWhWZASYalLY3XIDXVrziFTWs"
COOKIE_SID = "id=3805241824052954001|t=1780173349.896|te=1780174530.606|c=09B07B7B019396C25D8E9C64953E8EF3"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Przechowujemy listę znalezionych terminów, żeby nie spamować o tych samych
last_found_details = ""


def notify(text):
    """Wysyła powiadomienie na Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=20,
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def parse_available_events(page):
    """Skanuje wyrenderowane elementy na stronie i wyciąga szczegóły

    tylko tych wydarzeń, które mają wolne miejsca.
    """
    found_events = []
    
    # Reservio buduje listę z boksów (kart) wydarzeń. Szukamy wszystkich takich sekcji/kart.
    cards = page.locator('div[data-tests*="card"], [class*="event-list-item"], [class*="Card"]').all()
    
    # Jeśli selektor klas zawiedzie, spróbujmy zgarnąć elementy po prostu z głównego kontenera listy
    if not cards:
        cards = page.locator('main list-item, article').all()

    print(f"-> Znaleziono {len(cards)} boksów wydarzeń na stronie. Analizuję każdy z osobna...", flush=True)

    for card in cards:
        try:
            card_text = card.inner_text()
            card_text_lower = card_text.lower()
            
            # Warunek: karta musi zawierać informację o wolnym miejscu lub przycisk rejestracji
            if "wolne" in card_text_lower or "dostępne" in card_text_lower or "zarezerwuj" in card_text_lower:
                # Czyścimy tekst z podwójnych enterów i zbędnych spacji
                lines = [line.strip() for line in card_text.split('\n') if line.strip()]
                
                # Zazwyczaj pierwsze 3-4 linijki to Data, Godzina, Nazwa szkolenia i liczba miejsc
                event_info = " | ".join(lines[:4])
                found_events.append(event_info)
        except Exception:
            continue

    # Zapasowy fallback: Jeśli skomplikowana struktura kafelków zawiedzie, szukamy surowym regexem w body
    if not found_events:
        full_text = page.locator("body").inner_text()
        matches = re.findall(r"([^\n]*?(?:wolne miejsce|wolne miejsca|wolnych miejsc|zarezerwuj)[^\n]*)", full_text, re.IGNORECASE)
        if matches:
            found_events = [m.strip() for m in list(set(matches))]

    return found_events


def check_reservio_detailed():
    """Loguje się sesją, ładuje listę, przewija w dół i wyciąga konkretne wydarzenia."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        context.add_cookies([
            {"name": "ta", "value": COOKIE_TA, "domain": ".reservio.com", "path": "/"},
            {"name": "sid", "value": COOKIE_SID, "domain": ".reservio.com", "path": "/"},
            {"name": "calendarView", "value": "list", "domain": ".reservio.com", "path": "/"}
        ])

        page = context.new_page()
        
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)

        try:
            page.get_by_text("Rozumiem").click(timeout=3000)
        except:
            pass

        # Przewijamy listę na kolejne miesiące
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

        # Wyciągamy szczegóły wolnych szkoleń
        available_list = parse_available_events(page)
        
        context.close()
        browser.close()
        return available_list


# Start pętli głównej
print("Uruchamianie szczegółowego monitora Reservio.", flush=True)

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Szukam szczegółów wolnych miejsc...", flush=True)

        active_events = check_reservio_detailed()

        if active_events:
            print(f"[{now}] Znaleziono wolne terminy: {active_events}", flush=True)
            
            # Tworzymy jeden ciąg tekstowy ze wszystkich znalezionych szkoleń
            current_details_str = "\n".join([f"🔹 {event}" for event in active_events])
            
            # Wysyłamy alert tylko, jeśli zmieniła się lista dostępnych szkoleń
            if current_details_str != last_found_details:
                message = (
                    "🚨 *RESERVIO: WYKRYTO WOLNE MIEJSCA!*\n\n"
                    "**Oto co jest aktualnie dostępne:**\n"
                    f"{current_details_str}\n\n"
                    f"🔗 [Zapisz się tutaj]({URL})"
                )
                notify(message)
                last_found_details = current_details_str
        else:
            print(f"[{now}] Brak wolnych terminów. Wszystko zajęte.", flush=True)
            last_found_details = ""

    except Exception as e:
        print(f"Błąd działania pętli: {e}", flush=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Zasypiam na 180s...", flush=True)
    time.sleep(CHECK_EVERY_SECONDS)
