#!/bin/bash
set -e
cd "$(dirname "$0")/.."
mkdir -p out

ffmpeg -y -framerate 30 -start_number 0 -i frames/f_%04d.jpg -i assets/audio/mix.wav \
  -c:v libx264 -preset slow -crf 21 -pix_fmt yuv420p \
  -profile:v high -level 4.2 \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -c:a aac -b:a 192k -ar 48000 \
  -shortest -movflags +faststart \
  out/travel_world_is_too_big_1080x1920.mp4

ffmpeg -y -i out/travel_world_is_too_big_1080x1920.mp4 \
  -vf scale=540:960 -c:v libx264 -preset medium -crf 24 \
  -c:a aac -b:a 128k -movflags +faststart \
  out/travel_world_is_too_big_540p.mp4

echo "done: out/travel_world_is_too_big_1080x1920.mp4"
