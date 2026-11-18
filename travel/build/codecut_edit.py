#!/usr/bin/env python3
"""把 config/timeline.json 映射成 codecut 的编辑操作（ops.json）。

codecut 的同一视频轨内 clip 是顺序拼接的，字幕/片头卡的多行文字
必须拆到不同轨道；这里用 3 组「文字层 + 阴影层」轨道来实现。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "edit"
CFG = json.loads((ROOT / "config/timeline.json").read_text())

SERIF = "fonts/NotoSerifCJK-Medium.ttc"
SANS = "fonts/NotoSansCJK-Light.ttc"
WHITE = "#F7F2E8"
MUTED = "#C9C3B6"
OPEN_END = 4.25  # 让第一条字幕 4.30 开始时片头卡已经结束


def text(layer: int, cid: str, start: float, end: float, value: str,
         size: float, color: str, y: float, font: str = SERIF,
         opacity: float = 1.0) -> dict:
    clip = {
        "id": cid, "type": "text", "text": value,
        "start": round(start, 3), "duration": round(end - start, 3),
        "fontFile": font, "fontSize": size, "color": color,
        "align": "center", "position": {"x": 0, "y": y},
    }
    if opacity < 1:
        clip["opacity"] = opacity
    return {"type": "addText", "trackId": f"t{layer}", "clip": clip}


def build() -> list[dict]:
    shots = CFG["shots"]
    ops: list[dict] = [{"type": "removeTrack", "trackId": "a2"}]
    for layer in (1, 2, 3):
        ops.append({"type": "addTrack", "track": {
            "id": f"t{layer}", "kind": "video", "name": f"Title {layer}", "clips": []}})

    # 主视频轨：13 个运动镜头，0.8s 交叉淡化
    for i, s in enumerate(shots):
        clip = {
            "id": f"shot{i + 1:02d}", "type": "video", "assetId": s["asset"],
            "start": round(s["t0"], 3), "duration": round(s["t1"] - s["t0"], 3),
        }
        if i > 0:
            overlap = round(shots[i - 1]["t1"] - s["t0"], 3)
            clip["transition"] = {"type": "xfade", "duration": overlap, "name": "fade"}
        ops.append({"type": "addClip", "trackId": "v1", "clip": clip})

    # 片头/片尾卡（3 层）
    o0 = CFG["cards"]["open"]["t0"]
    ops += [
        text(1, "open_eyebrow", o0, OPEN_END, "TRAVEL  NOTES  ·  2026", 20, MUTED, -249, SANS),
        text(2, "open_title", o0, OPEN_END, CFG["title"], 88, WHITE, -83),
        text(3, "open_en", o0, OPEN_END, CFG["english"], 18, MUTED, 17, SANS),
    ]
    # 片尾卡（3 层）
    c0, c1 = CFG["cards"]["close"]["t0"], CFG["cards"]["close"]["t1"]
    ops += [
        text(1, "close_title", c0, c1, CFG["title"], 82, WHITE, -58),
        text(2, "close_line2", c0, c1, "那就一直走。", 46, WHITE, 23),
        text(3, "close_line3", c0, c1, "写给还在路上的你", 22, MUTED, 103, SANS),
    ]

    # 字幕：每行一个 text clip，按行分到第 1/2 层
    for i, sub in enumerate(CFG["subtitles"]):
        lines = sub["lines"]
        offsets = [624] if len(lines) == 1 else [590, 660]
        for j, (line, off) in enumerate(zip(lines, offsets), start=1):
            ops.append(text(j, f"sub{i + 1:02d}_{j}", sub["t"], sub["end"],
                            line, 46, "#FFFFFF", off))

    # 音频：已混好的 BGM + 旁白
    ops.append({"type": "addClip", "trackId": "a1", "clip": {
        "id": "mix", "type": "audio", "assetId": "mix", "start": 0,
        "duration": CFG["duration"], "volume": 1.0,
        "fadeIn": 0.6, "fadeOut": 1.2,
    }})
    return ops


if __name__ == "__main__":
    ops = build()
    out = PROJECT / "ops.json"
    out.write_text(json.dumps(ops, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out} ({len(ops)} operations)")
