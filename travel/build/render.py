#!/usr/bin/env python3
"""Travel film renderer — 1080x1920 / 30 fps.

Layers: plates (Ken Burns) -> film grade -> halation -> light leak ->
vignette -> grain -> subtitles / title cards.
"""
import argparse
import json
import math
import os
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = json.load(open(os.path.join(ROOT, "config", "timeline.json"), encoding="utf-8"))
SHOTS = CFG["shots"]
W, H = CFG["size"]
FPS = CFG["fps"]
DUR = CFG["duration"]
NFRAMES = int(round(DUR * FPS))

AI_DIR = os.path.join(ROOT, "assets", "ai")
FRAMES_DIR = os.path.join(ROOT, "frames")
PREVIEW_DIR = os.path.join(ROOT, "previews")

F_SERIF = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Light.ttc"
F_SERIF_MED = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc"
F_SANS = "/usr/share/fonts/opentype/noto/NotoSansCJK-Light.ttc"

BOTTOM_CROP = 0.086  # removes the generator watermark band
WHITE = (252, 249, 242)
MUTED = (222, 218, 207)

_fonts = {}
_plates = {}
_blocks = {}
_vignette = None
_grad = None
_open_scrim = None


def clamp(x, a, b):
    return max(a, min(b, x))


def smooth(x):
    x = clamp(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def font(path, size):
    key = (path, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(path, size, index=2)
    return _fonts[key]


# ------------------------------------------------------------------ plates
def plate(asset):
    if asset in _plates:
        return _plates[asset]
    path = None
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        p = os.path.join(AI_DIR, asset + ext)
        if os.path.exists(p):
            path = p
            break
    if path is None:
        raise FileNotFoundError(asset)
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.crop((0, 0, w, int(h * (1 - BOTTOM_CROP))))
    tw = int(round(im.height * W / H))
    if tw <= im.width:
        x0 = (im.width - tw) // 2
        im = im.crop((x0, 0, x0 + tw, im.height))
    else:
        th = int(round(im.width * H / W))
        y0 = max(0, (im.height - th) // 2)
        im = im.crop((0, y0, im.width, y0 + th))
    _plates[asset] = im
    return im


def shot_array(s, t):
    im = plate(s["asset"])
    pw, ph = im.size
    p = clamp((t - s["t0"]) / max(1e-6, s["t1"] - s["t0"]), 0, 1)
    e = smooth(p)
    z = s["z0"] + (s["z1"] - s["z0"]) * e
    cw, ch = pw / z, ph / z
    seed = sum(ord(c) for c in s["asset"]) % 97
    cx = (s["cx"] + s.get("pan_x", 0.0) * (e - 0.5) * 2) * pw
    cy = (s["cy"] + s.get("pan_y", 0.0) * (e - 0.5) * 2) * ph
    # delicate handheld drift
    cx += (math.sin(t * 1.21 + seed) + 0.6 * math.sin(t * 2.71 + seed * 2)) * 2.4
    cy += (math.sin(t * 0.93 + seed * 3) + 0.6 * math.cos(t * 2.17 + seed)) * 1.8
    cx = clamp(cx, cw / 2, pw - cw / 2)
    cy = clamp(cy, ch / 2, ph - ch / 2)
    crop = im.crop((int(cx - cw / 2), int(cy - ch / 2),
                    int(cx + cw / 2), int(cy + ch / 2)))
    crop = crop.resize((W, H), Image.LANCZOS)
    arr = np.asarray(crop, np.float32) / 255.0
    # gate weave
    dy = 1 if math.sin(t * 8.1 + seed) > 0.93 else 0
    dx = 1 if math.sin(t * 6.7 + seed * 5) > 0.94 else 0
    if dx or dy:
        arr = np.roll(arr, (dy, dx), axis=(0, 1))
    return arr


def composite_shots(t):
    active = []
    for s in SHOTS:
        if not (s["t0"] <= t < s["t1"]):
            continue
        w = 1.0
        if t < s["t0"] + CFG["fade"]:
            w = min(w, smooth((t - s["t0"]) / CFG["fade"]))
        if t > s["t1"] - CFG["fade"]:
            w = min(w, smooth((s["t1"] - t) / CFG["fade"]))
        active.append((s, max(w, 0.0)))

    if not active:
        return np.zeros((H, W, 3), np.float32), 0.0
    if len(active) == 1:
        s, w = active[0]
        return np.clip(shot_array(s, t) * w, 0, 1), 0.0

    total = sum(w for _, w in active)
    out = None
    for s, w in active:
        a = shot_array(s, t) * (w / total)
        out = a if out is None else out + a
    leak = min(active[0][1], active[1][1]) * 2.0
    return np.clip(out, 0, 1), leak


# ------------------------------------------------------------------ grade
def init_globals():
    global _vignette, _grad, _open_scrim
    if _vignette is not None:
        return
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    r = np.sqrt(nx * nx * 0.85 + ny * ny) / 1.25
    _vignette = (1.0 - 0.30 * np.clip(r, 0, 1) ** 2.3)[..., None].astype(np.float32)
    band = np.clip((yy - 1290) / 110, 0, 1) * np.clip((1800 - yy) / 150, 0, 1)
    band = band * band * (3 - 2 * band)
    _grad = (1.0 - 0.32 * band)[..., None].astype(np.float32)
    top = np.clip((yy - 560) / 130, 0, 1) * np.clip((1080 - yy) / 170, 0, 1)
    top = top * top * (3 - 2 * top)
    a = (0.42 * top * 255).astype(np.uint8)
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., 3] = a
    _open_scrim = Image.fromarray(rgba, "RGBA")


def grade(arr, t, leak):
    # halation: blurred warm highlights
    small = arr[::4, ::4]
    lum = small.mean(2)
    hi = np.clip(lum - 0.62, 0, 1) ** 1.25
    b = gaussian_filter(hi, 3.2)
    b_img = Image.fromarray((np.clip(b * 2.6, 0, 1) * 255).astype(np.uint8))
    b = np.asarray(b_img.resize((W, H), Image.BICUBIC), np.float32) / 255.0
    arr = arr + b[..., None] * np.array([0.085, 0.050, 0.030], np.float32)

    # gentle S-curve, restrained saturation
    arr = (arr - 0.5) * 1.075 + 0.5
    lum = arr.mean(2, keepdims=True)
    arr = lum + (arr - lum) * 1.08

    # split tone: teal shadows, amber highlights
    l = np.clip(arr.mean(2), 0, 1)
    arr = arr + ((1 - l) ** 2)[..., None] * np.array([-0.010, 0.005, 0.018], np.float32)
    arr = arr + (l ** 2)[..., None] * np.array([0.016, 0.006, -0.007], np.float32)

    # light leak during dissolves
    if leak > 0.02:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        g = np.clip((xx / W * 0.55 + (1 - yy / H) * 0.75) - 0.55, 0, 1) ** 1.4
        arr = arr + g[..., None] * np.array([0.10, 0.045, 0.012], np.float32) * leak

    arr = arr * _vignette
    arr = np.clip(arr, 0, 1)
    arr = np.clip((arr - 0.008) / 0.984, 0, 1)
    return arr


def finish(arr, i, t, sub_active):
    if sub_active:
        arr = arr * _grad
    rng = np.random.default_rng(10007 + i * 7919)
    # grain, stronger in the shadows, plus a touch of chroma noise
    g = rng.normal(0, 1, (H, W, 1)).astype(np.float32)
    lum = arr.mean(2, keepdims=True)
    arr = arr + g * (0.011 + 0.012 * (1 - lum))
    arr = arr + rng.normal(0, 0.0022, (H, W, 1)).astype(np.float32)
    # exposure breathing
    arr = arr * (1.0 + 0.006 * math.sin(t * 3.1) + 0.004 * math.sin(t * 0.77))
    return np.clip(arr, 0, 1)


# ------------------------------------------------------------------ text
def text_width(d, text, fnt, tracking):
    if tracking <= 0:
        return d.textlength(text, font=fnt)
    return sum(d.textlength(ch, font=fnt) + tracking for ch in text) - tracking


def text_block(lines, path, size, gap, color, tracking=0, shadow=0.85):
    key = (tuple(lines), path, size, gap, color, tracking, shadow)
    if key in _blocks:
        return _blocks[key]
    fnt = font(path, size)
    tmp = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    widths = [text_width(tmp, ln, fnt, tracking) for ln in lines]
    bw = int(max(widths)) + 90
    line_h = size + gap
    bh = line_h * len(lines) + 90
    block = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    sh = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    ds = ImageDraw.Draw(sh)

    def draw(target_lines, dy, fill, drawer):
        for k, ln in enumerate(target_lines):
            w = text_width(tmp, ln, fnt, tracking)
            x = (bw - w) / 2
            y = 45 + k * line_h + dy
            stroke = dict(stroke_width=1, stroke_fill=(0, 0, 0, 130))
            if tracking <= 0:
                drawer.text((x, y), ln, font=fnt, fill=fill, anchor="la", **stroke)
            else:
                for ch in ln:
                    drawer.text((x, y), ch, font=fnt, fill=fill, anchor="la", **stroke)
                    x += tmp.textlength(ch, font=fnt) + tracking

    draw(lines, 6, (0, 0, 0, 255), ds)
    sh = sh.filter(ImageFilter.GaussianBlur(12))
    alpha = sh.getchannel("A").point(lambda v: int(v * shadow))
    sh.putalpha(alpha)
    block = Image.alpha_composite(block, sh)
    draw(lines, 0, color + (248,), ImageDraw.Draw(block))
    _blocks[key] = block
    return block


def paste_block(img, block, cy, alpha=1.0, rise=0.0):
    if alpha <= 0.01:
        return
    if alpha < 0.999:
        b = block.copy()
        b.putalpha(b.getchannel("A").point(lambda v: int(v * alpha)))
    else:
        b = block
    x = (W - b.width) // 2
    y = int(cy - b.height / 2 + rise)
    img.alpha_composite(b, (x, y))


def subtitle_at(t):
    for idx, sub in enumerate(CFG["subtitles"]):
        if sub["t"] <= t < sub["end"]:
            a = min(smooth((t - sub["t"]) / 0.30), smooth((sub["end"] - t) / 0.30))
            return idx, sub, a
    return None, None, 0.0


def draw_subtitle(img, t):
    idx, sub, a = subtitle_at(t)
    if not sub or a <= 0.01:
        return False
    block = text_block(sub["lines"], F_SERIF_MED, 48, 20, WHITE, tracking=2)
    paste_block(img, block, 1530, a, rise=(1 - a) * 10)
    return True


def draw_open_card(img, t):
    c = CFG["cards"]["open"]
    if not (c["t0"] <= t < c["t1"]):
        return
    a = min(smooth((t - c["t0"]) / 0.55), smooth((c["t1"] - t) / 0.45))
    if a <= 0.01:
        return
    scrim = _open_scrim
    if a < 0.999:
        scrim = _open_scrim.copy()
        scrim.putalpha(scrim.getchannel("A").point(lambda v: int(v * a)))
    img.alpha_composite(scrim)
    eyebrow = text_block(["TRAVEL  NOTES  ·  2026"], F_SANS, 20, 0, MUTED, tracking=6)
    title = text_block([CFG["title"]], F_SERIF_MED, 104, 0, WHITE, tracking=10)
    english = text_block([CFG["english"]], F_SANS, 19, 0, MUTED, tracking=4)
    paste_block(img, eyebrow, 700, a * 0.9)
    paste_block(img, title, 825, a)
    # thin rule
    rule = Image.new("RGBA", (160, 2), (235, 230, 216, int(160 * a)))
    img.alpha_composite(rule, ((W - 160) // 2, 914))
    paste_block(img, english, 968, a * 0.9)


def draw_close_card(img, t):
    c = CFG["cards"]["close"]
    if not (c["t0"] <= t < c["t1"]):
        return
    a = min(smooth((t - c["t0"]) / 0.8), smooth((c["t1"] - t) / 0.9))
    if a <= 0.01:
        return
    title = text_block([CFG["title"]], F_SERIF_MED, 84, 0, WHITE, tracking=8)
    line2 = text_block(["那就一直走。"], F_SERIF, 48, 0, WHITE, tracking=4)
    line3 = text_block(["写给还在路上的你"], F_SERIF, 24, 0, MUTED, tracking=3)
    paste_block(img, title, 860, a)
    paste_block(img, line2, 960, a * 0.96)
    rule = Image.new("RGBA", (120, 1), (235, 230, 216, int(120 * a)))
    img.alpha_composite(rule, ((W - 120) // 2, 1012))
    paste_block(img, line3, 1052, a * 0.85)


# ------------------------------------------------------------------ frame
def render_frame(i):
    init_globals()
    t = i / FPS
    arr, leak = composite_shots(t)
    arr = grade(arr, t, leak)
    idx, sub, _ = subtitle_at(t)
    arr = finish(arr, i, t, sub is not None)
    img = Image.fromarray((arr * 255).astype(np.uint8)).convert("RGBA")
    draw_subtitle(img, t)
    draw_open_card(img, t)
    draw_close_card(img, t)
    return img.convert("RGB")


def render_one(i):
    render_frame(i).save(os.path.join(FRAMES_DIR, f"f_{i:04d}.jpg"), quality=94)
    return i


def render_sample(times):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    for t in times:
        i = min(NFRAMES - 1, int(round(t * FPS)))
        p = os.path.join(PREVIEW_DIR, f"t{t:05.2f}.jpg")
        render_frame(i).save(p, quality=94)
        print("sample", p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sample", "all"], default="sample")
    ap.add_argument("--times", type=float, nargs="*",
                    default=[1.8, 5.0, 10.0, 14.5, 18.5, 22.5, 26.5, 30.5, 34.5, 38.5, 42.5, 46.5, 50.0])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=NFRAMES)
    args = ap.parse_args()

    if args.mode == "sample":
        render_sample(args.times)
        return

    os.makedirs(FRAMES_DIR, exist_ok=True)
    with Pool(args.workers) as pool:
        for k in pool.imap_unordered(render_one, range(args.start, args.end), chunksize=8):
            if k % 150 == 0:
                print(f"  {k}/{args.end}", flush=True)
    print(f"done {args.end - args.start} frames -> {FRAMES_DIR}")


if __name__ == "__main__":
    main()
