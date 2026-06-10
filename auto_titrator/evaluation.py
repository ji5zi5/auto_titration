"""Evaluate color endpoint and ML equivalence-volume prediction errors."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable


REFERENCE_COLUMN = "reference_equivalence_volume_ml"
COLOR_ENDPOINT_COLUMN = "observed_color_endpoint_volume_ml"
ML_PREDICTION_COLUMN = "predicted_equivalence_volume_ml"


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(items) / len(items)


def compute_error_metrics(csv_path: str | Path) -> dict[str, Any]:
    """Compute absolute mL error metrics against reference equivalence volume."""

    color_errors: list[float] = []
    ml_errors: list[float] = []
    row_count = 0

    with Path(csv_path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            row_count += 1
            reference = _to_float(row.get(REFERENCE_COLUMN))
            if reference is None:
                continue

            color_endpoint = _to_float(row.get(COLOR_ENDPOINT_COLUMN))
            if color_endpoint is not None:
                color_errors.append(abs(color_endpoint - reference))

            ml_prediction = _to_float(row.get(ML_PREDICTION_COLUMN))
            if ml_prediction is not None:
                ml_errors.append(abs(ml_prediction - reference))

    mean_color = _mean(color_errors)
    mean_ml = _mean(ml_errors)
    improvement = None
    if mean_color is not None and mean_ml is not None:
        improvement = mean_color - mean_ml

    return {
        "row_count": row_count,
        "color_endpoint_error_count": len(color_errors),
        "ml_prediction_error_count": len(ml_errors),
        "mean_abs_color_endpoint_error_ml": mean_color,
        "mean_abs_ml_prediction_error_ml": mean_ml,
        "mean_abs_error_improvement_ml": improvement,
    }


def write_metrics_json(csv_path: str | Path, output_path: str | Path) -> Path:
    """Write evaluation metrics JSON and return the output path."""

    metrics = compute_error_metrics(csv_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate color endpoint and ML prediction errors.")
    parser.add_argument("csv", help="CSV containing reference, color endpoint, and prediction columns")
    parser.add_argument("--output", default="data/labeled/evaluation-metrics.json", help="Output metrics JSON path")
    args = parser.parse_args()

    output = write_metrics_json(args.csv, args.output)
    print(f"saved metrics: {output}")


if __name__ == "__main__":
    main()
