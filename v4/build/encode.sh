#!/bin/bash
set -e
cd "$(dirname "$0")/.."

ffmpeg -y -framerate 30 -i frames/f_%04d.jpg -i assets/audio/source.wav \
  -c:v libx264 -preset slow -crf 22 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -shortest -movflags +faststart \
  out_railgun_v4_rebuild.mp4

ffmpeg -y -i out_railgun_v4_rebuild.mp4 -vf scale=960:540 \
  -c:v libx264 -preset medium -crf 24 -c:a aac -b:a 128k \
  -movflags +faststart out_railgun_v4_rebuild_preview.mp4

echo "done: out_railgun_v4_rebuild.mp4"
