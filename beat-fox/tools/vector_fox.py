import math, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, SS, FPS = 720, 1280, 2, 30
DW, DH = W*SS, H*SS
FONT = '/usr/share/fonts/truetype/noto/NotoSerif-SemiBold.ttf'

def S(v): return int(round(float(v)*SS))

_cache = {}
def grad(key, c0, c1):
    if key in _cache: return _cache[key]
    a = np.array(c0, np.float32); b = np.array(c1, np.float32)
    t = np.linspace(0, 1, DH, dtype=np.float32)[:, None, None]
    arr = np.repeat((a*(1-t) + b*t).astype(np.uint8), DW, axis=1)
    im = Image.fromarray(arr, 'RGB').convert('RGBA')
    _cache[key] = im
    return im

def fill_poly(img, pts, c0=None, c1=None, gkey=None, alpha=255):
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).polygon([(S(x), S(y)) for x, y in pts], fill=alpha)
    if gkey:
        img.paste(grad(gkey, c0, c1), (0, 0), mask)
    else:
        img.paste(Image.new('RGBA', img.size, tuple(c0) + (255,)), (0, 0), mask)

def ellipse(img, cx, cy, rx, ry, color, width=0):
    ImageDraw.Draw(img).ellipse([S(cx-rx), S(cy-ry), S(cx+rx), S(cy+ry)],
                                fill=color, width=S(width) if width else 0)

def soft(img, cx, cy, r, color, alpha=70, blur=50):
    lay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).ellipse([S(cx-r), S(cy-r), S(cx+r), S(cy+r)], fill=color+(alpha,))
    img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(S(blur))))

def bez(p, n=32):
    p0, p1, p2, p3 = [np.array(q, float) for q in p]
    return [tuple(((1-t)**3)*p0 + 3*((1-t)**2)*t*p1 + 3*(1-t)*t*t*p2 + t**3*p3)
            for t in np.linspace(0, 1, n+1)]

def tail_poly(root, ang, length, bend, wmax, n=34):
    b = np.array(root, float)
    d = np.array([math.cos(ang), math.sin(ang)])
    perp = np.array([-d[1], d[0]])
    left, right, center = [], [], []
    for i in range(n+1):
        t = i/n
        q = b + d*length*t + perp*bend*math.sin(math.pi*t)*t
        w = wmax*(math.sin(math.pi*(0.10+0.90*t))**0.65)
        left.append(tuple(q + perp*w)); right.append(tuple(q - perp*w)); center.append(tuple(q))
    return left, right, center

def background():
    bg = grad('bg', (232, 244, 239), (253, 252, 247)).copy()
    soft(bg, 540, 260, 250, (198, 228, 224), 80, 110)
    soft(bg, 130, 860, 270, (215, 234, 229), 60, 130)
    soft(bg, 360, 1200, 320, (255, 253, 245), 110, 170)
    return bg

def draw_tails(img, t):
    d = ImageDraw.Draw(img)
    for layer, (wscale, lscale, alpha) in enumerate(((1.0, 1.0, 255), (0.7, 0.72, 230))):
        for k in range(-4, 5):
            ang = math.radians(-98 + k*25 + 4*math.sin(2*math.pi*0.42*t + k*0.7 + layer))
            root = (360 + k*14, 760 + abs(k)*7)
            length = (430 - abs(k)*15)*lscale
            bend = 125 * (1 if k < 0 else -1) * lscale
            wmax = (74 - abs(k)*3)*wscale
            left, right, center = tail_poly(root, ang, length, bend, wmax)
            i0 = int(len(left)*0.42)
            body_poly = left + right[::-1]
            tip_poly = left[i0:] + right[i0:][::-1]
            fill_poly(img, body_poly, (253, 254, 253), None, None, alpha=alpha)
            fill_poly(img, tip_poly, (251, 230, 190), (232, 183, 115), 'tgold', alpha=alpha)
            d.line([(S(x), S(y)) for x, y in body_poly + [body_poly[0]]],
                   fill=(240, 226, 200, 170), width=S(2), joint='curve')

