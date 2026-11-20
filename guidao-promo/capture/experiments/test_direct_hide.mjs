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
  function hideLines(){
    v.transit.visuals.forEach(vis=>{
      for(const k of ['core','glow','aura','overview']) if(vis[k]) vis[k].visible=false;
    });
  }
  function shot(id,t,tunnel){
    v.clock.timeSec=t;
    const tr=v.timetable.sample(t).find(x=>x.id===id);
    const geo=v.transit.geometries.get(tr.lineId);
    const s=tr.direction===0?tr.distance:geo.length-tr.distance;
    hideLines();
    if(tunnel){
      v.tunnel.update(geo,s,tr.direction,true); v.tunnel.group.visible=true;
      v.transit.group.visible=false; v.transit.labelGroup.visible=false; v.stationDetail.group.visible=false;
      v.buildings.setVisible(false); v.water.setVisible(false); v.vegetation.setVisible(false);
    }else{
      v.tunnel.update(null,0,0,false); v.tunnel.group.visible=false;
      v.transit.group.visible=true; v.transit.labelGroup.visible=false; v.stationDetail.group.visible=true;
      v.buildings.setVisible(true); v.water.setVisible(true); v.vegetation.setVisible(true);
    }
    const pose=v.trains.poseOf(tr,v.transit.geometries);
    const eye=tunnel?2.5:2.7;
    v.camera.position.set(pose.x,pose.y+eye,pose.z);
    v.camera.lookAt(pose.lookX,pose.lookY+2.35,pose.lookZ);
    v.camera.updateProjectionMatrix();
    v.renderer.render(v.scene,v.camera);
    return v.renderer.domElement.toDataURL('image/jpeg',0.95);
  }
  return {platform:shot('2-1-21600',21937+2.4,false),tunnel:shot('1-1-21600',21637+2.4,true)};
});
fs.writeFileSync('/workspace/guidao-promo/assets/3d/test_platform_hide.jpg',Buffer.from(out.platform.split(',')[1],'base64'));
fs.writeFileSync('/workspace/guidao-promo/assets/3d/test_tunnel_hide.jpg',Buffer.from(out.tunnel.split(',')[1],'base64'));
await browser.close();
