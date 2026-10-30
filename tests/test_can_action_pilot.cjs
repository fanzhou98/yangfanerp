'use strict';
// 本机试运行（未启用账号）时，界面上的按钮可见性必须与后端同一张动作表一致，
// 不能再按旧的第二张权限表放宽：库管看不到作废原辅料流水、会计看不到豆渣收款。
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/forms.js','utf8');
const start=source.indexOf('const legacyPermissionRoles=');
const end=source.indexOf('\nfunction canSeeData(');
const code=source.slice(start,end);
const catalog={roles:['管理员','库管','会计','出纳','老板','厂长','物流负责人','行政负责人','司机'],actions:[
 {id:'materials.void',roles:['会计']},
 {id:'materials.catalog',roles:['会计']},
 {id:'byproducts.receive',roles:['出纳']},
 {id:'weight.write',roles:['库管','会计']},
 {id:'purchases.receive',roles:['库管','会计']},
 {id:'master.customers.write',roles:['会计']},
 {id:'system.backup',roles:['会计']}
]};
const context={data:{access_catalog:catalog},role:'库管'};
vm.createContext(context);
vm.runInContext(code+'\nthis.canAction=canAction;',context);
const can=(role,key)=>{context.role=role;return context.canAction(key);};
assert.equal(can('库管','weight.write'),true);
assert.equal(can('库管','purchases.receive'),true);
assert.equal(can('库管','materials.void'),false,'库管不应看到作废原辅料流水');
assert.equal(can('库管','materials.catalog'),false,'库管不应看到维护物料档案');
assert.equal(can('库管','byproducts.receive'),false,'库管不应看到豆渣收款');
assert.equal(can('会计','materials.void'),true);
assert.equal(can('会计','master.customers.write'),true);
assert.equal(can('会计','system.backup'),true);
assert.equal(can('会计','byproducts.receive'),false,'豆渣收款归出纳');
assert.equal(can('出纳','byproducts.receive'),true);
assert.equal(can('出纳','materials.void'),false);
// 有账号时仍以服务端下发的 permissions.actions 为准，管理员全通。
const accountContext={data:{auth_user:{role:'会计'},permissions:{actions:['materials.void']},access_catalog:catalog},role:'会计'};
vm.createContext(accountContext);
vm.runInContext(code+'\nthis.canAction=canAction;',accountContext);
assert.equal(accountContext.canAction('materials.void'),true);
assert.equal(accountContext.canAction('system.backup'),false);
accountContext.data.auth_user.role='管理员';
assert.equal(accountContext.canAction('system.backup'),true);
// 没有 access_catalog 的老服务才回落到旧表，避免整页按钮全部消失。
const legacyContext={data:{},role:'会计'};
vm.createContext(legacyContext);
vm.runInContext(code+'\nthis.canAction=canAction;',legacyContext);
assert.equal(legacyContext.canAction('system.backup'),true);
console.log('canAction pilot ok');
