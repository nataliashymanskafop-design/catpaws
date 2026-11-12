import unittest
from unittest.mock import patch
from lxml import etree
import josera_stock as j


class JoseraTests(unittest.TestCase):
    def supplier_payload(self, status="in stock", title="Корм Josera 5 * 900 г", weight="4.500", price="1602.00", code="50014710"):
        return f'<partners_offers><offer><vendor_code>{code}</vendor_code><availability>{status}</availability><currency>UAH</currency><title>{title}</title><weight>{weight}</weight><price>{price}</price></offer></partners_offers>'.encode()

    def collision_payload(self, rows):
        root = etree.Element("partners_offers")
        for row in rows:
            values = dict(row)
            barcode = values.pop("barcode", "4032254749219")
            brand = values.pop("brand", "Josera")
            sale_price = values.pop("sale_price", None)
            offer = etree.fromstring(self.supplier_payload(**values)).find("offer")
            etree.SubElement(offer, "barcode").text = barcode
            etree.SubElement(offer, "brand").text = brand
            if sale_price is not None:
                etree.SubElement(offer, "sale_price").text = sale_price
            root.append(offer)
        return etree.tostring(root)

    def known_collisions(self):
        return [
            {"code": "50003279", "title": "Корм для котів Josera SensiCat 10 кг", "weight": "10.000", "price": "3610.00", "sale_price": "3610.00"},
            {"code": "50003279", "title": "Корм для котів 10 кг", "weight": "10.000", "price": "3610.00"},
            {"code": "50003279", "title": "Корм для котів 400 г", "weight": "0.400", "price": "230.00"},
            {"code": "50003279", "title": "Корм для котів 2 кг", "weight": "2.000", "price": "778.00"},
            {"code": "50009986", "title": "Корм для котів Josera Kitten grainfree 10 кг", "weight": "10.000", "price": "4320.00", "barcode": "4032254754992"},
            {"code": "50009986", "title": "Корм для котів 10 кг", "weight": "10.000", "price": "4390.00", "barcode": "4032254754992"},
            {"code": "50009986", "title": "Корм для котів 400 г", "weight": "0.400", "price": "240.00", "barcode": "4032254754992"},
            {"code": "50009986", "title": "Корм для котів 2 кг", "weight": "2.000", "price": "876.00", "barcode": "4032254754992"},
            {"code": "50009986", "title": "Корм для котів 2 x 10 кг", "weight": "20.000", "price": "8780.00", "sale_price": "7902.00", "barcode": "4032254754992"},
        ]

    def test_known_supplier_collisions_select_verified_recipes_not_other_sizes(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 2):
            supplier = j.read_supplier(self.collision_payload(self.known_collisions()))
        self.assertEqual(set(supplier), {"50003279", "50009986"})
        self.assertEqual(supplier["50003279"]["price"], j.Decimal("3610"))
        self.assertEqual(supplier["50009986"]["price"], j.Decimal("4320"))
        for product in supplier.values():
            self.assertEqual(product["unit_grams"], j.Decimal("10000"))
            self.assertEqual(product["pack_size"], 1)
            self.assertTrue(product["available"])
        self.assertIsNone(supplier["50009986"]["sale_price"])

    def test_known_collision_selection_does_not_depend_on_feed_order(self):
        rows = self.known_collisions()
        for ordered in (rows, list(reversed(rows)), rows[4:] + rows[:4]):
            with self.subTest(first=ordered[0]["title"]), patch.object(j, "MIN_SOURCE_PRODUCTS", 2):
                supplier = j.read_supplier(self.collision_payload(ordered))
            self.assertEqual(supplier["50003279"]["title"], "Корм для котів Josera SensiCat 10 кг")
            self.assertEqual(supplier["50009986"]["title"], "Корм для котів Josera Kitten grainfree 10 кг")

    def test_verified_collision_retains_current_supplier_price_sale_and_stock(self):
        rows = self.known_collisions()[:4]
        rows[0].update(price="3700.00", sale_price="3500.00", status="out of stock")
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1):
            supplier = j.read_supplier(self.collision_payload(rows))
        product = supplier["50003279"]
        self.assertEqual(product["price"], j.Decimal("3700"))
        self.assertEqual(product["sale_price"], j.Decimal("3500"))
        self.assertFalse(product["available"])

    def test_known_collision_without_verified_recipe_still_rejected(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), self.assertRaisesRegex(RuntimeError, "Duplicate Josera source SKU"):
            j.read_supplier(self.collision_payload(self.known_collisions()[1:4]))

    def test_two_matching_verified_offers_are_not_arbitrarily_selected(self):
        rows = self.known_collisions()[:4]
        rows.append(dict(rows[0], price="5000.00"))
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), self.assertRaisesRegex(RuntimeError, "Duplicate Josera source SKU"):
            j.read_supplier(self.collision_payload(rows))

    def test_collision_requires_verified_barcode_and_brand(self):
        for changed in ({"barcode": "0000000000000"}, {"brand": "Other"}):
            rows = self.known_collisions()[:4]
            rows[0].update(changed)
            with self.subTest(changed=changed), patch.object(j, "MIN_SOURCE_PRODUCTS", 1), self.assertRaisesRegex(RuntimeError, "Duplicate Josera source SKU"):
                j.read_supplier(self.collision_payload(rows))

    def test_selected_collision_still_requires_valid_pack_weight(self):
        rows = self.known_collisions()[:4]
        rows[0]["weight"] = "0.400"
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), self.assertRaisesRegex(RuntimeError, "Inconsistent Josera pack weight"):
            j.read_supplier(self.collision_payload(rows))

    def test_duplicate_rows_do_not_satisfy_minimum_unique_source_size(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 9), self.assertRaisesRegex(RuntimeError, "Josera source incomplete: 2"):
            j.read_supplier(self.collision_payload(self.known_collisions()))

    def test_verified_recipes_map_correct_prices_to_site_cards(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 2), patch.object(j, "MIN_SITE_PRODUCTS", 2):
            supplier = j.read_supplier(self.collision_payload(self.known_collisions()))
            rows, missing = j.map_catalog(self.catalog([
                ("50003279", "10 кг", "Сухий корм JOSERA SensiCat 10 кг"),
                ("50009986", "10 кг", "Сухий корм JOSERA Kitten grainfree 10 кг"),
            ]), supplier)
        self.assertEqual(missing, [])
        self.assertEqual(rows["50003279"]["price"], "3610.00")
        self.assertEqual(rows["50009986"]["price"], "4320.00")
        self.assertIsNone(rows["50009986"]["sale_price"])

    def catalog(self, rows, vendor="JOSERA"):
        root = etree.Element("yml_catalog")
        for code, weight, name in rows:
            o = etree.SubElement(root, "offer")
            etree.SubElement(o, "vendorCode").text = code
            etree.SubElement(o, "vendor").text = vendor
            etree.SubElement(o, "name_ua").text = name
            etree.SubElement(o, "param", name="Вага").text = weight
        return etree.tostring(root)

    def mapped(self, status="in stock"):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), patch.object(j, "MIN_SITE_PRODUCTS", 1):
            supplier = j.read_supplier(self.supplier_payload(status))
            rows, missing = j.map_catalog(self.catalog([
                ("50014710", "900 г", "Сухий корм 900 г"),
                ("50014710р", "900 г*5", "Сухий корм 900 г*5"),
            ]), supplier)
        return rows

    def test_pack_price_never_becomes_single_price(self):
        rows = self.mapped()
        self.assertEqual(rows["50014710"]["price"], "320.40")
        self.assertEqual(rows["50014710р"]["price"], "1602.00")
        _, _, stock = j.calculate(rows, None, [], True)
        self.assertEqual(stock, {"50014710": 20, "50014710р": 4})

    def test_josicat_650_single_and_seven_pack_retail_prices(self):
        for code, box_price, single_price in (
            ("50009045", "1224", "175.00"),
            ("50012991", "1224", "175.00"),
            ("50009209", "1224", "175.00"),
            ("50012493", "1428", "204.00"),
            ("50009211", "1428", "204.00"),
        ):
            with self.subTest(code=code), patch.object(j, "MIN_SOURCE_PRODUCTS", 1), patch.object(j, "MIN_SITE_PRODUCTS", 1):
                source = j.read_supplier(self.supplier_payload(
                    title="JosiCat 7 * 650 г", weight="4.550", price=box_price, code=code))
                rows, missing = j.map_catalog(self.catalog([
                    (code, "650 г", "JosiCat 650 г"),
                    (code + "*7", "650 г * 7", "JosiCat 650 г * 7"),
                ], vendor="JosiCat"), source)
                self.assertEqual(missing, [])
                self.assertEqual(rows[code]["price"], single_price)
                self.assertEqual(rows[code + "*7"]["price"], box_price + ".00")
                self.assertEqual(j.calculate(rows, None, [], True)[2],
                                 {code: 20, code + "*7": 2})

    def test_josicat_rounding_does_not_change_other_retail_prices(self):
        for vendor, title, weight, site_weight, price, expected in (
            ("JosiDog", "7 * 650 г", "4.550", "650 г", "1224", "174.86"),
            ("JosiCat", "5 * 900 г", "4.500", "900 г", "1602", "320.40"),
            ("JosiCat", "650 г", "0.650", "650 г", "174.86", "174.86"),
        ):
            with self.subTest(vendor=vendor, title=title), patch.object(j, "MIN_SOURCE_PRODUCTS", 1), patch.object(j, "MIN_SITE_PRODUCTS", 1):
                source = j.read_supplier(self.supplier_payload(
                    title=title, weight=weight, price=price))
                rows, _ = j.map_catalog(self.catalog([
                    ("50014710", site_weight, title)], vendor=vendor), source)
                self.assertEqual(rows["50014710"]["price"], expected)

    def test_unavailable_disables_both(self):
        _, _, stock = j.calculate(self.mapped("out of stock"), None, [], True)
        self.assertEqual(set(stock.values()), {0})

    def test_sale_bundle_consumes_common_units_once(self):
        rows = self.mapped()
        base, snapshots, _ = j.calculate(rows, None, [], True)
        order = {"id": 1, "products": [{"sku": "50014710р", "amount": 1}]}
        state = {"base_stock": base, "order_snapshots": snapshots}
        base, snapshots, stock = j.calculate(rows, state, [order])
        self.assertEqual(stock, {"50014710": 15, "50014710р": 3})
        base2, snaps2, stock2 = j.calculate(rows, {"base_stock": base, "order_snapshots": snapshots}, [order])
        self.assertEqual(stock2, stock)

    def test_single_sale_recalculates_bundle(self):
        rows = self.mapped()
        order = {"id": 1, "products": [{"sku": "50014710", "amount": 1}]}
        _, _, stock = j.calculate(rows, {"base_stock": {"50014710": 20}}, [order])
        self.assertEqual(stock, {"50014710": 19, "50014710р": 3})

    def test_existing_orders_only_baselined_at_initialization(self):
        order = {"id": 1, "products": [{"sku": "50014710р", "amount": 2}]}
        _, snapshots, stock = j.calculate(self.mapped(), None, [order], True)
        self.assertEqual(stock["50014710"], 20)
        self.assertEqual(snapshots["1"]["50014710р"], 2)

    def test_threshold_replenishes_available_only(self):
        for status, expected in (("in stock", 20), ("out of stock", 0)):
            base, _, _ = j.calculate(self.mapped(status), {"base_stock": {"50014710": 5}}, [])
            self.assertEqual(base["50014710"], expected)

    def test_restock_restores_allowance(self):
        base, _, _ = j.calculate(self.mapped(), {"base_stock": {"50014710": 0}}, [])
        self.assertEqual(base["50014710"], 20)

    def test_wet_stock_and_box_share_60_units(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), patch.object(j, "MIN_SITE_PRODUCTS", 1):
            supplier = j.read_supplier(self.supplier_payload(title="Вологий корм 16 * 70 г", weight="1.120", code="30001658", price="1168"))
            rows, missing = j.map_catalog(self.catalog([
                ("30001658", "70 г", "Вологий корм 70 г"),
                ("30001658_box", "70 г * 16 шт", "Вологий корм 16*70 г")]), supplier)
        _, _, stock = j.calculate(rows, None, [], True)
        self.assertEqual(stock, {"30001658": 60, "30001658_box": 3})
        self.assertEqual(rows["30001658"]["price"], "73.00")

    def test_supplier_single_maps_eight_pack(self):
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), patch.object(j, "MIN_SITE_PRODUCTS", 1):
            supplier = j.read_supplier(self.supplier_payload(title="Корм 400 г", weight="0.400", price="230", code="50004846"))
            rows, _ = j.map_catalog(self.catalog([("50004846p", "400 г *8", "Корм 400 г*8")]), supplier)
        self.assertEqual(rows["50004846p"]["price"], "1840.00")

    def test_missing_or_wrong_weight_stops_selling_without_changing_price(self):
        with patch.object(j, "MIN_SITE_PRODUCTS", 1):
            rows, missing = j.map_catalog(self.catalog([("50014957", "3 кг", "Корм 3 кг")]), {})
        self.assertEqual(missing, ["50014957"])
        self.assertIsNone(rows["50014957"]["price"])
        self.assertEqual(j.calculate(rows, None, [], True)[2]["50014957"], 0)
        source = {"50014957": {"unit_grams": j.Decimal(900), "pack_size": 5, "price": j.Decimal(100), "available": True}}
        with patch.object(j, "MIN_SITE_PRODUCTS", 1):
            rows, missing = j.map_catalog(self.catalog([("50014957", "3 кг", "Корм 3 кг")]), source)
        self.assertFalse(rows["50014957"]["matched"])

    def test_invalid_source_status_weight_duplicate_and_size_rejected(self):
        for payload in (
            self.supplier_payload(status="unknown"),
            self.supplier_payload(weight="0.900"),
            self.supplier_payload().replace(b"</partners_offers>", self.supplier_payload().split(b"<partners_offers>")[1]),
        ):
            with patch.object(j, "MIN_SOURCE_PRODUCTS", 1), self.assertRaises(RuntimeError):
                j.read_supplier(payload)
        with self.assertRaises(RuntimeError):
            j.read_supplier(self.supplier_payload())

    def test_unrelated_order_and_site_duplicate(self):
        rows = self.mapped()
        self.assertEqual(j.order_snapshot({"products": [{"sku": "OTHER", "amount": 100}]}, rows), {})
        with patch.object(j, "MIN_SITE_PRODUCTS", 1), self.assertRaises(RuntimeError):
            j.map_catalog(self.catalog([("X", "900 г", "Корм"), ("X", "900 г", "Корм")]), {})

    def test_no_promotion_or_purchase_price_is_used(self):
        payload = self.supplier_payload().replace(b"</offer>", b"<sale_price>800</sale_price><purchaseprice>500</purchaseprice></offer>")
        with patch.object(j, "MIN_SOURCE_PRODUCTS", 1):
            supplier = j.read_supplier(payload)
        self.assertEqual(supplier["50014710"]["price"], j.Decimal(1602))


if __name__ == "__main__":
    unittest.main()

