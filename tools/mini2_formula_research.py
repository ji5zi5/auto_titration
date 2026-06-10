"""Compare Mini2 UVC raw-to-Celsius formula candidates.

This is an evidence tool, not a final SDK replacement. It scores candidate
formulas against user-observed official-app min/max values and explicitly
marks formulas that create false 40C-class maxima when the app did not.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import numpy as np


WIDTH = 256
HEIGHT = 344
MATRIX_HEIGHT = 192
FRAME_BYTES = WIDTH * HEIGHT * 2
METADATA_START_ROW = MATRIX_HEIGHT
METADATA_END_ROW = HEIGHT


ScaleTransform = tuple[str, Callable[[float], float]]


SCALE_TRANSFORMS: list[ScaleTransform] = [
    ("value", lambda value: value),
    ("value_div_10", lambda value: value / 10.0),
    ("value_div_100", lambda value: value / 100.0),
    ("value_div_1000", lambda value: value / 1000.0),
    ("value_plus_3", lambda value: value + 3.0),
    ("value_plus_4", lambda value: value + 4.0),
    ("value_plus_5", lambda value: value + 5.0),
]


@dataclass
class DecodedFrame:
    frame_id: int
    full: np.ndarray
    matrix: np.ndarray


@dataclass
class Formula:
    name: str
    fn: Callable[[DecodedFrame], np.ndarray]
    note: str


def decode_frame(raw_bytes: bytes, frame_id: int = 0) -> DecodedFrame:
    if len(raw_bytes) != FRAME_BYTES:
        raise ValueError(f"expected {FRAME_BYTES} bytes, got {len(raw_bytes)}")
    full = np.frombuffer(raw_bytes, dtype="<u2").reshape(HEIGHT, WIDTH)
    return DecodedFrame(frame_id=frame_id, full=full, matrix=full[:MATRIX_HEIGHT].astype("float64"))


def decode_sequence(raw_path: Path) -> list[DecodedFrame]:
    raw_bytes = raw_path.read_bytes()
    if len(raw_bytes) % FRAME_BYTES != 0:
        raise ValueError(f"{raw_path} size {len(raw_bytes)} is not a multiple of {FRAME_BYTES}")
    return [
        decode_frame(raw_bytes[offset : offset + FRAME_BYTES], frame_id=i)
        for i, offset in enumerate(range(0, len(raw_bytes), FRAME_BYTES))
    ]


def safe_divide(values: np.ndarray, denominator: float) -> np.ndarray:
    if denominator == 0:
        return np.full(values.shape, np.nan, dtype="float64")
    return values / denominator


def metadata_positions() -> list[tuple[int, int]]:
    return [(row, col) for row in range(METADATA_START_ROW, METADATA_END_ROW) for col in range(WIDTH)]


def raw_bounds(frames: list[DecodedFrame]) -> tuple[list[float], list[float]]:
    return (
        [float(frame.matrix.min()) for frame in frames],
        [float(frame.matrix.max()) for frame in frames],
    )


def required_linear_terms(
    frames: list[DecodedFrame],
    *,
    app_min_c: float,
    app_max_c: float,
) -> tuple[list[float], list[float]]:
    """Return offset/scale required if app bounds exactly match raw min/max.

    For temp=(raw-offset)/scale:
      scale=(raw_max-raw_min)/(app_max-app_min)
      offset=raw_min-app_min*scale

    This is not asserted as the real formula. It is a diagnostic target used
    to rank metadata fields against the user's app-observed min/max range.
    """

    raw_mins, raw_maxs = raw_bounds(frames)
    app_span = max(app_max_c - app_min_c, 1e-9)
    scales = [(raw_max - raw_min) / app_span for raw_min, raw_max in zip(raw_mins, raw_maxs)]
    offsets = [raw_min - app_min_c * scale for raw_min, scale in zip(raw_mins, scales)]
    return offsets, scales


def builtin_formulas(app_min_c: float, app_max_c: float) -> list[Formula]:
    return [
        Formula(
            "raw_div16_minus_273_15",
            lambda frame: frame.matrix / 16.0 - 273.15,
            "Earlier unsupported Kelvin-like guess; expected to fail for this capture.",
        ),
        Formula(
            "offset_col5_scale_col10_div100",
            lambda frame: safe_divide(frame.matrix - float(frame.full[340, 5]), float(frame.full[340, 10]) / 100.0),
            "Previous candidate; must fail if it creates 40C false positives.",
        ),
        Formula(
            "offset_col5_scale_col14_plus4",
            lambda frame: safe_divide(frame.matrix - float(frame.full[340, 5]), float(frame.full[340, 14]) + 4.0),
            "Empirical metadata candidate: offset=row340[5], scale=row340[14]+4. Not proven as SDK formula.",
        ),
        Formula(
            "offset_col5_scale_29_fixed",
            lambda frame: (frame.matrix - float(frame.full[340, 5])) / 29.0,
            "Diagnostic fixed-scale affine formula near the app-observed 20C/37C range.",
        ),
        Formula(
            "per_frame_app_minmax_linear_reference",
            lambda frame: app_reference_map(frame.matrix, app_min_c, app_max_c),
            "Reference only: forces each frame's raw min/max to app min/max; not an implementable formula.",
        ),
    ]


def app_reference_map(matrix: np.ndarray, app_min_c: float, app_max_c: float) -> np.ndarray:
    raw_min = float(np.min(matrix))
    raw_max = float(np.max(matrix))
    if raw_max == raw_min:
        return np.full(matrix.shape, (app_min_c + app_max_c) / 2.0, dtype="float64")
    return app_min_c + (matrix - raw_min) * (app_max_c - app_min_c) / (raw_max - raw_min)


def formula_frame_stats(temp_c: np.ndarray) -> dict[str, float]:
    return {
        "min_c": round(float(np.nanmin(temp_c)), 6),
        "max_c": round(float(np.nanmax(temp_c)), 6),
        "mean_c": round(float(np.nanmean(temp_c)), 6),
        "center_c": round(float(temp_c[MATRIX_HEIGHT // 2, WIDTH // 2]), 6),
    }


def status_for_ranges(min_low: float, max_high: float, app_min_c: float, app_max_c: float, tolerance_c: float) -> str:
    if max_high > app_max_c + tolerance_c:
        return "fail"
    if min_low < app_min_c - tolerance_c:
        return "fail"
    return "candidate"


def score_builtin_formulas(
    frames: list[DecodedFrame],
    *,
    app_min_c: float,
    app_max_c: float,
    tolerance_c: float = 2.0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for formula in builtin_formulas(app_min_c, app_max_c):
        per_frame = [formula_frame_stats(formula.fn(frame)) for frame in frames]
        min_values = [row["min_c"] for row in per_frame]
        max_values = [row["max_c"] for row in per_frame]
        mean_values = [row["mean_c"] for row in per_frame]
        min_low = min(min_values)
        min_high = max(min_values)
        max_low = min(max_values)
        max_high = max(max_values)
        status = status_for_ranges(min_low, max_high, app_min_c, app_max_c, tolerance_c)
        rows.append(
            {
                "formula_name": formula.name,
                "status": status,
                "min_c_range": f"{min_low:.3f}..{min_high:.3f}",
                "max_c_range": f"{max_low:.3f}..{max_high:.3f}",
                "mean_c_range": f"{min(mean_values):.3f}..{max(mean_values):.3f}",
                "max_over_app_max_c": round(max(0.0, max_high - app_max_c), 6),
                "min_under_app_min_c": round(max(0.0, app_min_c - min_low), 6),
                "app_min_c": app_min_c,
                "app_max_c": app_max_c,
                "tolerance_c": tolerance_c,
                "note": formula.note,
            }
        )
    rows.sort(
        key=lambda row: (
            row["status"] != "candidate",
            float(row["max_over_app_max_c"]) + float(row["min_under_app_min_c"]),
        )
    )
    return rows


def metadata_field_inventory(
    frames: list[DecodedFrame],
    *,
    app_min_c: float,
    app_max_c: float,
) -> list[dict[str, Any]]:
    """Rank every UVC metadata field as a possible offset or scale source."""

    required_offsets, required_scales = required_linear_terms(frames, app_min_c=app_min_c, app_max_c=app_max_c)
    rows: list[dict[str, Any]] = []
    for row, col in metadata_positions():
        values = [float(frame.full[row, col]) for frame in frames]
        offset_mae = sum(abs(value - required) for value, required in zip(values, required_offsets)) / len(values)

        best_transform = ""
        best_scale_values: list[float] = []
        best_scale_mae = float("inf")
        for transform_name, transform in SCALE_TRANSFORMS:
            scales = [transform(value) for value in values]
            if any(not math.isfinite(scale) or scale <= 0 for scale in scales):
                continue
            if not all(10.0 <= scale <= 80.0 for scale in scales):
                continue
            scale_mae = sum(abs(scale - required) for scale, required in zip(scales, required_scales)) / len(scales)
            if scale_mae < best_scale_mae:
                best_scale_mae = scale_mae
                best_transform = transform_name
                best_scale_values = scales

        rows.append(
            {
                "row": row,
                "col": col,
                "values": " ".join(str(int(value)) for value in values[:10]),
                "min_value": round(min(values), 6),
                "max_value": round(max(values), 6),
                "unique_count": len({int(value) for value in values}),
                "offset_mae_vs_app_bounds": round(offset_mae, 6),
                "best_scale_transform": best_transform,
                "best_scale_values": " ".join(f"{value:.3f}" for value in best_scale_values[:10]),
                "best_scale_mae_vs_app_span": round(best_scale_mae, 6) if math.isfinite(best_scale_mae) else "",
                "offset_candidate": offset_mae <= 250.0,
                "scale_candidate": math.isfinite(best_scale_mae) and best_scale_mae <= 5.0,
            }
        )

    rows.sort(
        key=lambda row: (
            not (row["offset_candidate"] or row["scale_candidate"]),
            min(
                float(row["offset_mae_vs_app_bounds"]),
                float(row["best_scale_mae_vs_app_span"]) if row["best_scale_mae_vs_app_span"] != "" else float("inf"),
            ),
        )
    )
    return rows


def search_affine_metadata(
    frames: list[DecodedFrame],
    *,
    app_min_c: float,
    app_max_c: float,
    max_rows: int = 100,
    max_offset_candidates: int = 80,
    max_scale_candidates: int = 160,
    tolerance_c: float = 2.0,
) -> list[dict[str, Any]]:
    """Search simple affine formulas using metadata-derived offset/scale.

    The search is intentionally narrow and explainable:
    temp = (raw - offset_field) / scale_field
    where offset_field is an unchanged u16 metadata value and scale_field is a
    simple transform of a u16 metadata value.
    """

    inventory = metadata_field_inventory(frames, app_min_c=app_min_c, app_max_c=app_max_c)
    raw_mins, raw_maxs = raw_bounds(frames)
    rows: list[dict[str, Any]] = []

    offset_candidates = [
        (int(row["row"]), int(row["col"]), float(row["offset_mae_vs_app_bounds"]))
        for row in inventory
        if row["offset_candidate"]
    ]
    offset_candidates.sort(key=lambda item: item[2])
    offset_candidates = offset_candidates[:max_offset_candidates]

    scale_candidates: list[tuple[int, int, str, Callable[[float], float], float]] = []
    for row in inventory:
        if not row["scale_candidate"]:
            continue
        transform_name = str(row["best_scale_transform"])
        transform = next((fn for name, fn in SCALE_TRANSFORMS if name == transform_name), None)
        if transform is None:
            continue
        scale_candidates.append((int(row["row"]), int(row["col"]), transform_name, transform, float(row["best_scale_mae_vs_app_span"])))
    scale_candidates.sort(key=lambda item: item[4])
    scale_candidates = scale_candidates[:max_scale_candidates]

    for offset_row, offset_col, _offset_mae in offset_candidates:
        offsets = [float(frame.full[offset_row, offset_col]) for frame in frames]
        for scale_row, scale_col, transform_name, transform, scale_mae in scale_candidates:
            raw_scales = [float(frame.full[scale_row, scale_col]) for frame in frames]
            scales = [transform(value) for value in raw_scales]
            per_frame_min = [(raw_min - offset) / scale for raw_min, offset, scale in zip(raw_mins, offsets, scales)]
            per_frame_max = [(raw_max - offset) / scale for raw_max, offset, scale in zip(raw_maxs, offsets, scales)]
            min_low = min(per_frame_min)
            max_high = max(per_frame_max)
            mae_to_app = (
                abs(min_low - app_min_c)
                + abs(max_high - app_max_c)
                + abs((max(per_frame_min) - app_min_c))
                + abs((min(per_frame_max) - app_max_c))
            ) / 4.0
            rows.append(
                {
                    "offset_row": offset_row,
                    "offset_col": offset_col,
                    "scale_row": scale_row,
                    "scale_col": scale_col,
                    "scale_transform": transform_name,
                    "min_c_range": f"{min(per_frame_min):.3f}..{max(per_frame_min):.3f}",
                    "max_c_range": f"{min(per_frame_max):.3f}..{max(per_frame_max):.3f}",
                    "mae_to_app_bounds": round(mae_to_app, 6),
                    "scale_mae_vs_app_span": round(scale_mae, 6),
                    "status": status_for_ranges(min_low, max_high, app_min_c, app_max_c, tolerance_c),
                    "offset_values": " ".join(str(int(value)) for value in offsets[:10]),
                    "scale_values": " ".join(f"{value:.3f}" for value in scales[:10]),
                }
                )
    rows.sort(key=lambda row: (row["status"] != "candidate", row["mae_to_app_bounds"], row["scale_mae_vs_app_span"]))
    return rows[:max_rows]


def frame_level_diagnostics(
    frames: list[DecodedFrame],
    *,
    app_min_c: float,
    app_max_c: float,
) -> list[dict[str, Any]]:
    required_offsets, required_scales = required_linear_terms(frames, app_min_c=app_min_c, app_max_c=app_max_c)
    formulas = {formula.name: formula for formula in builtin_formulas(app_min_c, app_max_c)}
    rows: list[dict[str, Any]] = []
    for frame, required_offset, required_scale in zip(frames, required_offsets, required_scales):
        previous = formula_frame_stats(formulas["offset_col5_scale_col10_div100"].fn(frame))
        col14_plus4 = formula_frame_stats(formulas["offset_col5_scale_col14_plus4"].fn(frame))
        fixed29 = formula_frame_stats(formulas["offset_col5_scale_29_fixed"].fn(frame))
        raw_div16 = formula_frame_stats(formulas["raw_div16_minus_273_15"].fn(frame))
        rows.append(
            {
                "frame_id": frame.frame_id,
                "raw_min": int(frame.matrix.min()),
                "raw_max": int(frame.matrix.max()),
                "raw_mean": round(float(frame.matrix.mean()), 6),
                "raw_center": int(frame.matrix[MATRIX_HEIGHT // 2, WIDTH // 2]),
                "required_scale_if_app_bounds_exact": round(required_scale, 6),
                "required_offset_if_app_bounds_exact": round(required_offset, 6),
                "row340_col5_offset_candidate": int(frame.full[340, 5]),
                "row340_col10_div100_previous_scale": round(float(frame.full[340, 10]) / 100.0, 6),
                "row340_col14_plus4_scale_candidate": round(float(frame.full[340, 14]) + 4.0, 6),
                "row340_col15": int(frame.full[340, 15]),
                "row340_col16": int(frame.full[340, 16]),
                "previous_col10_min_c": previous["min_c"],
                "previous_col10_max_c": previous["max_c"],
                "col14_plus4_min_c": col14_plus4["min_c"],
                "col14_plus4_max_c": col14_plus4["max_c"],
                "fixed29_min_c": fixed29["min_c"],
                "fixed29_max_c": fixed29["max_c"],
                "raw_div16_min_c": raw_div16["min_c"],
                "raw_div16_max_c": raw_div16["max_c"],
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = list(rows[0].keys()) if rows else ["empty"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def process_sequence(
    raw_path: Path,
    output_dir: Path,
    *,
    app_min_c: float,
    app_max_c: float,
    tolerance_c: float = 2.0,
) -> dict[str, Any]:
    frames = decode_sequence(raw_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    score_rows = score_builtin_formulas(frames, app_min_c=app_min_c, app_max_c=app_max_c, tolerance_c=tolerance_c)
    inventory_rows = metadata_field_inventory(frames, app_min_c=app_min_c, app_max_c=app_max_c)
    search_rows = search_affine_metadata(frames, app_min_c=app_min_c, app_max_c=app_max_c, tolerance_c=tolerance_c)
    frame_diag_rows = frame_level_diagnostics(frames, app_min_c=app_min_c, app_max_c=app_max_c)
    write_csv(output_dir / "formula_candidate_scores.csv", score_rows)
    write_csv(output_dir / "metadata_affine_search.csv", search_rows)
    write_csv(output_dir / "metadata_field_inventory.csv", inventory_rows)
    write_csv(output_dir / "frame_level_diagnostics.csv", frame_diag_rows)
    implementable_scores = [row for row in score_rows if row["formula_name"] != "per_frame_app_minmax_linear_reference"]
    passing_implementable_scores = [row for row in implementable_scores if row["status"] == "candidate"]
    summary = {
        "source_file": str(raw_path),
        "frame_count": len(frames),
        "app_min_c": app_min_c,
        "app_max_c": app_max_c,
        "tolerance_c": tolerance_c,
        "best_builtin": passing_implementable_scores[0]["formula_name"] if passing_implementable_scores else "",
        "failed_formulas": [
            {
                "formula_name": row["formula_name"],
                "max_c_range": row["max_c_range"],
                "max_over_app_max_c": row["max_over_app_max_c"],
            }
            for row in implementable_scores
            if row["status"] == "fail"
        ],
        "best_metadata_search": search_rows[0] if search_rows else {},
        "metadata_fields_scanned": len(inventory_rows),
        "warning": "Candidate formulas are not proven until checked against exact app readings for the same captured frame.",
    }
    (output_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_readme(output_dir)
    return summary


def write_readme(output_dir: Path) -> None:
    (output_dir / "READ_ME_FIRST.txt").write_text(
        """Mini2 formula research

