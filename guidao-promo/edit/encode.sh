#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

FRAMES="out/frames"
if [ ! -f "$FRAMES/f_02399.jpg" ]; then
  echo "frames missing: render first with python3 edit/render.py" >&2
  exit 1
fi

ffmpeg -y -hide_banner -loglevel error \
  -framerate 30 -i "$FRAMES/f_%05d.jpg" \
  -i audio/mix.wav \
  -c:v libx264 -preset slow -crf 19 -pix_fmt yuv420p -profile:v high -level 4.1 \
  -c:a aac -b:a 192k -ar 48000 -ac 2 \
  -shortest -movflags +faststart \
  out/guidao_promo_1080p.mp4

ffmpeg -y -hide_banner -loglevel error \
  -ss 73.5 -i out/guidao_promo_1080p.mp4 -frames:v 1 -q:v 2 out/poster.jpg

ffmpeg -y -hide_banner -loglevel error \
  -i out/guidao_promo_1080p.mp4 \
  -vf "fps=1/5,scale=480:-1,tile=4x4" -frames:v 1 out/contact_sheet.jpg

ls -lh out/guidao_promo_1080p.mp4 out/poster.jpg out/contact_sheet.jpg
