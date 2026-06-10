"""Run-level curve/candidate ML for equivalence-point prediction.

This module targets the project's final ML question: estimate one equivalence
volume for a titration run.  It is intentionally separate from the older
frame-level evaluators so frame count is not mistaken for experiment count.
"""

from __future__ import annotations

import math
import argparse
import csv
import json
import platform
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .ml_typewise_eval import CsvRun, load_runs, resample_run

FEATURE_SETS = (
    "current_fusion",
    "compact_plus",
    "compact_plus_no_progress",
    "thermal_basic",
    "thermal_expanded",
    "color_expanded",
    "fusion_expanded",
    "fusion_no_progress",
    "run_quality_context",
)
PREDICTION_UNIT = "one_prediction_per_run"

VISIBLE_SERIES_COLUMNS = (
    "visible_color_delta",
    "visible_HSV_delta",
    "visible_R_mean",
    "visible_G_mean",
    "visible_B_mean",
    "visible_H_mean",
    "visible_S_mean",
    "visible_V_mean",
    "visible_H_delta",
    "visible_S_delta",
    "visible_V_delta",
    "visible_HSV_baseline_delta",
    "visible_color_baseline_delta",
)

THERMAL_SERIES_COLUMNS = (
    "thermal_roi_avg",
    "thermal_roi_max",
    "thermal_roi_min",
    "thermal_roi_std",
    "thermal_roi_range",
    "thermal_roi_iqr",
    "thermal_roi_p05",
    "thermal_roi_p25",
    "thermal_roi_p50",
    "thermal_roi_p75",
    "thermal_roi_p95",
    "thermal_roi_hot_fraction",
    "thermal_roi_cold_fraction",
    "thermal_raw_roi_range",
    "thermal_raw_roi_iqr",
    "thermal_raw_roi_p05",
    "thermal_raw_roi_p25",
    "thermal_raw_roi_p50",
    "thermal_raw_roi_p75",
    "thermal_raw_roi_p95",
    "thermal_raw_roi_hot_fraction",
    "thermal_raw_roi_cold_fraction",
    "thermal_raw_min",
    "thermal_raw_max",
    "thermal_raw_mean",
    "thermal_raw_std",
    "thermal_raw_range",
    "thermal_raw_iqr",
    "thermal_raw_p05",
    "thermal_raw_p25",
    "thermal_raw_p50",
    "thermal_raw_p75",
    "thermal_raw_p95",
)

THERMAL_COORDINATE_COLUMNS = (
    ("thermal_roi_min_x_norm", "thermal_roi_min_x", "thermal_roi_width"),
    ("thermal_roi_min_y_norm", "thermal_roi_min_y", "thermal_roi_height"),
    ("thermal_roi_max_x_norm", "thermal_roi_max_x", "thermal_roi_width"),
    ("thermal_roi_max_y_norm", "thermal_roi_max_y", "thermal_roi_height"),
    ("thermal_raw_roi_min_x_norm", "thermal_raw_roi_min_x", "thermal_roi_width"),
    ("thermal_raw_roi_min_y_norm", "thermal_raw_roi_min_y", "thermal_roi_height"),
    ("thermal_raw_roi_max_x_norm", "thermal_raw_roi_max_x", "thermal_roi_width"),
    ("thermal_raw_roi_max_y_norm", "thermal_raw_roi_max_y", "thermal_roi_height"),
)

QUALITY_CONTEXT_COLUMNS = (
    "abs_sync_offset_ms",
    "sync_offset_ms",
    "training_quality_score",
    "valid_for_training",
    "pump_run_rate_ml_per_s",
    "thermal_roi_width",
    "thermal_roi_height",
    "visible_roi_width",
    "visible_roi_height",
    "processing_latency_ms",
    "preview_visible_latency_ms",
)


@dataclass(frozen=True)
class RunCurve:
    run: CsvRun
    volume_ml: list[float]
    time_s: list[float]
    series: dict[str, list[float]]


@dataclass(frozen=True)
class EquivalenceCandidate:
    volume_ml: float
    source: str
    score: float
    index: int


@dataclass(frozen=True)
class TypewiseRunFold:
    titration_type: str
    held_out_concentration_m: float
    train_runs: list[CsvRun]
    test_runs: list[CsvRun]


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _numeric_array(rows: Sequence[Mapping[str, Any]], column: str) -> np.ndarray:
    values = [_to_float(row.get(column)) for row in rows]
    numeric = [value if value is not None else np.nan for value in values]
    arr = np.array(numeric, dtype=float)
    if np.all(np.isnan(arr)):
        return np.zeros(len(rows), dtype=float)
    index = np.arange(len(arr), dtype=float)
    valid = ~np.isnan(arr)
    arr[~valid] = np.interp(index[~valid], index[valid], arr[valid])
    return arr


def _safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    result = np.zeros(len(numerator), dtype=float)
    valid = np.isfinite(denominator) & (np.abs(denominator) > 1e-9)
    result[valid] = numerator[valid] / denominator[valid]
    return result


def _normalized_coordinate_array(rows: Sequence[Mapping[str, Any]], coordinate_column: str, size_column: str) -> np.ndarray:
    coordinate = _numeric_array(rows, coordinate_column)
    size = _numeric_array(rows, size_column)
    return _safe_divide(coordinate, size)


NumericSeries = Sequence[float] | np.ndarray


def _smooth(values: NumericSeries, window: int) -> np.ndarray:
    arr = np.array(values, dtype=float)
    if len(arr) == 0:
        return arr
    width = max(1, int(window))
    if width <= 1 or len(arr) < 3:
        return arr.copy()
    if width % 2 == 0:
        width += 1
    width = min(width, len(arr) if len(arr) % 2 == 1 else len(arr) - 1)
    if width <= 1:
        return arr.copy()
    kernel = np.ones(width, dtype=float) / float(width)
    pad = width // 2
    padded = np.pad(arr, (pad, pad), mode="edge")
    return np.convolve(padded, kernel, mode="valid")


def _gradient(y: NumericSeries, x: NumericSeries) -> np.ndarray:
    y_arr = np.array(y, dtype=float)
    x_arr = np.array(x, dtype=float)
    if len(y_arr) < 2:
        return np.zeros(len(y_arr), dtype=float)
    # Collapse duplicate volume values enough to avoid divide-by-zero warnings.
    x_safe = x_arr.copy()
    for i in range(1, len(x_safe)):
        if x_safe[i] <= x_safe[i - 1]:
            x_safe[i] = x_safe[i - 1] + 1e-6
    return np.gradient(y_arr, x_safe)


def _normalize(values: NumericSeries) -> np.ndarray:
    arr = np.abs(np.array(values, dtype=float))
    if len(arr) == 0:
        return arr
    max_value = float(np.max(arr))
    if max_value <= 0:
        return np.zeros(len(arr), dtype=float)
    return arr / max_value


def _rounded(values: NumericSeries) -> list[float]:
    return [round(float(value), 6) for value in values]


