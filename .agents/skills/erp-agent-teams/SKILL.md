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

规模控制：单线批次成员 **2–3 个**（实现/验证/评审）够用；勘察自己先做，不必派 analyst。双线并行（v1.0.0 实测：FIFO 优化 + 初始化裁剪，6 成员 / 15 任务 / 约 2.5 小时墙钟）才值得上 4–6 个成员——两条独立实现线各自配验证与评审，captain 只做定位、amend、字节绑定与收口。别为“看起来并发”拆出假独立的任务。

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

两条线并行时（v1.0.0 实测：FIFO 优化线 + entries 裁剪线），评审失败会自动派生 `repair` + `review r2`，另有系统生成的「修复后重验证」。**直接用系统派生的这些任务，不要另建同名任务**；确认 `integration` 的依赖已自动改指向新复审，否则 captain 手动 `edit_plan` 改依赖。

修复收口顺序：repair → 复审（review r2）→ 重验证 → integration。重验证必须绑定最终字节，且在 integration 出包前完成；只跑 delta + 最终字节全量，不重做上一轮全套。

## 4. 本项目验证工具

- 快速回归：`bash ops/quick_check.sh`（按 git 改动选测试）；交付前全量：`bash ops/quick_check.sh --full`（上限 600s，**同一时间只跑一套**，日志重定向 /tmp 再看末行）。
- 单模块：`cd tests && PYTHONPATH=.. python3 -m unittest -v <name>`。
- 金标法（本批最有效）：把上一版发布包 `output/releases/yangfan-erp-<旧版>.tar.gz` 解压到 `/tmp/`，用同一份生成器分别跑旧版与新工作树，比较 JSON 字节与摘要；金标脚本与产物放 `/tmp/erp-<版本>-*`，不要进仓库。金标的身份写进任务 output：包 sha256 + 解压路径 + VERSION。
- 候选树 = `git archive HEAD` + 工作树改动文件，固定下来再做比对；报告里列候选关键文件的 sha256，供下一轮“字节绑定”。
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
- **契约里的接口名与数字先实测**：v0.97.0 把接口写成 `/api/audit-history`（实际 403，实现是 `/api/audit`），基线写成 186,864B（同口径实为 165,196B）。写进契约前先按 `erp-delivery` 的实测配方跑一遍。
- **迁移投影类改动要在派活时点名全部消费点**：v0.97.0 漏了 `web/app.js:87` 的 `checkLatestRecords`，登录态静默变空，靠评审才抓回。派活时直接列出 grep 到的 `data.<key>`/`fresh.<key>`/`factoryData()` 消费点。
- **评审要跑变异测试**：把实现改回旧行为，测试必须红；v0.97.0 用这招证明了回归测试不是恒真。needs_revision 的 requiredFix 里写明“补一条能在回退时变红的断言”。
- **接受“包内不含 README/tests”**：仓库既有 allowlist 就是不含（v0.96.0 同样），契约别把它写成验收项，否则会逼成员改 out-of-scope 的 `ops/build_release.py`。
- **变异脚本绝不能写主工作树（v1.0.0 事故）**：engineer2 的 MR1/MR2/MR3 变异把主 `server.py` 改成三个变异的合并版，还生成未跟踪的 `tests/server.py`（会 shadow `import server`）。此后所有验证字节都对不上。规则：变异/一次性脚本在 `/tmp` 的候选副本树里做；captain 在每轮修复后核对关键文件 sha256（v1.0.0 是 server.py / app.js / resources.js / daily-work.js / test_bootstrap_entries.py 五个），并把哈希写进下一轮评审消息作为“字节绑定”。发现工作树被改先还原、删 `tests/server.py`，再让实现者重跑最终验证。
- **status 输出会截断 findings**：`agent_teams_status` 只给每个任务 output 的前几百字，评审的 finding 细节常被截掉。要定位就发消息让评审给“5 行以内：文件行 / 触发场景 / 用户可见后果 / 最小修法”，比解压 output 快。
- **修复轮 inScope 不够时 amend，别让成员降级方案**：v1.0.0 的 t14 原 inScope 缺 `web/app.js` 与 `server.py`，实现者主动请求 amend。captain 用 `agent_teams_amend_task` 补全（reason 写清缺哪条验收要动哪个文件），而不是接受“只修一半/F1 退化成 async”。
- **投影裁剪类批次的评审重点是“窗口外行为”**：静态 grep 覆盖不到“日期选择器能选任意历史日”这种路径。要求评审用旧前端 × 新前端做 node parity（v1.0.0 构造今天−50…+5 共 56 天逐日比对“已登记/已完成”），再补一个“历史未结项能否补录/作废”的真实 HTTP 用例。t8 正是靠这两类用例抓出 2 个 medium 回归。
- **隔离树的全量红先查库文件**：verifier 在 `git archive` 树里跑全量，`data/erp.db` 是 0B，`test_open_stock_query` 直接红。复制仓库 `data/erp.db` 到隔离树即可；别当代码回归。
- **性能类评审要专门验“状态游标会回退”**：FIFO 优化的 F1 就是 `_push` 用 bisect 插到更旧位置却不回退 `head`，跨库调拨后静默跳过活层，金标全绿也照样错。派活时点名“任何游标/缓存/索引位置，在插入更旧数据后必须回退或重建”。
- **发布前用“与上一版文件清单 diff + 内容哈希变化集合”做快速审计**：v1.0.0 与 v0.99.3 的 `tar tzf` 排序 diff 为空、内容变化恰好 8 个文件，一条命令就能证明“没误带文件”。

## 6. captain 收尾清单

1. 全部任务 terminal、成员 idle 后再汇总；删除/归档团队前不要丢未完成工作。
2. 亲自核验发布包：`cat VERSION`、`shasum -a 256` 与 `.sha256` 及 README 三处一致、`tar tzf | wc -l`、禁止项计数、与上一版文件清单 diff、包内 `release.json` 的 version/files/data_included。
3. 检查 README 顶部标题、当前状态条目、末尾 SHA，以及接手说明的标题/当前批次/下一项勘察/当前交付行。
4. 最终回复必须同时给：发布包路径链接、实际 SHA-256、可复制云端更新命令（上传 `/root` → `sha256sum -c` → 新临时目录解压 → `bash ops/upgrade_cloud.sh` → 核对 `/srv/yangfan-erp/current/VERSION` 与 `ops/cloud_status.sh`）；命令不写进 `releases/`。
5. `agent_teams_delete` 归档团队，并在回复里说明本批已知缺陷与下一批建议。