def draw_body(img, t, breath):
    sw = 3.2*math.sin(2*math.pi*0.36*t)
    hem = 1278 + 3*math.sin(2*math.pi*0.4*t + 0.6)
    # neck
    fill_poly(img, [(340, 396), (380, 396), (386, 530), (334, 530)],
              (250, 251, 251), (228, 239, 240), 'neck')
    # skirt
    left = bez([(332, 782), (252+sw, 1000), (196+sw, 1160), (168+sw, hem)], 22)
    right = bez([(390, 782), (468+sw, 1000), (524+sw, 1160), (552+sw, hem)], 22)
    hempts = [(552+sw, hem), (480, hem-16), (410, hem-4), (360, hem-18),
              (310, hem-4), (240, hem-16), (168+sw, hem)]
    fill_poly(img, left + hempts + right[::-1], (253, 254, 254), (212, 235, 240), 'skirt')
    # sheer layer
    ol = bez([(326, 800), (240+sw*1.3, 1010), (188+sw*1.3, 1176), (176+sw, hem+3)], 18)
    oh = [(176+sw, hem+3), (330, hem-8), (430, hem-6), (548+sw, hem+2)]
    fill_poly(img, ol + oh, (203, 231, 237), (227, 244, 246), 'sheer', alpha=105)
    # folds
    d = ImageDraw.Draw(img)
    for fx in (310, 360, 410):
        d.line([(S(fx), S(830)), (S(fx + (fx-360)*0.5 + sw*2), S(hem-10))],
               fill=(255, 255, 255, 90), width=S(3))
    # torso
    tor = bez([(324, 520), (316, 640), (324, 742), (332, 790)], 14) + \
          bez([(396, 520), (404, 640), (396, 742), (388, 790)], 14)[::-1]
    fill_poly(img, tor, (253, 254, 254), (234, 246, 247), 'torso')
    soft(img, 300, 640, 40, (206, 224, 226), 40, 40)
    # sash
    fill_poly(img, [(316, 758+breath), (404, 756+breath), (408, 792+breath), (312, 794+breath)],
              (156, 205, 212), None, None)
    ellipse(img, 360, 776+breath, 11, 9, (112, 170, 179, 255))
    for s in (-1, 1):
        fill_poly(img, [(360, 776+breath), (360+24*s, 796+breath),
                        (360+30*s, 830+breath), (360+8*s, 808+breath)],
                  (146, 197, 205), None, None)
    # arms + sleeves
    for s in (-1, 1):
        arm = bez([(360+34*s, 548), (360+78*s+sw, 650), (360+86*s+sw*1.4, 760),
                   (360+56*s+sw*1.1, 842)], 18)
        d.line([(S(x), S(y)) for x, y in arm], fill=(248, 248, 246, 255), width=S(11), joint='curve')
        hand = arm[-1]
        ellipse(img, hand[0], hand[1]+6, 9, 12, (250, 247, 243, 255))
        sl = bez([(360+36*s, 536), (360+108*s+sw*1.5, 626), (360+126*s+sw*2, 792),
                  (360+78*s+sw*1.4, 884)], 22)
        fill_poly(img, [(360+36*s, 536)] + sl + [(360+20*s, 614)],
                  (222, 240, 243), (243, 250, 250), 'sleeve', alpha=205)
        rb = bez([(360+28*s, 556), (360+128*s+sw*2.4, 690), (360+158*s+sw*3, 846),
                  (360+104*s+sw*2.2, 944)], 24)
        d.line([(S(x), S(y)) for x, y in rb], fill=(164, 213, 219, 200), width=S(3), joint='curve')
    # collar fur
    fur = [(336, 470), (322, 500), (338, 538), (354, 512), (360, 540),
           (366, 512), (382, 538), (398, 500), (384, 470)]
    fill_poly(img, fur, (252, 253, 252), (228, 240, 241), 'fur')

