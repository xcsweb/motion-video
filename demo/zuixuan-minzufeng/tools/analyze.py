#!/usr/bin/env python3
"""Measure the song tempo and beat phase from the actual accompaniment."""
import argparse
import json
from pathlib import Path

import librosa
import numpy as np

ROOT = Path('/workspace/demo/zuixuan-minzufeng')
SONG = ROOT / 'assets/zuixuan-official-instrumental.mp3'
OUT = ROOT / 'assets/song-analysis.json'
SR = 22050
HOP = 512


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--song', type=Path, default=SONG)
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    y, sr = librosa.load(args.song, sr=SR, mono=True)
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, frames = librosa.beat.beat_track(
        onset_envelope=onset, sr=sr, hop_length=HOP, units='frames'
    )
    times = librosa.frames_to_time(frames, sr=sr, hop_length=HOP)
    indices = np.arange(len(times), dtype=np.float64)
    slope, intercept = np.polyfit(indices, times, 1)
    bpm = 60.0 / slope

    # Refine a fixed beat grid against the measured onset envelope. The search
    # is local to the tracker's estimate and does not assume a nominal BPM.
    best = None
    for candidate_bpm in np.linspace(bpm - 0.30, bpm + 0.30, 121):
        period = 60.0 / candidate_bpm
        for phase in np.linspace(intercept - period / 2, intercept + period / 2, 160):
            grid = np.arange(phase, len(y) / sr, period)
            positions = np.rint(grid * sr / HOP).astype(int)
            valid = (positions >= 1) & (positions < len(onset) - 1)
            positions = positions[valid]
            local = onset[np.column_stack((positions - 1, positions, positions + 1))]
            score = float(np.sum(np.max(local, axis=1))) if len(positions) else 0.0
            score /= max(1, len(positions))
            if best is None or score > best['score']:
                best = {'bpm': float(candidate_bpm), 'phase': float(phase % period), 'score': score}

    duration = len(y) / sr
    result = {
        'source': str(args.song),
        'sampleRate': sr,
        'hopLength': HOP,
        'duration': duration,
        'trackerBpm': float(np.asarray(tempo).reshape(-1)[0]),
        'regressionBpm': float(bpm),
        'gridBpm': best['bpm'],
        'beatSeconds': 60.0 / best['bpm'],
        'barSeconds': 240.0 / best['bpm'],
        'phaseSeconds': best['phase'],
        'gridScore': best['score'],
        'trackedBeatCount': len(times),
        'firstTrackedBeats': [round(float(x), 6) for x in times[:32]],
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