def _add_series_to_curve(
    series: dict[str, list[float]],
    key: str,
    values: NumericSeries,
    volume: NumericSeries,
    *,
    smoothing_window: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    smooth = _smooth(values, smoothing_window)
    slope = _gradient(smooth, volume)
    curvature = _gradient(slope, volume)
    series[f"{key}_smooth"] = _rounded(smooth)
    series[f"{key}_slope"] = _rounded(slope)
    series[f"{key}_curvature"] = _rounded(curvature)
    return smooth, slope, curvature


def build_run_curve(run: CsvRun, *, smoothing_window: int = 5) -> RunCurve:
    """Build a smoothed, volume-indexed curve for one titration run."""

    rows = [row for row in run.rows if _to_float(row.get("injected_volume_ml")) is not None]
    if not rows:
        raise ValueError(f"{run.path}: no injected_volume_ml rows")
    rows.sort(key=lambda row: (_to_float(row.get("injected_volume_ml")) or 0.0, _to_float(row.get("time_s")) or 0.0))
    volume = _numeric_array(rows, "injected_volume_ml")
    time = _numeric_array(rows, "time_s")

    visible_color = _numeric_array(rows, "visible_color_delta")
    if not np.any(visible_color):
        h = _numeric_array(rows, "visible_H_mean")
        s = _numeric_array(rows, "visible_S_mean")
        v = _numeric_array(rows, "visible_V_mean")
        visible_color = np.sqrt((h - h[0]) ** 2 + (s - s[0]) ** 2 + (v - v[0]) ** 2)
    visible_hsv = _numeric_array(rows, "visible_HSV_delta")
    if not np.any(visible_hsv):
        visible_hsv = visible_color.copy()
    series: dict[str, list[float]] = {}
    source_values: dict[str, np.ndarray] = {
        "visible_color_delta": visible_color,
        "visible_HSV_delta": visible_hsv,
    }
    for column in VISIBLE_SERIES_COLUMNS:
        if column not in source_values:
            source_values[column] = _numeric_array(rows, column)
    for column in THERMAL_SERIES_COLUMNS:
        if column not in source_values:
            source_values[column] = _numeric_array(rows, column)
    for normalized_name, coordinate_column, size_column in THERMAL_COORDINATE_COLUMNS:
        source_values[normalized_name] = _normalized_coordinate_array(rows, coordinate_column, size_column)

    slopes: dict[str, np.ndarray] = {}
    for column, values in source_values.items():
        _smooth_values, slope, _curvature = _add_series_to_curve(
            series,
            column,
            values,
            volume,
            smoothing_window=smoothing_window,
        )
        slopes[column] = slope

    color_slope = slopes["visible_color_delta"]
    hsv_slope = slopes["visible_HSV_delta"]
    thermal_avg_slope = slopes["thermal_roi_avg"]
    thermal_p95_slope = slopes["thermal_roi_p95"]
    thermal_raw_slope = slopes["thermal_raw_roi_p50"]
    fusion_score = (
        _normalize(color_slope)
        + _normalize(hsv_slope)
        + _normalize(thermal_avg_slope)
        + _normalize(thermal_p95_slope)
        + _normalize(thermal_raw_slope)
    ) / 5.0
    series["fusion_score"] = _rounded(fusion_score)

    return RunCurve(
        run=run,
        volume_ml=_rounded(volume),
        time_s=_rounded(time),
        series=series,
    )


def _top_indices(scores: NumericSeries, max_count: int) -> list[int]:
    arr = np.array(scores, dtype=float)
    if len(arr) == 0:
        return []
    edge = max(1, int(len(arr) * 0.03))
    order = np.argsort(-arr)
    result: list[int] = []
    for index in order:
        i = int(index)
        if i < edge or i >= len(arr) - edge:
            continue
        if any(abs(i - old) <= 2 for old in result):
            continue
        result.append(i)
        if len(result) >= max_count:
            break
    return result


def extract_candidates(curve: RunCurve, *, max_candidates_per_source: int = 5) -> list[EquivalenceCandidate]:
    """Return theory-free candidate equivalence volumes from curve events."""

    source_scores = {
        "color": _normalize(curve.series.get("visible_color_delta_slope", []))
        + _normalize(curve.series.get("visible_HSV_delta_slope", [])),
        "thermal": _normalize(curve.series.get("thermal_roi_avg_slope", []))
        + _normalize(curve.series.get("thermal_roi_p95_slope", []))
        + _normalize(curve.series.get("thermal_raw_roi_p50_slope", [])),
        "fusion": np.array(curve.series.get("fusion_score", []), dtype=float),
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
    if curve.volume_ml:
        volumes = np.array(curve.volume_ml, dtype=float)
        max_volume = float(np.max(volumes))
        for fraction in (0.55, 0.60, 0.65, 0.70, 0.72, 0.75, 0.78, 0.80, 0.83, 0.85, 0.88):
            target = max_volume * fraction
            index = int(np.argmin(np.abs(volumes - target)))
            candidates.append(
                EquivalenceCandidate(
                    volume_ml=round(float(volumes[index]), 6),
                    source="fusion",
                    score=round(0.5 + fraction, 6),
                    index=index,
                )
            )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.source, candidate.volume_ml))
    return candidates


FORBIDDEN_CANDIDATE_COLUMNS = {
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
    "estimated_equivalence_volume_ml",
    "predicted_equivalence_volume_ml",
    "indicator_endpoint_offset_ml",
    "indicator_endpoint_volume_ml",
}
FORBIDDEN_CANDIDATE_PREFIXES = ("actual_", "predicted_", "estimated_", "reference_", "selected_pka_", "indicator_endpoint_")
FORBIDDEN_CANDIDATE_SUFFIXES = ("_label", "_target")
SOURCE_COLUMNS = {"source_is_color", "source_is_thermal", "source_is_fusion"}
RUN_CONTEXT_COLUMNS = {"candidate_fraction_of_run", "run_volume_max_ml", "run_duration_s"}
CANDIDATE_BASE_COLUMNS = {"candidate_score", "candidate_volume_ml"}
PROTOCOL_PROXY_COLUMNS = RUN_CONTEXT_COLUMNS | {"candidate_volume_ml"}
RELIABILITY_COLUMNS = {
    "nearest_color_candidate_distance_ml",
    "nearest_thermal_candidate_distance_ml",
    "nearest_fusion_candidate_distance_ml",
    "color_thermal_agreement_ml",
    "source_agreement_count_0p5ml",
    "source_agreement_count_1p0ml",
    "candidate_score_rank",
    "candidate_score_gap_to_best",
    "candidate_score_gap_to_next",
    "candidate_local_density_0p5ml",
    "candidate_local_density_1p0ml",
    "visible_thermal_slope_agreement",
    "visible_thermal_delta_agreement",
}
SENSOR_RELIABILITY_COLUMNS = {
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
    "visible_thermal_slope_agreement",
    "visible_thermal_delta_agreement",
}
LEGACY_COLOR_COLUMNS = {"visible_pre_post_delta", "visible_peak_slope", "visible_hsv_peak_slope"}
LEGACY_THERMAL_COLUMNS = {"thermal_pre_post_delta", "thermal_peak_slope", "thermal_p95_peak_slope", "thermal_raw_peak_slope"}
LEGACY_FUSION_COLUMNS = LEGACY_COLOR_COLUMNS | LEGACY_THERMAL_COLUMNS | {"fusion_peak_score"}
QUALITY_CONTEXT_SET = set(QUALITY_CONTEXT_COLUMNS)


def _canonical_feature_set(feature_set: str) -> str:
    aliases = {
        "color": "color_expanded",
        "thermal": "thermal_basic",
        "fusion": "current_fusion",
    }
    return aliases.get(feature_set, feature_set)


def is_forbidden_candidate_feature(column: str) -> bool:
    name = str(column)
    lower = name.lower()
    if name in FORBIDDEN_CANDIDATE_COLUMNS:
        return True
    if any(name.startswith(prefix) for prefix in FORBIDDEN_CANDIDATE_PREFIXES):
        return True
    if any(name.endswith(suffix) for suffix in FORBIDDEN_CANDIDATE_SUFFIXES):
        return True
    if "pka" in lower:
        return True
    if "equivalence" in lower:
        return True
    if "offset_from_theory" in lower or "theory_offset" in lower:
        return True
    return False


def assert_no_forbidden_candidate_features(columns: Iterable[str]) -> None:
    blocked = [column for column in columns if is_forbidden_candidate_feature(column)]
    if blocked:
        raise ValueError(f"forbidden candidate feature(s): {', '.join(blocked)}")


def _series_value(curve: RunCurve, key: str, index: int) -> float:
    values = curve.series.get(key, [])
    if not values:
        return 0.0
    i = max(0, min(index, len(values) - 1))
    return float(values[i])


def _window_mean(values: Sequence[float], start: int, end: int) -> float:
    if not values:
        return 0.0
    lo = max(0, start)
    hi = min(len(values), end)
    if hi <= lo:
        return float(values[max(0, min(len(values) - 1, lo))])
    return float(sum(values[lo:hi]) / (hi - lo))


def _window_std(values: Sequence[float], start: int, end: int) -> float:
    if not values:
        return 0.0
    lo = max(0, start)
    hi = min(len(values), end)
    if hi <= lo:
        return 0.0
    window = [float(value) for value in values[lo:hi]]
    if len(window) < 2:
        return 0.0
    return float(statistics.pstdev(window))


