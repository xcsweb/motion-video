#!/usr/bin/env bash
set -euo pipefail
OUT=/workspace/rail-promo/build
SRC=/workspace/rail-audio/FG9kbdcUioYMf3xuDr3cBQjLn5b.mp4
FR=/workspace/rail-promo/out/frames
MAP=/workspace/rail-promo/out/map
DIAL=/workspace/rail-promo/out/dial
GFX=/workspace/rail-promo/out/gfx
mkdir -p "$OUT"

GRADE="eq=contrast=1.10:brightness=0.015:saturation=1.16:gamma=0.97,colorbalance=rs=-0.04:gs=0.01:bs=0.09:rh=0.07:gh=0.015:bh=-0.05,curves=all='0/0 0.22/0.20 0.80/0.84 1/1',vignette=a=PI/5,noise=alls=6:allf=t+u"
ENC="-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p -r 30 -an"

# 01 tunnel POV (3D, 1280x720 -> crop 510 centered)
ffmpeg -y -v error -framerate 30 -i "$FR/01_tunnel/f_%04d.jpg" \
  -vf "crop=1280:510:0:105,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s01.mp4"

# 02 real: elevated light rail 5.5-7.0 @0.5x
ffmpeg -y -v error -ss 5.5 -t 1.5 -i "$SRC" \
  -vf "setpts=2.0*PTS,fps=30,crop=1280:510:0:0,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s02.mp4"

# 03 map reveal
ffmpeg -y -v error -framerate 30 -i "$MAP/reveal/f_%04d.jpg" \
  -vf "pad=1920:1080:0:157:black" $ENC "$OUT/s03.mp4"

# 04 real: station + train 13.2-14.05 @0.5x
ffmpeg -y -v error -ss 13.2 -t 0.85 -i "$SRC" \
  -vf "setpts=2.0*PTS,fps=30,crop=1280:510:0:0,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s04.mp4"

# 05 real: city dusk from window 15.0-16.05 @0.5x
ffmpeg -y -v error -ss 15.0 -t 1.05 -i "$SRC" \
  -vf "setpts=2.0*PTS,fps=30,crop=1280:510:0:0,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s05.mp4"

# 05b platform insert (3D station detail, 1920x1080 -> crop 765 from y=90)
ffmpeg -y -v error -framerate 30 -i "$FR/05b_platform/f_%04d.jpg" \
  -vf "crop=1920:765:0:90,eq=contrast=1.08:brightness=0.012:saturation=1.10:gamma=1.02,colorbalance=rs=-0.02:gs=0.0:bs=0.05,vignette=a=PI/5,noise=alls=5:allf=t+u,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s05b.mp4"

# 06 dial graphic (1280x720 -> fit 765 high, navy side bars)
ffmpeg -y -v error -framerate 30 -i "$DIAL/f_%04d.jpg" \
  -vf "scale=-2:766,pad=1920:766:(ow-iw)/2:0:0x05080D,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s06.mp4"

# 07 tunnel 2
ffmpeg -y -v error -framerate 30 -i "$FR/07_tunnel2/f_%04d.jpg" \
  -vf "crop=1280:510:0:105,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s07.mp4"

# 08 real: red bridge at night 7.8-9.233 @0.5x
ffmpeg -y -v error -ss 7.8 -t 1.433 -i "$SRC" \
  -vf "setpts=2.0*PTS,fps=30,crop=1280:510:0:0,scale=1920:765:flags=lanczos,$GRADE,pad=1920:1080:0:157:black" \
  $ENC "$OUT/s08.mp4"

# 09 map full
ffmpeg -y -v error -framerate 30 -i "$MAP/full/f_%04d.jpg" \
  -vf "pad=1920:1080:0:157:black" $ENC "$OUT/s09.mp4"

# 10 endcard still
ffmpeg -y -v error -loop 1 -framerate 30 -i "$GFX/endcard.png" -t 3.1 \
  -vf "trim=duration=3.1" $ENC "$OUT/s10.mp4"

for f in "$OUT"/s*.mp4; do
  printf "%-16s %s\n" "$(basename "$f")" "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f")"
done
