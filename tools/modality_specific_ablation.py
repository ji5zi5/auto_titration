#!/usr/bin/env python3
"""Modality-specific sensor ablation with fully nested leave-one-run-out selection.

For each sensor group and each outer held-out run, model family,
hyperparameters, and run-level score aggregation are selected only by an inner
leave-one-run-out evaluation over the outer training runs.  The outer test run
is used once, after selection, for an unbiased development-set prediction.

Only current injected volume and current/past-derived sensor values are model
inputs.  Labels, nominal/theoretical equivalence values, concentration,
end-of-run summaries, progress proxies, identifiers, and elapsed-time fields
are denied.
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import resource
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_curve_equivalence import _to_float, run_level_metrics  # noqa: E402
from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402
from tools.train_equivalence_current_volume import classifier_aggregate_predictions  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/modality_specific_ablation")
FEATURE_GROUPS = (
    "volume_only",
    "color_plus_volume",
    "thermal_plus_volume",
    "color_thermal_plus_volume",
)
AGGREGATION_MODES = ("top1", "top3", "top5", "top10", "weighted_median_top5")
RANDOM_STATE = 42

FORBIDDEN_EXACT = {
    "run_volume_max_ml",
    "run_duration_s",
    "candidate_fraction_of_run",
    "sample_concentration_M",
    "theoretical_equivalence_volume_ml",
    "theoretical_equivalence_time_s",
    "theoretical_equivalence_pH",
    "distance_to_equivalence_ml",
    "time_to_equivalence_s",
    "equivalence_window_ml",
    "equivalence_window_label",
    "csv_row_index",
    "frame_id",
    "csv_session_id",
    "roi_session_id",
    "time_s",
    "thermal_time_s",
    "visible_time_s",
    "csv_recording_elapsed_s",
    "pump_elapsed_s",
}
FORBIDDEN_TOKENS = (
    "equivalence",
    "concentration",
    "distance_to_",
    "time_to_",
    "progress",
    "fraction_of_run",
    "run_duration",
    "run_volume_max",
    "remaining",
    "_label",
    "_target",
    "actual_",
    "predicted_",
    "estimated_",
    "reference_",
    "session_id",
    "frame_id",
    "row_index",
    "elapsed",
)
SENSOR_METADATA_TOKENS = (
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


@dataclass(frozen=True)
class ModelCandidate:
    candidate_id: str
    family: str
    parameters: Mapping[str, Any]


def _number(value: Any) -> float | None:
    number = _to_float(value)
    return None if number is None else float(number)


def is_forbidden_feature(column: str) -> bool:
    lowered = str(column).lower()
    return column in FORBIDDEN_EXACT or any(token in lowered for token in FORBIDDEN_TOKENS)


def forbidden_features(columns: Iterable[str]) -> list[str]:
    return sorted(column for column in columns if is_forbidden_feature(column))


def _is_color_feature(column: str) -> bool:
    lowered = column.lower()
    return (
        column.startswith("visible_")
        and not column.startswith("visible_thermal_")
        and not is_forbidden_feature(column)
        and not any(token in lowered for token in SENSOR_METADATA_TOKENS)
    )


def _is_thermal_feature(column: str) -> bool:
    lowered = column.lower()
    return (
        column.startswith(("thermal_roi_", "thermal_raw_", "thermal_raw_roi_"))
        and not is_forbidden_feature(column)
        and not any(token in lowered for token in SENSOR_METADATA_TOKENS)
    )


def select_feature_columns(columns: Iterable[str], group: str) -> list[str]:
    if group not in FEATURE_GROUPS:
        raise ValueError(f"unknown feature group: {group}")
    available = set(columns)
    if "injected_volume_ml" not in available:
        raise ValueError("injected_volume_ml is required")
    selected = ["injected_volume_ml"]
    if group in {"color_plus_volume", "color_thermal_plus_volume"}:
        selected.extend(sorted(column for column in available if _is_color_feature(column)))
    if group in {"thermal_plus_volume", "color_thermal_plus_volume"}:
        selected.extend(sorted(column for column in available if _is_thermal_feature(column)))
    blocked = forbidden_features(selected)
    if blocked:
        raise ValueError(f"forbidden modality-ablation features: {blocked}")
    if group == "color_plus_volume" and any("thermal" in column for column in selected):
        raise ValueError("thermal-derived feature leaked into color group")
    if group == "thermal_plus_volume" and any(column.startswith("visible_") for column in selected):
        raise ValueError("visible feature leaked into thermal group")
    return selected


def project_row(row: Mapping[str, Any], columns: Sequence[str]) -> list[float]:
    return [float(_number(row.get(column)) or 0.0) for column in columns]


def candidate_space(group: str, *, n_estimators: int = 48) -> tuple[ModelCandidate, ...]:
    """Return a small, modality-aware search space.

    Linear models cover smooth standardized responses, histogram boosting covers
    nonlinear low-memory fits, and randomized trees cover sensor interactions.
    Volume-only deliberately avoids a high-dimensional tree configuration.
    """

    if group == "volume_only":
        return (
            ModelCandidate("logistic_c0p25", "LogisticRegression", {"C": 0.25}),
            ModelCandidate("logistic_c2", "LogisticRegression", {"C": 2.0}),
            ModelCandidate(
                "hist_depth3_leaf20",
                "HistGradientBoostingClassifier",
                {"max_depth": 3, "min_samples_leaf": 20, "max_iter": 60, "learning_rate": 0.08},
            ),
        )
    if group == "color_plus_volume":
        return (
            ModelCandidate("logistic_c0p25", "LogisticRegression", {"C": 0.25}),
            ModelCandidate(
                "extra_sqrt_leaf2",
                "ExtraTreesClassifier",
                {"n_estimators": n_estimators, "min_samples_leaf": 2, "max_features": "sqrt"},
            ),
            ModelCandidate(
                "hist_depth4_leaf15",
                "HistGradientBoostingClassifier",
                {"max_depth": 4, "min_samples_leaf": 15, "max_iter": 60, "learning_rate": 0.08},
            ),
        )
    if group == "thermal_plus_volume":
        return (
            ModelCandidate("logistic_c0p1", "LogisticRegression", {"C": 0.1}),
            ModelCandidate(
                "extra_sqrt_leaf2",
                "ExtraTreesClassifier",
                {"n_estimators": n_estimators, "min_samples_leaf": 2, "max_features": "sqrt"},
            ),
            ModelCandidate(
                "hist_depth5_leaf20",
                "HistGradientBoostingClassifier",
                {"max_depth": 5, "min_samples_leaf": 20, "max_iter": 60, "learning_rate": 0.08},
            ),
        )
    if group == "color_thermal_plus_volume":
        return (
            ModelCandidate("logistic_c0p1", "LogisticRegression", {"C": 0.1}),
            ModelCandidate(
                "extra_sqrt_leaf2",
                "ExtraTreesClassifier",
                {"n_estimators": n_estimators, "min_samples_leaf": 2, "max_features": "sqrt"},
            ),
            ModelCandidate(
                "extra_half_leaf4",
                "ExtraTreesClassifier",
                {"n_estimators": n_estimators, "min_samples_leaf": 4, "max_features": 0.5},
            ),
            ModelCandidate(
                "hist_depth5_leaf20",
                "HistGradientBoostingClassifier",
                {"max_depth": 5, "min_samples_leaf": 20, "max_iter": 60, "learning_rate": 0.08},
            ),
        )
    raise ValueError(f"unknown feature group: {group}")


def build_model(candidate: ModelCandidate):
    if candidate.family == "LogisticRegression":
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        return make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=float(candidate.parameters["C"]),
                class_weight="balanced",
                max_iter=500,
                random_state=RANDOM_STATE,
                solver="liblinear",
            ),
        )
    if candidate.family == "ExtraTreesClassifier":
        from sklearn.ensemble import ExtraTreesClassifier

        return ExtraTreesClassifier(
            **candidate.parameters,
            class_weight="balanced",
            n_jobs=1,
            random_state=RANDOM_STATE,
        )
    if candidate.family == "HistGradientBoostingClassifier":
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            **candidate.parameters,
            class_weight="balanced",
            random_state=RANDOM_STATE,
        )
    raise ValueError(f"unsupported model family: {candidate.family}")


def _volume_resampled_rows(run: CsvRun, grid_ml: float) -> list[Mapping[str, Any]]:
    if grid_ml <= 0:
        raise ValueError("grid_ml must be positive")
    selected: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    rows = sorted(
        (
            (float(volume), row)
            for row in run.rows
            if (volume := _number(row.get("injected_volume_ml"))) is not None
        ),
        key=lambda item: item[0],
    )
    for volume, row in rows:
        bin_id = int(round(volume / grid_ml))
        if bin_id not in seen:
            seen.add(bin_id)
            selected.append(row)
    return selected


def _records(runs: Sequence[CsvRun], columns: Sequence[str], grid_ml: float) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for run in runs:
        for row in _volume_resampled_rows(run, grid_ml):
            current = _number(row.get("injected_volume_ml"))
            if current is not None:
                records.append(
                    {
                        "run_path": str(run.path),
                        "current_volume_ml": float(current),
                        "actual_ml": float(run.theoretical_equivalence_volume_ml),
                        "features": project_row(row, columns),
                    }
                )
    return records


def _by_run(records: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["run_path"])].append(record)
    return grouped


def _fit_scores(
    train_records: Sequence[Mapping[str, Any]],
    test_records: Sequence[Mapping[str, Any]],
    *,
    zone_window_ml: float,
    candidate: ModelCandidate,
) -> tuple[np.ndarray, np.ndarray]:
    x_train = np.asarray([record["features"] for record in train_records], dtype=float)
    x_test = np.asarray([record["features"] for record in test_records], dtype=float)
    y_train = np.asarray(
        [
            abs(float(record["current_volume_ml"]) - float(record["actual_ml"])) <= zone_window_ml
            for record in train_records
        ],
        dtype=int,
    )
    if len(set(y_train.tolist())) < 2:
        raise ValueError("training fold contains only one zone class")
    fitted = build_model(candidate)
    fitted.fit(x_train, y_train)
    positive_index = list(fitted.classes_).index(1)
    scores = np.asarray(fitted.predict_proba(x_test)[:, positive_index], dtype=float)
    current = np.asarray([record["current_volume_ml"] for record in test_records], dtype=float)
    return current, scores


def _aggregate_candidates(current: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    predictions = classifier_aggregate_predictions(current, scores)
    return {mode: float(predictions[mode]) for mode in AGGREGATION_MODES}


def _select_configuration(
    train_runs: Sequence[CsvRun],
    records_by_run: Mapping[str, Sequence[Mapping[str, Any]]],
    candidates: Sequence[ModelCandidate],
    *,
    zone_window_ml: float,
) -> tuple[ModelCandidate, str, dict[str, float]]:
    """Jointly select model configuration and aggregation on outer-train only."""

    errors: dict[str, list[float]] = {
        f"{candidate.candidate_id}|{mode}": []
        for candidate in candidates
        for mode in AGGREGATION_MODES
    }
    for validation_run in train_runs:
        validation_path = str(validation_run.path)
        inner_train = [
            record
            for run in train_runs
            if str(run.path) != validation_path
            for record in records_by_run[str(run.path)]
        ]
        for candidate in candidates:
            current, scores = _fit_scores(
                inner_train,
                records_by_run[validation_path],
                zone_window_ml=zone_window_ml,
                candidate=candidate,
            )
            for mode, predicted in _aggregate_candidates(current, scores).items():
                errors[f"{candidate.candidate_id}|{mode}"].append(
                    abs(predicted - validation_run.theoretical_equivalence_volume_ml)
                )
    mean_errors = {key: float(np.mean(values)) for key, values in errors.items()}
    ordered_keys = list(errors)
    selected_key = min(ordered_keys, key=lambda key: (mean_errors[key], ordered_keys.index(key)))
    candidate_id, mode = selected_key.split("|", maxsplit=1)
    selected_candidate = next(candidate for candidate in candidates if candidate.candidate_id == candidate_id)
    return selected_candidate, mode, mean_errors


def _prediction_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = dict(run_level_metrics(rows))
    metrics["mape_percent"] = metrics["mae_percent_of_equivalence"]
    return metrics


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                    for key, value in row.items()
                }
            )


def evaluate_runs(
    runs: Sequence[CsvRun],
    *,
    output_dir: str | Path | None = None,
    grid_ml: float = 0.25,
    zone_window_ml: float = 1.0,
    n_estimators: int = 48,
) -> dict[str, Any]:
    started = time.perf_counter()
    if len(runs) < 4:
        raise ValueError("nested LORO requires at least four runs")
    run_paths = [str(run.path) for run in runs]
    if len(set(run_paths)) != len(run_paths):
        raise ValueError("run paths must be unique")
    all_columns = set().union(*(row.keys() for run in runs for row in run.rows))
    summary: dict[str, Any] = {
        "schema_version": "modality_specific_ablation_v1",
        "prediction_unit": "one_prediction_per_csv_run",
        "run_count": len(runs),
        "split": {
            "outer": "leave_one_run_out",
            "inner_selection": "leave_one_run_out_over_outer_training_runs_only",
            "selection_target": "minimum_inner_mean_run_level_mae_ml",
            "outer_test_used_for_model_selection": False,
            "outer_test_used_for_hyperparameter_selection": False,
            "outer_test_used_for_aggregation_selection": False,
        },
        "grid_ml": grid_ml,
        "zone_window_ml": zone_window_ml,
        "resource_limits": {
            "n_jobs": 1,
            "tree_n_estimators": n_estimators,
            "candidate_count_by_group": {
                group: len(candidate_space(group, n_estimators=n_estimators))
                for group in FEATURE_GROUPS
            },
        },
        "groups": {},
        "leakage_audit": {
            "forbidden_exact": sorted(FORBIDDEN_EXACT),
            "forbidden_tokens": list(FORBIDDEN_TOKENS),
            "all_groups_passed": True,
            "same_outer_runs_for_all_groups": True,
            "outer_test_excluded_from_all_selection": True,
            "features_are_current_row_or_online_past_window_values": True,
            "target_used_only_for_inner_train_labels_and_run_level_evaluation": True,
        },
        "preservation_note": (
            "This nested modality comparison is separate from and does not replace "
            "data/ml/current_volume_no_progress or its 1.27% typewise development selector result."
        ),
        "limitations": [
            "Only 12 development runs are available, with one run per titration-type/concentration condition.",
            "Targets are nominal theoretical equivalence volumes, not independently measured endpoints.",
            "Rows within a run are correlated; the independent evaluation unit is one CSV run.",
            "Nested LORO prevents outer-test selection leakage but is not external validation.",
        ],
    }
    combined_predictions: list[dict[str, Any]] = []
    model_selection_rows: list[dict[str, Any]] = []
    expected_paths = set(run_paths)
    for group in FEATURE_GROUPS:
        columns = select_feature_columns(all_columns, group)
        records_by_run = _by_run(_records(runs, columns, grid_ml))
        if set(records_by_run) != expected_paths:
            raise ValueError(f"{group}: missing run records")
        candidates = candidate_space(group, n_estimators=n_estimators)
        predictions: list[dict[str, Any]] = []
        for test_run in runs:
            test_path = str(test_run.path)
            outer_train_runs = [run for run in runs if str(run.path) != test_path]
            selected_candidate, selected_mode, inner_errors = _select_configuration(
                outer_train_runs,
                records_by_run,
                candidates,
                zone_window_ml=zone_window_ml,
            )
            outer_train_records = [
                record for run in outer_train_runs for record in records_by_run[str(run.path)]
            ]
            current, scores = _fit_scores(
                outer_train_records,
                records_by_run[test_path],
                zone_window_ml=zone_window_ml,
                candidate=selected_candidate,
            )
            predicted = _aggregate_candidates(current, scores)[selected_mode]
            actual = float(test_run.theoretical_equivalence_volume_ml)
            error = predicted - actual
            selection_paths = [str(run.path) for run in outer_train_runs]
            row = {
                "feature_group": group,
                "run_path": test_path,
                "titration_type": test_run.titration_type,
                "held_out_concentration_m_audit_only": test_run.concentration_m,
                "actual_equivalence_volume_ml": actual,
                "predicted_equivalence_volume_ml": round(predicted, 6),
                "signed_error_ml": round(error, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(
                    abs(error) / actual * 100.0 if actual else 0.0, 6
                ),
                "selected_candidate_id": selected_candidate.candidate_id,
                "selected_model_family": selected_candidate.family,
                "selected_hyperparameters": dict(selected_candidate.parameters),
                "selected_aggregation": selected_mode,
                "selection_run_paths": selection_paths,
                "inner_validation_run_paths": selection_paths,
                "selection_inner_mae_ml": round(
                    inner_errors[f"{selected_candidate.candidate_id}|{selected_mode}"], 6
                ),
            }
            predictions.append(row)
            combined_predictions.append(row)
            model_selection_rows.append(
                {
                    **{key: row[key] for key in (
                        "feature_group",
                        "run_path",
                        "selected_candidate_id",
                        "selected_model_family",
                        "selected_hyperparameters",
                        "selected_aggregation",
                        "selection_inner_mae_ml",
                    )},
                    "selection_run_paths": selection_paths,
                    "all_inner_mean_mae_ml": {
                        key: round(value, 6) for key, value in inner_errors.items()
                    },
                }
            )
        if {row["run_path"] for row in predictions} != expected_paths:
            raise AssertionError(f"{group}: outer run set differs")
        selected_model_counts = Counter(
            f"{row['selected_model_family']}:{row['selected_candidate_id']}" for row in predictions
        )
        summary["groups"][group] = {
            "feature_columns": columns,
            "feature_count": len(columns),
            "forbidden_features": forbidden_features(columns),
            "candidate_space": [
                {
                    "candidate_id": candidate.candidate_id,
                    "family": candidate.family,
                    "parameters": dict(candidate.parameters),
                }
                for candidate in candidates
            ],
            "metrics": _prediction_metrics(predictions),
            "selected_model_counts": dict(selected_model_counts),
            "selected_model_family_counts": dict(
                Counter(row["selected_model_family"] for row in predictions)
            ),
            "selected_aggregation_counts": dict(
                Counter(row["selected_aggregation"] for row in predictions)
            ),
            "predictions": predictions,
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
        (output / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_csv(output / "predictions.csv", combined_predictions)
        _write_csv(output / "model_selection.csv", model_selection_rows)
        for group in FEATURE_GROUPS:
            _write_csv(
                output / f"predictions_{group}.csv",
                summary["groups"][group]["predictions"],
            )
    return summary


def evaluate_folder(
    input_dir: str | Path,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    grid_ml: float = 0.25,
    zone_window_ml: float = 1.0,
    n_estimators: int = 48,
) -> dict[str, Any]:
    summary = evaluate_runs(
        load_runs(input_dir),
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
    parser.add_argument("--n-estimators", type=int, default=48)
    args = parser.parse_args(argv)
    summary = evaluate_folder(
        args.input_dir,
        output_dir=args.output_dir,
        grid_ml=args.grid_ml,
        zone_window_ml=args.zone_window_ml,
        n_estimators=args.n_estimators,
    )
    print(
        json.dumps(
            {
                group: {
                    "metrics": summary["groups"][group]["metrics"],
                    "selected_model_counts": summary["groups"][group]["selected_model_counts"],
                }
                for group in FEATURE_GROUPS
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
