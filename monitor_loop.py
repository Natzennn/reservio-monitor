from playwright.sync_api import sync_playwright
import requests
import os
import time
import re
from datetime import datetime

# Konfiguracja bota
URL = "https://test1874.reservio.com/events"
CHECK_EVERY_SECONDS = 180  # Sprawdzanie co 3 minuty

# Twoje tokeny sesyjne (wyciągnięte z ciasteczek)
COOKIE_TA = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIzMDM0YTM1Ni1jMTNiLTRiNGEtYmY0Zi1jOGRhMjkwODRiYmYiLCJqdGkiOiIxNGViZWQyOWIxNzI4ZmRhOWQxYTAyZmYxNTcxNzUxNTQ4NWQ1YzRhOWU1MGE5ZmE0ZmY0ZWFiM2ZiYTQwOTkzMGNmM2I4MzM0ZGU3OTI0NiIsImlhdCI6MTc4MDE3MzM1MS40MDQxODYsIm5iZiI6MTc4MDE3MzM1MS40MDQxOTMsImV4cCI6MTc4MDE3Njk1MS4yMTA2MDcsInN1YiI6IjQzNzM2NzgiLCJzY29wZXMiOlsidXNlciIsImNsaWVudCIsImFkbWluIiwibWFya2V0cGxhY2VCb29raW5nUmVxdWVzdCJdfQ.nS5A2ypEH1bgp_9KxaTUTlArIj3CD50yfz2E3h2awP41HzsfwwnAcKB8ZBcEtx8_XscqFvFowdAPX2oVe_CW-c8UAITskyprGK2bz5IZuBsG3NLref3qHlcYvcdWJcEqLNzAAnOEqnbANWaJ9vDWhWZASYalLY3XIDXVrziFTWs"
COOKIE_SID = "id=3805241824052954001|t=1780173349.896|te=1780174530.606|c=09B07B7B019396C25D8E9C64953E8EF3"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

# Przechowujemy poprzedni stan listy, żeby bot nie spamował o tych samych miejscach
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
    """Dzieli tekst strony na bloki przed przyciskami rezerwacji

    i wyciąga pełne informacje (datę, godzinę, nazwę szkolenia).
    """
    found_events = []
    
    # Pobieramy czysty tekst wyrenderowany na całej stronie
    full_text = page.locator("body").inner_text()
    
    # Dzielimy tekst strony przy użyciu słowa 'ZAREZERWUJ' (Twój aktywny przycisk ze screena)
    blocks = full_text.split("ZAREZERWUJ")
    
    if len(blocks) > 1:
        print(f"-> Analiza tekstu: wykryto {len(blocks) - 1} aktywnych sekcji rezerwacji.", flush=True)
        
        # Przechodzimy przez bloki tekstu znajdujące się bezpośrednio PRZED każdym napisem ZAREZERWUJ
        for i in range(len(blocks) - 1):
            current_block = blocks[i]
            
            # Czyścimy z pustych linii
            lines = [line.strip() for line in current_block.split("\n") if line.strip()]
            
            if lines:
                # Wyciągamy ostatnie 4 linie tekstu sprzed przycisku (tam jest data, godzina, nazwa, wolne miejsca)
                useful_lines = lines[-4:] if len(lines) >= 4 else lines
                event_details = " | ".join(useful_lines)
                
                # Dodatkowa walidacja, czy ta sekcja na pewno opisuje wolny termin
                if any(x in event_details.lower() for x in ["wolne", "wolnych", "dostępne"]):
                    found_events.append(event_details)
                    
    # Rezerwowy fallback: gdyby podział po 'ZAREZERWUJ' z jakiegoś powodu nie zadziałał
    if not found_events:
        print("-> Uruchamiam zapasowy skaner linii tekstu...", flush=True)
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        for idx, line in enumerate(lines):
            if any(x in line.lower() for x in ["wolne miejsce", "wolne miejsca", "wolnych miejsc"]):
                # Zgarnia tekst
