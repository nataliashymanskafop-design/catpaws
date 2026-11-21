"""Keep Natalia's extra five Black Friday discount points on the site only.

The selection is the approved 2026 campaign, not every active promotion.
JosiCat and JosiDog already use only the supplier's 15% and are untouched.
An absent or changed site promotion automatically stops this adjustment.
"""

from decimal import Decimal, ROUND_CEILING
import re

from normalize_feed_prices import normalize_price


JOSERA_BLACK_FRIDAY_SKUS = {
    "50014781", "50014783", "50014801", "50014785", "50014820",
    "50014799", "50014717", "50014818", "50014778", "50014791",
    "50014712", "50014845", "50014718", "50014832", "50014789",
    "50014836", "50014842", "50014821", "50009986", "50005511",
    "50008779", "50005505", "50003279", "50007695", "50010350",
    "50003228", "50005508",
}
HOME_FOOD_BLACK_FRIDAY_DISCOUNTS = {
    "3058004": 30, "1047007": 30, "3048016": 30, "1128016": 30,
    "3199100": 25, "1018100": 25, "7000004": 25, "7000005": 25,
    "1028100": 25, "3058110": 25,
}


def mono_black_friday_prices(offer):
    """Return (whole-UAH price, regular price, discount %) for this campaign."""
    sku = (offer.findtext("vendorCode") or "").strip()
    vendor = "".join((offer.findtext("vendor") or "").split()).casefold()
    if vendor == "josera" and sku in JOSERA_BLACK_FRIDAY_SKUS:
        site_discount = 25
    elif vendor == "homefood" and sku in HOME_FOOD_BLACK_FRIDAY_DISCOUNTS:
        site_discount = HOME_FOOD_BLACK_FRIDAY_DISCOUNTS[sku]
    else:
        return None

    try:
        price = Decimal(normalize_price(offer.findtext("price")))
        regular = Decimal(normalize_price(offer.findtext("oldprice")))
    except ValueError:
        return None
    if not 0 < price < regular:
        return None
    expected = regular * (100 - site_discount) / 100
    # Horoshop rounds sale prices to hryvnias. A different campaign is not ours.
    if abs(price - expected) > 1:
        return None

    mono_discount = site_discount - 5
    mono_price = regular * (100 - mono_discount) / 100
    return (
        int(mono_price.to_integral_value(rounding=ROUND_CEILING)),
        int(regular),
        mono_discount,
    )


def update_black_friday_description(offer, discount):
    """Keep the exported campaign introduction consistent with the Mono price."""
    pattern = re.compile(
        r"(ЧОРНА\s+П[’'ʼ]?ЯТНИЦЯ[^:]{0,60}:\s*знижка\s*)\d+(?:[.,]\d+)?%",
        re.IGNORECASE,
    )
    for node in offer:
        if node.tag.lower().startswith("description") and node.text:
            node.text = pattern.sub(
                lambda match: f"{match.group(1)}{discount}%", node.text, count=1
            )
