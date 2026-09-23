import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from lxml import etree


XML_URL = "https://catpaws.com.ua/content/export/3e9c244f28ee6d1e572f92646e76f6bb.xml"

# Попередній опублікований прайс Mono.
# Workflow завантажує його перед запуском цього скрипта.
PREVIOUS_FEED_FILE = "previous-offers-response.json"

SUPPLIER_STOCK = 999
DEFAULT_WAREHOUSE_ID = "SUPPLIER"
MIN_PRICE = 300

STOCK_SOURCES = (
    {
        "name": "HOME FOOD",
        "warehouse_id": "HOME_FOOD",
        "state_file": "public/home-food-stock-state.json",
        "dispatch_days": {0, 1, 2, 3, 4},
        "cutoff_hour": 12,
        "cutoff_minute": 0,
    },
    {
        "name": "Kormax",
        "warehouse_id": "KORMAX",
        "state_file": "public/kormax-stock-state.json",
        "dispatch_days": {0, 1, 2, 3, 4},
        "cutoff_hour": 12,
        "cutoff_minute": 0,
    },
    {
        "name": "DOMS",
        "warehouse_id": "DOMS",
        "state_file": "public/doms-stock-state.json",
        "dispatch_days": {0, 2, 4},
        "cutoff_hour": 15,
        "cutoff_minute": 30,
    },
    {
        "name": "PETIMPEX",
        "warehouse_id": "PETIMPEX",
        "state_file": "public/petimpex-stock-state.json",
        "dispatch_days": {0, 1, 2, 3, 4},
        "cutoff_hour": 12,
        "cutoff_minute": 0,
    },
)


def to_int(value, default=0):
    if value is None:
        return default

    value = str(value).strip()

    if value == "":
        return default

    try:
        return int(float(value))
    except ValueError:
        return default


def get_days_to_dispatch(
    dispatch_days=None,
    cutoff_hour=12,
    cutoff_minute=0,
):
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    allowed_days = dispatch_days or {0, 1, 2, 3, 4}
    before_cutoff = (now.hour, now.minute) < (
        cutoff_hour,
        cutoff_minute,
    )

    for days_ahead in range(8):
        candidate_weekday = (now.weekday() + days_ahead) % 7

        if candidate_weekday not in allowed_days:
            continue

        if days_ahead == 0 and not before_cutoff:
            continue

        return days_ahead

    return 7


def previous_source_stock(previous_feed, warehouse_id):
    result = {}

    if not previous_feed:
        return result

    for item in previous_feed.get("data") or []:
        code = str(item.get("code") or "").strip()

        if not code:
            continue

        for warehouse in item.get("warehouses") or []:
            if str(warehouse.get("id") or "") != warehouse_id:
                continue

            result[code] = max(0, to_int(warehouse.get("stock")))
            break

    return result


def load_stock_sources(previous_feed):
    stock_by_sku = {}

    for source in STOCK_SOURCES:
        state_file = source["state_file"]

        published_stock = None
        try:
            with open(state_file, "r", encoding="utf-8") as file:
                state = json.load(file)
            published_stock = state.get("published_stock")
        except (OSError, json.JSONDecodeError):
            pass

        if not isinstance(published_stock, dict) or not published_stock:
            published_stock = previous_source_stock(
                previous_feed,
                source["warehouse_id"],
            )

            if not published_stock:
                raise RuntimeError(
                    f'{source["name"]} stock is unavailable in both '
                    f'{state_file} and the previous Mono feed'
                )

            print(
                f'{source["name"]} state is unavailable. '
                'Keeping stock from the previous Mono feed.'
            )

        loaded = 0

        for sku, quantity in published_stock.items():
            normalized_sku = str(sku).strip()

            if not normalized_sku:
                continue

            if normalized_sku in stock_by_sku:
                previous = stock_by_sku[normalized_sku]
                raise RuntimeError(
                    f'Duplicate warehouse mapping for SKU '
                    f'{normalized_sku}: {previous["name"]} and '
                    f'{source["name"]}'
                )

            stock_by_sku[normalized_sku] = {
                **source,
                "stock": max(0, to_int(quantity)),
            }
            loaded += 1

        print(
            f'{source["name"]} stock loaded: '
            f'{loaded} products -> {source["warehouse_id"]}'
        )

    return stock_by_sku


