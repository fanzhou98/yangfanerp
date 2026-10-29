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

## 5 云端更新命令（最终回复里直接贴，不写进 releases/）

前提：包与 `.sha256` 已由用户上传到 `/root`；用户自行执行，不代为部署。

```bash
cd /root && \
sha256sum -c yangfan-erp-<ver>.tar.gz.sha256 && \
tmp=$(mktemp -d /root/erp-<ver>-XXXXXX) && \
tar xzf /root/yangfan-erp-<ver>.tar.gz -C "$tmp" && \
cd "$tmp" && \
sudo bash ops/upgrade_cloud.sh && \
cat /srv/yangfan-erp/current/VERSION && \
sudo bash ops/cloud_status.sh
```

注意：`ops/upgrade_cloud.sh` 需要 root；会先备份、停备份定时器与服务、再做候选库校验；失败时维护入口保持关闭并打印回滚提示，**不要加 `--keep-maintenance`**。

## 6 最终回复清单

- [ ] 发布包链接 + `.sha256` 链接
- [ ] 实际 SHA-256（与实测一致）
- [ ] 本批改了什么 + 成对实测数字（口径写明）
- [ ] 验证结论（谁验的、跑了哪些、有没有已知缺陷）
- [ ] 完整云端更新命令，并写明上传路径前提
- [ ] git 是否未提交、下一批建议