status: not proven

Purpose:
- Compare multiple raw-to-Celsius formula candidates.
- Reject 40C false positive formulas when the app did not show 40C.
- Search simple metadata-derived affine formulas.

Read in order:
1. formula_candidate_scores.csv
2. metadata_affine_search.csv
3. run_summary.json
4. frame_level_diagnostics.csv
5. metadata_field_inventory.csv

Important:
- A candidate row is not a final SDK formula.
- A fail row is rejected for the current app min/max observation.
- metadata_field_inventory.csv scans every bottom UVC metadata word, rows 192..343.
- Exact app min/max/center values for the same captured frame are still the strongest validation.
""",
        encoding="utf-8",
    )


def latest_sequence(default_root: Path) -> Path:
    candidates = sorted(default_root.glob("*/mini2_detailed_sequence.raw"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No mini2_detailed_sequence.raw found under {default_root}")
    return candidates[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score Mini2 UVC raw-to-Celsius formula candidates.")
    parser.add_argument("--raw-file", default="")
    parser.add_argument("--input-root", default="data/mini2_detailed_raw_test")
    parser.add_argument("--output-dir", default=f"data/mini2_formula_research/{datetime.now():%Y%m%d-%H%M%S}")
    parser.add_argument("--app-min-c", type=float, default=20.0)
    parser.add_argument("--app-max-c", type=float, default=37.0)
    parser.add_argument("--tolerance-c", type=float, default=2.0)
    args = parser.parse_args()

    raw_path = Path(args.raw_file) if args.raw_file else latest_sequence(Path(args.input_root))
    summary = process_sequence(
        raw_path,
        Path(args.output_dir),
        app_min_c=args.app_min_c,
        app_max_c=args.app_max_c,
        tolerance_c=args.tolerance_c,
    )
    print("Mini2 formula research complete.")
    print(f"  source: {summary['source_file']}")
    print(f"  frames: {summary['frame_count']}")
    print(f"  app bounds: {summary['app_min_c']}..{summary['app_max_c']} C")
    print(f"  output: {args.output_dir}")
    print("  status: not proven; inspect formula_candidate_scores.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
