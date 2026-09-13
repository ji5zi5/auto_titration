"""Live typewise classifier prediction for equivalence volume.

The artifact loaded here is trained from completed experiment CSVs, but live
prediction uses only values that can be observed during/after the current run:
current injected volume, visible/thermal sensor features, and experiment
metadata. It must not use theoretical equivalence, progress fraction, final run
length, or known sample concentration as input features.
"""

from __future__ import annotations

import math
import pickle
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


PREDICTION_SOURCE = "typewise_frame_zone_classifier"

_FORBIDDEN_FEATURE_EXACT = {
    "actual_ml",
    "delta_ml",
    "distance_to_equivalence_ml",
    "equivalence_window_label",
    "sample_concentration_m",
    "status_label",
    "theoretical_equivalence_volume_ml",
    "zone_label",
}
_FORBIDDEN_FEATURE_PARTS = (
    "actual_equivalence",
    "endpoint",
    "final_run",
    "known_sample",
    "sample_concentration",
    "sample_molarity",
    "distance_to_endpoint",
    "distance_to_equivalence",
    "equivalence",
    "ground_truth",
    "progress",
    "theory",
    "theoretical_",
    "zone_label",
)
_FORBIDDEN_FEATURE_SUFFIXES = ("_fraction", "_label", "_target")
_SENSOR_FEATURE_PREFIXES = ("visible_", "thermal_")

# Hardware-control artifacts may use arbitrary measured visible/thermal
# features, but every non-sensor input must be explicitly known to exist at
# runtime. Keep this manifest independent from the artifact so a retrained or
# tampered pickle cannot declare an endpoint/theory value safe by itself.
_RUNTIME_KNOWN_NON_SENSOR_FEATURES = {
    "abs_sync_offset_ms",
    "activity_model",
    "chemistry_model",
    "commanded_volume_ml",
    "confirmed_injected_volume_ml",
    "constants_candidate_count",
    "constants_confirmation_status",
    "constants_lookup_ambiguous",
    "indicator",
    "indicator_transition_high_ph",
    "indicator_transition_low_ph",
    "injected_volume_ml",
    "preview_visible_latency_ms",
    "processing_latency_ms",
    "pump_run_rate_ml_per_s",
    "roi_source",
    "roi_state",
    "sample_name",
    "sample_volume_ml",
    "source_quality",
    "sync_offset_ms",
    "sync_quality",
    "titrant_concentration_m",
    "titrant_name",
    "titrant_valence",
    "titration_is_strong_acid_strong_base",
    "titration_is_strong_acid_weak_base",
    "titration_is_weak_acid_strong_base",
    "titration_is_weak_acid_weak_base",
    "titration_type",
    "training_quality_score",
    "valid_for_training",
}


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def forbidden_hardware_control_features(feature_columns: Sequence[str]) -> list[str]:
    """Return artifact inputs not approved for live hardware control."""

    blocked: list[str] = []
    for column in feature_columns:
        name = str(column).strip().lower()
        has_forbidden_alias = (
            name in _FORBIDDEN_FEATURE_EXACT
            or any(part in name for part in _FORBIDDEN_FEATURE_PARTS)
            or any(name.endswith(suffix) for suffix in _FORBIDDEN_FEATURE_SUFFIXES)
        )
        is_sensor = name.startswith(_SENSOR_FEATURE_PREFIXES)
        if has_forbidden_alias or (
            not is_sensor and name not in _RUNTIME_KNOWN_NON_SENSOR_FEATURES
        ):
            blocked.append(str(column))
    return blocked


def validate_hardware_control_model(model: Mapping[str, Any]) -> None:
    """Reject an artifact that is unsafe to use as an automatic-stop input."""

    feature_columns = model.get("feature_columns")
    if not isinstance(feature_columns, list) or not feature_columns:
        raise ValueError("hardware-control typewise model has no feature_columns")
    if not isinstance(model.get("models"), Mapping):
        raise ValueError("hardware-control typewise model has no models mapping")
    blocked = forbidden_hardware_control_features(feature_columns)
    if blocked:
        raise ValueError(f"forbidden hardware-control model feature(s): {', '.join(blocked)}")
    sensor_columns = [
        str(column) for column in feature_columns if str(column).lower().startswith(_SENSOR_FEATURE_PREFIXES)
    ]
    if not sensor_columns:
        raise ValueError("hardware-control typewise model requires at least one sensor feature")


def load_typewise_model(path: str | Path | None) -> dict[str, Any] | None:
    """Load a trusted local sklearn pickle artifact if it exists."""

    if path is None:
        return None
    model_path = Path(path)
    if not str(model_path).strip() or not model_path.exists():
        return None
    with model_path.open("rb") as fh:
        model = pickle.load(fh)
    if not isinstance(model, dict) or model.get("artifact_type") != "typewise_frame_zone_classifier_v1":
        raise ValueError(f"unsupported typewise live model artifact: {model_path}")
    if not isinstance(model.get("models"), dict) or not isinstance(model.get("feature_columns"), list):
        raise ValueError(f"invalid typewise live model artifact: {model_path}")
    blocked = forbidden_hardware_control_features(model["feature_columns"])
    if blocked:
        raise ValueError(
            f"forbidden typewise live model feature(s) in {model_path}: {', '.join(blocked)}"
        )
    return model


