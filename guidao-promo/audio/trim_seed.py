#!/usr/bin/env python3
"""Trim silence and normalize the Seed TTS narration clips."""
import json
import os
import wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, 'audio', 'vo_seed')

meta = []
for i in range(1, 12):
    path = os.path.join(DIR, f'line_{i:02d}.wav')
    with wave.open(path, 'rb') as f:
        sr = f.getframerate()
        raw = f.readframes(f.getnframes())
    y = np.frombuffer(raw, dtype='<i2').astype(np.float32) / 32768.0
    idx = np.where(np.abs(y) > 0.012)[0]
    if len(idx):
        y = y[max(0, idx[0] - int(0.06 * sr)): min(len(y), idx[-1] + int(0.14 * sr))]
    peak = np.max(np.abs(y))
    if peak > 0:
        y = y / peak * 0.92
    n = min(int(0.015 * sr), len(y) // 2)
    if n > 0:
        y[:n] *= np.linspace(0, 1, n)
        y[-n:] *= np.linspace(1, 0, n)
    with wave.open(path, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sr)
        f.writeframes((np.clip(y, -1, 1) * 32767).astype('<i2').tobytes())
    dur = len(y) / sr
    meta.append({'index': i, 'duration': round(dur, 3), 'file': os.path.relpath(path, ROOT)})
    print(f'{i:02d}  {dur:5.2f}s')
print('total', round(sum(m['duration'] for m in meta), 2))
