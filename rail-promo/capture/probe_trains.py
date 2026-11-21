#!/usr/bin/env python3
"""Find a train approaching a station and inspect the cab-view framing."""
from playwright.sync_api import sync_playwright

SETUP = """
() => {
  const v = window.__viewer;
  window.__api.setQuality('high');
  v.evaluateAutoQuality = () => {};
  v.resolutionScale = 1;
  v.renderer.setPixelRatio(1);
  v.renderer.setSize(1920, 1080, false);
  return true;
}
"""

FIND = """
() => {
  const v = window.__viewer;
  const base = v.clock.timeSec;
  const out = [];
  for (let dt = 0; dt < 1200; dt += 0.5) {
    const ts = (base + dt) % 86400;
    const trains = v.timetable.sample(ts);
    for (const tr of trains) {
      if (tr.status === 'arriving' && tr.etaSec >= 4 && tr.etaSec <= 7) {
        out.push({ dt, ts, id: tr.id, line: tr.lineId, name: tr.lineName,
                   next: tr.nextStationName, eta: tr.etaSec, dist: tr.distance,
                   speed: tr.speedKph });
      }
    }
    if (out.length > 400) break;
  }
  out.sort((a, b) => {
    const pref = (x) => (x.line === '2' ? 0 : x.line === '3' ? 1 : 2);
    return pref(a) - pref(b) || a.eta - b.eta;
  });
  return out.slice(0, 12);
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("http://localhost:5173/", wait_until="load")
    pg.wait_for_function("() => window.__viewer && window.__api", timeout=120000)
    pg.wait_for_timeout(6000)
    pg.evaluate(SETUP)

    cands = pg.evaluate(FIND)
    for c in cands:
        print(c, flush=True)
    if not cands:
        print("no candidates")
        b.close()
        raise SystemExit(0)

    pick = cands[0]
    print("PICK", pick, flush=True)
    pg.evaluate(
        """(t) => {
      const v = window.__viewer;
      v.clock.setPaused(true);
      v.clock.timeSec = t;
      return true;
    }""",
        pick["ts"],
    )
    pg.wait_for_timeout(1500)
    trains = pg.evaluate("() => window.__viewer.currentTrains.map(t=>({id:t.id,line:t.lineId,eta:+t.etaSec.toFixed(1),next:t.nextStationName,st:t.status}))")
    print("trains", [t for t in trains if t["line"] == pick["line"]][:8], flush=True)
    target = next((t for t in trains if t["line"] == pick["line"] and t["next"] == pick["next"]), None)
    if not target:
        target = next((t for t in trains if t["line"] == pick["line"]), None)
    print("follow", target, flush=True)
    pg.evaluate("(id) => window.__api.followTrain(id)", target["id"])
    pg.wait_for_timeout(4000)
    pg.screenshot(path="/tmp/cab_test.jpg", timeout=180000)
    print("shot ok", flush=True)
    b.close()
