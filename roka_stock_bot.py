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
    {
        "name": "Maverick Comp.3 Wetsuit Open Box",
        "url": "https://rokamultisport.com/products/mens-maverick-comp-3-wetsuit-open-box",
        "variant_id": 50593984250129,
        "size": "L",
        "color": "Cyclone",
    },
    {
        "name": "Maverick Comp.3 Wetsuit Open Box",
        "url": "https://rokamultisport.com/products/mens-maverick-comp-3-wetsuit-open-box",
        "variant_id": 50593984250129,
        "size": "L",
        "color": "Black/Yellow",
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


def _normalized(value):
    return str(value or "").strip().lower()


def _matches_size(variant, size):
    size_aliases = {_normalized(size), "large"}
    values = [
        variant.get("title", ""),
        variant.get("option1", ""),
        variant.get("option2", ""),
        variant.get("option3", ""),
    ]

    for value in values:
        normalized = _normalized(value)
        if normalized in size_aliases:
            return True

        tokens = {
            token.strip().lower()
            for token in normalized.replace("/", "|").replace(",", "|").split("|")
        }
        if size_aliases & tokens:
            return True

    return False


def _matches_color(variant, color):
    if not color:
        return True

    target = _normalized(color)
    values = [
        variant.get("title", ""),
        variant.get("option1", ""),
        variant.get("option2", ""),
        variant.get("option3", ""),
    ]

    for value in values:
        normalized = _normalized(value)
        if normalized == target:
            return True

        # Handles titles such as "Black/Yellow / L".
        if target in {
            token.strip().lower()
            for token in normalized.split(" / ")
        }:
            return True

    return False


def find_variant(product, target_variant_id, size, color=None):
    variants = product.get("variants", [])

    if target_variant_id is not None:
        for variant in variants:
            try:
                if int(variant.get("id")) == int(target_variant_id):
                    if color is None or _matches_color(variant, color):
                        return variant
            except (TypeError, ValueError):
                pass

    for variant in variants:
        if _matches_size(variant, size) and _matches_color(variant, color):
            return variant

    return None


def state_key(product_config):
    if product_config.get("variant_id") is not None:
        return str(product_config["variant_id"])

    return "|".join(
        [
            product_config["url"],
            _normalized(product_config.get("color")),
            _normalized(product_config["size"]),
        ]
    )


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

    color_text = (
        f" in {product_config['color']} color"
        if product_config.get("color")
        else ""
    )

    message = (
        f"🚨 ROKA {product_config['name']} size {product_config['size']}"
        f"{color_text} is AVAILABLE!\n"
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
        product_config.get("variant_id"),
        product_config["size"],
        product_config.get("color"),
    )

    if variant is None:
        color_text = (
            f" in {product_config['color']} color"
            if product_config.get("color")
            else ""
        )
        raise RuntimeError(
            f"Could not find {product_config['name']} size "
            f"{product_config['size']!r}{color_text} variant."
        )

    available = bool(variant.get("available", False))
    key = state_key(product_config)
    previous = previous_states.get(key)

    color_text = (
        f" {product_config['color']}"
        if product_config.get("color")
        else ""
    )

    print(
        f"ROKA {product_config['name']}{color_text} size "
        f"{product_config['size']}: "
        f"{'AVAILABLE' if available else 'sold out'} "
        f"(variant {variant.get('id')}, previous: {previous})"
    )

    if available and previous is False:
        send_discord_alert(product_config, variant)
        print("Discord alert sent.")
    elif available and previous is None:
        print("First run and item is available; state initialized without alert.")

    previous_states[key] = available


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
