import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:960,height:540},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
for(const [id,name] of [['st-22','daxigou'],['st-19','liziba'],['st-64','tongyuanju']]){
  const d=await page.evaluate(([id])=>{
    const v=window.__viewer;
    cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
    v.autoDegraded=true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
    v.api.enterPlatformView(id);
    for(let i=0;i<25;i++){const now=performance.now();v.lastFrame=now-33.34;v.running=true;v.loop(now);v.running=false;cancelAnimationFrame(v.raf);}
    return {url:v.renderer.domElement.toDataURL('image/jpeg',0.95),cam:v.camera.position.toArray(),mode:v.appState?.platformStation};
  },[id]);
  console.log(name,d.cam);
  fs.writeFileSync(`/workspace/guidao-promo/assets/3d/platform_${name}.jpg`,Buffer.from(d.url.split(',')[1],'base64'));
}
await browser.close();
