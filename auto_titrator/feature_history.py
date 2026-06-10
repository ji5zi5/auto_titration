"""Lightweight feature history for live equivalence-point analysis.

This module deliberately stores scalar features, labels, confidence, and source
metadata. Full camera frames or thermal matrices are not serialized by default;
they belong in provider/display code, not in the feature history artifact.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np


Scalar = str | int | float | bool | None


@dataclass
class FeatureSample:
    """One lightweight feature sample from the live/replay stream."""

    time_s: float
    frame_id: int
    injected_volume_ml: float
    visible_features: Mapping[str, Any] = field(default_factory=dict)
    thermal_features: Mapping[str, Any] = field(default_factory=dict)
    status_label: str = "unknown"
    status_confidence: float = 0.0
    source_quality: str = "unknown"
    warnings: tuple[str, ...] = ()

    def to_serializable_row(self) -> dict[str, Scalar]:
        """Flatten this sample to scalar values suitable for CSV/JSON summaries."""

        row: dict[str, Scalar] = {
            "time_s": float(self.time_s),
            "frame_id": int(self.frame_id),
            "injected_volume_ml": float(self.injected_volume_ml),
            "status_label": self.status_label,
            "status_confidence": float(self.status_confidence),
            "source_quality": self.source_quality,
            "warnings": "; ".join(self.warnings),
        }
        for source in (self.visible_features, self.thermal_features):
            for key, value in source.items():
                row[str(key)] = _as_scalar(str(key), value)
        return row


class FeatureHistory:
    """Recent ring buffer plus optional full lightweight run history."""

    def __init__(self, *, max_recent: int = 250, keep_full_history: bool = True) -> None:
        if max_recent <= 0:
            raise ValueError("max_recent must be positive")
        self.max_recent = max_recent
        self.keep_full_history = keep_full_history
        self._recent: deque[FeatureSample] = deque(maxlen=max_recent)
        self._all: list[FeatureSample] = []

    def add(self, sample: FeatureSample) -> None:
        self._recent.append(sample)
        if self.keep_full_history:
            self._all.append(sample)

    def latest(self) -> FeatureSample | None:
        return self._recent[-1] if self._recent else None

    def recent_samples(self, *, max_count: int | None = None, since_s: float | None = None) -> list[FeatureSample]:
        samples = list(self._recent)
        if since_s is not None:
            samples = [sample for sample in samples if sample.time_s >= since_s]
        if max_count is not None:
            if max_count <= 0:
                return []
            samples = samples[-max_count:]
        return samples

    def full_history(self) -> list[FeatureSample]:
        return list(self._all if self.keep_full_history else self._recent)

    def to_serializable_rows(self, *, samples: Iterable[FeatureSample] | None = None) -> list[dict[str, Scalar]]:
        source = list(samples) if samples is not None else self.full_history()
        return [sample.to_serializable_row() for sample in source]


def _as_scalar(key: str, value: Any) -> Scalar:
    if isinstance(value, np.ndarray):
        raise ValueError(f"{key} contains a full NumPy array; default history serialization stores scalar features only")
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"{key} is not a scalar feature: {type(value).__name__}")
