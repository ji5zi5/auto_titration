#!/usr/bin/env python3
"""Bounded sensor-only transition-candidate union.

Candidate generation reads five sensor channels only.  It never reads volume,
concentration, theoretical endpoint, frame/time, or progress fields.
"""

from __future__ import annotations

import itertools
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

for variable in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"

import numpy as np


BASELINES = (6, 10, 16, 24)
WINDOWS = (2, 3, 5, 8, 12, 16)
THRESHOLDS = (0.15, 0.35, 0.70)
CONFIRMATIONS = (1, 2, 3)
REFRACTORIES = (1, 3, 6)
MODALITIES = ("color", "thermal")
MAX_CANDIDATES = 128


@dataclass(frozen=True)
class Candidate:
    boundary: int
    confirmation: int
    features: tuple[float, ...]
    support: int
    sources: tuple[str, ...]


def number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def causal_fill(values: np.ndarray) -> np.ndarray:
    result = values.astype(float, copy=True)
    for column in range(result.shape[1]):
        prior = 0.0
        for row in range(len(result)):
            if np.isfinite(result[row, column]):
                prior = float(result[row, column])
            else:
                result[row, column] = prior
    return result


def sensor_matrix(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Read only five permitted sensor channels."""
    hue = np.asarray([number(row.get("visible_H_mean")) for row in rows], dtype=float)
    saturation = np.asarray([number(row.get("visible_S_mean")) for row in rows], dtype=float)
    value = np.asarray([number(row.get("visible_V_mean")) for row in rows], dtype=float)
    radians = np.deg2rad(hue)
    color = np.column_stack((
        saturation * np.cos(radians), saturation * np.sin(radians), value,
    ))
    p50 = np.asarray([number(row.get("thermal_raw_roi_p50")) for row in rows], dtype=float)
    p95 = np.asarray([number(row.get("thermal_raw_roi_p95")) for row in rows], dtype=float)
    thermal = np.column_stack((p50, p95 - p50))
    valid = np.all(np.isfinite(thermal), axis=1) & np.any(np.abs(thermal) > 1e-12, axis=1)
    thermal[~valid] = np.nan
    return causal_fill(np.column_stack((color, thermal))), valid


def robust_scale(matrix: np.ndarray, baseline: int) -> tuple[np.ndarray, np.ndarray]:
    center = np.median(matrix[:baseline], axis=0)
    mad = np.median(np.abs(matrix[:baseline] - center), axis=0) * 1.4826
    return center, np.maximum(mad, np.asarray((0.01, 0.01, 0.01, 2.0, 2.0)))


def detect_one(
    matrix: np.ndarray,
    thermal_valid: np.ndarray,
    *,
    baseline: int,
    window: int,
    threshold: float,
    confirmation: int,
    refractory: int,
    modality: str,
) -> list[tuple[int, int, float]]:
    """Confirmed local shifts for one bounded-grid cell."""
    modality_slice = slice(0, 3) if modality == "color" else slice(3, 5)
    if modality == "thermal" and np.mean(thermal_valid[:baseline]) < 0.75:
        return []
    center, scale = robust_scale(matrix, baseline)
    first = max(baseline, 2 * window - 1)
    scores: list[tuple[int, float, float]] = []
    for end in range(first, len(matrix)):
        start = end - 2 * window + 1
        if modality == "thermal" and np.mean(thermal_valid[start:end + 1]) < 0.75:
            scores.append((end, 0.0, 0.0))
            continue
        before = np.median(matrix[start:end - window + 1], axis=0)
        after = np.median(matrix[end - window + 1:end + 1], axis=0)
        shift = (after - before) / scale
        departure = (after - center) / scale
        score = float(np.linalg.norm(shift[modality_slice]) / np.sqrt(3 if modality == "color" else 2))
        persistence = float(np.linalg.norm(departure[modality_slice]) / np.sqrt(3 if modality == "color" else 2))
        scores.append((end, score, persistence))
    output: list[tuple[int, int, float]] = []
    last = -refractory
    for peak_index in range(0, len(scores) - confirmation):
        end, score, persistence = scores[peak_index]
        future = scores[peak_index:peak_index + confirmation + 1]
        lasting = min(item[2] for item in future)
        # A plateau's earliest maximum is retained; confirmation backdates it.
        if score < threshold or lasting < threshold or score < max(item[1] for item in future):
            continue
        boundary = end - window + 1
        if boundary - last < refractory:
            continue
        output.append((boundary, future[-1][0], score + 0.25 * lasting))
        last = boundary
    return output


def local_sensor_features(
    matrix: np.ndarray,
    thermal_valid: np.ndarray,
    boundary: int,
    support: int,
    source_counts: Mapping[str, int],
) -> tuple[float, ...]:
    baseline = min(16, max(6, len(matrix) // 8))
    initial, scale = robust_scale(matrix, baseline)
    final = np.median(matrix[-baseline:], axis=0)
    direction = (final - initial) / scale
    values: list[float] = []
    for window in (2, 3, 5, 8, 12, 16):
        before = np.median(matrix[max(0, boundary - window):boundary], axis=0)
        after = np.median(matrix[boundary:min(len(matrix), boundary + window)], axis=0)
        shift = (after - before) / scale
        departure = (after - initial) / scale
        values.extend((
            float(np.linalg.norm(shift[:3]) / np.sqrt(3)),
            float(np.linalg.norm(shift[3:]) / np.sqrt(2)),
            float(np.linalg.norm(departure[:3]) / np.sqrt(3)),
            float(np.linalg.norm(departure[3:]) / np.sqrt(2)),
        ))
    after = np.median(matrix[boundary:min(len(matrix), boundary + 5)], axis=0)
    departure = (after - initial) / scale
    for modality_slice in (slice(0, 3), slice(3, 5)):
        direct = direction[modality_slice]
        state = departure[modality_slice]
        denom = float(np.dot(direct, direct)) + 1e-9
        coordinate = float(np.dot(state, direct) / denom)
        orthogonal = float(np.linalg.norm(state - coordinate * direct))
        values.extend((coordinate, orthogonal, float(np.linalg.norm(direct))))
    values.extend((
        float(np.log1p(support)),
        float(np.log1p(source_counts.get("color", 0))),
        float(np.log1p(source_counts.get("thermal", 0))),
        float(np.mean(thermal_valid[max(0, boundary - 8):min(len(matrix), boundary + 8)])),
    ))
    return tuple(values)


def generate_union_candidates(rows: Sequence[Mapping[str, Any]]) -> list[Candidate]:
    matrix, thermal_valid = sensor_matrix(rows)
    evidence: dict[int, list[tuple[int, float, str]]] = defaultdict(list)
    for baseline, window, threshold, confirmation, refractory, modality in itertools.product(
        BASELINES, WINDOWS, THRESHOLDS, CONFIRMATIONS, REFRACTORIES, MODALITIES
    ):
        if baseline + 2 * window + confirmation >= len(matrix):
            continue
        source = f"{modality}:b{baseline}:w{window}:t{threshold}:c{confirmation}:r{refractory}"
        for boundary, confirmed, strength in detect_one(
            matrix, thermal_valid, baseline=baseline, window=window,
            threshold=threshold, confirmation=confirmation,
            refractory=refractory, modality=modality,
        ):
            evidence[boundary].append((confirmed, strength, source))
    if len(evidence) > MAX_CANDIDATES:
        # Sensor-only bounded retention: consensus first, then aggregate salience.
        ordered = sorted(
            evidence,
            key=lambda boundary: (
                -len(evidence[boundary]),
                -sum(item[1] for item in evidence[boundary]),
                boundary,
            ),
        )[:MAX_CANDIDATES]
        evidence = {boundary: evidence[boundary] for boundary in ordered}
    candidates = []
    for boundary in sorted(evidence):
        items = evidence[boundary]
        source_counts = Counter(item[2].split(":", 1)[0] for item in items)
        candidates.append(Candidate(
            boundary=boundary,
            confirmation=min(item[0] for item in items),
            features=local_sensor_features(matrix, thermal_valid, boundary, len(items), source_counts),
            support=len(items),
            sources=tuple(sorted(item[2] for item in items)),
        ))
    return candidates


def feature_names() -> list[str]:
    names = []
    for window in (2, 3, 5, 8, 12, 16):
        names.extend((
            f"color_shift_w{window}", f"thermal_shift_w{window}",
            f"color_state_w{window}", f"thermal_state_w{window}",
        ))
    names.extend((
        "color_terminal_coordinate", "color_orthogonal_state", "color_terminal_change",
        "thermal_terminal_coordinate", "thermal_orthogonal_state", "thermal_terminal_change",
        "candidate_consensus", "color_source_consensus", "thermal_source_consensus",
        "thermal_availability",
    ))
    return names

