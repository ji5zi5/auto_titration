#!/usr/bin/env python3
"""Run-level LORO comparison of XGBoost, LightGBM, and CatBoost rankers."""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

for name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    generate_union_candidates,
)
from tools.sensor_transition_candidate_union import feature_names  # noqa: E402


DEFAULT_INPUT = ROOT / "머신러닝용 파일모음"
DEFAULT_OUTPUT = ROOT / "data/labeled/boosting-candidate-ranker-comparison.json"
SEEDS = (42, 1729, 20260728)
TYPE_ORDER = (
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
)
SENSOR_FEATURE_NAMES = tuple(feature_names())
FEATURE_NAMES = SENSOR_FEATURE_NAMES + tuple(f"titration_type_{name}" for name in TYPE_ORDER)


def transformed_features(candidates: Sequence[Any], titration_type: str) -> np.ndarray:
    sensor = np.asarray([candidate.features for candidate in candidates], dtype=float)
    sensor = np.sign(sensor) * np.log1p(np.abs(sensor))
    one_hot = np.zeros(len(TYPE_ORDER), dtype=float)
    one_hot[TYPE_ORDER.index(titration_type)] = 1.0
    context = np.repeat(one_hot[None, :], len(sensor), axis=0)
    return np.column_stack((sensor, context))


def relevance_labels(run: CsvRun, candidates: Sequence[Any]) -> np.ndarray:
    errors = np.asarray(
        [
            abs(
                float(run.rows[candidate.boundary]["injected_volume_ml"])
                - float(run.theoretical_equivalence_volume_ml)
            )
            for candidate in candidates
        ],
        dtype=float,
    )
    order = np.argsort(errors, kind="stable")
    labels = np.zeros(len(candidates), dtype=int)
    labels[order[: min(20, len(order))]] = 1
    labels[order[: min(8, len(order))]] = 2
    labels[order[: min(3, len(order))]] = 3
    labels[order[:1]] = 4
    return labels


def continuous_quality_labels(run: CsvRun, candidates: Sequence[Any]) -> np.ndarray:
    errors = np.asarray(
        [
            abs(
                float(run.rows[candidate.boundary]["injected_volume_ml"])
                - float(run.theoretical_equivalence_volume_ml)
            )
            for candidate in candidates
        ],
        dtype=float,
    )
    order = np.argsort(np.argsort(errors, kind="stable"), kind="stable").astype(float)
    rank_quality = 1.0 - order / max(1, len(errors) - 1)
    return np.exp(-4.0 * (1.0 - rank_quality))


def training_arrays(
    runs: Sequence[CsvRun],
    candidate_sets: Mapping[str, Sequence[Any]],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[int], np.ndarray]:
    matrices = []
    labels = []
    continuous = []
    groups = []
    group_ids = []
    for group_index, run in enumerate(runs):
        candidates = candidate_sets[str(run.path)]
        matrices.append(transformed_features(candidates, run.titration_type))
        labels.append(relevance_labels(run, candidates))
        continuous.append(continuous_quality_labels(run, candidates))
        groups.append(len(candidates))
        group_ids.extend([group_index] * len(candidates))
    return (
        np.vstack(matrices),
        np.concatenate(labels),
        np.concatenate(continuous),
        groups,
        np.asarray(group_ids, dtype=int),
    )


