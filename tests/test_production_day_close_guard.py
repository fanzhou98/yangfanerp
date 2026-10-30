import json,unittest,tempfile,uuid
from pathlib import Path
import test_workflow as fixture
import production_management as fm
import inventory

erp=fixture.erp

class ProductionDayCloseGuardTests(unittest.TestCase):
    def setUp(self):
        self.old=erp.DB;self.temp=tempfile.TemporaryDirectory();erp.DB=Path(self.temp.name)/'close-guard.db';erp.init_db()
    def tearDown(self):erp.DB=self.old;self.temp.cleanup()
    def close_day(self,day):
        with erp.connect(True) as c:
            payload={'business_date':day,'state':'closed','version':1,'products':[],'stock':[],'allocations':[],'customers':[],'closing_date':day}
            c.execute("INSERT OR REPLACE INTO stock_closings(business_date,payload) VALUES(?,?)",(day,json.dumps(payload,ensure_ascii=False)))
    def save(self,kind,body):
        with erp.connect(True) as c:return fm.save(c,kind,{'request_key':str(uuid.uuid4()),**body},'厂长',erp.now,erp.audit)
    def test_scrap_on_closed_day_is_rejected(self):
        self.close_day('2026-10-20')
        with self.assertRaises(ValueError) as caught:
            self.save('scrap',{'business_date':'2026-10-20','format':'note-v2','kg':'3','note':'日结后补登'})
        self.assertIn('日结',str(caught.exception))
    def test_open_day_still_accepts_scrap(self):
        self.close_day('2026-10-20')
        record=self.save('scrap',{'business_date':'2026-10-21','format':'note-v2','kg':'3','note':'日结次日登记'})
        self.assertEqual(record['business_date'],'2026-10-21')
    def test_moving_record_out_of_closed_day_is_rejected(self):
        self.close_day('2026-10-20')
        record=self.save('scrap',{'business_date':'2026-10-21','format':'note-v2','kg':'2','note':'先登记'})
        with self.assertRaises(ValueError):
            self.save('scrap',{'id':record['id'],'version':record['version'],'business_date':'2026-10-20','format':'note-v2','kg':'2','note':'再挪回日结日'})

if __name__=='__main__':unittest.main()
