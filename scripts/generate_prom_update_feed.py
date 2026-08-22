import os
from copy import deepcopy

import requests
from lxml import etree


HOROSHOP_URL = "https://catpaws.com.ua/content/export/77e6f1cd306feb32b68e245d1affc6bc.xml"

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


def main():
    print("Downloading Horoshop and Prom feeds...")

    horoshop_root = download_xml(HOROSHOP_URL)
    prom_root = download_xml(PROM_URL)

    # ---------------------------------------------------------
    # 1. Збираємо товари, які вже існують на Prom.
    #    Ключ = артикул (vendorCode)
    #    Значення = сам offer з Prom
    # ---------------------------------------------------------

    prom_offers = {}
    duplicate_codes = set()

    for offer in prom_root.xpath(".//offer"):
        code = vendor_code(offer)

        if not code:
            continue

        if code in prom_offers:
            duplicate_codes.add(code)
            continue

        prom_offers[code] = offer

    # ---------------------------------------------------------
    # 2. Збираємо актуальні товари Horoshop за артикулом.
    # ---------------------------------------------------------

    source_by_code = {
        vendor_code(offer): offer
        for offer in horoshop_root.xpath(".//offer")
        if vendor_code(offer)
    }

    # ---------------------------------------------------------
    # 3. Беремо структуру Horoshop, але очищаємо список товарів.
    # ---------------------------------------------------------

    output_root = deepcopy(horoshop_root)

    offers_parent = output_root.find(".//offers")

    if offers_parent is None:
        raise RuntimeError(
            "Horoshop feed does not contain an offers element"
        )

    for child in list(offers_parent):
        offers_parent.remove(child)

    matched = 0
    unavailable_missing = 0

    # ---------------------------------------------------------
    # 4. Формуємо update-feed ТІЛЬКИ для товарів,
    #    які вже існують на Prom.
    # ---------------------------------------------------------

    for code, prom_offer in prom_offers.items():

        prom_id = prom_offer.get("id")

        if not prom_id:
            continue

        source = source_by_code.get(code)

        # =====================================================
        # ТОВАР Є В HOROSHOP
        # =====================================================

        if source is not None:

            available = source.get("available", "false")

            offer = etree.SubElement(
                offers_parent,
                "offer",
                id=prom_id,
                available=available,
            )

            # Дані беремо з Horoshop.
            for tag in (
                "price",
                "oldprice",
                "currencyId",
                "categoryId",
                "vendorCode",
                "name",
                "name_ua",
            ):
                element = source.find(tag)

                if element is not None and element.text is not None:
                    offer.append(deepcopy(element))

            matched += 1

        # =====================================================
        # ТОВАР Є НА PROM, АЛЕ ЙОГО НЕМАЄ У ФІДІ HOROSHOP
        #
        # Раніше такі товари просто пропускались.
        # Через це Prom залишав старий статус "В наявності".
        #
        # Тепер явно передаємо available="false".
        # =====================================================

        else:

            offer = etree.SubElement(
                offers_parent,
                "offer",
                id=prom_id,
                available="false",
            )

            # Для ідентифікації залишаємо дані самого Prom.
            for tag in (
                "price",
                "oldprice",
                "currencyId",
                "categoryId",
                "vendorCode",
                "name",
                "name_ua",
            ):
                element = prom_offer.find(tag)

                if element is not None and element.text is not None:
                    offer.append(deepcopy(element))

            unavailable_missing += 1

            print(
                f"Marked unavailable: {code} "
                f"(exists on Prom, missing in Horoshop)"
            )

    # ---------------------------------------------------------
    # 5. Зберігаємо готовий файл.
    # ---------------------------------------------------------

    os.makedirs("public", exist_ok=True)

    etree.ElementTree(output_root).write(
        "public/prom-update.xml",
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    print()
    print(f"Matched with Horoshop: {matched}")
    print(
        f"Marked unavailable because missing in Horoshop: "
        f"{unavailable_missing}"
    )
    print(f"Total Prom products processed: {matched + unavailable_missing}")

    if duplicate_codes:
        print(
            "Skipped duplicate Prom article entries:",
            sorted(duplicate_codes),
        )


if __name__ == "__main__":
    main()
