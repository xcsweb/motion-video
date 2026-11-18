#!/usr/bin/env python3
"""Generate the Chinese voice-over lines with Piper and record their durations."""
import json
import os
import subprocess
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "assets", "tts", "zh_CN-huayan-medium.onnx")
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


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.dirname(TEXT), exist_ok=True)
    with open(TEXT, "w", encoding="utf-8") as f:
        f.write("\n".join(LINES) + "\n")

    timing = []
    for i, line in enumerate(LINES, 1):
        path = os.path.join(OUT, f"line_{i:02d}.wav")
        subprocess.run(
            ["python3", "-m", "piper", "--model", MODEL,
             "--length-scale", "1.12", "--sentence-silence", "0.18",
             "--output_file", path],
            input=line.encode("utf-8"), check=True,
        )
        dur = wav_duration(path)
        timing.append({"i": i, "text": line, "file": os.path.basename(path),
                       "duration": round(dur, 3)})
        print(f"{i:02d} {dur:5.2f}s  {line}")

    with open(os.path.join(OUT, "timing.json"), "w", encoding="utf-8") as f:
        json.dump(timing, f, ensure_ascii=False, indent=2)
    print("total", round(sum(t["duration"] for t in timing), 2), "s")


if __name__ == "__main__":
    main()
