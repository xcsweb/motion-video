from playwright.sync_api import sync_playwright
import time, os, json
OUT="/workspace/rail-promo/out/prev"
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader"])
    pg=b.new_page(viewport={"width":1280,"height":720})
    pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
    pg.wait_for_function("window.__viewer", timeout=90000); time.sleep(6)
    info=pg.evaluate("""()=>{
      const s=document.createElement('style');s.textContent='.ui-layer,.labels-layer{display:none!important}';document.head.appendChild(s);
      const v=window.__viewer; v.clock.paused=true; v.clock.timeSec=74000; window.__api.setQuality('high');
      const geos=v.transit.geometries;
      const tr=v.timetable.sample(74000).filter(t=>t.status==='running');
      const out=[];
      for(const t of tr){
        const p=v.trains.poseOf(t,geos);
        if(!p) continue;
        out.push({id:t.id,line:t.lineId,x:p.x,y:p.y,z:p.z,tx:p.tx,tz:p.tz,kph:p.speedKph});
      }
      window.__poses=out;
      return out.filter(p=>['2','3','6','1'].includes(p.line)).slice(0,12).map(p=>({id:p.id,line:p.line,x:Math.round(p.x),y:Math.round(p.y),z:Math.round(p.z),kph:p.kph}));
    }""")
    print(json.dumps(info,ensure_ascii=False)[:2000])
    # 选：2号线、3号线各一辆靠近市中心的
    picks=[]
    for line in ['2','3','6','1']:
        c=[p for p in info if p['line']==line]
        c.sort(key=lambda p: abs(p['x'])+abs(p['z']))
        if c: picks.append(c[0])
    for i,t in enumerate(picks):
        pg.evaluate("""([id,d])=>{
          const v=window.__viewer; v.clock.timeSec=74000;
          const p=window.__poses.find(x=>x.id===id);
          const rx=p.tz, rz=-p.tx;
          v.camera.position.set(p.x+rx*d, p.y+16, p.z+rz*d);
          v.camera.fov=45;v.camera.updateProjectionMatrix();
          v.cameraController.controls.target.set(p.x,p.y+2,p.z);
          v.camera.lookAt(p.x,p.y+2,p.z);v.cameraController.controls.update();
        }""",[t['id'], 38])
        time.sleep(0.8)
        pg.screenshot(path=f"{OUT}/tside_{t['line']}.png"); print("shot",t['line'],t['id'])
    b.close()
