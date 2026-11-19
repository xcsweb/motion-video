"""Screen Mixkit candidates against the 8 BGM selection rules."""
import glob
import json

import librosa
import numpy as np

NOTES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
pool = json.load(open('pool.json'))


def key_of(y, sr):
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr).mean(axis=1)
    chroma = (chroma - chroma.mean()) / (chroma.std() + 1e-9)
    best = ('?', -9, '?')
    for root in range(12):
        for mode, prof in (('major', MAJOR), ('minor', MINOR)):
            p = np.roll(prof, root)
            p = (p - p.mean()) / p.std()
            score = float((p * chroma).mean())
            if score > best[1]:
                best = (f'{NOTES[root]} {mode}', score, mode)
    return best


rows = []
for path in sorted(glob.glob('files/*.mp3')):
    mid = path.split('/')[-1].split('.')[0]
    try:
        y, sr = librosa.load(path, sr=22050, mono=True, duration=75)
    except Exception:
        continue
    tempo = float(np.atleast_1d(librosa.beat.beat_track(y=y, sr=sr)[0])[0])
    bpm = tempo
    while bpm > 95:
        bpm /= 2
    key, kscore, mode = key_of(y, sr)
    centroid = float(librosa.feature.spectral_centroid(y=y, sr=sr)[0].mean())
    spec = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    total = spec.sum() + 1e-9
    low = float(spec[freqs < 150].sum() / total)
    high = float(spec[freqs > 4000].sum() / total)
    onset = librosa.onset.onset_detect(y=y, sr=sr)
    rms = librosa.feature.rms(y=y)[0]
    dyn = float(np.percentile(rms, 90) - np.percentile(rms, 10))
    meta = pool.get(mid, {'name': mid, 'genre': '?', 'dur': '?'})
    rows.append({
        'id': int(mid), 'name': meta['name'], 'genre': meta['genre'],
        'bpm': round(bpm, 1), 'key': key, 'mode': mode, 'key_score': round(kscore, 2),
        'bright': round(centroid), 'low': round(low, 2), 'high': round(high, 2),
        'onset_per_s': round(len(onset) / (len(y) / sr), 1), 'dyn': round(dyn, 3),
    })

json.dump(rows, open('features.json', 'w'), ensure_ascii=False, indent=1)
for r in sorted(rows, key=lambda x: x['bright']):
    print(f"{r['id']:4d} {r['bpm']:5.1f} {r['key']:9s} b={r['bright']:4d} low={r['low']:.2f} on={r['onset_per_s']:.1f} dyn={r['dyn']:.2f} {r['genre'][:14]:14s} {r['name']}")
