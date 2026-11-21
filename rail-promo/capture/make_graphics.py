#!/usr/bin/env python3
"""Generate the 2D insert (radio dial) and text overlay PNGs."""
import os
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1920, 1080
FONT_B = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf"
FONT_R = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf"
OUT = "/workspace/rail-promo/out/gfx"
DIAL = "/workspace/rail-promo/out/dial"
os.makedirs(OUT, exist_ok=True)
os.makedirs(DIAL, exist_ok=True)

AMBER = (255, 176, 74)
WHITE = (245, 246, 248)
GREY = (150, 158, 168)


def font(path, size):
    return ImageFont.truetype(path, size)


def tracked(draw, xy, text, fnt, fill, tracking=0, anchor_center=False):
    x, y = xy
    widths = [draw.textlength(c, font=fnt) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    if anchor_center:
        x -= total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=fnt, fill=fill)
        x += w + tracking
    return total


def make_dial(n=29, w=1280, h=720):
    F = lambda s: font(FONT_B, s)
    Fr = lambda s: font(FONT_R, s)
    base = Image.new("RGB", (w, h), (5, 7, 10))
    d = ImageDraw.Draw(base)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(5 + 7 * k), int(8 + 10 * k), int(12 + 14 * k)))
    # frame ticks
    for x in range(40, w - 40, 24):
        d.line([(x, 30), (x, 34)], fill=(40, 44, 50))
    d.line([(40, 38), (w - 40, 38)], fill=(28, 31, 36))
    tracked(d, (48, 54), "CITY RADIO", Fr(18), (190, 196, 204), 5)
    tracked(d, (w - 340, 54), "山城夜行 · 调频", Fr(17), (120, 128, 138), 2)
    # on air
    d.ellipse([w - 96, 76, w - 86, 86], fill=(220, 50, 50))
    tracked(d, (w - 80, 72), "ON AIR", Fr(15), (220, 50, 50), 2)

    # frequency scale
    sy = 486
    x0, x1 = 168, w - 168
    d.line([(x0, sy), (x1, sy)], fill=(52, 56, 63), width=1)
    def fx(freq):
        return x0 + (freq - 87.0) / (93.0 - 87.0) * (x1 - x0)
    for i in range(int((93 - 87) * 10) + 1):
        freq = 87 + i / 10
        x = fx(freq)
        if i % 10 == 0:
            d.line([(x, sy - 12), (x, sy + 6)], fill=(110, 116, 126))
            d.text((x - 12, sy + 12), f"{int(freq)}", font=Fr(20), fill=(120, 126, 136))
        elif i % 5 == 0:
            d.line([(x, sy - 8), (x, sy + 4)], fill=(78, 83, 92))
        else:
            d.line([(x, sy - 5), (x, sy + 2)], fill=(46, 50, 57))

    for i in range(n):
        p = i / max(1, n - 1)
        e = 1 - (1 - p) ** 3
        img = base.copy()
        dd = ImageDraw.Draw(img)
        # big digits
        digits = "90.2"
        f_big = F(168)
        tw = dd.textlength(digits, font=f_big)
        dd.text(((w - tw) / 2 - 20, 226), digits, font=f_big, fill=WHITE)
        dd.text(((w + tw) / 2 + 6, 318), "MHz", font=Fr(30), fill=AMBER)
        tracked(dd, (w / 2, 196), "正在收听", Fr(20), (130, 138, 148), 6, True)
        # needle
        nx = fx(89.1 + 1.1 * e)
        dd.line([(nx, 432), (nx, 552)], fill=AMBER, width=3)
        dd.polygon([(nx - 9, 432), (nx + 9, 432), (nx, 418)], fill=AMBER)
        # glow
        gl = Image.new("RGB", (w, h), (0, 0, 0))
        gd = ImageDraw.Draw(gl)
        gd.line([(nx, 432), (nx, 552)], fill=(255, 150, 40), width=8)
        gl = gl.filter(ImageFilter.GaussianBlur(10))
        img = Image.blend(img, Image.composite(gl, img, gl.convert("L")), 0.55)
        dd = ImageDraw.Draw(img)
        # name
        tracked(dd, (w / 2, 590), "陈 伯 伯", F(54), WHITE, 10, True)
        tracked(dd, (w / 2, 662), "「从你的全世界路过」", Fr(22), (150, 156, 166), 2, True)
        # vignette + scanline
        vig = Image.new("L", (w, h), 0)
        vd = ImageDraw.Draw(vig)
        vd.ellipse([-w * 0.25, -h * 0.35, w * 1.25, h * 1.35], fill=255)
        vig = vig.filter(ImageFilter.GaussianBlur(160))
        black = Image.new("RGB", (w, h), (0, 0, 0))
        img = Image.composite(img, black, vig)
        scan = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        sd = ImageDraw.Draw(scan)
        for y in range(0, h, 3):
            sd.line([(0, y), (w, y)], fill=(0, 0, 0, 26))
        img = Image.alpha_composite(img.convert("RGBA"), scan).convert("RGB")
        img.save(f"{DIAL}/f_{i:04d}.jpg", quality=95)


