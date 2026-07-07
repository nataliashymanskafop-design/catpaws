import json
import requests
from datetime import datetime, timezone
from lxml import etree

XML_URL = "https://catpaws.com.ua/content/export/f58d0310c9401a7213540d5b6d75420a.xml?1783426713710"

response = requests.get(XML_URL, timeout=60)
response.raise_for_status()

root = etree.fromstring(response.content)

offers = root.xpath(".//offer")

data = []

for offer in offers:

    code = offer.findtext("vendorCode")

    if not code:
        continue

    price = int(float(offer.findtext("price", "0")))

    old_price = offer.findtext("oldprice")

    if old_price:
        old_price = int(float(old_price))
    else:
        old_price = None

    available = offer.get("available") == "true"

    item = {
        "code": code,
        "price": price,
        "old_price": old_price,
        "availability": available,
        "stock": 999 if available else 0,
        "warehouses": [
            {
                "id": "SUPPLIER",
                "stock": 999 if available else 0
            }
        ],
        "warranty_type": "no",
        "warranty_period": 0,
        "max_pay_in_parts": 6,
        "delivery_methods": [
            {
                "method": "nova-post:branch",
                "price": 0
            },
            {
                "method": "nova-post:postomat",
                "price": 0
            },
            {
                "method": "courier:nova-post",
                "price": 0
            }
        ],
        "days_to_dispatch": 0,
        "manufacture": None
    }

    data.append(item)

feed = {
    "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    "total": len(data),
    "data": data
}

with open("offers-response.json", "w", encoding="utf-8") as f:
    json.dump(feed, f, ensure_ascii=False, indent=2)

print(f"Generated {len(data)} offers")
