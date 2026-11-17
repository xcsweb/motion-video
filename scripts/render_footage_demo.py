#!/usr/bin/env python3
"""Render a short code-defined footage edit with FFmpeg and an original score."""
import argparse
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

FPS = 30
WIDTH = 1280
HEIGHT = 720
CLIP_DURATION = 2.9
TRANSITION_DURATION = 0.4
CREDIT_DURATION = 2.5
TOTAL_DURATION = 20.0

TIMELINE = [
    {"source": "sintel", "start": 3.5, "label": "01 / SNOW LINE", "transition": "fade"},
    {"source": "bbb", "start": 8.8, "label": "02 / BIG RABBIT", "transition": "wipeleft"},
    {"source": "sintel", "start": 12.7, "label": "03 / CLOSE UP", "transition": "dissolve"},
    {"source": "sintel", "start": 23.0, "label": "04 / DRAGON CITY", "transition": "circleopen"},
    {"source": "bbb", "start": 22.8, "label": "05 / BUTTERFLY", "transition": "fadeblack"},
    {"source": "sintel", "start": 26.7, "label": "06 / SWORD", "transition": "smoothleft"},
    {"source": "sintel", "start": 31.7, "label": "07 / FLIGHT", "transition": "fade"},
]


def font_path(name):
    return subprocess.check_output(
        ["fc-match", "-f", "%{file}", name], text=True
    ).strip()


