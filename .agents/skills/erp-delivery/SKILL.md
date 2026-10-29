---
name: erp-delivery
description: 在 ERP系统（/Users/zhoufan/Desktop/ERP系统）做任一发布批次时先加载本技能：勘察现状、接手 Codex 或上次会话的进度、冻结库副本成对实测、语义保持重构与变异测试、分级验证、出包与云端更新命令。用户说“推进/同步 codex 的工作/接着做/优化一下性能/出个版本/打个包”时使用。开团队再叠加 erp-agent-teams。
---

# ERP 发布批次作战手册

只写本仓库专属、可执行的步骤；通用规则见系统提示与 `AGENTS.md`。开 AgentTeams 时同时加载 `erp-agent-teams`（角色/DAG/契约模板在那里，本技能不重复）。

## 0 开工顺序（5 分钟，别跳）

1. 读 `README.md` 的“当前状态”和“下一步”；需要时读 `docs/Codex接手说明-*.md` 的“当前批次 / 下一项勘察”。
2. `git log -1 --oneline` 与 `git status --short`：确认 HEAD 基线，以及**哪些改动未提交**（常见是两三个版本混在一起）。
3. `cat VERSION`、`ls output/releases/`：确认最新包与版本号是否一致。
4. 给批次定性：语义保持裁剪 / 新功能 / 修 bug / 纯文档。定性决定验证口径，不是决定要不要写代码。

## 1 接手别人的进度（Codex 或上次会话）

- 结论只在会话尾部：`tail -c 20000 ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`，看最后几条 assistant 结论与工具结果；不要通读整个 rollout。
- **不信任“已完成”**，三项独立核对：
  1. `shasum -a 256` 实测 = `.sha256` 文件 = README 记录；
  2. `tar tzf ... | wc -l` = `release.json` 的 `files` 数 + 1；
  3. 包内 `VERSION` 与 README 标题一致。
- 看 fork 子线程的“遗言”：常写“未跑全量，留给主代理”——必须确认主代理真的跑了，而不是转述。
- 未提交范围用 `git status --short | wc -l` 量化；混版时不要整批 commit，按版本拆。
- 多成员/多轮修复时用 **sha256 字节绑定**：每轮修复后核对关键文件哈希，把哈希写进下一轮评审/验证的派活消息；评审先验哈希再开审，防止“审的是旧代码”。

## 2 先测后写（本仓库最值钱的一步）

详见 `references/measure.md`。铁律：

- **冻结副本**：一切实验连 `data/erp.db` 的 `/tmp` 副本（`sqlite3` 的 `backup` 或只读 URI），原库只读。
- **成对数字**：同一副本、同一口径、同一时刻，改前/改后各跑一次。HTTP 字节与函数级 `json.dumps` 字节是两个口径，不得混用；引用必须带口径与时刻。
- 设 `PYTHONPYCACHEPREFIX=/tmp/pyc-<版本>`，产物一律 `/tmp/erp-<版本>-*`，`output/` 只放发布包与校验文件。
- 权限矩阵按 8 个岗位（管理员、库管、会计、出纳、老板、厂长、物流负责人、行政负责人）逐一跑 `erp_access.scope_bootstrap`，不要只测管理员。
- 新读取面要读路由代码确认权限门，并实测 401/403；不要因为“前端不显示”就认为安全。

## 3 语义保持的四个动作

1. **基线取上一版发布包解压**，不是 git HEAD（HEAD 常落后好几个版本）。
2. **逐键/逐字节比**：JSON 序列化后比每个顶层键的 md5；差异只允许你在契约里声明的那几个键，其余必须 0。
3. **变异测试**：把实现改回旧行为，测试必须变红；否则那条断言是恒真。修复轮同样要证明“回退会被抓到”。
4. **grep 所有消费点**：`data.<key>`、`fresh.<key>`、`factoryData()`、`resourceData()`、`resourceData().x||factoryData().x` 这类回退。本项目真实踩过：迁移了订单详情轨迹，漏了 `web/app.js` 的 `checkLatestRecords`，登录态“最近相关操作”静默变空。

## 4 实现纪律

- 局部 `edit`，不整文件重写；只改 inScope；不顺手格式化。
- 不动 `VERSION`、`README.md`、`docs/`、`output/`、`data/`、迁移——这些归集成任务。
- 不新增第三方依赖；新测试放 `tests/`（Python `test_*.py`，前端 `test_*.cjs`）。
- 脚本兼容 macOS bash 3.2：不用 `mapfile`、关联数组。

