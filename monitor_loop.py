from playwright.sync_api import sync_playwright
import requests
import os
import time
import json
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Przechowujemy stan jako zestaw unikalnych ID wolnych terminów
last_available_event_ids = set()


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


def check_entire_calendar():
    """Wchodzi na stronę i przechwytuje ukryty pakiet danych (JSON) zawierający

    wszystkie wydarzenia z kalendarza na wiele miesięcy w przód.
    """
    found_free_places = False
    current_free_ids = set()
    alert_messages = []

    for attempt in range(3):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
                )
                page = browser.new_page()

                # Zmienna do zapisu surowych danych z kalendarza
                calendar_data = None

                # Funkcja pomocnicza wychwytująca paczkę danych sieciowych z Reservio
                def handle_response(response):
                    nonlocal calendar_data
                    # Szukamy odpowiedzi sieciowej, która zawiera dane o wydarzeniach (events)
                    if "events" in response.url and response.status == 200:
                        try:
                            calendar_data = response.json()
                        except:
                            pass

                # Rejestrujemy nasłuchiwanie sieci
                page.on("response", handle_response)

                # Wchodzimy na stronę
                page.goto(URL, wait_until="commit", timeout=60000)
                page.wait_for_timeout(8000)  # Czekamy aż pobierze kalendarz w tle

                browser.close()

                # --- ANALIZA CAŁEGO KALENDARZA ---
                if calendar_data:
                    # Wyciągamy listę wszystkich nadchodzących wydarzeń wykrytych w systemie
                    events = calendar_data.get("data", calendar_data.get("events", []))
                    if isinstance(calendar_data, dict) and "props" in calendar_data:
                        # Rezerwowy krok na wypadek, gdyby dane były zaszyte w Next.js state
                        try:
                            events = calendar_data["props"]["pageProps"]["initialState"]["events"]["items"]
                        except:
                            pass

                    # Jeśli struktura to czysta lista lub słownik - szukamy wolnych miejsc
                    # Przeszukujemy KAŻDE wydarzenie bez względu na to, w jakim jest tygodniu
                    for event in events:
                        if isinstance(event, dict):
                            name = event.get("name", "Trening")
                            start_time = event.get("start", event.get("dateTimeFrom", ""))
                            
                            # Pobieramy limity miejsc
                            bookings_count = event.get("bookingsCount", 0)
                            capacity = event.get("capacity", 0)
                            
                            # Obliczamy wolne miejsca
                            free_spots = capacity - bookings_count
                            event_id = event.get("id", f"{name}_{start_time}")

                            if free_spots > 0:
                                current_free_ids.add(event_id)
                                # Formatujemy ładną datę, jeśli istnieje
                                try:
                                    date_obj = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                                    formatted_date = date_obj.strftime("%d.%m.%Y o %H:%M")
                                except:
                                    formatted_date = start_time

                                alert_messages.append(f"🎯 *{name}*\n📅 Data: {formatted_date}\n🔥 Wolne miejsca: *{free_spots}*")

                    return current_free_ids, alert_messages
                else:
                    # Jeśli API nie odpowiedziało wprost, sprawdzamy też klasyczny tekst całej strony
                    # jako tryb awaryjny (zabezpieczenie)
                    page_text = page.inner_text("body").lower()
                    if any(x in page_text for x in ["miejsce dostępne", "miejsca dostępne", "miejsc dostępnych"]):
                        # Zwracamy sztuczne ID, żeby odpalić ogólny alert
                        return {"fallback_trigger"}, ["🚨 Wykryto wolne miejsca gdzieś na stronie kalendarza!"]
                    
                    return set(), []

        except Exception as e:
            print(f"Próba {attempt + 1} nieudana: {e}", flush=True)
            time.sleep(5)

    print("Nie udało się pobrać danych kalendarza po 3 próbach.", flush=True)
    return set(), []


notify("🚀 Zaawansowany monitor CAŁEGO kalendarza Reservio został uruchomiony.")

while True:
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{now}] Przeszukuję cały kalendarz w tle...", flush=True)

        current_free_ids, alerts = check_entire_calendar()

        # Sprawdzamy czy pojawiły się NOWE wolne terminy, których nie widzieliśmy wcześniej
        new_events = current_free_ids - last_available_event_ids

        if new_events and alerts:
            print(f"[{now}] Wykryto NOWE wolne miejsca!", flush=True)
            full_alert_text = "🚨 *RESERVIO: WYKRYTO WOLNE MIEJSCA!*\n\n" + "\n\n".join(alerts) + f"\n\n🔗 Zapisy: {URL}"
            notify(full_alert_text)
        else:
            print(f"[{now}] Brak nowych wolnych terminów w całym kalendarzu.", flush=True)

        # Aktualizujemy listę zapamiętanych wolnych miejsc
        last_available_event_ids = current_free_ids

    except Exception as e:
        print(f"Błąd pętli głównej: {e}", flush=True)

    time.sleep(CHECK_EVERY_SECONDS)
