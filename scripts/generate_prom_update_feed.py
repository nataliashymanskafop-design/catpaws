import os
import time
import requests
from lxml import etree
from generate_feed import is_modes_bowl

# Also disable existing Prom cards after the site stops exporting them.
SITE_ONLY_MODES_SKUS = {"ACRC(W)-1 bronze","ACRC(W)-4 bronze","ACRC(W)-4 golden","ACRC(W)-8 bronze","ACRC(W)-8 golden","ASB(MBF)--24 Oz","ASB(MBF)--32 Oz","ASB(MBF)--64 Oz","ASB(MBF)--96 Oz","ASB(W)-08 Oz","ASB(W)-16 Oz","ASB(W)-24 Oz","ASBH(S)-24 Oz","ASBPP-24 oz violet","ASR(CB)-16 Oz","ASR(CB)-24 Oz","ASR(CB)-32 Oz","ASR(CB)-64 Oz","ASR(CB)-96 Oz","ASR(DST)-16 Oz black","ASR(DST)-24 Oz black","ASR(DST)-32 Oz green","ASR(DST)-64 Oz green","ASR(DST)-96 Oz green","ASR(ETD)-16 oz","ASR(ETD)-24 oz","ASR(ETD)-32 oz","ASR(GMS1)-16 Oz","ASR(SP)-16 Oz","ASR(TRST)-24 Oz","ASR(TRST)-32 Oz","ASR(TRST)-64 Oz","ASR(TRST)-96 Oz","ASR-64 oz","ASR-96 oz","ASR2P(SLE)-24 Oz dual blue","ASR2P(SLE)-32 Oz dual blue","ASR2P(SLE)-64 Oz dual blue","ASR2P(SLE)-96 Oz dual blue","ASRP(FP)-24 Oz black/white","ASRP(FP)-32 Oz black/white","ASRP(M)-24 oz (Bone) black","ASRP(M)-64 oz (Bone) red","ASRP(SLE)- 64 oz violet","ASRP(SLE)- 96 oz violet","ASRP(SLE-C)- 16 oz","ASRP(SLE-C)- 24 oz","ASRP(SLE-C)- 32 oz","ASRP(SLE-C)- 64 oz","ASRP(SLE-C)- 96 oz","ASRP(SLT)- 16 oz blue","ASRP(SLT)- 24 oz blue","ASRP(SLT)- 32 oz blue","ASRP(SLT)- 64 oz blue","ASRP(SLT)- 96 oz blue","ASWT(ETD)-16","ASWT(ETD)-32","ASWTP2P(ST)-32 Oz black","ASWTP2P(ST)-64 Oz black","CCC-CP- 64 oz","CCH-CP- 48 oz","CCH-CP- 96 oz","CDBX(W)","DDBXT(TFM)-1/2 Pt","DDWF-PC-SL-2Qt","DDWF-PC-SL-3Qt","DDWF2B-CP-3 Qt","DDWF2B-RS-3 Qt","FBHD(NS)- 1 Qt","FBR(CB)- 2Qt","FBR(CB)- 3Qt","FBR(CB)- 5Qt","FBR(CNS)-1 Qt","HDE(C)-17","HDE(C)-21","HDN(LP)- 14 golden","HDN(LP)- 17 golden","HDN(LP)- 21 blue","HDN(LP)- 24 red","HDN(MB)- 17","HDN(MB)- 21","HDN(MB)- 24","PF-29"}



# ============================================================
# SETTINGS
# ============================================================

HOROSHOP_URL = (
    "https://catpaws.com.ua/content/export/"
    "77e6f1cd306feb32b68e245d1affc6bc.xml"
)

RAFI_SOURCE_URL = (
    "https://catpaws.com.ua/content/export/"
    "3e9c244f28ee6d1e572f92646e76f6bb.xml"
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
        return float("".join(value.split()).replace(",", "."))
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


def get_rafi_skus():

    print("Downloading RAFI exclusion list...")

    response = requests.get(
        RAFI_SOURCE_URL,
        timeout=60,
    )

    response.raise_for_status()

    root = etree.fromstring(
        response.content
    )

    rafi_skus = set()

    for offer in root.xpath(".//offer"):

        vendor = get_text(
            offer,
            "vendor"
        ).casefold()

        if vendor != "rafi":
            continue

        sku = normalize_code(
            get_text(
                offer,
                "vendorCode"
            )
        )

        if sku:
            rafi_skus.add(sku)

    print("RAFI products to disable:", len(rafi_skus))

    return rafi_skus


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
    rafi_skus,
):

    updates = []

    unavailable_count = 0
    available_count = 0
    missing_horoshop = 0
    skipped_duplicates = 0
    rafi_count = 0

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
        # REAL PROM PRODUCT ID
        # ----------------------------------------------------

        prom_id = prom_product.get("id")

        if not prom_id:
            continue

        if sku in SITE_ONLY_MODES_SKUS:
            updates.append({"id": prom_id, "presence": "not_available"})
            unavailable_count += 1
            continue

        # RAFI прибираємо з продажу на Prom, навіть якщо позиція вже
        # відсутня в основному Horoshop-фіді. Ціну при цьому не змінюємо.
        if sku in rafi_skus:

            updates.append({
                "id": prom_id,
                "presence": "not_available",
            })

            unavailable_count += 1
            rafi_count += 1

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
        # AVAILABILITY
        # ----------------------------------------------------

        available_raw = clean(
            horoshop_offer.get("available")
        ).lower()

        available = (
            not is_modes_bowl(horoshop_offer)
            and available_raw
            in (
                "true",
                "1",
                "yes",
            )
        )

        price = parse_price(get_text(horoshop_offer, "price"))
        oldprice_text = get_text(horoshop_offer, "oldprice")
        oldprice = parse_price(oldprice_text)
        valid_price = price is not None and price > 0
        has_discount = (
            valid_price and oldprice is not None and oldprice > price
        )
        # Omitted fields leave an existing Prom discount unchanged.
        # The documented API reset is discount=null, not oldprice=0.
        # A malformed source must not accidentally clear an active discount.
        clear_discount = (
            valid_price
            and (not oldprice_text or oldprice is not None)
            and not has_discount
        )

        # Unavailable products keep their base price. Expired discounts
        # still need clearing so they cannot reappear when stock returns.

        if not available:

            item = {
                "id": prom_id,
                "presence": "not_available",
            }
            if clear_discount:
                item["discount"] = None

            updates.append(item)

            unavailable_count += 1

            continue

        # ====================================================
        # PRODUCT IS AVAILABLE
        #
        # Тільки тут дозволено працювати з ціною.
        # ====================================================

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
        # Коли акції немає, явно видаляємо попередню знижку Prom.
        # discount та oldprice не можна передавати разом.
        # ----------------------------------------------------

        if has_discount:

            item["oldprice"] = oldprice
        elif clear_discount:
            item["discount"] = None

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
        "RAFI products disabled:",
        rafi_count
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

    rafi_skus = get_rafi_skus()

    prom_by_sku, duplicate_skus = (
        prepare_prom_products(
            prom_products
        )
    )

    updates = build_updates(
        prom_by_sku,
        duplicate_skus,
        horoshop_products,
        rafi_skus,
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
        "base price is preserved; ended discounts are cleared."
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
