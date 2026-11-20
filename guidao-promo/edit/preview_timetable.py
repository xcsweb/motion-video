#!/usr/bin/env python3
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os

W, H = 1920, 1080
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
F_DISPLAY = '/usr/share/fonts/opentype/smiley-sans/SmileySans-Oblique.otf'
F_BOLD = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'
F_BODY = '/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc'
F_MONO = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
TEAL = (95, 211, 196)
AMBER = (246, 168, 0)
DIM = (150, 172, 180)
WHITE = (242, 248, 247)
BG = (4, 7, 11)


def cover(im, w, h):
    r = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
    x = (im.width - w) // 2
    y = (im.height - h) // 2
    return im.crop((x, y, x + w, y + h))


def rounded(im, radius=18):
    mask = Image.new('L', im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=radius, fill=255)
    im = im.convert('RGBA')
    im.putalpha(mask)
    return im


bg = cover(Image.open(os.path.join(ROOT, 'assets/3d/hero_b.jpg')).convert('RGB'), W, H)
bg = Image.blend(bg, Image.new('RGB', (W, H), (5, 12, 17)), 0.55)
base = bg.convert('RGBA')

# left card
card = Image.new('RGBA', (640, 820), (0, 0, 0, 0))
d = ImageDraw.Draw(card)
d.rounded_rectangle([0, 0, 639, 819], radius=22, fill=(6, 15, 21, 225), outline=(70, 105, 112, 255), width=2)
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
base.alpha_composite(card, (80, 130))

# timetable panel
t = Image.open(os.path.join(ROOT, 'assets/ui/timetable.png')).convert('RGB')
t = t.crop((0, int(t.height * 0.435), t.width, t.height))
scale = 660 / t.width
t = t.resize((660, int(t.height * scale)), Image.LANCZOS)
t = t.crop((0, 0, 660, 1000))
panel = rounded(t, 20)
shadow = Image.new('RGBA', (700, 1040), (0, 0, 0, 0))
ImageDraw.Draw(shadow).rounded_rectangle([20, 20, 680, 1020], radius=22, fill=(0, 0, 0, 170))
shadow = shadow.filter(ImageFilter.GaussianBlur(18))
base.alpha_composite(shadow, (1120, 40))
base.alpha_composite(panel, (1140, 50))
d = ImageDraw.Draw(base)
d.rectangle([1140, 50, 1800, 54], fill=TEAL + (220,))
d.text((1140, 10), '2号线 · 各站到站时刻', font=ImageFont.truetype(F_BOLD, 26), fill=TEAL)

base.convert('RGB').save(os.path.join(ROOT, 'out/preview/timetable_shot.jpg'), quality=94)
print('saved out/preview/timetable_shot.jpg')
