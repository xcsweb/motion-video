import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:2});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(3000);
await page.evaluate(()=>window.__api.selectLine('2'));
await page.waitForTimeout(1200);
console.log('tabs',await page.evaluate(()=>[...document.querySelectorAll('[role=tab]')].map(b=>b.innerText)));
try{await page.getByRole('tab',{name:/时刻表/}).click({timeout:5000});}catch(e){console.log('click fail',e.message);}
await page.waitForTimeout(1200);
console.log('panel text',await page.evaluate(()=>document.querySelector('.train-panel')?.innerText.slice(0,800)));
try{await page.locator('.train-panel').screenshot({path:'/workspace/guidao-promo/assets/ui/timetable.png',timeout:30000});console.log('saved panel');}catch(e){console.log('shot fail',e.message);}
await page.screenshot({path:'/workspace/guidao-promo/assets/ui/timetable_full.png'});
await browser.close();
