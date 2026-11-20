#!/usr/bin/env python3
"""Build 20 s BGM audition clips with the same voice-over and SFX as the film."""
import json
import os
import subprocess

import numpy as np
from scipy.io import wavfile

from mix import (ROOT, SR, read_wav, resample_linear, add_at,
                 synth_boom, synth_click, synth_riser, synth_tick, synth_rumble)

DUR = 20.0
N = int(SR * DUR)

CANDIDATES = [
    # name, file, offset(sec), license note
    ('00_current', 'audio/bgm.mp3', 0.0),
    ('01_original_retrim', 'audio/bgm.mp3', 19.0),
    ('02_better_times', 'audio/bgm_candidates/173.mp3', 0.0),
    ('03_cyberpunk_city', 'audio/bgm_candidates/140.mp3', 0.0),
    ('04_close_up', 'audio/bgm_candidates/1167.mp3', 0.0),
]


def load_bgm(path, offset):
    out = os.path.join('/tmp', 'audition_bgm.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-ss', str(offset), '-i', os.path.join(ROOT, path),
        '-t', str(DUR + 1.0), '-ar', str(SR), '-ac', '2', out,
    ], check=True)
    # normalize bed to a fixed loudness so candidates compare fairly
    norm = os.path.join('/tmp', 'audition_bgm_norm.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', out, '-af', 'loudnorm=I=-23:TP=-2.0:LRA=8',
        '-ar', str(SR), '-ac', '2', norm,
    ], check=True)
    _, x = read_wav(norm)
    x = resample_linear(x, SR, SR, 2)[:N]
    if len(x) < N:
        x = np.pad(x, ((0, N - len(x)), (0, 0)))
    return x


def build(name, path, offset):
    bgm = load_bgm(path, offset)
    lines = json.load(open(os.path.join(ROOT, 'audio', 'lines.json'), encoding='utf-8'))
    vo = np.zeros((N, 2), np.float32)
    mask = np.zeros(N, np.float32)
    for line in lines:
        if line['start'] >= DUR:
            continue
        sr, clip = read_wav(os.path.join(ROOT, line['file']))
        clip = resample_linear(clip, sr, SR, 2)
        add_at(vo, clip, line['start'], 0.95)
        i = int(line['start'] * SR)
        j = min(N, i + len(clip))
        mask[i:j] = 1.0

    k = int(0.25 * SR)
    kernel = np.hanning(k)
    kernel /= kernel.sum()
    duck = np.clip(np.convolve(mask, kernel, mode='same') * 1.8, 0, 1)

    t = np.arange(N) / SR
    vol = np.interp(t, [0, 0.8, 8, 20], [0.0, 1.0, 0.95, 1.0])
    bed = bgm * vol[:, None] * (1.0 - 0.55 * duck[:, None])

    mix = vo + bed
    add_at(mix, synth_rumble(), 0.0, 0.9)
    add_at(mix, synth_click(), 0.48, 1.0)
    add_at(mix, synth_riser(), 0.55, 0.8)
    add_at(mix, synth_boom(), 1.25, 1.0)
    add_at(mix, synth_tick(), 8.0, 0.8)
    add_at(mix, synth_tick(), 15.0, 0.8)

    mix = mix / max(1e-6, np.max(np.abs(mix))) * 0.95
    raw = os.path.join('/tmp', f'audition_{name}_raw.wav')
    wavfile.write(raw, SR, (mix * 32767).astype(np.int16))

    loud = os.path.join('/tmp', f'audition_{name}_loud.wav')
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                    '-i', raw, '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
                    '-ar', str(SR), '-ac', '2', loud], check=True)

    out_dir = os.path.join(ROOT, 'out', 'bgm_tests')
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f'{name}.mp3')
    subprocess.run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                    '-i', loud, '-af', 'volume=2.8dB,alimiter=limit=0.68:level=false',
                    '-t', str(DUR), '-c:a', 'libmp3lame', '-b:a', '192k', out], check=True)
    print('wrote', out)


if __name__ == '__main__':
    for name, path, offset in CANDIDATES:
        build(name, path, offset)