def text_layer(text, size, color, y, x=None, tracking=0, bold=True, alpha=255, sub=None):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fnt = font(FONT_B if bold else FONT_R, size)
    tw = sum(d.textlength(c, font=fnt) for c in text) + tracking * (len(text) - 1)
    px = (W - tw) / 2 if x is None else x
    d.text((px, y), text, font=fnt, fill=color + (alpha,), stroke_width=2, stroke_fill=(0, 0, 0, 170))
    if sub:
        fs = font(FONT_R, sub[1])
        sw = d.textlength(sub[0], font=fs)
        d.text(((W - sw) / 2, y + size + 16), sub[0], font=fs, fill=sub[2] + (alpha,))
    # glow
    glow = img.filter(ImageFilter.GaussianBlur(8))
    out = Image.alpha_composite(glow, img)
    return out


def make_texts():
    # title
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((150, 430), "EP.02", font=font(FONT_R, 26), fill=AMBER + (255,))
    tracked(d, (155, 468), "山 城 轨 道", font(FONT_R, 26), (200, 206, 214), 4)
    title = "从你的全世界路过"
    fnt = font(FONT_B, 108)
    d.text((146, 540), title, font=fnt, fill=(248, 249, 251, 255), stroke_width=3, stroke_fill=(0, 0, 0, 190))
    d.line([(152, 690), (152 + 460, 690)], fill=AMBER + (220,), width=3)
    img.save(f"{OUT}/title.png")

    subs = [
        ("city_radio", "这里是 City Radio FM 90.2", 46),
        ("old_friend", "我是你们的老朋友", 46),
        ("how_are_you", "这些年你们过得怎么样", 46),
        ("new_friend", "有没有遇到新的朋友呢", 46),
    ]
    for key, txt, size in subs:
        text_layer(txt, size, (240, 242, 246), 958, tracking=1).save(f"{OUT}/sub_{key}.png")

    # end card
    card = Image.new("RGB", (W, H), (6, 9, 13))
    d = ImageDraw.Draw(card)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(6 + 6 * k), int(9 + 8 * k), int(13 + 10 * k)))
    for x in range(0, W, 40):
        d.line([(x, 0), (x, 12)], fill=(26, 30, 36))
    d.text((140, 300), "EP.02", font=font(FONT_R, 26), fill=AMBER)
    tracked(d, (145, 340), "山 城 轨 道", font(FONT_R, 26), (190, 198, 208), 4)
    d.text((138, 408), "从你的全世界路过", font=font(FONT_B, 96), fill=(245, 247, 250))
    d.line([(142, 556), (142 + 520, 556)], fill=AMBER, width=3)
    d.text((142, 596), "重庆轨道交通 · 16 条线路 · 281 座车站", font=font(FONT_R, 34), fill=(200, 206, 214))
    d.text((142, 662), "xcsweb.github.io/guidao", font=font(FONT_R, 28), fill=AMBER)
    d.text((142, 942), "画面：guidao 实时线网渲染　音频素材来源网络 · 仅作二创演示", font=font(FONT_R, 19), fill=(110, 118, 128))
    # abstract network on the right
    pts = [[(1080, 760), (1180, 700), (1300, 720), (1400, 640), (1530, 670), (1620, 590), (1740, 620)],
           [(1120, 880), (1230, 820), (1320, 850), (1450, 780), (1580, 810), (1700, 740)],
           [(1080, 620), (1160, 640), (1240, 590), (1360, 610), (1450, 540)]]
    for line in pts:
        d.line(line, fill=(60, 66, 74), width=4, joint="curve")
        for (px, py) in line:
            d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=(255, 176, 74))
    for (px, py) in [(1300, 720), (1450, 780), (1620, 590)]:
        d.ellipse([px - 9, py - 9, px + 9, py + 9], outline=(255, 176, 74), width=2)
    card.save(f"{OUT}/endcard.png")


if __name__ == "__main__":
    make_dial()
    make_texts()
    print("gfx done")
