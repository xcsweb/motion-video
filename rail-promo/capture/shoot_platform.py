#!/usr/bin/env python3
import base64, os, sys
from playwright.sync_api import sync_playwright

OUT = "/workspace/rail-promo/out/freecam"
os.makedirs(OUT, exist_ok=True)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 0

SETUP = """
() => {
  const s = document.createElement('style');
  s.textContent = '.ui-layer,.labels-layer{display:none!important}';
  document.head.appendChild(s);
  const v = window.__viewer;
  v.clock.paused = true;
  v.clock.timeSec = 74000;
  window.__api.setQuality('high');
  window.__api.selectLine(null);
  v.evaluateAutoQuality = () => {};
  v.resolutionScale = 1;
  v.renderer.setPixelRatio(1);
  v.renderer.setSize(1920, 1080, false);
  window.__api.enterPlatformView('st-20');

  return true;
}
"""

FIND = """
([lineId, d, t0]) => {
  const v = window.__viewer;
  const geos = v.transit.geometries;
  for (let t = t0; t < t0 + 900; t += 2) {
    const all = v.timetable.sample(t).filter(x => String(x.lineId) === lineId && x.status !== 'idle');
    for (const tr of all) {
      const p = v.trains.poseOf(tr, geos);
      if (!p) continue;
      const gap = d - tr.distance;
      if (gap > 20 && gap < 220) return { t, id: tr.id, gap };
    }
  }
  return null;
}
"""

GRAB = "()=>{const v=window.__viewer;v.renderer.render(v.scene,v.camera);return v.canvas.toDataURL('image/jpeg',0.95)}"

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("http://localhost:5173/", wait_until="load")
    pg.wait_for_function("() => window.__viewer && window.__api", timeout=120000)
    pg.wait_for_timeout(6000)
    pg.evaluate(SETUP)
    pg.wait_for_timeout(2500)
    f = pg.evaluate(FIND, ["3", 26169, 72000])
    print("found", f, flush=True)
    if not f:
        sys.exit(1)
    if N == 0:
        for k, dt in enumerate((10, 12, 14, 16)):
            pass
        for k, dt in enumerate((10, 12, 14, 16)):
            pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", f["t"] + dt)
            pg.wait_for_timeout(1200)
            d = pg.evaluate(GRAB).split(",", 1)[1]
            open(f"{OUT}/plat_{k}.jpg", "wb").write(base64.b64decode(d))
    else:
        out = "/workspace/rail-promo/out/frames/05_platform"
        os.makedirs(out, exist_ok=True)
        for i in range(N):
            pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", f["t"] + i / 30)
            pg.evaluate("()=>new Promise(r=>requestAnimationFrame(r))")
            d = pg.evaluate(GRAB).split(",", 1)[1]
            open(f"{out}/f_{i:04d}.jpg", "wb").write(base64.b64decode(d))
            if i % 12 == 0:
                print(i, flush=True)
    b.close()