def build_offer(offer, stock_by_sku):
    code = offer.findtext("vendorCode")

    if not code:
        return None

    price = to_int(offer.findtext("price"))

    price_allowed = price > MIN_PRICE
    site_available = offer.get("available") == "true"
    normalized_code = code.strip()
    stock_source = stock_by_sku.get(normalized_code)

    if stock_source:
        # Для підключених складів джерелом наявності є складський стан,
        # а не ознака available із сайту, яка може оновитися пізніше.
        stock = stock_source["stock"] if price_allowed else 0
        warehouse_id = stock_source["warehouse_id"]
        days_to_dispatch = get_days_to_dispatch(
            stock_source["dispatch_days"],
            stock_source["cutoff_hour"],
            stock_source["cutoff_minute"],
        )
    else:
        stock = (
            SUPPLIER_STOCK
            if site_available and price_allowed
            else 0
        )
        warehouse_id = DEFAULT_WAREHOUSE_ID
        days_to_dispatch = get_days_to_dispatch()

    available = stock > 0

    old_price_text = offer.findtext("oldprice")

    old_price = (
        to_int(old_price_text, None)
        if old_price_text
        else None
    )

    return {
        "code": normalized_code,
        "price": price,
        "old_price": old_price,
        "availability": available,
        "stock": stock,
        "warehouses": [
            {
                "id": warehouse_id,
                "stock": stock
            }
        ],
        "warranty_type": "no",
        "warranty_period": 0,
        "max_pay_in_parts": 6,
        "days_to_dispatch": days_to_dispatch,
        "delivery_methods": [
            {
                "method": "nova-post:branch",
                "price": 0
            },
            {
                "method": "courier:nova-post",
                "price": 0
            }
        ],
        "manufacture": None
    }


def stock_snapshot(offers):
    """
    Формуємо знімок тільки складських даних.

    Ціна, old_price, days_to_dispatch та інші поля
    НЕ впливають на updatedAt.
    """

    snapshot = {}

    for item in offers:
        code = item.get("code")

        if not code:
            continue

        warehouses = item.get("warehouses") or []

        warehouse_stock = {}

        for warehouse in warehouses:
            warehouse_id = str(
                warehouse.get("id", "")
            )

            warehouse_stock[warehouse_id] = (
                warehouse.get("stock", 0)
            )

        snapshot[code] = {
            "availability": item.get(
                "availability",
                False
            ),
            "stock": item.get("stock", 0),
            "warehouses": warehouse_stock,
"days_to_dispatch": item.get(
    "days_to_dispatch",
    0
)
        }

    return snapshot


def load_previous_feed():
    if not os.path.exists(PREVIOUS_FEED_FILE):
        print(
            "Previous feed not found. "
            "updatedAt will be set to current time."
        )
        return None

    try:
        with open(
            PREVIOUS_FEED_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except Exception as error:
        print(
            "Could not read previous feed:",
            error
        )
        return None


def get_updated_at(new_offers, previous_feed):
    now = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    if not previous_feed:
        print(
            "No previous feed. "
            "Using new updatedAt:",
            now
        )
        return now

    previous_updated_at = previous_feed.get(
        "updatedAt"
    )

    previous_offers = previous_feed.get(
        "data",
        []
    )

    old_stock = stock_snapshot(
        previous_offers
    )

    new_stock = stock_snapshot(
        new_offers
    )

    if old_stock == new_stock:
        if previous_updated_at:
            print(
                "Stock unchanged. "
                "Keeping updatedAt:",
                previous_updated_at
            )

            return previous_updated_at

    print(
        "Stock changed. "
        "New updatedAt:",
        now
    )

    return now


def main():
    print("Downloading XML...")

    response = requests.get(
        XML_URL,
        timeout=120
    )

    response.raise_for_status()

    root = etree.fromstring(
        response.content
    )

    previous_feed = load_previous_feed()
    stock_by_sku = load_stock_sources(previous_feed)

    offers = []

    for offer in root.xpath(".//offer"):
        item = build_offer(offer, stock_by_sku)

        if item is not None:
            offers.append(item)

    updated_at = get_updated_at(
        offers,
        previous_feed
    )

    result = {
        "updatedAt": updated_at,
        "total": len(offers),
        "data": offers
    }

    os.makedirs(
        "public",
        exist_ok=True
    )

    with open(
        "public/offers-response.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        f"Done: {len(offers)} offers"
    )

    print(
        f"updatedAt: {updated_at}"
    )


if __name__ == "__main__":
    main()
