import json
import os
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from lxml import etree

from generate_home_food_stock import download, fetch_orders, now_kyiv, format_api_time, parse_api_time
from josera_stock import JOSERA_URL, CATALOG_URL, read_supplier, map_catalog, calculate


STATE_FILE = "public/terravet-stock-state.json"
MIN_PRODUCTS = 150

# Exact MODES stock and conditional Josera stock share Mono warehouse TERRAVET.
TERRAVET_SOURCES = (
    ("MODES", "https://media.modes.ua/feeds/ModesDnipro.xml"),
)

# Shop-created sets contain three identical single-tablet MODES packages.
# Only these explicit codes are bundles; a generic '-3' suffix is not enough.
QUADROMIDAS_BASE_SKUS = (
    "ЗС000339", "ЗС000340", "ЗС000341", "ЗС000342",
    "ЗС000383", "ЗС000404", "ЗС000405", "ЗС000406",
)
QUADROMIDAS_PACK_SIZE = 3


def quadromidas_bundles(stock, unit_prices):
    quantities = {}
    prices = {}
    for base in QUADROMIDAS_BASE_SKUS:
        bundle = f"{base}-3"
        quantities[bundle] = parse_quantity(stock.get(base, 0)) // QUADROMIDAS_PACK_SIZE
        try:
            price = Decimal(str(unit_prices.get(base)))
        except (InvalidOperation, ValueError):
            continue
        if price.is_finite() and price > 0:
            prices[bundle] = float(price * QUADROMIDAS_PACK_SIZE)
    return quantities, prices


def clean(value):
    return " ".join(str(value or "").split())


def parse_quantity(value):
    text = clean(value).replace(",", ".")

    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def load_source(source_name, url, bundle_prices=None):
    print(f"Downloading {source_name} stock...")
    root = etree.fromstring(download(url))
    stock = {}
    duplicates = set()
    unit_prices = {}

    for offer in root.xpath(".//offer"):
        sku = clean(offer.findtext("vendorCode"))

        if not sku:
            continue

        quantity = parse_quantity(
            offer.findtext("quantity_in_stock")
        )

        if sku in stock:
            duplicates.add(sku)
            quantity = max(stock[sku], quantity)

        stock[sku] = quantity
        if source_name == "MODES" and sku in QUADROMIDAS_BASE_SKUS:
            unit_prices[sku] = offer.findtext("price")

    if len(stock) < MIN_PRODUCTS:
        raise RuntimeError(f"{source_name} stock feed incomplete: {len(stock)} products")
    if source_name == "MODES":
        quantities, prices = quadromidas_bundles(stock, unit_prices)
        conflicts = set(stock) & set(quantities)
        if conflicts:
            raise RuntimeError(f"MODES source now contains shop bundle SKUs: {sorted(conflicts)}")
        stock.update(quantities)
        if bundle_prices is not None:
            bundle_prices.update(prices)
    return stock, duplicates


def main():
    previous = {}
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            previous = json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass

    published_stock = {}
    duplicate_skus = set()
    source_counts = {}
    quadromidas_prices = {}

    for source_name, url in TERRAVET_SOURCES:
        source_stock, source_duplicates = load_source(
            source_name,
            url,
            quadromidas_prices,
        )
        source_counts[source_name] = len(source_stock)
        duplicate_skus.update(source_duplicates)

        for sku, quantity in source_stock.items():
            if sku in published_stock:
                duplicate_skus.add(sku)
                quantity = max(published_stock[sku], quantity)

            published_stock[sku] = quantity

    print("Downloading Josera partner feed and full site catalog...")
    supplier = read_supplier(download(JOSERA_URL))
    rows, missing = map_catalog(download(CATALOG_URL), supplier)
    api_key = os.environ.get("SALESDRIVE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SALESDRIVE_API_KEY is required for shared Josera bundle reservations")
    finished_at = now_kyiv()
    josera_previous = previous.get("josera")
    initializing = not josera_previous
    since = (finished_at - timedelta(days=30) if initializing
             else parse_api_time(josera_previous["last_sync"]) - timedelta(minutes=2))
    orders = fetch_orders(api_key, since, finished_at)
    base_stock, snapshots, josera_stock = calculate(
        rows, josera_previous, orders, initializing=initializing)
    conflicts = set(published_stock) & set(josera_stock)
    if conflicts:
        raise RuntimeError(f"MODES/Josera SKU conflict: {sorted(conflicts)}")
    published_stock.update(josera_stock)
    source_counts["JOSERA"] = len(josera_stock)
    retail_prices = {code: row["price"] for code, row in rows.items()
                     if row["price"] is not None}
    retail_prices.update(quadromidas_prices)
    sale_prices = {code: row["sale_price"] for code, row in rows.items()
                   if row.get("sale_price") is not None}
    josera_state = {
        "last_sync": format_api_time(finished_at),
        "base_stock": base_stock,
        "order_snapshots": snapshots,
    }
    print(f"Josera mapped: {len(rows) - len(missing)}/{len(rows)}; missing: {missing}")
    print(f"Josera conditional stock: {sum(q > 0 for q in josera_stock.values())} available; "
          f"{len(retail_prices)} correctly sized regular retail prices")
    for code in ("50014710", "50014710р", "30001658", "30001658_box", "30001660", "30001660_box"):
        print(f"Josera control {code}: stock={josera_stock.get(code)}; price={retail_prices.get(code)}")

    if len(published_stock) < MIN_PRODUCTS:
        raise RuntimeError(
            "TERRAVET stock feeds are empty or incomplete: "
            f"only {len(published_stock)} products"
        )

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            {
                "version": 2,
                "source_urls": {"MODES": TERRAVET_SOURCES[0][1], "JOSERA": JOSERA_URL},
                "josera": josera_state,
                "retail_prices": retail_prices,
                "sale_prices": sale_prices,
                "warehouse_id": "TERRAVET",
                "sources": source_counts,
                "duplicate_skus": sorted(duplicate_skus),
                "published_stock": dict(
                    sorted(published_stock.items())
                ),
            },
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    os.replace(temporary, STATE_FILE)

    available = sum(
        quantity > 0
        for quantity in published_stock.values()
    )
    total_units = sum(published_stock.values())

    print(
        "TERRAVET stock generated: "
        f"{len(published_stock)} products, "
        f"{available} available, "
        f"{total_units} total units, "
        f"{len(duplicate_skus)} duplicate SKUs; "
        f"sources: {source_counts}"
    )


if __name__ == "__main__":
    main()

