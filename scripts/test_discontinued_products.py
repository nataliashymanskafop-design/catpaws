import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lxml import etree

from discontinued_products import is_discontinued, is_discontinued_offer
import generate_feed as mono
import generate_products_feed as products_feed
import generate_doms_stock as doms
import generate_home_food_stock as home_food
import generate_site_stock_feed as site


RETIRED = [
    ("011117", "Килимок двошаровий для котячого лотка 60х80 - синій", "CAT MAT"),
    ("020695", "Chicopee HNL Cat Kitten 1.5 кг", "CHICOPEE"),
    ("old-sterilized", "Chicopee HNL Cat Sterilized Adult 1,5 кг", "CHICOPEE"),
    ("015370", "Chicopee CNL Dog Maxi Adult Poultry & Millet 15 кг", "CHICOPEE"),
    ("015417", "Chicopee CNL Dog Adult Light Lamb & Rice 15 кг", "CHICOPEE"),
    ("old-junior", "Chicopee CNL Cat JUNIOR New Life 15 кг", "CHICOPEE"),
    ("old-castrate", "Chicopee CNL Cat Adult Castrate 15 кг", "CHICOPEE"),
    ("017954", "Chicopee CNL Cat Adult Beauty Salmon 15 кг", "CHICOPEE"),
    ("old-senior", "Chicopee CNL Dog Senior Soft Chicken & Rice 2 кг", "CHICOPEE"),
    ("old-ostrich", "Chicopee HNL Dog Soft Adult Ostrich & Potato 2 кг", "CHICOPEE"),
    ("1016008", "Ласощі для собак HOME FOOD Легені яловичі, 80 г", "HOME FOOD"),
    ("3016004_", "Ласощі для котів HOME FOOD Легені яловичі, 40 г", "HOME FOOD"),
    ("70100_box7", "Набір ласощів HOME FOOD Яловичий мікс", "HOME FOOD"),
    ("1090018", "Ласощі для собак HOME FOOD Легені кролика, 80 г", "HOME FOOD"),
    ("70100_box9", "Набір ласощів HOME FOOD Преміальний мікс", "HOME FOOD"),
]
ACTIVE = [
    ("011115", "Килимок двошаровий для котячого лотка 60х80 - сірий", "CAT MAT"),
    ("020718", "Chicopee HNL Cat Kitten 8 кг", "CHICOPEE"),
    ("018166", "Chicopee HNL Cat Sterilized Adult 8 кг", "CHICOPEE"),
    ("026536", "Chicopee HNL Cat Sterilized Adult 400 г", "CHICOPEE"),
    ("015172", "Chicopee CNL Dog Maxi Puppy Poultry & Millet 15 кг", "CHICOPEE"),
    ("015394", "Chicopee CNL Dog Adult Light Lamb & Rice 2 кг", "CHICOPEE"),
    ("017916", "Chicopee CNL Cat JUNIOR New Life 1,5 кг", "CHICOPEE"),
    ("020640", "Chicopee CNL Cat Adult Castrate 1,5 кг", "CHICOPEE"),
    ("017947", "Chicopee CNL Cat Adult Beauty Salmon 1,5 кг", "CHICOPEE"),
    ("015455", "Chicopee CNL Dog Senior Soft Chicken & Rice 15 кг", "CHICOPEE"),
    ("015653", "Chicopee HNL Dog Soft Adult Ostrich & Potato 12 кг", "CHICOPEE"),
    ("70100_box6", "Набір HOME FOOD Довгожуйка", "HOME FOOD"),
    ("other-brand", "Легені яловичі, 80 г", "Another brand"),
    ("different-maxi", "Chicopee CNL Dog Maxi Adult Salmon & Rice 15 кг", "CHICOPEE"),
    ("1148016", "Сухий корм HOME FOOD Ягнятина з рисом, 1,6 кг", "HOME FOOD"),
]


def offer(row, price="1000"):
    sku, name, vendor = row
    result = etree.Element("offer", id=sku, available="true")
    for tag, value in [("vendorCode", sku), ("name", name), ("vendor", vendor), ("price", price)]:
        etree.SubElement(result, tag).text = value
    return result


