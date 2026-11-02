"""客户订货开关：暂停供货的客户保留档案，但不能新建订单。"""
import test_workflow as workflow

erp = workflow.erp


class CustomerOrderingTests(workflow.unittest.TestCase):
    setUp = workflow.WorkflowTests.setUp
    tearDown = workflow.WorkflowTests.tearDown

    def add(self, **extra):
        return erp.master({'kind': 'customer', 'create': True, 'name': '停供客户', 'region': '昌吉',
            'location_kind': 'market', 'market_id': 'M005', **extra}, '会计')['id']

    def row(self, cid):
        return next(c for c in erp.bootstrap()['customers'] if c['id'] == cid)

    def order_body(self, cid):
        return {'customer_id': cid, 'business_date': '2026-10-18', 'batch': '停供测试', 'note': '',
            'lines': [{'product_id': 'P001', 'ordered_qty': '10', 'actual_qty': '10', 'price': '3.333',
                'driver': [{'gross': '110', 'count': '5', 'tare': '1.8'}, {'gross': '112', 'count': '5', 'tare': '1.8'}],
                'customer': [{'gross': '219', 'count': '10', 'tare': '1.8'}]}]}

    def test_default_on_and_can_pause_and_resume(self):
        cid = self.add()
        self.assertEqual(self.row(cid)['ordering_enabled'], 1)
        erp.master({'kind': 'customer', 'create': False, 'id': cid, 'name': '停供客户', 'region': '昌吉',
            'location_kind': 'market', 'market_id': 'M005', 'ordering_enabled': '0'}, '会计')
        self.assertEqual(self.row(cid)['ordering_enabled'], 0)
        erp.master({'kind': 'customer', 'create': False, 'id': cid, 'name': '停供客户', 'region': '昌吉',
            'location_kind': 'market', 'market_id': 'M005', 'ordering_enabled': '1'}, '会计')
        self.assertEqual(self.row(cid)['ordering_enabled'], 1)

    def test_paused_customer_cannot_create_order(self):
        cid = self.add(ordering_enabled='0')
        with self.assertRaisesRegex(ValueError, '暂停订货'):
            erp.mutate('order', self.order_body(cid), '库管')
