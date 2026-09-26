import json
import os
from datetime import timedelta

from lxml import etree

from generate_home_food_stock import (
    PRODUCT_UPDATE_URL,
    api_json,
    download,
    fetch_orders,
    format_api_time,
    now_kyiv,
    parse_api_time,
)


CATALOG_XML_URL = (
    "https://catpaws.com.ua/content/export/"
    "3e9c244f28ee6d1e572f92646e76f6bb.xml"
)

OUTPUT_FILE = "public/doms-stock.yml"
STATE_FILE = "public/doms-stock-state.json"

# У замовленні №2527 товар 018128 вручну призначений на склад
# "ДОМС-ТРЕЙД - Святопетрівське". Перший запуск використовує це
# замовлення тільки для визначення числового ID складу.
BOOTSTRAP_ORDER_ID = 2527

WAREHOUSE_VARIABLE = "SALESDRIVE_DOMS_STOCK_ID"

# Звичайні товари: умовний залишок 20. Коли залишається 5 або менше,
# скрипт відновлює умовний залишок до 20.
DEFAULT_TARGET = 20
DEFAULT_THRESHOLD = 5

# Консерви рахуються як спільний запас одиничних банок і блоків:
# 60 банок = 10 блоків по 6. Продаж блока віднімає 6 банок.
CAN_TARGET = 60
CAN_THRESHOLD = 12


ALLOWED_BRANDS = {
    "chicopee",
    "homie",
    "clearcat",
    "catroyale",
    "catmat",
    "gattino",
}


# Усі товарні артикули з файла "Залишки на 16.09.2026.xls".
# Якщо товар дозволеного бренду відсутній у цьому списку, його залишок
# на складі Святопетрівське дорівнює нулю. Виняток: усі товари Homie
# вважаються наявними та отримують умовний залишок.
SUPPLIER_SKUS = {
    "023696", "023702", "019200", "019309", "018982", "019088",
    "018968", "019064", "019026", "019125", "019040", "019149",
    "015110", "015134", "015172", "015196", "015219", "015233",
    "015257", "024952", "024969", "024990", "8025003", "015318",
    "015332", "015370", "015394", "015417", "015455", "023573",
    "023580", "023009", "023016", "022972", "022989", "015516",
    "015530", "015592", "015615", "015639", "015653", "015554",
    "015578", "014366", "014373", "014380", "014397", "017916",
    "017978", "017985", "018036", "018043", "017947", "017954",
    "024624", "020640", "020671", "020695", "020718", "018128",
    "018135", "018098", "018104", "018180", "018197", "026536",
    "018159", "018166", "023061", "023078", "0242281", "024228",
    "0034451", "003445", "0030631", "003063", "0034141", "003414",
    "0033391", "003339", "76144186", "76144193", "76144100",
    "144117", "76144124", "144131", "76144148", "144155",
    "76144162", "144179", "368235", "368204", "368211", "368259",
    "244215", "653651", "653606", "653644", "653637", "653620",
    "653613", "011112", "011110", "011111", "011117", "011115",
    "011116", "011120", "000822", "000823",
}


# У Horoshop ці товари мають старі артикули, а в SalesDrive/DOMS — нові.
# Усередині стану і DOMS YML зберігаємо артикул сайту, щоб Mono правильно
# зіставляв залишок із товарним фідом. У запитах до SalesDrive використовуємо
# новий артикул, а артикули із замовлень переводимо назад у код сайту.
SUPPLIER_SKU_ALIASES = {
    "144100": "76144100",
    "144124": "76144124",
    "144148": "76144148",
    "144162": "76144162",
    "144186": "76144186",
    "144193": "76144193",
    "368215": "244215",
}

FORCE_ZERO_SKUS = {
    "368208",
    "368228",
    "368242",
}

SALESDRIVE_TO_SITE_SKU = {
    salesdrive_sku: site_sku
    for site_sku, salesdrive_sku
    in SUPPLIER_SKU_ALIASES.items()
}


# Блок консервів -> (артикул одиничної банки, банок у блоці).
# У SalesDrive і на сайті це окремі артикули, але запас у них спільний.
PACKS = {
    "023702": ("023696", 6),
    "019309": ("019200", 6),
    "019088": ("018982", 6),
    "019064": ("018968", 6),
    "019125": ("019026", 6),
    "019149": ("019040", 6),
}

CAN_BASE_SKUS = {base_sku for base_sku, _ in PACKS.values()}


def clean(value):
    return " ".join(str(value or "").split())


