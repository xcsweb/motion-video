#!/usr/bin/env python3
"""Four-bar 最炫民族风 sample using complete original dialogue phrases."""
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pyworld as pw
import scipy.io.wavfile as wf

SR = 48000
ROOT = Path('/workspace/demo/zuixuan-minzufeng')
SOURCE = Path('/workspace/.tmp-guichu/zuotian.mp4')
BACKING = ROOT / 'assets/zuixuan-official-instrumental.mp3'
ANALYSIS = json.loads((ROOT / 'assets/song-analysis.json').read_text(encoding='utf-8'))
BPM = ANALYSIS['gridBpm']
BEAT = 60.0 / BPM
BAR = 4.0 * BEAT
DURATION = 4.0 * BAR
UNITS_DIR = ROOT / 'assets/units'

CORPUS = {
    'baiyun': {'text': '我叫白云', 'start': 90.73, 'end': 92.28, 'speaker': '白云'},
    'heitu': {'text': '我叫黑土', 'start': 92.17, 'end': 93.62, 'speaker': '黑土'},
    'qishiwu': {'text': '我七十五', 'start': 95.51, 'end': 96.58, 'speaker': '黑土'},
    'shuji': {'text': '我属鸡', 'start': 96.47, 'end': 97.62, 'speaker': '白云'},
    'shuhu': {'text': '我属虎', 'start': 97.51, 'end': 98.54, 'speaker': '黑土'},
    'laogong': {'text': '这是我老公', 'start': 98.43, 'end': 99.66, 'speaker': '白云'},
    'laomu': {'text': '这是我老母', 'start': 99.55, 'end': 100.70, 'speaker': '黑土'},
}

# Two vocal lines follow the first two-line verse phrasing. Each pair of bars
# has three complete phrases on a 2.5 + 2.5 + 2.5 beat grid and a half-beat rest.
SEQUENCE = [
    {'unit': 'baiyun', 'beat': 0.0, 'beats': 2.5, 'pitch': 1.0},
    {'unit': 'shuji', 'beat': 2.5, 'beats': 2.5, 'pitch': 3.0},
    {'unit': 'laogong', 'beat': 5.0, 'beats': 2.5, 'pitch': 1.0},
    {'unit': 'heitu', 'beat': 8.0, 'beats': 2.5, 'pitch': -1.0},
    {'unit': 'shuhu', 'beat': 10.5, 'beats': 2.5, 'pitch': 1.0},
    {'unit': 'laomu', 'beat': 13.0, 'beats': 2.5, 'pitch': -1.0},
]


def run(cmd):
    subprocess.run([str(x) for x in cmd], check=True)


def read_audio(path):
    sr, x = wf.read(path)
    if sr != SR:
        raise ValueError(f'{path}: expected {SR}, got {sr}')
    if x.dtype.kind == 'i':
        x = x.astype(np.float32) / (32768.0 if x.dtype.itemsize == 2 else 2147483648.0)
    else:
        x = x.astype(np.float32)
    return x


def write_audio(path, x):
    x = np.clip(x, -1.0, 1.0)
    wf.write(path, SR, (x * 32767.0).astype(np.int16))


