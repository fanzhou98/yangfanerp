# 公网 ECS 安全加固（独立运维包）

本包不修改 ERP 程序、账号、数据库、安全组或 SSH 配置，不开公网端口。

`sudo bash install.sh` 安装只读检测服务，每分钟检查应用健康、Nginx、备份定时器、备份服务失败、磁盘余量、两小时内备份及清单是否存在、五分钟内登录失败/限流事件是否达到十次。结果写入 journald，不包含用户名、密码、Cookie 或业务数据。备份新鲜度不等于备份可恢复，仍须定期恢复演练。

安装前 `nginx -t` 必须通过；脚本仅支持既有洋帆 Nginx 站点，不覆盖站点、不启用 HTTPS、不取消维护状态。站点配置备份在 `/var/backups/yangfan-erp-security/`，专用访问日志记录时间、来源 IP、路径类别、状态和耗时，不记录原始路径、参数或请求内容。日志由 Ubuntu 已有 `/etc/logrotate.d/nginx` 的 `/var/log/nginx/*.log` 规则轮转；安装前须验证该规则存在。journald 设置专用上限前须确认整机保留需求。

查看：`systemctl status yangfan-erp-security.timer`、`journalctl -u yangfan-erp-security.service --since '15 minutes ago'`。检测失败退出非零；本机定时器及日志不等于短信/邮件已接通，也无法从宕机服务器发出通知。

云监控需配置独立的实例不可用/CPU/磁盘/内存告警，并选择已验证的联系人和通知渠道。登录异常及备份失败需通过已配置的日志采集/自定义指标接入，核实是否收费后启用；不能把基础云监控说成已覆盖应用事件。通知链路须人工测试收到。

SSH 收紧前应在 Workbench 核对连接的私网/公网方式和实际来源网段，并验证第二个连接成功；不要填入猜测 IP。Ubuntu 不需要对公网开放 3389。保留业务访问需求所需的 HTTPS 入口；证书与备案未完成前保持业务维护状态。

阿里云 MFA 绑定由账号本人在安全设置中完成验证器绑定和恢复信息保存。ERP 内部 MFA 仍需单独开发和验收，本包未实现。

回退：停用 `yangfan-erp-security.timer`，从安装输出的备份恢复站点，执行 `nginx -t && systemctl reload nginx`。保留日志与备份供核查。
