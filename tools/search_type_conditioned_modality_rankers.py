#!/usr/bin/env python3
"""Per-modality, per-titration-type development search for sequence rankers.

Color and thermal candidate unions are built independently.  For each known
titration type, the ranker family, feature subset, transform, score
normalization, global/type score weight, and aggregation are selected on the
same 12 development runs.  Each evaluated run remains excluded from model and
scaler fitting, but its outcome participates in configuration selection.

This is deliberately comparable to the existing fused post-hoc development
search.  It is not nested model-selection validation and not independent
external validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import os
import platform
import sys
import time
from dataclasses import asdict
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
from tools import search_advanced_type_conditioned_sensor_rankers as rankers  # noqa: E402
from tools.type_conditioned_sequence_modality_ablation import (  # noqa: E402
    generate_candidates,
)

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_ROOT = Path("data/ml/type_conditioned_modality_ranker_search")
TYPE_NAMES = rankers.TYPE_NAMES
SEEDS = rankers.SEEDS


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (list, dict, tuple)) else value
                for key, value in row.items()
            })


def coarse_aggregations() -> list[tuple[Any, ...]]:
    return [(1, 1.0, 1.0)] + list(itertools.product(
        (3, 5, 10, 20, 0),
        (0.05, 0.1, 0.3, 1.0),
        (0.0, 0.25, 0.5, 0.75),
    ))


def _evaluate_rows(
    runs: Sequence[CsvRun],
    sets,
    folds,
    *,
    normalization: str,
    global_weight: float,
    aggregation: tuple[Any, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for test in runs:
        global_scores, type_scores = folds[str(test.path)]
        score = (
            global_weight * rankers.normalize(global_scores, normalization)
            + (1.0 - global_weight) * rankers.normalize(type_scores, normalization)
        )
        boundary = rankers.aggregate(sets[str(test.path)], score, aggregation)
        boundary = max(0, min(boundary, len(test.rows) - 1))
        predicted = float(test.rows[boundary]["injected_volume_ml"])
        actual = float(test.theoretical_equivalence_volume_ml)
        rows.append({
            "run_path": str(test.path),
            "run_name": test.path.name,
            "titration_type": test.titration_type,
            "selected_boundary_audit_only": boundary,
            "predicted_equivalence_volume_ml": predicted,
            "actual_equivalence_volume_ml": actual,
            "signed_error_ml": predicted - actual,
            "absolute_error_ml": abs(predicted - actual),
            "ape_percent": abs(predicted - actual) / actual * 100.0,
            "outer_fit_run_paths": [
                str(run.path) for run in runs if run.path != test.path
            ],
        })
    return rows


def _dense_grid(titration_type: str):
    if titration_type == "strong_acid_strong_base":
        return (
            np.linspace(0.0, 1.0, 21),
            np.geomspace(0.05, 2.0, 40),
            np.linspace(0.0, 0.5, 21),
            [1, 2, 3, 5, 10, 20, 40, 64, 80, 100, 0],
        )
    if titration_type == "weak_acid_strong_base":
        return (
            np.linspace(0.0, 1.0, 51),
            np.geomspace(0.05, 2.0, 50),
            np.linspace(0.0, 0.5, 21),
            list(range(1, 31)) + [40, 64, 0],
        )
    if titration_type == "strong_acid_weak_base":
        return (
            np.linspace(0.0, 1.0, 21),
            np.geomspace(0.02, 1.0, 50),
            np.linspace(0.0, 0.5, 21),
            list(range(1, 31)) + [40, 64, 80, 100, 0],
        )
    return (
        np.linspace(0.0, 1.0, 21),
        np.geomspace(0.02, 1.0, 50),
        np.linspace(0.0, 0.5, 21),
        list(range(1, 21)) + [30, 40, 64, 0],
    )


def _dense_refine(
    runs: Sequence[CsvRun], sets, selected: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int]:
    output: dict[str, dict[str, Any]] = {}
    combinations = 0
    for titration_type in TYPE_NAMES:
        selected_config = selected[titration_type]
        spec = rankers.Spec(**selected_config["spec"])
        type_runs = [run for run in runs if run.titration_type == titration_type]
        folds = {}
        for test in type_runs:
            outer = [run for run in runs if run.path != test.path]
            same_type = [
                run for run in outer if run.titration_type == titration_type
            ]
            folds[str(test.path)] = (
                rankers.score_one(outer, sets[str(test.path)], sets, spec),
                rankers.score_one(same_type, sets[str(test.path)], sets, spec),
            )

        weights, temperatures, blends, top_ks = _dense_grid(titration_type)
        normalizations = ("rank", "zscore")
        combinations += (
            len(normalizations) * len(weights) * len(temperatures)
            * len(blends) * len(top_ks)
        )
        best = None
        for normalization in normalizations:
            normalized = {
                path: (
                    rankers.normalize(global_scores, normalization),
                    rankers.normalize(type_scores, normalization),
                )
                for path, (global_scores, type_scores) in folds.items()
            }
            for weight in weights:
                prepared = []
                for test in type_runs:
                    global_scores, type_scores = normalized[str(test.path)]
                    score = weight * global_scores + (1.0 - weight) * type_scores
                    order = np.argsort(-score, kind="stable")
                    prepared.append((test, score, order))
                for top_k in top_ks:
                    for temperature in temperatures:
                        centroids, top_boundaries = [], []
                        for test, score, order in prepared:
                            chosen = order if top_k == 0 else order[:min(top_k, len(order))]
                            z = (score[chosen] - float(np.max(score[chosen]))) / temperature
                            exp_weights = np.exp(z)
                            exp_weights /= float(np.sum(exp_weights))
                            candidates = sets[str(test.path)]
                            centroids.append(float(np.dot(
                                exp_weights,
                                [candidates[int(index)].boundary for index in chosen],
                            )))
                            top_boundaries.append(candidates[int(order[0])].boundary)
                        frames = np.rint(
                            np.outer(1.0 - blends, centroids)
                            + np.outer(blends, top_boundaries)
                        ).astype(int)
                        ape = np.empty_like(frames, dtype=float)
                        for column, test in enumerate(type_runs):
                            frames[:, column] = np.clip(
                                frames[:, column], 0, len(test.rows) - 1
                            )
                            actual = float(test.theoretical_equivalence_volume_ml)
                            ape[:, column] = [
                                abs(float(test.rows[int(frame)]["injected_volume_ml"]) - actual)
                                / actual * 100.0
                                for frame in frames[:, column]
                            ]
                        means = np.mean(ape, axis=1)
                        blend_index = int(np.argmin(means))
                        key = (
                            float(means[blend_index]), normalization, float(weight),
                            int(top_k), float(temperature), float(blends[blend_index]),
                        )
                        if best is None or key < best[:6]:
                            rows = []
                            for column, test in enumerate(type_runs):
                                frame = int(frames[blend_index, column])
                                predicted = float(test.rows[frame]["injected_volume_ml"])
                                actual = float(test.theoretical_equivalence_volume_ml)
                                rows.append({
                                    "run_path": str(test.path),
                                    "run_name": test.path.name,
                                    "titration_type": titration_type,
                                    "selected_boundary_audit_only": frame,
                                    "predicted_equivalence_volume_ml": predicted,
                                    "actual_equivalence_volume_ml": actual,
                                    "signed_error_ml": predicted - actual,
                                    "absolute_error_ml": abs(predicted - actual),
                                    "ape_percent": abs(predicted - actual) / actual * 100.0,
                                    "outer_fit_run_paths": [
                                        str(run.path) for run in runs if run.path != test.path
                                    ],
                                })
                            best = key + (rows,)
        assert best is not None
        mape, normalization, weight, top_k, temperature, blend, rows = best
        output[titration_type] = {
            "mape_percent": mape,
            "spec": asdict(spec),
            "normalization": normalization,
            "global_weight": weight,
            "same_type_weight": 1.0 - weight,
            "top_k": top_k,
            "temperature": temperature,
            "top_blend": blend,
            "rows": rows,
        }
        print(json.dumps({
            "phase": "dense",
            "titration_type": titration_type,
            "mape_percent": mape,
        }), flush=True)
    return output, combinations


def run_search(
    modality: str,
    *,
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    if modality not in {"color", "thermal", "fusion"}:
        raise ValueError(f"unknown modality: {modality}")
    started = time.perf_counter()
    output = Path(output_dir or DEFAULT_OUTPUT_ROOT / modality)
    output.mkdir(parents=True, exist_ok=True)
    runs = load_runs(input_dir)
    if len(runs) != 12:
        raise ValueError(f"expected 12 runs, found {len(runs)}")
    sets = {
        str(run.path): generate_candidates(run.rows, modality) for run in runs
    }
    empty = [Path(path).name for path, candidates in sets.items() if not candidates]
    if empty:
        raise ValueError(f"{modality} produced no candidates: {empty}")

    best_by_type: dict[str, tuple[Any, ...]] = {}
    failures = []
    aggregation_grid = coarse_aggregations()
    all_specs = rankers.specs()
    coarse_count = (
        len(all_specs) * 2 * 5 * len(aggregation_grid)
    )
    for spec_index, spec in enumerate(all_specs, 1):
        folds = {}
        try:
            for test in runs:
                outer = [run for run in runs if run.path != test.path]
                same_type = [
                    run for run in outer if run.titration_type == test.titration_type
                ]
                folds[str(test.path)] = (
                    rankers.score_one(outer, sets[str(test.path)], sets, spec),
                    rankers.score_one(same_type, sets[str(test.path)], sets, spec),
                )
        except Exception as error:
            failures.append({"spec": spec.name, "error": f"{type(error).__name__}: {error}"})
            continue

        for normalization, weight, aggregation in itertools.product(
            ("rank", "zscore"),
            (0.0, 0.25, 0.5, 0.75, 1.0),
            aggregation_grid,
        ):
            rows = _evaluate_rows(
                runs,
                sets,
                folds,
                normalization=normalization,
                global_weight=weight,
                aggregation=aggregation,
            )
            config = {
                "spec": asdict(spec),
                "normalization": normalization,
                "global_weight": weight,
                "same_type_weight": 1.0 - weight,
                "top_k": aggregation[0],
                "temperature": aggregation[1],
                "top_blend": aggregation[2],
            }
            config_id = hashlib.sha256(
                json.dumps(config, sort_keys=True).encode()
            ).hexdigest()[:16]
            for titration_type in TYPE_NAMES:
                selected_rows = [
                    row for row in rows if row["titration_type"] == titration_type
                ]
                mape = float(np.mean([row["ape_percent"] for row in selected_rows]))
                key = (mape, config_id, config, selected_rows)
                if (
                    titration_type not in best_by_type
                    or key[:2] < best_by_type[titration_type][:2]
                ):
                    best_by_type[titration_type] = key

        if spec_index % 25 == 0 or spec_index == len(all_specs):
            current = float(np.mean([
                best_by_type[name][0] for name in TYPE_NAMES
            ]))
            print(json.dumps({
                "phase": "coarse",
                "modality": modality,
                "completed": spec_index,
                "total": len(all_specs),
                "typewise_mape_percent": current,
            }), flush=True)

    selected = {
        name: {
            "mape_percent": best_by_type[name][0],
            "config_id": best_by_type[name][1],
            **best_by_type[name][2],
        }
        for name in TYPE_NAMES
    }
    dense, dense_count = _dense_refine(runs, sets, selected)
    rows = [row for name in TYPE_NAMES for row in dense[name]["rows"]]
    actual = np.asarray([row["actual_equivalence_volume_ml"] for row in rows])
    predicted = np.asarray([row["predicted_equivalence_volume_ml"] for row in rows])
    errors = predicted - actual
    metrics = {
        "mae_ml": float(np.mean(np.abs(errors))),
        "rmse_ml": float(np.sqrt(np.mean(errors * errors))),
        "mape_percent": float(np.mean(np.abs(errors) / actual) * 100.0),
        "max_absolute_error_ml": float(np.max(np.abs(errors))),
    }
    summary = {
        "schema_version": "type_conditioned_modality_ranker_search_v1",
        "modality": modality,
        "claim_scope": (
            "post_hoc_per_modality_per_titration_type_configuration_selection_"
            "on_same_12_development_runs_not_independent_validation"
        ),
        "poster_performance_claim_allowed": False,
        "run_count": len(runs),
        "known_context_input": ["titration_type"],
        "candidate_counts": {
            run.path.name: len(sets[str(run.path)]) for run in runs
        },
        "search": {
            "ranker_spec_count": len(all_specs),
            "coarse_configuration_count": coarse_count,
            "dense_configuration_count": dense_count,
            "total_configuration_count": coarse_count + dense_count,
            "failed_spec_count": len(failures),
        },
        "selected_type_configs": dense,
        "metrics": metrics,
        "predictions": rows,
        "determinism": {
            "seeds": list(SEEDS),
            "identical_predictions": True,
            "note": "estimators are deterministic; seeds are repeat labels only",
        },
        "validation_caveat": (
            "Each run is excluded from model/scaler fitting, but per-modality and "
            "per-type configurations minimize error on these same 12 outer-LORO "
            "development outcomes. This is not nested model-selection validation "
            "and not independent external validation."
        ),
        "selection_audit": {
            "outer_test_excluded_from_model_fit": True,
            "outer_test_truth_used_for_configuration_selection": True,
            "interpretation": (
                "Millions of configurations were selected against the same 12 "
                "outcomes. The resulting near-oracle frames are audit-only and "
                "must not be reported as predictive accuracy."
            ),
        },
        "runtime_seconds": time.perf_counter() - started,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
        },
    }
    import sklearn
    summary["versions"]["scikit_learn"] = sklearn.__version__
    write_csv(output / "predictions.csv", rows)
    write_csv(output / "selected_configs.csv", [
        {
            "titration_type": name,
            **{key: value for key, value in dense[name].items() if key != "rows"},
        }
        for name in TYPE_NAMES
    ])
    write_csv(output / "failed_specs.csv", failures)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "modality": modality,
        "metrics": metrics,
        "output": str(output),
    }, ensure_ascii=False, indent=2), flush=True)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modality", required=True, choices=("color", "thermal", "fusion"))
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir")
    args = parser.parse_args(argv)
    run_search(
        args.modality,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
