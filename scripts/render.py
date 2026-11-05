#!/usr/bin/env python3
"""RAILGUN // OVERDRIVE — a 24 s, 1920x1080@30 code-rendered music video.

Every frame is procedural: neon rail cannon, charging coils, electric arcs,
rainbow projectile trail, shockwaves, explosions, HUD and kinetic type.  All
events come from events.json so they land exactly on the generated beat track.
"""
import colorsys
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter

W, H = 1920, 1080
FPS = 30
DUR = 24.0
NFRAMES = int(DUR * FPS)

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frames")
PREVIEW_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "previews")

F_LATO = "/usr/share/fonts/truetype/lato/Lato-Black.ttf"
F_MONO = "/usr/share/fonts/truetype/firacode/FiraCode-Bold.ttf"
F_CJK = "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc"

CYAN = (0, 225, 255)
BLUE = (45, 110, 255)
VIOLET = (150, 70, 255)
MAGENTA = (255, 40, 210)
PINK = (255, 50, 120)
GOLD = (255, 190, 70)
LIME = (140, 255, 90)
WHITE = (255, 255, 255)

CONFIG = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "events.json")))
LAUNCH1 = CONFIG["launch1"]
LAUNCH2 = CONFIG["launch2"]
IMPACT1 = CONFIG["impact1"]
IMPACT2 = CONFIG["impact2"]
BEAT = CONFIG["beat"]

NEAR = np.array([300.0, 900.0])
MUZ = np.array([1430.0, 520.0])
AXIS = MUZ - NEAR
AXIS_LEN = float(np.linalg.norm(AXIS))
U = AXIS / AXIS_LEN
V = np.array([-U[1], U[0]])


# ------------------------------------------------------------------ utils
def sc(c, f):
    f = max(0.0, min(1.0, f))
    return tuple(int(c[k] * f) for k in range(3))


def mix(c1, c2, f):
    return tuple(int(c1[k] + (c2[k] - c1[k]) * f) for k in range(3))


def rainbow(f):
    r, g, b = colorsys.hsv_to_rgb((f * 0.95 + 0.02) % 1.0, 0.92, 1.0)
    return (int(r * 255), int(g * 255), int(b * 255))


def axis_point(t):
    return NEAR + AXIS * t


def gap(t):
    return 158.0 * max(0.0, 1.0 - t) ** 1.25 + 56.0 * t


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_in(x):
    x = max(0.0, min(1.0, x))
    return x ** 2.2


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def pulse_at(t, beats, decay=16.0):
    """Distance to the nearest beat, used for hard on-beat flashes."""
    if not beats:
        return 0.0
    k = round(t / BEAT)
    dt = abs(t - k * BEAT)
    return math.exp(-dt * decay)


def shift_rgb(a, dx, dy):
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    if abs(dx) >= w or abs(dy) >= h:
        return out
    sx, ex = max(0, dx), min(w, w + dx)
    sy, ey = max(0, dy), min(h, h + dy)
    out[sy:ey, sx:ex] = a[sy - dy:ey - dy, sx - dx:ex - dx]
    return out


