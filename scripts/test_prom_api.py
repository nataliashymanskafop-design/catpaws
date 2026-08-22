import os
import requests
import json

TOKEN = os.environ["PROM_API_TOKEN"]

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

url = "https://my.prom.ua/api/v1/products/list"

all_products = []
last_id = None

while True:
    params = {"limit": 100}

    if last_id is not None:
        params["last_id"] = last_id

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    print("HTTP:", response.status_code)
    response.raise_for_status()

    data = response.json()
    products = data.get("products", [])

    if not products:
        break

    all_products.extend(products)

    print("Downloaded:", len(all_products), "products")

    if len(products) < 100:
        break

    last_id = products[-1].get("id")

    if not last_id:
        break


print()
print("=" * 70)
print("TOTAL PROM PRODUCTS:", len(all_products))
print("=" * 70)


# ---------------------------------------------------------
# Покажемо структуру перших 3 товарів, як її реально віддає API
# ---------------------------------------------------------

for i, product in enumerate(all_products[:3], start=1):
    print()
    print("=" * 70)
    print(f"PRODUCT #{i}")
    print("=" * 70)

    print(
        json.dumps(
            product,
            ensure_ascii=False,
            indent=2,
        )
    )


# ---------------------------------------------------------
# Пошук контрольного артикула у ВСІХ полях
# ---------------------------------------------------------

CONTROL = "3C000412"

print()
print("=" * 70)
print("SEARCHING FOR:", CONTROL)
print("=" * 70)

found = []

for product in all_products:
    product_text = json.dumps(
        product,
        ensure_ascii=False,
    )

    if CONTROL.lower() in product_text.lower():
        found.append(product)


if found:
    print(f"FOUND: {len(found)}")

    for product in found:
        print()
        print(
            json.dumps(
                product,
                ensure_ascii=False,
                indent=2,
            )
        )
else:
    print("CONTROL", CONTROL, "NOT FOUND ANYWHERE IN API RESPONSE")
