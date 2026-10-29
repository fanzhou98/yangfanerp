#!/usr/bin/env python3
"""Allowlist-only release: no database, screenshots, logs, accounts or caches."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('server.py', 'cloud_app.py', 'auth.py', 'erp_access.py', 'billing.py', 'finance_query.py', 'resource_query.py', 'expense_query.py', 'expense_coverage.py', 'expense_estimates.py', 'expense_close.py', 'expense_recognition.py', 'byproduct_accounts.py', 'funds.py', 'cash_query.py', 'sales_chain.py', 'sales_query.py',
           'trade.py', 'crate_accounting.py', 'crate_packaging.py', 'accounting_entry.py', 'transport_closure.py', 'crate_inventory.py', 'business_reset.py', 'finished_goods.py', 'finished_goods_query.py', 'gel_tofu.py', 'order_corrections.py', 'billing_migration.py', 'migrations.py', 'migration_steps.py', 'inventory.py', 'inventory_query.py', 'stock_history.py', 'open_stock_query.py', 'delivery_query.py', 'check_history.py', 'material_query.py', 'inventory_reconciliation.py', 'printing.py', 'statements.py',
           'resources_costs.py', 'production_management.py', 'production_daily.py', 'production_config.py', 'material_allocation.py', 'owner_analysis.py', 'reporting.py', 'report_directory.py', 'metric_dictionary.py', 'cost_allocation.py', 'expense_parties.py', 'personnel.py', 'attendance_query.py', 'payroll_query.py', 'social_policy.py', 'payroll.py', 'employee_banks.py', 'company.py', 'product_profit.py', 'assets.py', 'driver_portal.py', 'purchasing.py', 'purchase_query.py', 'collaboration.py', 'audit_query.py', 'audit_rollback.py', 'receipt_ocr.py', 'requirements-cloud.txt', 'VERSION')
OPS = ('__init__.py', 'build_release.py', 'migrate.py', 'erp_ops.py', 'business_check.py', 'period_snapshot_check.py', 'initialize_cloud.py',
       'install_cloud.sh', 'upgrade_cloud.sh', 'cloud_status.sh')


def release_files(root=ROOT):
    paths = [Path(name) for name in MODULES]
    paths += [Path('ops') / name for name in OPS]
    paths += sorted(p.relative_to(root) for p in (root / 'web').iterdir()
                    if p.suffix in ('.js', '.css', '.html', '.png', '.ico', '.svg', '.webmanifest') and p.is_file())
    paths += sorted(p.relative_to(root) for p in (root / 'ops' / 'cloud').glob('*')
                    if p.is_file() and not p.name.startswith('.'))
    for path in paths:
        if (root / path).is_symlink() or not (root / path).is_file():
            raise ValueError(f'发布文件不存在或是符号链接: {path}')
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'output' / 'releases')
    args = parser.parse_args()
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('版本格式无效')
    files = release_files()
    manifest = {'version': version, 'data_included': False, 'files': {
        str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}}
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / f'yangfan-erp-{version}.tar.gz'
    # Exclusive creation prevents silently replacing an already-reviewed release.
    with target.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for path in files:
            info = archive.gettarinfo(str(ROOT / path), arcname=str(path))
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            info.mode = 0o755 if path.suffix == '.sh' else 0o644
            with (ROOT / path).open('rb') as source:
                archive.addfile(info, source)
        raw = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
        info = tarfile.TarInfo('release.json')
        info.size = len(raw)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(raw))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + '.sha256').write_text(f'{digest}  {target.name}\n')
    print(json.dumps({'archive': str(target), 'sha256': digest, 'files': len(files), 'data_included': False}))


if __name__ == '__main__':
    main()
