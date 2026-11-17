#!/usr/bin/env python3
"""Build project.json for the 24 s / 120 BPM guichu-beat demo."""
import json
import os

ROOT = "/workspace/demo/guichu-beat"

# (start, duration, sourceStart, scale)
SHOTS = [
    (0.0, 1.0, 180.2, 1.00),
    (1.0, 1.0, 203.5, 1.12),
    (2.0, 2.0, 187.0, 1.00),
    (4.0, 2.0, 199.0, 1.00),
    (6.0, 1.0, 181.2, 1.12),
    (7.0, 1.0, 206.0, 1.05),
    (8.0, 1.0, 213.0, 1.00),
    (9.0, 1.0, 217.0, 1.12),
    (10.0, 2.0, 219.0, 1.00),
    (12.0, 2.0, 222.0, 1.20),
    (14.0, 1.0, 223.2, 1.00),
    (15.0, 1.0, 227.0, 1.12),
    (16.0, 2.0, 232.0, 1.00),
    (18.0, 1.0, 211.0, 1.00),
    (19.0, 1.0, 236.0, 1.05),
    (20.0, 2.0, 220.0, 1.20),
    (22.0, 1.0, 181.0, 1.25),
    (23.0, 1.0, 182.1, 1.00),
]
W, H = 960, 720

assets = [
    {"id": "zuotian", "kind": "video", "path": "../../.tmp-guichu/zuotian.mp4"},
    {"id": "beat", "kind": "audio", "path": "assets/beat.wav"},
    {"id": "vocals", "kind": "audio", "path": "assets/vocals-comp.wav"},
]
for i in range(1, 7):
    assets.append({"id": f"sub{i}", "kind": "image", "path": f"assets/sub{i}.png"})

shot_clips = []
for i, (start, dur, src, scale) in enumerate(SHOTS, 1):
    clip = {
        "id": f"shot{i:02d}",
        "type": "video",
        "assetId": "zuotian",
        "start": start,
        "duration": dur,
        "sourceStart": src,
        "volume": 0,
        "scale": scale,
    }
    if scale > 1.0:
        clip["position"] = {
            "x": round(-(W * scale - W) / 2),
            "y": round(-(H * scale - H) / 2),
        }
    shot_clips.append(clip)

NUM = ["一", "二", "三", "四", "五", "六"]
sub_clips = [
    {
        "id": f"sub{i}",
        "type": "image",
        "assetId": f"sub{i}",
        "start": (i - 1) * 4.0,
        "duration": 4.0,
        "position": {"x": 0, "y": 0},
    }
    for i in range(1, 7)
]

project = {
    "schemaVersion": 1,
    "revision": 1,
    "name": "鬼畜节奏实验 - 120BPM",
    "assets": assets,
    "tracks": [
        {"id": "v1", "kind": "video", "name": "分镜", "clips": shot_clips},
        {"id": "v2", "kind": "video", "name": "字幕", "clips": sub_clips},
        {"id": "a1", "kind": "audio", "name": "伴奏", "clips": [
            {"id": "beat", "type": "audio", "assetId": "beat", "start": 0,
             "duration": 24, "sourceStart": 0, "volume": 0.58, "fadeOut": 0.2},
        ]},
        {"id": "a2", "kind": "audio", "name": "人声", "clips": [
            {"id": "vocals", "type": "audio", "assetId": "vocals", "start": 0,
             "duration": 24, "sourceStart": 0, "volume": 0.92},
        ]},
        {"id": "a3", "kind": "audio", "name": "人声双击", "clips": [
            {"id": "vocals-double", "type": "audio", "assetId": "vocals", "start": 0.125,
             "duration": 23.875, "sourceStart": 0, "volume": 0.30, "fadeOut": 0.2},
        ]},
    ],
    "output": {
        "path": "guichu-beat.mp4",
        "format": "mp4",
        "videoCodec": "h264",
        "audioCodec": "aac",
        "width": W,
        "height": H,
        "frameRate": 30,
        "pixelFormat": "yuv420p",
        "audioSampleRate": 48000,
        "audioChannels": 2,
    },
}

with open(os.path.join(ROOT, "project.json"), "w") as f:
    json.dump(project, f, ensure_ascii=False, indent=2)
print("shots", len(SHOTS), "cuts", len(SHOTS) - 1)
