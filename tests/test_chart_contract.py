import json,unittest
from decimal import Decimal
import test_reports_055 as fixture
import reporting
import owner_analysis

erp=fixture.erp
class ChartContracts(unittest.TestCase):
    setUp=fixture.ReportBatchTests.setUp
    tearDown=fixture.ReportBatchTests.tearDown
    order=fixture.ReportBatchTests.order
    def test_waterfall_has_server_cumulative_cents_and_exact_total(self):
        chart=reporting.waterfall([('净额','净额',10005),('成本','成本',-20008)],'测试')
        self.assertEqual([(p['start'],p['end']) for p in chart['points']],[(0,10005),(10005,-10003),(0,-10003)])
        self.assertEqual(chart['points'][-1]['value'],-10003)
        self.assertFalse(reporting.waterfall([('待补','待补',None)],'缺收入')['points'])
    def test_customer_drilldown_uses_ids_and_keeps_units(self):
        self.order('A',amount=10000);self.order('B',unit='袋',amount=20000)
        with erp.connect(True) as c:
            o=json.loads(c.execute("SELECT payload FROM orders WHERE id='B'").fetchone()[0]);o['customer_id']='C002';o['customer_name']='测试客户'
            c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(o),'B'))
        with erp.connect() as c:r=reporting.sales(c,'2026-10-01','2026-10-31')
        ranks=r['charts'][1]['points'];self.assertEqual(len(ranks),2);self.assertEqual({r['key'] for r in ranks},{'C001','C002'})
        self.assertEqual(ranks[0]['value'],20000);self.assertEqual(ranks[0]['products'][0]['unit'],'袋')
        self.assertEqual(sum(Decimal(row['share_pct']) for row in ranks),100)
        self.assertEqual(ranks[0]['products'][0]['sales_cents'],20000)
    def test_composition_splits_sowing_and_unknown_not_origin_guess(self):
        chart=reporting.inventory_composition([{'warehouse_name':'大库','qty':'10','sowing':{'春播':'2','复播':'4','未登记':'0'}}]);row=chart['points'][0]
        self.assertEqual(row['values']['spring'],'2');self.assertEqual(row['values']['summer'],'4');self.assertEqual(row['values']['unknown'],'4')
        self.assertEqual(sum(Decimal(v) for v in row['percentages'].values()),100)
    def test_composition_uses_sowing_origin_groups_in_tons(self):
        chart=reporting.inventory_composition([{'warehouse_name':'大库','qty':'2600','groups':{'春播|伊犁':'2000','复播|湖北':'600'}}]);row=chart['points'][0]
        self.assertEqual(chart['unit'],'吨');self.assertEqual(row['total'],'2.6')
        self.assertEqual(row['values'],{'春播|伊犁':'2','复播|湖北':'0.6'})
        self.assertEqual(sum(Decimal(v) for v in row['percentages'].values()),100)
        self.assertEqual([part['label'] for part in chart['parts']],['春播·伊犁','复播·湖北'])
        self.assertIn('柱长按各库房总量比例',chart['note'])
    def test_all_unknown_sowing_origin_groups_is_gap(self):
        chart=reporting.inventory_composition([{'warehouse_name':'大库','qty':'1000','groups':{'未登记|未登记':'1000'}}])
        self.assertEqual(chart['points'],[]);self.assertIn('播种类型与产地未登记',chart['empty_title'])
    def test_yield_only_connects_comparable_precomputed_values(self):
        chart=reporting.yield_comparison([{'product_name':'大豆腐','system':'tofu','yield_kg_per_kg':'2.5','previous_yield':'2','change_pct':None,'change_alert':False}],10)
        self.assertIsNone(chart['points'][0]['prev']);self.assertIsNone(chart['points'][0]['change_pct']);self.assertEqual(chart['comparable_count'],0)
        comparable=reporting.yield_comparison([{'product_name':'大豆腐','system':'tofu','yield_kg_per_kg':'2.5','previous_yield':'2','change_pct':'25','change_alert':True}],10)
        self.assertEqual(comparable['comparable_count'],1)
    def test_all_unknown_sowing_is_gap_not_100_percent_gray(self):
        chart=reporting.inventory_composition([{'warehouse_name':'大库','qty':'10','sowing':{'春播':'0','复播':'0','未登记':'10'}}])
        self.assertEqual(chart['points'],[]);self.assertIn('播种类型未登记',chart['empty_title'])
    def test_production_day_charts_are_quantity_only_and_handle_empty_basis(self):
        with erp.connect() as c:report=reporting.production_day(c,'2026-10-20')
        self.assertLessEqual(len(report['charts']),2);self.assertFalse('_cents' in json.dumps(report))
        self.assertTrue(report['gaps']);self.assertTrue(all(g['field'] and g['owner'] for g in report['gaps']))
    def test_live_day_and_month_bridge_match_reported_difference(self):
        self.order('A')
        with erp.connect(True) as c:
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['lines'][0].update(ordered_qty='1',factory=[],driver=[],customer=[],not_shipped=False,price='100');row['batch']='日常订货';row['route']='测试';c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(row),'A'))
        with erp.connect() as c:
            monthly=reporting.management_month(c,'2026-10');daily=owner_analysis.report(c,'2026-10-20')
        self.assertEqual(monthly['bridge']['points'][-1]['end'],monthly['difference_cents'])
        self.assertEqual(daily['cost']['bridge']['points'][-1]['end'],daily['cost']['difference_cents'])

if __name__=='__main__':unittest.main()
