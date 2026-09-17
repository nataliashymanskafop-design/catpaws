import json
import os
import subprocess
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from lxml import etree


CATALOG_XML_URL = "https://catpaws.com.ua/content/export/3e9c244f28ee6d1e572f92646e76f6bb.xml"
OUTPUT_FILE = "public/home-food-stock.yml"
STATE_FILE = "public/home-food-stock-state.json"

SALESDRIVE_BASE_URL = "https://catpaws.salesdrive.me"
ORDER_LIST_URL = f"{SALESDRIVE_BASE_URL}/api/order/list/"
PRODUCT_UPDATE_URL = f"{SALESDRIVE_BASE_URL}/product-handler/"

# Р¦Рµ Р·Р°РјРѕРІР»РµРЅРЅСЏ РїРѕРєР°Р·Р°РЅРµ РЅР° СЃРєСЂРёРЅС–: С‚РѕРІР°СЂ HOME FOOD Р·С– СЃРєР»Р°РґСѓ
# "HOME FOOD вЂ” Р—Р°Р·РёРјвЂ™СЏ". Р’РѕРЅРѕ РїРѕС‚СЂС–Р±РЅРµ Р»РёС€Рµ РѕРґРёРЅ СЂР°Р·, С‰РѕР± Р±РµР·РїРµС‡РЅРѕ
# РІРёР·РЅР°С‡РёС‚Рё С‡РёСЃР»РѕРІРёР№ ID СЃРєР»Р°РґСѓ. РџРѕС‚С–Рј ID Р·Р±РµСЂС–РіР°С”С‚СЊСЃСЏ Сѓ STATE_FILE.
BOOTSTRAP_ORDER_ID = 2526

DEFAULT_STOCK = 20
DEFAULT_THRESHOLD = 5
TREAT_STOCK = 21
TREAT_THRESHOLD = 5
CAT_CAN_STOCK = 60
CAT_CAN_THRESHOLD = 24
DOG_CAN_STOCK = 40
DOG_CAN_THRESHOLD = 16
BUNDLE_RESERVE = 1

# Р¦С– С‚РѕРІР°СЂРё С‚РёРјС‡Р°СЃРѕРІРѕ РІС–РґСЃСѓС‚РЅС–.
FORCE_ZERO_SKUS = {
    "3108016",
    "1019004",
}