def draw_face(img, t, mopen, blink, nod):
    ox, oy = 0, 0
    # ears first (behind head)
    for a, b, c in (((302, 228), (266, 88), (338, 192)),
                    ((418, 228), (454, 88), (382, 192))):
        fill_poly(img, [a, b, c], (251, 252, 252), (240, 208, 160), 'ear')
        fill_poly(img, [(a[0]+(c[0]-a[0])*0.24, a[1]+(c[1]-a[1])*0.24),
                        (b[0]*0.78+c[0]*0.22, b[1]*0.78+c[1]*0.22),
                        (c[0], c[1]+6)], (242, 181, 126), (251, 227, 190), 'earin', alpha=200)
    # head base + cheek tufts
    ellipse(img, 360, 312, 116, 118, (252, 253, 252, 255))
    for s in (-1, 1):
        fill_poly(img, [(360+96*s, 300), (360+150*s, 330), (360+108*s, 342),
                        (360+146*s, 366), (360+104*s, 372), (360+126*s, 394),
                        (360+96*s, 386)], (250, 251, 251), (232, 241, 242), 'tuft')
    soft(img, 300, 352, 46, (205, 222, 224), 34, 26)
    # muzzle
    fill_poly(img, [(337, 352), (383, 352), (376, 400), (360, 410), (344, 400)],
              (254, 254, 253), (242, 246, 246), 'muz')
    # nose
    d = ImageDraw.Draw(img)
    d.polygon([(S(349), S(366)), (S(371), S(366)), (S(363), S(380)), (S(357), S(380))],
              fill=(78, 54, 41, 255))
    ellipse(img, 356, 369, 3, 2, (154, 114, 92, 190))
    # eyes
    for ex, ey in ((319, 306), (401, 302)):
        almond = [(ex-23, ey-3), (ex-11, ey-16), (ex+9, ey-17), (ex+23, ey-4),
                  (ex+9, ey+13), (ex-8, ey+12)]
        fill_poly(img, almond, (255, 255, 255), None, None)
        ellipse(img, ex, ey, 14, 12, (231, 162, 60, 255))
        ellipse(img, ex, ey, 6, 10, (55, 37, 22, 255))
        ellipse(img, ex-5, ey-4, 3.4, 3.2, (255, 252, 241, 240))
        d.line([(S(ex-23), S(ey-3)), (S(ex-11), S(ey-16)), (S(ex+9), S(ey-17)), (S(ex+23), S(ey-4))],
               fill=(118, 84, 50, 255), width=S(2.6), joint='curve')
        d.line([(S(ex-14), S(ey-19)), (S(ex+10), S(ey-20))], fill=(222, 202, 180, 190), width=S(2))
        if blink > 0.02:
            d.pieslice([S(ex-25), S(ey-26), S(ex+25), S(ey+26)], 180, 360,
                       fill=(252, 253, 252, 255))
            d.line([(S(ex-23), S(ey-3)), (S(ex+23), S(ey-4))],
                   fill=(118, 84, 50, 255), width=S(2.6))
    # mouth
    mx, my = 360, 394
    if mopen < 0.06:
        d.arc([S(mx-14), S(my-7), S(mx+14), S(my+7)], 15, 165,
              fill=(126, 88, 72, 255), width=S(2.2))
    else:
        ow = 10 + 9*mopen
        oh = 1.5 + 12*mopen
        ellipse(img, mx, my + oh*0.55, ow, oh, (96, 54, 60, 255))
        if mopen > 0.4:
            ellipse(img, mx, my + oh*0.7, ow*0.58, oh*0.42, (188, 124, 133, 255))
        d.line([(S(mx-ow), S(my+0.5)), (S(mx+ow), S(my+0.5))],
               fill=(126, 88, 72, 255), width=S(1.5))
    # forehead mark
    fill_poly(img, [(360, 228), (367, 254), (360, 270), (353, 254)], (228, 176, 104), None, None)

def head_layer(t, mopen, blink, nod):
    tmp = Image.new('RGBA', (DW, DH), (0, 0, 0, 0))
    draw_face(tmp, t, mopen, blink, nod)
    crop = tmp.crop((S(40), S(60), S(700), S(720)))
    angle = 1.1*math.sin(2*math.pi*0.28*t) + nod*0.7
    crop = crop.rotate(-angle, resample=Image.BICUBIC, center=(S(360-40), S(440-60)))
    return crop, (40, 60 + nod*5)

def particles(t):
    rng = np.random.RandomState(7)
    xs = rng.uniform(60, 660, 14); ys0 = rng.uniform(600, 1250, 14)
    sp = rng.uniform(12, 30, 14); rr = rng.uniform(1.2, 3.2, 14)
    return [((x + 7*math.sin(t*0.6 + i)), (y - sp[i]*t) % 1280, r)
            for i, (x, y, r) in enumerate(zip(xs, ys0, rr))]