# ------------------------------------------------------------------ background
def build_background():
    rnd = np.random.default_rng(7)
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    top = np.array([4, 6, 17], np.float32)
    mid = np.array([18, 9, 34], np.float32)
    bot = np.array([3, 3, 8], np.float32)
    t1 = np.clip(yy * 1.7, 0, 1)
    t2 = np.clip((yy - 0.55) / 0.45, 0, 1)
    grad = (top * (1 - t1) + mid * t1) * (1 - t2) + bot * t2
    bg = np.repeat(grad[:, None, :], W, axis=1)

    for sigma, amp, tint in ((5.0, 60, np.array([70, 20, 95], np.float32)),
                             (11.0, 40, np.array([10, 45, 80], np.float32))):
        n = rnd.normal(size=(54, 96)).astype(np.float32)
        n = gaussian_filter(n, sigma)
        n = (n - n.min()) / (n.max() - n.min())
        n_img = np.asarray(Image.fromarray((n * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC),
                           np.float32) / 255.0
        bg += (n_img[..., None] ** 2.4) * tint * (amp / 100.0)

    img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    # star field
    for _ in range(760):
        x, y = int(rnd.uniform(0, W)), int(rnd.uniform(0, 760))
        b = rnd.uniform(40, 210)
        size = 1 if rnd.random() < 0.82 else 2
        d.point((x, y), fill=(int(b), int(b * 0.95), int(min(255, b * 1.1))))

    # giant orbital rings behind the cannon
    for rad, col, wid in ((430, (24, 70, 96), 2), (560, (46, 18, 62), 3), (700, (14, 42, 66), 1)):
        d.ellipse([1100 - rad, 430 - rad * 0.42, 1100 + rad, 430 + rad * 0.42], outline=col, width=wid)
    for a in range(0, 360, 6):
        ang = math.radians(a)
        r0, r1 = 410, 440
        x0, y0 = 1100 + r0 * math.cos(ang), 430 + r0 * 0.42 * math.sin(ang)
        x1, y1 = 1100 + r1 * math.cos(ang), 430 + r1 * 0.42 * math.sin(ang)
        if a % 12 == 0:
            d.line([x0, y0, x1, y1], fill=(20, 52, 70), width=1)

    # layered neon skyline (far -> near) with atmospheric haze
    def skyline(seed, y_base, hmin, hmax, wmin, wmax, fill, edge, win, dens, blur=0.0,
                sign_chance=0.0):
        lay = Image.new("RGB", (W, H), "black")
        dd = ImageDraw.Draw(lay)
        r2 = np.random.default_rng(seed)
        x = -50
        while x < W + 50:
            wd = int(r2.uniform(wmin, wmax))
            ht = int(r2.uniform(hmin, hmax))
            top = y_base - ht
            dd.rectangle([x, top, x + wd, y_base], fill=fill)
            dd.line([(x, top), (x + wd, top)], fill=edge, width=1)
            for _ in range(int(max(1, wd * ht * dens / 260))):
                wx = int(r2.uniform(x + 2, x + wd - 2))
                wy = int(r2.uniform(top + 4, y_base - 4))
                dd.point((wx, wy), fill=win)
            if r2.random() < sign_chance:
                sx = int(r2.uniform(x + 4, max(x + 5, x + wd - 20)))
                sh = int(r2.uniform(20, min(90, ht)))
                sy = int(r2.uniform(top + 6, max(top + 7, y_base - sh - 6)))
                col = (MAGENTA, CYAN, GOLD, LIME)[int(r2.integers(0, 4))]
                dd.rectangle([sx, sy, sx + 3, sy + sh], fill=sc(col, 0.32))
            x += wd + int(r2.uniform(3, 14))
        if blur:
            lay = lay.filter(ImageFilter.GaussianBlur(blur))
        return lay

    far = skyline(11, 862, 55, 190, 18, 54, (3, 4, 10), (10, 30, 46), (22, 58, 88), 1.4, 1.0, 0.1)
    mid = skyline(21, 928, 70, 260, 26, 78, (4, 5, 12), (16, 44, 62), (34, 96, 140), 0.9, 0.5, 0.25)
    img = Image.fromarray(np.clip(np.asarray(img, np.float32) + np.asarray(far, np.float32) * 0.95
                                  + np.asarray(mid, np.float32), 0, 255).astype(np.uint8))

    # haze band over the city
    yy2 = np.arange(H, dtype=np.float32)[:, None]
    haze = np.exp(-((yy2 - 900) / 85) ** 2)
    tint = np.array([26, 12, 44], np.float32)
    arr = np.asarray(img, np.float32)
    arr += haze[..., None] * tint
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    near = skyline(31, 1035, 70, 180, 40, 112, (2, 3, 7), (9, 24, 38), (16, 52, 84), 0.35, 0.0, 0.3)
    img = Image.fromarray(np.clip(np.asarray(img, np.float32) + np.asarray(near, np.float32), 0, 255).astype(np.uint8))

    # neon beacon beams
    d = ImageDraw.Draw(img)
    for bx, col, hh in ((250, CYAN, 300), (1210, MAGENTA, 380), (1720, GOLD, 260)):
        for k in range(8):
            a = 0.20 - k * 0.022
            d.line([(bx - k, 860 - hh), (bx + k, 860 - hh)], fill=sc(col, a), width=1)
        d.line([(bx, 860 - hh), (bx, 850)], fill=sc(col, 0.32), width=2)

    # wet-floor reflection
    refl = img.crop((0, 760, W, 1010)).transpose(Image.FLIP_TOP_BOTTOM)
    refl = refl.filter(ImageFilter.GaussianBlur(4))
    mask = Image.new("L", (W, 250), 0)
    md = ImageDraw.Draw(mask)
    for y in range(250):
        md.line([(0, y), (W, y)], fill=int(60 * (1 - y / 250) ** 1.7))
    img.paste(refl, (0, 878), mask)

    # perspective floor grid
    d = ImageDraw.Draw(img)
    for k in range(-12, 13):
        d.line([(960 + k * 55, 900), (960 + k * 240, 1080)], fill=(8, 26, 40), width=1)
    for y in (912, 930, 954, 986, 1026):
        d.line([(0, y), (W, y)], fill=(7, 20, 32), width=1)

    return np.asarray(img, np.float32) / 255.0


def build_vignette():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    r = np.sqrt(nx ** 2 * 0.82 + ny ** 2)
    v = np.clip(1 - 0.42 * np.clip(r - 0.45, 0, 2) ** 1.5, 0, 1)
    return v[..., None]


# ------------------------------------------------------------------ text helpers
_font_cache = {}


def font(path, size, index=0):
    key = (path, size, index)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(path, size, index=index)
    return _font_cache[key]


def text_spaced(d, xy, s, fnt, fill, spacing=0, anchor="la"):
    if spacing <= 0:
        d.text(xy, s, font=fnt, fill=fill, anchor=anchor)
        return
    widths = [d.textlength(ch, font=fnt) for ch in s]
    total = sum(widths) + spacing * (len(s) - 1)
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    for ch, wd in zip(s, widths):
        d.text((x, y), ch, font=fnt, fill=fill, anchor="l" + anchor[1])
        x += wd + spacing


def chroma_text(tx, xy, s, fnt, fill, spacing=0, anchor="mm", split=3):
    d = ImageDraw.Draw(tx)
    text_spaced(d, (xy[0] - split, xy[1]), s, fnt, sc(CYAN, 0.75), spacing, anchor)
    text_spaced(d, (xy[0] + split, xy[1] + 1), s, fnt, sc(MAGENTA, 0.75), spacing, anchor)
    text_spaced(d, xy, s, fnt, fill, spacing, anchor)


# ------------------------------------------------------------------ scene elements
def draw_rails(d, geo, cp, heat, rnd):
    off = geo["off"]
    fs = np.linspace(0.0, 1.0, 20)

    # solid silhouette so the cannon reads against the city
    up_s = [tuple(axis_point(f) - V * (gap(f) * 1.02 + 10) + off) for f in fs]
    lo_s = [tuple(axis_point(f) + V * (gap(f) * 1.02 + 10) + off) for f in fs][::-1]
    d.polygon(up_s + lo_s, fill=(4, 7, 14))

    # barrel body
    upper = [tuple(axis_point(f) - V * (gap(f) * 0.88) + off) for f in fs]
    lower = [tuple(axis_point(f) + V * (gap(f) * 0.88) + off) for f in fs][::-1]
    d.polygon(upper + lower, fill=(13, 21, 35))

    # lit top facet
    facet = upper + [tuple(axis_point(f) + off) for f in fs][::-1]
    d.polygon(facet, fill=(22, 33, 50))

    # energy channel between the rails
    up_in = [tuple(axis_point(f) - V * (gap(f) * 0.55) + off) for f in fs]
    lo_in = [tuple(axis_point(f) + V * (gap(f) * 0.55) + off) for f in fs][::-1]
    chan = sc(mix((30, 80, 120), CYAN, cp), 0.05 + 0.12 * cp + 0.10 * heat)
    d.polygon(up_in + lo_in, fill=chan)

    # panel seams across the barrel
    for f in np.arange(0.06, 0.96, 0.075):
        c = axis_point(f) + off
        d.line([tuple(c - V * (gap(f) * 0.88)), tuple(c + V * (gap(f) * 0.88))],
               fill=(6, 10, 18), width=4)
        d.line([tuple(c - V * (gap(f) * 0.88)), tuple(c - V * (gap(f) * 0.2))],
               fill=sc(CYAN, 0.10 + 0.18 * cp), width=1)

    # support fins under the barrel
    for f in (0.20, 0.38, 0.56):
        c = axis_point(f) + V * (gap(f) * 0.92) + off
        d.polygon([tuple(c), tuple(c + V * 90 + U * 40), tuple(c + V * 90 - U * 100)],
                  fill=(6, 10, 17))
        d.line([tuple(c), tuple(c + V * 90 + U * 40)], fill=sc(CYAN, 0.18 + 0.15 * cp), width=1)

    # rails: dark body + glowing inner edge
    for side in (-1, 1):
        a = axis_point(0.0) + V * (gap(0.0) * side) + off
        b = axis_point(1.0) + V * (gap(1.0) * side) + off
        tn, tf = 17.0, 8.0
        p_in_a = a - V * (tn * side)
        p_out_a = a + V * (tn * side)
        p_in_b = b - V * (tf * side)
        p_out_b = b + V * (tf * side)
        d.polygon([tuple(p_in_a), tuple(p_in_b), tuple(p_out_b), tuple(p_out_a)],
                  fill=(28, 42, 64))
        edge = mix((45, 100, 145), CYAN, cp)
        d.line([tuple(p_in_a), tuple(p_in_b)], fill=sc(edge, 0.30), width=12)
        d.line([tuple(p_in_a), tuple(p_in_b)], fill=sc(edge, 0.85 + 0.15 * cp), width=4)
        d.line([tuple(p_in_a), tuple(p_in_b)], fill=sc(WHITE, 0.35 + 0.5 * cp), width=1)
        d.line([tuple(p_out_a), tuple(p_out_b)], fill=sc(edge, 0.28), width=3)

    # muzzle block + prongs
    hw, depth = 150.0, 54.0
    c0 = MUZ - U * depth + off
    c1 = MUZ + U * depth + off
    d.polygon([tuple(c0 - V * hw), tuple(c1 - V * hw), tuple(c1 + V * hw), tuple(c0 + V * hw)],
              fill=(16, 24, 38))
    d.line([tuple(c0 - V * hw), tuple(c0 + V * hw)], fill=sc(CYAN, 0.45 + 0.4 * cp), width=3)
    d.line([tuple(c1 - V * hw), tuple(c1 + V * hw)], fill=(70, 92, 116), width=7)
    for side in (-1, 1):
        tip = c1 + V * (hw * side) + U * 78
        d.line([tuple(c1 + V * (hw * side)), tuple(tip)], fill=sc(CYAN, 0.5 + 0.3 * cp), width=6)
        d.line([tuple(c1 + V * (hw * side)), tuple(tip)], fill=sc(WHITE, 0.25 * cp), width=2)

    # heat spots at the rails near the armature
    for side in (-1, 1):
        p = axis_point(0.62) + V * (gap(0.62) * side) + off
        for r, a in ((34, 0.08), (20, 0.22), (10, 0.45)):
            d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r],
                      fill=sc(mix(GOLD, PINK, 0.5), a * (0.4 + heat)))