def synthesize_score(path):
    """Create an original 120 BPM electronic cue; no downloaded music is used."""
    sample_rate = 48000
    count = int(TOTAL_DURATION * sample_rate)
    mix = np.zeros((count, 2), dtype=np.float64)
    rng = np.random.default_rng(20261117)
    chords = [
        (110.00, 130.81, 164.81),
        (87.31, 110.00, 130.81),
        (130.81, 164.81, 196.00),
        (98.00, 123.47, 146.83),
    ]

    def add(signal, start, gain=1.0, stereo=(1.0, 1.0)):
        offset = int(start * sample_rate)
        if offset >= count:
            return
        length = min(len(signal), count - offset)
        mix[offset:offset + length, 0] += signal[:length] * gain * stereo[0]
        mix[offset:offset + length, 1] += signal[:length] * gain * stereo[1]

    for bar_start in np.arange(0, TOTAL_DURATION, 2.0):
        chord = chords[int(bar_start / 2.0) % len(chords)]
        local = np.arange(int(2.0 * sample_rate)) / sample_rate
        envelope = np.minimum(local / 0.12, 1.0) * np.minimum((2.0 - local) / 0.25, 1.0)
        pad = sum(
            np.sin(2 * np.pi * frequency * local)
            + 0.22 * np.sin(2 * np.pi * frequency * 2 * local)
            for frequency in chord
        ) / 3.0
        add(pad * envelope, bar_start, 0.11, (0.9, 1.0))
        add(np.roll(pad, 360) * envelope, bar_start, 0.07, (0.75, 0.9))

    for step, start in enumerate(np.arange(0, TOTAL_DURATION, 0.25)):
        chord = chords[int(start / 2.0) % len(chords)]
        frequency = chord[step % 3] * 4
        local = np.arange(int(0.24 * sample_rate)) / sample_rate
        pluck = (
            np.sin(2 * np.pi * frequency * local)
            + 0.3 * np.sin(2 * np.pi * frequency * 2 * local)
        ) * np.exp(-local * 15)
        add(pluck, start, 0.075, (0.8, 1.0) if step % 2 else (1.0, 0.8))

    for beat, start in enumerate(np.arange(0, TOTAL_DURATION, 0.5)):
        local = np.arange(int(0.32 * sample_rate)) / sample_rate
        phase = 2 * np.pi * (48 * local + 65 * 0.035 * (1 - np.exp(-local / 0.035)))
        kick = np.sin(phase) * np.exp(-local * 15)
        add(kick, start, 0.38)
        root = chords[int(start / 2.0) % len(chords)][0]
        bass = np.sin(2 * np.pi * root * local) * np.exp(-local * 7)
        add(bass, start, 0.12)
        if beat % 2:
            noise = rng.normal(0, 1, len(local))
            snare = (noise - np.roll(noise, 1)) * np.exp(-local * 24)
            add(snare, start, 0.10, (0.95, 1.0))

    for start in np.arange(0, TOTAL_DURATION, 0.25):
        local = np.arange(int(0.055 * sample_rate)) / sample_rate
        noise = rng.normal(0, 1, len(local))
        hat = (noise - np.roll(noise, 1)) * np.exp(-local * 70)
        add(hat, start, 0.027, (0.85, 1.0))

    fade = np.ones(count)
    fade[:sample_rate // 2] = np.linspace(0, 1, sample_rate // 2)
    fade[-sample_rate:] = np.linspace(1, 0, sample_rate)
    mix *= fade[:, None]
    mix = np.tanh(mix * 1.25)
    mix *= 0.92 / max(1e-9, np.max(np.abs(mix)))
    pcm = (mix * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm.tobytes())


def escape_text(text):
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def render(args):
    cjk = font_path("Noto Sans CJK SC")
    mono = font_path("DejaVu Sans Mono")
    inputs = []
    filters = []
    for index, clip in enumerate(TIMELINE):
        inputs += [
            "-ss", str(clip["start"]),
            "-t", str(CLIP_DURATION),
            "-i", str(getattr(args, clip["source"])),
        ]
        label = escape_text(clip["label"])
        source_name = "SINTEL" if clip["source"] == "sintel" else "BIG BUCK BUNNY"
        filters.append(
            f"[{index}:v]fps={FPS},scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1,settb=AVTB,setpts=PTS-STARTPTS,"
            "eq=contrast=1.07:saturation=1.12:brightness=-0.015,"
            f"drawbox=x=28:y=h-92:w=350:h=58:color=0x06101c@0.72:t=fill,"
            f"drawtext=fontfile='{mono}':text='{label}':x=44:y=h-78:fontsize=22:fontcolor=white,"
            f"drawtext=fontfile='{mono}':text='{source_name}':x=44:y=h-50:fontsize=13:fontcolor=0x77e8ff,"
            "format=yuv420p"
            f"[v{index}]"
        )

    previous = "v0"
    for index in range(1, len(TIMELINE)):
        output = f"x{index}"
        filters.append(
            f"[{previous}][v{index}]xfade=transition={TIMELINE[index]['transition']}:"
            f"duration={TRANSITION_DURATION}:offset={index * 2.5:.1f}[{output}]"
        )
        previous = output

    credit_lines = [
        f"drawtext=fontfile='{cjk}':text='开源素材 · 代码混剪':x=(w-text_w)/2:y=150:fontsize=58:fontcolor=white",
        f"drawtext=fontfile='{mono}':text='Sintel (c) Blender Foundation | durian.blender.org':x=(w-text_w)/2:y=300:fontsize=24:fontcolor=0x9deaff",
        f"drawtext=fontfile='{mono}':text='Big Buck Bunny (c) 2008 Blender Foundation | bigbuckbunny.org':x=(w-text_w)/2:y=348:fontsize=24:fontcolor=0x9deaff",
        f"drawtext=fontfile='{mono}':text='CC BY 3.0 | creativecommons.org/licenses/by/3.0/':x=(w-text_w)/2:y=420:fontsize=22:fontcolor=0xc7d5e5",
        f"drawtext=fontfile='{cjk}':text='裁切重排 / 交叉转场 / 调色 / 字幕 / 原创程序化配乐':x=(w-text_w)/2:y=510:fontsize=25:fontcolor=0xc7d5e5",
        f"drawtext=fontfile='{mono}':text='CODE-CUT / FFMPEG / 20 SEC':x=(w-text_w)/2:y=590:fontsize=18:fontcolor=0x6e8ca8",
    ]
    filters.append(
        f"color=c=0x07111f:s={WIDTH}x{HEIGHT}:r={FPS}:d={CREDIT_DURATION},"
        "settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p," + ",".join(credit_lines) + "[credit]"
    )
    filters.append(
        f"[{previous}][credit]xfade=transition=fade:duration={TRANSITION_DURATION}:offset=17.5[cut]"
    )

    intro_alpha = "if(lt(t,0.25),0,if(lt(t,0.75),(t-0.25)/0.5,if(lt(t,2.0),1,if(lt(t,2.5),(2.5-t)/0.5,0))))"
    filters.append(
        f"[cut]drawbox=x=26:y=24:w=294:h=38:color=0x06101c@0.62:t=fill:enable='lt(t,17.5)',"
        f"drawtext=fontfile='{mono}':text='MOTION / CODE CUT':x=40:y=33:fontsize=18:fontcolor=0x9deaff:enable='lt(t,17.5)',"
        f"drawtext=fontfile='{mono}':text='%{{pts\\:hms}}':x=w-178:y=33:fontsize=18:fontcolor=white:enable='lt(t,17.5)',"
        f"drawtext=fontfile='{cjk}':text='代码，也可以剪辑':x=(w-text_w)/2:y=250:fontsize=76:fontcolor=white:alpha='{intro_alpha}',"
        f"drawtext=fontfile='{mono}':text='FOOTAGE > TIMELINE > RENDER':x=(w-text_w)/2:y=360:fontsize=25:fontcolor=0x9deaff:alpha='{intro_alpha}',"
        "fade=t=in:st=0:d=0.25,fade=t=out:st=19.65:d=0.35,format=yuv420p[vout]"
    )

    with tempfile.TemporaryDirectory(prefix="code-cut-") as temporary:
        score = Path(temporary) / "original_score.wav"
        synthesize_score(score)
        command = ["ffmpeg", "-hide_banner", "-y", *inputs, "-i", str(score)]
        command += [
            "-filter_complex", ";".join(filters),
            "-map", "[vout]",
            "-map", f"{len(TIMELINE)}:a:0",
            "-t", str(TOTAL_DURATION),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-af", "loudnorm=I=-16:TP=-3:LRA=11",
            "-movflags", "+faststart",
            "-metadata", "title=Code Cut - Open Movie Demo",
            "-metadata", "comment=Sintel and Big Buck Bunny: CC BY 3.0, Blender Foundation. Original procedural score.",
            str(args.output),
        ]
        subprocess.run(command, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sintel", type=Path, required=True)
    parser.add_argument("--bbb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args())
