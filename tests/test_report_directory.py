import json,unittest,uuid
import test_reports_055 as fixture
import report_directory as directory
import reporting,erp_access as access,resources_costs as rc

erp=fixture.erp
class ReportDirectoryTests(unittest.TestCase):
    setUp=fixture.ReportBatchTests.setUp
    tearDown=fixture.ReportBatchTests.tearDown
    order=fixture.ReportBatchTests.order
    def directory(self,role='管理员',grants=None):
        with erp.connect() as c:return directory.catalog(c,'2026-10-20',grants or access.defaults(role),role)
    def entries(self,r):return [p for t in r['topics'] for p in t['pages']]
    def test_management_roles_can_find_map_without_expanding_amount_permissions(self):
        for role in ('管理员','老板','会计','出纳','厂长','库管','物流负责人'):
            self.assertIn('workspace.report-map',access.defaults(role)['modules'])
        self.assertNotIn('workspace.report-map',access.defaults('司机')['modules'])
        self.assertEqual(access.defaults('厂长')['data_scopes'],[])
    def test_directory_nine_topics_permissions_and_no_business_amounts(self):
        r=self.directory('厂长');self.assertEqual(len(r['topics']),9)
        entries=self.entries(r);self.assertTrue(entries)
        self.assertFalse(any(p['page'] in ('analytics','expenses','product-profit','ledger') for p in entries))
        self.assertNotIn('_cents',json.dumps(r));self.assertNotIn('value',json.dumps(r))
        self.assertTrue(all(p['owner'] and 'chart_count' in p and 'status' in p for p in entries))
    def test_unauthorized_source_never_evaluated(self):
        from unittest.mock import patch
        with patch.object(reporting,'management_month',side_effect=AssertionError('unauthorized')),patch.object(reporting,'expense_summary',side_effect=AssertionError('unauthorized')):
            self.directory('厂长')
    def test_production_chart_count_matches_live_contract(self):
        r=self.directory();p=next(p for p in self.entries(r) if p['page']=='production-report')
        with erp.connect() as c:actual=reporting.production_day(c,'2026-10-20')
        self.assertEqual(p['chart_slots'],len(actual['charts']));self.assertEqual(p['level'],'C');self.assertTrue(p['gaps'])
    def test_expense_chart_count_changes_with_data_not_frontend_constants(self):
        with erp.connect(True) as c:
            op=rc.Operations(c,erp.now,erp.audit)
            for cat in ('rent','water'):op.expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':cat,'amount':'100','handler':'测试','note':'凭据'},'管理员')
        self.assertEqual(next(p for p in self.entries(self.directory()) if p['page']=='expenses')['chart_count'],0)
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','category':'rent','amount':'1','handler':'测试','note':'凭据'},'管理员')
            actual=reporting.expense_summary(c,'2026-10')
        p=next(p for p in self.entries(self.directory()) if p['page']=='expenses')
        self.assertEqual(p['chart_count'],1);self.assertEqual(p['chart_slots'],len(actual['charts']))
    def test_sparse_trend_and_missing_are_not_formal_charts(self):
        self.order('A')
        with erp.connect(True) as c:
            row=json.loads(c.execute("SELECT payload FROM orders WHERE id='A'").fetchone()[0]);row['lines'][0]['ordered_qty']='1'
            c.execute('UPDATE orders SET payload=? WHERE id=?',(json.dumps(row),'A'))
        p=next(p for p in self.entries(self.directory()) if p['page']=='sales-daily')
        trend=next(c for c in p['charts'] if c['kind']=='trend')
        self.assertEqual(trend['level'],'B');self.assertEqual(trend['sample_count'],1)
        state=directory.chart_status([{'kind':'rank','title':'缺数据','points':[]}])
        self.assertEqual(state['chart_count'],0);self.assertEqual(state['level'],'C')
    def test_accountant_profit_routes_to_existing_page_without_analytics_grant(self):
        entries=self.entries(self.directory('会计'))
        self.assertTrue(any(p['page']=='product-profit' for p in entries))
        self.assertFalse(any(p['page']=='analytics' for p in entries))
    def test_existing_custom_grants_gain_only_map_navigation(self):
        with erp.connect(True) as c:
            c.execute('INSERT OR REPLACE INTO role_permissions VALUES(?,?,?,?)',('厂长',7,json.dumps({'modules':['workspace.dashboard','production.daily'],'actions':[],'data_scopes':[]}),'2026-10-25'))
            grants=access.permissions(c,'厂长')
        self.assertIn('workspace.report-map',grants['modules'])
        self.assertEqual(grants['data_scopes'],[]);self.assertEqual(grants['actions'],[])
        self.assertEqual(grants['version'],7)

    def test_dictionary_versions_rules_and_visibility(self):
        admin=self.directory();director=self.directory('厂长')
        self.assertTrue(admin['metrics']['version']);self.assertEqual(admin['metrics']['effective_date'],'2026-10-26')
        metrics={m['id']:m for m in admin['metrics']['items']}
        self.assertEqual(len(metrics),len(admin['metrics']['items']))
        self.assertIn('协商',metrics['delivery_claim']['formula'])
        self.assertIn('不能循环',metrics['inventory_variance']['missing'])
        self.assertIn('不以',metrics['settled_kg']['rules'])
        self.assertNotIn('net_profit',{m['id'] for m in director['metrics']['items']})
        self.assertNotIn('actual_cash',{m['id'] for m in director['metrics']['items']})
    def test_chart_ownership_has_one_overview_chart_and_production_at_most_one(self):
        entries=self.entries(self.directory())
        management=next(p for p in entries if p['page']=='analytics' and p['tab']=='overview')
        self.assertEqual(management['chart_slots'],1)
        production=next(p for p in entries if p['page']=='production-report')
        self.assertLessEqual(production['chart_slots'],1)

    def test_read_only_does_not_write(self):
        with erp.connect() as c:
            before=c.total_changes;directory.catalog(c,'2026-10-20',access.defaults('管理员'),'管理员')
            self.assertEqual(c.total_changes,before)

if __name__=='__main__':unittest.main()
