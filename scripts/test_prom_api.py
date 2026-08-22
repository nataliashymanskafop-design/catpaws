import os
import sys
import requests


PROM_API_URL = "https://my.prom.ua/api/v1"
CONTROL_CODE = "3C000412"


def main():
    token = os.environ.get("PROM_API_TOKEN")

    if not token:
        print("ERROR: PROM_API_TOKEN is not set")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print("Connecting to Prom API...")

    products = []
    last_id = None

    while True:
        params = {
            "limit": 100,
        }

        if last_id is not None:
            params["last_id"] = last_id

        response = requests.get(
            f"{PROM_API_URL}/products/list",
            headers=headers,
            params=params,
            timeout=60,
        )

        print("HTTP:", response.status_code)

        if response.status_code != 200:
            print(response.text)
            sys.exit(1)

        data = response.json()
        batch = data.get("products", [])

        if not batch:
            break

        products.extend(batch)

        print(
            f"Downloaded: {len(products)} products"
        )

        if len(batch) < 100:
            break

        last_id = batch[-1].get("id")

        if not last_id:
            break

    print()
    print("==============================")
    print(f"TOTAL PROM PRODUCTS: {len(products)}")
    print("==============================")

    found = []

    for product in products:

        external_id = str(
            product.get("external_id", "")
        ).strip()

        sku = str(
            product.get("sku", "")
        ).strip()

        product_id = product.get("id")

        if (
            external_id == CONTROL_CODE
            or sku == CONTROL_CODE
        ):
            found.append(product)

            print()
            print("CONTROL PRODUCT FOUND!")
            print("Prom ID:", product_id)
            print("external_id:", external_id)
            print("sku:", sku)
            print("name:", product.get("name"))
            print("presence:", product.get("presence"))
            print("price:", product.get("price"))

    if not found:
        print()
        print(
            f"CONTROL {CONTROL_CODE}: "
            "NOT FOUND VIA API"
        )


if __name__ == "__main__":
    main()
