#!/usr/bin/env python3
"""Extract one APK ZIP entry byte-for-byte and write a SHA-256 manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.apk) as zf:
        info = zf.getinfo(args.entry)
        data = zf.read(info)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(data)
    manifest = {
        "apk": str(args.apk),
        "entry": args.entry,
        "entry_size": len(data),
        "zip_crc32": f"{info.CRC:08x}",
        "sha256": hashlib.sha256(data).hexdigest(),
        "output": str(args.out),
    }
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
