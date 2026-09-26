import json
import os

from lxml import etree

from generate_home_food_stock import download


STATE_FILE = "public/terravet-stock-state.json"
MIN_PRODUCTS = 150

# Josera буде додана сюди другим джерелом, коли її фід буде готовий.
TERRAVET_SOURCES = (
    ("MODES", "https://media.modes.ua/feeds/ModesDnipro.xml"),
)


def clean(value):
    return " ".join(str(value or "").split())


def parse_quantity(value):
    text = clean(value).replace(",", ".")

    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def load_source(source_name, url):
    print(f"Downloading {source_name} stock...")
    root = etree.fromstring(download(url))
    stock = {}
    duplicates = set()

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

    return stock, duplicates


def main():
    published_stock = {}
    duplicate_skus = set()
    source_counts = {}

    for source_name, url in TERRAVET_SOURCES:
        source_stock, source_duplicates = load_source(
            source_name,
            url,
        )
        source_counts[source_name] = len(source_stock)
        duplicate_skus.update(source_duplicates)

        for sku, quantity in source_stock.items():
            if sku in published_stock:
                duplicate_skus.add(sku)
                quantity = max(published_stock[sku], quantity)

            published_stock[sku] = quantity

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
                "version": 1,
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
