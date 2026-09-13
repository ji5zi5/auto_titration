#!/usr/bin/env python3
"""Bounded exploratory nested search using sensor features only.

This analysis is deliberately separate from frozen report evidence.  It uses
the existing 12 CSV runs, evaluates one held-out run at a time, and performs
all feature-preset/model/aggregation selection using only the outer training
runs.  The three prescribed random seeds are evaluation replicates, not a
pool from which a best seed is selected.

Injected/current volume and theoretical endpoint values are used only to make
training labels and convert frame scores into an endpoint prediction.  They
are never included in a model feature matrix.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import resource
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Set these before importing NumPy/scikit-learn so native libraries remain
# bounded even when the caller has permissive machine-wide defaults.
for _name in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[_name] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_curve_equivalence import _to_float, run_level_metrics  # noqa: E402
from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from tools.train_equivalence_current_volume import classifier_aggregate_predictions  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/exploratory_robust_sensor_search")
SEEDS = (42, 1729, 20260728)
AGGREGATIONS = ("top1", "top3", "top5", "weighted_median_top5")

FORBIDDEN_EXACT = {
    "injected_volume_ml",
    "confirmed_injected_volume_ml",
    "commanded_volume_ml",
    "sample_concentration_M",
    "theoretical_equivalence_volume_ml",
    "theoretical_equivalence_time_s",
    "theoretical_equivalence_pH",
    "distance_to_equivalence_ml",
    "time_to_equivalence_s",
    "equivalence_window_ml",
    "equivalence_window_label",
    "candidate_fraction_of_run",
    "run_volume_max_ml",
    "run_duration_s",
    "time_s",
    "visible_time_s",
    "thermal_time_s",
    "csv_recording_elapsed_s",
    "pump_elapsed_s",
}
FORBIDDEN_TOKENS = (
    "equivalence",
    "concentration",
    "injected_volume",
    "commanded_volume",
    "distance_to_",
    "time_to_",
    "fraction_of_run",
    "run_volume",
    "run_duration",
    "remaining",
    "progress",
    "_label",
    "_target",
    "actual_",
    "predicted_",
    "estimated_",
    "reference_",
)
SENSOR_METADATA_TOKENS = (
    "_time",
    "capture_",
    "conversion_",
    "matrix_shape",
    "frame_rate",
    "rotation",
    "calibrated",
    "_source",
    "_width",
    "_height",
    "_x",
    "_y",
)


@dataclass(frozen=True, order=True)
class Candidate:
    modality: str
    model: str
    aggregation: str


def _number(value: Any) -> float | None:
    result = _to_float(value)
    return None if result is None else float(result)


def is_forbidden_feature(column: str) -> bool:
    lowered = str(column).lower()
    return column in FORBIDDEN_EXACT or any(token in lowered for token in FORBIDDEN_TOKENS)


def forbidden_features(columns: Iterable[str]) -> list[str]:
    return sorted(column for column in columns if is_forbidden_feature(column))


def _is_sensor_feature(column: str) -> bool:
    lowered = column.lower()
    return (
        column.startswith(("visible_", "thermal_roi_", "thermal_raw_"))
        and not is_forbidden_feature(column)
        and not any(token in lowered for token in SENSOR_METADATA_TOKENS)
    )


def select_sensor_columns(columns: Iterable[str], modality: str) -> list[str]:
    """Return deterministic, numeric sensor-only candidate columns."""

    if modality not in {"color", "thermal", "fusion"}:
        raise ValueError(f"unknown modality: {modality}")
    sensor = sorted(column for column in set(columns) if _is_sensor_feature(column))
    if modality == "color":
        selected = [column for column in sensor if column.startswith("visible_")]
    elif modality == "thermal":
        selected = [column for column in sensor if column.startswith(("thermal_roi_", "thermal_raw_"))]
    else:
        selected = sensor
    blocked = forbidden_features(selected)
    if blocked:
        raise ValueError(f"forbidden model features: {blocked}")
    if not selected:
        raise ValueError(f"no usable {modality} sensor features")
    return selected


def candidate_space() -> tuple[Candidate, ...]:
    return tuple(
        Candidate(modality, model, aggregation)
        for modality in ("color", "thermal", "fusion")
        for model in ("extra_trees", "random_forest")
        for aggregation in AGGREGATIONS
    )


def _resampled_rows(run: CsvRun, grid_ml: float) -> list[Mapping[str, Any]]:
    if grid_ml <= 0:
        raise ValueError("grid_ml must be positive")
    rows: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    ordered = sorted(
        (
            (float(volume), row)
            for row in run.rows
            if (volume := _number(row.get("injected_volume_ml"))) is not None
        ),
        key=lambda item: item[0],
    )
    for volume, row in ordered:
        bin_id = int(round(volume / grid_ml))
        if bin_id not in seen:
            seen.add(bin_id)
            rows.append(row)
    return rows


def _run_records(
    runs: Sequence[CsvRun], columns_by_modality: Mapping[str, Sequence[str]], grid_ml: float
) -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        run_rows: list[dict[str, Any]] = []
        for row in _resampled_rows(run, grid_ml):
            volume = _number(row.get("injected_volume_ml"))
            if volume is None:
                continue
            features = {
                modality: [
                    np.nan if _number(row.get(column)) is None else float(_number(row.get(column)))
                    for column in columns
                ]
                for modality, columns in columns_by_modality.items()
            }
            run_rows.append(
                {
                    "run_path": str(run.path),
                    "current_volume_ml_audit_only": volume,
                    "actual_ml_audit_only": float(run.theoretical_equivalence_volume_ml),
                    "features": features,
                }
            )
        records[str(run.path)] = run_rows
    return records


def _make_model(name: str, *, seed: int, n_estimators: int):
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import make_pipeline

    common = dict(
        n_estimators=n_estimators,
        random_state=seed,
        min_samples_leaf=2,
        class_weight="balanced",
        n_jobs=1,
        max_features="sqrt",
    )
    if name == "extra_trees":
        estimator = ExtraTreesClassifier(**common)
    elif name == "random_forest":
        estimator = RandomForestClassifier(**common)
    else:
        raise ValueError(f"unknown model: {name}")
    return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), estimator)


def _fit_score_run(
    train_records: Sequence[Mapping[str, Any]],
    test_records: Sequence[Mapping[str, Any]],
    candidate: Candidate,
    *,
    seed: int,
    zone_window_ml: float,
    n_estimators: int,
) -> tuple[np.ndarray, np.ndarray]:
    x_train = np.asarray([row["features"][candidate.modality] for row in train_records], dtype=float)
    x_test = np.asarray([row["features"][candidate.modality] for row in test_records], dtype=float)
    y_train = np.asarray(
        [
            abs(float(row["current_volume_ml_audit_only"]) - float(row["actual_ml_audit_only"]))
            <= zone_window_ml
            for row in train_records
        ],
        dtype=int,
    )
    if len(set(y_train.tolist())) < 2:
        raise ValueError("training fold contains only one endpoint-zone class")
    model = _make_model(candidate.model, seed=seed, n_estimators=n_estimators)
    model.fit(x_train, y_train)
    estimator = model.steps[-1][1]
    positive_index = list(estimator.classes_).index(1)
    scores = np.asarray(model.predict_proba(x_test)[:, positive_index], dtype=float)
    volumes = np.asarray([row["current_volume_ml_audit_only"] for row in test_records], dtype=float)
    return volumes, scores


def _aggregate(volumes: np.ndarray, scores: np.ndarray, mode: str) -> float:
    predictions = classifier_aggregate_predictions(volumes, scores)
    return float(predictions[mode])


def _inner_select(
    train_runs: Sequence[CsvRun],
    records_by_run: Mapping[str, Sequence[Mapping[str, Any]]],
    candidates: Sequence[Candidate],
    *,
    seed: int,
    zone_window_ml: float,
    n_estimators: int,
) -> tuple[Candidate, dict[str, float]]:
    """Nested LORO candidate selection, excluding the outer test run."""

    errors: dict[Candidate, list[float]] = {candidate: [] for candidate in candidates}
    grouped: dict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[(candidate.modality, candidate.model)].append(candidate)
    for validation_run in train_runs:
        validation_path = str(validation_run.path)
        inner_train = [
            record
            for run in train_runs
            if str(run.path) != validation_path
            for record in records_by_run[str(run.path)]
        ]
        for same_fit_candidates in grouped.values():
            base = same_fit_candidates[0]
            volumes, scores = _fit_score_run(
                inner_train,
                records_by_run[validation_path],
                base,
                seed=seed,
                zone_window_ml=zone_window_ml,
                n_estimators=n_estimators,
            )
            actual = float(validation_run.theoretical_equivalence_volume_ml)
            for candidate in same_fit_candidates:
                errors[candidate].append(abs(_aggregate(volumes, scores, candidate.aggregation) - actual))
    mean_errors = {candidate: float(np.mean(values)) for candidate, values in errors.items()}
    selected = min(candidates, key=lambda candidate: (mean_errors[candidate], candidate))
    return selected, {
        "|".join(asdict(candidate).values()): round(error, 6)
        for candidate, error in sorted(mean_errors.items())
    }


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(run_level_metrics(rows))
    result["mape_percent"] = result["mae_percent_of_equivalence"]
    result["max_absolute_error_ml"] = round(
        max((float(row["absolute_error_ml"]) for row in rows), default=0.0), 6
    )
    return result


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({str(key) for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                    if isinstance(value, (dict, list))
                    else value
                    for key, value in row.items()
                }
            )


def evaluate_runs(
    runs: Sequence[CsvRun],
    *,
    output_dir: str | Path | None = None,
    seeds: Sequence[int] = SEEDS,
    candidates: Sequence[Candidate] | None = None,
    grid_ml: float = 0.25,
    zone_window_ml: float = 1.0,
    n_estimators: int = 32,
    expected_run_count: int = 12,
) -> dict[str, Any]:
    started = time.perf_counter()
    if len(runs) != expected_run_count:
        raise ValueError(f"expected exactly {expected_run_count} existing runs, found {len(runs)}")
    if tuple(seeds) != SEEDS:
        raise ValueError(f"seed list must be exactly {SEEDS}")
    run_paths = [str(run.path) for run in runs]
    if len(set(run_paths)) != len(run_paths):
        raise ValueError("run paths must be unique")
    candidates = tuple(candidates or candidate_space())
    if not candidates:
        raise ValueError("candidate space must not be empty")

    all_columns = set().union(*(row.keys() for run in runs for row in run.rows))
    modalities = sorted({candidate.modality for candidate in candidates})
    columns_by_modality = {
        modality: select_sensor_columns(all_columns, modality) for modality in modalities
    }
    for columns in columns_by_modality.values():
        if forbidden_features(columns):
            raise AssertionError("leakage audit failed")
    records_by_run = _run_records(runs, columns_by_modality, grid_ml)
    if any(not records_by_run[path] for path in run_paths):
        raise ValueError("one or more runs contain no usable volume-indexed rows")

    predictions: list[dict[str, Any]] = []
    per_seed_rows: list[dict[str, Any]] = []
    for seed in seeds:
        seed_predictions: list[dict[str, Any]] = []
        for test_run in runs:
            test_path = str(test_run.path)
            outer_train = [run for run in runs if str(run.path) != test_path]
            selected, inner_scores = _inner_select(
                outer_train,
                records_by_run,
                candidates,
                seed=seed,
                zone_window_ml=zone_window_ml,
                n_estimators=n_estimators,
            )
            train_records = [record for run in outer_train for record in records_by_run[str(run.path)]]
            volumes, scores = _fit_score_run(
                train_records,
                records_by_run[test_path],
                selected,
                seed=seed,
                zone_window_ml=zone_window_ml,
                n_estimators=n_estimators,
            )
            predicted = _aggregate(volumes, scores, selected.aggregation)
            actual = float(test_run.theoretical_equivalence_volume_ml)
            error = predicted - actual
            row = {
                "seed": seed,
                "run_path": test_path,
                "titration_type": test_run.titration_type,
                "held_out_concentration_m_audit_only": test_run.concentration_m,
                "actual_equivalence_volume_ml": actual,
                "predicted_equivalence_volume_ml": round(predicted, 6),
                "signed_error_ml": round(error, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(abs(error) / actual * 100.0, 6),
                "selected_modality": selected.modality,
                "selected_model": selected.model,
                "selected_aggregation": selected.aggregation,
                "selection_run_paths": [str(run.path) for run in outer_train],
                "inner_candidate_mae_ml": inner_scores,
            }
            predictions.append(row)
            seed_predictions.append(row)
        metrics = _metrics(seed_predictions)
        per_seed_rows.append({"seed": seed, **metrics})

    metric_names = ("mae_ml", "rmse_ml", "mae_percent_of_equivalence", "max_absolute_error_ml")
    aggregate_rows = []
    for metric in metric_names:
        values = np.asarray([float(row[metric]) for row in per_seed_rows], dtype=float)
        aggregate_rows.append(
            {
                "metric": metric,
                "mean_across_seeds": round(float(np.mean(values)), 6),
                "std_across_seeds": round(float(np.std(values)), 6),
                "min_across_seeds": round(float(np.min(values)), 6),
                "max_across_seeds": round(float(np.max(values)), 6),
            }
        )
    selection_counts = Counter(
        (row["selected_modality"], row["selected_model"], row["selected_aggregation"])
        for row in predictions
    )
    summary: dict[str, Any] = {
        "schema_version": "exploratory_robust_sensor_nested_search_v1",
        "claim_scope": "exploratory_development_analysis_not_independent_external_validation",
        "frozen_report_evidence": False,
        "run_count": len(runs),
        "seeds": list(seeds),
        "seed_policy": "all prescribed seeds reported; no best-seed selection",
        "split": {
            "outer": "leave_one_run_out",
            "inner_selection": "leave_one_run_out_on_outer_training_runs_only",
            "outer_test_used_for_candidate_model_or_seed_selection": False,
        },
        "model_input_policy": "sensor measurements only; volume/truth/labels are audit-label-aggregation fields, never model matrix columns",
        "feature_columns": columns_by_modality,
        "leakage_audit": {
            "forbidden_features_found": {
                modality: forbidden_features(columns) for modality, columns in columns_by_modality.items()
            },
            "passed": True,
        },
        "search": {
            "candidate_count": len(candidates),
            "candidates": [asdict(candidate) for candidate in candidates],
            "zone_window_ml_fixed": zone_window_ml,
            "grid_ml": grid_ml,
            "n_estimators": n_estimators,
            "n_jobs": 1,
            "blas_threads": 1,
        },
        "per_seed_metrics": per_seed_rows,
        "aggregate_robustness": aggregate_rows,
        "outer_predictions": predictions,
        "selection_counts": [
            {"modality": key[0], "model": key[1], "aggregation": key[2], "count": count}
            for key, count in sorted(selection_counts.items())
        ],
        "limitations": [
            "Only the 12 existing development runs were used; no independent external validation set exists.",
            "Each condition has one run, so run-level LORO cannot separate condition shift from run-to-run variation.",
            "The targets are theoretical equivalence volumes rather than independently measured endpoint ground truth.",
            "Frame rows within a run are correlated and are not independent experiment replicates.",
            "The candidate space is intentionally bounded and does not establish global model optimality.",
        ],
    }
    summary["resource_usage"] = {
        "evaluation_seconds": round(time.perf_counter() - started, 6),
        "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    try:
        import sklearn

        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = None
    summary["versions"] = {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "scikit_learn": sklearn_version,
    }

    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        _write_csv(output / "outer_predictions.csv", predictions)
        _write_csv(output / "per_seed_metrics.csv", per_seed_rows)
        _write_csv(output / "aggregate_robustness.csv", aggregate_rows)
        _write_csv(output / "selection_counts.csv", summary["selection_counts"])
        _write_csv(
            output / "feature_manifest.csv",
            [
                {"modality": modality, "feature": feature}
                for modality, columns in columns_by_modality.items()
                for feature in columns
            ],
        )
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        report = [
            "# Exploratory robust sensor-model nested search",
            "",
            "**Exploratory development analysis — not independent external validation and not frozen report evidence.**",
            "",
            f"- Existing runs: {len(runs)}",
            f"- Seeds (all reported, none selected): {', '.join(map(str, seeds))}",
            "- Validation: outer leave-one-run-out; candidate/model/aggregation selection by inner LORO on outer training runs only",
            "- Model inputs: sensor measurements only; injected/current volume, concentration, theoretical endpoint, distance/time-to-equivalence, and labels excluded",
            "- Parallelism: n_jobs=1 and BLAS/OpenMP thread caps=1",
            "",
            "## Per-seed metrics",
            "",
            "| Seed | MAE (mL) | RMSE (mL) | MAPE (%) | Max abs error (mL) |",
            "|---:|---:|---:|---:|---:|",
        ]
        for row in per_seed_rows:
            report.append(
                f"| {row['seed']} | {row['mae_ml']:.4f} | {row['rmse_ml']:.4f} | "
                f"{row['mae_percent_of_equivalence']:.4f} | {row['max_absolute_error_ml']:.4f} |"
            )
        report.extend(["", "## Aggregate robustness", ""])
        for row in aggregate_rows:
            report.append(
                f"- `{row['metric']}`: mean {row['mean_across_seeds']:.4f}, "
                f"SD {row['std_across_seeds']:.4f}, range "
                f"[{row['min_across_seeds']:.4f}, {row['max_across_seeds']:.4f}]"
            )
        report.extend(["", "## Limitations", ""] + [f"- {item}" for item in summary["limitations"]])
        (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def evaluate_folder(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    grid_ml: float = 0.25,
    zone_window_ml: float = 1.0,
    n_estimators: int = 32,
) -> dict[str, Any]:
    runs = load_runs(input_dir)
    summary = evaluate_runs(
        runs,
        output_dir=output_dir,
        grid_ml=grid_ml,
        zone_window_ml=zone_window_ml,
        n_estimators=n_estimators,
    )
    summary["input_dir"] = str(input_dir)
    Path(output_dir, "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--grid-ml", type=float, default=0.25)
    parser.add_argument("--zone-window-ml", type=float, default=1.0)
    parser.add_argument("--n-estimators", type=int, default=32)
    args = parser.parse_args(argv)
    summary = evaluate_folder(
        args.input_dir,
        output_dir=args.output_dir,
        grid_ml=args.grid_ml,
        zone_window_ml=args.zone_window_ml,
        n_estimators=args.n_estimators,
    )
    print(json.dumps({"per_seed": summary["per_seed_metrics"], "aggregate": summary["aggregate_robustness"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
