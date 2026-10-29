import copy,unittest
from decimal import Decimal
import crate_packaging as packing
import crate_accounting,billing,trade,resources_costs as rc
import test_delivery_trade as fixture


class CratePackagingTests(unittest.TestCase):
    setUp=fixture.DeliveryTradeTests.setUp
    tearDown=fixture.DeliveryTradeTests.tearDown
    order=fixture.DeliveryTradeTests.order

    def configure(self,**changes):
        value={'version':packing.catalog(self.c)['version'],'methods':[{'id':'M-PAPER','name':'可改名包材','active':True},{'id':'M-HEAVY','name':'较重包材','active':True}],'default_method_id':'M-PAPER','rules':[{'product_id':'P001','asset_id':'CR-WHITE','method_id':'M-PAPER','tare':'2'},{'product_id':'P001','asset_id':'CR-WHITE','method_id':'M-HEAVY','tare':'2.501'}],**changes}
        return packing.save(self.c,value,'管理员',self.erp.now,self.erp.audit)

    def raw(self):
        return [{'asset_id':'CR-WHITE','qty':10,'tare':'2','packing_lines':[{'method_id':'M-PAPER','qty':8,'tare':'2'},{'method_id':'M-HEAVY','qty':2,'tare':'2.501'}]}]

    def test_precise_total_tare_and_physical_crate_identity(self):
        self.configure();rows=crate_accounting.normalize(self.c,'P001',self.raw(),Decimal(10))
        self.assertEqual(packing.total_tare(rows[0]),Decimal('21.002'))
        line={'actual_qty':'10','driver_weight_basis':'gross','driver':[{'gross':'100'}],'customer':[{'gross':'100'}],'crate_lines':rows}
        self.assertEqual(billing.settlement_net(line,'driver'),Decimal('78.998'))
        self.assertEqual(billing.settlement_net(line,'customer'),Decimal('78.998'))
        import production_management as factory
        for source in ('driver','customer'):
            weighted={**line,source:[{'gross':'100','count':'10','tare':'2'}]}
            self.assertEqual(factory.line_weight(weighted,source),(Decimal('78.998'),Decimal(10)))
        legacy={**line,'driver_weight_basis':'legacy_net','driver':[{'gross':'100','count':'10','tare':'0'}]}
        self.assertEqual(factory.line_weight(legacy,'driver'),(Decimal(100),Decimal(10)))
        o=self.order();o['lines'][0]['crate_lines']=rows
        before=rc.dump(rc.rows(self.c,'asset_records'))
        physical=trade.shipped_crates(self.c,o)
        self.assertEqual([(r['asset_id'],r['qty']) for r in physical],[('CR-WHITE',10)])
        self.assertNotIn('packing_lines',physical[0])
        self.assertEqual(rc.dump(rc.rows(self.c,'asset_records')),before)

    def test_historical_snapshot_survives_catalog_change_and_retirement(self):
        self.configure();rows=crate_accounting.normalize(self.c,'P001',self.raw(),Decimal(10))
        self.configure(methods=[{'id':'M-PAPER','name':'新名字','active':False},{'id':'M-HEAVY','name':'新重包材','active':False}],default_method_id='',rules=[])
        saved=crate_accounting.normalize(self.c,'P001',copy.deepcopy(rows),Decimal(10),prior=rows)
        self.assertEqual(saved,rows)
        changed=copy.deepcopy(rows);changed[0]['packing_lines'][0]['qty']=7;changed[0]['packing_lines'][1]['qty']=3
        with self.assertRaises(ValueError):crate_accounting.normalize(self.c,'P001',changed,Decimal(10),prior=rows)

    def test_rules_quantity_versions_and_permissions_are_server_validated(self):
        self.configure(rules=[])
        with self.assertRaisesRegex(ValueError,'标准'):crate_accounting.normalize(self.c,'P001',self.raw(),Decimal(10))
        self.configure()
        bad=self.raw();bad[0]['packing_lines'][0]['qty']=7
        with self.assertRaisesRegex(ValueError,'合计'):crate_accounting.normalize(self.c,'P001',bad,Decimal(10))
        with self.assertRaises(ValueError):self.configure(version=0)
        with self.assertRaises(ValueError):packing.save(self.c,{},'库管',self.erp.now,self.erp.audit)
        with self.assertRaisesRegex(ValueError,'皮重'):packing.tare_value('')
        with self.assertRaises(ValueError):packing.tare_value('NaN')

    def test_old_lines_retain_original_tare(self):
        old=crate_accounting.normalize(self.c,'P001',[{'asset_id':'CR-WHITE','qty':10,'tare':'1.75'}],Decimal(10))
        self.assertEqual(packing.total_tare(old[0]),Decimal('17.50'))
        self.assertNotIn('packing_lines',old[0])

    def special_asset(self,**changes):
        asset=next(a for a in rc.rows(self.c,'asset_records') if a['id']=='CR-WHITE')
        asset['special_packaging']=packing.normalize_asset_settings([{'id':'S-CLOTH','name':'布包','tare':'2.501','active':True,**changes}])
        self.c.execute('UPDATE asset_records SET payload=? WHERE id=?',(rc.dump(asset),asset['id']))

    def test_ordinary_needs_no_catalog_and_inherits_customer_tare(self):
        self.assertFalse(packing.catalog(self.c)['methods'])
        raw=[{'asset_id':'CR-WHITE','qty':10,'tare':'1.75','packing_lines':[{'method_id':packing.ORDINARY,'packing_kind':'ordinary','qty':10,'tare':'1.75'}]}]
        rows=crate_accounting.normalize(self.c,'P001',raw,Decimal(10))
        self.assertEqual(packing.total_tare(rows[0]),Decimal('17.50'))
        raw[0]['packing_lines'][0]['tare']='0'
        with self.assertRaisesRegex(ValueError,'沿用'):crate_accounting.normalize(self.c,'P001',raw,Decimal(10))

    def test_special_quantities_with_automatic_ordinary_remainder_and_snapshots(self):
        self.special_asset()
        raw=[{'asset_id':'CR-WHITE','qty':10,'tare':'2','packing_lines':[{'method_id':packing.ORDINARY,'packing_kind':'ordinary','qty':8,'tare':'2'},{'method_id':'S-CLOTH','qty':2,'tare':'2.501'}]}]
        rows=crate_accounting.normalize(self.c,'P001',raw,Decimal(10))
        self.assertEqual(packing.total_tare(rows[0]),Decimal('21.002'))
        self.assertEqual(packing.catalog(self.c)['special_assets']['CR-WHITE'][0]['name'],'布包')
        self.special_asset(tare='3',name='新布包')
        self.assertEqual(crate_accounting.normalize(self.c,'P001',copy.deepcopy(rows),Decimal(10),prior=rows),rows)
        with self.assertRaisesRegex(ValueError,'变化'):crate_accounting.normalize(self.c,'P001',raw,Decimal(10))
        changed=copy.deepcopy(rows);changed[0]['packing_lines'][0]['qty']=7;changed[0]['packing_lines'][1]['qty']=3
        revised=crate_accounting.normalize(self.c,'P001',changed,Decimal(10),prior=rows)
        self.assertEqual(revised[0]['packing_lines'][1]['tare'],'2.501')
        self.special_asset(active=False)
        with self.assertRaisesRegex(ValueError,'启用'):crate_accounting.normalize(self.c,'P001',changed,Decimal(10),prior=rows)

    def test_asset_settings_are_extensible_and_validate_reserved_ids(self):
        row=packing.normalize_asset_settings([{'name':'任意特殊包材','tare':'3.125'}])[0]
        self.assertTrue(row['id'].startswith('PACK-'))
        self.assertEqual(row['tare'],'3.125')
        with self.assertRaisesRegex(ValueError,'皮重'):packing.normalize_asset_settings([{'name':'未设皮重'}])
        with self.assertRaises(ValueError):packing.normalize_asset_settings([{'id':packing.ORDINARY,'name':'冒用普通','tare':'0'}])
        with self.assertRaisesRegex(ValueError,'停用'):packing.normalize_asset_settings([],prior=[row])

    def test_legacy_reserved_id_is_not_reinterpreted_as_new_ordinary(self):
        legacy={'version':1,'methods':[{'id':packing.ORDINARY,'name':'旧自定义包法','active':True}],'default_method_id':packing.ORDINARY,'rules':[{'product_id':'P001','asset_id':'CR-WHITE','method_id':packing.ORDINARY,'tare':'3'}]}
        self.c.execute('INSERT INTO meta VALUES(?,?)',(packing.KEY,rc.dump(legacy)))
        raw=[{'asset_id':'CR-WHITE','qty':10,'tare':'2','packing_lines':[{'method_id':packing.ORDINARY,'method_name':'旧自定义包法','qty':10,'tare':'3'}]}]
        rows=crate_accounting.normalize(self.c,'P001',raw,Decimal(10))
        self.assertEqual(rows[0]['packing_lines'][0]['method_name'],'旧自定义包法')
        self.assertNotIn('packing_kind',rows[0]['packing_lines'][0])
        self.assertEqual(packing.total_tare(rows[0]),Decimal('30'))
        spoof=copy.deepcopy(rows);spoof[0]['packing_lines'][0]['packing_kind']='ordinary'
        self.assertEqual(crate_accounting.normalize(self.c,'P001',spoof,Decimal(10),prior=rows),rows)
        legacy['methods'][0]['active']=False;legacy['default_method_id']='';legacy['rules']=[]
        packing.save(self.c,legacy,'管理员',self.erp.now,self.erp.audit)
        self.assertEqual(crate_accounting.normalize(self.c,'P001',rows,Decimal(10),prior=rows),rows)
