#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

FRAMES=frames/f_%04d.jpg
AUDIO=assets/audio/yixiao_91s.wav
OUT=out/jianghu_baiyujing_1080p.mp4
PREVIEW=out/jianghu_baiyujing_540p.mp4

ffmpeg -y -framerate 30 -i "$FRAMES" -i "$AUDIO" \
  -c:v libx264 -preset medium -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest -movflags +faststart \
  -metadata title="一笑江湖 · 天上白玉京" \
  -metadata artist="闻人听書_" \
  "$OUT"

ffmpeg -y -i "$OUT" -vf "scale=960:540" -c:v libx264 -preset fast -crf 24 \
  -c:a aac -b:a 128k -movflags +faststart "$PREVIEW"

ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUT"
ls -lh "$OUT" "$PREVIEW"
