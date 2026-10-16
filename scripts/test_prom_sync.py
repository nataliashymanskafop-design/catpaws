import os
import sys
import types
import unittest
import json
import tempfile
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

    def test_numeric_sku_spacing_preserves_pack_suffixes(self):
        for value in ('740197 - 1329', '740197\u00a0-\u00a01329', '740197- 1329', '740197 -1329'):
            self.assertEqual(sync.normalize_code(value), '740197-1329')
        self.assertNotEqual(sync.normalize_code('740197 - 1329-12'), '740197-1329')
        self.assertEqual(sync.normalize_code('ASR(CB)-16 Oz'), 'ASR(CB)-16 OZ')
        self.assertEqual(sync.normalize_code('018197'), '018197')

    def test_spaced_site_sku_matches_prom_price_promotion_and_presence(self):
        date = sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
        for available in ('true', 'false'):
            payload = f'<yml_catalog date="{date}"><offer available="{available}"><vendorCode>740197 - 1329</vendorCode><price>504</price><oldprice>630</oldprice></offer></yml_catalog>'
            response = unittest.mock.Mock(content=payload.encode())
            with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'MIN_SOURCE_PRODUCTS', 1):
                source = sync.get_horoshop_products()
            cards, duplicates = sync.prepare_prom_products([{'id': 42, 'sku': '740197-1329'}])
            item = sync.build_updates(cards, duplicates, source, set())[0]
            self.assertEqual(item['presence'], 'available' if available == 'true' else 'not_available')
            if available == 'true':
                self.assertEqual((item['price'], item['oldprice']), (504, 630))

    def test_source_spacing_collision_stops(self):
        date = sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
        response = unittest.mock.Mock(content=f'<yml_catalog date="{date}"><offer><vendorCode>740197 - 1329</vendorCode></offer><offer><vendorCode>740197-1329</vendorCode></offer></yml_catalog>'.encode())
        with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'MIN_SOURCE_PRODUCTS', 1):
            with self.assertRaisesRegex(RuntimeError, 'normalize'):
                sync.get_horoshop_products()

    def test_normalized_prom_duplicate_is_blocked(self):
        cards, duplicates = sync.prepare_prom_products([{'id': 1, 'sku': '740197 - 1329'}, {'id': 2, 'sku': '740197-1329'}])
        self.assertEqual(duplicates, {'740197-1329'})
        self.assertEqual(sync.build_updates(cards, duplicates, {'740197-1329': self.offer()}, set()), [])

    def test_josera_source_uses_single_pack_price_and_sale(self):
        products = {'50014710': self.offer('999'), '50009044': self.offer('999')}
        rows = {
            '50014710': {'available': True, 'price': '320.40', 'sale_price': None},
            '50009044': {'available': True, 'price': '2280.00', 'sale_price': '1520.00'},
        }
        state = {'josera': {'last_sync': sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')},
                 'published_stock': {'50014710': 20, '50009044': 20}}
        response = unittest.mock.Mock(content=b'feed')
        response.json.return_value = state
        with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'read_supplier', return_value={}), patch.object(sync, 'map_catalog', return_value=(rows, [])):
            result = sync.apply_josera_source(products)
        self.assertEqual(result['50014710'].findtext('price'), '320.40')
        self.assertIsNone(result['50014710'].findtext('oldprice'))
        self.assertEqual(result['50009044'].findtext('price'), '1520.00')
        self.assertEqual(result['50009044'].findtext('oldprice'), '2280.00')
        self.assertEqual(products['50014710'].findtext('price'), '999')

    def test_josera_zero_bundle_stock_and_supplier_unavailable(self):
        products = {'BUNDLE': self.offer(), 'UNIT': self.offer()}
        rows = {code: {'available': available, 'price': '630', 'sale_price': None}
                for code, available in [('BUNDLE', True), ('UNIT', False)]}
        state = {'josera': {'last_sync': sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')},
                 'published_stock': {'BUNDLE': 0, 'UNIT': 20}}
        response = unittest.mock.Mock(content=b'feed')
        response.json.return_value = state
        with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'read_supplier', return_value={}), patch.object(sync, 'map_catalog', return_value=(rows, [])):
            result = sync.apply_josera_source(products)
        self.assertTrue(all(o.get('available') == 'false' for o in result.values()))

    def test_josera_stale_or_incomplete_state_blocks_writes(self):
        response = unittest.mock.Mock(content=b'feed')
        for state in ({'josera': {'last_sync': '2000-01-01 00:00:00'}, 'published_stock': {'X': 20}},
                      {'josera': {'last_sync': sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')}, 'published_stock': {}},
                      {}):
            response.json.return_value = state
            with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'read_supplier', return_value={}), patch.object(sync, 'map_catalog', return_value=({'X': {}}, [])):
                with self.assertRaises(RuntimeError):
                    sync.apply_josera_source({'X': self.offer()})

    def test_josera_local_snapshot_avoids_published_state_cache(self):
        state = {'josera': {'last_sync': sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')},
                 'published_stock': {'X': 0}}
        rows = {'X': {'available': True, 'price': '630', 'sale_price': None}}
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json') as handle:
            json.dump(state, handle)
            handle.flush()
            with patch.dict(os.environ, {'PROM_TERRAVET_STATE_FILE': handle.name}), \
                    patch.object(sync.requests, 'get', return_value=unittest.mock.Mock(content=b'feed')) as get, \
                    patch.object(sync, 'read_supplier', return_value={}), \
                    patch.object(sync, 'map_catalog', return_value=(rows, [])):
                result = sync.apply_josera_source({'X': self.offer()})
            self.assertEqual(result['X'].get('available'), 'false')
            get.assert_called_once_with(sync.JOSERA_URL, timeout=60)

    def test_josera_stale_local_snapshot_still_blocks_writes(self):
        state = {'josera': {'last_sync': '2000-01-01 00:00:00'}, 'published_stock': {'X': 20}}
        with tempfile.NamedTemporaryFile(mode='w+', suffix='.json') as handle:
            json.dump(state, handle)
            handle.flush()
            with patch.dict(os.environ, {'PROM_TERRAVET_STATE_FILE': handle.name}), \
                    patch.object(sync.requests, 'get', return_value=unittest.mock.Mock(content=b'feed')), \
                    patch.object(sync, 'read_supplier', return_value={}), \
                    patch.object(sync, 'map_catalog', return_value=({'X': {}}, [])):
                with self.assertRaisesRegex(RuntimeError, 'stale or incomplete'):
                    sync.apply_josera_source({'X': self.offer()})

    def test_cosmetic_article_multiple_spaces_match(self):
        self.assertEqual(sync.normalize_code('2117  LOZH0150'), sync.normalize_code('2117 LOZH0150'))
        self.assertEqual(sync.normalize_code('2117\u00a0\u00a0LOZH0150'), '2117 LOZH0150')

    def test_spaces_in_price(self):
        self.assertEqual(sync.parse_price('1\u00a0278,48'), 1278.48)

    def test_stale_source_is_rejected(self):
        for stamp in ('2000-01-01 00:00', None, 'bad'):
            root = etree.Element('yml_catalog')
            if stamp:
                root.set('date', stamp)
            with self.assertRaises(RuntimeError):
                sync.validate_source_freshness(root)

    def test_unfiltered_catalog_loads_all_unique_skus(self):
        date = sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
        payload = f'<yml_catalog date="{date}"><offer><vendorCode>A</vendorCode><price>10</price></offer><offer><vendorCode>B</vendorCode></offer><offer><vendorCode>C</vendorCode></offer><offer><vendorCode>C</vendorCode></offer></yml_catalog>'
        response = unittest.mock.Mock()
        response.content = payload.encode()
        with patch.object(sync.requests, 'get', return_value=response) as get, patch.object(sync, 'MIN_SOURCE_PRODUCTS', 1):
            products = sync.get_horoshop_products()
            get.assert_called_once()
        self.assertEqual(set(products), {'A', 'B'})
        self.assertEqual(products['A'].findtext('price'), '10')

    def test_discontinued_and_rafi(self):
        for sku, rafi in [('GONE', set()), ('FORCE', set()), ('RAFI', {'RAFI'})]:
            self.assertEqual(self.build(self.offer(), sku, rafi),
                             {'id': 1, 'presence': 'not_available'})

    def test_duplicate_sku_skipped(self):
        self.assertEqual(sync.build_updates({'X': {'id': 1}}, {'X'},
                                           {'X': self.offer()}, set()), [])

    def test_verified_identical_duplicate_cards_both_sync(self):
        cards = [{'sku': '50013184', 'id': 3157113613, 'name': 'Сухий корм JosiDog Regular 2,7 кг'},
                 {'sku': '50013184', 'id': 2979412910, 'name': 'Сухий корм JosiDog Regular 2.7 кг'}]
        source = self.offer()
        etree.SubElement(source, 'name_ua').text = cards[0]['name']
        by_sku, duplicates = sync.prepare_prom_products(cards)
        updates = sync.build_updates(by_sku, duplicates, {'50013184': source}, set())
        self.assertEqual({item['id'] for item in updates}, {3157113613, 2979412910})
        self.assertTrue(all(item['price'] == 630 for item in updates))

    def test_duplicate_with_different_pack_stays_blocked(self):
        cards = [{'sku': '50013184', 'id': 3157113613, 'name': 'Сухий корм JosiDog Regular 2,7 кг'},
                 {'sku': '50013184', 'id': 2979412910, 'name': 'Сухий корм JosiDog Regular 20 кг'}]
        source = self.offer()
        etree.SubElement(source, 'name_ua').text = cards[0]['name']
        by_sku, duplicates = sync.prepare_prom_products(cards)
        self.assertEqual(sync.build_updates(by_sku, duplicates, {'50013184': source}, set()), [])

    def test_card_absent_from_complete_site_export_stops_selling(self):
        self.assertEqual(sync.build_updates({'OLD': {'id': 1, 'sku': 'OLD'}}, set(),
                                           {}, set()), [{'id': 1, 'presence': 'not_available'}])

    def test_incomplete_full_source_is_rejected(self):
        date = sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')
        response = unittest.mock.Mock()
        response.content = f'<yml_catalog date="{date}"><offer><vendorCode>A</vendorCode></offer></yml_catalog>'.encode()
        with patch.object(sync.requests, 'get', return_value=response), self.assertRaises(RuntimeError):
            sync.get_horoshop_products()

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
