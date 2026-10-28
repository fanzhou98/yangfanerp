---
name: erp-agent-teams
description: 在 ERP系统（/Users/zhoufan/Desktop/ERP系统）用 dsh-agent-teams 开团队做发布批次时先加载本技能。用户说“用 AgentTeams/开团队/多 agent”、要求接手 Codex 任务、或要做语义保持重构、工资/考勤/报表/权限类改动并出发布包时使用；含角色与 DAG 模板、契约条款、验证工具与已踩过的坑。
---

# ERP 项目 AgentTeams 作战手册

先读 `README.md` 的“当前状态”和 `docs/Codex接手说明-2026-10-27-v0.79.0.md` 的“下一项勘察”，再决定开不开团队。技能只补充系统提示里 captain 协议之外的项目专属做法，不重复通用规则。

## 1. 先判断值不值得开团队

| 情况 | 做法 |
|---|---|
| 单文件几十行、改法清楚、预算 ≤15 分钟 | 自己改，别开团队 |
| 多文件、要求“业务结果逐字节不变”、有金标可比 | 开团队，评审这一环最值钱 |
| 要出发布包、要留可审计证据链 | 开团队，证据分散到独立会话 |
| 需求还模糊 | 先对话钉需求，再考虑 |

规模控制：成员 **2–3 个**（实现/验证/评审）够用；勘察自己先做，不必派 analyst。4 个成员 + 8 个任务的实测代价约为单干的 4–5 倍 token、墙钟基本持平。

## 2. 建队与计划

- 团队用 `agent_teams_create(approval="required")` 建，**同一轮不要批准**；批准只发生在用户明确批准之后的新回合。
- 质量任务（implementation/verification/review/repair/integration）逐个 `agent_teams_create_task` 带完整契约；不要用 `plan.members/tasks` 一次性塞入质量任务（那里没有契约字段）。
- 契约模板见 `references/contracts.md`，直接复制改版本号与文件列表。
- 每个质量任务的 `subject` 必填；implementation/repair 必须有 `objective + acceptance + inScope + verify`；review 必须带 `reviewedTaskId` 与 `round`；verification/review 完成时用 `verdict`，needs_revision/reject 必须带 findings。
- 勘察类任务（kind=work）也要给可验收的产物路径，否则后面验证拿不到对照物。

## 3. 推荐 DAG（发布批次）

```
t1 勘察/金标（可选，captain 自己做则省略）
t2 implementation（engineer）
t3 verification（verifier，dep t2）
t4 review r1（reviewer，dep t3，reviewedTaskId=t2）
   └─ needs_revision → t6 repair（engineer）+ t7 review r2（reviewer），t5→t7
t8 修复后重验证（verifier，dep t6）← 必须补：修复改了字节，t3 的裁决不再绑定当前代码，runtime 会警告 stale verdict
t5 integration（engineer，dep t7 与 t8）
```

修复轮次只允许最小改动；评审建议（如“折进单条 SQL”）与实质要求（缺键报错、null 不报错）冲突时，让实现者按实质要求做并说明偏离，由下一轮评审裁定。

## 4. 本项目验证工具

- 快速回归：`bash ops/quick_check.sh`（按 git 改动选测试）；交付前全量：`bash ops/quick_check.sh --full`（上限 600s，**同一时间只跑一套**，日志重定向 /tmp 再看末行）。
- 单模块：`cd tests && PYTHONPATH=.. python3 -m unittest -v <name>`。
- 金标法（本批最有效）：把上一版发布包 `output/releases/yangfan-erp-<旧版>.tar.gz` 解压到 `/tmp/`，用同一份生成器分别跑旧版与新工作树，比较 JSON 字节与摘要；金标脚本与产物放 `/tmp/erp-<版本>-*`，不要进仓库。
- 读路径必须零写入：80 张用户表调用前后“行数 + 全行 sha256”一致、DML=0。
- 合成升级：复制上一版结构库到 /tmp，`ops/migrate.py apply` 两遍 + `check-db --full` + `business_check`，确认 schema 与迁移记录不变。
- 发布包：`python3 ops/build_release.py`（独占创建，不可覆盖）；包内 `release.json` 的 `files` 数 + 1 = `tar tzf | wc -l`；禁止项计数必须 0；与上一版 `tar tzf` 排序后 diff 应完全一致。

## 5. 已踩过的坑

- **报告双份投递**：成员既 `send_message` 又 `update_task(output)`，captain 会收到两遍。派活时要求“报告只写 update_task output，概要不要再发消息”。
- **全量测试重复跑**：t3 与 t8 各跑一次 369s 全量。只在最终字节上跑一次；修复轮只跑契约 verify + 金标 + 相关单模块。
- **契约措辞要实测**：性能数字、“单条 SQL”这类表述必须用最终实测值。本批实际是“聚合 SQL + 缺键守卫查询”，+0.18ms 是评审口径、+0.397ms 是验证口径，写文档用保守的最终值。
- **“不改语义”要看异常路径**：实现者可能顺手把脏数据 `KeyError` 改成静默回退（登录 bootstrap 会把脏条目算成生产确认）。评审必须逐行读 diff 并构造脏数据，而不是只看金标全绿。
- **缺键 vs 显式 null**：`json_type(...) IS NULL` 才是缺键；显式 null 是 `'null'`，v0.95.3 走回退不报错，不要一并报错。
- **不要重复派发**：成员 idle 后状态可能短暂仍显示 working/running，不要据此重发任务或消息。
- **文档与版本放 integration**：inScope 里明确排除 `README.md`、`VERSION`、`docs/`、`output/`，否则实现任务会顺手改版本号。
- **批准后不发“开始吧”**：调度器负责派发；只用消息传递实质指导（发现、口径、措辞）。

## 6. captain 收尾清单

1. 全部任务 terminal、成员 idle 后再汇总；删除/归档团队前不要丢未完成工作。
2. 亲自核验发布包：`cat VERSION`、`shasum -a 256` 与 `.sha256` 及 README 三处一致、`tar tzf | wc -l`、禁止项计数、与上一版文件清单 diff、包内 `release.json` 的 version/files/data_included。
3. 检查 README 顶部标题、当前状态条目、末尾 SHA，以及接手说明的标题/当前批次/下一项勘察/当前交付行。
4. 最终回复必须同时给：发布包路径链接、实际 SHA-256、可复制云端更新命令（上传 `/root` → `sha256sum -c` → 新临时目录解压 → `bash ops/upgrade_cloud.sh` → 核对 `/srv/yangfan-erp/current/VERSION` 与 `ops/cloud_status.sh`）；命令不写进 `releases/`。
5. `agent_teams_delete` 归档团队，并在回复里说明本批已知缺陷与下一批建议。
