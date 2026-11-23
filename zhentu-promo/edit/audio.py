#!/usr/bin/env python3
"""真途 · 40 秒宣传片：原创配乐 + 音效 + 旁白混音。

输出：
    audio/music.wav   原创配乐（含音效）
    audio/mix.wav     最终混音（48kHz / 16bit / stereo）

依赖：numpy scipy soundfile
"""
import json
import os

import numpy as np
import soundfile as sf
from scipy import signal

SR = 48000
DUR = 40.0
N = int(SR * DUR)
BPM = 90
BEAT = 60 / BPM
BAR = 4 * BEAT

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUD = os.path.join(ROOT, 'audio')


def t_axis(dur):
    return np.arange(int(dur * SR)) / SR


def env_adsr(n, a=0.005, d=0.1, s=0.7, r=0.3, sus=0.7):
    e = np.ones(n) * sus
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    na = min(na, n)
    e[:na] = np.linspace(0, 1, na, endpoint=False)
    nd = min(nd, max(0, n - na))
    if nd:
        e[na:na + nd] = np.linspace(1, sus, nd, endpoint=False)
    nr = min(nr, n)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def lowpass(y, fc, order=2):
    sos = signal.butter(order, fc, 'low', fs=SR, output='sos')
    return signal.sosfilt(sos, y)


def highpass(y, fc, order=2):
    sos = signal.butter(order, fc, 'high', fs=SR, output='sos')
    return signal.sosfilt(sos, y)


def bandpass(y, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], 'band', fs=SR, output='sos')
    return signal.sosfilt(sos, y)


def piano(f0, dur=1.4, amp=1.0):
    tt = t_axis(dur)
    y = np.zeros_like(tt)
    for k, a, dec in [(1, 1.0, 2.2), (2, 0.5, 3.0), (3, 0.28, 4.0), (4, 0.13, 5.2), (5, 0.06, 6.0), (6, 0.03, 7.0)]:
        y += a * np.sin(2 * np.pi * f0 * k * tt + k * 0.4) * np.exp(-tt * dec)
    y *= (1 - np.exp(-tt / 0.004))
    y = lowpass(y, 3800)
    return y * amp


def pad_note(f0, dur, amp=1.0):
    tt = t_axis(dur)
    y = np.zeros_like(tt)
    for det in (-0.0035, 0.0, 0.0035):
        f = f0 * (1 + det)
        for k in range(1, 9):
            y += (1.0 / k) * np.sin(2 * np.pi * f * k * tt + k * 1.3 + det * 300)
    y = lowpass(y, 1100)
    a, r = 0.55, 0.9
    e = np.ones_like(tt)
    na, nr = min(len(tt), int(a * SR)), min(len(tt), int(r * SR))
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return y * e * amp / 6.0


def bass_note(f0, dur, amp=1.0):
    tt = t_axis(dur)
    y = np.sin(2 * np.pi * f0 * tt) + 0.25 * np.sin(2 * np.pi * f0 * 2 * tt)
    y *= (1 - np.exp(-tt / 0.006)) * np.exp(-tt * 0.55)
    return y * amp


def kick(amp=1.0):
    tt = t_axis(0.42)
    f = 48 + 70 * np.exp(-tt * 30)
    phase = 2 * np.pi * np.cumsum(f) / SR
    y = np.sin(phase) * np.exp(-tt * 7.0)
    click = np.random.default_rng(2).normal(0, 1, len(tt)) * np.exp(-tt * 120) * 0.15
    return (y + click) * amp


