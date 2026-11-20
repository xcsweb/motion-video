import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:2});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
await page.evaluate(()=>{
  const v=window.__viewer;
  v.clock.paused=true; v.clock.timeSec=6*3600+5*60;
  for(let i=0;i<5;i++){const now=performance.now();v.lastFrame=now-33.34;v.running=true;v.loop(now);v.running=false;cancelAnimationFrame(v.raf);}
  window.__api.selectLine('2');
});
await page.waitForTimeout(1200);
const tabs=page.locator('[role=tab]');
await tabs.nth(1).evaluate(b=>b.click());
await page.waitForTimeout(1200);
console.log(await page.evaluate(()=>document.querySelector('.train-panel')?.innerText.slice(0,500)));
await page.locator('.train-panel').screenshot({path:'/workspace/guidao-promo/assets/ui/timetable_morning.png'});
await browser.close();
