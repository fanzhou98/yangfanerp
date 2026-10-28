#!/usr/bin/env python3
"""Create a fresh local factory demonstration DB in a private temporary folder."""
import argparse,json,sqlite3,sys,tempfile,uuid
from datetime import date,timedelta
from decimal import Decimal
from pathlib import Path
from contextlib import closing
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
import production_management as fm
import resources_costs as rc

def create(catalog_source,day):
    date.fromisoformat(day)
    # Read product definitions only; no real staff, accounts, sessions or business rows are copied.
    with closing(sqlite3.connect('file:'+str(catalog_source.resolve())+'?mode=ro',uri=True)) as source:
        products=source.execute('SELECT id,name,unit,price,tare,standard_kg FROM products ORDER BY id').fetchall()
    required={'P001','P002','P003','P004','P005','P006'}
    if not required<={p[0] for p in products}:raise ValueError('缺少演示所需的产品定义')
    folder=Path(tempfile.mkdtemp(prefix='erp-factory-demo-'));folder.chmod(0o700)
    db=folder/'factory-demo.db';server.DB=db;server.init_db(demo=False)
    with server.connect(True) as c:
        c.executemany('INSERT INTO products VALUES(?,?,?,?,?,?)',products)
        # The fresh database has an empty directory; seed relations after copying its catalogue.
        c.execute('UPDATE production_config_versions SET payload=? WHERE version=0',(rc.dump(fm.pc.seed(c)),))
        c.executemany('INSERT INTO delivery_markets(id,name,city) VALUES(?,?,?)',[('M901','演示一市场','演示城区'),('M902','演示二市场','演示城区')])
        c.executemany('INSERT INTO delivery_vehicles(id,name) VALUES(?,?)',[('V901','演示配送一号车'),('V902','演示配送二号车')])
        c.executemany('INSERT INTO customers(id,name,route,note,region,market_id,location_kind) VALUES(?,?,?,?,?,?,?)',[
            ('C901','演示·一号店','演示一市场','虚构测试客户','演示城区','M901','market'),
            ('C902','演示·二号店','演示一市场','虚构测试客户','演示城区','M901','market'),
            ('C903','演示·三号店','演示二市场','虚构测试客户；用于展示称重核对提示','演示城区','M902','market')])
        c.execute('INSERT INTO meta VALUES(?,?)',('preview_demo',rc.dump({'business_date':day,'label':'一天完整生产示例'})))
    def factory(kind,body):
        with server.connect(True) as c:return fm.save(c,kind,{'request_key':str(uuid.uuid4()),**body},'管理员',server.now,server.audit)
    def material(kind,mid,q,amount='0',wid='WH-COMMON',**extra):
        with server.connect(True) as c:return rc.Operations(c,server.now,server.audit).material({'request_key':str(uuid.uuid4()),'revision':rc.revision(c),'material_id':mid,'warehouse_id':wid,'business_date':day,'kind':kind,'qty':q,'amount':amount,'handler':'演示经办人','note':'演示数据 · '+('测试入库' if kind=='receipt' else '当天生产领用'),**extra},'管理员')
    employees=[]
    for i,gid in enumerate(['G-SKIN']*4+['G-TOFU']*5+['G-DRY']*3,1):employees.append(factory('employee',{'name':f'演示员工{i:02}','group_id':gid,'note':'虚构人员，仅用于查看分组考勤'}))
    yesterday=(date.fromisoformat(day)-timedelta(days=1)).isoformat()
    group_times=[{'group_id':'G-SKIN','start_time':'21:30','end_time':'05:30'},{'group_id':'G-TOFU','start_time':'22:00','end_time':'06:00'},{'group_id':'G-DRY','start_time':'23:00','end_time':'07:00'}]
    prior=[{'employee_id':e['id'],'group_id':e['group_id'],'status':'full'} for e in employees]
    factory('attendance',{'format':'group-day-v2','business_date':yesterday,'state':'confirmed','groups':group_times,'entries':prior,'note':'演示数据 · 仅作昨天排班对照'})
    current=[dict(e) for e in prior];current[0]['group_id']='G-TOFU';current[4]['group_id']='G-SKIN';current[2]['status']='half';current[7]['status']='leave';current[11]['status']='absent'
    group_times[0]['start_time']='21:00'
    attendance=factory('attendance',{'format':'group-day-v2','business_date':day,'state':'confirmed','groups':group_times,'entries':current,'note':'演示数据 · 调组、半天、请假与缺勤示例'})
    for i,(wid,q,price,protein,moisture) in enumerate([
        ('WH-TOFU','2000','4.8','40.5','11.8'),('WH-TOFU','1000','5','41.5','12.2'),
        ('WH-SKIN','1500','4.7','39.5','12.5'),('WH-SKIN','1000','4.9','40.8','11.9'),
        ('WH-EXTERNAL','3000','4.85','40.6','11.6'),('WH-MAIN','5000','5.1','42','12.2'),('WH-MAIN','1000','4.8','','')],1):
        material('receipt','RM-SOY',q,rc.ds(Decimal(q)*Decimal(price)),wid,quality={'batch_no':f'演示黄豆{i:02}','protein_pct':protein,'soluble_protein_pct':'8' if protein else '', 'moisture_pct':moisture,'test_note':'虚构检测数据，用于图表展示'})
    for mid,q,cost in [('A-GYPSUM','25','50'),('A-DEFOAMER','10','80'),('A-SALT','50','100'),('P-BAG','1000','300'),('P-CLOTH','100','500')]:material('receipt',mid,q,cost)
    for mid,q,wid,department in [('RM-SOY','1000','WH-TOFU','豆腐线'),('RM-SOY','500','WH-SKIN','豆皮线'),('A-GYPSUM','3','WH-COMMON','豆腐线'),('A-DEFOAMER','.4','WH-COMMON','豆腐线'),('A-DEFOAMER','.3','WH-COMMON','豆皮线'),('A-SALT','4','WH-COMMON','豆腐线'),('P-BAG','180','WH-COMMON','豆皮线'),('P-CLOTH','2','WH-COMMON','豆腐线')]:
        material('consume',mid,q,wid=wid,department=department)
    tanks={'P001':('10','0','0'),'P002':('0','10','0'),'P003':('3','0','0'),'P004':('0','0','12'),'P005':('0','3','0'),'P006':('1.5','0','0')}
    factory('daily',{'business_date':day,'systems':{'tofu':{'soak_tanks':'2'},'skin':{'soak_tanks':'1'}},'products':[{'product_id':pid,'system':'skin' if pid=='P004' else 'tofu','large_tanks':tanks.get(pid,('0','0','0'))[0],'small_tanks':tanks.get(pid,('0','0','0'))[1],'skin_tanks':tanks.get(pid,('0','0','0'))[2]} for pid,*_ in products],'note':'演示数据 · 两台磨浆系统同时生产；豆皮浆缸和豆干产出换算尚未确认，保留待补提示'})
    factory('scrap',{'format':'note-v2','business_date':day,'kg':'30','product_id':'P005','note':'演示数据 · 当天30kg烂豆皮用于素鸡；只记录用途'})
    opening={'P001':8,'P002':10,'P003':4,'P004':12,'P005':8,'P006':3}
    output={'P001':40,'P002':100,'P003':16,'P004':180,'P005':30,'P006':10}
    stock=[{'product_id':p[0],'existing_qty':str(opening.get(p[0],0)),'produced_qty':str(output.get(p[0],0))} for p in products]
    plan=server.save_warehouse({'business_date':day,'version':0,'stock':stock,'allocations':[],'customers':[],'order_versions':{}},'管理员')
    all_orders=[];pmap={p[0]:p for p in products}
    quantities=[('C901',[10,25,5,50,10,4]),('C902',[12,30,6,60,10,4]),('C903',[8,20,3,35,6,2])]
    unit_weights={'P001':Decimal('22'),'P002':Decimal('12'),'P003':Decimal('20'),'P006':Decimal('20')}
    for cid,qs in quantities:
        lines=[]
        for pid,q in zip(('P001','P002','P003','P004','P005','P006'),qs):
            _,name,unit,price,tare,standard=pmap[pid];driver=[];customer=[]
            if unit=='筐':
                t=Decimal(tare);kg=unit_weights[pid];ckg=Decimal('18') if cid=='C903' and pid=='P001' else kg-Decimal('.1')
                driver=[{'gross':rc.ds((kg+t)*q),'count':str(q),'tare':tare}];customer=[{'gross':rc.ds((ckg+t)*q),'count':str(q),'tare':tare}]
            lines.append({'product_id':pid,'ordered_qty':str(q),'actual_qty':str(q),'price':price,'driver':driver,'customer':customer})
        all_orders.append(server.mutate('order',{'customer_id':cid,'business_date':day,'batch':'演示配送','note':'演示数据 · 虚构配送订单','lines':lines},'管理员'))
    plan=server.save_warehouse({'business_date':day,'version':plan['version'],'stage':'confirm_dispatch','evidence_checked':True,'stock':stock,'allocations':[{'order_id':o['id'],'product_id':l['product_id'],'qty':l['actual_qty'],'mode':'manual'} for o in all_orders for l in o['lines']],'customers':[],'order_versions':{o['id']:o['version'] for o in all_orders}},'管理员')['plan']
    server.save_dispatch({'business_date':day,'version':0,'trips':[{'id':'DEMO-T1','name':'演示第一趟','period':'05:00','vehicle_id':'V901','driver':'演示司机甲'},{'id':'DEMO-T2','name':'演示第二趟','period':'06:00','vehicle_id':'V902','driver':'演示司机乙'}],'assignments':[{'market_id':'M901','trip_id':'DEMO-T1','sequence':1},{'market_id':'M902','trip_id':'DEMO-T2','sequence':1}]},'管理员')
    for o in all_orders[:2]:
        o=server.mutate('settle',{'version':o['version'],'mode':'customer','reason':'演示数据 · 已核对客户复称'},'管理员',o['id']);o=server.mutate('review',{'version':o['version'],'evidence_checked':True},'管理员',o['id'])
    server.mutate('receipt',{'version':o['version'],'amount':'3000','received_date':day,'method':'银行转账','note':'演示数据 · 虚构到账'},'管理员',o['id'])
    with server.connect(True) as c:
        snap=server.inventory.stock(c,day)
        server.inventory.Operations(c,server.now,server.audit).close({'business_date':day,'version':0,'plan_version':plan['version'],'inventory_revision':server.inventory.revision(c),'evidence_checked':True,'counts':[{'product_id':p['product_id'],'counted_qty':p['book_qty'],'reason':''} for p in snap['products']]},'管理员')
        report=fm.daily_report(c,day)
        assert next(p for p in report['products'] if p['product_id']=='P001')['derived_qty']=='40'
        assert next(p for p in report['products'] if p['product_id']=='P004')['yield_with_scrap']=='3.66'
        assert c.execute('PRAGMA foreign_key_check').fetchone() is None
    db.chmod(0o600)
    result={'database':str(db),'business_date':day,'employees':len(employees),'orders':len(all_orders),'tofu_issued_kg':'1000','skin_issued_kg':'500','skin_yield':'3.6','skin_yield_with_scrap':'3.66','attendance_notice':attendance['notice'],'source_business_rows_copied':False,'source_accounts_copied':False}
    (folder/'demo.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--catalog-source',type=Path,required=True);parser.add_argument('--date',required=True)
    args=parser.parse_args();result=create(args.catalog_source,args.date);print(json.dumps({k:v for k,v in result.items() if k!='attendance_notice'},ensure_ascii=False))
