#!/usr/bin/env python3
"""Build the audio for one episode: voice-over + score + ambience + mix.

Score / ambience are synthesized, so nothing licensed is used. The structure
follows the editing handbook: ambience leads, voice enters after a beat,
the score changes section at the turn, and there is air at the end.

    python3 build/episode_audio.py --project projects/xiancheng
"""
import argparse
import json
import os
import wave

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 48000
MODEL_DIR = os.path.join(ROOT, "assets", "models", "matcha-icefall-zh-baker")
VOCODER = os.path.join(ROOT, "assets", "models", "vocos-22khz-univ.onnx")

# pause after each line, seconds
PAUSES = [0.85, 0.55, 0.50, 0.80, 0.50, 0.50, 0.55, 0.75, 0.65, 1.15, 0.45, 2.70]
LEAD_IN = 1.50          # ambience before the first line
TAIL = 3.60             # air after the last line
TURN_LINE = 9           # score changes section on this line (1-based)


# ------------------------------------------------------------------ helpers
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


def bandpass(sig, lo, hi, order=2, sr=SR):
    sos = butter(order, [lo / (sr / 2), hi / (sr / 2)], btype="band", output="sos")
    return sosfilt(sos, sig, axis=0)


def pan_gains(pan):
    p = (max(-1.0, min(1.0, pan)) + 1) * 0.5
    return np.sqrt(1 - p), np.sqrt(p)


def place(buf, sig, t):
    i = int(max(0, t) * SR)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(sig))
    buf[i:j] += sig[:j - i]