def make_model(family: str, seed: int):
    if family == "xgboost":
        from xgboost import XGBRanker

        return XGBRanker(
            objective="rank:pairwise",
            n_estimators=120,
            max_depth=2,
            learning_rate=0.035,
            min_child_weight=5,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=10.0,
            reg_alpha=0.5,
            random_state=seed,
            n_jobs=1,
            verbosity=0,
        )
    if family == "lightgbm":
        from lightgbm import LGBMRanker

        return LGBMRanker(
            objective="lambdarank",
            n_estimators=120,
            max_depth=3,
            num_leaves=7,
            learning_rate=0.035,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=10.0,
            reg_alpha=0.5,
            random_state=seed,
            n_jobs=1,
            verbosity=-1,
        )
    if family == "catboost":
        from catboost import CatBoostRanker

        return CatBoostRanker(
            loss_function="YetiRankPairwise",
            iterations=120,
            depth=3,
            learning_rate=0.035,
            l2_leaf_reg=10.0,
            random_seed=seed,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
        )
    if family == "xgboost_regression":
        from xgboost import XGBRegressor

        return XGBRegressor(
            objective="reg:squarederror",
            n_estimators=120,
            max_depth=2,
            learning_rate=0.035,
            min_child_weight=5,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=10.0,
            reg_alpha=0.5,
            random_state=seed,
            n_jobs=1,
            verbosity=0,
        )
    if family == "lightgbm_regression":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            objective="regression_l1",
            n_estimators=120,
            max_depth=3,
            num_leaves=7,
            learning_rate=0.035,
            min_child_samples=20,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=10.0,
            reg_alpha=0.5,
            random_state=seed,
            n_jobs=1,
            verbosity=-1,
        )
    if family == "catboost_regression":
        from catboost import CatBoostRegressor

        return CatBoostRegressor(
            loss_function="MAE",
            iterations=120,
            depth=3,
            learning_rate=0.035,
            l2_leaf_reg=10.0,
            random_seed=seed,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
        )
    raise ValueError(f"unknown boosting ranker: {family}")


def fit_model(
    family: str,
    seed: int,
    runs: Sequence[CsvRun],
    candidate_sets: Mapping[str, Sequence[Any]],
):
    x, relevance, continuous, groups, group_ids = training_arrays(runs, candidate_sets)
    model = make_model(family, seed)
    if family in {"xgboost", "lightgbm"}:
        model.fit(x, relevance, group=groups)
    elif family == "catboost":
        model.fit(x, relevance, group_id=group_ids)
    else:
        model.fit(x, continuous)
    return model


def aggregate_prediction(
    run: CsvRun,
    candidates: Sequence[Any],
    scores: np.ndarray,
    mode: str,
) -> float:
    order = np.argsort(-scores, kind="stable")
    if mode == "top1":
        frame = candidates[int(order[0])].boundary
    elif mode == "softmax_top5":
        chosen = order[: min(5, len(order))]
        selected = scores[chosen]
        deviation = float(np.std(selected))
        normalized = np.zeros_like(selected) if deviation <= 1e-12 else (
            selected - float(np.mean(selected))
        ) / deviation
        weights = np.exp((normalized - float(np.max(normalized))) / 0.2)
        weights /= float(np.sum(weights))
        frame = int(
            round(
                float(
                    np.dot(
                        weights,
                        [candidates[int(index)].boundary for index in chosen],
                    )
                )
            )
        )
    else:
        raise ValueError(mode)
    frame = max(0, min(frame, len(run.rows) - 1))
    return float(run.rows[frame]["injected_volume_ml"])


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    signed = [float(row["predicted_ml"]) - float(row["actual_ml"]) for row in rows]
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
        "within_1ml_rate": statistics.mean(error <= 1.0 for error in absolute),
    }


def feature_importance(model: Any) -> list[dict[str, Any]]:
    raw_values = getattr(model, "feature_importances_", None)
    values = (
        np.asarray(raw_values, dtype=float).reshape(-1)
        if raw_values is not None
        else np.asarray([], dtype=float)
    )
    if values.size != len(FEATURE_NAMES):
        try:
            values = np.asarray(model.get_feature_importance(), dtype=float).reshape(-1)
        except Exception:
            return []
    order = np.argsort(-values, kind="stable")[:12]
    return [
        {"feature": FEATURE_NAMES[int(index)], "importance": float(values[int(index)])}
        for index in order
    ]


