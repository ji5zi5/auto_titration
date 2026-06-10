#!/usr/bin/env python3
"""Train/evaluate equivalence-volume models with current volume but no progress leakage.

Allowed core input: the volume already injected at the current frame
(`injected_volume_ml`) plus live sensor/chemistry metadata.  Forbidden inputs are
end-of-run progress proxies such as final max volume, run duration, frame count,
fractions of the finished run, labels, errors, or theoretical equivalence values.

The script evaluates one final equivalence-volume prediction per CSV run using
leave-one-run-out folds and writes durable artifacts for report/inspection.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_curve_equivalence import (  # noqa: E402
    _candidate_rows_for_runs,
    _is_protocol_fraction_candidate_row,
    _to_float,
    run_level_metrics,
)
from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/current_volume_no_progress")

PREDICTION_UNIT = "one_equivalence_volume_prediction_per_csv_run"
RANDOM_STATE = 42

# Exact columns that must never be model inputs.
FORBIDDEN_EXACT = {
    "theoretical_equivalence_volume_ml",
    "theoretical_equivalence_time_s",
    "theoretical_equivalence_pH",
    "calculated_theoretical_equivalence_volume_ml",
    "sample_concentration_from_theoretical_equivalence_M",
    "sample_concentration_from_predicted_equivalence_M",
    "sample_concentration_M",  # unknown in the final use case
    "actual_equivalence_volume_ml",
    "predicted_equivalence_volume_ml",
    "estimated_equivalence_volume_ml",
    "estimated_equivalence_time_s",
    "reference_equivalence_volume_ml",
    "candidate_error_ml",
    "candidate_abs_error_ml",
    "is_good_candidate",
    "distance_to_equivalence_ml",
    "time_to_equivalence_s",
    "delta_ml",
    "zone_label",
    "status_label",
    "status_confidence",
    "equivalence_window_label",
    "equivalence_window_ml",
    "candidate_fraction_of_run",
    "run_volume_max_ml",
    "run_duration_s",
    "row_count",
    "csv_row_index",
    "frame_id",
    "csv_session_id",
    "roi_session_id",
    "csv_recording_started_epoch_s",
    "csv_recording_elapsed_s",
    "pump_elapsed_s",
    "time_s",
    "thermal_time_s",
    "visible_time_s",
}

FORBIDDEN_CONTAINS = (
    "equivalence",
    "distance_to_",
    "time_to_",
    "_label",
    "_target",
    "actual_",
    "predicted_",
    "estimated_",
    "reference_",
    "fraction",
    "progress",
    "duration",
    "row_count",
    "frame_id",
    "session_id",
    "elapsed",
)

ALLOWED_NUMERIC_EXACT = {
    "injected_volume_ml",  # explicitly allowed by the project rule
    "pump_run_rate_ml_per_s",
    "sample_volume_ml",
    "sample_valence",
    "titrant_concentration_M",
    "titrant_valence",
    "indicator_transition_low_pH",
    "indicator_transition_high_pH",
    "constants_candidate_count",
    "constants_lookup_ambiguous",
    "training_quality_score",
    "valid_for_training",
    "abs_sync_offset_ms",
    "sync_offset_ms",
    "preview_visible_latency_ms",
    "processing_latency_ms",
    "visible_roi_width",
    "visible_roi_height",
    "thermal_roi_width",
    "thermal_roi_height",
}

ALLOWED_CATEGORICAL_EXACT = {
    "titration_type",
    "sample_name",
    "titrant_name",
    "indicator",
    "chemistry_model",
    "activity_model",
    "constants_confirmation_status",
    "sync_quality",
    "roi_source",
    "roi_state",
    "source_quality",
}

SENSOR_PREFIXES = (
    "visible_",
    "thermal_roi_",
    "thermal_raw_",
    "thermal_raw_roi_",
    "titration_is_",
)

SENSOR_EXCLUDE_TOKENS = (
    "capture_index",
    "capture_backend",
    "conversion_model",
    "conversion_calibration_source",
    "source",
    "matrix_shape",
    "rotation_degrees",
    "_x",
    "_y",
)

CANDIDATE_ALLOWED_EXACT = {
    "candidate_volume_ml",  # current volume of the detected sensor event; allowed
    "candidate_score",
    "fusion_peak_score",
    "source_is_color",
    "source_is_thermal",
    "source_is_fusion",
    "visible_thermal_slope_agreement",
    "visible_thermal_delta_agreement",
    "sensor_nearest_color_candidate_distance_ml",
    "sensor_nearest_thermal_candidate_distance_ml",
    "sensor_nearest_fusion_candidate_distance_ml",
    "sensor_color_thermal_agreement_ml",
    "sensor_source_agreement_count_0p5ml",
    "sensor_source_agreement_count_1p0ml",
    "sensor_candidate_score_rank",
    "sensor_candidate_score_gap_to_best",
    "sensor_candidate_score_gap_to_next",
    "sensor_candidate_local_density_0p5ml",
    "sensor_candidate_local_density_1p0ml",
    *ALLOWED_NUMERIC_EXACT,
}

CANDIDATE_FORBIDDEN_PREFIXES = ("nearest_", "color_thermal_", "source_agreement_", "candidate_local_density_")


@dataclass(frozen=True)
class Prediction:
    run_path: str
    titration_type: str
    concentration_m: float
    actual_ml: float
    predicted_ml: float
    method: str
    model: str
    fold: str
    notes: str = ""


def safe_float(value: Any) -> float | None:
    value = _to_float(value)
    if value is None or not math.isfinite(float(value)):
        return None
    return float(value)


def is_forbidden_column(column: str) -> bool:
    lowered = column.strip().lower()
    if column in FORBIDDEN_EXACT:
        return True
    return any(token in lowered for token in FORBIDDEN_CONTAINS)


def is_allowed_frame_feature(column: str) -> bool:
    if is_forbidden_column(column):
        return False
    if column in ALLOWED_NUMERIC_EXACT or column in ALLOWED_CATEGORICAL_EXACT:
        return True
    if column.startswith(SENSOR_PREFIXES):
        lowered = column.lower()
        if any(token in lowered for token in SENSOR_EXCLUDE_TOKENS):
            return False
        return True
    return False


def is_allowed_candidate_feature(column: str) -> bool:
    if column in CANDIDATE_ALLOWED_EXACT:
        return True
    if is_forbidden_column(column):
        return False
    if column.startswith(CANDIDATE_FORBIDDEN_PREFIXES):
        return False
    if column.startswith("sensor_"):
        return True
    if column.startswith(SENSOR_PREFIXES):
        lowered = column.lower()
        if any(token in lowered for token in SENSOR_EXCLUDE_TOKENS):
            return False
        return True
    return False


def assert_no_forbidden_features(columns: Iterable[str]) -> None:
    offenders = [column for column in columns if is_forbidden_column(column) and column != "injected_volume_ml"]
    if offenders:
        raise ValueError(f"forbidden feature columns selected: {offenders[:20]}")


def run_id(run: CsvRun) -> str:
    return str(run.path)


def all_frame_feature_columns(runs: Sequence[CsvRun]) -> list[str]:
    columns = sorted({column for run in runs for row in run.rows for column in row.keys() if is_allowed_frame_feature(column)})
    if "injected_volume_ml" not in columns:
        raise ValueError("injected_volume_ml must be present and selected")
    assert_no_forbidden_features(columns)
    return columns


def row_to_feature_dict(row: Mapping[str, Any], columns: Sequence[str]) -> dict[str, float | str]:
    features: dict[str, float | str] = {}
    for column in columns:
        if column in ALLOWED_CATEGORICAL_EXACT:
            features[column] = str(row.get(column) or "")
            continue
        value = safe_float(row.get(column))
        features[column] = 0.0 if value is None else float(value)
    return features


def volume_resampled_rows(run: CsvRun, *, grid_ml: float) -> list[Mapping[str, Any]]:
    """Keep at most one row per injected-volume bin to avoid row-count weighting."""

    rows: list[tuple[float, Mapping[str, Any]]] = []
    for row in run.rows:
        volume = safe_float(row.get("injected_volume_ml"))
        if volume is None:
            continue
        rows.append((volume, row))
    rows.sort(key=lambda item: item[0])
    if grid_ml <= 0:
        return [row for _volume, row in rows]
    selected: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    for volume, row in rows:
        bin_id = int(round(volume / grid_ml))
        if bin_id in seen:
            continue
        seen.add(bin_id)
        selected.append(row)
    return selected


def build_frame_records(runs: Sequence[CsvRun], *, grid_ml: float) -> tuple[list[dict[str, Any]], list[str]]:
    columns = all_frame_feature_columns(runs)
    records: list[dict[str, Any]] = []
    for run in runs:
        for row in volume_resampled_rows(run, grid_ml=grid_ml):
            volume = safe_float(row.get("injected_volume_ml"))
            if volume is None:
                continue
            record: dict[str, Any] = {
                "run_path": run_id(run),
                "titration_type": run.titration_type,
                "concentration_m": run.concentration_m,
                "actual_ml": run.theoretical_equivalence_volume_ml,
                "current_volume_ml": volume,
                "features": row_to_feature_dict(row, columns),
            }
            records.append(record)
    return records, columns


def vectorize(train_features: Sequence[Mapping[str, Any]], test_features: Sequence[Mapping[str, Any]]):
    from sklearn.feature_extraction import DictVectorizer  # type: ignore[reportMissingImports]
    from sklearn.impute import SimpleImputer  # type: ignore[reportMissingImports]
    from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]

    vec = DictVectorizer(sparse=False)
    imp = SimpleImputer(strategy="median")
    pipe = make_pipeline(vec, imp)
    x_train = pipe.fit_transform(list(train_features))
    x_test = pipe.transform(list(test_features))
    return x_train, x_test, pipe


def frame_model_specs(kind: str, train_size: int):
    if kind == "regressor":
        from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor  # type: ignore[reportMissingImports]
        from sklearn.kernel_ridge import KernelRidge  # type: ignore[reportMissingImports]
        from sklearn.linear_model import Ridge  # type: ignore[reportMissingImports]
        from sklearn.neighbors import KNeighborsRegressor  # type: ignore[reportMissingImports]
        from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]
        from sklearn.preprocessing import StandardScaler  # type: ignore[reportMissingImports]

        k = max(1, min(7, int(math.sqrt(max(1, train_size)))))
        return [
            ("extra_trees", ExtraTreesRegressor(n_estimators=160, random_state=RANDOM_STATE, min_samples_leaf=1, n_jobs=-1)),
            ("extra_trees_leaf3", ExtraTreesRegressor(n_estimators=160, random_state=RANDOM_STATE, min_samples_leaf=3, n_jobs=-1)),
            ("random_forest", RandomForestRegressor(n_estimators=120, random_state=RANDOM_STATE, min_samples_leaf=2, n_jobs=-1)),
            ("gradient_boosting", GradientBoostingRegressor(n_estimators=140, learning_rate=0.04, max_depth=2, random_state=RANDOM_STATE)),
            ("knn", make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k, weights="distance"))),
            ("ridge", make_pipeline(StandardScaler(), Ridge(alpha=1))),
            ("kernel_ridge", make_pipeline(StandardScaler(), KernelRidge(kernel="rbf", alpha=1, gamma=0.05))),
        ]
    if kind == "classifier":
        from sklearn.ensemble import ExtraTreesClassifier, GradientBoostingClassifier, RandomForestClassifier  # type: ignore[reportMissingImports]
        from sklearn.linear_model import LogisticRegression  # type: ignore[reportMissingImports]
        from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]
        from sklearn.preprocessing import StandardScaler  # type: ignore[reportMissingImports]

        return [
            ("extra_trees", ExtraTreesClassifier(n_estimators=160, random_state=RANDOM_STATE, min_samples_leaf=1, class_weight="balanced", n_jobs=-1)),
            ("extra_trees_leaf3", ExtraTreesClassifier(n_estimators=160, random_state=RANDOM_STATE, min_samples_leaf=3, class_weight="balanced", n_jobs=-1)),
            ("random_forest", RandomForestClassifier(n_estimators=120, random_state=RANDOM_STATE, min_samples_leaf=2, class_weight="balanced", n_jobs=-1)),
            ("gradient_boosting", GradientBoostingClassifier(n_estimators=100, learning_rate=0.04, max_depth=2, random_state=RANDOM_STATE)),
            ("logistic", make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"))),
        ]
    raise ValueError(kind)


def grouped_by_run(records: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(record["run_path"])].append(record)
    return grouped


def aggregate_prediction(values: np.ndarray, current_volumes: np.ndarray, mode: str, weights: np.ndarray | None = None) -> float:
    if len(values) == 0:
        return 0.0
    if mode == "median":
        return float(np.median(values))
    if mode == "mean":
        return float(np.mean(values))
    if mode.startswith("top"):
        k = int(mode[3:])
        if weights is None:
            order = np.argsort(np.abs(values - current_volumes))
        else:
            order = np.argsort(-weights)
        take = order[: max(1, min(k, len(order)))]
        if weights is not None:
            w = np.maximum(weights[take], 1e-9)
            return float(np.average(values[take], weights=w))
        return float(np.mean(values[take]))
    raise ValueError(mode)


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) == 0:
        return 0.0
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = np.maximum(weights[order], 1e-12)
    cumulative = np.cumsum(sorted_weights)
    cutoff = float(cumulative[-1]) / 2.0
    idx = int(np.searchsorted(cumulative, cutoff, side="left"))
    return float(sorted_values[max(0, min(idx, len(sorted_values) - 1))])


def classifier_aggregate_predictions(current: np.ndarray, scores: np.ndarray) -> dict[str, float]:
    """Convert per-frame zone scores into run-level volume predictions.

    These aggregations use only live/current injected volumes and model scores.
    They do not use final run volume, elapsed time, row count, progress fraction,
    or the true/theoretical equivalence volume.
    """

    predictions: dict[str, float] = {}
    if len(current) == 0:
        return predictions
    scores = np.nan_to_num(scores.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    current = current.astype(float)
    order = np.argsort(-scores)
    top_values = (1, 3, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100)
    median_top_values = (3, 5, 10, 20, 40, 80)
    power_top_values = (5, 10, 20, 40, 80)
    for top_k in top_values:
        take = order[: max(1, min(top_k, len(order)))]
        weights = np.maximum(scores[take], 1e-9)
        predictions[f"top{top_k}"] = float(np.average(current[take], weights=weights))
    for top_k in median_top_values:
        take = order[: max(1, min(top_k, len(order)))]
        predictions[f"median_top{top_k}"] = float(np.median(current[take]))
        predictions[f"weighted_median_top{top_k}"] = _weighted_median(current[take], np.maximum(scores[take], 1e-9))
    for top_k in power_top_values:
        take = order[: max(1, min(top_k, len(order)))]
        for power in (2.0, 3.0):
            weights = np.maximum(scores[take], 1e-9) ** power
            predictions[f"power{int(power)}_top{top_k}"] = float(np.average(current[take], weights=weights))
    # Score-threshold centroids. Thresholds are rank-based over the current run,
    # not final-volume/progress based.
    for quantile in (0.90, 0.95, 0.98):
        threshold = float(np.quantile(scores, quantile))
        mask = scores >= threshold
        if np.any(mask):
            weights = np.maximum(scores[mask], 1e-9)
            tag = str(quantile).replace("0.", "q")
            predictions[f"score_quantile_{tag}"] = float(np.average(current[mask], weights=weights))
            predictions[f"score_quantile_{tag}_median"] = float(np.median(current[mask]))
    # Smooth score peak on the injected-volume axis. This reduces one-frame
    # noise without using row/time/progress information.
    volume_order = np.argsort(current)
    sorted_current = current[volume_order]
    sorted_scores = scores[volume_order]
    for width in (3, 5, 9):
        if len(sorted_scores) < width:
            continue
        kernel = np.ones(width, dtype=float) / float(width)
        smoothed = np.convolve(sorted_scores, kernel, mode="same")
        idx = int(np.argmax(smoothed))
        predictions[f"smooth_peak_w{width}"] = float(sorted_current[idx])
        lo = max(0, idx - width // 2)
        hi = min(len(sorted_current), idx + width // 2 + 1)
        weights = np.maximum(smoothed[lo:hi], 1e-9)
        predictions[f"smooth_centroid_w{width}"] = float(np.average(sorted_current[lo:hi], weights=weights))
    return predictions


def evaluate_frame_remaining_regression(runs: Sequence[CsvRun], records: Sequence[Mapping[str, Any]]) -> list[tuple[str, list[Prediction]]]:
    grouped = grouped_by_run(records)
    results: list[tuple[str, list[Prediction]]] = []
    for model_name, model in frame_model_specs("regressor", len(records)):
        for aggregate in ("top3", "top5", "top10", "median"):
            predictions: list[Prediction] = []
            for test in runs:
                test_key = run_id(test)
                train_records = [record for record in records if record["run_path"] != test_key]
                test_records = grouped[test_key]
                x_train, x_test, _pipe = vectorize([r["features"] for r in train_records], [r["features"] for r in test_records])
                y_train = np.array([float(r["actual_ml"]) - float(r["current_volume_ml"]) for r in train_records], dtype=float)
                fitted = model
                from sklearn.base import clone  # type: ignore[reportMissingImports]

                fitted = clone(model)
                fitted.fit(x_train, y_train)
                remaining = np.array(fitted.predict(x_test), dtype=float)
                current = np.array([float(r["current_volume_ml"]) for r in test_records], dtype=float)
                corrected = current + remaining
                confidence = 1.0 / (np.abs(remaining) + 1e-6)
                pred = aggregate_prediction(corrected, current, aggregate, confidence)
                predictions.append(
                    Prediction(test_key, test.titration_type, test.concentration_m, test.theoretical_equivalence_volume_ml, pred, "frame_remaining_regression", model_name, f"loo_all/{aggregate}")
                )
            results.append((f"frame_remaining_regression:{model_name}:{aggregate}", predictions))
    return results


def evaluate_frame_zone_classifier(
    runs: Sequence[CsvRun], records: Sequence[Mapping[str, Any]], *, windows_ml: Sequence[float] = (0.5, 1.0, 2.0, 3.0)
) -> list[tuple[str, list[Prediction]]]:
    grouped = grouped_by_run(records)
    results: list[tuple[str, list[Prediction]]] = []
    for window_ml in windows_ml:
        for scope in ("all_types", "same_type"):
            for model_name, model in frame_model_specs("classifier", len(records)):
                predictions_by_mode: dict[str, list[Prediction]] = defaultdict(list)
                for test in runs:
                    test_key = run_id(test)
                    train_records = [record for record in records if record["run_path"] != test_key]
                    if scope == "same_type":
                        same_type_records = [record for record in train_records if record["titration_type"] == test.titration_type]
                        if len({record["run_path"] for record in same_type_records}) >= 2:
                            train_records = same_type_records
                    test_records = grouped[test_key]
                    x_train, x_test, _pipe = vectorize([r["features"] for r in train_records], [r["features"] for r in test_records])
                    y_train = np.array([abs(float(r["current_volume_ml"]) - float(r["actual_ml"])) <= window_ml for r in train_records], dtype=int)
                    if len(set(y_train.tolist())) < 2:
                        continue
                    from sklearn.base import clone  # type: ignore[reportMissingImports]

                    fitted = clone(model)
                    try:
                        fitted.fit(x_train, y_train)
                    except Exception:
                        continue
                    if hasattr(fitted, "predict_proba"):
                        proba = np.array(fitted.predict_proba(x_test), dtype=float)
                        positive_index = list(getattr(fitted, "classes_", [0, 1])).index(1)
                        scores = proba[:, positive_index]
                    else:
                        raw = np.array(fitted.decision_function(x_test), dtype=float)
                        scores = 1.0 / (1.0 + np.exp(-raw))
                    current = np.array([float(r["current_volume_ml"]) for r in test_records], dtype=float)
                    for mode, pred in classifier_aggregate_predictions(current, scores).items():
                        predictions_by_mode[mode].append(
                            Prediction(
                                test_key,
                                test.titration_type,
                                test.concentration_m,
                                test.theoretical_equivalence_volume_ml,
                                pred,
                                "frame_zone_classifier",
                                model_name,
                                f"loo_{scope}/window{window_ml}_{mode}",
                            )
                        )
                for mode, predictions in predictions_by_mode.items():
                    if len(predictions) == len(runs):
                        results.append((f"frame_zone_classifier:{model_name}:{scope}:window{window_ml}:{mode}", predictions))
    return results


def safe_candidate_feature_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns = sorted({column for row in rows for column in row.keys() if is_allowed_candidate_feature(column)})
    if "candidate_volume_ml" not in columns:
        raise ValueError("candidate_volume_ml must be present and selected")
    assert_no_forbidden_features(columns)
    return columns


def candidate_matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    matrix = []
    for row in rows:
        matrix.append([safe_float(row.get(column)) or 0.0 for column in columns])
    return np.array(matrix, dtype=float)


def evaluate_candidate_error_models(runs: Sequence[CsvRun]) -> tuple[list[tuple[str, list[Prediction]]], dict[str, Any]]:
    rows = _candidate_rows_for_runs(runs, max_candidates_per_source=8, good_window_ml=0.5)
    rows = [row for row in rows if not _is_protocol_fraction_candidate_row(row)]
    columns = safe_candidate_feature_columns(rows)
    rows_by_run = grouped_by_run(rows)
    results: list[tuple[str, list[Prediction]]] = []
    from sklearn.base import clone  # type: ignore[reportMissingImports]
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor  # type: ignore[reportMissingImports]
    from sklearn.linear_model import Ridge  # type: ignore[reportMissingImports]
    from sklearn.neighbors import KNeighborsRegressor  # type: ignore[reportMissingImports]
    from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]
    from sklearn.preprocessing import StandardScaler  # type: ignore[reportMissingImports]

    specs = [
        ("extra_trees", ExtraTreesRegressor(n_estimators=200, random_state=RANDOM_STATE, min_samples_leaf=1, n_jobs=-1)),
        ("extra_trees_leaf3", ExtraTreesRegressor(n_estimators=200, random_state=RANDOM_STATE, min_samples_leaf=3, n_jobs=-1)),
        ("random_forest", RandomForestRegressor(n_estimators=160, random_state=RANDOM_STATE, min_samples_leaf=2, n_jobs=-1)),
        ("gradient_boosting", GradientBoostingRegressor(n_estimators=160, learning_rate=0.04, max_depth=2, random_state=RANDOM_STATE)),
        ("knn", make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=5, weights="distance"))),
        ("ridge", make_pipeline(StandardScaler(), Ridge(alpha=1))),
    ]
    for model_name, model in specs:
        for mode in ("choose_min_abs", "corrected_min_abs", "corrected_top3"):
            predictions: list[Prediction] = []
            for test in runs:
                key = run_id(test)
                train_rows = [row for row in rows if str(row.get("run_path")) != key]
                test_rows = rows_by_run[key]
                x_train = candidate_matrix(train_rows, columns)
                x_test = candidate_matrix(test_rows, columns)
                y_abs = np.array([safe_float(row.get("candidate_abs_error_ml")) or 0.0 for row in train_rows], dtype=float)
                y_signed = np.array([safe_float(row.get("candidate_error_ml")) or 0.0 for row in train_rows], dtype=float)
                abs_model = clone(model)
                signed_model = clone(model)
                abs_model.fit(x_train, y_abs)
                signed_model.fit(x_train, y_signed)
                pred_abs = np.array(abs_model.predict(x_test), dtype=float)
                pred_signed = np.array(signed_model.predict(x_test), dtype=float)
                volumes = np.array([safe_float(row.get("candidate_volume_ml")) or 0.0 for row in test_rows], dtype=float)
                corrected = volumes - pred_signed
                if mode == "choose_min_abs":
                    idx = int(np.argmin(pred_abs))
                    pred = float(volumes[idx])
                elif mode == "corrected_min_abs":
                    idx = int(np.argmin(pred_abs))
                    pred = float(corrected[idx])
                else:
                    order = np.argsort(pred_abs)[: max(1, min(3, len(pred_abs)))]
                    weights = 1.0 / (np.maximum(pred_abs[order], 0.05))
                    pred = float(np.average(corrected[order], weights=weights))
                predictions.append(
                    Prediction(key, test.titration_type, test.concentration_m, test.theoretical_equivalence_volume_ml, pred, "sensor_candidate_error_model", model_name, f"loo_all/{mode}")
                )
            results.append((f"sensor_candidate_error_model:{model_name}:{mode}", predictions))
    diagnostics = {
        "candidate_row_count": len(rows),
        "candidate_feature_count": len(columns),
        "candidate_feature_columns": columns,
        "protocol_fraction_candidates_removed": True,
    }
    return results, diagnostics


def _series_from_run(run: CsvRun, column: str) -> tuple[np.ndarray, np.ndarray]:
    pairs: list[tuple[float, float]] = []
    for row in run.rows:
        volume = safe_float(row.get("injected_volume_ml"))
        value = safe_float(row.get(column))
        if volume is None or value is None:
            continue
        pairs.append((volume, value))
    if not pairs:
        return np.array([], dtype=float), np.array([], dtype=float)
    pairs.sort(key=lambda item: item[0])
    # Collapse repeated volume bins so gradients are stable without using row count.
    grouped: dict[float, list[float]] = defaultdict(list)
    for volume, value in pairs:
        grouped[round(volume, 3)].append(value)
    volumes = np.array(sorted(grouped.keys()), dtype=float)
    values = np.array([float(np.median(grouped[volume])) for volume in volumes], dtype=float)
    return volumes, values


def _safe_gradient(values: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    if len(values) < 3:
        return np.zeros(len(values), dtype=float)
    safe_volumes = volumes.astype(float).copy()
    for i in range(1, len(safe_volumes)):
        if safe_volumes[i] <= safe_volumes[i - 1]:
            safe_volumes[i] = safe_volumes[i - 1] + 1e-6
    return np.gradient(values, safe_volumes)


def _first_feature_value(run: CsvRun, column: str) -> float | str:
    for row in run.rows:
        if column in ALLOWED_CATEGORICAL_EXACT:
            text = str(row.get(column) or "").strip()
            if text:
                return text
        else:
            value = safe_float(row.get(column))
            if value is not None:
                return float(value)
    return "" if column in ALLOWED_CATEGORICAL_EXACT else 0.0


def run_summary_features(run: CsvRun, columns: Sequence[str]) -> dict[str, float | str]:
    """Summarize a full sensor curve without final-volume/progress features.

    The only volume-like features are event locations on the live injected-volume
    axis, e.g. the volume where a visible/thermal signal changes fastest.  It
    deliberately does not include max injected volume, run duration, row count,
    or any fraction/progress field.
    """

    features: dict[str, float | str] = {}
    for column in columns:
        if column == "injected_volume_ml":
            continue
        if column in ALLOWED_CATEGORICAL_EXACT or column in ALLOWED_NUMERIC_EXACT:
            features[column] = _first_feature_value(run, column)

    sensor_columns = [
        column
        for column in columns
        if column != "injected_volume_ml"
        and column not in ALLOWED_CATEGORICAL_EXACT
        and (column.startswith(SENSOR_PREFIXES) or column in ALLOWED_NUMERIC_EXACT)
    ]
    for column in sensor_columns:
        volumes, values = _series_from_run(run, column)
        if len(values) < 3:
            continue
        gradients = _safe_gradient(values, volumes)
        abs_gradients = np.abs(gradients)
        max_idx = int(np.argmax(values))
        min_idx = int(np.argmin(values))
        slope_idx = int(np.argmax(abs_gradients))
        baseline = float(np.median(values[: max(1, min(5, len(values)))]))
        centered = values - baseline
        centered_abs_idx = int(np.argmax(np.abs(centered)))
        features[f"{column}__first"] = float(values[0])
        features[f"{column}__last"] = float(values[-1])
        features[f"{column}__mean"] = float(np.mean(values))
        features[f"{column}__std"] = float(np.std(values))
        features[f"{column}__range"] = float(np.max(values) - np.min(values))
        features[f"{column}__p10"] = float(np.percentile(values, 10))
        features[f"{column}__p50"] = float(np.percentile(values, 50))
        features[f"{column}__p90"] = float(np.percentile(values, 90))
        features[f"{column}__last_minus_first"] = float(values[-1] - values[0])
        features[f"{column}__max_slope_abs"] = float(abs_gradients[slope_idx])
        features[f"{column}__volume_at_max_slope_abs"] = float(volumes[slope_idx])
        features[f"{column}__volume_at_max"] = float(volumes[max_idx])
        features[f"{column}__volume_at_min"] = float(volumes[min_idx])
        features[f"{column}__max_abs_baseline_delta"] = float(np.max(np.abs(centered)))
        features[f"{column}__volume_at_max_abs_baseline_delta"] = float(volumes[centered_abs_idx])
    return features


def run_summary_model_specs(train_size: int):
    from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor  # type: ignore[reportMissingImports]
    from sklearn.kernel_ridge import KernelRidge  # type: ignore[reportMissingImports]
    from sklearn.linear_model import Ridge  # type: ignore[reportMissingImports]
    from sklearn.neighbors import KNeighborsRegressor  # type: ignore[reportMissingImports]
    from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]
    from sklearn.preprocessing import StandardScaler  # type: ignore[reportMissingImports]
    from sklearn.svm import SVR  # type: ignore[reportMissingImports]

    k = max(1, min(5, int(math.sqrt(max(1, train_size)))))
    return [
        ("extra_trees", ExtraTreesRegressor(n_estimators=300, random_state=RANDOM_STATE, min_samples_leaf=1, n_jobs=-1)),
        ("extra_trees_leaf2", ExtraTreesRegressor(n_estimators=300, random_state=RANDOM_STATE, min_samples_leaf=2, n_jobs=-1)),
        ("random_forest", RandomForestRegressor(n_estimators=220, random_state=RANDOM_STATE, min_samples_leaf=1, n_jobs=-1)),
        ("gradient_boosting", GradientBoostingRegressor(n_estimators=220, learning_rate=0.03, max_depth=2, random_state=RANDOM_STATE)),
        ("knn", make_pipeline(StandardScaler(), KNeighborsRegressor(n_neighbors=k, weights="distance"))),
        ("ridge", make_pipeline(StandardScaler(), Ridge(alpha=1))),
        ("kernel_ridge", make_pipeline(StandardScaler(), KernelRidge(kernel="rbf", alpha=1, gamma=0.03))),
        ("svr_rbf", make_pipeline(StandardScaler(), SVR(kernel="rbf", C=30.0, gamma="scale", epsilon=0.05))),
    ]


def evaluate_run_summary_models(runs: Sequence[CsvRun]) -> list[tuple[str, list[Prediction]]]:
    columns = all_frame_feature_columns(runs)
    records = [
        {
            "run_path": run_id(run),
            "titration_type": run.titration_type,
            "concentration_m": run.concentration_m,
            "actual_ml": run.theoretical_equivalence_volume_ml,
            "features": run_summary_features(run, columns),
        }
        for run in runs
    ]
    results: list[tuple[str, list[Prediction]]] = []
    from sklearn.base import clone  # type: ignore[reportMissingImports]

    for scope in ("all_types", "same_type"):
        for model_name, model in run_summary_model_specs(len(records)):
            predictions: list[Prediction] = []
            for test in runs:
                key = run_id(test)
                train_records = [record for record in records if record["run_path"] != key]
                if scope == "same_type":
                    same_type_records = [record for record in train_records if record["titration_type"] == test.titration_type]
                    if len(same_type_records) >= 2:
                        train_records = same_type_records
                test_records = [record for record in records if record["run_path"] == key]
                x_train, x_test, _pipe = vectorize([r["features"] for r in train_records], [r["features"] for r in test_records])
                y_train = np.array([float(r["actual_ml"]) for r in train_records], dtype=float)
                fitted = clone(model)
                try:
                    fitted.fit(x_train, y_train)
                    pred = float(np.asarray(fitted.predict(x_test), dtype=float)[0])
                except Exception:
                    predictions = []
                    break
                pred = max(0.0, min(80.0, pred))
                predictions.append(
                    Prediction(
                        key,
                        test.titration_type,
                        test.concentration_m,
                        test.theoretical_equivalence_volume_ml,
                        pred,
                        "run_summary_sensor_curve",
                        model_name,
                        f"loo_{scope}",
                    )
                )
            results.append((f"run_summary_sensor_curve:{model_name}:{scope}", predictions))
    return results


def metrics_for_predictions(predictions: Sequence[Prediction]) -> dict[str, float]:
    rows = [
        {
            "actual_equivalence_volume_ml": prediction.actual_ml,
            "predicted_equivalence_volume_ml": prediction.predicted_ml,
        }
        for prediction in predictions
    ]
    metrics = dict(run_level_metrics(rows))
    # Local alias used by this script and the evaluator contract.
    metrics["mape_percent"] = metrics.get("mae_percent_of_equivalence", 0.0)
    return metrics


def typewise_metrics(predictions: Sequence[Prediction]) -> dict[str, dict[str, float]]:
    grouped: dict[str, list[Prediction]] = defaultdict(list)
    for prediction in predictions:
        grouped[prediction.titration_type].append(prediction)
    return {key: metrics_for_predictions(items) for key, items in sorted(grouped.items())}


def row_from_prediction(prediction: Prediction) -> dict[str, Any]:
    err = prediction.predicted_ml - prediction.actual_ml
    mape = abs(err) / abs(prediction.actual_ml) * 100.0 if prediction.actual_ml else 0.0
    return {
        "run_path": prediction.run_path,
        "titration_type": prediction.titration_type,
        "concentration_m": prediction.concentration_m,
        "actual_equivalence_volume_ml": prediction.actual_ml,
        "predicted_equivalence_volume_ml": round(prediction.predicted_ml, 6),
        "error_ml": round(err, 6),
        "abs_error_ml": round(abs(err), 6),
        "absolute_percentage_error": round(mape, 6),
        "method": prediction.method,
        "model": prediction.model,
        "fold": prediction.fold,
        "notes": prediction.notes,
    }


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def write_summary_doc(path: Path, summary: Mapping[str, Any]) -> None:
    best = summary["best"]
    lines = [
        "# 현재 주입량 허용 / 진행도 금지 ML 학습 결과",
        "",
        "이 평가는 `injected_volume_ml`은 입력으로 사용하지만, 최종 주입량·진행률·전체 시간·프레임 수·정답 거리 같은 누수 정보는 입력에서 제외했다.",
        "",
        f"- 입력 CSV: {summary['input_dir']}",
        f"- 실험 run 수: {summary['run_count']}",
        f"- 예측 단위: {PREDICTION_UNIT}",
        f"- 최고 모델: {best['method_key']}",
        f"- MAE: {best['metrics']['mae_ml']:.6f} mL",
        f"- RMSE: {best['metrics']['rmse_ml']:.6f} mL",
        f"- MAPE: {best['metrics']['mape_percent']:.6f} %",
        "",
    ]
    selector = summary.get("typewise_development_selector")
    if isinstance(selector, Mapping) and best["method_key"] == "typewise_development_selector:best_per_titration_type":
        lines.extend(
            [
                "> 주의: 현재 최고값은 적정 종류별로 모델을 따로 고른 development-set 결과이다. 금지 feature를 쓰지는 않았지만, 독립 외부 검증 성능으로 과장하면 안 된다.",
                "",
            ]
        )
    lines.extend(
        [
            "## 금지한 정보",
            "",
            "최종 주입량(run_volume_max), 진행률/fraction, 전체 실험 시간/duration, 프레임 수/행 번호, 이론 당량점, 정답과의 거리/오차/라벨은 feature에서 제거했다.",
            "",
            "## 적정 종류별 최고 모델 성능",
            "",
            "| 적정 종류 | MAE(mL) | RMSE(mL) | MAPE(%) |",
            "|---|---:|---:|---:|",
        ]
    )
    for titration_type, metrics in best["typewise_metrics"].items():
        lines.append(f"| {titration_type} | {metrics['mae_ml']:.6f} | {metrics['rmse_ml']:.6f} | {metrics['mape_percent']:.6f} |")
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "이 파일은 보고서용 수치 주장을 바로 고정하기보다, 누수 없는 조건에서 어떤 방식이 가장 나은지 확인하기 위한 학습 산출물이다.",
            "MAPE가 목표값 이하가 아니면 데이터 또는 모델 탐색을 더 해야 하며, 진행도 기반 결과와 섞어 주장하면 안 된다.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def metric_value(metrics: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = metrics.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def comparison_and_prediction_rows(results: Sequence[tuple[str, list[Prediction]]], runs: Sequence[CsvRun]) -> tuple[list[dict[str, Any]], dict[str, list[Prediction]]]:
    comparison_rows: list[dict[str, Any]] = []
    predictions_by_key: dict[str, list[Prediction]] = {}
    for key, predictions in results:
        if len(predictions) != len(runs):
            continue
        metrics = metrics_for_predictions(predictions)
        predictions_by_key[key] = predictions
        method, model, *rest = key.split(":")
        comparison_rows.append(
            {
                "method_key": key,
                "method": method,
                "model": model if model else "",
                "variant": ":".join(rest),
                "run_count": len(predictions),
                "mae_ml": round(metric_value(metrics, "mae_ml"), 6),
                "rmse_ml": round(metric_value(metrics, "rmse_ml"), 6),
                "mape_percent": round(metric_value(metrics, "mape_percent"), 6),
                "bias_ml": round(metric_value(metrics, "bias_ml"), 6),
                "within_0p5ml_rate": round(metric_value(metrics, "within_0.5ml_rate"), 6),
                "within_1p0ml_rate": round(metric_value(metrics, "within_1.0ml_rate"), 6),
                "within_5pct_rate": round(metric_value(metrics, "within_5pct_rate"), 6),
            }
        )
    comparison_rows.sort(key=lambda row: (float(row["mape_percent"]), float(row["mae_ml"])))
    return comparison_rows, predictions_by_key


def family_slug(family: str) -> str:
    return family.replace(":", "_").replace(".", "p")


def parse_family_windows(family: str) -> tuple[str, tuple[float, ...]]:
    if family.startswith("frame_classifier_"):
        raw = family.removeprefix("frame_classifier_").replace("p", ".")
        return "frame_classifier", (float(raw),)
    return family, (0.5, 1.0, 2.0, 3.0)


def result_rows_for_all_predictions(results: Sequence[tuple[str, list[Prediction]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method_key, predictions in results:
        for prediction in predictions:
            row = row_from_prediction(prediction)
            row["method_key"] = method_key
            rows.append(row)
    return rows


def load_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _prediction_from_row(row: Mapping[str, Any]) -> Prediction:
    return Prediction(
        run_path=str(row.get("run_path") or ""),
        titration_type=str(row.get("titration_type") or ""),
        concentration_m=float(row.get("concentration_m") or 0.0),
        actual_ml=float(row.get("actual_equivalence_volume_ml") or 0.0),
        predicted_ml=float(row.get("predicted_equivalence_volume_ml") or 0.0),
        method=str(row.get("method") or ""),
        model=str(row.get("model") or ""),
        fold=str(row.get("fold") or ""),
        notes=str(row.get("notes") or ""),
    )


def add_typewise_development_selector(all_prediction_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Add an explicitly caveated best-per-titration-type selector.

    This is useful for the current project because each titration family can have
    different color/thermal behavior.  It is still a development-set selector:
    model choice is based on the available labeled runs, so reports must not
    describe it as an independent held-out estimate.
    """

    rows_by_method: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in all_prediction_rows:
        method_key = str(row.get("method_key") or "")
        if method_key and not method_key.startswith("typewise_development_selector:"):
            rows_by_method[method_key].append(row)
    if not rows_by_method:
        return None
    expected_run_count = max(len({str(row.get("run_path") or "") for row in rows}) for rows in rows_by_method.values())
    full_methods = {key: rows for key, rows in rows_by_method.items() if len({str(row.get("run_path") or "") for row in rows}) == expected_run_count}
    if not full_methods:
        return None
    titration_types = sorted({str(row.get("titration_type") or "") for rows in full_methods.values() for row in rows if row.get("titration_type")})
    selected_rows: list[dict[str, Any]] = []
    selection: dict[str, dict[str, Any]] = {}
    selector_key = "typewise_development_selector:best_per_titration_type"
    for titration_type in titration_types:
        best: tuple[float, float, str, list[dict[str, Any]], dict[str, float]] | None = None
        for method_key, rows in full_methods.items():
            subset = [row for row in rows if str(row.get("titration_type") or "") == titration_type]
            if not subset:
                continue
            metrics = metrics_for_predictions([_prediction_from_row(row) for row in subset])
            item = (metrics["mape_percent"], metrics["mae_ml"], method_key, subset, metrics)
            if best is None or item[:2] < best[:2]:
                best = item
        if best is None:
            continue
        _mape, _mae, selected_method, subset, metrics = best
        selection[titration_type] = {
            "selected_method_key": selected_method,
            "mape_percent_on_available_type_runs": metrics["mape_percent"],
            "mae_ml_on_available_type_runs": metrics["mae_ml"],
            "run_count": len(subset),
        }
        for row in subset:
            copied = dict(row)
            copied["method_key"] = selector_key
            copied["method"] = "typewise_development_selector"
            copied["model"] = "best_per_titration_type"
            copied["fold"] = "development_selection_no_independent_validation"
            copied["notes"] = f"selected_source_method={selected_method}; caveat=development_set_model_selection"
            selected_rows.append(copied)
    if len(selected_rows) != expected_run_count:
        return None
    selector_predictions = [_prediction_from_row(row) for row in selected_rows]
    selector_metrics = metrics_for_predictions(selector_predictions)
    comparison_row = {
        "method_key": selector_key,
        "method": "typewise_development_selector",
        "model": "best_per_titration_type",
        "variant": "development_selection_no_independent_validation",
        "run_count": len(selected_rows),
        "mae_ml": round(metric_value(selector_metrics, "mae_ml"), 6),
        "rmse_ml": round(metric_value(selector_metrics, "rmse_ml"), 6),
        "mape_percent": round(metric_value(selector_metrics, "mape_percent"), 6),
        "bias_ml": round(metric_value(selector_metrics, "bias_ml"), 6),
        "within_0p5ml_rate": round(metric_value(selector_metrics, "within_0.5ml_rate"), 6),
        "within_1p0ml_rate": round(metric_value(selector_metrics, "within_1.0ml_rate"), 6),
        "within_5pct_rate": round(metric_value(selector_metrics, "within_5pct_rate"), 6),
    }
    all_prediction_rows.extend(selected_rows)
    return {
        "comparison_row": comparison_row,
        "prediction_rows": selected_rows,
        "selection": selection,
        "caveat": "적정 종류별 모델 선택은 현재 labeled CSV에서 고른 development-set 결과이며 독립 외부 검증 성능으로 쓰면 안 된다.",
    }


