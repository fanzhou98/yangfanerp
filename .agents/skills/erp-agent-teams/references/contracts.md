# 契约模板（复制后替换 {{...}}）

这些是 v0.95.4 批次实际使用并跑通的契约。按任务规模删减，但保留四类必填项：可验收的产物、精确的 verify 命令、inScope/outOfScope、已知边界。

## implementation（engineer）

- kind=implementation，dependencies=[勘察任务或空]，assignee=engineer
- objective：把 `{{目标}}` 的读取/计算改为 `{{方案}}`，业务结果与 vX.Y.Z 完全一致；内部完整 snapshot 供既有算法使用的默认口径不变。
- acceptance：
  1. 统计接口 bootstrap 的传入/返回均不携带明细（factory 投影 ≤ {{字节数}} 字节）。
  2. 所有落库与查询路径已纳入本批范围；全项目 grep 复核无遗漏。
  3. `{{索引/查询计划要求}}`；无 N+1。
  4. 不改变保存/确认/删除语义、版本令牌、金额与快照、权限隔离。
  5. 不新增迁移、schema 维持 `{{N}}`；不得改动 `data/` 与正式库。
  6. 所有断言通过且与改造前结果逐字节一致（金标在 /tmp/{{...}}）。
  7. 只改 inScope 内文件，不做整文件重写或无关格式化。
- inScope：实际要改的 3–6 个模块 + `tests/`
- outOfScope：`web/`、`data/`、`output/`、`ops/`、`docs/`、`README.md`、`VERSION`、`migrations.py`、`migration_steps.py`
- verify：精确的 unittest 命令 + `bash ops/quick_check.sh`（都写全，不要写“跑相关测试”）
- 提醒：金标生成器与证据放 `/tmp/erp-{{版本}}-*`，不要进仓库。

## verification（verifier）

- kind=verification，dependencies=[implementation]
- acceptance：
  1. 金标对比：同一生成器分别跑上一版发布包解压副本与当前工作树，19 个 JSON md5 与摘要逐字节相同。
  2. 读路径零写入：80 张用户表“行数 + 全行 sha256”前后一致，DML=0。
  3. 合成升级：复制上一版结构库，`migrate.py apply` 两遍 + `check-db --full` + `business_check`，schema 与迁移记录不变。
  4. 计划与体积：EXPLAIN 记录命中情况、扫描行数、返回字节；明确“无全表 payload 读取”的准确含义。
  5. 边界：草稿/冲突、未来日期排除、生产/管理隔离、separate-v1、未登记不补零，断言不得恒真。
  6. 最终字节上 `bash ops/quick_check.sh --full` 全过（日志 /tmp）。
  7. 报告结论与证据路径，列出未覆盖项与存疑。
- 要求：只读代码与临时库；全量测试同一时间只跑一套；不要相信实现者自述。在 `git archive` 隔离树跑全量时先把仓库 `data/erp.db` 复制进去（否则 0B 库会让 `test_open_stock_query` 等红，属环境问题）；首次 `ok:false` 且 `failed_cases` 为空时重跑一次，连续两次红才当回归。

## review（reviewer）

- kind=review，dependencies=[verification]，reviewedTaskId=implementation，round=1
- acceptance：
  1. 逐行审 diff：只改 inScope、最小集、无无关重写。
  2. 语义核对：三字段判定、回退分支、令牌、权限、隔离、版本令牌未被改变。
  3. SQL 正确性：日期边界（月末/闰月/跨年）、参数化、索引命中、无 N+1。
  4. 测试充分性：覆盖新路径与边界，断言可失败（把实现回退旧代码时测试必须红）。
  5. 无调试代码、临时路径、敏感数据。
  6. 明确 verdict；needs_revision 必须带 findings（id/severity/problem/requiredFix），不得批准自己的实现。
- 额外要求：对“不改语义”要构造脏数据（缺键、缺日期、显式 null、未来日期），而不只看金标全绿。
- 字节绑定：只审 captain 给出的 sha256 候选文件（或自己在 `/tmp` 冻结候选树），先核对 sha 再开审；只读纪律——评审期间主工作树出现任何改动都要先停手报告。
- 投影/裁剪类改动必须审“窗口外行为”：用旧前端 × 新前端做 node parity（逐日比对判定结果），并对“历史未结项能否补录/更正/作废”跑真实 HTTP；静态 grep 抓不到日期选择器越界这类路径。
- 性能类改动必须审“状态是否可回退/重建”：游标、缓存、索引位置在插入更旧数据、跨库调拨、作废后回退时是否失效。

## repair（engineer，由评审失败自动派生）

- 只允许修 finding 指出的问题，不改范围；完成后重跑金标与契约 verify。
- 偏离评审建议时必须在 output 说明理由与实测代价，由下一轮评审裁定。
- 需要动 inScope 外的文件（v1.0.0：`web/app.js`、`server.py`）时先在 output 说明，由 captain `agent_teams_amend_task` 补全；不要自行越界，也不要把验收降级成“只修一半”。
- 变异测试与一次性脚本只在 `/tmp` 的候选副本树里跑，禁止写主工作树；确认没有生成 `tests/server.py` 这类 shadow 文件，否则后续 `import server` 会静默用错模块。
- 收尾报告列出修复后的关键文件 sha256，供 captain 做“字节绑定”。

## 修复后重验证（verifier）

- 修复改了文件字节后必须补这一任务：金标 digest、check_t2、缺键/边界逐组与旧版对齐、读路径零写入、最终字节全量回归、合成升级。
- 只验证 delta 与最终字节，不重做上一轮全套证据；报告必须写“可绑定最终发布字节”。

## integration（engineer）

- kind=integration，dependencies=[review, 重验证]
- acceptance：
  1. VERSION=x.y.z；README 顶部标题、当前状态条目、末尾 SHA 更新；docs 接手说明标题/当前批次/下一项勘察/当前交付行同步；不新增逐版本文档。
  2. `python3 ops/build_release.py` 生成新包与 .sha256；文件数与 release.json 的 files 一致；release.json 在包内且 data_included=false；无 data/tests/docs/日志/截图/__pycache__/.DS_Store。
  3. `.sha256` 与 `shasum -a 256` 实际值一致，README 记录的 SHA 与实际一致。
  4. 不覆盖旧包；不部署、不上传、不重启线上、不建定时任务；只改 VERSION、README、接手说明与包目录。
  5. output 给交付摘要：版本、包路径、SHA、文件数、测试结论、下一批建议。
- verify：
  - `cd output/releases && shasum -a 256 -c yangfan-erp-x.y.z.tar.gz.sha256`
  - `tar tzf output/releases/yangfan-erp-x.y.z.tar.gz | grep -c -E '(^|/)(data|tests|docs|__pycache__)/|DS_Store|\.log$' || true`（应为 0）
  - `tar tzf output/releases/yangfan-erp-x.y.z.tar.gz | wc -l`（files+1）

## captain 发给成员的消息模板

- 给实现者：先读上一任务 output 与金标目录；列出 5–7 条必须遵守的语义坑；声明 outOfScope；要求自测后只写 update_task output。
- 给验证者：声明只读、证据目录、全量测试只跑一套；要求明确“存疑”而不是模糊通过。
- 给评审者：给出 finding 的判定问题与最小修复边界；要求 verdict+findings，不要重跑全量。
- 给交付者：给出最终实测数字、文档措辞、表数口径、发布前冒烟（浏览器测试 + 登录 bootstrap）。
