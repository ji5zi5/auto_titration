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
    return model


def feature_dict_from_row(row: Mapping[str, Any], feature_columns: Sequence[str], categorical_columns: set[str]) -> dict[str, float | str]:
    features: dict[str, float | str] = {}
    for column in feature_columns:
        if column in categorical_columns:
            features[column] = str(row.get(column) or "")
        else:
            features[column] = _safe_float(row.get(column)) or 0.0
    return features


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


def predict_typewise_equivalence(model: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], titration_type: str) -> dict[str, Any]:
    """Predict one equivalence volume from a finished live CSV row sequence."""

    type_key = str(titration_type or "").strip() or "strong_acid_strong_base"
    models = model.get("models") or {}
    entry = models.get(type_key) or models.get("default")
    if not isinstance(entry, Mapping):
        raise ValueError(f"no typewise model for titration_type={type_key!r}")

    feature_columns = list(model.get("feature_columns") or [])
    categorical_columns = set(model.get("categorical_columns") or [])
    estimator = entry.get("estimator")
    if estimator is None:
        raise ValueError(f"typewise model entry has no estimator: {type_key}")

    feature_rows: list[dict[str, float | str]] = []
    current_volumes: list[float] = []
    original_indices: list[int] = []
    for index, row in enumerate(rows):
        volume = _safe_float(row.get("injected_volume_ml"))
        if volume is None:
            continue
        feature_rows.append(feature_dict_from_row(row, feature_columns, categorical_columns))
        current_volumes.append(volume)
        original_indices.append(index)
    if not feature_rows:
        raise ValueError("no rows with injected_volume_ml for typewise live prediction")

    scores = _positive_scores(estimator, feature_rows)
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
