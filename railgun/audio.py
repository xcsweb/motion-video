#!/usr/bin/env python3
"""Procedural 120 BPM electronic track for the RAILGUN MV.

Everything is synthesized from scratch (no third-party samples, no copyright
issues).  The same constants drive the visuals so every cut lands on a beat.
"""
import json
import wave

import numpy as np
from scipy import signal

SR = 44100
DURATION = 24.0
BPM = 120
BEAT = 60.0 / BPM          # 0.5 s
BAR = 4 * BEAT             # 2.0 s

LAUNCH1 = 6.0
LAUNCH2 = 16.0
IMPACT1 = 8.0
IMPACT2 = 18.0
N = int(SR * DURATION)

rng = np.random.default_rng(20261104)


# ---------------------------------------------------------------- helpers
def t_axis(dur):
    return np.arange(int(dur * SR), dtype=np.float64) / SR


def env_exp(n, decay):
    return np.exp(-np.arange(n) / SR * decay)


def filt(x, kind, cutoff, order=2):
    sos = signal.butter(order, cutoff, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def add(buf, sig, start, gain=1.0, pan=0.0):
    """Add a mono signal into a stereo buffer with constant-power panning."""
    i0 = int(round(start * SR))
    if i0 >= N or i0 + len(sig) <= 0:
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
    m = np.max(np.abs(x)) + 1e-9
    return x * (peak / m)


# ---------------------------------------------------------------- drums
def kick():
    t = t_axis(0.55)
    f = 42.0 + 145.0 * np.exp(-t * 26.0)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t * 7.0)
    click = rng.standard_normal(len(t)) * np.exp(-t * 110.0) * 0.22
    return norm(body + click)


def snare():
    t = t_axis(0.22)
    noise = filt(rng.standard_normal(len(t)), "bandpass", [420, 7200])
    body = noise * np.exp(-t * 16.0)
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 22.0) * 0.45
    return norm(body + tone)


def hat(open_=False):
    dur = 0.14 if open_ else 0.055
    t = t_axis(dur)
    n = filt(rng.standard_normal(len(t)), "highpass", 6200)
    return norm(n * np.exp(-t * (22.0 if open_ else 70.0)))


def clap():
    t = t_axis(0.18)
    out = np.zeros_like(t)
    for d in (0.0, 0.018, 0.036):
        s = int(d * SR)
        n = filt(rng.standard_normal(len(t) - s), "bandpass", [700, 5200])
        out[s:] += n * np.exp(-np.arange(len(t) - s) / SR * 30.0)
    return norm(out)


# ---------------------------------------------------------------- tonal
NOTE = {n: 440.0 * 2 ** (v / 12) for n, v in {
    "A3": -12, "B3": -10, "C4": -9, "D4": -7, "E4": -5, "F4": -4,
    "G4": -2, "A4": 0, "B4": 2, "C5": 3, "D5": 5, "E5": 7, "F5": 8,
    "G5": 10, "A5": 12, "C6": 15, "E6": 19, "A2": -24, "C3": -21,
    "E3": -17, "F3": -16, "G3": -14, "D3": -19,
}.items()}


def saw_note(freq, dur, cutoff=2400, decay=5.0, detune=0.012):
    t = t_axis(dur)
    x = np.zeros(len(t))
    for d in (-detune, 0.0, detune):
        ph = (t * freq * (1 + d)) % 1.0
        x += (ph * 2.0 - 1.0)
    x /= 3.0
    x = filt(x, "lowpass", cutoff)
    x *= np.exp(-t * decay)
    x[: int(0.006 * SR)] *= np.linspace(0, 1, int(0.006 * SR))
    return x


def bass_note(freq, dur):
    t = t_axis(dur)
    ph = (t * freq) % 1.0
    x = (ph * 2.0 - 1.0)
    x = filt(x, "lowpass", 320, order=3)
    x = np.tanh(x * 1.6)
    x *= np.exp(-t * 4.0)
    return x


