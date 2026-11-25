#!/usr/bin/env bash
# encode.sh — 编码成片 + 封面 + 联系表 + 验收
#   用法: ./encode.sh [mix.wav]
set -euo pipefail

ROOT="/workspace/nana"
BUILD="$ROOT/build"
FRAMES="$ROOT/frames"
OUT="$ROOT/out"
MIX="${1:-$ROOT/assets/audio/mix.wav}"
MP4="$OUT/nana_cn_35s.mp4"

echo "== 检查素材"
[ -f "$MIX" ] || { echo "缺少混音文件: $MIX （先跑 build/mix_audio.py）"; exit 1; }
NF=$(ls "$FRAMES"/f_*.jpg 2>/dev/null | wc -l)
[ "$NF" -eq 1050 ] || { echo "帧数 $NF != 1050（先跑 render.py --all）"; exit 1; }
echo "frames=$NF  mix=$MIX"

echo "== 编码"
ffmpeg -y -hide_banner -loglevel warning \
  -framerate 30 -start_number 0 -i "$FRAMES/f_%05d.jpg" \
  -i "$MIX" \
  -map 0:v:0 -map 1:a:0 \
  -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -profile:v high -level 4.1 \
  -r 30 -s 1080x1920 \
  -color_primaries bt709 -color_trc bt709 -colorspace bt709 \
  -c:a aac -b:a 192k -ar 48000 -ac 2 \
  -movflags +faststart \
  -t 35.0 \
  "$MP4"

echo "== 封面 / 联系表"
python3 "$BUILD/render.py" --cover --contact

echo "== 验收"
ffprobe -v error -show_entries stream=index,codec_name,width,height,r_frame_rate,avg_frame_rate,sample_rate,channels\
,duration -show_entries format=duration,size,format_name -of default=nw=1 "$MP4"

echo "== 响度"
ffmpeg -hide_banner -nostats -i "$MP4" -af ebur128=peak=true -f null - 2>&1 \
  | grep -E "I:|Peak:|LRA:" | tail -4

echo "OK -> $MP4"
