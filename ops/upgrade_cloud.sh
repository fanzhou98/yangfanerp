#!/usr/bin/env bash
# Run from an unpacked NEW release. All customer data stays outside release dirs.
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请使用 sudo 运行'; exit 1; }
keep_maintenance=false
if [[ ${1:-} == --keep-maintenance && $# == 1 ]]; then
    keep_maintenance=true
elif [[ $# != 0 ]]; then
    echo '用法: sudo bash ops/upgrade_cloud.sh [--keep-maintenance]'; exit 1
fi
exec 9>/run/yangfan-erp-upgrade.lock
flock -n 9 || { echo '另一次升级尚未完成'; exit 1; }
source_dir=$(cd "$(dirname "$0")/.." && pwd)
previous=$(readlink -f /srv/yangfan-erp/current)
data_dir=/var/lib/yangfan-erp
[[ -f "$data_dir/erp.db" && -d "$previous" ]] || exit 1
release_dir=$(python3 "$source_dir/ops/cloud/prepare_release.py" "$source_dir" /srv/yangfan-erp/releases)
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/pip" install --disable-pip-version-check -r "$release_dir/requirements-cloud.txt"
candidate="$data_dir/upgrade-$(date -u +%Y%m%dT%H%M%SZ)-$$.db"
# A failure leaves the maintenance gate closed. It never silently reopens writes
# or restores an old DB after new business might have been committed.
trap 'echo "升级中止。维护入口保持关闭。旧版本: $previous；候选库: $candidate。核对备份后恢复。" >&2' ERR
touch /run/yangfan-erp-maintenance
systemctl stop yangfan-erp-backup.timer
systemctl stop yangfan-erp-backup.service
systemctl stop yangfan-erp.service
runuser -u yangfan-erp -- python3 "$previous/ops/erp_ops.py" backup --database "$data_dir/erp.db" --destination "$data_dir/backups"
runuser -u yangfan-erp -- python3 - "$data_dir/erp.db" "$candidate" <<'PY'
from pathlib import Path
import sqlite3, sys
source, target = map(Path, sys.argv[1:])
if target.exists(): raise RuntimeError('候选文件已存在')
with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
target.chmod(0o600)
PY
runuser -u yangfan-erp -- python3 "$release_dir/ops/initialize_cloud.py" --database "$candidate"
runuser -u yangfan-erp -- python3 "$release_dir/ops/erp_ops.py" check-db --database "$candidate" --full
runuser -u yangfan-erp -- python3 "$release_dir/ops/business_check.py" --database "$candidate"
# Clean checkpoint before moving the stopped DB; never leave WAL sidecars paired
# with a different main file. Refuse unusual modes rather than deleting sidecars.
runuser -u yangfan-erp -- python3 - "$data_dir/erp.db" <<'PY'
import sqlite3, sys
with sqlite3.connect(sys.argv[1]) as c:
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    if c.execute('PRAGMA journal_mode=DELETE').fetchone()[0] != 'delete':
        raise RuntimeError('无法安全切换日志模式')
PY
mv "$data_dir/erp.db" "$candidate.before.db"
mv "$candidate" "$data_dir/erp.db"
ln -s "$release_dir" /srv/yangfan-erp/current.next
mv -Tf /srv/yangfan-erp/current.next /srv/yangfan-erp/current
systemctl start yangfan-erp.service
for attempt in {1..15}; do
    if curl --fail --silent http://127.0.0.1:8765/api/health >/dev/null; then break; fi
    sleep 1
done
runuser -u yangfan-erp -- python3 "$release_dir/ops/erp_ops.py" health
systemctl enable --now yangfan-erp-backup.timer
if [[ $keep_maintenance == false ]]; then
    rm /run/yangfan-erp-maintenance
fi
trap - ERR
# Routine housekeeping on every successful upgrade: keep the running and previous
# release, the latest candidate databases, and recent backups only.
current=$(readlink -f /srv/yangfan-erp/current)
for dir in /srv/yangfan-erp/releases/*; do
    [[ -d $dir ]] || continue
    resolved=$(readlink -f "$dir")
    [[ $resolved == "$current" || $resolved == "$previous" ]] && continue
    rm -rf "$dir"
done
ls -1t /var/lib/yangfan-erp/upgrade-*.db.before.db 2>/dev/null | tail -n +3 | xargs -r rm -f || true
find /root -maxdepth 1 -type d -name 'yangfan-erp-*' ! -path "$source_dir" -exec rm -rf {} + 2>/dev/null || true
rm -rf /root/.cache/pip 2>/dev/null || true
newest_db=$(ls -1t /var/lib/yangfan-erp/backups/*.db 2>/dev/null | head -n1) || newest_db=''
newest_manifest=$(ls -1t /var/lib/yangfan-erp/backups/*.db.manifest.json 2>/dev/null | head -n1) || newest_manifest=''
if [[ -n $newest_db ]]; then
    find /var/lib/yangfan-erp/backups -maxdepth 1 -name 'erp-*.db' -mtime +14 ! -name "$(basename "$newest_db")" -delete 2>/dev/null || true
fi
if [[ -n $newest_manifest ]]; then
    find /var/lib/yangfan-erp/backups -maxdepth 1 -name 'erp-*.db.manifest.json' -mtime +14 ! -name "$(basename "$newest_manifest")" -delete 2>/dev/null || true
fi
find /srv/yangfan-erp/releases -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo '例行清理：保留当前与上一版本程序、最近两周备份；清理旧版本、旧候选库与安装缓存。'
echo "升级成功；旧程序保留于 $previous，升级前数据库保留于 $candidate.before.db，另有校验备份。"
if [[ $keep_maintenance == true ]]; then
    echo '按要求保留维护入口；本次仅更新程序，不开放公网业务访问。'
fi
