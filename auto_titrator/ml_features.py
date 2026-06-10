"""Derived scalar features for endpoint/equivalence machine learning.

The raw CSV already carries instantaneous color/thermal values. This module adds
run-context features that are cheap to compute online: baseline shifts, short
rolling-window statistics, slopes, titration-type one-hot values, and quality
flags. It deliberately returns scalar values only so rows remain CSV-friendly.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .chemistry import SUPPORTED_TITRATION_TYPES

TITRATION_TYPE_FEATURE_COLUMNS = tuple(f"titration_is_{name}" for name in SUPPORTED_TITRATION_TYPES)

DERIVED_ML_COLUMNS = [
    "visible_H_baseline_delta",
    "visible_S_baseline_delta",
    "visible_V_baseline_delta",
    "visible_HSV_baseline_delta",
    "visible_color_baseline_delta",
    "visible_H_slope_deg_per_s",
    "visible_S_slope_per_s",
    "visible_V_slope_per_s",
    "visible_HSV_delta_mean_1s",
    "visible_HSV_delta_max_1s",
    "visible_color_delta_mean_1s",
    "visible_color_delta_max_1s",
    "thermal_roi_avg_baseline_delta",
    "thermal_roi_p95_baseline_delta",
    "thermal_roi_avg_slope_c_per_s",
    "thermal_roi_p95_slope_c_per_s",
    "thermal_roi_delta_mean_1s",
    "thermal_roi_delta_max_1s",
    "thermal_raw_roi_p50_baseline_delta",
    "thermal_raw_roi_p95_baseline_delta",
    "thermal_raw_roi_p50_slope_per_s",
    "thermal_raw_roi_p95_slope_per_s",
    "thermal_raw_roi_delta_mean_1s",
    "thermal_raw_roi_delta_max_1s",
    "abs_sync_offset_ms",
    "training_quality_score",
    "valid_for_training",
    *TITRATION_TYPE_FEATURE_COLUMNS,
]

_HUE_COLUMNS = {"visible_H_mean"}


def derive_ml_features(
    history_rows: Sequence[Mapping[str, Any]],
    current_row: Mapping[str, Any],
    *,
    window_s: float = 1.0,
    baseline_s: float = 1.0,
) -> dict[str, float]:
    """Return ML-ready derived scalar features for ``current_row``.

    ``history_rows`` must contain earlier rows from the same run/session. Missing
    numeric inputs produce neutral zeros rather than blanks so downstream simple
    models can consume the columns consistently.
    """

    features = {column: 0.0 for column in DERIVED_ML_COLUMNS}
    rows = [row for row in history_rows if isinstance(row, Mapping)] + [current_row]
    timed_rows = [(time_value, row) for row in rows if (time_value := _row_time(row)) is not None]
    timed_rows.sort(key=lambda item: item[0])
    current_time = _row_time(current_row)

    _apply_titration_type_features(features, current_row, history_rows)
    _apply_quality_features(features, current_row)

    if current_time is None or not timed_rows:
        return _rounded(features)

    first_time = timed_rows[0][0]
    baseline_cutoff = first_time + max(0.0, float(baseline_s))
    baseline_rows = [row for time_value, row in timed_rows if time_value <= baseline_cutoff]
    if not baseline_rows:
        baseline_rows = [current_row]

    window_start = current_time - max(0.0, float(window_s))
    window_rows = [(time_value, row) for time_value, row in timed_rows if window_start <= time_value <= current_time]
    if not window_rows:
        window_rows = [(current_time, current_row)]

    _apply_baseline_delta(features, current_row, baseline_rows, "visible_H_mean", "visible_H_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "visible_S_mean", "visible_S_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "visible_V_mean", "visible_V_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "visible_HSV_delta", "visible_HSV_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "visible_color_delta", "visible_color_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "thermal_roi_avg", "thermal_roi_avg_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "thermal_roi_p95", "thermal_roi_p95_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "thermal_raw_roi_p50", "thermal_raw_roi_p50_baseline_delta")
    _apply_baseline_delta(features, current_row, baseline_rows, "thermal_raw_roi_p95", "thermal_raw_roi_p95_baseline_delta")

    _apply_slope(features, current_row, current_time, window_rows, "visible_H_mean", "visible_H_slope_deg_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "visible_S_mean", "visible_S_slope_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "visible_V_mean", "visible_V_slope_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "thermal_roi_avg", "thermal_roi_avg_slope_c_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "thermal_roi_p95", "thermal_roi_p95_slope_c_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "thermal_raw_roi_p50", "thermal_raw_roi_p50_slope_per_s")
    _apply_slope(features, current_row, current_time, window_rows, "thermal_raw_roi_p95", "thermal_raw_roi_p95_slope_per_s")

    _apply_window_stats(features, window_rows, "visible_HSV_delta", "visible_HSV_delta")
    _apply_window_stats(features, window_rows, "visible_color_delta", "visible_color_delta")
    _apply_window_stats(features, window_rows, "thermal_roi_delta", "thermal_roi_delta")
    _apply_window_stats(features, window_rows, "thermal_raw_roi_delta", "thermal_raw_roi_delta")

    return _rounded(features)


def _apply_titration_type_features(
    features: dict[str, float], current_row: Mapping[str, Any], history_rows: Sequence[Mapping[str, Any]]
) -> None:
    titration_type = str(current_row.get("titration_type") or "").strip()
    if not titration_type:
        for row in reversed(history_rows):
            titration_type = str(row.get("titration_type") or "").strip()
            if titration_type:
                break
    for name in SUPPORTED_TITRATION_TYPES:
        features[f"titration_is_{name}"] = 1.0 if titration_type == name else 0.0


def _apply_quality_features(features: dict[str, float], row: Mapping[str, Any]) -> None:
    abs_sync = abs(_to_float(row.get("sync_offset_ms")) or 0.0)
    features["abs_sync_offset_ms"] = abs_sync

    score = 1.0
    invalid = False
    sync_quality = str(row.get("sync_quality") or "").casefold()
    if sync_quality in {"bad", "poor", "out_of_sync", "missing"}:
        score -= 0.35
        invalid = True
    elif abs_sync > 80.0:
        score -= 0.25
    elif abs_sync > 40.0:
        score -= 0.10

    if "thermal_calibrated" in row and not _to_bool(row.get("thermal_calibrated")):
        score -= 0.15
    source_quality = str(row.get("source_quality") or "").casefold()
    if "unavailable" in source_quality or "raw preview only" in source_quality:
        score -= 0.20
    warnings = str(row.get("warnings") or "").strip()
    if warnings:
        score -= 0.10
    roi_state = str(row.get("roi_state") or "").casefold().strip()
    if roi_state and roi_state not in {"locked", "recording", "stopped"}:
        score -= 0.30
        invalid = True

    score = max(0.0, min(1.0, score))
    features["training_quality_score"] = score
    features["valid_for_training"] = 0.0 if invalid or score < 0.5 else 1.0


def _apply_baseline_delta(
    features: dict[str, float],
    current_row: Mapping[str, Any],
    baseline_rows: Sequence[Mapping[str, Any]],
    source_key: str,
    output_key: str,
) -> None:
    current = _to_float(current_row.get(source_key))
    if current is None:
        return
    baseline_values = [_to_float(row.get(source_key)) for row in baseline_rows]
    values = [value for value in baseline_values if value is not None]
    if not values:
        return
    if source_key in _HUE_COLUMNS:
        baseline = _circular_mean_deg(values)
        features[output_key] = _signed_hue_delta_deg(current, baseline)
    else:
        baseline = sum(values) / len(values)
        features[output_key] = current - baseline


def _apply_slope(
    features: dict[str, float],
    current_row: Mapping[str, Any],
    current_time: float,
    window_rows: Sequence[tuple[float, Mapping[str, Any]]],
    source_key: str,
    output_key: str,
) -> None:
    current = _to_float(current_row.get(source_key))
    if current is None:
        return
    first_time: float | None = None
    first_value: float | None = None
    for time_value, row in window_rows:
        candidate = _to_float(row.get(source_key))
        if candidate is not None:
            first_time = time_value
            first_value = candidate
            break
    if first_time is None or first_value is None:
        return
    dt = current_time - first_time
    if dt <= 0:
        return
    if source_key in _HUE_COLUMNS:
        delta = _signed_hue_delta_deg(current, first_value)
    else:
        delta = current - first_value
    features[output_key] = delta / dt


def _apply_window_stats(
    features: dict[str, float],
    window_rows: Sequence[tuple[float, Mapping[str, Any]]],
    source_key: str,
    output_prefix: str,
) -> None:
    values = [_to_float(row.get(source_key)) for _, row in window_rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return
    features[f"{output_prefix}_mean_1s"] = sum(numeric) / len(numeric)
    features[f"{output_prefix}_max_1s"] = max(numeric)


def _row_time(row: Mapping[str, Any]) -> float | None:
    for key in ("time_s", "csv_recording_elapsed_s", "pump_elapsed_s"):
        value = _to_float(row.get(key))
        if value is not None:
            return value
    return None


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


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value or "").strip().casefold()
    return text in {"1", "true", "yes", "y", "calibrated"}


def _circular_mean_deg(values: Sequence[float]) -> float:
    sin_sum = sum(math.sin(math.radians(value)) for value in values)
    cos_sum = sum(math.cos(math.radians(value)) for value in values)
    if sin_sum == 0.0 and cos_sum == 0.0:
        return 0.0
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0


def _signed_hue_delta_deg(current: float, reference: float) -> float:
    return ((float(current) - float(reference) + 180.0) % 360.0) - 180.0


def _rounded(features: Mapping[str, float]) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in features.items()}