# ---- timing
WORDS = [("Spider", 0.00, 0.60), ("is", 0.60, 0.88), ("easy,", 0.88, 1.20), ("right?", 1.40, 1.54),
         ("How", 3.10, 3.58), ("do", 3.58, 3.72), ("you", 3.72, 3.84), ("say", 3.84, 4.02),
         ("tomorrow", 4.02, 4.44), ("in", 4.44, 4.80), ("Spanish?", 4.80, 5.16)]

def audio_env(path, dur=5.16):
    raw = subprocess.run(['ffmpeg','-v','error','-i',path,'-ac','1','-ar','16000','-f','s16le','-'],
                         capture_output=True).stdout
    pcm = np.frombuffer(raw, np.int16).astype(np.float32)/32768.0
    hop = 160; n = len(pcm)//hop
    rms = np.sqrt(np.mean(pcm[:n*hop].reshape(n, hop)**2, axis=1))
    rms = np.clip(rms/(np.percentile(rms, 98)+1e-6), 0, 1)
    def env(t):
        if any(s-0.03 <= t <= e+0.03 for _, s, e in WORDS):
            i = int(t/0.01)
            return float(rms[max(0,i-1):min(n,i+2)].max()) if i < n else 0
        return 0.0
    return env

def draw_sub(img, t):
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, S(34))
    line = [w for w in WORDS if t >= (0 if w[1] < 2.6 else 3.0)]
    line = [w for w in WORDS if (0.0 <= w[1] < 2.6) or (3.0 <= w[1] < 5.3)]
    if t < 2.6: line = WORDS[:4]
    elif t >= 2.9: line = WORDS[4:]
    else: return
    widths = [d.textlength(w[0], font=f)/SS for w in line]
    gap = 9
    x = 360 - (sum(widths) + gap*(len(line)-1))/2
    for (w, s, e), wd in zip(line, widths):
        active = s-0.03 <= t <= e+0.05
        col = (216, 158, 78, 255) if active else (255, 255, 255, 235)
        d.text((S(x), S(1152)), w, font=f, fill=col, anchor='lm',
               stroke_width=S(2.5), stroke_fill=(40, 56, 58, 120))
        x += wd + gap

BG = None
def render_frame(t, env_fn, prev):
    tgt = env_fn(t)
    a = prev + (tgt-prev)*(0.6 if tgt > prev else 0.25)
    blink = 0.0
    for bt in (2.32, 4.42):
        dt = t - bt
        if 0 <= dt < 0.16:
            blink = math.sin(math.pi*dt/0.16)
    nod = sum(0.9*math.exp(-((t-s)/0.13)**2) for _, s, _ in WORDS if t >= s)
    nod = min(nod, 1.0)
    img = BG.copy()
    draw_tails(img, t)
    draw_body(img, t, 1.5*math.sin(2*math.pi*0.32*t))
    lay, pos = head_layer(t, a, blink, nod)
    img.alpha_composite(lay, (S(pos[0]), S(pos[1])))
    for x, y, r in particles(t):
        ellipse(img, x, y, r, r, (238, 210, 150, 85))
    draw_sub(img, t)
    return img, a

def still(path, t=0.4, m=0.7):
    global BG
    if BG is None: BG = background()
    img, _ = render_frame(t, lambda x: m, m)
    img.resize((W, H), Image.LANCZOS).convert('RGB').save(path)

def video(path, dur=5.16, outdir='/tmp/vecf'):
    global BG
    import os
    os.makedirs(outdir, exist_ok=True)
    BG = background()
    env = audio_env('source-audio.mp3')
    prev = 0.0
    nf = int(dur*FPS)
    for i in range(nf):
        t = i/FPS
        img, prev = render_frame(t, env, prev)
        img.resize((W, H), Image.LANCZOS).convert('RGB').save(f'{outdir}/f_{i:04d}.png')
    print('frames', nf)

if __name__ == '__main__':
    still('qa/vec_still.png', 0.5, 0.7)
    still('qa/vec_still_closed.png', 0.5, 0.0)
    print('ok')
