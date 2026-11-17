#!/usr/bin/env python3
"""24 s / 120 BPM procedural beat for the guichu-beat demo.

C major, C-Am-F-G loop, 12 bars.  Drums are written on the 16th-note grid so
every cut in the edit can land on a grid line.  Output: assets/beat.wav
"""
import wave

import numpy as np
from scipy import signal

SR = 48000
DURATION = 24.0
BPM = 120
BEAT = 60.0 / BPM
BAR = 4 * BEAT
STEP = BEAT / 4
N = int(SR * DURATION)
OUT = "/workspace/demo/guichu-beat/assets/beat.wav"

rng = np.random.default_rng(20261117)


def filt(x, kind, cutoff, order=2):
    sos = signal.butter(order, cutoff, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def t_axis(dur):
    return np.arange(int(dur * SR), dtype=np.float64) / SR


def add(buf, sig, start, gain=1.0, pan=0.0):
    i0 = int(round(start * SR))
    if i0 >= N:
        return
    if i0 < 0:
        sig = sig[-i0:]
        i0 = 0
    i1 = min(N, i0 + len(sig))
    seg = sig[: i1 - i0]
    gl = np.sqrt(0.5 * (1.0 - pan))
    gr = np.sqrt(0.5 * (1.0 + pan))
    buf[i0:i1, 0] += seg * gain * gl
    buf[i0:i1, 1] += seg * gain * gr


def norm(x, peak=1.0):
    return x * (peak / (np.max(np.abs(x)) + 1e-9))


def kick():
    t = t_axis(0.5)
    f = 46.0 + 130.0 * np.exp(-t * 30.0)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 8.0)
    click = filt(rng.standard_normal(len(t)), "highpass", 1800) * np.exp(-t * 90.0) * 0.25
    return norm(body + click)


def snare():
    t = t_axis(0.22)
    noise = filt(rng.standard_normal(len(t)), "bandpass", [500, 6800])
    body = noise * np.exp(-t * 18.0)
    tone = np.sin(2 * np.pi * 195 * t) * np.exp(-t * 24.0) * 0.5
    return norm(body + tone)


def hat(open_=False):
    dur = 0.13 if open_ else 0.05
    t = t_axis(dur)
    n = filt(rng.standard_normal(len(t)), "highpass", 7000)
    return norm(n * np.exp(-t * (20.0 if open_ else 80.0)))


def clap():
    t = t_axis(0.18)
    out = np.zeros_like(t)
    for d in (0.0, 0.016, 0.032):
        s = int(d * SR)
        n = filt(rng.standard_normal(len(t) - s), "bandpass", [800, 5200])
        out[s:] += n * np.exp(-np.arange(len(t) - s) / SR * 34.0)
    return norm(out)


def crash(dur=1.6):
    t = t_axis(dur)
    n = filt(rng.standard_normal(len(t)), "highpass", 4500)
    return norm(n * np.exp(-t * 3.2))


NOTE = {n: 440.0 * 2 ** (v / 12) for n, v in {
    "C2": -36, "D2": -34, "E2": -32, "F2": -31, "G2": -29, "A2": -27, "B2": -25,
    "C3": -24, "D3": -22, "E3": -20, "F3": -19, "G3": -17, "A3": -15, "B3": -13,
    "C4": -12, "D4": -10, "E4": -8, "F4": -7, "G4": -5, "A4": -3, "B4": -1,
    "C5": 0, "D5": 2, "E5": 4, "F5": 5, "G5": 7,
}.items()}


def saw_note(freq, dur, cutoff=2800, decay=6.0, detune=0.01):
    t = t_axis(dur)
    x = np.zeros(len(t))
    for d in (-detune, 0.0, detune):
        ph = (t * freq * (1 + d)) % 1.0
        x += ph * 2.0 - 1.0
    x /= 3.0
    x = filt(x, "lowpass", cutoff)
    x *= np.exp(-t * decay)
    a = int(0.006 * SR)
    x[:a] *= np.linspace(0, 1, a)
    return x


def bass_note(freq, dur):
    t = t_axis(dur)
    ph = (t * freq) % 1.0
    x = filt(ph * 2.0 - 1.0, "lowpass", 260, order=3)
    x = np.tanh(x * 1.8)
    x *= np.exp(-t * 3.5)
    return x


