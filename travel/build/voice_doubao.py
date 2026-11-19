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
import sys
import urllib.request
import uuid

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--env-file", default=os.path.expanduser("~/.volc_local/cred.env"))
    parser.add_argument("--format", default="mp3")
    parser.add_argument("--sample-rate", type=int, default=24000)
    parser.add_argument("--speech-rate", type=int, default=0)
    parser.add_argument("--uid", default="codecut-local")
    args = parser.parse_args()

    env = {**load_env_file(args.env_file), **os.environ}
    api_key = env.get("VOLC_API_KEY")
    speaker = env.get("VOLC_SPEAKER")
    if not api_key or not speaker:
        raise SystemExit("VOLC_API_KEY and VOLC_SPEAKER are required (env or --env-file)")

    audio = synthesize(
        args.text,
        speaker,
        api_key,
        env.get("VOLC_RESOURCE_ID", "seed-icl-2.0"),
        args.format,
        args.sample_rate,
        args.speech_rate,
        args.uid,
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as handle:
        handle.write(audio)
    print(f"wrote {args.out} ({len(audio)} bytes)")


if __name__ == "__main__":
    main()
