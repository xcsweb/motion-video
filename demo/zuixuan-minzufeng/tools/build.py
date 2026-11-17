#!/usr/bin/env python3
"""Sixteen-bar 最炫民族风 original-voice sample on the sung syllable grid."""
import json
import os
from pathlib import Path
import re
import subprocess

import numpy as np
import pyworld as pw
import scipy.io.wavfile as wf
from scipy.signal import medfilt

SR = 48000
ROOT = Path('/workspace/demo/zuixuan-minzufeng')
SOURCE = Path('/workspace/.tmp-guichu/zuotian.mp4')
BACKING = ROOT / 'assets/zuixuan-no-harmony-instrumental.mp3'
ANALYSIS = json.loads((ROOT / 'assets/song-analysis-no-harmony.json').read_text(encoding='utf-8'))
TRANSCRIPT = ROOT / 'assets/source-transcript.json'
BPM = ANALYSIS['gridBpm']
BEAT = 60.0 / BPM
BAR = 4.0 * BEAT
START_BEAT = 56.0
END_BEAT = 120.0
DURATION = (END_BEAT - START_BEAT) * BEAT
BACKING_START = ANALYSIS['phaseSeconds'] + START_BEAT * BEAT
UNITS_DIR = ROOT / 'assets/units-long'

# Original-vocal onsets snapped to the measured half-beat grid. Unit boundaries
# preserve natural word groups; only the sustained rhyme characters stand alone.
LINES = [
    {
        'speaker': '白云', 'text': '秋波就是秋天的菠菜',
        'units': ['秋波就是秋天的菠', '菜'],
        'beats': [56, 56.5, 57, 57.5, 58, 58.5, 59, 59.5, 60], 'end': 63,
        'midi': [58, 58, 57, 50, 58, 58, 58, 61, 61],
    },
    {
        'speaker': '黑土', 'text': '白云黑土咱俩来谈恋爱',
        'units': ['白云', '黑土', '咱俩', '来', '谈恋', '爱'],
        'beats': [63, 63.5, 64, 65, 65.5, 66, 66.5, 67, 67.5, 68], 'end': 71,
        'midi': [58, 59, 61, 58, 58, 61, 62, 65, 66, 62],
    },
    {
        'speaker': '白云', 'text': '我送你的秋波是最呀最可爱',
        'units': ['我', '送', '你的', '秋波是', '最', '呀', '最', '可', '爱'],
        'beats': [71, 72, 72.5, 73, 73.5, 74, 74.5, 75, 75.5, 76, 76.5, 77], 'end': 79,
        'midi': [65, 70, 70, 70, 67, 66, 64, 61, 58, 58, 55, 63],
    },
    {
        'speaker': '黑土', 'text': '你送我的猪肉才是最精彩',
        'units': ['你', '送', '我的', '猪肉', '才', '是', '最', '精', '彩'],
        'beats': [79, 80, 80.5, 81, 81.5, 82, 82.5, 83, 83.5, 84, 85], 'end': 87,
        'midi': [65, 65, 66, 66, 56, 63, 62, 58, 59, 58, 55],
    },
    {
        'speaker': '白云', 'text': '这张旧船票从哪里来',
        'units': ['这张旧船票', '从', '哪', '里', '来'],
        'beats': [87, 88, 89, 89.5, 90, 90.5, 91, 91.5, 92], 'end': 95,
        'midi': [58, 58, 57, 53, 58, 59, 57, 58, 62],
    },
    {
        'speaker': '黑土', 'text': '能否登上你的破船回来',
        'units': ['能否登上你的破船', '回', '来'],
        'beats': [95, 96, 96.5, 97, 97.5, 98, 98.5, 99, 99.5, 100], 'end': 103,
        'midi': [50, 61, 50, 59, 56, 62, 67, 63, 68, 61],
    },
    {
        'speaker': '白云', 'text': '昨天今天明天咱俩都要相爱',
        'units': ['昨天今天明天', '咱俩', '都', '要', '相', '爱'],
        'beats': [103, 104, 105, 105.5, 106, 106.5, 107, 107.5, 108, 108.5, 109, 109.5], 'end': 111,
        'midi': [65, 70, 69, 63, 65, 65, 60, 58, 58, 58, 61, 63],
    },
    {
        'speaker': '黑土', 'text': '咱俩好好过日子才最自在',
        'units': ['咱俩', '好', '好', '过', '日子', '才', '最', '自', '在'],
        'beats': [111, 111.5, 112, 112.5, 113, 113.5, 114, 114.5, 115, 115.5, 116], 'end': 120,
        'midi': [56, 56, 65, 65, 67, 62, 64, 65, 56, 60, 56],
    },
]

