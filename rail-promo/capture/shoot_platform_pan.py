#!/usr/bin/env python3
"""Platform insert: slow yaw drift at Niujiaotuo, 1920x1080 @30fps."""
import base64, math, os, sys, time
from playwright.sync_api import sync_playwright

OUT = "/workspace/rail-promo/out/frames/05b_platform"
os.makedirs(OUT, exist_ok=True)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 42

SETUP = """
() => {
  const s = document.createElement('style');
  s.textContent = '.ui-layer,.labels-layer{display:none!important}';
  document.head.appendChild(s);
  const v = window.__viewer;
  v.clock.paused = true;
  v.clock.timeSec = 74120;
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

INIT = """
() => {
  const v = window.__viewer;
  const pc = v.camera.position.clone();
  const t0 = v.cameraController.controls.target.clone();
  v.cameraController.update = () => {};
  v.camera.fov = 60;
  v.camera.updateProjectionMatrix();
  window.__pc = { x: pc.x, y: pc.y, z: pc.z };
  window.__yaw0 = Math.atan2(t0.z - pc.z, t0.x - pc.x);
  return window.__yaw0;
}
"""

CAM = """
([yaw, pitch]) => {
  const v = window.__viewer;
  const p = window.__pc;
  const y = window.__yaw0 + yaw;
  const d = 30;
  const tx = p.x + Math.cos(y) * Math.cos(pitch) * d;
  const ty = p.y + Math.sin(pitch) * d;
  const tz = p.z + Math.sin(y) * Math.cos(pitch) * d;
  v.camera.position.set(p.x, p.y, p.z);
  v.camera.lookAt(tx, ty, tz);
  v.camera.updateMatrixWorld(true);
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
    print("yaw0", pg.evaluate(INIT), flush=True)
    t0 = time.time()
    for i in range(N):
        f = i / max(1, N - 1)
        yaw = -0.055 + 0.11 * (f * f * (3 - 2 * f))
        pg.evaluate(CAM, [yaw, 0.06])
        pg.evaluate("()=>new Promise(r=>requestAnimationFrame(r))")
        d = pg.evaluate(GRAB).split(",", 1)[1]
        open(f"{OUT}/f_{i:04d}.jpg", "wb").write(base64.b64decode(d))
    print(f"done {N} in {time.time()-t0:.1f}s", flush=True)
    b.close()
