"""物料档案删除：只允许删未使用的自建物料，预置/有流水/已被采购引用时拒绝。"""
import unittest,uuid
import test_production_daily as fixture
import resources_costs as rc

erp=fixture.erp
class MaterialDeleteTests(unittest.TestCase):
    setUp=fixture.DailyFactoryTests.setUp
    tearDown=fixture.DailyFactoryTests.tearDown
    def create(self,name='测试辅料（待删）'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).item({'request_key':str(uuid.uuid4()),'name':name,'category':'辅料','unit':'公斤','reorder_qty':'0','active':True},'管理员')
    def delete(self,mid,version=1,reason='录错物料'):
        with erp.connect(True) as c:
            return rc.Operations(c,erp.now,erp.audit).item_delete({'request_key':str(uuid.uuid4()),'id':mid,'version':version,'reason':reason},'管理员')
    def test_delete_unused_custom_material(self):
        mid=self.create()['id']
        self.assertTrue(self.delete(mid)['deleted'])
        with erp.connect() as c:self.assertIsNone(c.execute('SELECT 1 FROM material_items WHERE id=?',(mid,)).fetchone())
    def test_builtin_material_is_protected(self):
        with self.assertRaisesRegex(ValueError,'预置'):self.delete('A-GYPSUM')
    def test_material_with_entry_cannot_be_deleted(self):
        mid=self.create()['id']
        with erp.connect(True) as c:
            rc.Operations(c,erp.now,erp.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':mid,'business_date':'2026-10-20','kind':'receipt','qty':'1','amount':'1','warehouse_id':'WH-COMMON','note':'测试入库','handler':'会计'},'管理员')
        with self.assertRaisesRegex(ValueError,'库存流水'):self.delete(mid)
    def test_stale_version_is_rejected(self):
        mid=self.create()['id']
        with self.assertRaisesRegex(ValueError,'已变更'):self.delete(mid,version=9)
    def test_permission_route_registered(self):
        import erp_access
        self.assertEqual(erp_access.mutation_permissions('/api/resources/item-delete',{}),['materials.catalog'])
        self.assertEqual(erp_access.mutation_permissions('/api/resources/item-order',{}),['materials.pin'])
        self.assertEqual(erp_access.mutation_permissions('/api/resources/material-batch',{}),['materials.write'])
