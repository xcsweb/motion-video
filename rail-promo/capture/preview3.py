from playwright.sync_api import sync_playwright
import time, os
OUT="/workspace/rail-promo/out/prev"
with sync_playwright() as p:
    b=p.chromium.launch(args=["--use-gl=swiftshader","--enable-unsafe-swiftshader"])
    pg=b.new_page(viewport={"width":1280,"height":720})
    pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
    pg.wait_for_function("window.__viewer", timeout=90000); time.sleep(6)
    st=pg.evaluate("""()=>{
      const s=document.createElement('style');s.textContent='.ui-layer,.labels-layer{display:none!important}';document.head.appendChild(s);
      const v=window.__viewer; v.clock.paused=true; v.clock.timeSec=74000; window.__api.setQuality('high');
      const net=v.loaded.network;
      return Object.fromEntries(['李子坝','牛角沱','小什字','大剧院','千厮门'].map(n=>[n,net.stations.filter(x=>x.name===n).map(x=>x.id)]));
    }""")
    print("stations",st)
    for sid,name in [("st-lzb","p_lzb")]:
        pass
    # platform 李子坝
    lzb=st.get('李子坝') or []
    if lzb:
        pg.evaluate("(sid)=>window.__api.enterPlatformView(sid)", lzb[0]); time.sleep(3)
        pg.screenshot(path=f"{OUT}/platform_lzb.png"); print("shot platform_lzb", lzb[0])
        pg.evaluate("()=>window.__api.exitPlatformView()"); time.sleep(1)
    for line,name in [("2","pov2"),("6","pov6")]:
        tid=pg.evaluate("(line)=>{const tr=window.__viewer.timetable.sample(74000).filter(t=>t.status==='running'&&t.lineId===line);return tr.length?tr[0].id:null}", line)
        if tid:
            pg.evaluate("(id)=>window.__api.followTrain(id)", tid); time.sleep(3)
            print("follow",tid, pg.evaluate("()=>({follow:window.__viewer.followId, dist:window.__viewer.camera.position.toArray()})"))
            pg.screenshot(path=f"{OUT}/{name}.png")
            pg.evaluate("()=>window.__api.followTrain(null)"); time.sleep(1)
    b.close()
