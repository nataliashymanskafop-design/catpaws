import unittest
from unittest.mock import patch
from lxml import etree

import generate_terravet_stock as t
import generate_feed as mono


class QuadromidasTests(unittest.TestCase):
    def test_full_packs_only(self):
        base = t.QUADROMIDAS_BASE_SKUS[0]
        for units, expected in ((-1, 0), (0, 0), (2, 0), (3, 1), (5, 1), (6, 2), (50, 16)):
            with self.subTest(units=units):
                quantities, _ = t.quadromidas_bundles({base: units}, {})
                self.assertEqual(quantities[base + '-3'], expected)

    def test_only_eight_confirmed_bundles(self):
        stock = {'unrelated': 90, 'unknown-3': 90}
        quantities, prices = t.quadromidas_bundles(stock, {})
        self.assertEqual(set(quantities), {base + '-3' for base in t.QUADROMIDAS_BASE_SKUS})
        self.assertEqual(set(quantities.values()), {0})
        self.assertEqual(prices, {})
        self.assertEqual(stock, {'unrelated': 90, 'unknown-3': 90})

    def test_prices_are_three_units(self):
        singles = [178, 190, 231, 264, 423, 141, 168, 210]
        unit_prices = dict(zip(t.QUADROMIDAS_BASE_SKUS, singles))
        _, prices = t.quadromidas_bundles({}, unit_prices)
        self.assertEqual(list(prices.values()), [534, 570, 693, 792, 1269, 423, 504, 630])
        unit_prices[t.QUADROMIDAS_BASE_SKUS[0]] = '178.25'
        _, prices = t.quadromidas_bundles({}, unit_prices)
        self.assertEqual(prices[t.QUADROMIDAS_BASE_SKUS[0] + '-3'], 534.75)

    def test_bad_prices_never_reset_site_price(self):
        for value in (None, '', 'invalid', 'NaN', 'Infinity', 0, -5):
            _, prices = t.quadromidas_bundles({}, {t.QUADROMIDAS_BASE_SKUS[0]: value})
            self.assertEqual(prices, {})

    def payload(self, base, suffix=''):
        return f'<yml_catalog><shop><offers><offer><vendorCode>{base}</vendorCode><price>178</price><quantity_in_stock>50</quantity_in_stock></offer><offer><vendorCode>unrelated</vendorCode><price>900</price><quantity_in_stock>11</quantity_in_stock></offer>{suffix}</offers></shop></yml_catalog>'.encode()

    def test_supplier_loader_preserves_units_and_unrelated_products(self):
        base = t.QUADROMIDAS_BASE_SKUS[0]
        prices = {}
        with patch.object(t, 'download', return_value=self.payload(base)), patch.object(t, 'MIN_PRODUCTS', 0):
            stock, duplicates = t.load_source('MODES', 'test-only', prices)
        self.assertEqual(stock[base], 50)
        self.assertEqual(stock['unrelated'], 11)
        self.assertEqual(stock[base + '-3'], 16)
        self.assertEqual(len(stock), 10)
        self.assertEqual(duplicates, set())
        self.assertEqual(prices, {base + '-3': 534})

    def test_supplier_bundle_conflict_fails_instead_of_overwriting(self):
        base = t.QUADROMIDAS_BASE_SKUS[0]
        extra = f'<offer><vendorCode>{base}-3</vendorCode><quantity_in_stock>9</quantity_in_stock></offer>'
        with patch.object(t, 'download', return_value=self.payload(base, extra)), patch.object(t, 'MIN_PRODUCTS', 0):
            with self.assertRaisesRegex(RuntimeError, 'bundle SKUs'):
                t.load_source('MODES', 'test-only')

    def test_mono_uses_bundle_quantity_and_terravet_warehouse(self):
        code = t.QUADROMIDAS_BASE_SKUS[0] + '-3'
        offer = etree.fromstring(f'<offer available="true"><vendorCode>{code}</vendorCode><vendor>ModeS</vendor><name>Квадромідас — набір 3 таблетки</name><price>534</price></offer>')
        source = next(s for s in mono.STOCK_SOURCES if s['warehouse_id'] == 'TERRAVET')
        result = mono.build_offer(offer, {code: {**source, 'stock': 16}}, {})
        self.assertEqual(result['price'], 534)
        self.assertEqual(result['stock'], 16)
        self.assertEqual(result['warehouses'], [{'id': 'TERRAVET', 'stock': 16}])
        self.assertTrue(result['availability'])
        result = mono.build_offer(offer, {code: {**source, 'stock': 0}}, {})
        self.assertFalse(result['availability'])


if __name__ == '__main__':
    unittest.main()
