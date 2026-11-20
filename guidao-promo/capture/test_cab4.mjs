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
  v.autoDegraded=true; v.applyQuality('high'); v.renderer.setPixelRatio(1); v.resize();
  const train=v.currentTrains.find(t=>t.id==='2-0-43080');
  const pose=v.trains.poseOf(train,v.transit.geometries);
  v.transit.visuals.forEach(vis=>{
    if(vis.core) vis.core.visible=false;
    if(vis.glow) vis.glow.visible=false;
    if(vis.aura) vis.aura.visible=false;
    if(vis.overview) vis.overview.visible=false;
  });
  v.transit.labelGroup.visible=false;
  v.camera.position.set(pose.x, pose.y+8, pose.z);
  v.camera.lookAt(pose.lookX, pose.lookY+6, pose.lookZ);
  v.camera.updateProjectionMatrix();
  v.renderer.render(v.scene,v.camera);
  return {url:v.renderer.domElement.toDataURL('image/jpeg',0.95),pose};
});
console.log('pose',r.pose);
fs.writeFileSync('/workspace/guidao-promo/assets/3d/cab_clean.jpg',Buffer.from(r.url.split(',')[1],'base64'));
await browser.close();