def pad_chord(freqs, dur, gain=1.0):
    t = t_axis(dur)
    x = np.zeros(len(t))
    for f in freqs:
        for d in (-0.006, 0.0, 0.006):
            x += np.sin(2 * np.pi * f * (1 + d) * t + rng.uniform(0, 6.28))
    x = filt(x, "lowpass", 1800) / (len(freqs) * 3)
    env = np.minimum(1.0, t / 0.4) * np.minimum(1.0, (dur - t) / 0.5)
    return x * env * gain


# ---------------------------------------------------------------- fx
def riser(dur, f0=180.0, f1=2400.0):
    t = t_axis(dur)
    sweep = np.sin(2 * np.pi * np.cumsum(f0 * (f1 / f0) ** (t / dur)) / SR)
    noise = rng.standard_normal(len(t))
    noise = filt(noise, "bandpass", [600, 5000])
    env = (t / dur) ** 2.2
    return norm((sweep * 0.6 + noise * 0.5) * env)


def charge_whine(dur, f0=120.0, f1=1500.0):
    t = t_axis(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    f = f * (1 + 0.03 * np.sin(2 * np.pi * 11 * t))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)
    x = np.tanh(x * 2.2)
    env = (t / dur) ** 1.4
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * 13 * t)
    return x * env * trem


def zap(dur=0.35):
    t = t_axis(dur)
    f = 60.0 + 3800.0 * np.exp(-t * 13.0)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.tanh(np.sin(ph) * 2.5)
    x = filt(x, "bandpass", [120, 9000])
    return x * np.exp(-t * 9.0)


def impact(power=1.0):
    dur = 1.6
    t = t_axis(dur)
    sub = np.sin(2 * np.pi * 44 * t) * np.exp(-t * 3.2)
    mid = np.sin(2 * np.pi * 96 * t) * np.exp(-t * 7.0)
    nz = rng.standard_normal(len(t))
    nz = filt(nz, "lowpass", 1400) * np.exp(-t * 5.5)
    ring = np.zeros(len(t))
    for f in (740, 1180, 1960, 3100):
        ring += np.sin(2 * np.pi * f * t + rng.uniform(0, 6)) * np.exp(-t * 4.0)
    ring /= 4.0
    x = (sub * 1.1 + mid * 0.55 + nz * 0.7 + ring * 0.28)
    return norm(x) * power


def explosion(dur=2.2):
    t = t_axis(dur)
    nz = rng.standard_normal(len(t))
    nz = filt(nz, "lowpass", 520)
    body = nz * np.exp(-t * 2.4)
    rumble = np.sin(2 * np.pi * 36 * t) * np.exp(-t * 2.0)
    crack = np.zeros(len(t))
    for _ in range(26):
        s = rng.uniform(0, dur - 0.08)
        i = int(s * SR)
        ln = int(0.05 * SR)
        burst = filt(rng.standard_normal(ln), "bandpass", [900, 6000]) * np.exp(
            -np.arange(ln) / SR * 40)
        crack[i:i + ln] += burst * rng.uniform(0.3, 1.0)
    return norm(body * 1.0 + rumble * 0.8 + crack * 0.5)


def electrical_crackle(dur, density=14.0, level=0.5):
    t = t_axis(dur)
    out = np.zeros(len(t))
    n = int(dur * density)
    for _ in range(n):
        s = rng.uniform(0, dur - 0.06)
        ln = int(rng.uniform(0.012, 0.05) * SR)
        i = int(s * SR)
        burst = filt(rng.standard_normal(ln), "bandpass", [rng.uniform(800, 2500), rng.uniform(5000, 9500)])
        burst = burst / (np.max(np.abs(burst)) + 1e-9)
        burst *= np.exp(-np.arange(ln) / SR * rng.uniform(40, 120))
        out[i:i + ln] += burst * rng.uniform(0.3, 1.0)
    return out * level


# ---------------------------------------------------------------- arrangement
music = np.zeros((N, 2))
fx = np.zeros((N, 2))
lead_buf = np.zeros((N, 2))
bass_buf = np.zeros((N, 2))

