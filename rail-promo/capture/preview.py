from playwright.sync_api import sync_playwright
import os, time, json, sys
OUT="/workspace/rail-promo/out/prev"
os.makedirs(OUT, exist_ok=True)
POSES = [
 ("liziba_close", [-1757, 300, 633], [-1557, 240, 483], 55),
 ("liziba_far",   [-2057, 420, 933], [-1557, 230, 483], 55),
 ("aerial_low",   [ 400,  900,  700], [   0, 180, -100], 55),
 ("aerial_wide",  [-1600, 2400, 1600], [ 300, 180, -300], 55),
 ("river",        [-900, 380, -1200], [-1080, 210, -387], 55),
 ("connection",   [ 2600, 700, 300],  [ 1800, 200, -400], 55),
]
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader"])
    pg=b.new_page(viewport={"width":1280,"height":720})
    pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
    pg.wait_for_function("window.__viewer", timeout=90000)
    time.sleep(6)
    pg.evaluate("""()=>{
      const s=document.createElement('style');
      s.textContent='.ui-layer,.labels-layer{display:none!important}';
      document.head.appendChild(s);
      const v=window.__viewer; v.clock.paused=true; v.clock.timeSec=73800;
    }""")
    for name,pos,tgt,fov in POSES:
        pg.evaluate("""([pos,tgt,fov])=>{
          const v=window.__viewer;
          v.camera.position.set(...pos); v.camera.fov=fov; v.camera.updateProjectionMatrix();
          v.cameraController.controls.target.set(...tgt);
          v.camera.lookAt(...tgt); v.cameraController.controls.update();
        }""",[pos,tgt,fov])
        time.sleep(0.6)
        pg.screenshot(path=f"{OUT}/{name}.png")
        print("shot",name)
    # platform views
    for sid,name in [("st-20","platform_njt"),("st-47","platform_xsz")]:
        pg.evaluate("(sid)=>window.__api.enterPlatformView(sid)", sid)
        time.sleep(2.5)
        pg.screenshot(path=f"{OUT}/{name}.png")
        print("shot",name)
        pg.evaluate("()=>window.__api.exitPlatformView()")
        time.sleep(1)
    b.close()
