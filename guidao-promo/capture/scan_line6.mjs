import { chromium } from 'playwright';
const browser=await chromium.launch({args:['--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
const page=await browser.newPage({viewport:{width:1280,height:720},deviceScaleFactor:1});
await page.goto('http://localhost:5173/',{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForFunction(()=>window.__viewer?.running && window.__api,null,{timeout:120000});
await page.waitForTimeout(2500);
const r=await page.evaluate(()=>{
  const v=window.__viewer; const out=[]; const want=['小什字','大剧院','红旗河沟','冉家坝','红土地','黄泥塝','花卉园','大龙山','光电园','江北城'];
  const g=v.transit.geometries.get('6');
  const stations=(g?.stations||[]).map(s=>({name:s.name,s:s.s}));
  for(let t=6*3600;t<23*3600;t+=10){
    const trains=v.timetable.sample(t).filter(x=>x.lineId==='6');
    for(const tr of trains){
      if(tr.status!=='dwelling') continue;
      const s=tr.direction===0?tr.distance:g.length-tr.distance;
      if(!g.isInsideTunnel(s)) continue;
      let best=null,bd=1e9;
      for(const st of stations){const d=Math.abs(st.s-s);if(d<bd){bd=d;best=st;}}
      if(!want.includes(best?.name)) continue; out.push({t,id:tr.id,next:tr.nextStationName,status:tr.status,s:Math.round(s),station:best?.name,dist:Math.round(bd)});
      if(out.length>=10) return out;
    }
  }
  return out;
});
console.log(JSON.stringify(r,null,2));
await browser.close();