def draw_coils(d, geo, t, cp, heat, charge_start, rnd):
    off = geo["off"]
    for j, tj in enumerate((0.08, 0.18, 0.28, 0.38, 0.48, 0.58, 0.70, 0.82, 0.93)):
        c = axis_point(tj) + off
        R = gap(tj) + 26
        # sequential ignition
        t_on = charge_start + 0.34 * j
        lit = smooth((t - t_on) / 0.22) if cp > 0 else 0.0
        if heat > 0.02:
            lit = max(lit, heat * 0.9)
        col = mix(CYAN, GOLD, min(1.0, heat + lit * 0.4))
        pts = []
        for a in range(0, 361, 5):
            ang = math.radians(a)
            p = c + V * (R * math.cos(ang)) + U * (R * 0.20 * math.sin(ang))
            pts.append((p[0], p[1]))
        if lit > 0.02:
            d.line(pts, fill=sc(col, 0.22 * lit + 0.04), width=10)
            d.line(pts, fill=sc(col, 0.55 * lit + 0.06), width=4)
            d.line(pts, fill=sc(WHITE, 0.30 * lit), width=1)
        else:
            d.line(pts, fill=(16, 28, 44), width=2)
        # coil ribs
        for s in (-1, 1):
            c2 = c + V * (R * 0.55 * s)
            d.line([tuple(c2 - U * 9), tuple(c2 + U * 9)], fill=sc(col, 0.25 + 0.4 * lit), width=2)


def draw_core(d, geo, t, cp, heat, rnd):
    c = axis_point(0.62) + geo["off"]
    pr = 1.0 + 0.10 * math.sin(t * 18)
    if t < 6:
        r = (30 + 66 * cp) * pr
    elif t < 12:
        r = 30 + 70 * math.exp(-(t - 6) * 4.5)
    elif t < 16:
        r = (30 + 66 * (t - 12) / 4) * pr
    else:
        r = 34 + 70 * math.exp(-(t - 16) * 4.0)
    r += 20 * heat
    # halo
    for k in range(10, 0, -1):
        rr = r * (0.5 + k * 0.12)
        a = (0.16 + 0.10 * cp) * (1 - k / 11) * (1 + heat)
        d.ellipse([c[0] - rr, c[1] - rr, c[0] + rr, c[1] + rr],
                  fill=sc(mix(VIOLET, CYAN, 0.5), a))
    # hot center
    d.ellipse([c[0] - r * 0.55, c[1] - r * 0.55, c[0] + r * 0.55, c[1] + r * 0.55], fill=sc((220, 245, 255), 0.45 + 0.4 * cp))
    d.ellipse([c[0] - r * 0.3, c[1] - r * 0.3, c[0] + r * 0.3, c[1] + r * 0.3], fill=sc(WHITE, 0.8 + 0.2 * heat))
    # orbiting sparks
    for k in range(44):
        ang = k * 2.399 + t * 4.2
        rr = r * (1.25 + 0.35 * math.sin(t * 5 + k))
        p = c + V * (rr * math.cos(ang)) + U * (rr * 0.4 * math.sin(ang))
        d.ellipse([p[0] - 2, p[1] - 2, p[0] + 2, p[1] + 2],
                  fill=sc(mix(CYAN, VIOLET, (k % 5) / 4.0), 0.5 + 0.4 * cp))
    return c, r


def bolt(d, p0, p1, width, col, rnd, disp=52, depth=5):
    pts = [np.array(p0, float), np.array(p1, float)]
    for _ in range(depth):
        nxt = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            mid = (a + b) / 2.0
            perp = np.array([-(b - a)[1], (b - a)[0]])
            n = np.linalg.norm(perp) + 1e-6
            mid = mid + perp / n * rnd.normal(0, disp)
            nxt += [mid, b]
        pts = nxt
        disp *= 0.62
    xy = [(p[0], p[1]) for p in pts]
    d.line(xy, fill=sc(col, 0.35), width=width * 3, joint="curve")
    d.line(xy, fill=sc(col, 0.85), width=width, joint="curve")


