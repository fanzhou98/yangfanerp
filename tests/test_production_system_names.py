"""The three built-in system names are stored in full, without text recognition."""
import copy
import json
import sqlite3
import unittest
import migration_steps


class ProductionSystemNameTests(unittest.TestCase):
    def test_explicit_names_in_directory_snapshots_and_issue_labels_preserve_business_values(self):
        c=sqlite3.connect(':memory:')
        c.execute('CREATE TABLE production_config_versions(version INTEGER PRIMARY KEY,effective_date TEXT,payload TEXT)')
        for table in ('factory_daily','material_entries'):c.execute('CREATE TABLE '+table+'(id TEXT PRIMARY KEY,payload TEXT)')
        systems=[{'id':sid,'name':name,'active':True,'soak_kg':'51.5'} for sid,name in [('tofu','旧名甲'),('skin','旧名乙'),('gel-tofu','内脂豆腐磨浆系统'),('custom','内脂豆腐实验磨浆系统')]]
        cfg={'version':3,'effective_date':'2026-10-20','systems':systems,'products':{'P001':{'system_ids':['tofu','gel-tofu']}},'processes':[{'id':'large','dry_kg':'32.5'}]}
        c.execute('INSERT INTO production_config_versions VALUES(?,?,?)',(3,'2026-10-20',json.dumps(cfg)))
        record={'id':'DAY1','business_date':'2026-10-20','version':8,'config_snapshot':copy.deepcopy(cfg),'systems':{'gel-tofu':{'soak_tanks':'3.5'}},'products':[{'product_id':'P001','system':'gel-tofu','system_name':'旧称','tanks':{'large':'2'}}]}
        c.execute('INSERT INTO factory_daily VALUES(?,?)',('DAY1',json.dumps(record)))
        entry={'id':'BEAN1','production_system_id':'gel-tofu','production_system_name':'内脂豆腐磨浆系统','department':'内脂豆腐磨浆系统','cost_target':'手工指定成本对象','qty':'50.125','amount_cents':12345,'version':6}
        c.execute('INSERT INTO material_entries VALUES(?,?)',('BEAN1',json.dumps(entry)))
        audits=[];ctx={'audit':lambda *args:audits.append(args),'now':lambda:'2026-10-24T12:00:00+08:00'}
        migration_steps.production_system_names(c,ctx)
        result=json.loads(c.execute('SELECT payload FROM production_config_versions').fetchone()[0])
        expected=['豆腐磨浆系统','豆皮磨浆系统','内脂磨浆系统','内脂豆腐实验磨浆系统']
        self.assertEqual([s['name'] for s in result['systems']],expected)
        for old,new in zip(cfg['systems'],result['systems']):old['name']=new['name']
        self.assertEqual(result,cfg)
        changed=json.loads(c.execute('SELECT payload FROM factory_daily').fetchone()[0]);record['config_snapshot']=result;record['products'][0]['system_name']='内脂磨浆系统'
        self.assertEqual(changed,record)
        changed=json.loads(c.execute('SELECT payload FROM material_entries').fetchone()[0]);entry.update(production_system_name='内脂磨浆系统',department='内脂磨浆系统')
        self.assertEqual(changed,entry)
        before=list(c.iterdump());migration_steps.production_system_names(c,ctx)
        self.assertEqual(before,list(c.iterdump()));self.assertEqual(len(audits),1)
        c.close()
