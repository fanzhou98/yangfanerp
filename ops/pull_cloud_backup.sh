#!/bin/bash
# 每日把云端最新一致性备份拉回本机并校验；本机保留 14 天。不改云端。
set -euo pipefail
PROFILE="${WORKBENCH_PROFILE:-default}"
INSTANCE="${ERP_INSTANCE:-i-2vcgck7stwnl1b8xt14m}"
REGION="${ERP_REGION:-cn-chengdu}"
DEST="${ERP_BACKUP_DIR:-$HOME/Documents/ERP云端备份}"
LOG="${ERP_PULL_LOG:-/tmp/erp-pull-cloud.log}"
mkdir -p "$DEST"
exec >>"$LOG" 2>&1
echo "[$(date '+%F %T')] pull start"
remote=$(workbench exec -P "$PROFILE" -i "$INSTANCE" -r "$REGION" -u root --timeout 300 \
  --command "ls -t /var/lib/yangfan-erp/backups/erp-*.db | head -1" 2>/dev/null | tr -d '\r' | grep -oE 'erp-[^/]+\.db' | tail -1)
[ -n "$remote" ] || { echo "no remote backup found"; exit 1; }
workbench download "/var/lib/yangfan-erp/backups/$remote" "$DEST/$remote" -P "$PROFILE" -i "$INSTANCE" -r "$REGION" --user-name root -f >/dev/null
workbench download "/var/lib/yangfan-erp/backups/$remote.manifest.json" "$DEST/$remote.manifest.json" -P "$PROFILE" -i "$INSTANCE" -r "$REGION" --user-name root -f >/dev/null
python3 - "$DEST/$remote" <<'PY'
import hashlib, json, sys
p = sys.argv[1]
expect = json.load(open(p + '.manifest.json'))['sha256']
got = hashlib.sha256(open(p, 'rb').read()).hexdigest()
print('sha256', 'ok' if got == expect else 'MISMATCH', got)
raise SystemExit(0 if got == expect else 1)
PY
BUCKET="${ERP_OSS_BUCKET:-yangfan-erp-backup}"
ALIYUN="${ALIYUN_BIN:-$HOME/.local/bin/aliyun}"
if [ -x "$ALIYUN" ]; then
  prefix="erp/$(date -u +%Y-%m-%d)"
  "$ALIYUN" ossutil cp "$DEST/$remote" "oss://$BUCKET/$prefix/$remote" --profile "${ERP_OSS_PROFILE:-erp-oss}" -f >/dev/null
  "$ALIYUN" ossutil cp "$DEST/$remote.manifest.json" "oss://$BUCKET/$prefix/$remote.manifest.json" --profile "${ERP_OSS_PROFILE:-erp-oss}" -f >/dev/null
  echo "[$(date '+%F %T')] oss ok: oss://$BUCKET/$prefix/$remote"
fi
find "$DEST" -maxdepth 1 -name 'erp-*.db' -mtime +14 -print -delete
find "$DEST" -maxdepth 1 -name 'erp-*.db.manifest.json' -mtime +14 -print -delete
echo "[$(date '+%F %T')] pull ok: $remote"
