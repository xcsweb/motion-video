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
  v.transit.visuals.forEach(vis=>{
    if(vis.glow) vis.glow.visible=false;
    if(vis.aura) vis.aura.visible=false;
    if(vis.overview) vis.overview.visible=false;
    if(vis.core && vis.core.material){vis.core.material.transparent=true;vis.core.material.opacity=0.22;}
  });
  function shot(id,t){
    v.clock.timeSec=t;
    const tr=v.timetable.sample(t).find(x=>x.id===id);
    const pose=v.trains.poseOf(tr,v.transit.geometries);
    v.camera.position.set(pose.x,pose.y+2.7,pose.z);
    v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
    v.camera.updateProjectionMatrix();
    v.renderer.render(v.scene,v.camera);
    return v.renderer.domElement.toDataURL('image/jpeg',0.95);
  }
  return {platform:shot('2-1-21600',21942),bridge:shot('3-0-21600',24221)};
});
fs.writeFileSync('/workspace/guidao-promo/assets/3d/test_platform_opacity.jpg',Buffer.from(out.platform.split(',')[1],'base64'));
fs.writeFileSync('/workspace/guidao-promo/assets/3d/test_bridge_opacity.jpg',Buffer.from(out.bridge.split(',')[1],'base64'));
await browser.close();