KICK = kick()
SNARE = snare()
HAT = hat()
HATO = hat(open_=True)
CLAP = clap()

# --- pads: ambient bed across the whole piece
pad_sections = [
    (0.0, 6.0, ["A3", "C4", "E4"], 0.55),
    (6.0, 12.0, ["A3", "C4", "E4"], 0.32),
    (12.0, 16.0, ["F3", "A3", "C4"], 0.6),
    (16.0, 22.0, ["A3", "C4", "E4"], 0.32),
    (22.0, 24.0, ["A3", "C4", "E4"], 0.8),
]
for start, end, notes, g in pad_sections:
    add(music, pad_chord([NOTE[n] for n in notes], end - start), start, g)

# --- charge 1 (0-4) and charge 2 (12-16)
for start, dur in ((0.0, 4.0), (12.0, 4.0)):
    add(fx, charge_whine(dur), start, 0.30)
    add(fx, electrical_crackle(dur, 16 if start == 0 else 22, 0.55), start, 0.55)

# --- build 1 (4-6): accelerating kicks + snare roll + riser
build_kicks = [4.0, 4.5, 4.9, 5.2, 5.45, 5.65, 5.8, 5.9]
for i, bt in enumerate(build_kicks):
    add(music, KICK, bt, 0.55 + i * 0.05, pan=0.0)
roll = np.linspace(5.0, 6.0, 9)
for i, st in enumerate(roll):
    add(music, SNARE, st, 0.25 + i * 0.045, pan=0.12)
add(fx, riser(2.0), 4.0, 0.65)
add(fx, electrical_crackle(1.8, 40, 0.6), 4.2, 0.5)

# --- drop 1 (6-12): four on the floor + bass + lead arps
lead_notes = ["A4", "C5", "E5", "A5", "G5", "E5", "C5", "E5"]
for k in range(12):                      # 6.0 .. 12.0
    bt = 6.0 + k * BEAT
    add(music, KICK, bt, 0.95)
    add(music, HAT, bt + 0.125, 0.30, pan=0.25)
    add(music, HAT, bt + 0.375, 0.22, pan=-0.2)
    if k % 2 == 1:
        add(music, SNARE, bt, 0.42)
        add(music, CLAP, bt, 0.30)
for k in range(12):                      # eighth-note bass
    st = 6.0 + k * BEAT / 2
    add(bass_buf, bass_note(NOTE["A2"] if k % 2 else NOTE["C3"], BEAT / 2), st, 0.5)
for k in range(24):                      # sixteenth lead arp
    st = 6.0 + k * BEAT / 4
    n = lead_notes[k % len(lead_notes)]
    add(lead_buf, saw_note(NOTE[n], 0.22, cutoff=3200, decay=6.0), st, 0.28, pan=0.15 if k % 2 else -0.15)

# --- re-arm (12-16): sparse heartbeat kicks + reverse-feeling snare + pad
for k in range(4):
    add(music, KICK, 12.0 + k * 1.0, 0.45)
add(fx, riser(2.0, 140, 1800), 14.0, 0.6)
add(fx, electrical_crackle(3.6, 25, 0.55), 12.2, 0.6)
for i, st in enumerate(np.linspace(14.6, 16.0, 6)):
    add(music, SNARE, st, 0.3 + i * 0.07, pan=0.1)

# --- drop 2 (16-22): double time energy + rainbow lead
lead2 = ["A4", "E5", "A5", "C6", "E6", "C6", "A5", "E5"]
for k in range(12):
    bt = 16.0 + k * BEAT
    add(music, KICK, bt, 1.0)
    add(music, KICK, bt + 0.25, 0.35)    # extra off-beat punch
    add(music, HAT, bt + 0.125, 0.34, pan=0.3)
    add(music, HATO, bt + 0.375, 0.26, pan=-0.25)
    if k % 2 == 1:
        add(music, SNARE, bt, 0.5)
        add(music, CLAP, bt, 0.36)
