#!/usr/bin/env python3
"""Generate filler clips via the TTS adapter and stage them for adb push to the car.

Workflow (车机连上后):
  1. python3 generate_fillers.py --voice default --out /tmp/filler-stage
  2. adb push /tmp/filler-stage/default /data/local/tmp/openclaw-home/.openclaw/media/filler/

Filler dir layout on device:
  /data/local/tmp/openclaw-home/.openclaw/media/filler/
    default/
      01.ogg 02.ogg ...
    <voice_id>/      # for additional preset voices
      01.ogg 02.ogg ...
"""
import argparse
import base64
import json
import os
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", default="http://172.20.10.2:8091")
    parser.add_argument("--voice", default="default",
                        help="voice id (matches voices.json key)")
    parser.add_argument("--out", required=True,
                        help="local staging directory; files land in <out>/<voice>/")
    parser.add_argument("--format", default="ogg", choices=["ogg", "mp3", "wav"])
    parser.add_argument("--phrases", nargs="*",
                        help="custom phrases; omit to use adapter defaults")
    args = parser.parse_args()

    body = {
        "voice": args.voice,
        "response_format": args.format,
    }
    if args.phrases:
        body["phrases"] = args.phrases

    req = urllib.request.Request(
        f"{args.adapter}/v1/filler/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    print(f"Calling {args.adapter}/v1/filler/generate (voice={args.voice}, format={args.format})...")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            payload = json.loads(resp.read())
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    out_dir = os.path.join(args.out, args.voice)
    os.makedirs(out_dir, exist_ok=True)

    for f in payload["fillers"]:
        path = os.path.join(out_dir, f["filename"])
        with open(path, "wb") as fp:
            fp.write(base64.b64decode(f["audio_b64"]))
        print(f"  wrote {path} ({f['size']} bytes) — '{f['phrase']}'")

    print(f"\nDone. {len(payload['fillers'])} fillers staged at {out_dir}")
    print(f"Next: adb push {out_dir} /data/local/tmp/openclaw-home/.openclaw/media/filler/{args.voice}")


if __name__ == "__main__":
    main()
