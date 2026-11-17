#!/usr/bin/env python3
"""Transcribe the source sketch with word times for original-voice lyric mining."""
import json
import os
from pathlib import Path

from faster_whisper import WhisperModel

ROOT = Path('/workspace/demo/zuixuan-minzufeng')
SOURCE = '/workspace/.tmp-guichu/zuotian.mp4'
OUT = ROOT / 'assets/source-transcript.json'


def main():
    model = WhisperModel(os.environ.get('WHISPER_MODEL', 'base'), device='cpu', compute_type='int8')
    segments, info = model.transcribe(
        SOURCE,
        language='zh',
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    result = {
        'source': SOURCE,
        'language': info.language,
        'duration': info.duration,
        'segments': [],
    }
    for segment in segments:
        record = {
            'id': segment.id,
            'start': segment.start,
            'end': segment.end,
            'text': segment.text.strip(),
            'words': [
                {'start': w.start, 'end': w.end, 'text': w.word}
                for w in (segment.words or [])
            ],
        }
        result['segments'].append(record)
        print(f"{segment.start:8.2f}-{segment.end:8.2f} {record['text']}", flush=True)
        if len(result['segments']) % 10 == 0:
            OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
