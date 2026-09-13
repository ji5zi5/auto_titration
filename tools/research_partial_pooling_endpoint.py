#!/usr/bin/env python3
"""Strictly nested, bounded partial-pooling endpoint ranker experiment."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    generate_union_candidates,
    resample_sensor_rows_by_volume,
)
from tools.type_conditioned_sensor_sequence_search import (  # noqa: E402
    FEATURE_SUBSETS,
)


DEFAULT_INPUT = ROOT / "머신러닝용 파일모음"
DEFAULT_OUTPUT = ROOT / "data/labeled/type-conditioned-partial-pooling-research.json"
TYPE_ORDER = (
    "strong_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_strong_base",
    "weak_acid_weak_base",
)


@dataclass(frozen=True, order=True)
class Spec:
    sampling: str
    pooling: str
    subset: str
    target: str
    alpha: float


SPECS = tuple(
    Spec(sampling, pooling, subset, target, alpha)
    for sampling in ("native", "volume_0p25ml")
    for pooling, subset, target, alpha in (
        ("global", "state", "rank", 10.0),
        ("global", "full_sensor", "exp_rank", 10.0),
        ("partial", "state", "rank", 100.0),
        ("partial", "full_sensor", "exp_rank", 100.0),
    )
)


def prepared_runs(runs: Sequence[CsvRun]) -> dict[str, dict[str, CsvRun]]:
    output = {"native": {}, "volume_0p25ml": {}}
    for run in runs:
        output["native"][str(run.path)] = run
        rows, _ = resample_sensor_rows_by_volume(run.rows, 0.25)
        output["volume_0p25ml"][str(run.path)] = replace(run, rows=rows)
    return output


def candidate_sets(
    prepared: Mapping[str, Mapping[str, CsvRun]],
) -> dict[str, dict[str, Sequence[Any]]]:
    return {
        sampling: {
            path: generate_union_candidates(run.rows) for path, run in by_path.items()
        }
        for sampling, by_path in prepared.items()
    }


def rank_quality(errors: np.ndarray) -> np.ndarray:
    order = np.argsort(np.argsort(errors, kind="stable"), kind="stable").astype(float)
    return 1.0 - order / max(1, len(errors) - 1)


def base_design(candidates: Sequence[Any], spec: Spec) -> np.ndarray:
    indices = FEATURE_SUBSETS[spec.subset]
    matrix = np.asarray(
        [[candidate.features[index] for index in indices] for candidate in candidates],
        dtype=float,
    )
    return np.sign(matrix) * np.log1p(np.abs(matrix))


def design(candidates: Sequence[Any], titration_type: str, spec: Spec) -> np.ndarray:
    base = base_design(candidates, spec)
    if spec.pooling == "global":
        return base
    one_hot = np.zeros(len(TYPE_ORDER), dtype=float)
    one_hot[TYPE_ORDER.index(titration_type)] = 1.0
    interactions = [base * value for value in one_hot]
    context = np.repeat(one_hot[None, :], len(base), axis=0)
    return np.column_stack([base, *interactions, context])


def fit_model(
    train_runs: Sequence[CsvRun],
    prepared: Mapping[str, Mapping[str, CsvRun]],
    candidates: Mapping[str, Mapping[str, Sequence[Any]]],
    spec: Spec,
):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    x_parts = []
    y_parts = []
    weights = []
    for original in train_runs:
        path = str(original.path)
        run = prepared[spec.sampling][path]
        run_candidates = candidates[spec.sampling][path]
        x_parts.append(design(run_candidates, original.titration_type, spec))
        errors = np.asarray(
            [
                abs(
                    float(run.rows[candidate.boundary]["injected_volume_ml"])
                    - float(original.theoretical_equivalence_volume_ml)
                )
                for candidate in run_candidates
            ],
            dtype=float,
        )
        quality = rank_quality(errors)
        if spec.target == "exp_rank":
            quality = np.exp(-4.0 * (1.0 - quality))
        y_parts.append(quality)
        weights.extend([1.0 / len(run_candidates)] * len(run_candidates))
    model = make_pipeline(StandardScaler(), Ridge(alpha=spec.alpha))
    model.fit(
        np.vstack(x_parts),
        np.concatenate(y_parts),
        ridge__sample_weight=np.asarray(weights, dtype=float),
    )
    return model


def predict(
    model: Any,
    original: CsvRun,
    prepared: Mapping[str, Mapping[str, CsvRun]],
    candidates: Mapping[str, Mapping[str, Sequence[Any]]],
    spec: Spec,
) -> float:
    path = str(original.path)
    run = prepared[spec.sampling][path]
    run_candidates = candidates[spec.sampling][path]
    scores = np.asarray(
        model.predict(design(run_candidates, original.titration_type, spec)),
        dtype=float,
    )
    selected = int(np.argmax(scores))
    frame = run_candidates[selected].boundary
    return float(run.rows[frame]["injected_volume_ml"])


def inner_select(
    outer_train: Sequence[CsvRun],
    prepared: Mapping[str, Mapping[str, CsvRun]],
    candidates: Mapping[str, Mapping[str, Sequence[Any]]],
) -> tuple[Spec, dict[str, float]]:
    scores = {}
    for spec in SPECS:
        errors = []
        for validation in outer_train:
            inner_train = [run for run in outer_train if run.path != validation.path]
            model = fit_model(inner_train, prepared, candidates, spec)
            prediction = predict(model, validation, prepared, candidates, spec)
            errors.append(
                abs(prediction - validation.theoretical_equivalence_volume_ml)
                / validation.theoretical_equivalence_volume_ml
                * 100.0
            )
        scores[spec] = statistics.mean(errors)
    selected = min(SPECS, key=lambda spec: (scores[spec], spec))
    return selected, {
        json.dumps(asdict(spec), sort_keys=True): value
        for spec, value in sorted(scores.items())
    }


def metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    signed = [row["predicted_ml"] - row["actual_ml"] for row in rows]
    absolute = [abs(value) for value in signed]
    ape = [
        value / row["actual_ml"] * 100.0 for value, row in zip(absolute, rows)
    ]
    return {
        "mae_ml": statistics.mean(absolute),
        "rmse_ml": statistics.mean(value * value for value in signed) ** 0.5,
        "mape_percent": statistics.mean(ape),
        "max_abs_error_ml": max(absolute),
        "max_ape_percent": max(ape),
    }


def evaluate(runs: Sequence[CsvRun]) -> dict[str, Any]:
    prepared = prepared_runs(runs)
    candidates = candidate_sets(prepared)
    predictions = []
    for test in runs:
        outer_train = [run for run in runs if run.path != test.path]
        selected, inner_scores = inner_select(outer_train, prepared, candidates)
        model = fit_model(outer_train, prepared, candidates, selected)
        predicted = predict(model, test, prepared, candidates, selected)
        predictions.append(
            {
                "run": test.path.name,
                "titration_type": test.titration_type,
                "actual_ml": float(test.theoretical_equivalence_volume_ml),
                "predicted_ml": predicted,
                "selected_spec": asdict(selected),
                "inner_mape_by_spec": inner_scores,
            }
        )
    selection_counts = {}
    for row in predictions:
        key = json.dumps(row["selected_spec"], sort_keys=True)
        selection_counts[key] = selection_counts.get(key, 0) + 1
    return {
        "schema_version": "strict_nested_partial_pooling_endpoint_v1",
        "run_count": len(runs),
        "candidate_spec_count": len(SPECS),
        "candidate_specs": [asdict(spec) for spec in SPECS],
        "split": (
            "outer leave-one-run-out; every sampling/pooling/subset/target/alpha "
            "choice selected by inner leave-one-run-out on outer training runs only"
        ),
        "model_inputs": (
            "sensor candidate features and known titration type only; volume used "
            "only for labels and selected-frame conversion"
        ),
        "metrics": metrics(predictions),
        "selection_counts": selection_counts,
        "predictions": predictions,
        "limitations": [
            "Candidate generation was developed before this nested comparison.",
            "Only 12 independent runs are available.",
            "Theoretical nominal volumes are not independently standardized wet references.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = evaluate(load_runs(args.input))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
