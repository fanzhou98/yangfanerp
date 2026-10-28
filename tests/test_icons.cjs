const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict'),cp=require('node:child_process');
const ctx={window:{addEventListener(){}},document:{addEventListener(){}},localStorage:{getItem(){return null;}},moduleVisible:()=>true};vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/workspace.js','utf8'),ctx);
const modules=JSON.parse(cp.execFileSync('python3',['-c','import erp_access,json;print(json.dumps(erp_access.module_definitions()))'],{encoding:'utf8'}));
for(const module of modules){const icon=ctx.submenuModuleIcon(module);assert(icon.includes('data-icon-source="48797"'),module.id);assert(!icon.includes('data-icon-key="generic"'),module.id+' 必须明确选型');assert(icon.includes('aria-hidden="true"'));assert(!/style=|<script|<use|href=|stroke="currentColor"|icon-layer-secondary/.test(icon),module.id);}
const stock=ctx.submenuModuleIcon({id:'inventory.operations'});assert(stock.includes('data-icon-id="40121439"'));assert(stock.includes('#42B4FA'));assert(stock.includes('#92DBFF'),'库存保留原稿双色');
const purchase=ctx.submenuModuleIcon({id:'purchase.orders'});assert(purchase.includes('#FFFFFF'),'购物车细节保持白色');
for(const id of ['asset.register','asset.crates','delivery.driver'])assert(!ctx.submenuModuleIcon({id}).includes('currentColor'),id+' 不再被旧线框覆盖');
assert.notEqual(ctx.submenuModuleIcon({id:'finance.accounts'}),ctx.submenuModuleIcon({id:'finance.payables'}),'账户与付款区分');
assert.notEqual(ctx.submenuModuleIcon({id:'sales.orders'}),ctx.submenuModuleIcon({id:'sales.archive'}),'订货与销售单据区分');
assert.notEqual(ctx.submenuModuleIcon({id:'production.daily'}),ctx.submenuModuleIcon({id:'inventory.cost'}),'日报与月报区分');
assert.equal(ctx.submenuModuleIcon({page:'masters',view:'pricing'}),ctx.submenuModuleIcon({id:'master.pricing'}));
const fallback=ctx.submenuModuleIcon({id:'<script>alert(1)</script>'});assert(fallback.includes('data-icon-key="generic"'));assert(!fallback.includes('<script>'));
const sections=vm.runInContext('NAV_SECTIONS',ctx);for(const section of sections)assert(!ctx.navigationSectionIcon(section.id).includes('data-icon-key="generic"'),section.id);
assert.equal(ctx.workflowTaskIcon({key:'purchases.pay'}),ctx.submenuModuleIcon({id:'finance.payables'}),'工作台和菜单同一业务用同一图标');
console.log(`彩色图标覆盖 ${modules.length} 个模块；原色、白色细节、语义区分、旧图覆盖与工作台一致性检查通过`);

assert.notEqual(ctx.submenuModuleIcon({id:'workspace.report-map'}),ctx.navigationSectionIcon('master'),'报表地图与基础资料必须使用不同图标');assert(ctx.submenuModuleIcon({id:'workspace.report-map'}).includes('data-icon-id="40122294"'));assert(ctx.navigationFoldIcon(true).includes('menu-fold'));assert(ctx.navigationFoldIcon(false).includes('menu-unfold'));
