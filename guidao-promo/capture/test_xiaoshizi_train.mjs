import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:960,height:540},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
const out=await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
  v.api.enterPlatformView('st-47');
  for(let i=0;i<6;i++){const now=performance.now();v.lastFrame=now-33.34;v.running=true;v.loop(now);v.running=false;cancelAnimationFrame(v.raf);}
  const arr=[];
  for(const t of [22996,22999,23002]){
    v.clock.timeSec=t;
    const trains=v.timetable.sample(t);
    v.trains.update(trains,v.transit.geometries,v.camera);
    v.renderer.render(v.scene,v.camera);
    arr.push({t,url:v.renderer.domElement.toDataURL('image/jpeg',0.95)});
  }
  return arr;
});
out.forEach((o,i)=>{console.log(o.t);fs.writeFileSync(`/workspace/guidao-promo/assets/3d/xiaoshizi_train_${i}.jpg`,Buffer.from(o.url.split(',')[1],'base64'));});
await browser.close();
