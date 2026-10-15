"""Publish Josera-only CRM quantities using the already calculated TERRAVET state."""
import json
import os
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from lxml import etree
from josera_stock import pack_weight

STATE_FILE = "public/terravet-stock-state.json"
OUTPUT_FILE = "public/josera-crm-stock.xml"
PURCHASE_FILE = "data/josera-purchase-prices.json"
CATALOG_URL = "https://catpaws.com.ua/content/export/9ba864d51aeb3249ffc3b374be058b88.xml"


def build_feed(state, catalog, purchase_prices):
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
    purchase_costs = {}
    sale_prices = {}
    if "sale_prices" not in state:
        raise RuntimeError("Josera promotional price state is not yet generated")
    retail_prices = state.get("retail_prices") or {}
    for offer in catalog.xpath(".//offer"):
        sku = (offer.findtext("vendorCode") or "").strip()
        if sku not in quantities:
            continue
        if sku in names:
            raise RuntimeError(f"Ambiguous Josera catalog SKU: {sku}")
        names[sku] = offer.findtext("name_ua") or offer.findtext("name") or sku
        base_match = re.fullmatch(r"(\d+)(?:[pр]|\*\d+|_box)?", sku)
        base = base_match[1] if base_match else sku
        purchase = purchase_prices.get(base)
        weight = next((p.text for p in offer.findall("param") if p.get("name") == "Вага"), None)
        pack = pack_weight(weight)
        if not purchase or not pack or abs(pack[0] - Decimal(purchase["unit_grams"])) > 1:
            raise RuntimeError(f"Unmatched Josera purchase price or unit size: {sku}")
        cost = Decimal(purchase["unit_cost"])
        if not cost.is_finite() or cost <= 0:
            raise RuntimeError(f"Invalid Josera purchase price: {sku}")
        purchase_costs[sku] = format((cost * pack[1]).quantize(Decimal("0.01")), "f")
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
        raw_sale = state["sale_prices"].get(sku)
        if raw_sale is not None:
            try:
                sale = Decimal("".join(str(raw_sale).split()).replace(",", "."))
            except InvalidOperation as error:
                raise RuntimeError(f"Invalid Josera promotional price: {sku}") from error
            if not sale.is_finite() or not 0 < sale < price:
                raise RuntimeError(f"Invalid Josera promotional price: {sku}")
            sale_prices[sku] = format(sale.quantize(Decimal("0.01")), "f")
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
        etree.SubElement(offer, "price").text = sale_prices.get(sku, prices[sku])
        # Equal price/oldprice explicitly clears a discount after a promotion ends.
        etree.SubElement(offer, "oldprice").text = prices[sku]
        etree.SubElement(offer, "currencyId").text = "UAH"
        etree.SubElement(offer, "vendorprice").text = purchase_costs[sku]
    return root


def main():
    from generate_home_food_stock import download

    with open(STATE_FILE, encoding="utf-8") as handle:
        state = json.load(handle)
    with open(PURCHASE_FILE, encoding="utf-8") as handle:
        purchase_prices = json.load(handle)["products"]
    root = build_feed(state, etree.fromstring(download(CATALOG_URL)), purchase_prices)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    temporary = OUTPUT_FILE + ".tmp"
    etree.ElementTree(root).write(temporary, encoding="UTF-8", xml_declaration=True, pretty_print=True)
    os.replace(temporary, OUTPUT_FILE)
    print(f"Josera CRM feed: {len(root.xpath('.//offer'))} articles; existing calculated unit/bundle quantities, retail/promotional prices and spreadsheet purchase costs")


if __name__ == "__main__":
    main()
