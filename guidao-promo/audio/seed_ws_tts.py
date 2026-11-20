#!/usr/bin/env python3
"""Synthesize speech with the Volcengine bidirectional streaming TTS WebSocket API.

Protocol: wss://openspeech.bytedance.com/api/v3/tts/bidirection
The API key is read from VOLC_API_KEY and is never written to the repo.
"""
import argparse
import asyncio
import json
import os
import struct
import uuid

import websockets

URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"

# message types
FULL_CLIENT = 0b0001
FULL_SERVER = 0b1001
AUDIO_SERVER = 0b1011
ERROR = 0b1111
WITH_EVENT = 0b0100

# events
START_CONNECTION = 1
FINISH_CONNECTION = 2
CONNECTION_STARTED = 50
CONNECTION_FAILED = 51
CONNECTION_FINISHED = 52
START_SESSION = 100
FINISH_SESSION = 102
SESSION_STARTED = 150
SESSION_FINISHED = 152
SESSION_FAILED = 153
TASK_REQUEST = 200


def pack(msg_type, event, payload=b"", session_id=""):
    header = bytes([0x11, (msg_type << 4) | WITH_EVENT, 0x10, 0x00])
    body = struct.pack(">i", event)
    if event not in (START_CONNECTION, FINISH_CONNECTION):
        sid = session_id.encode()
        body += struct.pack(">I", len(sid)) + sid
    body += struct.pack(">I", len(payload)) + payload
    return header + body


def unpack(data):
    msg_type = data[1] >> 4
    flag = data[1] & 0x0F
    pos = 4
    event = None
    session_id = ""
    error_code = None
    if flag == WITH_EVENT:
        event = struct.unpack(">i", data[pos:pos + 4])[0]
        pos += 4
        if event not in (START_CONNECTION, FINISH_CONNECTION,
                         CONNECTION_STARTED, CONNECTION_FAILED, CONNECTION_FINISHED):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            pos += 4
            session_id = data[pos:pos + size].decode("utf-8", "ignore")
            pos += size
        if event in (CONNECTION_STARTED, CONNECTION_FAILED, CONNECTION_FINISHED):
            size = struct.unpack(">I", data[pos:pos + 4])[0]
            pos += 4 + size
    if msg_type == ERROR:
        error_code = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
    size = struct.unpack(">I", data[pos:pos + 4])[0]
    pos += 4
    payload = data[pos:pos + size]
    return msg_type, event, session_id, error_code, payload


async def wait_event(ws, wanted):
    while True:
        raw = await ws.recv()
        msg_type, event, session_id, error_code, payload = unpack(raw)
        if msg_type == ERROR:
            raise SystemExit(f"WebSocket error {error_code}: {payload.decode('utf-8', 'ignore')[:600]}")
        if event == wanted:
            return payload
        if event in (CONNECTION_FAILED, SESSION_FAILED):
            raise SystemExit(f"event {event}: {payload.decode('utf-8', 'ignore')[:600]}")


async def synthesize(text, speaker, resource, out_path, sample_rate=24000):
    key = os.environ.get("VOLC_API_KEY")
    if not key:
        raise SystemExit("VOLC_API_KEY is not set")
    headers = {
        "X-Api-Key": key,
        "X-Api-Resource-Id": resource,
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    req = {
        "speaker": speaker,
        "audio_params": {"format": "mp3", "sample_rate": sample_rate},
        "text": text,
    }
    session_id = str(uuid.uuid4())
    audio = bytearray()

    async with websockets.connect(URL, additional_headers=headers,
                                  max_size=10 * 1024 * 1024, open_timeout=30) as ws:
        await ws.send(pack(FULL_CLIENT, START_CONNECTION, b"{}"))
        await wait_event(ws, CONNECTION_STARTED)

        start = {"req_params": {"speaker": speaker,
                                "audio_params": {"format": "mp3", "sample_rate": sample_rate}},
                 "event": START_SESSION}
        await ws.send(pack(FULL_CLIENT, START_SESSION, json.dumps(start).encode(), session_id))
        await wait_event(ws, SESSION_STARTED)

        task = {"req_params": req, "event": TASK_REQUEST}
        await ws.send(pack(FULL_CLIENT, TASK_REQUEST, json.dumps(task).encode(), session_id))
        await ws.send(pack(FULL_CLIENT, FINISH_SESSION, b'{"event":102}', session_id))

        while True:
            raw = await ws.recv()
            msg_type, event, sid, error_code, payload = unpack(raw)
            if msg_type == ERROR:
                raise SystemExit(f"WebSocket error {error_code}: {payload.decode('utf-8', 'ignore')[:600]}")
            if msg_type == AUDIO_SERVER:
                audio.extend(payload)
            if event == SESSION_FINISHED:
                break
            if event in (SESSION_FAILED, CONNECTION_FAILED):
                raise SystemExit(f"event {event}: {payload.decode('utf-8', 'ignore')[:600]}")

        await ws.send(pack(FULL_CLIENT, FINISH_CONNECTION, b"{}"))
        try:
            await asyncio.wait_for(wait_event(ws, CONNECTION_FINISHED), timeout=5)
        except Exception:
            pass

    if not audio:
        raise SystemExit("No audio returned")
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(audio)
    return len(audio)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--speaker", required=True)
    ap.add_argument("--resource", default="seed-tts-2.0")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    n = asyncio.run(synthesize(args.text, args.speaker, args.resource, args.out))
    print(f"{args.out}: {n} bytes")


if __name__ == "__main__":
    main()
