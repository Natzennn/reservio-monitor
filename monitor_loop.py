from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota (powrót do Reservio)
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

last_alert = None


def notify(text):
    """Wysyła powiadomienie na Telegram z obsługą błędów."""
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=20,
        )
    except Exception as e:
        print(f"Błąd Telegram: {e}", flush=True)


def check_reservio_like_velo():
    """Uruchamia czystą sesję przeglądarki o wysokiej rozdzielczości,

    czeka na stabilne załadowanie widżetów Reservio i szuka jakichkolwiek wolnych terminów.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )

        # Tworzymy duży ekran (FullHD), żeby Reservio załadowało pełny widok z kalendarzem bocznym
        page = browser.new_page(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Odpowiednik wait_until="networkidle" z Veloart - czekamy na załadowanie skryptów w tle
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(8000)  # Dodatkowe sekundy na stabilizację React/Next.js

        # Akceptujemy "Rozumiem" lub politykę prywatności, jeśli zasłania ekran (jak w Veloart)
        try:
            page.get_by_text("Rozumiem").click(timeout=3000)
        except Exception:
            pass

        # Pobieramy pełny tekst wyrenderowany na ekranie (widok listy/kalendarza)
        text = page.locator("body").inner_text()
        browser.close()

        # Szukamy JAKIEGOKOLWIEK śladu wolnego miejsca (na podstawie Twoich 3 screenów)
        # Szukamy: "X wolne miejsce", "X wolne miejsca", "X wolnych miejsc", "X miejsce dostępne" lub przycisku "ZAREZERWUJ"
        match = re.search(
            r"(\d+\s+(wolne miejsce|wolne miejsca|wolnych miejsc|miejsce dostępne|miejsca dostępne))|zarezerwuj",
            text.lower()
        )

        if match:
            # Wyciągamy fragment tekstu wokół znalezionego miejsca, żeby wiedzieć co to za termin
            matched_text = match.group(0)
            return True, matched_text
        
        return False, None


# Start bota
notify("✅ Monitor Reservio (Logika Veloart) został uruchomiony. Szukam wolnych miejsc...")
print("Start Reservio-Velo monitora.", flush=True)

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Sprawdzam Reservio logiką Veloart...", flush=True)

        found_spots, details = check_reservio_like_velo()

        if found_spots:
            print(f"[{now}] SUKCES! Znaleziono wolne miejsca: {details}", flush=True)
            
            # Zapobiegamy powtarzaniu tego samego alertu co 3 minuty
            if details != last_alert:
                notify(
                    "🚨 *RESERVIO: POJAWIŁO SIĘ WOLNE MIEJSCE!*\n\n"
                    f"💬 Komunikat z systemu: *{details}*\n"
                    "Złapano wolny termin w kalendarzu bocznum lub na liście.\n\n"
                    f"🔗 Rezerwuj szybko tutaj: {URL}"
                )
                last_alert = details
        else:
            print(f"[{now}] Brak wolnych miejsc w tym cyklu. Kalendarz jest pełny.", flush=True)

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    print(f"Zasypiam na {CHECK_EVERY_SECONDS} sekund...", flush=True)
    time.sleep(CHECK_EVERY_SECONDS)
