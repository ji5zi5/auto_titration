"""Retrospective equivalence-point estimation from lightweight features."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .feature_history import FeatureSample


@dataclass(frozen=True)
class EquivalenceResult:
    estimated_equivalence_time_s: float
    estimated_equivalence_volume_ml: float
    confidence: float
    evidence: tuple[str, ...] = ()
    theoretical_equivalence_volume_ml: float | None = None
    absolute_volume_error_ml: float | None = None
    relative_volume_error_percent: float | None = None
    warnings: tuple[str, ...] = ()
    candidate_index: int | None = None
    status_label: str = "unknown"

    def to_dict(self) -> dict[str, float | str | int | None]:
        return {
            "estimated_equivalence_time_s": self.estimated_equivalence_time_s,
            "estimated_equivalence_volume_ml": self.estimated_equivalence_volume_ml,
            "confidence": self.confidence,
            "evidence": "; ".join(self.evidence),
            "theoretical_equivalence_volume_ml": self.theoretical_equivalence_volume_ml,
            "absolute_volume_error_ml": self.absolute_volume_error_ml,
            "relative_volume_error_percent": self.relative_volume_error_percent,
            "warnings": "; ".join(self.warnings),
            "candidate_index": self.candidate_index,
            "status_label": self.status_label,
        }


def estimate_equivalence_point(
    samples: Sequence[FeatureSample] | Iterable[FeatureSample],
    *,
    theoretical_equivalence_volume_ml: float | None = None,
) -> EquivalenceResult:
    """Estimate the most likely equivalence point from stored feature history.

    The estimator is deliberately transparent: it combines normalized color
    change, thermal ROI change, and status-transition hints. ML can later add
    another evidence signal without becoming motor-control authority.
    """

    ordered = sorted(list(samples), key=lambda sample: (sample.time_s, sample.frame_id))
    if not ordered:
        raise ValueError("at least one feature sample is required")

    color_values = [_feature(sample.visible_features, "visible_color_delta", "color_delta") for sample in ordered]
    thermal_values = [_feature(sample.thermal_features, "thermal_roi_avg", "thermal_avg", "thermal_temperature_c") for sample in ordered]
    thermal_deltas = _absolute_deltas(thermal_values)

    max_color = max([value for value in color_values if value is not None] or [0.0])
    max_thermal_delta = max([value for value in thermal_deltas if value is not None] or [0.0])

    scores: list[float] = []
    for index, sample in enumerate(ordered):
        color_score = _normalize(color_values[index], max_color)
        thermal_score = _normalize(thermal_deltas[index], max_thermal_delta)
        status_score = _status_score(sample.status_label) * max(0.0, min(1.0, sample.status_confidence or 0.0))
        scores.append((0.45 * color_score) + (0.35 * thermal_score) + (0.20 * status_score))

    candidate_index = max(range(len(ordered)), key=lambda index: scores[index])
    candidate = ordered[candidate_index]
    estimated_time = float(candidate.time_s)
    estimated_volume = interpolate_volume_at_time(ordered, estimated_time)

    evidence: list[str] = []
    warnings: list[str] = list(candidate.warnings)
    color_strength = _normalize(color_values[candidate_index], max_color)
    thermal_strength = _normalize(thermal_deltas[candidate_index], max_thermal_delta)

    if max_color > 0:
        evidence.append(f"color change peak score={color_strength:.3f}")
    else:
        warnings.append("visible color change signal unavailable or flat")

    if any(value is not None for value in thermal_values):
        evidence.append(f"thermal ROI change score={thermal_strength:.3f}")
        if not _is_calibrated(candidate.thermal_features):
            warnings.append("thermal data present but not confirmed calibrated Celsius")
    else:
        warnings.append("thermal data unavailable; estimate is color/status based")

    if candidate.status_label not in ("", "unknown", "before"):
        evidence.append(f"status transition label={candidate.status_label}")

    confidence = _clamp(0.25 + 0.35 * color_strength + 0.25 * thermal_strength + 0.15 * _status_score(candidate.status_label))
    if any("unavailable" in warning.lower() or "not confirmed" in warning.lower() for warning in warnings):
        confidence = min(confidence, 0.82)

    absolute_error = None
    relative_error = None
    if theoretical_equivalence_volume_ml is not None:
        absolute_error = abs(estimated_volume - float(theoretical_equivalence_volume_ml))
        if theoretical_equivalence_volume_ml != 0:
            relative_error = absolute_error / abs(float(theoretical_equivalence_volume_ml)) * 100.0
        evidence.append(f"theoretical comparison error={absolute_error:.3f} mL")

    return EquivalenceResult(
        estimated_equivalence_time_s=round(estimated_time, 6),
        estimated_equivalence_volume_ml=round(estimated_volume, 6),
        confidence=round(confidence, 6),
        evidence=tuple(evidence),
        theoretical_equivalence_volume_ml=theoretical_equivalence_volume_ml,
        absolute_volume_error_ml=round(absolute_error, 6) if absolute_error is not None else None,
        relative_volume_error_percent=round(relative_error, 6) if relative_error is not None else None,
        warnings=tuple(dict.fromkeys(warnings)),
        candidate_index=candidate_index,
        status_label=candidate.status_label,
    )


def interpolate_volume_at_time(samples: Sequence[FeatureSample] | Iterable[FeatureSample], target_time_s: float) -> float:
    ordered = sorted(list(samples), key=lambda sample: (sample.time_s, sample.frame_id))
    if not ordered:
        raise ValueError("at least one sample is required")
    if target_time_s <= ordered[0].time_s:
        return float(ordered[0].injected_volume_ml)
    if target_time_s >= ordered[-1].time_s:
        return float(ordered[-1].injected_volume_ml)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.time_s <= target_time_s <= current.time_s:
            span = current.time_s - previous.time_s
            if span == 0:
                return float(current.injected_volume_ml)
            fraction = (target_time_s - previous.time_s) / span
            return float(previous.injected_volume_ml) + fraction * (float(current.injected_volume_ml) - float(previous.injected_volume_ml))
    return float(ordered[-1].injected_volume_ml)


def _feature(mapping: Mapping[str, object], *keys: str) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if value in ("", None):
            continue
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except ValueError:
                return None
        return None
    return None


def _absolute_deltas(values: Sequence[float | None]) -> list[float | None]:
    deltas: list[float | None] = []
    previous: float | None = None
    for value in values:
        if value is None or previous is None:
            deltas.append(0.0 if value is not None else None)
        else:
            deltas.append(abs(value - previous))
        if value is not None:
            previous = value
    return deltas


def _normalize(value: float | None, maximum: float) -> float:
    if value is None or maximum <= 0:
        return 0.0
    return _clamp(float(value) / maximum)


def _status_score(label: str) -> float:
    return {
        "near_endpoint": 0.65,
        "endpoint": 1.0,
        "overshoot": 0.35,
        "before": 0.0,
        "unknown": 0.0,
        "": 0.0,
    }.get(label, 0.0)


def _is_calibrated(features: Mapping[str, object]) -> bool:
    value = features.get("thermal_calibrated", features.get("calibrated_temperature", False))
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "calibrated"}
    return bool(value)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))
