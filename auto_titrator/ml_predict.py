"""Predict equivalence volume from a saved simple JSON model."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Mapping


PREDICTION_COLUMN = "predicted_equivalence_volume_ml"
PREDICTED_CONCENTRATION_COLUMN = "sample_concentration_from_predicted_equivalence_M"
PREDICTED_CONCENTRATION_ERROR_COLUMN = "predicted_sample_concentration_error_percent"


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_float_or_none(value: Any, *, default: float | None = None) -> float | None:
    if value is None or value == "":
        value = default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not number > 0:
        return None
    return number


def concentration_from_equivalence_volume(row: Mapping[str, Any], equivalence_volume_ml: float) -> float | None:
    """Calculate sample concentration from a predicted equivalence volume."""

    volume = _positive_float_or_none(equivalence_volume_ml)
    titrant_concentration = _positive_float_or_none(row.get("titrant_concentration_M"))
    titrant_valence = _positive_float_or_none(row.get("titrant_valence"), default=1.0)
    sample_volume = _positive_float_or_none(row.get("sample_volume_ml"))
    sample_valence = _positive_float_or_none(row.get("sample_valence"), default=1.0)
    if None in (volume, titrant_concentration, titrant_valence, sample_volume, sample_valence):
        return None
    return titrant_concentration * volume * titrant_valence / (sample_volume * sample_valence)


def concentration_error_percent(calculated: float | None, reference: Any) -> float | None:
    value = _positive_float_or_none(calculated)
    expected = _positive_float_or_none(reference)
    if value is None or expected is None:
        return None
    return (value - expected) / expected * 100.0


def load_model(path: str | Path) -> dict[str, Any]:
    """Load a model created by `ml_train.train_equivalence_model`."""

    model = json.loads(Path(path).read_text(encoding="utf-8"))
    if "feature_columns" not in model:
        raise ValueError("model is missing feature_columns")
    if "weights" not in model or "bias" not in model:
        raise ValueError("regression model is missing required fields")
    if len(model["feature_columns"]) != len(model["weights"]):
        raise ValueError("model feature_columns and weights lengths differ")
    return model


def load_optional_model(path: str | Path | None) -> dict[str, Any] | None:
    """Load a model only if it exists; return None while labeled data is absent."""

    if path is None:
        return None
    model_path = Path(path)
    if not model_path.exists():
        return None
    return load_model(model_path)


def predict_equivalence_volume(model: Mapping[str, Any], row: Mapping[str, Any]) -> float:
    """Predict ideal/reference equivalence volume in mL for one feature row."""

    total = float(model["bias"])
    for column, weight in zip(model["feature_columns"], model["weights"]):
        total += float(weight) * _to_float(row.get(column))
    return float(total)


def predict_row(model: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of `row` with schema prediction field filled."""

    predicted = dict(row)
    predicted_volume = predict_equivalence_volume(model, row)
    predicted[PREDICTION_COLUMN] = round(predicted_volume, 6)
    predicted_concentration = concentration_from_equivalence_volume(row, predicted_volume)
    if predicted_concentration is not None:
        predicted[PREDICTED_CONCENTRATION_COLUMN] = round(predicted_concentration, 8)
        error = concentration_error_percent(predicted_concentration, row.get("sample_concentration_M"))
        if error is not None:
            predicted[PREDICTED_CONCENTRATION_ERROR_COLUMN] = round(error, 6)
    return predicted


def predict_csv(*, model_path: str | Path, input_path: str | Path, output_path: str | Path) -> Path:
    """Add `predicted_equivalence_volume_ml` to every row in a CSV file."""

    model = load_model(model_path)
    input_file = Path(input_path)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with input_file.open(newline="", encoding="utf-8") as src:
        reader = csv.DictReader(src)
        fieldnames = list(reader.fieldnames or [])
        for column in (
            PREDICTION_COLUMN,
            PREDICTED_CONCENTRATION_COLUMN,
            PREDICTED_CONCENTRATION_ERROR_COLUMN,
        ):
            if column not in fieldnames:
                fieldnames.append(column)
        with output_file.open("w", newline="", encoding="utf-8") as dst:
            writer = csv.DictWriter(dst, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                writer.writerow(predict_row(model, row))
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Predict equivalence volume for rows in a titration CSV.")
    parser.add_argument("--model", required=True, help="JSON model from auto_titrator.ml_train")
    parser.add_argument("--input", required=True, help="Input CSV path")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    output = predict_csv(model_path=args.model, input_path=args.input, output_path=args.output)
    print(f"saved predictions: {output}")


if __name__ == "__main__":
    main()
