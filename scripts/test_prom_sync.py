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
    def test_interrupted_second_page_retries_the_same_cursor_without_losing_products(self):
        first=unittest.mock.Mock(status_code=200)
        first.json.return_value={'products':[{'id':i} for i in range(1,101)]}
        last=unittest.mock.Mock(status_code=200)
        last.json.return_value={'products':[{'id':101}]}
        with patch.object(sync.requests,'get',side_effect=[first,sync.requests.exceptions.ChunkedEncodingError('Response ended prematurely'),last]) as get, patch.object(sync.time,'sleep'):
            products=sync.get_prom_products()
        self.assertEqual([p['id'] for p in products],list(range(1,102)))
        self.assertEqual([call.kwargs['params'].get('last_id') for call in get.call_args_list],[None,100,100])

    def test_transient_prom_http_error_retries(self):
        failed=unittest.mock.Mock(status_code=503)
        failed.raise_for_status.side_effect=sync.requests.HTTPError(response=failed)
        recovered=unittest.mock.Mock(status_code=200)
        recovered.json.return_value={'products':[]}
        with patch.object(sync.requests,'get',side_effect=[failed,recovered]) as get, patch.object(sync.time,'sleep'):
            self.assertEqual(sync.get_prom_products(),[])
        self.assertEqual(get.call_count,2)

    def test_unauthorized_prom_api_is_not_retried(self):
        response=unittest.mock.Mock(status_code=401)
        response.raise_for_status.side_effect=sync.requests.HTTPError(response=response)
        with patch.object(sync.requests,'get',return_value=response) as get, patch.object(sync.time,'sleep') as sleep:
            with self.assertRaises(sync.requests.HTTPError):
                sync.get_prom_products()
        get.assert_called_once()
        sleep.assert_not_called()

    def test_persistent_interruption_raises_instead_of_returning_partial_catalog(self):
        first=unittest.mock.Mock(status_code=200)
        first.json.return_value={'products':[{'id':i} for i in range(1,101)]}
        error=sync.requests.exceptions.ChunkedEncodingError('Response ended prematurely')
        with patch.object(sync.requests,'get',side_effect=[first,error,error,error,error]) as get, patch.object(sync.time,'sleep'):
            with self.assertRaises(sync.requests.exceptions.ChunkedEncodingError):
                sync.get_prom_products()
        self.assertEqual(get.call_count,5)

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

    def test_bavaro_task_supplier_sale_is_cleared_at_regular_price(self):
        item = self.build(self.offer('1760', '2070'), sku='50005182')
        self.assertEqual(item, {'id': 1, 'presence': 'available',
                                'price': 2070, 'oldprice': 2070})

    def test_bavaro_task_regular_price_keeps_updating(self):
        item = self.build(self.offer('2199'), sku='50005182')
        self.assertEqual((item['price'], item['oldprice']), (2199, 2199))

    def test_bavaro_task_unavailable_clears_discount_without_repricing(self):
        item = self.build(self.offer('1760', '2070', available='false'), sku='50005182')
        self.assertEqual(item, {'id': 1, 'presence': 'not_available', 'discount': None})

    def test_other_bavaro_promotions_remain_unchanged(self):
        item = self.build(self.offer('1545', '1818'), sku='50005178')
        self.assertEqual((item['price'], item['oldprice']), (1545, 1818))

    def test_bavaro_task_readback_rejects_any_remaining_discount(self):
        item = self.build(self.offer('1760', '2070'), sku='50005182')
        product = {'price': 2070, 'presence': 'available', 'discount': None}
        self.assertEqual(sync.state_mismatches(item, product), [])
        for discount in ({'type': 'amount', 'value': 310}, {'type': 'percent', 'value': 15}):
            self.assertEqual(sync.state_mismatches(item, {**product, 'discount': discount}),
                             ['discount'])

    @patch.object(sync.time, 'sleep')
    def test_repeated_sync_does_not_restore_bavaro_task_promotion(self, sleep):
        product = {'id': 1, 'sku': '50005182', 'price': 2070,
                   'presence': 'available', 'discount': None}
        with patch.object(sync, 'post_batch') as post, \
                patch.object(sync, 'readback', return_value={'1': []}):
            for _ in range(2):
                item = self.build(self.offer('1760', '2070'), sku='50005182')
                self.assertEqual(sync.send_updates([item], [product]), ([1], {}))
            post.assert_not_called()

    def test_unavailable_clears_discount_without_repricing(self):
        self.assertEqual(self.build(self.offer(available='false')),
                         {'id': 1, 'presence': 'not_available', 'discount': None})

    def test_confirmed_barpi_is_available_despite_cached_site_export(self):
        item = self.build(self.offer('399', available='false'), sku='A-00003')
        self.assertEqual(item, {'id': 1, 'presence': 'available',
                                'price': 399, 'oldprice': 399})
        self.assertEqual(self.build(self.offer('399', available='false'), sku='A-00004'),
                         {'id': 1, 'presence': 'not_available', 'discount': None})

    def test_confirmed_barpi_still_requires_an_existing_site_card(self):
        self.assertEqual(sync.build_updates({'A-00003': {'id': 1, 'sku': 'A-00003'}},
                                            set(), {}, set()),
                         [{'id': 1, 'presence': 'not_available'}])

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

    def apply_supplier(self, sku, offer, regular, sale=None, stock=20):
        rows = {sku: {'available': True, 'price': regular, 'sale_price': sale}}
        state = {'josera': {'last_sync': sync.datetime.now(sync.ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')},
                 'published_stock': {sku: stock}}
        response = unittest.mock.Mock(content=b'feed')
        response.json.return_value = state
        with patch.object(sync.requests, 'get', return_value=response), patch.object(sync, 'read_supplier', return_value={}), patch.object(sync, 'map_catalog', return_value=(rows, [])):
            return sync.apply_josera_source({sku: offer})[sku]

    def test_black_friday_josicat_keeps_site_15_when_supplier_has_no_sale(self):
        result = self.apply_supplier('50009044', self.offer('1938', '2280'), '2280')
        self.assertEqual((result.findtext('price'), result.findtext('oldprice')), ('1938', '2280'))
        item = self.build(result, sku='50009044')
        self.assertEqual((item['price'], item['oldprice']), (1938, 2280))

    def test_black_friday_josidog_keeps_site_15_over_supplier_discount(self):
        result = self.apply_supplier('50012165', self.offer('2958', '3480'), '3480', '2610')
        self.assertEqual((result.findtext('price'), result.findtext('oldprice')), ('2958', '3480'))

    def test_black_friday_josera_keeps_site_25_over_supplier_15(self):
        result = self.apply_supplier('50014781', self.offer('2250', '3000'), '3000', '2550')
        self.assertEqual((result.findtext('price'), result.findtext('oldprice')), ('2250', '3000'))

    def campaign_offer(self, sku, price, regular, vendor):
        source = self.offer(str(price), str(regular))
        etree.SubElement(source, 'vendorCode').text = sku
        etree.SubElement(source, 'vendor').text = vendor
        return source

    def test_prom_josera_uses_supplier_twenty_after_source_validation(self):
        source = self.campaign_offer('50003279', 2708, 3610, 'JOSERA')
        result = self.apply_supplier('50003279', source, '3610', '3069')
        item = self.build(result, sku='50003279')
        self.assertEqual((item['price'], item['oldprice']), (2888, 3610))
        self.assertEqual((source.findtext('price'), result.findtext('price')), ('2708', '2708'))

    def test_prom_home_food_small_packs_keep_supplier_twenty_five(self):
        for sku in ('3058004', '1047007', '3048016', '1128016'):
            with self.subTest(sku=sku):
                source = self.campaign_offer(sku, 152, 217, 'HOME FOOD')
                item = self.build(source, sku=sku)
                self.assertEqual((item['price'], item['oldprice']), (163, 217))

    def test_prom_home_food_large_and_beauty_keep_supplier_twenty(self):
        for sku in ('3199100', '1018100', '1028100', '3058110', '7000004', '7000005'):
            with self.subTest(sku=sku):
                source = self.campaign_offer(sku, 3101, 4134, 'HOME FOOD')
                item = self.build(source, sku=sku)
                self.assertEqual((item['price'], item['oldprice']), (3308, 4134))

    def test_prom_josicat_and_josidog_fifteen_are_preserved(self):
        for sku, vendor, price, regular in (
            ('50009044', 'JOSICAT', 1938, 2280),
            ('50006774', 'JOSIDOG', 1415, 1665),
        ):
            source = self.campaign_offer(sku, price, regular, vendor)
            result = self.apply_supplier(sku, source, str(regular))
            item = self.build(result, sku=sku)
            self.assertEqual((item['price'], item['oldprice']), (price, regular))

    def test_prom_ordinary_or_changed_campaign_discounts_are_preserved(self):
        for sku, vendor, price, regular in (
            ('1038100', 'HOME FOOD', 2746, 3231),
            ('50003229', 'JOSERA', 3069, 3610),
            ('50003279', 'JOSERA', 3069, 3610),
        ):
            source = self.campaign_offer(sku, price, regular, vendor)
            item = self.build(source, sku=sku)
            self.assertEqual((item['price'], item['oldprice']), (price, regular))

    def test_prom_campaign_does_not_reprice_unavailable_goods(self):
        source = self.campaign_offer('3199100', 3101, 4134, 'HOME FOOD')
        source.set('available', 'false')
        self.assertEqual(self.build(source, sku='3199100'),
                         {'id': 1, 'presence': 'not_available'})

    def test_prom_campaign_repeated_sync_is_stable_and_readback_rejects_old_discount(self):
        source = self.campaign_offer('3199100', 3101, 4134, 'HOME FOOD')
        first = self.build(source, sku='3199100')
        self.assertEqual(self.build(source, sku='3199100'), first)
        product = {'price': 4134, 'presence': 'available',
                   'discount': {'type': 'amount', 'value': 826}}
        self.assertEqual(sync.state_mismatches(first, product), [])
        product['discount']['value'] = 1033
        self.assertEqual(sync.state_mismatches(first, product), ['discount'])

    def test_cleared_site_promotion_is_not_recreated_from_old_site_value(self):
        result = self.apply_supplier('50009044', self.offer('2280'), '2280')
        self.assertEqual(result.findtext('price'), '2280')
        self.assertIsNone(result.findtext('oldprice'))

    def test_stale_site_base_price_falls_back_to_current_supplier(self):
        result = self.apply_supplier('50009044', self.offer('1938', '2280'), '2400', '2040')
        self.assertEqual((result.findtext('price'), result.findtext('oldprice')), ('2040', '2400'))

    def test_unselected_supplier_promotions_are_unchanged(self):
        result = self.apply_supplier('UNSELECTED', self.offer('2250', '3000'), '3000', '2550')
        self.assertEqual((result.findtext('price'), result.findtext('oldprice')), ('2550', '3000'))

    def test_black_friday_zero_stock_still_blocks_sales(self):
        result = self.apply_supplier('50009044', self.offer('1938', '2280'), '2280', stock=0)
        self.assertEqual(result.get('available'), 'false')
        self.assertEqual(self.build(result, sku='50009044'),
                         {'id': 1, 'presence': 'not_available'})

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

    def test_rafi_exclusions_reuse_catalog_without_extra_download(self):
        rafi = self.offer()
        etree.SubElement(rafi, 'vendor').text = '  RaFi  '
        etree.SubElement(rafi, 'vendorCode').text = '740197 - 1329'
        other = self.offer()
        etree.SubElement(other, 'vendor').text = 'Dolina Noteci'
        etree.SubElement(other, 'vendorCode').text = 'OTHER'
        with patch.object(sync.requests, 'get', side_effect=AssertionError('No standalone RAFI request')):
            excluded = sync.get_rafi_skus({'740197-1329': rafi, 'OTHER': other})
        self.assertEqual(excluded, {'740197-1329'})

    def test_rafi_cards_are_completely_omitted_from_prom_updates(self):
        offer = self.offer()
        etree.SubElement(offer, 'vendor').text = 'RAFI'
        etree.SubElement(offer, 'vendorCode').text = 'RAFI-1'
        catalog = {'RAFI-1': offer}
        excluded = sync.get_rafi_skus(catalog)
        cards = {'RAFI-1': {'id': 1, 'sku': 'RAFI-1'},
                 'REMOVED-RAFI': {'id': 2, 'sku': 'REMOVED-RAFI', 'name': 'Dolina Noteci RAFI Adult 400 г'},
                 'OTHER': {'id': 3, 'sku': 'OTHER', 'name': 'Grafit'}}
        catalog['OTHER'] = self.offer()
        updates = sync.build_updates(cards, set(), catalog, excluded)
        self.assertEqual(updates, [
            {'id': 3, 'presence': 'available', 'price': 630, 'oldprice': 630},
        ])

    def test_discontinued_products_are_disabled(self):
        for sku, rafi in [('GONE', set()), ('FORCE', set())]:
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