for k in range(24):
    st = 16.0 + k * BEAT / 2
    add(bass_buf, bass_note(NOTE["A2"] if k % 2 else NOTE["E3"], BEAT / 2), st, 0.55)
for k in range(48):
    st = 16.0 + k * BEAT / 8
    n = lead2[k % len(lead2)]
    add(lead_buf, saw_note(NOTE[n], 0.16, cutoff=4200, decay=8.0), st, 0.26, pan=0.2 if k % 2 else -0.2)

# --- impacts at launches and projectile hits
add(fx, impact(1.0), LAUNCH1, 1.0)
add(fx, zap(0.5), LAUNCH1, 0.85)
add(fx, explosion(2.2), IMPACT1, 0.85)
add(fx, impact(1.15), LAUNCH2, 1.0)
add(fx, zap(0.6), LAUNCH2, 0.95)
add(fx, explosion(2.4), IMPACT2, 1.0)
add(fx, explosion(2.0), 20.0, 0.5)
add(fx, impact(0.7), 22.0, 0.55)
add(fx, explosion(1.4), 22.4, 0.4)

# --- sidechain: duck tonal layers under the kick
duck = np.ones(N)
for k in range(0, 48):
    bt = 6.0 + k * BEAT
    if bt > 22.0:
        break
    i0 = int(bt * SR)
    ln = int(0.28 * SR)
    i1 = min(N, i0 + ln)
    duck[i0:i1] = np.minimum(duck[i0:i1], 0.35 + 0.65 * np.linspace(0, 1, i1 - i0) ** 1.5)
for bt in (4.0, 4.5, 4.9, 5.2, 5.45, 5.65, 5.8, 5.9):
    i0 = int(bt * SR)
    ln = int(0.22 * SR)
    i1 = min(N, i0 + ln)
    duck[i0:i1] = np.minimum(duck[i0:i1], 0.5 + 0.5 * np.linspace(0, 1, i1 - i0) ** 2)

bass_buf *= duck[:, None]
lead_buf *= duck[:, None]

# simple ping-pong-ish delay for the lead
d = int(0.11 * SR)
lead_buf[d:] += lead_buf[:-d] * 0.32
lead_buf = np.tanh(lead_buf * 1.15) * 0.82

mix = music + bass_buf + lead_buf + fx

# gentle high-pass to remove DC, soft-clip, fade edges
mix = np.stack([filt(mix[:, c], "highpass", 24) for c in range(2)], axis=1)
mix = np.tanh(mix * 0.9)
mix *= np.minimum(1.0, np.arange(N) / (0.05 * SR))[:, None]
mix *= np.minimum(1.0, (N - np.arange(N)) / (0.35 * SR))[:, None]
mix = norm(mix, 0.94)

# mono compatibility check + write
out = (mix * 32767).astype(np.int16)
with wave.open("/workspace/railgun/music.wav", "wb") as f:
    f.setnchannels(2)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes(out.tobytes())

events = {
    "bpm": BPM,
    "duration": DURATION,
    "beat": BEAT,
    "bar": BAR,
    "launch1": LAUNCH1,
    "launch2": LAUNCH2,
    "impact1": IMPACT1,
    "impact2": IMPACT2,
    "beats": [round(i * BEAT, 4) for i in range(int(DURATION / BEAT) + 1)],
    "sections": [
        {"start": 0.0, "end": 4.0, "name": "charge1"},
        {"start": 4.0, "end": 6.0, "name": "build1"},
        {"start": 6.0, "end": 12.0, "name": "drop1"},
        {"start": 12.0, "end": 16.0, "name": "charge2"},
        {"start": 16.0, "end": 22.0, "name": "drop2"},
        {"start": 22.0, "end": 24.0, "name": "outro"},
    ],
}
with open("/workspace/railgun/events.json", "w") as f:
    json.dump(events, f, indent=2)

rms = np.sqrt(np.mean(mix ** 2))
print("wrote music.wav", out.shape, "rms", round(float(rms), 4), "peak", round(float(np.max(np.abs(mix))), 4))
