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

    # ---------------------------------------------------------
    # Товари, які ВЖЕ існують на Prom.
    # Працюємо тільки з ними.
    # ---------------------------------------------------------

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

    # ---------------------------------------------------------
    # Актуальний каталог Horoshop.
    # ---------------------------------------------------------

    horoshop_products = {}

    for offer in horoshop_root.xpath(".//offer"):
        code = vendor_code(offer)

        if code:
            horoshop_products[code] = offer

    # ---------------------------------------------------------
    # Створюємо МІНІМАЛЬНИЙ update-feed.
    #
    # НЕ передаємо:
    # name
    # name_ua
    # description
    # picture
    # categoryId
    # vendor
    # params
    #
    # Тільки:
    # ID Prom
    # vendorCode
    # available
    # price
    # oldprice
    # currencyId
    # ---------------------------------------------------------

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

    matched = 0
    unavailable = 0

    for code, prom_id in prom_products.items():

        source = horoshop_products.get(code)

        # -----------------------------------------------------
        # Є в Horoshop:
        # передаємо актуальну наявність + ціну + знижку
        # -----------------------------------------------------

        if source is not None:

            available = source.get("available", "false").lower()

            if available not in ("true", "false"):
                available = "false"

            offer = etree.SubElement(
                offers,
                "offer",
                id=prom_id,
                available=available,
            )

            add_text(
                offer,
                "vendorCode",
                code,
            )

            price = source.findtext("price")
            oldprice = source.findtext("oldprice")
            currency = source.findtext("currencyId")

            add_text(
                offer,
                "price",
                price,
            )

            # oldprice передаємо тільки якщо він реально є
            if oldprice:
                add_text(
                    offer,
                    "oldprice",
                    oldprice,
                )

            add_text(
                offer,
                "currencyId",
                currency or "UAH",
            )

            matched += 1

        # -----------------------------------------------------
        # Є на Prom, але немає в Horoshop:
        # ОБОВ'ЯЗКОВО вимикаємо наявність.
        #
        # Ціну тут НЕ чіпаємо.
        # -----------------------------------------------------

        else:

            offer = etree.SubElement(
                offers,
                "offer",
                id=prom_id,
                available="false",
            )

            add_text(
                offer,
                "vendorCode",
                code,
            )

            unavailable += 1

            print(
                f"Unavailable: {code} "
                f"(exists on Prom, missing in Horoshop)"
            )

    # ---------------------------------------------------------
    # Збереження
    # ---------------------------------------------------------

    os.makedirs("public", exist_ok=True)

    etree.ElementTree(root).write(
        "public/prom-update.xml",
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    print()
    print("PROM UPDATE FEED READY")
    print(f"Updated from Horoshop: {matched}")
    print(f"Marked unavailable: {unavailable}")
    print(f"Total existing Prom products: {matched + unavailable}")

    if duplicate_codes:
        print(
            "Duplicate Prom vendorCodes skipped:",
            sorted(duplicate_codes),
        )


if __name__ == "__main__":
    main()
