#!/usr/bin/env python3
"""Capture two UI stills (idle network / line selected) using the app's own
fly-to animation so the map ends up close enough for the lines to read."""
from playwright.sync_api import sync_playwright

OUT = "/workspace/rail-promo/out/ui_src"
CENTER = (-1080, -387)  # 牛角沱: 2/3 号线过江交汇处 (unused with flyTo)

SETUP = """
() => {
  const v = window.__viewer;
  window.__api.setQuality('high');
  window.__api.selectLine(null);
  v.evaluateAutoQuality = () => {};
  v.resolutionScale = 1;
  v.renderer.setPixelRatio(1);
  v.renderer.setSize(1920, 1080, false);
  v.clock.paused = false;
  return true;
}
"""

LOCK = """
() => {
  const v = window.__viewer;
  const bp = v.camera.position.clone();
  const bt = v.cameraController.controls.target.clone();
  const fv = v.camera.fov;
  window.__lock = setInterval(() => {
    if (v.cameraController.flying) v.cameraController.flying = null;
    v.camera.position.copy(bp);
    v.cameraController.controls.target.copy(bt);
    v.camera.fov = fv;
    v.camera.updateProjectionMatrix();
    v.camera.lookAt(bt);
    v.cameraController.controls.update();
  }, 16);
  return true;
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("http://localhost:5173/", wait_until="load")
    pg.wait_for_function("() => window.__viewer && window.__api", timeout=120000)
    pg.wait_for_timeout(7000)
    pg.evaluate(SETUP)
    pg.wait_for_timeout(9000)
    print(
        "dist",
        pg.evaluate(
            "() => Math.round(window.__viewer.camera.position.distanceTo("
            "window.__viewer.cameraController.controls.target))"
        ),
        flush=True,
    )

    pg.screenshot(path=f"{OUT}/app_base.png")
    print("base ok", flush=True)
    pg.evaluate(LOCK)
    pg.evaluate("() => window.__api.selectLine('3')")
    pg.wait_for_timeout(12000)
    pg.screenshot(path=f"{OUT}/app_click.png")
    print(
        "click cam",
        pg.evaluate("() => window.__viewer.camera.position.toArray().map(n=>Math.round(n))"),
        pg.evaluate("() => window.__viewer.cameraController.controls.target.toArray().map(n=>Math.round(n))"),
        pg.evaluate("() => window.__viewer.camera.fov"),
        pg.evaluate("() => !!window.__lock"),
        flush=True,
    )
    b.close()
