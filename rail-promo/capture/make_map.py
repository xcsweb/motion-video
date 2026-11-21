#!/usr/bin/env python3
"""Animated 2D metro map from guidao network data."""
import json
import math
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

NET = "/workspace/guidao/public/data/cq/network.json"
FONT_B = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf"
FONT_R = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf"
OUT = "/workspace/rail-promo/out/map"

W, H = 1920, 765
VIEW = (130, 18, 1790, 688)  # x0, y0, x1, y1


def font(p, s):
    return ImageFont.truetype(p, s)


def tracked(d, xy, text, fnt, fill, tr=0, center=False):
    x, y = xy
    ws = [d.textlength(c, font=fnt) for c in text]
    total = sum(ws) + tr * max(0, len(text) - 1)
    if center:
        x -= total / 2
    for c, w in zip(text, ws):
        d.text((x, y), c, font=fnt, fill=fill)
        x += w + tr
    return total


def load():
    d = json.load(open(NET))
    lines = [l for l in d["lines"] if len(l["path"]) >= 4]
    # fit to station distribution
    xs = sorted(s["x"] for s in d["stations"])
    zs = sorted(s["z"] for s in d["stations"])
    lo = int(len(xs) * 0.01)
    hi = int(len(xs) * 0.99)
    x0, x1 = xs[lo], xs[hi]
    z0, z1 = zs[lo], zs[hi]
    return d, lines, (x0, z0, x1, z1)


def make_proj(bounds, zoom=1.0, dx=0.0, dy=0.0):
    x0, z0, x1, z1 = bounds
    vx0, vy0, vx1, vy1 = VIEW
    bw, bh = x1 - x0, z1 - z0
    scale = min((vx1 - vx0) / bw, (vy1 - vy0) / bh) * zoom
    cx, cy = (vx0 + vx1) / 2 + dx * (vx1 - vx0), (vy0 + vy1) / 2 + dy * (vy1 - vy0)
    mx, mz = (x0 + x1) / 2, (z0 + z1) / 2

    def p(x, z):
        return (cx + (x - mx) * scale, cy - (z - mz) * scale)

    return p, scale


def arc_table(path):
    pts = [(path[i], path[i + 1]) for i in range(0, len(path) - 1, 2)]
    cum = [0.0]
    for (x1, z1), (x2, z2) in zip(pts, pts[1:]):
        cum.append(cum[-1] + math.hypot(x2 - x1, z2 - z1))
    return pts, cum


def point_at(pts, cum, dist):
    dist = max(0, min(cum[-1], dist))
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= dist:
            lo = mid
        else:
            hi = mid
    seg = cum[lo + 1] - cum[lo]
    f = 0 if seg == 0 else (dist - cum[lo]) / seg
    x1, z1 = pts[lo]
    x2, z2 = pts[lo + 1]
    return x1 + (x2 - x1) * f, z1 + (z2 - z1) * f


