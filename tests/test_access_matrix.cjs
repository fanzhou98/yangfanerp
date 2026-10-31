'use strict';
// 权限页必须同时展示「模块（查看）」与「动作（操作）」两类行：
// 新增页面若只在后端有权限、矩阵看不到，管理员就无法核对与调整。
const assert=require('node:assert/strict'),fs=require('node:fs');
const source=fs.readFileSync('web/auth-ui.js','utf8');
assert.ok(source.includes('岗位权限矩阵'),'缺少权限矩阵标题');
const matrix=source.slice(source.indexOf('岗位权限矩阵'),source.indexOf('配置岗位权限'));
assert.ok(matrix.includes('c.modules.map'),'权限矩阵未列出模块（查看）行');
assert.ok(matrix.includes('c.actions.map'),'权限矩阵未列出动作（操作）行');
assert.ok(matrix.includes('read_roles'),'模块行未使用 read_roles 判定授权');
assert.ok(matrix.includes('查看 · '),'模块行缺少「查看 · 」前缀');
const dialog=source.slice(source.indexOf('permisssion'.includes('x')?'':'' )||0);
assert.ok(source.includes('rolePermissionCatalog.modules.filter'),'配置弹窗未按模块列出');
assert.ok(source.includes('rolePermissionCatalog.actions.filter'),'配置弹窗未按动作列出');
console.log('ok 权限矩阵同时包含模块与动作');
