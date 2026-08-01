import os
import requests
from lxml import etree


XML_URL = "https://catpaws.com.ua/content/export/4533d74998115a860f812d46074665c9.xml"
MIN_PRICE = 300

def main():
    print("Downloading product XML...")

    response = requests.get(XML_URL, timeout=120)
    response.raise_for_status()

    root = etree.fromstring(response.content)

    updated = 0

    for offer in root.xpath(".//offer"):
        price_text = offer.findtext("price")

        try:
            price = float(price_text)
        except (TypeError, ValueError):
            price = 0

        if price <= MIN_PRICE:
            offer.getparent().remove(offer)
            continue    
        vendor_code = offer.findtext("vendorCode")

        if not vendor_code:
            continue

        old_code = offer.find("code")

        if old_code is not None:
            offer.remove(old_code)

        code = etree.Element("code")
        code.text = vendor_code.strip()

        offer.insert(0, code)

        updated += 1

    os.makedirs("public", exist_ok=True)

    tree = etree.ElementTree(root)

    tree.write(
        "public/products-feed.xml",
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True
    )

    print(f"Done: added code to {updated} products")


if __name__ == "__main__":
    main()
