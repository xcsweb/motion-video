#!/usr/bin/env python3
"""Mix voice-over, BGM and synthesized SFX; write SRT and a normalized 48k WAV."""
import json
import os
import subprocess
import wave

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
DUR = 80.0
N = int(SR * DUR)


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


def env_ar(n, attack, release):
    t = np.arange(n) / SR
    a = np.clip(t / max(1e-4, attack), 0, 1)
    r = np.clip((t[-1] - t) / max(1e-4, release), 0, 1)
    return (a * a * (3 - 2 * a)) * (r * r * (3 - 2 * r))


def synth_boom():
    n = int(1.8 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 48 * t) * np.exp(-t * 3.2)
    y += 0.4 * np.sin(2 * np.pi * 72 * t) * np.exp(-t * 4.5)
    y += 0.15 * np.random.default_rng(1).normal(0, 1, n) * np.exp(-t * 12)
    return np.stack([y, y], axis=1) * 0.55


def synth_click():
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 1600 * t) * np.exp(-t * 90)
    y += 0.5 * np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 120)
    return np.stack([y, y], axis=1) * 0.35


def synth_riser(dur=2.4):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(2)
    noise = rng.normal(0, 1, n)
    sos = butter(2, [300, 6000], btype='band', fs=SR, output='sos')
    noise = sosfilt(sos, noise)
    env = (t / dur) ** 2
    y = noise * env * 0.22
    return np.stack([y, y], axis=1)


def synth_tick():
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 120)
    return np.stack([y, y], axis=1) * 0.18


def synth_drone(dur=24.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(4)
    air = rng.normal(0, 1, n)
    air = sosfilt(butter(2, [120, 1800], btype='band', fs=SR, output='sos'), air) * 0.08
    y = 0.5 * np.sin(2 * np.pi * 55 * t) + 0.22 * np.sin(2 * np.pi * 82.5 * t) + air
    y *= 0.55 + 0.45 * np.sin(2 * np.pi * 0.07 * t)
    return np.stack([y, y], axis=1) * 0.5


def synth_rumble(dur=3.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(3)
    y = rng.normal(0, 1, n)
    sos = butter(2, 120, btype='low', fs=SR, output='sos')
    y = sosfilt(sos, y)
    y = y * np.minimum(1, t / 0.8) * np.exp(-np.maximum(0, t - 2.0) * 1.5)
    return np.stack([y, y], axis=1) * 0.5


def main():
    os.makedirs(os.path.join(ROOT, 'audio'), exist_ok=True)
    # BGM -> wav
    bgm_wav = os.path.join(ROOT, 'audio', 'bgm.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', os.path.join(ROOT, 'audio', 'bgm.mp3'),
        '-t', str(DUR), '-ar', str(SR), '-ac', '2', bgm_wav,
    ], check=True)
    _, bgm = read_wav(bgm_wav)
    bgm = resample_linear(bgm, SR, SR, 2)[:N]
    if len(bgm) < N:
        bgm = np.pad(bgm, ((0, N - len(bgm)), (0, 0)))

    lines = json.load(open(os.path.join(ROOT, 'audio', 'lines.json'), encoding='utf-8'))
    vo = np.zeros((N, 2), np.float32)
    vo_mask = np.zeros(N, np.float32)
    for line in lines:
        sr, clip = read_wav(os.path.join(ROOT, line['file']))
        clip = resample_linear(clip, sr, SR, 2)
        add_at(vo, clip, line['start'], 0.95)
        i = int(line['start'] * SR)
        j = min(N, i + len(clip))
        vo_mask[i:j] = 1.0

    # smooth duck mask
    k = int(0.25 * SR)
    kernel = np.hanning(k)
    kernel /= kernel.sum()
    duck = np.convolve(vo_mask, kernel, mode='same')
    duck = np.clip(duck * 1.8, 0, 1)

    # BGM volume envelope: opening, lift at 29s, resolve at 73s
    t = np.arange(N) / SR
    vol = np.interp(t, [0, 1.5, 8, 29, 54, 73, 77.5, 80], [0.0, 0.15, 0.20, 0.26, 0.28, 0.28, 0.12, 0.0])
    bed = bgm * vol[:, None] * (1.0 - 0.62 * duck[:, None])

    drone = synth_drone()
    denv = np.interp(t[:len(drone)], [0, 2, 16, 22], [0.0, 1.0, 0.75, 0.0])
    bed[:len(drone)] += drone * denv[:, None] * 0.16

    mix = vo + bed
    # SFX
    boom = synth_boom(); click = synth_click(); riser = synth_riser(); tick = synth_tick(); rumble = synth_rumble()
    add_at(mix, rumble, 0.0, 0.9)
    add_at(mix, click, 0.48, 1.0)
    add_at(mix, riser, 0.55, 0.8)
    add_at(mix, boom, 1.25, 1.0)
    add_at(mix, tick, 8.0, 0.8)
    add_at(mix, tick, 15.0, 0.8)
    add_at(mix, tick, 20.0, 0.8)
    add_at(mix, tick, 39.0, 0.8)
    add_at(mix, tick, 44.0, 0.8)
    add_at(mix, riser, 27.0, 0.6)
    add_at(mix, boom, 29.0, 0.55)
    add_at(mix, riser, 52.0, 0.5)
    add_at(mix, boom, 54.0, 0.5)
    add_at(mix, rumble, 73.0, 0.35)

    peak = np.max(np.abs(mix))
    mix = mix / max(1e-6, peak) * 0.95
    raw = os.path.join(ROOT, 'audio', 'mix_raw.wav')
    wavfile.write(raw, SR, (mix * 32767).astype(np.int16))

    loud = os.path.join(ROOT, 'audio', 'mix_loud.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', raw,
        '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
        '-ar', str(SR), '-ac', '2', loud,
    ], check=True)
    out = os.path.join(ROOT, 'audio', 'mix.wav')
    subprocess.run([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', loud,
        '-af', 'volume=2.8dB,alimiter=limit=0.68:level=false',
        '-ar', str(SR), '-ac', '2', out,
    ], check=True)
    print('wrote', out)

    # SRT
    def ts(x):
        h = int(x // 3600); m = int((x % 3600) // 60); s = int(x % 60); ms = int(round((x - int(x)) * 1000))
        return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    srt = []
    for i, line in enumerate(lines, 1):
        end = line['end']
        if i < len(lines):
            end = min(end, lines[i]['start'] - 0.05)
        srt.append(f'{i}\n{ts(line["start"])} --> {ts(end)}\n{line["subtitle"].replace("／", "")}\n')
    srt_path = os.path.join(ROOT, 'out', 'guidao_promo.srt')
    os.makedirs(os.path.dirname(srt_path), exist_ok=True)
    with open(srt_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(srt))
    print('wrote', srt_path)


if __name__ == '__main__':
    main()
