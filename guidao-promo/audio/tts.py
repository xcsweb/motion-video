#!/usr/bin/env python3
"""Generate the 11-line Chinese voice-over with Kokoro (sherpa-onnx)."""
import json
import os
import wave

import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, '.work', 'models', 'kokoro-multi-lang-v1_0')
OUT = os.path.join(ROOT, 'audio', 'vo')
SR = 48000

LINES = [
    (1, 0.0, '我点了一下重庆，整座城市站起来了。', '我点了一下重庆，\n整座城市站起来了。'),
    (2, 3.0, '从现在起，整座城市听你指挥。', '从现在起，\n整座城市听你指挥。'),
    (3, 8.0, '十五条线路，二百七十座车站，五百六十二公里，铺在真实地形上。', '十五条线路，二百七十座车站，\n五百六十二公里，铺在真实地形上。'),
    (4, 15.0, '打开浏览器，你就是重庆轨道交通的指挥使。', '打开浏览器，\n你就是重庆轨道交通的指挥使。'),
    (5, 20.0, '点开一条线，镜头带你飞过去。', '点开一条线，\n镜头带你飞过去。'),
    (6, 29.0, '把山城拉高，看清每一条线怎么穿过江面、桥梁和隧道。', '把山城拉高，\n看清每一条线怎么穿过江面、桥梁和隧道。'),
    (7, 39.0, '几点发车，几点进站，几点折返，全在掌握。', '几点发车，几点进站，几点折返，\n全在掌握。'),
    (8, 44.0, '每一座车站的到发时刻，都在你眼前。', '每一座车站的到发时刻，\n都在你眼前。'),
    (9, 54.0, '这不是一张地图，是一座正在运行的城市。', '这不是一张地图，\n是一座正在运行的城市。'),
    (10, 64.0, '从开放地图数据，到可接入的实时列车；一整座城市，在你手里运转。', '从开放地图数据，到可接入的实时列车；\n一整座城市，在你手里运转。'),
    (11, 73.0, '山城轨道。打开浏览器，走马上任。', '山城轨道。\n打开浏览器，走马上任。'),
]


def build_tts():
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=os.path.join(MODEL, 'model.onnx'),
                voices=os.path.join(MODEL, 'voices.bin'),
                tokens=os.path.join(MODEL, 'tokens.txt'),
                data_dir=os.path.join(MODEL, 'espeak-ng-data'),
                dict_dir=os.path.join(MODEL, 'dict'),
                lexicon=os.path.join(MODEL, 'lexicon-zh.txt'),
                lang='zh',
            ),
            num_threads=4,
            provider='cpu',
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def main():
    os.makedirs(OUT, exist_ok=True)
    tts = build_tts()
    meta = []
    for idx, start, text, subtitle in LINES:
        audio = tts.generate(text, sid=50, speed=0.95)
        y = np.array(audio.samples, np.float32)
        y = y / max(1e-6, np.max(np.abs(y))) * 0.92
        # trim silence
        idxs = np.where(np.abs(y) > 0.008)[0]
        if len(idxs):
            y = y[max(0, idxs[0] - 400): min(len(y), idxs[-1] + 1200)]
        # fade edges
        n = min(int(0.02 * audio.sample_rate), len(y) // 2)
        if n > 0:
            y[:n] *= np.linspace(0, 1, n)
            y[-n:] *= np.linspace(1, 0, n)
        y48 = resample_poly(y.astype(np.float64), SR, audio.sample_rate)
        y48 = np.clip(y48, -1, 1)
        path = os.path.join(OUT, f'line_{idx:02d}.wav')
        with wave.open(path, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes((y48 * 32767).astype('<i2').tobytes())
        dur = len(y48) / SR
        meta.append({
            'index': idx,
            'start': round(start, 3),
            'duration': round(dur, 3),
            'end': round(start + dur, 3),
            'text': text,
            'subtitle': subtitle,
            'file': os.path.relpath(path, ROOT),
        })
        print(f'{idx:02d}  start={start:6.2f}  dur={dur:5.2f}  end={start + dur:6.2f}  {text}')

    with open(os.path.join(ROOT, 'audio', 'lines.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print('wrote', os.path.join(ROOT, 'audio', 'lines.json'))


if __name__ == '__main__':
    main()