def merge_family_outputs(output_dir: str | Path, *, input_dir: str | Path, max_mape_percent: float | None) -> dict[str, Any]:
    out = Path(output_dir)
    comparison_rows: list[dict[str, Any]] = []
    all_prediction_rows: list[dict[str, Any]] = []
    for path in sorted(out.glob("model_comparison_*.csv")):
        if path.name == "model_comparison_merged.csv":
            continue
        comparison_rows.extend(load_csv_rows(path))
    for path in sorted(out.glob("all_predictions_*.csv")):
        if path.name == "all_predictions_merged.csv":
            continue
        all_prediction_rows.extend(load_csv_rows(path))
    if not comparison_rows:
        raise RuntimeError(f"no per-family comparison files found in {out}")
    typewise_selector = add_typewise_development_selector(all_prediction_rows)
    if typewise_selector is not None:
        comparison_rows.append(typewise_selector["comparison_row"])
    comparison_rows.sort(key=lambda row: (float(row.get("mape_percent") or 999999), float(row.get("mae_ml") or 999999)))
    best_key = str(comparison_rows[0]["method_key"])
    best_prediction_rows = [row for row in all_prediction_rows if row.get("method_key") == best_key]
    if not best_prediction_rows:
        raise RuntimeError(f"no prediction rows found for best method {best_key}")
    predictions = [_prediction_from_row(row) for row in best_prediction_rows]
    best_metrics = metrics_for_predictions(predictions)
    best_typewise = typewise_metrics(predictions)
    write_csv(out / "model_comparison.csv", comparison_rows)
    write_csv(out / "all_predictions_merged.csv", all_prediction_rows)
    write_csv(out / "best_predictions.csv", best_prediction_rows)
    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(out),
        "run_count": len(best_prediction_rows),
        "prediction_unit": PREDICTION_UNIT,
        "merge_source_files": [str(path) for path in sorted(out.glob("model_comparison_*.csv"))],
        "leakage_policy": {
            "allowed_current_volume": "injected_volume_ml and candidate_volume_ml",
            "forbidden_progress": sorted(FORBIDDEN_EXACT),
            "sample_concentration_as_feature": False,
            "protocol_fraction_candidates_removed": True,
        },
        "best": {
            "method_key": best_key,
            "metrics": best_metrics,
            "typewise_metrics": best_typewise,
            "predictions_csv": str(out / "best_predictions.csv"),
        },
        "typewise_development_selector": typewise_selector,
        "target": {
            "max_mape_percent": max_mape_percent,
            "passed": max_mape_percent is None or best_metrics["mape_percent"] <= max_mape_percent,
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_doc(Path("docs/ml_current_volume_no_progress.md"), summary)
    return summary


def evaluate_family(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    grid_ml: float,
    family: str,
    max_mape_percent: float | None,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    if family == "merge":
        return merge_family_outputs(out, input_dir=input_dir, max_mape_percent=max_mape_percent)

    runs = load_runs(input_dir)
    if len(runs) < 3:
        raise ValueError("at least 3 CSV runs are required")

    requested_family, windows = parse_family_windows(family)
    frame_records: list[dict[str, Any]] | list[Mapping[str, Any]] = []
    frame_columns: list[str] = []
    all_results: list[tuple[str, list[Prediction]]] = []
    candidate_diagnostics: dict[str, Any] = {"candidate_feature_columns": []}

    if requested_family in {"all", "frame_regression", "frame_classifier"}:
        frame_records, frame_columns = build_frame_records(runs, grid_ml=grid_ml)
    if requested_family in {"all", "run_summary"}:
        all_results.extend(evaluate_run_summary_models(runs))
    if requested_family in {"all", "frame_regression"}:
        all_results.extend(evaluate_frame_remaining_regression(runs, frame_records))
    if requested_family in {"all", "frame_classifier"}:
        all_results.extend(evaluate_frame_zone_classifier(runs, frame_records, windows_ml=windows))
    if requested_family in {"all", "candidate"}:
        candidate_results, candidate_diagnostics = evaluate_candidate_error_models(runs)
        all_results.extend(candidate_results)
    if requested_family not in {"all", "run_summary", "frame_regression", "frame_classifier", "candidate"}:
        raise ValueError(f"unknown family: {family}")

    comparison_rows, predictions_by_key = comparison_and_prediction_rows(all_results, runs)
    if not comparison_rows:
        raise RuntimeError("no model comparison rows were produced")
    best_key = str(comparison_rows[0]["method_key"])
    best_predictions = predictions_by_key[best_key]
    best_metrics = metrics_for_predictions(best_predictions)
    best_typewise = typewise_metrics(best_predictions)

    slug = family_slug(family)
    prediction_rows = [row_from_prediction(prediction) | {"method_key": best_key} for prediction in best_predictions]
    all_prediction_rows = result_rows_for_all_predictions(all_results)
    write_csv(out / f"model_comparison_{slug}.csv", comparison_rows)
    write_csv(out / f"all_predictions_{slug}.csv", all_prediction_rows)
    write_csv(out / f"best_predictions_{slug}.csv", prediction_rows)
    if requested_family in {"all", "frame_regression", "frame_classifier"}:
        write_csv(out / "selected_frame_feature_columns.csv", [{"feature": column} for column in frame_columns], ["feature"])
    if requested_family in {"all", "candidate"}:
        write_csv(out / "selected_candidate_feature_columns.csv", [{"feature": column} for column in candidate_diagnostics["candidate_feature_columns"]], ["feature"])

    summary = {
        "input_dir": str(input_dir),
        "output_dir": str(out),
        "family": family,
        "run_count": len(runs),
        "frame_record_count": len(frame_records),
        "frame_feature_count": len(frame_columns),
        "prediction_unit": PREDICTION_UNIT,
        "leakage_policy": {
            "allowed_current_volume": "injected_volume_ml and candidate_volume_ml",
            "forbidden_progress": sorted(FORBIDDEN_EXACT),
            "sample_concentration_as_feature": False,
            "protocol_fraction_candidates_removed": True,
        },
        "candidate_diagnostics": {key: value for key, value in candidate_diagnostics.items() if key != "candidate_feature_columns"},
        "best": {
            "method_key": best_key,
            "metrics": best_metrics,
            "typewise_metrics": best_typewise,
            "predictions_csv": str(out / f"best_predictions_{slug}.csv"),
        },
        "target": {
            "max_mape_percent": max_mape_percent,
            "passed": max_mape_percent is None or best_metrics["mape_percent"] <= max_mape_percent,
        },
    }
    (out / f"summary_{slug}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if family == "all":
        write_csv(out / "model_comparison.csv", comparison_rows)
        write_csv(out / "best_predictions.csv", prediction_rows)
        (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        write_summary_doc(Path("docs/ml_current_volume_no_progress.md"), summary)
    return summary


def evaluate(input_dir: str | Path, output_dir: str | Path, *, grid_ml: float, max_mape_percent: float | None) -> dict[str, Any]:
    return evaluate_family(input_dir, output_dir, grid_ml=grid_ml, family="all", max_mape_percent=max_mape_percent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--volume-grid-ml", type=float, default=0.25)
    parser.add_argument("--max-mape-percent", type=float, default=None)
    parser.add_argument(
        "--family",
        default="all",
        help="Evaluation family: all, merge, run_summary, candidate, frame_regression, frame_classifier, or frame_classifier_0p5/1p0/2p0/3p0",
    )
    args = parser.parse_args(argv)
    summary = evaluate_family(
        args.input_dir,
        args.output_dir,
        grid_ml=args.volume_grid_ml,
        family=args.family,
        max_mape_percent=args.max_mape_percent,
    )
    print(json.dumps({"output_dir": summary["output_dir"], "family": summary.get("family", "merge"), "best": summary["best"], "target": summary["target"]}, ensure_ascii=False, indent=2))
    if args.max_mape_percent is not None and summary["best"]["metrics"]["mape_percent"] > args.max_mape_percent:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
