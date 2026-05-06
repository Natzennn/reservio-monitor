import requests
import os
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin

OLX_URL = "https://www.olx.pl/praca/finanse-ksiegowosc/warszawa/?search%5Bdist%5D=30"
CHECK_EVERY_SECONDS = 60

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )

def get_offers():
    response = requests.get(
        OLX_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )

    soup = BeautifulSoup(response.text, "html.parser")
    offers = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(" ", strip=True)

        if "/oferta/" in href and title:
            link = urljoin("https://www.olx.pl", href)
            offers.append((title, link))

    unique = []
    seen = set()

    for title, link in offers:
        if link not in seen:
            seen.add(link)
            unique.append((title, link))

    return unique[:30]

notify("✅ Monitor OLX uruchomiony.")

known_links = set(link for _, link in get_offers())

while True:
    try:
        offers = get_offers()

        for title, link in reversed(offers):
            if link not in known_links:
                known_links.add(link)
                notify(f"🆕 Nowa oferta pracy OLX:\n{title}\n{link}")

        print("Sprawdzono OLX.")

    except Exception as e:
        print("Błąd OLX:", e)

    time.sleep(CHECK_EVERY_SECONDS)
