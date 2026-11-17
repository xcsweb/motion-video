#!/usr/bin/env python3
"""Render six bottom subtitles as transparent PNGs (960x720)."""
from PIL import Image, ImageDraw, ImageFont

W, H = 960, 720
FONT = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf"
LINES = [
    "改革春风吹满地",
    "中国人民真争气",
    "齐心协力跨世纪",
    "一场大水没咋地",
    "改革春风吹满地",
    "中国人民真争气",
]

font = ImageFont.truetype(FONT, 64)
for i, line in enumerate(LINES, 1):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    box = draw.textbbox((0, 0), line, font=font, stroke_width=7)
    tw = box[2] - box[0]
    x = (W - tw) // 2 - box[0]
    y = H - 92 - (box[3] - box[1]) - box[1]
    draw.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 170), stroke_width=7, stroke_fill=(0, 0, 0, 170))
    draw.text((x, y), line, font=font, fill=(255, 255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0, 255))
    img.save(f"/workspace/demo/guichu-beat/assets/sub{i}.png")
    print("wrote", i, line)
