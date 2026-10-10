import json
import os
import sys
import time
from datetime import datetime, timezone
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
        "name": "Maverick Pro.3 Wetsuit Open Box",
        "url": "https://rokamultisport.com/products/mens-maverick-pro-3-wetsuit-open-box",
        "variant_id": 50594096251153,
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
        "variant_id": 53122830762257,
        "size": "L",
        "color": "Black/Yellow",
    },
    {
        "name": "Maverick Comp.3 Wetsuit",
        "url": "https://rokamultisport.com/collections/all-mens-products/products/mens-maverick-comp-3-wetsuit",
        "variant_id": 51749635981585,
        "size": "L",
        "color": "Black/Yellow",
    },
]

STATE_FILE = Path("roka_state.json")
HISTORY_FILE = Path("roka_history.jsonl")
PRICE_STATE_FILE = Path("roka_price_state.json")
PRICE_WATCH = {
    "name": "Maverick Comp.3 Wetsuit",
    "url": "https://rokamultisport.com/collections/bestsellers/products/mens-maverick-comp-3-wetsuit",
    "variant_id": 51749635784977,
}
TIMEOUT = 20
MAX_REQUEST_ATTEMPTS = 3
RETRY_DELAYS = (2, 5)
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def fetch_product(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ROKA-Stock-Monitor/1.0)"
    }

    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        try:
            response = requests.get(
                url + ".js",
                headers=headers,
                timeout=TIMEOUT,
            )

            if response.status_code in RETRYABLE_STATUS_CODES:
                if attempt < MAX_REQUEST_ATTEMPTS:
                    delay = RETRY_DELAYS[attempt - 1]
                    print(
                        f"ROKA returned HTTP {response.status_code}; "
                        f"retrying in {delay}s "
                        f"(attempt {attempt}/{MAX_REQUEST_ATTEMPTS})."
                    )
                    time.sleep(delay)
                    continue

            response.raise_for_status()
            return response.json()

        except requests.RequestException as exc:
            if attempt >= MAX_REQUEST_ATTEMPTS:
                raise

            delay = RETRY_DELAYS[attempt - 1]
            print(
                f"ROKA request failed: {exc}; retrying in {delay}s "
                f"(attempt {attempt}/{MAX_REQUEST_ATTEMPTS})."
            )
            time.sleep(delay)

    raise RuntimeError("ROKA product request failed after all retry attempts.")



def fetch_rei_page(product_config):
    """Fetch an REI product page with a normal browser-like session."""
    # REI blocks generic Python HTTP clients with HTTP 403. Use a persistent
    # session, normal Chrome headers, and a first visit to the REI homepage so
    # the request looks more like a regular browser navigation.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.rei.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    session = requests.Session()
    session.headers.update(headers)

    # Establish the normal REI session/cookies first.
    home = session.get("https://www.rei.com/", timeout=TIMEOUT)
    if home.status_code == 403:
        raise RuntimeError("REI blocked the monitor with HTTP 403 on the homepage.")

    response = session.get(
        product_config["url"],
        params={"sku": product_config["sku"]},
        timeout=TIMEOUT,
    )

    if response.status_code == 403:
        raise RuntimeError(
            "REI blocked the monitor with HTTP 403. "
            "The product page cannot be checked from this GitHub Actions runner."
        )

    response.raise_for_status()
    return response.text


def check_rei_product(product_config, previous_states):
    """Monitor an REI SKU for online availability.

    REI does not expose a public read inventory API. The SKU-specific product
    page is used as the source of truth for shipping availability. Store
    pickup is location-specific on REI and requires a selected store, so this
    tracker does not guess a store.
    """
    html = fetch_rei_page(product_config)
    text = html.lower()

    # The SKU query selects the requested variant. Treat explicit sold-out
    # language as unavailable; otherwise require a purchasable/add-to-cart
    # signal before alerting.
    sku = product_config["sku"].lower()
    if sku not in text:
        raise RuntimeError(f"REI SKU {product_config['sku']} was not present in the response.")

    sold_out_markers = (
        "sold out",
        "out of stock",
        "currently unavailable",
    )
    purchase_markers = (
        "add to cart",
        "add to bag",
        "buy now",
    )

    available = not any(marker in text for marker in sold_out_markers) and any(
        marker in text for marker in purchase_markers
    )

    key = "rei|" + product_config["sku"]
    previous = previous_states.get(key)

    print(
        f"REI {product_config['name']} {product_config['color']} "
        f"{product_config['size']}: "
        f"{'AVAILABLE' if available else 'sold out/unavailable'} "
        f"(previous: {previous})"
    )

    if available and previous is False:
        send_rei_discord_alert(product_config)
        print("Discord alert sent.")

    if previous is None or previous != available:
        record = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "name": product_config["name"],
            "url": product_config["url"],
            "sku": product_config["sku"],
            "size": product_config["size"],
            "color": product_config["color"],
            "available": available,
            "previous_available": previous,
        }
        with HISTORY_FILE.open("a", encoding="utf-8") as history:
            history.write(json.dumps(record, separators=(",", ":")) + "\n")

    previous_states[key] = available


