import requests
import json
import os
from datetime import datetime, timezone
from lxml import etree

XML_URL = "https://catpaws.com.ua/content/export/f58d0310c9401a7213540d5b6d75420a.xml"

print("Downloading XML...")

xml = requests.get(XML_URL, timeout=120).content

root = etree.fromstring(xml)

offers = []

for offer in root.xpath(".//offer"):

    code = offer.findtext("vendorCode")
    if not code:
        code = offer.get("id")

    price = int(float(offer.findtext("price", "0")))

    old = offer.findtext("oldprice")
    old_price = int(float(old)) if old else None

    country = offer.findtext("country_of_origin")

   offers.append({
    "code": code,
    "price": price,
    "old_price": old_price,
    "availability": offer.get("available") == "true",

    "stock": 999,

    "warehouses": [
        {
            "id": "SUPPLIER",
            "stock": 999
        }
    ],

    "warranty_type": "no",
    "warranty_period": 0,

    "max_pay_in_parts": 6,

    "days_to_dispatch": 0,

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
})
            {
                "method": "courier:nova-post",
                "price": 0
            }
        ],
        "manufacture": {
            "country_code": country
        } if country else None
    })

result = {
    "updatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
    "total": len(offers),
    "data": offers
}

os.makedirs("public", exist_ok=True)

with open("public/offers-response.json","w",encoding="utf8") as f:
    json.dump(result,f,ensure_ascii=False,indent=2)

print("Done:",len(offers),"offers")
