import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from lxml import etree

from generate_home_food_stock import download
from generate_feed import is_modes_bowl


# Актуальний фід каталогу сайту. На відміну від Mono-фідів, тут не
# застосовуються обмеження за ціною, брендом або категорією.
CATALOG_XML_URL = os.environ.get(
    "SITE_CATALOG_XML_URL",
    "https://catpaws.com.ua/content/export/5d007701b07c6dab399214f2c0d6743c.xml",
)
OUTPUT_FILE = "public/site-stock-feed.xml"

OWN_STOCK_STATE_FILE = "public/own-stock-state.json"
SUPPLIER_STATE_FILES = (
    "public/home-food-stock-state.json",
    "public/kormax-stock-state.json",
    "public/doms-stock-state.json",
    "public/petimpex-stock-state.json",
    "public/terravet-stock-state.json",
    "public/darwin-stock-state.json",
)
FORCE_ZERO_BRANDS = {"rafi"}


def clean(value):
    return " ".join(str(value or "").split())


def to_quantity(value):
    try:
        return max(0, int(float(str(value).replace(",", "."))))
    except (TypeError, ValueError):
        return 0


def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Stock state is unavailable or invalid: {path}"
        ) from error

    published_stock = state.get("published_stock")

    if not isinstance(published_stock, dict) or not published_stock:
        raise RuntimeError(f"Stock state is empty or invalid: {path}")

    return {
        clean(sku): to_quantity(quantity)
        for sku, quantity in published_stock.items()
        if clean(sku)
    }


def load_supplier_stock():
    combined = {}

    for path in SUPPLIER_STATE_FILES:
        source_stock = load_state(path)

        for sku, quantity in source_stock.items():
            if sku in combined:
                raise RuntimeError(
                    f"SKU {sku} occurs in more than one supplier state"
                )

            combined[sku] = quantity

        print(f"Loaded {len(source_stock)} products from {path}")

    return combined


def resolve_quantity(sku, own_stock, supplier_stock):
    own_quantity = own_stock.get(sku, 0)

    # Викуплений товар і повернення фізично лежать у Наталії, тому
    # позитивний залишок власного складу має найвищий пріоритет.
    if own_quantity > 0:
        return own_quantity, "SUPPLIER"

    if sku in supplier_stock:
        return supplier_stock[sku], "supplier"

    # Товар, якого немає ані на власному, ані на підключених складах,
    # не повинен випадково залишитися доступним на сайті.
    return 0, "none"


def build_feed(catalog_root, own_stock, supplier_stock):
    root = etree.Element(
        "yml_catalog",
        date=datetime.now(ZoneInfo("Europe/Kyiv")).strftime(
            "%Y-%m-%d %H:%M"
        ),
    )
    shop = etree.SubElement(root, "shop")
    offers = etree.SubElement(shop, "offers")

    seen_skus = set()
    source_counts = {"SUPPLIER": 0, "supplier": 0, "none": 0}

    for source_offer in catalog_root.xpath(".//offer"):
        sku = clean(source_offer.findtext("vendorCode"))
        vendor = clean(source_offer.findtext("vendor")).casefold()

        if not sku:
            continue

        if sku in seen_skus:
            raise RuntimeError(f"Duplicate SKU in site catalog: {sku}")

        seen_skus.add(sku)
        # Site-only MODES bowls keep the manually selected inquiry status.
        # No stock/availability row may overwrite it during a site import.
        if is_modes_bowl(source_offer):
            continue

        if vendor in FORCE_ZERO_BRANDS:
            # З RAFI більше не працюємо. Товар залишається прихованим у
            # Horoshop, а фід додатково не дозволить повернути наявність.
            quantity, source = 0, "none"
        else:
            quantity, source = resolve_quantity(
                sku,
                own_stock,
                supplier_stock,
            )
        source_counts[source] += 1

        offer = etree.SubElement(
            offers,
            "offer",
            id=clean(source_offer.get("id")) or sku,
            available="true" if quantity > 0 else "false",
        )
        etree.SubElement(offer, "vendorCode").text = sku
        etree.SubElement(offer, "quantity_in_stock").text = str(quantity)

    if len(seen_skus) < 2000:
        raise RuntimeError(
            "Site catalog is empty or incomplete: "
            f"only {len(seen_skus)} products"
        )

    # A stock import must never overwrite retail or promotional prices.
    if root.xpath(".//price | .//oldprice | .//purchaseprice"):
        raise RuntimeError("Price fields are forbidden in the site stock feed")

    return root, source_counts


def main():
    print("Downloading current CatPaws catalog...")
    catalog_root = etree.fromstring(download(CATALOG_XML_URL))

    own_stock = load_state(OWN_STOCK_STATE_FILE)
    supplier_stock = load_supplier_stock()
    root, source_counts = build_feed(
        catalog_root,
        own_stock,
        supplier_stock,
    )

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    temporary = f"{OUTPUT_FILE}.tmp"
    etree.ElementTree(root).write(
        temporary,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )
    os.replace(temporary, OUTPUT_FILE)

    offers = root.xpath(".//offer")
    available = sum(
        offer.get("available") == "true"
        for offer in offers
    )
    print(
        "Site stock feed generated: "
        f"{len(offers)} products, {available} available, "
        f"sources: {source_counts}"
    )


if __name__ == "__main__":
    main()
