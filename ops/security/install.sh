#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请使用 sudo 运行'; exit 1; }
source_dir=$(cd "$(dirname "$0")" && pwd)
site=/etc/nginx/sites-available/yangfan-erp
[[ -f "$site" && -f /var/lib/yangfan-erp/erp.db ]] || { echo '未检测到既有 ERP 部署'; exit 1; }
[[ -f /etc/logrotate.d/nginx ]] && grep -Fq '/var/log/nginx/*.log' /etc/logrotate.d/nginx || { echo '请先核验 Nginx 日志轮转规则'; exit 1; }
[[ ! -e /etc/nginx/conf.d/yangfan-erp-security.conf && ! -e /opt/yangfan-erp-security ]] || { echo '安全包已存在，拒绝覆盖；请先核查安装记录'; exit 1; }
nginx -t
install -d -m 700 /var/backups/yangfan-erp-security
backup_file=$(mktemp /var/backups/yangfan-erp-security/nginx.XXXXXXXX)
cp -p "$site" "$backup_file"
rollback() {
    cp -p "$backup_file" "$site"
    rm -f /etc/nginx/conf.d/yangfan-erp-security.conf
    echo "安装失败，站点配置已恢复；备份：$backup_file" >&2
}
trap rollback ERR
install -d -m 755 /opt/yangfan-erp-security
install -m 644 "$source_dir/check.py" /opt/yangfan-erp-security/check.py
install -m 644 "$source_dir/nginx-security.conf" /etc/nginx/conf.d/yangfan-erp-security.conf
python3 - "$site" <<'PY'
from pathlib import Path
import re, sys
p = Path(sys.argv[1])
source = p.read_text()
# This directive overrides inherited default logs for all servers in this site.
updated, count = re.subn(r'(?m)^(\s*server\s*\{\s*)$', r'\1\n    access_log /var/log/nginx/yangfan-erp-security.log erp_security;', source)
if not count:
    raise SystemExit('未识别站点 server 块')
# Remove the previous privacy-driven disable only; do not touch proxy/SSL settings.
updated = re.sub(r'(?m)^\s*access_log off;\s*$', '', updated)
p.write_text(updated)
PY
if ! nginx -t; then
    rollback
    exit 1
fi
systemctl reload nginx
trap - ERR
install -m 644 "$source_dir/yangfan-erp-security.service" /etc/systemd/system/
install -m 644 "$source_dir/yangfan-erp-security.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now yangfan-erp-security.timer
echo "安全检测定时器和脱敏日志已安装；站点备份：$backup_file"
echo '短信／邮件尚需云监控接入并测试收件。'
