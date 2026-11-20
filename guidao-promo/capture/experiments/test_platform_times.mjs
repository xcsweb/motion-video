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
  const arr=[];
  for(const t of [21940,21945,21950,21955]){
    v.clock.timeSec=t;
    const tr=v.timetable.sample(t).find(x=>x.id==='2-1-21600');
    const pose=v.trains.poseOf(tr,v.transit.geometries);
    v.camera.position.set(pose.x,pose.y+2.7,pose.z);
    v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
    v.camera.updateProjectionMatrix();
    v.renderer.render(v.scene,v.camera);
    arr.push({t,next:tr.nextStationName,status:tr.status,url:v.renderer.domElement.toDataURL('image/jpeg',0.95)});
  }
  return arr;
});
out.forEach((o,i)=>{console.log(o.t,o.next,o.status);fs.writeFileSync(`/workspace/guidao-promo/assets/3d/platform_t${i}.jpg`,Buffer.from(o.url.split(',')[1],'base64'));});
await browser.close();
