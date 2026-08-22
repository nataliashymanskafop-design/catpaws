import os
import time
import requests
from lxml import etree


# ============================================================
# SETTINGS
# ============================================================

HOROSHOP_URL = (
    "https://catpaws.com.ua/content/export/"
    "77e6f1cd306feb32b68e245d1affc6bc.xml"
)

PROM_API_LIST_URL = "https://my.prom.ua/api/v1/products/list"
PROM_API_EDIT_URL = "https://my.prom.ua/api/v1/products/edit"

PROM_API_TOKEN = os.environ["PROM_API_TOKEN"]

BATCH_SIZE = 50


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


def parse_price(value):
    value = clean(value)

    if not value:
        return None

    try:
        return float(value.replace(",", "."))
    except (ValueError, TypeError):
        return None


# ============================================================
# PROM API
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

        params = {
            "limit": 100
        }

        if last_id is not None:
            params["last_id"] = last_id

        response = requests.get(
            PROM_API_LIST_URL,
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

        print(
            "Downloaded Prom products:",
            len(products)
        )

        if len(batch) < 100:
            break

        last_id = batch[-1].get("id")

        if not last_id:
            break

    return products


# ============================================================
# HOROSHOP
# ============================================================

def get_horoshop_products():

    print("Downloading Horoshop feed...")

    response = requests.get(
        HOROSHOP_URL,
        timeout=60,
    )

    response.raise_for_status()

    root = etree.fromstring(
        response.content
    )

    products = {}

    for offer in root.xpath(".//offer"):

        sku = normalize_code(
            get_text(
                offer,
                "vendorCode"
            )
        )

        if not sku:
            continue

        products[sku] = offer

    print(
        "Horoshop products:",
        len(products)
    )

    return products


# ============================================================
# PREPARE PROM PRODUCTS
# ============================================================

def prepare_prom_products(prom_products):

    prom_by_sku = {}

    duplicate_skus = set()

    for product in prom_products:

        sku = normalize_code(
            product.get("sku")
        )

        if not sku:
            continue

        if sku in prom_by_sku:

            duplicate_skus.add(sku)

            continue

        prom_by_sku[sku] = product

    print()
    print(
        "Prom products received:",
        len(prom_products)
    )

    print(
        "Prom products with SKU:",
        len(prom_by_sku)
    )

    if duplicate_skus:

        print(
            "Duplicate Prom SKU skipped:",
            sorted(duplicate_skus)
        )

    return prom_by_sku, duplicate_skus


# ============================================================
# BUILD API UPDATE LIST
# ============================================================

def build_updates(
    prom_by_sku,
    duplicate_skus,
    horoshop_products,
):

    updates = []

    unavailable_count = 0
    available_count = 0
    missing_horoshop = 0
    skipped_duplicates = 0

    for sku, prom_product in prom_by_sku.items():

        # ----------------------------------------------------
        # DUPLICATE SKU
        #
        # Не чіпаємо взагалі.
        # ----------------------------------------------------

        if sku in duplicate_skus:

            skipped_duplicates += 1

            continue

        # ----------------------------------------------------
        # PRODUCT MUST EXIST IN HOROSHOP
        # ----------------------------------------------------

        horoshop_offer = horoshop_products.get(
            sku
        )

        if horoshop_offer is None:

            missing_horoshop += 1

            continue

        # ----------------------------------------------------
        # REAL PROM PRODUCT ID
        # ----------------------------------------------------

        prom_id = prom_product.get("id")

        if not prom_id:
            continue

        # ----------------------------------------------------
        # AVAILABILITY
        # ----------------------------------------------------

        available_raw = clean(
            horoshop_offer.get("available")
        ).lower()

        available = (
            available_raw
            in (
                "true",
                "1",
                "yes",
            )
        )

        # ====================================================
        # CRITICAL RULE
        #
        # НЕМАЄ В НАЯВНОСТІ:
        #
        # міняємо ТІЛЬКИ presence.
        #
        # price НЕ передаємо.
        # oldprice НЕ передаємо.
        #
        # Таким чином ціна товару на Prom
        # залишається абсолютно без змін.
        # ====================================================

        if not available:

            item = {
                "id": prom_id,
                "presence": "not_available",
            }

            updates.append(item)

            unavailable_count += 1

            continue

        # ====================================================
        # PRODUCT IS AVAILABLE
        #
        # Тільки тут дозволено працювати з ціною.
        # ====================================================

        price = parse_price(
            get_text(
                horoshop_offer,
                "price"
            )
        )

        oldprice = parse_price(
            get_text(
                horoshop_offer,
                "oldprice"
            )
        )

        item = {
            "id": prom_id,
            "presence": "available",
        }

        # ----------------------------------------------------
        # CURRENT PRICE
        # ----------------------------------------------------

        if (
            price is not None
            and price > 0
        ):

            item["price"] = price

        # ----------------------------------------------------
        # OLD PRICE / DISCOUNT
        #
        # Передаємо oldprice ТІЛЬКИ коли:
        #
        # 1. товар є в наявності;
        # 2. oldprice існує;
        # 3. price існує;
        # 4. oldprice > price.
        #
        # НІКОЛИ не передаємо oldprice = 0.
        # ----------------------------------------------------

        if (
            oldprice is not None
            and price is not None
            and oldprice > price
            and oldprice > 0
        ):

            item["oldprice"] = oldprice

        updates.append(item)

        available_count += 1

    print()
    print("=" * 60)
    print("PROM UPDATE PREPARED")
    print("=" * 60)

    print(
        "Available products:",
        available_count
    )

    print(
        "Unavailable products:",
        unavailable_count
    )

    print(
        "Prom SKU missing in Horoshop:",
        missing_horoshop
    )

    print(
        "Duplicate SKU skipped:",
        skipped_duplicates
    )

    print(
        "Total products prepared:",
        len(updates)
    )

    return updates


# ============================================================
# SEND UPDATES TO PROM
# ============================================================

def send_updates(updates):

    headers = {
        "Authorization": f"Bearer {PROM_API_TOKEN}",
        "Content-Type": "application/json",
    }

    total = len(updates)

    processed = 0

    successful_ids = []
    errors = {}

    print()
    print("=" * 60)
    print("SENDING UPDATES TO PROM")
    print("=" * 60)

    for start in range(
        0,
        total,
        BATCH_SIZE
    ):

        batch = updates[
            start:start + BATCH_SIZE
        ]

        batch_number = (
            start // BATCH_SIZE
        ) + 1

        print()
        print(
            f"Sending batch #{batch_number}: "
            f"{len(batch)} products"
        )

        response = requests.post(
            PROM_API_EDIT_URL,
            headers=headers,
            json=batch,
            timeout=60,
        )

        print(
            "HTTP:",
            response.status_code
        )

        try:
            result = response.json()

            print(
                "Prom response:",
                result
            )

        except ValueError:

            print(
                "Prom response text:",
                response.text
            )

            response.raise_for_status()

            result = {}

        response.raise_for_status()

        batch_processed = result.get(
            "processed_ids",
            []
        )

        batch_errors = result.get(
            "errors",
            {}
        )

        successful_ids.extend(
            batch_processed
        )

        errors.update(
            batch_errors
        )

        processed += len(batch)

        print(
            f"Progress: "
            f"{processed}/{total}"
        )

        # Невелика пауза між пакетами,
        # щоб не бити API занадто швидко.
        time.sleep(0.5)

    return successful_ids, errors


# ============================================================
# MAIN
# ============================================================

def main():

    prom_products = get_prom_products()

    horoshop_products = (
        get_horoshop_products()
    )

    prom_by_sku, duplicate_skus = (
        prepare_prom_products(
            prom_products
        )
    )

    updates = build_updates(
        prom_by_sku,
        duplicate_skus,
        horoshop_products,
    )

    successful_ids, errors = (
        send_updates(updates)
    )

    print()
    print("=" * 60)
    print("PROM UPDATE FINISHED")
    print("=" * 60)

    print(
        "Products sent:",
        len(updates)
    )

    print(
        "Successfully processed:",
        len(successful_ids)
    )

    print(
        "Products with errors:",
        len(errors)
    )

    if errors:

        print()
        print("ERRORS:")

        for product_id, error in errors.items():

            print(
                product_id,
                error
            )

    print()
    print("=" * 60)

    print(
        "SAFETY RULE:"
    )

    print(
        "Unavailable products: "
        "ONLY presence is updated."
    )

    print(
        "Their price and oldprice "
        "are NEVER sent to Prom."
    )

    print("=" * 60)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
