#!/usr/bin/env python3
"""Generate the 11-line narration with the cloned Seed TTS voice."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from seed_tts import synthesize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'audio', 'vo_seed')
SR = 48000
SPEAKER = 'S_J0yK2jJl2'
RESOURCE = 'seed-icl-2.0'

LINES = [
    (1, '我点了一下重庆，整座城市站起来了。', '我点了一下重庆，\n整座城市站起来了。'),
    (2, '从现在起，整座城市听你指挥。', '从现在起，\n整座城市听你指挥。'),
    (3, '十五条线路，二百七十座车站，五百六十二公里，铺在真实地形上。', '十五条线路，二百七十座车站，\n五百六十二公里，铺在真实地形上。'),
    (4, '打开浏览器，你就是重庆轨道交通的指挥官。', '打开浏览器，\n你就是重庆轨道交通的指挥官。'),
    (5, '点开一条线，镜头带你飞过去。', '点开一条线，\n镜头带你飞过去。'),
    (6, '把山城拉高，看清每一条线怎么穿过江面、桥梁和隧道。', '把山城拉高，\n看清每一条线怎么穿过江面、桥梁和隧道。'),
    (7, '几点发车，几点进站，几点折返，全在掌握。', '几点发车，几点进站，几点折返，\n全在掌握。'),
    (8, '每一座车站的到发时刻，都在你眼前。', '每一座车站的到发时刻，\n都在你眼前。'),
    (9, '这不是一张地图，是一座正在运行的城市。', '这不是一张地图，\n是一座正在运行的城市。'),
    (10, '从开放地图数据，到可接入的实时列车；一整座城市，在你手里运转。', '从开放地图数据，到可接入的实时列车；\n一整座城市，在你手里运转。'),
    (11, '山城轨道。打开浏览器，走马上任。', '山城轨道。\n打开浏览器，走马上任。'),
]


def duration(path: str) -> float:
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def main():
    os.makedirs(OUT, exist_ok=True)
    meta = []
    for idx, text, subtitle in LINES:
        mp3 = os.path.join(OUT, f'line_{idx:02d}.mp3')
        if not os.path.exists(mp3) or os.path.getsize(mp3) == 0:
            synthesize(text, SPEAKER, RESOURCE, mp3)
        wav = os.path.join(OUT, f'line_{idx:02d}.wav')
        subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-i', mp3, '-ar', str(SR), '-ac', '1',
             wav],
            check=True)
        dur = duration(wav)
        meta.append({'index': idx, 'duration': round(dur, 3), 'text': text,
                     'subtitle': subtitle, 'file': os.path.relpath(wav, ROOT)})
        print(f'{idx:02d}  dur={dur:5.2f}  {text}')
    with open(os.path.join(ROOT, 'audio', 'lines_seed.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