def clap(amp=1.0):
    n = int(0.32 * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(4)
    nz = rng.normal(0, 1, n)
    nz = bandpass(nz, 900, 4200)
    e = np.zeros(n)
    for at, g in [(0.0, 1.0), (0.028, 0.7), (0.058, 0.5)]:
        i = int(at * SR)
        e[i:] += g * np.exp(-(tt[:n - i]) * 42)
    return nz * e * amp * 0.55


def hat(amp=1.0):
    n = int(0.09 * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(5)
    nz = highpass(rng.normal(0, 1, n), 7000)
    return nz * np.exp(-tt * 55) * amp * 0.4


def shaker(amp=1.0):
    n = int(0.06 * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(6)
    nz = bandpass(rng.normal(0, 1, n), 4500, 10000)
    return nz * (1 - np.exp(-tt * 200)) * np.exp(-tt * 60) * amp * 0.28


def boom(amp=1.0):
    tt = t_axis(1.6)
    f = 34 + 40 * np.exp(-tt * 12)
    phase = 2 * np.pi * np.cumsum(f) / SR
    y = np.sin(phase) * np.exp(-tt * 3.0)
    rng = np.random.default_rng(11)
    nz = lowpass(rng.normal(0, 1, len(tt)), 180) * np.exp(-tt * 8) * 0.5
    return (y + nz) * amp


def stamp(amp=1.0):
    tt = t_axis(0.5)
    f = 60 + 50 * np.exp(-tt * 40)
    phase = 2 * np.pi * np.cumsum(f) / SR
    thud = np.sin(phase) * np.exp(-tt * 14)
    rng = np.random.default_rng(12)
    slap = lowpass(rng.normal(0, 1, len(tt)), 1800) * np.exp(-tt * 55) * 0.6
    return (thud + slap) * amp


def whoosh(amp=1.0, dur=0.45):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(13)
    nz = rng.normal(0, 1, n)
    y = np.zeros(n)
    for i in range(0, n, 1024):
        seg = nz[i:i + 1024]
        c = 500 + 3800 * (i / n)
        sos = signal.butter(2, [max(100, c * 0.5), min(20000, c * 1.8)], 'band', fs=SR, output='sos')
        y[i:i + 1024] = signal.sosfilt(sos, seg)
    e = np.sin(np.pi * np.linspace(0, 1, n)) ** 1.6
    return y * e * amp * 0.4


def tick(amp=1.0):
    tt = t_axis(0.06)
    y = np.sin(2 * np.pi * 1850 * tt) * np.exp(-tt * 90)
    y += 0.4 * np.sin(2 * np.pi * 3100 * tt) * np.exp(-tt * 120)
    return y * amp * 0.5


def chime(amp=1.0):
    tt = t_axis(1.4)
    y = np.zeros_like(tt)
    for f, a, d in [(880, 1.0, 2.2), (1320, 0.5, 2.8), (1760, 0.25, 3.4), (2640, 0.12, 4.2)]:
        y += a * np.sin(2 * np.pi * f * tt) * np.exp(-tt * d)
    y *= (1 - np.exp(-tt / 0.003))
    return y * amp * 0.5


def riser(amp=1.0, dur=1.3):
    n = int(dur * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(14)
    nz = rng.normal(0, 1, n)
    nz = highpass(nz, 1200)
    e = (tt / dur) ** 2.2
    f = 220 * (2 ** (tt / dur * 2))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.16
    return (nz * 0.22 + tone) * e * amp


def paper(amp=1.0):
    n = int(0.55 * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(15)
    nz = bandpass(rng.normal(0, 1, n), 900, 6000)
    e = (1 - np.exp(-tt * 60)) * np.exp(-tt * 8)
    return nz * e * amp * 0.35


def add(buf, sig, at, amp=1.0, pan=0.0):
    i = int(at * SR)
    if i >= N or i < 0:
        return
    sig = sig[:N - i]
    if sig.ndim == 1:
        l = np.cos((pan + 1) * np.pi / 4)
        r = np.sin((pan + 1) * np.pi / 4)
        buf[i:i + len(sig), 0] += sig * l * amp
        buf[i:i + len(sig), 1] += sig * r * amp
    else:
        buf[i:i + len(sig)] += sig * amp


def build_music():
    music = np.zeros((N, 2))
    send = np.zeros((N, 2))

    chords = {
        'D': [146.83, 185.00, 220.00],
        'A': [110.00, 138.59, 164.81],
        'Bm': [123.47, 146.83, 185.00],
        'G': [98.00, 123.47, 146.83],
    }
    roots = {'D': 73.42, 'A': 55.00, 'Bm': 61.74, 'G': 49.00}
    prog = ['D', 'A', 'Bm', 'G'] * 3 + ['D', 'A', 'D']

    for bar, ch in enumerate(prog):
        at = bar * BAR
        notes = chords[ch]
        intensity = 1.0
        if bar <= 2:
            intensity = 0.72
        if bar == 13:
            intensity = 0.62
        if bar == 14:
            intensity = 0.9

        # pad
        for j, f in enumerate(notes):
            sig = pad_note(f * 2, BAR + 0.7, amp=0.30 * intensity)
            add(music, sig, at, amp=0.9, pan=(-0.55 + j * 0.55))
            add(send, sig, at, amp=0.35)

        # piano arpeggio（八分音符）
        pattern = [0, 1, 2, 1, 0, 2, 1, 2]
        for k, idx in enumerate(pattern):
            f = notes[idx] * 2
            if bar >= 7 and k % 2 == 1:
                f *= 2
            amp = 0.30 if bar <= 2 else 0.25
            if bar == 13:
                amp = 0.30
            sig = piano(f, 1.1, amp=amp * intensity)
            add(music, sig, at + k * BEAT / 2, amp=0.85, pan=-0.25 + 0.12 * (k % 3))
            add(send, sig, at + k * BEAT / 2, amp=0.22)

        # bass
        if bar >= 4:
            b = bass_note(roots[ch], BEAT * 1.6, amp=0.24 * intensity)
            add(music, b, at, amp=1.0)
            add(music, b, at + 2 * BEAT, amp=0.85)

        # drums
        if 4 <= bar <= 12:
            add(music, kick(0.55 * intensity), at)
            add(music, kick(0.45 * intensity), at + 2 * BEAT)
            add(music, clap(0.45 * intensity), at + BEAT, pan=0.1)
            add(music, clap(0.5 * intensity), at + 3 * BEAT, pan=-0.1)
            for k in range(8):
                add(music, hat(0.10 if k % 2 else 0.16), at + k * BEAT / 2, pan=0.35)
            if bar >= 8:
                for k in range(16):
                    if k % 2:
                        add(music, shaker(0.5), at + k * BEAT / 4, pan=-0.3)
        if bar == 13:
            add(music, kick(0.35), at)
        if bar == 14:
            add(music, kick(0.5), at)

    # 高频长音（副歌）
    for bar, f in [(8, 587.33), (9, 554.37), (10, 493.88), (11, 440.00)]:
        at = bar * BAR
        tt = t_axis(BAR)
        sig = np.sin(2 * np.pi * f * tt) * np.minimum(1, tt / 0.5) * np.exp(-tt * 0.4)
        sig = lowpass(sig, 3000)
        add(music, sig, at, amp=0.07, pan=0.2)
        add(send, sig, at, amp=0.08)

    # ---------- SFX ----------
    sfx = np.zeros((N, 2))
    add(sfx, paper(0.9), 0.02, pan=-0.2)
    for at in [1.85, 3.02, 3.63, 4.24, 20.28]:
        add(sfx, stamp(0.8), at, pan=0.05)
    for at in [8.92, 21.4, 24.02, 26.7, 29.4, 32.02, 34.7]:
        add(sfx, whoosh(0.8, 0.4), at - 0.1, pan=-0.1)
    for at in [9.45, 11.4, 12.1, 14.2, 17.0, 18.2, 25.5, 33.0]:
        add(sfx, tick(0.35), at, pan=0.25)
    add(sfx, boom(0.75), 5.35)
    add(sfx, boom(0.55), 19.32)
    add(sfx, chime(0.5), 19.36, pan=0.1)
    add(sfx, chime(0.22), 20.28, pan=-0.1)
    add(sfx, riser(0.5, 1.1), 17.5)
    add(sfx, riser(0.45, 1.2), 35.9)
    add(sfx, boom(0.85), 37.35)
    add(sfx, chime(0.18), 37.45, pan=-0.15)

    # ---------- reverb ----------
    rng = np.random.default_rng(21)
    ir_n = int(1.9 * SR)
    tt = np.arange(ir_n) / SR
    ir = rng.normal(0, 1, (ir_n, 2)) * np.exp(-tt * 2.3)[:, None]
    ir = lowpass(ir[:, 0], 5500), lowpass(ir[:, 1], 5500)
    ir = np.stack(ir, axis=1)
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-9
    wet = np.stack([signal.fftconvolve(send[:, 0], ir[:, 0])[:N],
                    signal.fftconvolve(send[:, 1], ir[:, 1])[:N]], axis=1)
    music = music + wet * 0.45

    # 轻微 bus 压缩 / 饱和
    music = np.tanh(music * 1.25) / np.tanh(1.25)
    music *= 0.82
    peak = np.abs(music).max()
    music = music / (peak + 1e-9) * 0.89
    peak = np.abs(sfx).max()
    sfx = sfx / (peak + 1e-9) * 0.89
    return music, sfx


def load_vo():
    vo = np.zeros((N, 2))
    with open(os.path.join(AUD, 'vo', 'lines.json'), encoding='utf-8') as f:
        lines = json.load(f)
    for row in lines:
        p = os.path.join(AUD, 'vo', f"line_{row['i']:02d}.wav")
        y, sr = sf.read(p, dtype='float32')
        assert sr == SR
        # 高通 + 轻压缩 + 归一
        y = highpass(y, 75)
        rms = np.sqrt((y ** 2).mean() + 1e-9)
        y = y / rms * 0.075
        y = np.tanh(y * 1.3) / 1.3
        # 淡入淡出
        nf = min(len(y), int(0.012 * SR))
        y[:nf] *= np.linspace(0, 1, nf)
        y[-nf:] *= np.linspace(1, 0, nf)
        add(vo, y, row['target'], amp=1.0, pan=0.0)
    peak = np.abs(vo).max()
    if peak > 0.95:
        vo = vo / peak * 0.95
    return vo


def duck(music, vo):
    env = np.abs(vo[:, 0]) + np.abs(vo[:, 1])
    # 平滑包络
    win = int(0.10 * SR)
    ker = np.hanning(win)
    ker /= ker.sum()
    env = np.convolve(env, ker, mode='same')
    env = np.clip(env * 11, 0, 1)
    gain = 1.0 - 0.42 * env
    return music * gain[:, None]


def main():
    os.makedirs(AUD, exist_ok=True)
    music, sfx = build_music()
    vo = load_vo()
    music = duck(music, vo)
    mix = music * 0.26 + sfx * 0.75 + vo * 3.2
    # 软限幅 + 母带
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)
    mix = np.stack([highpass(mix[:, 0], 32), highpass(mix[:, 1], 32)], axis=1)
    try:
        import pyloudnorm as pyln
        meter = pyln.Meter(SR)
        lufs = meter.integrated_loudness(mix)
        gain_db = -14.0 - lufs
        mix *= 10 ** (gain_db / 20)
        # 限制真峰
        peak = np.abs(mix).max()
        if peak > 0.89:
            mix *= 0.89 / peak
        print('loudness before', round(lufs, 2), 'gain', round(gain_db, 2))
    except Exception as e:
        peak = np.abs(mix).max()
        mix = mix / (peak + 1e-9) * 0.89
        print('loudnorm fallback', e)

    sf.write(os.path.join(AUD, 'music.wav'), music, SR, subtype='PCM_16')
    sf.write(os.path.join(AUD, 'sfx.wav'), sfx, SR, subtype='PCM_16')
    sf.write(os.path.join(AUD, 'vo.wav'), vo, SR, subtype='PCM_16')
    sf.write(os.path.join(AUD, 'mix.wav'), mix, SR, subtype='PCM_16')
    print('music rms', float(np.sqrt((music ** 2).mean())), 'peak', float(np.abs(music).max()))
    print('vo rms', float(np.sqrt((vo ** 2).mean())), 'peak', float(np.abs(vo).max()))
    print('mix peak', float(np.abs(mix).max()))
    print('wrote audio/music.wav audio/mix.wav')


if __name__ == '__main__':
    main()
