#!/usr/bin/env python3
"""Generate subtitles + project.json for the audio-first guichu cut."""
import os, json, math, subprocess, random
from PIL import Image, ImageDraw, ImageFont

ROOT = '/workspace/demo/guichu-v2'
W, H = 960, 720
FPS = 30
BPM = 105.47
BEAT = 60.0 / BPM
BAR = BEAT * 4
SRC = '../../.tmp-guichu/zuotian.mp4'
FONT = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'

SUBS = [
    (0, 2, '改革春风'),
    (2, 2, '改革春风'),
    (4, 2, '改革春风吹满地'),
    (6, 2, '改革春风吹满地'),
    (8, 2, '中国人民真争气'),
    (10, 2, '齐心协力跨世纪'),
    (12, 2, '一场大水没咋地'),
    (14, 2, '改革春风吹满地'),
]

# shot length patterns in beats, per bar; each row sums to 4 beats.
# Reference (58 shots / 67 bars = 0.87 shots per bar, median shot 4 beats):
# mostly one-bar holds, occasional 1-beat flurries, long shots as breaths.
PATTERNS = {
    0: [4.0],
    1: [4.0],
    2: [2.0, 2.0],
    3: [4.0],
    4: [1.0, 1.0, 2.0],
    5: [2.0, 2.0],
    6: [1.0, 1.0, 2.0],
    7: [4.0],
    8: [1.0, 1.0, 1.0, 1.0],
    9: [2.0, 2.0],
    10: [2.0, 2.0],
    11: [4.0],
    12: [1.0, 1.0, 2.0],
    13: [2.0, 2.0],
    14: [1.0, 1.0, 1.0, 1.0],
    15: [2.0, 2.0],
}

# source material: every detected scene in zuotian.mp4, grouped by shot size
SCENES_PATH = '/workspace/.tmp-analysis/zuotian_shots.json'
with open(SCENES_PATH) as fh:
    SCENES = json.load(fh)
POOLS = {'WIDE': [], 'MED': [], 'CU': []}
for _s in SCENES:
    _cat = _s.get('type', 'MED')
    if _cat in POOLS and _s['dur'] >= 0.4:
        POOLS[_cat].append((_s['start'], _s['dur']))
for _cat in POOLS:
    random.Random(17 + len(POOLS[_cat])).shuffle(POOLS[_cat])
CURSOR = {k: 0 for k in POOLS}
USED = set()


def take_scene(cat, dur):
    """Grab an unused source scene that is long enough for this cut."""
    order = [cat] if cat != 'AUD' else ['MED']
    if cat == 'CU':
        order = ['CU', 'MED']
    elif cat == 'WIDE':
        order = ['WIDE', 'MED']
    for want in order:
        pool = POOLS[want]
        n = len(pool)
        for k in range(n):
            idx = (CURSOR[want] + k) % n
            start, sdur = pool[idx]
            if start not in USED and sdur >= dur:
                USED.add(start)
                CURSOR[want] = idx + 1
                return start, want
    for want in order + ['WIDE', 'MED', 'CU']:
        pool = POOLS[want]
        n = len(pool)
        for k in range(n):
            idx = (CURSOR[want] + k) % n
            start, sdur = pool[idx]
            if start not in USED:
                USED.add(start)
                CURSOR[want] = idx + 1
                return start, want
    pool = POOLS[order[0]]
    idx = CURSOR[order[0]] % len(pool)
    CURSOR[order[0]] += 1
    return pool[idx][0], order[0]


def section_for_bar(bar):
    if bar <= 1:
        return 'intro'
    if bar <= 3:
        return 'pre'
    if bar <= 7:
        return 'hook'
    if bar <= 13:
        return 'verse'
    if bar == 14:
        return 'hook'
    return 'outro'


def pick_category(bar, idx, last):
    sec = section_for_bar(bar)
    if sec == 'intro':
        seq = ['WIDE', 'WIDE', 'MED', 'MED']
    elif sec == 'pre':
        seq = ['MED', 'CU', 'CU', 'MED']
    elif sec == 'hook':
        seq = ['CU', 'MED', 'CU', 'AUD', 'MED', 'CU', 'MED', 'CU']
    elif sec == 'verse':
        seq = ['MED', 'CU', 'MED', 'WIDE', 'CU', 'MED', 'AUD', 'CU']
    else:
        seq = ['CU', 'MED', 'CU', 'MED', 'WIDE']
    cat = seq[idx % len(seq)]
    if cat == last:
        # avoid wall-to-wall same type
        alt = {'CU': 'MED', 'MED': 'CU', 'WIDE': 'MED', 'AUD': 'MED'}[cat]
        cat = alt
    return cat


def make_subs():
    os.makedirs(ROOT + '/assets', exist_ok=True)
    font = ImageFont.truetype(FONT, 62)
    paths = []
    for i, (bar, span, text) in enumerate(SUBS, 1):
        img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        box = d.textbbox((0, 0), text, font=font, stroke_width=6)
        tw = box[2] - box[0]
        th = box[3] - box[1]
        x = (W - tw) // 2 - box[0]
        y = H - 84 - th - box[1]
        d.text((x + 3, y + 4), text, font=font, fill=(0, 0, 0, 160),
               stroke_width=6, stroke_fill=(0, 0, 0, 160))
        d.text((x, y), text, font=font, fill=(255, 255, 255, 255),
               stroke_width=6, stroke_fill=(0, 0, 0, 255))
        p = f'{ROOT}/assets/sub{i}.png'
        img.save(p)
        paths.append(p)
        print('sub', i, text)
    return paths