# РўС–Р»СЊРєРё С‚РѕРІР°СЂРё HOME FOOD, СЏРєС– РІР¶Рµ С” РІ РєР°С‚Р°Р»РѕР·С– SalesDrive.
# РЎРїРёСЃРѕРє СЃС„РѕСЂРјРѕРІР°РЅРёР№ Р· РµРєСЃРїРѕСЂС‚Сѓ SalesDrive РІС–Рґ 15.09.2026.
CRM_HOME_FOOD_SKUS = {
    "1367104", "2027107", "2127100", "2027100", "2028016", "2028100",
    "1017007", "1117016", "1017100", "1027007", "1127016", "1027100",
    "1118016", "1018100", "1128016", "1028100", "1018330", "1019100",
    "1028303", "1029100", "1047007", "1047016", "1047100", "1037077",
    "1137016", "1037100", "1057007", "1057016", "1057100", "1148016",
    "1048100", "1138016", "1038100", "3215010", "3315010", "1138003",
    "1367100", "1128003", "1367101", "1367103", "1367105", "1367102",
    "1118003", "1108003", "7010016", "7010018", "7010018_box", "7010050",
    "7010016_box", "7010050_box", "7010050_box1", "7010013", "7010011",
    "7010010", "7000003", "7000010", "7000009", "7000008", "7000011",
    "7000012", "7010014", "1006010", "1010010", "1008010", "1007010",
    "1013010", "1011010", "1005010", "1001010", "1002010", "1003010",
    "1004010", "1013008", "1019004", "1016008", "1014008", "1012008",
    "1026008", "1017008", "1010008", "1090018", "1024008", "1070008",
    "1011008", "1011088", "1022008", "1050008", "1080008", "1039008",
    "1039088", "1040008", "1060008", "1025004", "7000001", "7010021",
    "7010006", "1090008", "1018008", "1027008", "1021008", "7010022",
    "7010034", "7010032", "7010028", "7010043", "7010047", "7010045",
    "7010041", "7010039", "7010026", "7010037", "7010030", "70100_box5",
    "70100_box6", "70100_box7", "70100_box8", "70100_box9", "70100_box10",
    "1357100", "3017044", "3017016", "3117000", "3028004", "3028016",
    "3128100", "3038004", "3038016", "3038100", "3058004", "3058116",
    "3058110", "3048004", "3048016", "3048100", "3079004", "3079016",
    "3179100", "3099004", "3199016", "3199100", "3068004", "3068016",
    "3068100", "3088004", "3088016", "3088100", "3108004", "3108016",
    "3108100", "3118004", "3118016", "3118110", "3115010", "1357110",
    "1357102", "1357101", "1357111", "357112", "3158100", "1357112",
    "7010019", "7010015", "7010017", "7010017_box", "7010023", "7010024",
    "7010025", "7010019_box", "7010015_box", "7010023_box", "7010024_box",
    "7010025_box", "7010012", "0000098", "3006010", "3010010", "3008010",
    "3007010", "3011010", "3005010", "3001010", "3002010", "3003010",
    "3004010", "3011004", "3011044", "3070004", "3050004", "3039004",
    "3039044", "3051004", "1040004", "3060004", "3080004", "3090004",
    "7010044", "7010036", "7010033", "7010031", "7010042", "7010048",
    "7010038", "7010035", "7010029", "7010027", "7010040", "7010046",
    "7010040_box", "7010044_box", "70100_box1", "70100_box2", "70100_box3",
    "70100_box4", "7000019", "7000004", "7000006", "7000005", "7000007",
}


# Р—РІРёС‡Р°Р№РЅС– РєРѕСЂРѕР±РєРё: SKU РєРѕСЂРѕР±РєРё -> (SKU РѕРґРёРЅРёС†С–, С€С‚СѓРє Сѓ РєРѕСЂРѕР±С†С–).
SIMPLE_BOXES = {
    "7010018_box": ("7010018", 8),
    "7010016_box": ("7010016", 8),
    "7010050_box": ("7010050", 8),
    "7010017_box": ("7010017", 12),
    "7010019_box": ("7010019", 12),
    "7010015_box": ("7010015", 12),
    "7010023_box": ("7010023", 12),
    "7010024_box": ("7010024", 12),
    "7010025_box": ("7010025", 12),
    "7010040_box": ("7010040", 10),
    "7010044_box": ("7010044", 10),
}


# РђРІС‚РѕСЂСЃСЊРєС– РЅР°Р±РѕСЂРё: SKU РЅР°Р±РѕСЂСѓ -> {SKU СЃРєР»Р°РґРѕРІРѕС—: РєС–Р»СЊРєС–СЃС‚СЊ}.
BUNDLES = {
    "7010050_box1": {
        "7010016": 4,
        "7010050": 4,
    },
    "70100_box1": {
        "7010040": 1,
        "7010044": 1,
        "7010046": 1,
        "7010033": 1,
        "7010042": 1,
        "7010048": 1,
    },
    "70100_box2": {
        "7010036": 1,
        "7010033": 1,
        "7010031": 1,
        "7010038": 1,
        "7010035": 1,
    },
    "70100_box3": {
        "7010040": 1,
        "7010036": 1,
        "7010038": 1,
        "7010035": 1,
        "7010029": 1,
        "7010027": 1,
    },
    "70100_box4": {
        "7010040": 1,
        "7010044": 1,
        "7010046": 1,
        "7010036": 1,
        "7010033": 1,
        "7010031": 1,
        "7010042": 1,
        "7010048": 1,
        "7010038": 1,
        "7010035": 1,
        "7010029": 1,
        "7010027": 1,
    },
    "70100_box5": {
        "1019004": 1,
        "7010032": 1,
        "7010043": 1,
        "7010041": 1,
        "7010047": 1,
    },
    "70100_box6": {
        "1014008": 1,
        "1012008": 1,
        "1026008": 1,
        "1017008": 1,
        "1010008": 1,
    },
    "70100_box7": {
        "1013008": 1,
        "1016008": 1,
        "1024008": 1,
        "1022008": 1,
        "1014008": 1,
    },
    "70100_box8": {
        "7010032": 1,
        "7010043": 1,
        "7010041": 1,
        "7010034": 1,
        "7010047": 1,
    },
    # РђСЂС‚РёРєСѓР»Р° РєРѕСЃРёС‡РєРё Р·С– С€РєС–СЂРё Р»РѕСЃРѕСЃСЏ РЅРµРјР°С” Сѓ РєР°С‚Р°Р»РѕР·С–.
    # РќР°Р±С–СЂ Р·Р°Р»РёС€Р°С”С‚СЊСЃСЏ Р· РЅСѓР»СЊРѕРІРёРј Р·Р°Р»РёС€РєРѕРј.
    "70100_box9": {
        "1090018": 1,
        "__SALMON_SKIN_BRAID_SKU_REQUIRED__": 1,
        "7010028": 1,
        "7010026": 1,
    },
    "70100_box10": {
        "7000001": 1,
        "7010006": 1,
        "7010022": 1,
    },
}


