#!/usr/bin/env python3
"""Deterministic frame capture from the guidao dev server."""
import argparse
import base64
import os
import time
import json

from playwright.sync_api import sync_playwright

OUT = "/workspace/rail-promo/out/frames"
FPS = 30

# ---- shot table: (name, start, end, mode, payload) -------------------------
# mode: pose | follow | platform
SHOTS = [
    ("01_tunnel",   0.00, 1.60, "follow",   {"train": "1-0-68820", "t0": 74000}),
    ("02_aerial",   1.60, 5.20, "pose",     {"kf": [
        {"t": 0.0, "pos": [-3000, 3000, 2400], "tgt": [600, 200, -500], "fov": 45},
        {"t": 1.0, "pos": [-900, 1250, 900],  "tgt": [1400, 200, -600], "fov": 42},
    ]}),
    ("03_dive",     5.20, 7.20, "pose",     {"kf": [
        {"t": 0.0, "pos": [2760, 760, 980], "tgt": [2833, 230, -198], "fov": 50},
        {"t": 1.0, "pos": [2520, 430, 560], "tgt": [2833, 240, -198], "fov": 48},
    ]}),
    ("04_title",    7.18, 8.66, "train",    {"train": "2-0-68820", "t0": 74000, "d": 85, "h": 8, "fov": 25}),
    ("05_platform", 8.66, 10.42, "platform", {"station": "st-20", "t0": 74120}),
    ("06_dial",     10.42, 11.38, "none",   {}),
    ("07_tunnel2",  11.38, 13.86, "follow", {"train": "6-0-67320", "t0": 74000}),
    ("08_cross",    13.86, 16.70, "train",  {"train": "6-0-72720", "t0": 74200, "d": 78, "h": 5, "fov": 24}),
    ("09_climax",   16.70, 20.90, "pose",   {"kf": [
        {"t": 0.0, "pos": [-1400, 2100, 1500], "tgt": [500, 200, -400], "fov": 46},
        {"t": 1.0, "pos": [-300, 1750, 1050],  "tgt": [900, 220, -500], "fov": 44},
    ]}),
]

SETUP_JS = """
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
  v.renderer.setSize(window.innerWidth, window.innerHeight, false);
  window.__poses = {};
  const geos = v.transit.geometries;
  const tr = v.timetable.sample(74000).filter(t => t.status === 'running');
  for (const t of tr) {
    const p = v.trains.poseOf(t, geos);
    if (p) window.__poses[t.id] = p;
  }
}
"""

CAB_JS = """
([id]) => {
  const v = window.__viewer;
  const geos = v.transit.geometries;
  const tr = window.__tr;
  if (!tr) return false;
  const dt = v.clock.timeSec - window.__trT;
  tr.distance = window.__trBase + (tr.speedKph / 3.6) * dt;
  const p = v.trains.poseOf(tr, geos);
  if (!p) return false;
  if (!window.__origHeightAt) window.__origHeightAt = v.terrain.heightAt.bind(v.terrain);
  v.terrain.heightAt = () => -1000;
  v.camera.position.set(p.x, p.y + 3.1, p.z);
  v.camera.fov = 62;
  v.camera.updateProjectionMatrix();
  v.cameraController.controls.target.set(p.lookX, p.lookY + 3.1, p.lookZ);
  v.camera.lookAt(p.lookX, p.lookY + 3.1, p.lookZ);
  v.cameraController.controls.update();
  return true;
}
"""

POSE_JS = """
([pos, tgt, fov]) => {
  const v = window.__viewer;
  v.camera.position.set(pos[0], pos[1], pos[2]);
  v.camera.fov = fov;
  v.camera.updateProjectionMatrix();
  v.cameraController.controls.target.set(tgt[0], tgt[1], tgt[2]);
  v.camera.lookAt(tgt[0], tgt[1], tgt[2]);
  v.cameraController.controls.update();
}
"""

INIT_TRAIN_JS = """
([id, t]) => {
  const v = window.__viewer;
  const tr = v.timetable.sample(t).find(x => x.id === id);
  window.__tr = tr ? JSON.parse(JSON.stringify(tr)) : null;
  window.__trBase = tr ? tr.distance : 0;
  window.__trT = t;
  return !!window.__tr;
}
"""

TRAIN_JS = """
([id, d, h, fov]) => {
  const v = window.__viewer;
  const geos = v.transit.geometries;
  const tr = window.__tr;
  if (!tr) return false;
  const dt = v.clock.timeSec - window.__trT;
  tr.distance = window.__trBase + (tr.speedKph / 3.6) * dt;
  const p = v.trains.poseOf(tr, geos);
  if (!p) return false;
  const rx = p.tz, rz = -p.tx;
  v.camera.position.set(p.x + rx * d, p.y + h, p.z + rz * d);
  v.camera.fov = fov;
  v.camera.updateProjectionMatrix();
  v.cameraController.controls.target.set(p.x, p.y + 2, p.z);
  v.camera.lookAt(p.x, p.y + 2, p.z);
  v.cameraController.controls.update();
  return true;
}
"""


