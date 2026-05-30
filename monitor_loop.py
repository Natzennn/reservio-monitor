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
    """NOWY REGEX: Wykrywa zarówno 'miejsca dostępne' jak i 'wolne miejsca'

    z nowego widoku listy, który podesłałeś na screenach!
    """
    cleaned_text = text.lower()
    
    # Szukamy: "X wolne miejsce/miejsca/miejsc" LUB "X miejsce/miejsca dostępne"
    pattern = r"\d+\s+(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne|miejsc dostępnych)"
    
    matches = re.findall(pattern, cleaned_text)
    if len(matches) > 0:
        print(f"-> Znalezione dopasowania fraz: {matches}", flush=True)
    return len(matches) > 0


def check_reservio_perfect_scan():
    """Wchodzi na stronę, przewija ją w dół (żeby załadować listę na całe miesiące w przód)

    i pobiera pełny tekst.
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
                
                # Wchodzimy na stronę
                page.goto(URL, wait_until="commit", timeout=60000)
                page.wait_for_timeout(6000)
                
                # Symulujemy przewijanie w dół, aby dynamiczna lista (infinite scroll) dociągnęła odległe terminy
                for _ in range(3):
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500)
                
                # Pobieramy tekst ze skumulowanej, długiej listy wydarzeń
                text_data = page.inner_text("body")
                browser.close()
                return text_data
                
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Nie udało się pobrać danych ze strony po 3 próbach.")


notify("✅ Ostateczny monitor (Wykrywanie 'wolnych miejsc' + Scroll) uruchomiony!")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Przeszukuję listę wydarzeń (cały kalendarz)...", flush=True)

        # Pobieramy tekst z całej załadowanej listy nadchodzących treningów
        full_text = check_reservio_perfect_scan()
        
        # Sprawdzamy obecność wolnych miejsc nowym, elastycznym regexem
        current_state = has_available_place(full_text)

        print(f"[{now}] Wynik analizy: {current_state}", flush=True)

        if current_state != last_state:
            if current_state:
                notify(
                    f"🚨 Reservio: Wykryto wolne miejsca na szkolenie!\n\nSprawdź szybko kalendarz: {URL}"
                )
            last_state = current_state

        print(f"[{now}] Cykl zakończony. Zasypiam na {CHECK_EVERY_SECONDS}s.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
