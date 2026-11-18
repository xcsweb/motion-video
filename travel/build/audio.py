#!/usr/bin/env python3
"""Build the 52 s score and the final mix (piano + pad + wind + voice-over).

Everything is synthesized here: no external music, no licensed samples.
"""
import json
import os
import wave

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
DUR = 52.0
N = int(SR * DUR)
BAR = 4.0
BPM = 60

CFG = json.load(open(os.path.join(ROOT, "config", "timeline.json"), encoding="utf-8"))
VO_DIR = os.path.join(ROOT, "assets", "vo")
OUT_DIR = os.path.join(ROOT, "assets", "audio")

CHORDS = {
    "Am": [45, 52, 57, 60, 64],
    "F": [41, 48, 53, 57, 60],
    "C": [48, 55, 60, 64, 67],
    "G": [43, 50, 55, 59, 62],
}
PROG = ["Am", "F", "C", "G", "Am", "F", "C", "G", "F", "G", "Am", "F", "C"]


def mtof(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def env_ar(n, attack, release, sr=SR):
    t = np.arange(n) / sr
    a = np.clip(t / max(1e-4, attack), 0, 1)
    r = np.clip((t[-1] - t) / max(1e-4, release), 0, 1)
    a = a * a * (3 - 2 * a)
    r = r * r * (3 - 2 * r)
    return a * r


def lowpass(sig, cutoff, order=2, sr=SR):
    sos = butter(order, cutoff / (sr / 2), btype="low", output="sos")
    return sosfilt(sos, sig, axis=0)


def highpass(sig, cutoff, order=2, sr=SR):
    sos = butter(order, cutoff / (sr / 2), btype="high", output="sos")
    return sosfilt(sos, sig, axis=0)


def pan_gains(pan):
    p = (max(-1.0, min(1.0, pan)) + 1) * 0.5
    return np.sqrt(1 - p), np.sqrt(p)


# ---------------------------------------------------------------- piano
def piano_note(freq, dur, vel, pan, rng):
    n = int((dur + 1.9) * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, np.float64)
    stretch = 0.00038
    for k in range(1, 9):
        fk = freq * k * np.sqrt(1 + stretch * k * k)
        if fk > 15000:
            break
        amp = (1.0 / k ** 1.75) * (0.55 + 0.45 * vel) ** (k * 0.22)
        dec = 0.95 + 0.52 * k + 0.35 * (1 - vel)
        e = np.exp(-t * dec) * (1 - np.exp(-t / 0.0035))
        out += amp * e * np.sin(2 * np.pi * fk * t + rng.uniform(0, 2 * np.pi))
    # felt hammer: a short low-passed noise tick
    hn = int(0.035 * SR)
    tick = rng.normal(0, 1, hn) * np.exp(-np.arange(hn) / (0.006 * SR))
    tick = lowpass(tick, 2500, 1)
    out[:hn] += tick * 0.22 * vel
    out = lowpass(out, 3600, 2)
    gl, gr = pan_gains(pan)
    return np.stack([out * gl, out * gr], axis=1) * vel


def melody_events():
    """(bar, beat, midi, beats, velocity) — a plain, singable motif."""
    return [
        (2, 0.0, 76, 1.5, .42), (2, 1.5, 74, .5, .34), (2, 2.0, 72, 2.0, .38),
        (3, 0.0, 74, 2.0, .40), (3, 2.0, 71, 2.0, .34),
        (4, 0.0, 76, 1.0, .46), (4, 1.0, 81, 1.0, .52),
        (4, 2.0, 79, 1.0, .46), (4, 3.0, 76, 1.0, .40),
        (5, 0.0, 77, 1.5, .46), (5, 1.5, 76, .5, .36), (5, 2.0, 72, 2.0, .38),
        (6, 0.0, 74, 1.0, .42), (6, 1.0, 76, 1.0, .46), (6, 2.0, 79, 2.0, .50),
        (7, 0.0, 74, 2.0, .44), (7, 2.0, 71, 2.0, .36),
        (8, 0.0, 81, 1.0, .54), (8, 1.0, 79, 1.0, .48), (8, 2.0, 76, 2.0, .44),
        (9, 0.0, 74, 1.0, .44), (9, 1.0, 76, 1.0, .48),
        (9, 2.0, 74, 1.0, .40), (9, 3.0, 71, 1.0, .34),
        (10, 0.0, 69, 3.0, .36),
        (11, 0.0, 72, 2.0, .34), (11, 2.0, 76, 2.0, .36),
        (12, 0.0, 72, 4.0, .32),
    ]


def build_piano(rng):
    out = np.zeros((N, 2), np.float64)
    events = []
    # left hand: root on beats 1 and 3
    for bar, name in enumerate(PROG):
        root = CHORDS[name][0]
        for beat in (0.0, 2.0):
            events.append((bar * BAR + beat, mtof(root), 2.4, 0.26, -0.18))
    # broken chord: eighth notes, sparse at first, fuller later
    for bar, name in enumerate(PROG):
        if not (1 <= bar <= 10):
            continue
        notes = CHORDS[name]
        pattern = [0, 2, 3, 1, 2, 4, 3, 1]
        for j, idx in enumerate(pattern):
            if bar <= 2 and j % 2 == 1:
                continue
            if bar >= 9 and j in (5, 7):
                continue
            midi = notes[idx] + 12
            t0 = bar * BAR + j * 0.5 + rng.normal(0, 0.006)
            vel = 0.10 + 0.045 * rng.random() + (0.012 if bar >= 9 else 0)
            events.append((t0, mtof(midi), 0.85, vel, -0.35 + 0.18 * (idx / 4)))
    # melody
    for bar, beat, midi, beats, vel in melody_events():
        events.append((bar * BAR + beat, mtof(midi), beats * 0.95, vel,
                       -0.12 + rng.normal(0, 0.05)))
        if bar in (8, 9):  # one octave up, very soft
            events.append((bar * BAR + beat, mtof(midi + 12), beats * 0.9,
                           vel * 0.22, 0.22))

    for t0, freq, dur, vel, pan in sorted(events):
        note = piano_note(freq, dur, vel, pan, rng)
        i = int(t0 * SR)
        if i >= N:
            continue
        j = min(N, i + len(note))
        out[i:j] += note[:j - i]
    return out


# ---------------------------------------------------------------- pad / sub
def build_pad():
    out = np.zeros((N, 2), np.float64)
    for bar, name in enumerate(PROG):
        notes = CHORDS[name]
        t0 = bar * BAR
        length = BAR + 1.4
        n = int(length * SR)
        t = np.arange(n) / SR
        e = env_ar(n, 1.4, 1.6)
        # wider and slightly louder at the climax
        boost = 1.20 if bar in (9, 10) else 1.0
        for idx, midi in enumerate(notes):
            f = mtof(midi)
            for det in (-0.0035, 0.0, 0.0035):
                ph = (bar * 7 + idx) * 1.7
                sig = (np.sin(2 * np.pi * f * (1 + det) * t + ph)
                       + 0.28 * np.sin(2 * np.pi * 2 * f * (1 + det) * t + ph * 1.3)
                       + 0.12 * np.sin(2 * np.pi * 3 * f * (1 + det) * t + ph * 0.7))
                sig = lowpass(sig, 1500, 2)
                amp = 0.050 * boost / (1 + idx * 0.35)
                gl, gr = pan_gains(-0.5 + idx * 0.25 + det * 40)
                buf = sig * e * amp
                i = int(t0 * SR)
                j = min(N, i + n)
                out[i:j, 0] += buf[:j - i] * gl
                out[i:j, 1] += buf[:j - i] * gr
        # airy fifth two octaves up
        if 3 <= bar <= 11:
            f = mtof(notes[2] + 24)
            sig = np.sin(2 * np.pi * f * t) * 0.012 * e
            i = int(t0 * SR)
            j = min(N, i + n)
            out[i:j, 0] += sig[:j - i]
            out[i:j, 1] += sig[:j - i]
    return out


def build_sub():
    out = np.zeros((N, 2), np.float64)
    for bar, name in enumerate(PROG):
        f = mtof(CHORDS[name][0] - 12)
        n = int(4.6 * SR)
        t = np.arange(n) / SR
        e = env_ar(n, 1.1, 1.6)
        sig = np.sin(2 * np.pi * f * t) * e * (0.10 if bar < 8 else 0.13)
        i = int(bar * BAR * SR)
        j = min(N, i + n)
        out[i:j] += sig[:j - i, None]
    return out


# ---------------------------------------------------------------- texture
def build_textures(rng):
    t = np.arange(N) / SR
    # wind: filtered noise with slow breathing
    wind = rng.normal(0, 1, N)
    wind = lowpass(wind, 420, 2)
    wind = highpass(wind, 55, 2)
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * 0.037 * t + 0.6)
    lfo *= 0.75 + 0.25 * np.sin(2 * np.pi * 0.011 * t + 2.1)
    wl = wind * lfo * 0.020
    wr = np.roll(wind, 3111) * np.roll(lfo, 977) * 0.020
    # vinyl crackle
    crack = np.zeros(N)
    idx = rng.integers(0, N, int(DUR * 1.7))
    crack[idx] = rng.normal(0, 1, len(idx)) * rng.uniform(0.2, 1.0, len(idx))
    crack = highpass(crack, 1200, 1) * 0.005
    # tape hiss
    hiss = lowpass(rng.normal(0, 1, N), 9000, 1) * 0.0022
    return np.stack([wl + crack * 0.8 + hiss, wr + crack + hiss], axis=1)


