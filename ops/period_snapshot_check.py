#!/usr/bin/env python3
"""Read-only impact report for the v0.60.1 frozen-period status correction."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

WARNING={'field':'成本月份未结账，费用可能未录全','owner':'会计','target':'expenses'}


def inspect_database(path):
    result=[]
    with closing(sqlite3.connect(path.expanduser().resolve().as_uri()+'?mode=ro',uri=True)) as c:
        c.execute('PRAGMA query_only=ON')
        for month,version,raw in c.execute('SELECT month,version,payload FROM resource_periods ORDER BY month'):
            period=json.loads(raw)
            if period.get('state')!='closed':continue
            snapshot=period.get('report_snapshot')
            valid=isinstance(snapshot,dict) and period.get('month')==month and snapshot.get('month')==month and isinstance(snapshot.get('gaps'),list)
            candidate=valid and WARNING in snapshot['gaps']
            status='待修正状态提示' if candidate else '无需修正' if valid else '缺快照或结构需人工核查'
            digest=hashlib.sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest() if isinstance(snapshot,dict) else None
            result.append({'month':month,'version':version,'status':status,'snapshot_sha256':digest,
                           'status_revision':period.get('snapshot_status_revision')})
    return {'read_only':True,'closed_periods':len(result),
            'affected_count':sum(r['status']=='待修正状态提示' for r in result),
            'manual_review_count':sum(r['status']=='缺快照或结构需人工核查' for r in result),'periods':result}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps({'ok':True,**inspect_database(args.database)},ensure_ascii=False,indent=2))
        return 0
    except (OSError,sqlite3.Error,ValueError,TypeError,AttributeError):
        print(json.dumps({'ok':False,'error':'无法只读检查月结快照，请核对路径及数据库结构'},ensure_ascii=False))
        return 1


if __name__=='__main__':
    raise SystemExit(main())
