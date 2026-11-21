#!/usr/bin/env python3
"""Diagnose follow-camera placement after following a train."""
from playwright.sync_api import sync_playwright

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
    info = pg.evaluate("""() => {
      const v = window.__viewer;
      return {
        cam: v.camera.position.toArray().map(n=>Math.round(n)),
        target: v.cameraController.controls.target.toArray().map(n=>Math.round(n)),
        mode: v.cameraController.mode,
        exag: v.exaggeration,
        overview: v.transit.overview,
        trains: v.currentTrains.filter(t=>t.lineId==='2' && t.status==='arriving').map(t=>({id:t.id,eta:+t.etaSec.toFixed(1),next:t.nextStationName})).slice(0,4),
      };
    }""")
    print("BEFORE", info, flush=True)
    tid = info["trains"][0]["id"] if info["trains"] else None
    if not tid:
        tid = pg.evaluate("() => (window.__viewer.currentTrains.find(t=>t.lineId==='2')||{}).id")
    pg.evaluate("(id) => window.__api.followTrain(id)", tid)
    for i in range(3):
        pg.wait_for_timeout(2500)
        d = pg.evaluate("""() => {
          const v = window.__viewer;
          const p = v.cameraController.followPose;
          return {
            cam: v.camera.position.toArray().map(n=>Math.round(n)),
            mode: v.cameraController.mode,
            overview: v.transit.overview,
            pose: p ? {x:Math.round(p.x),y:Math.round(p.y),z:Math.round(p.z),lookX:Math.round(p.lookX),lookY:Math.round(p.lookY),lookZ:Math.round(p.lookZ)} : null,
            followId: v.followId,
            hasTrain: !!v.currentTrains.find(t=>t.id===v.followId),
          };
        }""")
        print("T%d" % i, d, flush=True)
    pg.screenshot(path="/tmp/cab_test2.jpg", timeout=180000)
    b.close()
