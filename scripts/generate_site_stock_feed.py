import json
import os
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from lxml import etree

from generate_home_food_stock import download
from generate_feed import FORCE_ZERO_SKUS, is_modes_bowl
from normalize_feed_prices import normalize_price
from generate_petimpex_catalog import OUTPUT_FILE as CLEAN_PETIMPEX_FILE
from discontinued_products import is_discontinued_offer


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
# Site-only override requested by Natalia on 2026-10-28 for MODES Tofu litter.
SITE_FORCE_ZERO_SKUS = {"ЗС000355", "ЗС000356", "ЗС000357", "ЗС000358", "ЗС000359"}
# Keep the inquiry status selected manually in Horoshop, even if stock returns.
PRESERVE_INQUIRY_STATUS_SKUS = {
    "ЗС000375",  # Анавірин, eye/nasal drops 10 ml, MODES.
    "ЗС000338",  # Вівадерм, medicinal ointment 25 g, MODES.
}
PETIMPEX_XML_URL = "https://files.petimpex.com/shimanskay/Shimanskaya.xml.yml"
PETIMPEX_STATE_FILE = "public/petimpex-stock-state.json"
PETIMPEX_SITE_CATALOG_XML_URL = (
    "https://catpaws.com.ua/content/export/662cd88f90355628d5b10786f126be34.xml"
)
# These public site brands are supplied by PETIMPEX. The November warehouse
# workbook has already been applied in Horoshop. Preserve the site's confirmed
# binary availability instead of restoring the older October supplier XML.
PETIMPEX_SITE_VENDORS = {
    "camon", "dolina noteci", "hyponic", "iv san bernard", "mera",
    "maxi paws", "nuevo",
}


def load_petimpex_prices(payload, tracked_skus):
    supplier_root = etree.fromstring(payload)
    offers = supplier_root.xpath(".//offer")
    if len(offers) < 1000:
        raise RuntimeError("PetImpex price source is empty or incomplete")
    prices = {}
    for offer in offers:
        sku = clean(offer.get("id"))
        if sku not in tracked_skus:
            continue
        value = offer.findtext("price")
        # Supplier bundles without retail prices must not overwrite site prices.
        if value is None:
            continue
        price = normalize_price(value)
        if float(price) <= 0:
            continue
        prices[sku] = price
    if len(prices) < 300:
        raise RuntimeError(f"PetImpex retail prices are incomplete: {len(prices)}")
    return prices


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
                # Blocked products are forced to zero when building the feed.
                if sku in FORCE_ZERO_SKUS:
                    continue
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

    # Відсутність джерела залишків не означає відсутність товару.
    # Не змінюємо ручну наявність на сайті; Mono має окремі правила.
    return None, "none"


