#!/usr/bin/env python3
"""Build a clear-reference-audio short sample, then recut picture to its beat grid."""
import json
import math
import os
import random
import subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = '/workspace/demo/guichu-v3'
SOURCE = '/workspace/reference/av19390801-guichu-ref.mp4'
SCENES_PATH = '/workspace/.tmp-analysis/shots.json'
FONT = '/usr/share/fonts/opentype/noto-cjk-otf/NotoSansCJKsc-Bold.otf'
W, H, FPS = 1280, 720, 30
AUDIO_START = 26.760
DURATION = 36.160
BEAT = 0.5688821465819665
PHASE = 0.4650611548307576

# Start times were read from the reference's embedded subtitles, not inferred from bars.
SUBS = [
    (0.24, '改革春风吹满地'),
    (2.24, '吹满地'),
    (3.24, '春风吹满地'),
    (4.74, '中国人民真争气'),
    (7.24, '真争气'),
    (8.24, '人民真争气'),
    (9.24, '这个世界太疯狂'),
    (11.74, '耗子都给猫当伴娘'),
    (14.74, '齐德隆'),
    (15.24, '齐东强'),
    (15.74, '齐德隆的咚得隆咚锵'),
    (18.24, '记得那是2003年的第一场雪'),
    (21.74, '第一场雪'),
    (23.74, '比2002年来滴稍晚了一些'),
    (26.74, '稍晚了一些'),
    (27.74, '抓牌看牌'),
    (29.74, '洗牌码牌'),
    (32.24, '失败'),
    (32.74, '知道因为啥失败吗'),
    (34.24, '真让我替你感到悲哀'),
]

# Each group contains one four-beat unit. Long holds alternate with short flurries.
PATTERNS = [
    [4], [2, 2], [4], [2, 2],
    [1, 1, 2], [2, 2], [1, 1, 1, 1], [4],
    [2, 2], [4], [2, 2], [1, 1, 2],
    [2, 2], [4], [1, 1, 2], [2, 2],
]


def make_subtitles():
    font = ImageFont.truetype(FONT, 52)
    assets = []
    timeline = []
    for i, (start, text) in enumerate(SUBS):
        end = SUBS[i + 1][0] if i + 1 < len(SUBS) else DURATION
        image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        box = draw.textbbox((0, 0), text, font=font, stroke_width=5)
        tw, th = box[2] - box[0], box[3] - box[1]
        x = (W - tw) // 2 - box[0]
        y = 650 - th // 2 - box[1]
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 255),
                  stroke_width=5, stroke_fill=(0, 0, 0, 255))
        name = f'sub{i + 1:02d}'
        image.save(f'{ROOT}/assets/{name}.png')
        assets.append({'id': name, 'kind': 'image', 'path': f'assets/{name}.png'})
        timeline.append({
            'text': text, 'start': round(start, 4), 'end': round(end, 4),
            'referenceStart': round(AUDIO_START + start, 4),
            'referenceEnd': round(AUDIO_START + end, 4),
        })
    with open(f'{ROOT}/assets/subtitles.json', 'w') as fh:
        json.dump(timeline, fh, ensure_ascii=False, indent=2)

    band = Image.new('RGBA', (W, 130), (0, 0, 0, 238))
    band.save(f'{ROOT}/assets/subtitle-band.png')
    assets.append({'id': 'subtitleBand', 'kind': 'image', 'path': 'assets/subtitle-band.png'})

    label = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(label)
    label_font = ImageFont.truetype(FONT, 27)
    text = '参考原声 · 清晰重剪'
    box = draw.textbbox((0, 0), text, font=label_font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.rounded_rectangle((20, 18, 20 + tw + 28, 18 + th + 20), radius=8,
                           fill=(0, 0, 0, 170))
    draw.text((34 - box[0], 28 - box[1]), text, font=label_font,
              fill=(255, 255, 255, 235))
    label.save(f'{ROOT}/assets/label.png')
    assets.append({'id': 'label', 'kind': 'image', 'path': 'assets/label.png'})
    return assets, timeline


def beat_cuts():
    first_beat = math.floor((AUDIO_START - PHASE) / BEAT) + 1
    cursor = PHASE + first_beat * BEAT - AUDIO_START
    cuts = [0.0, round(cursor, 6)]
    beat_index = first_beat
    for pattern in PATTERNS:
        for beats in pattern:
            cursor += beats * BEAT
            beat_index += beats
            if cursor >= DURATION - 0.04:
                cuts.append(DURATION)
                return cuts, beat_index
            cuts.append(round(cursor, 6))
    cuts.append(DURATION)
    return cuts, beat_index


def select_shots(cuts):
    with open(SCENES_PATH) as fh:
        scenes = json.load(fh)
    scenes = [s for s in scenes if 8.7 <= s['start'] and s['end'] <= 136.367 and s['dur'] >= 0.62]
    random.Random(20261117).shuffle(scenes)
    used = set()
    selected = []
    desired = ['MED', 'CU', 'WIDE', 'MED', 'CU', 'MED']
    for i, (start, end) in enumerate(zip(cuts[:-1], cuts[1:])):
        duration = end - start
        eligible = [s for s in scenes if s['dur'] >= duration + 0.08]
        preferred = [s for s in eligible if s['type'] == desired[i % len(desired)] and s['i'] not in used]
        unused = [s for s in eligible if s['i'] not in used]
        candidates = preferred or unused or eligible
        if not candidates:
            raise RuntimeError(f'No source scene long enough for shot {i + 1}: {duration:.3f}s')
        scene = candidates[0]
        used.add(scene['i'])
        available = max(0.0, scene['dur'] - duration - 0.06)
        offset = 0.03 + available * ((i * 0.61803398875) % 1.0)
        selected.append({
            'id': f'shot{i + 1:02d}', 'type': 'video', 'assetId': f'shot{i + 1:02d}',
            'start': round(start, 6), 'duration': round(end - start, 6),
            'sourceStart': 0, 'volume': 0,
            '_source': round(scene['start'] + offset, 6),
            '_scene': scene['i'],
        })
    return selected


def precut(shots):
    for i, shot in enumerate(shots):
        target = f"{ROOT}/assets/shots/{shot['id']}.mp4"
        subprocess.run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y',
            '-ss', f"{shot['_source']:.6f}", '-t', f"{shot['duration']:.6f}", '-i', SOURCE,
            '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '17',
            '-pix_fmt', 'yuv420p', '-r', str(FPS), '-g', '60',
            '-avoid_negative_ts', 'make_zero', target,
        ], check=True)
        print(f"{shot['id']}: scene {shot['_scene']:02d} source {shot['_source']:.3f}s "
              f"timeline {shot['start']:.3f}+{shot['duration']:.3f}s")


