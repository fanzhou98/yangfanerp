# 历史浏览器脚本（tests/legacy_browser）

这些脚本是 v0.82–v1.3 各批次交付时写的端到端验收，绑定当时的业务规则、DOM 选择和种子数据。2026-10-29 抽样盘点 40 个：**14 通过、26 失败**，失败原因是业务规则已变（配送区域校验、导航分组默认折叠、sticky 表头行为、用户页选择器等），不属当前回归。

## 现状

- **不作为发版依据**。`ops/release_gate.sh` 与 `ops/browser_check.sh --quick` 只跑 `tests/browser_smoke.js`（登录后进 37 个模块、断言无脚本错误与“加载失败”）。
- `ops/browser_check.sh --all` 会把这里一起跑，仅用于人工排查。
- 逐个修复成本高且会随下一轮业务变化再次失效；需要某个场景的浏览器覆盖时，按下面流程“复活”成维护脚本。

## 复活流程

1. 复制到 `tests/`：`git mv tests/legacy_browser/browser_x.js tests/browser_x.js`。
2. 用当前种子与选择器跑通：`node tests/browser_x.js`（先 `ERP_PLAYWRIGHT_MODULE` 指向 playwright-core，或直接 `bash ops/browser_check.sh browser_x.js`）。
3. 常见漂移点：
   - 导航项默认折叠，点击前先展开 `#nav [data-nav-toggle]`（`aria-expanded=false` 时 click）；
   - 区域/客户等字段有新校验，种子数据要按当前接口构造；
   - 输出目录不要再写 `output/`（历史脚本会往交付目录塞截图），改 `/tmp`。
4. 跑通后加进 `ops/browser_check.sh` 的 `QUICK` 或单独在 `release_gate` 调用，并保证 60 秒内。

## 盘点命令

```sh
bash ops/browser_check.sh --inventory     # 并行 4 个，明细 /tmp/erp-browser-inventory-*.json
ERP_BROWSER_JOBS=8 bash ops/browser_check.sh --inventory
```