def evaluate(input_dir: Path) -> dict[str, Any]:
    runs = load_runs(input_dir)
    if len(runs) != 12:
        raise ValueError(f"expected 12 runs, got {len(runs)}")
    candidate_sets = {
        str(run.path): generate_union_candidates(run.rows) for run in runs
    }
    all_rows = []
    full_fit_rows = []
    failures = []
    importances = []
    families = (
        "xgboost",
        "lightgbm",
        "catboost",
        "xgboost_regression",
        "lightgbm_regression",
        "catboost_regression",
    )
    for family in families:
        for seed in SEEDS:
            try:
                for training_scope in ("global_with_type", "same_type_only"):
                    for test in runs:
                        train = [
                            run
                            for run in runs
                            if run.path != test.path
                            and (
                                training_scope == "global_with_type"
                                or run.titration_type == test.titration_type
                            )
                        ]
                        if not train:
                            raise ValueError(
                                f"no training runs for {training_scope} {test.titration_type}"
                            )
                        model = fit_model(family, seed, train, candidate_sets)
                        candidates = candidate_sets[str(test.path)]
                        scores = np.asarray(
                            model.predict(
                                transformed_features(candidates, test.titration_type)
                            ),
                            dtype=float,
                        )
                        for mode in ("top1", "softmax_top5"):
                            predicted = aggregate_prediction(
                                test, candidates, scores, mode
                            )
                            row = {
                                "family": family,
                                "seed": seed,
                                "training_scope": training_scope,
                                "aggregation": mode,
                                "run": test.path.name,
                                "titration_type": test.titration_type,
                                "training_run_count": len(train),
                                "actual_ml": float(test.theoretical_equivalence_volume_ml),
                                "predicted_ml": predicted,
                            }
                            all_rows.append(row)
                final_model = fit_model(family, seed, runs, candidate_sets)
                for test in runs:
                    test_candidates = candidate_sets[str(test.path)]
                    final_scores = np.asarray(
                        final_model.predict(
                            transformed_features(
                                test_candidates, test.titration_type
                            )
                        ),
                        dtype=float,
                    )
                    for mode in ("top1", "softmax_top5"):
                        full_fit_rows.append(
                            {
                                "family": family,
                                "seed": seed,
                                "aggregation": mode,
                                "run": test.path.name,
                                "titration_type": test.titration_type,
                                "training_run_count": len(runs),
                                "actual_ml": float(
                                    test.theoretical_equivalence_volume_ml
                                ),
                                "predicted_ml": aggregate_prediction(
                                    test,
                                    test_candidates,
                                    final_scores,
                                    mode,
                                ),
                            }
                        )
                importances.append(
                    {
                        "family": family,
                        "seed": seed,
                        "top_features": feature_importance(final_model),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - comparison evidence.
                failures.append(
                    {"family": family, "seed": seed, "error": f"{type(exc).__name__}: {exc}"}
                )

    comparisons = []
    for family in families:
        for training_scope in ("global_with_type", "same_type_only"):
            for mode in ("top1", "softmax_top5"):
                rows = [
                    row
                    for row in all_rows
                    if row["family"] == family
                    and row["training_scope"] == training_scope
                    and row["aggregation"] == mode
                ]
                if not rows:
                    continue
                per_seed = [
                    {
                        "seed": seed,
                        **summarize([row for row in rows if row["seed"] == seed]),
                    }
                    for seed in SEEDS
                ]
                per_type = []
                for titration_type in TYPE_ORDER:
                    type_seed_metrics = [
                        summarize(
                            [
                                row
                                for row in rows
                                if row["seed"] == seed
                                and row["titration_type"] == titration_type
                            ]
                        )
                        for seed in SEEDS
                    ]
                    per_type.append(
                        {
                            "titration_type": titration_type,
                            "mean_mape_across_seeds": statistics.mean(
                                item["mape_percent"] for item in type_seed_metrics
                            ),
                            "mean_mae_across_seeds": statistics.mean(
                                item["mae_ml"] for item in type_seed_metrics
                            ),
                            "worst_max_abs_error_ml": max(
                                item["max_abs_error_ml"] for item in type_seed_metrics
                            ),
                        }
                    )
                comparisons.append(
                    {
                        "family": family,
                        "training_scope": training_scope,
                        "aggregation": mode,
                        "mean_mape_across_seeds": statistics.mean(
                            row["mape_percent"] for row in per_seed
                        ),
                        "sd_mape_across_seeds": statistics.pstdev(
                            row["mape_percent"] for row in per_seed
                        ),
                        "mean_mae_across_seeds": statistics.mean(
                            row["mae_ml"] for row in per_seed
                        ),
                        "worst_max_abs_error_ml": max(
                            row["max_abs_error_ml"] for row in per_seed
                        ),
                        "per_seed": per_seed,
                        "per_type": per_type,
                    }
                )
    ranked = sorted(
        comparisons,
        key=lambda row: (
            row["mean_mape_across_seeds"],
            row["worst_max_abs_error_ml"],
            row["family"],
        ),
    )
    full_fit_comparison = []
    for family in families:
        for mode in ("top1", "softmax_top5"):
            rows = [
                row
                for row in full_fit_rows
                if row["family"] == family and row["aggregation"] == mode
            ]
            if not rows:
                continue
            per_seed = [
                {
                    "seed": seed,
                    **summarize([row for row in rows if row["seed"] == seed]),
                }
                for seed in SEEDS
            ]
            per_type = []
            for titration_type in TYPE_ORDER:
                type_rows = [
                    row for row in rows if row["titration_type"] == titration_type
                ]
                per_type.append(
                    {
                        "titration_type": titration_type,
                        **summarize(type_rows),
                    }
                )
            full_fit_comparison.append(
                {
                    "family": family,
                    "aggregation": mode,
                    "mean_mape_across_seeds": statistics.mean(
                        row["mape_percent"] for row in per_seed
                    ),
                    "sd_mape_across_seeds": statistics.pstdev(
                        row["mape_percent"] for row in per_seed
                    ),
                    "mean_mae_across_seeds": statistics.mean(
                        row["mae_ml"] for row in per_seed
                    ),
                    "worst_max_abs_error_ml": max(
                        row["max_abs_error_ml"] for row in per_seed
                    ),
                    "per_seed": per_seed,
                    "per_type_all_seed_rows": per_type,
                }
            )
    full_fit_comparison.sort(
        key=lambda row: (
            row["mean_mape_across_seeds"],
            row["worst_max_abs_error_ml"],
            row["family"],
        )
    )
    return {
        "schema_version": "boosting_candidate_ranker_loro_v2",
        "run_count": len(runs),
        "split": (
            "outer leave-one-run-out; global_with_type trains on the other 11 runs; "
            "same_type_only trains on the other two runs of the selected titration type; "
            "no frame-random split"
        ),
        "model_inputs": (
            "34 color/thermal candidate features plus known titration type; "
            "current volume and theoretical endpoint excluded from model matrix"
        ),
        "fixed_hyperparameters": True,
        "seed_policy": "all three seeds reported; no best-seed selection",
        "comparison": ranked,
        "best": ranked[0] if ranked else None,
        "full_12_run_fit_replay": full_fit_comparison,
        "best_full_12_run_fit_replay": (
            full_fit_comparison[0] if full_fit_comparison else None
        ),
        "feature_importance": importances,
        "failures": failures,
        "predictions": all_rows,
        "full_fit_replay_predictions": full_fit_rows,
        "limitations": [
            "Candidate generation was developed on the same 12-run research dataset.",
            "Theoretical nominal endpoints are not independently standardized wet references.",
            "Twelve runs are insufficient to establish external generalization.",
        ],
        "versions": {
            "xgboost": __import__("xgboost").__version__,
            "lightgbm": __import__("lightgbm").__version__,
            "catboost": __import__("catboost").__version__,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else args.output)
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
