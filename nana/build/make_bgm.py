#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""《同一个 nana，两种命》原创 BGM 生成器。

128 BPM / 48 kHz / 立体声 / 35.000 s，全部声音用 numpy + scipy 程序化合成，
不使用任何采样、loop 或版权素材。运行本脚本会生成：

  nana/assets/audio/bgm.wav
  nana/config/beatmap.json

依赖：numpy, scipy, ffmpeg / ffprobe（用于 LUFS、真峰值测量与校验）。
"""

import json
import math
import os
import re
import subprocess
import sys
import wave

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d

SR = 48000
DUR = 35.0
N = int(round(SR * DUR))  # 1_680_000
BPM = 128
BEAT = 60.0 / BPM            # 0.46875
BAR = BEAT * 4               # 1.875
EIGHTH = BEAT / 2            # 0.234375
SIXTEENTH = BEAT / 4         # 0.1171875
THIRTY2 = BEAT / 8           # 0.05859375

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../nana
ASSET_WAV = os.path.join(ROOT, "assets", "audio", "bgm.wav")
BEATMAP_JSON = os.path.join(ROOT, "config", "beatmap.json")

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

rng_global = np.random.default_rng(20261125)


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------

def midi_hz(m):
    return 440.0 * 2.0 ** ((m - 69) / 12.0)


def db(x):
    return 10.0 ** (x / 20.0)


def tline(dur):
    return np.arange(int(round(dur * SR))) / SR


def noise(n, seed=0):
    return np.random.default_rng(seed).standard_normal(n)


def filt(x, kind, freq, order=2):
    nyq = SR / 2.0
    if kind == "hp":
        f = max(20.0, min(freq, nyq * 0.95))
        sos = signal.butter(order, f, "highpass", fs=SR, output="sos")
    elif kind == "lp":
        f = max(20.0, min(freq, nyq * 0.95))
        sos = signal.butter(order, f, "lowpass", fs=SR, output="sos")
    elif kind == "bp":
        lo, hi = freq
        lo = max(20.0, lo)
        hi = min(hi, nyq * 0.95)
        if hi <= lo * 1.02:
            hi = lo * 1.05
        sos = signal.butter(order, [lo, hi], "bandpass", fs=SR, output="sos")
    else:
        raise ValueError(kind)
    return signal.sosfilt(sos, x)


def fade_edges(x, a=0.003, r=0.006):
    n = len(x)
    na, nr = min(int(a * SR), n), min(int(r * SR), n)
    if na > 0:
        x[:na] *= np.linspace(0.0, 1.0, na)
    if nr > 0:
        x[-nr:] *= np.linspace(1.0, 0.0, nr)
    return x


class Bus:
    """(2, N) 立体声总线，add() 叠加单声道信号。"""

    def __init__(self):
        self.x = np.zeros((2, N), dtype=np.float64)

    def add(self, sig, t, gain=1.0, pan=0.0):
        i = int(round(t * SR))
        if i >= N or i < 0:
            return
        n = min(len(sig), N - i)
        if n <= 0:
            return
        pan = float(np.clip(pan, -1.0, 1.0))
        gl = math.sqrt(0.5) * math.cos(pan * math.pi / 4) * math.sqrt(2) * 0.70710678
        gr = math.sqrt(0.5) * math.sin(pan * math.pi / 4) * math.sqrt(2) * 0.70710678
        self.x[0, i:i + n] += sig[:n] * gain * gl
        self.x[1, i:i + n] += sig[:n] * gain * gr


# ----------------------------------------------------------------------------
# 乐器 / 音效合成（全部噪声+正弦，无采样）
# ----------------------------------------------------------------------------

def saw_add(freq, dur, nh=12, detune=0.0, phase_rand=0.0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    f = freq * (1.0 + detune)
    for h in range(1, nh + 1):
        fh = f * h
        if fh > 18500:
            break
        out += np.sin(2 * np.pi * fh * t + 0.7 * h + phase_rand) / h
    return out


def kick(dur=0.48, f0=150.0, f1=45.0, ptau=0.028, atau=0.13,
         drive=2.0, click=0.5, seed=1):
    t = tline(dur)
    f = f1 + (f0 - f1) * np.exp(-t / ptau)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / atau)
    body = np.tanh(drive * body) / np.tanh(drive)
    ck = noise(len(t), seed) * np.exp(-t / 0.0035)
    ck = filt(ck, "hp", 1800)
    att = max(int(0.0015 * SR), 1)
    body[:att] *= np.linspace(0, 1, att)
    out = body + ck * click * 0.55
    return fade_edges(out, 0.001, 0.01)


def trap_kick(dur=0.55, seed=2):
    x = kick(dur=dur, f0=170.0, f1=42.0, ptau=0.022, atau=0.17,
             drive=3.0, click=0.75, seed=seed)
    return x


def sub808(freq, dur, glide=1.45, glide_tau=0.055, drive=3.2, seed=3):
    t = tline(dur)
    f = freq * (1.0 + (glide - 1.0) * np.exp(-t / glide_tau))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t / (dur * 0.55))
    x = np.tanh(drive * x) / np.tanh(drive)
    att = max(int(0.004 * SR), 1)
    x[:att] *= np.linspace(0, 1, att)
    ck = noise(len(t), seed) * np.exp(-t / 0.004)
    x += filt(ck, "hp", 1200) * 0.08
    return fade_edges(x, 0.002, 0.02)


def sub_bass(freq, dur, seed=4):
    t = tline(dur)
    ph = 2 * np.pi * freq * t
    x = np.sin(ph) + 0.18 * np.sin(2 * ph) + 0.06 * np.sin(3 * ph)
    env = np.ones(len(t))
    att = int(0.012 * SR)
    env[:att] = np.linspace(0, 1, att)
    rel = int(0.05 * SR)
    env[-rel:] *= np.linspace(1, 0, rel)
    return fade_edges(x * env * 0.8, 0.002, 0.01)


def hat(dur=0.07, decay=0.022, hp=7800, seed=10, tone=0.0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    x = noise(n, seed) * np.exp(-t / decay)
    x = filt(x, "hp", hp, order=3)
    if tone > 0:
        x += np.sin(2 * np.pi * 9000 * t) * np.exp(-t / 0.01) * tone
    return fade_edges(x, 0.0005, 0.003)


def shaker(dur=0.09, seed=11):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    env = (1 - np.exp(-t / 0.006)) * np.exp(-t / 0.045)
    x = filt(noise(n, seed), "hp", 5200, order=2) * env
    return x


def snare(dur=0.3, tone=185.0, decay=0.10, seed=12, bright=1.0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    body = np.sin(2 * np.pi * tone * t) * np.exp(-t / 0.045) * 0.55
    nz = filt(noise(n, seed), "bp", (1100, 7000)) * np.exp(-t / decay)
    x = body + nz * 0.9 * bright
    return fade_edges(x, 0.001, 0.008)


def clap(dur=0.34, seed=13):
    n = int(round(dur * SR))
    out = np.zeros(n)
    for k, off in enumerate([0.0, 0.011, 0.024, 0.040]):
        i = int(off * SR)
        m = n - i
        tt = np.arange(m) / SR
        burst = filt(noise(m, seed + k), "bp", (900, 5500)) * np.exp(-tt / 0.035)
        out[i:] += burst * (0.9 if k == 0 else 0.55)
    body = np.sin(2 * np.pi * 190 * np.arange(n) / SR) * np.exp(-np.arange(n) / SR / 0.03) * 0.25
    return fade_edges(out + body, 0.001, 0.01)


def pluck(freq, dur=0.5, nh=10, decay=0.16, bright=1.0, detune=0.0, seed=0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    for h in range(1, nh + 1):
        f = freq * h * (1.0 + detune)
        if f > 18500:
            break
        tau = decay / (1.0 + 0.30 * h)
        amp = (1.0 / h ** 1.05) * (bright ** (h - 1))
        out += np.sin(2 * np.pi * f * t + 0.45 * h) * amp * np.exp(-t / tau)
    att = max(int(0.0018 * SR), 1)
    out[:att] *= np.linspace(0, 1, att)
    return fade_edges(out, 0.001, 0.01)


def bell(freq, dur=1.4, seed=20, amp=1.0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    for h, ratio, tau, a in [
        (1, 1.0, 0.42, 1.0), (2, 2.01, 0.26, 0.45),
        (3, 3.02, 0.18, 0.22), (4, 4.07, 0.12, 0.12),
        (5, 5.12, 0.09, 0.06),
    ]:
        out += np.sin(2 * np.pi * freq * ratio * t) * a * np.exp(-t / tau)
    return fade_edges(out * amp, 0.002, 0.03)


def piano(freq, dur=2.6, seed=30, amp=1.0):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    for h, a, tau in [(1, 1.0, 1.05), (2, 0.42, 0.72), (3, 0.22, 0.50),
                      (4, 0.11, 0.36), (5, 0.06, 0.27), (6, 0.03, 0.20)]:
        out += np.sin(2 * np.pi * freq * h * t + 0.15 * h) * a * np.exp(-t / tau)
    ham = filt(noise(n, seed), "bp", (2200, 9000)) * np.exp(-t / 0.008) * 0.12
    out = fade_edges(out + ham, 0.003, 0.04) * amp
    return out


def shimmer(dur=1.2, base=1400.0, seed=31):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, ratio in enumerate([1.0, 1.51, 2.03, 2.98, 4.02, 5.06]):
        f = base * ratio
        if f > 17000:
            continue
        out += np.sin(2 * np.pi * f * t + 0.9 * k) * np.exp(-t / (0.5 / (1 + 0.35 * k))) / (1 + k * 0.7)
    return fade_edges(out, 0.01, 0.08)


def pad_chord(midis, dur, cutoff=1500, detune=0.006, attack=0.28,
              release=0.85, nh=10, lfo=0.11):
    total = dur + release
    n = int(round(total * SR))
    t = np.arange(n) / SR
    out = np.zeros(n)
    for m in midis:
        f = midi_hz(m)
        out += saw_add(f, total, nh=nh, detune=+detune, phase_rand=0.6)
        out += saw_add(f, total, nh=nh, detune=-detune, phase_rand=2.1)
    out /= max(len(midis) * 2, 1)
    out = filt(out, "lp", cutoff, order=2)
    out *= 1.0 + 0.07 * np.sin(2 * np.pi * lfo * t)
    env = np.ones(n)
    na = max(int(attack * SR), 1)
    nr = max(int(release * SR), 1)
    env[:na] = np.linspace(0, 1, na) ** 1.4
    env[-nr:] *= np.linspace(1, 0, nr) ** 1.15
    return fade_edges(out * env, 0.003, 0.01)


def vocal_ah(freq, dur, seed=40, vib_rate=5.2, vib_depth=0.0055):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    inst = freq * (1.0 + vib_depth * np.sin(2 * np.pi * vib_rate * t))
    ph = 2 * np.pi * np.cumsum(inst) / SR
    src = np.zeros(n)
    for h in range(1, 32):
        if freq * h > 16000:
            break
        src += np.sin(h * ph + 0.3 * h) / h ** 1.15
    out = np.zeros(n)
    for fc, bw, g in [(800, 120, 1.0), (1150, 140, 0.55),
                      (2800, 240, 0.26), (3500, 320, 0.11)]:
        out += filt(src, "bp", (fc - bw / 2, fc + bw / 2), order=2) * g
    out += filt(noise(n, seed), "lp", 3500) * 0.015
    out *= 1.0 + 0.06 * np.sin(2 * np.pi * vib_rate * 0.5 * t)
    out = out / (np.max(np.abs(out)) + 1e-9)
    att = max(int(0.025 * SR), 1)
    rel = max(int(0.09 * SR), 1)
    out[:att] *= np.linspace(0, 1, att)
    out[-rel:] *= np.linspace(1, 0, rel)
    return out


def swept_noise(dur, f0, f1, q=1.4, seed=50, nseg=40):
    n = int(round(dur * SR))
    x = noise(n, seed)
    out = np.zeros(n)
    edges = np.linspace(0, n, nseg + 1).astype(int)
    for i in range(nseg):
        c = f0 * (f1 / f0) ** (i / max(nseg - 1, 1))
        bw = max(c / q, 60.0)
        lo = max(30.0, c - bw / 2)
        hi = min(SR * 0.45, c + bw / 2)
        if hi <= lo * 1.05:
            hi = lo * 1.08
        sos = signal.butter(2, [lo, hi], "bandpass", fs=SR, output="sos")
        a, b = edges[i], edges[i + 1]
        seg = signal.sosfilt(sos, x[a:b])
        m = b - a
        r = min(int(0.004 * SR), m // 2)
        if r > 0:
            seg[:r] *= np.linspace(0.0, 1.0, r)
            seg[-r:] *= np.linspace(1.0, 0.0, r)
        out[a:b] = seg
    return out


def riser(dur, f0=280.0, f1=7000.0, seed=60, reverse=False):
    t = tline(dur)
    x = swept_noise(dur, f0, f1, q=1.2, seed=seed)
    env = (t / dur) ** (2.0 if not reverse else 2.4)
    env *= np.minimum(1.0, (dur - t) / 0.01 + 0.0) if not reverse else 1.0
    if reverse:
        env = (t / dur) ** 2.6
    y = x * env
    y += np.sin(2 * np.pi * np.cumsum(np.linspace(f0 * 0.35, f1 * 0.35, len(t))) / SR) * env * 0.18
    return y


def whoosh(dur=0.42, seed=70, up=True):
    t = tline(dur)
    f0, f1 = (300, 6500) if up else (6500, 400)
    x = swept_noise(dur, f0, f1, q=1.6, seed=seed)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    return x * env


def impact(dur=2.0, seed=80):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    f = 32 + 95 * np.exp(-t / 0.10)
    boom = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.55)
    boom = np.tanh(2.2 * boom) / np.tanh(2.2)
    crack = filt(noise(n, seed), "bp", (200, 8000)) * np.exp(-t / 0.22) * 0.55
    tail = filt(noise(n, seed + 1), "bp", (300, 3000)) * np.exp(-t / 0.8) * 0.10
    return fade_edges(boom + crack + tail, 0.002, 0.05)


def heartbeat(seed=90):
    dur = 0.28
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    f = 42 + 16 * np.exp(-t / 0.02)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t / 0.06)
    x = np.tanh(1.8 * x) / np.tanh(1.8)
    return fade_edges(x, 0.003, 0.05)


def key_click(seed=100):
    n = int(round(0.035 * SR))
    t = np.arange(n) / SR
    x = filt(noise(n, seed), "bp", (2500, 10000)) * np.exp(-t / 0.004) * 0.5
    x += np.sin(2 * np.pi * 1500 * t) * np.exp(-t / 0.006) * 0.22
    x += np.sin(2 * np.pi * 95 * t) * np.exp(-t / 0.012) * 0.18
    return fade_edges(x, 0.0005, 0.004)


def wind(dur=3.2, seed=110):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    base = noise(n, seed)
    x = filt(base, "lp", 420, order=2) * 0.8
    x += filt(noise(n, seed + 1), "lp", 1400, order=2) * 0.25
    x *= 0.55 + 0.45 * np.sin(2 * np.pi * 0.16 * t + 0.7) ** 2
    env = np.ones(n)
    na = int(0.35 * SR)
    nr = int(0.9 * SR)
    env[:na] = np.linspace(0, 1, na)
    env[-nr:] *= np.linspace(1, 0, nr)
    return x * env


def glitch_stab(freq=880.0, dur=0.11, seed=120):
    n = int(round(dur * SR))
    x = pluck(freq, dur=dur, nh=14, decay=0.06, bright=1.0)
    x += filt(noise(n, seed), "hp", 3000) * np.exp(-np.arange(n) / SR / 0.02) * 0.35
    x = np.round(x * 8.0) / 8.0  # bitcrush
    return x


# ----------------------------------------------------------------------------
# 混响 / 延迟 / 侧链 / 限幅
# ----------------------------------------------------------------------------

def make_ir(dur=1.6, seed=200):
    n = int(round(dur * SR))
    t = np.arange(n) / SR
    ir = np.zeros((2, n))
    for ch in range(2):
        x = noise(n, seed + ch) * np.exp(-t / 0.42)
        x = filt(x, "lp", 6500, order=2)
        pre = int(0.012 * SR)
        x = np.concatenate([np.zeros(pre), x[:n - pre]])
        ir[ch] = x
    ir /= np.sqrt(np.sum(ir ** 2) / 2) + 1e-9
    return ir


def convolve_reverb(stereo, ir):
    out = np.zeros_like(stereo)
    for ch in range(2):
        out[ch] = signal.fftconvolve(stereo[ch], ir[ch], mode="full")[:N]
    return out


def pingpong_delay(stereo, delay_s, fb=0.33, mix=0.26):
    d = int(round(delay_s * SR))
    out = np.zeros_like(stereo)
    for k in range(1, 4):
        shift = d * k
        if shift >= N:
            break
        sp = np.zeros_like(stereo)
        sp[:, shift:] = stereo[:, :N - shift]
        if k % 2 == 1:
            sp = sp[::-1]
        out += sp * (mix * (fb ** (k - 1)))
    return out


def sidechain_env(times, depth=0.55, rel=0.30):
    env = np.ones(N)
    n = int(rel * SR)
    tt = np.arange(n) / SR
    shape = 1.0 - depth * (1.0 - np.exp(-tt / 0.0015)) * np.exp(-tt / (rel * 0.38))
    for t0 in times:
        i = int(round(t0 * SR))
        if i >= N:
            continue
        j = min(i + n, N)
        env[i:j] = np.minimum(env[i:j], shape[:j - i])
    return env


def limiter(x, ceiling=0.84, lookahead=0.004, release=0.10, os=4):
    """真峰值感知的 lookahead 限幅：在 os 倍过采样域取峰值包络。"""
    up = [signal.resample_poly(x[ch], os, 1) for ch in range(2)]
    m = min(len(up[0]), len(up[1]))
    pk = np.maximum(np.abs(up[0][:m]), np.abs(up[1][:m]))
    nb = m // os
    pk = pk[:nb * os].reshape(nb, os).max(axis=1)
    req = np.minimum(1.0, ceiling / np.maximum(pk, 1e-9))
    if len(req) < N:
        req = np.pad(req, (0, N - len(req)), mode="edge")
    else:
        req = req[:N]
    w = max(1, int(lookahead * SR))
    gmin = minimum_filter1d(req, size=2 * w + 1, mode="nearest")
    a = 1.0 - np.exp(-1.0 / (release * SR))
    gslow = signal.lfilter([a], [1.0, -(1.0 - a)], gmin)
    g = np.minimum(gmin, gslow)
    return x * g[np.newaxis, :]


def loudness(path):
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path,
           "-af", "loudnorm=I=-14:TP=-1:print_format=json", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    log = p.stderr
    s, e = log.rfind("{"), log.rfind("}")
    if s < 0 or e < 0:
        raise RuntimeError("loudnorm 解析失败:\n" + log[-2000:])
    d = json.loads(log[s:e + 1])
    return float(d["input_i"]), float(d["input_tp"]), float(d["input_lra"])


def measure_ebur128(path):
    """ffmpeg ebur128 正式测量：整体 LUFS + 真峰值。"""
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-i", path,
           "-af", "ebur128=peak=true", "-f", "null", "-"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    log = p.stderr
    sec = log[log.rfind("Summary:"):]
    mi = re.search(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", sec)
    mt = re.search(r"Peak:\s+(-?\d+(?:\.\d+)?)\s+dBFS", sec)
    ml = re.search(r"LRA:\s+(-?\d+(?:\.\d+)?)\s+LU", sec)
    if not (mi and mt):
        raise RuntimeError("ebur128 解析失败:\n" + log[-1500:])
    return float(mi.group(1)), float(mt.group(1)), float(ml.group(1)) if ml else float("nan")


def write_wav24(path, stereo):
    y = np.clip(stereo.T, -1.0, 1.0)
    ints = np.round(y * 8388607.0).astype("<i4")
    raw = np.frombuffer(ints.tobytes(), dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(SR)
        w.writeframes(raw)


# ----------------------------------------------------------------------------
# 编曲
# ----------------------------------------------------------------------------

CHORDS = {
    "Am": [57, 60, 64, 69],
    "F":  [53, 57, 60, 65],
    "C":  [55, 60, 64, 67],
    "G":  [55, 59, 62, 67],
    "Dm": [50, 53, 57, 62],
    "Em": [52, 55, 59, 64],
}
BASS_ROOT = {"Am": 33, "F": 29, "C": 36, "G": 31, "Dm": 26, "Em": 28}
CHORD_ORDER_1 = ["Am", "F", "C", "G", "Am", "F"]        # bars 3-8
CHORD_ORDER_2 = ["Am", "Am", "F", "F", "Dm", "Dm", "Am", "Am"]  # bars 10-17

drums = Bus()
bassb = Bus()
music = Bus()
pluckb = Bus()
fvb = Bus()
fx = Bus()
sfx_cues = []
kick_times = []


def cue(name, t):
    sfx_cues.append({"name": name, "t": round(float(t), 6)})


def bar_t(bar, beat=0.0):
    return (bar - 1) * BAR + beat * BEAT


def add_kick(t, gain=1.0, trap=False, pan=0.0):
    if trap:
        drums.add(trap_kick(seed=int(t * 1000) % 9999), t, gain=gain, pan=pan)
    else:
        drums.add(kick(seed=int(t * 1000) % 9999), t, gain=gain, pan=pan)
    kick_times.append(t)


def add_clap(t, gain=0.5, pan=0.0):
    drums.add(clap(seed=int(t * 777) % 9999), t, gain=gain, pan=pan)


def add_snare(t, gain=0.5, pan=0.0, bright=1.0):
    drums.add(snare(seed=int(t * 555) % 9999, bright=bright), t, gain=gain, pan=pan)


# ---------------- Intro: bars 1-2 (0.000 - 3.750) ----------------
intro_arp_notes = [69, 72, 76, 81, 76, 72, 76, 72]  # Am 琶音
step = 0
t = 0.0
while t < 3.70:
    idx = step % len(intro_arp_notes)
    bright = 0.28 + 0.72 * min(1.0, t / 3.2)
    f = midi_hz(intro_arp_notes[idx])
    p = pluck(f, dur=0.55, nh=12, decay=0.20 + 0.08 * bright, bright=bright)
    music.add(p, t, gain=0.34, pan=(-0.18 if step % 2 else 0.18))
    step += 1
    t += SIXTEENTH * 2

# 柔和低音铺底
for bar, chord in [(1, "Am"), (2, "Am")]:
    dur = BAR
    bassb.add(sub_bass(midi_hz(BASS_ROOT[chord]), dur) * 0.35, bar_t(bar), gain=0.9)
    music.add(pad_chord(CHORDS[chord][:3], BAR, cutoff=900, attack=0.6,
                        release=0.5, nh=8), bar_t(bar), gain=0.22, pan=-0.3)
    music.add(pad_chord(CHORDS[chord][:3], BAR, cutoff=900, attack=0.6,
                        release=0.5, nh=8, detune=0.009), bar_t(bar), gain=0.22, pan=0.3)

# 键盘 click（0.30 - 3.15）
kt = 0.30
kc = 0
while kt < 3.15:
    if kc % 7 != 5:
        fx.add(key_click(seed=200 + kc), kt, gain=0.5 * (0.7 + 0.3 * rng_global.random()),
               pan=0.1 * rng_global.uniform(-1, 1))
    kt += SIXTEENTH * rng_global.choice([1, 1, 2, 2, 3])
    kc += 1
cue("keyboard", 0.30)

# 反向 riser + 第 2 小节 build
fx.add(riser(BAR * 0.96, 300, 5000, seed=61, reverse=True), 1.92, gain=0.30)
cue("riser", 1.875)
music.add(bell(midi_hz(93), dur=1.6, amp=1.0), 0.55, gain=0.05, pan=0.35)

# 军鼓 build roll（2.8125 -> 3.75 加速）
t = 2.8125
k = 0
while t < 3.735:
    g = 0.10 + 0.30 * (t - 2.8125) / 0.92
    add_snare(t, gain=g, pan=0.08 * (-1) ** k, bright=1.3)
    t += SIXTEENTH if k < 4 else SIXTEENTH * 0.5
    k += 1
cue("snare_roll_build", 2.8125)
fx.add(riser(0.94, 500, 9000, seed=62), 2.81, gain=0.35)

# 冲击 / shimmer 进 Drop 1
drums.add(impact(seed=81), 3.75, gain=0.55)
fx.add(shimmer(1.4, 1200), 3.75, gain=0.22, pan=0.2)
fx.add(shimmer(1.3, 1800), 3.75, gain=0.14, pan=-0.35)
cue("impact", 3.75)
cue("shimmer", 3.75)

# ---------------- Drop 1: bars 3-8 (3.750 - 15.000) ----------------
drop1_start = 3.75
for bi, chord in enumerate(CHORD_ORDER_1):
    bar = 3 + bi
    t0 = bar_t(bar)
    notes = CHORDS[chord]
    root_hz = midi_hz(BASS_ROOT[chord])

    # pad（双声道宽）
    music.add(pad_chord(notes[:3], BAR, cutoff=1700, attack=0.12,
                        release=0.55, nh=10), t0, gain=0.34, pan=-0.42)
    music.add(pad_chord(notes[:3], BAR, cutoff=1700, attack=0.12,
                        release=0.55, nh=10, detune=0.009), t0, gain=0.34, pan=0.42)

    # 4/4 底鼓
    for b in range(4):
        add_kick(t0 + b * BEAT, gain=0.95)
        if b in (1, 3):
            add_clap(t0 + b * BEAT, gain=0.36, pan=-0.05)

    # sub bass：8 分音符律动
    for s in range(8):
        tt = t0 + s * EIGHTH
        f = root_hz if s % 4 != 3 else root_hz * 1.5
        dur = EIGHTH * 0.92
        bassb.add(sub_bass(f, dur, seed=300 + s), tt, gain=0.48)

    # 闭合 hat / 开镲
    for s in range(8):
        tt = t0 + s * EIGHTH
        drums.add(hat(seed=400 + s, decay=0.018), tt, gain=0.44, pan=0.18)
        if s % 2 == 1:
            drums.add(hat(dur=0.16, decay=0.06, seed=500 + s), tt, gain=0.22, pan=-0.22)

    # 16 分竖琴式 pluck 琶音
    pattern = [0, 1, 2, 3, 2, 1, 2, 3]
    for s in range(16):
        tt = t0 + s * SIXTEENTH
        note = notes[pattern[s % len(pattern)]] + 12
        if s % 8 == 7:
            note += 12
        p = pluck(midi_hz(note), dur=0.36, nh=9, decay=0.13, bright=0.9)
        pluckb.add(p, tt, gain=0.16 if s % 4 else 0.22,
                   pan=(-0.30 if s % 2 else 0.30))

    # 第 5-8 小节：shaker 16 分
    if bar >= 5:
        for s in range(16):
            tt = t0 + s * SIXTEENTH
            drums.add(shaker(seed=600 + s), tt, gain=0.18 if s % 2 else 0.27,
                      pan=0.45 * (1 if s % 2 else -1))

    # 女声和声切片（共振峰合成）
    if bar in (5, 6, 7, 8):
        spots = [2.5, 3.5] if bar % 2 == 1 else [1.5, 2.75]
        for s in spots:
            tt = t0 + s * BEAT
            v = vocal_ah(midi_hz(notes[2] + 12), 0.62, seed=700 + int(tt * 10))
            fvb.add(v, tt, gain=0.20, pan=-0.15)
            fvb.add(v, tt + 0.012, gain=0.13, pan=0.35)
            cue("vocal_chop", tt)

    # 小打点：bell 点缀
    if bar in (4, 6, 8):
        music.add(bell(midi_hz(notes[3] + 12), dur=0.9), t0 + 3.5 * BEAT,
                  gain=0.07, pan=-0.3)

cue("shaker", 7.5)
cue("riser", 11.25)
cue("snare_roll", 13.125)

# 第 8 小节末开始滚奏（13.125 -> 15.0），引入第 9 小节
rt = 13.125
k = 0
while rt < 14.995:
    g = 0.10 + 0.28 * (rt - 13.125) / 1.87
    add_snare(rt, gain=g, pan=0.12 * (-1) ** k, bright=1.2)
    rt += SIXTEENTH if rt < 14.5 else SIXTEENTH * 0.5
    k += 1

# 第 9 小节（15.0 - 16.875）：收束 + 军鼓滚奏 + riser
for s in range(16):  # 15.0 - 15.9375
    tt = 15.0 + s * SIXTEENTH
    if tt >= 15.9375:
        break
    add_snare(tt, gain=0.18 + 0.40 * (s / 16), pan=0.1 * (-1) ** s, bright=1.3)
    if s % 4 == 0:
        drums.add(hat(seed=800 + s, decay=0.02), tt, gain=0.26, pan=0.2)
fx.add(riser(0.94, 700, 11000, seed=63), 15.0, gain=0.55)
fx.add(whoosh(0.5, seed=71, up=False), 15.42, gain=0.26)

# 心跳（接近静音空间）
for i, tt in enumerate([16.055, 16.300, 16.505, 16.660]):
    fx.add(heartbeat(seed=900 + i), tt, gain=0.30 if i % 2 == 0 else 0.22)
cue("heartbeat", 16.055)
cue("silence", 16.725)

# 第 9 小节末：全部收掉（16.0 后只剩心跳，16.725-16.875 完全静音）
# 注意：drop2 的 impact 在 16.875 才触发，因此这里不额外加尾音。

# ---------------- Drop 2: bars 10-17 (16.875 - 31.875) ----------------
drums.add(impact(seed=82, dur=2.2), 16.875, gain=0.85)
fx.add(impact(seed=83, dur=1.6), 16.875, gain=0.5)
cue("impact", 16.875)
cue("glitch", 16.875)
cue("drop2", 16.875)

# glitch stutter 撞击
for k in range(10):
    tt = 16.875 + k * THIRTY2
    fx.add(glitch_stab(freq=midi_hz(69 if k % 2 else 76), dur=0.09,
                       seed=1000 + k), tt, gain=0.30 * (0.55 ** (k / 3)),
           pan=0.5 if k % 2 else -0.5)

# 蒙太奇切点（8 分音符网格）与 whoosh
MONTAGE_START = 20.625
MONTAGE_END = 24.375
MONTAGE_SHOTS = [
    ("clock_2347", 20.625, 22.125),
    ("router", 22.125, 22.875),
    ("phone", 22.875, 23.4375),
    ("slipper", 23.4375, 23.90625),
    ("point", 23.90625, 24.375),
]


def montage_shot(t):
    for name, a, b in MONTAGE_SHOTS:
        if a <= t < b:
            return name
    return "point"


montage_cut_times = [MONTAGE_START + k * EIGHTH for k in range(17)]
for k, tt in enumerate(montage_cut_times):
    if tt > MONTAGE_END + 1e-9:
        break
    fx.add(whoosh(0.34, seed=1100 + k, up=(k % 2 == 0)), tt - 0.06,
           gain=0.26, pan=(-0.55 if k % 2 else 0.55))
    cue("whoosh", tt)

sfx_cues.append({"name": "snare_fill", "t": round(MONTAGE_START, 6)})

# 每个 drop2 小节
for bi, chord in enumerate(CHORD_ORDER_2):
    bar = 10 + bi
    t0 = bar_t(bar)
    notes = CHORDS[chord]
    root_hz = midi_hz(BASS_ROOT[chord] - 12)  # 808 低八度
    montage = bar in (12, 13)
    half = bar in (16, 17)

    # dark pad
    music.add(pad_chord([n - 12 for n in notes[:3]], BAR, cutoff=620,
                        attack=0.20, release=0.7, nh=8, lfo=0.08),
              t0, gain=0.44, pan=-0.4)
    music.add(pad_chord([n - 12 for n in notes[:3]], BAR, cutoff=620,
                        attack=0.20, release=0.7, nh=8, lfo=0.08, detune=0.010),
              t0, gain=0.44, pan=0.4)

    # 底鼓 pattern
    if montage:
        beats = [0.0, 2.0]
    elif half:
        beats = [0.0]
    elif bar in (14, 15):
        beats = [0.0, 0.75, 1.5, 2.25, 3.0]
    else:
        beats = [0.0, 1.5, 2.75]

    for b in beats:
        add_kick(t0 + b * BEAT, gain=0.85, trap=True)

        # 808 跟随 kick，长音滑音
    kstep = beats + [4.0]
    for i, b in enumerate(beats):
        nxt = kstep[i + 1]
        dur = min((nxt - b) * BEAT * 0.94, 1.6)
        if half:
            dur = min(dur, 1.1)
        s = sub808(root_hz, max(dur, 0.30), glide=1.5 if not half else 1.25,
                   seed=1200 + i + bar * 10)
        bassb.add(s, t0 + b * BEAT, gain=0.62 if not half else 0.44)

    # 军鼓 / clap
    if montage:
        for s in range(8):
            add_snare(t0 + s * EIGHTH, gain=0.30 + 0.12 * (s % 2),
                      pan=-0.1 if s % 2 else 0.1, bright=1.15)
            if s % 2 == 0:
                add_clap(t0 + s * EIGHTH, gain=0.18, pan=0.25)
    elif half:
        for b in (3.0,):
            add_snare(t0 + b * BEAT, gain=0.30, bright=0.85)
            add_clap(t0 + b * BEAT, gain=0.16, pan=0.1)
    else:
        for b in (2.5,):
            add_snare(t0 + b * BEAT, gain=0.42, bright=1.05)
            add_clap(t0 + b * BEAT, gain=0.24, pan=-0.08)
        if bar in (14, 15):
            add_snare(t0 + 3.75 * BEAT, gain=0.22, bright=1.2)

    # 快速 hat（16 分 + 32 分 roll）
    if not half:
        for s in range(16):
            tt = t0 + s * SIXTEENTH
            if montage and s % 2 != 0:
                continue
            g = 0.30 if s % 2 == 0 else 0.19
            drums.add(hat(seed=1300 + s, decay=0.016), tt, gain=g,
                      pan=0.26 if s % 2 else -0.26)
        # 32 分 hat 连击（trap 味）
        for spot in (1.75, 3.5):
            for k in range(4):
                tt = t0 + spot * BEAT + k * THIRTY2
                drums.add(hat(seed=1400 + k, decay=0.012), tt,
                          gain=0.16 * (0.8 ** k), pan=(-1) ** k * 0.3)
        if bar in (14, 15):
            drums.add(hat(dur=0.2, decay=0.08, seed=1500), t0 + 3.75 * BEAT,
                      gain=0.24, pan=0.15)
    else:
        for s in range(4):
            tt = t0 + s * BEAT
            drums.add(hat(seed=1600 + s, decay=0.03), tt, gain=0.14, pan=0.3)

    # 中频 pluck stab：补足 trap 段在手机小喇叭上的存在感
    if not half and not montage:
        for j, s in enumerate((3, 7)):
            tt = t0 + s * EIGHTH
            note = notes[(j + bar) % len(notes)] + 12
            p = pluck(midi_hz(note), dur=0.26, nh=12, decay=0.085, bright=0.82)
            pluckb.add(p, tt, gain=0.22, pan=(0.28 if j else -0.28))

    # 蒙太奇：4 分音符重音 + 张力
    if montage:
        for b in range(4):
            add_clap(t0 + b * BEAT, gain=0.15, pan=0.35)
        fx.add(riser(BAR * 2, 500, 8000, seed=64), t0, gain=0.16)

    # 28.125 - 31.875：钢琴单音 + 暖 pad
    if half:
        piano_notes = ([69, 72, 76] if bar == 16 else [72, 76, 81])
        for j, m in enumerate(piano_notes):
            music.add(piano(midi_hz(m), dur=1.7, seed=1700 + j + bar),
                      t0 + j * (BEAT * 1.6), gain=0.24, pan=0.15 * (-1) ** j)
        music.add(pad_chord(CHORDS[chord][:3], BAR, cutoff=1200, attack=0.35,
                            release=0.6, nh=8), t0, gain=0.26, pan=0.0)

# 28.125 钢琴进入 + 26.25 glitch
cue("piano", 28.125)
for k in range(6):
    tt = 26.25 + k * THIRTY2
    fx.add(glitch_stab(freq=midi_hz(72 if k % 2 else 67), dur=0.08,
                       seed=1800 + k), tt, gain=0.20 * (0.7 ** k),
           pan=(-0.4 if k % 2 else 0.4))

# 24.375 / 26.25 处的冲击，标记蒙太奇结束
drums.add(impact(seed=84, dur=1.4), 24.375, gain=0.55)
fx.add(whoosh(0.45, seed=72, up=False), 24.20, gain=0.26)
cue("light_switch", 24.375)
cue("slipper", 25.3125)
sfx_cues.append({"name": "slipper", "t": 26.4375})

# 31.0 - 31.875 收束 riser
fx.add(riser(0.8, 400, 6000, seed=65, reverse=True), 31.0, gain=0.16)

# ---------------- Outro: 31.875 - 35.000 ----------------
drums.add(impact(seed=85, dur=2.4), 31.875, gain=0.30)
music.add(piano(midi_hz(69), dur=2.2, seed=1901, amp=1.0), 31.900, gain=0.30, pan=0.1)
music.add(piano(midi_hz(76), dur=2.0, seed=1902, amp=1.0), 32.400, gain=0.22, pan=-0.2)
music.add(piano(midi_hz(72), dur=2.2, seed=1903, amp=1.0), 33.000, gain=0.20, pan=0.25)
music.add(bell(midi_hz(88), dur=2.0, amp=1.0), 33.600, gain=0.09, pan=-0.35)
music.add(pad_chord(CHORDS["Am"][:3], 2.6, cutoff=1000, attack=0.4,
                    release=0.6, nh=8), 31.875, gain=0.34, pan=0.0)
music.add(pad_chord(CHORDS["F"][:3], 1.1, cutoff=900, attack=0.4,
                    release=0.5, nh=8), 34.0, gain=0.18, pan=0.0)
fx.add(wind(3.15, seed=1910), 31.875, gain=0.22)
fx.add(whoosh(0.5, seed=73, up=False), 34.55, gain=0.10)
bassb.add(sub_bass(55.0, 1.5, seed=1920) * 1.2, 34.5, gain=0.55)
cue("wind", 31.875)
cue("piano_tail", 31.875)
cue("sub_hit", 34.5)

# 最后一个 sub hit 让整体收尾
drums.add(kick(dur=0.9, f0=90, f1=38, atau=0.5, drive=1.4, click=0.2, seed=1930),
          34.5, gain=0.28)


# ----------------------------------------------------------------------------
# 混音
# ----------------------------------------------------------------------------

def build_mix():
    music.x += pluckb.x
    sc_drums = sidechain_env(kick_times, depth=0.62, rel=0.30)
    sc_bass = sidechain_env(kick_times, depth=0.80, rel=0.34)

    music_sc = music.x * (0.30 + 0.70 * sc_drums)
    bass_sc = bassb.x * (0.18 + 0.82 * sc_bass)
    fv_sc = fvb.x * (0.55 + 0.45 * sc_drums)

    send = music_sc * 0.55 + fv_sc * 0.7 + drums.x * 0.16 + fx.x * 0.30
    send += pingpong_delay(pluckb.x, SIXTEENTH * 3, fb=0.34, mix=0.22) * 0.8
    ir = make_ir(1.7)
    wet = convolve_reverb(send, ir)

    mix = (drums.x * 0.85
           + bass_sc * 0.80
           + music_sc * 0.78
           + fv_sc * 0.55
           + fx.x * 0.78
           + wet * 0.42)
    mix[0] = filt(mix[0], "hp", 28)
    mix[1] = filt(mix[1], "hp", 28)
    # 空气感高架：7 kHz 以上 +2 dB 左右，让 hat / shaker 更清晰
    for ch in range(2):
        mix[ch] += 0.26 * filt(mix[ch], "hp", 7000, order=2)

    # 15.0-16.875 收束：额外把整体再压暗、压小
    i0, i1 = int(15.0 * SR), int(16.875 * SR)
    mix[:, i0:i1] *= 0.92

    # 16.69 -> 16.725 淡出，16.725 -> 16.875 绝对静音
    i_f0, i_f1, i_f2 = int(16.69 * SR), int(16.725 * SR), int(16.875 * SR)
    mix[:, i_f0:i_f1] *= np.linspace(1.0, 0.0, i_f1 - i_f0) ** 1.2
    mix[:, i_f1:i_f2] = 0.0

    # 结尾淡出，保证 35.000s 处无爆音
    i_e = int(34.80 * SR)
    mix[:, i_e:] *= np.linspace(1.0, 0.0, N - i_e) ** 1.1
    # 开头 8ms 淡入
    na = int(0.008 * SR)
    mix[:, :na] *= np.linspace(0, 1, na)
    return mix


mix = build_mix()
assert np.all(np.isfinite(mix)), "混音包含 NaN/Inf"

# 预限幅（保留冲击），再按 LUFS 迭代
TARGET_I = -14.0
CEILING = db(-1.35)
x = mix.copy()
tmp = "/tmp/nana_bgm_master.wav"
write_wav24(tmp, x)
I0, TP0, _ = loudness(tmp)
print(f"[raw    ] I={I0:6.2f} LUFS  TP={TP0:6.2f} dBTP  peak={np.max(np.abs(x)):.3f}")
x = x * db(TARGET_I - I0)  # 先按整体增益预估

best = None
for it in range(7):
    x = limiter(x, ceiling=CEILING, lookahead=0.004, release=0.11)
    write_wav24(tmp, x)
    I, TP, LRA = loudness(tmp)
    print(f"[master ] pass {it}: I={I:6.2f} LUFS  TP={TP:6.2f} dBTP  LRA={LRA:5.1f}")
    if TP <= -0.95:
        if best is None or abs(I - TARGET_I) < abs(best[1] - TARGET_I):
            best = (x.copy(), I, TP)
    if TP > -1.0:
        x = x * db(-1.0 - TP - 0.10)
        continue
    err = TARGET_I - I
    if abs(err) <= 0.12:
        break
    x = x * db(err)

if best is not None and best[2] <= -0.95:
    x, I, TP = best

# 若仍偏响则纯衰减（安全），偏轻则小幅增益后重新限幅
for _ in range(4):
    err = TARGET_I - I
    if abs(err) <= 0.12:
        break
    if err < 0:
        x = x * db(err)
        write_wav24(tmp, x)
        I, TP, LRA = loudness(tmp)
    else:
        x = limiter(x * db(err), ceiling=CEILING, lookahead=0.004, release=0.11)
        write_wav24(tmp, x)
        I, TP, LRA = loudness(tmp)
    print(f"[trim   ] I={I:6.2f} LUFS  TP={TP:6.2f} dBTP  peak={np.max(np.abs(x)):.3f}")

write_wav24(tmp, x)
I, TP, LRA = loudness(tmp)
print(f"[final  ] I={I:6.2f} LUFS  TP={TP:6.2f} dBTP  peak={np.max(np.abs(x)):.3f}")

if not np.all(np.isfinite(x)):
    raise SystemExit("最终音频包含 NaN")
if np.max(np.abs(x)) >= 1.0:
    raise SystemExit("最终音频削波")

os.makedirs(os.path.dirname(ASSET_WAV), exist_ok=True)
write_wav24(ASSET_WAV, x)

# ffmpeg ebur128 正式校验，并做最后 0.2 dB 级微调
for _ in range(3):
    EB_I, EB_TP, EB_LRA = measure_ebur128(ASSET_WAV)
    print(f"[ebur128] I={EB_I:.2f} LUFS  true peak={EB_TP:.2f} dBTP  LRA={EB_LRA:.1f} LU")
    err = -14.0 - EB_I
    if abs(err) <= 0.08:
        break
    if err < 0:
        x = x * db(err)
    else:
        head = -1.0 - EB_TP - 0.08
        if head <= 0.02:
            break
        x = x * db(min(err, head))
    write_wav24(ASSET_WAV, x)

if abs(EB_I - (-14.0)) > 0.5 or EB_TP > -1.0:
    print("[warn] LUFS/真峰值超出目标，请检查 master 阶段")


# ----------------------------------------------------------------------------
# 段落统计 + beatmap
# ----------------------------------------------------------------------------

SECTIONS = [
    ("intro", 0.0, 3.75),
    ("drop1", 3.75, 15.0),
    ("break", 15.0, 16.875),
    ("drop2", 16.875, 28.125),
    ("split", 28.125, 31.875),
    ("outro", 31.875, 35.0),
]

print("\n段落 RMS / Peak:")
for name, a, b in SECTIONS:
    seg = x[:, int(round(a * SR)):int(round(b * SR))]
    rms = 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)
    pk = 20 * np.log10(np.max(np.abs(seg)) + 1e-12)
    print(f"  {name:6s} {a:6.3f}-{b:6.3f}s  RMS {rms:7.2f} dBFS  peak {pk:7.2f} dBFS")

# bars
bars = []
nbars = int(math.ceil(DUR / BAR))
for i in range(nbars):
    s = i * BAR
    e = min(DUR, (i + 1) * BAR)
    bars.append({"index": i + 1, "start": round(s, 6), "end": round(e, 6)})

# 分镜切点（严格来自 script.json）
shots = [
    ("s01", 0.0, 3.75), ("s02", 3.75, 7.5), ("s03", 7.5, 11.25),
    ("s04", 11.25, 15.0), ("s05", 15.0, 16.875), ("s06", 16.875, 20.625),
    ("s07", 20.625, 24.375), ("s08", 24.375, 28.125), ("s09", 28.125, 31.875),
    ("s10", 31.875, 35.0),
]
cuts = []
for sid, a, b in shots:
    cuts.append({"t": round(a, 6), "kind": "shot", "shot": sid})

for k, tt in enumerate(montage_cut_times):
    if tt >= MONTAGE_END - 1e-9:
        continue
    cuts.append({"t": round(tt, 6), "kind": "montage_8th",
                 "shot": "s07", "montage_shot": montage_shot(tt)})

cuts.sort(key=lambda c: (c["t"], c["kind"]))

beatmap = {
    "title": "同一个 nana，两种命",
    "bpm": BPM,
    "bar_seconds": round(BAR, 6),
    "beat_seconds": round(BEAT, 6),
    "eighth_seconds": round(EIGHTH, 6),
    "sixteenth_seconds": round(SIXTEENTH, 6),
    "duration": DUR,
    "sample_rate": SR,
    "channels": 2,
    "loudness_lufs": round(EB_I, 2),
    "true_peak_dbtp": round(EB_TP, 2),
    "loudness_range_lu": round(EB_LRA, 2),
    "bars": bars,
    "sections": [
        {"name": n, "start": round(a, 6), "end": round(b, 6)}
        for n, a, b in SECTIONS
    ],
    "drops": [
        {"name": "drop1_house", "start": 3.75, "end": 16.875},
        {"name": "drop2_trap", "start": 16.875, "end": 31.875},
    ],
    "cuts": cuts,
    "sfx_cues": sorted(sfx_cues, key=lambda c: c["t"]),
    "notes": {
        "intro": "滤波 pluck 琶音 + 键盘 click + 反向 riser，第 2 小节 build",
        "break": "第 9 小节收束，16.0-16.875 仅心跳，16.725-16.875 完全静音",
        "montage": "20.625-24.375 按 8 分音符网格切，snare fill + whoosh",
        "split": "28.125-31.875 鼓组减半，钢琴单音 + 暖 pad",
        "outro": "鼓组退出，钢琴尾音 + 风声 + 34.5s sub hit",
    },
}

with open(BEATMAP_JSON, "w", encoding="utf-8") as f:
    json.dump(beatmap, f, ensure_ascii=False, indent=2)

print(f"\nwav: {ASSET_WAV}")
print(f"beatmap: {BEATMAP_JSON}")
print(f"bars={len(bars)} cuts={len(cuts)} sfx_cues={len(sfx_cues)}")
print(f"final max sample={np.max(np.abs(x)):.6f}  nan={np.isnan(x).any()}")
