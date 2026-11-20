import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:800,height:450},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2000);
const r=await page.evaluate(()=>{
  const v=window.__viewer; const g=v.transit.geometries.get('6');
  const st=(g.stations||[]).find(s=>s.name==='小什字');
  const out=[];
  for(let t=22850;t<23010;t+=2){
    const tr=v.timetable.sample(t).find(x=>x.id==='6-0-21600');
    if(!tr) continue;
    const s=tr.direction===0?tr.distance:g.length-tr.distance;
    const d=st.s-s;
    out.push({t,status:tr.status,next:tr.nextStationName,s:Math.round(s),dist:Math.round(d)});
  }
  return out.filter(x=>x.dist>-50&&x.dist<260);
});
console.log(JSON.stringify(r,null,2));
await browser.close();
