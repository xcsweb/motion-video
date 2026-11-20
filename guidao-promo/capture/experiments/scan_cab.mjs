import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && typeof window.__api==='object',null,{timeout:120000});
await page.waitForTimeout(3000);
const rows=await page.evaluate(()=>{
  const v=window.__viewer;
  const out=[];
  for(const t of v.currentTrains){
    const geo=v.transit.geometries.get(t.lineId); if(!geo) continue;
    const s=t.direction===0?t.distance:geo.length-t.distance;
    const cameraS=s+(t.direction===0?18.6:-18.6);
    out.push({id:t.id,line:t.lineId,code:t.code,status:t.status,speed:t.speedKph,next:t.nextStationName,tunnel:geo.isInsideTunnel(cameraS),s:Math.round(s)});
  }
  return out;
});
console.log('total',rows.length,'open',rows.filter(r=>!r.tunnel).length);
console.log(JSON.stringify(rows.filter(r=>!r.tunnel).slice(0,20),null,2));
await browser.close();
