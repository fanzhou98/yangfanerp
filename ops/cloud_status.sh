#!/usr/bin/env bash
set -uo pipefail
echo '版本:'
cat /srv/yangfan-erp/current/VERSION
echo '服务与备份定时器:'
systemctl is-active yangfan-erp nginx yangfan-erp-backup.timer
echo '健康:'
python3 /srv/yangfan-erp/current/ops/erp_ops.py health
echo '磁盘:'
df -h /var/lib/yangfan-erp
echo '内存:'
free -h
echo '最近备份文件数:'
find /var/lib/yangfan-erp/backups -maxdepth 1 -name '*.db' -type f | wc -l
echo '维护状态:'
if [[ -e /run/yangfan-erp-maintenance ]]; then echo '维护中'; else echo '正常入口'; fi
