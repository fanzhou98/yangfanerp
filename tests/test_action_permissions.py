"""每个写接口都必须显式登记权限，或被允许的处理器内部鉴权覆盖。"""
from pathlib import Path
import re
import unittest

import erp_access


# 这些路径在进入统一权限表之前就由处理器自己校验角色（或有意的公开入口）。
INTERNALLY_GUARDED = {
    '/api/auth/login': '登录入口，未登录可访问',
    '/api/auth/logout': '退出登录，仅影响本人会话',
    '/api/auth/password': '修改本人密码，需校验旧密码',
    '/api/auth/activity': '登录态心跳，仅记录活动时间',
    '/api/role-permissions': 'save_permissions 内仅管理员可写',
    '/api/users': 'auth.create_user 内仅管理员可写',
    '/api/inventory-value': 'save_settings 内要求 costs.close',
    '/api/audit-rollback': '处理器内要求管理员',
    '/api/business-reset': 'authorize_authenticated 内要求管理员',
}


class ActionPermissionTests(unittest.TestCase):
    def post_paths(self):
        source = (Path(__file__).resolve().parent.parent / 'server.py').read_text('utf-8')
        block = source[source.index('def do_POST'):]
        return sorted(set(re.findall(r"path=='([^']+)'", block)))

    def test_every_post_path_is_registered_or_internally_guarded(self):
        for path in self.post_paths():
            if path in INTERNALLY_GUARDED:
                continue
            with self.subTest(path=path):
                self.assertIsNotNone(
                    erp_access.mutation_permissions(path, {}),
                    f'{path} 未登记权限，登录态会被判为未知操作',
                )

    def test_internal_guards_are_still_present_in_source(self):
        source = (Path(__file__).resolve().parent.parent / 'server.py').read_text('utf-8')
        for path, reason in INTERNALLY_GUARDED.items():
            if path.startswith('/api/auth/'):
                continue
            with self.subTest(path=path):
                self.assertIn(path, source, f'{path} 已不存在，请清理允许列表（{reason}）')

    def test_opening_receipts_requires_cashier(self):
        self.assertEqual(erp_access.mutation_permissions('/api/opening-receipts', {}), ['finance.receipt'])
        erp_access.authorize_authenticated('/api/opening-receipts', {}, '出纳')
        erp_access.authorize_authenticated('/api/opening-receipts', {}, '管理员')
        for role in ('库管', '会计', '厂长', '老板'):
            with self.subTest(role=role):
                with self.assertRaises(Exception):
                    erp_access.authorize_authenticated('/api/opening-receipts', {}, role)


if __name__ == '__main__':
    unittest.main()
