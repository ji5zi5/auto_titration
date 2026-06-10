"""Fit a project-local Mini2 raw-to-Celsius calibration from ROI points.

This avoids using whole-frame min/max as ground truth. The user supplies
specific ROI coordinates and temperatures measured by the official app or an
external thermometer for the same stable scene.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from tools.mini2_formula_research import MATRIX_HEIGHT, WIDTH, DecodedFrame, decode_sequence, latest_sequence, write_csv


REQUIRED_COLUMNS = ("frame_id", "label", "x", "y", "radius", "temp_c")


def write_template(points_path: Path) -> None:
    points_path.parent.mkdir(parents=True, exist_ok=True)
    points_path.write_text(
        "frame_id,label,x,y,radius,temp_c\n"
        "0,room_reference,60,50,4,22.0\n"
        "0,warm_reference,180,50,4,35.0\n",
        encoding="utf-8",
    )


def read_points(points_path: Path) -> list[dict[str, Any]]:
    with points_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        missing = [column for column in REQUIRED_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{points_path} is missing columns: {', '.join(missing)}")
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                rows.append(
                    {
                        "frame_id": int(row["frame_id"]),
                        "label": row["label"],
                        "x": int(float(row["x"])),
                        "y": int(float(row["y"])),
                        "radius": max(0, int(float(row["radius"]))),
                        "temp_c": float(row["temp_c"]),
                    }
                )
            except ValueError as exc:
                raise ValueError(f"invalid numeric value in {points_path} row {row_number}") from exc
    if len(rows) < 2:
        raise ValueError("at least two ROI temperature points are required")
    return rows


def roi_values(frame: DecodedFrame, *, x: int, y: int, radius: int) -> np.ndarray:
    if not (0 <= x < WIDTH and 0 <= y < MATRIX_HEIGHT):
        raise ValueError(f"ROI center out of matrix bounds: x={x}, y={y}")
    x0 = max(0, x - radius)
    x1 = min(WIDTH, x + radius + 1)
    y0 = max(0, y - radius)
    y1 = min(MATRIX_HEIGHT, y + radius + 1)
    return frame.matrix[y0:y1, x0:x1]


def extract_samples(raw_path: Path, points_path: Path) -> list[dict[str, Any]]:
    frames = decode_sequence(raw_path)
    points = read_points(points_path)
    by_id = {frame.frame_id: frame for frame in frames}
    samples: list[dict[str, Any]] = []
    for point in points:
        frame_id = int(point["frame_id"])
        if frame_id not in by_id:
            raise ValueError(f"frame_id {frame_id} not found in {raw_path}; available 0..{len(frames) - 1}")
        values = roi_values(by_id[frame_id], x=int(point["x"]), y=int(point["y"]), radius=int(point["radius"]))
        samples.append(
            {
                "frame_id": frame_id,
                "label": point["label"],
                "x": int(point["x"]),
                "y": int(point["y"]),
                "radius": int(point["radius"]),
                "temp_c": float(point["temp_c"]),
                "raw_mean": round(float(np.mean(values)), 6),
                "raw_min": round(float(np.min(values)), 6),
                "raw_max": round(float(np.max(values)), 6),
                "raw_std": round(float(np.std(values)), 6),
                "pixel_count": int(values.size),
            }
        )
    return samples


def fit_affine_model(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if len(samples) < 2:
        raise ValueError("at least two samples are required")
    x = np.array([float(sample["raw_mean"]) for sample in samples], dtype="float64")
    y = np.array([float(sample["temp_c"]) for sample in samples], dtype="float64")
    if float(np.max(x) - np.min(x)) == 0.0:
        raise ValueError("raw_mean values must not all be identical")
    slope, intercept = np.polyfit(x, y, deg=1)
    predicted = slope * x + intercept
    residuals = predicted - y
    scale_raw_per_c = 1.0 / slope if slope != 0 else float("nan")
    offset_raw = -intercept / slope if slope != 0 else float("nan")
    return {
        "formula": "temp_c = slope_c_per_raw * raw + intercept_c",
        "equivalent_formula": "temp_c = (raw - offset_raw) / scale_raw_per_c",
        "slope_c_per_raw": round(float(slope), 12),
        "intercept_c": round(float(intercept), 12),
        "scale_raw_per_c": round(float(scale_raw_per_c), 12),
        "offset_raw": round(float(offset_raw), 12),
        "sample_count": len(samples),
        "raw_mean_min": round(float(np.min(x)), 6),
        "raw_mean_max": round(float(np.max(x)), 6),
        "rmse_c": round(float(np.sqrt(np.mean(residuals**2))), 6),
        "max_abs_error_c": round(float(np.max(np.abs(residuals))), 6),
        "warning": "Project calibration only, not official SDK formula. Use same scene/ROI references and validate on held-out points.",
    }


def process(raw_path: Path, points_path: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = extract_samples(raw_path, points_path)
    formula = fit_affine_model(samples)
    write_csv(output_dir / "roi_samples.csv", samples)
    (output_dir / "roi_formula.json").write_text(json.dumps(formula, ensure_ascii=False, indent=2), encoding="utf-8")
    return formula


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit Mini2 ROI raw-to-Celsius calibration.")
    parser.add_argument("--raw-file", default="")
    parser.add_argument("--input-root", default="data/mini2_detailed_raw_test")
    parser.add_argument("--points-csv", default="data/mini2_roi_calibration/calibration_points.csv")
    parser.add_argument("--output-dir", default=f"data/mini2_roi_calibration/{datetime.now():%Y%m%d-%H%M%S}")
    args = parser.parse_args()

    raw_path = Path(args.raw_file) if args.raw_file else latest_sequence(Path(args.input_root))
    points_path = Path(args.points_csv)
    if not points_path.exists():
        write_template(points_path)
        print(f"Template written: {points_path}")
        print("Fill frame_id,label,x,y,radius,temp_c with same-scene ROI temperature references, then rerun.")
        return 2

    formula = process(raw_path, points_path, Path(args.output_dir))
    print("Mini2 ROI calibration complete.")
    print(f"  source: {raw_path}")
    print(f"  points: {points_path}")
    print(f"  output: {args.output_dir}")
    print(f"  temp_c = {formula['slope_c_per_raw']} * raw + {formula['intercept_c']}")
    print(f"  temp_c = (raw - {formula['offset_raw']}) / {formula['scale_raw_per_c']}")
    print(f"  rmse_c: {formula['rmse_c']}")
    print("  status: project calibration, not official SDK formula")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