def normalize_sku(value):
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_brand(value):
    return "".join(
        character
        for character in clean(value).casefold()
        if character.isalnum()
    )


def supplier_sku(sku):
    return SUPPLIER_SKU_ALIASES.get(sku, sku)


def site_sku(sku):
    return SALESDRIVE_TO_SITE_SKU.get(sku, sku)


def load_site_catalog():
    root = etree.fromstring(download(CATALOG_XML_URL))
    catalog = {}

    for offer in root.xpath(".//offer"):
        sku = normalize_sku(offer.findtext("vendorCode"))
        name = clean(offer.findtext("name"))
        brand = normalize_brand(offer.findtext("vendor"))

        if sku and name:
            catalog[sku] = {
                "name": name,
                "brand": brand,
            }

    return catalog


def build_product_catalog(site_catalog):
    products = {}

    for sku, item in site_catalog.items():
        if sku in SUPPLIER_SKUS or item["brand"] in ALLOWED_BRANDS:
            products[sku] = item

    return products


def base_skus(products):
    return set(products) - set(PACKS)


def stock_policy(sku, item):
    if sku in FORCE_ZERO_SKUS:
        return 0, 0, "zero"

    # Homie постачальник підтвердив як наявний, навіть якщо його немає
    # у файлі залишків.
    if item["brand"] == "homie":
        return DEFAULT_TARGET, DEFAULT_THRESHOLD, "available"

    # Якщо XML Horoshop ще містить старий артикул, перевіряємо
    # наявність за актуальним артикулом постачальника.
    if supplier_sku(sku) not in SUPPLIER_SKUS:
        return 0, 0, "zero"

    if sku in CAN_BASE_SKUS:
        return CAN_TARGET, CAN_THRESHOLD, "available"

    return DEFAULT_TARGET, DEFAULT_THRESHOLD, "available"


def calculate_stock(sku, base_stock):
    if sku in PACKS:
        base_sku, pack_size = PACKS[sku]
        return max(
            0,
            int(base_stock.get(base_sku, 0)) // pack_size,
        )

    return max(
        0,
        int(base_stock.get(sku, 0)),
    )


def materialize_stock(products, base_stock):
    return {
        sku: calculate_stock(sku, base_stock)
        for sku in products
    }


def initial_base_stock(products):
    result = {}
    policies = {}

    for sku in base_skus(products):
        target, _, policy = stock_policy(
            sku,
            products[sku],
        )
        result[sku] = target
        policies[sku] = policy

    return result, policies


def direct_order_snapshot(order, warehouse_id, products):
    snapshot = {}

    for item in order.get("products") or []:
        if int(item.get("stockId") or 0) != warehouse_id:
            continue

        sku = site_sku(
            normalize_sku(item.get("sku"))
        )

        if sku not in products:
            continue

        amount = int(float(item.get("amount") or 0))

        if amount > 0:
            snapshot[sku] = snapshot.get(sku, 0) + amount

    return snapshot


def find_warehouse_id(state, orders, products):
    configured = os.environ.get(
        WAREHOUSE_VARIABLE,
        "",
    ).strip()

    if configured:
        return int(configured)

    if state and state.get("warehouse_id"):
        return int(state["warehouse_id"])

    for order in orders:
        if int(order.get("id") or 0) != BOOTSTRAP_ORDER_ID:
            continue

        for item in order.get("products") or []:
            sku = site_sku(
            normalize_sku(item.get("sku"))
        )
            stock_id = item.get("stockId")

            if sku in products and stock_id:
                return int(stock_id)

    raise RuntimeError(
        "Could not determine DOMS warehouse ID from order #2527. "
        f"Set repository variable {WAREHOUSE_VARIABLE}."
    )


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if state.get("version") != 1:
        return None

    return state


