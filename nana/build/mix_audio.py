#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mix_audio.py — 《同一个 nana，两种命》35s 混音

  BGM（35s，128BPM 已定稿）+ 6 句旁白（按 voice/meta.json） + SFX
  旁白期间 BGM 侧链 -7 dB（80–100ms 过渡）
  混音峰值 -1 dBFS → ffmpeg loudnorm 两遍 → -14 LUFS / TP -1
  输出: nana/assets/audio/mix.wav  (48k 立体声 PCM，供 encode.sh 使用)
"""
import json
import os
import subprocess
import sys
import wave

import numpy as np

ROOT = "/workspace/nana"
AUD = os.path.join(ROOT, "assets", "audio")
WORK = "/tmp/nana_build"
SR = 48000
DUR = 35.0
N = int(round(SR * DUR))

RAW = os.path.join(WORK, "mix_raw.wav")
MIX = os.path.join(AUD, "mix.wav")
PLACEHOLDER = os.path.join(WORK, "bgm_placeholder.wav")


# ----------------------------------------------------------------------------- io
def load_wav(path):
    with wave.open(path, "rb") as w:
        sr, ch, sw, n = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v >= (1 << 23), v - (1 << 24), v)
        a = v.astype(np.float32) / 8388608.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise SystemExit("unsupported sample width %d in %s" % (sw, path))
    a = a.reshape(-1, ch)
    if sr != SR:
        raise SystemExit("expect 48k, got %d in %s" % (sr, path))
    return a


def save_wav(path, a, sw=2):
    a = np.clip(a, -1.0, 1.0)
    if sw == 2:
        d = (a * 32767.0).astype("<i2")
    else:
        d = (a * 8388607.0).astype("<i4")
    with wave.open(path, "wb") as w:
        w.setnchannels(a.shape[1])
        w.setsampwidth(sw)
        w.setframerate(SR)
        w.writeframes(d.tobytes())


def stereo(a):
    if a.ndim == 1:
        a = a[:, None]
    if a.shape[1] == 1:
        a = np.repeat(a, 2, axis=1)
    return a


def fit(a, n=N):
    """裁/补到 n 帧"""
    if len(a) >= n:
        return a[:n].copy()
    out = np.zeros((n, a.shape[1]), np.float32)
    out[: len(a)] = a
    return out


def db(x):
    return 10.0 ** (x / 20.0)


def place(buf, clip, t, gain_db, loop=False, end=None):
    g = db(gain_db)
    i0 = int(round(t * SR))
    n_end = N if end is None else min(N, int(round(end * SR)))
    if i0 >= n_end:
        return
    c = clip
    if loop:
        reps = int(np.ceil(N / len(c))) + 1
        c = np.tile(c, (reps, 1))
    if i0 < 0:
        c = c[-i0:]
        i0 = 0
    seg = c[: n_end - i0]
    buf[i0:i0 + len(seg)] += seg * g


def make_placeholder_bgm():
    """128 BPM 占位节拍（仅在 bgm.wav 缺失时使用）"""
    beat = 60.0 / 128.0
    n = int(beat * SR)
    tt = np.arange(n) / SR
    click = np.sin(2 * np.pi * 880 * tt) * np.exp(-tt * 55) * 0.5
    kick = np.sin(2 * np.pi * 58 * tt) * np.exp(-tt * 11) * 0.9
    bar = np.zeros((int(4 * beat * SR), 2), np.float32)
    for k in range(4):
        s = int(k * beat * SR)
        clip = (kick if k % 2 == 0 else click)[: int(beat * SR)]
        bar[s:s + len(clip)] += clip[:, None]
    reps = int(np.ceil(DUR / (4 * beat))) + 1
    out = np.tile(bar, (reps, 1))[:N]
    return out.astype(np.float32)


# ----------------------------------------------------------------------------- main
def main():
    os.makedirs(WORK, exist_ok=True)
    with open(os.path.join(ROOT, "config", "script.json"), encoding="utf-8") as f:
        script = json.load(f)
    with open(os.path.join(AUD, "voice", "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)

    # ---- BGM
    bgm_path = os.path.join(AUD, "bgm.wav")
    if os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 100000:
        bgm = stereo(load_wav(bgm_path))
        src_tag = "BGM assets/audio/bgm.wav (%s)" % __import__("time").strftime(
            "%H:%M:%S", __import__("time").localtime(os.path.getmtime(bgm_path)))
        used_placeholder = False
    else:
        bgm = stereo(make_placeholder_bgm())
        save_wav(PLACEHOLDER, bgm)
        src_tag = "占位 128BPM 节拍器 (bgm.wav 缺失)"
        used_placeholder = True
    bgm = fit(bgm)
    print("[mix]", src_tag)

    # ---- 旁白
    voice = np.zeros((N, 2), np.float32)
    for line in meta:
        p = line["file"]
        if not os.path.isabs(p):
            p = os.path.join("/workspace", p.lstrip("./"))
        v = stereo(load_wav(p))
        place(voice, v, line["start"], 0.0)
        print("[voice] %s @ %.2fs  %.2fs  %s" % (line["id"], line["start"], line["duration"], line["text"]))

    # ---- BGM 侧链包络：旁白期间 -7 dB，90ms 过渡
    duck = np.zeros(N, np.float32)
    for line in meta:
        s = int(round(line["start"] * SR))
        e = int(round(line["end"] * SR))
        duck[max(0, s):min(N, e)] = 1.0
    k = int(0.090 * SR)
    cs = np.cumsum(np.concatenate([np.zeros(1, np.float64), duck.astype(np.float64)]))
    env = ((cs[k:] - cs[:-k]) / k).astype(np.float32)
    env = np.concatenate([np.zeros(N - len(env), np.float32), env])[:N]
    bgm_gain = db(-7.0) * (1.0 - (1.0 - db(-7.0)) * env)   # -7dB 基础 + 再 -7dB 撕开
    bgm_track = bgm * bgm_gain[:, None]

    mix = bgm_track + voice

    # ---- SFX
    S = os.path.join(AUD, "sfx")
    kb = stereo(load_wav(os.path.join(S, "keyboard.wav")))
    place(mix, kb, 0.0, -20.0, loop=True)
    whoosh = stereo(load_wav(os.path.join(S, "whoosh.wav")))
    for t in (3.55, 16.70, 20.60, 24.30, 28.00, 31.70):
        place(mix, whoosh, t, -12.0)
    impact = stereo(load_wav(os.path.join(S, "impact.wav")))
    for t in (3.75, 16.875, 28.125):
        place(mix, impact, t, -6.0)
    hb = stereo(load_wav(os.path.join(S, "heartbeat.wav")))
    place(mix, hb, 15.10, -10.0)
    ls = stereo(load_wav(os.path.join(S, "light_switch.wav")))
    for t in (24.42, 25.35, 29.55):
        place(mix, ls, t, -12.0)
    sl = stereo(load_wav(os.path.join(S, "slipper.wav")))
    for t in (20.90, 27.10):
        place(mix, sl, t, -10.0)
    tv = stereo(load_wav(os.path.join(S, "tv_static.wav")))
    place(mix, tv, 28.20, -24.0, loop=True, end=32.0)
    print("[sfx] keyboard/whoosh x6/impact x3/heartbeat/light_switch x3/slipper x2/tv_static 28.2-32.0")

    # ---- 峰值 -1 dBFS
    pk = float(np.max(np.abs(mix)))
    if pk > 0:
        mix *= db(-1.0) / pk
    print("[mix] pre-loudnorm peak %.2f dBFS" % (20 * np.log10(max(pk, 1e-9))))

    save_wav(RAW, mix, sw=2)

    # ---- loudnorm 两遍
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", RAW, "-af",
         "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    txt = p.stderr
    j = json.loads(txt[txt.rindex("{"): txt.rindex("}") + 1])
    args = ("loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=%s:measured_TP=%s:measured_LRA=%s:"
            "measured_thresh=%s:offset=%s:linear=true:print_format=summary"
            % (j["input_i"], j["input_tp"], j["input_lra"], j["input_thresh"], j["target_offset"]))
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", RAW,
         "-af", args, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", MIX],
        check=True)
    print("[mix] loudnorm pass1 in_i=%s in_tp=%s" % (j["input_i"], j["input_tp"]))
    print("[mix] ->", MIX)
    if used_placeholder:
        print("[mix] 注意: 本次使用 BGM 占位节拍，拿到正式 bgm.wav 后请重跑本脚本")


if __name__ == "__main__":
    main()
