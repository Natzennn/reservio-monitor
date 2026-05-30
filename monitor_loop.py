from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Zmienna przechowująca stan z poprzedniego sprawdzenia
last_state = None


def notify(text):
    """Wysyła powiadomienie na Telegram."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def extract_booking_links_from_html(html_content):
    """Przeszukuje surowy kod źródłowy strony HTML w poszukiwaniu linków

    do rejestracji na wydarzenia. Wolne terminy MAJĄ aktywne linki href,
    pełne terminy ich NIE MAJĄ.
    """
    # Szukamy wzorca linków widocznych na Twoich screenach z DevTools: /events/ID-WYDARZENIA
    # Wykluczamy główny URL /events za pomocą znaku [^"]+ (musi być dalszy ciąg ID)
    links = re.findall(r'href="/events/([a-zA-Z0-9\-]+)"', html_content)
    
    # Usuwamy ewentualne duplikaty
    unique_links = list(set(links))
    
    if unique_links:
        print(f"-> Wykryto aktywne linki do zapisów (wolne miejsca!): {unique_links}", flush=True)
    
    return len(unique_links) > 0


def check_reservio_html_source():
    """Pobiera kompletny, surowy kod HTML strony po pełnym załadowaniu skryptów."""
    for attempt in range(3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu"
                    ]
                )
                page = browser.new_page()
                
                # Wchodzimy na stronę
                page.goto(URL, wait_until="commit", timeout=60000)
                
                # Dajemy 12 sekund na pełne dociągnięcie całego kalendarza w tle przez skrypty Next.js
                page.wait_for_timeout(12000)
                
                # Pobieramy pełny, surowy kod źródłowy HTML (zawiera też ukryte tagi i skrypty)
                raw_html = page.content()
                
                browser.close()
                return raw_html
                
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Nie udało się pobrać kodu HTML strony po 3 próbach.")


notify("🚨 Uruchomiono PANCERNY monitor HTML (Analiza linków rezerwacyjnych)...")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Pobieram i analizuję surowy kod HTML kalendarza...", flush=True)

        # Pobieramy czysty kod HTML
        html_source = check_reservio_html_source()
        
        # Sprawdzamy czy w kodzie ukrywa się jakikolwiek aktywny link do formularza zapisu
        current_state = extract_booking_links_from_html(html_source)

        print(f"[{now}] Wynik analizy kodu źródłowego: {current_state}", flush=True)

        if current_state != last_state:
            if current_state:
                notify(
                    f"🚨 SYSTEM RESERVIO: Wykryto otwarte linki do zapisów! Ktoś zwolnił miejsce!\n\nRezerwuj tutaj: {URL}"
                )
            last_state = current_state

        print(f"[{now}] Cykl zakończony. Zasypiam na {CHECK_EVERY_SECONDS}s.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