def main():
    assets, subtitle_timeline = make_subtitles()
    cuts, last_beat = beat_cuts()
    shots = select_shots(cuts)
    precut(shots)
    for shot in shots:
        assets.append({'id': shot['assetId'], 'kind': 'video',
                       'path': f"assets/shots/{shot['assetId']}.mp4"})
        del shot['_source']
        del shot['_scene']
    assets.append({'id': 'clearMix', 'kind': 'audio', 'path': 'assets/audio.wav'})

    subtitle_clips = [{
        'id': f'sub{i + 1:02d}', 'type': 'image', 'assetId': f'sub{i + 1:02d}',
        'start': sub['start'], 'duration': round(sub['end'] - sub['start'], 6),
        'position': {'x': 0, 'y': 0},
    } for i, sub in enumerate(subtitle_timeline)]

    project = {
        'schemaVersion': 1,
        'revision': 1,
        'name': '鬼畜 v3 - 参考原声清晰重剪短样',
        'assets': assets,
        'tracks': [
            {'id': 'v1', 'kind': 'video', 'name': '鼓点分镜', 'clips': shots},
            {'id': 'v2', 'kind': 'video', 'name': '遮挡原字幕', 'clips': [{
                'id': 'subtitleBand', 'type': 'image', 'assetId': 'subtitleBand',
                'start': 0, 'duration': DURATION, 'position': {'x': 0, 'y': 590},
            }]},
            {'id': 'v3', 'kind': 'video', 'name': '同步字幕', 'clips': subtitle_clips},
            {'id': 'v4', 'kind': 'video', 'name': '样片标识', 'clips': [{
                'id': 'label', 'type': 'image', 'assetId': 'label',
                'start': 0, 'duration': DURATION, 'position': {'x': 0, 'y': 0},
            }]},
            {'id': 'a1', 'kind': 'audio', 'name': '清晰参考原声', 'clips': [{
                'id': 'clearMix', 'type': 'audio', 'assetId': 'clearMix',
                'start': 0, 'duration': DURATION, 'sourceStart': 0, 'volume': 0.85,
            }]},
        ],
        'output': {
            'path': 'guichu-v3-clear.mp4', 'format': 'mp4', 'videoCodec': 'h264',
            'audioCodec': 'aac', 'width': W, 'height': H, 'frameRate': FPS,
            'pixelFormat': 'yuv420p', 'audioSampleRate': 48000, 'audioChannels': 2,
        },
    }
    with open(f'{ROOT}/project.json', 'w') as fh:
        json.dump(project, fh, ensure_ascii=False, indent=2)
    with open(f'{ROOT}/assets/shot-timeline.json', 'w') as fh:
        json.dump({'bpm': 60.0 / BEAT, 'phase': PHASE, 'audioSourceStart': AUDIO_START,
                   'duration': DURATION, 'cuts': cuts, 'lastBeatIndex': last_beat}, fh, indent=2)
    print(f'Built {len(shots)} shots, {len(subtitle_clips)} subtitles, {DURATION:.3f}s')


if __name__ == '__main__':
    main()
