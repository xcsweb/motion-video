from playwright.sync_api import sync_playwright
import time, os
OUT="/workspace/rail-promo/out/prev"; os.makedirs(OUT,exist_ok=True)
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader"])
    pg=b.new_page(viewport={"width":1280,"height":720})
    pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
    pg.wait_for_function("window.__viewer", timeout=90000); time.sleep(6)
    print(pg.evaluate("""()=>{
      const s=document.createElement('style');s.textContent='.ui-layer,.labels-layer{display:none!important}';document.head.appendChild(s);
      const v=window.__viewer; v.clock.paused=true; v.clock.timeSec=74000;
      window.__api.setQuality('high');
      const tr=v.timetable.sample(74000).filter(t=>t.status==='running');
      return {n:tr.length, sample:tr.slice(0,8).map(t=>({id:t.id,line:t.lineId,dir:t.direction,dist:Math.round(t.distance)}))};
    }"""))
    time.sleep(3)
    poses=[("xsz_close",[2380,420,420],[2833,230,-198],55),
           ("lzb_tight",[-1700,280,620],[-1557,225,483],50),
           ("river2",[-300,520,-1250],[-1080,200,-387],55)]
    for n,pos,tgt,fov in poses:
        pg.evaluate("""([pos,tgt,fov])=>{const v=window.__viewer;
          v.camera.position.set(...pos);v.camera.fov=fov;v.camera.updateProjectionMatrix();
          v.cameraController.controls.target.set(...tgt);v.camera.lookAt(...tgt);v.cameraController.controls.update();}""",[pos,tgt,fov])
        time.sleep(0.8); pg.screenshot(path=f"{OUT}/{n}.png"); print("shot",n)
    # follow trains
    ids=pg.evaluate("()=>window.__viewer.timetable.sample(74000).filter(t=>t.status==='running').map(t=>t.id+'|'+t.lineId)")
    for want,line in [("pov_l2","L2"),("pov_l6","L6")]:
        tid=[i for i in ids if line in i]
        if tid:
            pg.evaluate("(id)=>window.__api.followTrain(id)", tid[0])
            time.sleep(2); pg.screenshot(path=f"{OUT}/{want}.png"); print("shot",want,tid[0])
            pg.evaluate("()=>window.__api.followTrain(null)")
            time.sleep(1)
    b.close()
