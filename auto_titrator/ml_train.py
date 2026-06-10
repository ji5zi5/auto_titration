"""Offline equivalence-volume model training.

The first model is intentionally simple and transparent: a JSON-serializable
linear regression over CSV feature columns. If too little labeled data exists,
training falls back to a constant-mean model with an explicit sparse-data
warning instead of pretending a fitted model is reliable.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .ml_features import DERIVED_ML_COLUMNS


DEFAULT_FEATURE_COLUMNS = [
    "time_s",
    "injected_volume_ml",
    "visible_R_mean",
    "visible_G_mean",
    "visible_B_mean",
    "visible_H_mean",
    "visible_S_mean",
    "visible_V_mean",
    "visible_H_delta",
    "visible_S_delta",
    "visible_V_delta",
    "visible_HSV_delta",
    "visible_color_delta",
    "thermal_R_mean",
    "thermal_G_mean",
    "thermal_B_mean",
    "thermal_H_mean",
    "thermal_S_mean",
    "thermal_V_mean",
    "thermal_H_delta",
    "thermal_S_delta",
    "thermal_V_delta",
    "thermal_HSV_delta",
    "thermal_color_delta",
    "thermal_roi_avg",
    "thermal_roi_max",
    "thermal_roi_min",
    "thermal_roi_std",
    "thermal_roi_range",
    "thermal_roi_iqr",
    "thermal_roi_p05",
    "thermal_roi_p50",
    "thermal_roi_p95",
    "thermal_roi_hot_fraction",
    "thermal_roi_cold_fraction",
    "thermal_roi_delta",
    "thermal_matrix_avg",
    "thermal_matrix_max",
    "thermal_matrix_min",
    "thermal_matrix_std",
    "thermal_matrix_iqr",
    "thermal_matrix_p05",
    "thermal_matrix_p50",
    "thermal_matrix_p95",
    "thermal_raw_roi_p05",
    "thermal_raw_roi_p50",
    "thermal_raw_roi_p95",
    "thermal_raw_roi_iqr",
    "thermal_raw_mean",
    "thermal_raw_std",
    "sample_concentration_M",
    "sample_volume_ml",
    "sample_valence",
    "titrant_concentration_M",
    "titrant_valence",
    "selected_pka_value",
    "ionic_strength_m",
    "theoretical_equivalence_pH",
    "indicator_transition_low_pH",
    "indicator_transition_high_pH",
    "indicator_endpoint_offset_ml",
    "status_confidence",
    *DERIVED_ML_COLUMNS,
]

MODEL_METADATA = {
    "feature_version": "equivalence_features_v4",
    "model_family_decision": "transparent linear/constant baseline; choose RandomForest/SVM/etc only after labeled data review",
}

DEFAULT_TARGET_COLUMN = "reference_equivalence_volume_ml"
def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_training_examples(
    csv_paths: Iterable[str | Path],
    *,
    feature_columns: Sequence[str],
    target_column: str,
) -> tuple[np.ndarray, np.ndarray, int]:
    features: list[list[float]] = []
    targets: list[float] = []
    skipped = 0
    for csv_path in csv_paths:
        with Path(csv_path).open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                target = _to_float(row.get(target_column))
                if target is None:
                    skipped += 1
                    continue
                features.append([_to_float(row.get(column)) or 0.0 for column in feature_columns])
                targets.append(target)
    return np.array(features, dtype=float), np.array(targets, dtype=float), skipped


def _constant_model(
    *,
    target_mean: float,
    feature_columns: Sequence[str],
    target_column: str,
    training_row_count: int,
    warnings: Sequence[str],
) -> dict[str, Any]:
    return {
        "model_type": "constant_mean_v1",
        "feature_columns": list(feature_columns),
        "target_column": target_column,
        "bias": float(target_mean),
        "weights": [0.0 for _ in feature_columns],
        "training_row_count": int(training_row_count),
        "warnings": list(warnings),
        "metadata": dict(MODEL_METADATA),
    }


def _linear_model(
    *,
    x: np.ndarray,
    y: np.ndarray,
    feature_columns: Sequence[str],
    target_column: str,
    warnings: Sequence[str],
) -> dict[str, Any]:
    design = np.column_stack([np.ones(x.shape[0]), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    return {
        "model_type": "linear_regression_v1",
        "feature_columns": list(feature_columns),
        "target_column": target_column,
        "bias": float(coefficients[0]),
        "weights": [float(value) for value in coefficients[1:]],
        "training_row_count": int(x.shape[0]),
        "warnings": list(warnings),
        "metadata": dict(MODEL_METADATA),
    }


def train_equivalence_model(
    csv_paths: Iterable[str | Path],
    *,
    model_path: str | Path | None = None,
    feature_columns: Sequence[str] = DEFAULT_FEATURE_COLUMNS,
    target_column: str = DEFAULT_TARGET_COLUMN,
    min_rows: int = 3,
) -> dict[str, Any]:
    """Train and optionally save a simple equivalence-volume predictor."""

    x, y, skipped = _read_training_examples(
        csv_paths,
        feature_columns=feature_columns,
        target_column=target_column,
    )
    if y.size == 0:
        raise ValueError(f"no labeled rows found in target column {target_column!r}")

    warnings: list[str] = []
    if skipped:
        warnings.append(f"Skipped {skipped} rows without numeric {target_column}.")

    if y.size < min_rows:
        warnings.append(
            f"Sparse labeled data: {y.size} row(s) < min_rows={min_rows}; using constant mean model."
        )
        model = _constant_model(
            target_mean=float(y.mean()),
            feature_columns=feature_columns,
            target_column=target_column,
            training_row_count=int(y.size),
            warnings=warnings,
        )
    else:
        if y.size < len(feature_columns) + 1:
            warnings.append(
                f"Sparse labeled data: {y.size} rows for {len(feature_columns)} features; treat regression as provisional."
            )
        model = _linear_model(
            x=x,
            y=y,
            feature_columns=feature_columns,
            target_column=target_column,
            warnings=warnings,
        )

    if model_path is not None:
        output = Path(model_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(model, indent=2, sort_keys=True), encoding="utf-8")
    return model


def _parse_feature_columns(raw: str | None) -> Sequence[str]:
    if raw is None:
        return DEFAULT_FEATURE_COLUMNS
    columns = [item.strip() for item in raw.split(",") if item.strip()]
    if not columns:
        raise ValueError("--features must contain at least one column name")
    return columns


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a simple equivalence-volume model from titration CSV data.")
    parser.add_argument("csv", nargs="+", help="Labeled CSV file(s)")
    parser.add_argument("--model", default="data/labeled/equivalence-model.json", help="Output JSON model path")
    parser.add_argument("--features", help="Comma-separated feature columns; defaults to camera/pump schema fields")
    parser.add_argument("--target", default=DEFAULT_TARGET_COLUMN, help="Target column")
    parser.add_argument("--min-rows", type=int, default=3, help="Rows required before fitting linear regression")
    args = parser.parse_args()

    model = train_equivalence_model(
        args.csv,
        model_path=args.model,
        feature_columns=_parse_feature_columns(args.features),
        target_column=args.target,
        min_rows=args.min_rows,
    )
    print(f"saved model: {args.model}")
    for warning in model["warnings"]:
        print(f"warning: {warning}")


if __name__ == "__main__":
    main()
