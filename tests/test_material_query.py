import unittest
from decimal import Decimal
from unittest.mock import patch
import test_warehouse_landed_cost as fixture
import resources_costs as rc,material_query as q
class MaterialQueryTests(unittest.TestCase):
    setUp=fixture.WarehouseLandedTests.setUp
    tearDown=fixture.WarehouseLandedTests.tearDown
    material=fixture.WarehouseLandedTests.material
    def seed(self):
        self.material('opening','100','400');self.material('receipt','100','1000');self.material('consume','150');self.material('transfer','10',target_warehouse_id='WH-SKIN');e=self.material('receipt','10','50',wh='WH-SKIN');self.c.execute("UPDATE material_entries SET payload=json_set(payload,'$.amount_cents',0) WHERE id=?",(e['id'],));self.material('consume','2',wh='WH-SKIN')
    def test_scoped_fifo_matches_complete_ledger_and_balances(self):
        self.seed();full=rc.material_ledger(self.c,warehouse_details=True)
        scoped=rc.material_ledger(self.c,warehouse_details=True,material_ids=['RM-SOY'])
        self.assertEqual(scoped[1],full[1]);self.assertEqual(scoped[2],[s for s in full[2] if s['id']=='RM-SOY'])
        result=q.query(self.c,all_dates=True,material_id='RM-SOY',page_size=2);values=[]
        for page in range(1,result['pages']+1):values+=q.query(self.c,all_dates=True,material_id='RM-SOY',page_size=2,page=page)['rows']
        self.assertEqual(values,sorted(full[1],key=lambda r:(r['business_date'],r['sequence'],r['id']),reverse=True))
        for wh in ('WH-TOFU','WH-SKIN'):
            expected=next(s for s in full[2] if s['id']=='RM-SOY' and s['warehouse_id']==wh)
            result=q.query(self.c,view='stock',as_of='2026-10-20',material_id='RM-SOY',warehouse_id=wh)
            self.assertEqual(result['rows'][0]['qty'],expected['qty']);self.assertEqual(result['rows'][0]['value_cents'],expected['value_cents']);self.assertEqual(result['rows'][0]['uncosted_qty'],expected['uncosted_qty'])
        self.assertEqual(q.query(self.c,view='stock',as_of='2026-10-19',material_id='RM-SOY')['summary']['value_cents'],0)
    def test_page_summary_and_where_before_valuation_keep_all_warehouses(self):
        self.seed();full=rc.material_ledger(self.c)[1];expected=next(r for r in full if r['kind']=='consume' and r['warehouse_id']=='WH-SKIN')
        r=q.query(self.c,all_dates=True,warehouse_id='WH-SKIN',entry_kind='consume',material_id='RM-SOY',page_size=1)
        self.assertEqual(r['rows'][0]['cost_cents'],expected['cost_cents']);self.assertEqual(r['summary']['cost_cents'],expected['cost_cents'])
        self.assertEqual(r['rows'][0]['fifo_allocations'],expected['fifo_allocations'])
        original=rc.rows
        def guarded(c,table):
            self.assertNotEqual(table,'material_entries');return original(c,table)
        with patch.object(rc,'rows',guarded):self.assertEqual(q.query(self.c,all_dates=True,material_id='RM-SOY')['total'],6)
        sql,args=q.source_sql('2026-10-01','2026-10-31',False,material_id='RM-SOY')
        plan=' '.join(r[3] for r in self.c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn('material_history_item_date_sequence_id',plan)
    def test_voided_projection_parameters_and_price_redaction(self):
        self.seed();self.c.execute("INSERT INTO material_entries VALUES('V','V',?)",(rc.dump({'id':'V','material_id':'RM-SOY','business_date':'2026-10-20','sequence':10,'kind':'receipt','qty':'2','amount_cents':999,'voided':True,'unit':'公斤'}),))
        r=q.query(self.c,all_dates=True,status='voided');self.assertEqual(r['total'],1);self.assertIsNone(r['rows'][0]['cost_cents']);self.assertEqual(r['summary']['cost_cents'],0)
        self.assertEqual(q.query(self.c,all_dates=True,search='不存在')['total'],0)
        for args in ({'page':0},{'page_size':201},{'view':'bad'},{'status':'bad'},{'view':'stock','all_dates':True},{'all_dates':True,'start':'2026-10-01'},{'start':'2026-11-01','end':'2026-10-01'}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.query(self.c,**args)
        encoded=rc.dump(q.scope(q.query(self.c,all_dates=True),False));self.assertNotIn('_cents',encoded);self.assertNotIn('price',encoded)
    def test_start_date_keeps_earlier_lots_and_revaluation_refreshes(self):
        opening=self.material('opening','100','400',business_date='2026-09-01');self.material('receipt','100','1000',business_date='2026-09-02');self.material('consume','150',business_date='2026-10-01')
        r=q.query(self.c,start='2026-10-01',end='2026-10-01');self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['cost_cents'],90000);self.assertEqual(r['rows'][0]['balance_qty'],'50')
        self.assertEqual(q.query(self.c,view='stock',as_of='2026-09-02',material_id='RM-SOY')['summary']['value_cents'],140000)
        self.r.value({'id':opening['id'],'version':opening['version'],'amount':'800','note':'更正合成入库金额'},'会计')
        self.assertEqual(q.query(self.c,start='2026-10-01',end='2026-10-01')['rows'][0]['cost_cents'],130000)
    def test_stock_pages_keep_complete_summary(self):
        for i in range(80):self.c.execute('INSERT INTO material_items(id,name,category,unit,reorder_qty,active,version) VALUES(?,?,?,?,?,?,?)',(f'PAGE{i:03d}',f'合成物料{i:03d}','辅料','公斤','0',1,1))
        first=q.query(self.c,view='stock',search='合成物料',page_size=13);seen=[]
        for page in range(1,first['pages']+1):
            r=q.query(self.c,view='stock',search='合成物料',page_size=13,page=page);self.assertEqual(r['summary'],first['summary']);seen += [(s['id'],s['warehouse_id']) for s in r['rows']]
        self.assertEqual(len(seen),first['total']);self.assertEqual(len(set(seen)),first['total']);self.assertGreater(first['total'],50)

    def test_empty_legacy_warehouse_uses_canonical_fallback(self):
        e=self.material('receipt','10','40');self.c.execute("UPDATE material_entries SET payload=json_set(payload,'$.warehouse_id','') WHERE id=?",(e['id'],))
        r=q.query(self.c,all_dates=True,warehouse_id='WH-UNASSIGNED');self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['warehouse_id'],'WH-UNASSIGNED')
