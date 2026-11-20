import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
const OUT='/workspace/guidao-promo/assets/3d';
const scenes=[
  {name:'cab_tunnel', id:'1-1-21600', start:21637, tunnel:true},
  {name:'cab_platform', id:'2-1-21600', start:21937, tunnel:false},
  {name:'cab_bridge', id:'3-0-21600', start:24217, tunnel:false},
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
  v.autoDegraded=true; v.applyQuality('medium'); v.renderer.setPixelRatio(1); v.resize();
});
for(const sc of scenes){
  const dir=path.join(OUT,sc.name); fs.mkdirSync(dir,{recursive:true});
  const t0=Date.now();
  for(let i=0;i<45;i++){
    const d=await page.evaluate(([id,start,i,tunnel])=>{
      const v=window.__viewer;
      const t=start+i*0.12;
      v.clock.timeSec=t;
      const tr=v.timetable.sample(t).find(x=>x.id===id);
      const geo=v.transit.geometries.get(tr.lineId);
      const s=tr.direction===0?tr.distance:geo.length-tr.distance;
      const cameraS=s+(tr.direction===0?18.6:-18.6);
      if(tunnel){
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
      }else{
        v.tunnel.update(null,0,0,false);
        v.tunnel.group.visible=false;
        v.transit.group.visible=true;
        v.transit.labelGroup.visible=false;
        v.stationDetail.group.visible=true;
        v.buildings.setVisible(true);
        v.water.setVisible(true);
        v.vegetation.setVisible(true);
      }
      const pose=v.trains.poseOf(tr,v.transit.geometries);
      const eye=tunnel?2.5:2.7;
      v.camera.position.set(pose.x,pose.y+eye,pose.z);
      v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
      v.camera.updateProjectionMatrix();
      v.renderer.render(v.scene,v.camera);
      return v.renderer.domElement.toDataURL('image/jpeg',0.93);
    },[sc.id,sc.start,i,sc.tunnel]);
    fs.writeFileSync(path.join(dir,`f_${String(i).padStart(4,'0')}.jpg`),Buffer.from(d.split(',')[1],'base64'));
    if(i%10===0) console.log(sc.name,i);
  }
  console.log(sc.name,'done',((Date.now()-t0)/1000).toFixed(0)+'s');
}
await browser.close();
