#!/usr/bin/env python3
"""用 Kokoro（sherpa-onnx）生成《真途》宣传片旁白。

用法：
    /tmp/ttsenv/bin/python edit/voice.py --model /tmp/tts/kokoro-multi-lang-v1_0
"""
import argparse
import json
import os
import wave

import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'audio', 'vo')
SR = 48000

LINES = [
    '你收藏的攻略，可能过期了。',
    '门票涨了，店关了，车也停了。',
    '真途，把攻略拆成信息卡。',
    '每一条，都有人替你走过。',
    '附近刚发生的，才推给你。',
    '多少条还有效，一眼就知道。',
    '证据和票数，达标才算新鲜。',
    '三分钟，生成三版行程。',
    '哪条过期，出发前提醒你。',
    '点开路线，一站一站走。',
    '拿不准，让网友听证；回来，顺手核实。',
    '真途，每一条攻略，都有人替你走过。',
]

# 每句的目标入点（秒），与画面切点对齐
TARGETS = [0.35, 2.85, 6.25, 9.55, 12.10, 14.80, 17.50, 22.35,
           27.15, 30.00, 32.35, 36.20]


def build_tts(model_dir):
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=os.path.join(model_dir, 'model.onnx'),
                voices=os.path.join(model_dir, 'voices.bin'),
                tokens=os.path.join(model_dir, 'tokens.txt'),
                data_dir=os.path.join(model_dir, 'espeak-ng-data'),
                dict_dir=os.path.join(model_dir, 'dict'),
                lexicon=os.path.join(model_dir, 'lexicon-zh.txt'),
                lang='zh',
            ),
            num_threads=2,
            provider='cpu',
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def trim_silence(y, thresh=0.006, pad=0.06):
    idx = np.where(np.abs(y) > thresh)[0]
    if not len(idx):
        return y
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(y), idx[-1] + int(pad * SR))
    return y[a:b]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='/tmp/tts/kokoro-multi-lang-v1_0')
    ap.add_argument('--sid', type=int, default=48)
    ap.add_argument('--speed', type=float, default=0.98)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    tts = build_tts(args.model)
    rows = []
    for i, (text, target) in enumerate(zip(LINES, TARGETS), 1):
        audio = tts.generate(text, sid=args.sid, speed=args.speed)
        y = np.array(audio.samples, np.float32)
        y = resample_poly(y.astype(np.float64), SR, audio.sample_rate)
        y = trim_silence(y)
        y = y / (np.max(np.abs(y)) + 1e-9) * 0.9
        path = os.path.join(OUT, f'line_{i:02d}.wav')
        with wave.open(path, 'wb') as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(SR)
            f.writeframes((y * 32767).astype('<i2').tobytes())
        dur = len(y) / SR
        rows.append({'i': i, 'text': text, 'target': target, 'dur': round(dur, 3), 'end': round(target + dur, 3)})
        print(f'{i:02d}  target {target:5.2f}  dur {dur:5.2f}  end {target + dur:5.2f}  {text}')

    with open(os.path.join(ROOT, 'audio', 'vo', 'lines.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print('total speech', round(sum(r['dur'] for r in rows), 2))


if __name__ == '__main__':
    main()
