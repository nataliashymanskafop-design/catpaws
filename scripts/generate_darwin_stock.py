import json
import os

from lxml import etree

from generate_home_food_stock import CATALOG_XML_URL, download


STATE_FILE = "public/darwin-stock-state.json"
DARWIN_BRANDS = {"ambrosia", "happyone", "exclusion"}
AVAILABLE_STOCK = 2


def clean(value):
    return " ".join(str(value or "").split())


def main():
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

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(
            {
                "version": 1,
                "warehouse_id": "DARWIN",
                "available_stock_per_product": AVAILABLE_STOCK,
                "published_stock": dict(sorted(published_stock.items())),
            },
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    available = sum(quantity > 0 for quantity in published_stock.values())
    unavailable = len(published_stock) - available
    print(
        "Darwin stock generated: "
        f"{len(published_stock)} products, "
        f"{available} available x {AVAILABLE_STOCK}, "
        f"{unavailable} unavailable"
    )


if __name__ == "__main__":
    main()
