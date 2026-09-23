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


PETIMPEX_XML_URL = (
    "https://files.petimpex.com/shimanskay/Shimanskaya.xml.yml"
)
TRACKED_SKUS_FILE = "data/petimpex-skus.txt"
OUTPUT_FILE = "public/petimpex-stock.yml"
STATE_FILE = "public/petimpex-stock-state.json"

BOOTSTRAP_ORDER_ID = 2649
BOOTSTRAP_SKU = "НФ-00005773"
WAREHOUSE_VARIABLE = "SALESDRIVE_PETIMPEX_STOCK_ID"

MIN_SUPPLIER_OFFERS = 1000
MIN_TRACKED_PRODUCTS = 500


def clean(value):
    return " ".join(str(value or "").split())


def parse_quantity(value):
    text = clean(value).replace(",", ".")
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def load_supplier_feed():
    root = etree.fromstring(download(PETIMPEX_XML_URL))
    products = {}

    for offer in root.xpath(".//offer"):
        sku = clean(offer.get("id"))
        if not sku:
            continue

        products[sku] = {
            "name": clean(offer.findtext("name_ua") or offer.findtext("name")),
            "stock": parse_quantity(offer.findtext("quantity_in_stock")),
        }

    if len(products) < MIN_SUPPLIER_OFFERS:
        raise RuntimeError(
            "PETIMPEX feed is empty or incomplete: "
            f"only {len(products)} offers"
        )

    return products, clean(root.get("date"))


def load_tracked_skus():
    try:
        with open(TRACKED_SKUS_FILE, "r", encoding="utf-8") as file:
            skus = {
                line.strip()
                for line in file
                if line.strip() and not line.lstrip().startswith("#")
            }
    except OSError as error:
        raise RuntimeError(
            f"Could not read {TRACKED_SKUS_FILE}"
        ) from error

    if len(skus) < MIN_TRACKED_PRODUCTS:
        raise RuntimeError(
            "PETIMPEX tracked SKU list is incomplete: "
            f"only {len(skus)} products"
        )

    return skus


def load_site_catalog():
    root = etree.fromstring(download(CATALOG_XML_URL))
    result = {}

    for offer in root.xpath(".//offer"):
        sku = clean(offer.findtext("vendorCode"))
        name = clean(offer.findtext("name"))
        if sku:
            result[sku] = name or sku

    return result


def select_products(supplier, tracked_skus, site_catalog):
    # The static list contains products confirmed in the full CatPaws export,
    # including cards that are currently unavailable and therefore absent from
    # the public site XML. Current site products are added automatically so new
    # PETIMPEX cards start syncing without waiting for a manual list refresh.
    known_skus = set(tracked_skus)
    known_skus.update(set(site_catalog) & set(supplier))

    products = {}
    for sku in known_skus:
        supplier_item = supplier.get(sku)
        products[sku] = {
            "name": (
                (supplier_item or {}).get("name")
                or site_catalog.get(sku)
                or sku
            ),
            # A previously tracked item missing from the current supplier feed
            # must be set to zero instead of keeping a stale positive balance.
            "stock": int((supplier_item or {}).get("stock", 0)),
        }

    return products


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    return state if state.get("version") == 1 else None


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    temporary = f"{STATE_FILE}.tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")

    os.replace(temporary, STATE_FILE)


def find_warehouse_id(api_key, state):
    configured = os.environ.get(WAREHOUSE_VARIABLE, "").strip()
    if configured:
        return int(configured)

    if state and state.get("warehouse_id"):
        return int(state["warehouse_id"])

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
            if clean(item.get("sku")) != BOOTSTRAP_SKU:
                continue

            stock_id = item.get("stockId")
            if stock_id:
                return int(stock_id)

    raise RuntimeError(
        "Could not determine PETIMPEX warehouse ID from order #2649. "
        f"Set repository variable {WAREHOUSE_VARIABLE}."
    )


def changed_stock(products, state):
    current = {
        sku: int(item["stock"])
        for sku, item in products.items()
    }

    if not state:
        return current, current

    previous = {
        str(sku): int(quantity)
        for sku, quantity in state.get("published_stock", {}).items()
    }
    updates = {
        sku: quantity
        for sku, quantity in current.items()
        if previous.get(sku) != quantity
    }

    return current, updates


def update_salesdrive_stock(api_key, warehouse_id, updates):
    items = [
        {
            "id": sku,
            "stockBalanceByStock": {
                str(warehouse_id): int(quantity),
            },
        }
        for sku, quantity in sorted(updates.items())
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
                f"Could not update PETIMPEX stock in SalesDrive: {result}"
            )


def build_yml(products, published_stock):
    root = etree.Element(
        "yml_catalog",
        date=now_kyiv().strftime("%Y-%m-%d %H:%M"),
    )
    shop = etree.SubElement(root, "shop")
    etree.SubElement(shop, "name").text = "CatPaws PETIMPEX stock"
    etree.SubElement(shop, "company").text = "CatPaws"
    etree.SubElement(shop, "url").text = "https://catpaws.com.ua/"

    currencies = etree.SubElement(shop, "currencies")
    etree.SubElement(currencies, "currency", id="UAH", rate="1")
    categories = etree.SubElement(shop, "categories")
    etree.SubElement(categories, "category", id="1").text = "PETIMPEX"
    offers = etree.SubElement(shop, "offers")

    for sku, item in sorted(products.items()):
        quantity = int(published_stock.get(sku, 0))
        offer = etree.SubElement(
            offers,
            "offer",
            id=sku,
            available="true" if quantity > 0 else "false",
        )
        etree.SubElement(offer, "name").text = item["name"]
        etree.SubElement(offer, "vendorCode").text = sku
        etree.SubElement(offer, "price").text = "1"
        etree.SubElement(offer, "currencyId").text = "UAH"
        etree.SubElement(offer, "categoryId").text = "1"
        etree.SubElement(offer, "quantity_in_stock").text = str(quantity)
        etree.SubElement(offer, "stock").text = str(quantity)
        etree.SubElement(offer, "in_stock").text = "1" if quantity > 0 else "0"

    return etree.ElementTree(root)


def main():
    api_key = os.environ.get("SALESDRIVE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SALESDRIVE_API_KEY is not configured")

    supplier, supplier_updated_at = load_supplier_feed()
    tracked_skus = load_tracked_skus()
    site_catalog = load_site_catalog()
    products = select_products(supplier, tracked_skus, site_catalog)

    state = load_state()
    warehouse_id = find_warehouse_id(api_key, state)
    published_stock, updates = changed_stock(products, state)

    if updates:
        update_salesdrive_stock(api_key, warehouse_id, updates)

    save_state({
        "version": 1,
        "warehouse_id": warehouse_id,
        "supplier_updated_at": supplier_updated_at,
        "published_stock": published_stock,
    })

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    build_yml(products, published_stock).write(
        OUTPUT_FILE,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    positive = sum(quantity > 0 for quantity in published_stock.values())
    print(f"PETIMPEX offers in supplier feed: {len(supplier)}")
    print(f"Tracked CatPaws PETIMPEX products: {len(products)}")
    print(f"SalesDrive warehouse ID: {warehouse_id}")
    print(f"Products sent to SalesDrive: {len(updates)}")
    print(f"Products with positive stock: {positive}")
    print(f"Products with zero stock: {len(products) - positive}")
    print(f"Test SKU {BOOTSTRAP_SKU}: {published_stock.get(BOOTSTRAP_SKU, 0)}")
    print(f"Created: {OUTPUT_FILE}")
    print(f"State saved: {STATE_FILE}")


if __name__ == "__main__":
    main()
