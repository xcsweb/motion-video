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
  v.api.enterPlatformView('st-90');
  for(let i=0;i<6;i++){const now=performance.now();v.lastFrame=now-33.34;v.running=true;v.loop(now);v.running=false;cancelAnimationFrame(v.raf);}
  v.clock.timeSec=23130;
  const trains=v.timetable.sample(23130);
  v.trains.update(trains,v.transit.geometries,v.camera);
  v.renderer.render(v.scene,v.camera);
  const withRibbon=v.renderer.domElement.toDataURL('image/jpeg',0.95);
  v.transit.visuals.forEach(vis=>{for(const k of ['core','glow','aura','overview']) if(vis[k]) vis[k].visible=false;});
  v.renderer.render(v.scene,v.camera);
  const noRibbon=v.renderer.domElement.toDataURL('image/jpeg',0.95);
  return {withRibbon,noRibbon};
});
fs.writeFileSync('/workspace/guidao-promo/assets/3d/dajuyuan_arrival_ribbon.jpg',Buffer.from(out.withRibbon.split(',')[1],'base64'));
fs.writeFileSync('/workspace/guidao-promo/assets/3d/dajuyuan_arrival_noribbon.jpg',Buffer.from(out.noRibbon.split(',')[1],'base64'));
await browser.close();
