#!/usr/bin/env python3
"""Compare fixed endpoint deployment ensembles without frame-level leakage.

The script keeps the already selected per-titration configurations frozen and
compares only a small, predeclared set of deployment aggregation strategies.
Every nested prediction for a June test run is produced by models that did not
fit that run.  July runs have no standardized truth and are used for
repeatability and fold-dispersion diagnostics only.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    _aggregate_boundary,
    _combined_candidate_scores,
    generate_union_candidates,
    load_type_conditioned_sensor_model,
)
from tools.type_conditioned_sensor_sequence_search import (  # noqa: E402
    TYPE_CONFIGS,
    TypeConditionedConfig,
    aggregate_boundary,
    candidate_scores,
    fit_candidate_scorer,
    normalize_scores,
)


DEFAULT_MODEL = ROOT / "data/labeled/type-conditioned-sensor-endpoint-ranker.pkl"
DEFAULT_JUNE = ROOT / "머신러닝용 파일모음"
DEFAULT_JULY = ROOT / "Downloads.zip"
DEFAULT_OUTPUT = ROOT / "data/labeled/type-conditioned-sensor-endpoint-strategy-research.json"
JULY_RUNS = (
    "auto-titration-live-20260726-150424-session-5.csv",
    "auto-titration-live-20260726-151233-session-7.csv",
    "auto-titration-live-20260726-151632-session-8.csv",
)


def fit_pair(
    train_runs: Sequence[CsvRun],
    candidate_sets: Mapping[str, Sequence[Any]],
    config: TypeConditionedConfig,
    titration_type: str,
) -> dict[str, Any]:
    global_estimator = (
        fit_candidate_scorer(train_runs, candidate_sets, config)
        if config.global_weight > 0.0
        else None
    )
    type_estimator = None
    if config.global_weight < 1.0:
        type_runs = [run for run in train_runs if run.titration_type == titration_type]
        if not type_runs:
            raise ValueError(f"no type training runs for {titration_type}")
        type_estimator = fit_candidate_scorer(type_runs, candidate_sets, config)
    return {
        "global_estimator": global_estimator,
        "type_estimator": type_estimator,
    }


def predict_pair(
    pair: Mapping[str, Any],
    run: CsvRun,
    candidates: Sequence[Any],
    config: TypeConditionedConfig | Mapping[str, Any],
) -> float:
    if isinstance(config, TypeConditionedConfig):
        scores = np.zeros(len(candidates), dtype=float)
        if config.global_weight > 0.0:
            scores += config.global_weight * normalize_scores(
                candidate_scores(pair["global_estimator"], candidates, config),
                config.score_normalization,
            )
        if config.global_weight < 1.0:
            scores += (1.0 - config.global_weight) * normalize_scores(
                candidate_scores(pair["type_estimator"], candidates, config),
                config.score_normalization,
            )
        frame, _, _ = aggregate_boundary(candidates, scores, config)
    else:
        scores = _combined_candidate_scores(pair, candidates, config)
        frame, _, _ = _aggregate_boundary(candidates, scores, config)
    frame = max(0, min(int(frame), len(run.rows) - 1))
    return float(run.rows[frame]["injected_volume_ml"])


def aggregate_predictions(full: float, folds: Sequence[float]) -> dict[str, float]:
    values = np.asarray(folds, dtype=float)
    ordered = np.sort(values)
    trimmed = ordered[1:-1] if len(ordered) > 2 else ordered
    median = float(np.median(values))
    mean = float(np.mean(values))
    return {
        "single_full_fit": float(full),
        "fold_median": median,
        "fold_mean": mean,
        "fold_trimmed_mean": float(np.mean(trimmed)),
        "fixed_half_full_half_median": 0.5 * float(full) + 0.5 * median,
        "fixed_quarter_full_three_quarter_median": 0.25 * float(full) + 0.75 * median,
    }


def metrics(rows: Sequence[Mapping[str, float]], key: str) -> dict[str, float]:
    signed = [float(row[key]) - float(row["actual_ml"]) for row in rows]
    absolute = [abs(value) for value in signed]
    ape = [
        error / float(row["actual_ml"]) * 100.0
        for error, row in zip(absolute, rows)
    ]
    return {
        "mae_ml": statistics.mean(absolute),
        "rmse_ml": statistics.mean(value * value for value in signed) ** 0.5,
        "mape_percent": statistics.mean(ape),
        "max_abs_error_ml": max(absolute),
        "max_ape_percent": max(ape),
        "bias_ml": statistics.mean(signed),
    }


def coefficient_of_variation(values: Sequence[float]) -> float:
    return statistics.stdev(values) / statistics.mean(values) * 100.0


def run_research(
    *,
    model_path: Path,
    june_dir: Path,
    july_archive: Path,
) -> dict[str, Any]:
    artifact = load_type_conditioned_sensor_model(model_path)
    if artifact is None:
        raise FileNotFoundError(model_path)
    june_runs = load_runs(june_dir)
    if len(june_runs) != 12:
        raise ValueError(f"expected 12 June runs, got {len(june_runs)}")
    candidates = {
        str(run.path): generate_union_candidates(run.rows) for run in june_runs
    }

    nested_rows = []
    type_only_rows = []
    for test in june_runs:
        config = TYPE_CONFIGS[test.titration_type]
        outer_train = [run for run in june_runs if run.path != test.path]
        outer_pair = fit_pair(outer_train, candidates, config, test.titration_type)
        outer_prediction = predict_pair(
            outer_pair, test, candidates[str(test.path)], config
        )
        inner_predictions = []
        for omitted in outer_train:
            inner_train = [run for run in outer_train if run.path != omitted.path]
            inner_pair = fit_pair(
                inner_train, candidates, config, test.titration_type
            )
            inner_predictions.append(
                predict_pair(inner_pair, test, candidates[str(test.path)], config)
            )
        strategy_values = aggregate_predictions(outer_prediction, inner_predictions)
        nested_rows.append(
            {
                "run": test.path.name,
                "titration_type": test.titration_type,
                "actual_ml": float(test.theoretical_equivalence_volume_ml),
                "fold_sd_ml": statistics.stdev(inner_predictions),
                **strategy_values,
            }
        )

        same_type_train = [
            run
            for run in outer_train
            if run.titration_type == test.titration_type
        ]
        type_estimator = fit_candidate_scorer(same_type_train, candidates, config)
        type_scores = normalize_scores(
            candidate_scores(type_estimator, candidates[str(test.path)], config),
            config.score_normalization,
        )
        type_frame, _, _ = aggregate_boundary(
            candidates[str(test.path)], type_scores, config
        )
        type_frame = max(0, min(type_frame, len(test.rows) - 1))
        type_only_rows.append(
            {
                "actual_ml": float(test.theoretical_equivalence_volume_ml),
                "same_type_only": float(test.rows[type_frame]["injected_volume_ml"]),
            }
        )

    strategy_names = [
        key
        for key in nested_rows[0]
        if key
        not in {"run", "titration_type", "actual_ml", "fold_sd_ml"}
    ]
    nested_metrics = {key: metrics(nested_rows, key) for key in strategy_names}
    type_only_metrics = metrics(type_only_rows, "same_type_only")

    replay_rows = []
    for run in june_runs:
        entry = artifact["models"][run.titration_type]
        config = entry["config"]
        run_candidates = candidates[str(run.path)]
        full = predict_pair(entry, run, run_candidates, config)
        fold_values = [
            predict_pair(fold, run, run_candidates, config)
            for fold in entry["fold_estimators"]
        ]
        replay_rows.append(
            {
                "run": run.path.name,
                "titration_type": run.titration_type,
                "actual_ml": float(run.theoretical_equivalence_volume_ml),
                "fold_sd_ml": statistics.stdev(fold_values),
                **aggregate_predictions(full, fold_values),
            }
        )
    replay_metrics = {key: metrics(replay_rows, key) for key in strategy_names}

    with tempfile.TemporaryDirectory(prefix="endpoint_strategy_july_") as temp:
        with zipfile.ZipFile(july_archive) as archive:
            archive.extractall(temp)
        available = {run.path.name: run for run in load_runs(temp)}
        july_rows = []
        for name in JULY_RUNS:
            run = available[name]
            run_candidates = generate_union_candidates(run.rows)
            entry = artifact["models"][run.titration_type]
            config = entry["config"]
            full = predict_pair(entry, run, run_candidates, config)
            fold_values = [
                predict_pair(fold, run, run_candidates, config)
                for fold in entry["fold_estimators"]
            ]
            endpoints = aggregate_predictions(full, fold_values)
            concentrations = {
                key: float(run.rows[0]["titrant_concentration_M"])
                * value
                / float(run.rows[0]["sample_volume_ml"])
                for key, value in endpoints.items()
            }
            july_rows.append(
                {
                    "run": name,
                    "fold_sd_ml": statistics.stdev(fold_values),
                    "endpoint_ml": endpoints,
                    "concentration_M": concentrations,
                }
            )
    july_repeatability = {
        key: {
            "mean_M": statistics.mean(
                row["concentration_M"][key] for row in july_rows
            ),
            "sample_sd_M": statistics.stdev(
                row["concentration_M"][key] for row in july_rows
            ),
            "cv_percent": coefficient_of_variation(
                [row["concentration_M"][key] for row in july_rows]
            ),
        }
        for key in strategy_names
    }

    # July was already inspected and has no truth reference.  It remains
    # descriptive and cannot select the deployment strategy.
    selected = min(
        strategy_names,
        key=lambda key: (
            nested_metrics[key]["mape_percent"],
            nested_metrics[key]["max_ape_percent"],
        ),
    )
    return {
        "schema_version": "endpoint_deployment_strategy_research_v1",
        "selection_policy": (
            "Among predeclared strategies, minimize nested run-level MAPE and then "
            "nested maximum APE. June replay and July repeatability are descriptive "
            "and do not participate in selection."
        ),
        "july_usage": "descriptive_repeatability_only_not_model_selection",
        "selected_strategy": selected,
        "nested_run_level_metrics": nested_metrics,
        "same_type_only_loro_metrics": type_only_metrics,
        "deployment_replay_metrics": replay_metrics,
        "july_repeatability": july_repeatability,
        "nested_rows": nested_rows,
        "deployment_replay_rows": replay_rows,
        "july_rows": july_rows,
        "limitations": [
            "The four per-type estimator configurations were selected on the same June development set.",
            "June replay metrics are not independent accuracy estimates.",
            "July truth concentration was not standardized; July supports repeatability only.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--june", type=Path, default=DEFAULT_JUNE)
    parser.add_argument("--july", type=Path, default=DEFAULT_JULY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_research(
        model_path=args.model,
        june_dir=args.june,
        july_archive=args.july,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
