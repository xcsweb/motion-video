#!/usr/bin/env python3
"""Free-camera CBD push-in (guidao). Slow dolly toward Xiaoshizi, 30fps."""
import base64, os, sys, time
from playwright.sync_api import sync_playwright

OUT = "/workspace/rail-promo/out/frames/10_cbd"
os.makedirs(OUT, exist_ok=True)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 72

SETUP = """
() => {
  const s = document.createElement('style');
  s.textContent = '.ui-layer,.labels-layer{display:none!important}';
  document.head.appendChild(s);
  const v = window.__viewer;
  v.clock.paused = true;
  v.clock.timeSec = 72000;
  window.__api.setQuality('high');
  window.__api.selectLine(null);
  v.evaluateAutoQuality = () => {};
  v.resolutionScale = 1;
  v.renderer.setPixelRatio(1);
  v.renderer.setSize(1920, 1080, false);
  v.cameraController.update = () => {};
  return true;
}
"""

CAM = """
([p, t, fov]) => {
  const v = window.__viewer;
  v.camera.position.set(p[0], p[1], p[2]);
  v.camera.fov = fov;
  v.camera.updateProjectionMatrix();
  v.camera.lookAt(t[0], t[1], t[2]);
  v.camera.updateMatrixWorld(true);
}
"""

GRAB = "()=>{const v=window.__viewer;v.renderer.render(v.scene,v.camera);return v.canvas.toDataURL('image/jpeg',0.95)}"

# keyframes: wide -> closer, gently descending
KF = [
    (0.0, [2200, 380, 330], [2833, 245, -198], 44),
    (1.0, [2520, 330, 60], [2833, 245, -198], 40),
]

def lerp(a, b, f):
    return [a[i] + (b[i] - a[i]) * f for i in range(3)]

with sync_playwright() as p:
    b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
    pg = b.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
    pg.goto("http://localhost:5173/", wait_until="load")
    pg.wait_for_function("() => window.__viewer && window.__api", timeout=120000)
    pg.wait_for_timeout(6000)
    pg.evaluate(SETUP)
    pg.wait_for_timeout(1500)
    t0 = time.time()
    for i in range(N):
        f = i / max(1, N - 1)
        f = f * f * (3 - 2 * f)
        k0, k1 = KF[0], KF[-1]
        pos = lerp(k0[1], k1[1], f)
        tgt = lerp(k0[2], k1[2], f)
        fov = k0[3] + (k1[3] - k0[3]) * f
        pg.evaluate(CAM, [pos, tgt, fov])
        pg.evaluate("()=>new Promise(r=>requestAnimationFrame(r))")
        d = pg.evaluate(GRAB).split(",", 1)[1]
        open(f"{OUT}/f_{i:04d}.jpg", "wb").write(base64.b64decode(d))
        if i % 10 == 0:
            print(f"{i} {time.time()-t0:.1f}s", flush=True)
    b.close()
print(f"done {N} in {time.time()-t0:.1f}s")
