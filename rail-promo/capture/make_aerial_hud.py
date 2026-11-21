#!/usr/bin/env python3
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 766
FONT_B = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf"
FONT_R = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf"
AMBER = (255, 186, 96)


def tracked(d, xy, text, fnt, fill, tr=0):
    x, y = xy
    for c in text:
        d.text((x, y), c, font=fnt, fill=fill)
        x += d.textlength(c, font=fnt) + tr


img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
f1 = ImageFont.truetype(FONT_R, 15)
f2 = ImageFont.truetype(FONT_R, 17)
f3 = ImageFont.truetype(FONT_R, 20)
f4 = ImageFont.truetype(FONT_R, 15)

tracked(d, (72, 46), "CHONGQING RAIL TRANSIT", f1, (150, 158, 168), 4)
tracked(d, (70, 72), "重 庆 轨 道 交 通 · 线 网 航 拍", f2, (205, 212, 222), 2)
d.line([(72, 108), (236, 108)], fill=AMBER, width=2)

tracked(d, (72, 676), "两 江 四 岸 · 轨 道 穿 城", f3, (228, 234, 242), 3)
tracked(d, (72, 706), "16 条线路 / 281 座车站 / 实时模拟", f4, (128, 136, 148), 1)

tracked(d, (1798, 712), "guidao", f4, AMBER, 2)
img.save("/workspace/rail-promo/out/gfx/aerial_hud.png")
print("ok")