def lerp_kf(kf, prog):
    if prog <= kf[0]["t"]:
        return kf[0]
    if prog >= kf[-1]["t"]:
        return kf[-1]
    for a, b in zip(kf, kf[1:]):
        if a["t"] <= prog <= b["t"]:
            f = (prog - a["t"]) / (b["t"] - a["t"])
            f = f * f * (3 - 2 * f)  # smoothstep
            return {
                "pos": [a["pos"][i] + (b["pos"][i] - a["pos"][i]) * f for i in range(3)],
                "tgt": [a["tgt"][i] + (b["tgt"][i] - a["tgt"][i]) * f for i in range(3)],
                "fov": a["fov"] + (b["fov"] - a["fov"]) * f,
            }
    return kf[-1]


def grab(pg):
    pg.evaluate("()=>new Promise(r=>requestAnimationFrame(r))")
    data = pg.evaluate(
        "()=>{const v=window.__viewer;v.renderer.render(v.scene,v.camera);"
        "return v.canvas.toDataURL('image/jpeg',0.95)}"
    )
    return base64.b64decode(data.split(",")[1])


def stills(points=(0.0, 0.5, 1.0)):
    out = "/workspace/rail-promo/out/stills"
    os.makedirs(out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        pg = b.new_page(viewport={"width": 1280, "height": 720})
        pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
        pg.wait_for_function("window.__viewer", timeout=90000)
        time.sleep(6)
        pg.evaluate(SETUP_JS)
        time.sleep(1)
        for name, start, end, mode, cfg in SHOTS:
            if mode == "platform":
                pg.evaluate("(sid)=>window.__api.enterPlatformView(sid)", cfg["station"])
                pg.evaluate("()=>{window.__viewer.transit.group.visible=false}")
                time.sleep(2)
            if mode == "follow":
                pg.evaluate("(id)=>window.__api.followTrain(id)", cfg["train"])
                time.sleep(1.5)
            if mode in ("train", "cab"):
                pg.evaluate(INIT_TRAIN_JS, [cfg["train"], cfg.get("t0", 74000)])
            for prog in points:
                ts = start + (end - start) * prog
                t_sim = cfg.get("t0", 74000) + (ts - start)
                pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", t_sim)
                if mode == "train":
                    pg.evaluate(TRAIN_JS, [cfg["train"], cfg["d"], cfg["h"], cfg["fov"]])
                elif mode == "pose":
                    k = lerp_kf(cfg["kf"], prog)
                    pg.evaluate(POSE_JS, [k["pos"], k["tgt"], k["fov"]])
                with open(os.path.join(out, f"{name}_{int(prog*100):03d}.jpg"), "wb") as fh:
                    fh.write(grab(pg))
                print("still", name, prog)
            if mode == "platform":
                pg.evaluate("()=>{window.__viewer.transit.group.visible=true}")
                pg.evaluate("()=>window.__api.exitPlatformView()")
                time.sleep(0.5)

        b.close()


def capture(shot_filter=None, limit=None, width=1280, height=720):
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-unsafe-swiftshader"])
        pg = b.new_page(viewport={"width": width, "height": height})
        pg.goto("http://localhost:5173/", wait_until="load", timeout=60000)
        pg.wait_for_function("window.__viewer", timeout=90000)
        time.sleep(6)
        pg.evaluate(SETUP_JS)
        time.sleep(1)

        for name, start, end, mode, cfg in SHOTS:
            if shot_filter and shot_filter not in name:
                continue
            if mode == "none":
                continue
            d = os.path.join(OUT, name)
            os.makedirs(d, exist_ok=True)
            n = max(1, round((end - start) * FPS))
            if limit:
                n = min(n, limit)
            t0 = time.time()

            if mode == "platform":
                pg.evaluate("(sid)=>window.__api.enterPlatformView(sid)", cfg["station"])
                pg.evaluate("()=>{window.__viewer.transit.group.visible=false}")
                time.sleep(2)

            for i in range(n):
                ts = start + i / FPS
                t_sim = cfg.get("t0", 74000) + (ts - start)
                if mode == "follow":
                    if i == 0:
                        pg.evaluate("(id)=>window.__api.followTrain(id)", cfg["train"])
                        time.sleep(1.5)
                    pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", t_sim)
                elif mode == "train":
                    if i == 0:
                        pg.evaluate(INIT_TRAIN_JS, [cfg["train"], t_sim])
                    pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", t_sim)
                    pg.evaluate(TRAIN_JS, [cfg["train"], cfg["d"], cfg["h"], cfg["fov"]])
                elif mode == "platform":
                    pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", t_sim)
                else:
                    pg.evaluate("(t)=>{window.__viewer.clock.timeSec=t}", t_sim)
                    k = lerp_kf(cfg["kf"], i / max(1, n - 1))
                    pg.evaluate(POSE_JS, [k["pos"], k["tgt"], k["fov"]])
                pg.evaluate("()=>new Promise(r=>requestAnimationFrame(r))")
                data = pg.evaluate(
                    "()=>{const v=window.__viewer;"
                    "v.renderer.render(v.scene,v.camera);"
                    "return v.canvas.toDataURL('image/jpeg',0.95)}"
                )
                with open(os.path.join(d, f"f_{i:04d}.jpg"), "wb") as fh:
                    fh.write(base64.b64decode(data.split(",")[1]))

            if mode == "platform":
                pg.evaluate("()=>{window.__viewer.transit.group.visible=true}")
                pg.evaluate("()=>window.__api.exitPlatformView()")
                time.sleep(0.5)

            print(f"{name}: {n} frames in {time.time()-t0:.1f}s")

        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--stills", action="store_true")
    a = ap.parse_args()
    if a.stills:
        stills()
    else:
        capture(a.shot, a.limit, a.width, a.height)
