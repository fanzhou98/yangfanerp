"""Isolated fixture for browser_navigation.js. Never use the business database."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
path=Path(sys.argv[1]).resolve()
if path==server.DB.resolve() or not path.name.startswith('navigation-test-'):
    raise SystemExit('Browser fixtures require a dedicated navigation-test-*.db file')
server.DB=path
server.init_db()
data=server.bootstrap()
for index in range(36):
    market=data['delivery_markets'][[0,3,1,4,2,5][index%6]]
    customer=server.master({'kind':'customer','name':f'跳转测试客户{index:02}','region':market['city'],'market_id':market['id'],'location_kind':'market','delivery_method':'delivery'},'会计')
    server.mutate('order',{'customer_id':customer['id'],'business_date':'2026-10-22','batch':'日常订货','lines':[{'product_id':p['id'],'ordered_qty':'2','actual_qty':'0','price':p['price'],'driver':[],'customer':[]} for p in data['products']]},'库管')
