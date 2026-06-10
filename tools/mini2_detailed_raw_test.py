"""Detailed Mini2 UVC raw-frame evidence collector.

This tool is deliberately conservative: it extracts and reports raw evidence
from the 256x344 UVC frame, but it does not claim calibrated Celsius values.

Outputs answer these questions:
- Is the top 256x192 matrix stable across frames?
- Where are exact min/max pixels?
- Which lower-frame u16 values are close to matrix min/max, and by exactly how
  much?
- Which watched metadata/header positions change across frames?
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np


WIDTH = 256
HEIGHT = 344
MATRIX_HEIGHT = 192
FRAME_BYTES = WIDTH * HEIGHT * 2
INPUT_FORMAT = "yuyv422"
WATCHED_ROWS = {192, 193, 340}
WATCHED_POINTS = {
    "row192_col0": (192, 0),
    "row192_col1": (192, 1),
    "row192_col20": (192, 20),
    "row192_col21": (192, 21),
    "row193_col0": (193, 0),
    "row193_col1": (193, 1),
    "row193_col2": (193, 2),
    "row193_col4": (193, 4),
    "row193_col6": (193, 6),
    "row193_col28": (193, 28),
    "row340_col14": (340, 14),
    "row340_col15": (340, 15),
    "row340_col16": (340, 16),
}


@dataclass
class FrameReport:
    frame_id: int
    matrix: np.ndarray
    summary: dict[str, Any]
    candidates: list[dict[str, Any]]


def validate_frame_bytes(raw_bytes: bytes) -> None:
    if len(raw_bytes) != FRAME_BYTES:
        raise ValueError(f"expected {FRAME_BYTES} bytes for 256x344 uint16/YUYV raw frame, got {len(raw_bytes)}")


def split_raw_sequence(raw_bytes: bytes) -> list[bytes]:
    if not raw_bytes:
        raise ValueError("raw sequence is empty")
    if len(raw_bytes) % FRAME_BYTES != 0:
        raise ValueError(f"raw sequence size {len(raw_bytes)} is not a multiple of frame size {FRAME_BYTES}")
    return [raw_bytes[i : i + FRAME_BYTES] for i in range(0, len(raw_bytes), FRAME_BYTES)]


def yx_text(position: tuple[int, int]) -> str:
    return f"{int(position[0])},{int(position[1])}"


def percentile(values: np.ndarray, pct: float) -> float:
    return round(float(np.percentile(values, pct)), 6)


def candidate_flags(value: int, matrix_min: int, matrix_max: int, row: int, col: int, threshold: int) -> list[str]:
    flags: list[str] = []
    if abs(value - matrix_min) <= threshold:
        flags.append("within_threshold_of_matrix_min")
    if abs(value - matrix_max) <= threshold:
        flags.append("within_threshold_of_matrix_max")
    if row in WATCHED_ROWS and value != 0:
        flags.append("watched_metadata_row_nonzero")
    if value in {WIDTH, HEIGHT, MATRIX_HEIGHT}:
        flags.append("dimension_like")
    if 0 <= value <= 8000 and row in WATCHED_ROWS and value != 0:
        flags.append("centicelsius_plausible_if_div100_but_unproven")
    return flags


def scan_metadata_candidates(full_frame: np.ndarray, matrix_min: int, matrix_max: int, threshold: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    bottom = full_frame[MATRIX_HEIGHT:, :]
    for local_row, row_values in enumerate(bottom):
        row = local_row + MATRIX_HEIGHT
        for col, raw_value in enumerate(row_values):
            value = int(raw_value)
            flags = candidate_flags(value, matrix_min, matrix_max, row, col, threshold)
            if not flags:
                continue
            candidates.append(
                {
                    "row": row,
                    "col": col,
                    "byte_offset": row * WIDTH * 2 + col * 2,
                    "u16_value": value,
                    "delta_from_matrix_min": value - matrix_min,
                    "delta_from_matrix_max": value - matrix_max,
                    "value_div_100": round(value / 100.0, 4),
                    "candidate_flags": "|".join(flags),
                }
            )
    return candidates


def analyze_frame(raw_bytes: bytes, *, frame_id: int, threshold: int = 8) -> FrameReport:
    validate_frame_bytes(raw_bytes)
    full_frame = np.frombuffer(raw_bytes, dtype="<u2").reshape(HEIGHT, WIDTH)
    matrix = full_frame[:MATRIX_HEIGHT, :].copy()
    matrix_float = matrix.astype("float64")

    matrix_min = int(matrix.min())
    matrix_max = int(matrix.max())
    min_pos = tuple(int(v) for v in np.argwhere(matrix == matrix_min)[0])
    max_pos = tuple(int(v) for v in np.argwhere(matrix == matrix_max)[0])

    summary: dict[str, Any] = {
        "frame_id": frame_id,
        "matrix_shape": f"{matrix.shape[0]}x{matrix.shape[1]}",
        "matrix_min": matrix_min,
        "matrix_max": matrix_max,
        "matrix_mean": round(float(matrix_float.mean()), 6),
        "matrix_std": round(float(matrix_float.std()), 6),
        "matrix_p01": percentile(matrix, 1),
        "matrix_p05": percentile(matrix, 5),
        "matrix_p50": percentile(matrix, 50),
        "matrix_p95": percentile(matrix, 95),
        "matrix_p99": percentile(matrix, 99),
        "matrix_min_yx": yx_text(min_pos),
        "matrix_max_yx": yx_text(max_pos),
        "calibrated_celsius": False,
        "note": "raw matrix candidate only; no Celsius formula claimed",
    }

    for name, (row, col) in WATCHED_POINTS.items():
        summary[name] = int(full_frame[row, col])

    candidates = scan_metadata_candidates(full_frame, matrix_min, matrix_max, threshold)
    summary["metadata_candidate_count"] = len(candidates)
    return FrameReport(frame_id=frame_id, matrix=matrix, summary=summary, candidates=candidates)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_matrix_preview(matrix: np.ndarray, path: Path) -> bool:
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


def process_raw_sequence(raw_path: Path, output_dir: Path, *, threshold: int = 8) -> dict[str, Any]:
    frames = split_raw_sequence(raw_path.read_bytes())
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for frame_id, frame_bytes in enumerate(frames):
        report = analyze_frame(frame_bytes, frame_id=frame_id, threshold=threshold)
        np.save(output_dir / f"matrix_frame_{frame_id:03d}.npy", report.matrix)
        if frame_id < 5:
            write_matrix_preview(report.matrix, output_dir / f"matrix_preview_{frame_id:03d}.png")
        summary_rows.append(report.summary)
        for candidate in report.candidates:
            candidate_rows.append({"frame_id": frame_id, **candidate})

    summary_fields = list(summary_rows[0].keys()) if summary_rows else []
    candidate_fields = [
        "frame_id",
        "row",
        "col",
        "byte_offset",
        "u16_value",
        "delta_from_matrix_min",
        "delta_from_matrix_max",
        "value_div_100",
        "candidate_flags",
    ]
    write_csv(output_dir / "frame_summary.csv", summary_rows, summary_fields)
    write_csv(output_dir / "metadata_candidate_scan.csv", candidate_rows, candidate_fields)

    matrix_mins = [int(row["matrix_min"]) for row in summary_rows]
    matrix_maxs = [int(row["matrix_max"]) for row in summary_rows]
    matrix_means = [float(row["matrix_mean"]) for row in summary_rows]
    run_summary = {
        "source_file": str(raw_path),
        "frame_count": len(frames),
        "frame_bytes": FRAME_BYTES,
        "matrix_shape": f"{MATRIX_HEIGHT}x{WIDTH}",
        "threshold": threshold,
        "calibrated_celsius": False,
        "matrix_min_range": [min(matrix_mins), max(matrix_mins)] if matrix_mins else [],
        "matrix_max_range": [min(matrix_maxs), max(matrix_maxs)] if matrix_maxs else [],
        "matrix_mean_range": [min(matrix_means), max(matrix_means)] if matrix_means else [],
        "candidate_rows": len(candidate_rows),
        "outputs": {
            "frame_summary_csv": str(output_dir / "frame_summary.csv"),
            "metadata_candidate_scan_csv": str(output_dir / "metadata_candidate_scan.csv"),
            "matrix_npy_pattern": str(output_dir / "matrix_frame_###.npy"),
            "preview_png_pattern": str(output_dir / "matrix_preview_###.png"),
        },
    }
    (output_dir / "run_summary.json").write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output_dir, run_summary)
    return run_summary


def write_readme(output_dir: Path, run_summary: dict[str, Any]) -> None:
    text = f"""Mini2 detailed raw test