# ---------------------------------------------------------------- reverb
def make_ir(rng, seconds=3.2):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n, 2))
    for ch in range(2):
        noise = rng.normal(0, 1, n)
        noise = lowpass(noise, 5200, 2)
        e = np.exp(-t / 0.85)
        e[:int(0.022 * SR)] = 0
        ir[:, ch] = noise * e
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True))
    return ir


def reverb(sig, ir, wet):
    out = np.zeros_like(sig)
    for ch in range(2):
        w = fftconvolve(sig[:, ch], ir[:, ch])[:len(sig)]
        out[:, ch] = w
    return sig + wet * out


# ---------------------------------------------------------------- voice
def load_vo(path):
    with wave.open(path, "rb") as f:
        sr = f.getframerate()
        data = np.frombuffer(f.readframes(f.getnframes()), np.int16).astype(np.float64) / 32768
    data = resample_poly(data, SR, sr)
    # trim leading/trailing silence
    idx = np.where(np.abs(data) > 0.008)[0]
    if len(idx):
        data = data[max(0, idx[0] - int(0.04 * SR)): idx[-1] + int(0.06 * SR)]
    return data


def build_voice(ir, rng):
    out = np.zeros((N, 2), np.float64)
    timing = json.load(open(os.path.join(VO_DIR, "timing.json"), encoding="utf-8"))
    for item in timing:
        y = load_vo(os.path.join(VO_DIR, item["file"]))
        y = highpass(y, 95, 2)
        # presence
        band = highpass(lowpass(y, 4200, 2), 2200, 2)
        y = y + band * 0.30
        # gentle compression
        env = np.clip(lowpass(np.abs(y), 9, 2), 1e-6, None)
        thr = 0.07
        gain = np.where(env > thr, (env / thr) ** (1 / 3.0 - 1), 1.0)
        gain = np.clip(gain, 0.35, 1.0)
        y = y * gain
        y = np.tanh(y * 1.25) / 1.25
        peak = np.max(np.abs(y)) + 1e-9
        y = y / peak * 0.55
        y = np.stack([y, y], axis=1)
        y = reverb(y, ir, 0.16)
        y *= np.linspace(1, 1, len(y))[:, None]
        f = int(0.012 * SR)
        y[:f] *= np.linspace(0, 1, f)[:, None]
        y[-f:] *= np.linspace(1, 0, f)[:, None]
        start = int(CFG["voice"][item["i"] - 1]["t"] * SR)
        j = min(N, start + len(y))
        out[start:j] += y[:j - start]
    return out


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(20261118)
    print("piano ...")
    piano = build_piano(rng)
    print("pad / sub ...")
    pad = build_pad()
    sub = build_sub()
    texture = build_textures(rng)
    ir = make_ir(rng)

    print("reverb ...")
    piano = reverb(piano, ir, 0.34)
    pad = reverb(pad, ir, 0.55)
    sub = reverb(sub, ir, 0.08)

    bed = piano * 0.62 + pad + sub + texture
    bed = np.tanh(bed * 1.1) / 1.1

    print("voice ...")
    voice = build_voice(ir, rng)

    # duck the bed under the voice, smoothly
    env = lowpass(np.abs(voice.mean(axis=1)), 3.2, 2)
    env = env / (env.max() + 1e-9)
    duck = 1.0 - 0.65 * np.clip(env * 1.8, 0, 1)

    bed_gain = 0.28
    bed_mix = bed * duck[:, None] * bed_gain
    mix = bed_mix + voice * 1.15

    # stems for level checks
    wavfile.write(os.path.join(OUT_DIR, "_bed.wav"), SR,
                  (bed_mix * 32767).astype(np.int16))
    wavfile.write(os.path.join(OUT_DIR, "_voice.wav"), SR,
                  (voice * 32767).astype(np.int16))
    # global fades
    fi = int(1.6 * SR)
    fo = int(2.4 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    mix = np.tanh(mix * 1.05)
    mix = mix / (np.max(np.abs(mix)) + 1e-9) * 0.92

    wavfile.write(os.path.join(OUT_DIR, "bgm.wav"), SR,
                  (bed / (np.max(np.abs(bed)) + 1e-9) * 0.92 * 32767).astype(np.int16))
    wavfile.write(os.path.join(OUT_DIR, "mix.wav"), SR,
                  (mix * 32767).astype(np.int16))
    print("wrote", os.path.join(OUT_DIR, "mix.wav"), mix.shape, f"{len(mix)/SR:.2f}s")


if __name__ == "__main__":
    main()
