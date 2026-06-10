"""Extract the Mini2 UVC raw-matrix candidate from a 256x344 raw frame.

HIKMICRO Mini2 V2 exposes a non-standard UVC frame mode that appears as
``yuyv422 256x344``. The frame is exactly 176128 bytes, which can also be
viewed as a 344x256 little-endian uint16 image. Empirically, the top 192 rows
behave like the 256x192 thermal/raw matrix candidate; the remaining rows carry
metadata/display data.

This script intentionally does not claim calibrated Celsius values. It saves
the raw 256x192 uint16 candidate so later work can derive the temperature
conversion safely.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_WIDTH = 256
DEFAULT_HEIGHT = 344
DEFAULT_MATRIX_HEIGHT = 192
DEFAULT_INPUT_FORMAT = "yuyv422"


def expected_raw_bytes(width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> int:
    return width * height * 2


def extract_raw_matrix_candidate(
    raw_bytes: bytes,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    matrix_height: int = DEFAULT_MATRIX_HEIGHT,
) -> np.ndarray:
    """Return the top 256x192 little-endian uint16 matrix candidate."""

    expected = expected_raw_bytes(width, height)
    if len(raw_bytes) != expected:
        raise ValueError(f"expected {expected} bytes for {width}x{height} uint16 raw frame, got {len(raw_bytes)}")
    if matrix_height <= 0 or matrix_height > height:
        raise ValueError(f"matrix_height must be between 1 and {height}, got {matrix_height}")

    full_frame = np.frombuffer(raw_bytes, dtype="<u2").reshape(height, width)
    return full_frame[:matrix_height, :].copy()


def matrix_summary(matrix: np.ndarray, *, source_width: int, source_height: int, source_path: Path) -> dict[str, Any]:
    values = matrix.astype("float64")
    return {
        "source_file": str(source_path),
        "source_width": source_width,
        "source_height": source_height,
        "matrix_shape": f"{matrix.shape[0]}x{matrix.shape[1]}",
        "matrix_dtype": str(matrix.dtype),
        "matrix_min": int(matrix.min()),
        "matrix_max": int(matrix.max()),
        "matrix_mean": round(float(values.mean()), 6),
        "matrix_std": round(float(values.std()), 6),
        "note": "Raw uint16 matrix candidate only; not calibrated Celsius yet.",
    }


def write_matrix_csv(matrix: np.ndarray, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows([[int(value) for value in row] for row in matrix])


def write_preview_png(matrix: np.ndarray, path: Path) -> bool:
    """Write an 8-bit contrast-stretched preview image when OpenCV is available."""

    try:
        import cv2  # type: ignore[import-not-found]
    except Exception:
        return False

    values = matrix.astype("float32")
    low, high = np.percentile(values, [1, 99])
    if high <= low:
        preview = np.zeros(values.shape, dtype=np.uint8)
    else:
        preview = np.clip((values - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
    return bool(cv2.imwrite(str(path), preview))


def process_raw_file(
    raw_path: Path,
    output_dir: Path,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    matrix_height: int = DEFAULT_MATRIX_HEIGHT,
) -> dict[str, Any]:
    raw_bytes = raw_path.read_bytes()
    matrix = extract_raw_matrix_candidate(raw_bytes, width=width, height=height, matrix_height=matrix_height)

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix_csv_path = output_dir / "mini2_raw_matrix_candidate.csv"
    matrix_npy_path = output_dir / "mini2_raw_matrix_candidate.npy"
    preview_path = output_dir / "mini2_raw_matrix_preview.png"
    summary_path = output_dir / "summary.json"

    write_matrix_csv(matrix, matrix_csv_path)
    np.save(matrix_npy_path, matrix)
    preview_written = write_preview_png(matrix, preview_path)

    summary = matrix_summary(matrix, source_width=width, source_height=height, source_path=raw_path)
    summary.update(
        {
            "matrix_csv": str(matrix_csv_path),
            "matrix_npy": str(matrix_npy_path),
            "preview_png": str(preview_path) if preview_written else "",
        }
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def capture_raw_frame(
    device: str,
    raw_path: Path,
    *,
    input_format: str = DEFAULT_INPUT_FORMAT,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    timeout_s: float = 12.0,
) -> None:
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        input_format,
        "-video_size",
        f"{width}x{height}",
        "-i",
        device,
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-y",
        str(raw_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg raw capture failed: {(result.stdout or '') + (result.stderr or '')}".strip())
    if not raw_path.exists() or raw_path.stat().st_size != expected_raw_bytes(width, height):
        got = raw_path.stat().st_size if raw_path.exists() else 0
        raise RuntimeError(f"raw capture size mismatch: expected {expected_raw_bytes(width, height)} bytes, got {got}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract Mini2 256x192 raw matrix candidate from UVC 256x344 frame.")
    parser.add_argument("--raw-file", default="", help="Existing 256x344 yuyv422/rawvideo frame to analyze.")
    parser.add_argument("--capture-device", default="/dev/video0", help="V4L2 device used when --raw-file is omitted.")
    parser.add_argument("--output-dir", default=f"data/mini2_uvc_matrix_probe/{datetime.now():%Y%m%d-%H%M%S}")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--matrix-height", type=int, default=DEFAULT_MATRIX_HEIGHT)
    parser.add_argument("--input-format", default=DEFAULT_INPUT_FORMAT)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    raw_path = Path(args.raw_file) if args.raw_file else output_dir / f"mini2_{args.input_format}_{args.width}x{args.height}.raw"

    if not args.raw_file:
        print(f"Capturing Mini2 raw frame: {args.capture_device} {args.input_format} {args.width}x{args.height}")
        capture_raw_frame(
            args.capture_device,
            raw_path,
            input_format=args.input_format,
            width=args.width,
            height=args.height,
        )

    summary = process_raw_file(
        raw_path,
        output_dir,
        width=args.width,
        height=args.height,
        matrix_height=args.matrix_height,
    )
    print("Mini2 raw matrix candidate extracted.")
    print(f"  source: {summary['source_file']}")
    print(f"  shape: {summary['matrix_shape']} dtype={summary['matrix_dtype']}")
    print(
        f"  raw stats: min={summary['matrix_min']} max={summary['matrix_max']} "
        f"mean={summary['matrix_mean']} std={summary['matrix_std']}"
    )
    print(f"  csv: {summary['matrix_csv']}")
    print(f"  npy: {summary['matrix_npy']}")
    if summary.get("preview_png"):
        print(f"  preview: {summary['preview_png']}")
    print("  note: raw candidate only, not calibrated Celsius yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