class DiscontinuedProductsTests(unittest.TestCase):
    def test_all_ten_doms_notice_rows_and_lung_products_are_blocked(self):
        for row in RETIRED:
            with self.subTest(row=row):
                self.assertTrue(is_discontinued(*row))

    def test_obsolete_articles_are_caught_by_recipe_and_exact_pack_size(self):
        for _, name, vendor in RETIRED[:10]:
            with self.subTest(name=name):
                self.assertTrue(is_discontinued("unrecognized-article", name, vendor))

    def test_other_pack_sizes_recipes_colors_and_brands_are_unchanged(self):
        for row in ACTIVE:
            with self.subTest(row=row):
                self.assertFalse(is_discontinued(*row))

    def test_lung_boxes_and_lung_bundle_remain_blocked_with_stale_stock(self):
        for sku in ["1016008_box", "1016008-10", "1016008*10шт", "3016004_", "1090018", "70100_box7", "70100_BOX7", "70100_box9", "1016008_BOX"]:
            with self.subTest(sku=sku):
                self.assertTrue(is_discontinued(sku))
        self.assertEqual(home_food.calculate_stock("1016008", {"1016008": 999}), 0)
        self.assertEqual(home_food.calculate_stock("70100_box7", {s:999 for s in home_food.BUNDLES['70100_box7']}), 0)

    def test_doms_stale_stock_is_zeroed_and_not_replenished_or_exported(self):
        rows = RETIRED[:10] + [ACTIVE[0]]
        catalog = {s:{"name":n,"brand":v.casefold().replace(' ','')} for s,n,v in rows}
        stock = {s:20 for s,_,_ in rows}
        doms.replenish(catalog, stock)
        for sku,_,_ in RETIRED[:10]:
            self.assertEqual(stock[sku], 0)
        self.assertEqual(stock[ACTIVE[0][0]], 20)
        codes = doms.build_yml(catalog, stock).xpath('.//vendorCode/text()')
        self.assertEqual(codes, [ACTIVE[0][0]])

    def test_home_food_supplier_feed_omits_lungs_and_beef_mix(self):
        rows = RETIRED[10:] + [ACTIVE[11]]
        products = {s:n for s,n,_ in rows}
        stock = {s:999 for s in products}
        codes = home_food.build_yml(products, stock).xpath('.//vendorCode/text()')
        self.assertEqual(codes, [ACTIVE[11][0]])

    def test_mono_stock_cannot_override_a_retired_product(self):
        for row in RETIRED:
            with self.subTest(row=row):
                self.assertIsNone(mono.build_offer(offer(row), {}, {row[0]:999}))
        self.assertIsNotNone(mono.build_offer(offer(ACTIVE[1]), {}, {ACTIVE[1][0]:3}))

    def test_xml_and_json_mono_feeds_exclude_the_same_retired_products(self):
        root=etree.Element('yml_catalog')
        offers=etree.SubElement(root,'offers')
        for row in RETIRED+[ACTIVE[1]]:
            offers.append(offer(row))
        class Response:
            content=etree.tostring(root)
            def raise_for_status(self): pass
        with tempfile.TemporaryDirectory() as tmp:
            old=os.getcwd()
            try:
                os.chdir(tmp)
                with patch.object(products_feed.requests,'get',return_value=Response()), contextlib.redirect_stdout(io.StringIO()):
                    products_feed.main()
                codes=etree.parse('public/products-feed.xml').xpath('.//vendorCode/text()')
            finally:
                os.chdir(old)
        self.assertEqual(codes,[ACTIVE[1][0]])

    def test_site_update_omits_retired_rows_even_with_own_and_supplier_stock(self):
        root=etree.Element('yml_catalog')
        offers=etree.SubElement(root,'offers')
        for i in range(2000):
            offers.append(offer((f'control-{i}',f'Control {i}','Untracked')))
        for row in RETIRED+[ACTIVE[1]]:
            offers.append(offer(row))
        quantities={s:999 for s,_,_ in RETIRED+[ACTIVE[1]]}
        feed,_=site.build_feed(root,quantities,quantities)
        self.assertEqual(feed.xpath('.//vendorCode/text()'),[ACTIVE[1][0]])

    def test_manual_platform_removal_is_not_overwritten_by_prom_sync(self):
        with patch.dict(os.environ,{'PROM_API_TOKEN':'test-only'}):
            import generate_prom_update_feed as prom
        cards={s.upper():{'id':i+1,'sku':s.upper(),'name':n} for i,(s,n,_) in enumerate(RETIRED) if s!='017954'}
        with contextlib.redirect_stdout(io.StringIO()):
            updates=prom.build_updates(cards,set(),{},set())
        self.assertEqual(updates,[])


if __name__=='__main__':
    unittest.main()
