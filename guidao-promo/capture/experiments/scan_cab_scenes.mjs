import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
const r=await page.evaluate(()=>{
  const v=window.__viewer;
  const out={stations:{},candidates:{tunnel:[],platform:[],bridge:[]}};
  for(const id of ['1','2','3','6']){
    const g=v.transit.geometries.get(id);
    out.stations[id]=(g?.stations||[]).map(s=>({name:s.name,s:Math.round(s.s)}));
  }
  const wantTunnel=['两路口','小什字','较场口','观音桥','红旗河沟','牛角沱'];
  const wantPlatform=['李子坝','牛角沱','曾家岩','大溪沟','铜元局'];
  for(let t=6*3600;t<23*3600;t+=20){
    const trains=v.timetable.sample(t);
    for(const tr of trains){
      const g=v.transit.geometries.get(tr.lineId); if(!g) continue;
      const s=tr.direction===0?tr.distance:g.length-tr.distance;
      const cameraS=s+(tr.direction===0?18.6:-18.6);
      const tunnel=g.isInsideTunnel(cameraS);
      const item={t,id:tr.id,line:tr.lineId,next:tr.nextStationName,distance:Math.round(tr.distance),s:Math.round(s),tunnel};
      if(!tunnel && tr.lineId==='2' && wantPlatform.includes(tr.nextStationName) && out.candidates.platform.length<5) out.candidates.platform.push(item);
      if(tunnel && ['1','3','6'].includes(tr.lineId) && wantTunnel.includes(tr.nextStationName) && out.candidates.tunnel.length<5) out.candidates.tunnel.push(item);
      if(!tunnel && tr.lineId==='3' && ['铜元局','两路口'].includes(tr.nextStationName) && out.candidates.bridge.length<5) out.candidates.bridge.push(item);
    }
  }
  return out;
});
console.log(JSON.stringify(r,null,2));
await browser.close();
