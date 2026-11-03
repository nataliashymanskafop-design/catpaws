import contextlib
import io
import unittest

from lxml import etree
import generate_site_stock_feed as site


class PetimpexSiteAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.catalog = etree.Element("yml_catalog")
        self.offers = etree.SubElement(self.catalog, "offers")
        for i in range(2000):
            self.add_offer(f"untracked-{i}", vendor="Unknown vendor")

    def add_offer(self, sku, vendor="MERA", available="false"):
        offer = etree.SubElement(self.offers, "offer", id=sku, available=available)
        etree.SubElement(offer, "vendorCode").text = sku
        etree.SubElement(offer, "vendor").text = vendor
        return offer

    def build(self, own=None, supplier=None, prices=None):
        with contextlib.redirect_stdout(io.StringIO()):
            root, _ = site.build_feed(self.catalog, own or {}, supplier or {},
                                      prices or {})
        return {o.get("id"): o for o in root.findall(".//offer")}

    def test_public_site_status_overrides_both_stale_xml_directions(self):
        self.add_offer("absent", available="false"); self.add_offer("present", available="true")
        rows = self.build(supplier={"absent": 25, "present": 0})
        self.assertEqual(rows["absent"].get("available"), "false")
        self.assertEqual(rows["present"].get("available"), "true")
        self.assertTrue(all(o.find("quantity_in_stock") is None for o in rows.values()))

    def test_positive_own_stock_has_priority_and_keeps_exact_quantity(self):
        self.add_offer("owned")
        row = self.build(own={"owned": 3})["owned"]
        self.assertEqual(row.get("available"), "true")
        self.assertEqual(row.findtext("quantity_in_stock"), "3")

    def test_zero_own_stock_does_not_hide_confirmed_site_availability(self):
        self.add_offer("present", available="true")
        row = self.build(own={"present": 0})["present"]
        self.assertEqual(row.get("available"), "true")

    def test_literal_articles_and_prices_are_preserved_without_promo_fields(self):
        self.add_offer("PUBLIC / SKU", available="true")
        row = self.build(prices={"PUBLIC / SKU": "1 203.72"})["PUBLIC / SKU"]
        self.assertEqual(row.findtext("vendorCode"), "PUBLIC / SKU")
        self.assertEqual(row.findtext("price"), "1203.72")
        self.assertEqual({x.tag for x in row}, {"vendorCode", "price", "currencyId"})

    def test_other_supplier_and_untracked_manual_status_are_unchanged(self):
        self.add_offer("homefood", "HOME FOOD"); self.add_offer("manual", "Unknown vendor")
        rows = self.build(supplier={"homefood": 8})
        self.assertEqual(rows["homefood"].findtext("quantity_in_stock"), "8")
        self.assertNotIn("manual", rows)

    def test_duplicate_articles_are_omitted(self):
        self.add_offer("duplicate"); self.add_offer("duplicate")
        self.assertNotIn("duplicate", self.build())

    def test_blocked_brand_and_inquiry_exceptions_are_preserved(self):
        self.add_offer("rafi", "RAFI"); self.add_offer("ЗС000375", "MODES")
        rows = self.build(own={"rafi": 4})
        self.assertEqual(rows["rafi"].get("available"), "false")
        self.assertNotIn("ЗС000375", rows)

    def test_unknown_public_status_is_omitted(self):
        self.add_offer("unknown", available="inquiry")
        self.assertNotIn("unknown", self.build(supplier={"unknown": 9}))

    def test_every_petimpex_public_brand_keeps_its_status(self):
        for brand in site.PETIMPEX_SITE_VENDORS:
            self.add_offer(brand, brand.upper(), available="true")
        rows = self.build(supplier={brand: 0 for brand in site.PETIMPEX_SITE_VENDORS})
        self.assertTrue(all(rows[brand].get("available") == "true"
                            for brand in site.PETIMPEX_SITE_VENDORS))


if __name__ == "__main__":
    unittest.main()
