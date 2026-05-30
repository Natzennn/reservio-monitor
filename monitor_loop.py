from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
import json
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


def has_available_place(text):
    """Sprawdza za pomocą Regex w całym tekście, czy są wolne miejsca."""
    matches = re.findall(
        r"\d+\s+(miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
        text.lower()
    )
    return len(matches) > 0


def check_reservio_entire_calendar():
    """Otwiera stronę, wyciąga z niej cały ukryty kod JSON oraz pełny tekst,

    co pozwala monitorować wydarzenia w przód, a nie tylko obecny tydzień.
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
                
                # Wchodzimy na stronę i czekamy na stabilne załadowanie
                page.goto(URL, wait_until="commit", timeout=60000)
                
                # Kluczowe sekundy na dociągnięcie całego kalendarza przez JS
                page.wait_for_timeout(10000)
                
                # 1. POBIERANIE UKRYTEGO JSONA (Widzi miesiące w przód)
                # Szukamy tagu, który pokazałeś na zrzucie ekranu
                full_json_text = ""
                try:
                    next_data_script = page.locator("script#__NEXT_DATA__")
                    if next_data_script.count() > 0:
                        full_json_text = next_data_script.inner_text().lower()
                except Exception as json_err:
                    print(f"Brak skryptu JSON (nic nie szkodzi): {json_err}", flush=True)

                # 2. POBIERANIE WIDOCZNEGO TEKSTU (Dla obecnego tygodnia)
                visible_text = page.inner_text("body").lower()
                
                # Łączymy oba źródła danych w jeden wielki worek informacji
                combined_data = visible_text + " " + full_json_text
                
                browser.close()
                return combined_data
                
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Nie udało się pobrać danych ze strony po 3 próbach.")


notify("✅ Zaawansowany monitor CAŁEGO kalendarza (Wersja JSON+Tekst) wystartował.")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Przeszukuję cały kalendarz (obecny tydzień + ukryte dane)...", flush=True)

        # Pobieramy połączone dane z całego kodu strony
        big_text_data = check_reservio_entire_calendar()
        
        # Analizujemy, czy gdziekolwiek w kodzie/tekście pojawia się wolne miejsce
        current_state = has_available_place(big_text_data)

        print(f"[{now}] Wynik analizy (Dostępne miejsca w kalendarzu): {current_state}", flush=True)

        if current_state != last_state:
            if current_state:
                notify(
                    f"🚨 Reservio: Wykryto wolne miejsca na szkolenie (również w nadchodzących miesiącach)!\n\nLink do kalendarza: {URL}"
                )
            last_state = current_state

        print(f"[{now}] Cykl zakończony. Zasypiam na {CHECK_EVERY_SECONDS}s.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
