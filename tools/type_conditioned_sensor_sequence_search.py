#!/usr/bin/env python3
"""Type-conditioned deterministic sensor endpoint estimation.

The titration family is known before measurement and routes each run to a
fixed estimator configuration.  Candidate generation and ranker features use
only visible-HSV and thermal sensor sequences.  Sample concentration, current
volume, theoretical endpoint, time, and progress are not model inputs.

The four configurations were selected using these same 12 development runs.
The reported error is therefore a development result, not independent external
validation.  Each ranker fit still holds the evaluated run out.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

for _variable in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ[_variable] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from tools import sensor_sequence_endpoint_search as metrics_base  # noqa: E402
from tools import sensor_transition_candidate_union as candidate_union  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/type_conditioned_sensor_sequence_search")
SEEDS = (42, 1729, 20260728)
KNOWN_CONTEXT_INPUTS = ("titration_type",)
FORBIDDEN_MODEL_INPUTS = (
    "sample_concentration_M",
    "injected_volume_ml",
    "theoretical_equivalence_volume_ml",
    "time_s",
    "progress_fraction",
    "indicator",
)
FORBIDDEN_FEATURE_TOKENS = (
    "volume", "concentration", "equivalence", "endpoint", "progress",
    "fraction", "position", "frame", "time", "elapsed", "duration",
    "label", "target", "actual", "predicted", "distance", "remaining",
    "indicator",
)

FEATURE_NAMES = tuple(candidate_union.feature_names())
SHIFT = tuple(index for index in range(24) if index % 4 in (0, 1))
PERSISTENCE = tuple(index for index in range(24) if index % 4 in (2, 3))
TERMINAL = (24, 25, 26, 27, 28, 29)
PROVENANCE = (30, 31, 32, 33)
FEATURE_SUBSETS = {
    "state": tuple(sorted(set(PERSISTENCE + (24, 25, 27, 28) + PROVENANCE))),
    "persistence": tuple(sorted(set(PERSISTENCE + (24, 25, 27, 28) + PROVENANCE))),
    "shift_terminal": tuple(sorted(set(SHIFT + TERMINAL + PROVENANCE))),
    "full_sensor": tuple(range(34)),
}


@dataclass(frozen=True)
class TypeConditionedConfig:
    family: str
    parameter: str
    feature_subset: str
    feature_transform: str
    score_normalization: str
    global_weight: float
    top_k: int
    softmax_temperature: float
    top_candidate_weight: float


TYPE_CONFIGS: dict[str, TypeConditionedConfig] = {
    "strong_acid_strong_base": TypeConditionedConfig(
        "pls", "exp_rank@2", "state", "signed_log1p", "zscore",
        1.0, 0, 1.0, 0.0,
    ),
    "weak_acid_strong_base": TypeConditionedConfig(
        "lda", "5@svd", "shift_terminal", "raw", "rank",
        0.64, 26, 0.2, 0.0,
    ),
    "strong_acid_weak_base": TypeConditionedConfig(
        "kernel_ridge_rbf", "rank@1,0.05", "shift_terminal",
        "signed_log1p", "rank", 1.0, 0, 0.1, 0.0,
    ),
    "weak_acid_weak_base": TypeConditionedConfig(
        "qda", "5@0.9", "shift_terminal", "raw", "zscore",
        1.0, 5, 0.1, 0.0,
    ),
}


def forbidden_features(columns: Sequence[str]) -> list[str]:
    return sorted(
        column for column in columns
        if any(token in column.lower() for token in FORBIDDEN_FEATURE_TOKENS)
    )


def active_feature_names(config: TypeConditionedConfig) -> tuple[str, ...]:
    return tuple(FEATURE_NAMES[index] for index in FEATURE_SUBSETS[config.feature_subset])


def _validate_configs(
    runs: Sequence[CsvRun], configs: Mapping[str, TypeConditionedConfig],
) -> None:
    run_types = {run.titration_type for run in runs}
    missing = sorted(run_types - set(configs))
    if missing:
        raise ValueError(f"missing type-conditioned configurations: {missing}")
    for titration_type in run_types:
        config = configs[titration_type]
        if config.family not in {"pls", "lda", "qda", "kernel_ridge_rbf"}:
            raise ValueError(f"unsupported ranker family: {config.family}")
        if config.feature_subset not in FEATURE_SUBSETS:
            raise ValueError(f"unknown feature subset: {config.feature_subset}")
        if config.feature_transform not in {"raw", "signed_log1p"}:
            raise ValueError(f"unknown feature transform: {config.feature_transform}")
        if config.score_normalization not in {"zscore", "rank"}:
            raise ValueError(f"unknown score normalization: {config.score_normalization}")
        if not 0.0 <= config.global_weight <= 1.0:
            raise ValueError(f"invalid global weight for {titration_type}")
        if not 0.0 <= config.top_candidate_weight <= 1.0:
            raise ValueError(f"invalid top candidate weight for {titration_type}")
        if config.top_k < 0 or config.softmax_temperature <= 0.0:
            raise ValueError(f"invalid aggregation for {titration_type}")
        count = sum(run.titration_type == titration_type for run in runs)
        if config.global_weight < 1.0 and count < 3:
            raise ValueError(
                f"{titration_type} needs at least three runs for held-out type ranking"
            )
        blocked = forbidden_features(active_feature_names(config))
        if blocked:
            raise AssertionError(f"forbidden model features for {titration_type}: {blocked}")


def transformed_design(
    candidates: Sequence[candidate_union.Candidate], config: TypeConditionedConfig,
) -> np.ndarray:
    indices = FEATURE_SUBSETS[config.feature_subset]
    values = np.asarray([
        [candidate.features[index] for index in indices]
        for candidate in candidates
    ], dtype=float)
    if config.feature_transform == "signed_log1p":
        values = np.sign(values) * np.log1p(np.abs(values))
    return values


def _candidate_error(
    run: CsvRun, candidate: candidate_union.Candidate,
) -> float:
    """Training-label access only; never called on an outer test selection."""

    mapped = float(run.rows[candidate.boundary]["injected_volume_ml"])
    return abs(mapped - float(run.theoretical_equivalence_volume_ml))


def _rank_quality(errors: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(errors, kind="stable"), kind="stable").astype(float)
    return 1.0 - order / max(1, len(errors) - 1)


def _training_arrays(
    train_runs: Sequence[CsvRun],
    candidate_sets: Mapping[str, Sequence[candidate_union.Candidate]],
    config: TypeConditionedConfig,
) -> tuple[np.ndarray, list[np.ndarray]]:
    designs: list[np.ndarray] = []
    errors: list[np.ndarray] = []
    for run in train_runs:
        candidates = candidate_sets[str(run.path)]
        designs.append(transformed_design(candidates, config))
        errors.append(np.asarray([
            _candidate_error(run, candidate) for candidate in candidates
        ], dtype=float))
    return np.vstack(designs), errors


def fit_candidate_scorer(
    train_runs: Sequence[CsvRun],
    candidate_sets: Mapping[str, Sequence[candidate_union.Candidate]],
    config: TypeConditionedConfig,
):
    from sklearn.cross_decomposition import PLSRegression
    from sklearn.discriminant_analysis import (
        LinearDiscriminantAnalysis, QuadraticDiscriminantAnalysis,
    )
    from sklearn.kernel_ridge import KernelRidge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    x, errors = _training_arrays(train_runs, candidate_sets, config)
    if config.family in {"pls", "kernel_ridge_rbf"}:
        target_kind, model_arg = config.parameter.split("@", 1)
        if target_kind == "rank":
            y = np.concatenate([_rank_quality(value) for value in errors])
        elif target_kind == "exp_rank":
            y = np.concatenate([
                np.exp(-4.0 * (1.0 - _rank_quality(value))) for value in errors
            ])
        elif target_kind == "neg_log_error":
            y = np.concatenate([-np.log1p(value) for value in errors])
        else:
            raise ValueError(f"unsupported target kind: {target_kind}")
        if config.family == "pls":
            estimator = PLSRegression(
                n_components=int(model_arg), scale=False, max_iter=1000
            )
        else:
            alpha, gamma = map(float, model_arg.split(","))
            estimator = KernelRidge(alpha=alpha, gamma=gamma, kernel="rbf")
        model = make_pipeline(StandardScaler(), estimator)
        model.fit(x, y)
        return model

    positive_k, variant = config.parameter.split("@", 1)
    k = int(positive_k)
    labels = np.concatenate([
        np.isin(
            np.arange(len(value)),
            np.argsort(value, kind="stable")[:min(k, len(value))],
        ).astype(int)
        for value in errors
    ])
    if config.family == "lda":
        estimator = (
            LinearDiscriminantAnalysis(solver="svd")
            if variant == "svd"
            else LinearDiscriminantAnalysis(solver="lsqr", shrinkage=float(variant))
        )
    else:
        estimator = QuadraticDiscriminantAnalysis(reg_param=float(variant))
    model = make_pipeline(StandardScaler(), estimator)
    positive = np.flatnonzero(labels == 1)
    negative = np.flatnonzero(labels == 0)
    repeat = max(1, len(negative) // max(1, len(positive)))
    balanced = np.concatenate((negative, np.tile(positive, repeat)))
    model.fit(x[balanced], labels[balanced])
    return model


def candidate_scores(model, candidates, config: TypeConditionedConfig) -> np.ndarray:
    design = transformed_design(candidates, config)
    if config.family in {"pls", "kernel_ridge_rbf"}:
        return np.asarray(model.predict(design), dtype=float).reshape(-1)
    if hasattr(model, "decision_function"):
        return np.asarray(model.decision_function(design), dtype=float).reshape(-1)
    return np.asarray(model.predict_proba(design)[:, 1], dtype=float)


def normalize_scores(scores: Sequence[float], method: str) -> np.ndarray:
    values = np.asarray(scores, dtype=float)
    if method == "zscore":
        deviation = float(np.std(values))
        if deviation <= 1e-12:
            return np.zeros_like(values)
        return (values - float(np.mean(values))) / deviation
    if method == "rank":
        order = np.argsort(np.argsort(values, kind="stable"), kind="stable")
        return order.astype(float) / max(1, len(values) - 1)
    raise ValueError(f"unknown score normalization: {method}")


def aggregate_boundary(
    candidates: Sequence[candidate_union.Candidate], scores: Sequence[float],
    config: TypeConditionedConfig,
) -> tuple[int, int, float]:
    score = np.asarray(scores, dtype=float)
    order = sorted(range(len(candidates)), key=lambda index: (-float(score[index]), index))
    top_index = order[0]
    selected = order if config.top_k == 0 else order[:min(config.top_k, len(order))]
    selected_scores = np.asarray([score[index] for index in selected], dtype=float)
    centered = (
        selected_scores - float(np.max(selected_scores))
    ) / config.softmax_temperature
    weights = np.exp(centered)
    weights /= float(np.sum(weights))
    centroid = float(np.dot(
        weights,
        np.asarray([candidates[index].boundary for index in selected], dtype=float),
    ))
    boundary = int(round(
        config.top_candidate_weight * candidates[top_index].boundary
        + (1.0 - config.top_candidate_weight) * centroid
    ))
    margin = (
        float(score[order[0]] - score[order[1]])
        if len(order) > 1 else float("inf")
    )
    return boundary, candidates[top_index].confirmation, margin


def select_frame(
    train_runs: Sequence[CsvRun], test_run: CsvRun,
    candidate_sets: Mapping[str, Sequence[candidate_union.Candidate]],
    config: TypeConditionedConfig,
) -> tuple[int, int, float, list[str], list[str]]:
    if any(run.path == test_run.path for run in train_runs):
        raise ValueError("outer test run leaked into ranker training runs")
    candidates = candidate_sets[str(test_run.path)]
    scores = np.zeros(len(candidates), dtype=float)
    global_paths: list[str] = []
    type_paths: list[str] = []

    if config.global_weight > 0.0:
        global_model = fit_candidate_scorer(train_runs, candidate_sets, config)
        scores += config.global_weight * normalize_scores(
            candidate_scores(global_model, candidates, config),
            config.score_normalization,
        )
        global_paths = [str(run.path) for run in train_runs]
    if config.global_weight < 1.0:
        type_train = [
            run for run in train_runs
            if run.titration_type == test_run.titration_type
        ]
        if not type_train:
            raise ValueError(f"no type-specific training runs for {test_run.titration_type}")
        type_model = fit_candidate_scorer(type_train, candidate_sets, config)
        scores += (1.0 - config.global_weight) * normalize_scores(
            candidate_scores(type_model, candidates, config),
            config.score_normalization,
        )
        type_paths = [str(run.path) for run in type_train]

    frame, confirmation, margin = aggregate_boundary(candidates, scores, config)
    frame = max(0, min(frame, len(test_run.rows) - 1))
    return frame, confirmation, margin, global_paths, type_paths


def candidate_union_signature(
    candidate_sets: Mapping[str, Sequence[candidate_union.Candidate]],
) -> str:
    payload = [
        (Path(path).name, candidate.boundary, candidate.support)
        for path in sorted(candidate_sets)
        for candidate in candidate_sets[path]
    ]
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":")).encode()
    ).hexdigest()


def _numeric_column_audit(
    runs: Sequence[CsvRun], column: str,
) -> dict[str, Any]:
    total_rows = sum(len(run.rows) for run in runs)
    observed = [
        value
        for run in runs
        for row in run.rows
        if (value := metrics_base._number(row.get(column))) is not None
    ]
    values = sorted({float(value) for value in observed})
    return {
        "observed_values_M": values,
        "total_row_count": total_rows,
        "numeric_value_count": len(observed),
        "missing_or_invalid_count": total_rows - len(observed),
        "constant_across_all_recorded_rows": (
            len(observed) == total_rows and len(values) == 1
        ),
        "used_as_model_input": False,
    }


def _observed_text_values(
    runs: Sequence[CsvRun], column: str,
) -> list[str]:
    return sorted({
        text
        for run in runs
        for row in run.rows
        if (text := str(row.get(column) or "").strip())
    })


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _provenance_manifest(runs: Sequence[CsvRun]) -> dict[str, Any]:
    script_paths = (
        ROOT / "tools/sensor_transition_candidate_union.py",
        ROOT / "tools/type_conditioned_sensor_sequence_search.py",
        ROOT / "tools/search_advanced_type_conditioned_sensor_rankers.py",
        ROOT / "tools/reproduce_advanced_type_conditioned_sensor_rankers.py",
        ROOT / "tools/search_dense_type_conditioned_aggregation.py",
        ROOT / "tools/reproduce_dense_type_conditioned_sensor_rankers.py",
    )
    return {
        "input_csv_sha256": {
            run.path.name: _sha256(run.path) for run in sorted(runs, key=lambda item: item.path.name)
        },
        "script_sha256": {
            str(path.relative_to(ROOT)): _sha256(path)
            for path in script_paths
        },
    }


def evaluate_runs(
    runs: Sequence[CsvRun], *, output_dir: str | Path | None = None,
    seeds: Sequence[int] = SEEDS,
    configs: Mapping[str, TypeConditionedConfig] = TYPE_CONFIGS,
    expected_run_count: int = 12,
) -> dict[str, Any]:
    started = time.perf_counter()
    if len(runs) != expected_run_count:
        raise ValueError(f"expected exactly {expected_run_count} runs, found {len(runs)}")
    if tuple(seeds) != SEEDS:
        raise ValueError(f"seed list must be exactly {SEEDS}")
    if len({str(run.path) for run in runs}) != len(runs):
        raise ValueError("run paths must be unique")
    _validate_configs(runs, configs)

    candidate_sets = {
        str(run.path): candidate_union.generate_union_candidates(run.rows)
        for run in runs
    }
    empty = [path for path, candidates in candidate_sets.items() if not candidates]
    if empty:
        raise ValueError(f"runs contain no sensor transition candidates: {empty}")

    predictions: list[dict[str, Any]] = []
    per_seed: list[dict[str, Any]] = []
    stratified: list[dict[str, Any]] = []
    for seed in seeds:
        seed_rows: list[dict[str, Any]] = []
        for test_run in runs:
            outer_train = [run for run in runs if run.path != test_run.path]
            config = configs[test_run.titration_type]
            frame, confirmation, margin, global_paths, type_paths = select_frame(
                outer_train, test_run, candidate_sets, config
            )
            # The outer-test volume is first accessed after sensor frame selection.
            predicted = float(test_run.rows[frame]["injected_volume_ml"])
            confirmation_volume = float(
                test_run.rows[min(confirmation, len(test_run.rows) - 1)]["injected_volume_ml"]
            )
            actual = float(test_run.theoretical_equivalence_volume_ml)
            error = predicted - actual
            seed_rows.append({
                "seed": seed,
                "run_path": str(test_run.path),
                "known_titration_type": test_run.titration_type,
                "actual_equivalence_volume_ml": actual,
                "predicted_equivalence_volume_ml": predicted,
                "selected_frame_audit_only": frame,
                "signed_error_ml": error,
                "absolute_error_ml": abs(error),
                "absolute_error_percent_of_equivalence": abs(error) / actual * 100.0,
                "candidate_count": len(candidate_sets[str(test_run.path)]),
                "model_variant": "type_conditioned_sensor_union_dense_aggregation_ranker",
                "configuration": asdict(config),
                "top_two_score_margin_audit_only": round(margin, 9),
                "confirmation_frame_audit_only": confirmation,
                "confirmation_lag_ml_audit_only": confirmation_volume - predicted,
                "global_model_run_paths": global_paths,
                "type_model_run_paths": type_paths,
            })
        predictions.extend(seed_rows)
        per_seed.append({"seed": seed, **metrics_base._metrics(seed_rows)})
        for titration_type in sorted({run.titration_type for run in runs}):
            type_rows = [
                row for row in seed_rows
                if row["known_titration_type"] == titration_type
            ]
            stratified.append({
                "seed": seed, "titration_type": titration_type,
                **metrics_base._metrics(type_rows),
            })

    aggregate: list[dict[str, Any]] = []
    for metric in ("mae_ml", "rmse_ml", "mape_percent", "max_absolute_error_ml"):
        values = np.asarray([row[metric] for row in per_seed], dtype=float)
        aggregate.append({
            "metric": metric,
            "mean_across_seeds": round(float(np.mean(values)), 6),
            "std_across_seeds": round(float(np.std(values)), 6),
            "min_across_seeds": round(float(np.min(values)), 6),
            "max_across_seeds": round(float(np.max(values)), 6),
        })

    oracle_rows: list[dict[str, Any]] = []
    for run in runs:
        candidates = candidate_sets[str(run.path)]
        oracle = min(candidates, key=lambda candidate: _candidate_error(run, candidate))
        predicted = float(run.rows[oracle.boundary]["injected_volume_ml"])
        actual = float(run.theoretical_equivalence_volume_ml)
        oracle_rows.append({
            "run_path": str(run.path),
            "known_titration_type": run.titration_type,
            "candidate_count": len(candidates),
            "oracle_frame_audit_only": oracle.boundary,
            "predicted_equivalence_volume_ml": predicted,
            "actual_equivalence_volume_ml": actual,
            "absolute_error_ml": abs(predicted - actual),
            "absolute_error_percent_of_equivalence": abs(predicted - actual) / actual * 100.0,
        })
    oracle_mape = float(np.mean([
        row["absolute_error_percent_of_equivalence"] for row in oracle_rows
    ]))

    active_features = sorted({
        feature
        for config in configs.values()
        for feature in active_feature_names(config)
    })
    blocked = forbidden_features(active_features)
    titrant_context_audit = _numeric_column_audit(
        runs, "titrant_concentration_M"
    )
    titrant_concentrations = titrant_context_audit["observed_values_M"]
    indicator_values = _observed_text_values(runs, "indicator")
    constant_context_not_used = {}
    if titrant_context_audit["constant_across_all_recorded_rows"]:
        constant_context_not_used["titrant_concentration_M"] = titrant_concentrations[0]
    all_seed_vectors = [
        [row["predicted_equivalence_volume_ml"] for row in predictions if row["seed"] == seed]
        for seed in seeds
    ]
    summary: dict[str, Any] = {
        "schema_version": "type_conditioned_sensor_union_development_v3",
        "claim_scope": (
            "same_12_run_typewise_development_configuration_selection_"
            "not_independent_external_validation"
        ),
        "prediction_scope": "complete_record_sensor_sequence_endpoint_localization",
        "run_count": len(runs),
        "seeds": list(seeds),
        "seed_policy": (
            "deterministic repeat check only; estimators do not consume a random seed"
        ),
        "seed_predictions_identical": all(
            vector == all_seed_vectors[0] for vector in all_seed_vectors[1:]
        ),
        "split": {
            "ranker_fit": "outer_leave_one_run_out",
            "configuration_selection": "same 12 development runs by titration type",
            "outer_test_run_used_in_ranker_fit": False,
            "independent_external_validation": False,
        },
        "configuration_search": {
            "ranker_specs": 1242,
            "score_normalizations": 2,
            "global_type_weights": 5,
            "aggregation_configs": 81,
            "initial_combinations_compared": 1006020,
            "dense_typewise_aggregation_combinations_compared": 1024350,
            "total_combinations_compared": 2030370,
            "selection_data": "same 12 development runs, separately by titration type",
            "outer_test_truth_excluded_from_configuration_selection": False,
        },
        "known_context_inputs": list(KNOWN_CONTEXT_INPUTS),
        "known_context_policy": (
            "titration type routes each run to a pre-defined configuration and, "
            "when configured, a same-type ranker; it is not a sensor matrix column"
        ),
        "constant_context_not_used": constant_context_not_used,
        "titrant_context_audit": titrant_context_audit,
        "metadata_context_not_used": {
            "indicator": {
                "observed_legacy_values": indicator_values,
                "used_as_model_input": False,
                "reason": "legacy CSV indicator metadata is incomplete/inconsistent",
            }
        },
        "forbidden_model_inputs": list(FORBIDDEN_MODEL_INPUTS),
        "model_input_policy": (
            "five sensor channels and known titration-type routing only; sample "
            "concentration/current volume/truth/time/progress/indicator excluded"
        ),
        "candidate_union": {
            "signature": candidate_union_signature(candidate_sets),
            "oracle_mape_percent_audit_only": round(oracle_mape, 6),
            "grid": {
                "baselines": list(candidate_union.BASELINES),
                "windows": list(candidate_union.WINDOWS),
                "thresholds": list(candidate_union.THRESHOLDS),
                "confirmations": list(candidate_union.CONFIRMATIONS),
                "refractories": list(candidate_union.REFRACTORIES),
                "modalities": list(candidate_union.MODALITIES),
                "max_candidates_per_run": candidate_union.MAX_CANDIDATES,
            },
            "per_run": oracle_rows,
        },
        "leakage_audit": {
            "passed": not blocked,
            "active_feature_names": active_features,
            "forbidden_features_found": blocked,
            "known_context_inputs": list(KNOWN_CONTEXT_INPUTS),
            "candidate_sensor_columns": [
                "visible_H_mean", "visible_S_mean", "visible_V_mean",
                "thermal_raw_roi_p50", "thermal_raw_roi_p95",
            ],
            "training_label_only": [
                "theoretical_equivalence_volume_ml",
                "injected_volume_ml candidate mapping",
            ],
            "test_volume_access": "only after selected frame",
        },
        "type_configs": {
            key: asdict(value) for key, value in sorted(configs.items())
        },
        "provenance": _provenance_manifest(runs),
        "per_seed_metrics": per_seed,
        "stratified_metrics": stratified,
        "aggregate_robustness": aggregate,
        "outer_predictions": predictions,
        "limitations": [
            "The four type-specific configurations were selected on these same 12 development runs.",
            "The search compared 2,030,370 configuration combinations "
            "(1,006,020 initial plus 1,024,350 dense aggregation settings), "
            "so selection optimism is substantial.",
            "The evaluated run was excluded from ranker fitting but its error participated in final configuration selection.",
            "The candidate-generation grid was developed in the same research dataset and has no independent preregistration provenance.",
            "The result is not an independent external-validation estimate.",
            "Each chemistry/concentration condition has one run, so condition shift and run variation are confounded.",
            "Training labels use theoretical rather than independently observed endpoints.",
            "The complete recorded sequence and terminal sensor state are used for endpoint localization.",
            "The estimated endpoint is not a measured physical stop-volume error.",
        ],
        "resource_usage": {
            "evaluation_seconds": round(time.perf_counter() - started, 6),
            "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        },
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
    }
    try:
        import sklearn
        summary["versions"]["scikit_learn"] = sklearn.__version__
    except Exception:
        summary["versions"]["scikit_learn"] = None

    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        metrics_base._write_csv(output / "outer_predictions.csv", predictions)
        metrics_base._write_csv(output / "per_seed_metrics.csv", per_seed)
        metrics_base._write_csv(output / "stratified_metrics.csv", stratified)
        metrics_base._write_csv(output / "aggregate_robustness.csv", aggregate)
        metrics_base._write_csv(output / "candidate_oracle_audit.csv", oracle_rows)
        metrics_base._write_csv(
            output / "feature_manifest.csv",
            [{"feature": feature} for feature in active_features],
        )
        metrics_base._write_csv(
            output / "known_context_manifest.csv",
            [{"known_context": value} for value in KNOWN_CONTEXT_INPUTS],
        )
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report = [
            "# 적정 종류 조건부 센서 당량점 추정 모델", "",
            "이 결과는 같은 12회 개발 자료에서 적정 종류별 설정을 선택한 값이며, 독립 검증값은 아니다.", "",
            "- 사전에 알려진 조건: 적정 종류",
            "- 센서 입력: HSV 3개 채널과 열화상 2개 채널의 시퀀스 변화",
            "- 제외 입력: 미지 시료 농도, 현재 주입량, 이론 당량점, 시간, 진행률, 지시약",
            "- 표준용액 농도: 모든 실험에서 0.100 M로 같아 입력에서 제외", "",
            "## 결정론적 재실행 확인", "",
            "| 시드 | MAE (mL) | RMSE (mL) | MAPE (%) |",
            "|---:|---:|---:|---:|",
        ]
        report.extend(
            f"| {row['seed']} | {row['mae_ml']:.6f} | {row['rmse_ml']:.6f} | {row['mape_percent']:.6f} |"
            for row in per_seed
        )
        report.extend(["", "## 한계", ""] + [f"- {item}" for item in summary["limitations"]])
        (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def evaluate_folder(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    *, output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, Any]:
    summary = evaluate_runs(load_runs(input_dir), output_dir=output_dir)
    summary["input_dir"] = str(input_dir)
    Path(output_dir, "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    summary = evaluate_folder(args.input_dir, output_dir=args.output_dir)
    print(json.dumps({
        "per_seed": summary["per_seed_metrics"],
        "aggregate": summary["aggregate_robustness"],
        "seed_predictions_identical": summary["seed_predictions_identical"],
        "candidate_oracle_mape_percent": summary["candidate_union"]["oracle_mape_percent_audit_only"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
