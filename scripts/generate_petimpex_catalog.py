"""PetImpex retail catalog with import-safe prices and supplier SKU identifiers."""
import os
from lxml import etree
from generate_home_food_stock import download
from normalize_feed_prices import normalize_feed_prices, normalize_price

SOURCE_URL = "https://files.petimpex.com/shimanskay/Shimanskaya.xml.yml"
OUTPUT_FILE = "public/petimpex-clean.xml"


def clean_catalog(payload):
    root = etree.fromstring(payload)
    offers = root.xpath(".//offer")
    if len(offers) < 1000:
        raise RuntimeError(f"PetImpex source incomplete: {len(offers)} offers")
    changed = normalize_feed_prices(root)
    seen = set()
    priced = 0
    for offer in offers:
        code = str(offer.get("id") or "").strip()
        if not code or code in seen:
            raise RuntimeError(f"Missing or duplicate PetImpex article: {code}")
        seen.add(code)
        # Original vendorCode contains EAN, while offer id contains the SKU.
        # Use the actual SKU in both fields so an import cannot confuse EAN/id.
        vendor_code = offer.find("vendorCode")
        if vendor_code is not None and vendor_code.text:
            ean = vendor_code.text.strip()
            if ean != code and offer.find("barcode") is None:
                etree.SubElement(offer, "barcode").text = ean
        else:
            vendor_code = etree.SubElement(offer, "vendorCode")
        vendor_code.text = code
        for field in list(offer):
            if field.tag.lower() in {"purchaseprice", "wholesaleprice", "cost"}:
                offer.remove(field)
        value = offer.findtext("price")
        if value is not None:
            if normalize_price(value) != value:
                raise RuntimeError(f"Price serialization failed: {code}")
            priced += 1
    if priced < 1000:
        raise RuntimeError(f"PetImpex retail prices incomplete: {priced}")
    return root, len(offers), priced, changed


def main():
    root, count, priced, changed = clean_catalog(download(SOURCE_URL))
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    temporary = OUTPUT_FILE + ".tmp"
    etree.ElementTree(root).write(temporary, encoding="UTF-8", xml_declaration=True)
    os.replace(temporary, OUTPUT_FILE)
    print(f"PetImpex clean retail catalog: {count} offers; {priced} retail prices; "
          f"{changed} price fields normalized; numeric price format verified")
    print(f"Created: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
