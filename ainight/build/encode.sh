#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

AUDIO="assets/audio/yixiao_14s.wav"
OUT="out"
mkdir -p "$OUT"

ffmpeg -y -framerate 30 -i "frames/f_%05d.jpg" -i "$AUDIO" \
  -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest -movflags +faststart \
  "$OUT/ainight_15s_1080p.mp4"

ffmpeg -y -i "$OUT/ainight_15s_1080p.mp4" \
  -vf "scale=960:-2" -c:v libx264 -preset slow -crf 24 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -movflags +faststart \
  "$OUT/ainight_15s_540p.mp4"

ls -lh "$OUT"