calibrated Celsius: NO
status: candidate only

What this run contains:
- frame_summary.csv: exact raw matrix statistics for each frame.
- metadata_candidate_scan.csv: lower-frame u16 values that match explicit scan rules.
- matrix_frame_###.npy: extracted top 256x192 uint16 matrix for each frame.
- matrix_preview_###.png: contrast preview for the first frames only.

Important interpretation rule:
- Do not call any metadata value a temperature unless it is verified against an external
  reference such as the official app's displayed min/max/center temperature.
- Candidate flags mean only that a number met a scan rule.
- Exact deltas are recorded in metadata_candidate_scan.csv. Use those deltas, not vague wording.

Run facts:
- frame_count: {run_summary['frame_count']}
- matrix_shape: {run_summary['matrix_shape']}
- matrix_min_range: {run_summary['matrix_min_range']}
- matrix_max_range: {run_summary['matrix_max_range']}
- matrix_mean_range: {run_summary['matrix_mean_range']}
"""
    (output_dir / "READ_ME_FIRST.txt").write_text(text, encoding="utf-8")


def capture_one_frame(device: str, output_path: Path, *, timeout_s: float = 12.0) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        INPUT_FORMAT,
        "-video_size",
        f"{WIDTH}x{HEIGHT}",
        "-i",
        device,
        "-frames:v",
        "1",
        "-f",
        "rawvideo",
        "-y",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg capture failed: {(result.stdout or '') + (result.stderr or '')}".strip())
    if not output_path.exists() or output_path.stat().st_size != FRAME_BYTES:
        got = output_path.stat().st_size if output_path.exists() else 0
        raise RuntimeError(f"capture size mismatch: expected {FRAME_BYTES} bytes, got {got}")


def split_sequence_to_frame_files(sequence_path: Path, raw_dir: Path) -> int:
    raw_bytes = sequence_path.read_bytes()
    frames = split_raw_sequence(raw_bytes)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for frame_id, frame_bytes in enumerate(frames):
        (raw_dir / f"frame_{frame_id:03d}.raw").write_bytes(frame_bytes)
    return len(frames)


def capture_sequence(device: str, output_dir: Path, *, frame_count: int, delay_s: float) -> Path:
    raw_dir = output_dir / "raw_frames"
    raw_dir.mkdir(parents=True, exist_ok=True)
    sequence_path = output_dir / "mini2_detailed_sequence.raw"
    fps = max(1.0 / delay_s, 0.1) if delay_s > 0 else 25.0
    print(f"Capturing {frame_count} frames in one ffmpeg session -> {sequence_path}")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        INPUT_FORMAT,
        "-video_size",
        f"{WIDTH}x{HEIGHT}",
        "-i",
        device,
        "-vf",
        f"fps={fps:.6g}",
        "-frames:v",
        str(frame_count),
        "-f",
        "rawvideo",
        "-y",
        str(sequence_path),
    ]
    timeout_s = max(15.0, frame_count * max(delay_s, 0.1) + 15.0)
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg sequence capture failed: {(result.stdout or '') + (result.stderr or '')}".strip())
    expected_size = FRAME_BYTES * frame_count
    if not sequence_path.exists() or sequence_path.stat().st_size != expected_size:
        got = sequence_path.stat().st_size if sequence_path.exists() else 0
        if got > 0 and got % FRAME_BYTES == 0:
            actual_frames = got // FRAME_BYTES
            print(f"Warning: expected {frame_count} frames, captured {actual_frames}; continuing with captured frames.")
        else:
            raise RuntimeError(f"sequence capture size mismatch: expected {expected_size} bytes, got {got}")
    split_count = split_sequence_to_frame_files(sequence_path, raw_dir)
    print(f"Saved split raw frames: {split_count} files in {raw_dir}")
    return sequence_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Detailed Mini2 raw-frame test without Celsius claims.")
    parser.add_argument("--raw-file", default="", help="Existing raw sequence. If omitted, frames are captured from V4L2.")
    parser.add_argument("--capture-device", default="/dev/video0")
    parser.add_argument("--frame-count", type=int, default=10)
    parser.add_argument("--delay-s", type=float, default=0.5)
    parser.add_argument("--threshold", type=int, default=8)
    parser.add_argument("--output-dir", default=f"data/mini2_detailed_raw_test/{datetime.now():%Y%m%d-%H%M%S}")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if args.raw_file:
        raw_path = Path(args.raw_file)
    else:
        raw_path = capture_sequence(args.capture_device, output_dir, frame_count=args.frame_count, delay_s=args.delay_s)

    run_summary = process_raw_sequence(raw_path, output_dir, threshold=args.threshold)
    print("Mini2 detailed raw test complete.")
    print(f"  calibrated Celsius: NO")
    print(f"  frames: {run_summary['frame_count']}")
    print(f"  output: {output_dir}")
    print(f"  summary: {output_dir / 'frame_summary.csv'}")
    print(f"  candidates: {output_dir / 'metadata_candidate_scan.csv'}")
    print(f"  read first: {output_dir / 'READ_ME_FIRST.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
