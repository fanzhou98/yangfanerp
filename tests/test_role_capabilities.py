"""默认岗位的最小权限矩阵：防止后续配置把敏感动作误授出去。"""
import unittest

import erp_access


def actions(role):
    return set(erp_access.defaults(role)['actions'])


class RoleCapabilityTests(unittest.TestCase):
    def test_cashier_cannot_approve_or_settle_business(self):
        for key in ('finance.settle', 'costs.write', 'costs.close',
                    'purchases.write', 'master.products.write', 'master.pricing.write'):
            with self.subTest(action=key):
                self.assertFalse(erp_access.role_can('出纳', key), f'出纳不应拥有 {key}')

    def test_warehouse_cannot_touch_money_or_costs(self):
        for key in ('finance.receipt', 'finance.settle', 'costs.write', 'costs.close',
                    'materials.value', 'master.pricing.write'):
            with self.subTest(action=key):
                self.assertFalse(erp_access.role_can('库管', key), f'库管不应拥有 {key}')

    def test_accountant_cannot_receive_money(self):
        self.assertFalse(erp_access.role_can('会计', 'finance.receipt'), '会计不应登记收款')

    def test_owner_is_read_only(self):
        self.assertEqual(actions('老板'), set())

    def test_admin_keeps_full_control(self):
        for key in ('finance.receipt', 'finance.settle', 'costs.close',
                    'master.products.write', 'master.pricing.write', 'system.backup'):
            with self.subTest(action=key):
                self.assertTrue(erp_access.role_can('管理员', key), f'管理员应拥有 {key}')


if __name__ == '__main__':
    unittest.main()
