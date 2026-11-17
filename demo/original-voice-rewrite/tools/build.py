#!/usr/bin/env python3
"""Four-bar original-voice rewrite: whole dialogue phrases only.

No TTS, no WORLD synthesis and no syllable fragmentation. Rubber Band applies
one tempo/pitch transform to each complete source phrase; every phrase keeps
its original consonants, vowels and coarticulation.
"""
import json
import os
import subprocess

import numpy as np
import pyworld as pw
import scipy.io.wavfile as wf

SR = 48000
BPM = 105.47
BEAT = 60.0 / BPM
BAR = 4.0 * BEAT
SLOT = BAR / 2.0
DURATION = 4.0 * BAR
ROOT = '/workspace/demo/original-voice-rewrite'
SOURCE = '/workspace/.tmp-guichu/zuotian.mp4'
BACKING = '/workspace/demo/guichu-v2/assets/backing.wav'
UNITS_DIR = ROOT + '/assets/units'

# Source spans come from the earlier picture-linked dialogue edit. Each span
# contains a complete spoken phrase and keeps its original picture timecode.
CORPUS = {
    'baiyun': {'text': '我叫白云', 'start': 90.73, 'end': 92.28, 'speaker': '白云'},
    'heitu': {'text': '我叫黑土', 'start': 92.17, 'end': 93.62, 'speaker': '黑土'},
    'qishiyi': {'text': '我七十一', 'start': 94.03, 'end': 95.62, 'speaker': '白云'},
    'qishiwu': {'text': '我七十五', 'start': 95.51, 'end': 96.58, 'speaker': '黑土'},
    'shuji': {'text': '我属鸡', 'start': 96.47, 'end': 97.62, 'speaker': '白云'},
    'shuhu': {'text': '我属虎', 'start': 97.51, 'end': 98.54, 'speaker': '黑土'},
    'laogong': {'text': '这是我老公', 'start': 98.43, 'end': 99.66, 'speaker': '白云'},
    'laomu': {'text': '这是我老母', 'start': 99.55, 'end': 100.70, 'speaker': '黑土'},
}

# New lyric order: every pair is reversed from the original dialogue.
# Small call/response pitch shifts retain the actors' natural phrase intonation.
# The note names describe the backing harmony colour, not a forced vocal F0.
SEQUENCE = [
    ('heitu', 'Eb4', -2.0), ('baiyun', 'G4', 2.0),
    ('laomu', 'F4', -1.0), ('laogong', 'D4', 2.0),
    ('qishiwu', 'C4', -2.0), ('qishiyi', 'A4', 2.0),
    ('shuhu', 'D4', 0.0), ('shuji', 'Bb4', 3.0),
]


