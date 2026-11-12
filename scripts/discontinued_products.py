"""Permanent feed exclusions confirmed by Natalia on 2026-11-12.

The November DOMS notice supersedes the November 2 stock snapshot.
Unknown/obsolete articles are also matched by recipe AND exact pack size.
Platform cards are removed manually; these rules only control exported data.
"""

import re


DOMS_DISCONTINUED_SKUS = {
    "011117",  # CAT MAT, 60 x 80 cm, blue.
    "020695",  # Chicopee HNL Cat Kitten, 1.5 kg.
    "015370",  # Chicopee CNL Dog Maxi Adult Poultry & Millet, 15 kg.
    "015417",  # Chicopee CNL Dog Adult Light Lamb & Rice, 15 kg.
    "017954",  # Chicopee CNL Cat Adult Beauty Salmon, 15 kg.
}
HOME_FOOD_LUNG_SKUS = {"1016008", "3016004", "3016004_", "1090018"}
HOME_FOOD_LUNG_BUNDLE_SKUS = {
    "70100_box7",  # Beef Mix includes beef lung, 1016008.
    "70100_box9",  # Premium Mix includes rabbit lung, 1090018.
}
DISCONTINUED_SKUS = (
    DOMS_DISCONTINUED_SKUS
    | HOME_FOOD_LUNG_SKUS
    | HOME_FOOD_LUNG_BUNDLE_SKUS
)
_RETIRED_CODES = {sku.casefold() for sku in DISCONTINUED_SKUS}


def normalized(value):
    return " ".join(str(value or "").casefold().split())


def pack_grams(name):
    matches = re.findall(r"(\d+(?:[.,]\d+)?)\s*(кг|kg|гр|г|g)\b", name)
    if not matches:
        return None
    amount, unit = matches[-1]
    return round(float(amount.replace(",", ".")) * (1000 if unit in {"кг", "kg"} else 1))


def contains(name, *fragments):
    return any(fragment in name for fragment in fragments)


def is_discontinued(sku, name="", vendor=""):
    sku = str(sku or "").strip()
    if sku.casefold() in _RETIRED_CODES:
        return True
    # Boxes of a retired item must not survive as independent offers.
    base = re.split(r"(?:_box\d*|-\d+|\*\d+(?:шт\.?)?)$", sku, maxsplit=1, flags=re.IGNORECASE)[0]
    if base.casefold() in _RETIRED_CODES:
        return True

    name = normalized(name)
    brand = re.sub(r"\W+", "", normalized(vendor))
    compact_name = re.sub(r"\W+", "", name)
    if brand == "homefood" or "homefood" in compact_name:
        # Match the standalone lung treats, not food ingredients or braids.
        return (
            bool(re.search(r"\b(?:леген\w*|легк(?:ие|ое|их)|lungs?)\b", name))
            and not contains(name, "косич", "braid", "сухий корм", "сухой корм", "dry food")
        )

    if brand == "catmat" and re.search(r"60\s*[xх×]\s*80", name):
        return contains(name, "синій", "синий", "blue")

    if brand != "chicopee" and "chicopee" not in name:
        return False
    grams = pack_grams(name)
    hnl = contains(name, "hnl", "holistic nature", "holistic")
    cnl = contains(name, "cnl", "classic nature")
    cat = contains(name, "cat", "кот", "кошен", "кіш", "кіт")
    if hnl and grams == 1500:
        return (contains(name, "kitten", "кіттен", "киттен")
                or (cat and contains(name, "стерил", "steriliz", "sterilis")))
    if hnl and grams == 2000:
        return (contains(name, "ostrich", "страус")
                and contains(name, "soft", "софт")
                and contains(name, "adult", "едалт", "эдалт", "доросл", "взросл"))
    if cnl and grams == 15000:
        return (
            contains(name, "new life", "нью лайф")
            or (cat and contains(name, "junior", "джуніор", "джуниор"))
            or contains(name, "castrat", "кастрат")
            or contains(name, "beauty", "б'юті", "б’юті", "бюті", "бьюти")
            or (contains(name, "maxi", "максі", "макси")
                and contains(name, "adult", "едалт", "эдалт", "доросл", "взросл")
                and contains(name, "poultry", "птиц", "птах")
                and contains(name, "millet", "просо"))
            or (contains(name, "light", "лайт")
                and contains(name, "lamb", "ягня", "ягнен")
                and contains(name, "rice", "рис"))
        )
    if cnl and grams == 2000:
        return (
            contains(name, "senior", "сеніор", "сеньор", "літніх", "пожил")
            and contains(name, "chicken", "курк", "курч")
            and contains(name, "rice", "рис")
        )
    return False


def is_discontinued_offer(offer):
    return is_discontinued(
        offer.findtext("vendorCode"),
        offer.findtext("name") or offer.findtext("name_ua"),
        offer.findtext("vendor"),
    )
