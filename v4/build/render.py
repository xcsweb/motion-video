#!/usr/bin/env python3
"""RAILGUN // OVERDRIVE v4 复刻版。

三类素材：
  image  — AI 插画 + Ken Burns 运镜 + 统一调色
  web    — HTML 页面用 Playwright 逐帧截取，按 t 取帧
  cannon — 复用 v1 的电磁炮绘制函数，按 6 个机位重新取景

UI 层（卡拉 OK 歌词 / HUD / 片头片尾）最后叠加，不受镜头运动影响。
"""
import argparse
import glob
import importlib.util
import json
import math
import os
from bisect import bisect_right
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import gaussian_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H, FPS = 1920, 1080, 30
DUR = 85.29
NFRAMES = int(round(DUR * FPS))

TIMELINE = json.load(open(os.path.join(ROOT, "config", "timeline.json")))
SCENES = TIMELINE["scenes"]
LYRICS = json.load(open(os.path.join(ROOT, "config", "lyrics.json")))["lyrics"]
AI_DIR = os.path.join(ROOT, "assets", "ai")
WEB_DIR = os.path.join(ROOT, "assets", "web")
FRAMES_DIR = os.path.join(ROOT, "frames")
PREVIEW_DIR = os.path.join(ROOT, "previews")

F_LATO = "/usr/share/fonts/truetype/lato/Lato-Black.ttf"
F_MONO = "/usr/share/fonts/truetype/firacode/FiraCode-Bold.ttf"
F_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"

CYAN = (0, 225, 255)
MAGENTA = (255, 46, 209)
GOLD = (255, 190, 70)
WHITE = (255, 255, 255)

# 复用 v1 的程序化绘制函数
_spec = importlib.util.spec_from_file_location(
    "rgbase", os.path.join(ROOT, "..", "scripts", "render.py"))
RG = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RG)

_font_cache = {}
_img_cache = {}
_base_bg = None
_vign = None
_band = None
_grain = None
_left_oval = None
_end_panel = None


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size, index=0)
    return _font_cache[key]


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def sc(c, f):
    f = max(0.0, min(1.0, f))
    return tuple(int(c[k] * f) for k in range(3))


def scene_at(t):
    for s in SCENES:
        if s["t0"] <= t < s["t1"]:
            return s, (t - s["t0"]) / max(1e-6, s["t1"] - s["t0"])
    return SCENES[-1], 1.0


def _init():
    global _base_bg, _vign, _band, _grain, _left_oval, _end_panel
    if _base_bg is not None:
        return
    _base_bg = RG.build_background()
    _vign = RG.build_vignette()
    yy = np.arange(H, dtype=np.float32)
    up = np.clip((yy - 770) / 62, 0, 1)
    up = up * up * (3 - 2 * up)
    dn = np.clip((1000 - yy) / 58, 0, 1)
    dn = dn * dn * (3 - 2 * dn)
    _band = (up * dn)[:, None, None] * 0.45
    rng = np.random.default_rng(99)
    _grain = [rng.normal(0, 1, (H, W, 1)).astype(np.float32) for _ in range(6)]
    yy2, xx2 = np.mgrid[0:H, 0:W].astype(np.float32)
    oval = ((xx2 - 540) / 760) ** 2 + ((yy2 - 430) / 430) ** 2
    _left_oval = (np.clip(1 - oval, 0, 1) ** 0.8)[..., None] * 0.55
    mx = np.clip((1520 - xx2) / 140, 0, 1) * np.clip((xx2 - 330) / 140, 0, 1)
    my = np.clip((1020 - yy2) / 140, 0, 1) * np.clip((yy2 - 640) / 140, 0, 1)
    _end_panel = (mx * my * 0.58)[..., None]


