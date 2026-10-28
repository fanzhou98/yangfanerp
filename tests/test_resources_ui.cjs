const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
const reports={
 'production-month':{title:'生产月报',start:'2026-10-01',end:'2026-10-31',generated_at:'2026-11-01T08:00:00+08:00',source:'业务台账',basis:'按产品单位，不跨单位加总',registered_days:1,open_days:0,bean_kg:'10',rows:[{product_name:'豆腐',unit:'筐',normal_qty:'100',processing_qty:'5',input_qty:'30',shipped_qty:'8',loss_qty:'1'}]},
};
const c={window:{addEventListener(){}},document:{addEventListener(){}},productionWarehouseOptions:()=>[],resourceWarehouseName:()=>'',data:{products:[],resources:{items:[],entries:[],expenses:[],byproducts:[],categories:[],periods:[]},access_catalog:{modules:[]}},page:'production',role:'会计',canAction:()=>true,canSeeData:()=>false,today:()=>'2026-10-20',esc:v=>String(v??''),num:v=>String(Number(v)),yuan:v=>(Number(v)/100).toFixed(2),amount:v=>'¥'+(Number(v)/100).toFixed(2),head:(a,b)=>a+b,metrics:x=>JSON.stringify(x),factoryReport:kind=>reports[kind]?{value:reports[kind]}:{loading:true},readState:()=>'<p>读取中</p>'};
vm.createContext(c);vm.runInContext(fs.readFileSync('web/resources.js','utf8')+'\n'+fs.readFileSync('web/reports.js','utf8'),c);
const initial=c.resourceMaterialPage();assert(initial.includes('库存余额表'));assert(initial.includes('material-search'));assert(initial.includes('全部状态'));
const html=c.resourceProductionPage();assert(html.includes('2026-10-01'));assert(html.includes('100 筐'));assert(html.includes('30 公斤'));assert(html.includes('8 筐'));assert(html.includes('不跨单位加总'));
for(const points of [[],[{label:'单点',value:1}],[{label:'正值',value:1},{label:'缺失',value:null},{label:'负值',value:-1}],[{label:'极值',value:1e16}],[{label:'异常',value:NaN},{label:'溢出',value:Infinity},{label:'合法',value:1}]]){
 const chart=c.reportChart({kind:'trend',title:'测试问题',type:'cents',unit:'元',points});assert(chart.includes('data-report-chart'));assert(!chart.includes('style='));assert(!chart.includes('<svg'),'图表由统一试点组件挂载');
 const table=c.chartTable({kind:'trend',unit:'元',type:'cents',points});assert.equal(table.rows.length,points.length);assert(!JSON.stringify(table).includes('NaN'));assert(!JSON.stringify(table).includes('Infinity'));
}
const gap=c.chartTable({kind:'trend',type:'cents',points:[{label:'A',value:0},{label:'B',value:null}]});assert.notEqual(gap.rows[0][1],gap.rows[1][1]);
const bridge=c.chartTable({kind:'waterfall',type:'cents',points:[{label:'收入',value:100,start:0,end:100},{label:'成本',value:-50,start:100,end:50}]});assert(bridge.rows[1][2].includes('0.5'));
console.log('服务端报表契约、试点组件挂载、真实零与未知、瀑布累计表检查通过');
