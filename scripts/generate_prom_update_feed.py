import os
import math
from datetime import datetime
from zoneinfo import ZoneInfo
import time
import requests
from lxml import etree
from generate_feed import DISCONTINUED_SKUS, FORCE_ZERO_SKUS, is_modes_bowl

# Also disable existing Prom cards after the site stops exporting them.
SITE_ONLY_MODES_SKUS = {"ACRC(W)-1 bronze","ACRC(W)-4 bronze","ACRC(W)-4 golden","ACRC(W)-8 bronze","ACRC(W)-8 golden","ASB(MBF)--24 Oz","ASB(MBF)--32 Oz","ASB(MBF)--64 Oz","ASB(MBF)--96 Oz","ASB(W)-08 Oz","ASB(W)-16 Oz","ASB(W)-24 Oz","ASBH(S)-24 Oz","ASBPP-24 oz violet","ASR(CB)-16 Oz","ASR(CB)-24 Oz","ASR(CB)-32 Oz","ASR(CB)-64 Oz","ASR(CB)-96 Oz","ASR(DST)-16 Oz black","ASR(DST)-24 Oz black","ASR(DST)-32 Oz green","ASR(DST)-64 Oz green","ASR(DST)-96 Oz green","ASR(ETD)-16 oz","ASR(ETD)-24 oz","ASR(ETD)-32 oz","ASR(GMS1)-16 Oz","ASR(SP)-16 Oz","ASR(TRST)-24 Oz","ASR(TRST)-32 Oz","ASR(TRST)-64 Oz","ASR(TRST)-96 Oz","ASR-64 oz","ASR-96 oz","ASR2P(SLE)-24 Oz dual blue","ASR2P(SLE)-32 Oz dual blue","ASR2P(SLE)-64 Oz dual blue","ASR2P(SLE)-96 Oz dual blue","ASRP(FP)-24 Oz black/white","ASRP(FP)-32 Oz black/white","ASRP(M)-24 oz (Bone) black","ASRP(M)-64 oz (Bone) red","ASRP(SLE)- 64 oz violet","ASRP(SLE)- 96 oz violet","ASRP(SLE-C)- 16 oz","ASRP(SLE-C)- 24 oz","ASRP(SLE-C)- 32 oz","ASRP(SLE-C)- 64 oz","ASRP(SLE-C)- 96 oz","ASRP(SLT)- 16 oz blue","ASRP(SLT)- 24 oz blue","ASRP(SLT)- 32 oz blue","ASRP(SLT)- 64 oz blue","ASRP(SLT)- 96 oz blue","ASWT(ETD)-16","ASWT(ETD)-32","ASWTP2P(ST)-32 Oz black","ASWTP2P(ST)-64 Oz black","CCC-CP- 64 oz","CCH-CP- 48 oz","CCH-CP- 96 oz","CDBX(W)","DDBXT(TFM)-1/2 Pt","DDWF-PC-SL-2Qt","DDWF-PC-SL-3Qt","DDWF2B-CP-3 Qt","DDWF2B-RS-3 Qt","FBHD(NS)- 1 Qt","FBR(CB)- 2Qt","FBR(CB)- 3Qt","FBR(CB)- 5Qt","FBR(CNS)-1 Qt","HDE(C)-17","HDE(C)-21","HDN(LP)- 14 golden","HDN(LP)- 17 golden","HDN(LP)- 21 blue","HDN(LP)- 24 red","HDN(MB)- 17","HDN(MB)- 21","HDN(MB)- 24","PF-29"}



# ============================================================
# SETTINGS
# ============================================================

# Unfiltered Prom export created on 2026-10-14, with daily autogeneration.
# All currently exported brands use one authoritative source.
HOROSHOP_URL = "https://catpaws.com.ua/content/export/9ba864d51aeb3249ffc3b374be058b88.xml"

RAFI_SOURCE_URL = (
    "https://catpaws.com.ua/content/export/"
    "3e9c244f28ee6d1e572f92646e76f6bb.xml"
)

PROM_API_LIST_URL = "https://my.prom.ua/api/v1/products/list"
PROM_API_EDIT_URL = "https://my.prom.ua/api/v1/products/edit"

PROM_API_TOKEN = os.environ["PROM_API_TOKEN"]

