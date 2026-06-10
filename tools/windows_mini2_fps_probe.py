#!/usr/bin/env python3
"""Windows-native camera FPS probe for HIKMICRO Mini2 UVC modes.

Run with Windows Python, not WSL Python:

    py -3 windows_mini2_fps_probe.py

The script is intentionally standalone.  It does not import this repository's
modules, because the goal is only to determine whether Windows can capture the
Mini2 faster than the WSL usbipd/V4L2 path.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from queue import Empty
from typing import Any


BACKENDS = {
    "ANY": 0,
    "DSHOW": 700,
    "MSMF": 1400,
}

MODES: list[dict[str, Any]] = [
    {"name": "default", "width": 0, "height": 0, "fourcc": "", "fps": 0, "convert_rgb": None},
    {"name": "yuy2_256x344_25", "width": 256, "height": 344, "fourcc": "YUY2", "fps": 25, "convert_rgb": None},
    {"name": "yuy2_raw_256x344_25", "width": 256, "height": 344, "fourcc": "YUY2", "fps": 25, "convert_rgb": 0},
    {"name": "yuy2_256x196_25", "width": 256, "height": 196, "fourcc": "YUY2", "fps": 25, "convert_rgb": None},
    {"name": "yuy2_raw_256x196_25", "width": 256, "height": 196, "fourcc": "YUY2", "fps": 25, "convert_rgb": 0},
    {"name": "nv12_256x192_25", "width": 256, "height": 192, "fourcc": "NV12", "fps": 25, "convert_rgb": None},
    {"name": "nv12_raw_256x192_25", "width": 256, "height": 192, "fourcc": "NV12", "fps": 25, "convert_rgb": 0},
]


def fourcc_to_str(value: float) -> str:
    try:
        ivalue = int(value)
        chars = [chr((ivalue >> (8 * i)) & 0xFF) for i in range(4)]
        return "".join(c if 32 <= ord(c) < 127 else "." for c in chars)
    except Exception:
        return ""


def worker(
    index: int,
    backend_name: str,
    backend_value: int,
    mode: dict[str, Any],
    frames: int,
    warmup: int,
    output_dir: str,
    queue: mp.Queue,
) -> None:
    import cv2  # imported in child so parent can report missing dependency cleanly
    import numpy as np

    started = time.perf_counter()
    cap = cv2.VideoCapture(index, backend_value) if backend_name != "ANY" else cv2.VideoCapture(index)
    result: dict[str, Any] = {
        "index": index,
        "backend": backend_name,
        "mode": mode["name"],
        "opened": bool(cap.isOpened()),
        "read_ok": False,
        "frames_requested": frames,
        "frames_read": 0,
        "elapsed_s": 0.0,
        "measured_fps": 0.0,
        "shape": "",
        "dtype": "",
        "mean": "",
        "std": "",
        "probably_blank": "",
        "requested_width": mode["width"],
        "requested_height": mode["height"],
        "requested_fourcc": mode["fourcc"],
        "requested_fps": mode["fps"],
        "prop_width": "",
        "prop_height": "",
        "prop_fps": "",
        "prop_fourcc": "",
        "snapshot": "",
        "error": "",
    }
    try:
        if not cap.isOpened():
            queue.put(result)
            return
        if mode["fourcc"]:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*mode["fourcc"]))
        if mode["width"]:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(mode["width"]))
        if mode["height"]:
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(mode["height"]))
        if mode["fps"]:
            cap.set(cv2.CAP_PROP_FPS, float(mode["fps"]))
        if mode["convert_rgb"] is not None:
            cap.set(cv2.CAP_PROP_CONVERT_RGB, int(mode["convert_rgb"]))

        result["prop_width"] = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        result["prop_height"] = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        result["prop_fps"] = cap.get(cv2.CAP_PROP_FPS)
        result["prop_fourcc"] = fourcc_to_str(cap.get(cv2.CAP_PROP_FOURCC))

        first = None
        for _ in range(max(0, warmup)):
            ok, frame = cap.read()
            if ok and frame is not None:
                first = frame
        read_count = 0
        t0 = time.perf_counter()
        for _ in range(frames):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            if first is None:
                first = frame
            read_count += 1
        elapsed = time.perf_counter() - t0
        result["frames_read"] = read_count
        result["elapsed_s"] = elapsed
        result["measured_fps"] = (read_count / elapsed) if elapsed > 0 else 0.0
        result["read_ok"] = read_count > 0
        if first is not None:
            arr = np.asarray(first)
            result["shape"] = "x".join(str(v) for v in arr.shape)
            result["dtype"] = str(arr.dtype)
            mean = float(np.mean(arr))
            std = float(np.std(arr))
            result["mean"] = mean
            result["std"] = std
            result["probably_blank"] = bool(mean < 1.0 or std < 1.0)
            snap = Path(output_dir) / f"snapshot_index{index}_{backend_name}_{mode['name']}.png"
            try:
                cv2.imwrite(str(snap), first)
                result["snapshot"] = str(snap)
            except Exception as exc:
                result["snapshot"] = f"save_failed:{type(exc).__name__}:{exc}"
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["total_child_s"] = time.perf_counter() - started
        cap.release()
        queue.put(result)


def run_attempt(args: tuple[int, str, int, dict[str, Any], int, int, str, float]) -> dict[str, Any]:
    index, backend_name, backend_value, mode, frames, warmup, output_dir, timeout_s = args
    queue: mp.Queue = mp.Queue()
    proc = mp.Process(
        target=worker,
        args=(index, backend_name, backend_value, mode, frames, warmup, output_dir, queue),
    )
    proc.start()
    proc.join(timeout_s)
    if proc.is_alive():
        proc.terminate()
        proc.join(2.0)
        return {
            "index": index,
            "backend": backend_name,
            "mode": mode["name"],
            "opened": "",
            "read_ok": False,
            "frames_requested": frames,
            "frames_read": 0,
            "elapsed_s": "",
            "measured_fps": 0.0,
            "shape": "",
            "dtype": "",
            "mean": "",
            "std": "",
            "probably_blank": "",
            "requested_width": mode["width"],
            "requested_height": mode["height"],
            "requested_fourcc": mode["fourcc"],
            "requested_fps": mode["fps"],
            "prop_width": "",
            "prop_height": "",
            "prop_fps": "",
            "prop_fourcc": "",
            "snapshot": "",
            "error": f"timeout after {timeout_s}s",
        }
    try:
        return queue.get_nowait()
    except Empty:
        return {
            "index": index,
            "backend": backend_name,
            "mode": mode["name"],
            "opened": "",
            "read_ok": False,
            "frames_requested": frames,
            "frames_read": 0,
            "elapsed_s": "",
            "measured_fps": 0.0,
            "shape": "",
            "dtype": "",
            "mean": "",
            "std": "",
            "probably_blank": "",
            "requested_width": mode["width"],
            "requested_height": mode["height"],
            "requested_fourcc": mode["fourcc"],
            "requested_fps": mode["fps"],
            "prop_width": "",
            "prop_height": "",
            "prop_fps": "",
            "prop_fourcc": "",
            "snapshot": "",
            "error": f"child exited {proc.exitcode} without result",
        }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "index",
        "backend",
        "mode",
        "opened",
        "read_ok",
        "frames_requested",
        "frames_read",
        "elapsed_s",
        "measured_fps",
        "shape",
        "dtype",
        "mean",
        "std",
        "probably_blank",
        "requested_width",
        "requested_height",
        "requested_fourcc",
        "requested_fps",
        "prop_width",
        "prop_height",
        "prop_fps",
        "prop_fourcc",
        "snapshot",
        "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indices", default="0-9", help="camera indices, e.g. 0-5 or 0,1,4")
    parser.add_argument("--frames", type=int, default=75)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--timeout-s", type=float, default=12.0)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)

    try:
        import cv2  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        print(f"OpenCV import failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Install with: py -3 -m pip install opencv-python numpy", file=sys.stderr)
        return 2

    if "-" in args.indices:
        a, b = args.indices.split("-", 1)
        indices = list(range(int(a), int(b) + 1))
    else:
        indices = [int(x.strip()) for x in args.indices.split(",") if x.strip()]

    out_dir = Path(args.output_dir) if args.output_dir else Path("windows_mini2_fps_probe") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)

    attempts = [
        (index, backend_name, backend_value, mode, args.frames, args.warmup, str(out_dir), args.timeout_s)
        for index in indices
        for backend_name, backend_value in BACKENDS.items()
        for mode in MODES
    ]

    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        index, backend_name, _backend_value, mode, *_rest = attempt
        print(f"probe index={index} backend={backend_name} mode={mode['name']}", flush=True)
        row = run_attempt(attempt)
        rows.append(row)
        if row.get("read_ok"):
            print(
                "  OK "
                f"fps={float(row.get('measured_fps') or 0):.3f} "
                f"shape={row.get('shape')} "
                f"prop={row.get('prop_width')}x{row.get('prop_height')} "
                f"fourcc={row.get('prop_fourcc')} "
                f"blank={row.get('probably_blank')}",
                flush=True,
            )
        elif row.get("opened"):
            print(f"  opened but no frames: {row.get('error')}", flush=True)
        elif row.get("error"):
            print(f"  fail: {row.get('error')}", flush=True)

    csv_path = out_dir / "windows_mini2_fps_probe.csv"
    write_csv(csv_path, rows)
    readable = [r for r in rows if r.get("read_ok")]
    best = sorted(readable, key=lambda r: float(r.get("measured_fps") or 0), reverse=True)[:10]
    summary = {
        "output_dir": str(out_dir),
        "csv": str(csv_path),
        "attempts": len(rows),
        "readable_attempts": len(readable),
        "best": best,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", csv_path)
    print("BEST")
    print(json.dumps(best, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
