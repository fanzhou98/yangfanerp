---
name: erp-efficiency
description: ERP系统（/Users/zhoufan/Desktop/ERP系统）做任何批次时的耗时与效率手册。用户说“太慢/耗时/效率低/怎么优化”，或准备跑全量验证、排查测试失败、写文档出包、开 AgentTeams 之前先加载；与 erp-delivery、erp-agent-teams 叠加使用，不替代它们。
---

# ERP 批次效率手册

目标：把单批交付从“30 分钟里有 20 分钟在等测试”压到“测试在后台跑、人一直在产出”。下列数字是本机 2026-10-29 实测，不是估算。

## 0 先记住三个数字

| 动作 | 实测耗时 | 结论 |
|---|---|---|
| `bash ops/quick_check.sh`（按改动挑测试） | **3 秒**（38 例） | 迭代期唯一闸门，改一次跑一次 |
| 单模块 `python3 -m unittest -v test_x` | **0.1–3 秒** | 定位阶段用它，不要全量 |
| `bash ops/quick_check.sh --full`（91 项，含 1008 个 Python 用例） | **约 7 分钟**（python-tests 392.8s） | 一批只跑一次，且必须放后台 |

## 1 本仓库真实的时间黑洞（按浪费从大到小）

1. **全量测试重跑**：本机 1008 个用例 388.8s；`ops/verify.py` 不保留失败输出（防泄密），失败后不看名单就重跑整套，一次 7 分钟。实测 v0.99.1 批次为一次 387.9s 的假失败，连带重跑 3 次整套，白扔约 28 分钟。
2. **`sleep` 轮询**：`sleep 60/180/240` + `pgrep -f ops/verify.py` 的组合。`pgrep -f` 会匹配到自己那条命令，出现“明明 EXIT=1 了还显示 RUNNING”的假状态；一次批次里十几次空转，等于 20 分钟不做任何事。
3. **验证口径跑错目录**：`cd tests && python3 -m unittest discover` 与 `python3 -m unittest discover -s tests`（仓库根，verify.py 的真实调用）是两种发现方式，结果可能不同；两种都跑一遍就是 13 分钟。
4. **契约写错数字返工**（AgentTeams）：v0.97.0 把接口写成 `/api/audit-history`（实际 403，实现是 `/api/audit`）、基线写成 186,864B（同口径实为 165,196B），成员按错契约做完再返工。
5. **文档与 SHA 来回改**：VERSION、README 标题/当前状态/包 SHA、docs 交接说明是 4 处以上；先改文档再出包，包出来还得改一次 SHA。
6. **沙箱里的无效命令**：`ps aux` 被 workspace-write 拒绝、`ls /tmp` 撞符号链接，各浪费一轮。用 `pgrep -fl python`、`ls /private/tmp` 这类允许的读操作。

## 2 五条硬规则

**规则 1：迭代只跑 quick，全量放到“代码已定稿”之后。**
```sh
bash ops/quick_check.sh > /tmp/qc.log 2>&1; tail -3 /tmp/qc.log
```

**规则 2：全量必须后台起、只起一次、收结果一次。**
```sh
# 起（日志带 EXIT 标记，永远不再靠 pgrep 判断）
(bash ops/quick_check.sh --full > /tmp/full-$(date +%H%M).log 2>&1; echo EXIT=$? >> /tmp/full-$(date +%H%M).log) &
# 收：只认最后一行 EXIT=，不认进程名
tail -2 /tmp/full-1301.log
```
起完之后**立刻去做文档/README 草稿/下一项勘察**，不要 `sleep` 等；收结果用 `job_output(wait=true, timeout_ms=120000)`，单次等待上限 120 秒，超时就继续干别的。

