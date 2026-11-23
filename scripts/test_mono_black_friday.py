import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from lxml import etree

import generate_feed as mono
import generate_products_feed as products
from mono_black_friday import mono_black_friday_prices, update_black_friday_description


def offer(sku, price, regular=None, vendor="JOSERA", description=None):
    result = etree.Element("offer", id=sku, available="true")
    fields = {"vendorCode": sku, "vendor": vendor, "name": sku, "price": str(price)}
    if regular is not None:
        fields["oldprice"] = str(regular)
    if description is not None:
        fields["description"] = description
    for key, value in fields.items():
        etree.SubElement(result, key).text = value
    return result


class MonoBlackFridayTests(unittest.TestCase):
    def test_josera_uses_the_exact_site_price_for_both_discount_levels(self):
        for sku, price, regular in [
            ("50003279", 2888, 3610),
            ("50014801", 2610, 3263),
            ("50005511", 3293, 4390),
            ("50014789", 4519, 6025),
        ]:
            source = offer(sku, price, regular)
            self.assertIsNone(mono_black_friday_prices(source))
            result = mono.build_offer(source, {}, {sku: 2})
            self.assertEqual((result["price"], result["old_price"]), (price, regular))

    def test_home_food_uses_supplier_discount_and_preserves_the_regular_price(self):
        self.assertEqual(mono_black_friday_prices(offer("3199100", 3101, 4134, "HOME FOOD")), (3308, 4134, 20))
        self.assertEqual(mono_black_friday_prices(offer("3058110", 2955, 3940, "HOME FOOD")), (3152, 3940, 20))
        self.assertEqual(mono_black_friday_prices(offer("3058004", 152, 217, "HOME FOOD")), (163, 217, 25))

    def test_josicat_and_josidog_supplier_fifteen_percent_is_unchanged(self):
        for sku, price, regular, vendor in [
            ("50006774", 1415, 1665, "JOSIDOG"),
            ("50012154", 2168, 2550, "JOSIDOG"),
            ("50009044", 1938, 2280, "JOSICAT"),
        ]:
            with self.subTest(sku=sku):
                source = offer(sku, price, regular, vendor)
                self.assertIsNone(mono_black_friday_prices(source))
                result = mono.build_offer(source, {}, {sku: 2})
                self.assertEqual((result["price"], result["old_price"]), (price, regular))

    def test_other_promotions_including_the_same_brands_are_unchanged(self):
        rows = [
            offer("other-josera", 1500, 2000),
            offer("50003229", 3069, 3610),
            offer("1038100", 2746, 3231, "HOME FOOD"),
            offer("3028016", 542, 677, "HOME FOOD"),
            offer("other-brand", 1500, 2000, "Nature's Protection"),
        ]
        for source in rows:
            self.assertIsNone(mono_black_friday_prices(source))

    def test_a_cleared_or_changed_campaign_is_never_recreated(self):
        for price, regular in [(3610, None), (3610, 3610), (3069, 3610), (0, 3610), (2708, "invalid")]:
            with self.subTest(price=price, regular=regular):
                self.assertIsNone(mono_black_friday_prices(offer("50003279", price, regular)))

    def test_campaign_text_is_corrected_without_changing_nutritional_percentages(self):
        source = offer("3199100", 3101, 4134, "HOME FOOD", "ЧОРНА П’ЯТНИЦЯ HOME FOOD: знижка 25%. Протеїн 25%.")
        update_black_friday_description(source, 20)
        self.assertEqual(source.findtext("description"), "ЧОРНА П’ЯТНИЦЯ HOME FOOD: знижка 20%. Протеїн 25%.")

    def test_both_published_formats_agree_and_apply_the_existing_price_floor_after_adjustment(self):
        source = etree.Element("yml_catalog")
        offers = etree.SubElement(etree.SubElement(source, "shop"), "offers")
        rows = [
            offer("50003279", 2888, 3610),
            offer("50005511", 3293, 4390),
            offer("3199100", 3101, 4134, "HOME FOOD"),
            offer("3058110", 2955, 3940, "HOME FOOD", "ЧОРНА П’ЯТНИЦЯ HOME FOOD: знижка 25%."),
            offer("50006774", 1415, 1665, "JOSIDOG"),
            offer("50009044", 1938, 2280, "JOSICAT"),
            offer("1038100", 2746, 3231, "HOME FOOD"),
            offer("1018100", 975, 1300, "HOME FOOD"),
            offer("1028100", 938, 1250, "HOME FOOD"),
            offer("3058004", 152, 217, "HOME FOOD"),
        ]
        offers.extend(rows)
        payload = etree.tostring(source)
        response = Mock(content=payload)
        response.raise_for_status.return_value = None
        stock = {r.findtext("vendorCode"): 2 for r in rows}
        cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as temp, patch.object(mono.requests, "get", return_value=response), \
                 patch.object(mono, "load_stock_sources", return_value={}), \
                 patch.object(mono, "load_own_stock", return_value=stock), \
                 patch.object(mono, "restore_confirmed_treats", side_effect=lambda root: root), \
                 patch.object(products, "restore_confirmed_treats", side_effect=lambda root: root), \
                 contextlib.redirect_stdout(io.StringIO()):
                os.chdir(temp)
                mono.main()
                products.main()
                price_feed = json.loads(Path("public/offers-response.json").read_text())
                catalog = etree.parse("public/products-feed.xml")
                actual = {x["code"]: (x["price"], x["old_price"]) for x in price_feed["data"]}
                xml_actual = {o.findtext("vendorCode"): (int(float(o.findtext("price"))), int(o.findtext("oldprice"))) for o in catalog.findall(".//offer")}
                self.assertEqual(actual, xml_actual)
                self.assertEqual(actual["50003279"], (2888, 3610))
                self.assertEqual(actual["50005511"], (3293, 4390))
                self.assertEqual(actual["50006774"], (1415, 1665))
                self.assertEqual(actual["50009044"], (1938, 2280))
                self.assertEqual(actual["1038100"], (2746, 3231))
                self.assertEqual(actual["1018100"], (1040, 1300))
                self.assertNotIn("1028100", actual)  # 1000 UAH is still below the strict floor.
                self.assertNotIn("3058004", actual)
                hairball = next(o for o in catalog.findall(".//offer") if o.findtext("vendorCode") == "3058110")
                self.assertIn("знижка 20%", hairball.findtext("description"))
                self.assertTrue(all(x["stock"] == 2 for x in price_feed["data"]))
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
