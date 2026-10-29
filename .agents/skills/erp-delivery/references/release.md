# 出包与交付清单

只在评审通过后的最终字节上做一次。

## 1 出包前

```bash
cat VERSION                      # 已是目标版本
bash ops/quick_check.sh --full   # 最终字节全量，≤600s，日志 /tmp
git status --short               # 确认没有临时文件混进包
```

`VERSION`、`README.md`、`docs/Codex接手说明-*.md` 的改动属于集成任务，不要和实现混在同一批。

## 2 打包

```bash
python3 ops/build_release.py
```

- 脚本**独占创建**，不会覆盖同名包；重新打包先删旧包或升版本号。
- 包内 allowlist 只含后端模块、`ops/`、`web/`、`VERSION`、`requirements-cloud.txt`、`release.json`；**不含 README、tests、docs**（v0.96.0 同样如此）。若某次必须入包，先改 `ops/build_release.py` 并单独评审。

## 3 三方校验

```bash
cd output/releases
shasum -a 256 yangfan-erp-<ver>.tar.gz
cat yangfan-erp-<ver>.tar.gz.sha256
tar tzf yangfan-erp-<ver>.tar.gz | wc -l          # = release.json files + 1
tar xzOf yangfan-erp-<ver>.tar.gz VERSION         # 必须等于版本号
tar xzOf yangfan-erp-<ver>.tar.gz release.json | head -5   # version / data_included=false
tar tzf yangfan-erp-<ver>.tar.gz | grep -cE '(^|/)(data|tests|docs|__pycache__)/|DS_Store|\.log$' || true   # 0
```

再抽一两个改动文件，比对包内哈希与工作区哈希（`shasum -a 256 web/app.js` vs `tar xzOf ... | shasum`）。

## 4 README 要改的四处

1. 顶部标题 `# ... · v<ver>`；
2. `## 当前状态（v<ver>）` 下的本批条目：改了什么、**成对实测数字（带口径）**、权限/语义收紧、schema 与模块数、测试规模；
3. `## 下一步`：保留既有两项，不删不减；
4. 交付记录里的 SHA（如有）与实际一致。

`docs/Codex接手说明-*.md` 同步“当前批次 / 下一项勘察 / 当前交付”，不新增逐版本文档（`docs/` 维持 6 份）。

## 5 云端更新操作模板（代理执行，默认不在最终回复附命令）

2026-10-29 用户已授权 Codex / Harness 执行后续常规发布，由唯一发布负责人操作。先读取 AGENTS.md 的维护窗口及授权边界；无需再请用户手工上传或复制命令。

固定连接参数：`-P default -i i-2vcgck7stwnl1b8xt14m -r cn-chengdu`，Linux 用户 root。凭证只交由 CLI 读取，禁止输出、复制、提交配置文件。

先确认 `workbench version` 可用，再只读预检：

```bash
workbench exec -P default -i i-2vcgck7stwnl1b8xt14m -r cn-chengdu -u root --command 'cat /srv/yangfan-erp/current/VERSION && bash /srv/yangfan-erp/current/ops/cloud_status.sh'
```

核对已部署版本、健康与维护标记。目标版本已部署且内容一致、健康正常则跳过；线上更高版本、同版本内容冲突或异常维护状态先停止定位，不自动降级。不能单凭 cloud_status.sh 退出码判断通过，应核对各项输出及下述独立检查。

包在本机 `output/releases/`，本地实测 SHA 必须与最终验证记录、校验文件一致。逐个上传：

```bash
workbench upload "output/releases/yangfan-erp-<ver>.tar.gz" "/root/yangfan-erp-<ver>.tar.gz" -P default -i i-2vcgck7stwnl1b8xt14m -r cn-chengdu --user-name root
workbench upload "output/releases/yangfan-erp-<ver>.tar.gz.sha256" "/root/yangfan-erp-<ver>.tar.gz.sha256" -P default -i i-2vcgck7stwnl1b8xt14m -r cn-chengdu --user-name root
```

同名远端文件先核对 SHA，一致复用、不一致停止，禁止 --force 覆盖。使用 `workbench exec` 的同一组连接参数，加 `--timeout 900 --command <远端脚本正文>` 执行以下整条命令链；正文用安全 shell 引号或脚本文件传入，不拼接不可信输入。每次 exec 都是独立 Shell，不能把 cd 和后续操作拆开调用。执行前将版本与 SHA 占位符替换为已验证的实际值。

```bash
cd /root && \
echo '<actual-sha256>  yangfan-erp-<ver>.tar.gz' | sha256sum -c - && \
sha256sum -c yangfan-erp-<ver>.tar.gz.sha256 && \
tmp=$(mktemp -d /root/erp-<ver>-XXXXXX) && \
tar xzf /root/yangfan-erp-<ver>.tar.gz -C "$tmp" && \
cd "$tmp" && \
sudo bash ops/upgrade_cloud.sh && \
cat /srv/yangfan-erp/current/VERSION && \
sudo bash ops/cloud_status.sh && \
test "$(cat /srv/yangfan-erp/current/VERSION)" = "<ver>" && \
systemctl is-active --quiet yangfan-erp nginx yangfan-erp-backup.timer && \
curl --fail --silent http://127.0.0.1:8765/api/health && \
test ! -e /run/yangfan-erp-maintenance
```

核实升级前一致性备份、目标版本、健康、服务/备份定时器、维护入口及既有 HTTPS 地址后才报告成功。超时或断连先只读检查升级锁、状态、版本和备份，禁止直接重试。失败保留现场，不自动恢复旧数据库、不清库、不绕过维护入口。

本地/线上分别记录状态。本机更新核对既有进程、数据库路径和启动参数，先备份再正常重启并验收版本与健康；无运行服务时不额外启动，不批量杀进程。两端只同步程序，不互相覆盖业务库或账号。纯规则/文档修改不升版本、不打包、不重启。

注意：`ops/upgrade_cloud.sh` 需要 root；会先备份、停备份定时器与服务、再做候选库校验；失败时维护入口保持关闭并打印回滚提示，**不要加 `--keep-maintenance`**。

## 6 最终回复清单

- [ ] 发布包链接 + `.sha256` 链接
- [ ] 实际 SHA-256（与实测一致）
- [ ] 本批改了什么 + 成对实测数字（口径写明）
- [ ] 验证结论（谁验的、跑了哪些、有没有已知缺陷）
- [ ] 默认不附上传或更新命令，也不另存逐版本命令留档；只有用户明确索要时提供并说明上传路径前提
- [ ] 本地/线上各自更新状态、实际版本、备份及健康结果；未执行必须说明
- [ ] git 是否未提交、下一批建议
