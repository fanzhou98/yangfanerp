import unittest
import erp_access as access
import auth


class ReadEndpointTests(unittest.TestCase):
    def user(self, role):
        return {'role': role, 'permissions': access.defaults(role)}

    def test_new_settlement_and_profit_endpoints_allow_admin(self):
        for path in ('/api/byproduct-settlement', '/api/product-profit'):
            access.authorize_read(path, self.user('管理员'))

    def test_accountant_can_read_byproduct_settlement_and_profit(self):
        access.authorize_read('/api/byproduct-settlement', self.user('会计'))
        access.authorize_read('/api/product-profit', self.user('会计'))

    def test_driver_and_warehouse_cannot_read_profit(self):
        with self.assertRaises(auth.AuthError):
            access.authorize_read('/api/product-profit', self.user('司机'))
        with self.assertRaises(auth.AuthError):
            access.authorize_read('/api/product-profit', self.user('库管'))
