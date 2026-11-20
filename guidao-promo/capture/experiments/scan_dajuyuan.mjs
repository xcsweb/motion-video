import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
const r=await page.evaluate(()=>{
  const v=window.__viewer; const g=v.transit.geometries.get('6');
  const st=(g.stations||[]).find(s=>s.name==='大剧院');
  const out=[];
  for(let t=6*3600;t<23*3600;t+=5){
    for(const tr of v.timetable.sample(t).filter(x=>x.lineId==='6')){
      const s=tr.direction===0?tr.distance:g.length-tr.distance;
      const d=st.s-s;
      if(tr.nextStationName==='大剧院' && d>40 && d<600 && ['running','arriving'].includes(tr.status)){
        out.push({t,id:tr.id,status:tr.status,s:Math.round(s),distToStation:Math.round(d)});
        if(out.length>=12) return out;
      }
    }
  }
  return out;
});
console.log(JSON.stringify(r,null,2));
await browser.close();
