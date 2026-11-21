from playwright.sync_api import sync_playwright
import time
OUT="/workspace/rail-promo/out/prev"
V=[("A","2-0-68820",85,8,24),("B","2-0-68820",45,-2,35),("C","6-0-72720",80,5,24),("D","6-0-72240",40,2,40)]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader"])
    pg=b.new_page(viewport={"width":1280,"height":720})
    pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
    pg.wait_for_function("window.__viewer", timeout=90000); time.sleep(6)
    pg.evaluate("""()=>{
      const s=document.createElement('style');s.textContent='.ui-layer,.labels-layer{display:none!important}';document.head.appendChild(s);
      const v=window.__viewer; v.clock.paused=true; v.clock.timeSec=74000; window.__api.setQuality('high');
      const geos=v.transit.geometries; const tr=v.timetable.sample(74000).filter(t=>t.status==='running');
      window.__poses=[]; for(const t of tr){const q=v.trains.poseOf(t,geos); if(q) window.__poses.push({id:t.id,line:t.lineId,...q});}
    }""")
    for name,tid,d,h,fov in V:
        pg.evaluate("""([tid,d,h,fov])=>{
          const v=window.__viewer; v.clock.timeSec=74000;
          const p=window.__poses.find(x=>x.id===tid);
          const rx=p.tz, rz=-p.tx;
          v.camera.position.set(p.x+rx*d, p.y+h, p.z+rz*d);
          v.camera.fov=fov;v.camera.updateProjectionMatrix();
          v.cameraController.controls.target.set(p.x,p.y+2,p.z);
          v.camera.lookAt(p.x,p.y+2,p.z);v.cameraController.controls.update();
        }""",[tid,d,h,fov])
        time.sleep(1.0); pg.screenshot(path=f"{OUT}/v_{name}.png"); print("shot",name)
    b.close()
