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
mkdir -p "$DEST/.media-objects"
chmod 700 "$DEST" "$DEST/.media-objects"
media_list=$(mktemp /tmp/erp-backup-media.XXXXXX)
trap 'rm -f "$media_list"' EXIT
python3 - "$DEST/$remote.manifest.json" >"$media_list" <<'PY'
import json,re,sys
m=json.load(open(sys.argv[1])).get('media') or {}
for digest in sorted({v['sha256'] for v in m.get('files',{}).values()}):
    if not re.fullmatch('[a-f0-9]{64}',digest):raise SystemExit('invalid media checksum')
    print(digest)
PY
while IFS= read -r digest; do
  if [ ! -f "$DEST/.media-objects/$digest" ] || ! python3 - "$DEST/.media-objects/$digest" "$digest" <<'PY'
import hashlib,sys
with open(sys.argv[1],'rb') as f:
    h=hashlib.file_digest(f,'sha256') if hasattr(hashlib,'file_digest') else hashlib.sha256(f.read())
raise SystemExit(h.hexdigest()!=sys.argv[2])
PY
  then
    workbench download "/var/lib/yangfan-erp/backups/.media-objects/$digest" "$DEST/.media-objects/$digest" -P "$PROFILE" -i "$INSTANCE" -r "$REGION" --user-name root -f >/dev/null
  fi
  chmod 600 "$DEST/.media-objects/$digest"
done <"$media_list"
python3 - "$DEST/$remote" <<'PY'
import hashlib, json, sys
from pathlib import Path
p = sys.argv[1]
manifest=json.load(open(p + '.manifest.json'))
for item in (manifest.get('media') or {}).get('files',{}).values():
    obj=Path(p).parent/'.media-objects'/item['sha256']
    with obj.open('rb') as f:
        h=hashlib.sha256()
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    if obj.stat().st_size!=item['bytes'] or h.hexdigest()!=item['sha256']:raise SystemExit('media checksum mismatch')
expect = manifest['sha256']
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
  while IFS= read -r digest; do
    "$ALIYUN" ossutil cp "$DEST/.media-objects/$digest" "oss://$BUCKET/$prefix/.media-objects/$digest" --profile "${ERP_OSS_PROFILE:-erp-oss}" -f >/dev/null
  done <"$media_list"
  echo "[$(date '+%F %T')] oss ok: oss://$BUCKET/$prefix/$remote"
fi
# launchd 下 find 可能被 macOS 隐私保护拒绝；清理失败不影响备份与上传结果
find "$DEST" -maxdepth 1 -name 'erp-*.db' -mtime +14 -print -delete || echo "cleanup skipped: $DEST not readable"
find "$DEST" -maxdepth 1 -name 'erp-*.db.manifest.json' -mtime +14 -print -delete || echo "cleanup skipped: $DEST not readable"
echo "[$(date '+%F %T')] pull ok: $remote"
