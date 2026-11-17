import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from lxml import etree

import generate_kormax_stock as kormax
import generate_site_stock_feed as site


class KormaxSkuAliasTests(unittest.TestCase):
    def supplier(self, rows):
        values = [('Артикул', 'Назва', 'Бренд', 'Статус', 'Кількість')]+rows
        sheet=SimpleNamespace(iter_rows=lambda **kwargs:iter(values))
        with patch.object(kormax,'download',return_value=b'fixture'), patch.object(kormax,'load_workbook',return_value=SimpleNamespace(active=sheet)):
            return kormax.load_supplier()

    def row(self, sku, band='від 11 до 100', status='В наявності'):
        return (sku, 'Вологий корм для котів Nature Protection, 85 г', "Nature's Protection Superior Care", status, band)

    def catalog(self):
        return {sku:'Вологий корм для котів, 85 г'+(' * 12 шт' if sku.endswith('_box') else '')
                for sku in ['NPSC47908','NPSC47911','NPSC47908_box','NPSC47911_box']}

    def test_both_supplier_articles_use_the_existing_site_article(self):
        supplier=self.supplier([self.row('NPSC47908-K2'),self.row('NPSC47911-K2')])
        self.assertEqual(set(supplier),{'NPSC47908','NPSC47911'})
        self.assertEqual(supplier['NPSC47908']['quantity_band'],'від 11 до 100')

    def test_other_k2_articles_are_preserved(self):
        supplier=self.supplier([self.row('NPSC70465-K2'),self.row('NPSC47912-K2')])
        self.assertEqual(set(supplier),{'NPSC70465-K2','NPSC47912-K2'})

    def test_supplier_replacement_is_not_counted_as_a_second_stock(self):
        for rows in ([self.row('NPSC47908','до 5'),self.row('NPSC47908-K2')],
                     [self.row('NPSC47908-K2'),self.row('NPSC47908','до 5')]):
            supplier=self.supplier(rows)
            self.assertEqual(len(supplier),1)
            self.assertEqual(supplier['NPSC47908']['quantity_band'],'від 11 до 100')

    def test_both_twelve_pouch_sets_share_the_single_pouch_stock(self):
        supplier=self.supplier([self.row('NPSC47908-K2'),self.row('NPSC47911-K2')])
        products,boxes=kormax.build_product_catalog(self.catalog(),supplier)
        base,_=kormax.initial_base_stock(products,boxes,supplier)
        self.assertEqual(boxes,{'NPSC47908_box':('NPSC47908',12),'NPSC47911_box':('NPSC47911',12)})
        self.assertEqual(base,{'NPSC47908':60,'NPSC47911':60})
        self.assertEqual(kormax.materialize_stock(products,base,boxes),{'NPSC47908':60,'NPSC47911':60,'NPSC47908_box':5,'NPSC47911_box':5})
        consumption=kormax.expand_consumption('NPSC47908_box',1,boxes)
        self.assertEqual(consumption,{'NPSC47908':12})
        base['NPSC47908']-=consumption['NPSC47908']
        self.assertEqual(kormax.calculate_stock('NPSC47908_box',base,boxes),4)

    def test_low_and_missing_supplier_stock_do_not_create_a_full_set(self):
        supplier=self.supplier([self.row('NPSC47908-K2','до 5'),self.row('NPSC47911-K2','до 5','Немає в наявності')])
        products,boxes=kormax.build_product_catalog(self.catalog(),supplier)
        base,_=kormax.initial_base_stock(products,boxes,supplier)
        stock=kormax.materialize_stock(products,base,boxes)
        self.assertEqual(stock,{'NPSC47908':5,'NPSC47911':0,'NPSC47908_box':0,'NPSC47911_box':0})

    def test_both_exported_feeds_keep_site_articles_and_correct_set_quantities(self):
        supplier=self.supplier([self.row('NPSC47908-K2'),self.row('NPSC47911-K2')])
        products,boxes=kormax.build_product_catalog(self.catalog(),supplier)
        base,_=kormax.initial_base_stock(products,boxes,supplier)
        stock=kormax.materialize_stock(products,base,boxes)
        warehouse=kormax.build_yml(products,stock)
        self.assertEqual(set(warehouse.xpath('.//vendorCode/text()')),set(products))
        root=etree.Element('yml_catalog');offers=etree.SubElement(root,'offers')
        for i in range(2000):
            o=etree.SubElement(offers,'offer',id=f'control-{i}')
            etree.SubElement(o,'vendorCode').text=f'control-{i}'
            etree.SubElement(o,'vendor').text='Untracked'
        for sku in products:
            o=etree.SubElement(offers,'offer',id=sku)
            etree.SubElement(o,'vendorCode').text=sku
            etree.SubElement(o,'vendor').text="Nature's Protection"
        with contextlib.redirect_stdout(io.StringIO()):
            feed,_=site.build_feed(root,{},stock)
        result={o.findtext('vendorCode'):o for o in feed.findall('.//offer')}
        self.assertEqual(set(result),set(products))
        self.assertEqual(result['NPSC47908'].findtext('quantity_in_stock'),'60')
        self.assertEqual(result['NPSC47911_box'].findtext('quantity_in_stock'),'5')
        self.assertTrue(all(o.get('available')=='true' for o in result.values()))

    def test_replayed_bundle_order_is_not_deducted_twice(self):
        supplier=self.supplier([self.row('NPSC47908-K2'),self.row('NPSC47911-K2')])
        products,boxes=kormax.build_product_catalog(self.catalog(),supplier)
        order={'id':1,'products':[{'sku':'NPSC47908_box','stockId':7,'amount':1}]}
        initial={'base_stock':{},'order_snapshots':{},'supplier_bands':{}}
        base,snapshots,_=kormax.apply_order_changes(products,boxes,7,[order],initial,supplier)
        self.assertEqual(base['NPSC47908'],48)
        current={'base_stock':base,'order_snapshots':snapshots,'supplier_bands':{}}
        replay,_,deltas=kormax.apply_order_changes(products,boxes,7,[order],current,supplier)
        self.assertEqual(replay['NPSC47908'],48)
        self.assertEqual(deltas,{})


if __name__=='__main__':
    unittest.main()
