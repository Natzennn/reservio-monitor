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
    """Szuka frazy 'wolne miejsce/miejsca' z widoku listy."""
    cleaned_text = text.lower()
    pattern = r"\d+\s+(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne)"
    matches = re.findall(pattern, cleaned_text)
    if len(matches) > 0:
        print(f"-> Znaleziono wolne terminy! Szczegóły frazy: {matches}", flush=True)
    return len(matches) > 0


def check_reservio_force_list_view():
    """Wchodzi na stronę, klika przycisk widoku listy i pobiera tekst."""
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
                
                # Ustawiamy duży ekran, żeby ikony się nie schowały w wersji mobilnej
                page.set_viewport_size({"width": 1920, "height": 1080})
                
                page.goto(URL, wait_until="commit", timeout=60000)
                page.wait_for_timeout(6000)  # Czekamy na załadowanie strony
                
                # KLIKANIE IKONY LISTY (w prawym górnym rogu)
                # Na Twoim screenie przycisk listy to ostatni button w nawigacji widoków.
                # Próbujemy kliknąć ikonę listy za pomocą elastycznych selektorów.
                list_buttons = [
                    "button:has(svg):right-of(button:has(svg))", # Przycisk po prawej stronie innego przycisku z ikoną
                    "main header button:last-of-type",
                    ".styles-module__calendarView___3w_TI+button",
                    "button:has(svg)" # Fallback
                ]
                
                clicked = False
                for selector in list_buttons:
                    try:
                        elements = page.locator(selector)
                        # Jeśli znaleźliśmy przyciski widoku, klikamy ostatni (widok listy)
                        if elements.count() > 0:
                            elements.last.click()
                            clicked = True
                            print(f"-> Kliknięto przełącznik widoku za pomocą: {selector}", flush=True)
                            break
                    except:
                        continue
                
                if not clicked:
                    print("-> Nie udało się kliknąć ikony (być może widok listy jest domyślny). Próbuję dalej...", flush=True)
                
                # Po ewentualnym kliknięciu czekamy 5 sekund, aż lista zaciągnie wydarzenia w dół
                page.wait_for_timeout(5000)
                
                # Wykonujemy scroll w dół, żeby dociągnąć czerwiec i lipiec z listy
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(3000)
                
                # Wyciągamy wyrenderowany tekst ze zbudowanej listy
                final_text = page.inner_text("body")
                
                browser.close()
                return final_text
                
        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)
            
    raise Exception("Błąd podczas wymuszania widoku listy.")


notify("🚨 Uruchomiono monitor z wymuszaniem widoku listy (Force List View)...")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Przełączam Reservio na widok listy i skanuję...", flush=True)

        text_data = check_reservio_force_list_view()
        current_state = has_available_place(text_data)

        print(f"[{now}] Wynik analizy: {current_state}", flush=True)

        if current_state != last_state:
            if current_state:
                notify(
                    f"🚨 Reservio: Wykryto wolne miejsca na liście szkoleń!\n\nZapisy: {URL}"
                )
            last_state = current_state

        print(f"[{now}] Cykl zakończony. Zasypiam na {CHECK_EVERY_SECONDS}s.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
