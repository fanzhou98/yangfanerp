# 实测配方（冻结副本 / 成对数字 / 逐键 diff / 变异测试）

原则：**先测再写契约**。契约里的字节数、行数、接口名、耗时都必须来自这里的一次真实运行；不要把估算或旧快照写进契约和 README。

## 1 冻结库副本（原库只读）

```bash
mkdir -p /tmp/erp-<ver>
cd /Users/zhoufan/Desktop/ERP系统
python3 - <<'PY'
import sqlite3
src = sqlite3.connect('file:data/erp.db?mode=ro', uri=True)
dst = sqlite3.connect('/tmp/erp-<ver>/db-copy.db')
src.backup(dst)          # 在线备份，源库不会被写
dst.close(); src.close()
PY
```

后续所有探针都指向副本。`server.py:38` 的 `DB` 是模块级全局，测试/探针里直接改：

```python
import pathlib, sys, json
sys.path.insert(0, '/tmp/erp-<ver>/src-new')   # 或 src-old
import server
server.DB = pathlib.Path('/tmp/erp-<ver>/db-copy.db')
res = server.bootstrap(include_expense_history=False,
                       include_byproduct_history=False,
                       factory_light=True)
blob = json.dumps(res, ensure_ascii=False, separators=(',', ':'))
print('bytes', len(blob.encode()))
```

## 2 逐键 diff（证明“只动了声明的键”）

两次运行（旧版包解压副本 vs 当前工作树）各写一份 JSON，再比：

```python
import json, hashlib
old = json.load(open('/tmp/erp-<ver>/old.json'))
new = json.load(open('/tmp/erp-<ver>/new.json'))

def h(v):
    return hashlib.md5(json.dumps(v, sort_keys=True, ensure_ascii=False,
                                  separators=(',', ':')).encode()).hexdigest()

for k in sorted(set(old) | set(new)):
    if h(old.get(k)) != h(new.get(k)):
        a = len(json.dumps(old.get(k), ensure_ascii=False, separators=(',', ':')))
        b = len(json.dumps(new.get(k), ensure_ascii=False, separators=(',', ':')))
        print(f'{k}: {a}B -> {b}B  Δ={b - a}')
```

验收口径：差异键集合 == 契约声明集合；其余键 0 字节。再把 `Δ` 求和与总字节差对齐（对不上说明还有隐藏差异）。

## 3 权限矩阵（8 岗位）

```python
roles = ['管理员', '库管', '会计', '出纳', '老板', '厂长', '物流负责人', '行政负责人']
configs = {r: erp_access.permissions(c, r) for r in ['管理员', *erp_access.ACCOUNT_ROLES]}
for role in roles:
    user = <按 tests 里的 helper 构造该角色登录态>
    out = erp_access.scope_bootstrap(copy.deepcopy(res), user, configs, c)
    assert out['audit'] == []          # 本轮声明的不变量
    ...
```

角色权限字段 = `modules`（查看）+ `actions`（操作）；`scope_bootstrap` 的过滤集中在 `erp_access.py:488-518`，改读取面时逐条核对它 pop/置空的键。

## 4 变异测试（证明测试不是恒真）

1. 在 `/tmp` 拷贝一份仓库或直接改工作树后 `git stash`/手工还原；
2. 把实现改回旧行为（删掉新分支、把异步改回同步、把过滤改成子串）；
3. 跑对应测试，**必须变红**；记录失败条数与退出码；
4. 还原后再跑一次，必须全绿。

v0.97.0 实例：删掉 `/api/audit` 分支 → `node tests/test_order_audit_trail.cjs` 6 条 FAIL、exit 2。

## 5 金标（跨版本逐字节对比）

```bash
mkdir -p /tmp/erp-<ver>/src-old
tar xzf output/releases/yangfan-erp-<old>.tar.gz -C /tmp/erp-<ver>/src-old
```

同一生成器分别 `sys.path.insert` 两套源码、同一个 `db-copy.db`、同一个随机种子，输出 JSON 后比 md5。旧版包是**上一版语义的唯一权威基线**，不要用 git HEAD 代替。

## 6 常见坑

- `json.dumps` 的 `separators`/`ensure_ascii`/`sort_keys` 不一致会让字节数差出几个百分点——成对数字必须同一参数。
- HTTP 真实字节（`/api/bootstrap`）与函数级字节是两个口径；README 引用哪个就只写哪个，并注明口径。
- 本机 `data/erp.db` 可能被正在运行的服务写心跳（`auth_session_activity`），文件 md5 会变；要用逐表哈希说明“本批未写库”，不要写“文件字节未变”。
- `ops/quick_check.sh --full` 会跑 `tests/*.cjs`；`quick` 模式只对 `web/*.js` 做 `node --check`。
