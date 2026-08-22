import os
from copy import deepcopy

import requests
from lxml import etree


HOROSHOP_URL = (
    "https://catpaws.com.ua/content/export/"
    "77e6f1cd306feb32b68e245d1affc6bc.xml"
)

PROM_URL = (
    "https://internet-magazin-zootovarov-catpaws.prom.ua/products_feed.xml"
    "?hash_tag=8a56485e1e4e81c1d667052043b301b8"
    "&sales_notes=&product_ids=&label_ids="
    "&exclude_fields=description"
    "&html_description=0"
    "&yandex_cpa="
    "&process_presence_sure="
    "&languages=uk"
    "&extra_fields="
    "&group_ids="
)


def download_xml(url):
    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return etree.fromstring(response.content)


def get_vendor_code(offer):
    value = offer.findtext("vendorCode")
    return value.strip() if value else ""


def get_prom_offers(root):
    """
    Повертає товари, які реально присутні в експорті Prom.
    Ключ — vendorCode / артикул.
    """

    result = {}
    duplicates = set()

    for offer in root.xpath(".//offer"):
        code = get_vendor_code(offer)

        if not code:
            continue

        if code in result:
            duplicates.add(code)
            continue

        result[code] = offer

    return result, duplicates


def get_horoshop_offers(root):
    """
    Товари Horoshop за артикулом.
    """

    result = {}

    for offer in root.xpath(".//offer"):
        code = get_vendor_code(offer)

        if not code:
            continue

        result[code] = offer

    return result


def copy_if_exists(source, destination, tag):
    element = source.find(tag)

    if element is not None and element.text is not None:
        destination.append(deepcopy(element))


def main():

    print("Downloading Horoshop and Prom feeds...")

    horoshop_root = download_xml(HOROSHOP_URL)
    prom_root = download_xml(PROM_URL)

    prom_by_code, duplicate_codes = get_prom_offers(prom_root)
    horoshop_by_code = get_horoshop_offers(horoshop_root)

    print(f"Prom products found: {len(prom_by_code)}")
    print(f"Horoshop products found: {len(horoshop_by_code)}")

    # ---------------------------------------------------------
    # Створюємо НОВИЙ мінімальний YML.
    # Не копіюємо каталог Horoshop.
    # ---------------------------------------------------------

    yml_catalog = etree.Element("yml_catalog")

    shop = etree.SubElement(yml_catalog, "shop")

    name = etree.SubElement(shop, "name")
    name.text = "CatPaws"

    company = etree.SubElement(shop, "company")
    company.text = "CatPaws"

    currencies = etree.SubElement(shop, "currencies")

    etree.SubElement(
        currencies,
        "currency",
        id="UAH",
        rate="1"
    )

    offers_parent = etree.SubElement(shop, "offers")

    updated = 0
    unavailable = 0
    skipped = 0

    # ---------------------------------------------------------
    # Головне:
    # працюємо ТІЛЬКИ з артикулами, які вже є на Prom.
    # ---------------------------------------------------------

    for code, prom_offer in prom_by_code.items():

        source = horoshop_by_code.get(code)

        # -----------------------------------------------------
        # Товар є і на Prom, і в Horoshop
        # -----------------------------------------------------

        if source is not None:

            available = source.get("available", "false").lower()

            if available not in ("true", "false"):
                available = "false"

            offer = etree.SubElement(
                offers_parent,
                "offer",

                # КРИТИЧНО:
                # id = артикул, а НЕ внутрішній Prom ID
                id=code,

                available=available,
            )

            vendor = etree.SubElement(offer, "vendorCode")
            vendor.text = code

            copy_if_exists(source, offer, "price")
            copy_if_exists(source, offer, "oldprice")
            copy_if_exists(source, offer, "currencyId")

            # Якщо currencyId немає
            if offer.find("currencyId") is None:
                currency = etree.SubElement(
                    offer,
                    "currencyId"
                )
                currency.text = "UAH"

            updated += 1

            continue

        # -----------------------------------------------------
        # Товар є на Prom, але його НЕМАЄ в Horoshop.
        #
        # Значить він більше не продається / відсутній.
        # Передаємо available=false.
        #
        # Ціну беремо зі старого Prom-фіда,
        # щоб Prom не отримав порожню картку.
        # -----------------------------------------------------

        offer = etree.SubElement(
            offers_parent,
            "offer",
            id=code,
            available="false",
        )

        vendor = etree.SubElement(offer, "vendorCode")
        vendor.text = code

        copy_if_exists(prom_offer, offer, "price")
        copy_if_exists(prom_offer, offer, "oldprice")
        copy_if_exists(prom_offer, offer, "currencyId")

        if offer.find("currencyId") is None:
            currency = etree.SubElement(
                offer,
                "currencyId"
            )
            currency.text = "UAH"

        unavailable += 1

        print(
            f"Unavailable: {code} "
            f"(exists on Prom, missing in Horoshop)"
        )

    # ---------------------------------------------------------
    # Запис файлу
    # ---------------------------------------------------------

    os.makedirs("public", exist_ok=True)

    output_file = "public/prom-update.xml"

    etree.ElementTree(yml_catalog).write(
        output_file,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    print()
    print("======================================")
    print("PROM UPDATE FEED READY")
    print("======================================")
    print(f"Existing Prom products: {len(prom_by_code)}")
    print(f"Updated from Horoshop: {updated}")
    print(f"Marked unavailable: {unavailable}")
    print(f"Skipped: {skipped}")

    if duplicate_codes:
        print(
            "Duplicate Prom vendorCodes skipped:",
            sorted(duplicate_codes)
        )

    # ---------------------------------------------------------
    # Контроль конкретного товару
    # ---------------------------------------------------------

    CONTROL_CODE = "3C000412"

    if CONTROL_CODE in prom_by_code:

        if CONTROL_CODE in horoshop_by_code:

            status = horoshop_by_code[
                CONTROL_CODE
            ].get("available", "false")

            print(
                f"CONTROL {CONTROL_CODE}: "
                f"found in Horoshop, "
                f"available={status}"
            )

        else:

            print(
                f"CONTROL {CONTROL_CODE}: "
                "exists on Prom, "
                "missing in Horoshop -> "
                "available=false"
            )

    else:

        print(
            f"CONTROL {CONTROL_CODE}: "
            "NOT FOUND in Prom export"
        )


if __name__ == "__main__":
    main()
