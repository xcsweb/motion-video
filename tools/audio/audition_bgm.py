#!/usr/bin/env python3
"""Build short BGM audition clips: voice-over + one BGM candidate each.

Inputs are two JSON files:

  lines.json
    [{"start": 0.0, "file": "audio/vo/line_01.wav"}, ...]
    Relative file paths resolve against the current working directory.

  candidates.json
    [{"name": "02_better_times", "path": "music/173.mp3", "offset": 0.0}, ...]
    "offset" trims into the track so a quiet intro can be skipped.

Example:
  python3 tools/audio/audition_bgm.py \
    --lines guidao-promo/audio/lines.json \
    --candidates /tmp/candidates.json \
    --out-dir guidao-promo/out/bgm_tests
"""
import argparse
import json
import os
import subprocess
import tempfile

import numpy as np
from scipy.io import wavfile


def read_wav(path):
    sr, data = wavfile.read(path)
    if data.dtype == np.int16:
        data = data.astype(np.float32) / 32768.0
    elif data.dtype == np.int32:
        data = data.astype(np.float32) / 2147483648.0
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    return sr, data


def resample_linear(x, sr_in, sr_out, ch):
    if sr_in == sr_out:
        return x
    n = int(round(len(x) * sr_out / sr_in))
    idx = np.linspace(0, len(x) - 1, n)
    out = np.zeros((n, ch), np.float32)
    for c in range(ch):
        out[:, c] = np.interp(idx, np.arange(len(x)), x[:, c])
    return out


def add_at(mix, clip, at, gain=1.0):
    i = int(at * SR)
    if i >= len(mix):
        return
    j = min(len(mix), i + len(clip))
    mix[i:j] += clip[: j - i] * gain


def load_bgm(path, offset, tmp, duration):
    raw = os.path.join(tmp, 'bgm_raw.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-ss', str(offset), '-i', path, '-t', str(duration + 1.0),
        '-ar', str(SR), '-ac', '2', raw,
    ], check=True)
    norm = os.path.join(tmp, 'bgm_norm.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', raw, '-af', f'loudnorm=I={args.bed_lufs}:TP=-2.0:LRA=8',
        '-ar', str(SR), '-ac', '2', norm,
    ], check=True)
    _, x = read_wav(norm)
    x = resample_linear(x, SR, SR, 2)[:N]
    if len(x) < N:
        x = np.pad(x, ((0, N - len(x)), (0, 0)))
    return x


def build(candidate, lines):
    name = candidate['name']
    offset = float(candidate.get('offset', 0.0))
    with tempfile.TemporaryDirectory() as tmp:
        bgm = load_bgm(candidate['path'], offset, tmp, DUR)
        vo = np.zeros((N, 2), np.float32)
        mask = np.zeros(N, np.float32)
        for line in lines:
            if line['start'] >= DUR:
                continue
            sr, clip = read_wav(line['file'])
            clip = resample_linear(clip, sr, SR, 2)
            add_at(vo, clip, line['start'], args.voice_gain)
            i = int(line['start'] * SR)
            j = min(N, i + len(clip))
            mask[i:j] = 1.0

        k = int(0.25 * SR)
        kernel = np.hanning(k)
        kernel /= kernel.sum()
        duck = np.clip(np.convolve(mask, kernel, mode='same') * 1.8, 0, 1)

        t = np.arange(N) / SR
        vol = np.interp(t, [0, 0.8, 8, DUR], [0.0, 1.0, 0.95, 1.0])
        bed = bgm * vol[:, None] * (1.0 - args.duck * duck[:, None])

        mix = vo + bed
        mix = mix / max(1e-6, np.max(np.abs(mix))) * 0.95
        raw = os.path.join(tmp, 'mix_raw.wav')
        wavfile.write(raw, SR, (mix * 32767).astype(np.int16))

        loud = os.path.join(tmp, 'mix_loud.wav')
        subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                        '-i', raw, '-af', f'loudnorm=I={args.target_lufs}:TP=-1.5:LRA=11',
                        '-ar', str(SR), '-ac', '2', loud], check=True)

        os.makedirs(args.out_dir, exist_ok=True)
        out = os.path.join(args.out_dir, f'{name}.mp3')
        subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                        '-i', loud, '-af', 'volume=2.8dB,alimiter=limit=0.68:level=false',
                        '-t', str(DUR), '-c:a', 'libmp3lame', '-b:a', '192k', out], check=True)
    print('wrote', out)


def main():
    global SR, N, DUR, args
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--lines', required=True, help='voice-over lines JSON')
    ap.add_argument('--candidates', required=True, help='BGM candidates JSON')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--duration', type=float, default=20.0)
    ap.add_argument('--sample-rate', type=int, default=48000)
    ap.add_argument('--target-lufs', type=float, default=-14.0)
    ap.add_argument('--bed-lufs', type=float, default=-23.0)
    ap.add_argument('--duck', type=float, default=0.55)
    ap.add_argument('--voice-gain', type=float, default=0.95)
    args = ap.parse_args()

    SR = args.sample_rate
    DUR = args.duration
    N = int(SR * DUR)

    lines = json.load(open(args.lines, encoding='utf-8'))
    candidates = json.load(open(args.candidates, encoding='utf-8'))
    for c in candidates:
        build(c, lines)


if __name__ == '__main__':
    main()
