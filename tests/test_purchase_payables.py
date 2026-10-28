"""Goods payable SQL pages keep received/paid/outstanding and earliest-due overdue semantics."""
import unittest
from datetime import datetime as RealDatetime
from unittest.mock import patch
import test_purchasing as fixture
import resources_costs as rc,purchasing as p,purchase_query as q

TODAY='2026-12-31'

class FrozenDatetime:
    @classmethod
    def now(cls,tz=None):return RealDatetime.fromisoformat(TODAY).replace(tzinfo=tz)

def reference(c):
    proj=p.projection(c);orders=[o for o in proj['orders'] if o['received_cents']>0];payments=proj['payments']
    overdue={}
    for o in orders:
        paid=sum(x['amount_cents'] for x in payments if x['order_id']==o['id'] and not x.get('charge_id'))
        for receipt in sorted([r for r in proj['receipts'] if r['order_id']==o['id']],key=lambda r:(r['due_date'],r['id'])):
            applied=min(paid,receipt['amount_cents']);paid-=applied;left=receipt['amount_cents']-applied
            if left>0 and receipt['due_date']<TODAY:overdue[o['id']]=overdue.get(o['id'],0)+left
    for o in orders:o['overdue_cents']=overdue.get(o['id'],0)
    return list(reversed(orders))

def matches(o,month='',supplier='',search='',status=''):
    text=' '.join([o['id'],o.get('order_id',''),o.get('supplier_name',''),o.get('payee_name','')]+[l.get('material_name','') for l in o.get('lines',[])]).lower()
    if month and not o['business_date'].startswith(month):return False
    if supplier and o['supplier_id']!=supplier:return False
    if search and search.lower() not in text:return False
    if status=='未付清' and not o['outstanding_cents']>0:return False
    if status=='已付清' and o['outstanding_cents']!=0:return False
    if status=='已逾期' and not o['overdue_cents']>0:return False
    return True

