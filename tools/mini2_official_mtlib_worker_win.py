#!/usr/bin/env python3
"""Windows worker for official HIKMICRO Mini2 raw->Celsius conversion.

Run this with Windows Python, because MTlib_OL.dll is a Windows DLL.  WSL/Linux
code can spawn this worker through Windows interop (for example ``py.exe -3``)
and stream each 256x192 raw frame plus its 1024-byte addline block through the
binary protocol implemented in ``auto_titrator.official_hikmicro``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.official_hikmicro import (  # noqa: E402
    DLL_DIR_DEFAULT,
    OfficialMtlibConverter,
    worker_loop,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Official HIKMICRO MTlib worker for Mini2 live frames")
    parser.add_argument("--metadata-jpeg", required=True, help="Mini2 radiometric JPEG used for official calibration/config")
    parser.add_argument("--dll-dir", default=str(DLL_DIR_DEFAULT), help="Folder containing MTlib_OL.dll")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="requested MT_Process point batch size; Mini2 INT path is forced to 1 internally for correctness",
    )
    args = parser.parse_args(argv)

    converter = OfficialMtlibConverter.from_jpeg(
        args.metadata_jpeg,
        dll_dir=args.dll_dir,
        batch_size=args.batch_size,
    )
    try:
        worker_loop(converter, sys.stdin.buffer, sys.stdout.buffer)
    finally:
        converter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
