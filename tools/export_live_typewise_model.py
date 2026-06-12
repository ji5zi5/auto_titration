#!/usr/bin/env python3
"""Export the current typewise frame-zone classifier as a live sklearn artifact."""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sklearn.base import clone  # type: ignore[reportMissingImports]
from sklearn.feature_extraction import DictVectorizer  # type: ignore[reportMissingImports]
from sklearn.impute import SimpleImputer  # type: ignore[reportMissingImports]
from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]

from auto_titrator.ml_typewise_eval import load_runs  # noqa: E402
from tools.train_equivalence_current_volume import (  # noqa: E402
    ALLOWED_CATEGORICAL_EXACT,
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    RANDOM_STATE,
    build_frame_records,
    frame_model_specs,
)

DEFAULT_OUTPUT = Path("data/labeled/typewise-current-volume-classifier.pkl")


def _parse_selected_method(method_key: str) -> dict[str, Any]:
    parts = method_key.split(":")
    if len(parts) < 4 or parts[0] != "frame_zone_classifier":
        raise ValueError(f"unsupported selected method key: {method_key}")
    model_name = parts[1]
    rest = parts[2:]
    scope = "all_types"
    if rest and rest[0] in {"all_types", "same_type"}:
        scope = rest.pop(0)
    if len(rest) < 2:
        raise ValueError(f"cannot parse selected method key: {method_key}")
    window_part = rest.pop(0)
    match = re.fullmatch(r"window([0-9]+(?:\.[0-9]+)?)", window_part)
    if not match:
        raise ValueError(f"cannot parse window in selected method key: {method_key}")
    return {
        "model_name": model_name,
        "scope": scope,
        "window_ml": float(match.group(1)),
        "aggregate_mode": ":".join(rest),
    }


def _model_spec_by_name(name: str, train_size: int):
    specs = dict(frame_model_specs("classifier", train_size))
    if name not in specs:
        raise ValueError(f"unknown classifier model spec: {name}")
    return specs[name]


def _fit_pipeline(model_spec: Any, feature_rows: Sequence[Mapping[str, Any]], labels: np.ndarray):
    pipeline = make_pipeline(DictVectorizer(sparse=False), SimpleImputer(strategy="median"), clone(model_spec))
    pipeline.fit(list(feature_rows), labels)
    return pipeline


def export_model(*, input_dir: str | Path, summary_path: str | Path, output_path: str | Path, grid_ml: float) -> Path:
    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    selector = summary.get("typewise_development_selector") or {}
    selection = selector.get("selection") or {}
    if not isinstance(selection, dict) or not selection:
        raise ValueError("summary does not contain typewise_development_selector.selection")

    runs = load_runs(input_dir)
    records, feature_columns = build_frame_records(runs, grid_ml=grid_ml)
    feature_columns = list(feature_columns)
    models: dict[str, dict[str, Any]] = {}

    for titration_type, selected in sorted(selection.items()):
        method_key = str(selected.get("selected_method_key") or "")
        parsed = _parse_selected_method(method_key)
        train_records = list(records)
        if parsed["scope"] == "same_type":
            train_records = [record for record in train_records if record["titration_type"] == titration_type]
        if not train_records:
            raise ValueError(f"no training records for {titration_type}")
        labels = np.array(
            [abs(float(record["current_volume_ml"]) - float(record["actual_ml"])) <= float(parsed["window_ml"]) for record in train_records],
            dtype=int,
        )
        if len(set(labels.tolist())) < 2:
            raise ValueError(f"training labels have one class only for {titration_type}")
        model_spec = _model_spec_by_name(str(parsed["model_name"]), len(train_records))
        pipeline = _fit_pipeline(model_spec, [record["features"] for record in train_records], labels)
        models[titration_type] = {
            "estimator": pipeline,
            "selected_method_key": method_key,
            "model_name": parsed["model_name"],
            "scope": parsed["scope"],
            "window_ml": parsed["window_ml"],
            "aggregate_mode": parsed["aggregate_mode"],
            "development_mape_percent": selected.get("mape_percent_on_available_type_runs"),
            "development_mae_ml": selected.get("mae_ml_on_available_type_runs"),
            "training_record_count": len(train_records),
            "positive_label_count": int(labels.sum()),
            "negative_label_count": int(len(labels) - labels.sum()),
        }

    artifact = {
        "artifact_type": "typewise_frame_zone_classifier_v1",
        "random_state": RANDOM_STATE,
        "input_dir": str(input_dir),
        "source_summary": str(summary_path),
        "feature_columns": feature_columns,
        "categorical_columns": sorted(ALLOWED_CATEGORICAL_EXACT),
        "models": models,
        "leakage_policy": summary.get("leakage_policy", {}),
        "caveat": selector.get("caveat", "development-set typewise model selection; not independent external validation"),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        pickle.dump(artifact, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--summary", default=str(DEFAULT_OUTPUT_DIR / "summary.json"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--volume-grid-ml", type=float, default=0.25)
    args = parser.parse_args(argv)
    output = export_model(input_dir=args.input_dir, summary_path=args.summary, output_path=args.output, grid_ml=args.volume_grid_ml)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
