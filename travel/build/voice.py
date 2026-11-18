#!/usr/bin/env python3
"""Generate the Chinese voice-over lines with Matcha-TTS and record their durations."""
import json
import os
import wave

import numpy as np
import sherpa_onnx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(ROOT, "assets", "models", "matcha-icefall-zh-baker")
VOCODER = os.path.join(ROOT, "assets", "models", "vocos-22khz-univ.onnx")
OUT = os.path.join(ROOT, "assets", "vo")
TEXT = os.path.join(ROOT, "config", "narration.txt")

LINES = [
    "走得越远，越知道自己走不完这个世界。",
    "后来我不再急着赶路。",
    "在陌生的山谷里，等一场雾散。",
    "在无人的海边，看浪把脚印抹平。",
    "旅行不是去更多的地方，",
    "而是让一个地方，真正经过你。",
    "世界很大，我们很小。",
    "但每一次出发，都是把自己重新交还给世界。",
    "所以走吧，哪怕只能走到下一次日落。",
    "剩下的路，交给风。",
]


def wav_duration(path):
    with wave.open(path, "rb") as f:
        return f.getnframes() / f.getframerate()


def build_tts():
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


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.dirname(TEXT), exist_ok=True)
    with open(TEXT, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")

    tts = build_tts()
    timing = []
    for i, line in enumerate(LINES, 1):
        path = os.path.join(OUT, f"line_{i:02d}.wav")
        audio = tts.generate(line, sid=0, speed=0.95)
        samples = np.clip(np.array(audio.samples, dtype=np.float32), -1.0, 1.0)
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(audio.sample_rate)
            f.writeframes((samples * 32767).astype("<i2").tobytes())
        dur = wav_duration(path)
        timing.append({"i": i, "text": line, "file": os.path.basename(path),
                       "duration": round(dur, 3)})
        print(f"{i:02d} {dur:5.2f}s  {line}")

    with open(os.path.join(OUT, "timing.json"), "w", encoding="utf-8") as f:
        json.dump(timing, f, ensure_ascii=False, indent=2)
    print("total", round(sum(t["duration"] for t in timing), 2), "s")


if __name__ == "__main__":
    main()