def precut(shots):
    """Cut every shot into its own short file.

    ffmpeg fans a single long input out to every trim branch at once, which
    buffers one frame per branch and blows past 4 GB of RAM on ~50 shots.
    Pre-cutting keeps each render branch on a tiny file and memory flat.
    """
    out_dir = ROOT + '/assets/shots'
    os.makedirs(out_dir, exist_ok=True)
    for stale in os.listdir(out_dir):
        if stale.endswith('.mp4'):
            os.remove(os.path.join(out_dir, stale))
    for i, shot in enumerate(shots):
        name = f'shot{i + 1:02d}'
        target = f'{out_dir}/{name}.mp4'
        start = shot['sourceStart']
        dur = shot['duration']
        subprocess.run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y',
            '-ss', f'{start:.3f}', '-t', f'{dur:.4f}', '-i', ROOT + '/' + SRC,
            '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', '60',
            '-avoid_negative_ts', 'make_zero', target,
        ], check=True)
        print('cut', name, f'{start:.2f}+{dur:.2f}')
    return out_dir


def main():
    sub_paths = make_subs()
    assets = []
    for i in range(1, len(SUBS) + 1):
        assets.append({'id': f'sub{i}', 'kind': 'image', 'path': f'assets/sub{i}.png'})
    assets.append({'id': 'mix', 'kind': 'audio', 'path': 'assets/audio.wav'})

    shots = []
    last_cat = None
    idx_global = 0
    for bar in range(16):
        beat_pos = bar * 4
        for j, beats in enumerate(PATTERNS[bar]):
            cat = pick_category(bar, j, last_cat)
            last_cat = cat
            start = round(beat_pos * BEAT, 4)
            end = round((beat_pos + beats) * BEAT, 4)
            dur = round(end - start, 4)
            src, cat = take_scene(cat, dur)
            src = round(src + 0.05, 3)
            scale = 1.0
            if cat == 'MED':
                scale = [1.0, 1.08, 1.12][idx_global % 3]
            if cat == 'CU':
                scale = [1.0, 1.06][idx_global % 2]
            pos = None
            if scale != 1.0:
                pos = {'x': -round(W * (scale - 1) / 2), 'y': -round(H * (scale - 1) / 2)}
            clip = {
                'id': f'shot{idx_global + 1:02d}',
                'type': 'video',
                'assetId': f'shot{idx_global + 1:02d}',
                'start': start,
                'duration': dur,
                'sourceStart': 0,
                'volume': 0,
                'scale': scale,
                '_cut': {'start': round(src, 4), 'duration': dur},
            }
            if pos:
                clip['position'] = pos
            shots.append(clip)
            print(f"shot{idx_global+1:02d} bar{bar:02d} {cat:4s} {start:6.2f}s dur {dur:5.2f} src {src:6.2f} sc {scale}")
            beat_pos += beats
            idx_global += 1

    precut([{'sourceStart': s['_cut']['start'], 'duration': s['_cut']['duration']} for s in shots])
    for s in shots:
        assets.append({'id': s['assetId'], 'kind': 'video',
                       'path': f"assets/shots/{s['assetId']}.mp4"})
        del s['_cut']

    # subtitles
    subs = []
    for i, (bar, span, text) in enumerate(SUBS, 1):
        st = round(bar * BAR, 4)
        en = round((bar + span) * BAR, 4)
        subs.append({
            'id': f'sub{i}',
            'type': 'image',
            'assetId': f'sub{i}',
            'start': st,
            'duration': round(en - st, 4),
            'position': {'x': 0, 'y': 0},
        })

    # flash frames + fade in/out
    fx = []
    for k, t in enumerate([4 * BAR, 14 * BAR]):
        fx.append({'id': f'flash{k}', 'type': 'color', 'color': '#FFFFFF',
                   'start': round(t, 4), 'duration': 0.067, 'opacity': 0.7})
    for k in range(3):
        fx.append({'id': f'fadein{k}', 'type': 'color', 'color': '#000000',
                   'start': round(k * 0.1, 4), 'duration': 0.1, 'opacity': [0.8, 0.5, 0.2][k]})
    end = round(16 * BAR, 4)
    for k in range(4):
        fx.append({'id': f'fadeout{k}', 'type': 'color', 'color': '#000000',
                   'start': round(end - 0.48 + k * 0.12, 4), 'duration': 0.12,
                   'opacity': [0.25, 0.5, 0.75, 1.0][k]})

    project = {
        'schemaVersion': 1,
        'revision': 1,
        'name': '鬼畜 v2 - 音频优先 105.47BPM',
        'assets': assets,
        'tracks': [
            {'id': 'v1', 'kind': 'video', 'name': '分镜', 'clips': shots},
            {'id': 'v2', 'kind': 'video', 'name': '特效', 'clips': fx},
            {'id': 'v3', 'kind': 'video', 'name': '字幕', 'clips': subs},
            {'id': 'a1', 'kind': 'audio', 'name': '成品音频', 'clips': [{
                'id': 'mix', 'type': 'audio', 'assetId': 'mix',
                'start': 0, 'duration': round(16 * BAR, 4), 'sourceStart': 0, 'volume': 0.88,
            }]},
        ],
        'output': {
            'path': 'guichu-v2.mp4', 'format': 'mp4', 'videoCodec': 'h264',
            'audioCodec': 'aac', 'width': W, 'height': H, 'frameRate': FPS,
            'pixelFormat': 'yuv420p', 'audioSampleRate': 48000, 'audioChannels': 2,
        },
    }
    json.dump(project, open(ROOT + '/project.json', 'w'), ensure_ascii=False, indent=1)
    print('shots', len(shots), 'duration', round(16 * BAR, 2))


if __name__ == '__main__':
    main()
