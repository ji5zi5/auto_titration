#!/usr/bin/env python3
"""Reproduce the same-12-run post-hoc dense-aggregation development result.

Inference uses five sensor sequences plus pre-known titration_type routing only.
Every held-out run is excluded from every scaler/model fit. Configuration
selection was nevertheless performed post hoc on these same 12 outer-LORO
development outcomes, so this is not independent external validation.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "data/ml/dense_type_conditioned_sensor_ranker_reproduction"
sys.path.insert(0, str(REPO))

from auto_titrator.ml_typewise_eval import load_runs  # noqa: E402
from tools import search_advanced_type_conditioned_sensor_rankers as rankers  # noqa: E402
from tools.sensor_transition_candidate_union import (  # noqa: E402
    feature_names,
    generate_union_candidates,
)

SEEDS = (42, 1729, 20260728)
REFERENCE_MAPE_PERCENT = 0.359791
INITIAL_CONFIGURATION_COUNT = 1_006_020
DENSE_CONFIGURATION_COUNT = 1_024_350
TOTAL_CONFIGURATION_COUNT = (
    INITIAL_CONFIGURATION_COUNT + DENSE_CONFIGURATION_COUNT
)
SENSOR_COLUMNS = (
    "visible_H_mean",
    "visible_S_mean",
    "visible_V_mean",
    "thermal_raw_roi_p50",
    "thermal_raw_roi_p95",
)
FORBIDDEN_INPUTS = (
    "sample_concentration_M",
    "injected_volume_ml",
    "theoretical_equivalence_volume_ml",
    "time_s",
    "progress_fraction",
    "indicator",
)
FORBIDDEN_FEATURE_TOKENS = (
    "volume", "concentration", "endpoint", "equivalence", "time",
    "progress", "indicator", "frame", "position", "target", "label",
)


@dataclass(frozen=True)
class FrozenConfig:
    spec: rankers.Spec
    normalization: str
    global_weight: float
    top_k: int
    temperature: float
    top_blend: float = 0.0


CONFIGS = {
    "strong_acid_strong_base": FrozenConfig(
        rankers.Spec("pls", "state", "signed_log1p", "exp_rank@2"),
        "zscore", 1.0, 0, 1.0,
    ),
    "weak_acid_strong_base": FrozenConfig(
        rankers.Spec("lda", "shift_terminal", "raw", "5@svd"),
        "rank", 0.64, 26, 0.2,
    ),
    "strong_acid_weak_base": FrozenConfig(
        rankers.Spec(
            "kernel_ridge_rbf", "shift_terminal", "signed_log1p",
            "rank@1,0.05",
        ),
        "rank", 1.0, 0, 0.1,
    ),
    "weak_acid_weak_base": FrozenConfig(
        rankers.Spec("qda", "shift_terminal", "raw", "5@0.9"),
        "zscore", 1.0, 5, 0.1,
    ),
}


def metrics(rows):
    actual = np.asarray([row["actual_ml"] for row in rows], dtype=float)
    predicted = np.asarray([row["predicted_ml"] for row in rows], dtype=float)
    error = predicted - actual
    return {
        "mae_ml": float(np.mean(np.abs(error))),
        "rmse_ml": float(np.sqrt(np.mean(error * error))),
        "mape_percent": float(np.mean(np.abs(error) / actual) * 100.0),
        "max_absolute_error_ml": float(np.max(np.abs(error))),
    }


def write_csv(path, rows):
    columns = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    runs = load_runs(REPO / "머신러닝용 파일모음")
    if len(runs) != 12:
        raise AssertionError(f"expected exactly 12 development runs, got {len(runs)}")
    if set(CONFIGS) != {run.titration_type for run in runs}:
        raise AssertionError("titration-type routing table does not cover the data")

    candidate_sets = {
        str(run.path): generate_union_candidates(run.rows) for run in runs
    }

    # Directly prove candidate generation is invariant to every forbidden field.
    metadata_invariance = {}
    for run in runs:
        changed = copy.deepcopy(run.rows)
        for index, row in enumerate(changed):
            row.update({
                "sample_concentration_M": 9.9,
                "injected_volume_ml": 9999.0 - index,
                "theoretical_equivalence_volume_ml": -123.0,
                "time_s": 10000.0 + index,
                "progress_fraction": -index,
                "indicator": "PERTURBED",
            })
        unchanged = generate_union_candidates(changed) == candidate_sets[str(run.path)]
        metadata_invariance[run.path.name] = unchanged
    if not all(metadata_invariance.values()):
        raise AssertionError("forbidden metadata changed sensor candidates")

    exact_rows = []
    for test in runs:
        config = CONFIGS[test.titration_type]
        outer_train = [run for run in runs if run.path != test.path]
        if any(run.path == test.path for run in outer_train):
            raise AssertionError("outer test leaked into global fit")
        candidates = candidate_sets[str(test.path)]

        global_scores = rankers.score_one(
            outer_train, candidates, candidate_sets, config.spec
        )
        global_fit_paths = [str(run.path) for run in outer_train]
        type_fit_paths = []
        if config.global_weight < 1.0:
            type_train = [
                run for run in outer_train
                if run.titration_type == test.titration_type
            ]
            if any(run.path == test.path for run in type_train):
                raise AssertionError("outer test leaked into type fit")
            type_scores = rankers.score_one(
                type_train, candidates, candidate_sets, config.spec
            )
            type_fit_paths = [str(run.path) for run in type_train]
        else:
            type_scores = np.zeros_like(global_scores)

        scores = (
            config.global_weight
            * rankers.normalize(global_scores, config.normalization)
            + (1.0 - config.global_weight)
            * rankers.normalize(type_scores, config.normalization)
        )
        frame = rankers.aggregate(
            candidates,
            scores,
            (config.top_k, config.temperature, config.top_blend),
        )
        frame = max(0, min(frame, len(test.rows) - 1))

        # Volume and truth are first read after sensor-only frame localization.
        predicted = float(test.rows[frame]["injected_volume_ml"])
        actual = float(test.theoretical_equivalence_volume_ml)
        exact_rows.append({
            "run_name": test.path.name,
            "titration_type": test.titration_type,
            "actual_ml": actual,
            "predicted_ml": predicted,
            "signed_error_ml": predicted - actual,
            "absolute_error_ml": abs(predicted - actual),
            "ape_percent": abs(predicted - actual) / actual * 100.0,
            "selected_frame_audit_only": frame,
            "global_fit_paths": json.dumps(global_fit_paths, ensure_ascii=False),
            "type_fit_paths": json.dumps(type_fit_paths, ensure_ascii=False),
        })

    seed_rows = [{"seed": seed, **row} for seed in SEEDS for row in exact_rows]
    vectors = {
        seed: [row["predicted_ml"] for row in seed_rows if row["seed"] == seed]
        for seed in SEEDS
    }
    deterministic_repeat_identical = (
        len({tuple(vector) for vector in vectors.values()}) == 1
    )
    if not deterministic_repeat_identical:
        raise AssertionError("predictions changed by seed")

    active_features = sorted({
        feature_names()[index]
        for config in CONFIGS.values()
        for index in rankers.SUBSETS[config.spec.subset]
    })
    blocked = [
        name for name in active_features
        if any(token in name.lower() for token in FORBIDDEN_FEATURE_TOKENS)
    ]
    if blocked:
        raise AssertionError(f"forbidden model feature names: {blocked}")

    overall = metrics(exact_rows)
    per_type = {
        name: metrics([row for row in exact_rows if row["titration_type"] == name])
        for name in sorted(CONFIGS)
    }
    per_seed = [
        {"seed": seed, **metrics([row for row in seed_rows if row["seed"] == seed])}
        for seed in SEEDS
    ]
    if not overall["mape_percent"] < REFERENCE_MAPE_PERCENT:
        raise AssertionError("result did not improve the requested reference")

    config_json = {
        name: {
            "spec": asdict(config.spec),
            "normalization": config.normalization,
            "global_weight": config.global_weight,
            "same_type_weight": 1.0 - config.global_weight,
            "top_k": "all" if config.top_k == 0 else config.top_k,
            "temperature": config.temperature,
            "top_blend": config.top_blend,
        }
        for name, config in CONFIGS.items()
    }
    summary = {
        "schema_version": "dense_type_conditioned_sensor_reproduction_v1",
        "model_variant": "type_conditioned_sensor_union_dense_aggregation_ranker",
        "claim_scope": (
            "post_hoc_configuration_selection_on_the_same_12_development_runs; "
            "not nested model-selection validation and not independent external validation"
        ),
        "run_count": 12,
        "reference_mape_percent": REFERENCE_MAPE_PERCENT,
        "metrics": overall,
        "improvement_percentage_points": REFERENCE_MAPE_PERCENT - overall["mape_percent"],
        "per_type_metrics": per_type,
        "per_seed_metrics": per_seed,
        "deterministic_repeat": {
            "seeds": list(SEEDS),
            "identical_predictions": deterministic_repeat_identical,
            "interpretation": (
                "deterministic repeat check only; the fitted estimators do not "
                "consume these seed values, so this is not seed-robustness evidence"
            ),
            "metric_std": {
                key: float(np.std([row[key] for row in per_seed]))
                for key in ("mae_ml", "rmse_ml", "mape_percent")
            },
        },
        "method": {
            "known_inference_context": ["titration_type"],
            "sensor_columns": list(SENSOR_COLUMNS),
            "forbidden_inference_inputs": list(FORBIDDEN_INPUTS),
            "configs": config_json,
            "search_note": (
                "The prior type-conditioned ranker families were retained. A dense "
                "post-hoc aggregation search adjusted weak_acid_strong_base from "
                "global_weight=0.75/top_k=20/temperature=1.0 to "
                "0.64/26/0.2; the other frozen settings were unchanged."
            ),
        },
        "configuration_search": {
            "initial_combinations_compared": INITIAL_CONFIGURATION_COUNT,
            "dense_typewise_aggregation_combinations_compared": (
                DENSE_CONFIGURATION_COUNT
            ),
            "total_combinations_compared": TOTAL_CONFIGURATION_COUNT,
            "selection_data": "same 12 development runs, separately by titration type",
            "outer_test_truth_excluded_from_configuration_selection": False,
        },
        "leakage_audit": {
            "passed": not blocked and all(metadata_invariance.values()),
            "outer_test_excluded_from_every_scaler_and_model_fit": True,
            "active_feature_names": active_features,
            "forbidden_feature_names": blocked,
            "forbidden_metadata_candidate_invariance": metadata_invariance,
            "training_label_only": [
                "candidate boundary -> injected_volume_ml",
                "theoretical_equivalence_volume_ml",
            ],
            "test_volume_and_truth_access": "after sensor-only frame selection, audit/output mapping only",
        },
        "predictions": exact_rows,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
        "provenance": {
            "input_csv_sha256": {
                run.path.name: hashlib.sha256(run.path.read_bytes()).hexdigest()
                for run in sorted(runs, key=lambda item: item.path.name)
            },
            "script_sha256": {
                str(path.relative_to(REPO)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (
                    REPO / "tools/sensor_transition_candidate_union.py",
                    REPO / "tools/search_advanced_type_conditioned_sensor_rankers.py",
                    REPO / "tools/search_dense_type_conditioned_aggregation.py",
                    REPO / "tools/reproduce_dense_type_conditioned_sensor_rankers.py",
                    REPO / "tools/type_conditioned_sensor_sequence_search.py",
                )
            },
        },
        "artifacts_sha256": {},
    }
    import sklearn
    summary["versions"]["scikit_learn"] = sklearn.__version__

    write_csv(OUTPUT / "exact_predictions.csv", exact_rows)
    write_csv(OUTPUT / "predictions_by_seed.csv", seed_rows)
    write_csv(OUTPUT / "per_seed_metrics.csv", per_seed)
    for artifact in ("exact_predictions.csv", "predictions_by_seed.csv", "per_seed_metrics.csv"):
        summary["artifacts_sha256"][artifact] = hashlib.sha256(
            (OUTPUT / artifact).read_bytes()
        ).hexdigest()
    (OUTPUT / "final_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "metrics": overall,
        "deterministic_repeat_identical": deterministic_repeat_identical,
        "leakage_audit_passed": summary["leakage_audit"]["passed"],
    }, indent=2))


if __name__ == "__main__":
    main()