def save_state(state):
    os.makedirs(
        os.path.dirname(STATE_FILE),
        exist_ok=True,
    )

    temporary = f"{STATE_FILE}.tmp"

    with open(
        temporary,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    os.replace(
        temporary,
        STATE_FILE,
    )


def expand_consumption(sku, amount):
    if sku in PACKS:
        base_sku, pack_size = PACKS[sku]

        return {
            base_sku: amount * pack_size,
        }

    return {
        sku: amount,
    }


def apply_order_changes(
    products,
    warehouse_id,
    orders,
    state,
):
    base_stock = {}
    previous_policies = state.get(
        "supplier_policies",
        {},
    )

    for sku in base_skus(products):
        target, _, policy = stock_policy(
            sku,
            products[sku],
        )

        current = int(
            state.get(
                "base_stock",
                {},
            ).get(
                sku,
                target,
            )
        )

        if target == 0:
            current = 0
        elif current > target:
            current = target
        elif (
            previous_policies.get(sku) == "zero"
            and current == 0
        ):
            # Товар раніше був відсутній, але тепер знайдений
            # у залишках постачальника.
            current = target

        base_stock[sku] = current

    snapshots = state.get(
        "order_snapshots",
        {},
    )
    direct_deltas = {}

    for order in orders:
        order_id = str(order.get("id"))
        previous = snapshots.get(
            order_id,
            {},
        )
        current = direct_order_snapshot(
            order,
            warehouse_id,
            products,
        )

        for sku in set(previous) | set(current):
            delta = (
                int(current.get(sku, 0))
                - int(previous.get(sku, 0))
            )

            if not delta:
                continue

            direct_deltas[sku] = (
                direct_deltas.get(sku, 0)
                + delta
            )

            for base_sku, base_delta in expand_consumption(
                sku,
                delta,
            ).items():
                if base_sku in base_stock:
                    base_stock[base_sku] = max(
                        0,
                        base_stock[base_sku] - base_delta,
                    )

        snapshots[order_id] = current

    return (
        base_stock,
        snapshots,
        direct_deltas,
    )


def replenish(products, base_stock):
    replenished = []
    policies = {}

    for sku in sorted(base_stock):
        target, threshold, policy = stock_policy(
            sku,
            products[sku],
        )

        policies[sku] = policy

        if target == 0:
            base_stock[sku] = 0
        elif base_stock[sku] <= threshold:
            base_stock[sku] = target
            replenished.append(sku)

    return replenished, policies


def update_salesdrive_stock(
    api_key,
    warehouse_id,
    updates,
):
    items = [
        {
            "id": supplier_sku(sku),
            "stockBalanceByStock": {
                str(warehouse_id): int(quantity),
            },
        }
        for sku, quantity in sorted(updates.items())
    ]

    for offset in range(0, len(items), 100):
        result = api_json(
            PRODUCT_UPDATE_URL,
            api_key,
            payload={
                "action": "update",
                "product": items[offset:offset + 100],
            },
        )

        if result.get("status") not in (
            None,
            "success",
        ):
            raise RuntimeError(
                f"Could not update SalesDrive stock: {result}"
            )


def build_yml(products, published_stock):
    root = etree.Element(
        "yml_catalog",
        date=now_kyiv().strftime(
            "%Y-%m-%d %H:%M"
        ),
    )

    shop = etree.SubElement(
        root,
        "shop",
    )

    etree.SubElement(
        shop,
        "name",
    ).text = "CatPaws DOMS stock"

    etree.SubElement(
        shop,
        "company",
    ).text = "CatPaws"

    etree.SubElement(
        shop,
        "url",
    ).text = "https://catpaws.com.ua/"

    currencies = etree.SubElement(
        shop,
        "currencies",
    )

    etree.SubElement(
        currencies,
        "currency",
        id="UAH",
        rate="1",
    )

    categories = etree.SubElement(
        shop,
        "categories",
    )

    etree.SubElement(
        categories,
        "category",
        id="1",
    ).text = "DOMS"

    offers = etree.SubElement(
        shop,
        "offers",
    )

    for sku, item in sorted(products.items()):
        quantity = int(
            published_stock.get(
                sku,
                0,
            )
        )

        offer = etree.SubElement(
            offers,
            "offer",
            id=sku,
            available=(
                "true"
                if quantity > 0
                else "false"
            ),
        )

        etree.SubElement(
            offer,
            "name",
        ).text = item["name"]

        etree.SubElement(
            offer,
            "vendorCode",
        ).text = sku

        etree.SubElement(
            offer,
            "price",
        ).text = "1"

        etree.SubElement(
            offer,
            "currencyId",
        ).text = "UAH"

        etree.SubElement(
            offer,
            "categoryId",
        ).text = "1"

        etree.SubElement(
            offer,
            "quantity_in_stock",
        ).text = str(quantity)

        etree.SubElement(
            offer,
            "stock",
        ).text = str(quantity)

        etree.SubElement(
            offer,
            "in_stock",
        ).text = (
            "1"
            if quantity > 0
            else "0"
        )

    return etree.ElementTree(root)


def main():
    api_key = os.environ.get(
        "SALESDRIVE_API_KEY",
        "",
    ).strip()

    if not api_key:
        raise RuntimeError(
            "SALESDRIVE_API_KEY is not configured"
        )

    site_catalog = load_site_catalog()
    products = build_product_catalog(
        site_catalog
    )

    if not products:
        raise RuntimeError(
            "No DOMS products found in the CatPaws catalog"
        )

    state = load_state()
    finished_at = now_kyiv()
    initializing = state is None

    if initializing:
        orders = fetch_orders(
            api_key,
            finished_at - timedelta(days=30),
            finished_at,
        )

        warehouse_id = find_warehouse_id(
            None,
            orders,
            products,
        )

        base_stock, supplier_policies = (
            initial_base_stock(products)
        )

        snapshots = {
            str(order.get("id")): direct_order_snapshot(
                order,
                warehouse_id,
                products,
            )
            for order in orders
        }

        published_stock = materialize_stock(
            products,
            base_stock,
        )

        updates = published_stock
        replenished = []

        print(
            "Initial DOMS stock synchronization"
        )
    else:
        warehouse_id = find_warehouse_id(
            state,
            [],
            products,
        )

        orders = fetch_orders(
            api_key,
            parse_api_time(
                state["last_sync"]
            ) - timedelta(minutes=2),
            finished_at,
        )

        previous_published = {
            sku: int(quantity)
            for sku, quantity
            in state.get(
                "published_stock",
                {},
            ).items()
        }

        (
            base_stock,
            snapshots,
            direct_deltas,
        ) = apply_order_changes(
            products,
            warehouse_id,
            orders,
            state,
        )

        (
            replenished,
            supplier_policies,
        ) = replenish(
            products,
            base_stock,
        )

        published_stock = materialize_stock(
            products,
            base_stock,
        )

        # SalesDrive уже сам списав безпосередньо
        # замовлений SKU.
        # Надсилаємо лише пов'язані коригування
        # блоків/банок, зміни наявності та
        # поповнення умовного залишку.
        automatic_stock = dict(
            previous_published
        )

        for sku, delta in direct_deltas.items():
            automatic_stock[sku] = max(
                0,
                int(
                    automatic_stock.get(
                        sku,
                        0,
                    )
                ) - delta,
            )

        updates = {
            sku: quantity
            for sku, quantity
            in published_stock.items()
            if int(
                automatic_stock.get(
                    sku,
                    0,
                )
            ) != int(quantity)
        }

    # Ці артикули мають бути передані в SalesDrive явно. Для перейменованих
    # позицій це виправляє старий залишок, записаний під кодом Horoshop;
    # для відсутніх у постачальника товарів гарантує нульовий залишок.
    forced_sync_skus = (
        set(SUPPLIER_SKU_ALIASES)
        | FORCE_ZERO_SKUS
    )

    for sku in forced_sync_skus:
        if sku in published_stock:
            updates[sku] = published_stock[sku]

    if updates:
        update_salesdrive_stock(
            api_key,
            warehouse_id,
            updates,
        )

    save_state({
        "version": 1,
        "warehouse_id": warehouse_id,
        "last_sync": format_api_time(
            finished_at
        ),
        "base_stock": base_stock,
        "published_stock": published_stock,
        "supplier_policies": supplier_policies,
        "order_snapshots": snapshots,
    })

    os.makedirs(
        os.path.dirname(OUTPUT_FILE),
        exist_ok=True,
    )

    build_yml(
        products,
        published_stock,
    ).write(
        OUTPUT_FILE,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    positive = sum(
        quantity > 0
        for quantity in published_stock.values()
    )

    homie = sum(
        item["brand"] == "homie"
        for item in products.values()
    )

    print(
        f"DOMS supplier SKUs in XLS: "
        f"{len(SUPPLIER_SKUS)}"
    )
    print(
        f"DOMS products in CatPaws catalog: "
        f"{len(products)}"
    )
    print(
        f"Homie products treated as available: "
        f"{homie}"
    )
    print(
        f"Linked canned-food packs: "
        f"{len(PACKS)}"
    )
    print(
        f"SalesDrive warehouse ID: "
        f"{warehouse_id}"
    )
    print(
        f"Updated orders read: "
        f"{len(orders)}"
    )
    print(
        f"Products sent to SalesDrive: "
        f"{len(updates)}"
    )
    print(
        f"Products replenished by threshold: "
        f"{len(replenished)}"
    )
    print(
        f"Products with positive stock: "
        f"{positive}"
    )
    print(
        f"Products with zero stock: "
        f"{len(products) - positive}"
    )
    print(
        f"Created: {OUTPUT_FILE}"
    )
    print(
        f"State saved: {STATE_FILE}"
    )


if __name__ == "__main__":
    main()
