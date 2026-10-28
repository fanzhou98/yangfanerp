"""Physical crate groups: parent totals include each attribute exactly once."""
from decimal import Decimal
import resources_costs as rc
import crate_accounting,trade


def decorate(c,day,report,stock):
    assets=report['assets'];types={a['id']:a for a in assets if a['category']=='周转筐'}
    children={a['id']:[x['id'] for x in types.values() if x.get('parent_asset_id')==a['id']] for a in types.values() if not a.get('parent_asset_id')}
    roots={aid:a.get('parent_asset_id') or aid for aid,a in types.items()}
    records=rc.rows(c,'asset_records');counts={r['asset_id']:r for r in records if r['kind']=='count' and r['business_date']==day}
    splits={r['product_id']:r for r in records if r['kind']=='occupied-count' and r['business_date']==day}
    occupied={aid:Decimal(0) for aid in types};pending={aid:[] for aid in types};parent_total={aid:Decimal(0) for aid in children};parent_pending={aid:[] for aid in children};products=[]
    for p in stock:
        if p['unit']!='筐':continue
        vs=crate_accounting.variants(c,p['product_id']);ids=[v['id'] for v in vs];parents=set(roots[i] for i in ids);allowed=set(ids)|parents
        count=p['counted_qty'];split=splits.get(p['product_id']);valid=bool(split and count!='' and sum(x['qty'] for x in split['lines'])==Decimal(count) and all(x['asset_id'] in allowed for x in split['lines']))
        detail={**p,'asset_ids':ids,'count':split,'split_valid':valid,'attribute_lines':split['lines'] if valid else []};products.append(detail)
        if not ids:continue
        if count=='':
            for aid in allowed:pending[aid].append(p['product_name']+'未盘产品结存')
            for aid in parents:parent_pending[aid].append(p['product_name']+'未盘产品结存')
            continue
        qty=Decimal(count)
        if len(parents)==1:parent_total[next(iter(parents))]+=qty
        elif valid:
            for x in split['lines']:parent_total[roots[x['asset_id']]]+=Decimal(x['qty'])
        else:
            for aid in parents:parent_pending[aid].append(p['product_name']+'跨框型待拆分')
        if valid:
            for x in split['lines']:occupied[x['asset_id']]+=Decimal(x['qty'])
        elif len(ids)==1:occupied[ids[0]]+=qty
        else:
            for aid in ids:pending[aid].append(p['product_name']+'装货框待按属性拆分')
    shipped={aid:Decimal(0) for aid in types}
    orders=[o for o in rc.rows(c,'orders') if o['business_date']==day]
    for o in orders:
        for x in trade.shipped_crates(c,o):
            if x['asset_id'] in shipped:shipped[x['asset_id']]+=Decimal(str(x['qty']))
    result=[];base={r['id']:r for r in report['crates']}
    for aid,a in types.items():
        r={**base[aid],'occupied_qty':None if pending[aid] else rc.ds(occupied[aid]),'missing_products':list(dict.fromkeys(pending[aid])),'shipped_qty':rc.ds(shipped[aid])}
        # Legacy reports could infer dispatch from a product without an order record.
        if not orders and not a.get('parent_asset_id'):r['shipped_qty']=base[aid]['shipped_qty']
        result.append(r)
    lookup={r['id']:r for r in result};groups=[]
    for aid,child_ids in children.items():
        root=lookup[aid];members=[aid,*child_ids];count=counts.get(aid);issues=[]
        if not child_ids:
            root['occupied_qty']=None if parent_pending[aid] else rc.ds(parent_total[aid]);root['missing_products']=list(dict.fromkeys(parent_pending[aid]));root['total_qty']=None if root['occupied_qty'] is None or root['empty_qty'] is None else rc.ds(Decimal(root['occupied_qty'])+Decimal(root['empty_qty'])+Decimal(root['damaged_qty'] or 0));groups.append({**root,'attributes':[]});continue
        values={x['asset_id']:x for x in (count or {}).get('attribute_counts',[])}
        for cid in child_ids:
            child=lookup[cid];value=values.get(cid)
            if value:child.update(empty_qty=value['empty_qty'],damaged_qty=value['damaged_qty'])
            child['total_qty']=None if child['occupied_qty'] is None or child['empty_qty'] is None else rc.ds(Decimal(child['occupied_qty'])+Decimal(child['empty_qty'])+Decimal(child['damaged_qty'] or 0))
        root['occupied_qty']=None if parent_pending[aid] else rc.ds(parent_total[aid]);root['missing_products']=list(dict.fromkeys(parent_pending[aid]))
        for key in ('shipped_qty','returned_qty','received_qty','scrapped_qty'):
            root[key]=rc.ds(sum((Decimal(str(lookup[i][key])) for i in members),Decimal(0)))
        residual={**types[aid],'name':'未分属性 / 历史未分色','is_unclassified':True,'occupied_qty':None if root['occupied_qty'] is None else rc.ds(Decimal(root['occupied_qty'])-sum((Decimal(lookup[i]['occupied_qty'] or '0') for i in child_ids),Decimal(0))),'missing_products':list(dict.fromkeys(x for i in child_ids for x in pending[i])),'count':count}
        if count and 'attribute_counts' in count:
            residual.update(empty_qty=count.get('unclassified_empty_qty',0),damaged_qty=count.get('unclassified_damaged_qty',0))
            # Attributes added after this day's count remain explicitly unclassified.
        elif count:
            for key in ('empty_qty','damaged_qty'):
                known=sum((int(lookup[i][key] or 0) for i in child_ids))
                residual[key]=int(count[key])-known
                if residual[key]<0:issues.append('历史父框总数小于属性明细，请在父框中重新核对盘点');residual[key]=None
        else:residual.update(empty_qty=None,damaged_qty=None)
        for key in ('shipped_qty','returned_qty','received_qty','scrapped_qty'):residual[key]=rc.ds(Decimal(root[key])-sum((Decimal(str(lookup[i][key])) for i in child_ids),Decimal(0)))
        if issues:root.update(empty_qty=None,damaged_qty=None)
        elif count and 'attribute_counts' in count:
            root['empty_qty']=sum(x['empty_qty'] for x in count['attribute_counts'])+count.get('unclassified_empty_qty',0);root['damaged_qty']=sum(x['damaged_qty'] for x in count['attribute_counts'])+count.get('unclassified_damaged_qty',0)
        root['total_qty']=None if root['occupied_qty'] is None or root['empty_qty'] is None else rc.ds(Decimal(root['occupied_qty'])+Decimal(root['empty_qty'])+Decimal(root['damaged_qty'] or 0))
        residual['total_qty']=None if residual['occupied_qty'] is None or residual['empty_qty'] is None or residual['damaged_qty'] is None else rc.ds(Decimal(residual['occupied_qty'])+Decimal(residual['empty_qty'])+Decimal(residual['damaged_qty']))
        root['count_issues']=issues;groups.append({**root,'attributes':[lookup[i] for i in child_ids],'unclassified':residual})
    report.update(crates=result,crate_groups=groups,occupied_products=products,inventory_revision=__import__('inventory').revision(c))
    return report
