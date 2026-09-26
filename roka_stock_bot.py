import json
import os
import sys
from pathlib import Path

import requests

PRODUCTS = [
    {
        "name": "Maverick X-3 Wetsuit Open Box",
        "url": "https://rokamultisport.com/products/mens-maverick-x-3-wetsuit-open-box",
        "variant_id": 50594180366609,
        "size": "L",
    },
    {
        "name": "Maverick Pro-3 Wetsuit",
        "url": "https://rokamultisport.com/collections/outlet-wetsuits/products/mens-maverick-pro-3-wetsuit",
        "variant_id": 49751913890065,
        "size": "L",
    },
]

STATE_FILE = Path("roka_state.json")
TIMEOUT = 20


def fetch_product(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ROKA-Stock-Monitor/1.0)"
    }
    response = requests.get(url + ".js", headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def find_variant(product, target_variant_id, size):
    variants = product.get("variants", [])

    for variant in variants:
        try:
            if int(variant.get("id")) == target_variant_id:
                return variant
        except (TypeError, ValueError):
            pass

    size_aliases = {size.strip().lower(), "large"}
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

            tokens = {
                token.strip().lower()
                for token in normalized.replace("/", "|").replace(",", "|").split("|")
            }
            if size_aliases & tokens:
                return variant

    return None


def load_previous_states():
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if "available" in data:
        return {str(PRODUCTS[0]["variant_id"]): data.get("available")}
    return data if isinstance(data, dict) else {}


def save_states(states):
    STATE_FILE.write_text(json.dumps(states, indent=2) + "\n")


def send_discord_alert(product_config, variant):
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
        f"🚨 ROKA {product_config['name']} size {product_config['size']} is AVAILABLE!\n"
        f"{product_config['url']}\n"
        f"Price: {price if price is not None else 'see site'}"
    )

    response = requests.post(
        webhook,
        json={"content": message},
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def check_product(product_config, previous_states):
    product = fetch_product(product_config["url"])
    variant = find_variant(
        product,
        product_config["variant_id"],
        product_config["size"],
    )

    if variant is None:
        raise RuntimeError(
            f"Could not find {product_config['name']} size "
            f"{product_config['size']!r} variant "
            f"(target variant ID {product_config['variant_id']})."
        )

    available = bool(variant.get("available", False))
    state_key = str(product_config["variant_id"])
    previous = previous_states.get(state_key)

    print(
        f"ROKA {product_config['name']} size {product_config['size']}: "
        f"{'AVAILABLE' if available else 'sold out'} "
        f"(variant {variant.get('id')}, previous: {previous})"
    )

    if available and previous is False:
        send_discord_alert(product_config, variant)
        print("Discord alert sent.")
    elif available and previous is None:
        print("First run and item is available; state initialized without alert.")

    previous_states[state_key] = available


def main():
    previous_states = load_previous_states()

    for product_config in PRODUCTS:
        try:
            check_product(product_config, previous_states)
        except Exception as exc:
            print(
                f"Monitor failed for {product_config['name']}: {exc}",
                file=sys.stderr,
            )

    save_states(previous_states)


if __name__ == "__main__":
    main()
