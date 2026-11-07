#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《一笑江湖》× AI 程序员 · 15 秒短片逐帧渲染器
用法:
  python3 build/render.py                # 全量渲染
  python3 build/render.py --step 2       # 快速预览（隔帧）
  python3 build/render.py --preview 1.2 4.0 9.2   # 指定时间点出预览图
"""
import argparse
import json
import math
import os
import random
import re

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AI_DIR = os.path.join(ROOT, "assets", "ai")
FRAME_DIR = os.path.join(ROOT, "frames")
PREVIEW_DIR = os.path.join(ROOT, "previews")

MONO_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
MONOB_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CJK_PATH = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Regular.otf"
CJKB_PATH = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf"
SERIF_PATH = "/usr/share/fonts/opentype/noto-cjk-otf/NotoSerifCJKsc-Regular.otf"

W, H = 1920, 1080
SRC_W, SRC_H = 2560, 1440
CROP_BOTTOM = 0.10

with open(os.path.join(ROOT, "config", "timeline.json"), encoding="utf-8") as f:
    TL = json.load(f)
with open(os.path.join(ROOT, "config", "lyrics.json"), encoding="utf-8") as f:
    LY = json.load(f)

FPS = TL["fps"]
DURATION = TL["duration"]
SHOTS = TL["shots"]
LINES = LY["lines"]

# ---------------------------------------------------------------- colors
C_BG = (7, 10, 14)
C_PANEL = (13, 17, 23)
C_PANEL2 = (16, 22, 30)
C_LINE = (26, 36, 47)
C_TEXT = (201, 209, 217)
C_DIM = (122, 134, 148)
C_GRAY = (86, 96, 108)
C_CYAN = (111, 227, 255)
C_BLUE = (121, 192, 255)
C_RED = (255, 107, 107)
C_GREEN = (63, 185, 80)

_font_cache = {}
_glyph_cache = {}


def _font(path, size, fallback=MONO_PATH):
    key = (path, size)
    if key not in _font_cache:
        p = path if os.path.exists(path) else fallback
        _font_cache[key] = ImageFont.truetype(p, size)
    return _font_cache[key]


def mono(size):
    return _font(MONO_PATH, size)


def monob(size):
    return _font(MONOB_PATH, size, MONO_PATH)


def cjk(size):
    return _font(CJK_PATH, size, MONO_PATH)


def cjkb(size):
    return _font(CJKB_PATH, size, CJK_PATH)


def serif(size):
    return _font(SERIF_PATH, size, CJK_PATH)


def smoothstep(a, b, x):
    if b <= a:
        return 1.0 if x >= b else 0.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def text_track(d, xy, s, font, fill, tracking=0, center=None, right=None):
    """逐字绘制，支持字距；center/right 传坐标时自动对齐。"""
    widths = [d.textlength(ch, font=font) for ch in s]
    total = sum(widths) + tracking * max(0, len(s) - 1)
    x, y = xy
    if center is not None:
        x = center - total / 2
    if right is not None:
        x = right - total
    for ch, w in zip(s, widths):
        d.text((x, y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def overlay(im, fn):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fn(ImageDraw.Draw(ov))
    return Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")


# ---------------------------------------------------------------- base fx
def make_vignette(strength=0.42):
    yy, xx = np.mgrid[0:H, 0:W]
    nx = (xx - W / 2) / (W / 2)
    ny = (yy - H / 2) / (H / 2)
    r2 = nx * nx + ny * ny
    v = 1.0 - strength * np.clip(r2 / 2.0, 0, 1) ** 1.15
    return v.astype(np.float32)[..., None]


VIG = make_vignette()
VIG_SOFT = make_vignette(0.30)


_img_cache = {}


def load_image(name):
    if name in _img_cache:
        return _img_cache[name]
    path = os.path.join(AI_DIR, name + ".jpg")
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.crop((0, 0, w, int(h * (1 - CROP_BOTTOM))))
    w, h = im.size
    tw = int(h * W / H)
    if tw < w:
        left = (w - tw) // 2
        im = im.crop((left, 0, left + tw, h))
    else:
        th = int(w * H / W)
        top = (h - th) // 2
        im = im.crop((0, top, w, top + th))
    im = im.resize((SRC_W, SRC_H), Image.LANCZOS)
    _img_cache[name] = im
    return im


def grade(im, tint):
    a = np.asarray(im).astype(np.float32) / 255.0
    if tint == "night":
        mul, contrast, sat, lift = (0.88, 0.96, 1.10), 1.07, 0.82, 0.012
        shadow = np.array([0.0, 0.008, 0.040], dtype=np.float32)
    elif tint == "surreal":
        mul, contrast, sat, lift = (0.88, 1.02, 1.13), 1.08, 0.98, 0.018
        shadow = np.array([0.0, 0.018, 0.050], dtype=np.float32)
    elif tint == "dawn":
        mul, contrast, sat, lift = (0.94, 1.00, 1.06), 1.02, 0.78, 0.052
        shadow = np.array([0.028, 0.030, 0.048], dtype=np.float32)
    else:
        mul, contrast, sat, lift = (1.0, 1.0, 1.0), 1.0, 1.0, 0.0
        shadow = np.zeros(3, dtype=np.float32)
    a = a * np.array(mul, dtype=np.float32)
    a = (a - 0.5) * contrast + 0.5
    lum = a.mean(axis=2, keepdims=True)
    a = lum + (a - lum) * sat
    a = a * (1.0 - lift) + lift + shadow
    return np.clip(a, 0, 1)


def bloom(im, strength):
    if strength <= 0:
        return im
    small = im.resize((W // 4, H // 4), Image.BILINEAR)
    a = np.asarray(small).astype(np.int16)
    bright = np.clip((a - 146) * 3, 0, 255).astype(np.uint8)
    b = Image.fromarray(bright).filter(ImageFilter.GaussianBlur(9))
    b = b.resize((W, H), Image.BILINEAR)
    return Image.blend(im, ImageChops.screen(im, b), strength)


def add_float_particles(im, t, strength=1.0):
    """代码河流上方漂移的青蓝粒子。"""
    if strength <= 0:
        return im
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    rng = random.Random(int(t * 24) * 733 + 41)
    n = int(8 * strength)
    for i in range(n):
        phase = rng.uniform(0, 1)
        speed = rng.uniform(0.10, 0.30)
        x = ((phase + t * speed) % 1.0) * W
        y = H * rng.uniform(0.30, 0.72) + 26 * math.sin(t * 2.1 + i)
        r = rng.uniform(1.4, 3.6)
        alpha = rng.randint(60, 170)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(150, 238, 255, alpha))
        if rng.random() < 0.4:
            d.line((x, y, x - rng.uniform(8, 26), y + rng.uniform(2, 8),
                   ), fill=(120, 225, 255, alpha // 2), width=1)
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    return Image.alpha_composite(im.convert("RGBA"), layer).convert("RGB")


def add_grain(im, seed, amount=4.2):
    arr = np.asarray(im).astype(np.int16)
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, amount, (H, W, 1)).astype(np.int16)
    arr = arr + noise
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def post_look(im, seed, vignette=VIG, grain=4.2):
    a = np.asarray(im).astype(np.float32)
    a = a * vignette
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return add_grain(im, seed, grain)


# ---------------------------------------------------------------- camera
def shot_at(t):
    for s in SHOTS:
        if s["t0"] <= t < s["t1"]:
            return s
    return SHOTS[-1]


def shot_before(s):
    i = SHOTS.index(s)
    return SHOTS[max(0, i - 1)]


def camera(im, s, t):
    p = clamp((t - s["t0"]) / max(0.001, s["t1"] - s["t0"]), 0, 1)
    z = s.get("z0", 1.0) + (s.get("z1", s.get("z0", 1.0)) - s.get("z0", 1.0)) * p
    cx0, cy0 = s.get("cx", 0.5), s.get("cy", 0.5)
    cx1, cy1 = s.get("cx1", cx0), s.get("cy1", cy0)
    cx = cx0 + (cx1 - cx0) * p
    cy = cy0 + (cy1 - cy0) * p
    cw, ch = SRC_W / z, SRC_H / z
    x = clamp(cx * SRC_W - cw / 2, 0, SRC_W - cw)
    y = clamp(cy * SRC_H - ch / 2, 0, SRC_H - ch)
    out = im.crop((int(x), int(y), int(x + cw), int(y + ch)))
    out = out.resize((W, H), Image.LANCZOS)
    dx = int(round(1.0 * math.sin(t * 0.83)))
    if dx:
        out = ImageChops.offset(out, dx, 0)
    return out


def image_shot(s, t):
    im = camera(load_image(s["asset"]), s, t)
    a = grade(im, s.get("tint", "night"))
    im = Image.fromarray((a * 255).astype(np.uint8))
    im = bloom(im, s.get("bloom", 0.16))
    if s.get("type") == "river":
        im = add_float_particles(im, t, 1.0)
    return im


# ---------------------------------------------------------------- ui kit
def radial_bg(center=(0.42, 0.42), inner=(13, 22, 32), outer=(5, 7, 10)):
    yy, xx = np.mgrid[0:H, 0:W]
    dx = (xx / W - center[0]) / 0.9
    dy = (yy / H - center[1]) / 0.9
    r = np.sqrt(dx * dx + dy * dy)
    k = np.clip(1.0 - r, 0, 1) ** 1.6
    out = np.array(outer, dtype=np.float32)[None, None, :] * (1 - k[..., None]) + \
        np.array(inner, dtype=np.float32)[None, None, :] * k[..., None]
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def window_chrome(d, box, title, active=True):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=10, fill=C_PANEL, outline=C_LINE, width=1)
    d.rectangle((x0 + 1, y0 + 1, x1 - 1, y0 + 42), fill=(18, 24, 32))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((x0 + 18 + i * 20, y0 + 15, x0 + 30 + i * 20, y0 + 27), fill=c)
    d.text((x0 + 86, y0 + 21), title, font=cjk(16), fill=C_DIM, anchor="lm")
    d.line((x0 + 1, y0 + 42, x1 - 1, y0 + 42), fill=C_LINE)


# ---- code editor
CODE = [
    "# agent_rewrite.py",
    "import asyncio",
    "from dataclasses import dataclass",
    "",
    "@dataclass",
    "class Agent:",
    "    name: str",
    '    model: str = "v4"',
    "",
    "    async def run(self, task):",
    "        plan = await self.think(task)",
    "        for step in plan:",
    "            await self.act(step)",
    "        return self.reflect()",
    "",
    "async def main():",
    '    agent = Agent("assistant")',
    "    result = await agent.run(",
    '        "rewrite everything",',
    "    )",
    "    print(result)",
    "",
    "# TODO: what is left?",
    "",
]

_TOK = re.compile(r'(#[^\n]*|"[^"]*"|\'[^\']*\'|'
                  r'\b(?:import|from|class|async|def|await|return|for|in|True|False|None)\b|'
                  r'\b\d+\b|\bself\b)')


def draw_code_line(d, x, y, line, font):
    pos = 0
    for m in _TOK.finditer(line):
        if m.start() > pos:
            d.text((x, y), line[pos:m.start()], font=font, fill=C_TEXT)
            x += d.textlength(line[pos:m.start()], font=font)
        tok = m.group(0)
        if tok.startswith("#"):
            col = (125, 133, 144)
        elif tok.startswith('"') or tok.startswith("'"):
            col = (165, 214, 255)
        elif tok in ("self",):
            col = (210, 168, 255)
        elif tok[0].isdigit():
            col = (121, 192, 255)
        else:
            col = (255, 123, 114)
        d.text((x, y), tok, font=font, fill=col)
        x += d.textlength(tok, font=font)
        pos = m.end()
    if pos < len(line):
        d.text((x, y), line[pos:], font=font, fill=C_TEXT)


_code_base = None


def code_base():
    global _code_base
    if _code_base is not None:
        return _code_base
    im = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 48), fill=C_PANEL)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((22 + i * 22, 18, 34 + i * 22, 30), fill=c)
    d.text((96, 24), "ainight / agent_rewrite.py", font=mono(17), fill=(139, 148, 158),
           anchor="lm")
    d.text((W - 26, 24), "Python 3.11", font=mono(15), fill=(110, 118, 129), anchor="rm")
    # sidebar
    d.rectangle((0, 48, 252, H), fill=(11, 15, 20))
    d.line((252, 48, 252, H), fill=C_LINE)
    d.text((24, 68), "EXPLORER", font=mono(13), fill=(90, 100, 112))
    items = [("ainight", 0), ("agent_rewrite.py", 1), ("utils.py", 1),
             ("requirements.txt", 1), ("deploy.cjs", 1), ("README.md", 1)]
    for i, (name, depth) in enumerate(items):
        y = 108 + i * 34
        if name == "agent_rewrite.py":
            d.rectangle((8, y - 6, 246, y + 24), fill=(18, 28, 39))
            d.rectangle((8, y - 6, 10, y + 24), fill=C_CYAN)
        d.text((26 + depth * 20, y + 8), ("▸ " if depth == 0 else "") + name,
               font=mono(16), fill=C_TEXT if name == "agent_rewrite.py" else C_DIM,
               anchor="lm")
    # editor tabs
    d.rectangle((252, 48, 1390, 96), fill=C_PANEL)
    d.line((252, 96, 1390, 96), fill=C_LINE)
    d.text((276, 72), "agent_rewrite.py", font=mono(17), fill=C_TEXT, anchor="lm")
    d.line((264, 95, 520, 95), fill=C_CYAN, width=2)
    d.text((560, 72), "utils.py", font=mono(17), fill=C_GRAY, anchor="lm")
    # gutter
    d.rectangle((252, 96, 322, H), fill=(9, 12, 17))
    d.line((322, 96, 322, H), fill=(20, 27, 36))
    for i in range(1, 25):
        d.text((314, 120 + (i - 1) * 37), str(i), font=mono(15), fill=(70, 80, 92),
               anchor="rm")
    # AI panel
    d.rectangle((1390, 48, W, H), fill=(11, 15, 21))
    d.line((1390, 48, 1390, H), fill=C_LINE)
    d.text((1418, 74), "AI ASSISTANT", font=mono(14), fill=(110, 122, 136))
    d.ellipse((1660, 67, 1674, 81), fill=C_GREEN)
    d.text((1684, 74), "connected", font=mono(13), fill=C_GRAY, anchor="lm")
    d.line((1390, 100, W, 100), fill=C_LINE)
    d.text((1418, 1046), "ainight · v4.1", font=mono(13), fill=(70, 80, 92))
    _code_base = im
    return im


def render_code(s, t):
    local = t - s["t0"]
    dur = s["t1"] - s["t0"]
    im = code_base().copy()
    d = ImageDraw.Draw(im)
    n = int(clamp(4 + local / (dur * 0.72) * 20, 4, 24))
    last_y = 120 + (n - 1) * 37
    d.rectangle((322, last_y - 8, 1390, last_y + 30, ), fill=(17, 27, 38))
    f = mono(23)
    for i, line in enumerate(CODE[:n]):
        draw_code_line(d, 336, 120 + i * 37, line, f)
    # caret
    if int(local * 5) % 2 == 0:
        caret_x = 336 + int(d.textlength(CODE[n - 1], font=f)) + 2
        d.rectangle((caret_x, last_y + 2, caret_x + 12, last_y + 27), fill=C_CYAN)
    # AI panel content
    def panel(dr):
        if local > 0.06:
            a = int(255 * smoothstep(0.06, 0.20, local))
            dr.rounded_rectangle((1418, 118, 1880, 190), radius=12,
                                 fill=(26, 43, 58, a))
            dr.text((1442, 138), "把 agent 模块重写一遍", font=cjk(20),
                    fill=(214, 232, 245, a))
        if local > 0.30:
            a = int(255 * smoothstep(0.30, 0.46, local))
            dr.rounded_rectangle((1418, 210, 1880, 420), radius=12,
                                 fill=(17, 24, 32, a), outline=(36, 49, 64, a), width=1)
            msg = "已重写整个模块。\n128 行，用时 8.2 秒。\n相当于你 3 天的工作量。"
            shown = int((local - 0.30) / 0.020)
            part = msg[:shown]
            yy = 232
            for ln in part.split("\n"):
                dr.text((1442, yy), ln, font=cjk(19), fill=(198, 213, 226, a))
                yy += 34
            if shown >= len(msg):
                dr.text((1442, 390), "✓ DONE", font=mono(14), fill=(63, 185, 80, a))
        if local > 1.0:
            a = int(255 * smoothstep(1.0, 1.2, local))
            dr.line((1418, 860, 1880, 860), fill=(30, 41, 52, a))
            dr.text((1418, 878), "128 LINES", font=mono(15), fill=(111, 227, 255, a))
            dr.text((1560, 878), "8.2 SEC", font=mono(15), fill=(200, 211, 222, a))
            dr.text((1706, 878), "-3 DAYS", font=mono(15), fill=(255, 107, 107, a))
    return overlay(im, panel)


# ---- hands
def render_hands(s, t):
    im = image_shot(s, t)
    local = t - s["t0"]
    dur = s["t1"] - s["t0"]
    p = clamp(local / dur, 0, 1)

    def hud(dr):
        dr.text((82, 84), "AI OUTPUT   128 LINES", font=mono(19),
                fill=(126, 220, 246, 210))
        dr.text((82, 118), "YOUR INPUT  0 LINES", font=mono(19), fill=(150, 160, 172, 170))
        # typing dots
        dr.text((W - 92, 86), "AI is typing", font=mono(19), fill=(178, 196, 210, 200),
                anchor="rm")
        dots = int(t * 3) % 4
        dr.text((W - 74, 86), "." * dots, font=mono(19), fill=(126, 220, 246, 220),
                anchor="lm")
        # progress line
        dr.line((82, 1000, 82 + int(560 * p), 1000), fill=(111, 227, 255, 150), width=3)
        dr.line((82 + int(560 * p), 1000, 642, 1000), fill=(70, 82, 95, 90), width=3)
        dr.text((82, 1016), "generating…", font=mono(14), fill=(130, 142, 156, 160))
    return overlay(im, hud)


# ---- phone / job
_phone_base = None


def phone_base():
    global _phone_base
    if _phone_base is not None:
        return _phone_base
    im = radial_bg(center=(0.20, 0.10), inner=(14, 21, 30), outer=(4, 6, 9))
    # warm lamp glow bottom right
    yy, xx = np.mgrid[0:H, 0:W]
    g = np.exp(-(((xx - W * 0.93) / (W * 0.22)) ** 2 +
                 ((yy - H * 0.95) / (H * 0.25)) ** 2))
    arr = np.asarray(im).astype(np.float32)
    arr += g[..., None] * np.array([36, 24, 10], dtype=np.float32)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(im)

    window_chrome(d, (90, 110, 1180, 890), "招聘 · 高级后端工程师")
    d.text((132, 205), "高级后端工程师", font=cjkb(52), fill=(232, 238, 244))
    d.text((132, 272), "北京 · 某互联网公司 · 20–35K", font=cjk(22), fill=C_DIM)
    d.text((1146, 212), "已读 7 天", font=cjk(20), fill=(140, 150, 162), anchor="ra")
    d.line((132, 322, 1138, 322), fill=C_LINE)
    rows = [("5–10 年经验", 360, C_TEXT), ("本科及以上", 412, C_TEXT),
            ("年龄 35 岁以下", 464, C_RED)]
    for txt, y, col in rows:
        d.text((132, y), txt, font=cjk(28), fill=col)
    d.line((132, 548, 1138, 548), fill=C_LINE)
    d.text((132, 574), "负责交易系统重构与性能优化", font=cjk(20), fill=C_DIM)
    d.text((132, 612), "熟悉大模型工具链 / Agent 框架", font=cjk(20), fill=C_DIM)
    d.text((132, 650), "加分项：一个人，顶一个团队。", font=cjk(20), fill=(158, 168, 180))
    d.rounded_rectangle((132, 712, 320, 752), radius=6, fill=(17, 26, 36),
                        outline=(34, 46, 58))
    d.text((152, 732), "Python / Go / K8s", font=mono(15), fill=(126, 140, 154),
           anchor="lm")
    d.rounded_rectangle((336, 712, 470, 752), radius=6, fill=(17, 26, 36),
                        outline=(34, 46, 58))
    d.text((356, 732), "LLM", font=mono(15), fill=(126, 140, 154), anchor="lm")
    d.rounded_rectangle((132, 806, 420, 858), radius=8, fill=(20, 29, 39),
                        outline=(36, 47, 59))
    d.text((156, 832), "继续沟通", font=cjk(22), fill=(104, 116, 130), anchor="lm")
    d.text((452, 832), "对方已读，暂无回复", font=cjk(18), fill=(88, 99, 112), anchor="lm")

    window_chrome(d, (1210, 110, 1850, 460), "HR 王女士")
    d.rounded_rectangle((1236, 166, 1836, 214), radius=10, fill=(27, 38, 50))
    d.text((1240, 178), "我们更希望找年轻一点的同学", font=cjk(19), fill=(198, 210, 222))
    d.rounded_rectangle((1236, 228, 1690, 276), radius=10, fill=(27, 38, 50))
    d.text((1240, 240), "你懂的。", font=cjk(19), fill=(198, 210, 222))
    d.text((1836, 420), "已读 · 昨天 23:47", font=cjk(15), fill=(96, 108, 122), anchor="ra")

    window_chrome(d, (1210, 500, 1850, 890), "账单提醒")
    d.text((1240, 545), "房租", font=cjk(24), fill=C_DIM)
    d.text((1240, 575), "¥4,500", font=monob(56), fill=(238, 243, 248))
    d.text((1240, 680), "距到期还有 1 天", font=cjk(26), fill=C_RED)
    d.text((1240, 724), "余额 ¥1,203.66", font=cjk(20), fill=C_DIM)
    _phone_base = im
    return im


def render_phone(s, t):
    im = phone_base().copy()
    local = t - s["t0"]

    def dyn(dr):
        # 35 岁以下 pulsing underline
        pulse = 0.5 + 0.5 * math.sin(local * 9.0)
        a = int(60 + 90 * pulse)
        dr.rounded_rectangle((124, 452, 420, 512), radius=6,
                             outline=(255, 107, 107, a), width=2)
        dr.line((132, 508, 132 + int(200 * (0.6 + 0.4 * pulse)), 508),
                fill=(255, 107, 107, min(255, a + 40)), width=3)
        # read receipt blinks once
        if local > 0.55:
            a2 = int(200 * (1 - smoothstep(0.55, 0.8, local)))
            dr.text((1836, 420), "已读 · 昨天 23:47", font=cjk(15),
                    fill=(120, 132, 146, a2), anchor="ra")
    return overlay(im, dyn)


# ---- github
_gh_base = None
_GH_CELLS = None


def gh_cells():
    global _GH_CELLS
    if _GH_CELLS is None:
        rng = np.random.default_rng(11)
        cells = []
        for c in range(53):
            for r in range(7):
                v = rng.random()
                if v < 0.52:
                    cells.append((c, r, 0.0))
                else:
                    cells.append((c, r, float(rng.choice([0.28, 0.5, 0.72, 1.0]))))
        _GH_CELLS = cells
    return _GH_CELLS


def github_base():
    global _gh_base
    if _gh_base is not None:
        return _gh_base
    im = radial_bg(center=(0.30, 0.38), inner=(12, 17, 23), outer=(4, 6, 9))
    d = ImageDraw.Draw(im)
    d.text((120, 86), "CONTRIBUTIONS · 过去 12 个月", font=cjk(21), fill=(126, 138, 152))
    d.line((120, 130, 600, 130), fill=C_LINE)
    d.text((112, 250), "0", font=monob(280), fill=(230, 237, 243))
    d.text((128, 552), "次提交", font=cjk(38), fill=(142, 154, 168))
    d.line((120, 640, 640, 640), fill=C_LINE)
    d.text((120, 690), "AI 提交了 4,271 次", font=cjk(36), fill=(120, 220, 244))
    d.text((120, 750), "过去 12 个月", font=cjk(20), fill=(104, 115, 128))
    # grid labels
    d.text((780, 270), "12 个月前", font=cjk(15), fill=(96, 108, 122))
    d.text((1782, 270), "今天", font=cjk(15), fill=(96, 108, 122), anchor="ra")
    d.text((780, 470), "你的贡献图，正在变灰。", font=cjk(26), fill=(170, 180, 192))
    d.text((780, 510), "每一个方块，都曾经是你熬过的夜。", font=cjk(18), fill=(108, 119, 132))
    # legend
    d.text((1734, 470), "少", font=cjk(16), fill=(104, 115, 128))
    for i in range(4):
        d.rounded_rectangle((1764 + i * 22, 472, 1776 + i * 22, 484), radius=2,
                            fill=[(22, 27, 34), (14, 68, 41), (0, 109, 50), (38, 166, 65)][i])
    d.text((1850, 470), "多", font=cjk(16), fill=(104, 115, 128))
    _gh_base = im
    return im


def render_github(s, t):
    local = t - s["t0"]
    dur = s["t1"] - s["t0"]
    im = github_base().copy()
    d = ImageDraw.Draw(im)
    fade = 1.0 - smoothstep(0.28, 0.88, local)
    palette = [(14, 68, 41), (0, 109, 50), (38, 166, 65), (57, 211, 83)]
    gray = (33, 38, 45)
    x0, y0, cell, gap = 780, 300, 14, 5
    for c, r, v in gh_cells():
        col = gray
        if v > 0:
            base = palette[min(3, int(v * 4))]
            col = tuple(int(gray[i] + (base[i] - gray[i]) * fade * (0.35 + 0.65 * v))
                        for i in range(3))
        xx = x0 + c * (cell + gap)
        yy = y0 + r * (cell + gap)
        d.rounded_rectangle((xx, yy, xx + cell, yy + cell), radius=2, fill=col)
    # a faint red seam when fully gray
    if local > dur * 0.75:
        a = int(90 * smoothstep(dur * 0.75, dur * 0.95, local))
        d.line((780, 440, 1782, 440), fill=(255, 107, 107, a), width=1)
    return im


# ---- chat
_chat_base = None


def chat_base():
    global _chat_base
    if _chat_base is not None:
        return _chat_base
    im = radial_bg(center=(0.50, 0.34), inner=(14, 20, 29), outer=(4, 6, 9))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((360, 120, 1560, 960), radius=18, fill=(12, 17, 23),
                        outline=(30, 41, 53), width=1)
    d.rectangle((360, 121, 1560, 250), fill=(15, 21, 29))
    d.line((360, 250, 1560, 250), fill=C_LINE)
    d.ellipse((414, 168, 482, 236), fill=(23, 39, 53))
    d.text((448, 202), "AI", font=monob(24), fill=C_CYAN, anchor="mm")
    d.text((502, 174), "AI 助手 v4.1", font=cjk(30), fill=(222, 231, 240))
    d.ellipse((504, 214, 514, 224), fill=C_GREEN)
    d.text((524, 219), "在线 · 已连接", font=cjk(17), fill=(120, 178, 140), anchor="lm")
    d.text((1524, 184), "03:41", font=mono(18), fill=(92, 104, 118), anchor="rm")
    # input bar
    d.rounded_rectangle((400, 852, 1520, 934), radius=20, fill=(10, 14, 19),
                        outline=(30, 41, 53), width=1)
    d.text((432, 893), "输入消息…", font=cjk(20), fill=(88, 99, 112), anchor="lm")
    d.ellipse((1454, 868, 1500, 914), fill=(24, 34, 44))
    d.polygon([(1466, 891), (1490, 879), (1490, 903)], fill=(84, 96, 110))
    _chat_base = im
    return im


def render_chat(s, t):
    local = t - s["t0"]
    im = chat_base().copy()

    def dyn(dr):
        if local > 0.10:
            a = int(255 * smoothstep(0.10, 0.28, local))
            dr.rounded_rectangle((400, 300, 1180, 430), radius=16,
                                 fill=(18, 26, 36, a), outline=(33, 45, 59, a), width=1)
            dr.text((432, 326), "方案已生成。", font=cjk(28), fill=(205, 217, 230, a))
            dr.text((432, 374), "你的岗位，可以优化。", font=cjk(28), fill=(205, 217, 230, a))
        if local > 0.32:
            a = int(255 * smoothstep(0.32, 0.44, local))
            dr.rounded_rectangle((1288, 480, 1520, 572), radius=16,
                                 fill=(23, 43, 58, a), outline=(38, 60, 78, a), width=1)
            shown = max(0, int((local - 0.40) / 0.055))
            dr.text((1312, 504), "那我呢？"[:shown], font=cjk(36), fill=(226, 238, 248, a))
            if shown >= 4 and int(local * 4) % 2 == 0:
                dr.rectangle((1452, 506, 1456, 550), fill=(226, 238, 248, a))
        # typing dots
        if 0.88 < local < 1.62:
            a = int(220 * (1 - smoothstep(1.42, 1.62, local)))
            for i in range(3):
                ph = (local - 0.88) * 6.0 - i * 0.7
                dy = -4.0 * max(0, math.sin(ph))
                dr.ellipse((432 + i * 24, 612 + dy, 444 + i * 24, 624 + dy),
                           fill=(120, 220, 244, a))
    return overlay(im, dyn)


# ---- room title
def render_room(s, t):
    im = image_shot(s, t)
    local = t - s["t0"]

    def dyn(dr):
        a1 = int(220 * smoothstep(0.25, 0.85, local))
        if a1 > 0:
            dr.text((140, 150), "AM 03:00", font=mono(26), fill=(146, 200, 220, a1))
            dr.line((140, 196, 140 + int(120 * smoothstep(0.25, 1.0, local)), 196),
                    fill=(146, 200, 220, int(a1 * 0.7)), width=2)
        a2 = int(255 * smoothstep(0.45, 1.25, local))
        if a2 > 0:
            # soft dark gradient behind title
            dr.rectangle((0, 640, 900, H), fill=(0, 0, 0, int(110 * smoothstep(0.45, 1.1, local))))
            text_track(dr, (0, 700), "凌晨三点", serif(112), (244, 248, 252, a2),
                       tracking=6, right=760)
            dr.text((150, 860), "第 1,027 个这样的夜晚", font=cjk(28),
                    fill=(176, 188, 202, a2))
    return overlay(im, dyn)


def render_reflect(s, t):
    return image_shot(s, t)


# ---- dawn / final
def render_dawn(s, t):
    im = image_shot(s, t)
    local = t - s["t0"]

    def dyn(dr):
        # bottom gradient for legibility
        a0 = int(150 * smoothstep(0.0, 0.5, local))
        for i in range(260):
            y = H - 260 + i
            al = int(a0 * (i / 260.0) ** 1.2)
            dr.line((0, y, W, y), fill=(3, 5, 8, al))
        a1 = int(200 * smoothstep(0.15, 0.6, local))
        dr.text((142, 128), "06:12 AM", font=mono(24), fill=(170, 200, 214, a1))
        # final lines
        a2 = int(255 * smoothstep(0.10, 0.45, local))
        a3 = int(255 * smoothstep(0.38, 0.80, local))
        if a2 > 0:
            text_track(dr, (142, 690), "我不甘心。", serif(100), (250, 250, 250, a2),
                       tracking=5)
        if a3 > 0:
            text_track(dr, (142, 820), "为什么不是我。", serif(100), (250, 250, 250, a3),
                       tracking=5)
    return overlay(im, dyn)


# ---------------------------------------------------------------- lyrics
def draw_lyrics(im, t):
    def fn(dr):
        for ln in LINES:
            if t < ln["t"] - 0.15 or t > ln["end"] + 0.05:
                continue
            line_fade = smoothstep(ln["t"] - 0.12, ln["t"] + 0.10, t)
            line_fade *= 1.0 - smoothstep(ln["end"] - 0.10, ln["end"] + 0.05, t)
            if t > 13.25:
                line_fade *= 0.34
            if line_fade <= 0.01:
                continue
            font = serif(50)
            txt = ln["text"]
            widths = [dr.textlength(ch, font=font) for ch in txt]
            total = sum(widths) + 3 * (len(txt) - 1)
            x = W / 2 - total / 2
            y = 1004
            for i, (ch, w) in enumerate(zip(txt, widths)):
                rev = ln["t"] + i * 0.055
                ca = smoothstep(rev, rev + 0.22, t)
                a = int(225 * line_fade * ca)
                if a <= 2:
                    continue
                dr.text((x + 1, y + 2), ch, font=font, fill=(0, 0, 0, int(a * 0.55)))
                dr.text((x, y), ch, font=font, fill=(236, 243, 250, a))
                x += w + 3
    return overlay(im, fn)


# ---------------------------------------------------------------- frame
def render_shot(s, t):
    kind = s.get("type", "image")
    if kind == "room":
        return render_room(s, t)
    if kind == "code":
        return render_code(s, t)
    if kind == "hands":
        return render_hands(s, t)
    if kind == "phone":
        return render_phone(s, t)
    if kind == "github":
        return render_github(s, t)
    if kind == "river":
        return image_shot(s, t)
    if kind == "reflect":
        return render_reflect(s, t)
    if kind == "chat":
        return render_chat(s, t)
    if kind == "dawn":
        return render_dawn(s, t)
    return image_shot(s, t)


def render_frame(t, fi):
    s = shot_at(t)
    im = render_shot(s, t)
    # crossfade from previous shot
    if s.get("trans") == "fade" and (t - s["t0"]) < 0.30:
        prev = shot_before(s)
        a = clamp((t - s["t0"]) / 0.30, 0, 1)
        im = Image.blend(render_shot(prev, t), im, a)
    # flash
    if s.get("trans") == "flash" and (t - s["t0"]) < 0.20:
        k = 1.0 - (t - s["t0"]) / 0.20
        flash_im = Image.new("RGB", (W, H), (150, 224, 255))
        im = Image.blend(im, flash_im, 0.45 * k)
    # lyrics on top of picture
    im = draw_lyrics(im, t)
    # fade in / out
    if t < 0.32:
        im = Image.blend(Image.new("RGB", (W, H), (0, 0, 0)), im,
                         smoothstep(0.0, 0.32, t))
    if t > DURATION - 0.30:
        im = Image.blend(im, Image.new("RGB", (W, H), (0, 0, 0)),
                         smoothstep(DURATION - 0.30, DURATION, t))
    # grain + vignette
    ui = s.get("type") in ("code", "phone", "github", "chat")
    return post_look(im, fi * 97 + 13, vignette=VIG_SOFT if ui else VIG,
                     grain=3.4 if ui else 4.6)


def save_frame(fi, path):
    t = fi / FPS
    im = render_frame(t, fi)
    im.save(path, quality=93, subsampling=1)
    return fi


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--preview", nargs="*", type=float, default=None)
    args = ap.parse_args()

    os.makedirs(FRAME_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)

    if args.preview:
        for tt in args.preview:
            fi = int(round(tt * FPS))
            im = render_frame(tt, fi)
            out = os.path.join(PREVIEW_DIR, "p_%05.2f.jpg" % tt)
            im.save(out, quality=94, subsampling=1)
            print("preview ->", out)
        return

    total = int(round(DURATION * FPS))
    idx = list(range(0, total, max(1, args.step)))
    todo = []
    for fi in idx:
        path = os.path.join(FRAME_DIR, "f_%05d.jpg" % fi)
        if args.force or not os.path.exists(path):
            todo.append((fi, path))
    print("frames:", total, "todo:", len(todo), "jobs:", args.jobs)

    if args.jobs > 1 and len(todo) > 8:
        import multiprocessing as mp
        with mp.Pool(args.jobs) as pool:
            for k, _ in enumerate(pool.starmap(save_frame, todo), 1):
                if k % 30 == 0 or k == len(todo):
                    print("  %d/%d" % (k, len(todo)), flush=True)
    else:
        for k, (fi, path) in enumerate(todo, 1):
            save_frame(fi, path)
            if k % 30 == 0 or k == len(todo):
                print("  %d/%d" % (k, len(todo)), flush=True)
    print("done ->", FRAME_DIR)


if __name__ == "__main__":
    main()