def send_rei_discord_alert(product_config):
    message = (
        f"🚨 REI {product_config['name']} is AVAILABLE!\n"
        f"Size: {product_config['size']}\n"
        f"Color: {product_config['color']}\n"
        f"SKU: {product_config['sku']}\n"
        f"{product_config['url']}?sku={product_config['sku']}\n"
        f"Shipping availability detected. Check REI for pickup at your selected store."
    )
    send_discord_message(message)


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
                    if _matches_size(variant, size) and _matches_color(variant, color):
                        return variant
            except (TypeError, ValueError):
                pass

    for variant in variants:
        if _matches_size(variant, size) and _matches_color(variant, color):
            return variant

    return None


def state_key(product_config):
    # Color-specific trackers must have separate keys even when Shopify gives
    # them the same variant ID in the supplied product data.
    if product_config.get("color"):
        return "|".join(
            [
                product_config["url"],
                _normalized(product_config.get("color")),
                _normalized(product_config.get("size")),
            ]
        )

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


def append_history(product_config, variant, available, previous):
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "name": product_config["name"],
        "url": product_config["url"],
        "size": product_config["size"],
        "color": product_config.get("color"),
        "variant_id": variant.get("id"),
        "available": available,
        "previous_available": previous,
        "price": variant.get("price"),
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as history:
        history.write(json.dumps(record, separators=(",", ":")) + "\n")


def send_discord_message(message):
    webhook = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set; cannot send the Discord message."
        )

    response = requests.post(
        webhook,
        json={"content": message},
        timeout=TIMEOUT,
    )
    response.raise_for_status()


def send_discord_alert(product_config, variant):
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

    send_discord_message(message)


def send_failure_alert(product_config, error):
    color_text = (
        f" in {product_config['color']} color"
        if product_config.get("color")
        else ""
    )
    message = (
        f"⚠️ ROKA STOCK MONITOR FAILED\n"
        f"Product: {product_config['name']} size {product_config['size']}{color_text}\n"
        f"Error: {error}\n"
        f"URL: {product_config['url']}\n"
        f"The bot may not be checking this item correctly."
    )
    send_discord_message(message)


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

    # Record the initial observation and every subsequent availability change.
    # This gives us a compact historical timeline without writing a row every
    # five minutes (which would make the Git repository unnecessarily large).
    if previous is None or previous != available:
        append_history(product_config, variant, available, previous)
        if previous is None:
            print("Initial stock state recorded in history.")
        else:
            print("Stock state change recorded in history.")

    previous_states[key] = available


def check_price_drop():
    """Track this exact Shopify variant and alert when its price decreases."""
    product = fetch_product(PRICE_WATCH["url"])
    variant = next(
        (
            item for item in product.get("variants", [])
            if str(item.get("id")) == str(PRICE_WATCH["variant_id"])
        ),
        None,
    )
    if variant is None:
        raise RuntimeError(
            f"Could not find price-watch variant {PRICE_WATCH['variant_id']}."
        )

    try:
        current_price = int(variant["price"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Price-watch variant returned an invalid price.")

    try:
        price_state = json.loads(PRICE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        price_state = {}

    previous_price = price_state.get(str(PRICE_WATCH["variant_id"]))
    if previous_price is not None:
        try:
            previous_price = int(previous_price)
        except (TypeError, ValueError):
            previous_price = None

    print(
        f"ROKA price watch {PRICE_WATCH['name']}: "
        f"${current_price / 100:.2f} "
        f"(previous: "
        f"${previous_price / 100:.2f}" if previous_price is not None
        else f"ROKA price watch {PRICE_WATCH['name']}: "
             f"${current_price / 100:.2f} (baseline)"
    )

    if previous_price is not None and current_price < previous_price:
        message = (
            f"💸 ROKA PRICE DROP: {PRICE_WATCH['name']}!\n"
            f"Price decreased from ${previous_price / 100:.2f} "
            f"to ${current_price / 100:.2f}.\n"
            f"{PRICE_WATCH['url']}?variant={PRICE_WATCH['variant_id']}"
        )
        send_discord_message(message)
        print("Price-drop Discord alert sent.")

    PRICE_STATE_FILE.write_text(
        json.dumps({str(PRICE_WATCH["variant_id"]): current_price}, indent=2) + "\n"
    )


def main():
    previous_states = load_previous_states()
    failures = []

    for product_config in PRODUCTS:
        try:
            check_product(product_config, previous_states)
        except Exception as exc:
            print(
                f"Monitor failed for {product_config['name']}: {exc}",
                file=sys.stderr,
            )
            failures.append((product_config, exc))
            try:
                send_failure_alert(product_config, exc)
                print("Failure alert sent.")
            except Exception as alert_exc:
                print(
                    f"Could not send failure alert: {alert_exc}",
                    file=sys.stderr,
                )

    try:
        check_price_drop()
    except Exception as exc:
        print(f"Price monitor failed: {exc}", file=sys.stderr)
        try:
            send_discord_message(
                f"⚠️ ROKA PRICE MONITOR FAILED\nError: {exc}\n"
                f"URL: {PRICE_WATCH['url']}"
            )
        except Exception as alert_exc:
            print(f"Could not send price failure alert: {alert_exc}", file=sys.stderr)
        failures.append((PRICE_WATCH, exc))

    save_states(previous_states)

    if failures:
        raise RuntimeError(
            f"{len(failures)} product monitor(s) failed."
        )


if __name__ == "__main__":
    main()
