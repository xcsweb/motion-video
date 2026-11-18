#!/usr/bin/env python3
"""把 AI 静帧做成 9:16 电影感运动镜头，供 codecut 时间线使用。

- 裁掉底部 8.6% 的 AI 水印
- 居中裁成 1080x1920，并压一层很轻的底部渐变 scrim（保证字幕可读）
- ffmpeg zoompan 做 Ken Burns（推/拉 + 轻微横移）
- 统一胶片调色、暗角、颗粒
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config/timeline.json").read_text())
SRC = ROOT / "assets/ai"
PLATES = ROOT / "assets/plates"
MOTION = ROOT / "assets/motion"
PLATES.mkdir(parents=True, exist_ok=True)
MOTION.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920
FPS = 30
BOTTOM_CROP = 0.086


def plate(name: str) -> Path:
    out = PLATES / f"{name}.jpg"
    img = Image.open(SRC / f"{name}.jpg").convert("RGB")
    w, h = img.size
    # 1) 去掉底部水印
    img = img.crop((0, 0, w, int(h * (1 - BOTTOM_CROP))))
    # 2) 等比放大到高度 1920，居中裁成 1080x1920
    w, h = img.size
    scale = H / h
    nw = max(W, int(round(w * scale)))
    img = img.resize((nw, H), Image.LANCZOS)
    left = (nw - W) // 2
    img = img.crop((left, 0, left + W, H))

    # 3) 底部渐变 scrim（0.62H 处开始，底部 0.46）
    arr = np.asarray(img).astype(np.float32)
    y = np.arange(H, dtype=np.float32) / H
    t = np.clip((y - 0.60) / 0.40, 0.0, 1.0)
    a = (t ** 1.7) * 0.46
    arr *= (1.0 - a)[:, None, None]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    img.save(out, quality=95, subsampling=1)
    return out


def motion(name: str, t0: float, t1: float, cx: float, cy: float,
           z0: float, z1: float, pan_x: float, pan_y: float,
           first: bool, last: bool) -> Path:
    dur = round(t1 - t0, 3)
    n = max(2, int(round(dur * FPS)))
    p = plate(name)
    out = MOTION / f"{name}.mp4"

    zoom = f"{z0}+({z1}-{z0})*on/{n - 1}"
    x = (f"max(0,min(iw-iw/zoom,{cx}*iw-(iw/zoom)/2+{pan_x}*iw*on/{n - 1}))")
    y = (f"max(0,min(ih-ih/zoom,{cy}*ih-(ih/zoom)/2+{pan_y}*ih*on/{n - 1}))")

    vf = (
        f"scale={W * 2}:{H * 2}:flags=lanczos,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.06:saturation=0.93:gamma=1.01,"
        "colorbalance=rs=-0.018:gs=0.004:bs=0.028:rh=0.028:gh=0.0:bh=-0.022,"
        "unsharp=5:5:0.35:5:5:0.0,"
        "vignette=angle=PI/4.7,"
        "noise=alls=2:allf=t,"
        "format=yuv420p"
    )
    if first:
        vf += ",fade=t=in:st=0:d=0.9"
    if last:
        vf += f",fade=t=out:st={dur - 1.4:.3f}:d=1.4"

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-framerate", str(FPS), "-t", f"{dur}",
        "-i", str(p),
        "-vf", vf,
        "-frames:v", str(n),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-movflags", "+faststart", "-an", str(out),
    ]
    subprocess.run(cmd, check=True)
    return out


def main() -> None:
    shots = CFG["shots"]
    for i, s in enumerate(shots):
        out = motion(
            s["asset"], s["t0"], s["t1"], s["cx"], s["cy"],
            s["z0"], s["z1"], s.get("pan_x", 0.0), s.get("pan_y", 0.0),
            first=(i == 0), last=(i == len(shots) - 1),
        )
        print(f"[{i + 1:02d}/{len(shots)}] {out.name} {s['t1'] - s['t0']:.1f}s")


if __name__ == "__main__":
    main()