**规则 3：全量红了先拿“失败用例名单”，永远不要直接重跑整套。**
```sh
# verify.py 只告诉你 python-tests:false，名单要自己留一份 verbose 日志（一次性，后台）
python3 -m unittest discover -s tests -v > /tmp/pytests.log 2>&1
grep -E "^(FAIL|ERROR):" /tmp/pytests.log | sed -E 's/^(FAIL|ERROR): ([^ ]+).*/\2/' | sort -u
# 只跑这几个（秒级）
cd tests && PYTHONPATH=.. python3 -m unittest -v test_mod.Class.test_name
```
判断标准：名单里的用例单跑通过 = 时序/端口/共享临时目录类不稳定；单跑仍红 = 真回归。前者记一笔“已知不稳定”，后者才改代码。**第二次全量只在最终代码字节上跑。**

**规则 4：测试发现口径写死为仓库根。**
`python3 -m unittest discover -s tests -v` 是 `ops/verify.py` 的实际调用；`ops/quick_check.sh --full` 走的就是它。不要再手工 `cd tests` 跑第二遍。

**规则 5：出包顺序固定，SHA 只改一次。**
改代码 → `quick_check` → 后台起全量 → 写 VERSION/README 标题与状态、docs 交接说明（**先不写包 SHA**）→ 收全量 → `python3 ops/build_release.py` → 用实测 SHA 一次性补 README/docs/`.sha256` 三处 → `git commit`。
包内不含 README/tests/docs（allowlist），所以“改 README”不需要重新出包；改代码才需要。

## 3 慢任务的时间预算表

| 阶段 | 预算 | 做法 |
|---|---|---|
| 接手/勘察（Codex 或上次会话） | 5 分钟 | `tail -c 20000 ~/.codex/sessions/.../rollout-*.jsonl` 看结论；`git log -1`、`cat VERSION`、`ls output/releases/`；不读整个 rollout |
| 定位与实测 | 10 分钟 | 冻结库副本 + 一个 `/tmp/*.py` 脚本出成对数字；产物只写 `/tmp` |
| 实现 | 15 分钟 | 局部 `edit`；改完立刻 `quick_check` |
| 全量验证 | 7 分钟，**并行** | 后台起，同时写文档；只跑一次 |
| 出包+文档+commit | 5 分钟 | 按规则 5 的顺序 |

## 4 AgentTeams 并行时的效率规则

- 派活前把契约里的接口名、基线字节、文件行号**实测一遍**再写（`erp-agent-teams` 的坑清单第一条）。错一个数字，返工 20 分钟。
- 让验证成员跑全量时，船长不要闲着：并行写 README/docs 草稿；全量结果回来只补数字。
- 成员报告只写 `update_task(output)`，不发消息；船长不轮询 `status`，等调度器唤醒。
- 一个批次最多 1 次全量 + 1 次修复后全量；第二次仍红就停，按 AGENTS“同一方案失败 3 次停下”处理。

## 5 可选改造 backlog（要做另开批次，不在本技能内直接改）

1. `ops/verify.py`：python-tests 失败时把 `FAIL:/ERROR:` 的**用例名**（不写断言内容，避免泄密）追加到日志或 `--json` 输出，省掉一次 7 分钟重跑。
2. `ops/quick_check.sh --full --jobs N`：按 `tests/test_*.py` 分模块并行 `unittest discover -p`，每进程独立临时库。
3. `tests/` 分级：给 HTTP/迁移类慢用例打 `slow` 标记，quick_check 默认跳过。

## 6 反模式速查（看到就停）

- `sleep 60` 以上等测试 → 改成后台 + 干活 + `job_output(wait, 120s)`。
- `pgrep -f ops/verify.py` 判断是否跑完 → 认日志里的 `EXIT=`。
- 全量红 → `grep` 名单 → 单跑；不要“再跑一遍看看”。
- 先写 README 的包 SHA 再出包 → 顺序反了，必然改两次。
- 为了“确认一下”再 `cd tests` 跑一遍 discover → 13 分钟没了。
- `ps aux` / 扫 `output/`、`data/` → 沙箱拒绝或浪费时间，用 `pgrep -fl python`、`sqlite3 data/erp.db`。