def fit_slot(x, samples):
    if len(x) < samples:
        x = np.pad(x, (0, samples - len(x)))
    else:
        x = x[:samples].copy()
    fade_in = min(int(0.008 * SR), len(x) // 8)
    fade_out = min(int(0.025 * SR), len(x) // 8)
    if fade_in:
        x[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out:
        x[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    return x


def srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def main():
    os.makedirs(UNITS_DIR, exist_ok=True)
    vocal = np.zeros(int(round(DURATION * SR)), dtype=np.float32)
    timeline = []

    for index, event in enumerate(SEQUENCE):
        item = CORPUS[event['unit']]
        unit_id = event['unit']
        original_path = UNITS_DIR / f'{index + 1:02d}-{unit_id}-original.wav'
        tuned_path = UNITS_DIR / f'{index + 1:02d}-{unit_id}-tuned.wav'
        source_duration = item['end'] - item['start']
        run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y',
            '-ss', f"{item['start']:.6f}", '-t', f'{source_duration:.6f}',
            '-i', SOURCE, '-vn', '-ac', '1', '-ar', SR,
            '-af', 'highpass=f=65,lowpass=f=12000',
            '-c:a', 'pcm_s16le', original_path,
        ])
        original = read_audio(original_path)
        voiced = pw.harvest(
            original.astype(np.float64), SR,
            f0_floor=70.0, f0_ceil=400.0, frame_period=5.0
        )[0]
        f0_values = voiced[voiced > 0]
        source_f0 = float(np.median(f0_values)) if len(f0_values) else 0.0

        output_start = event['beat'] * BEAT
        output_end = (event['beat'] + event['beats']) * BEAT
        offset = int(round(output_start * SR))
        end_sample = int(round(output_end * SR))
        target_duration = (end_sample - offset) / SR
        tempo = source_duration / target_duration
        pitch = 2.0 ** (event['pitch'] / 12.0)
        filters = (
            f'rubberband=tempo={tempo:.8f}:pitch={pitch:.8f}:'
            'transients=smooth:detector=soft:formant=preserved:pitchq=quality,'
            'aresample=48000'
        )
        run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', original_path,
            '-af', filters, '-ac', '1', '-ar', SR,
            '-c:a', 'pcm_f32le', tuned_path,
        ])
        tuned = fit_slot(read_audio(tuned_path), end_sample - offset)
        active = np.abs(tuned) > max(0.006, float(np.max(np.abs(tuned))) * 0.04)
        rms = float(np.sqrt(np.mean(tuned[active] ** 2))) if np.any(active) else 0.0
        gain = min(3.0, 0.12 / rms) if rms > 1e-6 else 1.0
        tuned *= gain
        peak = float(np.max(np.abs(tuned)))
        if peak > 0.94:
            tuned *= 0.94 / peak
        vocal[offset:end_sample] += tuned

        record = {
            'index': index + 1,
            'unitId': unit_id,
            'text': item['text'],
            'speaker': item['speaker'],
            'source': {'file': str(SOURCE), 'start': item['start'], 'end': item['end']},
            'sourceDuration': source_duration,
            'output': {'start': output_start, 'end': output_end},
            'beat': event['beat'],
            'beats': event['beats'],
            'sourceMedianF0Hz': round(source_f0, 3),
            'appliedPitchSemitones': event['pitch'],
            'tempoFactor': round(tempo, 5),
            'processing': 'whole-phrase Rubber Band; formants preserved; no WORLD synthesis',
            'originalUnit': os.path.relpath(original_path, ROOT),
            'tunedUnit': os.path.relpath(tuned_path, ROOT),
        }
        timeline.append(record)
        print(f"{index + 1}. {item['speaker']}: {item['text']} | "
              f"beat {event['beat']:+.1f} | tempo {tempo:.3f} | pitch {event['pitch']:+.1f} st")

    write_audio(ROOT / 'assets/vocals.wav', vocal)

    # The public timed lyrics place the first verse at 23.89 s. Snap that
    # reference to the measured fixed beat grid rather than guessing a bar cut.
    verse_start = ANALYSIS['phaseSeconds'] + round(
        (23.89 - ANALYSIS['phaseSeconds']) / BEAT
    ) * BEAT
    instrumental_path = ROOT / 'assets/instrumental.wav'
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y',
        '-ss', f'{verse_start:.8f}', '-t', f'{DURATION:.8f}', '-i', BACKING,
        '-ac', '2', '-ar', SR, '-c:a', 'pcm_s16le', instrumental_path,
    ])
    backing = read_audio(instrumental_path)
    if backing.ndim == 1:
        backing = np.column_stack([backing, backing])
    if len(backing) < len(vocal):
        backing = np.pad(backing, ((0, len(vocal) - len(backing)), (0, 0)))
    backing = backing[:len(vocal)]

    vocal_active = np.abs(vocal) > 0.008
    vocal_rms = float(np.sqrt(np.mean(vocal[vocal_active] ** 2)))
    backing_rms = float(np.sqrt(np.mean(backing ** 2)))
    backing_gain = min(0.55, vocal_rms / (3.2 * backing_rms))
    mix = backing * backing_gain + vocal[:, None]
    fade_in = int(0.020 * SR)
    fade_out = int(0.150 * SR)
    mix[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    peak = float(np.max(np.abs(mix)))
    if peak > 0.92:
        mix *= 0.92 / peak
    write_audio(ROOT / 'zuixuan-minzufeng-sample.wav', mix)
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y',
        '-i', ROOT / 'zuixuan-minzufeng-sample.wav',
        '-c:a', 'libmp3lame', '-q:a', '2', ROOT / 'zuixuan-minzufeng-sample.mp3',
    ])

    metadata = {
        'title': '白云黑土·最炫民族风（四小节原声填词样）',
        'bpm': BPM,
        'beatSeconds': BEAT,
        'barSeconds': BAR,
        'duration': DURATION,
        'sourceVideo': str(SOURCE),
        'song': {
            'title': '最炫民族风',
            'artist': '凤凰传奇',
            'original': str(ROOT / 'assets/zuixuan-original.mp3'),
            'instrumental': str(BACKING),
            'sourceStart': verse_start,
            'duration': DURATION,
            'originalPage': 'http://www.kqcp.com/index.php?c=show&id=78',
            'instrumentalPage': 'https://5sing.kugou.com/bz/2650283.html',
            'rightsNote': '仅作用户要求的非商业试样；公开发布或商业使用需另行确认歌曲、录音及原片授权。',
        },
        'method': [
            'Complete original dialogue phrases only; no syllable slicing.',
            'One Rubber Band tempo/pitch transform per phrase; formants preserved.',
            'No TTS, voice conversion or WORLD synthesis.',
            'Subtitle times come from the actual rendered audio event grid.',
        ],
        'lyrics': [
            '白云：我叫白云／我属鸡／这是我老公',
            '黑土：我叫黑土／我属虎／这是我老母',
        ],
        'vocalRms': vocal_rms,
        'backingRms': backing_rms,
        'backingGain': backing_gain,
        'units': timeline,
    }
    (ROOT / 'assets/timeline.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    with (ROOT / 'assets/subtitles.srt').open('w', encoding='utf-8') as f:
        for i, record in enumerate(timeline, 1):
            f.write(f"{i}\n{srt_time(record['output']['start'])} --> "
                    f"{srt_time(record['output']['end'])}\n"
                    f"{record['speaker']}：{record['text']}\n\n")
    print('wrote', ROOT / 'zuixuan-minzufeng-sample.mp3')
    print('duration', DURATION, 'verse start', verse_start,
          'backing gain', backing_gain,
          'vocal/backing RMS ratio', vocal_rms / (backing_rms * backing_gain))


if __name__ == '__main__':
    main()
