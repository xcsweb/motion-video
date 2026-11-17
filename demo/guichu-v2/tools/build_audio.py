#!/usr/bin/env python3
"""Build the audio-first guichu track: 16 bars @105.47 BPM.

Pipeline:
 1. split 6 known vocal phrases into 7 syllables each
 2. WORLD-analyse every syllable (F0 / spectral envelope / aperiodicity)
 3. re-synthesise short hits at target pitches on the 16th grid
 4. synthesise backing (drums, bass, chords, riser, impact)
 5. sidechain + reverb + limiter -> assets/mix.wav
"""
import os, json, math, sys
import numpy as np
import scipy.io.wavfile as wf
from scipy.signal import butter, sosfilt, fftconvolve
import pyworld as pw

SR = 48000
BPM = 105.47
BEAT = 60.0 / BPM
BAR = BEAT * 4
SIX = BEAT / 4
S32 = BEAT / 8
TOTAL_BARS = 16
DUR = TOTAL_BARS * BAR

ROOT = '/workspace/demo/guichu-v2'
VOCAL_SRC = '/workspace/demo/guichu-song/song-vocals-autotuned.wav'
NOTE = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def read_mono(path, target=SR):
    sr, x = wf.read(path)
    if x.dtype.kind == 'i':
        x = x.astype(np.float32) / 32768.0
    else:
        x = x.astype(np.float32)
    if x.ndim > 1:
        x = x.mean(1)
    if sr != target:
        from scipy.signal import resample_poly
        g = math.gcd(target, sr)
        x = resample_poly(x, target // g, sr // g).astype(np.float32)
    return x


def lowpass(x, fc, order=2):
    sos = butter(order, min(fc, SR / 2 - 100), 'low', fs=SR, output='sos')
    return sosfilt(sos, x).astype(np.float32)


def highpass(x, fc, order=2):
    sos = butter(order, max(fc, 20), 'high', fs=SR, output='sos')
    return sosfilt(sos, x).astype(np.float32)


def bandpass(x, lo, hi, order=2):
    sos = butter(order, [max(lo, 20), min(hi, SR / 2 - 100)], 'band', fs=SR, output='sos')
    return sosfilt(sos, x).astype(np.float32)


def env_follow(x, attack=0.02, release=0.15):
    a = math.exp(-1.0 / (attack * SR))
    r = math.exp(-1.0 / (release * SR))
    e = np.empty_like(x)
    prev = 0.0
    for i, v in enumerate(np.abs(x)):
        coeff = a if v > prev else r
        prev = coeff * prev + (1 - coeff) * v
        e[i] = prev
    return e


# ---------------------------------------------------------------- syllables
def split_syllables(x, sr, n=7):
    """The source phrases are sung at 120 BPM: one character per beat.
    Use fixed 0.5 s windows, trimmed to the voiced part, minimum 0.12 s."""
    beat = 0.5
    spans = []
    for i in range(n):
        a = i * beat
        b = (i + 1) * beat
        seg = x[int(a * sr):int(b * sr)]
        if len(seg) == 0:
            spans.append((a, b)); continue
        e = np.abs(seg)
        thr = max(e.max() * 0.06, 0.004)
        idx = np.where(e > thr)[0]
        if len(idx) < int(0.04 * sr):
            # fall back to the centre 0.2 s
            spans.append((a + 0.1, b - 0.1)); continue
        s0 = max(0, idx[0] - int(0.01 * sr))
        s1 = min(len(seg), idx[-1] + int(0.02 * sr))
        if (s1 - s0) / sr < 0.12:
            mid = (s0 + s1) / 2
            s0 = max(0, int(mid - 0.06 * sr))
            s1 = min(len(seg), int(mid + 0.06 * sr))
        spans.append((a + s0 / sr, a + s1 / sr))
    return spans


def analyse_phrase(path, n=7, frame_period=5.0):
    x = read_mono(path)
    sr = SR
    # the vocal file is 6 phrases at 120 BPM -> exactly 4.0 s each
    blocks = [(i * 4.0, (i + 1) * 4.0) for i in range(6)]
    phrases = blocks
    print('phrases:', [(round(a, 2), round(b, 2)) for a, b in phrases])
    return x, phrases


def build_library():
    x, phrases = analyse_phrase(VOCAL_SRC)
    lines = ['改革春风吹满地', '中国人民真争气', '齐心协力跨世纪', '一场大水没咋地']
    lib = {}
    for li in range(4):
        a, b = phrases[li]
        seg = x[int(a * SR):int(b * SR)]
        spans = split_syllables(seg, SR, 7)
        if len(spans) != 7:
            print(f'!! phrase {li} got {len(spans)} spans, fallback equal split')
            L = b - a
            spans = [(i * L / 7, (i + 1) * L / 7) for i in range(7)]
        chars = list(lines[li])
        syls = []
        for ci, (s, e) in enumerate(spans):
            y = seg[int(s * SR):int(e * SR)].astype(np.float64)
            if len(y) < 400:
                y = np.pad(y, (0, 400 - len(y)))
            f0, t = pw.harvest(y, SR, frame_period=5.0)
            f0 = pw.stonemask(y, f0, t, SR)
            sp = pw.cheaptrick(y, f0, t, SR)
            ap = pw.d4c(y, f0, t, SR)
            v = f0[f0 > 0]
            med = float(np.median(v)) if len(v) else 200.0
            syls.append({'char': chars[ci], 'f0': f0, 'sp': sp, 'ap': ap,
                         'med': med, 'dur': (e - s)})
            print(f'  {lines[li][ci]}  span {s:5.2f}-{e:5.2f} ({(e-s)*1000:4.0f}ms)  med {med:6.1f}Hz')
        lib[li] = syls
    return lib, lines


# ---------------------------------------------------------------- vocal render
def render_hit(syl, target_midi, dur, drift=0.3, fade=0.006):
    """Take the attack of a syllable and re-pitch it to target_midi."""
    frames = max(3, int(dur / 0.005))
    f0 = syl['f0'][:frames].copy()
    sp = syl['sp'][:frames].copy()
    ap = syl['ap'][:frames].copy()
    if len(f0) < frames:
        pad = frames - len(f0)
        f0 = np.pad(f0, (0, pad), mode='edge')
        sp = np.pad(sp, ((0, pad), (0, 0)), mode='edge')
        ap = np.pad(ap, ((0, pad), (0, 0)), mode='edge')
    med = syl['med']
    tgt = hz(target_midi)
    voiced = f0 > 0
    f0n = np.zeros_like(f0)
    if voiced.any():
        ratio = (f0[voiced] / med) ** drift
        f0n[voiced] = tgt * ratio
    # keep voicedness of the original attack; if all unvoiced, force pitch
    if not voiced.any():
        f0n[:] = tgt
    y = pw.synthesize(f0n, sp, ap, SR, frame_period=5.0)
    # trim / pad to exact length
    n = int(dur * SR)
    if len(y) < n:
        y = np.pad(y, (0, n - len(y)))
    else:
        y = y[:n]
    # envelope
    w = np.ones(n, dtype=np.float32)
    nf = min(int(fade * SR), n // 2)
    if nf > 2:
        w[:nf] = np.linspace(0, 1, nf) ** 0.5
        w[-nf:] = np.linspace(1, 0, nf) ** 0.5
    return (y * w).astype(np.float32)


def place(buf, x, t):
    a = int(t * SR)
    if a >= len(buf):
        return
    b = min(len(buf), a + len(x))
    buf[a:b] += x[:b - a]


def build_vocal(lib):
    out = np.zeros(int(DUR * SR) + SR, dtype=np.float32)
    # event list for reporting / subtitles
    events = []

    def char_hits(line_idx, char_idx, start_bar, start_beat, n_hits=4, target=55,
                  extra32=False, tail=0.115):
        """Place one character as n_hits sixteenth-note attacks."""
        syl = lib[line_idx][char_idx]
        base = start_bar * BAR + start_beat * BEAT
        for h in range(n_hits):
            t = base + h * SIX
            d = tail * 1.6 if h == 0 else (tail if h < n_hits - 1 else tail * 1.5)
            place(out, render_hit(syl, target, d), t)
        if extra32:
            place(out, render_hit(syl, target + 2, 0.06), base + n_hits * SIX)
        events.append({'bar': start_bar, 'beat': start_beat, 'char': syl['char'],
                       'midi': target, 'hits': n_hits + (1 if extra32 else 0)})

    # --- bars 0-1 intro: first four chars, sparse (one per beat) ---
    for i, midi in enumerate([67, 67, 67, 67]):
        char_hits(0, i, 0, i, n_hits=1, target=midi, tail=0.20)
    # bar 1: "春风" again, two hits each
    char_hits(0, 2, 1, 0, n_hits=2, target=55, tail=0.12)
    char_hits(0, 3, 1, 2, n_hits=2, target=51, tail=0.12)

    # --- bars 2-3 pre-drop: "改革春风" accelerating ---
    for i, midi in enumerate([55, 55, 51, 53]):
        char_hits(0, i, 2, i, n_hits=4, target=midi, extra32=(i >= 2))
    for i, midi in enumerate([55, 55, 51]):
        char_hits(0, i, 3, i, n_hits=4, target=midi, extra32=True)
    # bar 3 last beat is silent (handled by muting backing, vocal stops)

    # --- hooks and verses ---
    plan = [
        (4, 0, [55, 55, 55, 55, 51, 53, 55], 0.11),   # 改革春风吹满地
        (6, 0, [55, 55, 55, 55, 51, 53, 55], 0.11),   # repeat
        (8, 1, [55, 55, 51, 51, 53, 53, 55], 0.11),   # 中国人民真争气
        (10, 2, [55, 55, 51, 51, 53, 53, 55], 0.11),  # 齐心协力跨世纪
        (12, 3, [55, 55, 51, 51, 53, 53, 55], 0.11),  # 一场大水没咋地
    ]
    for bar, line, pitches, tail in plan:
        for ci, midi in enumerate(pitches):
            char_hits(line, ci, bar, ci, n_hits=4, target=midi,
                      extra32=(ci in (0, 3, 6)), tail=tail)

    # --- bar 14 hook short: 改革春风 ---
    for ci, midi in enumerate([55, 55, 51, 53]):
        char_hits(0, ci, 14, ci, n_hits=4, target=midi, extra32=True, tail=0.10)

    # --- bar 15 outro: 吹满地, last char long ---
    for ci, midi in enumerate([51, 53, 55]):
        char_hits(0, ci + 4, 15, ci, n_hits=4, target=midi, extra32=(ci < 2), tail=0.16)
    # final sustained G
    syl = lib[0][6]
    place(out, render_hit(syl, 55, 0.55), 15 * BAR + 3 * BEAT)

    return out[:int(DUR * SR)], events


# ---------------------------------------------------------------- backing
def synth_backing():
    n = int(DUR * SR)
    out = np.zeros(n, dtype=np.float32)
    # chord roots per bar (Cm, Bb, F, Gm cycle; resolve to Cm at the end)
    roots = {0: 48, 2: 46, 4: 41, 6: 43, 8: 48, 10: 46, 12: 41, 14: 43, 15: 48}
    chords = {0: [48, 51, 55], 2: [46, 50, 53], 4: [41, 45, 48],
              6: [43, 46, 50], 8: [48, 51, 55], 10: [46, 50, 53],
              12: [41, 45, 48], 14: [43, 46, 50], 15: [48, 51, 55]}

    def chords_at(bar):
        b = bar if bar in chords else max(k for k in chords if k <= bar)
        return b

    def make_kick():
        t = np.arange(int(0.5 * SR)) / SR
        f = 45 + 95 * np.exp(-t * 28)
        ph = 2 * np.pi * np.cumsum(f) / SR
        return (np.sin(ph) * np.exp(-t * 11) * 0.9).astype(np.float32)

    def make_snare():
        t = np.arange(int(0.25 * SR)) / SR
        noise = np.random.default_rng(3).normal(0, 1, len(t)).astype(np.float32)
        noise = bandpass(noise, 1200, 9000)
        body = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 30) * 0.3
        return ((noise * np.exp(-t * 22) * 0.5) + body).astype(np.float32)

    def make_hat(open_=False):
        dur = 0.18 if open_ else 0.06
        t = np.arange(int(dur * SR)) / SR
        noise = np.random.default_rng(5).normal(0, 1, len(t)).astype(np.float32)
        noise = highpass(noise, 7000, 2)
        return (noise * np.exp(-t * (18 if open_ else 55)) * 0.32).astype(np.float32)

    def make_impact():
        t = np.arange(int(1.2 * SR)) / SR
        f = 38 + 60 * np.exp(-t * 9)
        ph = 2 * np.pi * np.cumsum(f) / SR
        low = np.sin(ph) * np.exp(-t * 4.0)
        noise = bandpass(np.random.default_rng(9).normal(0, 1, len(t)).astype(np.float32), 80, 4000)
        return (low * 0.9 + noise * np.exp(-t * 7) * 0.35).astype(np.float32)

    def make_riser(dur):
        n = int(dur * SR)
        t = np.arange(n) / SR
        noise = np.random.default_rng(11).normal(0, 1, n).astype(np.float32)
        out = np.zeros(n, dtype=np.float32)
        # crude sweeping band: crossfade low and high passed noise
        lo = lowpass(noise, 800)
        hi = highpass(noise, 3000)
        for i in range(0, n, 256):
            a = i / n
            out[i:i + 256] = (lo[i:i + 256] * (1 - a) + hi[i:i + 256] * a)
        env = (t / dur) ** 2
        return (out * env * 0.5).astype(np.float32)

    kick = make_kick(); snare = make_snare(); hat = make_hat(False); ohat = make_hat(True)
    impact = make_impact()

    # --- drums ---
    for bar in range(TOTAL_BARS):
        for sixteenth in range(16):
            t = bar * BAR + sixteenth * SIX
            # intro: hats only, kick from bar 1 beat 3
            if bar == 0:
                if sixteenth % 4 == 0:
                    place(out, hat * 0.55, t)
                continue
            if bar == 1:
                if sixteenth % 2 == 0:
                    place(out, hat * (0.55 if sixteenth % 4 else 0.8), t)
                if sixteenth in (8, 11):
                    place(out, kick * 0.5, t)
                continue
            # pre-drop bars 2-3: full but last beat of bar 3 silent
            if bar == 3 and sixteenth >= 12:
                continue
            # hats
            if sixteenth % 4 == 0:
                place(out, hat, t)
            elif sixteenth % 2 == 0:
                place(out, hat * 0.55, t)
            else:
                place(out, hat * 0.28, t)
            if sixteenth in (6, 14) and bar % 2 == 1:
                place(out, ohat * 0.7, t)
            # kick
            if sixteenth in (0, 8):
                place(out, kick, t)
            if sixteenth in (7, 15) and bar % 2 == 1:
                place(out, kick * 0.55, t)
            if bar >= 4 and sixteenth == 10:
                place(out, kick * 0.4, t)
            # snare
            if sixteenth in (4, 12):
                place(out, snare, t)
            if bar >= 4 and sixteenth in (7, 15):
                place(out, snare * 0.16, t)

    # impact at drop and at bar 14
    place(out, impact * 0.9, 4 * BAR)
    place(out, impact * 0.7, 14 * BAR)
    # riser across bars 2-3
    place(out, make_riser(2 * BAR) * 0.9, 2 * BAR)
    # outro: remove drums after bar 15 beat 2 by fading the drum bus later? handled in mix

    # --- bass + chords (separate buffers so we can duck them) ---
    music = np.zeros(n, dtype=np.float32)
    for bar in range(TOTAL_BARS):
        cb = chords_at(bar)
        root = chords[cb][0] - 12
        # bass: 8th notes, octave pop on beat 3
        if bar == 0:
            beats = [0]
        elif bar in (1, 3, 15):
            beats = [0, 2]
        else:
            beats = [0, 1, 2, 3]
        for bi in beats:
            for half in (0, 0.5):
                t = bar * BAR + (bi + half) * BEAT
                if bar == 3 and bi == 3:
                    continue
                dur = BEAT * 0.46
                tt = np.arange(int(dur * SR)) / SR
                f = hz(root + (12 if (bi == 2 and half == 0) else 0))
                wave = 0.6 * np.sin(2 * np.pi * f * tt) + 0.4 * np.sign(np.sin(2 * np.pi * f * tt))
                env = np.minimum(1, tt / 0.008) * np.exp(-tt * 6)
                place(music, (wave * env * 0.36).astype(np.float32), t)
        # chord stabs on off-beats
        if bar >= 2 and not (bar == 3):
            for bi in range(4):
                t = bar * BAR + (bi + 0.5) * BEAT
                dur = 0.16
                tt = np.arange(int(dur * SR)) / SR
                sig = np.zeros_like(tt)
                for j, m in enumerate(chords[cb]):
                    f = hz(m)
                    for det in (-0.08, 0.0, 0.08):
                        sig += np.sign(np.sin(2 * np.pi * (f * 2 ** (det / 12)) * tt)) * 0.18
                env = np.minimum(1, tt / 0.005) * np.exp(-tt * 18)
                place(music, bandpass((sig * env).astype(np.float32), 180, 4500) * 0.30, t)

    # outro low-pass sweep on the whole music bus
    outro_start = 15 * BAR
    a = int(outro_start * SR)
    tt = np.arange(len(music) - a) / SR
    # crossfade to a heavily low-passed version
    lp = lowpass(music[a:], 1200)
    mixv = np.ones(len(tt), dtype=np.float32)
    sweep = np.clip(tt / (BAR * 0.9), 0, 1)
    music[a:] = music[a:] * (1 - sweep) + lp * sweep
    music[a:] *= np.clip(1.0 - tt / (BAR * 1.05), 0, 1)

    return out + music, out, music


# ---------------------------------------------------------------- mix
def reverb_ir(dur=0.8, decay=6.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ir = np.random.default_rng(21).normal(0, 1, n).astype(np.float32) * np.exp(-t * decay)
    ir = lowpass(ir, 6000)
    return ir / (np.abs(ir).sum() + 1e-9)


def master(vocal, backing):
    # vocal processing: high-pass, compress, presence, double, reverb
    v = highpass(vocal, 120, 2)
    # simple compressor
    thr = 0.08
    ratio = 4.0
    env = env_follow(v, 0.005, 0.06)
    gain = np.ones_like(v)
    over = env > thr
    gain[over] = (thr + (env[over] - thr) / ratio) / (env[over] + 1e-9)
    v = v * gain
    # presence
    v = v + bandpass(v, 2500, 5000) * 0.35
    # double (1/16 delay)
    d = int(SIX * SR)
    vd = np.zeros_like(v)
    vd[d:] = v[:-d] * 0.25
    # reverb
    ir = reverb_ir()
    rv = fftconvolve(v, ir)[:len(v)].astype(np.float32) * 0.12
    vocal_bus = v + vd + rv
    # sidechain backing
    e = env_follow(vocal_bus, 0.01, 0.18)
    e = e / (e.max() + 1e-9)
    duck = 1.0 - 0.34 * np.clip(e * 3, 0, 1)
    mix = backing * duck * 0.66 + vocal_bus * 1.75
    print('stem rms: vocal_bus %.1f dB  backing %.1f dB' % (
        20*np.log10(np.sqrt((vocal_bus**2).mean())+1e-9),
        20*np.log10(np.sqrt((backing**2).mean())+1e-9)))
    # gentle saturation to raise RMS like the reference master
    mix = np.tanh(mix * 1.6) / np.tanh(1.6)
    # gentle bus compression
    env2 = env_follow(mix, 0.01, 0.12)
    thr2 = 0.25
    over2 = env2 > thr2
    g2 = np.ones_like(mix)
    g2[over2] = (thr2 + (env2[over2] - thr2) / 2.0) / (env2[over2] + 1e-9)
    mix = mix * g2
    # limiter
    peak = np.abs(mix).max()
    if peak > 0:
        mix = mix / peak * 0.92
    # fade tail
    nf = int(0.35 * SR)
    mix[-nf:] *= np.linspace(1, 0, nf) ** 2
    return mix.astype(np.float32), vocal_bus


def main():
    check = '--check' in sys.argv
    lib, lines = build_library()
    vocal, events = build_vocal(lib)
    backing, drums, music = synth_backing()
    n = len(vocal)
    tt = np.arange(n) / SR
    bars = tt / BAR
    # --- arrangement automation: soft intro, thin pre-drop, hard drop, fade-out ---
    vgain = np.ones(n, dtype=np.float32)
    vgain[bars < 2] = 0.70
    vgain[(bars >= 2) & (bars < 4)] = 0.85
    vgain[bars >= 15] = np.clip(1 - (bars[bars >= 15] - 15) * 1.1, 0, 1)
    vocal = vocal * vgain
    bgain = np.ones(n, dtype=np.float32)
    bgain[bars < 1] = 0.45
    bgain[(bars >= 1) & (bars < 2)] = 0.60
    bgain[(bars >= 2) & (bars < 4)] = 0.78
    bgain[bars >= 15] = np.clip(1 - (bars[bars >= 15] - 15) * 1.3, 0, 1)
    backing = backing * bgain
    # thin the low end before the drop so the drop lands harder
    thin = highpass(backing, 130)
    w = np.clip(bars / 4.0, 0, 1) ** 1.5  # 0 at start -> 1 at bar 4
    backing = backing * (1 - w) + thin * w
    # hard silence on the last beat of bar 3
    sil_a = int((4 * BAR - BEAT) * SR)
    sil_b = int(4 * BAR * SR)
    backing[sil_a:sil_b] *= np.linspace(1, 0, sil_b - sil_a) ** 3
    vocal[sil_a:sil_b] *= np.linspace(1, 0, sil_b - sil_a) ** 3
    # final 0.22 s of bar 3: true silence (the "suck" before the drop)
    z0 = int((4 * BAR - 0.22) * SR)
    z1 = int(4 * BAR * SR)
    backing[z0:z1] = 0
    vocal[z0:z1] = 0
    mix, vbus = master(vocal, backing)
    print('vocal events', len(events), 'duration', len(mix) / SR)
    if check:
        return
    # write stems
    os.makedirs(ROOT + '/assets', exist_ok=True)
    wf.write(ROOT + '/assets/vocals.wav', SR, (np.clip(vocal, -1, 1) * 32767).astype(np.int16))
    wf.write(ROOT + '/assets/backing.wav', SR, (np.clip(backing * 0.8, -1, 1) * 32767).astype(np.int16))
    # stereo master: vocal center, backing slightly wide
    n = len(mix)
    stereo = np.zeros((n, 2), dtype=np.float32)
    stereo[:, 0] = mix
    stereo[:, 1] = mix
    # widen backing a touch by delaying right
    d = int(0.006 * SR)
    stereo[d:, 1] += backing[d:] * 0.08
    peak = np.abs(stereo).max()
    stereo = stereo / (peak + 1e-9) * 0.95
    wf.write(ROOT + '/assets/mix.wav', SR, (stereo * 32767).astype(np.int16))
    json.dump({'bpm': BPM, 'bars': TOTAL_BARS, 'dur': DUR, 'events': events},
              open(ROOT + '/assets/vocal_events.json', 'w'), ensure_ascii=False, indent=1)
    print('wrote assets/mix.wav', round(len(mix) / SR, 2), 's')


if __name__ == '__main__':
    main()
