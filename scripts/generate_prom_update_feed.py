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

    # Map every published Prom article to the existing Prom product ID.
    prom_ids = {}
    duplicate_codes = set()
    for offer in prom_root.xpath(".//offer"):
        code = vendor_code(offer)
        product_id = offer.get("id")
        if not code or not product_id:
            continue
        if code in prom_ids:
            duplicate_codes.add(code)
            continue
        prom_ids[code] = product_id

    source_by_code = {
        vendor_code(offer): offer
        for offer in horoshop_root.xpath(".//offer")
        if vendor_code(offer)
    }

    # Keep the Horoshop catalog metadata, but replace the offers with a minimal
    # update-only feed. Prom IDs prevent creation of duplicate product cards.
    output_root = deepcopy(horoshop_root)
    offers_parent = output_root.find(".//offers")
    if offers_parent is None:
        raise RuntimeError("Horoshop feed does not contain an offers element")
    for child in list(offers_parent):
        offers_parent.remove(child)

    matched = 0
    for code, prom_id in prom_ids.items():
        source = source_by_code.get(code)
        if source is None:
            continue

        offer = etree.SubElement(
            offers_parent,
            "offer",
            id=prom_id,
            available=source.get("available", ""),
        )

        # These fields are sufficient for the selected Prom update settings.
        for tag in ("price", "oldprice", "currencyId", "categoryId", "vendorCode", "name", "name_ua"):
            element = source.find(tag)
            if element is not None and element.text is not None:
                offer.append(deepcopy(element))

        matched += 1

    os.makedirs("public", exist_ok=True)
    etree.ElementTree(output_root).write(
        "public/prom-update.xml",
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    )

    missing = len(prom_ids) - matched
    print(f"Done: {matched} matched products, {missing} missing in Horoshop")
    if duplicate_codes:
        print(f"Skipped duplicate Prom article entries: {sorted(duplicate_codes)}")


if __name__ == "__main__":
    main()
