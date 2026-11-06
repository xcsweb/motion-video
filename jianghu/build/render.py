#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《一笑江湖》· 天上白玉京 MV 逐帧渲染器
用法:
  python3 build/render.py                # 全量
  python3 build/render.py --step 15      # 快速预览
"""
import argparse
import json
import math
import os
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_DIR = os.path.join(ROOT, "assets", "ai")
FRAME_DIR = os.path.join(ROOT, "frames")
PREVIEW_DIR = os.path.join(ROOT, "previews")
BRUSH_PATH = os.path.join(ROOT, "assets", "MaShanZheng-Regular.ttf")
SERIF_PATH = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSerifCJKsc-Regular.otf"

W, H = 1920, 1080
SRC_W, SRC_H = 2560, 1440
SRC_CROP_BOTTOM = 0.09

with open(os.path.join(ROOT, "config", "timeline.json"), encoding="utf-8") as f:
    TL = json.load(f)
with open(os.path.join(ROOT, "config", "lyrics.json"), encoding="utf-8") as f:
    LY = json.load(f)

FPS = TL["fps"]
DURATION = TL["duration"]
SHOTS = TL["shots"]
LINES = LY["lines"]

_font_cache = {}
_glyph_cache = {}


def brush(size):
    key = ("b", size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(BRUSH_PATH, size)
    return _font_cache[key]


def serif(size):
    key = ("s", size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(SERIF_PATH, size)
    return _font_cache[key]


def has_glyph(font, ch):
    key = (id(font), ch)
    if key not in _glyph_cache:
        try:
            _glyph_cache[key] = font.getmask(ch).getbbox() is not None
        except Exception:
            _glyph_cache[key] = False
    return _glyph_cache[key]


def smoothstep(a, b, x):
    if b <= a:
        return 1.0 if x >= b else 0.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_vignette():
    yy, xx = np.mgrid[0:H, 0:W]
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    r2 = nx * nx + ny * ny
    v = 1.0 - 0.42 * np.clip(r2 / 2.0, 0, 1) ** 1.15
    return v.astype(np.float32)[..., None]


VIG = make_vignette()


def make_fog():
    rng = np.random.default_rng(7)
    n = rng.random((270, 480)).astype(np.float32)
    n = gaussian_filter(n, sigma=14)
    n = (n - n.min()) / (n.max() - n.min())
    n = np.clip((n - 0.35) * 1.8, 0, 1)
    img = Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    return np.asarray(img).astype(np.float32) / 255.0


FOG = make_fog()

_img_cache = {}


def load_image(name):
    if name in _img_cache:
        return _img_cache[name]
    path = os.path.join(AI_DIR, name + ".jpg")
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.crop((0, 0, w, int(h * (1 - SRC_CROP_BOTTOM))))
    w, h = im.size
    tw = int(h * W / H)
    if tw < w:
        left = (w - tw) // 2
        im = im.crop((left, 0, left + tw, h))
    im = im.resize((SRC_W, SRC_H), Image.LANCZOS)
    _img_cache[name] = im
    return im


def grade(im, tint):
    a = np.asarray(im).astype(np.float32) / 255.0
    if tint == "cold":
        mul, contrast, sat, lift = (0.90, 0.99, 1.10), 1.06, 0.86, 0.02
        shadow = np.array([0.0, 0.015, 0.045], dtype=np.float32)
    elif tint == "warm":
        mul, contrast, sat, lift = (1.10, 1.00, 0.87), 1.04, 0.98, 0.015
        shadow = np.array([0.040, 0.018, 0.0], dtype=np.float32)
    elif tint == "memory":
        mul, contrast, sat, lift = (1.16, 1.00, 0.78), 0.92, 0.92, 0.045
        shadow = np.array([0.055, 0.030, 0.0], dtype=np.float32)
    elif tint == "red":
        mul, contrast, sat, lift = (1.20, 0.90, 0.80), 1.02, 0.94, 0.02
        shadow = np.array([0.050, 0.010, 0.0], dtype=np.float32)
    elif tint == "edge":
        mul, contrast, sat, lift = (0.98, 1.00, 1.06), 1.05, 0.90, 0.02
        shadow = np.array([0.010, 0.020, 0.040], dtype=np.float32)
    elif tint == "falling":
        mul, contrast, sat, lift = (1.03, 0.99, 1.04), 1.03, 0.92, 0.025
        shadow = np.array([0.020, 0.015, 0.030], dtype=np.float32)
    else:
        mul, contrast, sat, lift = (1.04, 1.01, 1.00), 1.02, 0.94, 0.025
        shadow = np.array([0.025, 0.020, 0.020], dtype=np.float32)
    a = a * np.array(mul, dtype=np.float32)
    a = (a - 0.5) * contrast + 0.5
    lum = a.mean(axis=2, keepdims=True)
    a = lum + (a - lum) * sat
    a = a * (1.0 - lift) + lift + shadow
    return np.clip(a, 0, 1)


def bloom(im, strength):
    if strength <= 0:
        return im
    small = im.resize((W // 4, H // 4), Image.BILINEAR)
    a = np.asarray(small).astype(np.int16)
    bright = np.clip((a - 148) * 3, 0, 255).astype(np.uint8)
    b = Image.fromarray(bright).filter(ImageFilter.GaussianBlur(9))
    b = b.resize((W, H), Image.BILINEAR)
    return Image.blend(im, ImageChops.screen(im, b), strength)


def add_fog(im, t, strength, warm=False):
    if strength <= 0:
        return im
    arr = np.asarray(im).astype(np.float32)
    oy = int(t * 7) % H
    ox = int(t * 19) % W
    f = np.roll(FOG, (oy, ox), axis=(0, 1))[..., None]
    col = np.array([236, 214, 182] if warm else [205, 220, 235], dtype=np.float32)
    k = strength * 0.55
    arr = arr * (1 - k * f) + col * (k * f)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def add_snow(im, t, strength):
    if strength <= 0:
        return im
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = random.Random(int(t * 30) * 131 + 17)
    n = int(210 * strength)
    for _ in range(n):
        speed = rng.uniform(16, 52)
        drift = rng.uniform(-22, 22)
        x = (rng.uniform(0, W) + drift * t) % W
        y = (rng.uniform(0, H) + speed * t) % H
        r = rng.choice([1, 1, 1, 2, 2, 3])
        alpha = rng.randint(55, 165)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(242, 246, 255, alpha))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def add_rain(im, t, strength):
    if strength <= 0:
        return im
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = random.Random(int(t * 30) * 977 + 3)
    n = int(190 * strength)
    for _ in range(n):
        speed = rng.uniform(55, 110)
        x = rng.uniform(0, W)
        y = (rng.uniform(0, H) + speed * t) % H
        ln = rng.uniform(12, 30)
        alpha = rng.randint(45, 120)
        d.line((x, y, x - 5, y + ln), fill=(205, 220, 235, alpha), width=1)
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def shot_at(t):
    for s in SHOTS:
        if s["t0"] <= t < s["t1"]:
            return s
    return SHOTS[-1]


def camera(im, s, t):
    p = clamp((t - s["t0"]) / max(0.001, s["t1"] - s["t0"]), 0, 1)
    z = s.get("z0", 1.0) + (s.get("z1", s.get("z0", 1.0)) - s.get("z0", 1.0)) * p
    cx0, cy0 = s.get("cx", 0.5), s.get("cy", 0.5)
    cx1, cy1 = s.get("cx1", cx0), s.get("cy1", cy0)
    cx = cx0 + (cx1 - cx0) * p
    cy = cy0 + (cy1 - cy0) * p
    cw, ch = SRC_W / z, SRC_H / z
    x = clamp(cx * SRC_W - cw / 2, 0, SRC_W - cw)
    y = clamp(cy * SRC_H - ch / 2, 0, SRC_H - ch)
    out = im.crop((int(x), int(y), int(x + cw), int(y + ch)))
    out = out.resize((W, H), Image.LANCZOS)
    dx = int(round(1.1 * math.sin(t * 0.83)))
    if dx:
        out = ImageChops.offset(out, dx, 0)
    return out


def render_edict(s, t):
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    top = np.array([10, 16, 22], dtype=np.float32)
    bot = np.array([20, 29, 38], dtype=np.float32)
    arr = top[None, None, :] * (1 - yy[..., None]) + bot[None, None, :] * yy[..., None]
    arr = np.repeat(arr, W, axis=1)
    yy2, xx2 = np.mgrid[0:H, 0:W]
    d2 = ((xx2 - W * 0.5) / (W * 0.55)) ** 2 + ((yy2 - H * 0.3) / (H * 0.55)) ** 2
    glow = np.clip(1.0 - d2, 0, 1) ** 2
    arr += glow[..., None] * np.array([28, 38, 50], dtype=np.float32)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    im = add_fog(im, t, 0.10)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((520, 46, 1400, 1034), outline=(150, 190, 205, 55), width=1)
    d.rectangle((534, 60, 1386, 1020), outline=(150, 190, 205, 25), width=1)
    d.text((960, 540), "天", font=brush(620), anchor="mm", fill=(150, 190, 210, 14))
    draw_vcols(layer, [s["text"]], x_right=1080, y0=118, size=132, spacing=146,
               col_gap=148, color=(232, 242, 246), alpha_mul=0.92, seal="玉")
    d.text((960, 968), s.get("sub", ""), font=serif(38), anchor="mm",
           fill=(190, 210, 220, 170))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def render_shot(s, t):
    if s.get("type") == "edict":
        return render_edict(s, t)
    im = camera(load_image(s["asset"]), s, t)
    tint = s.get("tint", "cold")
    a = grade(im, tint)
    bs = {"memory": 0.40, "warm": 0.42, "falling": 0.35, "dawn": 0.30,
          "red": 0.25}.get(tint, 0.12)
    im = Image.fromarray((a * 255).astype(np.uint8))
    im = bloom(im, bs)
    if s.get("fog"):
        im = add_fog(im, t, s["fog"], warm=(tint in ("warm", "memory", "falling")))
    if s.get("snow"):
        im = add_snow(im, t, s["snow"])
    if s.get("rain"):
        im = add_rain(im, t, s["rain"])
    return im


def split_cols(text, max_chars=12):
    parts = text.split(" ")
    cols = []
    for part in parts:
        if not part:
            continue
        for i in range(0, len(part), max_chars):
            cols.append(part[i:i + max_chars])
    return cols or [text]


def draw_vcols(layer, cols, x_right, y0, size, spacing, col_gap, color,
               alpha_mul=1.0, seal=None, char_alpha=None):
    d = ImageDraw.Draw(layer)
    flat = []
    for ci, col in enumerate(cols):
        for i, ch in enumerate(col):
            flat.append((ci, i, len(flat), ch))
    for ci, i, k, ch in flat:
        x = x_right - ci * col_gap
        y = y0 + i * spacing
        if char_alpha is not None:
            alpha, colr = char_alpha(ci, i, k)
        else:
            alpha, colr = int(255 * alpha_mul), color
        alpha = int(clamp(alpha, 0, 255))
        if alpha <= 0:
            continue
        f = brush(size) if has_glyph(brush(size), ch) else serif(size)
        d.text((x + 2, y + 3), ch, font=f, anchor="mm",
               fill=(0, 0, 0, int(alpha * 0.58)))
        d.text((x, y), ch, font=f, anchor="mm",
               fill=(int(colr[0]), int(colr[1]), int(colr[2]), alpha))
    if seal:
        sx = x_right
        sy = y0 + len(cols[0]) * spacing + 4
        d.rounded_rectangle((sx - 26, sy - 26, sx + 26, sy + 26), radius=4,
                            fill=(168, 48, 40, 215))
        d.text((sx, sy), seal, font=brush(34), anchor="mm",
               fill=(246, 236, 226, 245))


def draw_lyrics(im, t):
    line = None
    for ln in LINES:
        if t >= ln["t"] - 0.05 and t <= ln["end"] + 0.28:
            line = ln
    if line is None:
        return im
    fade_in = smoothstep(line["t"] - 0.05, line["t"] + 0.38, t)
    fade_out = 1.0 - smoothstep(line["end"], min(line["end"] + 0.30, DURATION), t)
    mul = fade_in * fade_out
    if mul <= 0.02:
        return im
    cols = split_cols(line["text"], 12)
    total = sum(len(c) for c in cols)
    prog = clamp((t - line["t"]) / max(0.15, line["end"] - line["t"]), 0, 1)
    idx = min(total - 1, int(prog * total))

    def ca(ci, i, k):
        if k < idx:
            return int(232 * mul), (236, 242, 248)
        if k == idx:
            return int(255 * mul), (255, 214, 150)
        return int(62 * mul), (198, 214, 230)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_vcols(layer, cols, x_right=1878, y0=96, size=62, spacing=69,
               col_gap=72, color=(236, 242, 248), alpha_mul=mul,
               seal="玉" if "笑" in line["text"] else None, char_alpha=ca)
    d = ImageDraw.Draw(layer)
    txt = line["text"].replace(" ", "　")
    d.rectangle((84, 996, 88, 1042), fill=(205, 176, 120, int(180 * mul)))
    d.text((112, 1018), txt, font=serif(32), anchor="lm",
           fill=(238, 242, 246, int(212 * mul)),
           stroke_width=2, stroke_fill=(0, 0, 0, int(190 * mul)))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def draw_title(im, t):
    a = smoothstep(0.55, 1.60, t) * (1.0 - smoothstep(6.0, 8.2, t))
    if a <= 0.02:
        return im
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw_vcols(layer, ["天上白玉京"], x_right=322, y0=148, size=96, spacing=104,
               col_gap=108, color=(246, 248, 242), alpha_mul=a, seal="玉")
    d = ImageDraw.Draw(layer)
    d.text((322, 728), "一 笑 江 湖", font=serif(38), anchor="mm",
           fill=(224, 232, 236, int(190 * a)))
    d.text((322, 780), "闻人听書_", font=serif(22), anchor="mm",
           fill=(190, 206, 216, int(150 * a)))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def draw_end(im, t):
    a = smoothstep(88.15, 89.20, t)
    if a <= 0.02:
        return im
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 0, W, H), fill=(4, 8, 12, int(176 * a)))
    draw_vcols(layer, ["他日若得脱身法", "生吃黄连苦也甜"],
               x_right=1016, y0=112, size=76, spacing=86, col_gap=94,
               color=(240, 236, 224), alpha_mul=a, seal="苦")
    d.text((960, 938), "《一笑江湖》 · 闻人聽書", font=serif(28), anchor="mm",
           fill=(202, 210, 216, int(170 * a)))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def previous_shot(s):
    i = SHOTS.index(s)
    return SHOTS[i - 1] if i > 0 else None


def compose(t, idx):
    s = shot_at(t)
    im = render_shot(s, t)
    trd = 0.55 if s.get("trans") == "dissolve" else 0.32
    if s["t0"] > 0 and t < s["t0"] + trd:
        ps = previous_shot(s)
        if ps is not None:
            pb = render_shot(ps, s["t0"] - 1.0 / FPS)
            a = smoothstep(s["t0"], s["t0"] + trd, t)
            im = Image.blend(pb, im, a)
        if s.get("trans") == "flash":
            fl = smoothstep(s["t0"], s["t0"] + 0.18, t)
            im = Image.blend(im, Image.new("RGB", (W, H), (255, 248, 232)),
                             0.55 * (1 - fl))
    elif s["t0"] == 0:
        a = smoothstep(0.0, 0.95, t)
        im = Image.blend(Image.new("RGB", (W, H), (2, 5, 8)), im, a)
    im = draw_title(im, t)
    im = draw_lyrics(im, t)
    im = draw_end(im, t)
    arr = np.asarray(im).astype(np.float32) * VIG
    rng = np.random.default_rng(idx + 1)
    arr += rng.normal(0.0, 3.1, (H, W, 1))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _render_one(job):
    idx, step, force = job
    t = idx / FPS
    path = os.path.join(FRAME_DIR if step == 1 else PREVIEW_DIR,
                        ("f_%04d.jpg" if step == 1 else "p_%04d.jpg") % idx)
    if os.path.exists(path) and not force:
        return 0
    compose(t, idx).save(path, quality=92, subsampling=1)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=int(round(DURATION * FPS)))
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    os.makedirs(FRAME_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    jobs = [(i, args.step, args.force) for i in range(args.start, args.end, args.step)]
    total = len(jobs)
    done = 0
    if args.jobs <= 1:
        for job in jobs:
            done += _render_one(job)
            if done % 60 == 0:
                print("[render] %d/%d" % (done, total), flush=True)
    else:
        from multiprocessing import Pool
        with Pool(processes=args.jobs) as pool:
            for r in pool.imap_unordered(_render_one, jobs, chunksize=8):
                done += 1
                if done % 60 == 0:
                    print("[render] %d/%d" % (done, total), flush=True)
    print("[render] done", flush=True)


if __name__ == "__main__":
    main()
