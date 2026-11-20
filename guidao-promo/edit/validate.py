#!/usr/bin/env python3
"""Technical and content validation for the guidao promo."""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MP4 = os.path.join(ROOT, 'out', 'guidao_promo_1080p.mp4')
SRT = os.path.join(ROOT, 'out', 'guidao_promo.srt')

ok = True


def check(name, cond, detail=''):
    global ok
    print(('PASS  ' if cond else 'FAIL  ') + name + (('  ' + detail) if detail else ''))
    if not cond:
        ok = False


def probe():
    out = subprocess.check_output([
        'ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', MP4
    ], text=True)
    return json.loads(out)


def loudness():
    p = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', MP4, '-af', 'ebur128=peak=true', '-f', 'null', '-'],
        capture_output=True, text=True)
    text = p.stderr.split('Summary:')[-1]
    m = re.search(r'Integrated loudness:\s*\n\s*I:\s*(-?\d+\.\d+)\s*LUFS', text)
    tp = re.search(r'True peak:\s*\n\s*Peak:\s*(-?\d+\.\d+)\s*dBFS', text)
    return (float(m.group(1)) if m else None, float(tp.group(1)) if tp else None)


def parse_srt(path):
    with open(path, encoding='utf-8') as f:
        blocks = [b.strip() for b in f.read().split('\n\n') if b.strip()]
    rows = []
    for b in blocks:
        lines = b.split('\n')
        if len(lines) < 3:
            continue
        m = re.match(r'(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)', lines[1])
        if not m:
            continue
        vals = [int(x) for x in m.groups()]
        start = vals[0] * 3600 + vals[1] * 60 + vals[2] + vals[3] / 1000
        end = vals[4] * 3600 + vals[5] * 60 + vals[6] + vals[7] / 1000
        rows.append((start, end, '\n'.join(lines[2:])))
    return rows


def main():
    check('mp4 exists', os.path.exists(MP4), MP4)
    if not os.path.exists(MP4):
        sys.exit(1)
    info = probe()
    v = next(s for s in info['streams'] if s['codec_type'] == 'video')
    a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    dur = float(info['format']['duration'])
    fps = v['r_frame_rate']
    check('resolution 1920x1080', v['width'] == 1920 and v['height'] == 1080, f"{v['width']}x{v['height']}")
    check('fps 30', fps == '30/1', fps)
    check('duration 75-90s', 75 <= dur <= 90, f'{dur:.2f}s')
    check('codec h264', v['codec_name'] == 'h264', v['codec_name'])
    check('pix_fmt yuv420p', v.get('pix_fmt') == 'yuv420p', str(v.get('pix_fmt')))
    check('audio aac 48k stereo', a is not None and a['codec_name'] == 'aac' and int(a['sample_rate']) == 48000 and a['channels'] == 2,
          f"{a['codec_name']} {a['sample_rate']} {a['channels']}ch" if a else 'missing')
    lufs, tp = loudness()
    check('loudness -14 +/- 0.5 LUFS', lufs is not None and abs(lufs + 14) <= 0.5, f'{lufs} LUFS')
    check('true peak <= -1.5 dBFS', tp is not None and tp <= -1.5, f'{tp} dBFS')
    rows = parse_srt(SRT)
    check('srt 11 entries', len(rows) == 11, str(len(rows)))
    check('srt monotonic', all(rows[i][0] < rows[i + 1][0] for i in range(len(rows) - 1)))
    check('srt no overlap', all(rows[i][1] <= rows[i + 1][0] + 0.001 for i in range(len(rows) - 1)))
    print()
    print('RESULT:', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
