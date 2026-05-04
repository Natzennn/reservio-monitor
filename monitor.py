import requests
import hashlib
import os

URL = "https://test1874.reservio.com/events"
STATE_FILE = "hash.txt"

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

def notify(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=20
    )

response = requests.get(URL, timeout=20, headers={
    "User-Agent": "Mozilla/5.0"
})

html = response.text
current_hash = hashlib.sha256(html.encode("utf-8")).hexdigest()

old_hash = None
if os.path.exists(STATE_FILE):
    with open(STATE_FILE, "r") as f:
        old_hash = f.read().strip()

if old_hash and old_hash != current_hash:
    notify("🚨 Zmiana na Reservio! Sprawdź terminy: " + URL)

with open(STATE_FILE, "w") as f:
    f.write(current_hash)

print("Sprawdzono stronę.")
notify("TEST działa 🚀")
