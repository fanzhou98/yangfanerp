const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{},document:{getElementById:()=>null}};vm.createContext(context);vm.runInContext(fs.readFileSync('web/print.js','utf8'),context);
const sum=context.window.ERPPrint.sumDecimal;
assert.equal(sum(['0.1','0.2']),'0.3');assert.equal(sum(['-1.125','2.125']),'1');assert.equal(sum(['99999999999999999999.9','0.1']),'100000000000000000000');assert.equal(sum([]),'0');assert.equal(sum(['0.000001','0.000002']),'0.000003');assert.equal(sum(['1e3']),null);assert.equal(sum(['not-a-number']),null);
assert.equal(typeof context.window.ERPPrint.open,'function');assert.equal(typeof context.window.ERPPrint.mount,'function');
console.log('通用打印组件接口及小数、负数、超安全整数的精确合计通过');