BATCH_SIZE = 50
MIN_SOURCE_PRODUCTS = 2000
# Both cards were checked in the Prom cabinet on 2026-10-14: same feed SKU,
# same JosiDog recipe and 2.7 kg pack. Unknown duplicate groups still stop.
CONFIRMED_DUPLICATE_IDS = {
    "50013180": {3157113607, 2980324957},
    "50013181": {3157113608, 2985134061},
    "50013184": {3157113613, 2979412910},
}


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
        price = float("".join(value.split()).replace(",", "."))
        return price if math.isfinite(price) else None
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
    seen_pages = set()

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

        if not isinstance(data, dict) or not isinstance(data.get("products"), list):
            raise RuntimeError("Invalid Prom product list response")
        batch = data["products"]

        if not batch:
            break

        page_ids = tuple(p.get("id") for p in batch)
        if page_ids in seen_pages:
            raise RuntimeError("Prom pagination repeated a page")
        seen_pages.add(page_ids)
        products.extend(batch)

        print(
            "Downloaded Prom products:",
            len(products)
        )

        if len(batch) < 100:
            break

        last_id = batch[-1].get("id")

        if not last_id:
            raise RuntimeError("Prom pagination cursor missing")

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
    validate_source_freshness(root)

    products = {}
    duplicate_skus = set()

    for offer in root.xpath(".//offer"):

        sku = normalize_code(
            get_text(
                offer,
                "vendorCode"
            )
        )

        if not sku:
            continue

        if sku in products:
            duplicate_skus.add(sku)
        products[sku] = offer

    for sku in duplicate_skus:
        products.pop(sku, None)
    print("Ambiguous source SKUs skipped:", sorted(duplicate_skus))

    print(
        "Horoshop products:",
        len(products)
    )

    if len(products) < MIN_SOURCE_PRODUCTS:
        raise RuntimeError("Full Horoshop source is empty or incomplete; refusing synchronization")

    return products


def validate_source_freshness(root):
    value = root.get("date")
    try:
        generated = datetime.strptime(value, "%Y-%m-%d %H:%M").replace(
            tzinfo=ZoneInfo("Europe/Kyiv"))
    except (ValueError, TypeError):
        raise RuntimeError("Horoshop export has no valid generation timestamp")
    age_hours = (datetime.now(ZoneInfo("Europe/Kyiv")) - generated).total_seconds() / 3600
    print("Horoshop export generated:", value, "age hours:", round(age_hours, 2))
    if age_hours > 36 or age_hours < -1:
        raise RuntimeError("Horoshop export is stale or future-dated; refusing outdated prices/promotions")


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

def normalize_product_name(value):
    # Normalize punctuation and 2,7/2.7 notation only; do not fuzzy-match titles.
    return "".join(ch for ch in clean(value).casefold() if ch.isalnum())


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
            prom_by_sku[sku].setdefault("_duplicate_cards", []).append(product)

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
    verified_duplicate_groups = {}
    missing_items = []

    for sku, prom_product in prom_by_sku.items():

        # ----------------------------------------------------
        # DUPLICATE SKU
        #
        # Не чіпаємо взагалі.
        # ----------------------------------------------------

        if sku in duplicate_skus:
            cards = [prom_product] + prom_product.get("_duplicate_cards", [])
            source = horoshop_products.get(sku)
            source_names = set() if source is None else {
                normalize_product_name(get_text(source, field))
                for field in ("name", "name_ua")
                if get_text(source, field)
            }
            verified = (
                {p.get("id") for p in cards} == CONFIRMED_DUPLICATE_IDS.get(sku)
                and len(cards) == len(CONFIRMED_DUPLICATE_IDS[sku])
                and all(normalize_product_name(p.get("name")) in source_names for p in cards)
            )
            if not verified:
                skipped_duplicates += 1
                continue
            verified_duplicate_groups[sku] = cards

        # ----------------------------------------------------
        # REAL PROM PRODUCT ID
        # ----------------------------------------------------

        prom_id = prom_product.get("id")

        if not prom_id:
            continue

        if (
            sku in SITE_ONLY_MODES_SKUS
            or sku in DISCONTINUED_SKUS
            or sku in FORCE_ZERO_SKUS
        ):
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
            missing_items.append({"sku": sku, "id": prom_id,
                                  "external_id": prom_product.get("external_id")})
            # The source is now an unfiltered, size-validated full site export.
            # Missing cards are hidden/deleted on the site or use obsolete SKUs;
            # stop selling them on Prom, retaining their price/content.
            updates.append({"id": prom_id, "presence": "not_available"})
            unavailable_count += 1

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
            # Prom also documents equal price/oldprice as a reset.
            # Use it for available goods, retaining null for unavailable goods.
            item["oldprice"] = price

        updates.append(item)

        available_count += 1

    by_id = {item["id"]: item for item in updates}
    for sku, cards in verified_duplicate_groups.items():
        template = by_id.get(cards[0]["id"])
        if template is None:
            continue
        for card in cards[1:]:
            updates.append({**template, "id": card["id"]})
            if template["presence"] == "available":
                available_count += 1
            else:
                unavailable_count += 1
    print("Verified duplicate groups synchronized:", sorted(verified_duplicate_groups))

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
    print("Products absent from full site export (disabled on Prom):", missing_items)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and (missing_items or duplicate_skus):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"Source coverage: {missing_horoshop} unmatched SKUs; "
                         f"{skipped_duplicates} duplicate SKUs skipped.\n")
            handle.write(f"Unmatched SKU/IDs: {missing_items}\n")
            handle.write(f"Duplicate SKUs: {sorted(duplicate_skus)}\n")

    return updates


# ============================================================
# SEND UPDATES TO PROM
# ============================================================