def feature_dict_from_row(row: Mapping[str, Any], feature_columns: Sequence[str], categorical_columns: set[str]) -> dict[str, float | str]:
    features: dict[str, float | str] = {}
    for column in feature_columns:
        if column in categorical_columns:
            features[column] = str(row.get(column) or "")
        else:
            features[column] = _safe_float(row.get(column)) or 0.0
    return features


def _hardware_control_feature_dict_from_row(
    row: Mapping[str, Any],
    feature_columns: Sequence[str],
    categorical_columns: set[str],
    *,
    row_index: int,
) -> dict[str, float | str]:
    features: dict[str, float | str] = {}
    for column in feature_columns:
        is_sensor = str(column).lower().startswith(_SENSOR_FEATURE_PREFIXES)
        if is_sensor:
            number = _safe_float(row.get(column))
            if number is None:
                raise ValueError(
                    f"missing or non-finite required sensor feature {column!r} in row {row_index}"
                )
            features[column] = number
            continue
        if column in categorical_columns:
            # Optional run metadata was trained with an empty-string category.
            # Endpoint truth leakage is rejected by the artifact schema above;
            # only live sensor values must fail closed when absent.
            features[column] = str(row.get(column) or "").strip()
            continue
        number = _safe_float(row.get(column))
        features[column] = 0.0 if number is None else number
    return features


def _model_entry(
    model: Mapping[str, Any],
    titration_type: str,
    *,
    strict_hardware_control: bool,
) -> tuple[str, Mapping[str, Any]]:
    raw_type = str(titration_type or "").strip()
    if strict_hardware_control and not raw_type:
        raise ValueError("titration_type is required for hardware-control scoring")
    type_key = raw_type or "strong_acid_strong_base"
    models = model.get("models") or {}
    entry = models.get(type_key)
    if entry is None and not strict_hardware_control:
        entry = models.get("default")
    if not isinstance(entry, Mapping):
        raise ValueError(f"no typewise model for titration_type={type_key!r}")
    return type_key, entry


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