def run(cmd):
    subprocess.run(cmd, check=True)


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
    fade_out = min(int(0.020 * SR), len(x) // 8)
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
    corpus_out = []

    for index, (unit_id, note_name, semitones) in enumerate(SEQUENCE):
        item = CORPUS[unit_id]
        original_path = f'{UNITS_DIR}/{index + 1:02d}-{unit_id}-original.wav'
        tuned_path = f'{UNITS_DIR}/{index + 1:02d}-{unit_id}-tuned.wav'
        source_duration = item['end'] - item['start']
        run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y',
            '-ss', f"{item['start']:.6f}", '-t', f'{source_duration:.6f}',
            '-i', SOURCE, '-vn', '-ac', '1', '-ar', str(SR),
            '-af', 'highpass=f=65,lowpass=f=12000',
            '-c:a', 'pcm_s16le', original_path,
        ])
        original = read_audio(original_path)
        voiced = pw.harvest(original.astype(np.float64), SR, f0_floor=70.0,
                            f0_ceil=400.0, frame_period=5.0)[0]
        f0_values = voiced[voiced > 0]
        source_f0 = float(np.median(f0_values)) if len(f0_values) else 0.0
        pitch = 2.0 ** (semitones / 12.0)
        tempo = source_duration / SLOT
        filters = (
            f'rubberband=tempo={tempo:.8f}:pitch={pitch:.8f}:'
            'transients=smooth:detector=soft:formant=preserved:pitchq=quality,'
            'aresample=48000'
        )
        run([
            'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', original_path,
            '-af', filters, '-ac', '1', '-ar', str(SR),
            '-c:a', 'pcm_f32le', tuned_path,
        ])
        output_start = index * SLOT
        offset = int(round(output_start * SR))
        output_end = int(round((index + 1) * SLOT * SR))
        tuned = fit_slot(read_audio(tuned_path), output_end - offset)
        active = np.abs(tuned) > max(0.006, float(np.max(np.abs(tuned))) * 0.04)
        rms = float(np.sqrt(np.mean(tuned[active] ** 2))) if np.any(active) else 0.0
        gain = min(3.0, 0.12 / rms) if rms > 1e-6 else 1.0
        tuned *= gain
        peak = float(np.max(np.abs(tuned)))
        if peak > 0.94:
            tuned *= 0.94 / peak
        vocal[offset:output_end] += tuned
        record = {
            'index': index + 1,
            'unitId': unit_id,
            'text': item['text'],
            'speaker': item['speaker'],
            'source': {'file': SOURCE, 'start': item['start'], 'end': item['end']},
            'sourceDuration': source_duration,
            'output': {'start': output_start, 'end': output_start + SLOT},
            'backingChordTone': note_name,
            'sourceMedianF0Hz': round(source_f0, 3),
            'appliedPitchSemitones': round(semitones, 3),
            'tempoFactor': round(tempo, 5),
            'processing': 'whole-phrase Rubber Band; formants preserved; no WORLD synthesis',
            'originalUnit': os.path.relpath(original_path, ROOT),
            'tunedUnit': os.path.relpath(tuned_path, ROOT),
        }
        timeline.append(record)
        corpus_out.append(record)
        print(f"{index + 1}. {item['text']} | {item['start']:.2f}-{item['end']:.2f} | "
              f"tempo {tempo:.3f} | pitch {semitones:+.2f} st | F0 {source_f0:.1f} Hz")

    write_audio(ROOT + '/assets/vocals.wav', vocal)

    backing = read_audio(BACKING)
    if backing.ndim == 1:
        backing = np.column_stack([backing, backing])
    start_sample = int(round(4 * BAR * SR))
    n_samples = len(vocal)
    backing = backing[start_sample:start_sample + n_samples]
    if len(backing) < n_samples:
        backing = np.pad(backing, ((0, n_samples - len(backing)), (0, 0)))
    write_audio(ROOT + '/assets/instrumental.wav', backing)

    vocal_active = np.abs(vocal) > 0.008
    vocal_rms = float(np.sqrt(np.mean(vocal[vocal_active] ** 2)))
    backing_rms = float(np.sqrt(np.mean(backing ** 2)))
    backing_gain = min(0.70, vocal_rms / (3.0 * backing_rms))
    mix = backing * backing_gain + vocal[:, None]
    fade_in = int(0.020 * SR)
    fade_out = int(0.180 * SR)
    mix[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    peak = float(np.max(np.abs(mix)))
    if peak > 0.92:
        mix *= 0.92 / peak
    write_audio(ROOT + '/original-voice-rewrite.wav', mix)
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y',
        '-i', ROOT + '/original-voice-rewrite.wav',
        '-c:a', 'libmp3lame', '-q:a', '2', ROOT + '/original-voice-rewrite.mp3',
    ])

    lines = []
    for bar in range(4):
        pair = SEQUENCE[bar * 2:bar * 2 + 2]
        lines.append('／'.join(CORPUS[unit_id]['text'] for unit_id, _, _ in pair))
    metadata = {
        'title': '白云黑土·台词倒装（四小节原声填词样）',
        'bpm': BPM,
        'beatSeconds': BEAT,
        'barSeconds': BAR,
        'duration': DURATION,
        'sourceVideo': SOURCE,
        'backing': {'file': BACKING, 'sourceStart': 4 * BAR, 'duration': DURATION},
        'method': [
            'Only complete original dialogue phrases are selected.',
            'Each phrase receives one Rubber Band tempo/pitch transform.',
            'No TTS, no voice conversion, no WORLD synthesis, no syllable slicing.',
            'Picture timecodes are retained for the later video edit.',
        ],
        'lyrics': lines,
        'vocalRms': vocal_rms,
        'backingRms': backing_rms,
        'backingGain': backing_gain,
        'units': timeline,
    }
    with open(ROOT + '/assets/timeline.json', 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    with open(ROOT + '/assets/source-corpus.json', 'w', encoding='utf-8') as f:
        json.dump(corpus_out, f, ensure_ascii=False, indent=2)
    with open(ROOT + '/assets/subtitles.srt', 'w', encoding='utf-8') as f:
        for i, record in enumerate(timeline, 1):
            f.write(f"{i}\n{srt_time(record['output']['start'])} --> "
                    f"{srt_time(record['output']['end'])}\n{record['text']}\n\n")
    print('wrote', ROOT + '/original-voice-rewrite.wav')
    print('duration', DURATION, 'backing gain', backing_gain,
          'vocal/backing RMS ratio', vocal_rms / (backing_rms * backing_gain))


if __name__ == '__main__':
    main()
