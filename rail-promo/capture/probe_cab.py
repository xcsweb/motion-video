#!/usr/bin/env python3
"""Shoot one cab-view still approaching a chosen station."""
import sys
from playwright.sync_api import sync_playwright

WANT = sys.argv[1] if len(sys.argv) > 1 else "牛角沱"
ETA = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0

FIND = """
(args) => {
  const v = window.__viewer;
  const base = v.clock.timeSec;
  const out = [];
  for (let dt = 0; dt < 1800; dt += 0.5) {
    const ts = (base + dt) % 86400;
    for (const tr of v.timetable.sample(ts)) {
      if (tr.lineId !== '2') continue;
      if (tr.nextStationName !== args.want) continue;
      if (tr.status !== 'arriving') continue;
      if (tr.etaSec >= args.eta && tr.etaSec <= args.eta + 1) {
        out.push({ ts, id: tr.id, next: tr.nextStationName, eta: +tr.etaSec.toFixed(1) });
      }
    }
    if (out.length > 20) break;
  }
  return out;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("http://localhost:5173/", wait_until="load")
    pg.wait_for_function("() => window.__viewer && window.__api", timeout=120000)
    pg.wait_for_timeout(6000)
    pg.evaluate("""() => {
      const v = window.__viewer;
      window.__api.setQuality('high');
      v.evaluateAutoQuality = () => {};
      v.resolutionScale = 1;
      v.renderer.setPixelRatio(1);
      v.renderer.setSize(1920, 1080, false);
      return true;
    }""")
    cands = pg.evaluate(FIND, {"want": WANT, "eta": ETA})
    print("cands", len(cands), cands[:4], flush=True)
    if not cands:
        b.close()
        raise SystemExit(1)
    pick = cands[0]
    pg.evaluate("""(ts) => {
      const v = window.__viewer;
      v.clock.setPaused(true);
      v.clock.timeSec = ts;
      return true;
    }""", pick["ts"])
    pg.wait_for_timeout(1200)
    tid = pg.evaluate("(id) => (window.__viewer.currentTrains.find(t=>t.id===id)||{}).id", pick["id"])
    pg.evaluate("(id) => window.__api.followTrain(id)", tid)
    pg.wait_for_timeout(600)
    pg.evaluate("""() => {
      const v = window.__viewer;
      v.cameraController.followBlend = 1;
      document.querySelector('.ui-layer').style.display = 'none';
      v.transit.group.visible = false;
      return true;
    }""")
    pg.wait_for_timeout(4000)
    print(pg.evaluate("""() => {
      const v = window.__viewer;
      return {cam: v.camera.position.toArray().map(n=>Math.round(n)),
              mode: v.cameraController.mode, overview: v.transit.overview};
    }"""), flush=True)
    pg.screenshot(path="/tmp/cab_snap2.jpg", timeout=180000)
    print("ok", flush=True)
    b.close()