# ------------------------------------------------------------------ 素材
def load_image(asset):
    if asset in _img_cache:
        return _img_cache[asset]
    path = None
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        p = os.path.join(AI_DIR, asset + ext)
        if os.path.exists(p):
            path = p
            break
    if path is None:  # 缺图时用深色占位，保证流程可跑
        arr = np.zeros((H, W, 3), np.float32)
    else:
        im = Image.open(path).convert("RGB")
        sw, sh = im.size
        # 裁掉生成图底部的水印带
        im = im.crop((0, 0, sw, int(sh * 0.85)))
        sw, sh = im.size
        target = W / H
        if sw / sh > target:
            nw = int(sh * target)
            im = im.crop(((sw - nw) // 2, 0, (sw + nw) // 2, sh))
        else:
            nh = int(sw / target)
            im = im.crop((0, (sh - nh) // 2, sw, (sh + nh) // 2))
        arr = np.asarray(im, np.float32) / 255.0
    _img_cache[asset] = arr
    return arr


def web_frame(page, local_t):
    files = sorted(glob.glob(os.path.join(WEB_DIR, page, "f_*.jpg")))
    if not files:
        return np.zeros((H, W, 3), np.float32)
    idx = min(len(files) - 1, max(0, int(round(local_t * 24))))
    im = Image.open(files[idx]).convert("RGB")
    return np.asarray(im, np.float32) / 255.0


# ------------------------------------------------------------------ 镜头
def apply_camera(arr, s, p, t):
    z = s["z0"] + (s["z1"] - s["z0"]) * smooth(p)
    if s.get("cut") == "punch":
        tb = t - s["t0"]
        if 0 <= tb < 0.22:
            z += 0.07 * math.exp(-tb * 15)
    h, w = arr.shape[:2]
    cw, ch = w / z, h / z
    cx = min(max(s["cx"] * w, cw / 2), w - cw / 2)
    cy = min(max(s["cy"] * h, ch / 2), h - ch / 2)
    im = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    crop = im.crop((int(cx - cw / 2), int(cy - ch / 2),
                    int(cx + cw / 2), int(cy + ch / 2)))
    if abs(s.get("rot", 0)) > 0.01:
        crop = crop.rotate(s["rot"], resample=Image.BICUBIC, expand=False)
        k = 1.02 + abs(s["rot"]) * 0.006
        cw2, ch2 = crop.size
        crop = crop.crop((cw2 * (1 - 1 / k) / 2, ch2 * (1 - 1 / k) / 2,
                          cw2 * (1 + 1 / k) / 2, ch2 * (1 + 1 / k) / 2))
    return np.asarray(crop.resize((W, H), Image.BICUBIC), np.float32) / 255.0


def apply_transition(img, s, t):
    tb = t - s["t0"]
    if not (0 <= tb < 0.34):
        return img
    cut = s.get("cut")
    if cut == "flash":
        img = img + 0.45 * math.exp(-tb * 13.0)
    elif cut == "whip":
        k = 0.5 * math.exp(-tb * 9.0)
        a = np.zeros_like(img)
        for j in range(5):
            a += np.roll(img, int((j - 2) * 150 * k), axis=1)
        img = img * (1 - k) + a / 5.0 * k
    elif cut == "glitch":
        rnd = np.random.default_rng(int(t * 3000) + 17)
        n = int(4 + 12 * math.exp(-tb * 8))
        for _ in range(n):
            y0 = int(rnd.integers(0, img.shape[0] - 40))
            hh = int(rnd.integers(4, 50))
            dx = int(rnd.normal(0, 80 * math.exp(-tb * 7)))
            img[y0:y0 + hh] = np.roll(img[y0:y0 + hh], dx, axis=1)
    elif cut == "fade":
        img = img * smooth(tb / 0.40)
    return img


def grade(arr, tint):
    a = arr
    small = a[::4, ::4]
    lum = small.mean(2)
    hi = np.clip(lum - 0.55, 0, 1) ** 1.5
    bloom = gaussian_filter(hi, 5.0)
    bloom = np.asarray(Image.fromarray((np.clip(bloom, 0, 1) * 255).astype(np.uint8))
                       .resize((W, H), Image.BICUBIC), np.float32) / 255.0
    a = a + bloom[..., None] * np.array([0.07, 0.045, 0.11], np.float32)
    a = (a - 0.5) * 1.04 + 0.5
    a *= np.array(tint, np.float32)
    return np.clip(a, 0, 1)


# ------------------------------------------------------------------ 电磁炮
def cannon_frame(s, t):
    _init()
    t0 = s["t0"]
    local = t - t0
    ft = max(0.02, s["fire"] - t0)
    if local < ft:
        cp = 0.08 + 0.92 * smooth(local / ft)
        heat = 0.10 * (1 - local / ft) * 0
    else:
        cp = 0.95 * math.exp(-(local - ft) * 4.0)
        heat = 0.92 * math.exp(-(local - ft) * 1.6)
    recoil = 0.0
    if local >= ft:
        ts = local - ft
        recoil = 28 * math.exp(-ts * 9.0) * math.cos(ts * 28.0)
    geo = {"off": -RG.U * recoil}
    rnd = np.random.default_rng(int(t * 1000) + 7)

    base = Image.fromarray((np.clip(_base_bg, 0, 1) * 255).astype(np.uint8))
    em = Image.new("RGB", (W, H), "black")
    sp = Image.new("RGB", (W, H), "black")
    d = ImageDraw.Draw(em)
    RG.draw_rails(d, geo, cp, heat, rnd)
    RG.draw_coils(d, geo, local, cp, heat, 0.0, rnd)
    core, _r = RG.draw_core(d, geo, local, cp, heat, rnd)
    RG.draw_arcs(d, geo, local, cp, heat, rnd)

    if local >= ft:
        ts = local - ft
        RG.draw_muzzle_flash(sp, RG.MUZ, ts, 1.0)
        RG.draw_burst(em, RG.MUZ, ts, 90, int(t * 30), 1.1)
        RG.draw_shockwave(em, RG.MUZ, ts, CYAN, 1.2)
        RG.draw_projectile(sp, local, ft, rnd, 1.0)
        # 炮口辉光
        RG.add_radial(em, RG.MUZ, 260, CYAN, MAGENTA, 0.9)
        # 冲击帧的径向速度线
        if ts < 0.28:
            a = 1 - ts / 0.28
            dd = ImageDraw.Draw(sp)
            for k in range(44):
                ang = k * math.pi * 2 / 44 + rnd.normal(0, .04)
                r0 = 180 + 60 * rnd.random()
                r1 = 900 + 300 * rnd.random()
                dd.line([(RG.MUZ[0] + math.cos(ang) * r0, RG.MUZ[1] + math.sin(ang) * r0),
                         (RG.MUZ[0] + math.cos(ang) * r1, RG.MUZ[1] + math.sin(ang) * r1)],
                        fill=sc(WHITE, .22 * a), width=2)
        # 蓄力时核心到炮口的电弧
    else:
        ts = ft - local
        if ts < 0.7:
            f = 1 - ts / 0.7
            RG.bolt(d, core, RG.MUZ, 6, RG.mix(WHITE, CYAN, .3),
                    np.random.default_rng(int(t * 30) + 51), disp=30 * (1 - f) + 4, depth=4)

    out = np.asarray(base, np.float32) + np.asarray(em, np.float32) + np.asarray(sp, np.float32) * 1.15
    return np.clip(out / 255.0, 0, 1)


# ------------------------------------------------------------------ UI
def draw_lyrics(ui, t):
    ly = None
    for item in LYRICS:
        if item["t"] <= t < item["end"]:
            ly = item
            break
    if not ly:
        return
    fade = max(0.0, min(1.0, (t - ly["t"]) / 0.22, (ly["end"] - t) / 0.22))
    if fade <= 0.02:
        return
    jp = ly["jp"]
    n = len(jp)
    size = 64 if n <= 16 else (54 if n <= 26 else 46)
    f = font(F_CJK, size)
    d = ImageDraw.Draw(ui)
    widths = [d.textlength(ch, font=f) for ch in jp]
    total = sum(widths)
    x = 960 - total / 2
    y = 838
    p = (t - ly["t"]) / max(0.01, ly["end"] - ly["t"])
    rv = p * n * 1.12
    for k, (ch, wd) in enumerate(zip(jp, widths)):
        if k < int(rv):
            col = WHITE
            if ly.get("hit") and k >= int(rv) - 2:
                col = (255, 240, 205)
        elif k == int(rv):
            col = (170, 215, 235)
        else:
            col = (78, 128, 152)
        d.text((x + 2, y + 2), ch, font=f, fill=(0, 0, 0, int(190 * fade)), anchor="lm")
        d.text((x, y), ch, font=f, fill=sc(col, 0.55 + 0.45 * fade), anchor="lm")
        x += wd
    if ly.get("cn"):
        fc = font(F_CJK, 30)
        d.text((962, 900), ly["cn"], font=fc, fill=(0, 0, 0, int(180 * fade)), anchor="mm")
        d.text((960, 898), ly["cn"], font=fc, fill=sc((205, 235, 245), 0.92 * fade), anchor="mm")
    bw, bx, by = 620, 650, 938
    d.line([(bx, by), (bx + bw, by)], fill=sc((90, 165, 190), 0.55 * fade), width=3)
    d.line([(bx, by), (bx + int(bw * min(1.0, p * 1.02)), by)],
           fill=sc(GOLD if ly.get("hit") else CYAN, 0.95 * fade), width=3)
    for k in range(9):
        xx = bx + bw * k / 8
        d.line([(xx, by - 7), (xx, by - 2)], fill=sc(CYAN, 0.5 * fade), width=1)
    if ly.get("hit"):
        d.rectangle([416, 808, 423, 868], fill=sc(GOLD, 0.9 * fade))
        d.text((960, 966), "★  HIT LINE", font=font(F_MONO, 17),
               fill=sc((255, 225, 160), 0.8 * fade), anchor="mm")


def draw_hud(ui, t, s, idx):
    d = ImageDraw.Draw(ui)
    d.text((72, 50), "RAILGUN // OVERDRIVE", font=font(F_LATO, 26),
           fill=(235, 248, 255, 235))
    d.text((74, 88), "ELECTROMAGNETIC OVERDRIVE  /  85 SEC", font=font(F_MONO, 14),
           fill=(120, 180, 200, 210))
    d.text((W - 74, 52), f"CUT {idx + 1:02d} / {len(SCENES):02d}", font=font(F_MONO, 17),
           fill=(150, 200, 220, 210), anchor="ra")
    d.text((W - 74, 80), RG_TIME(t), font=font(F_MONO, 15),
           fill=(110, 165, 185, 200), anchor="ra")
    lab = {"image": "ANIME PLATE / AI PAINT", "cannon": "RAILGUN SYSTEM"}.get(s["kind"], "")
    if lab:
        d.text((W - 74, H - 52), lab, font=font(F_MONO, 13),
               fill=(110, 170, 190, 190), anchor="ra")


def RG_TIME(t):
    f = int(t * FPS)
    return f"{f // (FPS * 60):02d}:{(f // FPS) % 60:02d}:{f % FPS:02d}"


def chroma(ui, xy, text, fnt, fill, spacing=0, split=4, anchor="lm"):
    d = ImageDraw.Draw(ui)
    for dx, col in ((-split, sc(CYAN, .7)), (split, sc(MAGENTA, .7))):
        x = xy[0]
        for ch in text:
            d.text((x + dx, xy[1] + (1 if dx > 0 else 0)), ch, font=fnt, fill=col, anchor=anchor)
            x += d.textlength(ch, font=fnt) + spacing
    x = xy[0]
    for ch in text:
        d.text((x, xy[1]), ch, font=fnt, fill=fill, anchor=anchor)
        x += d.textlength(ch, font=fnt) + spacing


def draw_titles(ui, t):
    d = ImageDraw.Draw(ui)
    if t < 2.30:
        a = smooth((t - 0.20) / 0.45) * smooth((2.30 - t) / 0.30)
        if a > 0.02:
            chroma(ui, (430, 330), "RAILGUN", font(F_LATO, 150), sc(WHITE, .96 * a), spacing=5, split=5)
            d.text((432, 428), "only my railgun  /  ELECTROMAGNETIC OVERDRIVE",
                   font=font(F_MONO, 22), fill=sc(CYAN, .9 * a))
            d.text((432, 472), "电 磁 炮 · 过 载", font=font(F_CJK, 30), fill=sc(GOLD, .9 * a))
            d.line([(432, 458), (432 + 600 * smooth((t - .3) / .6), 458)],
                   fill=sc(CYAN, .5 * a), width=2)
    if t >= 81.60:
        a = smooth((t - 81.60) / 0.7)
        a *= max(0.0, min(1.0, (DUR - t) / 0.8))
        if a > 0.02:
            d.line([(432, 688), (432 + 720, 688)], fill=sc(CYAN, .55 * a), width=2)
            chroma(ui, (430, 752), "RAILGUN", font(F_LATO, 128), sc(WHITE, .95 * a), spacing=4, split=4)
            d.text((432, 828), "only my railgun", font=font(F_LATO, 34), fill=sc(WHITE, .85 * a))
            d.text((432, 872), "fripSide  /  NBC Universal Japan", font=font(F_MONO, 19),
                   fill=sc(CYAN, .85 * a))
            d.text((432, 908), "143 BPM  ·  1920×1080  ·  30 FPS", font=font(F_MONO, 17),
                   fill=sc((165, 200, 215), .85 * a))
            d.text((432, 944), "FAN-MADE TECHNICAL DEMO  ·  NOT OFFICIAL", font=font(F_MONO, 14),
                   fill=sc((130, 160, 175), .8 * a))


# ------------------------------------------------------------------ 单帧
def render_frame(i):
    _init()
    t = i / FPS
    s, p = scene_at(t)
    kind = s["kind"]

    if kind == "image":
        arr = load_image(s["asset"])
        arr = apply_camera(arr, s, p, t)
    elif kind == "web":
        arr = web_frame(s["page"], t - s["t0"])
        z = 1.0
        if s.get("cut") == "punch":
            tb = t - s["t0"]
            if tb < 0.22:
                z += 0.05 * math.exp(-tb * 15)
        if z > 1.001:
            im = Image.fromarray((arr * 255).astype(np.uint8))
            cw, ch = int(W / z), int(H / z)
            im = im.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2))
            arr = np.asarray(im.resize((W, H), Image.BICUBIC), np.float32) / 255.0
    else:
        arr = cannon_frame(s, t)

    arr = grade(arr, s.get("tint", (1, 1, 1)))
    arr = apply_transition(arr, s, t)
    arr *= _vign

    # 片头/片尾左侧暗化，保证标题可读
    if t < 2.3 or t >= 81.6:
        strength = 1.6 if t >= 81.6 else 1.0
        arr = arr * np.clip(1 - _left_oval * strength, 0.08, 1)
    if t >= 81.6:
        arr = arr * (1 - _end_panel)

    # 歌词暗带
    arr = arr * (1 - _band)

    # gate weave + 曝光闪烁
    if t < 2.3 or t >= 81.6:
        pass
    r = np.random.default_rng(1000 + i)
    arr = np.roll(arr, int(r.integers(-1, 2)), axis=0)
    arr = np.roll(arr, int(r.integers(-1, 2)), axis=1)
    arr *= 1.0 + 0.015 * float(r.normal())
    g = _grain[i % 6]
    arr = arr + g * 0.010 + r.normal(0, 0.0025)

    ui = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    show_hud = kind in ("image", "cannon") and t >= 2.30 and t < 81.60
    if show_hud:
        draw_hud(ui, t, s, SCENES.index(s))
    draw_lyrics(ui, t)
    draw_titles(ui, t)

    base = Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))
    base = Image.alpha_composite(base.convert("RGBA"), ui).convert("RGB")
    return base


def render_one(i):
    img = render_frame(i)
    img.save(os.path.join(FRAMES_DIR, f"f_{i:04d}.jpg"), quality=94)
    return i


def render_sample(times):
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    out = []
    for t in times:
        i = min(NFRAMES - 1, int(round(t * FPS)))
        img = render_frame(i)
        p = os.path.join(PREVIEW_DIR, f"t{t:05.2f}_f{i:04d}.png")
        img.save(p)
        out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sample", "all"], default="sample")
    ap.add_argument("--times", type=float, nargs="*", default=[1.5, 6.0, 12.6, 20.0, 37.0, 49.0, 58.0, 70.0, 79.0])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=NFRAMES)
    args = ap.parse_args()

    if args.mode == "sample":
        for p in render_sample(args.times):
            print("sample", p)
        return

    os.makedirs(FRAMES_DIR, exist_ok=True)
    n = args.end - args.start
    with Pool(args.workers) as pool:
        for k in pool.imap_unordered(render_one, range(args.start, args.end), chunksize=8):
            if k % 100 == 0:
                print(f"  {k}/{args.end}", flush=True)
    print(f"done {n} frames -> {FRAMES_DIR}")


if __name__ == "__main__":
    main()
