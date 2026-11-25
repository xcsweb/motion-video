#!/usr/bin/env python3
"""Generate the six Chinese voice lines and the procedural SFX set for the
35 s vertical short "同一个 nana，两种命".

Re-runnable: every output file is overwritten. Temporary files go to /tmp.

Outputs
  nana/assets/audio/voice/v1..v6.wav   48 kHz / mono / 16-bit
  nana/assets/audio/voice/meta.json
  nana/assets/audio/sfx/*.wav          48 kHz / stereo / 16-bit
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import sherpa_onnx
from scipy import signal
from scipy.io import wavfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_JSON = ROOT / "nana" / "config" / "script.json"
MODEL_DIR = ROOT / "nana" / "assets" / "models" / "vits-zh-hf-fanchen-C"
VOICE_DIR = ROOT / "nana" / "assets" / "audio" / "voice"
SFX_DIR = ROOT / "nana" / "assets" / "audio" / "sfx"
TMP_DIR = Path("/tmp")

SR_OUT = 48000
SR_TTS = 16000
PEAK_DB = -3.0          # voice peak target
SILENCE_DB = -45.0      # trim threshold
MARGIN_S = 0.040        # silence kept around the trimmed speech
GAP_S = 0.15            # required gap before the next line
MAX_SPEED = 1.15


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def db_to_lin(db):
    return float(10.0 ** (db / 20.0))


def peak_db(x):
    p = float(np.max(np.abs(x))) if len(x) else 0.0
    return 20.0 * np.log10(p) if p > 0 else -np.inf


def normalize_peak(x, target_db):
    p = float(np.max(np.abs(x)))
    if p <= 0:
        return x
    return x * (db_to_lin(target_db) / p)


def trim_silence(x, sr, thresh_db=SILENCE_DB, margin_s=MARGIN_S):
    thresh = db_to_lin(thresh_db)
    idx = np.flatnonzero(np.abs(x) > thresh)
    if len(idx) == 0:
        return x
    margin = int(round(margin_s * sr))
    a = max(0, int(idx[0]) - margin)
    b = min(len(x), int(idx[-1]) + 1 + margin)
    return x[a:b]


def fade_edges(x, sr, ms=3.0):
    n = min(len(x), int(sr * ms / 1000.0))
    if n < 2:
        return x
    ramp = np.linspace(0.0, 1.0, n, dtype=np.float64)
    if x.ndim == 2:
        ramp = ramp[:, None]
    y = x.astype(np.float64).copy()
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def write_wav(path, x, sr=SR_OUT):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.clip(x, -1.0, 1.0)
    wavfile.write(str(path), sr, (data * 32767.0).astype(np.int16))


def resample_16k_to_48k(x):
    return signal.resample_poly(x.astype(np.float64), 3, 1)


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #
def build_tts():
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=str(MODEL_DIR / "vits-zh-hf-fanchen-C.onnx"),
                lexicon=str(MODEL_DIR / "lexicon.txt"),
                tokens=str(MODEL_DIR / "tokens.txt"),
                dict_dir=str(MODEL_DIR / "dict"),
            ),
            num_threads=2,
            provider="cpu",
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def synth(tts, text, speed):
    audio = tts.generate(text, sid=0, speed=speed)
    x = np.asarray(audio.samples, dtype=np.float32)
    assert audio.sample_rate == SR_TTS, audio.sample_rate
    return x


def atempo(x, factor, tag):
    """ffmpeg atempo on a temp 16 kHz wav (pitch preserving)."""
    src = TMP_DIR / f"nana_{tag}_src.wav"
    dst = TMP_DIR / f"nana_{tag}_atempo.wav"
    write_wav(src, x, SR_TTS)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src), "-filter:a", f"atempo={factor:.4f}", str(dst)],
        check=True,
    )
    sr, y = wavfile.read(str(dst))
    y = y.astype(np.float32) / 32768.0
    if y.ndim > 1:
        y = y.mean(axis=1)
    return np.asarray(y, dtype=np.float32)


def build_voice_line(tts, line, tts_text, limit_s):
    """Synthesize + fit one line. Returns final 48 kHz mono float array."""
    base_speed = float(line["rate"])
    speed = base_speed
    x = trim_silence(synth(tts, tts_text, speed), SR_TTS)
    dur = len(x) / SR_TTS

    # 1) speed up step by step (never beyond 1.15)
    while dur > limit_s and speed < MAX_SPEED - 1e-6:
        speed = min(MAX_SPEED, round(speed + 0.02, 2))
        x = trim_silence(synth(tts, tts_text, speed), SR_TTS)
        dur = len(x) / SR_TTS
        print(f"    [{line['id']}] speed -> {speed:.2f}, dur {dur:.3f}s")

    # 2) still too long: ffmpeg atempo, still pitch preserving
    if dur > limit_s:
        factor = dur / (limit_s * 0.985)
        factor = min(max(factor, 1.0), 2.0)
        x = trim_silence(atempo(x, factor, line["id"]), SR_TTS)
        dur = len(x) / SR_TTS
        print(f"    [{line['id']}] atempo x{factor:.3f}, dur {dur:.3f}s")

    if dur > limit_s:
        raise RuntimeError(
            f"{line['id']} still {dur:.3f}s > allowed {limit_s:.3f}s")

    y = resample_16k_to_48k(x)
    y = normalize_peak(y, PEAK_DB).astype(np.float32)
    y = fade_edges(y, SR_OUT, 2.0)
    return y, dur, speed


# --------------------------------------------------------------------------- #
# SFX building blocks
# --------------------------------------------------------------------------- #
def _env(n, sr, attack, tau, curve=1.0):
    t = np.arange(n) / sr
    a = np.clip(t / max(attack, 1e-6), 0.0, 1.0) ** curve
    d = np.exp(-np.maximum(t - attack, 0.0) / tau)
    return a * d


def _bp(x, sr, lo, hi, order=2):
    sos = signal.butter(order, [lo, hi], btype="band", fs=sr, output="sos")
    return signal.sosfilt(sos, x)


def _lp(x, sr, f, order=2):
    sos = signal.butter(order, f, btype="low", fs=sr, output="sos")
    return signal.sosfilt(sos, x)


def _hp(x, sr, f, order=2):
    sos = signal.butter(order, f, btype="high", fs=sr, output="sos")
    return signal.sosfilt(sos, x)


def _decimate_stereo(mono):
    """Dual-mono stereo (keeps transients mono-compatible, no comb filter)."""
    return np.stack([mono, mono], axis=1)


def swept_noise(dur, rng, f_start, f_end, sigma=0.45, win_s=0.025):
    """Band-limited noise whose centre frequency sweeps exponentially."""
    n = int(dur * SR_OUT)
    x = rng.standard_normal(n)
    win = max(128, int(win_s * SR_OUT) // 2 * 2)
    hop = win // 2
    w = np.hanning(win)
    pad = win
    xp = np.concatenate([np.zeros(pad), x, np.zeros(pad)])
    n_frames = 1 + (len(xp) - win) // hop
    out = np.zeros(len(xp))
    norm = np.zeros(len(xp))
    freqs = np.fft.rfftfreq(win, 1.0 / SR_OUT)
    lf = np.log(np.maximum(freqs, 20.0))
    ln2 = np.log(2.0)
    for i in range(n_frames):
        s = i * hop
        spec = np.fft.rfft(xp[s:s + win] * w)
        frac = i / max(1, n_frames - 1)
        fc = f_start * (f_end / f_start) ** frac
        mask = np.exp(-0.5 * ((lf - np.log(fc)) / (sigma * ln2)) ** 2)
        y = np.fft.irfft(spec * mask, win)
        out[s:s + win] += y * w
        norm[s:s + win] += w * w
    out /= np.maximum(norm, 1e-9)
    return out[pad:pad + n]


# --------------------------------------------------------------------------- #
# SFX generators
# --------------------------------------------------------------------------- #
def sfx_keyboard():
    dur = 3.70
    n = int(round(dur * SR_OUT))
    left = np.zeros(n, dtype=np.float64)
    right = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(20240422)
    steps = 16
    step = dur / steps
    for i in range(steps):
        human = rng.uniform(-0.006, 0.006)
        onset = int(round((i * step + human) * SR_OUT))
        hit_n = int(0.075 * SR_OUT)
        if onset + hit_n > n:
            hit_n = n - onset
        t = np.arange(hit_n) / SR_OUT
        click = rng.standard_normal(hit_n) * _env(hit_n, SR_OUT, 0.0008, 0.006)
        click = _bp(click, SR_OUT, 1800.0, 6200.0)
        body = (np.sin(2 * np.pi * 165.0 * t)
                + 0.45 * np.sin(2 * np.pi * 310.0 * t))
        body *= _env(hit_n, SR_OUT, 0.0015, 0.018)
        accent = 1.0 if i % 4 == 0 else (0.78 if i % 2 == 0 else 0.6)
        amp = accent * rng.uniform(0.8, 1.05)
        hit = (0.55 * click / (np.max(np.abs(click)) + 1e-9)
               + 0.35 * body)
        hit *= amp
        pan = rng.uniform(-0.28, 0.28)
        l_gain = np.cos((pan + 1.0) * np.pi / 4.0)
        r_gain = np.sin((pan + 1.0) * np.pi / 4.0)
        left[onset:onset + hit_n] += hit * l_gain
        right[onset:onset + hit_n] += hit * r_gain
    # a little tonal variety: one softer key pair inside the loop
    st = np.stack([left, right], axis=1)
    st = normalize_peak(st, -3.0)
    return fade_edges(st, SR_OUT, 2.0)


def sfx_whoosh():
    dur = 0.35
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(7)
    t = np.arange(n) / SR_OUT
    peak_at = 0.62
    env = np.where(
        t < peak_at * dur,
        (t / (peak_at * dur)) ** 2.2,
        ((1.0 - t / dur) / (1.0 - peak_at)) ** 1.4,
    )
    l = swept_noise(dur, rng, 320.0, 6500.0, sigma=0.55)
    r = swept_noise(dur, rng, 300.0, 6000.0, sigma=0.5)
    # thin out the very low end so it stays airy
    l = _hp(l, SR_OUT, 180.0)
    r = _hp(r, SR_OUT, 180.0)
    st = np.stack([l * env, r * env], axis=1)
    return normalize_peak(fade_edges(st, SR_OUT, 4.0), -2.0)


def sfx_light_switch():
    dur = 0.25
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(11)
    out = np.zeros(n)
    click_n = int(0.010 * SR_OUT)
    t = np.arange(click_n) / SR_OUT
    click = _hp(rng.standard_normal(click_n), SR_OUT, 2200.0)
    click *= np.exp(-t / 0.0022)
    out[:click_n] += 0.9 * click / (np.max(np.abs(click)) + 1e-9)
    body_n = int(0.060 * SR_OUT)
    tb = np.arange(body_n) / SR_OUT
    body = (0.6 * np.sin(2 * np.pi * 1750.0 * tb)
            + 0.4 * np.sin(2 * np.pi * 3250.0 * tb))
    body *= np.exp(-tb / 0.008)
    out[:body_n] += 0.55 * body
    thud_n = int(0.090 * SR_OUT)
    tt = np.arange(thud_n) / SR_OUT
    out[:thud_n] += 0.08 * np.sin(2 * np.pi * 130.0 * tt) * np.exp(-tt / 0.018)
    mono = fade_edges(out, SR_OUT, 1.0)
    return normalize_peak(_decimate_stereo(mono), -2.0)


def sfx_slipper():
    dur = 0.30
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(23)
    out = np.zeros(n)

    def slap(offset, amp):
        m = int(0.10 * SR_OUT)
        t = np.arange(m) / SR_OUT
        nz = _lp(rng.standard_normal(m), SR_OUT, 1400.0)
        nz *= _env(m, SR_OUT, 0.0012, 0.016)
        nz /= np.max(np.abs(nz)) + 1e-9
        f0 = 105.0 * np.exp(-t / 0.05) + 58.0
        phase = 2 * np.pi * np.cumsum(f0) / SR_OUT
        thump = np.sin(phase) * _env(m, SR_OUT, 0.002, 0.030)
        hit = (0.6 * nz + 0.9 * thump) * amp
        s = int(offset * SR_OUT)
        out[s:s + m] += hit[:n - s]

    slap(0.0, 1.0)
    slap(0.085, 0.55)
    mono = fade_edges(out, SR_OUT, 1.5)
    return normalize_peak(_decimate_stereo(mono), -2.5)


def sfx_heartbeat():
    dur = 1.60
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(31)
    out = np.zeros(n)

    def beat(offset, amp):
        m = int(0.32 * SR_OUT)
        t = np.arange(m) / SR_OUT
        f0 = 62.0 * np.exp(-t / 0.09) + 38.0
        phase = 2 * np.pi * np.cumsum(f0) / SR_OUT
        tone = np.sin(phase) + 0.35 * np.sin(2 * phase)
        tone *= _env(m, SR_OUT, 0.006, 0.070)
        nz = _lp(rng.standard_normal(m), SR_OUT, 220.0)
        nz *= _env(m, SR_OUT, 0.004, 0.035)
        nz /= np.max(np.abs(nz)) + 1e-9
        hit = (tone + 0.25 * nz) * amp
        s = int(offset * SR_OUT)
        out[s:s + m] += hit[:n - s]

    beat(0.14, 1.0)
    beat(0.92, 0.8)
    mono = fade_edges(out, SR_OUT, 2.0)
    return normalize_peak(_decimate_stereo(mono), -3.0)


def sfx_tv_static():
    dur = 1.50
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(47)
    t = np.arange(n) / SR_OUT

    def chan():
        x = rng.standard_normal(n)
        # pink-ish tilt: less hissy than flat white noise
        spec = np.fft.rfft(x)
        freqs = np.fft.rfftfreq(n, 1.0 / SR_OUT)
        tilt = 1.0 / (np.maximum(freqs, 40.0) / 40.0) ** 0.35
        x = np.fft.irfft(spec * tilt, n)
        x = _bp(x, SR_OUT, 120.0, 6000.0, order=3)
        x /= np.sqrt(np.mean(x ** 2)) + 1e-9
        # sparse crackles, kept well below the noise bed's peaks
        for _ in range(40):
            pos = rng.integers(0, n)
            ln = rng.integers(6, 26)
            seg = rng.standard_normal(min(ln, n - pos))
            x[pos:pos + len(seg)] += (0.7 * seg
                                      * np.exp(-np.arange(len(seg)) / (ln / 3.0)))
        mod = 1.0 + 0.16 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6.28))
        x *= mod
        return x / (np.sqrt(np.mean(x ** 2)) + 1e-9)

    st = np.stack([chan(), chan()], axis=1)
    st = fade_edges(st, SR_OUT, 12.0)
    return normalize_peak(st, -3.5)


def sfx_impact():
    dur = 0.50
    n = int(round(dur * SR_OUT))
    rng = np.random.default_rng(59)
    t = np.arange(n) / SR_OUT

    f0 = 118.0 * np.exp(-t / 0.055) + 34.0
    phase = 2 * np.pi * np.cumsum(f0) / SR_OUT
    sub = np.sin(phase) * _env(n, SR_OUT, 0.0025, 0.115)

    nz = _lp(rng.standard_normal(n), SR_OUT, 900.0)
    nz *= _env(n, SR_OUT, 0.001, 0.030)
    nz /= np.max(np.abs(nz)) + 1e-9

    click = _hp(rng.standard_normal(n), SR_OUT, 3000.0)
    click *= _env(n, SR_OUT, 0.0006, 0.005)
    click /= np.max(np.abs(click)) + 1e-9

    mono = 1.0 * sub + 0.35 * nz + 0.18 * click
    mono = np.tanh(1.6 * mono) / np.tanh(1.6)   # soft saturation, no clipping
    mono = fade_edges(mono, SR_OUT, 2.0)
    st = _decimate_stereo(mono)
    return normalize_peak(st, -1.5)


SFX = {
    "keyboard": sfx_keyboard,
    "whoosh": sfx_whoosh,
    "light_switch": sfx_light_switch,
    "slipper": sfx_slipper,
    "heartbeat": sfx_heartbeat,
    "tv_static": sfx_tv_static,
    "impact": sfx_impact,
}


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def probe(path):
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=sample_rate,channels,duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    return json.loads(res.stdout)["streams"][0]


def validate_all():
    ok = True
    files = sorted(VOICE_DIR.glob("v*.wav")) + sorted(SFX_DIR.glob("*.wav"))
    print("\n=== WAV check ===")
    print(f"{'file':22s} {'sr':>6s} {'ch':>2s} {'dur(s)':>7s} {'peak(dBFS)':>10s}")
    for f in files:
        info = probe(f)
        sr, ch = int(info["sample_rate"]), int(info["channels"])
        data = wavfile.read(str(f))[1]
        x = data.astype(np.float64) / 32768.0
        p = peak_db(x)
        dur = len(x) / sr
        print(f"{f.name:22s} {sr:6d} {ch:2d} {dur:7.3f} {p:10.2f}")
        if sr != 48000:
            print(f"  !! {f.name}: sample rate {sr}")
            ok = False
        if p > -1.0 + 1e-6:
            print(f"  !! {f.name}: peak {p:.2f} dBFS above -1 dBFS")
            ok = False
        if f.parent == VOICE_DIR and ch != 1:
            print(f"  !! {f.name}: expected mono")
            ok = False
        if f.parent == SFX_DIR and ch != 2:
            print(f"  !! {f.name}: expected stereo")
            ok = False
    return ok


# --------------------------------------------------------------------------- #
def main():
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    SFX_DIR.mkdir(parents=True, exist_ok=True)

    script = json.loads(SCRIPT_JSON.read_text(encoding="utf-8"))
    lines = script["voice_lines"]
    film_end = float(script.get("duration", 35.0))

    tts = build_tts()
    print(f"TTS ready: {tts.sample_rate} Hz, {tts.num_speakers} speakers")

    meta = []
    for i, line in enumerate(lines):
        nxt = float(lines[i + 1]["t"]) if i + 1 < len(lines) else film_end
        start = float(line["t"])
        limit = nxt - GAP_S - start
        if limit <= 0:
            raise RuntimeError(f"{line['id']}: no room at t={start}")
        tts_text = line["text"].replace("nana", "娜娜").replace("Nana", "娜娜")
        print(f"  {line['id']} t={start:.2f} limit={limit:.2f}s  {tts_text!r}")
        y, dur, speed = build_voice_line(tts, line, tts_text, limit)
        out = VOICE_DIR / f"{line['id']}.wav"
        write_wav(out, y, SR_OUT)
        end = start + len(y) / SR_OUT
        meta.append({
            "id": line["id"],
            "text": line["text"],
            "tts_text": tts_text,
            "start": start,
            "duration": round(len(y) / SR_OUT, 4),
            "end": round(end, 4),
            "file": str(out.relative_to(ROOT)),
            "peak": round(peak_db(y.astype(np.float64)), 2),
            "speed": speed,
        })

    (VOICE_DIR / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("\n=== voice timing ===")
    limits = []
    for i, (m, line) in enumerate(zip(meta, lines)):
        nxt = float(lines[i + 1]["t"]) if i + 1 < len(lines) else film_end
        limits.append(nxt)
        gap = nxt - m["end"]
        flag = "OK" if gap >= GAP_S - 1e-6 else "TOO LONG"
        print(f"{m['id']}: {m['start']:6.2f} -> {m['end']:6.2f}  "
              f"dur {m['duration']:.3f}s  gap {gap:.3f}s  {flag}")

    print("\n=== SFX ===")
    for name, fn in SFX.items():
        st = fn()
        write_wav(SFX_DIR / f"{name}.wav", st, SR_OUT)
        print(f"  {name}.wav  {len(st) / SR_OUT:.3f}s  peak {peak_db(st):.2f} dBFS")

    if not validate_all():
        print("\nVALIDATION FAILED")
        sys.exit(1)

    over = [m["id"] for m, nxt in zip(meta, limits)
            if m["end"] > nxt - GAP_S + 1e-6]
    if over:
        print(f"\n!! lines overflow: {over}")
        sys.exit(1)
    print("\nAll good.")


if __name__ == "__main__":
    main()
