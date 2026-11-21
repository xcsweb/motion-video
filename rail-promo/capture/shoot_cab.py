#!/usr/bin/env python3
"""Capture a clean cab-view arrival at a station as 30 fps stills."""
import base64
import json
import os
import sys

from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

WANT = sys.argv[1] if len(sys.argv) > 1 else "牛角沱"
ETA = float(sys.argv[2]) if len(sys.argv) > 2 else 7.0
N = int(sys.argv[3]) if len(sys.argv) > 3 else 72
FPS = 30
OUT = "/workspace/rail-promo/out/cab"
os.makedirs(OUT, exist_ok=True)

W, H = 1920, 1080
CH = 765
CY = (H - CH) // 2

FIND = """
(args) => {
  const v = window.__viewer;
  const base = v.clock.timeSec;
  const out = [];
  for (let dt = 0; dt < 1800; dt += 0.5) {
    const ts = (base + dt) % 86400;
    for (const tr of v.timetable.sample(ts)) {
      if (tr.lineId !== '2' || tr.nextStationName !== args.want) continue;
      if (tr.status !== 'arriving') continue;
      if (tr.etaSec >= args.eta && tr.etaSec <= args.eta + 1) {
        out.push({ ts, id: tr.id, eta: +tr.etaSec.toFixed(1) });
      }
    }
    if (out.length > 20) break;
  }
  return out;
}
"""


def grade(im):
    im = ImageEnhance.Color(im).enhance(0.78)
    im = ImageEnhance.Contrast(im).enhance(1.1)
    im = ImageEnhance.Brightness(im).enhance(0.98)
    cool = Image.new("RGB", im.size, (10, 18, 30))
    im = Image.blend(im, cool, 0.05)
    vig = Image.new("L", im.size, 0)
    vd = ImageDraw.Draw(vig)
    w, h = im.size
    vd.ellipse([-w * 0.2, -h * 0.3, w * 1.2, h * 1.3], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    return Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), vig)


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
    print("cands", len(cands), cands[:2], flush=True)
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
    pg.wait_for_timeout(1500)
    tid = pg.evaluate("(id) => (window.__viewer.currentTrains.find(t=>t.id===id)||{}).id", pick["id"])
    pg.evaluate("(id) => window.__api.followTrain(id)", tid)
    pg.wait_for_timeout(600)
    pg.evaluate("""() => {
      const v = window.__viewer;
      v.cameraController.followBlend = 1;
      document.querySelector('.ui-layer').style.display = 'none';
      if (v.transit.setLabelsEnabled) v.transit.setLabelsEnabled(false);
      return true;
    }""")
    pg.wait_for_timeout(2500)

    for i in range(N):
        t = pick["ts"] + i / FPS
        pg.evaluate("(t) => { window.__viewer.clock.timeSec = t; return true; }", t)
        pg.wait_for_timeout(450)
        data = pg.evaluate("""() => {
          const v = window.__viewer;
          v.renderer.render(v.scene, v.camera);
          return v.renderer.domElement.toDataURL('image/jpeg', 0.95);
        }""")
        raw = base64.b64decode(data.split(",", 1)[1])
        open(f"{OUT}/raw_{i:04d}.jpg", "wb").write(raw)
        if i % 10 == 0:
            print("frame", i, flush=True)

    # compose the 2.39 band and grade
    for i in range(N):
        im = Image.open(f"{OUT}/raw_{i:04d}.jpg").convert("RGB")
        im = im.crop((0, CY, W, CY + CH)).resize((W, CH), Image.LANCZOS)
        g = grade(im)
        canvas = Image.new("RGB", (W, H), (5, 8, 13))
        canvas.paste(g, (0, CY))
        canvas.save(f"{OUT}/f_{i:04d}.jpg", quality=95)
    print("done", N, flush=True)
    b.close()
