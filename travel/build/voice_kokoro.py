#!/usr/bin/env python3
"""Render narration with Kokoro (sherpa-onnx) into the project vo folder.

    python3 build/voice_kokoro.py --project projects/xiancheng --sid 48

Chinese speaker ids in kokoro v1.0: 46 zf_xiaobei, 47 zf_xiaoni,
48 zf_xiaoxiao, 49 zf_xiaoyi, 50 zm_yunjian, 51 zm_yunxi, 52 zm_yunxia.
"""
import argparse
import os
import wave

import numpy as np
import sherpa_onnx
from scipy.signal import resample_poly

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "assets", "models", "kokoro-multi-lang-v1_0")
SR = 48000


def build_tts():
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                model=os.path.join(D, "model.onnx"),
                voices=os.path.join(D, "voices.bin"),
                tokens=os.path.join(D, "tokens.txt"),
                data_dir=os.path.join(D, "espeak-ng-data"),
                dict_dir=os.path.join(D, "dict"),
                lexicon=os.path.join(D, "lexicon-zh.txt"),
                lang="zh",
            ),
            num_threads=2,
            provider="cpu",
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="projects/xiancheng")
    ap.add_argument("--sid", type=int, default=48)
    ap.add_argument("--speed", type=float, default=0.94)
    args = ap.parse_args()

    proj = os.path.join(ROOT, args.project)
    out = os.path.join(proj, "audio", "vo")
    os.makedirs(out, exist_ok=True)
    lines = [l.strip() for l in open(os.path.join(proj, "narration.txt"),
                                     encoding="utf-8") if l.strip()]

    tts = build_tts()
    total = 0.0
    for i, line in enumerate(lines, 1):
        a = tts.generate(line, sid=args.sid, speed=args.speed)
        y = np.clip(np.array(a.samples, np.float32), -1, 1)
        path = os.path.join(out, f"line_{i:02d}.wav")
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(a.sample_rate)
            f.writeframes((y * 32767).astype("<i2").tobytes())
        y48 = resample_poly(y.astype(np.float64), SR, a.sample_rate)
        idx = np.where(np.abs(y48) > 0.008)[0]
        d = (idx[-1] - idx[0]) / SR if len(idx) else 0.0
        total += d
        print(f"  {i:02d} {d:5.2f}s  {line}")
    print(f"sid {args.sid}  speech {total:.2f}s  -> {out}")


if __name__ == "__main__":
    main()