def _add_candidate_series_features(
    row: dict[str, Any],
    curve: RunCurve,
    key: str,
    index: int,
    *,
    window_points: int,
) -> None:
    values = curve.series.get(f"{key}_smooth", [])
    if not values:
        return
    pre = _window_mean(values, index - window_points, index)
    post = _window_mean(values, index + 1, index + 1 + window_points)
    plateau_early = _window_mean(values, index + 1, index + 1 + window_points)
    plateau_late = _window_mean(values, index + 1 + window_points, index + 1 + 2 * window_points)
    row[f"{key}_at_candidate"] = round(_series_value(curve, f"{key}_smooth", index), 6)
    row[f"{key}_pre_post_delta"] = round(post - pre, 6)
    row[f"{key}_peak_slope"] = round(abs(_series_value(curve, f"{key}_slope", index)), 6)
    row[f"{key}_curvature"] = round(abs(_series_value(curve, f"{key}_curvature", index)), 6)
    row[f"{key}_local_std"] = round(_window_std(values, index - window_points, index + 1 + window_points), 6)
    row[f"{key}_plateau_delta"] = round(plateau_late - plateau_early, 6)


def _first_numeric_from_run(run: CsvRun, column: str) -> float:
    for row in run.rows:
        value = _to_float(row.get(column))
        if value is not None:
            return float(value)
    return 0.0


def _is_protocol_fraction_candidate(candidate: EquivalenceCandidate) -> bool:
    return candidate.source == "fusion" and float(candidate.score) > 1.0


def _is_protocol_fraction_candidate_row(row: Mapping[str, Any]) -> bool:
    return row.get("candidate_source") == "fusion" and (_to_float(row.get("candidate_score")) or 0.0) > 1.0


def _nearest_distance(volume: float, candidates: Sequence[EquivalenceCandidate], source: str) -> float:
    source_volumes = [float(candidate.volume_ml) for candidate in candidates if candidate.source == source]
    if not source_volumes:
        return 0.0
    return min(abs(float(volume) - other) for other in source_volumes)


def _min_pairwise_source_distance(candidates: Sequence[EquivalenceCandidate], left: str, right: str) -> float:
    left_volumes = [float(candidate.volume_ml) for candidate in candidates if candidate.source == left]
    right_volumes = [float(candidate.volume_ml) for candidate in candidates if candidate.source == right]
    if not left_volumes or not right_volumes:
        return 0.0
    return min(abs(a - b) for a in left_volumes for b in right_volumes)


def _source_agreement_count(volume: float, candidates: Sequence[EquivalenceCandidate], window_ml: float) -> int:
    return len(
        {
            candidate.source
            for candidate in candidates
            if abs(float(candidate.volume_ml) - float(volume)) <= abs(float(window_ml))
        }
    )


def _candidate_local_density(volume: float, candidates: Sequence[EquivalenceCandidate], window_ml: float) -> int:
    return sum(1 for candidate in candidates if abs(float(candidate.volume_ml) - float(volume)) <= abs(float(window_ml)))


def _add_reliability_feature_group(
    row: dict[str, Any],
    *,
    volume: float,
    score: float,
    candidates: Sequence[EquivalenceCandidate],
    prefix: str = "",
) -> None:
    color_thermal_agreement = _min_pairwise_source_distance(candidates, "color", "thermal")
    sorted_scores = sorted((float(candidate.score) for candidate in candidates), reverse=True)
    best_score = sorted_scores[0] if sorted_scores else 0.0
    lower_scores = [value for value in sorted_scores if value < score]
    row[f"{prefix}nearest_color_candidate_distance_ml"] = round(_nearest_distance(volume, candidates, "color"), 6)
    row[f"{prefix}nearest_thermal_candidate_distance_ml"] = round(_nearest_distance(volume, candidates, "thermal"), 6)
    row[f"{prefix}nearest_fusion_candidate_distance_ml"] = round(_nearest_distance(volume, candidates, "fusion"), 6)
    row[f"{prefix}color_thermal_agreement_ml"] = round(color_thermal_agreement, 6)
    row[f"{prefix}source_agreement_count_0p5ml"] = float(_source_agreement_count(volume, candidates, 0.5))
    row[f"{prefix}source_agreement_count_1p0ml"] = float(_source_agreement_count(volume, candidates, 1.0))
    row[f"{prefix}candidate_score_rank"] = float(1 + sum(1 for value in sorted_scores if value > score))
    row[f"{prefix}candidate_score_gap_to_best"] = round(best_score - score, 6)
    row[f"{prefix}candidate_score_gap_to_next"] = round(score - lower_scores[0], 6) if lower_scores else 0.0
    row[f"{prefix}candidate_local_density_0p5ml"] = float(_candidate_local_density(volume, candidates, 0.5))
    row[f"{prefix}candidate_local_density_1p0ml"] = float(_candidate_local_density(volume, candidates, 1.0))


def _add_visible_thermal_agreement_features(row: dict[str, Any]) -> None:
    row["visible_thermal_slope_agreement"] = round(
        min(
            abs(_to_float(row.get("visible_peak_slope")) or 0.0),
            abs(_to_float(row.get("thermal_peak_slope")) or 0.0),
        ),
        6,
    )
    row["visible_thermal_delta_agreement"] = round(
        min(
            abs(_to_float(row.get("visible_pre_post_delta")) or 0.0),
            abs(_to_float(row.get("thermal_pre_post_delta")) or 0.0),
        ),
        6,
    )


def _add_candidate_reliability_features(rows: list[dict[str, Any]], candidates: Sequence[EquivalenceCandidate]) -> None:
    if not rows:
        return
    sensor_candidates = [candidate for candidate in candidates if not _is_protocol_fraction_candidate(candidate)]
    for row in rows:
        volume = _to_float(row.get("candidate_volume_ml")) or 0.0
        score = _to_float(row.get("candidate_score")) or 0.0
        _add_reliability_feature_group(row, volume=volume, score=score, candidates=candidates)
        _add_reliability_feature_group(row, volume=volume, score=score, candidates=sensor_candidates, prefix="sensor_")
        _add_visible_thermal_agreement_features(row)


def build_candidate_rows(
    run: CsvRun,
    curve: RunCurve,
    candidates: Sequence[EquivalenceCandidate],
    *,
    good_window_ml: float = 0.5,
    window_points: int = 4,
) -> list[dict[str, Any]]:
    """Build candidate-level training/evaluation rows.

    Target columns are included for training/evaluation but excluded by
    ``select_candidate_feature_columns``.
    """

    rows: list[dict[str, Any]] = []
    run_volume_max = max(curve.volume_ml) if curve.volume_ml else 0.0
    run_duration = max(curve.time_s) - min(curve.time_s) if curve.time_s else 0.0
    for candidate in candidates:
        i = int(candidate.index)
        error = float(candidate.volume_ml) - float(run.theoretical_equivalence_volume_ml)
        row = {
            "run_path": str(run.path),
            "titration_type": run.titration_type,
            "held_out_concentration_m": run.concentration_m,
            "candidate_volume_ml": round(float(candidate.volume_ml), 6),
            "candidate_fraction_of_run": round(float(candidate.volume_ml) / run_volume_max, 6) if run_volume_max else 0.0,
            "run_volume_max_ml": round(float(run_volume_max), 6),
            "run_duration_s": round(float(run_duration), 6),
            "candidate_source": candidate.source,
            "candidate_score": round(float(candidate.score), 6),
            "candidate_error_ml": round(error, 6),
            "candidate_abs_error_ml": round(abs(error), 6),
            "is_good_candidate": 1.0 if abs(error) <= abs(float(good_window_ml)) else 0.0,
            "actual_equivalence_volume_ml": round(float(run.theoretical_equivalence_volume_ml), 6),
            "fusion_peak_score": round(abs(_series_value(curve, "fusion_score", i)), 6),
            "source_is_color": 1.0 if candidate.source == "color" else 0.0,
            "source_is_thermal": 1.0 if candidate.source == "thermal" else 0.0,
            "source_is_fusion": 1.0 if candidate.source == "fusion" else 0.0,
        }
        for column in QUALITY_CONTEXT_COLUMNS:
            row[column] = round(_first_numeric_from_run(run, column), 6)
        for key in VISIBLE_SERIES_COLUMNS:
            _add_candidate_series_features(row, curve, key, i, window_points=window_points)
        for key in THERMAL_SERIES_COLUMNS:
            _add_candidate_series_features(row, curve, key, i, window_points=window_points)
        for normalized_name, _coordinate_column, _size_column in THERMAL_COORDINATE_COLUMNS:
            _add_candidate_series_features(row, curve, normalized_name, i, window_points=window_points)

        # Backward-compatible compact features used by the original curve model.
        row["visible_pre_post_delta"] = row.get("visible_color_delta_pre_post_delta", 0.0)
        row["visible_peak_slope"] = row.get("visible_color_delta_peak_slope", 0.0)
        row["visible_hsv_peak_slope"] = row.get("visible_HSV_delta_peak_slope", 0.0)
        row["thermal_pre_post_delta"] = row.get("thermal_roi_avg_pre_post_delta", 0.0)
        row["thermal_peak_slope"] = row.get("thermal_roi_avg_peak_slope", 0.0)
        row["thermal_p95_peak_slope"] = row.get("thermal_roi_p95_peak_slope", 0.0)
        row["thermal_raw_peak_slope"] = row.get("thermal_raw_roi_p50_peak_slope", 0.0)
        rows.append(row)
    _add_candidate_reliability_features(rows, candidates)
    return rows


