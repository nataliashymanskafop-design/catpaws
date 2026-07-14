import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from lxml import etree


XML_URL = "https://catpaws.com.ua/content/export/7b8be9ac1a32f219fa42e478828c728a.xml?1784021774060"
SUPPLIER_STOCK = 999
WAREHOUSE_ID = "1"


def to_int(value, default=0):
    if value is None:
        return default

    value = str(value).strip()

    if value == "":
        return default

    try:
        return int(float(value))
    except ValueError:
        return default


def get_days_to_dispatch():
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    weekday = now.weekday()

    if weekday == 5:
        return 2

    if weekday == 6:
        return 1

    if now.hour < 12:
        return 0

    if weekday == 4:
        return 3

    return 1


def build_offer(offer):
    code = offer.findtext("vendorCode")

    if not code:
        return None

    available = offer.get("available") == "true"

    stock = SUPPLIER_STOCK if available else 0

    old_price_text = offer.findtext("oldprice")
    old_price = to_int(old_price_text, None) if old_price_text else None

    return {
        "code": code.strip(),
        "price": to_int(offer.findtext("price")),
        "old_price": old_price,
        "availability": available,
        "stock": stock,
        "warehouses": [
            {
                "id": WAREHOUSE_ID,
                "stock": stock
            }
        ],
        "warranty_type": "no",
        "warranty_period": 0,
        "max_pay_in_parts": 6,
        "days_to_dispatch": get_days_to_dispatch(),
        "delivery_methods": [
            {
                "method": "nova-post:branch",
                "price": 0
            },
            {
                "method": "courier:nova-post",
                "price": 0
            }
        ],
        "manufacture": None
    }


def main():
    print("Downloading XML...")

    response = requests.get(XML_URL, timeout=120)
    response.raise_for_status()

    root = etree.fromstring(response.content)

    offers = []

    for offer in root.xpath(".//offer"):
        item = build_offer(offer)

        if item is not None:
            offers.append(item)

    result = {
        "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "total": len(offers),
        "data": offers
    }

    os.makedirs("public", exist_ok=True)

    with open("public/offers-response.json", "w", encoding="utf-8") as file:
        json.dump(result, file, ensure_ascii=False, indent=2)

    print(f"Done: {len(offers)} offers")


if __name__ == "__main__":
    main()
