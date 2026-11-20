import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const OUT='/workspace/guidao-promo/assets/3d';
const scenes=[
  
  {name:'cab_platform', id:'2-1-21600', start:21937},
  {name:'cab_bridge', id:'3-0-21600', start:24217},
];
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:960,height:540},deviceScaleFactor:1});
page.on('pageerror',e=>console.log('PAGE_ERR',e.message));
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('low'); v.renderer.setPixelRatio(1); v.resize();
});
for(const sc of scenes){
  const dir=path.join(OUT,sc.name); fs.mkdirSync(dir,{recursive:true});
  const t0=Date.now();
  const meta=await page.evaluate(([id,start])=>{
    const v=window.__viewer;
    v.clock.timeSec=start;
    v.api.followTrain(id);
    for(let i=0;i<4;i++){const now=performance.now();v.lastFrame=now-33.34;v.running=true;v.loop(now);v.running=false;cancelAnimationFrame(v.raf);}
    v.cameraController.followBlend=1;
    const tr=v.timetable.sample(start).find(t=>t.id===id);
    const g=v.transit.geometries.get(tr.lineId);
    const s=tr.direction===0?tr.distance:g.length-tr.distance;
    return {tunnel:g.isInsideTunnel(s+18.6), line:tr.lineId};
  },[sc.id,sc.start]);
  console.log(sc.name,'tunnel',meta.tunnel);
  for(let i=0;i<45;i++){
    const d=await page.evaluate(([id,start,i,tunnel])=>{
      const v=window.__viewer;
      const t=start+i*0.12;
      v.clock.timeSec=t;
      const tr=v.timetable.sample(t).find(x=>x.id===id);
      const pose=v.trains.poseOf(tr,v.transit.geometries);
      const eye=tunnel?2.5:2.7;
      v.camera.position.set(pose.x,pose.y+eye,pose.z);
      v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
      v.camera.updateProjectionMatrix();
      v.renderer.render(v.scene,v.camera);
      return v.renderer.domElement.toDataURL('image/jpeg',0.93);
    },[sc.id,sc.start,i,meta.tunnel]);
    fs.writeFileSync(path.join(dir,`f_${String(i).padStart(4,'0')}.jpg`),Buffer.from(d.split(',')[1],'base64'));
    if(i%10===0) console.log(sc.name,i);
  }
  console.log(sc.name,'done',((Date.now()-t0)/1000).toFixed(0)+'s');
}
await browser.close();
