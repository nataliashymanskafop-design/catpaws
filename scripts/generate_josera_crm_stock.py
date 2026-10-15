"""Publish Josera-only CRM quantities using the already calculated TERRAVET state."""
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from lxml import etree

STATE_FILE = "public/terravet-stock-state.json"
OUTPUT_FILE = "public/josera-crm-stock.xml"
CATALOG_URL = "https://catpaws.com.ua/content/export/9ba864d51aeb3249ffc3b374be058b88.xml"


def build_feed(state, catalog):
    base_stock = (state.get("josera") or {}).get("base_stock")
    published = state.get("published_stock")
    if not isinstance(base_stock, dict) or not base_stock or not isinstance(published, dict):
        raise RuntimeError("Calculated Josera stock state is missing")
    quantities = {}
    for sku, quantity in published.items():
        match = re.fullmatch(r"(\d+)(?:[pр]|\*\d+|_box)?", sku)
        base = match[1] if match else sku
        if base not in base_stock:
            continue
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 0:
            raise RuntimeError(f"Invalid calculated Josera quantity: {sku}")
        quantities[sku] = quantity
    if len(quantities) < 100:
        raise RuntimeError(f"Josera CRM stock is incomplete: {len(quantities)}")

    names = {}
    prices = {}
    retail_prices = state.get("retail_prices") or {}
    for offer in catalog.xpath(".//offer"):
        sku = (offer.findtext("vendorCode") or "").strip()
        if sku not in quantities:
            continue
        if sku in names:
            raise RuntimeError(f"Ambiguous Josera catalog SKU: {sku}")
        names[sku] = offer.findtext("name_ua") or offer.findtext("name") or sku
        # Use the same unit/bundle retail prices already calculated for the site.
        # Unmatched supplier articles keep the regular price in the site catalog.
        raw_price = retail_prices.get(sku) or offer.findtext("oldprice") or offer.findtext("price")
        try:
            price = Decimal("".join(str(raw_price or "").split()).replace(",", "."))
        except InvalidOperation as error:
            raise RuntimeError(f"Invalid Josera retail price: {sku}") from error
        if not price.is_finite() or price <= 0:
            raise RuntimeError(f"Invalid Josera retail price: {sku}")
        prices[sku] = format(price.quantize(Decimal("0.01")), "f")
    if set(quantities) - set(names):
        raise RuntimeError("Calculated Josera articles are missing from the catalog")

    root = etree.Element("yml_catalog", date=datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%Y-%m-%d %H:%M"))
    shop = etree.SubElement(root, "shop")
    offers = etree.SubElement(shop, "offers")
    for sku, quantity in sorted(quantities.items()):
        offer = etree.SubElement(offers, "offer", id=sku, available="true" if quantity > 0 else "false")
        etree.SubElement(offer, "vendorCode").text = sku
        etree.SubElement(offer, "name").text = names[sku]
        etree.SubElement(offer, "quantity_in_stock").text = str(quantity)
        etree.SubElement(offer, "price").text = prices[sku]
        etree.SubElement(offer, "currencyId").text = "UAH"
    return root


def main():
    from generate_home_food_stock import download

    with open(STATE_FILE, encoding="utf-8") as handle:
        state = json.load(handle)
    root = build_feed(state, etree.fromstring(download(CATALOG_URL)))
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    temporary = OUTPUT_FILE + ".tmp"
    etree.ElementTree(root).write(temporary, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    os.replace(temporary, OUTPUT_FILE)
    print(f"Josera CRM feed: {len(root.xpath('.//offer'))} articles; existing calculated unit/bundle quantities and retail prices")


if __name__ == "__main__":
    main()
