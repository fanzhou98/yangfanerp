#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请使用 sudo 运行'; exit 1; }
[[ -s /etc/letsencrypt/live/yangfan-erp/fullchain.pem ]] || { echo '请先取得有效 HTTPS 证书'; exit 1; }
release_dir=$(readlink -f /srv/yangfan-erp/current)
site_host=$(sed -n 's/^ERP_PUBLIC_ORIGIN=https:\/\///p' /etc/yangfan-erp.env)
[[ $site_host =~ ^[a-zA-Z0-9.-]+$ ]] || exit 1
cp /etc/nginx/sites-available/yangfan-erp /etc/nginx/sites-available/yangfan-erp.before-https
sed "s/__HOST__/$site_host/g" "$release_dir/ops/cloud/nginx-https.conf.template" > /etc/nginx/sites-available/yangfan-erp
if ! nginx -t; then
    cp /etc/nginx/sites-available/yangfan-erp.before-https /etc/nginx/sites-available/yangfan-erp
    exit 1
fi
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/yangfan-nginx <<'EOF'
#!/bin/sh
/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx
EOF
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/yangfan-nginx
systemctl reload nginx
echo 'HTTPS 已启用；请确认已安排证书自动续期，并从浏览器验证可信连接。'