def download(url):
    result = subprocess.run(
        ["curl", "-fL", "--silent", "--show-error", url],
        check=True,
        capture_output=True,
    )
    return result.stdout


def repair_mojibake(value):
    text = " ".join(str(value or "").split())

    try:
        return text.encode("cp1251").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def normalize_name(name):
    return " ".join(str(name or "").lower().split())


def is_treat(name):
    normalized = normalize_name(name)
    keywords = (
        "Р»Р°СЃРѕС‰",
        "СЃРЅРµРє",
        "snack",
        "СЃРѕР»РѕРјРє",
        "С‡РµРєС–",
        "chew",
        "РєРѕСЃРёС‡Рє",
    )
    return any(keyword in normalized for keyword in keywords)


def is_water(name):
    normalized = normalize_name(name)
    return "РІРѕРґР°" in normalized or "water" in normalized


def load_home_food_catalog():
    root = etree.fromstring(download(CATALOG_XML_URL))
    catalog_names = {}

    for offer in root.xpath(".//offer"):
        sku = str(offer.findtext("vendorCode") or "").strip()
        name = repair_mojibake(offer.findtext("name"))

        if not sku or not name:
            continue

        catalog_names[sku] = name

    products = {}

    for sku in CRM_HOME_FOOD_SKUS:
        name = catalog_names.get(sku)

        # РќРµ РґРѕРґР°С”РјРѕ SKU, СЏРєРёС… СѓР¶Рµ РЅРµРјР°С” РІ РєР°С‚Р°Р»РѕР·С– СЃР°Р№С‚Сѓ.
        if not name:
            continue

        # Р’РѕРґСѓ РґРѕ С„С–РґР° HOME FOOD РЅРµ РґРѕРґР°С”РјРѕ.
        if is_water(name):
            continue

        products[sku] = name

    return products


CAT_CAN_SKUS = {
    base_sku
    for base_sku, pack_size in SIMPLE_BOXES.values()
    if pack_size == 12
}

DOG_CAN_SKUS = {
    base_sku
    for base_sku, pack_size in SIMPLE_BOXES.values()
    if pack_size == 8
}

TREAT_COMPONENT_SKUS = {
    component_sku
    for components in BUNDLES.values()
    for component_sku in components
    if not component_sku.startswith("__")
}

DERIVED_SKUS = set(SIMPLE_BOXES) | set(BUNDLES)


def now_kyiv():
    return datetime.now(ZoneInfo("Europe/Kyiv"))


def format_api_time(value):
    return value.strftime("%Y-%m-%d %H:%M:%S")


def parse_api_time(value):
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=ZoneInfo("Europe/Kyiv")
    )


