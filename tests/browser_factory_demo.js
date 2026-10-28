const {chromium}=require(process.env.ERP_PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'chrome',headless:true});try{
 const page=await browser.newPage({viewport:{width:1512,height:1050}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.ERP_FACTORY_DEMO_URL||'http://127.0.0.1:8766');await page.getByRole('heading',{name:'豆腐磨浆 · 用豆对照',exact:true}).waitFor();
 assert.equal(await page.evaluate(()=>data.demo_context.business_date),'2026-10-20');assert((await page.locator('.notice').innerText()).includes('演示数据'));assert.equal(await page.locator('#content > section.panel').last().locator('h2').first().innerText(),'生产换算依据');
 const report=await page.evaluate(async()=>api('/api/factory/report?kind=daily&date=2026-10-20'));assert.equal(report.systems[0].issued_kg,'1000');assert.equal(report.systems[1].issued_kg,'500');assert.equal(report.products.find(p=>p.product_id==='P004').derived_qty,'180');assert.equal(report.products.find(p=>p.product_id==='P004').yield_with_scrap,'3.66');assert(report.products.every(p=>p.output_status==='已日结'));assert.equal(report.scrap_total_kg,'30');
 await page.screenshot({path:path.resolve(__dirname,'../docs/v0.31.1一天示例日报.png'),fullPage:true});await page.screenshot({path:path.resolve(__dirname,'../docs/v0.31.1日报首屏.png')});
 const go=async name=>{await page.locator(name==='settlements'?'#nav [data-act=pending-settlements]':`#nav [data-page="${name}"]`).click();await page.waitForFunction(n=>page===n&&!navigationLoading,name);};
 await go('attendance');assert.equal(await page.locator('.attendance-person').count(),12);assert.equal(await page.locator('.attendance-person.status-half').count(),1);await page.screenshot({path:path.resolve(__dirname,'../docs/v0.31.1一天示例考勤.png'),fullPage:true});
 await go('soy-inventory');assert((await page.locator('#content').innerText()).includes('演示黄豆'));await page.screenshot({path:path.resolve(__dirname,'../docs/v0.31.1一天示例黄豆.png'),fullPage:true});
 await page.locator('#avatar').click();await page.locator('#role').selectOption('会计');await go('settlements');assert(await page.locator('.factory-weight-inline').count()>0);
 await go('sales-daily');await page.getByRole('heading',{name:'客户销售额',exact:true}).waitFor();
 assert.deepEqual(errors,[]);console.log(JSON.stringify({demoBanner:true,demoDate:'2026-10-20',completeStockCounts:true,derivedSkinOutput:180,skinYieldWithScrap:3.66,staff:12,twoLines:true,basisAtBottom:true,weightWarning:true,salesReport:true,browserErrors:errors}));
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1);});
