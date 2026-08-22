import os

import requests
from lxml import etree


HOROSHOP_URL = (
    "https://catpaws.com.ua/content/export/"
    "77e6f1cd306feb32b68e245d1affc6bc.xml"
)

PROM_URL = (
    "https://internet-magazin-zootovarov-catpaws.prom.ua/products_feed.xml"
    "?hash_tag=8a56485e1e4e81c1d667052043b301b8"
    "&sales_notes=&product_ids=&label_ids=&exclude_fields=description"
    "&html_description=0&yandex_cpa=&process_presence_sure="
    "&languages=uk&extra_fields=&group_ids="
)


def download_xml(url):
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return etree.fromstring(response.content)


def vendor_code(offer):
    value = offer.findtext("vendorCode")
    return value.strip() if value else ""


def add_text(parent, tag, value):
    if value is None:
        return

    value = str(value).strip()

    if not value:
        return

    element = etree.SubElement(parent, tag)
    element.text = value


def main():
    print("Downloading Horoshop and Prom feeds...")

    horoshop_root = download_xml(HOROSHOP_URL)
    prom_root = download_xml(PROM_URL)

    # =========================================================
    # 1. Товари, які вже є в експорті Prom
    # =========================================================

    prom_products = {}
    duplicate_codes = set()

    for offer in prom_root.xpath(".//offer"):
        code = vendor_code(offer)
        prom_id = offer.get("id")

        if not code or not prom_id:
            continue

        if code in prom_products:
            duplicate_codes.add(code)
            continue

        prom_products[code] = prom_id

    print(f"Products found in Prom export: {len(prom_products)}")

    # =========================================================
    # 2. Актуальні товари Horoshop
    # =========================================================

    horoshop_products = {}

    for offer in horoshop_root.xpath(".//offer"):
        code = vendor_code(offer)

        if code:
            horoshop_products[code] = offer

    print(f"Products found in Horoshop: {len(horoshop_products)}")

    # =========================================================
    # 3. Мінімальний update-feed
    #
    # Потрапляють ТІЛЬКИ товари:
    # Prom + Horoshop
    #
    # Передаємо:
    # - Prom ID
    # - артикул
    # - наявність
    # - ціну
    # - стару ціну / знижку
    #
    # НЕ передаємо:
    # - назву
    # - опис
    # - фото
    # - категорію
    # - характеристики
    # =========================================================

    root = etree.Element("yml_catalog")

    shop = etree.SubElement(root, "shop")

    currencies = etree.SubElement(shop, "currencies")

    etree.SubElement(
        currencies,
        "currency",
        id="UAH",
        rate="1",
    )

    offers = etree.SubElement(shop, "offers")

    updated = 0
    skipped_missing = 0

    for code, prom_id in prom_products.items():

        source = horoshop_products.get(code)

        # -----------------------------------------------------
        # Якщо товару вже немає в Horoshop —
        # НЕ додаємо його у XML.
        # -----------------------------------------------------

        if source is None:
            skipped_missing += 1
            continue

        # -----------------------------------------------------
        # Наявність
        # -----------------------------------------------------

        available = source.get("available", "false").lower()

        if available not in ("true", "false"):
            available = "false"

        offer = etree.SubElement(
            offers,
            "offer",
            id=prom_id,
            available=available,
        )

        # -----------------------------------------------------
        # Артикул
        # -----------------------------------------------------

        add_text(
            offer,
            "vendorCode",
            code,
        )

        # -----------------------------------------------------
        # Ціна
        # -----------------------------------------------------

        price = source.findtext("price")

        add_text(
            offer,
            "price",
            price,
        )

        # -----------------------------------------------------
        # Знижка / стара ціна
        # -----------------------------------------------------

        oldprice = source.findtext("oldprice")

        if oldprice:
            add_text(
                offer,
                "oldprice",
                oldprice,
            )

        # -----------------------------------------------------
        # Валюта
        # -----------------------------------------------------

        currency = source.findtext("currencyId")

        add_text(
            offer,
            "currencyId",
            currency or "UAH",
        )

        updated += 1

    # =========================================================
    # 4. Зберігаємо XML
    # =========================================================

    os.makedirs("public", exist_ok=True)

    etree.ElementTree(root).write(
        "public/prom-update.xml",
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    # =========================================================
    # 5. Лог
    # =========================================================

    print()
    print("PROM UPDATE FEED READY")
    print(f"Products included in update feed: {updated}")
    print(
        f"Prom products missing in Horoshop and NOT included: "
        f"{skipped_missing}"
    )

    if duplicate_codes:
        print(
            "Duplicate Prom vendorCodes skipped:",
            sorted(duplicate_codes),
        )


if __name__ == "__main__":
    main()
