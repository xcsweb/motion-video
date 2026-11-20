import { chromium } from 'playwright';
import fs from 'node:fs';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
page.on('pageerror',e=>console.log('PAGE_ERR',e.message));
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && typeof window.__api==='object',null,{timeout:120000});
await page.waitForTimeout(3000);
const info=await page.evaluate(()=>{
  const v=window.__viewer;
  const list=v.currentTrains.filter(t=>t.lineId==='2').map(t=>({id:t.id,code:t.code,status:t.status,distance:t.distance,next:t.nextStationName,direction:t.direction,speed:t.speedKph}));
  return list.slice(0,8);
});
console.log(JSON.stringify(info,null,2));
await page.evaluate(()=>{
  const v=window.__viewer;
  cancelAnimationFrame(v.raf); v.running=false; v.clock.paused=true;
  v.autoDegraded=true; v.applyQuality('high'); v.renderer.setPixelRatio(1); v.resize();
});
const id=info[0]?.id;
console.log('picked',id);
if(id){
  await page.evaluate((id)=>{
    const v=window.__viewer;
    v.api.followTrain(id);
    for(let i=0;i<80;i++){
      v.clock.timeSec += 1/30;
      const now=performance.now(); v.lastFrame=now-33.34;
      v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
    }
  },id);
  await page.waitForTimeout(200);
  const d=await page.evaluate(()=>{
    const v=window.__viewer;
    const now=performance.now(); v.lastFrame=now-33.34;
    v.running=true; v.loop(now); v.running=false; cancelAnimationFrame(v.raf);
    return {url:v.renderer.domElement.toDataURL('image/jpeg',0.95), cam:v.camera.position.toArray(), target:v.cameraController.controls.target.toArray(), tunnel:v.tunnelActiveView};
  });
  console.log('cam',d.cam,'target',d.target,'tunnel',d.tunnel);
  fs.writeFileSync('/workspace/guidao-promo/assets/3d/cab_test.jpg',Buffer.from(d.url.split(',')[1],'base64'));
}
await browser.close();
