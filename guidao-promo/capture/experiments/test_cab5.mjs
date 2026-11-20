import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && typeof window.__api==='object',null,{timeout:120000});
await page.waitForTimeout(2500);
const shots=await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('high'); v.renderer.setPixelRatio(1); v.resize();
  const train=v.currentTrains.find(t=>t.id==='2-0-43080');
  const pose=v.trains.poseOf(train,v.transit.geometries);
  v.transit.visuals.forEach(vis=>{if(vis.core)vis.core.visible=false;if(vis.glow)vis.glow.visible=false;if(vis.aura)vis.aura.visible=false;if(vis.overview)vis.overview.visible=false;});
  v.transit.labelGroup.visible=false;
  const out=[];
  for(const [h,dist,drop] of [[4.5,60,2],[3.2,45,1.2],[6,90,3]]){
    v.camera.position.set(pose.x,pose.y+h,pose.z);
    v.camera.lookAt(pose.x+pose.tx*dist,pose.y+drop,pose.z+pose.tz*dist);
    v.camera.updateProjectionMatrix();
    v.renderer.render(v.scene,v.camera);
    out.push(v.renderer.domElement.toDataURL('image/jpeg',0.95));
  }
  return out;
});
shots.forEach((u,i)=>fs.writeFileSync(`/workspace/guidao-promo/assets/3d/cab_v${i+1}.jpg`,Buffer.from(u.split(',')[1],'base64')));
console.log('done',shots.length);
await browser.close();
