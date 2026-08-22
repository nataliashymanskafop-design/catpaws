import os
import requests
from lxml import etree


# ============================================================
# SETTINGS
# ============================================================

HOROSHOP_URL = (
    "https://catpaws.com.ua/content/export/"
    "77e6f1cd306feb32b68e245d1affc6bc.xml"
)

PROM_API_URL = "https://my.prom.ua/api/v1/products/list"

OUTPUT_FILE = "prom-update.xml"

PROM_API_TOKEN = os.environ["PROM_API_TOKEN"]


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_code(value):
    return clean(value).upper()


def get_text(element, tag):
    node = element.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


# ============================================================
# DOWNLOAD ALL EXISTING PROM PRODUCTS VIA API
# ============================================================

def get_prom_products():
    headers = {
        "Authorization": f"Bearer {PROM_API_TOKEN}",
        "Content-Type": "application/json",
    }

    products = []
    last_id = None

    print("Downloading products from Prom API...")

    while True:
        params = {"limit": 100}

        if last_id is not None:
            params["last_id"] = last_id

        response = requests.get(
            PROM_API_URL,
            headers=headers,
            params=params,
            timeout=30,
        )

        print("Prom API HTTP:", response.status_code)

        response.raise_for_status()

        data = response.json()
        batch = data.get("products", [])

        if not batch:
            break

        products.extend(batch)

        print("Downloaded Prom products:", len(products))

        if len(batch) < 100:
            break

        last_id = batch[-1].get("id")

        if not last_id:
            break

    return products


# ============================================================
# DOWNLOAD HOROSHOP XML
# ============================================================

def get_horoshop_products():
    print("Downloading Horoshop feed...")

    response = requests.get(
        HOROSHOP_URL,
        timeout=60,
    )

    response.raise_for_status()

    root = etree.fromstring(response.content)

    products = {}

    for offer in root.xpath(".//offer"):

        vendor_code = normalize_code(
            get_text(offer, "vendorCode")
        )

        if not vendor_code:
            continue

        products[vendor_code] = offer

    print("Horoshop products:", len(products))

    return products


# ============================================================
# BUILD UPDATE FEED
# ============================================================

def build_feed():

    prom_products = get_prom_products()
    horoshop_products = get_horoshop_products()

    # --------------------------------------------------------
    # IMPORTANT:
    # Only products confirmed by Prom API are allowed
    # into the update feed.
    # --------------------------------------------------------

    prom_by_sku = {}

    duplicate_skus = set()

    for product in prom_products:

        sku = normalize_code(product.get("sku"))

        if not sku:
            continue

        if sku in prom_by_sku:
            duplicate_skus.add(sku)
            continue

        prom_by_sku[sku] = product

    print()
    print("Prom products received:", len(prom_products))
    print("Prom products with SKU:", len(prom_by_sku))

    if duplicate_skus:
        print(
            "Duplicate Prom SKU skipped:",
            sorted(duplicate_skus)
        )

    # --------------------------------------------------------
    # XML
    # --------------------------------------------------------

    yml_catalog = etree.Element("yml_catalog")

    shop = etree.SubElement(yml_catalog, "shop")

    offers = etree.SubElement(shop, "offers")

    updated = 0
    missing_horoshop = 0
    skipped_duplicates = 0

    for sku, prom_product in prom_by_sku.items():

        # Do not touch duplicate SKUs.
        # We cannot safely determine which Prom card is correct.
        if sku in duplicate_skus:
            skipped_duplicates += 1
            continue

        horoshop_offer = horoshop_products.get(sku)

        # ----------------------------------------------------
        # CRITICAL SAFETY RULE:
        #
        # If product does not exist in Horoshop,
        # DO NOT put it in XML.
        #
        # We also DO NOT mark it unavailable here.
        # This feed is ONLY for matched existing products.
        # ----------------------------------------------------

        if horoshop_offer is None:
            missing_horoshop += 1
            continue

        prom_id = clean(prom_product.get("id"))

        if not prom_id:
            continue

        # ----------------------------------------------------
        # HOROSHOP DATA
        # ----------------------------------------------------

        price = get_text(horoshop_offer, "price")
        oldprice = get_text(horoshop_offer, "oldprice")

        available_raw = clean(
            horoshop_offer.get("available")
        ).lower()

        available = (
            "true"
            if available_raw in ("true", "1", "yes")
            else "false"
        )

        # ----------------------------------------------------
        # EXISTING PROM PRODUCT ONLY
        #
        # id = real Prom product ID from API
        # vendorCode = real SKU confirmed by Prom API
        # ----------------------------------------------------

        offer = etree.SubElement(
            offers,
            "offer",
            id=prom_id,
            available=available,
        )

        vendor_code = etree.SubElement(
            offer,
            "vendorCode"
        )
        vendor_code.text = sku

        if price:
            price_node = etree.SubElement(
                offer,
                "price"
            )
            price_node.text = price

        # ----------------------------------------------------
        # DISCOUNT
        #
        # Horoshop:
        # price    = current selling price
        # oldprice = old price before discount
        #
        # Prom receives both.
        # ----------------------------------------------------

        if oldprice:
            try:
                old_price_num = float(
                    oldprice.replace(",", ".")
                )

                price_num = float(
                    price.replace(",", ".")
                )

                if old_price_num > price_num:
                    oldprice_node = etree.SubElement(
                        offer,
                        "oldprice"
                    )
                    oldprice_node.text = oldprice

            except (ValueError, AttributeError):
                pass

        currency = etree.SubElement(
            offer,
            "currencyId"
        )
        currency.text = "UAH"

        updated += 1

    # ========================================================
    # SAVE
    # ========================================================

    tree = etree.ElementTree(yml_catalog)

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True,
        pretty_print=True,
    )

    print()
    print("=" * 60)
    print("PROM SAFE UPDATE FEED READY")
    print("=" * 60)

    print("Prom API products:", len(prom_products))
    print("Prom unique SKU:", len(prom_by_sku))
    print("Included in update feed:", updated)
    print("Prom SKU missing in Horoshop:", missing_horoshop)
    print("Duplicate SKU skipped:", skipped_duplicates)

    print()
    print(
        "SAFETY: feed contains ONLY products "
        "confirmed by Prom API and Horoshop."
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    build_feed()