## 5 验证分级

| 时机 | 命令 | 说明 |
|---|---|---|
| 每次改完 | `bash ops/quick_check.sh` | 按 git 改动挑测试，目标 60s |
| 最终字节 | `bash ops/quick_check.sh --full` | 转 `ops/verify.py`，**默认 8 进程并行约 85–100s**（1008 例；串行 388.8s），同一时间只跑一套；后台起、日志带 `EXIT=` 收结果，等待与失败定位见 `erp-efficiency` |
| 失败时 | 先 `grep -E "^(FAIL\|ERROR):"` 拿用例名单，再单跑 | 不要重跑整套；口径固定为仓库根的 `unittest discover -s tests -v` |
| 单模块 | `cd tests && PYTHONPATH=.. python3 -m unittest -v <name>` | 先窄后宽 |
| 读路径 | 用户表“行数 + 全行 sha256”前后一致 | 任何“查询变快”的改动都要做 |

## 6 出包与交付

见 `references/release.md`。必核：`python3 ops/build_release.py`（独占创建，旧包不覆盖）、实测 SHA 与 `.sha256` 一致、包内 `VERSION` 与 `release.json` 一致、无 `data/`。

最终回复给出发布包链接、实际 SHA-256、验证与本地/线上实际更新结果，并说明 git 状态、本批已知缺陷与下一批。用户于2026-10-29明确要求不再留档更新命令，默认不附命令、不另存逐版本命令；仅用户明确索要时提供。

## 7 已知坑（2026-10 实测）

- **契约里的接口名和数字要先实测再写**：v0.97.0 契约把接口写成 `/api/audit-history`（实际 403，实现是 `/api/audit`），基线写成 186,864B（同口径实为 165,196B）。写契约前先跑一遍。
- **报告双份**：成员既 `send_message` 又 `update_task(output)`。派活时要求“报告只写 update_task output”。
- **修复改了字节就要补验证**：至少 quick + 变异测试；全量只在最终字节上跑一次。
- **本地库会被在跑的服务写心跳**：`data/erp.db` 的 md5 会变，逐表哈希才说明问题；结论写“本批未写库”，不要写“文件字节未变”。
- **打包 allowlist 不含 README/tests/docs**（v0.96.0 亦然）。别把“包内缺 README”当回归，除非先改 `ops/build_release.py`。
- **前端新测试可能只在 `--full` 生效**：`ops/quick_check.sh` 对 `web/*.js` 只做 `node --check`；`tests/*.cjs` 由 `ops/verify.py` 的 glob 在 `--full` 执行。
- **金标取上一版发布包，不取 git HEAD**（v1.0.0 用 v0.99.3 的 `tar.gz` 解压副本；HEAD 常常落后好几个未发布的版本）。金标身份写进报告：包 sha256 + 路径 + `VERSION`。
- **变异测试在 `/tmp` 副本树里做**：v1.0.0 有人把 MR1/MR2/MR3 变异直接写进主 `server.py`，还留下 `tests/server.py` shadow `import server`，后续所有验证字节失效。变异前先复制候选树；改完主工作树任何文件都要用 `shasum -a 256` 复核关键文件与报告一致。
- **前端行为回归用 node parity 夹具**：把旧版前端与新前端加载到同一份数据上逐日比对（v1.0.0 用今天−50…+5 共 56 天比“已登记/已完成”）；`tests/test_daily_work.cjs` 这类夹具只 `runInContext` 部分 JS 文件，漏加载 `web/resources.js` 会让函数未定义，属夹具缺口而非运行时问题。
- **隔离树跑全量先复制 `data/erp.db`**：`git archive` 出来的树里库是 0B，`test_open_stock_query` 等会红；复制仓库库文件后单跑通过即环境问题。
- **出包后用“清单 diff + 内容变化集合”快速审计**：与上一版 `tar tzf` 排序 diff 应为空，`shasum` 内容变化应恰好是期望的那几个文件；v1.0.0 是 8 个（VERSION、resources_costs.py、server.py、5 个 web JS）。
- **规模/性能类批次要自建 20k/40k 生成器**：本机 `data/erp.db` 只有几百行，证明不了“线性化”；生成器与副本库放 `/tmp/erp-<版本>-*`，40k 行用例的数据生成脚本不要进仓库。
