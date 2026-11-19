#!/usr/bin/env python3
"""Synthesize narration with a Doubao cloned voice (Seed ICL 2.0, cloud TTS).

Credentials are read from the environment or an env file:
  VOLC_API_KEY      console API key (X-Api-Key)
  VOLC_SPEAKER      cloned speaker id
  VOLC_RESOURCE_ID  defaults to seed-icl-2.0
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid
import wave

API = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


def load_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def synthesize(text, speaker, api_key, resource_id, fmt, sample_rate, speech_rate, uid):
    payload = {
        "user": {"uid": uid},
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {
                "format": fmt,
                "sample_rate": sample_rate,
                "speech_rate": speech_rate,
            },
        },
    }
    request = urllib.request.Request(
        API,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
    )
    chunks = []
    with urllib.request.urlopen(request, timeout=180) as response:
        body = response.read().decode("utf-8")
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            message = json.loads(body)
        code = message.get("code", 0)
        if code != 0:
            raise SystemExit(f"TTS failed: code={code} message={message.get('message', '')}")
        data = message.get("data")
        if data:
            chunks.append(base64.b64decode(data))
        if message.get("data") is None and "code" in message:
            break
    if not chunks:
        raise SystemExit("TTS returned no audio data")
    return b"".join(chunks)


def split_segments(text):
    parts = re.split(r"(?<=[。！？!?：:])|\n+", text)
    return [part.strip() for part in parts if part.strip()]


def decode_to_wav(audio, path, sample_rate, fmt):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise SystemExit("ffmpeg is required for gap synthesis")
    source = f"{path}.{fmt}"
    with open(source, "wb") as handle:
        handle.write(audio)
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", source, "-ar", str(sample_rate), "-ac", "1", "-c:a", "pcm_s16le", path],
        check=True,
    )
    os.remove(source)


def join_with_gaps(wav_paths, gap, sample_rate, out, fmt):
    frames = []
    for index, path in enumerate(wav_paths):
        with wave.open(path, "rb") as handle:
            frames.append(handle.readframes(handle.getnframes()))
        if gap > 0 and index < len(wav_paths) - 1:
            frames.append(b"\x00" * int(sample_rate * 2 * gap))
    combined = os.path.join(tempfile.mkdtemp(prefix="doubao-"), "joined.wav")
    with wave.open(combined, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"".join(frames))
    if fmt == "wav":
        os.replace(combined, out)
        return
    ffmpeg = shutil.which("ffmpeg")
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", combined, "-c:a", "libmp3lame", "-b:a", "128k", out],
        check=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--env-file", default=os.path.expanduser("~/.volc_local/cred.env"))
    parser.add_argument("--format", default="mp3")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument(
        "--speech-rate",
        type=int,
        default=0,
        help="Doubao speech rate; negative values slow the voice down.",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0,
        help="Silence in seconds inserted at every sentence end; enables segmented synthesis.",
    )
    parser.add_argument("--uid", default="codecut-local")
    args = parser.parse_args()

    env = {**load_env_file(args.env_file), **os.environ}
    api_key = env.get("VOLC_API_KEY")
    speaker = env.get("VOLC_SPEAKER")
    if not api_key or not speaker:
        raise SystemExit("VOLC_API_KEY and VOLC_SPEAKER are required (env or --env-file)")

    def render(text):
        return synthesize(
            text,
            speaker,
            api_key,
            env.get("VOLC_RESOURCE_ID", "seed-icl-2.0"),
            args.format,
            args.sample_rate,
            args.speech_rate,
            args.uid,
        )

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    segments = split_segments(args.text) if args.gap > 0 else []
    if len(segments) > 1:
        workdir = tempfile.mkdtemp(prefix="doubao-")
        wav_paths = []
        for index, segment in enumerate(segments):
            wav_path = os.path.join(workdir, f"seg{index:02d}.wav")
            decode_to_wav(render(segment), wav_path, args.sample_rate, args.format)
            wav_paths.append(wav_path)
        join_with_gaps(wav_paths, args.gap, args.sample_rate, args.out, args.format)
        print(f"wrote {args.out} ({len(segments)} segments, gap {args.gap}s)")
        return

    audio = render(args.text)
    with open(args.out, "wb") as handle:
        handle.write(audio)
    print(f"wrote {args.out} ({len(audio)} bytes)")


if __name__ == "__main__":
    main()