def render(mode, nframes, fps=30):
    od = os.path.join(OUT, mode)
    os.makedirs(od, exist_ok=True)
    data, lines, bounds = load()
    stations = data["stations"]
    tables = {l["id"]: arc_table(l["path"]) for l in lines}
    labels = ["沙坪坝", "重庆北站南广场", "朝天门", "杨家坪", "鱼洞"]
    lab = {}
    for s in stations:
        if s["name"] in labels and s["name"] not in lab:
            lab[s["name"]] = s

    for i in range(nframes):
        t = i / fps
        p = 1.0 if mode == "full" else min(1.0, t / (nframes / fps))
        if mode == "full":
            zoom = 0.875 + 0.030 * (i / nframes)
            dx = -0.010 * (i / nframes)
            dy = 0.100 + 0.004 * math.sin(i / nframes * math.pi)
            proj, scale = make_proj(bounds, zoom, dx, dy)
            img = Image.new("RGB", (W, H), (5, 8, 12))
        else:
            zoom = 0.965 - 0.095 * p
            proj, scale = make_proj(bounds, zoom, 0, 0.100)
            img = Image.new("RGB", (W, H), (5, 8, 12))

        d = ImageDraw.Draw(img)
        # background grid
        for gx in range(0, W, 60):
            d.line([(gx, 0), (gx, H)], fill=(9, 13, 19))
        for gy in range(0, H, 60):
            d.line([(0, gy), (W, gy)], fill=(9, 13, 19))
        # vignette-ish corner marks
        d.line([(60, 95), (60, 71), (84, 71)], fill=(60, 66, 76), width=2)
        d.line([(W - 60, H - 164), (W - 60, H - 140), (W - 84, H - 140)], fill=(60, 66, 76), width=2)

        glow = Image.new("RGB", (W, H), (0, 0, 0))
        gd = ImageDraw.Draw(glow)

        # lines
        for idx, ln in enumerate(lines):
            if mode == "reveal":
                start = 0.06 + idx * 0.045
                span = 0.42
                lp = max(0.0, min(1.0, (p - start) / span))
                lp = 1 - (1 - lp) ** 2
            else:
                lp = 1.0
            if lp <= 0:
                continue
            pts = [proj(x, z) for x, z in tables[ln["id"]][0]]
            npts = max(2, int(len(pts) * lp))
            seg = pts[:npts]
            if len(seg) < 2:
                continue
            col = ln["color"].lstrip("#")
            rgb = tuple(int(col[j:j + 2], 16) for j in (0, 2, 4))
            d.line(seg, fill=rgb, width=3, joint="curve")
            gd.line(seg, fill=tuple(int(c * 0.85) for c in rgb), width=7, joint="curve")

        # station dots
        for s in stations:
            x, y = proj(s["x"], s["z"])
            if not (60 < x < W - 60 and 40 < y < H - 40):
                continue
            show = 1.0 if mode == "full" else max(0.0, min(1.0, (p - 0.55) / 0.35))
            if show <= 0:
                continue
            r = 2.1 if len(s["lines"]) == 1 else 3.6
            d.ellipse([x - r, y - r, x + r, y + r], fill=(232, 238, 246))
            if len(s["lines"]) > 1:
                d.ellipse([x - r - 2.5, y - r - 2.5, x + r + 2.5, y + r + 2.5], outline=(255, 186, 96), width=1)

        # moving trains (full mode)
        if mode == "full":
            for idx, ln in enumerate(lines):
                pts, cum = tables[ln["id"]]
                if not pts:
                    continue
                speed = 900.0  # data units / s
                dist = (t * speed + idx * 2600) % max(1.0, cum[-1])
                tx, tz = point_at(pts, cum, dist)
                bx, bz = point_at(pts, cum, max(0, dist - 600))
                p1, p2 = proj(tx, tz), proj(bx, bz)
                d.line([p2, p1], fill=(255, 255, 255), width=3)
                d.ellipse([p1[0] - 4, p1[1] - 4, p1[0] + 4, p1[1] + 4], fill=(255, 255, 255))
                gd.line([p2, p1], fill=(255, 220, 150), width=8)

        glow = glow.filter(ImageFilter.GaussianBlur(7))
        img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.5)
        d = ImageDraw.Draw(img)

        # station labels
        if mode == "full" or p > 0.86:
            for name, s in lab.items():
                x, y = proj(s["x"], s["z"])
                if not (80 < x < W - 200 and 50 < y < H - 130):
                    continue
                f = font(FONT_R, 15)
                d.text((x + 8, y - 19), name, font=f, fill=(196, 204, 214))
                d.line([(x + 1, y - 4), (x + 6, y - 8)], fill=(150, 158, 170), width=1)

        # HUD
        fsmall = font(FONT_R, 15)
        tracked(d, (72, 28), "CHONGQING RAIL TRANSIT", fsmall, (168, 176, 188), 4)
        tracked(d, (72, 52), "重 庆 轨 道 交 通 · 线 网 图", font(FONT_R, 17), (124, 132, 144), 2)
        d.line([(72, 82), (420, 82)], fill=(46, 52, 62))
        # vignette
        vig = Image.new("L", (W, H), 0)
        ImageDraw.Draw(vig).ellipse([-W*0.3, -H*0.4, W*1.3, H*1.4], fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(180))
        img = Image.composite(img, Image.new("RGB", (W, H), (2, 3, 5)), vig)
        d = ImageDraw.Draw(img)

        clock = "21:%02d" % (8 + int(t) % 52)
        tracked(d, (W - 190, 28), clock, font(FONT_R, 26), (226, 232, 240), 3)
        tracked(d, (W - 190, 62), "2026.11.21", fsmall, (110, 118, 128), 2)

        count = 16 if mode == "full" else int(16 * max(0, min(1, (p - 0.2) / 0.6)))
        scount = 281 if mode == "full" else int(281 * max(0, min(1, (p - 0.2) / 0.6)))
        tracked(d, (72, 650), f"{count:02d}", font(FONT_B, 38), (240, 244, 250), 0)
        tracked(d, (124, 662), "条线路", font(FONT_R, 15), (130, 138, 150), 2)
        tracked(d, (240, 650), f"{scount}", font(FONT_B, 38), (240, 244, 250), 0)
        tracked(d, (318, 662), "座车站", font(FONT_R, 15), (130, 138, 150), 2)
        tracked(d, (W - 200, 668), "guidao", font(FONT_R, 16), (255, 186, 96), 2)

        img = img.filter(ImageFilter.UnsharpMask(radius=1.4, percent=60, threshold=2))
        img.save(f"{od}/f_{i:04d}.jpg", quality=95)
    print(mode, nframes, "frames")


if __name__ == "__main__":
    render("reveal", 60)
    render("full", 126)
