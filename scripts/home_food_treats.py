"""HOME FOOD packaging and availability confirmed by Natalia.

Keep the current packaging and bundle recipes available while the full Horoshop
import catches up. Other brands and the discontinued 1016008 pack are untouched.
"""

import json
from pathlib import Path

from lxml import etree


CATALOG_FILE = Path(__file__).resolve().parents[1] / "data/home-food-treats.json"
with CATALOG_FILE.open(encoding="utf-8") as source:
    TREAT_CATALOG = json.load(source)

# Share cat recipes with the stock generator so unavailable components also
# block their sets in feeds that receive stale positive bundle stock.
CAT_TREAT_BUNDLES = {
    "70100_box1": dict.fromkeys(
        ("7010040", "7010044", "7010046", "7010033", "7010042", "7010048"), 1
    ),
    "70100_box2": dict.fromkeys(
        ("7010036", "7010033", "7010031", "7010038", "7010035"), 1
    ),
    "70100_box3": dict.fromkeys(
        ("7010040", "7010036", "7010038", "7010035", "7010029", "7010027"), 1
    ),
    "70100_box4": dict.fromkeys(
        ("7010040", "7010044", "7010046", "7010036", "7010033", "7010031",
         "7010042", "7010048", "7010038", "7010035", "7010029", "7010027"), 1
    ),
}

# Temporary unavailability confirmed on 2026-11-17 and 2026-11-19. Keep these cards, but do
# not let the previous all-available confirmation restore them on the next run.
TEMPORARILY_UNAVAILABLE_TREATS = {"1016060", "1090018", "1038028", "7010028", "7010029"}
UNAVAILABLE_TREAT_SKUS = TEMPORARILY_UNAVAILABLE_TREATS | {
    sku for sku, components in {
        **CAT_TREAT_BUNDLES,
        **{sku: record.get("components") or [] for sku, record in TREAT_CATALOG.items()},
    }.items()
    if any(component in TEMPORARILY_UNAVAILABLE_TREATS for component in components)
}


def restore_confirmed_treats(root):
    offers = root.find(".//offers")
    if offers is None:
        return root
    by_sku = {}
    for offer in offers.findall("offer"):
        sku = str(offer.findtext("vendorCode") or "").strip()
        by_sku.setdefault(sku, []).append(offer)

    for sku, record in TREAT_CATALOG.items():
        matching = by_sku.get(sku, [])
        if len(matching) > 1:
            # Preserve the normal duplicate-SKU checks; do not choose a card.
            continue
        missing = not matching
        offer = matching[0] if matching else etree.SubElement(offers, "offer", id=sku)
        offer.set("available", "false" if sku in UNAVAILABLE_TREAT_SKUS else "true")

        def put(tag, value):
            node = offer.find(tag)
            if node is None:
                node = etree.SubElement(offer, tag)
            node.text = str(value)

        if missing:
            for tag, value in {
                "vendorCode": sku, "name": record["name"], "name_ua": record["name"],
                "vendor": "HOME FOOD", "price": f'{record["price"]:.2f}',
                "currencyId": "UAH", "categoryId": "1088", "url": record["url"],
            }.items():
                put(tag, value)
        if record.get("components"):
            put("name", record["name"])
            put("name_ua", record["name"])
            put("description", record["description"])
            for param in offer.findall("param"):
                if "ваг" in str(param.get("name") or "").casefold():
                    param.text = f'{record["weight_grams"]} г'
            put("weight", f'{record["weight_grams"] / 1000:g}')
        if sku == "70100_box7":
            put("price", f'{record["price"]:.2f}')
            for tag in ("oldprice", "old_price"):
                for node in offer.findall(tag):
                    offer.remove(node)
        if missing or record.get("components"):
            for picture in offer.findall("picture"):
                offer.remove(picture)
            for url in record["pictures"]:
                etree.SubElement(offer, "picture").text = url
    for sku in UNAVAILABLE_TREAT_SKUS:
        for offer in by_sku.get(sku, []):
            offer.set("available", "false")
    return root
