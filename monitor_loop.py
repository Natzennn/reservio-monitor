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


def has_available_place(text):
    """Sprawdza za pomocą Regex, czy w wyrenderowanym tekście są wolne miejsca."""
    matches = re.findall(
        r"\d+\s+(miejsce dostępne|miejsca dostępne|miejsc dostępnych)",
        text.lower()
    )
    return len(matches) > 0


def check_reservio_by_clicking():
    """Otwiera stronę i klika strzałkę w prawo kilka razy, żeby wyrenderować

    nadchodzące tygodnie, po czym zbiera z nich skumulowany tekst.
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
                
                # Wejście na stronę
                page.goto(URL, wait_until="commit", timeout=60000)
                page.wait_for_timeout(6000)
                
                # Zbieramy tekst z 1. tygodnia (obecnego)
                accumulated_text = page.inner_text("body").lower()
                
                # Klikamy strzałkę "Dalej" (w prawo) 5 razy, żeby sprawdzić kolejnych 5 tygodni w przód!
                # Selektory pasują do przycisków nawigacji kalendarza (szukamy ikony lub strzałki)
                for i in range(5):
                    try:
                        # Próbuje kliknąć przycisk nawigacji (strzałkę w prawo)
                        next_button = page.locator('button:has(svg), [aria-label*="next"], .next-button, .bi-chevron-right').first
                        if next_button.count() > 0:
                            next_button.click()
                            page.wait_for_timeout(2000)  # Czekamy 2 sekundy na załadowanie nowego tygodnia
                            # Doklejamy tekst z kolejnego tygodnia do naszego "worka"
                            accumulated_text += " " + page.inner_text("body").lower()
                    except Exception as click_err:
                        print(f"Nie udało się kliknąć strzałki na kroku {i}: {click_err}", flush=True)
                
                browser.close()
                return accumulated_text
                
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Nie udało się pobrać danych ze strony po 3 próbach.")


notify("✅ Poprawiony monitor klikający (Sprawdzanie tygodni w przód) wystartował.")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Przeklikuję kalendarz na 5 tygodni w przód...", flush=True)

        # Pobieramy tekst z przeklikanych tygodni
        full_text_data = check_reservio_by_clicking()
        
        # Sprawdzamy czy gdziekolwiek w tych tygodniach pojawił się tekst "X miejsc dostępnych"
        current_state = has_available_place(full_text_data)

        print(f"[{now}] Wynik analizy (Dostępne miejsca w sprawdzanych tygodniach): {current_state}", flush=True)

        if current_state != last_state:
            if current_state:
                notify(
                    f"🚨 Reservio: Wykryto wolne miejsca na szkolenie w sprawdzanych tygodniach!\n\nLink do kalendarza: {URL}"
                )
            last_state = current_state

        print(f"[{now}] Cykl zakończony. Zasypiam na {CHECK_EVERY_SECONDS}s.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
