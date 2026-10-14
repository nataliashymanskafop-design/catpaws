import unittest
from unittest.mock import patch
from lxml import etree
import josera_stock as j


class JoseraTests(unittest.TestCase):
    def supplier_payload(self, status="in stock", title="Корм Josera 5 * 900 г", weight="4.500", price="1602.00", code="50014710"):
        return f'<partners_offers><offer><vendor_code>{code}</vendor_code><availability>{status}</availability><currency>UAH</currency><title>{title}</title><weight>{weight}</weight><price>{price}</price></offer></partners_offers>'.encode()

    def catalog(self, rows):
        root = etree.Element("yml_catalog")
        for code, weight, name in rows:
            o = etree.SubElement(root, "offer")
            etree.SubElement(o, "vendorCode").text = code
            etree.SubElement(o, "vendor").text = "JOSERA"
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