class PurchasePayablesTests(unittest.TestCase):
    def setUp(self):
        fixture.PurchasingTests.setUp(self);self.clock=patch.object(q,'datetime',FrozenDatetime);self.clock.start();self.addCleanup(self.clock.stop)
    tearDown=fixture.PurchasingTests.tearDown
    def put(self,table,row):self.c.execute('INSERT INTO '+table+' VALUES(?,?,?)',(row['id'],row['id'],rc.dump(row)))
    def seed(self,n=95):
        for i in range(n):
            oid=f'PB{i:03d}';day=f'2026-{9+i%3:02d}-{1+i%9:02d}'
            name='特殊供应商' if i==8 else '分页供应商'
            order={'id':oid,'version':1,'business_date':day,'expected_date':'2026-12-01','supplier_id':self.s['id'],'supplier_name':name,'state':'confirmed','total_cents':1000,
              'lines':[{'id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':'10','price':'100','amount_cents':1000}]}
            self.put('purchase_orders',order)
            if i%7==0:continue
            if i%5==0:
                parts=[('400','2026-10-01'),('600','2026-11-15')]
            else:
                parts=[('1000',f'2026-{10+i%2:02d}-{1+i%20:02d}' if i%11 else '2027-02-01')]
            for j,(amount,due) in enumerate(parts):
                self.put('purchase_receipts',{'id':f'PR{i:03d}-{j}','order_id':oid,'business_date':'2026-10-05','supplier_id':self.s['id'],'supplier_name':name,'due_date':due,'amount_cents':int(amount),
                  'lines':[{'line_id':'L1','material_id':'RM-SOY','material_name':'黄豆','warehouse_id':'WH-TOFU','unit':'公斤','qty':str(int(amount)//100),'amount_cents':int(amount),'material_entry_id':f'ME{i:03d}-{j}'}]})
            if i%3==0:self.put('purchase_payments',{'id':f'PG{i:03d}','order_id':oid,'supplier_id':self.s['id'],'supplier_name':name,'business_date':'2026-12-01','amount_cents':500})
            if i%4==0:self.put('purchase_payments',{'id':f'PGX{i:03d}','order_id':oid,'supplier_id':self.s['id'],'supplier_name':name,'business_date':'2026-12-02','amount_cents':500 if i%12==0 else 1000})
            if i%5==0:
                self.put('purchase_charges',{'id':f'PC{i:03d}','order_id':oid,'receipt_id':f'PR{i:03d}-0','business_date':'2026-11-01','due_date':'2026-11-30','kind':'freight','supplier_id':'TRANSPORT-PAYEE','supplier_name':'运输收款方','payee_name':'测试承运人','amount_cents':100,'allocations':[{'material_entry_id':f'ME{i:03d}-0','amount_cents':100}]})
                self.put('purchase_payments',{'id':f'PCT{i:03d}','charge_id':f'PC{i:03d}','order_id':oid,'supplier_id':'TRANSPORT-PAYEE','supplier_name':'运输收款方','payee_name':'测试承运人','business_date':'2026-12-03','amount_cents':100})
    def test_filters_summary_and_order_match_full_projection(self):
        self.seed();baseline=reference(self.c)
        total=len(baseline);self.assertEqual(q.payables(self.c)['total'],total)
        for month,supplier,search,status in [('', '', '', ''),('2026-10','','',''),('','','特殊',''),('','','黄豆','未付清'),('','','', '已付清'),('2026-09','','','已逾期')]:
            expected=[o for o in baseline if matches(o,month,supplier,search,status)]
            got=q.payables(self.c,month=month,supplier_id=supplier,search=search,status=status,page_size=200)
            self.assertEqual([o['id'] for o in got['rows']],[o['id'] for o in expected],(month,search,status))
            self.assertEqual(got['total'],len(expected));self.assertEqual(got['summary']['received_cents'],sum(o['received_cents'] for o in expected))
            self.assertEqual(got['summary']['paid_cents'],sum(o['paid_cents'] for o in expected))
            self.assertEqual(got['summary']['outstanding_cents'],sum(o['outstanding_cents'] for o in expected))
            self.assertEqual(got['summary']['overdue_cents'],sum(o['overdue_cents'] for o in expected))
        paid=q.payables(self.c,status='已付清',page_size=200)
        self.assertTrue(paid['rows']);self.assertTrue(all(o['outstanding_cents']==0 for o in paid['rows']))
        overdue=q.payables(self.c,status='已逾期',page_size=200)
        self.assertTrue(overdue['rows']);self.assertTrue(all(o['overdue_cents']>0 for o in overdue['rows']))
    def test_pages_are_stable_and_do_not_read_full_tables(self):
        self.seed();expected=[o['id'] for o in reference(self.c)]
        seen=[];first=None
        for page in range(1,8):
            result=q.payables(self.c,page=page,page_size=13);seen+= [o['id'] for o in result['rows']]
            first=first or result['summary'];self.assertEqual(result['summary'],first)
        self.assertEqual(seen,expected)
        original=rc.rows
        def guarded(c,table):
            self.assertNotIn(table,('purchase_orders','purchase_receipts','purchase_payments','purchase_charges'));return original(c,table)
        with patch.object(rc,'rows',guarded):q.payables(self.c,page=2,page_size=13)
        self.assertEqual(q.payables(self.c,page=9999,page_size=13)['page'],q.payables(self.c,page=1,page_size=13)['pages'])
    def test_overdue_uses_earliest_due_receipts_and_ignores_fee_payments(self):
        self.seed()
        row=next(o for o in reference(self.c) if o['id']=='PB001')
        self.assertEqual((row['received_cents'],row['paid_cents'],row['overdue_cents']),(1000,0,1000))
        row=next(o for o in reference(self.c) if o['id']=='PB005')
        self.assertEqual((row['received_cents'],row['paid_cents'],row['overdue_cents']),(1000,0,1000))
        row=next(o for o in reference(self.c) if o['id']=='PB015')
        self.assertEqual((row['received_cents'],row['paid_cents'],row['overdue_cents']),(1000,500,500))
        got=next(o for o in q.payables(self.c,page_size=200)['rows'] if o['id']=='PB015')
        self.assertEqual(got['overdue_cents'],500)
    def test_parameters_and_read_only(self):
        self.seed();before=self.c.total_changes
        for args in ({'month':'2026-13'},{'month':'2026-1'},{'status':'坏状态'},{'page':0},{'page_size':201}):
            with self.subTest(args=args),self.assertRaises(ValueError):q.payables(self.c,**args)
        self.assertEqual(self.c.total_changes,before)
