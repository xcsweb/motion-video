#!/usr/bin/env python3
"""用火山引擎豆包语音合成生成《真途》宣传片旁白。

默认音色为预置大模型音色 zh_male_liufei_uranus_bigtts（资源 volc.service_type.10029）。
若当前 API Key 只开通了声音复刻 2.0，可回退：
    --speaker S_tOxL2jJl2 --resource seed-icl-2.0

用法：
    python3 edit/voice_doubao.py
    python3 edit/voice_doubao.py --speaker S_tOxL2jJl2 --resource seed-icl-2.0
"""
import argparse
import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'audio', 'vo')
SR = 48000
API_KEY = os.environ.get('VOLC_API_KEY', 'ef0e809e-8ce3-4a3d-9453-2fadaa58fbe1')

LINES = [
    '你收藏的攻略，可能早就过期了。',
    '门票涨了，店关了，车也停了。',
    '真途，把攻略拆成信息卡。',
    '每条都有人替你走过。',
    '附近刚发生的，才推给你。',
    '多少条还有效，一眼就知道。',
    '证据和票数达标，才算新鲜。',
    '三分钟，生成三版行程。',
    '哪条过期，出发前提醒你。',
    '点开路线，一站一站走。',
    '拿不准，让网友听证；回来，顺手核实。',
    '真途，只推没失效的攻略，少踩坑。',
]

TARGETS = [0.35, 3.05, 6.25, 9.55, 12.10, 14.80, 17.50, 22.35,
           27.15, 30.00, 32.35, 36.20]


def synth(text, speaker, resource, api_key, speed=1.0):
    body = {
        'user': {'uid': 'zhentu-promo'},
        'req_params': {
            'text': text,
            'speaker': speaker,
            'audio_params': {'format': 'mp3', 'sample_rate': 24000, 'speech_rate': int((speed - 1) * 100)},
        },
    }
    req = urllib.request.Request(
        'https://openspeech.bytedance.com/api/v3/tts/unidirectional',
        data=json.dumps(body).encode(),
        headers={
            'X-Api-Key': api_key,
            'X-Api-Resource-Id': resource,
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')
        raise SystemExit(f'TTS HTTP {exc.code}: {detail}') from exc

    chunks = []
    # 非流式按行返回多个 JSON；流式返回 SSE。两种都兼容。
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('data:'):
            line = line[5:].strip()
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get('code') not in (None, 0, 3000, 20000000):
            raise SystemExit(f"TTS error: {obj.get('code')} {obj.get('message')}")
        data = obj.get('data')
        if data:
            chunks.append(base64.b64decode(data))
    if not chunks:
        raise SystemExit(f'TTS returned no audio: {raw[:400]}')
    return b''.join(chunks)


def decode(mp3_bytes, out_wav):
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
        tmp.write(mp3_bytes)
        path = tmp.name
    try:
        subprocess.run(
            ['ffmpeg', '-loglevel', 'error', '-y', '-i', path, '-ac', '1', '-ar', str(SR), out_wav],
            check=True,
        )
    finally:
        os.unlink(path)


def trim_silence(path, thresh=0.006, pad=0.06):
    y, sr = sf.read(path, dtype='float32')
    if y.ndim > 1:
        y = y.mean(axis=1)
    idx = np.where(np.abs(y) > thresh)[0]
    if len(idx):
        a = max(0, idx[0] - int(pad * sr))
        b = min(len(y), idx[-1] + int(pad * sr))
        y = y[a:b]
    sf.write(path, y, sr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--speaker', default='zh_male_liufei_uranus_bigtts')
    ap.add_argument('--resource', default='seed-tts-2.0')
    ap.add_argument('--api-key', default=API_KEY)
    ap.add_argument('--speed', type=float, default=1.0)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    rows = []
    prev_end = -1.0
    for i, (text, target) in enumerate(zip(LINES, TARGETS), 1):
        print(f'[{i:02d}] {text}')
        mp3 = synth(text, args.speaker, args.resource, args.api_key, args.speed)
        wav = os.path.join(OUT, f'line_{i:02d}.wav')
        decode(mp3, wav)
        trim_silence(wav)
        y, sr = sf.read(wav, dtype='float32')
        if sr != SR:
            y = resample_poly(y, SR, sr)
            sf.write(wav, y, SR)
        dur = len(y) / SR
        # 上一句没说完时顺延，避免两句叠在一起
        target = max(target, prev_end + 0.12)
        prev_end = target + dur
        rows.append({'i': i, 'text': text, 'target': round(target, 3), 'dur': round(dur, 3), 'end': round(prev_end, 3)})
        print(f'    {dur:.2f}s @ {target:.2f}s -> {prev_end:.2f}s')

    with open(os.path.join(OUT, 'lines.json'), 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print('saved', os.path.join(OUT, 'lines.json'))


if __name__ == '__main__':
    main()
