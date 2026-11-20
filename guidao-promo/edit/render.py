#!/usr/bin/env python3
"""Frame compositor for the 80s guidao promo.

Renders 1920x1080 @ 30fps JPEG frames from the captured 3D stills, UI
screenshots, 2D map and procedural graphics. Audio is mixed separately.
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1920, 1080
FPS = 30
DUR = 80.0
N = int(DUR * FPS)

F_DISPLAY = '/usr/share/fonts/opentype/smiley-sans/SmileySans-Oblique.otf'
F_BOLD = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'
F_BODY = '/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc'
F_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'

TEAL = (95, 211, 196)
AMBER = (246, 168, 0)
WHITE = (236, 246, 250)
DIM = (150, 170, 182)
INK = (4, 7, 11)
INK2 = (7, 14, 20)
LINE6 = (219, 90, 123)

rng = np.random.default_rng(7)


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def smooth(a, b, x):
    if a == b:
        return 1.0 if x >= b else 0.0
    t = clamp((x - a) / (b - a))
    return t * t * (3 - 2 * t)


def ease(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def load_image(rel):
    return Image.open(os.path.join(ROOT, rel)).convert('RGB')


def fit(img, zoom=1.0, panx=0.0, pany=0.0):
    """Crop a zoomed window and resize to 1920x1080."""
    w, h = img.size
    z = max(1.0, zoom)
    cw, ch = w / z, h / z
    cx = w / 2 + panx * w
    cy = h / 2 + pany * h
    cx = min(w - cw / 2, max(cw / 2, cx))
    cy = min(h - ch / 2, max(ch / 2, cy))
    box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
    return img.resize((W, H), Image.LANCZOS, box=box)


def grade_3d(img):
    arr = np.asarray(img.resize((W, H), Image.LANCZOS)).astype(np.float32) / 255.0
    lum = arr @ np.array([0.299, 0.587, 0.114], np.float32)
    arr = (arr - 0.5) * 1.14 + 0.5
    arr = lum[..., None] + (arr - lum[..., None]) * 1.10
    arr[..., 1] *= 0.97
    shadow = np.clip(1 - lum * 1.7, 0, 1)[..., None]
    high = np.clip((lum - 0.45) * 1.9, 0, 1)[..., None]
    arr = arr + shadow * np.array([-0.004, 0.010, 0.030], np.float32)
    arr = arr + high * np.array([0.024, 0.010, -0.004], np.float32)
    arr = np.clip(arr, 0, 1)
    # bloom
    bright = np.clip((lum - 0.52) * 2.4, 0, 1)[..., None] * arr
    b = Image.fromarray((bright * 255).clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))
    barr = np.asarray(b).astype(np.float32) / 255.0
    arr = 1 - (1 - arr) * (1 - barr * 0.38)
    # vignette
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    v = np.clip(1 - 0.34 * np.clip(r - 0.35, 0, 1) ** 1.4, 0, 1)
    arr = arr * v[..., None]
    # fine static grain
    arr = arr + rng.normal(0, 0.006, arr.shape).astype(np.float32)
    return Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8))


def clip_frame(name, local, dur, count):
    """Load one graded frame from a rendered 3D clip."""
    i = int(round(clamp(local / dur) * (count - 1)))
    hit = CLIP_CACHE.get(name)
    if hit and hit[0] == i:
        return hit[1]
    im = Image.open(os.path.join(ROOT, 'assets', '3d', name, f'f_{i:04d}.jpg')).convert('RGB')
    im = grade_3d(im)
    CLIP_CACHE[name] = (i, im)
    return im


def text_card(items, align='left', pad=24, shadow=True):
    """items: list of (text, font_path, size, color, gap_after)."""
    rendered = []
    maxw = 0
    total = 0
    for text, font_path, size, color, gap in items:
        font = ImageFont.truetype(font_path, int(size * 2))
        bbox = font.getbbox(text or ' ')
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        line_h = int(size * 2 * 1.28)
        rendered.append((text, font, color, line_h, gap))
        maxw = max(maxw, w)
        total += line_h + int(gap * 2)
    img = Image.new('RGBA', (maxw + pad * 2, total + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    y = pad
    for text, font, color, line_h, gap in rendered:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        x = pad if align == 'left' else (img.width - tw) / 2
        if shadow:
            d.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 150))
        d.text((x, y), text, font=font, fill=color + (255,))
        y += line_h + int(gap * 2)
    return img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.LANCZOS)


def put(base, card, xy, alpha=1.0, scale=1.0, shadow=False):
    if alpha <= 0.001:
        return
    if scale != 1.0:
        card = card.resize((max(1, int(card.width * scale)), max(1, int(card.height * scale))), Image.LANCZOS)
    if alpha < 1.0:
        card = card.copy()
        a = card.getchannel('A').point(lambda v: int(v * alpha))
        card.putalpha(a)
    if shadow:
        sh = Image.new('RGBA', (card.width + 40, card.height + 40), (0, 0, 0, 0))
        black = Image.new('RGBA', card.size, (0, 0, 0, 170))
        sh.paste(black, (20, 24), card.getchannel('A'))
        sh = sh.filter(ImageFilter.GaussianBlur(16))
        base.alpha_composite(sh, (int(xy[0]) - 20, int(xy[1]) - 20))
    base.alpha_composite(card, (int(xy[0]), int(xy[1])))


def rounded_ui(rel, width):
    im = Image.open(os.path.join(ROOT, rel)).convert('RGBA')
    if 'station' in rel:
        im = im.crop((0, 0, im.width, int(im.height * 0.89)))
    h = int(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    mask = Image.new('L', im.size, 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([2, 2, im.width - 3, im.height - 3], radius=22, fill=255)
    im.putalpha(mask)
    return im


def subtitle_cards():
    lines = json.load(open(os.path.join(ROOT, 'audio', 'lines.json'), encoding='utf-8'))
    cards = []
    for line in lines:
        card = text_card([
            (part, F_BODY, 44, WHITE, 0.18)
            for part in line['subtitle'].split('\n')
        ], align='center', pad=18, shadow=True)
        cards.append((line['index'], line['start'], line['end'], card))
    return cards


def bottom_scrim():
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for i in range(260):
        a = int(150 * (i / 260) ** 1.6)
        d.rectangle([0, H - 260 + i, W, H - 260 + i + 1], fill=(2, 6, 9, a))
    return img


# ---------------------------------------------------------------- assets
ASSETS = {}
SUBS = None
SCRIM = None
CLIP_CACHE = {}


def rounded_img(im, radius=20):
    im = im.convert('RGBA')
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    im.putalpha(mask)
    return im


def timetable_card():
    card = Image.new('RGBA', (640, 820), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle([0, 0, 639, 819], radius=22, fill=(6, 15, 21, 228), outline=(70, 105, 112, 255), width=2)
    d.rectangle([40, 48, 46, 150], fill=TEAL + (255,))
    d.text((70, 50), '运营组织 / SERVICE', font=ImageFont.truetype(F_BODY, 24), fill=TEAL)
    d.text((66, 120), '15 条线', font=ImageFont.truetype(F_DISPLAY, 76), fill=WHITE)
    d.text((70, 225), '共用同一运营时段', font=ImageFont.truetype(F_BODY, 30), fill=DIM)
    d.text((70, 300), '06:00 – 23:00', font=ImageFont.truetype(F_MONO, 52), fill=AMBER)
    d.line([(70, 390), (570, 390)], fill=(60, 90, 98, 255), width=2)
    for i, (label, value) in enumerate([('首班', '06:00'), ('末班', '23:00')]):
        x = 70 + i * 250
        d.text((x, 430), label, font=ImageFont.truetype(F_BODY, 26), fill=DIM)
        d.text((x, 470), value, font=ImageFont.truetype(F_MONO, 58), fill=WHITE)
    d.text((70, 590), '高峰 5 分 · 平峰 8 分', font=ImageFont.truetype(F_BODY, 28), fill=TEAL)
    d.text((70, 650), '运营时段 + 首末班 + 发车间隔', font=ImageFont.truetype(F_BODY, 24), fill=DIM)
    d.rounded_rectangle([70, 720, 250, 762], radius=21, fill=(60, 44, 6, 255), outline=AMBER + (180,), width=1)
    d.text((92, 728), '模拟班次', font=ImageFont.truetype(F_BOLD, 22), fill=AMBER)
    return card


def init_assets():
    global SUBS, SCRIM
    for name in ['hero_a', 'hero_b', 'hero_c', 'exag10_c', 'exag14_c', 'exag18_c', 'night', 'hook3d', 'river']:
        ASSETS[name] = grade_3d(load_image(f'assets/3d/{name}.jpg'))
    ASSETS['map2d'] = load_image('assets/graphics/map2d.jpg')
    ASSETS['map2d_line2'] = load_image('assets/graphics/map2d_line2.jpg')
    ASSETS['map2d_line6'] = load_image('assets/graphics/map2d_line6.jpg')
    ASSETS['map2d_line2_crop'] = load_image('assets/graphics/map2d_line2_crop.jpg')
    ASSETS['map2d_line6_crop'] = load_image('assets/graphics/map2d_line6_crop.jpg')
    SUBS = subtitle_cards()
    SCRIM = bottom_scrim()

    # big text cards
    C = {}
    C['s01'] = text_card([
        ('点一下', F_DISPLAY, 92, WHITE, 0.12),
        ('整座城市站起来', F_DISPLAY, 92, TEAL, 0),
    ])
    C['s02'] = text_card([
        ('从现在起', F_DISPLAY, 84, WHITE, 0.14),
        ('整座城市听你指挥', F_DISPLAY, 84, TEAL, 0),
    ])
    C['s04'] = text_card([
        ('打开浏览器', F_DISPLAY, 76, WHITE, 0.16),
        ('你就是指挥官', F_DISPLAY, 116, TEAL, 0),
    ])
    C['title'] = text_card([
        ('山城轨道', F_DISPLAY, 126, WHITE, 0.10),
        ('CHONGQING TRANSIT · 3D', F_MONO, 24, TEAL, 0),
    ])
    C['s05'] = text_card([('点开一条线', F_DISPLAY, 58, WHITE, 0)])
    C['s06'] = text_card([
        ('2 号线', F_DISPLAY, 58, (0, 160, 80), 0.10),
        ('嘉陵江 · 李子坝', F_BODY, 28, WHITE, 0),
    ])
    C['s07'] = text_card([
        ('6 号线', F_DISPLAY, 58, (219, 90, 123), 0.10),
        ('跨江段', F_BODY, 28, WHITE, 0),
    ])
    C['s08'] = text_card([
        ('高程夸张', F_BODY, 26, DIM, 0.10),
        ('×1.0 → ×1.8', F_MONO, 34, AMBER, 0),
    ])
    C['s10'] = text_card([
        ('运行图', F_DISPLAY, 64, WHITE, 0.10),
        ('全在掌握', F_DISPLAY, 64, TEAL, 0),
    ])
    C['s08b'] = text_card([
        ('6 号线 · 小什字', F_BODY, 25, LINE6, 0.06),
        ('隧道进站', F_DISPLAY, 44, WHITE, 0),
    ])
    C['s08c'] = text_card([
        ('6 号线 · 小什字', F_BODY, 25, LINE6, 0.06),
        ('站台视角', F_DISPLAY, 44, WHITE, 0),
    ])
    C['s13'] = text_card([('一座正在运行的城市', F_BODY, 34, DIM, 0)])
    C['brand'] = text_card([
        ('山城轨道', F_DISPLAY, 150, WHITE, 0.14),
        ('打开浏览器，走马上任', F_BOLD, 40, AMBER, 0),
    ], align='center')
    C['end'] = text_card([
        ('山城轨道', F_DISPLAY, 92, WHITE, 0.10),
        ('打开浏览器，走马上任', F_BOLD, 28, AMBER, 0),
        ('', F_BODY, 20, WHITE, 0),
        ('xcsweb.github.io/guidao', F_MONO, 30, TEAL, 0.22),
        ('github.com/xcsweb/guidao', F_MONO, 24, DIM, 0),
    ], align='center')
    C['credit'] = text_card([
        ('线网 / 建筑 / 水系 © OpenStreetMap 贡献者 (ODbL)', F_BODY, 19, (105, 125, 135), 0.10),
        ('高程 Terrarium / AWS Open Data · 列车为模拟班次 · AI 配音', F_BODY, 19, (105, 125, 135), 0.10),
        ('音乐 A New Life · Mixkit Free License', F_BODY, 19, (105, 125, 135), 0),
    ], align='center')
    ASSETS['C'] = C
    ASSETS['ui_line'] = rounded_ui('assets/ui/line_panel.png', 384)
    ASSETS['ui_train'] = rounded_ui('assets/ui/train_panel.png', 412)
    ASSETS['ui_station'] = rounded_ui('assets/ui/station_card_jc.png', 330)
    ASSETS['tt_card'] = timetable_card().resize((560, 718), Image.LANCZOS)
    tt = Image.open(os.path.join(ROOT, 'assets/ui/timetable.png')).convert('RGB')
    tt = tt.crop((0, int(tt.height * 0.435), tt.width, tt.height))
    tt = tt.resize((660, int(tt.height * 660 / tt.width)), Image.LANCZOS)
    raw = tt.crop((0, 0, 660, 1000)).resize((528, 800), Image.LANCZOS).convert('RGBA')
    grad = Image.new('RGBA', raw.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for i in range(80):
        gd.rectangle([0, 720 + i, 528, 721 + i], fill=(6, 15, 21, int(245 * (i / 80) ** 1.4)))
    ASSETS['tt_panel'] = rounded_img(Image.alpha_composite(raw, grad), 18)


# ---------------------------------------------------------------- shots
def base_dark():
    return Image.new('RGBA', (W, H), INK + (255,))


def with_subs(base, t):
    if SCRIM:
        base.alpha_composite(SCRIM)
    for idx, start, end, card in SUBS:
        if idx in (1, 11):
            continue
        if start - 0.15 <= t <= end + 0.15:
            a = min(smooth(start - 0.15, start + 0.05, t), 1 - smooth(end - 0.05, end + 0.15, t))
            put(base, card, ((W - card.width) / 2, H - 96 - card.height), a)
    return base


def add_flash(base, alpha, color=TEAL):
    if alpha <= 0:
        return
    layer = Image.new('RGBA', (W, H), color + (int(255 * alpha),))
    base.alpha_composite(layer)


def map_inset(base, name, xy, width=480, alpha=1.0):
    im = ASSETS[name].resize((width, int(width * 9 / 16)), Image.LANCZOS).convert('RGBA')
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=14, fill=255)
    im.putalpha(mask)
    put(base, im, xy, alpha, shadow=True)
    d = ImageDraw.Draw(base)
    x, y = int(xy[0]), int(xy[1])
    d.rounded_rectangle([x, y, x + width, y + int(width * 9 / 16)], radius=14, outline=TEAL + (110,), width=2)


def cursor(base, x, y, scale=1.0):
    d = ImageDraw.Draw(base)
    pts = [(x, y), (x, y + 26 * scale), (x + 7 * scale, y + 19 * scale), (x + 14 * scale, y + 30 * scale),
           (x + 19 * scale, y + 27 * scale), (x + 12 * scale, y + 16 * scale), (x + 22 * scale, y + 15 * scale)]
    d.polygon(pts, fill=(245, 252, 255, 255), outline=(0, 0, 0, 220))


def s01(t):
    C = ASSETS['C']
    base = fit(ASSETS['map2d'], zoom=1.0 + 0.035 * ease(t / 0.6), panx=0.0, pany=0.0).convert('RGBA')
    # cursor moves in
    cx = lerp(1260, 960, ease(min(1, t / 0.45)))
    cy = lerp(760, 540, ease(min(1, t / 0.45)))
    d = ImageDraw.Draw(base)
    if t < 0.55:
        pulse = 0.5 + 0.5 * math.sin(t * 12)
        d.ellipse([cx - 18 - 6 * pulse, cy - 18 - 6 * pulse, cx + 18 + 6 * pulse, cy + 18 + 6 * pulse],
                  outline=TEAL + (int(120 * pulse),), width=2)
    cursor(base, cx, cy)
    # click ripple
    if t > 0.48:
        for k in range(3):
            rr = (t - 0.48 - k * 0.12) * 900
            if rr > 0:
                a = int(180 * max(0, 1 - rr / 520))
                d.ellipse([960 - rr, 540 - rr, 960 + rr, 540 + rr], outline=TEAL + (a,), width=3)
    # tilt + crossfade to 3D
    if t > 0.55:
        p = smooth(0.55, 1.9, t)
        sy = 1.0 - 0.28 * p
        tilted = base.resize((W, max(2, int(H * sy))), Image.LANCZOS)
        canvas = Image.new('RGBA', (W, H), (3, 7, 10, 255))
        canvas.alpha_composite(tilted, (0, int((H - tilted.height) * 0.55)))
        # cyan edge glow at the fold
        glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.rectangle([0, int(H * 0.55) - 3, W, int(H * 0.55) + 3], fill=TEAL + (int(110 * (1 - p)),))
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(8)))
        base = canvas
        a = smooth(0.85, 1.75, t)
        h3 = fit(ASSETS['hook3d'], zoom=lerp(1.10, 1.0, ease((t - 0.85) / 1.2))).convert('RGBA')
        base = Image.blend(base, h3, a)
    add_flash(base, 0.22 * smooth(0.5, 0.7, t) * (1 - smooth(0.9, 1.4, t)))
    # text
    put(base, C['s01'], (120, 330), smooth(1.85, 2.25, t))
    return base


def s02(t):
    C = ASSETS['C']
    base = fit(ASSETS['hook3d'], zoom=1.04 - 0.04 * ease((t - 3) / 5)).convert('RGBA')
    put(base, C['title'], (120, 300), smooth(3.3, 3.8, t))
    return base


def stat_card(t, start):
    p = ease((t - start) / 1.4)
    n1 = int(round(15 * p)); n2 = int(round(270 * p)); n3 = int(round(562 * p))
    return text_card([
        (str(n1), F_MONO, 92, TEAL, 0.02),
        ('条线路', F_BODY, 26, WHITE, 0.28),
        (str(n2), F_MONO, 92, WHITE, 0.02),
        ('座车站', F_BODY, 26, WHITE, 0.28),
        (str(n3), F_MONO, 92, AMBER, 0.02),
        ('公里线网', F_BODY, 26, WHITE, 0.18),
        ('32,736 栋建筑 · 614 条水系', F_BODY, 22, DIM, 0),
    ])


def s03(t):
    if t < 11.0:
        idx = int((t - 8.0) * FPS)
        idx = max(0, min(89, idx))
        frame = Image.open(os.path.join(ROOT, f'assets/3d/orbit_a/f_{idx:04d}.jpg')).convert('RGB')
        base = grade_3d(frame).convert('RGBA')
    else:
        base = fit(ASSETS['hero_b'], zoom=1.02 + 0.03 * ease((t - 11) / 4)).convert('RGBA')
    card = stat_card(t, 8.4)
    put(base, card, (120, 250), smooth(8.2, 8.7, t))
    return base


def s04(t):
    C = ASSETS['C']
    base = fit(ASSETS['hero_b'], zoom=1.02 + 0.05 * ease((t - 15) / 5)).convert('RGBA')
    put(base, C['s04'], (120, 310), smooth(15.2, 15.7, t))
    return base


def s05(t):
    C = ASSETS['C']
    base = fit(ASSETS['hero_c'], zoom=1.03 + 0.03 * ease((t - 20) / 3)).convert('RGBA')
    p = ease((t - 20.0) / 0.55)
    x = lerp(-440, 56, p)
    put(base, ASSETS['ui_line'], (x, 110), p, shadow=True)
    put(base, C['s05'], (520, 140), smooth(20.2, 20.6, t))
    return base


def s06(t):
    C = ASSETS['C']
    base = fit(ASSETS['hero_c'], zoom=1.04 + 0.05 * ease((t - 23) / 3), panx=-0.01, pany=0.0).convert('RGBA')
    map_inset(base, 'map2d_line2_crop', (1330, 540), 480, smooth(23.1, 23.5, t))
    put(base, C['s06'], (120, 760), smooth(23.1, 23.5, t))
    return base


def s07(t):
    C = ASSETS['C']
    base = fit(ASSETS['hero_b'], zoom=1.03 + 0.04 * ease((t - 26) / 3), panx=0.01).convert('RGBA')
    map_inset(base, 'map2d_line6_crop', (1330, 540), 480, smooth(26.1, 26.5, t))
    put(base, C['s07'], (120, 760), smooth(26.1, 26.5, t))
    return base


def s08(t):
    C = ASSETS['C']
    base = fit(ASSETS['exag10_c'], zoom=1.01 + 0.03 * ease((t - 29) / 5)).convert('RGBA')
    put(base, C['s08'], (1300, 790), smooth(29.2, 29.6, t))
    return base


def s08b(t):
    """6 号线小什字：第一视角隧道进站。"""
    C = ASSETS['C']
    local = t - 31.5
    img = clip_frame('line6_arrival_hd', local, 2.5, 60)
    base = fit(img, zoom=1.0 + 0.02 * ease(local / 2.5)).convert('RGBA')
    put(base, C['s08b'], (120, 96), smooth(31.62, 31.95, t))
    return base


def s08c(t):
    """6 号线小什字：站台视角看进站列车。"""
    C = ASSETS['C']
    local = t - 34.0
    img = clip_frame('line6_platform_hd', local, 2.5, 66)
    base = fit(img, zoom=1.0 + 0.025 * ease(local / 2.5), panx=0.006).convert('RGBA')
    put(base, C['s08c'], (120, 96), smooth(34.12, 34.45, t))
    return base


def s09(t):
    C = ASSETS['C']
    p = smooth(36.5, 37.8, t)
    a = fit(ASSETS['exag14_c'], zoom=1.01).convert('RGBA')
    b = fit(ASSETS['exag18_c'], zoom=1.01).convert('RGBA')
    base = Image.blend(a, b, p)
    # big 1.8
    big = text_card([('×1.8', F_MONO, 120, AMBER, 0)], align='center')
    put(base, big, (1300, 560), smooth(37.4, 37.8, t))
    return base


def s10(t):
    C = ASSETS['C']
    base = fit(ASSETS['hero_a'], zoom=1.02 + 0.03 * ease((t - 39) / 5)).convert('RGBA')
    p = ease((t - 39.2) / 0.6)
    x = lerp(W + 20, W - 470, p)
    put(base, ASSETS['ui_train'], (x, 110), p, shadow=True)
    tag = text_card([('模拟班次', F_BODY, 20, AMBER, 0)])
    put(base, tag, (x, 72), p)
    put(base, C['s10'], (120, 760), smooth(39.3, 39.7, t))
    return base


def s11(t):
    """运营时段 + 首末班 + 每站到站时刻。"""
    base = fit(ASSETS['hero_b'], zoom=1.02 + 0.03 * ease((t - 44) / 5)).convert('RGBA')
    base.alpha_composite(Image.new('RGBA', (W, H), (4, 10, 14, 150)))

    p = ease((t - 44.15) / 0.7)
    x = lerp(-580, 70, p)
    y = 64
    put(base, ASSETS['tt_card'], (x, y), p, shadow=True)
    if x > -500:
        d = ImageDraw.Draw(base)
        pulse = 0.55 + 0.45 * math.sin((t - 44.5) * 4.2)
        d.rounded_rectangle([x + 52, y + 252, x + 525, y + 326], radius=11,
                            outline=AMBER + (int(150 * pulse),), width=2)

    q = ease((t - 44.3) / 0.7)
    px = lerp(W + 20, 1240, q)
    put(base, ASSETS['tt_panel'], (px, 56), q, shadow=True)
    label = text_card([('2 号线 · 各站到站时刻', F_BOLD, 25, TEAL, 0)])
    put(base, label, (1240, 18), q)
    return base


def s12(t):
    base = fit(ASSETS['night'], zoom=1.10 - 0.10 * ease((t - 49) / 5)).convert('RGBA')
    return base


def s13(t):
    C = ASSETS['C']
    base = fit(ASSETS['night'], zoom=1.04 + 0.04 * ease((t - 54) / 10), panx=0.01).convert('RGBA')
    put(base, C['s13'], (120, 110), smooth(54.2, 54.8, t))
    return base


TERM_LINES = [
    ('$ npm run build:data', TEAL),
    ('> cq-transit-3d@1.0.0 build:data', DIM),
    ('[osm]   15 lines / 270 stations / 562 km', WHITE),
    ('[terrain] bake 3 tiers / 11.8 MB', WHITE),
    ('[network] 2,491 track points', WHITE),
    ('[done]  public/data/cq ready', TEAL),
]


def s14(t):
    base = Image.new('RGBA', (W, H), (3, 8, 12, 255))
    d = ImageDraw.Draw(base)
    # faint grid
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(12, 26, 34, 255))
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(12, 26, 34, 255))
    # window
    x0, y0, x1, y1 = 220, 210, 1700, 740
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=(5, 12, 18, 245), outline=(40, 70, 78, 255), width=2)
    d.rounded_rectangle([x0, y0, x1, y0 + 52], radius=18, fill=(9, 20, 27, 255))
    for i, col in enumerate([(220, 80, 70), (230, 180, 60), (80, 190, 120)]):
        d.ellipse([x0 + 22 + i * 26, y0 + 18, x0 + 36 + i * 26, y0 + 32], fill=col)
    font = ImageFont.truetype(F_MONO, 28)
    elapsed = max(0, t - 64.0)
    chars = int(elapsed * 95)
    used = 0
    y = y0 + 90
    for text, color in TERM_LINES:
        n = max(0, min(len(text), chars - used))
        if n > 0:
            d.text((x0 + 40, y), text[:n], font=font, fill=color + (255,))
        used += len(text) + 4
        y += 52
        if used > chars:
            break
    # flow bar
    fy = 790
    items = ['OSM', '地形', '线网', '列车']
    fx = 330
    for i, label in enumerate(items):
        active = (t - 64.0) > (i + 1) * 0.55
        col = TEAL if active else (50, 75, 82)
        d.rounded_rectangle([fx, fy - 24, fx + 170, fy + 24], radius=24, fill=(6, 15, 20, 240), outline=col + (255,), width=2)
        d.text((fx + 68, fy - 13), label, font=ImageFont.truetype(F_BODY, 24), fill=WHITE if active else DIM)
        if i < len(items) - 1:
            d.line([fx + 180, fy, fx + 270, fy], fill=col + (255,), width=2)
        fx += 290
    return base


def s15(t):
    base = Image.new('RGBA', (W, H), (3, 8, 12, 255))
    d = ImageDraw.Draw(base)
    for x in range(0, W, 64):
        d.line([(x, 0), (x, H)], fill=(12, 26, 34, 255))
    for y in range(0, H, 64):
        d.line([(0, y), (W, y)], fill=(12, 26, 34, 255))
    head = text_card([('城市数据包，即插即用', F_DISPLAY, 46, WHITE, 0)], align='center')
    put(base, head, ((W - head.width) / 2, 130), smooth(69.1, 69.6, t))
    boxes = [
        ('城市注册表', 'manifest.json', 130, 340),
        ('标准数据包', 'network / terrain', 500, 340),
        ('渲染核心', 'Three.js', 870, 340),
        ('实时 Provider', 'VITE_REALTIME_URL', 1240, 340),
    ]
    p = ease((t - 69.0) / 1.2)
    for i, (title, sub, x, y) in enumerate(boxes):
        active = p > i * 0.2
        col = TEAL if active else (45, 70, 78)
        d.rounded_rectangle([x, y, x + 320, y + 170], radius=16, fill=(6, 15, 21, 240), outline=col + (255,), width=2)
        d.text((x + 28, y + 40), title, font=ImageFont.truetype(F_BOLD, 32), fill=WHITE if active else DIM)
        d.text((x + 28, y + 98), sub, font=ImageFont.truetype(F_MONO, 19), fill=col + (255,))
        if i < 3:
            d.line([x + 320, y + 85, x + 370, y + 85], fill=(col if active else (45, 70, 78)) + (255,), width=3)
    note = text_card([('四叉树 LOD · 实例化 · 按需渲染', F_BODY, 22, DIM, 0)], align='center')
    put(base, note, ((W - note.width) / 2, 700), smooth(70.2, 70.6, t))
    return base


def s16(t):
    C = ASSETS['C']
    base = fit(ASSETS['night'], zoom=1.05 - 0.05 * ease((t - 73) / 4)).convert('RGBA')
    # dim
    dim = Image.new('RGBA', (W, H), (0, 0, 0, 90))
    base.alpha_composite(dim)
    put(base, C['brand'], ((W - C['brand'].width) / 2, 360), smooth(73.2, 73.8, t))
    return base


def s17(t):
    C = ASSETS['C']
    base = Image.new('RGBA', (W, H), (2, 5, 8, 255))
    put(base, C['end'], ((W - C['end'].width) / 2, 300), smooth(77.0, 77.4, t))
    put(base, C['credit'], ((W - C['credit'].width) / 2, 900), smooth(77.3, 77.7, t))
    # fade out
    fade = smooth(79.2, 79.95, t)
    if fade > 0:
        base.alpha_composite(Image.new('RGBA', (W, H), (0, 0, 0, int(255 * fade))))
    return base


def render_frame(t):
    if t < 3: base = s01(t)
    elif t < 8: base = s02(t)
    elif t < 15: base = s03(t)
    elif t < 20: base = s04(t)
    elif t < 23: base = s05(t)
    elif t < 26: base = s06(t)
    elif t < 29: base = s07(t)
    elif t < 31.5: base = s08(t)
    elif t < 34: base = s08b(t)
    elif t < 36.5: base = s08c(t)
    elif t < 39: base = s09(t)
    elif t < 44: base = s10(t)
    elif t < 49: base = s11(t)
    elif t < 54: base = s12(t)
    elif t < 64: base = s13(t)
    elif t < 69: base = s14(t)
    elif t < 73: base = s15(t)
    elif t < 77: base = s16(t)
    else: base = s17(t)
    return with_subs(base.convert('RGBA'), t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preview', nargs='*', type=float, help='render specific seconds')
    ap.add_argument('--start', type=float, default=0)
    ap.add_argument('--end', type=float, default=DUR)
    args = ap.parse_args()
    init_assets()
    outdir = os.path.join(ROOT, 'out', 'frames')
    os.makedirs(outdir, exist_ok=True)
    if args.preview:
        os.makedirs(os.path.join(ROOT, 'out', 'preview'), exist_ok=True)
        for sec in args.preview:
            img = render_frame(sec).convert('RGB')
            p = os.path.join(ROOT, 'out', 'preview', f'p_{sec:05.1f}.jpg')
            img.save(p, quality=94)
            print('preview', p)
        return
    i0 = int(round(args.start * FPS))
    i1 = int(round(args.end * FPS))
    for i in range(i0, i1):
        t = i / FPS
        img = render_frame(t).convert('RGB')
        img.save(os.path.join(outdir, f'f_{i:05d}.jpg'), quality=93, subsampling=1)
        if i % 60 == 0:
            print(f'{i}/{N}  {t:5.1f}s', flush=True)
    print('done', i1 - i0, 'frames')


if __name__ == '__main__':
    main()
