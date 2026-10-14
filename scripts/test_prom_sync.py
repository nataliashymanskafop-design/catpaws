import os
import sys
import types
import unittest
from unittest.mock import patch
from lxml import etree

os.environ.setdefault('PROM_API_TOKEN', 'test-only')
rules = types.ModuleType('generate_feed')
rules.DISCONTINUED_SKUS = {'GONE'}
rules.FORCE_ZERO_SKUS = {'FORCE'}
rules.is_modes_bowl = lambda offer: False
sys.modules['generate_feed'] = rules
import generate_prom_update_feed as sync


class SyncTests(unittest.TestCase):
    def offer(self, price='630', old='', available='true'):
        e = etree.Element('offer', available=available)
        etree.SubElement(e, 'price').text = price
        if old:
            etree.SubElement(e, 'oldprice').text = old
        return e

    def build(self, offer, sku='653651', rafi=None):
        return sync.build_updates({sku: {'id': 1, 'sku': sku}}, set(),
                                  {sku: offer}, rafi or set())[0]

    def test_ended_discount_uses_equal_prices(self):
        self.assertEqual(self.build(self.offer()),
                         {'id': 1, 'presence': 'available', 'price': 630, 'oldprice': 630})

    def test_active_discount(self):
        item = self.build(self.offer('504', '630'))
        self.assertEqual(item['oldprice'] - item['price'], 126)
        self.assertNotIn('discount', item)

    def test_unavailable_clears_discount_without_repricing(self):
        self.assertEqual(self.build(self.offer(available='false')),
                         {'id': 1, 'presence': 'not_available', 'discount': None})

    def test_malformed_oldprice_preserves_discount(self):
        item = self.build(self.offer(old='bad'))
        self.assertNotIn('oldprice', item)
        self.assertNotIn('discount', item)

    def test_bad_price_never_reprices_or_clears(self):
        for price in ('bad', 'nan', 'inf', '0', '-1'):
            item = self.build(self.offer(price))
            self.assertNotIn('price', item)
            self.assertNotIn('oldprice', item)
            self.assertNotIn('discount', item)

    def test_spaces_in_price(self):
        self.assertEqual(sync.parse_price('1\u00a0278,48'), 1278.48)

    def test_stale_source_is_rejected(self):
        for stamp in ('2000-01-01 00:00', None, 'bad'):
            root = etree.Element('yml_catalog')
            if stamp:
                root.set('date', stamp)
            with self.assertRaises(RuntimeError):
                sync.validate_source_freshness(root)

    def test_discontinued_and_rafi(self):
        for sku, rafi in [('GONE', set()), ('FORCE', set()), ('RAFI', {'RAFI'})]:
            self.assertEqual(self.build(self.offer(), sku, rafi),
                             {'id': 1, 'presence': 'not_available'})

    def test_duplicate_sku_skipped(self):
        self.assertEqual(sync.build_updates({'X': {'id': 1}}, {'X'},
                                           {'X': self.offer()}, set()), [])

    def test_active_discount_readback_amount_and_percent(self):
        item = {'id': 1, 'presence': 'available', 'price': 504, 'oldprice': 630}
        for discount in ({'type': 'amount', 'value': 126},
                         {'type': 'percent', 'value': 20}):
            self.assertEqual(sync.state_mismatches(item,
                             {'price': 630, 'presence': 'available', 'discount': discount}), [])

    def test_stale_discount_is_failure(self):
        item = self.build(self.offer())
        self.assertEqual(sync.state_mismatches(item,
                         {'price': 630, 'presence': 'available',
                          'discount': {'type': 'amount', 'value': 126}}), ['discount'])

    def test_expired_or_future_promotion_is_not_matching(self):
        item = {'price': 504, 'oldprice': 630}
        for dates in ({'date_end': '01.01.2000'}, {'date_start': '01.01.2099'}):
            discount = {'type': 'amount', 'value': 126, **dates}
            self.assertEqual(sync.state_mismatches(item, {'price': 630, 'discount': discount}),
                             ['discount dates'])

    def test_wrong_availability_detected(self):
        self.assertEqual(sync.state_mismatches({'presence': 'not_available'},
                                               {'presence': 'available'}), ['presence'])

    @patch.object(sync.time, 'sleep')
    def test_empty_ack_requires_readback_and_retries(self, sleep):
        item = {'id': 1, 'presence': 'not_available'}
        initial = [{'id': 1, 'presence': 'available'}]
        with patch.object(sync, 'post_batch', return_value={'processed_ids': []}) as post:
            with patch.object(sync, 'readback', side_effect=[{'1': ['presence']}, {'1': []}]):
                self.assertEqual(sync.send_updates([item], initial), ([1], {}))
                self.assertEqual(post.call_count, 2)

    @patch.object(sync.time, 'sleep')
    def test_empty_ack_with_unchanged_state_is_error(self, sleep):
        with patch.object(sync, 'post_batch', return_value={'processed_ids': []}):
            with patch.object(sync, 'readback', return_value={'1': ['presence']}):
                ids, errors = sync.send_updates([{'id': 1, 'presence': 'not_available'}],
                                                [{'id': 1, 'presence': 'available'}])
                self.assertEqual(ids, [])
                self.assertEqual(errors, {'1': ['presence']})

    @patch.object(sync.time, 'sleep')
    def test_already_matching_is_verified_without_write(self, sleep):
        with patch.object(sync, 'post_batch') as post:
            with patch.object(sync, 'readback', return_value={'1': []}):
                self.assertEqual(sync.send_updates([{'id': 1, 'presence': 'available'}],
                                                  [{'id': 1, 'presence': 'available'}]), ([1], {}))
                post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
