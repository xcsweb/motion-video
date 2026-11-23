#!/usr/bin/env python3
"""真途 · 40 秒竖屏宣传片渲染器（Pillow 逐帧合成）。

产物：
    out/frames/f_0000.jpg … f_1199.jpg
    out/preview/t_XX.jpg（--times 预览）

用法：
    python3 edit/render.py --times 0.8,3.4,6.2,9.6
    python3 edit/render.py
"""
import argparse
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
FPS = 30
DUR = 40.0
N_FRAMES = int(round(FPS * DUR))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREEN_DIR = os.path.join(ROOT, 'assets', 'screens')
IMG_DIR = os.path.join(ROOT, 'assets', 'img')
OUT_DIR = os.path.join(ROOT, 'out', 'frames')
PREVIEW_DIR = os.path.join(ROOT, 'out', 'preview')

# ---------------- palette ----------------
INK = (22, 35, 30)
INK_SOFT = (62, 76, 69)
PAPER = (247, 243, 234)
PAPER_WARM = (242, 235, 222)
GREEN = (14, 124, 102)
GREEN_DEEP = (9, 83, 68)
DEEP = (9, 25, 21)
DEEP2 = (13, 36, 30)
AMBER = (219, 156, 78)
RED = (190, 66, 45)
BLUE = (42, 95, 112)
WHITE = (255, 255, 255)
MUTED = (128, 138, 130)

# ---------------- fonts ----------------
F_BLACK = '/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc'
F_BOLD = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'
F_MED = '/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc'
F_REG = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf'
F_SERIF = '/usr/share/fonts/opentype/noto/NotoSerifCJK-Black.ttc'
F_SERIF_B = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSerifCJKsc-Bold.otf'
F_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf'

_font_cache = {}


def font(path, size):
    key = (path, size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size)
    return _font_cache[key]


