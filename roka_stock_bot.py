import json
import os
import sys
from pathlib import Path

import requests

PRODUCT_URL = "https://rokamultisport.com/products/mens-maverick-x-3-wetsuit-open-box"
PRODUCT_JSON_URL = PRODUCT_URL + ".js"

# Exact variant from the product URL the user provided.
TARGET_VARIANT_ID = 50594180366609
SIZE_TO_WATCH = "L"

STATE_FILE = Path("roka_state.json")
TIMEOUT = 20


def fetch_product():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ROKA-Stock-Monitor/1.0)"
    }
    response = requests.get(PRODUCT_JSON_URL, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def find_variant(product):
    variants = product.get("variants", [])

    # Prefer the exact variant ID from the user's ROKA product URL.
    for variant in variants:
        try:
            if int(variant.get("id")) == TARGET_VARIANT_ID:
                return variant
        except (TypeError, ValueError):
            pass

    # Fallback in case ROKA changes the variant ID.
    size_aliases = {"l", "large"}
    for variant in variants:
        values = [
            variant.get("title", ""),
            variant.get("option1", ""),
            variant.get("option2", ""),
            variant.get("option3", ""),
        ]
        for value in values:
            normalized = str(value).strip().lower()
            if normalized in size_aliases:
                return variant

            # Also handle labels such as "Black / L" or "Size: L".
            tokens = {
                token.strip().lower()
                for token in normalized.replace("/", "|").replace(",", "|").split("|")
            }
            if size_aliases & tokens:
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
    STATE_FILE.write_text(
        json.dumps({"available": bool(available)}, indent=2) + "\n"
    )


def send_discord_alert(variant):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set; cannot send the stock alert."
        )

    price = variant.get("price")
    if price is not None:
        try:
            price = "$" + f"{int(price) / 100:.2f}"
        except (ValueError, TypeError):
            pass

    message = (
        f"🚨 ROKA size {SIZE_TO_WATCH} is AVAILABLE!\n"
        f"{PRODUCT_URL}\n"
        f"Price: {price if price is not None else 'see site'}"
    )

    response = requests.post(
        webhook,
        json={"content": message},
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def main():
    product = fetch_product()
    variant = find_variant(product)

    if variant is None:
        raise RuntimeError(
            f"Could not find the ROKA size {SIZE_TO_WATCH!r} variant "
            f"(target variant ID {TARGET_VARIANT_ID})."
        )

    available = bool(variant.get("available", False))
    previous = load_previous_state()

    print(
        f"ROKA {SIZE_TO_WATCH}: "
        f"{'AVAILABLE' if available else 'sold out'} "
        f"(variant {variant.get('id')}, previous: {previous})"
    )

    if available and previous is False:
        send_discord_alert(variant)
        print("Discord alert sent.")
    elif available and previous is None:
        print("First run and item is available; state initialized without alert.")

    save_state(available)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Monitor failed: {exc}", file=sys.stderr)
        raise