def prices_equal(left, right):
    left, right = parse_price(left), parse_price(right)
    return (left is not None and right is not None
            and math.isfinite(left) and math.isfinite(right)
            and abs(left - right) <= 0.011)


def discount_amount(product):
    discount = product.get("discount")
    if not discount:
        return 0.0
    value = parse_price(discount.get("value"))
    if value is None:
        return None
    if discount.get("type") == "percent":
        base = parse_price(product.get("price"))
        return None if base is None else base * value / 100
    if discount.get("type") == "amount":
        return value
    return None


def discount_is_current(discount):
    if not discount:
        return False
    today = datetime.now(ZoneInfo("Europe/Kyiv")).date()
    for field, boundary in (("date_start", "start"), ("date_end", "end")):
        value = discount.get(field)
        if value:
            try:
                day = datetime.strptime(value, "%d.%m.%Y").date()
            except (ValueError, TypeError):
                return False
            if (boundary == "start" and day > today) or (boundary == "end" and day < today):
                return False
    return True


def state_mismatches(item, product):
    if product is None:
        return ["product missing from API readback"]
    failures = []
    if "presence" in item and product.get("presence") != item["presence"]:
        failures.append("presence")
    # Prom stores the regular price plus a discount, while oldprice requests
    # contain a discounted price and the regular price separately.
    expected_base = item.get("oldprice", item.get("price"))
    if expected_base is not None and not prices_equal(product.get("price"), expected_base):
        failures.append("price")
    if "oldprice" in item:
        expected_discount = item["oldprice"] - item["price"]
        if not prices_equal(discount_amount(product), expected_discount):
            failures.append("discount")
        elif expected_discount > 0 and not discount_is_current(product.get("discount")):
            failures.append("discount dates")
    elif "discount" in item and item["discount"] is None:
        if product.get("discount") is not None:
            failures.append("discount")
    return failures


def post_batch(batch):
    response = requests.post(
        PROM_API_EDIT_URL,
        headers={"Authorization": f"Bearer {PROM_API_TOKEN}",
                 "Content-Type": "application/json"},
        json=batch, timeout=60,
    )
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Prom returned a non-object update response")
    print("Prom acknowledgment:", len(result.get("processed_ids", [])),
          "errors:", result.get("errors", {}),
          "warnings:", result.get("warnings", {}))
    return result


def readback(updates):
    products = {str(p["id"]): p for p in get_prom_products()}
    states = {str(item["id"]): state_mismatches(item, products.get(str(item["id"])))
              for item in updates}
    shown = 0
    for item in updates:
        product = products.get(str(item["id"]), {})
        control = normalize_code(product.get("sku")) in {"653651", "5578", "018197", "7000008"}
        if control or (states[str(item["id"])] and shown < 10):
            print("Readback detail:", {"sku": product.get("sku"), "expected": item,
                  "actual": {key: product.get(key) for key in ("id", "price", "presence", "discount")}})
            shown += 1
    return states


def send_updates(updates, initial_products):
    initial = {str(p["id"]): p for p in initial_products}
    changed = [item for item in updates
               if state_mismatches(item, initial.get(str(item["id"])))]
    print("Already matching:", len(updates) - len(changed))
    print("Products needing changes:", len(changed))
    for start in range(0, len(changed), BATCH_SIZE):
        post_batch(changed[start:start + BATCH_SIZE])
        time.sleep(0.5)

    # A 200 response is not proof of a write. Read actual states even when
    # processed_ids is empty, and count already-matching goods separately.
    states = readback(updates)
    pending = [item for item in updates if states[str(item["id"])]]
    if pending:
        print("Readback mismatches, retrying:",
              {str(item["id"]): states[str(item["id"])] for item in pending})
        time.sleep(2)
        for start in range(0, len(pending), BATCH_SIZE):
            post_batch(pending[start:start + BATCH_SIZE])
            time.sleep(0.5)
        states = readback(updates)

    errors = {pid: fields for pid, fields in states.items() if fields}
    verified = [item["id"] for item in updates if not states[str(item["id"])]]
    print("Verified actual Prom states:", len(verified), "/", len(updates))
    for sku in ("653651", "5578", "018197", "7000008"):
        for product in initial_products:
            if normalize_code(product.get("sku")) == sku:
                print("Control SKU", sku, "ID", product["id"],
                      "readback:", states.get(str(product["id"]), "not in source"))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("## Prom synchronization\n")
            handle.write(f"Verified: {len(verified)}/{len(updates)}. "
                         f"Changed requests: {len(changed)}. "
                         f"Mismatches: {len(errors)}.\n")
            if errors:
                handle.write(f"Unconfirmed product IDs/fields: {errors}\n")
    return verified, errors


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
        send_updates(updates, prom_products)
    )

    print()
    print("=" * 60)
    print("PROM UPDATE FINISHED")
    print("=" * 60)

    print(
        "Products checked:",
        len(updates)
    )

    print(
        "Verified matching products:",
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

    if errors:
        raise RuntimeError(f"Prom state verification failed for {len(errors)} products")

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



