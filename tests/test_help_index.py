import unittest

import erp_access
import help_index


def payload(role):
    return help_index.index({'role': role, 'permissions': erp_access.defaults(role)})


class HelpIndexAccessTests(unittest.TestCase):
    def test_route_is_authorized_for_every_account_role(self):
        for role in erp_access.ACCOUNT_ROLES:
            erp_access.authorize_read('/api/help-index', {'role': role, 'permissions': erp_access.defaults(role)})

    def test_driver_gets_function_names_but_no_metric_formulas(self):
        result = payload('司机')
        self.assertEqual(result['metrics'], [])
        self.assertIn('delivery.driver', {row['id'] for row in result['modules']})

    def test_warehouse_keeps_stock_metrics_and_loses_payroll_and_receivables(self):
        ids = {row['id'] for row in payload('库管')['metrics']}
        self.assertIn('inventory_variance', ids)
        self.assertNotIn('wage_basic', ids)
        self.assertNotIn('receivable_current', ids)

    def test_every_metric_keeps_its_formula_and_a_page_this_role_can_open(self):
        for role in erp_access.ACCOUNT_ROLES:
            result = payload(role)
            for row in result['metrics']:
                self.assertTrue(row['formula'], (role, row['id']))
                self.assertTrue(row['where'], (role, row['id']))
                self.assertEqual({item['page'] for item in row['where']}, {row['page']})

    def test_topics_only_point_at_pages_the_role_can_open(self):
        for role in erp_access.ACCOUNT_ROLES:
            for topic in payload(role)['topics']:
                self.assertTrue(topic['where'], (role, topic['id']))

    def test_every_module_keyword_and_metric_keyword_names_a_real_row(self):
        known_modules = {row['id'] for row in erp_access.module_definitions()}
        known_metrics = {row['id'] for row in payload('管理员')['metrics']}
        self.assertEqual(set(help_index.MODULE_WORDS) - known_modules, set())
        self.assertEqual(set(help_index.METRIC_WORDS) - known_metrics, set())


if __name__ == '__main__':
    unittest.main()