def pad_chord(freqs, dur):
    t = t_axis(dur)
    x = np.zeros(len(t))
    for f in freqs:
        for d in (-0.004, 0.0, 0.004):
            x += np.sin(2 * np.pi * f * (1 + d) * t + rng.uniform(0, 6.28))
    x = filt(x, "lowpass", 1500) / (len(freqs) * 3)
    env = np.minimum(1.0, t / 0.25) * np.minimum(1.0, (dur - t) / 0.35)
    return x * env


KICK, SNARE, HAT, HATO, CLAP = kick(), snare(), hat(), hat(True), clap()
CRASH = crash()

music = np.zeros((N, 2))
bass_buf = np.zeros((N, 2))
arp_buf = np.zeros((N, 2))

# C - Am - F - G
PROG = [
    ("C2", ["C4", "E4", "G4"]),
    ("A2", ["A3", "C4", "E4"]),
    ("F2", ["F3", "A3", "C4"]),
    ("G2", ["G3", "B3", "D4"]),
]
ENERGY = [0.90, 0.92, 0.96, 1.00, 1.02, 1.04, 1.06, 1.08, 1.10, 1.12, 1.12, 1.12]

for bar in range(12):
    t0 = bar * BAR
    root_name, chord = PROG[bar % 4]
    root = NOTE[root_name]
    e = ENERGY[bar]

    # pad
    add(music, pad_chord([NOTE[n] for n in chord], BAR), t0, 0.16 * e)

    # kick grid: 0, 3, 6, 10 (+ 14 on odd bars)
    for s, g in ((0, 1.0), (3, 0.78), (6, 0.88), (10, 0.84)):
        add(music, KICK, t0 + s * STEP, g * e)
    if bar % 2 == 1:
        add(music, KICK, t0 + 14 * STEP, 0.55 * e)

    # snare backbeat + ghost notes
    for s in (4, 12):
        add(music, SNARE, t0 + s * STEP, 0.62 * e)
        add(music, CLAP, t0 + s * STEP, 0.26 * e)
    for s in (7, 15):
        add(music, SNARE, t0 + s * STEP, 0.14 * e)

    # hats on every 16th, accented on the quarter
    for s in range(16):
        if s == 14 and bar % 2 == 1:
            add(music, HATO, t0 + s * STEP, 0.22 * e, pan=-0.2)
        else:
            acc = 0.30 if s % 4 == 0 else 0.16
            add(music, HAT, t0 + s * STEP, acc * e, pan=0.22 if s % 2 else -0.18)

    # bass on the 16th grid
    for s, ratio, length, g in (
        (0, 1.0, 0.34, 0.52), (3, 1.0, 0.20, 0.40), (6, 1.5, 0.26, 0.46),
        (8, 1.0, 0.30, 0.50), (11, 2.0, 0.18, 0.38), (14, 1.5, 0.22, 0.42),
    ):
        add(bass_buf, bass_note(root * ratio, length), t0 + s * STEP, g * e)

    # 16th arpeggio from bar 4 on, gives the top end constant motion
    if bar >= 4:
        tones = [NOTE[n] for n in chord] + [NOTE[chord[0]] * 2]
        order = [0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1, 0, 2, 1, 2]
        for s in range(16):
            f = tones[order[s] % len(tones)]
            add(arp_buf, saw_note(f, 0.16, cutoff=3400, decay=9.0),
                t0 + s * STEP, 0.085 * e, pan=0.18 if s % 2 else -0.18)

# accents
add(music, CRASH, 0.0, 0.75)
add(music, CRASH, 16.0, 0.6)
for i, s in enumerate(np.linspace(22.0, 24.0, 9)[:-1]):
    add(music, SNARE, s, 0.18 + i * 0.045)
add(music, CRASH, 23.9, 0.45)

mix = music + bass_buf + arp_buf
mix = np.stack([filt(mix[:, c], "highpass", 26) for c in range(2)], axis=1)
mix = np.tanh(mix * 0.95)
mix *= np.minimum(1.0, np.arange(N) / (0.03 * SR))[:, None]
mix *= np.minimum(1.0, (N - np.arange(N)) / (0.3 * SR))[:, None]
mix = norm(mix, 0.90)

with wave.open(OUT, "wb") as f:
    f.setnchannels(2)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes((mix * 32767).astype(np.int16).tobytes())

print("wrote", OUT, "rms", round(float(np.sqrt(np.mean(mix ** 2))), 4),
      "peak", round(float(np.max(np.abs(mix))), 3))
