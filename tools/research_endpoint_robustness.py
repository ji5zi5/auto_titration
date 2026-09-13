#!/usr/bin/env python3
"""Dry replay robustness study for the deployed post-run endpoint model."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    generate_union_candidates,
    load_type_conditioned_sensor_model,
)
from tools.research_endpoint_ensemble_strategies import (  # noqa: E402
    aggregate_predictions,
    predict_pair,
)


DEFAULT_MODEL = ROOT / "data/labeled/type-conditioned-sensor-endpoint-ranker.pkl"
DEFAULT_RUNS = ROOT / "머신러닝용 파일모음"
DEFAULT_OUTPUT = ROOT / "data/labeled/type-conditioned-sensor-endpoint-robustness.json"
STRATEGIES = (
    "single_full_fit",
    "fold_median",
    "fixed_half_full_half_median",
)


def clone_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def thin(rows: Sequence[Mapping[str, Any]], step: int) -> list[dict[str, Any]]:
    output = clone_rows(rows[::step])
    if rows and output[-1] != rows[-1]:
        output.append(dict(rows[-1]))
    return output


def duplicate(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows for _ in range(2)]


def thermal_dropout(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = clone_rows(rows)
    for row in output:
        row["thermal_raw_roi_p50"] = ""
        row["thermal_raw_roi_p95"] = ""
    return output


def visible_dropout(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = clone_rows(rows)
    for row in output:
        row["visible_H_mean"] = ""
        row["visible_S_mean"] = ""
        row["visible_V_mean"] = ""
    return output


def thermal_zero_burst(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = clone_rows(rows)
    lo, hi = int(len(output) * 0.4), int(len(output) * 0.55)
    for row in output[lo:hi]:
        row["thermal_raw_roi_p50"] = 0
        row["thermal_raw_roi_p95"] = 0
    return output


def thermal_spikes(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = clone_rows(rows)
    for index in range(11, len(output), 23):
        sign = -1.0 if (index // 23) % 2 else 1.0
        for key in ("thermal_raw_roi_p50", "thermal_raw_roi_p95"):
            try:
                output[index][key] = float(output[index].get(key) or 0.0) + sign * 500.0
            except (TypeError, ValueError):
                pass
    return output


def visible_small_noise(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = clone_rows(rows)
    for index, row in enumerate(output):
        phase = math.sin(index * 0.73)
        for key, scale in (
            ("visible_H_mean", 0.8),
            ("visible_S_mean", 0.004),
            ("visible_V_mean", 0.004),
        ):
            try:
                row[key] = float(row.get(key) or 0.0) + phase * scale
            except (TypeError, ValueError):
                pass
    return output


def prefix(rows: Sequence[Mapping[str, Any]], fraction: float) -> list[dict[str, Any]]:
    return clone_rows(rows[: max(40, int(len(rows) * fraction))])


PERTURBATIONS: dict[str, Callable[[Sequence[Mapping[str, Any]]], list[dict[str, Any]]]] = {
    "identity": clone_rows,
    "thin_2x": lambda rows: thin(rows, 2),
    "thin_3x": lambda rows: thin(rows, 3),
    "duplicate_2x": duplicate,
    "thermal_dropout": thermal_dropout,
    "visible_dropout": visible_dropout,
    "thermal_zero_burst": thermal_zero_burst,
    "thermal_spikes": thermal_spikes,
    "visible_small_noise": visible_small_noise,
    "prefix_90pct": lambda rows: prefix(rows, 0.90),
}


def predict_strategies(
    artifact: Mapping[str, Any],
    run: CsvRun,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    candidates = generate_union_candidates(rows)
    if not candidates:
        raise ValueError("no candidates")
    entry = artifact["models"][run.titration_type]
    config = entry["config"]
    replay_run = replace(run, rows=list(rows))
    full = predict_pair(entry, replay_run, candidates, config)
    folds = [
        predict_pair(fold, replay_run, candidates, config)
        for fold in entry["fold_estimators"]
    ]
    return aggregate_predictions(full, folds)


def summarize(rows: Sequence[Mapping[str, Any]], strategy: str) -> dict[str, Any]:
    valid = [row for row in rows if strategy in row.get("predictions", {})]
    errors = [
        abs(float(row["predictions"][strategy]) - float(row["actual_ml"]))
        for row in valid
    ]
    drifts = [float(row["drift_ml"][strategy]) for row in valid]
    return {
        "success_count": len(valid),
        "failure_count": len(rows) - len(valid),
        "mape_percent": statistics.mean(
            error / float(row["actual_ml"]) * 100.0
            for error, row in zip(errors, valid)
        )
        if valid
        else None,
        "mae_ml": statistics.mean(errors) if errors else None,
        "mean_abs_drift_ml": statistics.mean(abs(value) for value in drifts)
        if drifts
        else None,
        "max_abs_drift_ml": max((abs(value) for value in drifts), default=None),
    }


def run_research(model_path: Path, runs_dir: Path) -> dict[str, Any]:
    artifact = load_type_conditioned_sensor_model(model_path)
    if artifact is None:
        raise FileNotFoundError(model_path)
    runs = load_runs(runs_dir)
    baseline = {
        run.path.name: predict_strategies(artifact, run, run.rows) for run in runs
    }
    details = []
    for name, transform in PERTURBATIONS.items():
        for run in runs:
            transformed = transform(run.rows)
            record = {
                "perturbation": name,
                "run": run.path.name,
                "titration_type": run.titration_type,
                "row_count": len(transformed),
                "actual_ml": float(run.theoretical_equivalence_volume_ml),
                "predictions": {},
                "drift_ml": {},
                "error": "",
            }
            try:
                predictions = predict_strategies(artifact, run, transformed)
                record["predictions"] = {
                    key: predictions[key] for key in STRATEGIES
                }
                record["drift_ml"] = {
                    key: predictions[key] - baseline[run.path.name][key]
                    for key in STRATEGIES
                }
            except Exception as exc:  # noqa: BLE001 - failure is study output.
                record["error"] = f"{type(exc).__name__}: {exc}"
            details.append(record)
    summary = {
        perturbation: {
            strategy: summarize(
                [row for row in details if row["perturbation"] == perturbation],
                strategy,
            )
            for strategy in STRATEGIES
        }
        for perturbation in PERTURBATIONS
    }
    non_dropout = [
        name
        for name in PERTURBATIONS
        if name not in {"identity", "thermal_dropout", "visible_dropout"}
    ]
    aggregate_robustness = {}
    for strategy in STRATEGIES:
        cells = [summary[name][strategy] for name in non_dropout]
        aggregate_robustness[strategy] = {
            "mean_perturbed_mape_percent": statistics.mean(
                float(cell["mape_percent"]) for cell in cells if cell["mape_percent"] is not None
            ),
            "mean_abs_drift_ml": statistics.mean(
                float(cell["mean_abs_drift_ml"])
                for cell in cells
                if cell["mean_abs_drift_ml"] is not None
            ),
            "worst_abs_drift_ml": max(
                float(cell["max_abs_drift_ml"])
                for cell in cells
                if cell["max_abs_drift_ml"] is not None
            ),
            "total_failures": sum(int(cell["failure_count"]) for cell in cells),
        }
    return {
        "schema_version": "endpoint_dry_replay_robustness_v1",
        "perturbations": list(PERTURBATIONS),
        "strategies": list(STRATEGIES),
        "summary": summary,
        "aggregate_non_dropout_robustness": aggregate_robustness,
        "details": details,
        "interpretation": (
            "Synthetic replay perturbations test software sensitivity, not wet-chemistry accuracy. "
            "Complete sensor dropout is reported separately and may legitimately invoke site fallback."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--runs", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_research(args.model, args.runs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
