import unittest,json,copy
from datetime import date,timedelta
from unittest.mock import patch
import test_inventory_reconciliation as fixture
import check_history as q,resources_costs as rc,inventory_reconciliation as check

erp=fixture.erp
class CheckHistoryTests(unittest.TestCase):
    setUp=fixture.InventoryReconciliationTests.setUp
    tearDown=fixture.InventoryReconciliationTests.tearDown
    order=fixture.InventoryReconciliationTests.order
    report=fixture.InventoryReconciliationTests.report
    body=fixture.InventoryReconciliationTests.body
    save=fixture.InventoryReconciliationTests.save
    def query(self,**kw):
        with erp.connect() as c:return q.history(c,**kw)
    def test_original_saved_sources_and_versions_survive_current_change(self):
        self.order();self.save(self.body());old=next(p for p in self.report()['products'] if p['product_id']=='P004')
        self.order('580');self.assertTrue(self.report()['source_changed']);r=self.query(all_dates=True)['rows'][0];self.assertEqual(r['difference_qty'],'20');self.assertEqual(r['shipped_qty'],'600')
        self.save(self.body());current=next(p for p in self.report()['products'] if p['product_id']=='P004');latest=self.query(all_dates=True);self.assertEqual(latest['total'],1);self.assertEqual(latest['rows'][0]['difference_qty'],current['difference_qty'])
        all_versions=self.query(all_dates=True,versions='all');self.assertEqual([p['version'] for p in all_versions['rows']],[2,1]);self.assertEqual([p['difference_qty'] for p in all_versions['rows']],['0',old['difference_qty']]);self.assertEqual(all_versions['summary'][0]['matched_count'],1);self.assertEqual(all_versions['summary'][0]['variance_count'],1)
        with erp.connect() as c:
            v=q.record(c,'2026-10-22',1);self.assertEqual(v['source_snapshot'][0]['actual_qty'],'600');self.assertFalse(v['is_latest'])
        self.order('570');self.assertEqual(self.query(all_dates=True)['rows'][0]['difference_qty'],'0');self.assertEqual(self.report()['products'][3]['status'],'实发来源已变更，请重新核对')
    def insert(self,day,i=0,**extra):
        product={'product_id':'P004','unit':'公斤','pre_qty':'1','post_qty':'0.9','post_in_qty':'0','post_out_qty':'0','post_source':'manual'}
        value={'id':'IC-'+day,'kind':'inventory-check','business_date':day,'version':1,'handler':'CH83合成经办','note':'原保存依据 % _','sources_checked':True,'products':[product],'source_snapshot':[{'order_id':'H'+str(i),'product_id':'P004','unit':'公斤','actual_qty':'0.1','ordered_qty':'0.1'}],'history':[],**extra}
        with erp.connect(True) as c:c.execute('INSERT INTO trade_records VALUES(?,?)',(value['id'],rc.dump(value)))
        return value
    def test_pages_summary_decimal_and_search_are_scope_wide(self):
        for i in range(126):self.insert((date(2026,6,1)+timedelta(days=i)).isoformat(),i)
        first=self.query(all_dates=True);keys=[]
        for page in range(1,first['pages']+1):
            r=self.query(all_dates=True,page=page);self.assertEqual(r['summary'],first['summary']);keys += [(x['business_date'],x['version'],x['product_id']) for x in r['rows']];self.assertTrue(all(x['difference_qty']=='0' for x in r['rows']))
        self.assertEqual(len(keys),126);self.assertEqual(len(set(keys)),126);self.assertEqual(first['summary'][0]['matched_count'],126);self.assertEqual(first['summary'][0]['unit'],'公斤');self.assertNotIn('shipped_qty',first['summary'][0]);self.assertEqual(self.query(all_dates=True,search='% _')['total'],126)
        self.assertEqual(self.query(start='2026-06-01',end='2026-06-01')['total'],1);self.assertEqual(self.query(all_dates=True,search='不存在')['rows'],[])
    def test_pending_unknown_unit_and_negative_status(self):
        v=self.insert('2026-06-01');p=v['products'][0]
        cases=[('missing',{'products':[{**p,'post_qty':''}]}),('unconfirmed',{'sources_checked':False}),('unit',{'source_snapshot':[{'product_id':'P004','unit':'筐','actual_qty':'1'}]}),('negative',{'products':[{**p,'pre_qty':'0'}]}),('source_missing',{'source_snapshot':None})]
        for status,changes in cases:
            with self.subTest(status=status),erp.connect(True) as c:
                body={**v,**changes};c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump(body),v['id']));r=q.history(c,all_dates=True,status=status);self.assertEqual(r['total'],1);self.assertEqual(r['rows'][0]['status'],status)
                if status not in ('negative',):self.assertIsNone(r['rows'][0]['difference_qty'])
                if status=='source_missing':self.assertFalse(q.record(c,'2026-06-01',1)['snapshot_available'])
    def test_current_catalog_unit_change_does_not_reinterpret_snapshot(self):
        self.insert('2026-06-01')
        with erp.connect(True) as c:c.execute("UPDATE products SET unit='筐',name='新档案名称' WHERE id='P004'")
        r=self.query(all_dates=True)['rows'][0];self.assertEqual(r['unit'],'公斤');self.assertEqual(r['product_name'],'新档案名称');self.assertEqual(r['status'],'matched')
    def test_readonly_redaction_indexes_and_parameters(self):
        v=self.insert('2026-06-01');v['amount_cents']=999;v['products'][0]['price']='9';v['source_snapshot'][0]['price']='99'
        with erp.connect(True) as c:
            c.execute('UPDATE trade_records SET payload=? WHERE id=?',(rc.dump(v),v['id']));before=c.total_changes
            with patch.object(rc,'rows',side_effect=AssertionError('history must not read entire ledgers')):
                r=q.history(c,all_dates=True);detail=q.record(c,'2026-06-01',1)
            self.assertEqual(c.total_changes,before);self.assertNotIn('price',json.dumps(detail));self.assertNotIn('_cents',json.dumps(r));self.assertNotIn('_cents',json.dumps(detail))
            sql,args=q.source_sql('2026-06-01','2026-06-30',False);plan=' '.join(r[3] for r in c.execute('EXPLAIN QUERY PLAN '+sql,args));self.assertIn('SEARCH t USING INDEX trade_check_kind_date_id',plan)
            for args in ({'page':0},{'page_size':201},{'status':'bad'},{'versions':'bad'},{'all_dates':True,'start':'2026-06-01'},{'start':'2026-07-01','end':'2026-06-01'},{'start':'2026-02-30'}):
                with self.subTest(args=args),self.assertRaises(ValueError):q.history(c,**args)
            with self.assertRaises(LookupError):q.record(c,'2026-06-01',9)
            with self.assertRaises(ValueError):q.record(c,'bad',1)