def api_json(url, api_key, params=None, payload=None):
    if params:
        url = f"{url}?{urlencode(params)}"

    data = None
    headers = {
        "Accept": "application/json",
        "X-Api-Key": api_key,
    }

    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers)

    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"SalesDrive API returned HTTP {error.code}: {details[:500]}"
        ) from error
    except URLError as error:
        raise RuntimeError(f"SalesDrive API is unavailable: {error}") from error

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as error:
        raise RuntimeError("SalesDrive API returned invalid JSON") from error

    if result.get("status") == "error" or result.get("success") is False:
        raise RuntimeError(f"SalesDrive API error: {result}")

    return result


def fetch_orders(api_key, updated_from, updated_to):
    orders = []
    page = 1

    while page <= 20:
        result = api_json(
            ORDER_LIST_URL,
            api_key,
            params={
                "page": page,
                "limit": 100,
                "filter[updateAt][from]": format_api_time(updated_from),
                "filter[updateAt][to]": format_api_time(updated_to),
            },
        )
        batch = result.get("data") or []
        orders.extend(batch)

        if len(batch) < 100:
            break

        page += 1

    if page > 20:
        raise RuntimeError("Too many updated SalesDrive orders; pagination limit reached")

    return orders


def find_warehouse_id(state, orders):
    configured = os.environ.get("SALESDRIVE_HOME_FOOD_STOCK_ID", "").strip()
    if configured:
        return int(configured)

    if state and state.get("warehouse_id"):
        return int(state["warehouse_id"])

    for order in orders:
        if int(order.get("id") or 0) != BOOTSTRAP_ORDER_ID:
            continue

        for product in order.get("products") or []:
            if str(product.get("sku") or "").strip() == "1019100":
                stock_id = product.get("stockId")
                if stock_id:
                    return int(stock_id)

    raise RuntimeError(
        "Could not determine the HOME FOOD warehouse ID from order #2526. "
        "Set repository variable SALESDRIVE_HOME_FOOD_STOCK_ID."
    )


def load_state():
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)
    except (OSError, json.JSONDecodeError):
        return None

    if state.get("version") != 2:
        return None

    return state


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    temporary = f"{STATE_FILE}.tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2, sort_keys=True)
        file.write("\n")

    os.replace(temporary, STATE_FILE)


def stock_policy(sku, name):
    if sku in FORCE_ZERO_SKUS:
        return 0, 0
    if sku in CAT_CAN_SKUS:
        return CAT_CAN_STOCK, CAT_CAN_THRESHOLD
    if sku in DOG_CAN_SKUS:
        return DOG_CAN_STOCK, DOG_CAN_THRESHOLD
    if sku in TREAT_COMPONENT_SKUS or is_treat(name):
        return TREAT_STOCK, TREAT_THRESHOLD
    return DEFAULT_STOCK, DEFAULT_THRESHOLD


def base_skus(products):
    return set(products) - DERIVED_SKUS


def initial_base_stock(products):
    result = {}
    for sku in base_skus(products):
        target, _ = stock_policy(sku, products[sku])
        result[sku] = target
    return result


