"""Synthetic complete factory day for dashboard browser tests; no real business data."""
import sys,json,uuid,time,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import server,auth,resources_costs as rc
from ops.create_factory_demo import create
out=Path(sys.argv[1]);catalog=out.with_name('test-catalog.db');server.DB=catalog;server.init_db()
r=create(catalog,'2026-10-20');source=Path(r['database']);shutil.copyfile(source,out);shutil.rmtree(source.parent);catalog.unlink()
server.DB=out;server.init_db()
with server.connect(True) as c:
 c.execute("DELETE FROM meta WHERE key='preview_demo'")
 admin=auth.create_initial_admin(c,'admin','测试管理员','Dashboard-Test-2026!',int(time.time()))
 users={}
 for username,role in [('warehouse','库管'),('accountant','会计'),('cashier','出纳'),('owner','老板'),('director','厂长'),('logistics','物流负责人'),('driver','司机')]:
  users[username]=auth.create_user(c,admin,{'username':username,'display_name':'测试'+role,'role':role,'password':'Dashboard-Test-2026!'},int(time.time()))
 c.execute('UPDATE auth_users SET must_change_password=0')
 for entry in rc.rows(c,'material_entries'):
  if entry['material_id']=='RM-SOY' and entry['kind'] in ('receipt','opening'):
   entry.setdefault('quality',{}).update(origin='伊犁' if entry['warehouse_id']=='WH-TOFU' else '东北',sowing_type='春播' if entry['warehouse_id']=='WH-TOFU' else '复播')
   c.execute('UPDATE material_entries SET payload=? WHERE id=?',(rc.dump(entry),entry['id']))
 import cost_allocation as ca
 for category in ca.categories(c):
  if not category['manual_entry']:continue
  rc.Operations(c,server.now,server.audit).expense({'request_key':str(uuid.uuid4()),'business_date':'2026-10-20','period':'2026-10','category':category['id'],'amount':'310','handler':'测试','note':category['name']+'演示费用'},'管理员')
 plan=rc.rows(c,'dispatch_plans')[0];plan['trips'][0].update(driver_ids=[users['driver']['driver_id']],driver_id=users['driver']['driver_id'])
 c.execute('UPDATE dispatch_plans SET payload=? WHERE business_date=?',(rc.dump(plan),plan['business_date']))