def draw_arcs(d, geo, t, cp, heat, rnd):
    off = geo["off"]
    n = int(2 + 10 * cp + 6 * heat)
    for _ in range(n):
        tj = rnd.uniform(0.10, 0.95)
        p0 = axis_point(tj) - V * gap(tj) + off
        p1 = axis_point(tj + rnd.uniform(-0.025, 0.025)) + V * gap(tj) + off
        col = CYAN if rnd.random() < 0.55 else (MAGENTA if rnd.random() < 0.7 else WHITE)
        bolt(d, p0, p1, int(rnd.uniform(2, 4)), col, rnd, disp=gap(tj) * 0.30, depth=4)

    # arcs spitting off the energy core
    c = axis_point(0.62) + off
    r = 46 + 94 * cp
    for _ in range(int(1 + 6 * heat)):
        ang = rnd.uniform(0, 6.283)
        tgt = c + (V * math.cos(ang) + U * 0.3 * math.sin(ang)) * r * 1.7
        bolt(d, c, tgt, 3, mix(GOLD, WHITE, rnd.random()), rnd, disp=20, depth=3)


def draw_projectile(sp, t, launch, rnd, power=1.0):
    ts = t - launch
    if not (0 <= ts < 1.2):
        return 0.0
    p = MUZ + U * (3000 * ts)
    trail = min(1250, 3000 * ts) * (1 + 0.4 * power)
    segs = 70
    d = ImageDraw.Draw(sp)
    # soft chromatic glow behind the trail
    for k, col in enumerate((CYAN, MAGENTA)):
        d.line([tuple(p - U * trail), tuple(p)], fill=sc(col, 0.22 * power), width=int(26 + 10 * power))
    for k in range(segs):
        a = p - U * trail * (k / segs)
        b = p - U * trail * ((k + 1) / segs)
        f = k / segs
        col = rainbow(f * 0.75 + 0.05)
        thick = int(3 + 15 * (1 - f) * power)
        d.line([tuple(a), tuple(b)], fill=sc(col, 0.95 * (1 - f) ** 0.5), width=thick)
        d.line([tuple(a), tuple(b)], fill=sc(WHITE, 0.6 * (1 - f) ** 2), width=max(1, thick // 3))
    d = ImageDraw.Draw(sp)
    d.ellipse([p[0] - 30, p[1] - 30, p[0] + 30, p[1] + 30], fill=sc(CYAN, 0.16 * power))
    d.ellipse([p[0] - 20, p[1] - 20, p[0] + 20, p[1] + 20], fill=sc(MAGENTA, 0.45 * power))
    d.ellipse([p[0] - 9, p[1] - 9, p[0] + 9, p[1] + 9], fill=WHITE)
    return 1.0


def draw_burst(sp, center, ts, n, seed, power=1.0, hue=0.0):
    if ts < 0 or ts > 2.2:
        return
    rnd = np.random.default_rng(seed)
    d = ImageDraw.Draw(sp)
    for i in range(n):
        ang = rnd.uniform(0, 6.283)
        speed = rnd.uniform(180, 2100) * power
        life = math.exp(-ts * 1.9)
        if life < 0.03:
            continue
        pos = center + np.array([math.cos(ang), math.sin(ang)]) * speed * ts
        if not (-200 < pos[0] < W + 200 and -200 < pos[1] < H + 200):
            continue
        col = WHITE if i % 5 < 3 else (GOLD if i % 5 == 3 else CYAN)
        if i % 7 == 0:
            col = MAGENTA
        r = rnd.uniform(1.2, 3.2) * power
        tail = pos - np.array([math.cos(ang), math.sin(ang)]) * speed * 0.035 * (0.4 + life)
        d.line([tuple(tail), tuple(pos)], fill=sc(col, life), width=max(1, int(r * 1.7)))
        d.ellipse([pos[0] - r, pos[1] - r, pos[0] + r, pos[1] + r], fill=sc(col, life))


def draw_shockwave(em, center, ts, color, power=1.0, delay=0.0):
    ts2 = ts - delay
    if ts2 < 0 or ts2 > 0.9:
        return
    r = (80 + 1500 * ease_out(ts2 / 0.9)) * power
    a = (1 - ts2 / 0.9) ** 1.4
    d = ImageDraw.Draw(em)
    for k, col in enumerate((color, WHITE, color)):
        rr = r * (1 - k * 0.10)
        wd = max(1, int((10 - k * 3) * a * power))
        d.ellipse([center[0] - rr, center[1] - rr * 0.72,
                   center[0] + rr, center[1] + rr * 0.72],
                  outline=sc(col, 0.55 * a), width=wd)


def add_radial(img, center, radius, c_in, c_out, gain, power=2.0, n=192):
    """Add a smooth radial glow sprite at full-res, without a hard disc edge."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    r = np.sqrt((xx - (n - 1) / 2) ** 2 + (yy - (n - 1) / 2) ** 2) / ((n - 1) / 2)
    r = np.clip(r, 0, 1)
    inten = ((1 - r) ** power * gain)[..., None]
    c1 = np.array(c_in, np.float32)
    c2 = np.array(c_out, np.float32)
    col = c1[None, None, :] * (1 - r[..., None]) + c2[None, None, :] * r[..., None]
    rgb = np.clip(col * inten, 0, 255).astype(np.uint8)
    size = max(8, int(radius * 2))
    sprite = Image.fromarray(rgb).resize((size, size), Image.BILINEAR)
    x, y = int(center[0] - size / 2), int(center[1] - size / 2)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + size), min(H, y + size)
    if x1 <= x0 or y1 <= y0:
        return
    sub = img.crop((x0, y0, x1, y1))
    sub = ImageChops.add(sub, sprite.crop((x0 - x, y0 - y, x1 - x, y1 - y)))
    img.paste(sub, (x0, y0))


def draw_explosion(em, center, ts, power=1.0):
    if ts < 0 or ts > 2.4:
        return
    rnd = np.random.default_rng(int(center[0] * 7 + center[1]))
    a = math.exp(-ts * 1.35)
    R = (60 + 360 * ease_out(ts / 0.55)) * power
    add_radial(em, center, R, GOLD, PINK, 0.62 * a, power=1.7)
    add_radial(em, center, R * 0.45, WHITE, GOLD, 0.80 * a, power=2.4)
    d = ImageDraw.Draw(em)
    # debris streaks
    for _ in range(70):
        ang = rnd.uniform(0, 6.283)
        rr0 = R * rnd.uniform(0.35, 0.9)
        rr1 = rr0 + rnd.uniform(30, 170) * a
        x0, y0 = center[0] + math.cos(ang) * rr0, center[1] + math.sin(ang) * rr0
        x1, y1 = center[0] + math.cos(ang) * rr1, center[1] + math.sin(ang) * rr1
        col = (GOLD, PINK, CYAN, LIME)[int(rnd.integers(0, 4))]
        d.line([(x0, y0), (x1, y1)], fill=sc(col, a * 0.75), width=int(rnd.uniform(1, 4)))
    draw_shockwave(em, center, ts, GOLD, 0.9 * power, 0.02)
    draw_shockwave(em, center, ts, PINK, 0.7 * power, 0.10)


def draw_muzzle_flash(sp, center, ts, power=1.0):
    if ts < 0 or ts > 0.55:
        return
    a = math.exp(-ts * 12.0)
    R = (100 + 380 * ease_out(ts / 0.55)) * power
    add_radial(sp, center, R, WHITE, MAGENTA, 0.58 * a, power=1.7)
    add_radial(sp, center, R * 0.42, WHITE, GOLD, 0.85 * a, power=2.2)
    d = ImageDraw.Draw(sp)
    for ang in range(0, 360, 30):
        rad = math.radians(ang)
        ln = R * (1.0 if ang % 60 == 0 else 0.7)
        d.line([tuple(center), (center[0] + math.cos(rad) * ln, center[1] + math.sin(rad) * ln)],
               fill=sc(mix(WHITE, CYAN, 0.35), 0.18 * a), width=4)
    d.ellipse([center[0] - 30, center[1] - 30, center[0] + 30, center[1] + 30], fill=sc(WHITE, a))


def draw_target(em, t, cp):
    tgt = np.array([1775.0, 300.0])
    d = ImageDraw.Draw(em)
    a = 0.16 + 0.40 * cp
    charging = (0.5 < t < 6.2) or (12.0 < t < 16.2)
    if charging and cp > 0.05:
        d.line([tuple(MUZ), tuple(tgt)], fill=sc(MAGENTA, 0.10 + 0.30 * cp), width=1)
    r = 52
    for ang0 in (0, 90, 180, 270):
        d.arc([tgt[0] - r, tgt[1] - r, tgt[0] + r, tgt[1] + r], ang0 + 16, ang0 + 74,
              fill=sc(CYAN, a), width=2)
    d.ellipse([tgt[0] - 5, tgt[1] - 5, tgt[0] + 5, tgt[1] + 5], fill=sc(MAGENTA, 0.5 + 0.4 * cp))
    d.line([(tgt[0] - 70, tgt[1]), (tgt[0] - 58, tgt[1])], fill=sc(CYAN, a), width=1)
    d.line([(tgt[0] + 58, tgt[1]), (tgt[0] + 70, tgt[1])], fill=sc(CYAN, a), width=1)
    d.text((tgt[0] + 68, tgt[1] - 26), "TGT-014", font=font(F_MONO, 18),
           fill=sc(CYAN, 0.55 + 0.35 * cp))



# ------------------------------------------------------------------ HUD / type
def draw_hud(tx, t, cp, heat, status):
    d = ImageDraw.Draw(tx)
    fm = font(F_MONO, 26)
    fs = font(F_MONO, 20)
    dim = sc((120, 225, 245), 0.85 + 0.15 * heat)
    bright = sc((200, 255, 255), 0.9)

    # corner brackets
    L, m = 46, 44
    for cx, cy, sx, sy in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
        d.line([(cx, cy), (cx + sx * L, cy)], fill=dim, width=2)
        d.line([(cx, cy), (cx, cy + sy * L)], fill=dim, width=2)
        d.line([(cx + sx * 4, cy + sy * 4), (cx + sx * 22, cy + sy * 4)], fill=bright, width=1)
        d.line([(cx + sx * 4, cy + sy * 4), (cx + sx * 4, cy + sy * 22)], fill=bright, width=1)

    d.text((96, 84), "RAILGUN // MK-IV", font=fm, fill=bright)
    d.text((96, 118), "ELECTROMAGNETIC LAUNCH SYSTEM", font=fs, fill=dim)
    d.text((96, 176), "CHARGE", font=fs, fill=dim)
    pct = int(round(cp * 100))
    d.text((96, 204), f"{pct:03d}%", font=font(F_LATO, 62), fill=sc(GOLD if heat > 0.4 or cp > 0.95 else CYAN, 0.95))

    # charge bar
    bx, by, bw, bh = 96, 286, 430, 18
    d.rectangle([bx, by, bx + bw, by + bh], outline=sc(CYAN, 0.55), width=2)
    fillw = int(bw * cp)
    if fillw > 8:
        d.rectangle([bx + 2, by + 2, bx + fillw - 2, by + bh - 2],
                    fill=sc(mix(CYAN, GOLD, min(1, heat + cp * 0.3)), 0.8))
    for k in range(21):
        x = bx + bw * k / 20
        d.line([(x, by - 8), (x, by - 2)], fill=sc(CYAN, 0.4), width=1)

    # right side telemetry
    d.text((W - 96, 84), "TARGET LOCK", font=fm, fill=bright, anchor="ra")
    d.text((W - 96, 118), "RANGE 12.4 KM / AZ 014", font=fs, fill=dim, anchor="ra")
    d.text((W - 96, 176), "COIL TEMP", font=fs, fill=dim, anchor="ra")
    temp = 2880 + int(cp * 2600) + int(heat * 900)
    d.text((W - 96, 204), f"{temp} K", font=font(F_LATO, 44), fill=sc(PINK if heat > 0.3 else CYAN, 0.95), anchor="ra")

    # bottom status
    d.text((96, H - 96), "CAPACITOR BANK", font=fs, fill=dim)
    segs = 28
    for k in range(segs):
        on = k / segs < cp
        x = 96 + k * 17
        d.rectangle([x, H - 62, x + 12, H - 40],
                    fill=sc(GOLD if heat > 0.35 else CYAN, 0.85) if on else (10, 30, 44))

    d.text((W - 96, H - 96), "SYNC 120 BPM", font=fs, fill=dim, anchor="ra")
    d.text((W - 96, H - 62), status, font=fm, fill=sc(PINK if "OVER" in status else bright, 1.0), anchor="ra")

    # target reticle at muzzle
    mx, my = MUZ
    if status.startswith("FIRING") or heat > 0.5:
        for r, wd, cc in ((46, 2, CYAN), (64, 1, MAGENTA)):
            d.ellipse([mx - r, my - r, mx + r, my + r], outline=sc(cc, 0.7), width=wd)
        d.line([(mx - 86, my), (mx - 56, my)], fill=bright, width=2)
        d.line([(mx + 56, my), (mx + 86, my)], fill=bright, width=2)
        d.line([(mx, my - 86), (mx, my - 56)], fill=bright, width=2)
        d.line([(mx, my + 56), (mx, my + 86)], fill=bright, width=2)


def draw_center_title(tx, t):
    f_big = font(F_LATO, 208)
    f_sub = font(F_MONO, 30)
    # title in during 0.45 - 3.9
    if 0.45 <= t < 4.1:
        a = smooth(min(1, (t - 0.45) / 0.45))
        if t > 3.4:
            a *= max(0, 1 - (t - 3.4) / 0.7)
        if a > 0.01:
            jitter = 5 if (int(t * 30) % 7 == 0) else 0
            chroma_text(tx, (960 + jitter, 430), "RAILGUN", f_big, sc(WHITE, 0.55 + 0.45 * a),
                        spacing=8, split=4 + jitter)
            d = ImageDraw.Draw(tx)
            d.text((960, 545), "ELECTROMAGNETIC OVERDRIVE", font=f_sub,
                   fill=sc(CYAN, 0.8 * a), anchor="mm")
            d.line([(760, 512), (1160, 512)], fill=sc(CYAN, 0.5 * a), width=2)

    # overcharge warning 4.1 - 6.0
    if 4.1 <= t < 6.0:
        beat = pulse_at(t, CONFIG["beats"], 20)
        a = smooth((t - 4.1) / 0.3)
        f = font(F_LATO, 118)
        chroma_text(tx, (960, 300), "OVERCHARGE", f, sc(GOLD, 0.7 + 0.3 * beat), spacing=4,
                    split=3 + int(beat * 6))
        d = ImageDraw.Draw(tx)
        d.text((960, 390), "COIL LIMIT EXCEEDED", font=font(F_MONO, 26), fill=sc(PINK, 0.85 * a), anchor="mm")

    # launch 1
    if 6.0 <= t < 7.2:
        ts = t - 6.0
        a = max(0.0, 1 - ts / 0.9)
        s = "FIRE" if ts < 0.35 else "FIRED"
        chroma_text(tx, (960, 300), s, font(F_LATO, 168), sc(WHITE, 0.95 * a), spacing=10,
                    split=8 + int(ts * 10))
    # re-arm
    if 12.0 <= t < 15.9:
        a = smooth((t - 12.0) / 0.4)
        chroma_text(tx, (960, 330), "RE-ARM", font(F_LATO, 128), sc(CYAN, 0.85 * a), spacing=8,
                    split=3)
        d = ImageDraw.Draw(tx)
        d.text((960, 420), "CAPACITORS DRAINING // CHARGE CYCLE 02", font=font(F_MONO, 24),
               fill=sc(VIOLET, 0.9 * a), anchor="mm")

    # launch 2 / overdrive
    if 16.0 <= t < 17.6:
        ts = t - 16.0
        a = max(0.0, 1 - ts / 1.1)
        chroma_text(tx, (960, 300), "OVERDRIVE", font(F_LATO, 162), sc(WHITE, 0.95 * a), spacing=6,
                    split=9 + int(ts * 12))

    # impact
    if 17.9 <= t < 20.0:
        ts = t - 17.9
        a = smooth(ts / 0.25) * max(0.0, 1 - (ts - 0.9) / 1.0)
        if a > 0:
            chroma_text(tx, (960, 340), "IMPACT", font(F_LATO, 150), sc(GOLD, 0.95 * a), spacing=12,
                        split=7)

    # end card 22.0 - 24.0
    if t >= 22.0:
        a = smooth(min(1, (t - 22.0) / 0.5))
        fade = max(0.0, min(1, (DUR - t) / 0.55))
        aa = a * fade
        if aa > 0.01:
            d = ImageDraw.Draw(tx)
            d.line([(600, 392), (1320, 392)], fill=sc(CYAN, 0.55 * aa), width=2)
            chroma_text(tx, (960, 470), "RAILGUN", font(F_LATO, 168), sc(WHITE, 0.95 * aa), spacing=8, split=5)
            d.text((960, 566), "OVERDRIVE", font=font(F_LATO, 58), fill=sc(GOLD, 0.95 * aa), anchor="mm")
            d.text((960, 636), "电磁炮 · 过载", font=font(F_CJK, 34), fill=sc(CYAN, 0.85 * aa), anchor="mm")
            d.text((960, 700), "CODE-GENERATED MV  /  120 BPM  /  1920x1080",
                   font=font(F_MONO, 22), fill=sc((150, 210, 230), 0.8 * aa), anchor="mm")
            d.line([(600, 742), (1320, 742)], fill=sc(MAGENTA, 0.45 * aa), width=2)


# ------------------------------------------------------------------ main frame
BASE = None
VIGN = None


def render_frame(i):
    t = i / FPS
    rnd = np.random.default_rng(1000 + i * 7919)

    heat = 0.0
    if LAUNCH1 - 0.05 <= t < LAUNCH1:
        heat = math.exp(-(LAUNCH1 - t) * 5.0)
    if LAUNCH1 <= t < LAUNCH1 + 2.0:
        heat = max(heat, 0.90 * math.exp(-(t - LAUNCH1) * 1.7))
    if LAUNCH2 - 0.05 <= t < LAUNCH2:
        heat = math.exp(-(LAUNCH2 - t) * 4.2)
    if LAUNCH2 <= t < LAUNCH2 + 2.4:
        heat = max(heat, 0.95 * math.exp(-(t - LAUNCH2) * 1.5))
    heat = max(heat, 0.12 * pulse_at(t, CONFIG["beats"], 12.0))

    if t < 4.0:
        cp = smooth(t / 4.0)
        charge_start = 0.0
    elif t < 6.0:
        cp = 1.0
        charge_start = 0.0
    elif t < 12.0:
        cp = 0.9 * math.exp(-(t - 6.0) * 8.0)
        charge_start = 0.0
    elif t < 16.0:
        cp = smooth((t - 12.0) / 4.0)
        charge_start = 12.0
    elif t < 22.0:
        cp = 0.95 * math.exp(-(t - 16.0) * 8.0)
        charge_start = 12.0
    else:
        cp = 0.0
        charge_start = 12.0

    recoil = 0.0
    for launch, amp, freq in ((LAUNCH1, 34.0, 30.0), (LAUNCH2, 52.0, 26.0)):
        ts = t - launch
        if 0 <= ts < 0.6:
            recoil += amp * math.exp(-ts * 9.0) * math.cos(ts * freq)
    geo = {"off": -U * recoil}

    em = Image.new("RGB", (W, H), "black")
    sp = Image.new("RGB", (W, H), "black")
    tx = Image.new("RGB", (W, H), "black")

    # ---------------- backdrop energy (adds life to the static plate)
    de = ImageDraw.Draw(em)
    for k in range(5):
        rr = 220 + 150 * k + 40 * math.sin(t * 0.5 + k)
        a = 0.045 + 0.03 * pulse_at(t, CONFIG["beats"], 10.0) * cp
        de.ellipse([1080 - rr, 455 - rr * 0.44, 1080 + rr, 455 + rr * 0.44],
                   outline=sc(mix(CYAN, MAGENTA, k / 5), a), width=2)

    # horizon pulse from the music
    bp = pulse_at(t, CONFIG["beats"], 14.0) if (6 <= t < 12 or 16 <= t < 22) else 0.0
    if bp > 0.05:
        de.ellipse([960 - 900, 900 - 90, 960 + 900, 900 + 90],
                   fill=sc((0, 90, 140), 0.10 * bp))

    # ---------------- cannon
    draw_rails(de, geo, cp, heat, rnd)
    draw_coils(de, geo, t, cp, heat, charge_start, rnd)
    if t < 21.9:
        core, core_r = draw_core(de, geo, t, cp, heat, rnd)
        draw_arcs(de, geo, t, cp, heat, rnd)
    else:
        core = axis_point(0.62) + geo["off"]
    draw_target(em, t, cp)

    # core -> muzzle energy link just before launch
    for launch in (LAUNCH1, LAUNCH2):
        ts = launch - t
        if 0 < ts < 0.7:
            f = 1 - ts / 0.7
            bolt(de, core, MUZ, 6, mix(WHITE, CYAN, 0.3), np.random.default_rng(i + 51),
                 disp=30 * (1 - f) + 4, depth=4)
            de.line([tuple(core), tuple(MUZ)], fill=sc(CYAN, 0.35 * f), width=int(4 + 16 * f))

    # ---------------- particles
    if cp > 0.05 and t < 16.5:
        for k in range(260):
            ang = k * 2.399 + t * (5.0 if k % 2 else -4.2)
            rr = (30 + 260 * (1 - cp)) * (0.35 + 0.65 * ((k * 0.618) % 1.0))
            p = core + V * (rr * math.cos(ang)) + U * (rr * 0.35 * math.sin(ang))
            fade = 0.35 + 0.65 * ((k * 0.37) % 1.0)
            col = (CYAN, WHITE, VIOLET, MAGENTA)[k % 4]
            r = 1 + (k % 3)
            ImageDraw.Draw(sp).ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r],
                                       fill=sc(col, fade * (0.35 + 0.5 * cp)))

    # launch 1
    ts1 = t - LAUNCH1
    if 0 <= ts1 < 1.4:
        draw_shockwave(em, MUZ, ts1, CYAN, 1.0, 0.0)
        draw_shockwave(em, MUZ, ts1, MAGENTA, 0.9, 0.07)
        draw_shockwave(em, MUZ, ts1, GOLD, 0.7, 0.14)
        draw_burst(sp, MUZ, ts1, 260, i + 300, 1.0, 0.02)
        draw_muzzle_flash(sp, MUZ, ts1, 1.0)
        draw_projectile(sp, t, LAUNCH1, rnd, 1.0)
    if ts1 > 0:
        draw_explosion(em, np.array([1760.0, 330.0]), ts1 - 1.9, 1.0)

    # launch 2 — triple
    ts2 = t - LAUNCH2
    if 0 <= ts2 < 1.8:
        draw_shockwave(em, MUZ, ts2, GOLD, 1.15, 0.0)
        draw_shockwave(em, MUZ, ts2, MAGENTA, 1.05, 0.06)
        draw_shockwave(em, MUZ, ts2, LIME, 0.9, 0.12)
        draw_shockwave(em, MUZ, ts2, CYAN, 0.8, 0.18)
        draw_burst(sp, MUZ, ts2, 380, i + 700, 1.15, 0.0)
        draw_muzzle_flash(sp, MUZ, ts2, 1.2)
        draw_projectile(sp, t, LAUNCH2, rnd, 1.15)
        # three rail beams
        for k, col in enumerate((CYAN, MAGENTA, GOLD)):
            p = MUZ + U * (2400 * ts2) + V * (-160 + k * 160)
            ImageDraw.Draw(sp).line([tuple(MUZ + V * (-160 + k * 160)), tuple(p)],
                                    fill=sc(col, max(0, 0.7 - ts2 * 0.9)), width=6)
    if ts2 > 0:
        draw_explosion(em, np.array([1800.0, 400.0]), ts2 - 1.8, 1.0)
        draw_explosion(em, np.array([1520.0, 560.0]), ts2 - 3.0, 0.8)
        draw_explosion(em, np.array([1860.0, 690.0]), ts2 - 4.5, 0.7)

    # beat sparks in the drops
    if 6 <= t < 12.0 or 16 <= t < 22.0:
        k = int(round(t / BEAT))
        bt = k * BEAT
        dt = t - bt
        if 0 <= dt < 0.35:
            draw_shockwave(em, core, dt, CYAN, 0.25, 0.0)
            draw_burst(sp, core, dt, 40, i + k, 0.35, hue=k / 12.0)

    # floating embers after the climax
    if 18.0 < t < 23.0:
        for k in range(160):
            x = ((k * 137.5 + t * (18 + (k % 7) * 6)) % W)
            y = (H - ((k * 61.0 + t * 40) % (H + 100)))
            a = 0.25 + 0.55 * ((k * 0.31) % 1.0)
            ImageDraw.Draw(sp).ellipse([x - 1, y - 1, x + 1, y + 1],
                                       fill=sc((GOLD, PINK, CYAN)[k % 3], a))

    # ---------------- HUD + typography
    if t > 0.6 and t < 21.9:
        status = "STANDBY"
        if 0 < t < 4.0:
            status = "CHARGING"
        elif 4.0 <= t < 6.0:
            status = "OVERCHARGE" if int(t * 8) % 2 == 0 else "OVERCHARGE!"
        elif 6.0 <= t < 7.0:
            status = "FIRING"
        elif 12.0 <= t < 16.0:
            status = "RE-ARMING"
        elif 16.0 <= t < 17.3:
            status = "OVERDRIVE"
        elif t >= 17.9:
            status = "IMPACT CONFIRMED"
        draw_hud(tx, t, cp if t < 22 else 0.0, heat, status)
    draw_center_title(tx, t)

    # ---------------- compositing
    em_a = np.asarray(em, np.float32) / 255.0
    sp_a = np.asarray(sp, np.float32) / 255.0
    tx_a = np.asarray(tx, np.float32) / 255.0

    base = BASE * (1.0 + 0.10 * bp + 0.05 * heat)

    # bloom pyramid
    small = np.asarray(Image.fromarray(np.clip((em_a + sp_a) * 255, 0, 255).astype(np.uint8))
                       .resize((480, 270), Image.BILINEAR), np.float32) / 255.0
    bright = np.clip((small - 0.18) / 0.82, 0, 1)
    b_tight = gaussian_filter(bright, sigma=(2.5, 2.5, 0))
    b_wide = gaussian_filter(bright, sigma=(9, 9, 0))
    streak = gaussian_filter(bright, sigma=(1.5, 26, 0))
    up = lambda a: np.asarray(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
                              .resize((W, H), Image.BICUBIC), np.float32) / 255.0
    bloom = up(b_tight) * 0.65 + up(b_wide) * 1.25 + up(streak) * 1.35

    # muzzle flash light (short, so the frame is not washed out)
    flash = 0.0
    for launch, amp in ((LAUNCH1, 1.15), (LAUNCH2, 1.45)):
        ts = t - launch
        if 0 <= ts < 0.20:
            flash += amp * math.exp(-ts * 26.0)

    img = base + em_a * 1.15 + sp_a * 1.35 + bloom + tx_a * 1.0
    # glow for typography
    glow_tx = np.asarray(tx.filter(ImageFilter.GaussianBlur(14)), np.float32) / 255.0
    img += glow_tx * 0.95
    img += flash

    # tone map + grade
    img = 1.0 - np.exp(-img * 1.28)
    img = np.clip(img, 0, 1)
    # saturation boost
    lum = img.mean(axis=2, keepdims=True)
    img = np.clip(lum + (img - lum) * 1.30, 0, 1)

    # chromatic aberration: subtle overall, strong only on impact frames
    ca = int(1 + 3.5 * heat)
    if 0 <= ts1 < 0.18:
        ca = int(9 * math.exp(-ts1 * 16))
    if 0 <= ts2 < 0.22:
        ca = int(11 * math.exp(-ts2 * 14))
    if ca > 1:
        r = shift_rgb(img[..., 0:1], ca, 0)
        b = shift_rgb(img[..., 2:3], -ca, 0)
        img = np.concatenate([r, img[..., 1:2], b], axis=2)

    # scanlines
    img *= (1.0 - 0.055 * (np.arange(H) % 2 == 0))[:, None, None]
    img *= VIGN

    # camera shake
    shake = 0.0
    for launch, amp in ((LAUNCH1, 26.0), (LAUNCH2, 38.0)):
        ts = t - launch
        if 0 <= ts < 0.8:
            shake += amp * math.exp(-ts * 11.0)
    if 16 <= t < 22:
        shake += 4.0 * pulse_at(t, CONFIG["beats"], 18.0)
    if shake > 0.5:
        dx = int(rnd.normal(0, shake))
        dy = int(rnd.normal(0, shake * 0.7))
        img = shift_rgb(img, dx, dy)

    # glitch slices around the two launches and the build
    g = 0.0
    if 4.6 <= t < 6.0:
        g = 0.25 + 0.5 * pulse_at(t, CONFIG["beats"], 18.0)
    if 0 <= ts1 < 0.35:
        g = 1.2 * math.exp(-ts1 * 9)
    if 0 <= ts2 < 0.4:
        g = 1.4 * math.exp(-ts2 * 8)
    if g > 0.02:
        rnd2 = np.random.default_rng(i * 17 + 3)
        for _ in range(int(4 + 9 * g)):
            y0 = int(rnd2.integers(0, H - 50))
            hh = int(rnd2.integers(3, 46))
            dx = int(rnd2.normal(0, 55 * g))
            img[y0:y0 + hh] = np.roll(img[y0:y0 + hh], dx, axis=1)

    # grain
    img += rnd.normal(0, 0.012, (H, W, 1)).astype(np.float32)

    return np.clip(img * 255, 0, 255).astype(np.uint8)


def render_one(i):
    arr = render_frame(i)
    Image.fromarray(arr).save(os.path.join(OUT_DIR, f"f_{i:04d}.jpg"), quality=94, subsampling=1)
    return i


def _init():
    global BASE, VIGN
    BASE = build_background()
    VIGN = build_vignette()


if __name__ == "__main__":
    import argparse
    from multiprocessing import Pool

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="sample", choices=["sample", "all"])
    ap.add_argument("--times", default="0.5,2.0,3.5,5.0,5.85,6.03,6.15,6.35,6.7,8.2,10.0,13.5,15.8,16.03,16.2,16.5,18.0,20.0,23.0")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=NFRAMES)
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    _init()

    if args.mode == "sample":
        times = [float(x) for x in args.times.split(",")]
        for tt in times:
            i = min(NFRAMES - 1, int(round(tt * FPS)))
            arr = render_frame(i)
            Image.fromarray(arr).save(os.path.join(PREVIEW_DIR, f"t{tt:05.2f}_f{i:04d}.png"))
            print("sample", tt, i, flush=True)
    else:
        with Pool(args.workers, initializer=_init) as pool:
            done = 0
            for i in pool.imap_unordered(render_one, range(args.start, args.end), chunksize=4):
                done += 1
                if done % 60 == 0:
                    print(f"rendered {done}/{args.end - args.start}", flush=True)
        print("done", flush=True)
