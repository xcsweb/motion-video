#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render.py — 《同一个 nana，两种命》竖屏短片帧渲染 / 封面 / 联系表

用法:
  python3 render.py --samples            # 12 张样帧 -> out/samples/
  python3 render.py --all                # 1050 帧 -> frames/f_%05d.jpg
  python3 render.py --all --workers 4
  python3 render.py --cover --contact    # 封面 + 联系表
"""
import argparse
import math
import os
import sys
import traceback
from functools import lru_cache
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

# ----------------------------------------------------------------------------- 基础
ROOT = "/workspace/nana"
AI = os.path.join(ROOT, "assets", "ai")
OUT = os.path.join(ROOT, "out")
FRAMES = os.path.join(ROOT, "frames")
SAMPLES = os.path.join(OUT, "samples")

W, H = 1080, 1920
FPS = 30
DUR = 35.0
NF = int(round(DUR * FPS))          # 1050

WHITE = (255, 255, 255)
PINK = (255, 92, 168)
PINK_SOFT = (255, 168, 214)
CYAN = (120, 215, 255)
INK = (14, 12, 18)

NOTO_BLACK = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 2)
NOTO_MEDIUM = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc", 2)
SERIF_BLACK = ("/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc", 2)
SMILEY = ("/usr/share/fonts/opentype/smiley-sans/SmileySans-Oblique.otf", 0)
LATO = ("/usr/share/fonts/truetype/lato/Lato-Black.ttf", 0)

WHITE_IMG = Image.new("RGB", (W, H), WHITE)


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = clamp((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def ease_out(x):
    x = clamp(x, 0, 1)
    return 1 - (1 - x) ** 3


def ease_out_back(x, s=1.70158):
    x = clamp(x, 0, 1) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


@lru_cache(maxsize=256)
def F(fk, size):
    path, idx = fk
    return ImageFont.truetype(path, int(size), index=idx)


# ----------------------------------------------------------------------------- 素材
_IMGS = {}


def src(name):
    if name not in _IMGS:
        p = os.path.join(AI, name + ".jpg")
        _IMGS[name] = Image.open(p).convert("RGB")
    return _IMGS[name]


def outro_img():
    """outro 优先 b4b（白色碎花睡衣，与 b2/b3 连续），缺失时回退 b4。"""
    return src("b4b_gentle" if os.path.exists(os.path.join(AI, "b4b_gentle.jpg")) else "b4_gentle")


# ----------------------------------------------------------------------------- 裁切 / 调色
def crop_resize(im, z, fx, fy, panx=0.0, pany=0.0, out=(W, H), bottom=2430.0):
    """按 zoom / 焦点裁切。bottom 保证裁切底边不进右下角 AI 水印区。"""
    sw, sh = im.size
    cw, ch = sw / z, sh / z
    l = fx * sw - cw / 2 + panx
    t = fy * sh - ch / 2 + pany
    l = clamp(l, 0.0, sw - cw)
    t = clamp(t, 0.0, sh - ch)
    t = min(t, max(0.0, bottom - ch))
    return im.resize(out, Image.BICUBIC, box=(l, t, l + cw, t + ch))


def crop_aspect(im, out, z, fx, fy, bottom=2430.0):
    sw, sh = im.size
    ar = out[0] / out[1]
    ch = sh / z
    cw = ch * ar
    if cw > sw:
        cw = sw
        ch = cw / ar
    l = clamp(fx * sw - cw / 2, 0.0, sw - cw)
    t = clamp(fy * sh - ch / 2, 0.0, sh - ch)
    t = min(t, max(0.0, bottom - ch))
    return im.resize(out, Image.BICUBIC, box=(l, t, l + cw, t + ch))


@lru_cache(maxsize=96)
def _lut(contrast, brightness, gamma, lift, gain):
    out = []
    lr, lg, lb = lift
    gr, gg, gb = gain
    gains = (gr, gg, gb)
    lifts = (lr, lg, lb)
    for c in range(3):
        for v in range(256):
            x = v / 255.0
            x = (x - 0.5) * contrast + 0.5
            x *= brightness
            x = max(0.0, x) ** gamma
            x = x * gains[c] + lifts[c]
            out.append(clamp(int(round(x * 255)), 0, 255))
    return out


def grade(img, contrast=1.0, brightness=1.0, gamma=1.0, lift=(0, 0, 0), gain=(1, 1, 1), tint=None, tint_amt=0.0):
    img = img.point(_lut(contrast, brightness, gamma, tuple(lift), tuple(gain)))
    if tint and tint_amt > 0:
        img = Image.blend(img, Image.new("RGB", img.size, tint), tint_amt)
    return img


def grade_a(img, bright=1.0):
    return grade(img, 1.06, 1.02 * bright, 0.965, lift=(0.006, 0.0, 0.012),
                 gain=(1.02, 0.995, 1.05), tint=(255, 198, 238), tint_amt=0.055)


def grade_b(img, bright=1.0):
    return grade(img, 1.20, 1.0 * bright, 1.01, lift=(0.0, 0.004, 0.022),
                 gain=(0.965, 1.0, 1.09), tint=(96, 176, 255), tint_amt=0.055)


def grade_warm(img):
    return grade(img, 1.04, 1.05, 1.0, lift=(0.012, 0.006, 0.0),
                 gain=(1.06, 1.0, 0.93), tint=(255, 186, 120), tint_amt=0.07)


def bloom(img, amount=0.18, radius=16):
    if amount <= 0.001:
        return img
    small = img.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(radius / 4.0))
    up = small.resize((W, H), Image.BILINEAR)
    return Image.blend(img, ImageChops.screen(img, up), clamp(amount, 0, 1))


@lru_cache(maxsize=8)
def vignette(strength):
    w, h = W // 4, H // 4
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx - w / 2) / (w / 2)
    ny = (yy - h / 2) / (h / 2)
    r = np.sqrt(nx ** 2 + ny ** 2) / 1.414
    m = 1.0 - strength * np.clip(r, 0, 1) ** 1.6
    arr = np.stack([m * 255.0] * 3, -1).astype(np.uint8)
    return Image.fromarray(arr).resize((W, H), Image.BILINEAR)


def add_grain(img, seed, amp=6):
    arr = np.asarray(img, dtype=np.int16).copy()
    rng = np.random.default_rng(seed)
    n = rng.integers(-amp, amp + 1, size=(H // 4, W // 4)).astype(np.int16)
    n = np.repeat(np.repeat(n, 4, 0), 4, 1)
    arr += n[:, :, None]
    np.clip(arr, 0, 255, out=arr)
    return Image.fromarray(arr.astype(np.uint8))


def glitch(img, seed, strength=1.0):
    arr = np.asarray(img).copy()
    rng = np.random.default_rng(seed)
    for _ in range(int(rng.integers(4, 9))):
        y0 = int(rng.integers(0, H - 60))
        hh = int(rng.integers(6, 44))
        dx = int(rng.integers(-16, 17) * strength)
        arr[y0:y0 + hh] = np.roll(arr[y0:y0 + hh], dx, axis=1)
    sh = int(max(2, 7 * strength))
    arr[:, :, 0] = np.roll(arr[:, :, 0], sh, axis=1)
    arr[:, :, 2] = np.roll(arr[:, :, 2], -sh, axis=1)
    return Image.fromarray(arr)


@lru_cache(maxsize=24)
def glow_img(cx, cy, rx, ry, color, strength):
    w, h = W // 4, H // 4
    yy, xx = np.mgrid[0:h, 0:w]
    d = ((xx - cx * w) ** 2) / (rx * w) ** 2 + ((yy - cy * h) ** 2) / (ry * h) ** 2
    m = np.clip(1.0 - d, 0, 1) ** 2 * strength
    arr = (m[..., None] * np.array(color, np.float32)[None, None, :]).astype(np.uint8)
    return Image.fromarray(arr).resize((W, H), Image.BILINEAR)


def add_glow(img, cx, cy, rx, ry, color, strength):
    return ImageChops.screen(img, glow_img(round(cx, 3), round(cy, 3), round(rx, 3), round(ry, 3), tuple(color), round(strength, 3)))


def particles(img, t, seed=3, n=80, rise=0.13, color=(255, 238, 255), alpha=180):
    layer = Image.new("RGBA", (W // 2, H // 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = np.random.default_rng(seed)
    xs = rng.random(n)
    ys = rng.random(n)
    sp = rng.random(n) * 0.6 + 0.5
    sz = rng.random(n)
    ph = rng.random(n) * 6.283
    for i in range(n):
        yy = (ys[i] - rise * t * sp[i]) % 1.0
        xx = (xs[i] + 0.010 * math.sin(t * 0.6 + ph[i])) % 1.0
        X = xx * W / 2
        Y = yy * H / 2
        r = 1.0 + sz[i] * 2.4
        a = int(alpha * (0.35 + 0.65 * abs(math.sin(t * 1.4 + ph[i] * 3))))
        d.ellipse([X - r, Y - r, X + r, Y + r], fill=tuple(color) + (a,))
    layer = layer.filter(ImageFilter.GaussianBlur(1.1)).resize((W, H), Image.BILINEAR)
    img.paste(layer, (0, 0), layer)
    return img


# ----------------------------------------------------------------------------- 文字
def rich_text(runs, tracking=0.0, strokes=(), glow=None):
    """runs: ((text, fontkey, size, fill), ...)  ->  RGBA 图层（已裁紧）"""
    key = (tuple((r[0], r[1], int(r[2]), tuple(r[3])) for r in runs), float(tracking),
           tuple((int(a), tuple(b)) for a, b in strokes), glow)
    return _rich_cached(key)


@lru_cache(maxsize=512)
def _rich_cached(key):
    runs, tracking, strokes, glow = key
    chars = []
    for text, fk, size, fill in runs:
        f = F(fk, size)
        for ch in text:
            chars.append((ch, f, int(size), tuple(fill)))
    widths = [f.getlength(ch) for ch, f, size, fill in chars]
    total = sum(widths) + tracking * max(0, len(chars) - 1)
    maxsize = max(c[2] for c in chars)
    pad = int(maxsize * 1.15) + max([s[0] for s in strokes], default=0)
    cw = int(total) + pad * 2 + 4
    chh = int(maxsize * 1.7) + pad * 2
    img = Image.new("RGBA", (max(8, cw), max(8, chh)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x = float(pad)
    base_y = pad + maxsize
    for (ch, f, size, fill), w in zip(chars, widths):
        for sw, col in sorted(strokes, key=lambda s: -s[0]):
            if sw > 0:
                d.text((x, base_y), ch, font=f, fill=col, anchor="ls",
                       stroke_width=int(sw), stroke_fill=col)
        d.text((x, base_y), ch, font=f, fill=fill, anchor="ls")
        x += w + tracking
    if glow:
        color, amt, rad = tuple(glow[:3]), glow[3], glow[4]
        a = img.getchannel("A")
        g = a.filter(ImageFilter.GaussianBlur(rad))
        gl = Image.new("RGBA", img.size, tuple(color) + (0,))
        gl.putalpha(g.point(lambda v: int(v * amt)))
        img = Image.alpha_composite(gl, img)
    bb = img.getbbox()
    if bb:
        img = img.crop(bb)
    return img


def T(text, fk, size, fill=WHITE, strokes=(), glow=None, tracking=0.0):
    return rich_text(((text, fk, size, fill),), tracking, strokes, glow)


def with_alpha(layer, a):
    if a >= 0.999:
        return layer
    l = layer.copy()
    l.putalpha(l.getchannel("A").point(lambda v: int(v * max(0.0, a))))
    return l


def scaled(layer, s):
    if abs(s - 1.0) < 0.004:
        return layer
    return layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.LANCZOS)


def over(base, layer, cx, cy, s=1.0, rot=0.0, alpha=1.0):
    l = layer
    if s != 1.0:
        l = scaled(l, s)
    if abs(rot) > 0.01:
        l = l.rotate(rot, expand=True, resample=Image.BICUBIC)
    if alpha < 0.999:
        l = with_alpha(l, alpha)
    base.paste(l, (int(round(cx - l.width / 2)), int(round(cy - l.height / 2))), l)


def sticker_style(fill=WHITE, stroke_black=12, stroke_red=6):
    """B 段贴纸字描边规格：白字 + 红黑双描边。"""
    strokes = []
    if stroke_black:
        strokes.append((stroke_black, (12, 10, 14)))
    if stroke_red:
        strokes.append((stroke_red, (232, 24, 52)))
    return tuple(strokes)


# ----------------------------------------------------------------------------- 镜头抖动
def shake(t, t0, dur, amp):
    if t < t0 or t > t0 + dur:
        return 0.0, 0.0
    k = 1 - (t - t0) / dur
    k = k * k
    return amp * k * math.sin((t - t0) * 84.0), amp * 0.8 * k * math.cos((t - t0) * 67.0)


def handheld(t, amp=1.0):
    ox = amp * (2.8 * math.sin(t * 7.1) + 1.6 * math.sin(t * 13.7 + 1.2) + 0.8 * math.sin(t * 23.3 + 0.4))
    oy = amp * (2.3 * math.sin(t * 9.3 + 2.1) + 1.3 * math.sin(t * 17.1 + 0.7))
    return ox, oy


# ----------------------------------------------------------------------------- 1. intro
_TXT_INTRO = "西语会说吧？就是 nana"
_INTRO_BG = None
_INTRO_CHROME = None


def intro_bg():
    global _INTRO_BG
    if _INTRO_BG is None:
        w, h = W // 2, H // 2
        yy, xx = np.mgrid[0:h, 0:w]
        base = np.zeros((h, w, 3), np.float32)
        base[:] = (7, 8, 15)
        for cx, cy, rx, ry, col, amp in (
            (0.26, 0.30, 0.62, 0.46, (26, 40, 96), 0.9),
            (0.76, 0.74, 0.60, 0.44, (78, 26, 62), 0.85),
            (0.50, 0.46, 0.70, 0.30, (16, 18, 42), 0.5),
        ):
            d = ((xx - cx * w) ** 2) / (rx * w) ** 2 + ((yy - cy * h) ** 2) / (ry * h) ** 2
            m = np.clip(1.0 - d, 0, 1) ** 2.2 * amp
            base += m[..., None] * np.array(col, np.float32)[None, None, :]
        np.clip(base, 0, 255, out=base)
        _INTRO_BG = Image.fromarray(base.astype(np.uint8)).resize((W, H), Image.BILINEAR)
    return _INTRO_BG


def intro_chrome():
    global _INTRO_CHROME
    if _INTRO_CHROME is None:
        o = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(o)
        d.rounded_rectangle([100, 815, 980, 985], radius=38, fill=(18, 19, 27, 236),
                            outline=(78, 80, 98, 175), width=2)
        d.rounded_rectangle([100, 815, 980, 985], radius=38, outline=(255, 120, 190, 40), width=1)
        f = F(NOTO_MEDIUM, 30)
        chips = ["中文", "nana", "原创音乐"]
        gap, y, hh = 18, 1042, 56
        ws = [f.getlength(c) + 54 for c in chips]
        total = sum(ws) + gap * (len(chips) - 1)
        x = (W - total) / 2
        for c, cw in zip(chips, ws):
            d.rounded_rectangle([x, y, x + cw, y + hh], radius=hh / 2, fill=(24, 26, 36, 195),
                                outline=(72, 74, 92, 155), width=1)
            d.text((x + cw / 2, y + hh / 2), c, font=f, fill=(152, 154, 172), anchor="mm")
            x += cw + gap
        # 发送按钮底座
        d.ellipse([856, 856, 944, 944], fill=(38, 30, 46, 235), outline=(120, 92, 116, 190), width=2)
        d.line([(900, 918), (900, 884)], fill=(180, 168, 190), width=5)
        d.polygon([(886, 897), (900, 880), (914, 897)], fill=(180, 168, 190))
        _INTRO_CHROME = o
    return _INTRO_CHROME


def frame_intro(t):
    img = intro_bg().copy()
    img.paste(intro_chrome(), (0, 0), intro_chrome())

    f = F(NOTO_MEDIUM, 44)
    n = 0
    if t >= 0.45:
        n = int((t - 0.45) / 0.055) + 1
        n = clamp(n, 0, len(_TXT_INTRO))
    typed = _TXT_INTRO[:n]
    if t < 0.45:
        txt0 = "问问 AI…"
        lay = T(txt0, NOTO_MEDIUM, 44, (122, 126, 144))
        over(img, lay, 140 + f.getlength(txt0) / 2, 900)
    else:
        lay = T(typed, NOTO_MEDIUM, 44, (246, 246, 252),
                glow=(255, 150, 205, 0.30, 10))
        cw = f.getlength(typed)
        over(img, lay, 140 + cw / 2, 900)
        if (t * 1.7) % 1.0 < 0.62:
            d = ImageDraw.Draw(img)
            x = 140 + cw + 4
            d.rounded_rectangle([x, 874, x + 5, 926], radius=2, fill=(255, 96, 170))

    # 发送按钮发光
    g = smoothstep(3.32, 3.5, t)
    if g > 0.01:
        gl = glow_img(0.8333, 0.4688, 0.10, 0.056, (255, 110, 180), 0.85 * g)
        img = ImageChops.screen(img, gl)
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(lay)
        dd.ellipse([856, 856, 944, 944], fill=(255, 96, 168, int(70 * g)), outline=(255, 150, 200, int(220 * g)), width=3)
        dd.line([(900, 918), (900, 884)], fill=(255, 255, 255, 255), width=5)
        dd.polygon([(886, 897), (900, 880), (914, 897)], fill=(255, 255, 255, 255))
        img.paste(lay, (0, 0), lay)
    return img


# ----------------------------------------------------------------------------- 2. a1
def nana_big(t_alpha=1.0, split=0.0, t=0.0, y=430, size=210):
    lay = T("nana", LATO, size, (255, 255, 255), glow=(255, 104, 182, 0.95, 34))
    return lay


def frame_a1(t):
    z = lerp(1.14, 1.22, smoothstep(3.75, 7.5, t))
    sx, sy = shake(t, 3.75, 0.45, 15)
    img = crop_resize(src("a1_nursery"), z, 0.5, 0.52, sx, sy)
    img = grade_a(img)
    img = bloom(img, 0.22)
    img = add_glow(img, 0.16, 0.40, 0.42, 0.36, (255, 196, 232), 0.42)
    img = particles(img, t, seed=3, n=80, rise=0.12)

    a = smoothstep(3.80, 4.06, t)
    if a > 0.01:
        lay = T("nana", LATO, 210, WHITE, glow=(255, 104, 182, 0.95, 34))
        s = lerp(0.90, 1.0, ease_out(smoothstep(3.80, 4.25, t)))
        over(img, lay, 540, 430, s=s, alpha=a)

    p = smoothstep(4.10, 4.42, t)
    if p > 0.01:
        lay = T("nana = 摇篮曲", SMILEY, 76, WHITE,
                strokes=((10, (44, 6, 34)),), glow=(255, 128, 206, 0.85, 24))
        over(img, lay, 540, 1540, s=lerp(0.55, 1.0, ease_out_back(p)), alpha=min(1.0, p * 1.8))
    return img


# ----------------------------------------------------------------------------- 3. a2
def frame_a2(t):
    k = smoothstep(7.5, 11.25, t)
    z = lerp(1.12, 1.22, k)
    pan = lerp(-26, 30, k)
    oy = 5 * math.sin(t * 4.0)
    img = crop_resize(src("a2_crib"), z, 0.5, 0.55, pan, oy)
    img = grade_a(img)
    img = bloom(img, 0.24)
    img = add_glow(img, 0.82, 0.22, 0.40, 0.30, (255, 224, 240), 0.45)
    img = particles(img, t, seed=11, n=95, rise=0.15)

    lay_txt = T("哄你睡", SMILEY, 150, WHITE,
                strokes=((9, (255, 128, 196)),), glow=(255, 130, 205, 0.75, 24))
    chars = [("哄", 7.70), ("你", 7.92), ("睡", 8.14)]
    # 居中排版：逐字 x
    f = F(SMILEY, 150)
    ws = [f.getlength(c) for c, _ in chars]
    total = sum(ws)
    x = 540 - total / 2
    for (c, t0), w in zip(chars, ws):
        p = smoothstep(t0, t0 + 0.26, t)
        if p > 0.01:
            cl = T(c, SMILEY, 150, WHITE, strokes=((9, (255, 128, 196)),),
                   glow=(255, 130, 205, 0.75, 24))
            over(img, cl, x + w / 2, 1430, s=lerp(0.4, 1.0, ease_out_back(p)), alpha=min(1.0, p * 1.9))
        x += w
    return img


# ----------------------------------------------------------------------------- 4. a1 -> a2
def frame_a_mix(t):
    k = smoothstep(11.25, 11.95, t)
    z = lerp(1.15, 1.30, smoothstep(11.25, 15.0, t))
    sx, sy = handheld(t, 0.35)
    i1 = crop_resize(src("a1_nursery"), z * 0.98, 0.5, 0.52, sx, sy)
    i2 = crop_resize(src("a2_crib"), z, 0.5, 0.54, sx * 0.6, sy * 0.6)
    img = Image.blend(i1, i2, k)
    img = grade_a(img)
    pk = lerp(0.03, 0.15, smoothstep(12.0, 14.6, t))
    img = Image.blend(img, Image.new("RGB", (W, H), (255, 150, 212)), pk)
    img = bloom(img, lerp(0.20, 0.46, smoothstep(12.4, 14.7, t)))
    img = particles(img, t, seed=7, n=100, rise=0.20, alpha=200)

    # nana 从 11.4 重现，RGB 分离
    a = smoothstep(11.40, 11.55, t)
    if a > 0.01:
        off = lerp(15, 3, smoothstep(11.4, 12.3, t))
        if t > 12.3:
            off = 3.0 + 7.0 * max(0.0, math.sin((t - 12.3) * 9.0)) * 0.6
        lay = T("nana", LATO, 210, WHITE)
        base = Image.new("RGBA", (lay.width + 2 * int(off) + 8, lay.height + 8), (0, 0, 0, 0))
        for dx, col in ((-off, (255, 30, 80)), (off, (0, 200, 255))):
            cl = Image.new("RGBA", lay.size, tuple(col) + (0,))
            cl.putalpha(lay.getchannel("A").point(lambda v: int(v * 0.9)))
            base.alpha_composite(cl, (int(off) + 4 + int(dx), 4))
        wht = Image.new("RGBA", lay.size, (255, 255, 255, 0))
        wht.putalpha(lay.getchannel("A"))
        base.alpha_composite(wht, (int(off) + 4, 4))
        glow = glow_img(0.5, 0.2239, 0.30, 0.10, (255, 90, 175), 0.8 * a)
        img = ImageChops.screen(img, glow)
        over(img, base, 540, 430, s=lerp(0.95, 1.0, ease_out(smoothstep(11.4, 11.8, t))), alpha=a)

    p = smoothstep(12.40, 12.75, t)
    if p > 0.01:
        lay = T("一个词，两种命", SMILEY, 86, WHITE,
                strokes=((10, (44, 6, 34)),), glow=(255, 128, 206, 0.8, 24))
        over(img, lay, 540, 1500, s=lerp(0.6, 1.0, ease_out_back(p)), alpha=min(1.0, p * 1.6))

    e = smoothstep(14.40, 14.88, t)
    if e > 0.005:
        img = Image.blend(img, WHITE_IMG, 0.88 * e)
    return img


# ----------------------------------------------------------------------------- 5. 黑场
def frame_break(t):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    if t < 15.18:
        return img
    a = smoothstep(15.18, 15.42, t)
    p1 = math.exp(-((t - 15.28) / 0.11) ** 2)
    p2 = math.exp(-((t - 16.02) / 0.11) ** 2)
    pulse = max(p1, p2, 0.12)
    lay = T("那中文呢？", NOTO_BLACK, 100, WHITE,
            glow=(255, 40, 62, 0.55 + 0.45 * pulse, 30))
    ox, oy = 0, 0
    if t > 16.40:
        ox, oy = shake(t, 16.40, 0.30, 9)
    s = 1.0 + 0.035 * pulse
    over(img, lay, 540 + ox, 960 + oy, s=s, alpha=a)
    return img


# ----------------------------------------------------------------------------- 6. b1/b2
def b1_frame(t, z=1.14, dark=1.0):
    sx, sy = handheld(t, 1.0)
    img = crop_resize(src("b1_livingroom"), z, 0.5, 0.50, sx, sy)
    img = grade_b(img, bright=dark)
    img = add_glow(img, 0.90, 0.52, 0.38, 0.30, (40, 120, 255), 0.55)
    return img


def b2_frame(t, z=1.14, dark=1.0, punch=0.0):
    sx, sy = handheld(t, 1.0 + punch)
    img = crop_resize(src("b2_grandma"), z, 0.47, 0.30, sx, sy)
    img = grade_b(img, bright=dark)
    img = add_glow(img, 0.55, 0.28, 0.55, 0.28, (40, 120, 255), 0.42)
    return img


def frame_b(t):
    if t < 17.225:
        img = b1_frame(t, 1.14 + 0.02 * smoothstep(16.875, 17.225, t))
    else:
        pz = smoothstep(19.18, 19.40, t)
        z = lerp(1.14, 1.35, pz)
        img = b2_frame(t, z, punch=0.8 * pz)
    p = smoothstep(17.00, 17.14, t)
    if p > 0.01:
        lay = T("nana = 奶奶", SMILEY, 86, WHITE,
                strokes=((13, (10, 8, 12)), (7, (226, 22, 48))),
                glow=(255, 46, 74, 0.55, 16))
        s = lerp(1.7, 1.0, ease_out_back(smoothstep(17.0, 17.16, t)))
        over(img, lay, 540, 1360, s=s, rot=-3.0, alpha=min(1.0, p * 2.0))
    return img


# ----------------------------------------------------------------------------- 7. 蒙太奇
CUTS = [
    (20.625, "b5_clock", 1.25, (0.50, 0.55), "几点了？", 70, (0.50, 0.795)),
    (21.094, "b7_phone", 1.15, (0.50, 0.53), "手机拿来。", 70, (0.50, 0.780)),
    (21.563, "b6_router", 1.20, (0.44, 0.45), "WiFi 断了。", 64, (0.50, 0.775)),
    (22.031, "b8_slipper", 1.12, (0.50, 0.55), "还不睡？", 72, (0.50, 0.200)),
    (22.500, "b3_point", 1.18, (0.46, 0.37), "关灯！", 80, (0.50, 0.800)),
    (22.969, "b5_clock", 1.35, (0.50, 0.54), "23:47", 80, (0.50, 0.795)),
    (23.438, "b2_grandma", 1.12, (0.47, 0.30), "睡！", 80, (0.50, 0.780)),
    (23.906, "b3_point", 1.30, (0.46, 0.37), "立刻。", 80, (0.50, 0.790)),
]


def frame_montage(t):
    idx = int(clamp((t - 20.625) / 0.46875, 0, 7.999))
    t0, name, z0, (fx, fy), txt, size, (tx, ty) = CUTS[idx]
    local = t - t0
    z = z0 * (1.0 + 0.012 * local / 0.46875)
    sx, sy = handheld(t, 1.15)
    img = crop_resize(src(name), z, fx, fy, sx + 6 * math.sin(t * 30) * local, sy)
    if name.startswith("b2") or name.startswith("b3"):
        img = grade_b(img, bright=0.97)
    else:
        img = grade_b(img, bright=1.0)
    img = add_glow(img, 0.82, 0.50, 0.36, 0.30, (40, 120, 255), 0.45)
    # 每刀 1 帧白闪 + 轻微 glitch
    if local < 0.070:
        img = glitch(img, 1000 + idx, 0.8)
        img = Image.blend(img, WHITE_IMG, 0.30 * (1.0 - local / 0.070))
    p = smoothstep(t0, t0 + 0.10, t)
    lay = T(txt, SMILEY, size, WHITE,
            strokes=((11, (10, 8, 12)), (6, (226, 22, 48))),
            glow=(255, 46, 74, 0.5, 14))
    over(img, lay, tx * W, ty * H, s=lerp(1.45, 1.0, ease_out_back(p)), rot=-3.0 + 1.2 * math.sin(t * 2.2),
         alpha=min(1.0, p * 2.2))
    return img


# ----------------------------------------------------------------------------- 8. 关灯 / 催睡
def frame_b_punch(t):
    if t < 25.2:
        img = b1_frame(t, 1.16, dark=0.52)
        img = add_glow(img, 0.90, 0.52, 0.34, 0.26, (30, 100, 255), 0.40)
        p = smoothstep(24.50, 24.80, t)
        lay = T("催你睡", SMILEY, 150, WHITE,
                strokes=((13, (10, 8, 12)), (7, (226, 22, 48))),
                glow=(255, 46, 74, 0.6, 22))
        over(img, lay, 540, 1400, s=lerp(1.4, 1.0, ease_out_back(p)), rot=-2.0, alpha=min(1.0, p * 1.8))
    elif t < 26.1:
        img = b2_frame(t, 1.16, dark=0.48)
        p = smoothstep(25.42, 25.62, t)
        lay = T("关灯。", SMILEY, 62, WHITE,
                strokes=((9, (10, 8, 12)), (5, (226, 22, 48))), glow=(255, 46, 74, 0.5, 12))
        over(img, lay, 540, 1290, s=lerp(0.6, 1.0, ease_out_back(p)), rot=-3.0, alpha=min(1.0, p * 2.0))
    elif t < 27.0:
        img = b3_frame(t, 1.20, dark=0.86)
        p = smoothstep(26.18, 26.40, t)
        lay = T("手机拿来。", SMILEY, 96, WHITE,
                strokes=((12, (10, 8, 12)), (6, (226, 22, 48))), glow=(255, 46, 74, 0.55, 18))
        over(img, lay, 540, 1350, s=lerp(1.4, 1.0, ease_out_back(p)), rot=-3.0, alpha=min(1.0, p * 1.9))
    else:
        k = smoothstep(27.0, 28.125, t)
        z = lerp(1.10, 1.30, k)
        sx, sy = handheld(t, 1.2)
        img = crop_resize(src("b8_slipper"), z, 0.5, 0.56, sx, sy + 40 * k)
        img = grade_b(img, bright=0.9)
        img = add_glow(img, 0.20, 0.55, 0.30, 0.30, (255, 150, 90), 0.30)
        p = smoothstep(27.10, 27.32, t)
        lay = T("睡！", SMILEY, 150, WHITE,
                strokes=((13, (10, 8, 12)), (7, (226, 22, 48))), glow=(255, 46, 74, 0.6, 22))
        over(img, lay, 540, 420, s=lerp(1.5, 1.0, ease_out_back(p)), rot=-4.0, alpha=min(1.0, p * 1.9))
    return img


def b3_frame(t, z=1.20, dark=1.0):
    sx, sy = handheld(t, 1.1)
    img = crop_resize(src("b3_point"), z, 0.46, 0.37, sx, sy)
    img = grade_b(img, bright=dark)
    img = add_glow(img, 0.84, 0.55, 0.34, 0.30, (40, 120, 255), 0.40)
    return img


# ----------------------------------------------------------------------------- 9. 分屏
def frame_split(t):
    left = crop_resize(src("a2_crib"), 1.22, 0.44, 0.52, 0, 0)
    left = grade_a(left)
    left = bloom(left, 0.22)
    right = b1_frame(t, 1.18, dark=0.92)
    img = Image.new("RGB", (W, H))
    img.paste(left.crop((0, 0, 540, H)), (0, 0))
    img.paste(right.crop((540, 0, 1080, H)), (540, 0))

    if t >= 29.6:
        dark = Image.new("RGB", (W, H), (0, 0, 0))
        m = Image.linear_gradient("L").resize((W, H))
        # 用简单整体压暗再补夜灯
        img = Image.blend(img, dark, 0.40 * smoothstep(29.6, 30.1, t))
        img = add_glow(img, 0.22, 0.80, 0.26, 0.20, (255, 176, 96), 0.55)
        img = add_glow(img, 0.78, 0.80, 0.26, 0.20, (255, 176, 96), 0.55)

    d = ImageDraw.Draw(img)
    d.rectangle([538, 0, 542, H], fill=(232, 236, 255))
    # 中线柔光
    gl = Image.new("RGB", (W, H), (0, 0, 0))
    gd = ImageDraw.Draw(gl)
    gd.rectangle([534, 0, 546, H], fill=(90, 92, 120))
    img = Image.blend(img, ImageChops.screen(img, gl.filter(ImageFilter.GaussianBlur(10))), 0.5)

    labs = [("nana", SERIF_BLACK, 60, (255, 170, 216), 250, 236),
            ("nana", LATO, 60, (128, 224, 255), 830, 236)]
    for txt, fk, size, col, cx, cy in labs:
        lay = T(txt, fk, size, col, strokes=((9, (10, 10, 16)),), glow=col + (0.6, 12))
        over(img, lay, cx, cy, alpha=smoothstep(28.4, 28.9, t))

    p = smoothstep(28.40, 28.80, t)
    lay = T("同一个 nana，两种命", SMILEY, 78, WHITE,
            strokes=((11, (8, 8, 12)),), glow=(255, 220, 240, 0.45, 18))
    if lay.width > 1040:
        lay = T("同一个 nana，两种命", SMILEY, 74, WHITE,
                strokes=((10, (8, 8, 12)),), glow=(255, 220, 240, 0.45, 18))
    over(img, lay, 540, 960, s=lerp(0.7, 1.0, ease_out_back(p)), alpha=min(1.0, p * 1.5))
    return img


# ----------------------------------------------------------------------------- 10. outro
def frame_outro(t):
    if t >= 33.90:
        img = Image.new("RGB", (W, H), (0, 0, 0))
        a = smoothstep(33.86, 33.96, t)
        lay = rich_text((("中文会说吧？就是——", SMILEY, 64, (255, 255, 255)),
                         ("奶奶", SMILEY, 64, (255, 152, 206))),
                        glow=(255, 110, 190, 0.6, 18))
        over(img, lay, 540, 900, s=1.0, alpha=a)
        sub = T("AI 生成画面 · 原创音乐", NOTO_MEDIUM, 38, (186, 188, 202))
        over(img, sub, 540, 1010, alpha=smoothstep(33.88, 33.99, t))
        if (t * 1.6) % 1.0 < 0.6:
            d = ImageDraw.Draw(img)
            x = 540 + lay.width / 2 + 14
            d.rounded_rectangle([x, 872, x + 5, 928], radius=2, fill=(255, 110, 180))
        return img

    z = lerp(1.12, 1.18, smoothstep(31.875, 33.8, t))
    sx, sy = handheld(t, 0.45)
    img = crop_resize(outro_img(), z, 0.50, 0.40, sx, sy)
    img = grade_warm(img)
    img = bloom(img, 0.18)
    img = add_glow(img, 0.13, 0.40, 0.30, 0.26, (255, 180, 110), 0.45)

    a = smoothstep(32.20, 32.65, t)
    lay = T("晚安，做个好梦。", NOTO_MEDIUM, 72, (255, 250, 244),
            strokes=((6, (52, 32, 22)),), glow=(255, 190, 140, 0.55, 18))
    over(img, lay, 540, 1560, alpha=a)

    f = smoothstep(33.70, 33.90, t)
    if f > 0:
        img = Image.blend(img, Image.new("RGB", (W, H), (0, 0, 0)), f)
    return img


# ----------------------------------------------------------------------------- 白闪
FLASH = [
    (3.56, 0.06, 0.08, 0.14, 1.00),
    (14.78, 0.08, 0.05, 0.09, 1.00),
    (16.86, 0.02, 0.05, 0.14, 1.00),
    (20.60, 0.02, 0.02, 0.09, 0.45),
    (24.36, 0.02, 0.03, 0.12, 0.85),
    (28.11, 0.02, 0.03, 0.12, 0.75),
    (31.74, 0.06, 0.04, 0.14, 1.00),
    (24.42, 0.01, 0.02, 0.10, 0.40),
    (25.35, 0.01, 0.02, 0.10, 0.42),
    (29.55, 0.02, 0.03, 0.12, 0.32),
]
for _c in (21.094, 21.563, 22.031, 22.500, 22.969, 23.438, 23.906):
    FLASH.append((_c - 0.0015, 0.008, 0.010, 0.030, 0.38))


def flash_env(t):
    a = 0.0
    for t0, rise, hold, fall, peak in FLASH:
        if t < t0:
            continue
        d = t - t0
        if d < rise:
            a = max(a, peak * d / rise)
        elif d < rise + hold:
            a = max(a, peak)
        elif d < rise + hold + fall:
            a = max(a, peak * (1.0 - (d - rise - hold) / fall))
    return a


# ----------------------------------------------------------------------------- 总装
def render_frame(i):
    global IMG_CUR
    t = i / FPS
    if t < 3.75:
        img = frame_intro(t)
        vig, gr = 0.40, 5
    elif t < 7.5:
        img = frame_a1(t)
        vig, gr = 0.34, 6
    elif t < 11.25:
        img = frame_a2(t)
        vig, gr = 0.34, 6
    elif t < 15.0:
        img = frame_a_mix(t)
        vig, gr = 0.36, 6
    elif t < 16.875:
        img = frame_break(t)
        vig, gr = 0.0, 5
    elif t < 20.625:
        img = frame_b(t)
        vig, gr = 0.46, 6
    elif t < 24.375:
        img = frame_montage(t)
        vig, gr = 0.48, 6
    elif t < 28.125:
        img = frame_b_punch(t)
        vig, gr = 0.50, 6
    elif t < 31.875:
        img = frame_split(t)
        vig, gr = 0.40, 6
    else:
        img = frame_outro(t)
        if t >= 33.90:
            vig, gr = 0.0, 2
        else:
            vig, gr = 0.34, 5

    if vig > 0:
        img = ImageChops.multiply(img, vignette(vig))
    img = add_grain(img, 1337 + i * 7, gr)

    fa = flash_env(t)
    if fa > 0.003:
        img = Image.blend(img, WHITE_IMG, clamp(fa, 0, 1))
    return img


def render_one(i):
    p = os.path.join(FRAMES, "f_%05d.jpg" % i)
    try:
        render_frame(i).save(p, quality=94, subsampling=1, optimize=False)
        return i
    except Exception:
        sys.stderr.write("frame %d failed\n%s\n" % (i, traceback.format_exc()))
        raise


# ----------------------------------------------------------------------------- 封面 / 联系表
def make_cover(path):
    CW, CH = 1080, 1440
    left = crop_aspect(src("a2_crib"), (540, CH), 1.30, 0.42, 0.60)
    left = grade_a(bloom(left, 0.24))
    right = crop_aspect(src("b2_grandma"), (540, CH), 1.18, 0.50, 0.34)
    right = grade_b(right)
    img = Image.new("RGB", (CW, CH))
    img.paste(left, (0, 0))
    img.paste(right, (540, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([537, 0, 541, CH], fill=(236, 240, 255))

    # 上下渐变压暗，保证文字可读（渐隐，无硬边）
    for y0, y1, amt, fade_top in ((0, 400, 0.66, False), (1040, CH, 0.70, True)):
        hh = y1 - y0
        grad = Image.linear_gradient("L").resize((CW, hh))
        if not fade_top:                      # 顶部条：越靠上越黑
            grad = grad.transpose(Image.FLIP_TOP_BOTTOM)
        ov = Image.new("RGBA", (CW, hh), (4, 4, 10, 255))
        ov.putalpha(grad.point(lambda v: int(v * amt)))
        base = img.crop((0, y0, CW, y1)).convert("RGBA")
        img.paste(Image.alpha_composite(base, ov).convert("RGB"), (0, y0))

    top = T("西语 nana  vs  中文 nana", NOTO_MEDIUM, 34, (232, 232, 240))
    over(img, top, 540, 96)

    main = T("同一个 nana", SMILEY, 108, WHITE, strokes=((12, (8, 8, 12)), (6, (226, 22, 48))),
             glow=(255, 90, 170, 0.55, 22))
    over(img, main, 540, 210)
    sub = T("两种命", SMILEY, 104, (255, 226, 240), strokes=((12, (8, 8, 12)), (6, (226, 22, 48))),
            glow=(255, 90, 170, 0.5, 22))
    over(img, sub, 540, 320)

    t1 = T("哄你睡", SMILEY, 68, (255, 176, 220), strokes=((8, (10, 8, 12)),), glow=(255, 120, 200, 0.6, 14))
    over(img, t1, 268, 1180)
    t2 = T("催你睡", SMILEY, 68, (150, 224, 255), strokes=((8, (10, 8, 12)),), glow=(80, 170, 255, 0.6, 14))
    over(img, t2, 812, 1180)

    btm = T("同一个发音 · AI 生成画面 · 原创音乐", NOTO_MEDIUM, 32, (206, 208, 220))
    over(img, btm, 540, 1340)
    img.save(path, quality=93, subsampling=1)


def make_contact(path, times):
    cols, rows = 4, 3
    cw, chh = W // cols, H // 4  # 270 x 480 -> 1080 x 1440
    sheet = Image.new("RGB", (cw * cols, chh * rows), (10, 10, 14))
    d = ImageDraw.Draw(sheet)
    f = F(NOTO_MEDIUM, 22)
    for k, t in enumerate(times[:cols * rows]):
        i = int(round(t * FPS))
        i = clamp(i, 0, NF - 1)
        p = os.path.join(FRAMES, "f_%05d.jpg" % i)
        im = Image.open(p).convert("RGB").resize((cw, chh), Image.LANCZOS)
        c, r = k % cols, k // cols
        sheet.paste(im, (c * cw, r * chh))
        d.rectangle([c * cw, r * chh + chh - 34, c * cw + cw, r * chh + chh], fill=(0, 0, 0))
        d.text((c * cw + 8, r * chh + chh - 30), "%05.2fs" % t, font=f, fill=(228, 228, 236))
    sheet.save(path, quality=92, subsampling=1)


# ----------------------------------------------------------------------------- main
SAMPLE_TIMES = [1, 5, 9, 13, 16, 18, 21, 23, 26, 29, 32, 34]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--samples", action="store_true")
    ap.add_argument("--cover", action="store_true")
    ap.add_argument("--contact", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--range", type=str, default=None, help="start:end 帧号")
    ap.add_argument("--times", type=str, default=None)
    args = ap.parse_args()

    os.makedirs(FRAMES, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    did = False
    if args.samples:
        os.makedirs(SAMPLES, exist_ok=True)
        times = [float(x) for x in args.times.split(",")] if args.times else SAMPLE_TIMES
        for t in times:
            i = int(round(t * FPS))
            p = os.path.join(SAMPLES, "s_%05.2f.jpg" % t)
            render_frame(i).save(p, quality=94, subsampling=1)
            print("sample", p)
        did = True

    if args.contact:
        times = [float(x) for x in args.times.split(",")] if args.times else SAMPLE_TIMES
        p = os.path.join(OUT, "contact_sheet.jpg")
        make_contact(p, times)
        print("contact", p)
        did = True

    if args.cover:
        p = os.path.join(OUT, "cover.jpg")
        make_cover(p)
        print("cover", p)
        did = True

    if args.all or args.range:
        if args.range:
            a, b = args.range.split(":")
            idxs = list(range(int(a), int(b)))
        else:
            idxs = list(range(NF))
            for fn in os.listdir(FRAMES):
                if fn.startswith("f_") and fn.endswith(".jpg"):
                    os.remove(os.path.join(FRAMES, fn))
        n = 0
        with Pool(processes=args.workers) as pool:
            for _ in pool.imap_unordered(render_one, idxs, chunksize=8):
                n += 1
                if n % 100 == 0 or n == len(idxs):
                    print("frames %d/%d" % (n, len(idxs)), flush=True)
        did = True

    if not did:
        ap.print_help()


if __name__ == "__main__":
    main()
