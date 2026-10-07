"""Serialize feed prices as plain decimal numbers for Horoshop imports."""
from decimal import Decimal, InvalidOperation
import re

PRICE_TAGS = {"price", "oldprice", "purchaseprice"}


def normalize_price(value):
    text = re.sub(r"[\s\u200b\ufeff]+", "", str(value or "")).replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ValueError(f"Invalid feed price: {value!r}")
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError(f"Invalid feed price: {value!r}") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"Invalid feed price: {value!r}")
    return format(number, "f")


def normalize_feed_prices(root):
    changed = 0
    for offer in root.xpath(".//offer"):
        for field in offer:
            if field.tag.lower() not in PRICE_TAGS:
                continue
            normalized = normalize_price(field.text)
            changed += field.text != normalized
            field.text = normalized
    return changed
