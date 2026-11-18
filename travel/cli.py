#!/usr/bin/env python3
"""剪辑 CLI — 世界走不完（1080x1920 / 52 s）

用法：
  python3 cli.py voice            生成旁白（Piper）
  python3 cli.py audio            合成 BGM 并混音
  python3 cli.py sample           渲染抽查帧
  python3 cli.py render           全量渲染
  python3 cli.py encode           编码成片
  python3 cli.py all              从旁白到成片全流程

素材（13 张竖屏图）放在 assets/ai/，命名与 config/timeline.json 对应。
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(cmd):
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main():
    ap = argparse.ArgumentParser(description="travel cut CLI")
    ap.add_argument("cmd", choices=["voice", "audio", "sample", "render", "encode", "all"])
    ap.add_argument("--times", type=float, nargs="*")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    if args.cmd == "voice":
        run([PY, "build/voice.py"])
    elif args.cmd == "audio":
        run([PY, "build/audio.py"])
    elif args.cmd == "sample":
        cmd = [PY, "build/render.py", "--mode", "sample"]
        if args.times:
            cmd += ["--times"] + [str(t) for t in args.times]
        run(cmd)
    elif args.cmd == "render":
        run([PY, "build/render.py", "--mode", "all", "--workers", str(args.workers)])
    elif args.cmd == "encode":
        run(["bash", "build/encode.sh"])
    else:
        run([PY, "build/voice.py"])
        run([PY, "build/audio.py"])
        run([PY, "build/render.py", "--mode", "all", "--workers", str(args.workers)])
        run(["bash", "build/encode.sh"])


if __name__ == "__main__":
    main()
