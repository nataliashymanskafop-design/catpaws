import json
import os

from lxml import etree

from generate_home_food_stock import download


STATE_FILE = "public/own-stock-state.json"
YML_URL_VARIABLE = "SALESDRIVE_OWN_STOCK_YML_URL"
MIN_PRODUCTS = 3000


def clean(value):
    return " ".join(str(value or "").split())


def parse_quantity(value):
    text = clean(value).replace(",", ".")

    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def load_exact_stock():
    url = os.environ.get(YML_URL_VARIABLE, "").strip()

    if not url:
        raise RuntimeError(
            f"GitHub secret {YML_URL_VARIABLE} is not configured"
        )

    root = etree.fromstring(download(url))
    published_stock = {}
    duplicate_skus = set()

    for offer in root.xpath(".//offer"):
        sku = clean(
            offer.findtext("vendorCode")
            or offer.findtext("article")
            or offer.get("id")
        )

        if not sku:
            continue

        quantity = parse_quantity(
            offer.findtext("quantity_in_stock")
        )

        if sku in published_stock:
            duplicate_skus.add(sku)
            # Однакові артикули можуть залишитися у старих дублях карток.
            # Беремо більше значення, але не сумуємо його двічі.
            quantity = max(published_stock[sku], quantity)

        published_stock[sku] = quantity

    if len(published_stock) < MIN_PRODUCTS:
        raise RuntimeError(
            "Own SalesDrive stock export is empty or incomplete: "
            f"only {len(published_stock)} products"
        )

    return (
        dict(sorted(published_stock.items())),
        sorted(duplicate_skus),
        clean(root.get("date")),
    )


def main():
    print("Downloading exact own SalesDrive stock...")
    published_stock, duplicate_skus, source_date = load_exact_stock()

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    temporary = f"{STATE_FILE}.tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            {
                "version": 1,
                "warehouse_id": "SUPPLIER",
                "source": "SalesDrive warehouse: FOP Shymanska",
                "source_date": source_date,
                "duplicate_skus": duplicate_skus,
                "published_stock": published_stock,
            },
            file,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        file.write("\n")

    os.replace(temporary, STATE_FILE)

    available = sum(
        quantity > 0
        for quantity in published_stock.values()
    )
    total_units = sum(published_stock.values())

    print(
        "Exact own stock generated: "
        f"{len(published_stock)} products, "
        f"{available} available, "
        f"{total_units} total units, "
        f"{len(duplicate_skus)} duplicate SKUs"
    )


if __name__ == "__main__":
    main()
