"""Josera partner feed mapped to site units and bundles; stock is conditional."""
import re
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from lxml import etree

JOSERA_URL = "https://josera.ua/feeds/JoseraPartners.xml"
CATALOG_URL = "https://catpaws.com.ua/content/export/9ba864d51aeb3249ffc3b374be058b88.xml"
BRANDS = {"josera", "josidog", "josicat", "green petfood", "bavaro"}
MIN_SOURCE_PRODUCTS = 100
MIN_SITE_PRODUCTS = 100
DRY_STOCK = 20
WET_STOCK = 60
THRESHOLD = 5


def clean(value):
    return " ".join(str(value or "").split())


def money(value):
    try:
        result = Decimal("".join(str(value or "").split()).replace(",", "."))
        return result if result.is_finite() and result > 0 else None
    except InvalidOperation:
        return None


def number(value):
    try:
        return Decimal(clean(value).replace(",", "."))
    except InvalidOperation:
        return None


def pack_weight(text):
    # Site weights: 900 г*5; source titles: 5 * 900 г.
    text = clean(text).lower()
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(кг|г)\b", text)
    if not match:
        return None
    unit = Decimal(match[1].replace(",", ".")) * (1000 if match[2] == "кг" else 1)
    after = re.search(r"\b(?:кг|г)\s*\*\s*(\d+)", text)
    before = re.search(r"(\d+)\s*\*\s*\d+(?:[.,]\d+)?\s*(?:кг|г)\b", text)
    count = int(after[1]) if after else int(before[1]) if before else 1
    return unit, count


def read_supplier(payload):
    root = etree.fromstring(payload)
    products = {}
    for offer in root.xpath(".//offer"):
        code = clean(offer.findtext("vendor_code"))
        if not code:
            raise RuntimeError("Josera offer has no vendor_code")
        if code in products:
            raise RuntimeError(f"Duplicate Josera source SKU: {code}")
        status = clean(offer.findtext("availability")).casefold()
        if status not in {"in stock", "out of stock"}:
            raise RuntimeError(f"Unknown Josera availability: {code}: {status}")
        if clean(offer.findtext("currency")) != "UAH":
            raise RuntimeError(f"Unknown Josera currency: {code}")
        pack = pack_weight(offer.findtext("title"))
        weight = number(offer.findtext("weight"))
        if pack is None or weight is None or weight <= 0:
            raise RuntimeError(f"Missing Josera pack weight: {code}")
        unit, count = pack
        if abs(unit * count - weight * 1000) > Decimal("1"):
            raise RuntimeError(f"Inconsistent Josera pack weight: {code}")
        products[code] = {
            "available": status == "in stock",
            "unit_grams": unit, "pack_size": count,
            "price": money(offer.findtext("price")),
            "sale_price": money(offer.findtext("sale_price")),
            "title": clean(offer.findtext("title")),
        }
    if len(products) < MIN_SOURCE_PRODUCTS:
        raise RuntimeError(f"Josera source incomplete: {len(products)}")
    return products


def map_catalog(payload, supplier):
    root = etree.fromstring(payload)
    offers = [o for o in root.xpath(".//offer")
              if clean(o.findtext("vendor")).casefold() in BRANDS]
    if len(offers) < MIN_SITE_PRODUCTS:
        raise RuntimeError(f"Josera site catalog incomplete: {len(offers)}")
    counts = Counter(clean(o.findtext("vendorCode")) for o in offers)
    rows = {}
    missing = []
    for offer in offers:
        code = clean(offer.findtext("vendorCode"))
        if not code or counts[code] > 1:
            raise RuntimeError(f"Ambiguous Josera site SKU: {code}")
        match = re.fullmatch(r"(\d+)(?:[pр]|\*\d+|_box)?", code)
        base = match[1] if match else code
        source = supplier.get(base)
        weight = next((p.text for p in offer.findall("param")
                       if p.get("name") == "Вага"), None)
        pack = pack_weight(weight)
        if pack is None:
            raise RuntimeError(f"Missing site pack weight: {code}")
        unit, count = pack
        # A matching numeric SKU alone is insufficient: also verify unit size.
        matched = source is not None and abs(unit - source["unit_grams"]) <= Decimal("1")
        if not matched:
            missing.append(code)
        price = None
        if matched and source["price"] is not None:
            price = str((source["price"] / source["pack_size"] * count).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP))
        sale_price = None
        if matched and source.get("sale_price") is not None and source["price"] is not None:
            if source["sale_price"] < source["price"]:
                sale_price = str((source["sale_price"] / source["pack_size"] * count).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP))
        rows[code] = {
            "base": base, "pack_size": count,
            "target": WET_STOCK if unit < 200 or "волог" in clean(offer.findtext("name_ua") or offer.findtext("name")).casefold() else DRY_STOCK,
            "available": bool(matched and source["available"]),
            "price": price, "sale_price": sale_price, "matched": matched,
        }
    return rows, missing


def stock_targets(rows):
    targets = {}
    for row in rows.values():
        base = row["base"]
        target = row["target"] if row["available"] else 0
        if base in targets and targets[base] != target:
            raise RuntimeError(f"Conflicting Josera availability/policy: {base}")
        targets[base] = target
    return targets


def order_snapshot(order, rows):
    # This is a virtual supplier allowance, not physical inventory.
    # Count Josera sales across the store; exact own stock stays independent.
    snapshot = {}
    for item in order.get("products") or []:
        code = clean(item.get("sku"))
        if code not in rows:
            continue
        try:
            amount = max(0, int(Decimal(str(item.get("amount") or 0))))
        except (InvalidOperation, ValueError):
            continue
        if amount:
            snapshot[code] = snapshot.get(code, 0) + amount
    return snapshot


def calculate(rows, previous, orders, initializing=False):
    targets = stock_targets(rows)
    old_base = previous.get("base_stock", {}) if previous else {}
    base_stock = {base: max(0, int(old_base.get(base, target)))
                  for base, target in targets.items()}
    snapshots = dict(previous.get("order_snapshots", {})) if previous else {}
    for order in orders:
        key = str(order.get("id"))
        current = order_snapshot(order, rows)
        old = snapshots.get(key, {})
        if not initializing:
            for code in set(old) | set(current):
                if code not in rows:
                    continue
                row = rows[code]
                delta = (current.get(code, 0) - old.get(code, 0)) * row["pack_size"]
                base = row["base"]
                base_stock[base] = max(0, base_stock[base] - delta)
        if current or key in snapshots:
            snapshots[key] = current
    for base, target in targets.items():
        if target == 0:
            base_stock[base] = 0
        elif base_stock[base] <= THRESHOLD:
            base_stock[base] = target
        else:
            base_stock[base] = min(base_stock[base], target)
    published = {code: base_stock[row["base"]] // row["pack_size"]
                 for code, row in rows.items()}
    return base_stock, snapshots, published
