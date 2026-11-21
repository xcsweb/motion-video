#!/usr/bin/env python3
"""Procedural light-rail rolling SFX stem (clack-clack + rumble + motor)."""
import numpy as np
from scipy.signal import butter, sosfilt, fftconvolve

SR = 48000
DUR = 24.0
N = int(SR * DUR)
rng = np.random.default_rng(7)


def band(x, lo, hi, order=4):
    sos = butter(order, [lo, hi], btype="band", fs=SR, output="sos")
    return sosfilt(sos, x)


def lowp(x, f, order=4):
    sos = butter(order, f, btype="low", fs=SR, output="sos")
    return sosfilt(sos, x)


def env_ar(n, a, r):
    t = np.arange(n) / SR
    e = np.minimum(t / max(a, 1e-4), 1.0) * np.exp(-np.maximum(t - a, 0) / max(r, 1e-4))
    return e


def clack(level=1.0, bright=1.0):
    n = int(0.12 * SR)
    hi = band(rng.standard_normal(n), 650, 2400) * env_ar(n, 0.0015, 0.020)
    lo = lowp(rng.standard_normal(n), 150) * env_ar(n, 0.002, 0.060) * 0.9
    body = hi * 0.55 * bright + lo
    return body * level


def rumble(dur):
    n = int(dur * SR)
    x = np.cumsum(rng.standard_normal(n))
    x = x - lowp(x, 25)
    x = lowp(x, 150)
    x /= (np.max(np.abs(x)) + 1e-9)
    mod = 0.75 + 0.25 * np.sin(2 * np.pi * 0.37 * np.arange(n) / SR + rng.uniform(0, 6))
    return x * mod


def motor(dur, f0=185.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    vib = 1.0 + 0.004 * np.sin(2 * np.pi * 5.1 * t)
    s = np.sin(2 * np.pi * f0 * t * vib) * 0.5 + np.sin(2 * np.pi * f0 * 2 * t * vib) * 0.22
    s += band(rng.standard_normal(n), 900, 1600) * 0.05
    return s


def whoosh(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    e = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return band(rng.standard_normal(n), 250, 1400) * e


def squeal(dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 2050 + 90 * np.sin(2 * np.pi * 2.3 * t)
    e = np.clip(t / 0.25, 0, 1) * np.clip((dur - t) / 0.3, 0, 1)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.5 + band(rng.standard_normal(n), 1800, 3200) * 0.35) * e


def ir(dur=0.9, decay=0.42):
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n) * np.exp(-t / decay)
    x = lowp(x, 3200)
    return x / (np.sqrt(np.sum(x ** 2)) + 1e-9)


def place(buf, sig, start, gain=1.0, rev=0.0, revbuf=None):
    i = int(start * SR)
    if i >= len(buf):
        return
    if rev > 0:
        sig = sig + revbuf * rev
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[: j - i] * gain


def track(dur, base, clack_iv0, clack_iv1, gain=1.0, rev=0.0, revbuf=None,
          motor_lvl=0.0, whoosh_lvl=0.0, squeal_at=None):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    out += rumble(dur) * base
    if motor_lvl:
        out += motor(dur, 180 + rng.uniform(-8, 8)) * motor_lvl
    pos = 0.05
    while pos < dur - 0.15:
        k = pos / dur
        iv = clack_iv0 + (clack_iv1 - clack_iv0) * k
        for off, lv in ((0.0, 1.0), (0.135, 0.55)):
            c = clack(1.0, 1.0)
            place(out, c, pos + off, 0.55 * lv)
        pos += max(0.28, iv) * rng.uniform(0.97, 1.03)
    if whoosh_lvl:
        out += whoosh(dur) * whoosh_lvl
    if squeal_at is not None:
        place(out, squeal(0.9), squeal_at, 0.35)
    if rev > 0:
        out = out + fftconvolve(out, revbuf)[:n] * rev
    # edge fades
    fade = int(0.12 * SR)
    if n > 2 * fade:
        out[:fade] *= np.linspace(0, 1, fade)
        out[-fade:] *= np.linspace(1, 0, fade)
    return out * gain


revbuf = ir()

buf = np.zeros(N)
# 01 tunnel POV 0.0-1.6 : close, echoey, decelerating slightly
place(buf, track(1.75, 0.55, 0.55, 0.72, rev=0.55, revbuf=revbuf, motor_lvl=0.10), 0.0, 1.0)
# 08 bridge 13.8-16.7 : distant, airy
place(buf, track(3.0, 0.16, 0.9, 0.9, whoosh_lvl=0.06), 13.75, 0.55)
# 07 tunnel 2 11.4-13.8
place(buf, track(2.55, 0.50, 0.6, 0.6, rev=0.5, revbuf=revbuf, motor_lvl=0.09), 11.35, 0.95)
# 05b arrival 16.7-18.2 : braking, squeal
place(buf, track(1.6, 0.42, 0.85, 0.5, rev=0.35, revbuf=revbuf, motor_lvl=0.07,
                 squeal_at=1.15), 16.65, 0.95)
# 05c platform 18.2-19.2 : train passing, no reverb
place(buf, track(1.15, 0.30, 0.42, 0.46, whoosh_lvl=0.10), 18.15, 0.9)

# gentle low-shelf lift on the sub, keep mids clean
buf = buf / (np.max(np.abs(buf)) + 1e-9) * 0.85
st = np.stack([buf, np.roll(buf, int(0.004 * SR))], axis=1)
st = np.clip(st, -1, 1)
out = (st * 32767).astype(np.int16)
import wave
with wave.open("/workspace/rail-promo/out/sfx_rail.wav", "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(out.tobytes())
print("wrote sfx_rail.wav")
