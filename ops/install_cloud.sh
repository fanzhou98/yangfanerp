#!/usr/bin/env bash
# First installation only. Does not modify cloud security groups or create users.
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请使用 sudo 运行'; exit 1; }
site_host=${1:?用法: sudo bash ops/install_cloud.sh 公网IP或域名}
[[ $site_host =~ ^[a-zA-Z0-9.-]+$ ]] || { echo '站点地址格式无效'; exit 1; }
source_dir=$(cd "$(dirname "$0")/.." && pwd)
[[ ! -e /srv/yangfan-erp/current && ! -e /var/lib/yangfan-erp/erp.db ]] || { echo '已安装或已有数据库；请使用升级流程'; exit 1; }
[[ ! -e /etc/nginx/sites-available/yangfan-erp ]] || { echo '站点配置已存在；拒绝覆盖'; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3-venv nginx ca-certificates curl
id yangfan-erp >/dev/null 2>&1 || useradd --system --home-dir /var/lib/yangfan-erp --shell /usr/sbin/nologin yangfan-erp
install -d -o root -g root -m 755 /srv/yangfan-erp/releases
install -d -o yangfan-erp -g yangfan-erp -m 700 /var/lib/yangfan-erp /var/lib/yangfan-erp/backups
release_dir=$(python3 "$source_dir/ops/cloud/prepare_release.py" "$source_dir" /srv/yangfan-erp/releases)
python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/pip" install --disable-pip-version-check -r "$release_dir/requirements-cloud.txt"
runuser -u yangfan-erp -- /usr/bin/python3 "$release_dir/ops/initialize_cloud.py" --database /var/lib/yangfan-erp/erp.db --new
ln -s "$release_dir" /srv/yangfan-erp/current
printf 'ERP_PUBLIC_ORIGIN=https://%s\nERP_DATABASE=/var/lib/yangfan-erp/erp.db\nERP_COOKIE_SECURE=1\n' "$site_host" > /etc/yangfan-erp.env
chmod 644 /etc/yangfan-erp.env
install -m 644 "$release_dir/ops/cloud/yangfan-erp.service" /etc/systemd/system/
install -m 644 "$release_dir/ops/cloud/yangfan-erp-backup.service" /etc/systemd/system/
install -m 644 "$release_dir/ops/cloud/yangfan-erp-backup.timer" /etc/systemd/system/
install -m 644 "$release_dir/ops/cloud/yangfan-erp-photo-prune.service" /etc/systemd/system/
install -m 644 "$release_dir/ops/cloud/yangfan-erp-photo-prune.timer" /etc/systemd/system/
install -d -m 755 /var/www/yangfan-acme/.well-known/acme-challenge
sed "s/__HOST__/$site_host/g" "$release_dir/ops/cloud/nginx-http.conf.template" > /etc/nginx/sites-available/yangfan-erp
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    mv /etc/nginx/sites-enabled/default /etc/nginx/default-site.before-yangfan
fi
ln -s /etc/nginx/sites-available/yangfan-erp /etc/nginx/sites-enabled/yangfan-erp
nginx -t
systemctl daemon-reload
systemctl enable --now yangfan-erp.service yangfan-erp-backup.timer yangfan-erp-photo-prune.timer
systemctl reload nginx
for attempt in {1..15}; do
    if curl --fail --silent http://127.0.0.1:8765/api/health >/dev/null; then break; fi
    sleep 1
done
runuser -u yangfan-erp -- python3 "$release_dir/ops/erp_ops.py" health
systemctl start yangfan-erp-backup.service
echo '基础服务已安装；公网业务入口尚未开放。下一步由你交互创建管理员，再配置可信 HTTPS。'
echo 'sudo -u yangfan-erp python3 /srv/yangfan-erp/current/server.py --database /var/lib/yangfan-erp/erp.db --create-admin'
