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

PROM_LIST_URL = "https://my.prom.ua/api/v1/products/list"
PROM_EDIT_URL = "https://my.prom.ua/api/v1/products/edit_by_external_id"

PROM_API_TOKEN = os.environ["PROM_API_TOKEN"]

# Скільки товарів відправляємо одним запитом.
# Робимо невеликі пачки для безпеки.
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
    except ValueError:
        return None


# ============================================================
# PROM HEADERS
# ============================================================

def prom_headers():
    return {
        "Authorization": f"Bearer {PROM_API_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ============================================================
# DOWNLOAD ALL PROM PRODUCTS
# ============================================================

def get_prom_products():

    print()
    print("=" * 60)
    print("DOWNLOADING PROM PRODUCTS")
    print("=" * 60)

    products = []
    last_id = None

    while True:

        params = {
            "limit": 100,
        }

        if last_id is not None:
            params["last_id"] = last_id

        response = requests.get(
            PROM_LIST_URL,
            headers=prom_headers(),
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

    print()
    print("TOTAL PROM PRODUCTS:", len(products))

    return products


# ============================================================
# DOWNLOAD HOROSHOP
# ============================================================

def get_horoshop_products():

    print()
    print("=" * 60)
    print("DOWNLOADING HOROSHOP")
    print("=" * 60)

    response = requests.get(
        HOROSHOP_URL,
        timeout=60,
    )

    response.raise_for_status()

    root = etree.fromstring(response.content)

    products = {}

    for offer in root.xpath(".//offer"):

        sku = normalize_code(
            get_text(offer, "vendorCode")
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
# CREATE PROM SKU INDEX
# ============================================================

def create_prom_index(prom_products):

    prom_by_sku = {}

    duplicates = set()

    no_sku = 0

    for product in prom_products:

        sku = normalize_code(
            product.get("sku")
        )

        if not sku:
            no_sku += 1
            continue

        if sku in prom_by_sku:
            duplicates.add(sku)
            continue

        prom_by_sku[sku] = product

    print()
    print("=" * 60)
    print("PROM INDEX")
    print("=" * 60)

    print(
        "Products with SKU:",
        len(prom_by_sku)
    )

    print(
        "Products without SKU:",
        no_sku
    )

    print(
        "Duplicate SKU:",
        len(duplicates)
    )

    if duplicates:
        print(
            "Duplicate SKU skipped:",
            sorted(duplicates)
        )

    return prom_by_sku, duplicates


# ============================================================
# PREPARE UPDATES
# ============================================================

def prepare_updates(
    prom_by_sku,
    duplicates,
    horoshop_products,
):

    updates = []

    matched = 0
    missing_horoshop = 0
    missing_external_id = 0
    duplicate_skipped = 0

    print()
    print("=" * 60)
    print("PREPARING PROM UPDATES")
    print("=" * 60)

    for sku, prom_product in prom_by_sku.items():

        # ----------------------------------------------------
        # DUPLICATE SKU
        # ----------------------------------------------------

        if sku in duplicates:

            duplicate_skipped += 1

            continue

        # ----------------------------------------------------
        # FIND SAME SKU IN HOROSHOP
        # ----------------------------------------------------

        horoshop_offer = horoshop_products.get(
            sku
        )

        # Товар є на Prom, але його немає в Horoshop.
        #
        # НІЧОГО З НИМ НЕ РОБИМО.
        #
        # Не вимикаємо.
        # Не видаляємо.
        # Не змінюємо.
        if horoshop_offer is None:

            missing_horoshop += 1

            continue

        # ----------------------------------------------------
        # EXTERNAL ID
        # ----------------------------------------------------

        external_id = clean(
            prom_product.get("external_id")
        )

        if not external_id:

            print(
                f"SKIP {sku}: "
                "Prom external_id is empty"
            )

            missing_external_id += 1

            continue

        # ----------------------------------------------------
        # PRICE
        # ----------------------------------------------------

        price = parse_price(
            get_text(
                horoshop_offer,
                "price",
            )
        )

        oldprice = parse_price(
            get_text(
                horoshop_offer,
                "oldprice",
            )
        )

        if price is None:

            print(
                f"SKIP {sku}: "
                "Horoshop price is empty"
            )

            continue

        # ----------------------------------------------------
        # AVAILABILITY
        # ----------------------------------------------------

        available_raw = clean(
            horoshop_offer.get("available")
        ).lower()

        is_available = (
            available_raw
            in (
                "true",
                "1",
                "yes",
            )
        )

        presence = (
            "available"
            if is_available
            else "not_available"
        )

        # ----------------------------------------------------
        # UPDATE OBJECT
        #
        # IMPORTANT:
        # id here = PROM EXTERNAL_ID
        #
        # NOT internal Prom product ID.
        # ----------------------------------------------------

        item = {
            "id": external_id,
            "price": price,
            "presence": presence,
        }

        # ----------------------------------------------------
        # OLD PRICE / DISCOUNT
        # ----------------------------------------------------

        if (
            oldprice is not None
            and oldprice > price
        ):

            item["oldprice"] = oldprice

        else:

            # 0 прибирає стару перекреслену ціну,
            # якщо акція на Horoshop вже закінчилася.
            item["oldprice"] = 0

        updates.append(item)

        matched += 1

    print()
    print("Matched products:", matched)

    print(
        "Prom SKU missing in Horoshop:",
        missing_horoshop
    )

    print(
        "Missing external_id:",
        missing_external_id
    )

    print(
        "Duplicate SKU skipped:",
        duplicate_skipped
    )

    return updates


# ============================================================
# SEND ONE BATCH TO PROM
# ============================================================

def send_batch(batch, batch_number):

    print()
    print(
        f"Sending batch #{batch_number}: "
        f"{len(batch)} products"
    )

    response = requests.post(
        PROM_EDIT_URL,
        headers=prom_headers(),
        json=batch,
        timeout=60,
    )

    print(
        "HTTP:",
        response.status_code
    )

    if response.status_code not in (
        200,
        201,
        202,
    ):

        print()
        print("PROM ERROR:")
        print(response.text)

        response.raise_for_status()

    try:

        result = response.json()

        print(
            "Prom response:",
            result
        )

    except ValueError:

        print(
            "Prom response:",
            response.text
        )

    return True


# ============================================================
# SEND ALL UPDATES
# ============================================================

def send_updates(updates):

    print()
    print("=" * 60)
    print("UPDATING PROM")
    print("=" * 60)

    if not updates:

        print("Nothing to update.")

        return

    total = len(updates)

    success = 0

    batch_number = 0

    for start in range(
        0,
        total,
        BATCH_SIZE,
    ):

        batch_number += 1

        batch = updates[
            start:start + BATCH_SIZE
        ]

        send_batch(
            batch,
            batch_number,
        )

        success += len(batch)

        print(
            f"Progress: "
            f"{success}/{total}"
        )

        # Невелика пауза між запитами
        time.sleep(0.5)

    print()
    print("=" * 60)
    print("PROM UPDATE FINISHED")
    print("=" * 60)

    print(
        "Products sent:",
        success
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print("CATPAWS -> PROM API SYNC")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. PROM
    # --------------------------------------------------------

    prom_products = get_prom_products()

    # --------------------------------------------------------
    # 2. HOROSHOP
    # --------------------------------------------------------

    horoshop_products = (
        get_horoshop_products()
    )

    # --------------------------------------------------------
    # 3. PROM SKU INDEX
    # --------------------------------------------------------

    (
        prom_by_sku,
        duplicates,
    ) = create_prom_index(
        prom_products
    )

    # --------------------------------------------------------
    # 4. MATCH BY OUR SKU
    # --------------------------------------------------------

    updates = prepare_updates(
        prom_by_sku,
        duplicates,
        horoshop_products,
    )

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("SAFETY CHECK")
    print("=" * 60)

    print(
        "Prom products:",
        len(prom_products)
    )

    print(
        "Horoshop products:",
        len(horoshop_products)
    )

    print(
        "Products prepared:",
        len(updates)
    )

    # Захист від випадкової масової помилки.
    if len(updates) == 0:

        raise RuntimeError(
            "SAFETY STOP: "
            "0 matched products."
        )

    # --------------------------------------------------------
    # 5. UPDATE PROM
    # --------------------------------------------------------

    send_updates(updates)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
