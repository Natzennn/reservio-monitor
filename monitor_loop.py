from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie dokładnie co 3 minuty

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Zmienna przechowująca stan z poprzedniego sprawdzenia
last_state = None


def notify(text):
    """Wysyła powiadomienie na Telegram z obsługą błędów sieciowych."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def has_available_place(text):
    """Sprawdza za pomocą Regex, czy w tekście strony są wolne miejsca."""
    matches = re.findall(
        r"\d+\s+(miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
        text.lower()
    )
    return len(matches) > 0


def check_reservio_once():
    """Uruchamia czystą instancję Chromium, pobiera tekst strony i całkowicie ją zamyka.

    Dzięki temu unikamy problemów z pamięcią podręczną (cache) i wyciekami
    pamięci.
    """
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
                
                # 'commit' gwarantuje, że nie utgniemy na ładujących się w tle skryptach śledzących
                page.goto(URL, wait_until="commit", timeout=60000)
                
                # Kluczowe 10 sekund czekania – w tym czasie JS dociąga z bazy pomarańczowe klocki
                page.wait_for_timeout(10000)
                
                # Pobieramy wyłącznie czysty tekst widoczny na ekranie
                text = page.inner_text("body").lower()
                browser.close()
                return text
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Nie udało się załadować i odczytać strony po 3 próbach.")


# Powiadomienie o restarcie bota na Railway
notify("✅ Poprawiony monitor Reservio (Czysty start sesji) został uruchomiony.")

# Główna pętla programu działająca 24/7
while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Rozpoczynam sprawdzanie strony...", flush=True)

        # Pobieramy tekst z nowo otwartej przeglądarki
        text = check_reservio_once()
        
        # Analizujemy tekst pod kątem wolnych miejsc
        current_state = has_available_place(text)

        print(f
