"""Small isolated fixture for shortage/dispatch confirmation browser checks."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
path=Path(sys.argv[1]).resolve()
if path==server.DB.resolve() or not path.name.startswith('navigation-test-'):raise SystemExit('Use a dedicated navigation-test-*.db file')
server.DB=path;server.init_db()
with server.connect(True) as c:
    c.execute('DELETE FROM orders');c.execute('DELETE FROM receipts')
for cid in ['C001','C002']:
    server.mutate('order',{'dispatch_required':True,'workflow_version':1,'customer_id':cid,'business_date':'2026-10-22','batch':'预分配验证','lines':[{'product_id':pid,'ordered_qty':qty,'actual_qty':'0','price':price,'driver':[],'customer':[]} for pid,qty,price in [('P001','8','3'),('P004','2','75')]]},'库管')