def build_feed(catalog_root, own_stock, supplier_stock, retail_prices=None,
               petimpex_catalog_root=None):
    retail_prices = retail_prices or {}
    root = etree.Element(
        "yml_catalog",
        date=datetime.now(ZoneInfo("Europe/Kyiv")).strftime(
            "%Y-%m-%d %H:%M"
        ),
    )
    shop = etree.SubElement(root, "shop")
    offers = etree.SubElement(shop, "offers")

    seen_skus = set()
    source_counts = {"SUPPLIER": 0, "supplier": 0, "none": 0, "petimpex_site": 0}

    catalog_offers = catalog_root.xpath(".//offer")
    if petimpex_catalog_root is not None:
        # The current general YML includes PETIMPEX cards missing from the older
        # export. Refresh only those public brands; retain every other supplier's
        # original catalog rows and stock rules unchanged.
        current_petimpex = [
            offer for offer in petimpex_catalog_root.xpath(".//offer")
            if clean(offer.findtext("vendor")).casefold() in PETIMPEX_SITE_VENDORS
        ]
        if len(current_petimpex) < 500:
            raise RuntimeError("Current public PETIMPEX site catalog is incomplete")
        catalog_offers = [
            offer for offer in catalog_offers
            if clean(offer.findtext("vendor")).casefold() not in PETIMPEX_SITE_VENDORS
        ] + current_petimpex
    sku_counts = Counter(clean(item.findtext("vendorCode")) for item in catalog_offers)
    duplicate_skus = {sku for sku, count in sku_counts.items() if sku and count > 1}
    if duplicate_skus:
        print(f"Ambiguous duplicate SKUs omitted from site update: {sorted(duplicate_skus)}")

    for source_offer in catalog_offers:
        sku = clean(source_offer.findtext("vendorCode"))
        vendor = clean(source_offer.findtext("vendor")).casefold()

        if not sku:
            continue

        seen_skus.add(sku)
        # Manual removal in Horoshop must not be undone by a later import.
        if is_discontinued_offer(source_offer):
            continue
        # Never select an arbitrary card when several IDs share the same SKU.
        if sku in duplicate_skus:
            continue
        # MODES bowls and inquiry-only medicines keep the manually selected status.
        # No stock/availability row may overwrite it during a site import.
        if is_modes_bowl(source_offer) or sku in PRESERVE_INQUIRY_STATUS_SKUS:
            continue

        availability = None
        if sku in FORCE_ZERO_SKUS or sku in SITE_FORCE_ZERO_SKUS:
            # A stale catalog or stock state must not restore this product.
            quantity, source = 0, "none"
        elif vendor in FORCE_ZERO_BRANDS:
            # З RAFI більше не працюємо. Товар залишається прихованим у
            # Horoshop, а фід додатково не дозволить повернути наявність.
            quantity, source = 0, "none"
        elif vendor in PETIMPEX_SITE_VENDORS and own_stock.get(sku, 0) <= 0:
            # Read only availability already published in the public site catalog.
            # Do not upload a private warehouse snapshot or invent exact stock
            # from the workbook's <10/>10 buckets. This Horoshop export writes
            # available="" for out-of-stock cards. A missing attribute or an
            # unknown status still preserves the manual site status.
            published_available = source_offer.get("available")
            if published_available in {"true", "false", ""}:
                availability = published_available == "true"
            quantity, source = None, "petimpex_site"
        else:
            quantity, source = resolve_quantity(
                sku,
                own_stock,
                supplier_stock,
            )
        source_counts[source] += 1
        if quantity is None and availability is None:
            # Omit the entire row so Horoshop preserves its existing status.
            continue

        offer = etree.SubElement(
            offers,
            "offer",
            id=str(source_offer.findtext("vendorCode") or ""),
            available="true" if (availability if availability is not None else quantity > 0) else "false",
        )
        # Horoshop matches the literal article: keep internal spaces from its catalog.
        etree.SubElement(offer, "vendorCode").text = str(source_offer.findtext("vendorCode") or "")
        if quantity is not None:
            etree.SubElement(offer, "quantity_in_stock").text = str(quantity)
        if sku in retail_prices:
            etree.SubElement(offer, "price").text = normalize_price(retail_prices[sku])
            etree.SubElement(offer, "currencyId").text = "UAH"

    if len(seen_skus) < 2000:
        raise RuntimeError(
            "Site catalog is empty or incomplete: "
            f"only {len(seen_skus)} products"
        )

    # Retail prices are explicitly authorized; discounts, old prices and gifts
    # remain managed on the site and must never be reset by this feed.
    if root.xpath(".//oldprice | .//purchaseprice | .//discount | .//gift"):
        raise RuntimeError("Promotional or purchase price fields are forbidden")

    return root, source_counts


def petimpex_payload():
    if os.path.exists(CLEAN_PETIMPEX_FILE):
        with open(CLEAN_PETIMPEX_FILE, "rb") as handle:
            return handle.read()
    return download(PETIMPEX_XML_URL)


def main():
    print("Downloading current CatPaws catalog...")
    catalog_root = etree.fromstring(download(CATALOG_XML_URL))
    petimpex_catalog_root = etree.fromstring(download(PETIMPEX_SITE_CATALOG_XML_URL))

    own_stock = load_state(OWN_STOCK_STATE_FILE)
    supplier_stock = load_supplier_stock()
    retail_prices = load_petimpex_prices(
        petimpex_payload(),
        load_state(PETIMPEX_STATE_FILE),
    )
    with open("public/terravet-stock-state.json", encoding="utf-8") as handle:
        terravet_state = json.load(handle)
    josera_prices = terravet_state.get("retail_prices", {})
    if not isinstance(josera_prices, dict):
        raise RuntimeError("Invalid TERRAVET retail price state")
    conflicts = set(retail_prices) & set(josera_prices)
    if conflicts:
        raise RuntimeError(f"PetImpex/Josera retail price conflict: {sorted(conflicts)}")
    retail_prices.update(josera_prices)
    print(f"Josera correctly sized retail prices loaded: {len(josera_prices)}")
    root, source_counts = build_feed(
        catalog_root,
        own_stock,
        supplier_stock,
        retail_prices,
        petimpex_catalog_root,
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
        f"sources: {source_counts}, "
        f"normalized retail prices: {len(root.xpath('.//offer/price'))}"
    )


if __name__ == "__main__":
    main()

