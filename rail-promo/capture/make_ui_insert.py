#!/usr/bin/env python3
"""Compose a 2 s UI interaction insert from two app screenshots."""
import os
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

W, H = 1920, 1080
CW, CH = 1920, 765
CY = (H - CH) // 2  # 157
N = 60

OUT = "/workspace/rail-promo/out/ui"
os.makedirs(OUT, exist_ok=True)

base = Image.open("/workspace/rail-promo/out/ui_src/app_base.png").convert("RGB")
click = Image.open("/workspace/rail-promo/out/ui_src/app_click.png").convert("RGB")


def grade(im):
    im = ImageEnhance.Color(im).enhance(0.74)
    im = ImageEnhance.Contrast(im).enhance(1.12)
    im = ImageEnhance.Brightness(im).enhance(0.94)
    cool = Image.new("RGB", im.size, (10, 18, 30))
    im = Image.blend(im, cool, 0.07)
    vig = Image.new("L", im.size, 0)
    vd = ImageDraw.Draw(vig)
    w, h = im.size
    vd.ellipse([-w * 0.2, -h * 0.3, w * 1.2, h * 1.3], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(140))
    return Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), vig)


base = grade(base)
click = grade(click)

START = (980, 640)
TARGET = (176, 449)
CLICK_F = 14
END = (1080, 690)


def ease(t):
    return 1 - (1 - t) ** 3


def cursor(d, x, y, s=1.0, alpha=255):
    pts = [(0, 0), (0, 21), (5, 16.5), (8.5, 24), (11.6, 22.6), (8.4, 15.2), (14.6, 14.6)]
    pts = [(x + px * s, y + py * s) for px, py in pts]
    d.polygon(pts, fill=(250, 250, 250, alpha), outline=(20, 22, 26, alpha))


CROP_Y = 0  # full app chrome, playback bar falls outside the 765 band


for i in range(N):
    zoom = 1.0 + 0.012 * (i / (N - 1))
    img = base if i < CLICK_F else click
    sc = img.crop((0, CROP_Y, 1920, CROP_Y + 765))
    nw, nh = int(1920 * zoom), int(765 * zoom)
    sc = sc.resize((nw, nh), Image.LANCZOS)
    scale = nw / 1920
    px = (W - nw) // 2
    py = CY - int((nh - 765) / 2)
    canvas = Image.new("RGB", (W, H), (5, 8, 13))
    canvas.paste(sc, (px, py))
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)

    def place(x, y, s=1.0):
        return px + x * scale, py + (y - CROP_Y) * scale, s

    if i < CLICK_F:
        t = ease(min(1.0, i / (CLICK_F - 1)))
        cx = START[0] + (TARGET[0] - START[0]) * t
        cy = START[1] + (TARGET[1] - START[1]) * t
        cursor(d, *place(cx, cy))
    else:
        t = ease(min(1.0, (i - CLICK_F) / 22))
        cx = TARGET[0] + (END[0] - TARGET[0]) * t
        cy = TARGET[1] + (END[1] - TARGET[1]) * t
        s = 0.86 if i < CLICK_F + 3 else 1.0
        cursor(d, *place(cx, cy, s))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
    canvas.save(f"{OUT}/f_{i:04d}.jpg", quality=95)

print("frames", N)
