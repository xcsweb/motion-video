#!/usr/bin/env python3
"""Render the 2D map assets used by the promo compositor."""
import json
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
OUT = os.path.join(ROOT, 'assets', 'graphics')
os.makedirs(OUT, exist_ok=True)

W, H = 3840, 2160  # 2x of 1920x1080
INK = (4, 7, 11)
GRID = (22, 38, 48)
RIVER = (24, 78, 92)
TEXT = (210, 230, 240)
DIM = (120, 140, 150)

FONT_DISPLAY = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'
FONT_BODY = '/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc'
FONT_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'


def load_json(name):
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        return json.load(f)


def pairs(path):
    return [(path[i], path[i + 1]) for i in range(0, len(path) - 1, 2)]


def build_transform(network):
    # Frame the dense urban core; far suburban tails run off-frame like a real map crop.
    minx, maxx, minz, maxz = -18000, 22000, -22000, 2500
    pad = 80
    sx = (W - pad * 2) / (maxx - minx)
    sz = (H - pad * 2) / (maxz - minz)
    s = min(sx, sz)
    cx = (minx + maxx) / 2
    cz = (minz + maxz) / 2
    return lambda x, z: (W / 2 + (x - cx) * s, H / 2 + (z - cz) * s)


def draw_grid(draw):
    step = 96
    for x in range(0, W, step):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, step):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)


def draw_rivers(draw, rivers, tf):
    for river in rivers:
        pts = [tf(x, z) for x, z in pairs(river['path'])]
        if len(pts) < 2:
            continue
        width = max(2, int(river['width'] * 0.004))
        draw.line(pts, fill=RIVER, width=width, joint='curve')


def draw_lines(base, network, tf, highlight=None):
    glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    sharp = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sharp)
    for line in network['lines']:
        color = line['color']
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
        pts = [tf(x, z) for x, z in pairs(line['path'])]
        if len(pts) < 2:
            continue
        active = highlight is None or line['id'] == highlight
        alpha = 255 if active else 42
        width = 9 if active else 6
        gd.line(pts, fill=rgb + (alpha,), width=width + 12, joint='curve')
        sd.line(pts, fill=rgb + (alpha,), width=width, joint='curve')
    glow = glow.filter(ImageFilter.GaussianBlur(14))
    base.alpha_composite(glow)
    base.alpha_composite(sharp)


def draw_stations(base, network, tf, highlight=None):
    d = ImageDraw.Draw(base)
    font = ImageFont.truetype(FONT_BODY, 28)
    key = {'李子坝', '朝天门', '重庆北站南广场', '观音桥', '沙坪坝', '较场口', '牛角沱', '大剧院', '杨家坪'}
    for st in network['stations']:
        x, y = tf(st['x'], st['z'])
        active = highlight is None or highlight in st['lines']
        r = 5
        d.ellipse([x - r, y - r, x + r, y + r], fill=(230, 245, 250) if active else (90, 110, 120))
        if st['name'] in key:
            tw = d.textlength(st['name'], font=font)
            d.rounded_rectangle([x + 10, y - 30, x + 20 + tw, y + 4], radius=6, fill=(6, 13, 19, 210))
            d.text((x + 15, y - 28), st['name'], font=font, fill=TEXT)


def vignette(img):
    mask = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-W * 0.25, -H * 0.35, W * 1.25, H * 1.35], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(260))
    dark = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    img.paste(dark, (0, 0), Image.eval(mask, lambda v: int((255 - v) * 0.55)))


def make_map(name, highlight=None):
    network = load_json('network.json')
    features = load_json('features.json')
    tf = build_transform(network)
    img = Image.new('RGBA', (W, H), INK + (255,))
    d = ImageDraw.Draw(img)
    draw_grid(d)
    halo = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([W * 0.22, H * 0.12, W * 0.78, H * 0.92], fill=(20, 70, 74, 46))
    halo = halo.filter(ImageFilter.GaussianBlur(320))
    img.alpha_composite(halo)
    draw_rivers(d, features['rivers'], tf)
    draw_lines(img, network, tf, highlight)
    draw_stations(img, network, tf, highlight)
    vignette(img)
    img.convert('RGB').save(os.path.join(OUT, name), quality=95)
    if highlight:
        line = next(l for l in network['lines'] if l['id'] == highlight)
        pts = [tf(x, z) for x, z in pairs(line['path'])]
        pts = [(x, y) for x, y in pts if 0 <= x <= W and 0 <= y <= H]
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        cw = min(W, max(max(xs) - min(xs) + 260, 900))
        ch = cw * 9 / 16
        cx = min(W - cw / 2, max(cw / 2, cx))
        cy = min(H - ch / 2, max(ch / 2, cy))
        box = [cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2]
        crop = img.crop(tuple(int(v) for v in box)).resize((960, 540), Image.LANCZOS)
        crop.convert('RGB').save(os.path.join(OUT, f'map2d_line{highlight}_crop.jpg'), quality=95)
        print('saved', f'map2d_line{highlight}_crop.jpg')
    print('saved', name)


if __name__ == '__main__':
    make_map('map2d.jpg')
    make_map('map2d_line2.jpg', '2')
    make_map('map2d_line6.jpg', '6')
