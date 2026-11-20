import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const OUT='/workspace/guidao-promo/assets/3d/line6_arrival_hd';
fs.mkdirSync(OUT,{recursive:true});
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
});
for(let i=0;i<60;i++){
  const d=await page.evaluate((i)=>{
    const v=window.__viewer;
    const t=22978+i*0.15;
    v.clock.timeSec=t;
    const tr=v.timetable.sample(t).find(x=>x.id==='6-0-21600');
    const geo=v.transit.geometries.get('6');
    const s=tr.direction===0?tr.distance:geo.length-tr.distance;
    v.tunnel.update(geo,s,tr.direction,true);
    v.tunnel.group.visible=true;
    v.transit.group.visible=false;
    v.transit.labelGroup.visible=false;
    v.stationDetail.group.visible=false;
    v.buildings.setVisible(false);
    v.water.setVisible(false);
    v.vegetation.setVisible(false);
    v.terrain.group.visible=true;
    v.portals.group.visible=true;
    v.trains.setOverviewMode(false);
    v.trains.group.visible=false;
    v.trains.points.visible=false;
    const pose=v.trains.poseOf(tr,v.transit.geometries);
    v.camera.position.set(pose.x,pose.y+2.5,pose.z);
    v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
    v.camera.updateProjectionMatrix();
    v.renderer.render(v.scene,v.camera);
    return v.renderer.domElement.toDataURL('image/jpeg',0.93);
  },i);
  fs.writeFileSync(path.join(OUT,`f_${String(i).padStart(4,'0')}.jpg`),Buffer.from(d.split(',')[1],'base64'));
  if(i%15===0) console.log(i);
}
console.log('done');
await browser.close();
