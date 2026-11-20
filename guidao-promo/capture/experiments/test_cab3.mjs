import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && typeof window.__api==='object',null,{timeout:120000});
await page.waitForTimeout(2500);
const r=await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
  v.api.followTrain('2-0-43080');
  for(let i=0;i<40;i++){
    v.clock.timeSec += 1/30;
    const now=performance.now(); v.lastFrame=now-33.34;
    v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
  }
  const url=v.renderer.domElement.toDataURL('image/jpeg',0.95);
  return {url,cam:v.camera.position.toArray(),target:v.cameraController.controls.target.toArray(),tunnel:v.tunnelActiveView,transit:v.transit.group.visible};
});
console.log('cam',r.cam,'target',r.target,'tunnel',r.tunnel,'transit',r.transit);
fs.writeFileSync('/workspace/guidao-promo/assets/3d/cab_open.jpg',Buffer.from(r.url.split(',')[1],'base64'));
await browser.close();
