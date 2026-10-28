import copy,json,unittest
import test_workflow as workflow

erp=workflow.erp

class WeightPriorityTests(unittest.TestCase):
    setUp=workflow.WorkflowTests.setUp
    tearDown=workflow.WorkflowTests.tearDown
    order=workflow.WorkflowTests.order

    def bill(self,o,**body):
        return erp.mutate('settle',{'version':o['version'],'mode':'auto',**body},'会计',o['id'])

    def test_customer_driver_factory_standard_priority_and_exact_amounts(self):
        for source,expected in [('customer','201'),('driver','204'),('factory','190'),('standard','180')]:
            with self.subTest(source=source):
                o=self.order();line=o['lines'][0];line['factory_net_kg']='190'
                if source!='customer':line['customer']=[]
                if source in ('factory','standard'):line['driver']=[]
                if source=='standard':line['factory_net_kg']=''
                o=erp.mutate('order',o,'会计',o['id'])
                o=erp.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True},'库管',o['id'])
                billed=self.bill(o)
                self.assertEqual(billed['lines'][0]['settlement_mode'],source)
                self.assertEqual(billed['lines'][0]['bill_qty'],expected)
                self.assertEqual(billed['total_cents'],erp.money(erp.Decimal(expected)*erp.Decimal('3.333')))

    def test_factory_change_invalidates_handoff_and_locks_allocation(self):
        import inventory
        o=self.order();o['lines'][0].update(customer=[],driver=[],factory_net_kg='190')
        o=erp.mutate('order',o,'会计',o['id'])
        self.assertTrue(inventory.allocation_locked(o,o['lines'][0]))
        o=erp.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True},'库管',o['id'])
        o['lines'][0]['factory_net_kg']='191'
        changed=erp.mutate('order',o,'会计',o['id'])
        self.assertIsNone(changed['weight_confirmation'])

    def test_incomplete_customer_weight_cannot_silently_fall_back(self):
        o=self.order();o['lines'][0]['customer'][0]['count']='9'
        o=erp.mutate('order',o,'会计',o['id'])
        with self.assertRaises(erp.ValidationError):self.bill(o)

    def test_standard_snapshot_survives_master_change(self):
        o=self.order();o['lines'][0].update(driver=[],customer=[])
        with erp.connect(True) as c:c.execute("INSERT OR REPLACE INTO meta VALUES('product_average_weights',?)",(json.dumps({'P001':'99'}),))
        o=erp.mutate('order',o,'会计',o['id'])
        self.assertEqual(self.bill(o)['lines'][0]['bill_qty'],'180')

    def test_pack_customer_driver_factory_and_standard_fallback(self):
        with erp.connect(True) as c:c.execute("INSERT OR REPLACE INTO meta VALUES('settlement_unit','公斤')")
        for source in ['package_customer','package_actual','factory','package_standard']:
            with self.subTest(source=source):
                o=self.order('P004');line=o['lines'][0]
                line.update(package_customer_net_kg='97',package_net_kg='98',factory_net_kg='99')
                if source!='package_customer':line['package_customer_net_kg']=''
                if source in ('factory','package_standard'):line['package_net_kg']=''
                if source=='package_standard':line['factory_net_kg']=''
                o=erp.mutate('order',o,'会计',o['id']);billed=self.bill(o)
                expected={'package_customer':'97','package_actual':'98','factory':'99','package_standard':str(10*erp.Decimal(line['standard_kg']))}[source]
                self.assertEqual(billed['lines'][0]['settlement_mode'],source)
                self.assertEqual(erp.Decimal(billed['lines'][0]['bill_qty']),erp.Decimal(expected))

    def test_invalid_factory_weights_and_unshipped_are_rejected(self):
        for value in ['-1','0','abc','1.1234']:
            o=self.order();o['lines'][0]['factory_net_kg']=value
            with self.assertRaises(erp.ValidationError):erp.mutate('order',o,'会计',o['id'])

    def test_settlement_tare_adjustment_preserves_original_weights_and_handoff(self):
        o=self.order()
        o=erp.mutate('confirm-weight',{'version':o['version'],'evidence_checked':True},'库管',o['id'])
        raw=copy.deepcopy(o['lines'][0]['customer']);handoff=copy.deepcopy(o['weight_confirmation'])
        billed=self.bill(o,tare_overrides={'P001':{'customer':'1.5'}})
        self.assertEqual(billed['lines'][0]['bill_qty'],'204')
        self.assertEqual(billed['lines'][0]['customer'],raw)
        self.assertEqual(billed['weight_confirmation'],handoff)
        self.assertEqual(billed['lines'][0]['settlement_tares'],{'customer':'1.5'})

    def test_settlement_tare_invalid_values_and_sources_are_rejected(self):
        o=self.order()
        for override in [{'customer':'-1'},{'customer':'101'},{'customer':'50'},{'customer':'1.1234'},{'factory':'1'},{'driver':'1.5'}]:
            with self.subTest(override=override),self.assertRaises(erp.ValidationError):self.bill(o,tare_overrides={'P001':override})

    def test_direct_driver_net_is_not_reduced_by_customer_tare(self):
        o=self.order();o['lines'][0].update(driver=[{'gross':'200','count':'10','tare':'0','note':'司机净重'}],customer=[])
        o=erp.mutate('order',o,'会计',o['id'])
        billed=self.bill(o)
        self.assertEqual(billed['lines'][0]['driver_net'],'200')
        self.assertEqual(billed['lines'][0]['bill_qty'],'200')
        self.assertEqual(billed['lines'][0]['driver'][0]['tare'],'0')
