#!/usr/bin/env python3
"""Build the beat-cut motion shots for the 拾芥-style cover (22.75s, 133 BPM).

13 shots on a 1.8s grid (last 1.15s), hard cuts, no transitions.
Reuses plate() from make_motion.py so the grade matches the earlier film.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_motion import FPS, MOTION, W, H, plate  # noqa: E402

import subprocess  # noqa: E402

SRC = ["01_mist_valley", "02_snow_mountain", "03_coastal_road", "04_black_sand",
       "05_plateau", "06_night_train", "07_desert_stars", "08_rain_city",
       "09_cloud_sea", "10_old_town"]

# name, source, dur, cx, cy, z0, z1, pan_x, pan_y
SHOTS = [
    ("sj01", 0, 1.80, 0.50, 0.46, 1.14, 1.02, 0.00, 0.000),
    ("sj02", 1, 1.80, 0.48, 0.50, 1.02, 1.16, 0.030, 0.000),
    ("sj03", 2, 1.80, 0.52, 0.52, 1.10, 1.00, -0.030, 0.000),
    ("sj04", 3, 1.80, 0.50, 0.44, 1.00, 1.13, 0.000, 0.030),
    ("sj05", 4, 1.80, 0.47, 0.48, 1.15, 1.03, 0.025, 0.000),
    ("sj06", 5, 1.80, 0.53, 0.50, 1.03, 1.15, -0.025, 0.000),
    ("sj07", 6, 1.80, 0.50, 0.52, 1.12, 1.00, 0.000, -0.025),
    ("sj08", 7, 1.80, 0.49, 0.47, 1.00, 1.14, 0.028, 0.000),
    ("sj09", 8, 1.80, 0.51, 0.50, 1.14, 1.02, -0.028, 0.000),
    ("sj10", 9, 1.80, 0.48, 0.46, 1.02, 1.16, 0.000, 0.026),
    ("sj11", 0, 1.80, 0.52, 0.52, 1.13, 1.01, -0.020, 0.000),
    ("sj12", 5, 1.80, 0.50, 0.48, 1.01, 1.15, 0.022, 0.000),
    ("sj13", 7, 1.15, 0.50, 0.50, 1.10, 1.00, 0.000, 0.000),
]


def shot(name, src_i, dur, cx, cy, z0, z1, pan_x, pan_y, last):
    p = plate(SRC[src_i])
    out = MOTION / f"{name}.mp4"
    n = max(2, int(round(dur * FPS)))
    zoom = f"{z0}+({z1}-{z0})*on/{n - 1}"
    x = f"max(0,min(iw-iw/zoom,{cx}*iw-(iw/zoom)/2+{pan_x}*iw*on/{n - 1}))"
    y = f"max(0,min(ih-ih/zoom,{cy}*ih-(ih/zoom)/2+{pan_y}*ih*on/{n - 1}))"
    vf = (
        f"scale={W * 2}:{H * 2}:flags=lanczos,"
        f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={W}x{H}:fps={FPS},"
        "eq=contrast=1.07:saturation=0.90:gamma=1.01,"
        "colorbalance=rs=-0.022:gs=0.004:bs=0.034:rh=0.032:gh=0.0:bh=-0.026,"
        "unsharp=5:5:0.35:5:5:0.0,"
        "vignette=angle=PI/4.4,"
        "noise=alls=2:allf=t,"
        "format=yuv420p"
    )
    if last:
        vf += f",fade=t=out:st={max(0.0, dur - 0.7):.3f}:d=0.7"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-loop", "1", "-framerate", str(FPS), "-t", f"{dur}",
           "-i", str(p), "-vf", vf, "-frames:v", str(n),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
           "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-movflags", "+faststart", "-an", str(out)]
    subprocess.run(cmd, check=True)
    return out


if __name__ == "__main__":
    for i, s in enumerate(SHOTS):
        shot(*s, last=(i == len(SHOTS) - 1))
        print(f"[{i + 1:02d}/{len(SHOTS)}] {s[0]} {s[2]:.2f}s")
