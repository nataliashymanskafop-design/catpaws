import csv
import io
import os
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

from lxml import etree


CATALOG_XML_URL = "https://catpaws.com.ua/content/export/3e9c244f28ee6d1e572f92646e76f6bb.xml"
STOCK_CSV_URL = "https://feedcraft.space/feeds/horoshop-hf-stock.csv"
OUTPUT_FILE = "public/home-food-stock.yml"


# Тільки товари HOME FOOD, які вже є в каталозі SalesDrive.
# Список сформований з експорту SalesDrive від 15.09.2026.
CRM_HOME_FOOD_SKUS = {
    "1367104", "2027107", "2127100", "2027100", "2028016", "2028100",
    "1017007", "1117016", "1017100", "1027007", "1127016", "1027100",
    "1118016", "1018100", "1128016", "1028100", "1018330", "1019100",
    "1028303", "1029100", "1047007", "1047016", "1047100", "1037077",
    "1137016", "1037100", "1057007", "1057016", "1057100", "1148016",
    "1048100", "1138016", "1038100", "3215010", "3315010", "1138003",
    "1367100", "1128003", "1367101", "1367103", "1367105", "1367102",
    "1118003", "1108003", "7010016", "7010018", "7010018_box", "7010050",
    "7010016_box", "7010050_box", "7010050_box1", "7010013", "7010011", "7010010",
    "7000003", "7000010", "7000009", "7000008", "7000011", "7000012",
    "7010014", "1006010", "1010010", "1008010", "1007010", "1013010",
    "1011010", "1005010", "1001010", "1002010", "1003010", "1004010",
    "1013008", "1019004", "1016008", "1014008", "1012008", "1026008",
    "1017008", "1010008", "1090018", "1024008", "1070008", "1011008",
    "1011088", "1022008", "1050008", "1080008", "1039008", "1039088",
    "1040008", "1060008", "1025004", "7000001", "7010021", "7010006",
    "1090008", "1018008", "1027008", "1021008", "7010022", "7010034",
    "7010032", "7010028", "7010043", "7010047", "7010045", "7010041",
    "7010039", "7010026", "7010037", "7010030", "70100_box5", "70100_box6",
    "70100_box7", "70100_box8", "70100_box9", "70100_box10", "1357100", "3017044",
    "3017016", "3117000", "3028004", "3028016", "3128100", "3038004",
    "3038016", "3038100", "3058004", "3058116", "3058110", "3048004",
    "3048016", "3048100", "3079004", "3079016", "3179100", "3099004",
    "3199016", "3199100", "3068004", "3068016", "3068100", "3088004",
    "3088016", "3088100", "3108004", "3108016", "3108100", "3118004",
    "3118016", "3118110", "3115010", "1357110", "1357102", "1357101",
    "1357111", "357112", "3158100", "1357112", "7010019", "7010015",
    "7010017", "7010017_box", "7010023", "7010024", "7010025", "7010019_box",
    "7010015_box", "7010023_box", "7010024_box", "7010025_box", "7010012", "0000098",
    "3006010", "3010010", "3008010", "3007010", "3011010", "3005010",
    "3001010", "3002010", "3003010", "3004010", "3011004", "3011044",
    "3070004", "3050004", "3039004", "3039044", "3051004", "1040004",
    "3060004", "3080004", "3090004", "7010044", "7010036", "7010033",
    "7010031", "7010042", "7010048", "7010038", "7010035", "7010029",
    "7010027", "7010040", "7010046", "7010040_box", "7010044_box", "70100_box1",
    "70100_box2", "70100_box3", "70100_box4", "7000019", "7000004", "7000006",
    "7000005", "7000007",
}


# Звичайні коробки: SKU коробки -> (SKU одиниці, штук у коробці).
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


# Авторські набори: SKU набору -> {SKU складової: кількість у наборі}.
# Якщо хоча б однієї складової немає у фіді залишків, набір матиме залишок 0.
BUNDLES = {
    "7010050_box1": {"7010016": 4, "7010050": 4},
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
    # Артикула косички зі шкіри лосося немає у каталозі/фіді.
    # Службовий ключ залишає набір із нульовим залишком, доки артикул не буде відомий.
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


def parse_quantity(value):
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return 0
    try:
        return max(0, int(float(text)))
    except ValueError:
        return 0


def load_supplier_stock():
    content = download(STOCK_CSV_URL).decode("utf-8-sig")
    rows = csv.DictReader(io.StringIO(content), delimiter=";")
    stock = {}
    for row in rows:
        sku = str(row.get("article") or "").strip()
        if sku:
            stock[sku] = parse_quantity(row.get("quantity"))
    if len(stock) < 50:
        raise RuntimeError(
            f"HOME FOOD stock feed is empty or incomplete: only {len(stock)} rows. "
            "The previous published YML will not be overwritten."
        )
    return stock


def load_home_food_catalog():
    root = etree.fromstring(download(CATALOG_XML_URL))
    catalog_names = {}
    for offer in root.xpath(".//offer"):
        sku = str(offer.findtext("vendorCode") or "").strip()
        name = " ".join(str(offer.findtext("name") or "").split())
        if not sku or not name:
            continue
        catalog_names[sku] = name

    # Не беремо всі позиції постачальника. Публікуємо тільки SKU,
    # які вже були вивантажені з каталогу SalesDrive.
    return {sku: catalog_names.get(sku, sku) for sku in CRM_HOME_FOOD_SKUS}


def calculate_stock(sku, supplier_stock):
    if sku in SIMPLE_BOXES:
        base_sku, pack_size = SIMPLE_BOXES[sku]
        return supplier_stock.get(base_sku, 0) // pack_size

    if sku in BUNDLES:
        possible_sets = [
            supplier_stock.get(component_sku, 0) // component_quantity
            for component_sku, component_quantity in BUNDLES[sku].items()
        ]
        return min(possible_sets) if possible_sets else 0

    if "_box" in sku.lower():
        return 0

    return supplier_stock.get(sku, 0)


def build_yml(products, supplier_stock):
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
        quantity = calculate_stock(sku, supplier_stock)
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
        etree.SubElement(offer, "quantity_in_stock").text = str(quantity)

    return etree.ElementTree(root)


def main():
    supplier_stock = load_supplier_stock()
    products = load_home_food_catalog()
    document = build_yml(products, supplier_stock)

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    document.write(
        OUTPUT_FILE,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    positive = sum(calculate_stock(sku, supplier_stock) > 0 for sku in products)
    print(f"HOME FOOD products in catalog: {len(products)}")
    print(f"Products with positive stock: {positive}")
    print(f"Created: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
