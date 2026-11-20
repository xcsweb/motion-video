#!/usr/bin/env python3
"""Synthesize speech with the Volcengine Seed TTS HTTP API.

The API key is read from VOLC_API_KEY and is never written to the repo.
"""
import argparse
import base64
import json
import os
import uuid

import requests

URL = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"


def synthesize(text: str, speaker: str, resource: str, out_path: str,
               sample_rate: int = 24000) -> int:
    key = os.environ.get("VOLC_API_KEY")
    if not key:
        raise SystemExit("VOLC_API_KEY is not set")
    headers = {
        "X-Api-Key": key,
        "X-Api-Resource-Id": resource,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    body = {
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {"format": "mp3", "sample_rate": sample_rate},
        }
    }
    audio = bytearray()
    with requests.post(URL, headers=headers, json=body, stream=True, timeout=120) as r:
        if r.status_code != 200:
            raise SystemExit(f"HTTP {r.status_code}: {r.text[:600]}")
        for raw in r.iter_lines():
            if not raw:
                continue
            obj = json.loads(raw)
            code = obj.get("code")
            if code not in (0, 20000000, None):
                raise SystemExit(f"API error {code}: {obj.get('message')}")
            if obj.get("data"):
                audio.extend(base64.b64decode(obj["data"]))
    if not audio:
        raise SystemExit("No audio returned")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(audio)
    return len(audio)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--speaker", default="S_J0yK2jJl2")
    ap.add_argument("--resource", default="seed-icl-2.0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = synthesize(args.text, args.speaker, args.resource, args.out)
    print(f"{args.out}: {n} bytes")


if __name__ == "__main__":
    main()