def aggregate_classifier_scores(current: np.ndarray, scores: np.ndarray, mode: str) -> tuple[float, list[int]]:
    """Aggregate per-frame near-equivalence scores into one predicted volume."""

    if len(current) == 0:
        raise ValueError("at least one current-volume row is required")
    current = current.astype(float)
    scores = np.nan_to_num(scores.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    order = np.argsort(-scores)

    if mode.startswith("top"):
        k = int(mode[3:])
        take = order[: max(1, min(k, len(order)))]
        weights = np.maximum(scores[take], 1e-9)
        return float(np.average(current[take], weights=weights)), take.tolist()

    if mode.startswith("median_top"):
        k = int(mode.removeprefix("median_top"))
        take = order[: max(1, min(k, len(order)))]
        return float(np.median(current[take])), take.tolist()

    if mode.startswith("weighted_median_top"):
        k = int(mode.removeprefix("weighted_median_top"))
        take = order[: max(1, min(k, len(order)))]
        return _weighted_median(current[take], np.maximum(scores[take], 1e-9)), take.tolist()

    if mode.startswith("power") and "_top" in mode:
        power_text, top_text = mode.split("_top", 1)
        power = float(power_text.removeprefix("power"))
        k = int(top_text)
        take = order[: max(1, min(k, len(order)))]
        weights = np.maximum(scores[take], 1e-9) ** power
        return float(np.average(current[take], weights=weights)), take.tolist()

    if mode.startswith("score_quantile_"):
        suffix = mode.removeprefix("score_quantile_")
        use_median = suffix.endswith("_median")
        if use_median:
            suffix = suffix.removesuffix("_median")
        quantile = float("0." + suffix.removeprefix("q"))
        threshold = float(np.quantile(scores, quantile))
        mask = scores >= threshold
        take = np.nonzero(mask)[0]
        if len(take) == 0:
            take = order[:1]
        if use_median:
            return float(np.median(current[take])), take.tolist()
        weights = np.maximum(scores[take], 1e-9)
        return float(np.average(current[take], weights=weights)), take.tolist()

    if mode.startswith("smooth_peak_w") or mode.startswith("smooth_centroid_w"):
        width = int(mode.rsplit("w", 1)[1])
        volume_order = np.argsort(current)
        sorted_current = current[volume_order]
        sorted_scores = scores[volume_order]
        if len(sorted_scores) < width:
            take = order[:1]
            return float(current[take[0]]), take.tolist()
        kernel = np.ones(width, dtype=float) / float(width)
        smoothed = np.convolve(sorted_scores, kernel, mode="same")
        idx = int(np.argmax(smoothed))
        if mode.startswith("smooth_peak_w"):
            return float(sorted_current[idx]), [int(volume_order[idx])]
        lo = max(0, idx - width // 2)
        hi = min(len(sorted_current), idx + width // 2 + 1)
        weights = np.maximum(smoothed[lo:hi], 1e-9)
        return float(np.average(sorted_current[lo:hi], weights=weights)), [int(i) for i in volume_order[lo:hi]]

    raise ValueError(f"unsupported classifier aggregation mode: {mode}")


def _positive_scores(estimator: Any, features: Sequence[Mapping[str, Any]]) -> np.ndarray:
    if hasattr(estimator, "predict_proba"):
        proba = np.asarray(estimator.predict_proba(list(features)), dtype=float)
        classes = list(getattr(estimator, "classes_", [0, 1]))
        positive_index = classes.index(1) if 1 in classes else proba.shape[1] - 1
        return proba[:, positive_index]
    raw = np.asarray(estimator.decision_function(list(features)), dtype=float)
    return 1.0 / (1.0 + np.exp(-raw))


def score_typewise_rows(
    model: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    titration_type: str,
    *,
    strict_hardware_control: bool = False,
) -> dict[str, Any]:
    """Return causal per-row scores, optionally enforcing auto-stop safety."""

    if strict_hardware_control:
        validate_hardware_control_model(model)
    type_key, entry = _model_entry(
        model, titration_type, strict_hardware_control=strict_hardware_control
    )
    estimator = entry.get("estimator")
    if estimator is None:
        raise ValueError(f"typewise model entry has no estimator: {type_key}")
    if not rows:
        raise ValueError("at least one live row is required")
    feature_columns = list(model.get("feature_columns") or [])
    categorical_columns = set(model.get("categorical_columns") or [])
    if strict_hardware_control:
        features = [
            _hardware_control_feature_dict_from_row(
                row, feature_columns, categorical_columns, row_index=index
            )
            for index, row in enumerate(rows)
        ]
    else:
        features = [feature_dict_from_row(row, feature_columns, categorical_columns) for row in rows]
    scores = _positive_scores(estimator, features)
    if len(scores) != len(rows) or (strict_hardware_control and not np.all(np.isfinite(scores))):
        raise ValueError("typewise estimator returned invalid hardware-control scores")
    return {
        "scores": [float(np.clip(score, 0.0, 1.0)) for score in scores],
        "titration_type": type_key,
        "model_key": str(entry.get("selected_method_key") or ""),
        "model_name": str(entry.get("model_name") or ""),
        "window_ml": entry.get("window_ml"),
    }


def score_typewise_rows_for_hardware_control(
    model: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    titration_type: str,
) -> dict[str, Any]:
    """Fail-closed scoring API intended for automatic pump-stop callers."""

    return score_typewise_rows(
        model,
        rows,
        titration_type,
        strict_hardware_control=True,
    )


def predict_typewise_equivalence(
    model: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    titration_type: str,
    *,
    strict_hardware_control: bool = False,
) -> dict[str, Any]:
    """Predict one equivalence volume from a finished live CSV row sequence."""

    if strict_hardware_control:
        validate_hardware_control_model(model)
    type_key, entry = _model_entry(
        model, titration_type, strict_hardware_control=strict_hardware_control
    )

    score_rows: list[Mapping[str, Any]] = []
    current_volumes: list[float] = []
    original_indices: list[int] = []
    for index, row in enumerate(rows):
        volume = _safe_float(row.get("injected_volume_ml"))
        if volume is None:
            continue
        score_rows.append(row)
        current_volumes.append(volume)
        original_indices.append(index)
    if not score_rows:
        raise ValueError("no rows with injected_volume_ml for typewise live prediction")

    scores = np.asarray(
        score_typewise_rows(
            model,
            score_rows,
            type_key,
            strict_hardware_control=strict_hardware_control,
        )["scores"],
        dtype=float,
    )
    current = np.asarray(current_volumes, dtype=float)
    aggregate_mode = str(entry.get("aggregate_mode") or "top10")
    predicted, local_indices = aggregate_classifier_scores(current, scores, aggregate_mode)
    best_local = int(local_indices[0]) if local_indices else int(np.argmax(scores))
    candidate_index = int(original_indices[max(0, min(best_local, len(original_indices) - 1))])
    selected_scores = scores[local_indices] if local_indices else scores[[best_local]]
    confidence = float(np.clip(np.nanmean(selected_scores), 0.0, 1.0))

    return {
        "predicted_equivalence_volume_ml": round(float(predicted), 6),
        "predicted_equivalence_confidence": round(confidence, 6),
        "predicted_equivalence_source": PREDICTION_SOURCE,
        "predicted_equivalence_evidence": (
            f"{type_key} {entry.get('model_name')} classifier; "
            f"window={entry.get('window_ml')} mL; aggregate={aggregate_mode}; "
            f"training_mape={entry.get('development_mape_percent')}%"
        ),
        "candidate_index": candidate_index,
        "model_key": entry.get("selected_method_key", ""),
    }
