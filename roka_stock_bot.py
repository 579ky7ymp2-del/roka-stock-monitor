import json
import os
import sys
from pathlib import Path

import requests

PRODUCT_URL = "https://rokamultisport.com/products/mens-maverick-x-3-wetsuit-open-box"
PRODUCT_JSON_URL = PRODUCT_URL + ".js"
SIZE_TO_WATCH = "L"
STATE_FILE = Path("roka_state.json")
TIMEOUT = 20

def fetch_product():
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ROKA-Stock-Monitor/1.0)"}
    response = requests.get(PRODUCT_JSON_URL, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()

def find_variant(product):
    target = SIZE_TO_WATCH.strip().lower()
    for variant in product.get("variants", []):
        values = [variant.get("title", ""), variant.get("option1", ""), variant.get("option2", ""), variant.get("option3", "")]
        if any(str(value).strip().lower() == target for value in values):
            return variant
    return None

def load_previous_state():
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text()).get("available")
    except (OSError, json.JSONDecodeError):
        return None

def save_state(available):
    STATE_FILE.write_text(json.dumps({"available": bool(available)}, indent=2) + "\n")

def send_discord_alert(variant):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        print("DISCORD_WEBHOOK_URL is not set; skipping notification.")
        return False
    price = variant.get("price")
    if price is not None:
        try:
            price = f"${int(price) / 100:.2f}"
        except (ValueError, TypeError):
            pass
    message = f"🚨 ROKA size {SIZE_TO_WATCH} is AVAILABLE!\n{PRODUCT_URL}\nPrice: {price if price is not None else 'see site'}"
    response = requests.post(webhook, json={"content": message}, timeout=TIMEOUT)
    response.raise_for_status()
    return True

def main():
    product = fetch_product()
    variant = find_variant(product)
    if variant is None:
        raise RuntimeError(f"Could not find a variant matching size {SIZE_TO_WATCH!r}.")
    available = bool(variant.get("available", False))
    previous = load_previous_state()
    print(f"ROKA {SIZE_TO_WATCH}: {'AVAILABLE' if available else 'sold out'} (previous: {previous})")
    if available and previous is False:
        send_discord_alert(variant)
    elif available and previous is None:
        print("First run and item is available; state initialized without alert.")
    save_state(available)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        raise
