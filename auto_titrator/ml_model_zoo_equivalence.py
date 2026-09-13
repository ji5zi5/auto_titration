"""Model-zoo equivalence-volume evaluation without progress leakage.

This module evaluates one predicted equivalence volume per titration run.  It is
separate from the older curve evaluator because this pass has stricter rules:

* no theoretical/reference/target/error/label columns as model inputs;
* no end-of-run progress/fraction features in headline/report models;
* splits are grouped by titration type and held-out concentration;
* optional strong-model dependencies are skipped with durable warnings.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .ml_typewise_eval import CsvRun, load_runs
from .ml_curve_equivalence import (
    EquivalenceCandidate,
    TypewiseRunFold,
    _normalize,
    _to_float,
    _top_indices,
    build_candidate_rows,
    build_run_curve,
    build_typewise_run_folds,
    run_level_metrics,
)

RANDOM_STATE = 42
DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/model_zoo_equivalence_current")
PREDICTION_UNIT = "one_prediction_per_run_model_zoo"

MODEL_COMPARISON_COLUMNS = [
    "claim_scope",
    "validation_mode",
    "selection_mode",
    "split_id",
    "titration_type",
    "held_out_concentration_m",
    "model",
    "params_json",
    "feature_set",
    "candidate_mode",
    "train_run_count",
    "test_run_count",
    "candidate_row_count",
    "feature_count",
    "mae_ml",
    "rmse_ml",
    "mape_percent",
    "bias_ml",
    "concentration_error_percent",
    "within_0p5ml_rate",
    "within_1p0ml_rate",
    "within_2pct_rate",
    "within_5pct_rate",
    "warnings_json",
    "skipped_optional_dependencies_json",
]

WARNING_COLUMNS = [
    "warning_code",
    "severity",
    "claim_scope",
    "validation_mode",
    "split_id",
    "titration_type",
    "model",
    "feature_set",
    "candidate_mode",
    "trigger_metric",
    "threshold",
    "observed_value",
    "message",
]

FORBIDDEN_EXACT = {
    "theoretical_equivalence_volume_ml",
    "theoretical_equivalence_time_s",
    "theoretical_equivalence_pH",
    "actual_equivalence_volume_ml",
    "candidate_error_ml",
    "candidate_abs_error_ml",
    "is_good_candidate",
    "delta_ml",
    "zone_label",
    "status_label",
    "status_confidence",
    "distance_to_equivalence_ml",
    "time_to_equivalence_s",
    "equivalence_window_ml",
    "equivalence_window_label",
    "estimated_equivalence_volume_ml",
    "predicted_equivalence_volume_ml",
    "indicator_endpoint_offset_ml",
    "indicator_endpoint_volume_ml",
    "candidate_fraction_of_run",
    "run_volume_max_ml",
    "run_duration_s",
}
FORBIDDEN_PREFIXES = (
    "actual_",
    "predicted_",
    "estimated_",
    "reference_",
    "selected_pka_",
    "indicator_endpoint_",
)
FORBIDDEN_SUFFIXES = ("_label", "_target")
FORBIDDEN_CONTAINS = ("equivalence",)
PROGRESS_COLUMNS = {"candidate_fraction_of_run", "run_volume_max_ml", "run_duration_s"}
STATIC_COLUMNS = {
    "titration_type",
    "sample_name",
    "sample_concentration_M",
    "sample_volume_ml",
    "sample_valence",
    "titrant_name",
    "titrant_concentration_M",
    "titrant_valence",
    "indicator",
    "theoretical_equivalence_volume_ml",
}
RAW_INTERPOLATABLE_EXACT = {
    "time_s",
    "csv_recording_elapsed_s",
    "pump_elapsed_s",
    "injected_volume_ml",
    "pump_run_rate_ml_per_s",
    "abs_sync_offset_ms",
    "sync_offset_ms",
    "training_quality_score",
    "valid_for_training",
    "preview_visible_latency_ms",
    "processing_latency_ms",
    "visible_roi_width",
    "visible_roi_height",
    "thermal_roi_width",
    "thermal_roi_height",
}


@dataclass(frozen=True)
class ModelSpec:
    name: str
    claim_scope: str
    feature_set: str
    candidate_mode: str
    params: dict[str, Any]
    factory: Callable[[], Any]
    strong_model: bool = False
    optional_dependency: str | None = None


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _model_variant_id(spec: ModelSpec) -> str:
    payload = {
        "name": spec.name,
        "claim_scope": spec.claim_scope,
        "feature_set": spec.feature_set,
        "candidate_mode": spec.candidate_mode,
        "params": spec.params,
    }
    digest = hashlib.sha1(_json(payload).encode("utf-8")).hexdigest()[:10]
    return f"{spec.name}-{digest}"


def _first_text(rows: Sequence[Mapping[str, Any]], column: str) -> str:
    for row in rows:
        value = str(row.get(column) or "").strip()
        if value:
            return value
    return ""


def _is_forbidden_feature(column: str, *, allow_progress: bool = False) -> bool:
    name = str(column)
    lower = name.lower()
    if name in FORBIDDEN_EXACT:
        if allow_progress and name in PROGRESS_COLUMNS:
            return False
        return True
    if any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        return True
    if any(name.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True
    if any(part in lower for part in FORBIDDEN_CONTAINS):
        return True
    if "pka" in lower:
        return True
    if "target" in lower or "label" in lower:
        return True
    return False


def forbidden_features(columns: Iterable[str], *, allow_progress: bool = False) -> list[str]:
    return [column for column in columns if _is_forbidden_feature(column, allow_progress=allow_progress)]


def assert_no_forbidden_features(columns: Iterable[str], *, allow_progress: bool = False) -> None:
    blocked = forbidden_features(columns, allow_progress=allow_progress)
    if blocked:
        raise ValueError(f"forbidden model feature(s): {', '.join(blocked)}")


def _is_interpolatable_column(column: str) -> bool:
    if _is_forbidden_feature(column):
        return False
    if column in RAW_INTERPOLATABLE_EXACT:
        return True
    return column.startswith("visible_") or column.startswith("thermal_")


def _aggregate_duplicate_volumes(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, str]]:
    groups: dict[float, list[Mapping[str, Any]]] = {}
    for row in rows:
        volume = _to_float(row.get("injected_volume_ml"))
        if volume is None:
            continue
        groups.setdefault(round(float(volume), 9), []).append(row)
    if not groups:
        raise ValueError("no injected_volume_ml rows available for volume resampling")
    volumes = np.array(sorted(groups), dtype=float)
    all_columns = set().union(*(row.keys() for row in rows))
    numeric_columns = sorted(column for column in all_columns if _is_interpolatable_column(column))
    series: dict[str, np.ndarray] = {}
    for column in numeric_columns:
        values: list[float] = []
        usable = False
        for volume in volumes:
            nums = [_to_float(row.get(column)) for row in groups[round(float(volume), 9)]]
            nums = [float(value) for value in nums if value is not None]
            if nums:
                values.append(float(statistics.median(nums)))
                usable = True
            else:
                values.append(float("nan"))
        if not usable:
            continue
        arr = np.array(values, dtype=float)
        valid = np.isfinite(arr)
        if not np.any(valid):
            continue
        if not np.all(valid):
            arr[~valid] = np.interp(volumes[~valid], volumes[valid], arr[valid])
        series[column] = arr
    metadata = {column: _first_text(rows, column) for column in STATIC_COLUMNS}
    return volumes, series, metadata


def volume_resample_run(run: CsvRun, *, step_ml: float = 0.05) -> CsvRun:
    """Resample a run onto a fixed injected-volume grid.

    Only raw observable columns are interpolated.  Label/target/error columns are
    not interpolated and only the run-level theoretical volume remains as
    metadata for evaluation.
    """

    if step_ml <= 0:
        raise ValueError("step_ml must be positive")
    source_rows = [row for row in run.rows if _to_float(row.get("injected_volume_ml")) is not None]
    if not source_rows:
        raise ValueError(f"{run.path}: no injected_volume_ml rows")
    volumes, series, metadata = _aggregate_duplicate_volumes(source_rows)
    start = float(np.min(volumes))
    end = float(np.max(volumes))
    if end <= start:
        grid = np.array([start], dtype=float)
    else:
        count = int(math.floor((end - start) / step_ml)) + 1
        grid = start + np.arange(count, dtype=float) * step_ml
        if grid[-1] < end and (end - grid[-1]) > step_ml * 0.5:
            grid = np.append(grid, end)
    out_rows: list[dict[str, Any]] = []
    for idx, volume in enumerate(grid):
        row: dict[str, Any] = dict(metadata)
        row["injected_volume_ml"] = round(float(volume), 6)
        row["sample_concentration_M"] = str(run.concentration_m)
        row["theoretical_equivalence_volume_ml"] = str(run.theoretical_equivalence_volume_ml)
        row["titration_type"] = run.titration_type
        for column, values in series.items():
            if column == "injected_volume_ml":
                continue
            row[column] = round(float(np.interp(volume, volumes, values)), 6)
        if "time_s" not in row:
            row["time_s"] = float(idx)
        out_rows.append(row)
    return CsvRun(
        path=run.path,
        titration_type=run.titration_type,
        concentration_m=run.concentration_m,
        theoretical_equivalence_volume_ml=run.theoretical_equivalence_volume_ml,
        rows=out_rows,
    )


def _savgol_or_moving(values: Sequence[float], *, window_points: int, polyorder: int = 2) -> np.ndarray:
    arr = np.array(values, dtype=float)
    if len(arr) < 5:
        return arr.copy()
    width = max(3, int(window_points))
    if width % 2 == 0:
        width += 1
    width = min(width, len(arr) if len(arr) % 2 == 1 else len(arr) - 1)
    if width <= polyorder + 1:
        width = polyorder + 3
        if width % 2 == 0:
            width += 1
    if width > len(arr):
        width = len(arr) if len(arr) % 2 == 1 else len(arr) - 1
    if width < 3 or width <= polyorder:
        return arr.copy()
    try:
        from scipy.signal import savgol_filter  # type: ignore

        return np.array(savgol_filter(arr, window_length=width, polyorder=min(polyorder, width - 1), mode="interp"), dtype=float)
    except Exception:
        kernel = np.ones(width, dtype=float) / width
        pad = width // 2
        return np.convolve(np.pad(arr, (pad, pad), mode="edge"), kernel, mode="valid")


def _add_savgol_series(curve: Any, *, window_points: int) -> None:
    # Add a second smoothed/derivative family without replacing existing legacy
    # moving-average fields.  Candidate extraction can use both families.
    volume = np.array(curve.volume_ml, dtype=float)
    for key in (
        "visible_color_delta",
        "visible_HSV_delta",
        "visible_H_mean",
        "visible_S_mean",
        "visible_V_mean",
        "thermal_roi_avg",
        "thermal_roi_p95",
        "thermal_raw_roi_p50",
        "thermal_raw_roi_p95",
    ):
        base = curve.series.get(f"{key}_smooth")
        if not base:
            continue
        smooth = _savgol_or_moving(base, window_points=window_points)
        slope = np.gradient(smooth, volume) if len(smooth) > 1 else np.zeros(len(smooth), dtype=float)
        curvature = np.gradient(slope, volume) if len(slope) > 1 else np.zeros(len(slope), dtype=float)
        curve.series[f"{key}_savgol"] = [round(float(v), 6) for v in smooth]
        curve.series[f"{key}_savgol_slope"] = [round(float(v), 6) for v in slope]
        curve.series[f"{key}_savgol_curvature"] = [round(float(v), 6) for v in curvature]


def _candidate_score(curve: Any, keys: Sequence[str]) -> np.ndarray:
    acc: np.ndarray | None = None
    for key in keys:
        arr = _normalize(curve.series.get(key, []))
        if len(arr) == 0:
            continue
        acc = arr if acc is None else acc + arr
    if acc is None:
        return np.zeros(len(curve.volume_ml), dtype=float)
    return acc / max(1, len(keys))


def extract_sensor_candidates(curve: Any, *, max_candidates_per_source: int = 5) -> list[EquivalenceCandidate]:
    color_score = _candidate_score(
        curve,
        (
            "visible_color_delta_slope",
            "visible_HSV_delta_slope",
            "visible_H_mean_slope",
            "visible_color_delta_savgol_slope",
            "visible_HSV_delta_savgol_slope",
        ),
    )
    thermal_score = _candidate_score(
        curve,
        (
            "thermal_roi_avg_slope",
            "thermal_roi_p95_slope",
            "thermal_raw_roi_p50_slope",
            "thermal_roi_avg_savgol_slope",
            "thermal_roi_p95_savgol_slope",
            "thermal_raw_roi_p50_savgol_slope",
        ),
    )
    if len(color_score) and len(thermal_score):
        fusion_score = (color_score + thermal_score) / 2.0
    elif len(color_score):
        fusion_score = color_score
    else:
        fusion_score = thermal_score
    source_scores = {
        "color": color_score,
        "thermal": thermal_score,
        "fusion_sensor": fusion_score,
    }
    candidates: list[EquivalenceCandidate] = []
    for source, scores in source_scores.items():
        for index in _top_indices(scores, max_candidates_per_source):
            candidates.append(
                EquivalenceCandidate(
                    volume_ml=round(float(curve.volume_ml[index]), 6),
                    source=source,
                    score=round(float(scores[index]), 6),
                    index=index,
                )
            )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.source, candidate.volume_ml))
    return candidates


def _protocol_fraction_candidates(curve: Any) -> list[EquivalenceCandidate]:
    if not curve.volume_ml:
        return []
    volumes = np.array(curve.volume_ml, dtype=float)
    max_volume = float(np.max(volumes))
    candidates: list[EquivalenceCandidate] = []
    for fraction in (0.55, 0.60, 0.65, 0.70, 0.72, 0.75, 0.78, 0.80, 0.83, 0.85, 0.88):
        target = max_volume * fraction
        index = int(np.argmin(np.abs(volumes - target)))
        candidates.append(
            EquivalenceCandidate(
                volume_ml=round(float(volumes[index]), 6),
                source="protocol_fraction",
                score=round(0.5 + fraction, 6),
                index=index,
            )
        )
    return candidates


def candidate_rows_for_runs(
    runs: Sequence[CsvRun],
    *,
    volume_grid_ml: float = 0.05,
    smoothing_window_ml: float = 0.25,
    max_candidates_per_source: int = 5,
    include_protocol_candidates: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    window_points = max(3, int(round(smoothing_window_ml / max(volume_grid_ml, 1e-9))))
    if window_points % 2 == 0:
        window_points += 1
    for run in runs:
        resampled = volume_resample_run(run, step_ml=volume_grid_ml)
        curve = build_run_curve(resampled, smoothing_window=window_points)
        _add_savgol_series(curve, window_points=window_points)
        candidates = extract_sensor_candidates(curve, max_candidates_per_source=max_candidates_per_source)
        if include_protocol_candidates:
            candidates = sorted(
                [*candidates, *_protocol_fraction_candidates(curve)],
                key=lambda candidate: (-candidate.score, candidate.source, candidate.volume_ml),
            )
        run_rows = build_candidate_rows(resampled, curve, candidates, window_points=max(2, window_points // 2))
        for row in run_rows:
            source = str(row.get("candidate_source") or "")
            row["source_is_fusion_sensor"] = 1.0 if source == "fusion_sensor" else 0.0
            row["source_is_protocol_fraction"] = 1.0 if source == "protocol_fraction" else 0.0
            # Recompute a useful nearest-fusion feature for the new explicit source.
            fusion_volumes = [float(c.volume_ml) for c in candidates if c.source == "fusion_sensor"]
            volume = _to_float(row.get("candidate_volume_ml")) or 0.0
            row["nearest_fusion_sensor_candidate_distance_ml"] = (
                round(min(abs(volume - other) for other in fusion_volumes), 6) if fusion_volumes else 0.0
            )
        rows.extend(run_rows)
    return rows


def select_feature_columns(columns: Iterable[str], *, feature_set: str, allow_progress: bool = False) -> list[str]:
    selected: list[str] = []
    for column in sorted(set(columns)):
        if _is_forbidden_feature(column, allow_progress=allow_progress):
            continue
        if column in PROGRESS_COLUMNS and not allow_progress:
            continue
        if column in {"run_path", "titration_type", "candidate_source", "held_out_concentration_m"}:
            continue
        if feature_set == "sensor_signal_only" and (
            column == "candidate_volume_ml" or column.startswith("pump_") or column in {"time_s", "csv_recording_elapsed_s"}
        ):
            continue
        if feature_set == "sensor_signal_only" and not (
            column == "candidate_score"
            or column.startswith("visible_")
            or column.startswith("thermal_")
            or column.startswith("source_is_")
            or "agreement" in column
            or "density" in column
            or "nearest_" in column
            or "score_gap" in column
            or "score_rank" in column
        ):
            continue
        if feature_set == "sensor_plus_current_volume" and not (
            column == "candidate_volume_ml"
            or column == "candidate_score"
            or column == "pump_run_rate_ml_per_s"
            or column.startswith("visible_")
            or column.startswith("thermal_")
            or column.startswith("source_is_")
            or "agreement" in column
            or "density" in column
            or "nearest_" in column
            or "score_gap" in column
            or "score_rank" in column
        ):
            continue
        if feature_set == "sensor_plus_progress" and not (
            column == "candidate_volume_ml"
            or column == "candidate_score"
            or column == "pump_run_rate_ml_per_s"
            or column in PROGRESS_COLUMNS
            or column.startswith("visible_")
            or column.startswith("thermal_")
            or column.startswith("source_is_")
            or "agreement" in column
            or "density" in column
            or "nearest_" in column
            or "score_gap" in column
            or "score_rank" in column
        ):
            continue
        selected.append(column)
    assert_no_forbidden_features(selected, allow_progress=allow_progress)
    blocked_progress = [column for column in selected if column in PROGRESS_COLUMNS or "fraction_of_run" in column]
    if blocked_progress and not allow_progress:
        raise ValueError(f"progress/protocol feature(s) leaked into model input: {blocked_progress}")
    return selected


def _matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    matrix: list[list[float]] = []
    for row in rows:
        matrix.append([_to_float(row.get(column)) or 0.0 for column in columns])
    return np.array(matrix, dtype=float)


def _safe_model_name(name: str, params: Mapping[str, Any]) -> str:
    if not params:
        return name
    compact = "_".join(f"{k}-{v}" for k, v in sorted(params.items()))
    return f"{name}[{compact}]"


def _sklearn_model_specs() -> list[ModelSpec]:
    try:
        from sklearn.ensemble import (
            ExtraTreesRegressor,
            GradientBoostingRegressor,
            HistGradientBoostingRegressor,
            RandomForestRegressor,
        )
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import RBF, WhiteKernel
        from sklearn.kernel_ridge import KernelRidge
        from sklearn.neural_network import MLPRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVR
    except Exception as exc:  # pragma: no cover - tested via runtime warnings
        raise RuntimeError(f"scikit-learn model imports failed: {exc!r}") from exc

    specs: list[ModelSpec] = []

    def add_extra(name: str, *, claim_scope: str, feature_set: str, candidate_mode: str) -> None:
        for params in itertools.product([100], [None, 3], [1, 2]):
            n_estimators, max_depth, min_samples_leaf = params
            pdict = {"n_estimators": n_estimators, "max_depth": max_depth, "min_samples_leaf": min_samples_leaf}
            specs.append(
                ModelSpec(
                    name=name,
                    claim_scope=claim_scope,
                    feature_set=feature_set,
                    candidate_mode=candidate_mode,
                    params=pdict,
                    factory=lambda pdict=pdict: ExtraTreesRegressor(random_state=RANDOM_STATE, **pdict),
                )
            )

    add_extra(
        "baseline_extra_trees_sensor_signal",
        claim_scope="headline",
        feature_set="sensor_signal_only",
        candidate_mode="sensor_only_no_progress",
    )
    add_extra(
        "extra_trees_sensor_plus_current_volume",
        claim_scope="headline",
        feature_set="sensor_plus_current_volume",
        candidate_mode="sensor_plus_current_volume_no_progress",
    )

    for c, gamma, epsilon in itertools.product([0.1, 1, 10], ["scale", 0.1, 1], [0.05, 0.2, 0.5]):
        pdict = {"C": c, "gamma": gamma, "epsilon": epsilon}
        specs.append(
            ModelSpec(
                name="svr_rbf_sensor_plus_current_volume",
                claim_scope="headline",
                feature_set="sensor_plus_current_volume",
                candidate_mode="sensor_plus_current_volume_no_progress",
                params=pdict,
                factory=lambda pdict=pdict: make_pipeline(StandardScaler(), SVR(kernel="rbf", **pdict)),
            )
        )

    # Exploratory sklearn strong/broader candidates.
    exploratory_factories: list[tuple[str, dict[str, Any], Callable[[], Any], bool]] = [
        (
            "random_forest_regressor",
            {"n_estimators": 100, "max_depth": None, "min_samples_leaf": 1},
            lambda: RandomForestRegressor(n_estimators=100, random_state=RANDOM_STATE),
            False,
        ),
        (
            "gradient_boosting_regressor",
            {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 2},
            lambda: GradientBoostingRegressor(n_estimators=80, learning_rate=0.05, max_depth=2, random_state=RANDOM_STATE),
            True,
        ),
        (
            "hist_gradient_boosting_regressor",
            {"max_iter": 80, "learning_rate": 0.05, "max_leaf_nodes": 7},
            lambda: HistGradientBoostingRegressor(max_iter=80, learning_rate=0.05, max_leaf_nodes=7, random_state=RANDOM_STATE),
            True,
        ),
        (
            "kernel_ridge_rbf",
            {"alpha": 1.0, "gamma": 0.1},
            lambda: make_pipeline(StandardScaler(), KernelRidge(kernel="rbf", alpha=1.0, gamma=0.1)),
            True,
        ),
        (
            "gaussian_process_regressor",
            {"kernel": "RBF+WhiteKernel", "alpha": 1e-6},
            lambda: make_pipeline(
                StandardScaler(),
                GaussianProcessRegressor(kernel=RBF(length_scale=1.0) + WhiteKernel(noise_level=1e-2), alpha=1e-6, random_state=RANDOM_STATE),
            ),
            True,
        ),
        (
            "mlp_regressor",
            {"hidden_layer_sizes": [16], "max_iter": 500, "early_stopping": False},
            lambda: make_pipeline(
                StandardScaler(),
                MLPRegressor(hidden_layer_sizes=(16,), max_iter=500, alpha=0.01, random_state=RANDOM_STATE),
            ),
            True,
        ),
    ]
    for name, params, factory, strong in exploratory_factories:
        specs.append(
            ModelSpec(
                name=name,
                claim_scope="exploratory",
                feature_set="sensor_plus_current_volume",
                candidate_mode="sensor_plus_current_volume_no_progress",
                params=params,
                factory=factory,
                strong_model=strong,
            )
        )
    return specs


def _optional_model_specs() -> tuple[list[ModelSpec], list[dict[str, Any]]]:
    specs: list[ModelSpec] = []
    skipped: list[dict[str, Any]] = []
    try:
        from xgboost import XGBRegressor  # type: ignore

        specs.append(
            ModelSpec(
                name="xgboost_reg_squarederror",
                claim_scope="exploratory",
                feature_set="sensor_plus_current_volume",
                candidate_mode="sensor_plus_current_volume_no_progress",
                params={"n_estimators": 60, "max_depth": 2, "learning_rate": 0.05},
                factory=lambda: XGBRegressor(
                    n_estimators=60,
                    max_depth=2,
                    learning_rate=0.05,
                    objective="reg:squarederror",
                    random_state=RANDOM_STATE,
                    n_jobs=1,
                    verbosity=0,
                ),
                strong_model=True,
                optional_dependency="xgboost",
            )
        )
    except Exception as exc:
        skipped.append({"dependency": "xgboost", "error": repr(exc)})
    try:
        from lightgbm import LGBMRegressor  # type: ignore

        specs.append(
            ModelSpec(
                name="lightgbm_regression_l1",
                claim_scope="exploratory",
                feature_set="sensor_plus_current_volume",
                candidate_mode="sensor_plus_current_volume_no_progress",
                params={"n_estimators": 60, "max_depth": 2, "learning_rate": 0.05, "min_child_samples": 2},
                factory=lambda: LGBMRegressor(
                    n_estimators=60,
                    max_depth=2,
                    learning_rate=0.05,
                    min_child_samples=2,
                    objective="regression_l1",
                    random_state=RANDOM_STATE,
                    n_jobs=1,
                    verbose=-1,
                ),
                strong_model=True,
                optional_dependency="lightgbm",
            )
        )
    except Exception as exc:
        skipped.append({"dependency": "lightgbm", "error": repr(exc)})
    try:
        from catboost import CatBoostRegressor  # type: ignore

        specs.append(
            ModelSpec(
                name="catboost_mae",
                claim_scope="exploratory",
                feature_set="sensor_plus_current_volume",
                candidate_mode="sensor_plus_current_volume_no_progress",
                params={"iterations": 60, "depth": 2, "learning_rate": 0.05, "loss_function": "MAE"},
                factory=lambda: CatBoostRegressor(
                    iterations=60,
                    depth=2,
                    learning_rate=0.05,
                    loss_function="MAE",
                    random_seed=RANDOM_STATE,
                    thread_count=1,
                    verbose=False,
                ),
                strong_model=True,
                optional_dependency="catboost",
            )
        )
    except Exception as exc:
        skipped.append({"dependency": "catboost", "error": repr(exc)})
    return specs, skipped


def _progress_model_specs(specs: Sequence[ModelSpec]) -> list[ModelSpec]:
    out: list[ModelSpec] = []
    for spec in specs:
        if spec.feature_set == "sensor_plus_current_volume":
            out.append(
                replace(
                    spec,
                    feature_set="sensor_plus_progress",
                    candidate_mode=spec.candidate_mode.replace("_no_progress", "_with_progress"),
                )
            )
        elif spec.candidate_mode.endswith("_no_progress"):
            out.append(replace(spec, candidate_mode=spec.candidate_mode.replace("_no_progress", "_with_progress_candidates")))
        else:
            out.append(spec)
    return out


def model_specs(*, include_optional: bool = True, include_progress: bool = False) -> tuple[list[ModelSpec], list[dict[str, Any]]]:
    specs = _sklearn_model_specs()
    skipped: list[dict[str, Any]] = []
    if include_optional:
        optional, skipped = _optional_model_specs()
        specs.extend(optional)
    if include_progress:
        specs = _progress_model_specs(specs)
    return specs, skipped


def _warning(
    code: str,
    *,
    severity: str,
    claim_scope: str,
    validation_mode: str,
    split_id: str,
    titration_type: str,
    model: str,
    feature_set: str,
    candidate_mode: str,
    trigger_metric: str,
    threshold: str | float,
    observed_value: str | float,
    message: str,
) -> dict[str, Any]:
    return {
        "warning_code": code,
        "severity": severity,
        "claim_scope": claim_scope,
        "validation_mode": validation_mode,
        "split_id": split_id,
        "titration_type": titration_type,
        "model": model,
        "feature_set": feature_set,
        "candidate_mode": candidate_mode,
        "trigger_metric": trigger_metric,
        "threshold": threshold,
        "observed_value": observed_value,
        "message": message,
    }


def _fit_predict_candidates(
    spec: ModelSpec,
    train_rows: Sequence[Mapping[str, Any]],
    test_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from sklearn.base import clone  # type: ignore

    x_train = _matrix(train_rows, feature_columns)
    x_test = _matrix(test_rows, feature_columns)
    y_abs = np.array([_to_float(row.get("candidate_abs_error_ml")) or 0.0 for row in train_rows], dtype=float)
    y_signed = np.array([_to_float(row.get("candidate_error_ml")) or 0.0 for row in train_rows], dtype=float)
    abs_model = spec.factory()
    signed_model = clone(abs_model)
    abs_model.fit(x_train, y_abs)
    signed_model.fit(x_train, y_signed)
    train_abs_pred = np.array(abs_model.predict(x_train), dtype=float)
    train_signed_pred = np.array(signed_model.predict(x_train), dtype=float)
    test_abs_pred = np.array(abs_model.predict(x_test), dtype=float)
    test_signed_pred = np.array(signed_model.predict(x_test), dtype=float)

    train_candidate_volumes = np.array([_to_float(row.get("candidate_volume_ml")) or 0.0 for row in train_rows], dtype=float)
    train_actual = np.array([_to_float(row.get("actual_equivalence_volume_ml")) or 0.0 for row in train_rows], dtype=float)
    train_corrected = train_candidate_volumes - train_signed_pred
    train_corrected_mae = float(np.mean(np.abs(train_corrected - train_actual))) if len(train_actual) else 0.0

    out_rows: list[dict[str, Any]] = []
    for index, row in enumerate(test_rows):
        out = dict(row)
        out["predicted_candidate_abs_error_ml"] = round(float(test_abs_pred[index]), 6)
        out["predicted_candidate_error_ml"] = round(float(test_signed_pred[index]), 6)
        out_rows.append(out)
    meta = {
        "train_corrected_equivalence_mae_ml": train_corrected_mae,
        "train_abs_error_fit_mae_ml": float(np.mean(np.abs(train_abs_pred - y_abs))) if len(y_abs) else 0.0,
    }
    return out_rows, meta


def _choose_run_prediction(candidate_rows: Sequence[Mapping[str, Any]], *, spec: ModelSpec) -> dict[str, Any]:
    if not candidate_rows:
        return {}
    chosen = min(
        candidate_rows,
        key=lambda row: (
            _to_float(row.get("predicted_candidate_abs_error_ml")) if _to_float(row.get("predicted_candidate_abs_error_ml")) is not None else float("inf"),
            -(_to_float(row.get("candidate_score")) or 0.0),
        ),
    )
    candidate_volume = _to_float(chosen.get("candidate_volume_ml")) or 0.0
    signed_error = _to_float(chosen.get("predicted_candidate_error_ml")) or 0.0
    predicted = candidate_volume - signed_error
    actual = _to_float(chosen.get("actual_equivalence_volume_ml")) or 0.0
    return {
        "run_path": chosen.get("run_path", ""),
        "titration_type": chosen.get("titration_type", ""),
        "held_out_concentration_m": chosen.get("held_out_concentration_m", ""),
        "model": spec.name,
        "params_json": _json(spec.params),
        "feature_set": spec.feature_set,
        "candidate_mode": spec.candidate_mode,
        "claim_scope": spec.claim_scope,
        "actual_equivalence_volume_ml": round(float(actual), 6),
        "predicted_equivalence_volume_ml": round(float(predicted), 6),
        "chosen_candidate_volume_ml": round(float(candidate_volume), 6),
        "chosen_candidate_source": chosen.get("candidate_source", ""),
        "chosen_candidate_score": chosen.get("candidate_score", ""),
        "predicted_candidate_error_ml": round(float(signed_error), 6),
        "prediction_error_ml": round(float(predicted - actual), 6),
        "abs_prediction_error_ml": round(abs(float(predicted - actual)), 6),
    }


def _group_rows_by_run(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("run_path") or ""), []).append(row)
    return grouped


def _row_from_metrics(
    *,
    spec: ModelSpec,
    fold: TypewiseRunFold,
    split_id: str,
    feature_columns: Sequence[str],
    candidate_count: int,
    metrics: Mapping[str, Any],
    warnings: Sequence[Mapping[str, Any]],
    skipped_optional: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "claim_scope": spec.claim_scope,
        "validation_mode": "leave_one_concentration_out",
        "selection_mode": "fixed_grid_exhaustive_small_data" if spec.claim_scope == "headline" else "exploratory_model_zoo_same_split",
        "split_id": split_id,
        "titration_type": fold.titration_type,
        "held_out_concentration_m": fold.held_out_concentration_m,
        "model": spec.name,
        "params_json": _json(spec.params),
        "feature_set": spec.feature_set,
        "candidate_mode": spec.candidate_mode,
        "train_run_count": len({str(run.path) for run in fold.train_runs}),
        "test_run_count": len({str(run.path) for run in fold.test_runs}),
        "candidate_row_count": candidate_count,
        "feature_count": len(feature_columns),
        "mae_ml": metrics.get("mae_ml", 0.0),
        "rmse_ml": metrics.get("rmse_ml", 0.0),
        "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
        "bias_ml": metrics.get("bias_ml", 0.0),
        "concentration_error_percent": metrics.get("concentration_mae_percent", 0.0),
        "within_0p5ml_rate": metrics.get("within_0.5ml_rate", 0.0),
        "within_1p0ml_rate": metrics.get("within_1.0ml_rate", 0.0),
        "within_2pct_rate": metrics.get("within_2pct_rate", 0.0),
        "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
        "warnings_json": _json([w.get("warning_code") for w in warnings]),
        "skipped_optional_dependencies_json": _json(skipped_optional),
    }


def _warnings_for_result(
    *,
    spec: ModelSpec,
    fold: TypewiseRunFold,
    split_id: str,
    feature_count: int,
    train_candidate_count: int,
    train_meta: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    model_label = spec.name
    train_run_count = len({str(run.path) for run in fold.train_runs})
    heldout_mae = float(metrics.get("mae_ml", 0.0) or 0.0)
    train_mae = float(train_meta.get("train_corrected_equivalence_mae_ml", 0.0) or 0.0)
    common = dict(
        claim_scope=spec.claim_scope,
        validation_mode="leave_one_concentration_out",
        split_id=split_id,
        titration_type=fold.titration_type,
        model=model_label,
        feature_set=spec.feature_set,
        candidate_mode=spec.candidate_mode,
    )
    if feature_count > train_run_count * 5:
        warnings.append(
            _warning(
                "feature_count_high_vs_runs",
                severity="warn",
                trigger_metric="feature_count/train_run_count",
                threshold=train_run_count * 5,
                observed_value=feature_count,
                message="Feature count is high compared with unique training runs.",
                **common,
            )
        )
    if train_mae < 0.25 and heldout_mae > 2.0:
        warnings.append(
            _warning(
                "train_heldout_gap_high",
                severity="warn",
                trigger_metric="train_mae_and_heldout_mae",
                threshold="train<0.25 and heldout>2.0",
                observed_value=f"train={train_mae:.6g}, heldout={heldout_mae:.6g}",
                message="Training candidate correction is very low but held-out run error is high.",
                **common,
            )
        )
    ratio = heldout_mae / max(train_mae, 0.05)
    if ratio > 10:
        warnings.append(
            _warning(
                "heldout_train_ratio_high",
                severity="warn",
                trigger_metric="heldout_mae/train_mae",
                threshold=10,
                observed_value=round(ratio, 6),
                message="Held-out MAE is much larger than training corrected MAE.",
                **common,
            )
        )
    if spec.strong_model and train_run_count < 10:
        warnings.append(
            _warning(
                "strong_model_small_data",
                severity="info",
                trigger_metric="train_run_count",
                threshold=10,
                observed_value=train_run_count,
                message="Strong model evaluated on a very small number of independent training runs.",
                **common,
            )
        )
    if train_candidate_count > train_run_count and train_run_count <= 3:
        warnings.append(
            _warning(
                "candidate_rows_not_independent_runs",
                severity="info",
                trigger_metric="candidate_rows_vs_unique_runs",
                threshold="unique_train_runs>3 preferred",
                observed_value=f"candidate_rows={train_candidate_count}, train_runs={train_run_count}",
                message="Candidate rows are not independent experiments; evaluation remains grouped by run.",
                **common,
            )
        )
    return warnings


def evaluate_fold(
    fold: TypewiseRunFold,
    spec: ModelSpec,
    *,
    volume_grid_ml: float,
    smoothing_window_ml: float,
    skipped_optional: Sequence[Mapping[str, Any]],
    include_progress: bool = False,
    include_protocol_candidates: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if include_protocol_candidates and not include_progress:
        raise ValueError("protocol-fraction candidates require include_progress=True because they depend on end-of-run volume")
    split_id = f"{fold.titration_type}-holdout-{fold.held_out_concentration_m:g}M-{_model_variant_id(spec)}"
    train_rows = candidate_rows_for_runs(
        fold.train_runs,
        volume_grid_ml=volume_grid_ml,
        smoothing_window_ml=smoothing_window_ml,
        include_protocol_candidates=include_protocol_candidates,
    )
    test_rows = candidate_rows_for_runs(
        fold.test_runs,
        volume_grid_ml=volume_grid_ml,
        smoothing_window_ml=smoothing_window_ml,
        include_protocol_candidates=include_protocol_candidates,
    )
    if not train_rows or not test_rows:
        metrics = run_level_metrics([])
        warning_rows = [
            _warning(
                "no_candidate_rows",
                severity="error",
                claim_scope=spec.claim_scope,
                validation_mode="leave_one_concentration_out",
                split_id=split_id,
                titration_type=fold.titration_type,
                model=spec.name,
                feature_set=spec.feature_set,
                candidate_mode=spec.candidate_mode,
                trigger_metric="candidate_row_count",
                threshold=">0",
                observed_value=0,
                message="No candidate rows were available for this fold.",
            )
        ]
        return (
            _row_from_metrics(
                spec=spec,
                fold=fold,
                split_id=split_id,
                feature_columns=[],
                candidate_count=0,
                metrics=metrics,
                warnings=warning_rows,
                skipped_optional=skipped_optional,
            ),
            [],
            [],
            warning_rows,
            [],
        )
    feature_columns = select_feature_columns(
        set().union(*(row.keys() for row in train_rows + test_rows)),
        feature_set=spec.feature_set,
        allow_progress=include_progress,
    )
    predictions_by_candidate, train_meta = _fit_predict_candidates(spec, train_rows, test_rows, feature_columns)
    run_predictions: list[dict[str, Any]] = []
    for _run_path, rows in _group_rows_by_run(predictions_by_candidate).items():
        chosen = _choose_run_prediction(rows, spec=spec)
        if chosen:
            chosen["split_id"] = split_id
            run_predictions.append(chosen)
    metrics = run_level_metrics(run_predictions)
    warning_rows = _warnings_for_result(
        spec=spec,
        fold=fold,
        split_id=split_id,
        feature_count=len(feature_columns),
        train_candidate_count=len(train_rows),
        train_meta=train_meta,
        metrics=metrics,
    )
    comparison_row = _row_from_metrics(
        spec=spec,
        fold=fold,
        split_id=split_id,
        feature_columns=feature_columns,
        candidate_count=len(test_rows),
        metrics=metrics,
        warnings=warning_rows,
        skipped_optional=skipped_optional,
    )
    candidate_feature_rows = []
    for row in test_rows:
        candidate_feature_rows.append(
            {
                "run_path": row.get("run_path", ""),
                "candidate_source": row.get("candidate_source", ""),
                "candidate_volume_ml": row.get("candidate_volume_ml", ""),
                **{column: row.get(column, 0.0) for column in feature_columns},
            }
        )
    return comparison_row, run_predictions, candidate_feature_rows, warning_rows, list(feature_columns)


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = sorted(set().union(*(row.keys() for row in rows))) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _prediction_group_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("claim_scope") or ""),
        str(row.get("model") or ""),
        str(row.get("params_json") or ""),
        str(row.get("feature_set") or ""),
        str(row.get("candidate_mode") or ""),
    )


def _aggregate_prediction_rows(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = {}
    for row in predictions:
        grouped.setdefault(_prediction_group_key(row), []).append(row)
    rows: list[dict[str, Any]] = []
    for (claim_scope, model, params_json, feature_set, candidate_mode), subset in grouped.items():
        metrics = run_level_metrics(subset)
        rows.append(
            {
                "claim_scope": claim_scope,
                "model": model,
                "params_json": params_json,
                "feature_set": feature_set,
                "candidate_mode": candidate_mode,
                "run_count": metrics.get("run_count", 0),
                "mae_ml": metrics.get("mae_ml", 0.0),
                "rmse_ml": metrics.get("rmse_ml", 0.0),
                "mape_percent": metrics.get("mae_percent_of_equivalence", 0.0),
                "bias_ml": metrics.get("bias_ml", 0.0),
                "concentration_error_percent": metrics.get("concentration_mae_percent", 0.0),
                "within_0p5ml_rate": metrics.get("within_0.5ml_rate", 0.0),
                "within_1p0ml_rate": metrics.get("within_1.0ml_rate", 0.0),
                "within_2pct_rate": metrics.get("within_2pct_rate", 0.0),
                "within_5pct_rate": metrics.get("within_5pct_rate", 0.0),
            }
        )
    rows.sort(key=lambda row: (float(row.get("mae_ml") or 0.0), str(row.get("claim_scope")), str(row.get("model"))))
    return rows


def _typewise_best_headline_rows(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for row in predictions:
        if row.get("claim_scope") != "headline":
            continue
        by_type.setdefault(str(row.get("titration_type") or ""), []).append(row)
    rows: list[dict[str, Any]] = []
    for titration_type, subset in sorted(by_type.items()):
        candidates = _aggregate_prediction_rows(subset)
        if not candidates:
            continue
        best = dict(candidates[0])
        best["titration_type"] = titration_type
        rows.append(best)
    return rows


def _candidate_availability_rows(
    runs: Sequence[CsvRun],
    *,
    volume_grid_ml: float,
    smoothing_window_ml: float,
    include_protocol_candidates: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        candidate_rows = candidate_rows_for_runs(
            [run],
            volume_grid_ml=volume_grid_ml,
            smoothing_window_ml=smoothing_window_ml,
            include_protocol_candidates=include_protocol_candidates,
        )
        if not candidate_rows:
            continue
        best_score = max(candidate_rows, key=lambda row: _to_float(row.get("candidate_score")) or 0.0)
        oracle = min(candidate_rows, key=lambda row: abs((_to_float(row.get("candidate_volume_ml")) or 0.0) - run.theoretical_equivalence_volume_ml))
        for method, row in (("max_candidate_score", best_score), ("oracle_best_available_sensor_candidate", oracle)):
            volume = _to_float(row.get("candidate_volume_ml")) or 0.0
            rows.append(
                {
                    "titration_type": run.titration_type,
                    "run_path": str(run.path),
                    "actual_equivalence_volume_ml": round(float(run.theoretical_equivalence_volume_ml), 6),
                    "method": method,
                    "candidate_source": row.get("candidate_source", ""),
                    "candidate_volume_ml": round(float(volume), 6),
                    "abs_error_ml": round(abs(float(volume) - float(run.theoretical_equivalence_volume_ml)), 6),
                }
            )
    return rows


def evaluate_model_zoo(
    input_dir: str | Path = DEFAULT_INPUT_DIR,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    *,
    volume_grid_ml: float = 0.05,
    smoothing_window_ml: float = 0.25,
    include_optional: bool = True,
    max_specs: int | None = None,
    include_progress: bool = False,
    include_protocol_candidates: bool | None = None,
) -> dict[str, Any]:
    runs = load_runs(input_dir)
    folds = build_typewise_run_folds(runs)
    if include_protocol_candidates is None:
        include_protocol_candidates = include_progress
    if include_protocol_candidates and not include_progress:
        raise ValueError("protocol-fraction candidates require include_progress=True because they depend on end-of-run volume")
    specs, skipped_optional = model_specs(include_optional=include_optional, include_progress=include_progress)
    if max_specs is not None:
        specs = specs[: int(max_specs)]
    out = Path(output_dir)
    comparison_rows: list[dict[str, Any]] = []
    all_predictions: list[dict[str, Any]] = []
    all_warnings: list[dict[str, Any]] = []
    feature_columns_by_split: dict[str, list[str]] = {}

    for skipped in skipped_optional:
        all_warnings.append(
            _warning(
                "optional_dependency_skipped",
                severity="info",
                claim_scope="exploratory",
                validation_mode="dependency_check",
                split_id="optional_dependency_check",
                titration_type="all",
                model=str(skipped.get("dependency", "")),
                feature_set="",
                candidate_mode="",
                trigger_metric="import",
                threshold="installed",
                observed_value="missing",
                message=str(skipped.get("error", "")),
            )
        )

    for fold in folds:
        for spec in specs:
            comparison, predictions, candidate_features, warnings, feature_columns = evaluate_fold(
                fold,
                spec,
                volume_grid_ml=volume_grid_ml,
                smoothing_window_ml=smoothing_window_ml,
                skipped_optional=skipped_optional,
                include_progress=include_progress,
                include_protocol_candidates=include_protocol_candidates,
            )
            comparison_rows.append(comparison)
            all_predictions.extend(predictions)
            all_warnings.extend(warnings)
            split_id = str(comparison["split_id"])
            feature_columns_by_split[split_id] = feature_columns
            _write_csv(out / "predictions" / fold.titration_type / f"{split_id}.csv", predictions)
            _write_csv(out / "candidate_feature_tables" / fold.titration_type / f"{split_id}.csv", candidate_features)

    _write_csv(out / "model_comparison.csv", comparison_rows, MODEL_COMPARISON_COLUMNS)
    _write_csv(out / "warnings.csv", all_warnings, WARNING_COLUMNS)

    headline_predictions = [row for row in all_predictions if row.get("claim_scope") == "headline"]
    exploratory_predictions = [row for row in all_predictions if row.get("claim_scope") == "exploratory"]
    aggregate_rows = _aggregate_prediction_rows(all_predictions)
    typewise_best_rows = _typewise_best_headline_rows(all_predictions)
    candidate_availability_rows = _candidate_availability_rows(
        runs,
        volume_grid_ml=volume_grid_ml,
        smoothing_window_ml=smoothing_window_ml,
        include_protocol_candidates=include_protocol_candidates,
    )
    _write_csv(out / "aggregate_by_model.csv", aggregate_rows)
    _write_csv(out / "typewise_best_headline.csv", typewise_best_rows)
    _write_csv(out / "candidate_availability_diagnostic.csv", candidate_availability_rows)
    summary = {
        "schema_version": "model_zoo_equivalence_v1",
        "prediction_unit": PREDICTION_UNIT,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "volume_grid_ml": volume_grid_ml,
        "smoothing_window_ml": smoothing_window_ml,
        "run_count": len(runs),
        "fold_count": len(folds),
        "model_spec_count": len(specs),
        "include_progress": include_progress,
        "include_protocol_candidates": include_protocol_candidates,
        "model_comparison_columns": MODEL_COMPARISON_COLUMNS,
        "warning_columns": WARNING_COLUMNS,
        "skipped_optional_dependencies": skipped_optional,
        "overall_headline_metrics_all_rows": run_level_metrics(headline_predictions),
        "overall_exploratory_metrics_all_rows": run_level_metrics(exploratory_predictions),
        "aggregate_by_model_rows": len(aggregate_rows),
        "typewise_best_headline_rows": len(typewise_best_rows),
        "candidate_availability_rows": len(candidate_availability_rows),
        "warnings": all_warnings,
        "feature_columns_by_split": feature_columns_by_split,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "model_comparison.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--volume-grid-ml", type=float, default=0.05)
    parser.add_argument("--smoothing-window-ml", type=float, default=0.25)
    parser.add_argument("--no-optional", action="store_true")
    parser.add_argument(
        "--include-progress",
        action="store_true",
        help="Allow end-of-run progress features for an explicitly non-strict comparison run.",
    )
    parser.add_argument(
        "--no-protocol-candidates",
        action="store_true",
        help="With --include-progress, keep sensor candidates only instead of adding max-volume fraction candidates.",
    )
    parser.add_argument("--max-specs", type=int, default=None, help="Developer smoke limit; not valid for final model comparison")
    args = parser.parse_args(argv)
    output_dir_was_explicit = "--output-dir" in raw_argv or any(arg.startswith("--output-dir=") for arg in raw_argv)
    output_dir = args.output_dir
    if args.include_progress and not output_dir_was_explicit and Path(output_dir) == DEFAULT_OUTPUT_DIR:
        output_dir = "data/ml/model_zoo_equivalence_with_progress"
    summary = evaluate_model_zoo(
        args.input_dir,
        output_dir,
        volume_grid_ml=args.volume_grid_ml,
        smoothing_window_ml=args.smoothing_window_ml,
        include_optional=not args.no_optional,
        max_specs=args.max_specs,
        include_progress=args.include_progress,
        include_protocol_candidates=args.include_progress and not args.no_protocol_candidates,
    )
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "run_count",
                    "fold_count",
                    "model_spec_count",
                    "include_progress",
                    "include_protocol_candidates",
                    "skipped_optional_dependencies",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