# ---------------- math helpers ----------------
def clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def ease_out(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp01(x)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def lerp(a, b, p):
    return a + (b - a) * p


def smoothstep(a, b, x):
    if a == b:
        return 1.0 if x >= b else 0.0
    p = clamp01((x - a) / (b - a))
    return p * p * (3 - 2 * p)


def sstep(t, a, b):
    return smoothstep(a, b, t)


# ---------------- assets ----------------
def load_screen(name):
    return Image.open(os.path.join(SCREEN_DIR, name + '.png')).convert('RGB')


SCREENS = {}


def screens():
    if SCREENS:
        return SCREENS
    for fn in sorted(os.listdir(SCREEN_DIR)):
        if fn.endswith('.png'):
            SCREENS[fn[:-4]] = load_screen(fn[:-4])
    return SCREENS


def img(name, size=None):
    im = Image.open(os.path.join(IMG_DIR, name)).convert('RGB')
    if size:
        im = ImageOps_fit(im, size)
    return im


def ImageOps_fit(im, size):
    """cover-fit to size."""
    tw, th = size
    r = max(tw / im.width, th / im.height)
    nw, nh = int(im.width * r + 0.5), int(im.height * r + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    x = (nw - tw) // 2
    y = (nh - th) // 2
    return im.crop((x, y, x + tw, y + th))


# ---------------- static backgrounds ----------------
def _noise_layer(w, h, seed, alpha=14, blur=0.6):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, 1, (h // 2, w // 2)).astype(np.float32)
    n = np.clip(128 + n * 26, 0, 255).astype(np.uint8)
    im = Image.fromarray(n, 'L').resize((w, h), Image.BILINEAR)
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    return im


def make_paper_bg():
    w, h = W + 160, H + 220
    base = Image.new('RGB', (w, h), PAPER)
    d = ImageDraw.Draw(base, 'RGBA')
    # 细网格
    for x in range(0, w, 120):
        d.line([(x, 0), (x, h)], fill=(120, 110, 90, 9), width=1)
    for y in range(0, h, 120):
        d.line([(0, y), (w, y)], fill=(120, 110, 90, 9), width=1)
    # 等高线
    rng = random.Random(31)
    for k in range(9):
        pts = []
        y0 = 160 + k * 210 + rng.randint(-40, 40)
        amp = rng.randint(22, 60)
        for x in range(-40, w + 40, 18):
            y = y0 + math.sin(x / rng.randint(160, 300) + k) * amp
            pts.append((x, y))
        d.line(pts, fill=(14, 124, 102, 10), width=2)
    # 纸纹
    noise = _noise_layer(w, h, 7, blur=0.4)
    base = Image.composite(Image.new('RGB', (w, h), (236, 229, 214)), base, noise.point(lambda v: int(v * 0.10)))
    # 暗角
    vig = Image.new('L', (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.2, -h * 0.25, w * 1.2, h * 1.15], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(160)).point(lambda v: int(255 - v * 0.10))
    base = Image.composite(Image.new('RGB', (w, h), (225, 218, 203)), base, vig)
    return base


def make_dark_bg():
    w, h = W + 160, H + 220
    base = Image.new('RGB', (w, h), DEEP)
    px = base.load()
    # 顶部暖光
    glow = Image.new('L', (w, h), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([w * 0.35, -h * 0.22, w * 1.05, h * 0.34], fill=110)
    gd.ellipse([-w * 0.2, h * 0.55, w * 0.4, h * 1.05], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    warm = Image.new('RGB', (w, h), (38, 62, 48))
    base = Image.composite(warm, base, glow)
    # 等高线
    d = ImageDraw.Draw(base, 'RGBA')
    rng = random.Random(9)
    for k in range(14):
        pts = []
        y0 = 90 + k * 150 + rng.randint(-50, 50)
        amp = rng.randint(18, 50)
        for x in range(-40, w + 40, 16):
            y = y0 + math.sin(x / rng.randint(150, 280) + k * 0.7) * amp
            pts.append((x, y))
        d.line(pts, fill=(120, 190, 165, 16), width=2)
    # 颗粒
    noise = _noise_layer(w, h, 17, blur=0.3)
    base = Image.composite(Image.new('RGB', (w, h), (16, 38, 31)), base, noise.point(lambda v: int(v * 0.18)))
    # 暗角
    vig = Image.new('L', (w, h), 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.1, -h * 0.1, w * 1.1, h * 1.1], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(220)).point(lambda v: int(255 - v * 0.55))
    base = Image.composite(Image.new('RGB', (w, h), (4, 12, 10)), base, vig)
    return base


PAPER_BG = None
DARK_BG = None
GRAIN = None
GRAIN_NP = None
VIGNETTE = None


def init_static():
    global PAPER_BG, DARK_BG, GRAIN, VIGNETTE
    if PAPER_BG is not None:
        return
    PAPER_BG = make_paper_bg()
    DARK_BG = make_dark_bg()
    rng = np.random.default_rng(3)
    g = rng.normal(0, 1, (H // 2, W // 2)).astype(np.float32)
    g = np.clip(128 + g * 34, 0, 255).astype(np.uint8)
    GRAIN = Image.fromarray(g, 'L').resize((W, H), Image.BILINEAR)
    v = Image.new('L', (W, H), 0)
    vd = ImageDraw.Draw(v)
    vd.ellipse([-W * 0.12, -H * 0.08, W * 1.12, H * 1.08], fill=255)
    v = v.filter(ImageFilter.GaussianBlur(180))
    VIGNETTE = v.point(lambda x: int((255 - x) * 0.30))
    global GRAIN_NP
    GRAIN_NP = rng.normal(0, 4.2, (H, W, 1)).astype(np.int16)


def bg(kind, t, drift=1.0):
    src = PAPER_BG if kind == 'paper' else DARK_BG
    ox = int(math.sin(t * 0.11) * 18 * drift) + 80
    oy = int((t * 2.2 * drift) % 200) + 110
    ox = max(0, min(src.width - W, ox))
    oy = max(0, min(src.height - H, oy))
    return src.crop((ox, oy, ox + W, oy + H)).copy()


def finish(canvas, grain=True):
    if grain:
        arr = np.asarray(canvas, dtype=np.int16)
        arr = np.clip(arr + GRAIN_NP, 0, 255).astype(np.uint8)
        canvas = Image.fromarray(arr, 'RGB')
    canvas = Image.composite(Image.new('RGB', canvas.size, (0, 0, 0)), canvas, VIGNETTE)
    return canvas


# ---------------- text ----------------
def tracked(d, xy, text, f, fill, spacing=0, anchor='la'):
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill, anchor='la')
        x += d.textlength(ch, font=f) + spacing
    return x


def text_w(d, text, f, spacing=0):
    return d.textlength(text, font=f) + spacing * max(0, len(text) - 1)


def draw_rich_line(canvas, x, y, segments, f, spacing=0, underline_color=None, underline_p=0.0):
    """segments: [(text, color), ...]；返回整行宽度。"""
    d = ImageDraw.Draw(canvas)
    cx = x
    accent_boxes = []
    for text, color in segments:
        for ch in text:
            d.text((cx, y), ch, font=f, fill=color, anchor='la')
            cx += d.textlength(ch, font=f) + spacing
        if color != segments[0][1] or len(segments) > 1:
            pass
    total = cx - x - spacing
    # underline 仅给非首色段
    if underline_p > 0:
        cx2 = x
        for i, (text, color) in enumerate(segments):
            wseg = text_w(d, text, f, spacing)
            if i > 0:
                accent_boxes.append((cx2, cx2 + wseg))
            cx2 += wseg + spacing
        for (a, b) in accent_boxes:
            p = clamp01(underline_p)
            x2 = a + (b - a) * p
            d.line([(a, y + f.size * 1.08), (x2, y + f.size * 1.08 + math.sin((x2 - a) / 40) * 2)],
                   fill=underline_color or GREEN, width=7)
    return total


def has_cjk(s):
    return any('\u4e00' <= ch <= '\u9fff' for ch in s)


def kicker(canvas, t, start, label, color=GREEN, dark=False):
    p = ease_out((t - start) / 0.5)
    if p <= 0:
        return
    layer = Image.new('RGBA', (W, 80), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    f = font(F_BOLD, 24) if has_cjk(label) else font(F_MONO, 22)
    col = (color[0], color[1], color[2], int(220 * p))
    x = 78
    d.line([(x, 30), (x + 46 * p, 30)], fill=col, width=3)
    tracked(d, (x + 62, 16), label, f, col, spacing=4 if has_cjk(label) else 5)
    canvas.paste(layer, (0, 62), layer)


def headline(canvas, t, start, lines, y=132, size=62, underline_color=None, dark=False):
    """lines: [[(text,color),...], ...]"""
    base_col = PAPER if dark else INK
    lh = int(size * 1.34)
    layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for i, segs in enumerate(lines):
        p = ease_out((t - start - i * 0.13) / 0.55)
        if p <= 0:
            continue
        f = font(F_BLACK, size)
        x = 78
        dy = int((1 - p) * 26)
        positions = []
        for j, (text, col) in enumerate(segs):
            use = col if col else base_col
            d.text((x, y + i * lh + dy), text, font=f, fill=use + (int(255 * p),), anchor='la')
            positions.append((x, x + d.textlength(text, font=f)))
            x += d.textlength(text, font=f)
        # accent 下划线（第二段起）
        if underline_color and len(segs) > 1 and i == len(lines) - 1:
            up = ease_out((t - start - 0.32) / 0.5)
            if up > 0:
                a, b = positions[1]
                yline = y + i * lh + dy + int(size * 1.06)
                d.line([(a, yline), (a + (b - a) * up, yline + math.sin(up * 3) * 2)],
                       fill=underline_color + (int(215 * up),), width=8)
    canvas.paste(layer, (0, 0), layer)


def rich(text_color_pairs):
    return text_color_pairs


# ---------------- phone ----------------
def screen_slice(name, w, h, zoom=1.0, focus=(0.5, 0.45)):
    im = screens()[name]
    if zoom > 1.001:
        sw, sh = im.size
        cw, ch = sw / zoom, sh / zoom
        cx = min(max(focus[0] * sw, cw / 2), sw - cw / 2)
        cy = min(max(focus[1] * sh, ch / 2), sh - ch / 2)
        im = im.crop((int(cx - cw / 2), int(cy - ch / 2), int(cx + cw / 2), int(cy + ch / 2)))
    return im.resize((int(w), int(h)), Image.LANCZOS)


def swipe_pair(a, b, p, w, h):
    ia, ib = screens()[a], screens()[b]
    src = Image.new('RGB', (ia.width, ia.height * 2))
    src.paste(ia, (0, 0))
    src.paste(ib, (0, ia.height))
    off = int(p * ia.height)
    crop = src.crop((0, off, ia.width, off + ia.height))
    return crop.resize((int(w), int(h)), Image.LANCZOS)


def rounded_mask(size, radius):
    m = Image.new('L', size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def paste_phone(canvas, screen_img, x, y, w, h, bezel=10, radius=52, shadow=True, alpha=255):
    """在 canvas 上贴一台手机，返回屏幕矩形。"""
    w, h = int(w), int(h)
    frame = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    mask = rounded_mask((w, h), radius)
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=(16, 24, 21, alpha))
    inner = (w - bezel * 2, h - bezel * 2)
    scr = screen_img.resize(inner, Image.LANCZOS)
    frame.paste(scr, (bezel, bezel), rounded_mask(inner, max(6, radius - bezel)))
    frame.putalpha(mask)
    if shadow:
        sh = Image.new('RGBA', (w + 160, h + 180), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([80, 90, w + 80, h + 90], radius=radius + 8, fill=(0, 0, 0, 110))
        sh = sh.filter(ImageFilter.GaussianBlur(38))
        canvas.paste(sh, (int(x) - 80, int(y) - 60), sh)
    canvas.paste(frame, (int(x), int(y)), frame)
    return (int(x + bezel), int(y + bezel), int(x + w - bezel), int(y + h - bezel))


def callout(canvas, xy, target, text, sub='', color=GREEN, dark=False, align='right', p=1.0, width=None):
    """标注胶囊 + 引线。"""
    if p <= 0:
        return
    f = font(F_BOLD, 30)
    fs = font(F_MED, 22)
    d0 = ImageDraw.Draw(canvas)
    tw = d0.textlength(text, font=f)
    sw = d0.textlength(sub, font=fs) if sub else 0
    bw = int(max(tw, sw) + 44)
    bh = 92 if sub else 66
    x, y = xy
    if align == 'right':
        x = x - bw
    # leader
    lx = x + bw if align == 'right' else x
    ly = y + bh / 2
    dd = ImageDraw.Draw(canvas, 'RGBA')
    dd.line([(lx, ly), (target[0], target[1])], fill=color + (int(200 * p),), width=3)
    dd.ellipse([target[0] - 7, target[1] - 7, target[0] + 7, target[1] + 7], fill=color + (int(230 * p),))
    # chip
    layer = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    bgc = (255, 253, 247, 246) if not dark else (16, 40, 33, 238)
    ld.rounded_rectangle([0, 0, bw - 1, bh - 1], radius=22, fill=bgc, outline=color + (170,), width=2)
    ld.text((22, 14 if sub else 18), text, font=f, fill=(color if not dark else (235, 248, 242)) + (255,))
    if sub:
        ld.text((22, 50), sub, font=fs, fill=(INK_SOFT if not dark else (175, 199, 190)) + (235,))
    layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
    canvas.paste(layer, (int(x), int(y)), layer)


# ---------------- scenes ----------------
CUR = None


def scene_hook(t, lt, dur):
    global CUR
    CUR = bg('dark', t, 0.6)
    kicker(CUR, lt, 0.05, 'ZHENTU  /  00', color=AMBER, dark=True)
    headline(CUR, lt, 0.18, [
        [('你收藏的攻略，', PAPER)],
        [('可能', PAPER), ('过期', (232, 96, 70)), ('了。', PAPER)],
    ], y=120, size=64, dark=True)

    cards = [
        ('shaxi_cover.jpg', '2019.06', '沙溪 · 兴教寺门票', '20 元 / 人', -3, 0.15, 540, 790),
        ('shaxi_dusk.jpg', '2022.10', '沙溪 · 白族书局', '营业到 22:00', 2, 0.28, 560, 1105),
        ('nuodeng.jpg', '2024.04', '诺邓 · 进村班车', '15:40 末班', -2, 0.41, 525, 1420),
    ]
    for i, (imgn, date, title, val, ang, at, cx, cy) in enumerate(cards):
        p = ease_out((lt - at) / 0.5)
        if p <= 0:
            continue
        cw, ch = 560, 300
        card = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, cw - 1, ch - 1], radius=24, fill=(250, 246, 238, 255))
        photo = ImageOps_fit(Image.open(os.path.join(IMG_DIR, imgn)).convert('RGB'), (cw, 176)).convert('RGBA')
        card.paste(photo, (0, 0))
        cd.text((28, 190), date, font=font(F_MONO, 21), fill=(122, 130, 122, 255))
        cd.text((28, 224), title, font=font(F_BOLD, 29), fill=(26, 40, 34, 255))
        cd.text((28, 262), val, font=font(F_MED, 25), fill=(14, 124, 102, 255))
        card.putalpha(rounded_mask((cw, ch), 24))
        rot = card.rotate(ang, expand=True, resample=Image.BICUBIC)
        sh = Image.new('RGBA', (rot.width + 80, rot.height + 80), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([40, 52, rot.width + 40, rot.height + 52], radius=28, fill=(0, 0, 0, 120))
        sh = sh.filter(ImageFilter.GaussianBlur(26))
        CUR.paste(sh, (int(cx - rot.width / 2) - 40, int(cy - rot.height / 2) - 34), sh)
        lay = Image.new('RGBA', rot.size, (0, 0, 0, 0))
        lay.paste(rot, (0, 0))
        lay.putalpha(lay.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(lay, (int(cx - rot.width / 2), int(cy - rot.height / 2 + (1 - p) * 40)), lay)

    fp = ease_out((lt - 1.55) / 0.5)
    if fp > 0:
        layer = Image.new('RGBA', (W, 60), (0, 0, 0, 0))
        dd = ImageDraw.Draw(layer)
        dd.text((W / 2, 0), '三 年，足 够 让 一 条 攻 略 失 效', font=font(F_SERIF_B, 26), fill=(196, 188, 170, int(190 * fp)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * fp)))
        CUR.paste(layer, (0, 1710), layer)

    # 过期印章
    sp = ease_out((lt - 1.85) / 0.32)
    if sp > 0:
        st = Image.new('RGBA', (560, 240), (0, 0, 0, 0))
        sd = ImageDraw.Draw(st)
        sd.rounded_rectangle([4, 4, 556, 236], radius=18, outline=(205, 66, 45, 255), width=12)
        sd.rounded_rectangle([24, 24, 536, 216], radius=10, outline=(205, 66, 45, 120), width=3)
        sd.text((280, 120), '已 过 期', font=font(F_BLACK, 76), fill=(205, 66, 45, 255), anchor='mm')
        st = st.rotate(-13, expand=True, resample=Image.BICUBIC)
        sc = lerp(1.9, 1.0, sp)
        st = st.resize((int(st.width * sc), int(st.height * sc)), Image.LANCZOS)
        st.putalpha(st.getchannel('A').point(lambda v: int(v * min(1, sp * 1.6))))
        CUR.paste(st, (int(W / 2 - st.width / 2), int(1100 - st.height / 2)), st)


def scene_broken(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, 'THINGS CHANGE  /  01')
    headline(CUR, lt, 0.1, [
        [('门票涨了，店关了，', INK)],
        [('车也', INK), ('停了', RED), ('。', INK)],
    ], y=116, size=62)

    rows = [
        ('门票', '20 元', '50 元', '涨', 0.02, RED),
        ('书店', '营业到 22:00', '已停业', '关', 0.38, RED),
        ('班车', '15:40', '已停运', '停', 0.74, RED),
    ]
    for i, (lab, old, new, stamp, at, col) in enumerate(rows):
        p = ease_out((lt - 0.25 - at) / 0.42)
        if p <= 0:
            continue
        y = 620 + i * 270
        row = Image.new('RGBA', (920, 236), (0, 0, 0, 0))
        rd = ImageDraw.Draw(row)
        rd.rounded_rectangle([0, 0, 919, 235], radius=24, fill=(252, 248, 240, 255), outline=(210, 201, 184, 255), width=2)
        rd.rounded_rectangle([26, 26, 186, 210], radius=16, fill=(235, 240, 232, 255))
        rd.text((106, 118), lab, font=font(F_BOLD, 38), fill=(20, 90, 74, 255), anchor='mm')
        rd.text((228, 66), old, font=font(F_MED, 33), fill=(120, 118, 108, 255))
        # 手写删除线
        rd.line([(228, 104), (228 + rd.textlength(old, font=font(F_MED, 33)), 104)], fill=(150, 60, 45, 200), width=4)
        rd.text((228, 140), new, font=font(F_BLACK, 46), fill=(28, 42, 36, 255))
        # 印章
        rd.rounded_rectangle([760, 54, 888, 182], radius=14, outline=col + (255,), width=6)
        rd.text((824, 118), stamp, font=font(F_BLACK, 62), fill=col + (255,), anchor='mm')
        row.putalpha(rounded_mask((920, 236), 24))
        lay = Image.new('RGBA', row.size, (0, 0, 0, 0))
        lay.paste(row, (0, 0))
        lay.putalpha(lay.getchannel('A').point(lambda v: int(v * p)))
        rot = lay.rotate(lerp(2.5, 0, p), expand=True, resample=Image.BICUBIC)
        CUR.paste(rot, (int(80 + (1 - p) * 120), int(y + (1 - p) * 30 - (rot.height - 236) / 2)), rot)

    # 底部注释
    p = ease_out((lt - 1.85) / 0.5)
    if p > 0:
        layer = Image.new('RGBA', (W, 90), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((W / 2, 0), '信息会过期，但没人告诉你。', font=font(F_SERIF_B, 36), fill=(96, 102, 94, int(220 * p)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, 1590), layer)


def scene_brand(t, lt, dur):
    global CUR
    CUR = bg('dark', t, 0.3)
    # 背景暖圆
    p = ease_out((lt - 0.1) / 1.0)
    if p > 0:
        disc = Image.new('RGBA', (900, 900), (0, 0, 0, 0))
        dd = ImageDraw.Draw(disc)
        dd.ellipse([40, 40, 860, 860], fill=(201, 144, 82, int(22 * p)))
        disc = disc.filter(ImageFilter.GaussianBlur(30))
        CUR.paste(disc, (90, 260), disc)

    # 印章
    sp = ease_out((lt - 0.02) / 0.38)
    if sp > 0:
        seal = Image.new('RGBA', (290, 290), (0, 0, 0, 0))
        sd = ImageDraw.Draw(seal)
        sd.rounded_rectangle([8, 8, 282, 282], radius=24, fill=(247, 243, 234, 255))
        sd.rounded_rectangle([24, 24, 266, 266], radius=16, outline=(14, 124, 102, 255), width=8)
        sd.text((145, 145), '真', font=font(F_SERIF, 178), fill=(14, 124, 102, 255), anchor='mm')
        seal = seal.rotate(-5, expand=True, resample=Image.BICUBIC)
        sc = lerp(1.7, 1.0, sp)
        seal = seal.resize((int(seal.width * sc), int(seal.height * sc)), Image.LANCZOS)
        seal.putalpha(seal.getchannel('A').point(lambda v: int(v * min(1, sp * 1.5))))
        CUR.paste(seal, (int(W / 2 - seal.width / 2), int(620 - seal.height / 2)), seal)

    # 字标
    p = ease_out((lt - 0.52) / 0.55)
    if p > 0:
        layer = Image.new('RGBA', (W, 340), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((W / 2, 10), '真 途', font=font(F_BLACK, 140), fill=PAPER + (int(255 * p),), anchor='ma')
        tracked(d, (W / 2 - 62, 268), 'ZHENTU', font(F_MONO, 24), PAPER + (int(180 * p),), spacing=10)
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, int(810 + (1 - p) * 18)), layer)

    # 标语
    p = ease_out((lt - 0.9) / 0.6)
    if p > 0:
        layer = Image.new('RGBA', (W, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((W / 2, 10), '每一条攻略，都有人替你走过', font=font(F_SERIF_B, 42), fill=(238, 233, 220, int(245 * p)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, int(1150 + (1 - p) * 14)), layer)

    # 背景细圆
    p = ease_out((lt - 0.35) / 1.0)
    if p > 0:
        d = ImageDraw.Draw(CUR, 'RGBA')
        r = 345
        d.ellipse([W / 2 - r, 620 - r, W / 2 + r, 620 + r], outline=(120, 190, 165, int(46 * p)), width=2)
    # 副标
    p = ease_out((lt - 0.98) / 0.6)
    if p > 0:
        layer = Image.new('RGBA', (W, 60), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        d.text((W / 2, 0), '旅 行 攻 略  ·  网 友 核 实', font=font(F_MED, 24), fill=(14, 158, 130, int(210 * p)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, 1245), layer)

    # 底部细线
    p = ease_out((lt - 1.5) / 0.7)
    if p > 0:
        d = ImageDraw.Draw(CUR, 'RGBA')
        d.line([(W / 2 - 90 * p, 1330), (W / 2 + 90 * p, 1330)], fill=(14, 124, 102, 160), width=2)
    # 片头字幕条
    p = ease_out((lt - 1.7) / 0.6)
    if p > 0:
        d = ImageDraw.Draw(CUR, 'RGBA')
        d.line([(78, 1700), (1002, 1700)], fill=(120, 160, 145, int(34 * p)), width=2)
        d.text((78, 1730), 'EP.01  /  攻略会过期', font=font(F_MED, 21), fill=(150, 170, 160, int(190 * p)))
        d.text((1002, 1730), '真途 · 旅行攻略核实平台', font=font(F_MED, 21), fill=(150, 170, 160, int(190 * p)), anchor='ra')


def _scene_feed_impl(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.6)
    kicker(CUR, lt, 0.02, '01  /  发现')
    headline(CUR, lt, 0.08, [
        [('每一条，', INK)],
        [('都有人', INK), ('替你走过', GREEN), ('。', INK)],
    ], y=120, size=62)

    push = 1.0 + 0.05 * ease_out(lt / dur)
    swipe = ease_in_out((lt - 0.95) / 0.45)
    if swipe <= 0:
        scr = screen_slice('01_home', 660, 1430, push, (0.5, 0.4))
    else:
        scr = swipe_pair('01_home', '03_home_card3', swipe, 660, 1430)
    rect = paste_phone(CUR, scr, 210, 366, 660, 1430, bezel=10, radius=54)

    if lt > 1.45:
        callout(CUR, (1042, 96), (rect[2] - 48, 840), '沙溪 2 日', '路线可直接播放', color=AMBER, align='right', p=ease_out((lt - 1.45) / 0.4))



# ---------------- graphic helpers ----------------
def ring_gauge(canvas, cx, cy, r, pct, color=GREEN, width=16, p=1.0, track=(205, 198, 182, 110)):
    if p <= 0:
        return
    d = ImageDraw.Draw(canvas, 'RGBA')
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=track, width=width)
    if pct > 0:
        end = -90 + 360 * pct * p
        d.arc([cx - r, cy - r, cx + r, cy + r], -90, end, fill=color + (255,), width=width)
        a = math.radians(end)
        d.ellipse([cx + r * math.cos(a) - width / 2, cy + r * math.sin(a) - width / 2,
                   cx + r * math.cos(a) + width / 2, cy + r * math.sin(a) + width / 2], fill=color + (255,))


def check_mark(canvas, cx, cy, s, p, color=WHITE, width=14):
    if p <= 0:
        return
    d = ImageDraw.Draw(canvas, 'RGBA')
    pts = [(cx - s, cy + s * 0.02), (cx - s * 0.25, cy + s * 0.62), (cx + s, cy - s * 0.55)]
    # 两段按进度绘制
    if p < 0.5:
        q = p / 0.5
        x = lerp(pts[0][0], pts[1][0], q)
        y = lerp(pts[0][1], pts[1][1], q)
        d.line([pts[0], (x, y)], fill=color + (255,), width=width)
    else:
        d.line([pts[0], pts[1]], fill=color + (255,), width=width)
        q = (p - 0.5) / 0.5
        x = lerp(pts[1][0], pts[2][0], q)
        y = lerp(pts[1][1], pts[2][1], q)
        d.line([pts[1], (x, y)], fill=color + (255,), width=width)


def stamp(canvas, text, cx, cy, color, angle=-8, scale=1.0, alpha=255, size=64, padx=36, pady=20, bw=8):
    if alpha <= 0:
        return
    f = font(F_BLACK, size)
    d0 = ImageDraw.Draw(canvas)
    tw = d0.textlength(text, font=f)
    w, h = int(tw + padx * 2), int(size + pady * 2)
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([bw // 2, bw // 2, w - bw // 2, h - bw // 2], radius=12, outline=color + (255,), width=bw)
    d.rounded_rectangle([bw * 2, bw * 2, w - bw * 2, h - bw * 2], radius=6, outline=color + (110,), width=2)
    d.text((w / 2, h / 2), text, font=f, fill=color + (255,), anchor='mm')
    layer = layer.rotate(angle, expand=True, resample=Image.BICUBIC)
    if scale != 1.0:
        layer = layer.resize((int(layer.width * scale), int(layer.height * scale)), Image.LANCZOS)
    layer.putalpha(layer.getchannel('A').point(lambda v: int(v * alpha / 255)))
    canvas.paste(layer, (int(cx - layer.width / 2), int(cy - layer.height / 2)), layer)


def tap(canvas, x, y, p, dark=True):
    if p <= 0:
        return
    d = ImageDraw.Draw(canvas, 'RGBA')
    for k in range(2):
        q = ((p * 1.5 + k * 0.5) % 1.0)
        r = 18 + 52 * q
        a = int(150 * (1 - q))
        d.ellipse([x - r, y - r, x + r, y + r], outline=(255, 255, 255, a), width=3)
    d.ellipse([x - 17, y - 17, x + 17, y + 17], fill=(255, 255, 255, 240))
    d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(24, 34, 30, 255))


def pill(canvas, cx, cy, text, fg=PAPER, bg=GREEN, size=30, alpha=255, padx=34, pady=18):
    if alpha <= 0:
        return
    f = font(F_BOLD, size)
    d0 = ImageDraw.Draw(canvas)
    tw = d0.textlength(text, font=f)
    w, h = int(tw + padx * 2), int(size + pady * 2)
    layer = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=bg + (255,))
    d.text((w / 2, h / 2 - 2), text, font=f, fill=fg + (255,), anchor='mm')
    layer.putalpha(layer.getchannel('A').point(lambda v: int(v * alpha / 255)))
    canvas.paste(layer, (int(cx - w / 2), int(cy - h / 2)), layer)


def flash(canvas, alpha):
    if alpha <= 0:
        return
    ov = Image.new('RGBA', canvas.size, (255, 250, 238, int(alpha)))
    canvas.paste(ov, (0, 0), ov)


# ---------------- scenes 05–15 ----------------
def scene_messages(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.6)
    kicker(CUR, lt, 0.02, '02  /  消息')
    headline(CUR, lt, 0.08, [
        [('附近刚发生的，', INK)],
        [('才推给', INK), ('你', GREEN), ('。', INK)],
    ], y=120, size=62)

    scr = screen_slice('09_messages', 640, 1386, 1.03, (0.5, 0.40))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
    callout(CUR, (1042, 96), (rect[2] - 40, 760), '800m', '2 小时前有人核实', color=BLUE,
            align='right', p=ease_out((lt - 0.75) / 0.45))
    callout(CUR, (1042, 196), (rect[2] - 40, 1030), '兴趣推荐', '为什么推给你，写清楚', color=GREEN,
            align='right', p=ease_out((lt - 1.45) / 0.45))


def scene_destination(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '03  /  目的地的保鲜度')
    headline(CUR, lt, 0.08, [
        [('多少条还有效，', INK)],
        [(None or '一眼', AMBER), ('就知道。', INK)],
    ], y=120, size=62)

    scr = screen_slice('04_destination', 640, 1386, 1.10, (0.5, 0.34))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)

    p = ease_out((lt - 0.55) / 0.9)
    if p > 0:
        cx, cy, r = 942, 300, 78
        ring_gauge(CUR, cx, cy, r, 0.45, GREEN, width=13, p=p)
        d = ImageDraw.Draw(CUR)
        d.text((cx, cy - 8), '45%', font=font(F_MONO, 38), fill=INK, anchor='mm')
        d.text((cx, cy + 34), '整体保鲜度', font=font(F_MED, 18), fill=INK_SOFT, anchor='mm')
        layer = Image.new('RGBA', (230, 50), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((115, 4), '5 / 11 条新鲜', font=font(F_BOLD, 22), fill=GREEN + (255,), anchor='ma')
        CUR.paste(layer, (cx - 115, cy + r + 16), layer)
        d = ImageDraw.Draw(CUR, 'RGBA')
        d.line([(cx, cy + r + 72), (rect[2] - 54, 560)], fill=GREEN + (150,), width=2)
        d.ellipse([rect[2] - 60, 554, rect[2] - 48, 566], fill=GREEN + (220,))


def scene_fact(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '04  /  一条信息卡')
    headline(CUR, lt, 0.08, [
        [('证据和票数，', INK)],
        [('都摆在', INK), ('你面前', GREEN), ('。', INK)],
    ], y=120, size=62)

    focus = 0.28 + 0.26 * ease_in_out(lt / dur)
    scr = screen_slice('05_fact_pending', 640, 1386, 1.12, (0.5, focus))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
    callout(CUR, (1042, 96), (rect[2] - 46, 500), '5 / 6', '还差 1 票就生效', color=AMBER,
            align='right', p=ease_out((lt - 0.6) / 0.45))
    # 底部证据提示
    pp = ease_out((lt - 1.35) / 0.5)
    if pp > 0:
        pill(CUR, 540, 1818, '3 份证据 · 时间 / 地点 / 票据', fg=GREEN, bg=(232, 241, 234), size=24,
             alpha=int(230 * pp), padx=28, pady=14)


def scene_vote(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '05  /  核实')
    headline(CUR, lt, 0.08, [
        [('票数达标，', INK)],
        [('才算', INK), ('新鲜', GREEN), ('。', INK)],
    ], y=120, size=62)

    cut = 0.62
    if lt < cut:
        scr = screen_slice('06_vote_sheet', 640, 1386, 1.05, (0.5, 0.56))
        rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
        tp = ease_out((lt - 0.10) / 0.25)
        tap(CUR, 540, 1640, tp)
        flash(CUR, max(0, 255 * (lt - 0.5) / 0.12))
    else:
        # 结果卡片
        p = ease_out((lt - cut) / 0.4)
        card = Image.new('RGBA', (940, 1200), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle([0, 0, 939, 1199], radius=34, fill=(252, 249, 241, 255),
                             outline=(214, 205, 189, 255), width=2)
        cd.text((54, 46), '核实结果', font=font(F_MED, 24), fill=(128, 134, 125, 255))
        cd.text((54, 84), '兴教寺门票 · 20 元 / 人', font=font(F_BOLD, 32), fill=INK + (255,))
        cd.line([(54, 140), (886, 140)], fill=(222, 214, 198, 255), width=2)

        ring_p = ease_out((lt - cut - 0.08) / 0.62)
        cx, cy, r = 470, 430, 182
        cd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(226, 219, 204, 255), width=18)
        if ring_p > 0:
            end = -90 + 360 * ring_p
            cd.arc([cx - r, cy - r, cx + r, cy + r], -90, end, fill=GREEN + (255,), width=18)
            a = math.radians(end)
            cd.ellipse([cx + r * math.cos(a) - 10, cy + r * math.sin(a) - 10,
                        cx + r * math.cos(a) + 10, cy + r * math.sin(a) + 10], fill=GREEN + (255,))
        count_p = ease_out((lt - cut - 0.42) / 0.35)
        num = 5 + (1 if count_p > 0.5 else 0) if lt < cut + 0.8 else 6
        cd.text((cx, cy - 26), f'{num} / 6', font=font(F_MONO, 92), fill=GREEN + (255,), anchor='mm')
        cd.text((cx, cy + 60), '人确认真实', font=font(F_MED, 26), fill=INK_SOFT + (255,), anchor='mm')

        tp = ease_out((lt - cut - 0.60) / 0.35)
        if tp > 0:
            cd.text((cx, 720), '达到门槛，已通过核实', font=font(F_BLACK, 44), fill=INK + (int(255 * tp),), anchor='ma')
        sp = ease_out((lt - cut - 0.90) / 0.30)
        if sp > 0:
            cd.rounded_rectangle([330, 820, 750, 892], radius=36, fill=(232, 242, 233, 255))
            cd.text((540, 850), '新鲜 · 30 天内有效', font=font(F_BOLD, 28), fill=GREEN + (int(255 * sp),), anchor='mm')
        cd.text((54, 1036), '已同步给 214 位近期到访者', font=font(F_BOLD, 24), fill=GREEN + (255,))
        cd.text((54, 1080), '5 位到访者 + 1 位本地人', font=font(F_MED, 22), fill=(140, 145, 136, 255))
        cd.text((886, 1080), '真途 · 信息卡 #sx-4', font=font(F_MED, 19), fill=(170, 170, 160, 255), anchor='ra')
        card.putalpha(card.getchannel('A').point(lambda v: int(v * p)))
        # 阴影
        sh = Image.new('RGBA', (card.width + 120, card.height + 120), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([60, 70, 1000, 1270], radius=38, fill=(0, 0, 0, 90))
        sh = sh.filter(ImageFilter.GaussianBlur(30))
        CUR.paste(sh, (40, 300), sh)
        CUR.paste(card, (70, 330 + int((1 - p) * 40)), card)
        if sp > 0:
            stamp(CUR, '新鲜', 850, 505, GREEN, angle=-9, scale=lerp(1.4, 1.0, sp), alpha=int(255 * sp), size=46, padx=26, pady=14, bw=6)


def scene_plan(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '06  /  排行程')
    headline(CUR, lt, 0.08, [
        [('三分钟，', INK)],
        [('生成', INK), ('三版', AMBER), ('行程。', INK)],
    ], y=120, size=62)

    # 连接线
    lp = ease_out((lt - 0.2) / 0.7)
    if lp > 0:
        d = ImageDraw.Draw(CUR, 'RGBA')
        d.line([(185, 748), (185 + 710 * lp, 748)], fill=(14, 124, 102, 80), width=3)

    names = ['10_plan_step1', '11_plan_step2', '12_plan_step3']
    labels = ['01  选地方', '02  选兴趣', '03  生成']
    xs = [25, 375, 725]
    for i, (nm, lab, x) in enumerate(zip(names, labels, xs)):
        p = ease_out((lt - 0.15 - i * 0.28) / 0.5)
        if p <= 0:
            continue
        y = 790 + (1 - p) * 46
        scr = screen_slice(nm, 322, 698, 1.0)
        paste_phone(CUR, scr, x, y, 330, 716, bezel=4, radius=34, shadow=False, alpha=int(255 * p))
        d = ImageDraw.Draw(CUR, 'RGBA')
        d.text((x + 165, 720), lab, font=font(F_BOLD, 26), fill=INK + (int(220 * p),), anchor='ma')
        d.ellipse([x + 165 - 5, 748 - 5, x + 165 + 5, 748 + 5], fill=GREEN + (int(240 * p),))

    pp = ease_out((lt - 1.55) / 0.5)
    if pp > 0:
        pill(CUR, 540, 1720, '≈ 3 分钟 · 不用自己拼', fg=PAPER, bg=GREEN_DEEP, size=28, alpha=int(240 * pp))


def scene_variants(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '07  /  三个版本')
    headline(CUR, lt, 0.08, [
        [('经典、小众、松弛，', INK)],
        [('选一个', INK), ('最像你的', GREEN), ('。', INK)],
    ], y=120, size=58)

    scr = screen_slice('13_variants', 640, 1386, 1.06, (0.5, 0.48))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)

    callout(CUR, (1042, 96), (rect[2] - 54, 620), '3 个版本', '标好取舍，不塞满', color=GREEN,
            align='right', p=ease_out((lt - 1.1) / 0.45))


def scene_trip(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '08  /  出发前')
    headline(CUR, lt, 0.08, [
        [('哪条过期了，', INK)],
        [('出发前', INK), ('提醒你', RED), ('。', INK)],
    ], y=120, size=62)

    scr = screen_slice('14_trip', 640, 1386, 1.09, (0.5, 0.34))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
    target = (rect[2] - 62, 980)
    callout(CUR, (1042, 96), target, '3 条', '出发前要确认', color=RED,
            align='right', p=ease_out((lt - 0.65) / 0.45))
    # 脉冲
    pp = ease_out((lt - 0.8) / 0.4)
    if pp > 0:
        d = ImageDraw.Draw(CUR, 'RGBA')
        q = (lt * 0.9) % 1.0
        r = 22 + 34 * q
        d.ellipse([target[0] - r, target[1] - r, target[0] + r, target[1] + r],
                  outline=RED + (int(150 * (1 - q) * pp),), width=2)


def scene_play(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '09  /  在路上')
    headline(CUR, lt, 0.08, [
        [('点开路线，', INK)],
        [('一站一站走。', INK), ('', INK)],
    ], y=120, size=62)

    scr = screen_slice('15_play', 640, 1386, 1.08, (0.5, 0.40))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)

    # 沿站点移动的脉冲
    p = ease_out((lt - 0.45) / 0.5)
    if p > 0:
        mv = ease_in_out((lt - 0.75) / 1.65)
        rx = lerp(0.152, 0.318, mv)
        ry = lerp(0.392, 0.402, mv)
        cx = rect[0] + (rect[2] - rect[0]) * rx
        cy = rect[1] + (rect[3] - rect[1]) * ry
        d = ImageDraw.Draw(CUR, 'RGBA')
        for k in range(2):
            q = ((lt * 0.75 + k * 0.5) % 1.0)
            r = 14 + 34 * q
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=GREEN + (int(160 * (1 - q) * p),), width=3)
        d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11], fill=GREEN + (int(255 * p),))
        d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255, int(255 * p)))
    pill(CUR, 540, 1818, '第 1 天 · 09:00 兴教寺', fg=GREEN, bg=(232, 241, 234), size=24,
         alpha=int(230 * p), padx=28, pady=14)


def scene_hearing(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '10  /  出行听证')
    headline(CUR, lt, 0.08, [
        [('拿不准，', INK)],
        [('让网友替你', INK), ('听证', BLUE), ('。', INK)],
    ], y=120, size=62)

    focus = 0.30 + 0.22 * ease_in_out(lt / dur)
    scr = screen_slice('17_hearing', 640, 1386, 1.06, (0.5, focus))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
    callout(CUR, (1042, 96), (rect[2] - 46, 560), '5 / 6', '网友正在表决', color=BLUE,
            align='right', p=ease_out((lt - 0.7) / 0.45))


def scene_review(t, lt, dur):
    global CUR
    CUR = bg('paper', t, 0.5)
    kicker(CUR, lt, 0.02, '11  /  回来')
    headline(CUR, lt, 0.08, [
        [('回来，', INK)],
        [('顺手', INK), ('核实一条', GREEN), ('。', INK)],
    ], y=120, size=62)

    scr = screen_slice('18_profile', 640, 1386, 1.07, (0.5, 0.42))
    rect = paste_phone(CUR, scr, 220, 380, 640, 1386, bezel=10, radius=52)
    callout(CUR, (1042, 96), (rect[2] - 50, 760), '+2', '信誉 · 帮到下一个人', color=GREEN,
            align='right', p=ease_out((lt - 0.7) / 0.45))
    # 收尾压暗
    fp = ease_out((lt - 2.05) / 0.55)
    if fp > 0:
        ov = Image.new('RGBA', CUR.size, (6, 16, 13, int(255 * fp)))
        CUR.paste(ov, (0, 0), ov)


def scene_end(t, lt, dur):
    global CUR
    CUR = bg('dark', t, 0.25)
    d = ImageDraw.Draw(CUR, 'RGBA')
    # 细圆
    p = ease_out((lt - 0.05) / 0.9)
    if p > 0:
        r = 330
        d.ellipse([W / 2 - r, 660 - r, W / 2 + r, 660 + r], outline=(120, 190, 165, int(44 * p)), width=2)

    # 印章
    sp = ease_out((lt - 0.02) / 0.36)
    if sp > 0:
        seal = Image.new('RGBA', (250, 250), (0, 0, 0, 0))
        sd = ImageDraw.Draw(seal)
        sd.rounded_rectangle([8, 8, 242, 242], radius=22, fill=(247, 243, 234, 255))
        sd.rounded_rectangle([22, 22, 228, 228], radius=14, outline=(14, 124, 102, 255), width=8)
        sd.text((125, 125), '真', font=font(F_SERIF, 150), fill=(14, 124, 102, 255), anchor='mm')
        seal = seal.rotate(-5, expand=True, resample=Image.BICUBIC)
        seal = seal.resize((int(seal.width * lerp(1.5, 1.0, sp)), int(seal.height * lerp(1.5, 1.0, sp))), Image.LANCZOS)
        seal.putalpha(seal.getchannel('A').point(lambda v: int(v * min(1, sp * 1.5))))
        CUR.paste(seal, (int(W / 2 - seal.width / 2), int(600 - seal.height / 2)), seal)

    p = ease_out((lt - 0.36) / 0.5)
    if p > 0:
        layer = Image.new('RGBA', (W, 320), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((W / 2, 0), '真 途', font=font(F_BLACK, 148), fill=PAPER + (int(255 * p),), anchor='ma')
        tracked(ld, (W / 2 - 62, 238), 'ZHENTU', font(F_MONO, 24), PAPER + (int(180 * p),), spacing=10)
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, int(790 + (1 - p) * 16)), layer)

    p = ease_out((lt - 0.78) / 0.55)
    if p > 0:
        layer = Image.new('RGBA', (W, 80), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((W / 2, 0), '每一条攻略，都有人替你走过', font=font(F_SERIF_B, 40), fill=(236, 231, 218, int(245 * p)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, int(1122 + (1 - p) * 12)), layer)

    p = ease_out((lt - 1.15) / 0.5)
    if p > 0:
        pill(CUR, 540, 1272, '内测预约 · 评论区见', fg=(12, 40, 32), bg=(232, 226, 210), size=32,
             alpha=int(245 * p), padx=40, pady=20)
    p = ease_out((lt - 1.5) / 0.5)
    if p > 0:
        layer = Image.new('RGBA', (W, 60), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.text((W / 2, 0), '如果它真能用，你想先去哪？', font=font(F_MED, 26), fill=(168, 184, 174, int(210 * p)), anchor='ma')
        layer.putalpha(layer.getchannel('A').point(lambda v: int(v * p)))
        CUR.paste(layer, (0, 1360), layer)

    d = ImageDraw.Draw(CUR, 'RGBA')
    d.line([(W / 2 - 70, 1480), (W / 2 + 70, 1480)], fill=(14, 158, 130, int(140 * p)), width=2)
    d.text((W / 2, 1760), '微信小程序  ·  内测中', font=font(F_MED, 22), fill=(128, 148, 138, 200), anchor='mm')


# ---------------- static scene table ----------------
SCENES = [
    ('hook', 0.0, 2.6667, scene_hook),
    ('broken', 2.6667, 5.3333, scene_broken),
    ('brand', 5.3333, 8.0, scene_brand),
    ('feed', 8.0, 10.6667, _scene_feed_impl),
    ('messages', 10.6667, 13.3333, scene_messages),
    ('destination', 13.3333, 16.0, scene_destination),
    ('fact', 16.0, 18.6667, scene_fact),
    ('vote', 18.6667, 21.3333, scene_vote),
    ('plan', 21.3333, 24.0, scene_plan),
    ('variants', 24.0, 26.6667, scene_variants),
    ('trip', 26.6667, 29.3333, scene_trip),
    ('play', 29.3333, 32.0, scene_play),
    ('hearing', 32.0, 34.6667, scene_hearing),
    ('review', 34.6667, 37.3333, scene_review),
    ('end', 37.3333, 40.0, scene_end),
]


def scene_bounds():
    return [(n, a, b) for n, a, b, _ in SCENES]


def render_time(t):
    init_static()
    global CUR
    for name, a, b, fn in SCENES:
        if a <= t < b:
            fn(t, t - a, b - a)
            return finish(CUR)
    # 默认最后一帧
    name, a, b, fn = SCENES[-1]
    fn(t, t - a, b - a)
    return finish(CUR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--times', type=str, default='')
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--contact', action='store_true')
    ap.add_argument('--range', type=str, default='')
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    if args.range:
        a, b = [int(x) for x in args.range.split(',')]
        for i in range(a, min(b, N_FRAMES)):
            im = render_time(i / FPS)
            im.save(os.path.join(OUT_DIR, f'f_{i:04d}.jpg'), quality=93)
        print('range done', a, b)
        return
    if args.contact:
        cols, rows = 8, 5
        tw, th = 216, 384
        sheet = Image.new('RGB', (cols * tw, rows * th), (20, 20, 20))
        for i in range(cols * rows):
            t = i * (DUR / (cols * rows))
            im = render_time(t).resize((tw, th), Image.LANCZOS)
            sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
            print('contact', i, round(t, 2), flush=True)
        sheet.save(os.path.join(ROOT, 'out', 'contact_sheet.jpg'), quality=92)
        return
    if args.times:
        for ts in args.times.split(','):
            t = float(ts)
            im = render_time(t)
            path = os.path.join(PREVIEW_DIR, f't_{t:05.2f}.jpg')
            im.save(path, quality=94)
            print('preview', path)
        return
    for i in range(N_FRAMES):
        im = render_time(i / FPS)
        im.save(os.path.join(OUT_DIR, f'f_{i:04d}.jpg'), quality=93)
        if i % 60 == 0:
            print(f'{i}/{N_FRAMES}', flush=True)
    print('done')


if __name__ == '__main__':
    main()
