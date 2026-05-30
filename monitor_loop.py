from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

# Twoje spersonalizowane tokeny sesyjne wyciągnięte ze zrzutu
COOKIE_TA = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIzMDM0YTM1Ni1jMTNiLTRiNGEtYmY0Zi1jOGRhMjkwODRiYmYiLCJqdGkiOiIxNGViZWQyOWIxNzI4ZmRhOWQxYTAyZmYxNTcxNzUxNTQ4NWQ1YzRhOWU1MGE5ZmE0ZmY0ZWFiM2ZiYTQwOTkzMGNmM2I4MzM0ZGU3OTI0NiIsImlhdCI6MTc4MDE3MzM1MS40MDQxODYsIm5iZiI6MTc4MDE3MzM1MS40MDQxOTMsImV4cCI6MTc4MDE3Njk1MS4yMTA2MDcsInN1YiI6IjQzNzM2NzgiLCJzY29wZXMiOlsidXNlciIsImNsaWVudCIsImFkbWluIiwibWFya2V0cGxhY2VCb29raW5nUmVxdWVzdCJdfQ.nS5A2ypEH1bgp_9KxaTUTlArIj3CD50yfz2E3h2awP41HzsfwwnAcKB8ZBcEtx8_XscqFvFowdAPX2oVe_CW-c8UAITskyprGK2bz5IZuBsG3NLref3qHlcYvcdWJcEqLNzAAnOEqnbANWaJ9vDWhWZASYalLY3XIDXVrziFTWs"
COOKIE_SID = "id=3805241824052954001|t=1780173349.896|te=1780174530.606|c=09B07B7B019396C25D8E9C64953E8EF3"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_alert = None


def notify(text):
    """Wysyła powiadomienie na Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def has_available_place(text):
    """Przeszukuje tekst pod kątem fraz świadczących o wolnym terminie."""
    cleaned_text = text.lower()
    # Szukamy słów "wolne miejsce/miejsca" lub aktywnego przycisku "zarezerwuj"
    pattern = r"\d+\s+(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne)|zarezerwuj"
    matches = re.findall(pattern, cleaned_text)
    if len(matches) > 0:
        print(f"-> Detekcja trafień: {matches}", flush=True)
    return len(matches) > 0


def check_reservio_authenticated():
    """Uruchamia Playwright z wstrzykniętą tożsamością użytkownika, wymuszając widok listy."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Wstrzykujemy tokeny autoryzacyjne bezpośrednio do kontenera przeglądarki bota
        context.add_cookies([
            {
                "name": "ta",
                "value": COOKIE_TA,
                "domain": ".reservio.com",
                "path": "/"
            },
            {
                "name": "sid",
                "value": COOKIE_SID,
                "domain": ".reservio.com",
                "path": "/"
            },
            {
                "name": "calendarView",
                "value": "list",  # Wymuszamy domyślny widok listy zamiast kalendarza!
                "domain": ".reservio.com",
                "path": "/"
            }
        ])

        page = context.new_page()
        
        # Wchodzimy na stronę jako zalogowany użytkownik z widokiem listy
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(6000)

        # Klikamy "Rozumiem" jeśli pojawi się baner cookieyes, by odsłonić widok
        try:
            page.get_by_text("Rozumiem").click(timeout=3000)
        except:
            pass

        # Przewijamy listę 3 razy w dół (infinite scroll), aby załadować czerwiec i lipiec
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)

        # Pobieramy pełną zawartość tekstową wyrenderowaną na stronie
        page_text = page.locator("body").inner_text()
        
        context.close()
        browser.close()
        return page_text


# Start pętli
notify("🚀 Uruchomiono autoryzowany monitor Reservio. Sesja wstrzyknięta pomyślnie.")
print("Uruchamianie autoryzowanego monitora.", flush=True)

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Sprawdzam kalendarz przy użyciu tokenu sesji...", flush=True)

        full_content = check_reservio_authenticated()
        current_state = has_available_place(full_content)

        print(f"[{now}] Wynik analizy konta: {current_state}", flush=True)

        if current_state != last_alert:
            if current_state:
                notify(
                    f"🚨 *RESERVIO: WYKRYTO WOLNE MIEJSCE ZA POMOCĄ TWOJEJ SESJI!*\n\n"
                    "Bot pomyślnie załadował Twój widok listy i odnalazł wolny termin!\n\n"
                    f"🔗 Zapisz się natychmiast: {URL}"
                )
            last_alert = current_state

    except Exception as e:
        print(f"Błąd działania pętli: {e}", flush=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Cykl zakończony. Sen na 180s...", flush=True)
    time.sleep(CHECK_EVERY_SECONDS)