# ------------------------------------------------------------------ piano
def piano_note(freq, dur, vel, pan, rng):
    n = int((dur + 2.1) * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k in range(1, 9):
        fk = freq * k * np.sqrt(1 + 0.00038 * k * k)
        if fk > 15000:
            break
        amp = (1.0 / k ** 1.75) * (0.55 + 0.45 * vel) ** (k * 0.22)
        e = np.exp(-t * (0.95 + 0.52 * k + 0.35 * (1 - vel))) * (1 - np.exp(-t / 0.0035))
        out += amp * e * np.sin(2 * np.pi * fk * t + rng.uniform(0, 2 * np.pi))
    hn = int(0.035 * SR)
    tick = rng.normal(0, 1, hn) * np.exp(-np.arange(hn) / (0.006 * SR))
    out[:hn] += lowpass(tick, 2500, 1) * 0.20 * vel
    out = lowpass(out, 3600, 2)
    gl, gr = pan_gains(pan)
    return np.stack([out * gl, out * gr], axis=1) * vel


def strings_note(freq, dur, vel, pan, rng):
    n = int((dur + 1.6) * SR)
    t = np.arange(n) / SR
    e = env_ar(n, 0.55, 0.9)
    vib = 1 + 0.0035 * np.sin(2 * np.pi * 4.6 * t + rng.uniform(0, 6))
    out = np.zeros(n)
    for k in range(1, 11):
        fk = freq * k
        if fk > 9000:
            break
        out += (1.0 / k ** 1.15) * np.sin(2 * np.pi * fk * vib * t + rng.uniform(0, 6))
    out = lowpass(out, 2400, 2) * e * vel * 0.055
    gl, gr = pan_gains(pan)
    return np.stack([out * gl, out * gr], axis=1)


def pad_note(freq, n, amp, pan, rng):
    t = np.arange(n) / SR
    e = env_ar(n, 1.3, 1.5)
    sig = np.zeros(n)
    for det in (-0.003, 0.0, 0.003):
        sig += np.sin(2 * np.pi * freq * (1 + det) * t + rng.uniform(0, 6))
        sig += 0.25 * np.sin(2 * np.pi * 2 * freq * (1 + det) * t + rng.uniform(0, 6))
    sig = lowpass(sig, 1400, 2) * e * amp
    gl, gr = pan_gains(pan)
    return np.stack([sig * gl, sig * gr], axis=1)


# ------------------------------------------------------------------ score
CH_A = {"Am": [45, 52, 57, 60, 64], "F": [41, 48, 53, 57, 60],
        "C": [48, 55, 60, 64, 67], "G": [43, 50, 55, 59, 62]}
PROG_A = ["Am", "F", "C", "G"]
PROG_B = ["C", "G", "Am", "F"]


def section(total, bar, prog, t_from, kind, rng):
    """Render one score section. kind: 'a' (sparse) or 'b' (full)."""
    out = np.zeros((total, 2))
    end = total / SR
    if t_from >= end:
        return out
    bars = []
    t = t_from
    k = 0
    while t < end - 0.4:
        bars.append((t, prog[k % len(prog)], k))
        t += bar
        k += 1
    for t0, name, idx in bars:
        notes = CH_A[name]
        n = int((bar + 1.4) * SR)
        for j, midi in enumerate(notes[1:], 1):
            place(out, pad_note(mtof(midi), n, 0.16 / (1 + j * 0.5),
                                -0.45 + j * 0.22, rng), t0)
        # bass root, two hits
        for b in ((0.0, 0.30) if kind == "a" else (0.0, 0.28), (bar * 0.5, 0.22)):
            place(out, piano_note(mtof(notes[0] - 12), 2.2, b[1], -0.1, rng), t0 + b[0])
        # broken chord
        pattern = [1, 3, 2, 4, 3, 1, 2, 3]
        step = bar / 8 if kind == "a" else bar / 8
        for j, pidx in enumerate(pattern):
            if kind == "a" and j % 2 == 1 and idx < 2:
                continue
            if kind == "a" and j in (5, 7) and idx % 2 == 1:
                continue
            midi = notes[min(pidx, len(notes) - 1)] + 12
            vel = 0.085 + 0.03 * rng.random() + (0.02 if kind == "b" else 0)
            place(out, piano_note(mtof(midi), 0.9, vel,
                                  -0.35 + 0.2 * (pidx / 4), rng),
                  t0 + j * step + rng.normal(0, 0.006))
        # melody: sparse in a, warm strings doubling in b
        if kind == "b" and idx % 2 == 0:
            m = notes[3] + 12
            place(out, piano_note(mtof(m), 1.6, 0.30, 0.12, rng), t0 + 0.1)
            place(out, piano_note(mtof(m - 2), 1.2, 0.24, 0.12, rng), t0 + bar * 0.5)
            place(out, strings_note(mtof(notes[2]), bar * 0.95, 1.0, 0.0, rng), t0)
            place(out, strings_note(mtof(notes[3]), bar * 0.95, 0.9, 0.25, rng), t0)
    return out


def build_score(total, b_start, rng):
    a = section(total, 4.14, PROG_A, 0.0, "a", rng)
    b = section(total, 3.75, PROG_B, b_start, "b", rng)
    # a clean section change: fade A out just before B, then let B swell
    idx = int(b_start * SR)
    fade = int(0.55 * SR)
    a[max(0, idx - fade):idx] *= np.linspace(1, 0, min(fade, idx))[:, None]
    a[idx:] *= 0.0
    b[:int(0.35 * SR)] *= np.linspace(0, 1, int(0.35 * SR))[:, None]
    score = a + b
    # sub follows the active section so it never clashes at the turn
    roots = [(t, PROG_A[k % 4], 4.14) for k, t in enumerate(np.arange(0, b_start, 4.14))]
    roots += [(b_start + k * 3.75, PROG_B[k % 4], 3.75)
              for k in range(int(max(0, total / SR - b_start) / 3.75))]
    for t0, name, seg in roots:
        f = mtof(CH_A[name][0] - 24)
        n = int((seg + 0.4) * SR)
        tt = np.arange(n) / SR
        sig = np.sin(2 * np.pi * f * tt) * env_ar(n, 1.0, 1.2) * 0.10
        place(score, np.stack([sig, sig], axis=1), t0)
    return score


# ------------------------------------------------------------------ ambience
def amb_station(n, rng):
    t = np.arange(n) / SR
    rumble = lowpass(rng.normal(0, 1, n), 110, 2) * (0.55 + 0.45 * np.sin(2 * np.pi * 0.09 * t))
    squeal_env = np.exp(-((t - 0.55) ** 2) / 0.02)
    squeal = (np.sin(2 * np.pi * 2380 * t) * 0.5 + np.sin(2 * np.pi * 3100 * t) * 0.3)
    sig = rumble * 0.35 + squeal * squeal_env * 0.05
    return np.stack([sig, np.roll(sig, 731)], axis=1)


def amb_street(n, rng):
    t = np.arange(n) / SR
    base = lowpass(rng.normal(0, 1, n), 900, 2) * 0.06
    sig = np.stack([base, np.roll(base, 517)], axis=1)
    for _ in range(int(n / SR * 1.4)):
        f0 = rng.uniform(2200, 3900)
        dur = rng.uniform(0.05, 0.13)
        m = int(dur * SR)
        tt = np.arange(m) / SR
        chirp = np.sin(2 * np.pi * f0 * tt * (1 + 0.25 * tt / dur))
        chirp *= np.hanning(m) * rng.uniform(0.012, 0.03)
        pan = rng.uniform(-0.7, 0.7)
        gl, gr = pan_gains(pan)
        i = rng.integers(0, max(1, n - m))
        sig[i:i + m, 0] += chirp * gl
        sig[i:i + m, 1] += chirp * gr
    return sig


def amb_market(n, rng):
    t = np.arange(n) / SR
    murmur = bandpass(rng.normal(0, 1, n), 260, 1300, 2)
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 3.1 * t + 0.4)
    sig = np.stack([murmur * lfo, np.roll(murmur, 941) * np.roll(lfo, 331)], axis=1) * 0.045
    for _ in range(int(n / SR * 0.9)):
        m = int(0.09 * SR)
        tt = np.arange(m) / SR
        clink = np.sin(2 * np.pi * rng.uniform(1600, 3200) * tt) * np.exp(-tt / 0.02)
        i = rng.integers(0, max(1, n - m))
        pan = rng.uniform(-0.6, 0.6)
        gl, gr = pan_gains(pan)
        sig[i:i + m, 0] += clink * 0.02 * gl
        sig[i:i + m, 1] += clink * 0.02 * gr
    return sig


