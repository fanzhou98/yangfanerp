"""权限判定一致性守卫：界面门控与路由权限都必须引用规范动作名。

历史上出现过两类漂移：后端保留了按运行模式切换的第二张动作表（v1.11.36 已删），
界面也保留过旧别名映射（v1.11.46 已改为读服务端动作目录）。这个测试把“界面引用的
动作名”“路由要求的动作名”都钉在 erp_access 的定义表上，以后再加页面或路由时，
写错动作名会在测试里直接失败，而不是等岗位用户点出「无权限」。
"""
import glob
import re
import unittest

import erp_access


KNOWN_ACTIONS = {row[0] for row in erp_access.ACTIONS} | {row[0] for row in erp_access.EXTRA_ACTIONS}


class UIGateActionTest(unittest.TestCase):
    def test_ui_gates_use_canonical_action_names(self):
        problems = []
        for name in sorted(glob.glob('web/*.js')):
            with open(name, encoding='utf-8') as f:
                source = f.read()
            for match in re.finditer(r"(?:canAction|needPermission)\(\s*'([^']+)'", source):
                if match.group(1) not in KNOWN_ACTIONS:
                    problems.append(f'{name}: {match.group(1)}')
            for match in re.finditer(r'data-required-action="([^"]+)"', source):
                if match.group(1) not in KNOWN_ACTIONS:
                    problems.append(f'{name}: data-required-action={match.group(1)}')
        self.assertEqual(problems, [])

    def test_routes_map_to_canonical_action_names(self):
        probes = [
            ('/api/social-compensation', {}), ('/api/crate-packaging', {}),
            ('/api/receipt-ocr/settings', {}), ('/api/receipt-evidence/recognize', {}),
            ('/api/inventory-check', {}), ('/api/order-corrections', {'action': 'shipment'}),
            ('/api/processing', {}), ('/api/processing/rules', {}),
            ('/api/byproduct-settlement', {'action': 'settle'}),
            ('/api/byproduct-settlement', {'action': 'config'}),
            ('/api/fund-accounts', {}), ('/api/byproduct-statements/issue', {}),
            ('/api/gel-tofu/output', {}), ('/api/finished-goods/receipt', {}),
            ('/api/trade/trip', {}), ('/api/driver/weights', {}),
            ('/api/master', {'kind': 'customer'}), ('/api/master', {'kind': 'product'}),
            ('/api/master', {'kind': 'rule'}), ('/api/master/batch-rules', {}),
            ('/api/master/product-order', {}), ('/api/backup', {}),
            ('/api/warehouse', {}), ('/api/stock-close', {}),
            ('/api/resources/void', {'ledger': 'material'}),
            ('/api/resources/void', {'ledger': 'expense'}),
            ('/api/resources/void', {'ledger': 'byproduct'}),
            ('/api/resources/receive', {}), ('/api/resources/item', {}),
            ('/api/resources/restore', {'ledger': 'material'}),
            ('/api/returns/action', {'action': 'refund'}),
        ]
        problems = []
        for path, body in probes:
            needed = erp_access.mutation_permissions(path, body)
            if needed is None:
                problems.append(f'{path} {body}: 未配置权限（返回 None）')
                continue
            for key in needed:
                if key not in KNOWN_ACTIONS:
                    problems.append(f'{path} {body}: {key}')
        self.assertEqual(problems, [])

    def test_every_protected_module_needs_admin_action(self):
        # 管理页只允许管理员；补页逻辑不得把它们顺手补回普通岗位。
        known_modules = {row['id'] for row in erp_access.module_definitions()}
        for module in erp_access.PROTECTED_MODULES:
            self.assertIn(module, known_modules)


if __name__ == '__main__':
    unittest.main()
