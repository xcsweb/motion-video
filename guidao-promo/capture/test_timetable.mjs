import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:2});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running,null,{timeout:120000});
await page.waitForTimeout(3500);
console.log(await page.evaluate(()=>document.body.innerText.slice(0,1200)));
const tabs=await page.evaluate(()=>[...document.querySelectorAll('button')].map(b=>b.innerText.trim()).filter(Boolean).slice(0,50));
console.log('BUTTONS',JSON.stringify(tabs));
// try opening line 2 and timetable
try{ await page.getByText('2号线',{exact:false}).first().click({timeout:5000}); }catch(e){ console.log('line click fail',e.message); }
await page.waitForTimeout(1000);
try{ await page.getByText('时刻表',{exact:false}).first().click({timeout:5000}); }catch(e){ console.log('tab click fail',e.message); }
await page.waitForTimeout(1500);
const info=await page.evaluate(()=>[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&e.textContent?.includes('时刻表')).map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.trim()})).slice(0,10));
console.log('INFO',JSON.stringify(info));
await page.screenshot({path:'/workspace/guidao-promo/assets/ui/timetable_full.png'});
await browser.close();