def amb_rain(n, rng):
    t = np.arange(n) / SR
    body = highpass(rng.normal(0, 1, n), 700, 2) * 0.05
    body = lowpass(body, 7000, 2)
    sig = np.stack([body, np.roll(body, 1337)], axis=1)
    drops = np.zeros(n)
    idx = rng.integers(0, n, int(n / SR * 60))
    drops[idx] = rng.uniform(0.02, 0.09, len(idx))
    drops = bandpass(drops, 900, 5200, 1)
    sig[:, 0] += drops * 0.6
    sig[:, 1] += np.roll(drops, 211) * 0.6
    return sig


def amb_night(n, rng):
    t = np.arange(n) / SR
    murmur = bandpass(rng.normal(0, 1, n), 180, 800, 2) * 0.035
    sig = np.stack([murmur, np.roll(murmur, 613)], axis=1)
    for _ in range(int(n / SR * 1.1)):
        m = int(0.12 * SR)
        tt = np.arange(m) / SR
        slap = rng.normal(0, 1, m) * np.exp(-tt / 0.012)
        slap = lowpass(slap, 2600, 2) * 0.09
        i = rng.integers(0, max(1, n - m))
        pan = rng.uniform(-0.5, 0.5)
        gl, gr = pan_gains(pan)
        sig[i:i + m, 0] += slap * gl
        sig[i:i + m, 1] += slap * gr
    return sig


def amb_wind(n, rng):
    t = np.arange(n) / SR
    w = lowpass(rng.normal(0, 1, n), 400, 2)
    w = highpass(w, 60, 2)
    lfo = 0.55 + 0.45 * np.sin(2 * np.pi * 0.03 * t + 0.7)
    return np.stack([w * lfo * 0.022, np.roll(w, 1601) * np.roll(lfo, 499) * 0.022], axis=1)


def build_ambience(total, events, rng):
    out = np.zeros((total, 2))
    place(out, amb_wind(total, rng), 0.0)
    for kind, t0, t1, gain in events:
        n = int((t1 - t0) * SR)
        if n <= 0:
            continue
        seg = {"station": amb_station, "street": amb_street, "market": amb_market,
               "rain": amb_rain, "night": amb_night}[kind](n, rng)
        f = int(min(1.1, (t1 - t0) / 3) * SR)
        seg[:f] *= np.linspace(0, 1, f)[:, None]
        seg[-f:] *= np.linspace(1, 0, f)[:, None]
        place(out, seg * gain, t0)
    return out


