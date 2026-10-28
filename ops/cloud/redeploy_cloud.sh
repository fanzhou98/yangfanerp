#!/usr/bin/env bash
# 云端整机重建：旧程序与旧数据目录改名保留（不删除），再用已校验的发布包重新安装。
# 仅用于业务库为空、且已确认要放弃现有账号的场景。
# 用法：sudo bash redeploy_cloud.sh <站点域名> [发布目录]
# 发布目录可省略：脚本位于 <发布目录>/ops/cloud/ 时自动定位。
set -euo pipefail
[[ $EUID == 0 ]] || { echo '请使用 sudo 运行'; exit 1; }
site_host=${1:?用法: sudo bash redeploy_cloud.sh 站点域名 [发布目录]}
[[ $site_host =~ ^[a-zA-Z0-9.-]+$ ]] || { echo '站点地址格式无效'; exit 1; }
source_dir=${2:-}
if [[ -z $source_dir ]]; then
    candidate=$(cd "$(dirname "$0")/../.." 2>/dev/null && pwd) || candidate=
    [[ -n $candidate && -f $candidate/VERSION ]] && source_dir=$candidate
fi
if [[ -z $source_dir || ! -f $source_dir/VERSION || ! -f $source_dir/ops/install_cloud.sh ]]; then
    echo '找不到发布目录。二选一：'
    echo '  1) 把脚本放到 <发布目录>/ops/cloud/ 下执行'
    echo '  2) 显式指定：sudo bash redeploy_cloud.sh 站点域名 /root/yangfan-erp-0.44.1'
    exit 1
fi
source_dir=$(cd "$source_dir" && pwd)
version=$(cat "$source_dir/VERSION")
ts=$(date -u +%Y%m%dT%H%M%SZ)
old_srv=/srv/yangfan-erp.old-$ts
old_data=/var/lib/yangfan-erp.old-$ts
conf_backup=/root/redeploy-config-$ts.tar.gz

echo "== 0 前置检查（目标版本 $version） =="
[[ -f /var/lib/yangfan-erp/erp.db ]] || { echo '找不到现有数据库'; exit 1; }
avail=$(df -Pk /var/lib | awk 'NR==2{print $4}')
(( avail > 2097152 )) || { echo '磁盘可用空间不足 2GB'; exit 1; }
[[ ! -e $old_srv && ! -e $old_data ]] || { echo '改名目标已存在'; exit 1; }

echo '== 1 业务空校验：非空立即中止 =='
python3 - <<'PY'
import sqlite3, sys
tables = ('customers', 'orders', 'receipts', 'products', 'purchase_orders',
          'sales_returns', 'statement_documents', 'indirect_expenses',
          'byproduct_sales', 'material_entries')
c = sqlite3.connect('file:/var/lib/yangfan-erp/erp.db?mode=ro', uri=True)
counts = {t: c.execute('select count(*) from ' + t).fetchone()[0] for t in tables}
print('  业务计数', counts)
if any(counts.values()):
    sys.exit('存在业务数据，拒绝重建')
PY

echo '== 2 备份配置与数据库 =='
tar -czf "$conf_backup" -C / etc/yangfan-erp.env etc/nginx/sites-available/yangfan-erp \
    etc/systemd/system/yangfan-erp.service etc/systemd/system/yangfan-erp-backup.service \
    etc/systemd/system/yangfan-erp-backup.timer
echo "  配置备份 $conf_backup"
runuser -u yangfan-erp -- python3 /srv/yangfan-erp/current/ops/erp_ops.py backup \
    --database /var/lib/yangfan-erp/erp.db --destination /var/lib/yangfan-erp/backups

echo '== 3 进入维护并停服 =='
touch /run/yangfan-erp-maintenance
systemctl stop yangfan-erp-backup.timer yangfan-erp-backup.service yangfan-erp.service

echo '== 4 旧目录改名保留 =='
mv /srv/yangfan-erp "$old_srv"
mv /var/lib/yangfan-erp "$old_data"
echo "  旧程序 $old_srv"
echo "  旧数据 $old_data"

echo '== 5 移走旧站点配置（安装脚本拒绝覆盖） =='
rm -f /etc/nginx/sites-enabled/yangfan-erp
mv /etc/nginx/sites-available/yangfan-erp "/etc/nginx/sites-available/yangfan-erp.old-$ts"

echo '== 6 重新安装 =='
cd "$source_dir"
bash ops/install_cloud.sh "$site_host"

echo '== 7 恢复维护入口（含重启后仍生效） =='
printf 'f /run/yangfan-erp-maintenance 0644 root root -\n' > /etc/tmpfiles.d/yangfan-erp-maintenance.conf
chmod 644 /etc/tmpfiles.d/yangfan-erp-maintenance.conf
systemd-tmpfiles --create /etc/tmpfiles.d/yangfan-erp-maintenance.conf
touch /run/yangfan-erp-maintenance

echo '== 8 验收 =='
bash /srv/yangfan-erp/current/ops/cloud_status.sh || true
curl -s -o /dev/null -w "  Host $site_host 返回 HTTP %{http_code}\n" -H "Host: $site_host" http://127.0.0.1/
ss -ltn | grep -E ':(80|443) ' || true
echo
echo "旧程序保留: $old_srv"
echo "旧数据保留: $old_data"
echo "配置备份:   $conf_backup"
echo "下一步重建管理员（交互输入密码，不写进命令）:"
echo "sudo -u yangfan-erp python3 /srv/yangfan-erp/current/server.py --database /var/lib/yangfan-erp/erp.db --create-admin"
