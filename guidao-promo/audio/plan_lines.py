#!/usr/bin/env python3
"""Lay the trimmed narration clips on the 80s timeline and write lines.json."""
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'audio', 'vo_seed')

TEXTS = [
    (1, '我点了一下重庆，整座城市站起来了。', '我点了一下重庆，\n整座城市站起来了。', 0.0),
    (2, '从现在起，整座城市听你指挥。', '从现在起，\n整座城市听你指挥。', 3.9),
    (3, '十五条线路，二百七十座车站，五百六十二公里，铺在真实地形上。', '十五条线路，二百七十座车站，\n五百六十二公里，铺在真实地形上。', 8.0),
    (4, '打开浏览器，你就是重庆轨道交通的指挥官。', '打开浏览器，\n你就是重庆轨道交通的指挥官。', 15.0),
    (5, '点开一条线，镜头带你飞过去。', '点开一条线，\n镜头带你飞过去。', 20.0),
    (6, '把山城拉高，看清每一条线怎么穿过江面、桥梁和隧道。', '把山城拉高，\n看清每一条线怎么穿过江面、桥梁和隧道。', 29.0),
    (7, '几点发车，几点进站，几点折返，全在掌握。', '几点发车，几点进站，几点折返，\n全在掌握。', 39.0),
    (8, '每一座车站的到发时刻，都在你眼前。', '每一座车站的到发时刻，\n都在你眼前。', 44.0),
    (9, '这不是一张地图，是一座正在运行的城市。', '这不是一张地图，\n是一座正在运行的城市。', 54.0),
    (10, '从开放地图数据，到可接入的实时列车；一整座城市，在你手里运转。', '从开放地图数据，到可接入的实时列车；\n一整座城市，在你手里运转。', 64.0),
    (11, '山城轨道。打开浏览器，走马上任。', '山城轨道。\n打开浏览器，走马上任。', 73.0),
]


def duration(path):
    out = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


lines = []
for idx, text, subtitle, start in TEXTS:
    path = os.path.join(DIR, f'line_{idx:02d}.wav')
    dur = duration(path)
    lines.append({
        'index': idx,
        'start': round(start, 3),
        'duration': round(dur, 3),
        'end': round(start + dur, 3),
        'text': text,
        'subtitle': subtitle,
        'file': os.path.relpath(path, ROOT),
    })
    print(f'{idx:02d}  {start:5.1f} -> {start + dur:5.2f}')

with open(os.path.join(ROOT, 'audio', 'lines.json'), 'w', encoding='utf-8') as f:
    json.dump(lines, f, ensure_ascii=False, indent=2)
print('wrote audio/lines.json')