# ------------------------------------------------------------------ reverb
def make_ir(rng, seconds=3.0):
    n = int(seconds * SR)
    t = np.arange(n) / SR
    ir = np.zeros((n, 2))
    for ch in range(2):
        noise = lowpass(rng.normal(0, 1, n), 5200, 2)
        e = np.exp(-t / 0.82)
        e[:int(0.02 * SR)] = 0
        ir[:, ch] = noise * e
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True))
    return ir


def reverb(sig, ir, wet):
    out = np.zeros_like(sig)
    for ch in range(2):
        out[:, ch] = reverb_one(sig[:, ch], ir[:, ch])
    return sig + wet * out


def reverb_one(x, h):
    return fftconvolve(x, h)[:len(x)]


# ------------------------------------------------------------------ voice
def build_tts():
    import sherpa_onnx
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            matcha=sherpa_onnx.OfflineTtsMatchaModelConfig(
                acoustic_model=os.path.join(MODEL_DIR, "model-steps-3.onnx"),
                vocoder=VOCODER,
                lexicon=os.path.join(MODEL_DIR, "lexicon.txt"),
                tokens=os.path.join(MODEL_DIR, "tokens.txt"),
                dict_dir=os.path.join(MODEL_DIR, "dict"),
            ),
            num_threads=2,
            provider="cpu",
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def synth_lines(tts, lines, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for i, line in enumerate(lines, 1):
        audio = tts.generate(line, sid=0, speed=0.92)
        y = np.clip(np.array(audio.samples, np.float32), -1, 1)
        path = os.path.join(out_dir, f"line_{i:02d}.wav")
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(audio.sample_rate)
            f.writeframes((y * 32767).astype("<i2").tobytes())
        y = resample_poly(y.astype(np.float64), SR, audio.sample_rate)
        idx = np.where(np.abs(y) > 0.008)[0]
        if len(idx):
            y = y[max(0, idx[0] - int(0.05 * SR)): idx[-1] + int(0.08 * SR)]
        rows.append({"i": i, "text": line, "wav": path,
                     "duration": len(y) / SR, "audio": y})
        print(f"  {i:02d} {len(y) / SR:5.2f}s  {line}")
    return rows


def load_vo(lines, vo_dir):
    rows = []
    for i, line in enumerate(lines, 1):
        path = os.path.join(vo_dir, f"line_{i:02d}.wav")
        with wave.open(path, "rb") as f:
            sr = f.getframerate()
            y = np.frombuffer(f.readframes(f.getnframes()), np.int16)
        y = resample_poly(y.astype(np.float64) / 32768, SR, sr)
        idx = np.where(np.abs(y) > 0.008)[0]
        if len(idx):
            y = y[max(0, idx[0] - int(0.05 * SR)): idx[-1] + int(0.08 * SR)]
        rows.append({"i": i, "text": line, "wav": path,
                     "duration": len(y) / SR, "audio": y})
    return rows


def voice_chain(y):
    y = highpass(y, 95, 2)
    y = y + highpass(lowpass(y, 4200, 2), 2200, 2) * 0.28
    env = np.clip(lowpass(np.abs(y), 9, 2), 1e-6, None)
    thr = 0.07
    gain = np.clip(np.where(env > thr, (env / thr) ** (1 / 3.0 - 1), 1.0), 0.35, 1.0)
    y = np.tanh(y * gain * 1.22) / 1.22
    return y / (np.max(np.abs(y)) + 1e-9) * 0.56


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="projects/xiancheng")
    ap.add_argument("--reuse-vo", action="store_true")
    args = ap.parse_args()
    proj = os.path.join(ROOT, args.project)
    out_dir = os.path.join(proj, "audio")
    vo_dir = os.path.join(out_dir, "vo")
    os.makedirs(out_dir, exist_ok=True)

    lines = [l.strip() for l in open(os.path.join(proj, "narration.txt"),
                                     encoding="utf-8") if l.strip()]
    assert len(lines) == len(PAUSES), f"{len(lines)} lines vs {len(PAUSES)} pauses"

    print("voice ...")
    if args.reuse_vo and os.path.exists(os.path.join(vo_dir, f"line_{len(lines):02d}.wav")):
        rows = load_vo(lines, vo_dir)
        for row in rows:
            print(f"  {row['i']:02d} {row['duration']:5.2f}s  {row['text']}")
    else:
        tts = build_tts()
        rows = synth_lines(tts, lines, vo_dir)

    t = LEAD_IN
    for row, pause in zip(rows, PAUSES):
        row["start"] = t
        t += row["duration"] + pause
    total_s = t + TAIL
    total = int(total_s * SR)
    b_start = rows[TURN_LINE - 1]["start"] - 0.35
    print(f"total {total_s:.2f}s, score turns at {b_start:.2f}s")

    rng = np.random.default_rng(20261118)
    print("score ...")
    score = build_score(total, b_start, rng)
    ir = make_ir(rng)
    score = reverb(score, ir, 0.32)
    print("ambience ...")
    s = {r["i"]: r for r in rows}
    events = [
        ("station", 0.0, s[4]["start"] + 1.2, 0.55),
        ("street", s[3]["start"] - 1.0, s[5]["start"] + 1.0, 0.60),
        ("market", s[6]["start"] - 1.2, s[7]["start"] + 0.6, 0.65),
        ("rain", s[7]["start"] - 1.0, s[8]["start"] + 1.6, 0.85),
        ("night", s[8]["start"] - 1.0, s[9]["start"] + 2.0, 0.60),
    ]
    amb = build_ambience(total, events, rng)

    print("mix ...")
    voice = np.zeros((total, 2))
    for row in rows:
        y = voice_chain(row["audio"])
        y = highpass(y, 90, 2)
        y = np.stack([y, y], axis=1)
        y = reverb(y, ir, 0.14)
        f = int(0.015 * SR)
        y[:f] *= np.linspace(0, 1, f)[:, None]
        y[-f:] *= np.linspace(1, 0, f)[:, None]
        place(voice, y, row["start"])
        row["duration"] = len(row["audio"]) / SR

    env = lowpass(np.abs(voice.mean(axis=1)), 3.2, 2)
    env = env / (env.max() + 1e-9)
    duck = 1.0 - 0.66 * np.clip(env * 1.8, 0, 1)

    bed = np.tanh((score * 0.50 + amb) * 1.05) / 1.05
    bed_peak = np.max(np.abs(bed)) + 1e-9
    bed = bed / bed_peak * 0.33
    mix = bed * duck[:, None] + voice * 1.10

    fi, fo = int(1.2 * SR), int(2.6 * SR)
    mix[:fi] *= np.linspace(0, 1, fi)[:, None]
    mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    mix = np.tanh(mix * 1.02)
    mix = mix / (np.max(np.abs(mix)) + 1e-9) * 0.93

    pcm = lambda x: (np.clip(x, -1, 1) * 32767).astype(np.int16)
    wavfile.write(os.path.join(out_dir, "mix.wav"), SR, pcm(mix))
    wavfile.write(os.path.join(out_dir, "bgm.wav"), SR, pcm(bed))
    wavfile.write(os.path.join(out_dir, "vo.wav"), SR, pcm(voice))

    def srt_time(x):
        h, x = divmod(x, 3600)
        m, x = divmod(x, 60)
        s, ms = divmod(x, 1)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms * 1000):03d}"

    with open(os.path.join(out_dir, "subtitle.srt"), "w", encoding="utf-8") as f:
        for k, row in enumerate(rows, 1):
            f.write(f"{k}\n{srt_time(row['start'])} --> "
                    f"{srt_time(row['start'] + row['duration'])}\n{row['text']}\n\n")

    timing = [{"i": r["i"], "text": r["text"], "start": round(r["start"], 3),
               "duration": round(r["duration"], 3)} for r in rows]
    json.dump({"total": round(total_s, 3), "turn": round(b_start, 3),
               "lines": timing}, open(os.path.join(out_dir, "timing.json"), "w",
                                      encoding="utf-8"), ensure_ascii=False, indent=2)

    peak = float(np.max(np.abs(mix)))
    rms = float(np.sqrt(np.mean(mix ** 2)))
    print(f"wrote mix.wav  {total_s:.2f}s  peak {20*np.log10(peak):.2f} dBFS  "
          f"rms {20*np.log10(rms):.2f} dBFS")


if __name__ == "__main__":
    main()
