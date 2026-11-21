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
      const tr=v.timetable.sample(74000).filter(t=>t.status==='running');
      const out=[];
      for(const t of tr){
        if(!['2','3','6','1'].includes(t.lineId)) continue;
        const p=v.trains.poseOf(t.id);
        if(!p) continue;
        const pos=p.pos||p.position;
        if(Math.abs(pos.x)<5000&&Math.abs(pos.z)<4000) out.push({id:t.id,line:t.lineId,x:pos.x,y:pos.y,z:pos.z,keys:Object.keys(p)});
      }
      return out.slice(0,8);
    }""")
    print(json.dumps(info,ensure_ascii=False)[:1500])
    for i,t in enumerate(info[:4]):
        pg.evaluate("""([id,x,y,z])=>{
          const v=window.__viewer;
          v.clock.timeSec=74000;
          v.camera.position.set(x+70,y+28,z+70);
          v.camera.fov=50;v.camera.updateProjectionMatrix();
          v.cameraController.controls.target.set(x,y+4,z);
          v.camera.lookAt(x,y+4,z);v.cameraController.controls.update();
        }""",[t['id'],t['x'],t['y'],t['z']])
        time.sleep(0.8)
        pg.screenshot(path=f"{OUT}/train_{t['line']}_{i}.png")
        print("shot",t['line'],t['id'])
    b.close()