# Slice rhyme consonants/vowels from the same original word rather than taking
# unrelated occurrences. Other units use their longest exact transcript match.
SOURCE_ALIASES = {
    '秋波': '豬锅',
    '秋波是': '豬锅是',
    '秋波就是秋天的菠': '豬锅就是豬天地博',
    '秋天的': '豬天地',
    '梦中': '夢中',
    '旧船票': '旧传票',
    '这张旧船票': '这张旧传票',
    '猪肉': '豬肉',
    '咱俩': '阿俩',
}
SOURCE_SLICES = {
    '菠': ('博菜', 0),
    '菜': ('博菜', 1),
    '相': ('相约', 0),
    '才': ('材理', 0),
    '彩': ('材理', 0),
}


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
    fade_in = min(int(0.006 * SR), len(x) // 8)
    fade_out = min(int(0.022 * SR), len(x) // 8)
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


def chinese(text):
    return re.sub(r'[^\u4e00-\u9fff]', '', text or '')


def load_corpus():
    data = json.loads(TRANSCRIPT.read_text(encoding='utf-8'))
    corpus = []
    for segment in data['segments']:
        chars = []
        for word in segment.get('words', []):
            text = chinese(word.get('text', ''))
            if not text or word.get('start') is None or word.get('end') is None:
                continue
            start = float(word['start'])
            end = max(start + 0.04, float(word['end']))
            for index, char in enumerate(text):
                chars.append({
                    'text': char,
                    'start': start + (end - start) * index / len(text),
                    'end': start + (end - start) * (index + 1) / len(text),
                })
        if not chars:
            text = chinese(segment['text'])
            for index, char in enumerate(text):
                chars.append({
                    'text': char,
                    'start': segment['start'] + (segment['end'] - segment['start']) * index / len(text),
                    'end': segment['start'] + (segment['end'] - segment['start']) * (index + 1) / len(text),
                })
        corpus.append({
            'segmentId': segment['id'],
            'segmentText': segment['text'],
            'text': ''.join(char['text'] for char in chars),
            'chars': chars,
        })
    return corpus


def find_source(unit, corpus, target_duration):
    query, slice_index = SOURCE_SLICES.get(
        unit, (SOURCE_ALIASES.get(unit, unit), None),
    )
    candidates = []
    for segment in corpus:
        text = segment['text']
        offset = 0
        while True:
            index = text.find(query, offset)
            if index < 0:
                break
            first = index if slice_index is None else index + slice_index
            last = index + len(query) if slice_index is None else first + 1
            selected = segment['chars'][first:last]
            offset = index + 1
            if len(selected) != (len(query) if slice_index is None else 1):
                continue
            start = selected[0]['start']
            end = selected[-1]['end']
            duration = end - start
            if duration <= 0.04:
                continue
            per_char = duration / len(selected)
            score = abs(np.log(duration / target_duration))
            score += 0.15 * abs(np.log(max(per_char, 0.04) / 0.24))
            if len(query) > 1:
                score -= 0.08
            candidates.append((score, start, end, segment, selected, query))
    if not candidates:
        raise RuntimeError(f'No original-voice source found for {unit!r} (query {query!r})')
    _, start, end, segment, selected, source_query = min(candidates, key=lambda item: item[0])
    return {
        'text': unit,
        'sourceQuery': source_query,
        'start': max(0.0, start - 0.012),
        'end': end + 0.030,
        'segmentId': segment['segmentId'],
        'segmentText': segment['segmentText'],
    }


def source_f0(audio):
    voiced = pw.harvest(
        audio.astype(np.float64), SR,
        f0_floor=70.0, f0_ceil=400.0, frame_period=5.0,
    )[0]
    values = voiced[voiced > 0]
    return float(np.median(values)) if len(values) else 0.0


def main():
    os.makedirs(UNITS_DIR, exist_ok=True)
    corpus = load_corpus()
    source_cache = {}
    vocal = np.zeros(int(round(DURATION * SR)), dtype=np.float32)
    timeline = []
    subtitle_lines = []

    for line_index, line in enumerate(LINES, 1):
        if ''.join(line['units']) != line['text'] or len(line['beats']) != len(line['text']):
            raise ValueError(f"Invalid lyric grid: {line['text']}")
        char_index = 0
        events = []
        for unit_index, unit in enumerate(line['units'], 1):
            next_char = char_index + len(unit)
            start_beat = line['beats'][char_index]
            end_beat = line['beats'][next_char] if next_char < len(line['beats']) else line['end']
            target_duration = (end_beat - start_beat) * BEAT
            cache_key = (unit, round(target_duration, 3))
            if cache_key not in source_cache:
                source_cache[cache_key] = find_source(unit, corpus, target_duration)
            item = source_cache[cache_key]
            unit_id = f'{line_index:02d}-{unit_index:02d}'
            original_path = UNITS_DIR / f'{unit_id}-{unit}-original.wav'
            source_duration = item['end'] - item['start']
            run([
                'ffmpeg', '-hide_banner', '-v', 'error', '-y',
                '-ss', f"{item['start']:.6f}", '-t', f'{source_duration:.6f}',
                '-i', SOURCE, '-vn', '-ac', '1', '-ar', SR,
                '-af', 'highpass=f=65,lowpass=f=12000',
                '-c:a', 'pcm_s16le', original_path,
            ])
            original = read_audio(original_path)
            events.append({
                'unit': unit,
                'item': item,
                'charStart': char_index,
                'charEnd': next_char,
                'startBeat': start_beat,
                'endBeat': end_beat,
                'originalPath': original_path,
                'original': original,
                'sourceF0': source_f0(original),
            })
            char_index = next_char

        valid_f0 = [event['sourceF0'] for event in events if event['sourceF0'] > 0]
        fallback_f0 = 180.0 if line['speaker'] == '白云' else 125.0
        line_source_f0 = float(np.median(valid_f0)) if valid_f0 else fallback_f0
        line_source_midi = 69 + 12 * np.log2(line_source_f0 / 440.0)
        target_midi = medfilt(np.asarray(line['midi'], dtype=np.float64), kernel_size=3)
        target_midi = np.clip(
            target_midi, np.median(target_midi) - 7.0, np.median(target_midi) + 7.0,
        )
        octave = int(np.round((float(np.median(target_midi)) - line_source_midi) / 12.0)) * 12

        for event in events:
            output_start = (event['startBeat'] - START_BEAT) * BEAT
            output_end = (event['endBeat'] - START_BEAT) * BEAT
            offset = int(round(output_start * SR))
            end_sample = int(round(output_end * SR))
            target_duration = (end_sample - offset) / SR
            source_duration = len(event['original']) / SR
            event_f0 = event['sourceF0'] or line_source_f0
            event_source_midi = 69 + 12 * np.log2(event_f0 / 440.0)
            event_target_midi = float(np.median(target_midi[event['charStart']:event['charEnd']])) - octave
            semitones = float(np.clip(event_target_midi - event_source_midi, -1.5, 1.5))
            tempo = source_duration / target_duration
            pitch = 2.0 ** (semitones / 12.0)
            window = 'long' if target_duration > 0.8 else 'standard'
            filters = (
                f'rubberband=tempo={tempo:.8f}:pitch={pitch:.8f}:'
                f'transients=crisp:detector=compound:formant=preserved:pitchq=quality:window={window},'
                'aresample=48000'
            )
            tuned_path = event['originalPath'].with_name(
                event['originalPath'].name.replace('-original.wav', '-tuned.wav')
            )
            run([
                'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', event['originalPath'],
                '-af', filters, '-ac', '1', '-ar', SR,
                '-c:a', 'pcm_f32le', tuned_path,
            ])
            tuned = fit_slot(read_audio(tuned_path), end_sample - offset)
            active = np.abs(tuned) > max(0.006, float(np.max(np.abs(tuned))) * 0.04)
            rms = float(np.sqrt(np.mean(tuned[active] ** 2))) if np.any(active) else 0.0
            gain = min(4.0, 0.115 / rms) if rms > 1e-6 else 1.0
            tuned *= gain
            peak = float(np.max(np.abs(tuned)))
            if peak > 0.94:
                tuned *= 0.94 / peak
            vocal[offset:end_sample] += tuned

            record = {
                'line': line_index,
                'speaker': line['speaker'],
                'text': event['unit'],
                'source': {
                    'file': str(SOURCE),
                    'start': round(event['item']['start'], 6),
                    'end': round(event['item']['end'], 6),
                    'segmentId': event['item']['segmentId'],
                    'segmentText': event['item']['segmentText'],
                    'query': event['item']['sourceQuery'],
                },
                'output': {'start': output_start, 'end': output_end},
                'beat': event['startBeat'] - START_BEAT,
                'beats': event['endBeat'] - event['startBeat'],
                'sourceMedianF0Hz': round(event_f0, 3),
                'targetMidi': round(event_target_midi, 3),
                'appliedPitchSemitones': round(semitones, 3),
                'tempoFactor': round(tempo, 5),
                'processing': 'original word/whole-character Rubber Band; formants preserved; no WORLD synthesis',
                'originalUnit': os.path.relpath(event['originalPath'], ROOT),
                'tunedUnit': os.path.relpath(tuned_path, ROOT),
            }
            timeline.append(record)
            print(
                f"{line_index}.{event['unit']} | beat {record['beat']:.1f}-{record['beat'] + record['beats']:.1f} | "
                f"source {event['item']['start']:.2f} | tempo {tempo:.3f} | pitch {semitones:+.1f}",
                flush=True,
            )

        line_start = (line['beats'][0] - START_BEAT) * BEAT
        line_end = (line['end'] - START_BEAT) * BEAT
        subtitle_lines.append({
            'speaker': line['speaker'], 'text': line['text'],
            'start': line_start, 'end': line_end,
        })

    write_audio(ROOT / 'assets/vocals-long.wav', vocal)
    instrumental_path = ROOT / 'assets/instrumental-no-harmony.wav'
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y',
        '-ss', f'{BACKING_START:.8f}', '-t', f'{DURATION:.8f}', '-i', BACKING,
        '-filter_complex',
        '[0:a]asplit=2[a][b];[a]stereotools=mlev=0.015625[side];'
        '[b]lowpass=f=180[low];[side][low]'
        'amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[out]',
        '-map', '[out]', '-ac', '2', '-ar', SR, '-c:a', 'pcm_s16le', instrumental_path,
    ])
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', instrumental_path,
        '-c:a', 'libmp3lame', '-q:a', '2', ROOT / 'zuixuan-no-harmony-bgm-30s.mp3',
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
    backing_gain = min(0.65, vocal_rms / (3.0 * backing_rms))
    mix = backing * backing_gain + vocal[:, None]
    fade_in = int(0.020 * SR)
    fade_out = int(0.180 * SR)
    mix[:fade_in] *= np.linspace(0.0, 1.0, fade_in)[:, None]
    mix[-fade_out:] *= np.linspace(1.0, 0.0, fade_out)[:, None]
    peak = float(np.max(np.abs(mix)))
    if peak > 0.95:
        mix *= 0.95 / peak
    raw_path = ROOT / 'assets/mix-long-raw.wav'
    write_audio(raw_path, mix)
    final_wav = ROOT / 'zuixuan-minzufeng-long-sample.wav'
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', raw_path,
        '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11', '-ar', SR,
        '-c:a', 'pcm_s16le', final_wav,
    ])
    run([
        'ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', final_wav,
        '-c:a', 'libmp3lame', '-q:a', '2', ROOT / 'zuixuan-minzufeng-long-sample.mp3',
    ])

    metadata = {
        'title': '白云黑土·最炫民族风（十六小节原声填词样）',
        'bpm': BPM,
        'beatSeconds': BEAT,
        'barSeconds': BAR,
        'duration': DURATION,
        'sourceVideo': str(SOURCE),
        'song': {
            'title': '最炫民族风',
            'artist': '凤凰传奇',
            'instrumental': str(BACKING),
            'sourceStart': BACKING_START,
            'duration': DURATION,
            'instrumentalPage': 'https://5sing.kugou.com/bz/2845354.html',
            'instrumentalLabel': '原版无和声纯伴奏',
            'rightsNote': '仅作用户要求的非商业试样；公开发布或商业使用需另行确认歌曲、录音及原片授权。',
        },
        'method': [
            'Eight sung phrases on a measured 16-bar, half-beat onset grid.',
            'Original dialogue word groups and complete characters; no TTS or voice conversion.',
            'One Rubber Band tempo/pitch transform per unit; formants preserved.',
            'Sustained rhyme characters are isolated instead of stretching a whole sentence.',
            'Subtitle times come from the final rendered event grid.',
        ],
        'lyrics': [f"{line['speaker']}：{line['text']}" for line in subtitle_lines],
        'vocalRms': vocal_rms,
        'backingRms': backing_rms,
        'backingGain': backing_gain,
        'lines': subtitle_lines,
        'units': timeline,
    }
    (ROOT / 'assets/timeline-long.json').write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8',
    )
    with (ROOT / 'assets/subtitles-long.srt').open('w', encoding='utf-8') as file:
        for index, record in enumerate(subtitle_lines, 1):
            file.write(
                f"{index}\n{srt_time(record['start'])} --> {srt_time(record['end'])}\n"
                f"{record['speaker']}：{record['text']}\n\n",
            )
    print('wrote', ROOT / 'zuixuan-minzufeng-long-sample.mp3')
    print(
        'duration', DURATION, 'backing start', BACKING_START,
        'backing gain', backing_gain,
        'vocal/backing RMS ratio', vocal_rms / (backing_rms * backing_gain),
    )


if __name__ == '__main__':
    main()
