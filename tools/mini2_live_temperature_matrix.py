"""Capture Mini2 25fps raw UVC frames and emit Celsius-matrix ROI/ML features.

Default output is lightweight scalar CSV. Full 256x192 matrices stay in memory;
use --save-matrix-npy-dir only for short debugging runs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.color_analysis import Roi
from auto_titrator.live_app import classify_status
from auto_titrator.feature_history import FeatureSample
from auto_titrator.mini2_live import (
    MINI2_FRAME_RATE_HZ,
    MINI2_INPUT_FORMAT,
    MINI2_UVC_HEIGHT,
    MINI2_UVC_WIDTH,
    Mini2FfmpegRawFrameReader,
    ThermalConversionUnavailable,
    build_temperature_frame,
    extract_temperature_features,
    load_raw_to_celsius_converter,
)


def parse_roi(value: str) -> Roi:
    parts = [int(part.strip()) for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,width,height")
    return Roi(x=parts[0], y=parts[1], width=parts[2], height=parts[3])


def load_converter_args(args: argparse.Namespace):
    if args.official_worker_command:
        return load_raw_to_celsius_converter(
            {
                "type": "official_worker",
                "command": args.official_worker_command,
                "calibration_source": args.official_jpeg or "official_mtlib_worker",
            }
        )
    if args.official_jpeg:
        return load_raw_to_celsius_converter(
            {
                "type": "official_mtlib",
                "metadata_jpeg": args.official_jpeg,
                "dll_dir": args.official_dll_dir,
                "batch_size": args.official_batch_size,
            }
        )
    if args.converter_config:
        config = json.loads(Path(args.converter_config).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("converter config JSON must be an object")
        return load_raw_to_celsius_converter(config)
    if args.affine_json:
        return load_raw_to_celsius_converter({"type": "affine", "path": args.affine_json})
    if args.lookup_csv:
        return load_raw_to_celsius_converter({"type": "lookup", "path": args.lookup_csv, "interpolate": True})
    if args.slope_c_per_raw is not None and args.intercept_c is not None:
        return load_raw_to_celsius_converter(
            {
                "type": "affine",
                "slope_c_per_raw": args.slope_c_per_raw,
                "intercept_c": args.intercept_c,
            }
        )
    raise ThermalConversionUnavailable(
        "No raw->Celsius converter supplied. Use official DLL options "
        "(--official-jpeg on Windows, or --official-worker-command from WSL). "
        "Approximate --affine-json/--lookup-csv options are kept only for old validation tests."
    )


def run(args: argparse.Namespace) -> Path:
    converter = load_converter_args(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    matrix_dir = Path(args.save_matrix_npy_dir) if args.save_matrix_npy_dir else None
    if matrix_dir is not None:
        matrix_dir.mkdir(parents=True, exist_ok=True)

    reader = Mini2FfmpegRawFrameReader(
        device=args.device,
        frame_rate_hz=args.frame_rate_hz,
        input_format=args.input_format,
        width=args.width,
        height=args.height,
    )
    rows: list[dict[str, Any]] = []
    previous_features: dict[str, object] | None = None
    endpoint_seen = False
    start = time.monotonic()
    try:
        with reader:
            for frame_id in range(args.frames):
                raw_matrix, addline_tag1 = read_live_raw_parts(reader)
                elapsed_s = time.monotonic() - start
                frame = build_temperature_frame(
                    raw_matrix=raw_matrix,
                    converter=converter,
                    frame_id=frame_id,
                    addline_tag1=addline_tag1,
                    timestamp_s=elapsed_s,
                    frame_rate_hz=args.frame_rate_hz,
                )
                features = extract_temperature_features(
                    frame.temperature_matrix_c,
                    args.roi,
                    raw_matrix=frame.raw_matrix,
                    previous=previous_features,
                    converter_name=frame.converter_name,
                    calibration_source=frame.calibration_source,
                    frame_rate_hz=frame.frame_rate_hz,
                )
                sample = FeatureSample(
                    time_s=elapsed_s,
                    frame_id=frame_id,
                    injected_volume_ml=0.0,
                    thermal_features=features,
                    source_quality=str(features["source_quality"]),
                )
                label, confidence = classify_status(sample, endpoint_seen=endpoint_seen)
                endpoint_seen = endpoint_seen or label == "endpoint"
                row = sample.to_serializable_row()
                row.update(
                    {
                        "status_label": label,
                        "status_confidence": round(confidence, 6),
                        "temperature_matrix_shape": f"{frame.temperature_matrix_c.shape[0]}x{frame.temperature_matrix_c.shape[1]}",
                    }
                )
                rows.append(row)
                previous_features = features
                if matrix_dir is not None:
                    np.save(matrix_dir / f"mini2_temperature_matrix_{frame_id:05d}.npy", frame.temperature_matrix_c)
                if args.print_every and (frame_id % args.print_every == 0):
                    print(
                        f"frame={frame_id} roi_avg={features['thermal_roi_avg']}C "
                        f"matrix_min={features['thermal_matrix_min']}C "
                        f"matrix_max={features['thermal_matrix_max']}C status={label}",
                        flush=True,
                    )
    finally:
        reader.close()

    fieldnames = sorted({key for row in rows for key in row.keys()})
    preferred = [
        "time_s",
        "frame_id",
        "status_label",
        "status_confidence",
        "thermal_roi_avg",
        "thermal_roi_max",
        "thermal_roi_min",
        "thermal_roi_std",
        "thermal_roi_delta",
        "thermal_matrix_avg",
        "thermal_matrix_max",
        "thermal_matrix_min",
        "thermal_matrix_std",
        "thermal_raw_mean",
        "thermal_raw_min",
        "thermal_raw_max",
        "thermal_conversion_model",
        "thermal_conversion_calibration_source",
        "source_quality",
        "warnings",
    ]
    ordered = [name for name in preferred if name in fieldnames] + [name for name in fieldnames if name not in preferred]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)
    total_elapsed_s = time.monotonic() - start
    summary = {
        "output_csv": str(output),
        "frames": len(rows),
        "elapsed_s": round(total_elapsed_s, 6),
        "measured_loop_fps": round(len(rows) / total_elapsed_s, 6) if rows and total_elapsed_s > 0 else 0.0,
        "target_frame_rate_hz": args.frame_rate_hz,
        "source_frame": f"{args.width}x{args.height} {args.input_format}",
        "temperature_matrix_shape": "192x256",
        "converter": converter.model_name,
        "calibration_source": converter.calibration_source,
        "full_matrix_csv_saved": False,
        "matrix_npy_dir": str(matrix_dir) if matrix_dir is not None else "",
    }
    summary_path = output.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved live Mini2 feature CSV: {output}")
    print(f"saved summary: {summary_path}")
    return output


def read_live_raw_parts(reader: Mini2FfmpegRawFrameReader) -> tuple[np.ndarray, bytes | None]:
    """Read raw pixels and, when supported, Mini2's per-frame addline block."""

    if hasattr(reader, "read_frame_parts"):
        parts = reader.read_frame_parts()
        return parts.raw_matrix, parts.addline_tag1
    return reader.read_raw_matrix(), None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mini2 25fps raw UVC frame -> 256x192 Celsius matrix feature probe")
    parser.add_argument("--device", default="/dev/video0")
    parser.add_argument("--frames", type=int, default=50)
    parser.add_argument("--frame-rate-hz", type=float, default=MINI2_FRAME_RATE_HZ)
    parser.add_argument("--input-format", default=MINI2_INPUT_FORMAT)
    parser.add_argument("--width", type=int, default=MINI2_UVC_WIDTH)
    parser.add_argument("--height", type=int, default=MINI2_UVC_HEIGHT)
    parser.add_argument("--roi", type=parse_roi, default=Roi(96, 72, 64, 48), help="x,y,width,height in 256x192 matrix coordinates")
    parser.add_argument("--output", default="data/raw/mini2-live-temperature-features.csv")
    parser.add_argument("--converter-config", default="", help="JSON object with type=affine or type=lookup")
    parser.add_argument("--official-jpeg", default="", help="Mini2 radiometric JPEG for official MTlib metadata/config")
    parser.add_argument("--official-dll-dir", default=r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
    parser.add_argument("--official-batch-size", type=int, default=1)
    parser.add_argument(
        "--official-worker-command",
        default="",
        help="Windows Python worker command, e.g. py.exe -3 tools/mini2_official_mtlib_worker_win.py --metadata-jpeg data/fixtures/mini2/IR_00001.jpeg",
    )
    parser.add_argument("--affine-json", default="", help="ROI calibration JSON from tools/mini2_roi_calibration.py")
    parser.add_argument("--lookup-csv", default="", help="raw_u16,Celsius lookup CSV")
    parser.add_argument("--slope-c-per-raw", type=float, default=None)
    parser.add_argument("--intercept-c", type=float, default=None)
    parser.add_argument("--save-matrix-npy-dir", default="", help="optional debugging only; disabled by default")
    parser.add_argument("--print-every", type=int, default=5)
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error("--frames must be positive")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
