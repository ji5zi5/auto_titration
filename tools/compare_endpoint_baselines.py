"""Compare deterministic endpoint rules with the report ML variants.

The non-ML rules are development baselines, not independent validation:
their type-specific settings were selected on the same 12 runs used for the
report's type-specific ML development comparison.  Target/theory columns are
used only after prediction to calculate error.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Mapping, Sequence

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = REPO_ROOT / "머신러닝용 파일모음"
DEFAULT_ML_PREDICTIONS = (
    REPO_ROOT
    / "data/ml/report_modality_sensor_features_only"
    / "selected_predictions_color_thermal_fusion.csv"
)
DEFAULT_ML_CURRENT_VOLUME_PREDICTIONS = (
    REPO_ROOT
    / "data/ml/report_modality_development_selector"
    / "selected_predictions_color_thermal_fusion.csv"
)
DEFAULT_MANUAL_TITRATION = REPO_ROOT / "data/analysis/manual_titration_user_provided.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/analysis/non_ml_baseline_comparison"

RESAMPLE_STEP_ML = 0.1
EDGE_EXCLUSION_FRACTION = 0.05


@dataclass(frozen=True)
class ColorSlopeConfig:
    signal: str
    baseline_fraction: float
    smoothing_ml: float
    major_slope_fraction: float
    selection: str


@dataclass(frozen=True)
class FusionThresholdConfig:
    baseline_fraction: float
    smoothing_ml: float
    color_threshold: float
    fusion_threshold: float
    color_weight: float
    sustained_ml: float


# Selected separately for each titration type on the same 12 development runs
# as the report's type-specific ML selector.  The settings are deterministic
# after selection and never read theory/label columns during prediction.
COLOR_SLOPE_CONFIGS: dict[str, ColorSlopeConfig] = {
    "strong_acid_strong_base": ColorSlopeConfig(
        signal="rgb_projection",
        baseline_fraction=0.15,
        smoothing_ml=12.0,
        major_slope_fraction=0.50,
        selection="last",
    ),
    "strong_acid_weak_base": ColorSlopeConfig(
        signal="saturation",
        baseline_fraction=0.05,
        smoothing_ml=1.0,
        major_slope_fraction=0.50,
        selection="last",
    ),
    "weak_acid_strong_base": ColorSlopeConfig(
        signal="red",
        baseline_fraction=0.05,
        smoothing_ml=10.0,
        major_slope_fraction=0.20,
        selection="max",
    ),
    "weak_acid_weak_base": ColorSlopeConfig(
        signal="value",
        baseline_fraction=0.05,
        smoothing_ml=12.0,
        major_slope_fraction=0.50,
        selection="last",
    ),
}

FUSION_THRESHOLD_CONFIGS: dict[str, FusionThresholdConfig] = {
    "strong_acid_strong_base": FusionThresholdConfig(
        baseline_fraction=0.20,
        smoothing_ml=2.0,
        color_threshold=0.85,
        fusion_threshold=0.85,
        color_weight=0.70,
        sustained_ml=0.2,
    ),
    "strong_acid_weak_base": FusionThresholdConfig(
        baseline_fraction=0.10,
        smoothing_ml=2.0,
        color_threshold=0.88,
        fusion_threshold=0.85,
        color_weight=0.80,
        sustained_ml=1.0,
    ),
    "weak_acid_strong_base": FusionThresholdConfig(
        baseline_fraction=0.20,
        smoothing_ml=0.5,
        color_threshold=0.90,
        fusion_threshold=0.65,
        color_weight=0.70,
        sustained_ml=0.2,
    ),
    "weak_acid_weak_base": FusionThresholdConfig(
        baseline_fraction=0.10,
        smoothing_ml=0.5,
        color_threshold=0.95,
        fusion_threshold=0.65,
        color_weight=0.70,
        sustained_ml=0.2,
    ),
}

DEFAULT_COLOR_SLOPE_CONFIG = ColorSlopeConfig(
    signal="hue",
    baseline_fraction=0.10,
    smoothing_ml=1.0,
    major_slope_fraction=1.0,
    selection="max",
)
DEFAULT_FUSION_THRESHOLD_CONFIG = FusionThresholdConfig(
    baseline_fraction=0.10,
    smoothing_ml=1.0,
    color_threshold=0.80,
    fusion_threshold=0.70,
    color_weight=0.70,
    sustained_ml=0.2,
)


def safe_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=float), percent))


def _column_value(row: Mapping[str, object], column: str) -> float | None:
    value = safe_float(row.get(column))
    if value is not None:
        return value
    fallbacks = {
        "visible_R_mean": "visible_H_mean",
        "visible_G_mean": "visible_H_mean",
        "visible_B_mean": "visible_H_mean",
        "visible_S_mean": "visible_H_mean",
        "visible_V_mean": "visible_H_mean",
        "thermal_roi_avg": "thermal_roi_avg_baseline_delta",
    }
    return safe_float(row.get(fallbacks.get(column, "")))


def _collapse_matrix(
    rows: Sequence[Mapping[str, object]],
    columns: Sequence[str],
) -> tuple[np.ndarray, np.ndarray]:
    grouped: dict[float, list[list[float]]] = {}
    for row in rows:
        volume = safe_float(row.get("injected_volume_ml"))
        values = [_column_value(row, column) for column in columns]
        if volume is None or any(value is None for value in values):
            continue
        grouped.setdefault(round(volume, 2), []).append([float(value) for value in values])
    if len(grouped) < 3:
        raise ValueError("at least three valid volume bins are required")
    volumes = np.asarray(sorted(grouped), dtype=float)
    matrix = np.asarray(
        [
            [median(sample[column] for sample in grouped[volume]) for column in range(len(columns))]
            for volume in volumes
        ],
        dtype=float,
    )
    return volumes, matrix


def _resampled_curve(
    rows: Sequence[Mapping[str, object]],
) -> tuple[np.ndarray, np.ndarray]:
    columns = (
        "visible_R_mean",
        "visible_G_mean",
        "visible_B_mean",
        "visible_H_mean",
        "visible_S_mean",
        "visible_V_mean",
        "thermal_roi_avg",
    )
    volumes, matrix = _collapse_matrix(rows, columns)
    grid = np.arange(volumes[0], volumes[-1] + RESAMPLE_STEP_ML / 2.0, RESAMPLE_STEP_ML)
    resampled = np.column_stack(
        [np.interp(grid, volumes, matrix[:, column]) for column in range(matrix.shape[1])]
    )
    return grid, resampled


def _moving_mean(values: np.ndarray, width_ml: float) -> np.ndarray:
    points = max(1, int(round(float(width_ml) / RESAMPLE_STEP_ML)))
    if points <= 1:
        return values.astype(float, copy=True)
    left = points // 2
    right = points - 1 - left
    kernel = np.ones(points, dtype=float) / points
    padded = np.pad(values, (left, right), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _baseline_projection(
    values: np.ndarray,
    baseline_fraction: float,
) -> np.ndarray:
    count = max(3, int(len(values) * baseline_fraction))
    start = np.median(values[:count], axis=0)
    end = np.median(values[-count:], axis=0)
    direction = end - start
    denominator = float(np.dot(direction, direction))
    if denominator <= 1e-12:
        return np.zeros(len(values), dtype=float)
    return ((values - start) @ direction) / denominator


def _signal_progress(
    matrix: np.ndarray,
    signal: str,
    baseline_fraction: float,
) -> np.ndarray:
    if signal == "rgb_projection":
        return _baseline_projection(matrix[:, :3], baseline_fraction)
    column = {
        "red": 0,
        "green": 1,
        "blue": 2,
        "hue": 3,
        "saturation": 4,
        "value": 5,
    }.get(signal)
    if column is None:
        raise ValueError(f"unsupported color signal: {signal}")
    return _baseline_projection(matrix[:, column : column + 1], baseline_fraction)


def _titration_type(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        return ""
    return str(rows[0].get("titration_type") or "").strip()


def predict_color_max_slope(
    rows: Sequence[Mapping[str, object]],
    config: ColorSlopeConfig | None = None,
) -> float:
    """Return the major color-slope location using a deterministic rule."""

    selected = config or COLOR_SLOPE_CONFIGS.get(
        _titration_type(rows),
        DEFAULT_COLOR_SLOPE_CONFIG,
    )
    volumes, matrix = _resampled_curve(rows)
    progress = _moving_mean(
        _signal_progress(matrix, selected.signal, selected.baseline_fraction),
        selected.smoothing_ml,
    )
    gradients = np.abs(np.gradient(progress, volumes))
    edge = max(2, int(len(volumes) * EDGE_EXCLUSION_FRACTION))
    candidate_indices = np.arange(edge, max(edge + 1, len(volumes) - edge))
    candidate_gradients = gradients[candidate_indices]
    maximum = float(np.max(candidate_gradients))
    major = candidate_indices[
        candidate_gradients >= selected.major_slope_fraction * maximum
    ]
    if selected.selection == "max":
        index = int(candidate_indices[int(np.argmax(candidate_gradients))])
    elif selected.selection == "last":
        index = int(major[-1])
    elif selected.selection == "center":
        index = int(round(np.average(major, weights=gradients[major])))
    else:
        raise ValueError(f"unsupported slope selection: {selected.selection}")
    return float(volumes[index])


def _thermal_change_score(
    matrix: np.ndarray,
    baseline_fraction: float,
    smoothing_ml: float,
) -> np.ndarray:
    thermal = matrix[:, 6]
    count = max(3, int(len(thermal) * baseline_fraction))
    baseline = float(np.median(thermal[:count]))
    absolute = np.abs(thermal - baseline)
    low = float(np.percentile(absolute, 5.0))
    high = float(np.percentile(absolute, 95.0))
    if high <= low + 1e-12:
        return np.zeros(len(thermal), dtype=float)
    normalized = np.clip((absolute - low) / (high - low), 0.0, 1.0)
    return _moving_mean(normalized, smoothing_ml)


def predict_color_thermal_threshold(
    rows: Sequence[Mapping[str, object]],
    config: FusionThresholdConfig | None = None,
) -> float:
    """Return the first sustained adaptive color+thermal threshold crossing."""

    selected = config or FUSION_THRESHOLD_CONFIGS.get(
        _titration_type(rows),
        DEFAULT_FUSION_THRESHOLD_CONFIG,
    )
    volumes, matrix = _resampled_curve(rows)
    color = _moving_mean(
        _signal_progress(matrix, "hue", selected.baseline_fraction),
        selected.smoothing_ml,
    )
    color = np.clip(color, 0.0, 1.0)
    thermal = _thermal_change_score(
        matrix,
        selected.baseline_fraction,
        selected.smoothing_ml,
    )
    fusion = selected.color_weight * color + (1.0 - selected.color_weight) * thermal
    passed = (color >= selected.color_threshold) & (fusion >= selected.fusion_threshold)
    sustained_points = max(1, int(round(selected.sustained_ml / RESAMPLE_STEP_ML)))
    for index in range(0, len(passed) - sustained_points + 1):
        if bool(np.all(passed[index : index + sustained_points])):
            return float(volumes[index])
    return float(volumes[int(np.argmax(fusion))])


def metric_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, float | int]:
    absolute_errors = [float(row["absolute_error_ml"]) for row in rows]
    percentage_errors = [float(row["absolute_percentage_error"]) for row in rows]
    return {
        "run_count": len(rows),
        "mae_ml": round(mean(absolute_errors), 6),
        "rmse_ml": round(math.sqrt(mean([value * value for value in absolute_errors])), 6),
        "mape_percent": round(mean(percentage_errors), 6),
        "within_1pct_rate": round(sum(value <= 1.0 for value in percentage_errors) / len(rows), 6),
        "within_2pct_rate": round(sum(value <= 2.0 for value in percentage_errors) / len(rows), 6),
        "within_5pct_rate": round(sum(value <= 5.0 for value in percentage_errors) / len(rows), 6),
    }


def prediction_row(
    *,
    method: str,
    run_path: Path,
    source_row: Mapping[str, object],
    predicted_volume: float,
) -> dict[str, object]:
    actual = float(source_row["theoretical_equivalence_volume_ml"])
    absolute_error = abs(predicted_volume - actual)
    return {
        "method": method,
        "run_path": str(run_path),
        "titration_type": str(source_row.get("titration_type") or ""),
        "concentration_m": float(source_row["sample_concentration_M"]),
        "actual_equivalence_volume_ml": actual,
        "predicted_equivalence_volume_ml": round(predicted_volume, 6),
        "absolute_error_ml": round(absolute_error, 6),
        "absolute_percentage_error": round(absolute_error / actual * 100.0, 6),
    }


def load_ml_predictions(path: Path) -> dict[str, dict[str, str]]:
    rows = load_rows(path)
    return {Path(row["run_path"]).name: row for row in rows}


def load_manual_predictions(path: Path) -> dict[tuple[str, float], dict[str, str]]:
    rows = load_rows(path)
    return {
        (
            row["titration_type"],
            round(float(row["verification_concentration_M"]), 6),
        ): row
        for row in rows
    }


def evaluate(
    input_dir: Path = DEFAULT_INPUT_DIR,
    ml_predictions_path: Path = DEFAULT_ML_PREDICTIONS,
    ml_current_volume_predictions_path: Path = DEFAULT_ML_CURRENT_VOLUME_PREDICTIONS,
    manual_titration_path: Path = DEFAULT_MANUAL_TITRATION,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sensor_only_dir = ml_predictions_path.parent
    ml_predictions = {
        "machine_learning_color": load_ml_predictions(
            sensor_only_dir / "selected_predictions_color_only.csv"
        ),
        "machine_learning_thermal": load_ml_predictions(
            sensor_only_dir / "selected_predictions_thermal_only.csv"
        ),
        "machine_learning_fusion": load_ml_predictions(ml_predictions_path),
        "machine_learning_fusion_with_volume": load_ml_predictions(
            ml_current_volume_predictions_path
        ),
    }
    manual_predictions = load_manual_predictions(manual_titration_path)
    per_run: list[dict[str, object]] = []
    for run_path in sorted(input_dir.glob("*.csv")):
        rows = load_rows(run_path)
        if not rows:
            continue
        manual = manual_predictions[
            (
                str(rows[0]["titration_type"]),
                round(float(rows[0]["sample_concentration_M"]), 6),
            )
        ]
        per_run.append(
            prediction_row(
                method="manual_titration_user_provided",
                run_path=run_path,
                source_row=rows[0],
                predicted_volume=float(manual["manual_equivalence_volume_ml"]),
            )
        )
        per_run.append(
            prediction_row(
                method="color_major_slope",
                run_path=run_path,
                source_row=rows[0],
                predicted_volume=predict_color_max_slope(rows),
            )
        )
        per_run.append(
            prediction_row(
                method="color_thermal_adaptive_threshold",
                run_path=run_path,
                source_row=rows[0],
                predicted_volume=predict_color_thermal_threshold(rows),
            )
        )
        for method, predictions in ml_predictions.items():
            ml = predictions[run_path.name]
            per_run.append(
                prediction_row(
                    method=method,
                    run_path=run_path,
                    source_row=rows[0],
                    predicted_volume=float(ml["predicted_equivalence_volume_ml"]),
                )
            )

    comparison: list[dict[str, object]] = []
    for method in (
        "manual_titration_user_provided",
        "color_major_slope",
        "color_thermal_adaptive_threshold",
        "machine_learning_color",
        "machine_learning_thermal",
        "machine_learning_fusion",
        "machine_learning_fusion_with_volume",
    ):
        method_rows = [row for row in per_run if row["method"] == method]
        comparison.append({"method": method, **metric_summary(method_rows)})
    return per_run, comparison


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_dir: Path,
    per_run: list[dict[str, object]],
    comparison: list[dict[str, object]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "per_run_predictions.csv", per_run)
    write_csv(output_dir / "overall_comparison.csv", comparison)
    summary = {
        "schema_version": "endpoint_baseline_comparison_v3",
        "selection_scope": (
            "type-specific settings selected on the same 12 development runs "
            "as the report ML development selector"
        ),
        "run_count": len(per_run) // 7,
        "manual_titration_provenance": {
            "path": str(DEFAULT_MANUAL_TITRATION.relative_to(REPO_ROOT)),
            "status": "user_provided_unverified",
            "note": "Values were supplied in chat and were not corroborated against a laboratory notebook or raw measurement record.",
        },
        "rules": {
            "color_major_slope": {
                key: asdict(value) for key, value in COLOR_SLOPE_CONFIGS.items()
            },
            "color_thermal_adaptive_threshold": {
                key: asdict(value) for key, value in FUSION_THRESHOLD_CONFIGS.items()
            },
            "excluded_prediction_inputs": [
                "sample_concentration_M",
                "theoretical_equivalence_volume_ml",
                "distance_to_equivalence_ml",
                "time_to_equivalence_s",
                "equivalence_window_label",
                "status_label",
            ],
        },
        "comparison": comparison,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--ml-predictions", type=Path, default=DEFAULT_ML_PREDICTIONS)
    parser.add_argument(
        "--ml-current-volume-predictions",
        type=Path,
        default=DEFAULT_ML_CURRENT_VOLUME_PREDICTIONS,
    )
    parser.add_argument(
        "--manual-titration",
        type=Path,
        default=DEFAULT_MANUAL_TITRATION,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    per_run, comparison = evaluate(
        args.input_dir,
        args.ml_predictions,
        args.ml_current_volume_predictions,
        args.manual_titration,
    )
    if len(per_run) != 84:
        raise SystemExit(f"expected 84 method-run rows, found {len(per_run)}")
    write_outputs(args.output_dir, per_run, comparison)
    print(
        json.dumps(
            {"output_dir": str(args.output_dir), "comparison": comparison},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