def calculate_stock(sku, base_stock):
    if sku in FORCE_ZERO_SKUS:
        return 0

    if sku in SIMPLE_BOXES:
        component_sku, pack_size = SIMPLE_BOXES[sku]
        return max(0, int(base_stock.get(component_sku, 0)) // pack_size)

    if sku in BUNDLES:
        # Р РµР·РµСЂРІ РІ РѕРґРЅСѓ РѕРґРёРЅРёС†СЋ Р·Р°Р»РёС€Р°С”РјРѕ Р»РёС€Рµ РґР»СЏ РЅР°Р±РѕСЂС–РІ Р»Р°СЃРѕС‰С–РІ.
        # 7010050_box1 вЂ” Р·РјС–С€Р°РЅР° РєРѕСЂРѕР±РєР° РєРѕРЅСЃРµСЂРІС–РІ 4 + 4.
        reserve = 0 if sku == "7010050_box1" else BUNDLE_RESERVE
        possible_sets = []
        for component_sku, component_quantity in BUNDLES[sku].items():
            component_stock = int(base_stock.get(component_sku, 0))
            possible_sets.append(
                max(0, component_stock // component_quantity - reserve)
            )
        return min(possible_sets) if possible_sets else 0

    if "_box" in sku.lower():
        return 0

    return max(0, int(base_stock.get(sku, 0)))


def materialize_stock(products, base_stock):
    return {
        sku: calculate_stock(sku, base_stock)
        for sku in products
    }


def direct_order_snapshot(order, warehouse_id, products):
    snapshot = {}
    for item in order.get("products") or []:
        if int(item.get("stockId") or 0) != warehouse_id:
            continue

        sku = str(item.get("sku") or "").strip()
        if sku not in products:
            continue

        amount = int(float(item.get("amount") or 0))
        if amount > 0:
            snapshot[sku] = snapshot.get(sku, 0) + amount

    return snapshot


def expand_consumption(sku, amount):
    if sku in SIMPLE_BOXES:
        component_sku, pack_size = SIMPLE_BOXES[sku]
        return {component_sku: amount * pack_size}

    if sku in BUNDLES:
        return {
            component_sku: amount * component_quantity
            for component_sku, component_quantity in BUNDLES[sku].items()
            if not component_sku.startswith("__")
        }

    return {sku: amount}


def apply_order_changes(products, warehouse_id, orders, state):
    current_base_skus = base_skus(products)
    base_stock = {}
    for sku in current_base_skus:
        if sku in state["base_stock"]:
            base_stock[sku] = int(state["base_stock"][sku])
        else:
            target, _ = stock_policy(sku, products[sku])
            base_stock[sku] = target
    snapshots = state.get("order_snapshots", {})
    direct_deltas = {}

    for order in orders:
        order_id = str(order.get("id"))
        previous = snapshots.get(order_id, {})
        current = direct_order_snapshot(order, warehouse_id, products)

        for sku in set(previous) | set(current):
            delta = int(current.get(sku, 0)) - int(previous.get(sku, 0))
            if not delta:
                continue

            direct_deltas[sku] = direct_deltas.get(sku, 0) + delta
            for component_sku, component_delta in expand_consumption(
                sku, delta
            ).items():
                if component_sku in base_stock:
                    base_stock[component_sku] = max(
                        0,
                        base_stock[component_sku] - component_delta,
                    )

        snapshots[order_id] = current

    return base_stock, snapshots, direct_deltas


def replenish_low_stock(products, base_stock):
    replenished = []

    for sku in sorted(base_stock):
        target, threshold = stock_policy(sku, products[sku])

        if target == 0:
            if base_stock[sku] != 0:
                base_stock[sku] = 0
                replenished.append(sku)
            continue

        if base_stock[sku] <= threshold:
            base_stock[sku] = target
            replenished.append(sku)

    return replenished


def update_salesdrive_stock(api_key, warehouse_id, updates):
    items = [
        {
            "id": sku,
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
        if result.get("status") not in (None, "success"):
            raise RuntimeError(f"Could not update SalesDrive stock: {result}")


def build_yml(products, published_stock):
    now = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M")

    root = etree.Element("yml_catalog", date=now)
    shop = etree.SubElement(root, "shop")

    etree.SubElement(shop, "name").text = "CatPaws HOME FOOD stock"
    etree.SubElement(shop, "company").text = "CatPaws"
    etree.SubElement(shop, "url").text = "https://catpaws.com.ua/"

    currencies = etree.SubElement(shop, "currencies")
    etree.SubElement(currencies, "currency", id="UAH", rate="1")

    categories = etree.SubElement(shop, "categories")
    etree.SubElement(categories, "category", id="1").text = "HOME FOOD"

    offers = etree.SubElement(shop, "offers")

    for sku, name in sorted(products.items()):
        quantity = int(published_stock.get(sku, 0))

        offer = etree.SubElement(
            offers,
            "offer",
            id=sku,
            available="true" if quantity > 0 else "false",
        )

        etree.SubElement(offer, "name").text = name
        etree.SubElement(offer, "vendorCode").text = sku
        etree.SubElement(offer, "price").text = "1"
        etree.SubElement(offer, "currencyId").text = "UAH"
        etree.SubElement(offer, "categoryId").text = "1"

        # РљС–Р»СЊРєС–СЃС‚СЊ С‚РѕРІР°СЂСѓ РґР»СЏ С–РјРїРѕСЂС‚Сѓ РЅР° СЃРєР»Р°Рґ SalesDrive.
        etree.SubElement(
            offer,
            "quantity_in_stock",
        ).text = str(quantity)

        etree.SubElement(
            offer,
            "stock",
        ).text = str(quantity)

        # РћРєСЂРµРјРµ РїСЂРѕСЃС‚Рµ РїРѕР»Рµ РЅР°СЏРІРЅРѕСЃС‚С– РґР»СЏ SalesDrive:
        # 1 вЂ” С‚РѕРІР°СЂ Сѓ РЅР°СЏРІРЅРѕСЃС‚С–, 0 вЂ” С‚РѕРІР°СЂ РІС–РґСЃСѓС‚РЅС–Р№.
        etree.SubElement(
            offer,
            "in_stock",
        ).text = "1" if quantity > 0 else "0"

    return etree.ElementTree(root)


def main():
    api_key = os.environ.get("SALESDRIVE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SALESDRIVE_API_KEY is not configured")

    products = load_home_food_catalog()
    state = load_state()
    run_finished_at = now_kyiv()
    initializing = state is None

    if initializing:
        orders = fetch_orders(
            api_key,
            run_finished_at - timedelta(days=30),
            run_finished_at,
        )
        warehouse_id = find_warehouse_id(None, orders)
        base_stock = initial_base_stock(products)
        snapshots = {
            str(order.get("id")): direct_order_snapshot(
                order, warehouse_id, products
            )
            for order in orders
        }
        published_stock = materialize_stock(products, base_stock)
        updates = published_stock
        replenished = []
        print("Initial HOME FOOD stock synchronization")
    else:
        warehouse_id = find_warehouse_id(state, [])
        updated_from = parse_api_time(state["last_sync"]) - timedelta(minutes=2)
        orders = fetch_orders(api_key, updated_from, run_finished_at)

        previous_published = {
            sku: int(quantity)
            for sku, quantity in state["published_stock"].items()
        }
        base_stock, snapshots, direct_deltas = apply_order_changes(
            products,
            warehouse_id,
            orders,
            state,
        )
        replenished = replenish_low_stock(products, base_stock)
        published_stock = materialize_stock(products, base_stock)

        # SalesDrive already subtracts the product line selected in an order.
        # Estimate that automatic result and send only corrections caused by
        # bundles/boxes or a threshold replenishment.
        automatic_stock = dict(previous_published)
        for sku, delta in direct_deltas.items():
            automatic_stock[sku] = max(
                0,
                int(automatic_stock.get(sku, 0)) - delta,
            )

        updates = {
            sku: quantity
            for sku, quantity in published_stock.items()
            if int(automatic_stock.get(sku, 0)) != int(quantity)
        }

    if updates:
        update_salesdrive_stock(api_key, warehouse_id, updates)

    state = {
        "version": 2,
        "warehouse_id": warehouse_id,
        "last_sync": format_api_time(run_finished_at),
        "base_stock": base_stock,
        "published_stock": published_stock,
        "order_snapshots": snapshots,
    }
    save_state(state)

    document = build_yml(products, published_stock)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    document.write(
        OUTPUT_FILE,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    positive = sum(quantity > 0 for quantity in published_stock.values())

    zero = len(products) - positive

    print(f"HOME FOOD products in catalog: {len(products)}")
    print(f"SalesDrive warehouse ID: {warehouse_id}")
    print(f"Updated orders read: {len(orders)}")
    print(f"Products sent to SalesDrive: {len(updates)}")
    print(f"Products replenished by threshold: {len(replenished)}")
    print(f"Products with positive stock: {positive}")
    print(f"Products with zero stock: {zero}")
    print(f"Created: {OUTPUT_FILE}")
    print(f"State saved: {STATE_FILE}")


if __name__ == "__main__":
    main()
