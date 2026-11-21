from playwright.sync_api import sync_playwright
import time, json
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
      for(const t of tr){const p=v.trains.poseOf(t,geos); if(p) out.push({id:t.id,line:t.lineId,...p});}
      window.__poses=out;
      const res={};
      for(const line of ['2','3','6','loop']){
        const c=out.filter(p=>p.line===line).sort((a,b)=>(Math.abs(a.x)+Math.abs(a.z))-(Math.abs(b.x)+Math.abs(b.z)));
        res[line]=c.slice(0,2).map(p=>({id:p.id,x:Math.round(p.x),y:Math.round(p.y),z:Math.round(p.z)}));
      }
      return res;
    }""")
    print(json.dumps(info,ensure_ascii=False))
    for line,cands in info.items():
        for t in cands[:1]:
            pg.evaluate("""([id])=>{
              const v=window.__viewer; v.clock.timeSec=74000;
              const p=window.__poses.find(x=>x.id===id);
              const rx=p.tz, rz=-p.tx;
              const d=26;
              v.camera.position.set(p.x+rx*d, p.y+9, p.z+rz*d);
              v.camera.fov=50;v.camera.updateProjectionMatrix();
              v.cameraController.controls.target.set(p.x,p.y+2.2,p.z);
              v.camera.lookAt(p.x,p.y+2.2,p.z);v.cameraController.controls.update();
            }""",[t['id']])
            time.sleep(1.2)
            pg.screenshot(path=f"{OUT}/near_{line}.png"); print("shot",line,t['id'])
    b.close()
