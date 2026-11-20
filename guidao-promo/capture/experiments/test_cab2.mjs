import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && typeof window.__api==='object',null,{timeout:120000});
await page.waitForTimeout(3000);
await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('high'); v.renderer.setPixelRatio(1); v.resize();
  v.api.followTrain('2-0-43080');
  for(let i=0;i<120;i++){
    v.clock.timeSec += 1/30;
    const now=performance.now(); v.lastFrame=now-33.34;
    v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
  }
});
await page.waitForTimeout(300);
const d=await page.evaluate(()=>{
  const v=window.__viewer;
  const now=performance.now(); v.lastFrame=now-33.34;
  v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
  return {url:v.renderer.domElement.toDataURL('image/jpeg',0.95),cam:v.camera.position.toArray(),target:v.cameraController.controls.target.toArray(),tunnel:v.tunnelActiveView};
});
console.log('cam',d.cam,'target',d.target,'tunnel',d.tunnel);
fs.writeFileSync('/workspace/guidao-promo/assets/3d/cab_test.jpg',Buffer.from(d.url.split(',')[1],'base64'));
await browser.close();
