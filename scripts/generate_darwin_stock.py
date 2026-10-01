import json
import os
from datetime import timedelta

from lxml import etree

from generate_home_food_stock import (
    CATALOG_XML_URL,
    PRODUCT_UPDATE_URL,
    api_json,
    download,
    fetch_orders,
    now_kyiv,
)


STATE_FILE = "public/darwin-stock-state.json"
DARWIN_BRANDS = {"ambrosia", "happyone", "exclusion"}
AVAILABLE_STOCK = 2
BOOTSTRAP_ORDER_ID = 2773
WAREHOUSE_VARIABLE = "SALESDRIVE_DARWIN_STOCK_ID"


def clean(value):
    return " ".join(str(value or "").split())


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return state


def numeric_warehouse_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_warehouse_id(state, api_key, product_skus):
    configured = numeric_warehouse_id(
        os.environ.get(WAREHOUSE_VARIABLE, "").strip()
    )
    if configured:
        return configured

    stored = numeric_warehouse_id(
        state.get("warehouse_id") if state else None
    )
    if stored:
        return stored

    finished_at = now_kyiv()
    orders = fetch_orders(
        api_key,
        finished_at - timedelta(days=30),
        finished_at,
    )

    for order in orders:
        if int(order.get("id") or 0) != BOOTSTRAP_ORDER_ID:
            continue

        for item in order.get("products") or []:
            sku = clean(item.get("sku"))
            stock_id = numeric_warehouse_id(item.get("stockId"))

            if sku in product_skus and stock_id:
                return stock_id

    raise RuntimeError(
        "Could not determine Darwin warehouse ID from order #2773. "
        f"Set repository variable {WAREHOUSE_VARIABLE}."
    )


def update_salesdrive_stock(api_key, warehouse_id, stock):
    items = [
        {
            "id": sku,
            "stockBalanceByStock": {
                str(warehouse_id): int(quantity),
            },
        }
        for sku, quantity in sorted(stock.items())
    ]

    for offset in range(0, len(items), 100):
        result = api_json(
            PRODUCT_UPDATE_URL,
            api_key,
            payload={
                "action": "update",
                "product": items[offset:offset + 100],
            },
        )

        if result.get("status") not in (None, "success"):
            raise RuntimeError(
                f"Could not update SalesDrive Darwin stock: {result}"
            )


def save_state(warehouse_id, published_stock):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    temporary = f"{STATE_FILE}.tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            {
                "version": 2,
                "warehouse_id": warehouse_id,
                "available_stock_per_product": AVAILABLE_STOCK,
                "published_stock": dict(sorted(published_stock.items())),
            },
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    os.replace(temporary, STATE_FILE)


def main():
    api_key = os.environ.get("SALESDRIVE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SALESDRIVE_API_KEY is not configured")

    print("Downloading CatPaws catalog for Darwin stock...")
    root = etree.fromstring(download(CATALOG_XML_URL))
    published_stock = {}

    for offer in root.xpath(".//offer"):
        vendor = clean(offer.findtext("vendor")).casefold()

        if vendor not in DARWIN_BRANDS:
            continue

        sku = clean(offer.findtext("vendorCode"))
        if not sku:
            continue

        published_stock[sku] = (
            AVAILABLE_STOCK
            if offer.get("available") == "true"
            else 0
        )

    if len(published_stock) < 100:
        raise RuntimeError(
            "Darwin product list is empty or incomplete: "
            f"only {len(published_stock)} products"
        )

    state = load_state()
    warehouse_id = find_warehouse_id(
        state,
        api_key,
        set(published_stock),
    )

    # Darwin не передає точну кількість. Для товарів, які постачальник
    # позначає доступними, тримаємо обережний залишок 2. Це також
    # виправляє від'ємні та нульові залишки в SalesDrive.
    update_salesdrive_stock(
        api_key,
        warehouse_id,
        published_stock,
    )
    save_state(warehouse_id, published_stock)

    available = sum(quantity > 0 for quantity in published_stock.values())
    unavailable = len(published_stock) - available
    print(f"SalesDrive warehouse ID: {warehouse_id}")
    print(f"Products sent to SalesDrive: {len(published_stock)}")
    print(
        "Darwin stock generated: "
        f"{len(published_stock)} products, "
        f"{available} available x {AVAILABLE_STOCK}, "
        f"{unavailable} unavailable"
    )


if __name__ == "__main__":
    main()