def select_candidate_feature_columns(columns: Iterable[str], *, feature_set: str = "fusion") -> list[str]:
    feature_set = _canonical_feature_set(feature_set)
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"unknown feature_set: {feature_set}")
    selected: list[str] = []
    for column in sorted(set(columns)):
        if is_forbidden_candidate_feature(column):
            continue
        if column in {"run_path", "titration_type", "candidate_source", "held_out_concentration_m"}:
            continue
        if feature_set == "current_fusion" and not (
            column in LEGACY_FUSION_COLUMNS
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        if feature_set == "compact_plus" and not (
            column in LEGACY_FUSION_COLUMNS
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
            or column in RELIABILITY_COLUMNS
        ):
            continue
        if feature_set == "compact_plus_no_progress" and not (
            column in LEGACY_FUSION_COLUMNS
            or column in SOURCE_COLUMNS
            or column == "candidate_score"
            or column in SENSOR_RELIABILITY_COLUMNS
        ):
            continue
        if feature_set == "thermal_basic" and not (
            column in LEGACY_THERMAL_COLUMNS
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        if feature_set == "color_expanded" and not (
            column.startswith("visible_")
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        if feature_set == "thermal_expanded" and not (
            column.startswith("thermal_")
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        if feature_set == "fusion_expanded" and not (
            column.startswith("visible_")
            or column.startswith("thermal_")
            or column.startswith("fusion_")
            or column in SOURCE_COLUMNS
            or column in RUN_CONTEXT_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        if feature_set == "fusion_no_progress" and not (
            column.startswith("visible_")
            or column.startswith("thermal_")
            or column.startswith("fusion_")
            or column in SOURCE_COLUMNS
            or column == "candidate_score"
        ):
            continue
        if feature_set == "fusion_no_progress" and column in PROTOCOL_PROXY_COLUMNS:
            continue
        if feature_set == "run_quality_context" and not (
            column in QUALITY_CONTEXT_SET
            or column in SOURCE_COLUMNS
            or column in CANDIDATE_BASE_COLUMNS
        ):
            continue
        selected.append(column)
    assert_no_forbidden_candidate_features(selected)
    return selected


def build_typewise_run_folds(runs: Sequence[CsvRun]) -> list[TypewiseRunFold]:
    """Return leave-one-concentration-out folds inside each titration type."""

    by_type: dict[str, list[CsvRun]] = defaultdict(list)
    for run in runs:
        by_type[run.titration_type].append(run)
    folds: list[TypewiseRunFold] = []
    for titration_type in sorted(by_type):
        type_runs = by_type[titration_type]
        concentrations = sorted({round(float(run.concentration_m), 8) for run in type_runs})
        for concentration in concentrations:
            train = [run for run in type_runs if round(float(run.concentration_m), 8) != concentration]
            test = [run for run in type_runs if round(float(run.concentration_m), 8) == concentration]
            if train and test:
                folds.append(TypewiseRunFold(titration_type, float(concentration), train, test))
    return folds


def run_level_metrics(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute run-level equivalence-volume error metrics."""

    def _rate_within(values: Sequence[float], threshold: float) -> float:
        """Return inclusive hit rate with a small tolerance for float noise."""

        if not values:
            return 0.0
        epsilon = 1e-9
        return round(sum(value <= threshold + epsilon for value in values) / len(values), 6)

    errors: list[float] = []
    percent_errors: list[float] = []
    actual_volumes: list[float] = []
    predicted_volumes: list[float] = []
    for row in predictions:
        predicted = _to_float(row.get("predicted_equivalence_volume_ml"))
        actual = _to_float(row.get("actual_equivalence_volume_ml"))
        if predicted is None or actual is None:
            continue
        predicted_f = float(predicted)
        actual_f = float(actual)
        error = predicted_f - actual_f
        errors.append(error)
        predicted_volumes.append(predicted_f)
        actual_volumes.append(actual_f)
        if abs(actual_f) > 1e-12:
            percent_errors.append(100.0 * error / actual_f)
    abs_errors = [abs(error) for error in errors]
    abs_percent_errors = [abs(error) for error in percent_errors]
    n = len(errors)
    if not errors:
        return {
            "prediction_unit": PREDICTION_UNIT,
            "run_count": 0,
            "mean_actual_equivalence_volume_ml": 0.0,
            "mean_predicted_equivalence_volume_ml": 0.0,
            "mae_ml": 0.0,
            "median_abs_error_ml": 0.0,
            "bias_ml": 0.0,
            "rmse_ml": 0.0,
            "mae_percent_of_equivalence": 0.0,
            "median_abs_percent_error": 0.0,
            "bias_percent_of_equivalence": 0.0,
            "rmse_percent_of_equivalence": 0.0,
            "concentration_mae_percent": 0.0,
            "within_0.1ml_rate": 0.0,
            "within_0.2ml_rate": 0.0,
            "within_0.5ml_rate": 0.0,
            "within_1.0ml_rate": 0.0,
            "within_1pct_rate": 0.0,
            "within_2pct_rate": 0.0,
            "within_5pct_rate": 0.0,
        }
    percent_n = len(percent_errors)
    percent_metrics = {
        "mae_percent_of_equivalence": round(float(statistics.mean(abs_percent_errors)), 6) if abs_percent_errors else 0.0,
        "median_abs_percent_error": round(float(statistics.median(abs_percent_errors)), 6) if abs_percent_errors else 0.0,
        "bias_percent_of_equivalence": round(float(statistics.mean(percent_errors)), 6) if percent_errors else 0.0,
        "rmse_percent_of_equivalence": (
            round(float(math.sqrt(statistics.mean(error * error for error in percent_errors))), 6) if percent_errors else 0.0
        ),
        # For fixed titration stoichiometry/sample volume, concentration inferred
        # from the predicted equivalence volume has the same relative error as
        # predicted equivalence volume itself. This is a legitimate collected
        # signal comparison, not a model input leak.
        "concentration_mae_percent": round(float(statistics.mean(abs_percent_errors)), 6) if abs_percent_errors else 0.0,
        "within_1pct_rate": _rate_within(abs_percent_errors, 1.0),
        "within_2pct_rate": _rate_within(abs_percent_errors, 2.0),
        "within_5pct_rate": _rate_within(abs_percent_errors, 5.0),
    }
    return {
        "prediction_unit": PREDICTION_UNIT,
        "run_count": n,
        "mean_actual_equivalence_volume_ml": round(float(statistics.mean(actual_volumes)), 6),
        "mean_predicted_equivalence_volume_ml": round(float(statistics.mean(predicted_volumes)), 6),
        "mae_ml": round(float(statistics.mean(abs_errors)), 6),
        "median_abs_error_ml": round(float(statistics.median(abs_errors)), 6),
        "bias_ml": round(float(statistics.mean(errors)), 6),
        "rmse_ml": round(float(math.sqrt(statistics.mean(error * error for error in errors))), 6),
        **percent_metrics,
        "within_0.1ml_rate": _rate_within(abs_errors, 0.1),
        "within_0.2ml_rate": _rate_within(abs_errors, 0.2),
        "within_0.5ml_rate": _rate_within(abs_errors, 0.5),
        "within_1.0ml_rate": _rate_within(abs_errors, 1.0),
    }


def _candidate_rows_for_runs(
    runs: Sequence[CsvRun],
    *,
    smoothing_window: int = 5,
    max_candidates_per_source: int = 5,
    good_window_ml: float = 0.5,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in runs:
        curve = build_run_curve(run, smoothing_window=smoothing_window)
        candidates = extract_candidates(curve, max_candidates_per_source=max_candidates_per_source)
        rows.extend(build_candidate_rows(run, curve, candidates, good_window_ml=good_window_ml))
    return rows


def _matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> list[list[float]]:
    return [[_to_float(row.get(column)) or 0.0 for column in columns] for row in rows]


def _rows_by_run(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("run_path") or "")].append(row)
    return grouped


def _heuristic_pick(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    return max(rows, key=lambda row: (_to_float(row.get("candidate_score")) or 0.0, -(_to_float(row.get("candidate_volume_ml")) or 0.0)))


def _predict_candidate_errors(
    train_rows: Sequence[Mapping[str, Any]],
    test_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    *,
    quick: bool,
) -> tuple[list[float] | None, list[float] | None, dict[str, Any]]:
    if quick:
        return None, None, {"model": "max_candidate_score_baseline", "candidate_target": "candidate_abs_error_ml"}
    try:
        from sklearn.ensemble import ExtraTreesRegressor, RandomForestRegressor  # type: ignore[reportMissingImports]
        from sklearn.base import clone  # type: ignore[reportMissingImports]
        from sklearn.linear_model import Ridge  # type: ignore[reportMissingImports]
        from sklearn.neighbors import KNeighborsRegressor  # type: ignore[reportMissingImports]
        from sklearn.pipeline import make_pipeline  # type: ignore[reportMissingImports]
        from sklearn.preprocessing import StandardScaler  # type: ignore[reportMissingImports]
    except Exception as exc:
        return None, None, {"model": "max_candidate_score_baseline", "candidate_target": "candidate_abs_error_ml", "warning": repr(exc)}

    x_train = np.array(_matrix(train_rows, feature_columns), dtype=float)
    y_abs = np.array([_to_float(row.get("candidate_abs_error_ml")) or 0.0 for row in train_rows], dtype=float)
    y_signed = np.array([_to_float(row.get("candidate_error_ml")) or 0.0 for row in train_rows], dtype=float)
    x_test = np.array(_matrix(test_rows, feature_columns), dtype=float)
    candidates = [
        ("ridge", make_pipeline(StandardScaler(), Ridge())),
        ("knn_regressor", KNeighborsRegressor(n_neighbors=max(1, min(3, len(train_rows))))),
        ("random_forest_regressor", RandomForestRegressor(n_estimators=50, random_state=42)),
        ("extra_trees_regressor", ExtraTreesRegressor(n_estimators=50, random_state=42)),
    ]
    best_abs_predictions: list[float] | None = None
    best_signed_predictions: list[float] | None = None
    best_meta: dict[str, Any] = {"model": "max_candidate_score_baseline", "candidate_target": "candidate_abs_error_ml"}
    best_mae: float | None = None
    model_failures: list[dict[str, str]] = []
    for name, model in candidates:
        try:
            abs_model = clone(model)
            signed_model = clone(model)
            abs_model.fit(x_train, y_abs)
            signed_model.fit(x_train, y_signed)
            train_abs_pred = np.array(abs_model.predict(x_train), dtype=float)
            train_signed_pred = np.array(signed_model.predict(x_train), dtype=float)
            candidate_volumes = np.array([_to_float(row.get("candidate_volume_ml")) or 0.0 for row in train_rows], dtype=float)
            actual_volumes = np.array([_to_float(row.get("actual_equivalence_volume_ml")) or 0.0 for row in train_rows], dtype=float)
            corrected_train = candidate_volumes - train_signed_pred
            # Optimize for the final task, not just candidate absolute-error fit.
            mae = float(np.mean(np.abs(corrected_train - actual_volumes))) + 0.05 * float(np.mean(np.abs(train_abs_pred - y_abs)))
            test_abs_pred = [float(value) for value in abs_model.predict(x_test)]
            test_signed_pred = [float(value) for value in signed_model.predict(x_test)]
        except Exception as exc:
            model_failures.append({"model": name, "error": repr(exc)})
            continue
        if best_mae is None or mae < best_mae:
            best_mae = mae
            best_abs_predictions = test_abs_pred
            best_signed_predictions = test_signed_pred
            best_meta = {
                "model": name,
                "candidate_target": "candidate_abs_error_ml + candidate_error_ml",
                "train_corrected_equivalence_mae_ml": round(mae, 6),
                "top_feature_importances": _feature_importance(abs_model, feature_columns),
            }
    if model_failures:
        best_meta["model_failures"] = model_failures
    return best_abs_predictions, best_signed_predictions, best_meta


def _feature_importance(model: Any, feature_columns: Sequence[str], *, limit: int = 12) -> list[dict[str, Any]]:
    estimator = model
    if hasattr(model, "steps") and getattr(model, "steps"):
        estimator = model.steps[-1][1]
    values = getattr(estimator, "feature_importances_", None)
    if values is None:
        coef = getattr(estimator, "coef_", None)
        if coef is not None:
            values = np.abs(np.array(coef, dtype=float)).ravel()
    if values is None:
        return []
    arr = np.array(values, dtype=float).ravel()
    if len(arr) != len(feature_columns):
        return []
    order = np.argsort(-np.abs(arr))[:limit]
    return [
        {"feature": str(feature_columns[int(index)]), "importance": round(float(arr[int(index)]), 6)}
        for index in order
        if float(abs(arr[int(index)])) > 0
    ]


def predict_fold(
    fold: TypewiseRunFold,
    *,
    feature_set: str = "fusion",
    quick: bool = False,
) -> dict[str, Any]:
    """Predict one equivalence volume for each held-out run in a fold."""

    train_candidates = _filter_candidate_rows_for_feature_set(_candidate_rows_for_runs(fold.train_runs), feature_set)
    test_candidates = _filter_candidate_rows_for_feature_set(_candidate_rows_for_runs(fold.test_runs), feature_set)
    if not train_candidates or not test_candidates:
        return {
            "titration_type": fold.titration_type,
            "held_out_concentration_m": fold.held_out_concentration_m,
            "feature_set": feature_set,
            "prediction_unit": PREDICTION_UNIT,
            "candidate_count": len(test_candidates),
            "feature_columns": [],
            "model": {
                "model": "unevaluable_no_candidate_rows",
                "warning": "source-specific candidate extraction produced no train/test rows; no fallback to unrelated modality candidates",
                "feature_count": 0,
                "progress_feature_count": 0,
            },
            "predictions": [],
            "metrics": run_level_metrics([]),
            "train_candidate_count": len(train_candidates),
            "test_candidate_rows": test_candidates,
        }
    feature_columns = select_candidate_feature_columns(
        set().union(*(row.keys() for row in train_candidates + test_candidates)),
        feature_set=feature_set,
    )
    assert_no_forbidden_candidate_features(feature_columns)
    predicted_abs_errors, predicted_signed_errors, model_meta = _predict_candidate_errors(
        train_candidates, test_candidates, feature_columns, quick=quick
    )
    model_meta = dict(model_meta)
    model_meta["feature_count"] = len(feature_columns)
    model_meta["progress_feature_count"] = sum(1 for column in feature_columns if column in PROTOCOL_PROXY_COLUMNS)
    test_with_predictions: list[dict[str, Any]] = []
    for index, row in enumerate(test_candidates):
        out = dict(row)
        if predicted_abs_errors is not None:
            out["predicted_candidate_abs_error_ml"] = round(float(predicted_abs_errors[index]), 6)
        if predicted_signed_errors is not None:
            out["predicted_candidate_error_ml"] = round(float(predicted_signed_errors[index]), 6)
        test_with_predictions.append(out)

    predictions: list[dict[str, Any]] = []
    for run_path, rows in _rows_by_run(test_with_predictions).items():
        if predicted_abs_errors is None:
            chosen = _heuristic_pick(rows)
        else:
            chosen = min(
                rows,
                key=lambda row: (
                    _to_float(row.get("predicted_candidate_abs_error_ml")) or float("inf"),
                    -(_to_float(row.get("candidate_score")) or 0.0),
                ),
            )
        actual = _to_float(chosen.get("actual_equivalence_volume_ml")) or 0.0
        candidate_volume = _to_float(chosen.get("candidate_volume_ml")) or 0.0
        predicted_error = _to_float(chosen.get("predicted_candidate_error_ml"))
        predicted = candidate_volume if predicted_error is None else candidate_volume - predicted_error
        signed_error = predicted - actual
        signed_error_percent = 100.0 * signed_error / actual if abs(actual) > 1e-12 else 0.0
        predicted_concentration = (fold.held_out_concentration_m * predicted / actual) if abs(actual) > 1e-12 else 0.0
        predictions.append(
            {
                "run_path": run_path,
                "titration_type": fold.titration_type,
                "held_out_concentration_m": fold.held_out_concentration_m,
                "feature_set": feature_set,
                "prediction_unit": PREDICTION_UNIT,
                "predicted_equivalence_volume_ml": round(predicted, 6),
                "sample_concentration_from_predicted_equivalence_M": round(predicted_concentration, 8),
                "actual_equivalence_volume_ml": round(actual, 6),
                "absolute_error_ml": round(abs(signed_error), 6),
                "signed_error_ml": round(signed_error, 6),
                "absolute_error_percent_of_equivalence": round(abs(signed_error_percent), 6),
                "signed_error_percent_of_equivalence": round(signed_error_percent, 6),
                "equivalence_derived_concentration_error_percent": round(signed_error_percent, 6),
                "predicted_sample_concentration_error_percent": round(signed_error_percent, 6),
                "chosen_candidate_volume_ml": round(candidate_volume, 6),
                "chosen_candidate_source": chosen.get("candidate_source", ""),
                "chosen_candidate_score": chosen.get("candidate_score", 0.0),
                "predicted_candidate_error_ml": "" if predicted_error is None else round(float(predicted_error), 6),
            }
        )
    return {
        "titration_type": fold.titration_type,
        "held_out_concentration_m": fold.held_out_concentration_m,
        "feature_set": feature_set,
        "prediction_unit": PREDICTION_UNIT,
        "candidate_count": len(test_candidates),
        "feature_columns": feature_columns,
        "model": model_meta,
        "predictions": predictions,
        "metrics": run_level_metrics(predictions),
        "train_candidate_count": len(train_candidates),
        "test_candidate_rows": test_candidates,
    }


def _filter_candidate_rows_for_feature_set(rows: Sequence[Mapping[str, Any]], feature_set: str) -> list[dict[str, Any]]:
    feature_set = _canonical_feature_set(feature_set)
    if feature_set == "color_expanded":
        filtered = [dict(row) for row in rows if row.get("candidate_source") == "color"]
    elif feature_set in {"thermal_basic", "thermal_expanded"}:
        filtered = [dict(row) for row in rows if row.get("candidate_source") == "thermal"]
    elif feature_set in {"fusion_no_progress", "compact_plus_no_progress"}:
        filtered = [
            dict(row)
            for row in rows
            if not _is_protocol_fraction_candidate_row(row)
        ]
    else:
        filtered = [dict(row) for row in rows]
    return filtered


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _feature_set_metrics(folds: Sequence[Mapping[str, Any]], feature_set: str) -> dict[str, Any]:
    predictions = [prediction for fold in folds if fold.get("feature_set") == feature_set for prediction in fold.get("predictions", [])]
    metrics = run_level_metrics(predictions)
    metrics["fold_count"] = sum(1 for fold in folds if fold.get("feature_set") == feature_set)
    return metrics


def _best_feature_set(feature_metrics: Mapping[str, Mapping[str, Any]]) -> str:
    return min(
        FEATURE_SETS,
        key=lambda name: (
            float("inf")
            if int(_to_float(feature_metrics.get(name, {}).get("run_count")) or 0) <= 0
            else float(feature_metrics.get(name, {}).get("mae_ml", float("inf")))
        ),
    )


PRIMARY_COMPARISON_SETS = (
    "current_fusion",
    "compact_plus",
    "compact_plus_no_progress",
    "fusion_expanded",
    "fusion_no_progress",
)


def _primary_comparison(feature_metrics: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {name: dict(feature_metrics.get(name, {})) for name in PRIMARY_COMPARISON_SETS}


def _comparison_rows(summary: Mapping[str, Any], *, primary_only: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allowed = set(PRIMARY_COMPARISON_SETS) if primary_only else None
    for titration_type, payload in summary.get("types", {}).items():
        for feature_set, metrics in payload.get("feature_set_metrics", {}).items():
            if allowed is not None and feature_set not in allowed:
                continue
            rows.append(
                {
                    "titration_type": titration_type,
                    "feature_set": feature_set,
                    "comparison_role": "primary" if feature_set in PRIMARY_COMPARISON_SETS else "exploratory",
                    **{k: v for k, v in metrics.items() if k != "prediction_unit"},
                }
            )
    return rows


def _typewise_run_metric_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return one selected-model metric row per titration type."""

    rows: list[dict[str, Any]] = []
    for titration_type, payload in summary.get("types", {}).items():
        selected = payload.get("selected_model", {})
        metrics = payload.get("run_level_metrics", {})
        rows.append(
            {
                "titration_type": titration_type,
                "selected_feature_set": selected.get("feature_set", ""),
                "run_count": metrics.get("run_count", 0),
                "mean_actual_equivalence_volume_ml": metrics.get("mean_actual_equivalence_volume_ml", 0),
                "mean_predicted_equivalence_volume_ml": metrics.get("mean_predicted_equivalence_volume_ml", 0),
                "mae_ml": metrics.get("mae_ml", 0),
                "median_abs_error_ml": metrics.get("median_abs_error_ml", 0),
                "bias_ml": metrics.get("bias_ml", 0),
                "rmse_ml": metrics.get("rmse_ml", 0),
                "mae_percent_of_equivalence": metrics.get("mae_percent_of_equivalence", 0),
                "median_abs_percent_error": metrics.get("median_abs_percent_error", 0),
                "bias_percent_of_equivalence": metrics.get("bias_percent_of_equivalence", 0),
                "rmse_percent_of_equivalence": metrics.get("rmse_percent_of_equivalence", 0),
                "concentration_mae_percent": metrics.get("concentration_mae_percent", 0),
                "within_1pct_rate": metrics.get("within_1pct_rate", 0),
                "within_2pct_rate": metrics.get("within_2pct_rate", 0),
                "within_5pct_rate": metrics.get("within_5pct_rate", 0),
                "within_0.5ml_rate": metrics.get("within_0.5ml_rate", 0),
                "within_1.0ml_rate": metrics.get("within_1.0ml_rate", 0),
            }
        )
    return rows


def _feature_importance_rows(summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for titration_type, payload in summary.get("types", {}).items():
        for fold in payload.get("folds", []):
            for rank, item in enumerate(fold.get("model", {}).get("top_feature_importances", []), start=1):
                rows.append(
                    {
                        "titration_type": titration_type,
                        "fold_id": fold.get("fold_id", ""),
                        "feature_set": fold.get("feature_set", ""),
                        "rank": rank,
                        "feature": item.get("feature", ""),
                        "importance": item.get("importance", 0),
                    }
                )
    return rows


def _candidate_feature_rows(
    candidate_rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
) -> list[dict[str, Any]]:
    """Project diagnostic candidate rows to the exact model-input feature table."""

    output: list[dict[str, Any]] = []
    for row in candidate_rows:
        out: dict[str, Any] = {
            "run_path": row.get("run_path", ""),
            "candidate_source": row.get("candidate_source", ""),
        }
        for column in feature_columns:
            out[column] = row.get(column, "")
        output.append(out)
    return output


def _progress_warning(titration_type: str, feature_metrics: Mapping[str, Mapping[str, Any]]) -> str | None:
    expanded = _to_float(feature_metrics.get("fusion_expanded", {}).get("mae_ml"))
    no_progress = _to_float(feature_metrics.get("fusion_no_progress", {}).get("mae_ml"))
    if expanded is None or no_progress is None:
        return None
    if no_progress - expanded > 0.5:
        return (
            f"{titration_type}: fusion_expanded가 fusion_no_progress보다 {round(no_progress - expanded, 6)} mL 낮은 MAE를 보여 "
            "주입량/진행 정보 또는 고정비율 후보가 성능에 기여하는지 점검해야 함"
        )
    return None


def _compact_plus_progress_warning(titration_type: str, feature_metrics: Mapping[str, Mapping[str, Any]]) -> str | None:
    compact = _to_float(feature_metrics.get("compact_plus", {}).get("mae_ml"))
    no_progress = _to_float(feature_metrics.get("compact_plus_no_progress", {}).get("mae_ml"))
    if compact is None or no_progress is None:
        return None
    if no_progress - compact > 0.5:
        return (
            f"{titration_type}: compact_plus가 compact_plus_no_progress보다 {round(no_progress - compact, 6)} mL 낮은 MAE를 보여 "
            "현재 데이터에서는 sensor-only 후보 일치도만으로 부족하며, 장치가 실제로 수집 가능한 주입량/진행 정보가 최종 예측에 중요함"
        )
    return None


def _expanded_overfit_warning(titration_type: str, feature_metrics: Mapping[str, Mapping[str, Any]]) -> str | None:
    current = _to_float(feature_metrics.get("current_fusion", {}).get("mae_ml"))
    expanded = _to_float(feature_metrics.get("fusion_expanded", {}).get("mae_ml"))
    if current is None or expanded is None:
        return None
    if expanded - current > 0.5:
        return (
            f"{titration_type}: fusion_expanded가 current_fusion보다 {round(expanded - current, 6)} mL 높은 MAE를 보여 "
            "현재 12-run 데이터에서는 확장 feature 과적합/잡음 증폭 가능성이 있음"
        )
    return None


def evaluate_runs(
    runs: Sequence[CsvRun],
    *,
    output_dir: str | Path | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    """Evaluate curve-equivalence prediction for already-loaded runs."""

    folds = build_typewise_run_folds(runs)
    summary: dict[str, Any] = {
        "schema_version": "curve_equivalence_ml_v1",
        "prediction_unit": PREDICTION_UNIT,
        "feature_sets": list(FEATURE_SETS),
        "versions": {
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
        },
        "types": {},
        "warnings": [],
    }
    output = Path(output_dir) if output_dir is not None else None
    all_summary_rows: list[dict[str, Any]] = []
    for fold in folds:
        type_payload = summary["types"].setdefault(
            fold.titration_type,
            {"folds": [], "feature_set_metrics": {}, "run_level_metrics": {}, "selected_model": {}},
        )
        for feature_set in FEATURE_SETS:
            result = predict_fold(fold, feature_set=feature_set, quick=quick)
            fold_id = f"holdout-{fold.held_out_concentration_m:g}M-{feature_set}"
            prediction_rows = result["predictions"]
            candidate_rows = result["test_candidate_rows"]
            fold_payload = {
                "fold_id": fold_id,
                "titration_type": fold.titration_type,
                "held_out_concentration_m": fold.held_out_concentration_m,
                "feature_set": feature_set,
                "prediction_unit": PREDICTION_UNIT,
                "candidate_count": result["candidate_count"],
                "feature_columns": result["feature_columns"],
                "model": result["model"],
                "metrics": result["metrics"],
                "predictions": prediction_rows,
                "train_run_paths": [str(run.path) for run in fold.train_runs],
                "test_run_paths": [str(run.path) for run in fold.test_runs],
            }
            type_payload["folds"].append(fold_payload)
            all_summary_rows.append(
                {
                    "titration_type": fold.titration_type,
                    "fold_id": fold_id,
                    "held_out_concentration_m": fold.held_out_concentration_m,
                    "feature_set": feature_set,
                    **{k: v for k, v in result["metrics"].items() if k != "prediction_unit"},
                    "candidate_count": result["candidate_count"],
                    "feature_count": len(result["feature_columns"]),
                    "progress_feature_count": result["model"].get("progress_feature_count", 0),
                    "model": result["model"].get("model"),
                }
            )
            if output is not None:
                _write_csv(output / "predictions" / fold.titration_type / f"{fold_id}.csv", prediction_rows)
                _write_csv(output / "candidate_tables" / fold.titration_type / f"{fold_id}.csv", candidate_rows)
                _write_csv(
                    output / "candidate_feature_tables" / fold.titration_type / f"{fold_id}.csv",
                    _candidate_feature_rows(candidate_rows, result["feature_columns"]),
                )

    all_predictions: list[dict[str, Any]] = []
    for titration_type, payload in summary["types"].items():
        feature_metrics = {feature_set: _feature_set_metrics(payload["folds"], feature_set) for feature_set in FEATURE_SETS}
        best_feature_set = _best_feature_set(feature_metrics)
        payload["feature_set_metrics"] = feature_metrics
        payload["primary_comparison"] = _primary_comparison(feature_metrics)
        payload["run_level_metrics"] = feature_metrics[best_feature_set]
        payload["selected_model"] = {
            "feature_set": best_feature_set,
            "selection_metric": "lowest_run_level_mae_ml",
            "selection_scope": "exploratory_best_across_feature_sets",
            "claim_warning": "post-hoc feature-set selection; use primary_comparison for headline comparison",
            "metrics": feature_metrics[best_feature_set],
            "prediction_unit": PREDICTION_UNIT,
        }
        warning = _progress_warning(titration_type, feature_metrics)
        if warning:
            summary["warnings"].append(warning)
        compact_warning = _compact_plus_progress_warning(titration_type, feature_metrics)
        if compact_warning:
            summary["warnings"].append(compact_warning)
        expanded_warning = _expanded_overfit_warning(titration_type, feature_metrics)
        if expanded_warning:
            summary["warnings"].append(expanded_warning)
        all_predictions.extend(
            prediction
            for fold in payload["folds"]
            if fold["feature_set"] == best_feature_set
            for prediction in fold["predictions"]
        )
        if output is not None:
            selected_path = output / "selected_models" / titration_type / "selected_model.json"
            selected_path.parent.mkdir(parents=True, exist_ok=True)
            selected_path.write_text(json.dumps(payload["selected_model"], ensure_ascii=False, indent=2), encoding="utf-8")
    summary["overall_run_level_metrics"] = run_level_metrics(all_predictions)

    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        (output / "curve_equivalence_summary.json").write_text(
            json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_csv(output / "curve_equivalence_summary.csv", all_summary_rows)
        _write_csv(output / "feature_set_comparison.csv", _comparison_rows(summary))
        _write_csv(output / "primary_comparison.csv", _comparison_rows(summary, primary_only=True))
        _write_csv(output / "typewise_run_metrics.csv", _typewise_run_metric_rows(summary))
        _write_csv(output / "feature_importance.csv", _feature_importance_rows(summary))
        (output / "report.md").write_text(_render_report(summary), encoding="utf-8")
    return summary


def evaluate_folder(
    folder: str | Path,
    *,
    output_dir: str | Path = "data/ml/curve_equivalence_current",
    fps: float = 25.0,
    quick: bool = False,
) -> dict[str, Any]:
    """Load CSVs, resample to 25fps, and evaluate run-level equivalence prediction."""

    runs = [resample_run(run, fps=fps) for run in load_runs(folder)]
    return evaluate_runs(runs, output_dir=output_dir, quick=quick)


def _render_report(summary: Mapping[str, Any]) -> str:
    lines = [
        "# 곡선 기반 당량점 예측 ML 보고서",
        "",
        "이 분석은 프레임별 delta_ml 회귀를 최종 목표로 보지 않고, 한 번의 적정 실험에서 당량점 부피 오차를 줄이는 것을 목표로 한다.",
        "각 CSV run을 주입량-센서값 곡선으로 변환하고, 색/열/융합 변화가 큰 후보 부피를 뽑은 뒤 후보 중 하나를 최종 당량점으로 선택한다.",
        "이론 당량점은 후보 오차 학습과 평가 target으로만 사용하고, model input feature에는 넣지 않는다.",
        "25fps 행은 곡선 내부 관측치일 뿐 독립 실험 수로 해석하지 않는다. 따라서 현재 결과는 proof-of-concept이다.",
        "feature set 중 최저 MAE를 고르는 것은 탐색적 결과이며, 핵심 비교는 current_fusion / compact_plus / compact_plus_no_progress / fusion_expanded / fusion_no_progress로 따로 본다.",
        "주입량/현재 부피는 펌프와 시간으로 실제 수집 가능한 정당한 입력값이며, no_progress 계열은 이를 금지한 최종 모델이 아니라 센서-only 기여도를 확인하는 ablation이다.",
        "candidate_tables는 target/오차까지 포함한 진단용 후보표이고, 실제 모델 입력 확인은 candidate_feature_tables를 사용한다.",
        "",
        "## 전체 요약",
    ]
    overall = summary.get("overall_run_level_metrics", {})
    lines.append(
        f"- 전체 run-level MAE={overall.get('mae_ml', 0)} mL, median AE={overall.get('median_abs_error_ml', 0)} mL, "
        f"±0.5 mL 성공률={overall.get('within_0.5ml_rate', 0)}"
    )
    lines.append(
        f"- 평균 실제/예측 당량부피={overall.get('mean_actual_equivalence_volume_ml', 0)} / "
        f"{overall.get('mean_predicted_equivalence_volume_ml', 0)} mL"
    )
    lines.append(
        f"- 상대오차 MAE={overall.get('mae_percent_of_equivalence', 0)}%, "
        f"농도 환산 오차 MAE={overall.get('concentration_mae_percent', 0)}%, "
        f"±2% 성공률={overall.get('within_2pct_rate', 0)}"
    )
    lines.append("")
    typewise_rows = _typewise_run_metric_rows(summary)
    if typewise_rows:
        lines.extend(
            [
                "## 타입별 핵심 지표",
                "| 적정 종류 | 선택 feature set | run 수 | 실제/예측 평균 mL | MAE mL | 상대오차 MAE | 농도 환산 오차 | bias % | ±1/±2/±5% 성공률 |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in typewise_rows:
            lines.append(
                f"| {row['titration_type']} | {row['selected_feature_set']} | {row['run_count']} | "
                f"{row['mean_actual_equivalence_volume_ml']} / {row['mean_predicted_equivalence_volume_ml']} | "
                f"{row['mae_ml']} | {row['mae_percent_of_equivalence']}% | "
                f"{row['concentration_mae_percent']}% | {row['bias_percent_of_equivalence']}% | "
                f"{row['within_1pct_rate']} / {row['within_2pct_rate']} / {row['within_5pct_rate']} |"
            )
        lines.append("")
    warnings = summary.get("warnings", [])
    if warnings:
        lines.append("## 경고/해석 주의")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## 1차 핵심 비교")
    lines.append("- `current_fusion`: 기존 곡선 후보 모델에 가까운 기준선")
    lines.append("- `compact_plus`: current_fusion에 후보 간 source agreement/score rank/density feature를 소량 추가한 모델")
    lines.append(
        "- `compact_plus_no_progress`: compact_plus에서 실제 주입량/진행 정보와 고정비율 후보를 일부러 제거해 "
        "센서-only 후보 일치도의 기여도를 확인하는 ablation 모델"
    )
    lines.append("- `fusion_expanded`: 열화상/색상 분포 feature를 확장한 센서 융합 모델")
    lines.append(
        "- `fusion_no_progress`: 실제 주입량/진행 정보를 일부러 제거해 "
        "센서 feature만 남겼을 때 성능이 얼마나 떨어지는지 확인하는 ablation 모델"
    )
    lines.append("")
    for titration_type, payload in summary.get("types", {}).items():
        lines.append(f"### `{titration_type}` primary comparison")
        for feature_set, fs_metrics in payload.get("primary_comparison", {}).items():
            lines.append(
                f"- {feature_set}: MAE={fs_metrics.get('mae_ml', 0)} mL, "
                f"상대오차={fs_metrics.get('mae_percent_of_equivalence', 0)}%, "
                f"median AE={fs_metrics.get('median_abs_error_ml', 0)} mL, "
                f"±0.5 mL={fs_metrics.get('within_0.5ml_rate', 0)}"
            )
        lines.append("")
    lines.append("## 타입별 요약")
    for titration_type, payload in summary.get("types", {}).items():
        selected = payload.get("selected_model", {})
        metrics = payload.get("run_level_metrics", {})
        lines.extend(
            [
                f"### `{titration_type}`",
                f"- 탐색적 최저 MAE feature set: {selected.get('feature_set')}",
                f"- 선택 주의: {selected.get('claim_warning', '탐색적 선택')}",
                f"- 당량점 부피 오차 MAE: {metrics.get('mae_ml', 0)} mL",
                f"- 상대오차 MAE: {metrics.get('mae_percent_of_equivalence', 0)}%",
                f"- 농도 환산 오차 MAE: {metrics.get('concentration_mae_percent', 0)}%",
                f"- median AE: {metrics.get('median_abs_error_ml', 0)} mL",
                f"- bias: {metrics.get('bias_ml', 0)} mL",
                f"- ±0.1/±0.2/±0.5/±1.0 mL 성공률: "
                f"{metrics.get('within_0.1ml_rate', 0)} / {metrics.get('within_0.2ml_rate', 0)} / "
                f"{metrics.get('within_0.5ml_rate', 0)} / {metrics.get('within_1.0ml_rate', 0)}",
                f"- ±1/±2/±5% 성공률: "
                f"{metrics.get('within_1pct_rate', 0)} / {metrics.get('within_2pct_rate', 0)} / "
                f"{metrics.get('within_5pct_rate', 0)}",
            ]
        )
        for feature_set, fs_metrics in payload.get("feature_set_metrics", {}).items():
            lines.append(
                f"  - {feature_set}: MAE={fs_metrics.get('mae_ml', 0)} mL, "
                f"상대오차={fs_metrics.get('mae_percent_of_equivalence', 0)}%, "
                f"±0.5 mL={fs_metrics.get('within_0.5ml_rate', 0)}"
            )
        lines.append("")
    lines.extend(
        [
            "## 해석",
            "- 이전 프레임별 delta_ml 회귀 MAE가 큰 이유는 전체 적정 구간(-수십 mL~과적정)을 매 프레임 맞히는 문제였기 때문이다.",
            "- 이번 방식은 실제 목표인 최종 당량점 부피 하나를 예측하므로 전람회 목표와 더 직접적으로 대응한다.",
            "- expanded feature가 좋아져도 12개 run 안의 retrospective LOO 결과이므로, '일반화 정확도'가 아니라 '기존 데이터에서 센서 feature 확장을 평가한 결과'로 표현해야 한다.",
            "- 단, 타입별 독립 농도 수가 적으므로 일반화 정확도라고 주장하지 말고 반복 실험을 늘려야 한다.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate curve-based equivalence-point ML from titration CSVs.")
    parser.add_argument("folder", help="Folder containing titration CSV files")
    parser.add_argument("--output-dir", default="data/ml/curve_equivalence_current")
    parser.add_argument("--fps", type=float, default=25.0)
    parser.add_argument("--quick", action="store_true", help="Use deterministic baseline candidate scoring only")
    args = parser.parse_args(argv)
    summary = evaluate_folder(args.folder, output_dir=args.output_dir, fps=args.fps, quick=args.quick)
    print(json.dumps({"output_dir": args.output_dir, "overall": summary["overall_run_level_metrics"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
