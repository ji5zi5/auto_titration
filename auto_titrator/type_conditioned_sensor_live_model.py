"""Post-run endpoint prediction with the frozen type-conditioned sensor ranker.

The deployed artifact contains estimators fitted on the completed June
development runs.  Runtime candidate generation reads sensor channels only;
the injected volume is looked up after a sensor frame has been selected.
This model is intended for final CSV analysis, not causal pump control.
"""

from __future__ import annotations

import math
import pickle
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from tools.sensor_transition_candidate_union import (
    BASELINES,
    CONFIRMATIONS,
    MAX_CANDIDATES,
    MODALITIES,
    REFRACTORIES,
    THRESHOLDS,
    WINDOWS,
    Candidate,
    local_sensor_features,
    robust_scale,
    sensor_matrix,
)


ARTIFACT_TYPE = "type_conditioned_sensor_endpoint_ranker_v1"
PREDICTION_SOURCE = "type_conditioned_sensor_endpoint_ranker"
SENSOR_COLUMNS = (
    "visible_H_mean",
    "visible_S_mean",
    "visible_V_mean",
    "thermal_raw_roi_p50",
    "thermal_raw_roi_p95",
)


def _sensor_scores(
    matrix: np.ndarray,
    thermal_valid: np.ndarray,
    *,
    baseline: int,
    window: int,
    modality: str,
    window_statistics: Mapping[int, Sequence[tuple[int, np.ndarray, np.ndarray, float]]]
    | None = None,
) -> list[tuple[int, float, float]]:
    modality_slice = slice(0, 3) if modality == "color" else slice(3, 5)
    if modality == "thermal" and np.mean(thermal_valid[:baseline]) < 0.75:
        return []
    center, scale = robust_scale(matrix, baseline)
    first = max(baseline, 2 * window - 1)
    scores: list[tuple[int, float, float]] = []
    if window_statistics is None:
        rows = []
        for end in range(2 * window - 1, len(matrix)):
            start = end - 2 * window + 1
            rows.append(
                (
                    end,
                    np.median(matrix[start : end - window + 1], axis=0),
                    np.median(matrix[end - window + 1 : end + 1], axis=0),
                    float(np.mean(thermal_valid[start : end + 1])),
                )
            )
    else:
        rows = window_statistics[window]
    for end, before, after, thermal_coverage in rows:
        if end < first:
            continue
        if modality == "thermal" and thermal_coverage < 0.75:
            scores.append((end, 0.0, 0.0))
            continue
        shift = (after - before) / scale
        departure = (after - center) / scale
        divisor = np.sqrt(3 if modality == "color" else 2)
        score = float(np.linalg.norm(shift[modality_slice]) / divisor)
        persistence = float(np.linalg.norm(departure[modality_slice]) / divisor)
        scores.append((end, score, persistence))
    return scores


def _precompute_window_statistics(
    matrix: np.ndarray,
    thermal_valid: np.ndarray,
) -> dict[int, list[tuple[int, np.ndarray, np.ndarray, float]]]:
    statistics_by_window = {}
    for window in WINDOWS:
        rows = []
        for end in range(2 * window - 1, len(matrix)):
            start = end - 2 * window + 1
            rows.append(
                (
                    end,
                    np.median(matrix[start : end - window + 1], axis=0),
                    np.median(matrix[end - window + 1 : end + 1], axis=0),
                    float(np.mean(thermal_valid[start : end + 1])),
                )
            )
        statistics_by_window[window] = rows
    return statistics_by_window


def _detect_from_scores(
    scores: Sequence[tuple[int, float, float]],
    *,
    window: int,
    threshold: float,
    confirmation: int,
    refractory: int,
) -> list[tuple[int, int, float]]:
    output: list[tuple[int, int, float]] = []
    last = -refractory
    for peak_index in range(0, len(scores) - confirmation):
        end, score, _ = scores[peak_index]
        future = scores[peak_index : peak_index + confirmation + 1]
        lasting = min(item[2] for item in future)
        if score < threshold or lasting < threshold or score < max(item[1] for item in future):
            continue
        boundary = end - window + 1
        if boundary - last < refractory:
            continue
        output.append((boundary, future[-1][0], score + 0.25 * lasting))
        last = boundary
    return output


def generate_union_candidates(rows: Sequence[Mapping[str, Any]]) -> list[Candidate]:
    """Generate the frozen candidate union while caching repeated sensor scores."""

    matrix, thermal_valid = sensor_matrix(rows)
    window_statistics = _precompute_window_statistics(matrix, thermal_valid)
    evidence: dict[int, list[tuple[int, float, str]]] = defaultdict(list)
    for baseline, window, modality in product(BASELINES, WINDOWS, MODALITIES):
        if baseline + 2 * window + min(CONFIRMATIONS) >= len(matrix):
            continue
        scores = _sensor_scores(
            matrix,
            thermal_valid,
            baseline=baseline,
            window=window,
            modality=modality,
            window_statistics=window_statistics,
        )
        if not scores:
            continue
        for threshold, confirmation, refractory in product(
            THRESHOLDS, CONFIRMATIONS, REFRACTORIES
        ):
            if baseline + 2 * window + confirmation >= len(matrix):
                continue
            source = (
                f"{modality}:b{baseline}:w{window}:t{threshold}:"
                f"c{confirmation}:r{refractory}"
            )
            for boundary, confirmed, strength in _detect_from_scores(
                scores,
                window=window,
                threshold=threshold,
                confirmation=confirmation,
                refractory=refractory,
            ):
                evidence[boundary].append((confirmed, strength, source))

    if len(evidence) > MAX_CANDIDATES:
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
        candidates.append(
            Candidate(
                boundary=boundary,
                confirmation=min(item[0] for item in items),
                features=local_sensor_features(
                    matrix, thermal_valid, boundary, len(items), source_counts
                ),
                support=len(items),
                sources=tuple(sorted(item[2] for item in items)),
            )
        )
    return candidates


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def resample_sensor_rows_by_volume(
    rows: Sequence[Mapping[str, Any]],
    step_ml: float,
    *,
    phase_fraction: float = 0.0,
) -> tuple[list[dict[str, float | None]], list[int]]:
    """Interpolate sensor rows onto a fixed physical-volume grid.

    The injected volume is a sampling coordinate only.  It is not included in
    candidate features.  Returned source indices map resampled volumes back to
    the nearest original CSV row for result annotation.
    """

    if step_ml <= 0:
        raise ValueError("volume resample step must be positive")
    if not 0.0 <= phase_fraction < 1.0:
        raise ValueError("volume resample phase must be in [0, 1)")
    samples = []
    for index, row in enumerate(rows):
        volume = _finite_float(row.get("injected_volume_ml"))
        if volume is None or volume < 0:
            continue
        samples.append((volume, index, row))
    if len(samples) < 2:
        raise ValueError("volume resampling requires at least two valid rows")
    samples.sort(key=lambda item: (item[0], item[1]))
    volumes = np.asarray([item[0] for item in samples], dtype=float)
    start = float(volumes[0])
    stop = float(volumes[-1])
    if stop - start < step_ml:
        raise ValueError("recorded volume range is too short for endpoint analysis")
    grid_start = start + phase_fraction * step_ml
    grid = np.arange(grid_start, stop + step_ml * 0.5, step_ml, dtype=float)
    grid = grid[grid <= stop + 1e-9]
    if len(grid) < 2:
        raise ValueError("volume resampling produced too few rows")

    output: list[dict[str, float | None]] = [
        {"injected_volume_ml": float(volume)} for volume in grid
    ]
    for column in SENSOR_COLUMNS:
        observed_x = []
        observed_y = []
        for volume, _, row in samples:
            value = _finite_float(row.get(column))
            if value is None:
                continue
            observed_x.append(volume)
            observed_y.append(value)
        if len(observed_x) < 2:
            for target in output:
                target[column] = None
            continue

        x = np.asarray(observed_x, dtype=float)
        y = np.asarray(observed_y, dtype=float)
        unique_x, inverse = np.unique(x, return_inverse=True)
        collapsed = np.zeros(len(unique_x), dtype=float)
        if column == "visible_H_mean":
            radians = np.deg2rad(y)
            sin_values = np.zeros(len(unique_x), dtype=float)
            cos_values = np.zeros(len(unique_x), dtype=float)
            for group in range(len(unique_x)):
                mask = inverse == group
                sin_values[group] = float(np.mean(np.sin(radians[mask])))
                cos_values[group] = float(np.mean(np.cos(radians[mask])))
            unwrapped = np.unwrap(np.arctan2(sin_values, cos_values))
            interpolated = np.rad2deg(
                np.interp(grid, unique_x, unwrapped)
            ) % 360.0
        else:
            for group in range(len(unique_x)):
                collapsed[group] = float(np.median(y[inverse == group]))
            interpolated = np.interp(grid, unique_x, collapsed)
        for target, value in zip(output, interpolated):
            target[column] = float(value)

    source_indices = []
    for volume in grid:
        position = int(np.searchsorted(volumes, volume, side="left"))
        candidates = [max(0, min(position, len(volumes) - 1))]
        if position > 0:
            candidates.append(position - 1)
        nearest = min(candidates, key=lambda item: abs(float(volumes[item]) - volume))
        source_indices.append(int(samples[nearest][1]))
    return output, source_indices


def load_type_conditioned_sensor_model(
    path: str | Path | None,
) -> dict[str, Any] | None:
    """Load the trusted local post-run endpoint ranker artifact."""

    if path is None:
        return None
    model_path = Path(path)
    if not str(model_path).strip() or not model_path.exists():
        return None
    with model_path.open("rb") as handle:
        artifact = pickle.load(handle)
    if not isinstance(artifact, dict) or artifact.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError(f"unsupported type-conditioned sensor model: {model_path}")
    models = artifact.get("models")
    if not isinstance(models, Mapping) or not models:
        raise ValueError(f"type-conditioned sensor model has no estimators: {model_path}")
    return artifact


def sensor_coverage(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"visible": 0.0, "thermal": 0.0}
    visible = 0
    thermal = 0
    for row in rows:
        visible_values = [_finite_float(row.get(key)) for key in SENSOR_COLUMNS[:3]]
        if all(value is not None for value in visible_values):
            visible += 1
        p50 = _finite_float(row.get("thermal_raw_roi_p50"))
        p95 = _finite_float(row.get("thermal_raw_roi_p95"))
        if (
            p50 is not None
            and p95 is not None
            and abs(p50) > 1e-12
            and abs(p95) > 1e-12
            and p95 >= p50
        ):
            thermal += 1
    return {
        "visible": visible / len(rows),
        "thermal": thermal / len(rows),
    }


def _prepare_runtime_variants(
    rows: Sequence[Mapping[str, Any]],
    entry: Mapping[str, Any],
) -> list[tuple[Sequence[Mapping[str, Any]], list[int], str]]:
    coverage = sensor_coverage(rows)
    if coverage["visible"] < 0.80:
        raise ValueError(
            f"insufficient visible sensor coverage: {coverage['visible']:.3f}"
        )
    if coverage["thermal"] < 0.80:
        raise ValueError(
            f"insufficient thermal sensor coverage: {coverage['thermal']:.3f}"
        )
    target_step = _finite_float(entry.get("training_median_positive_volume_step_ml"))
    valid_volumes = [
        value
        for row in rows
        if (value := _finite_float(row.get("injected_volume_ml"))) is not None
    ]
    if target_step is None or target_step <= 0 or len(valid_volumes) < 2:
        return [(rows, list(range(len(rows))), "native_rows")]
    volume_range = max(valid_volumes) - min(valid_volumes)
    observed_dense_step = volume_range / max(1, len(valid_volumes) - 1)
    if observed_dense_step >= target_step * 0.70:
        return [(rows, list(range(len(rows))), "native_rows")]
    variants = []
    for phase in (0.0, 0.5):
        prepared, source_indices = resample_sensor_rows_by_volume(
            rows, target_step, phase_fraction=phase
        )
        variants.append(
            (
                prepared,
                source_indices,
                f"volume_resampled_{target_step:.6f}ml_phase_{phase:.2f}",
            )
        )
    return variants


def _transform_design(candidates: Sequence[Any], config: Mapping[str, Any]) -> np.ndarray:
    indices = tuple(int(index) for index in config.get("feature_indices") or ())
    if not indices:
        raise ValueError("endpoint model has no active sensor features")
    values = np.asarray(
        [[candidate.features[index] for index in indices] for candidate in candidates],
        dtype=float,
    )
    transform = str(config.get("feature_transform") or "raw")
    if transform == "signed_log1p":
        values = np.sign(values) * np.log1p(np.abs(values))
    elif transform != "raw":
        raise ValueError(f"unsupported endpoint feature transform: {transform}")
    if not np.all(np.isfinite(values)):
        raise ValueError("endpoint sensor features contain non-finite values")
    return values


def _candidate_scores(
    estimator: Any,
    candidates: Sequence[Any],
    config: Mapping[str, Any],
) -> np.ndarray:
    design = _transform_design(candidates, config)
    family = str(config.get("family") or "")
    if family in {"pls", "kernel_ridge_rbf"}:
        scores = estimator.predict(design)
    elif hasattr(estimator, "decision_function"):
        scores = estimator.decision_function(design)
    elif hasattr(estimator, "predict_proba"):
        scores = np.asarray(estimator.predict_proba(design), dtype=float)[:, 1]
    else:
        raise ValueError(f"endpoint estimator cannot score candidates: {family}")
    result = np.asarray(scores, dtype=float).reshape(-1)
    if len(result) != len(candidates) or not np.all(np.isfinite(result)):
        raise ValueError("endpoint estimator returned invalid candidate scores")
    return result


def _normalize_scores(scores: Sequence[float], method: str) -> np.ndarray:
    values = np.asarray(scores, dtype=float)
    if method == "zscore":
        deviation = float(np.std(values))
        if deviation <= 1e-12:
            return np.zeros_like(values)
        return (values - float(np.mean(values))) / deviation
    if method == "rank":
        order = np.argsort(np.argsort(values, kind="stable"), kind="stable")
        return order.astype(float) / max(1, len(values) - 1)
    raise ValueError(f"unsupported endpoint score normalization: {method}")


def _aggregate_boundary(
    candidates: Sequence[Any],
    scores: Sequence[float],
    config: Mapping[str, Any],
) -> tuple[int, int, float]:
    values = np.asarray(scores, dtype=float)
    order = sorted(
        range(len(candidates)), key=lambda index: (-float(values[index]), index)
    )
    top_index = order[0]
    top_k = int(config.get("top_k") or 0)
    selected = order if top_k == 0 else order[: min(top_k, len(order))]
    temperature = float(config.get("softmax_temperature") or 1.0)
    if temperature <= 0:
        raise ValueError("endpoint softmax temperature must be positive")
    selected_scores = np.asarray([values[index] for index in selected], dtype=float)
    centered = (selected_scores - float(np.max(selected_scores))) / temperature
    weights = np.exp(centered)
    weights /= float(np.sum(weights))
    centroid = float(
        np.dot(
            weights,
            np.asarray([candidates[index].boundary for index in selected], dtype=float),
        )
    )
    top_weight = float(config.get("top_candidate_weight") or 0.0)
    boundary = int(
        round(
            top_weight * candidates[top_index].boundary
            + (1.0 - top_weight) * centroid
        )
    )
    margin = (
        float(values[order[0]] - values[order[1]])
        if len(order) > 1
        else float("inf")
    )
    confirmation = int(getattr(candidates[top_index], "confirmation", boundary))
    return boundary, confirmation, margin


def _combined_candidate_scores(
    estimator_entry: Mapping[str, Any],
    candidates: Sequence[Any],
    config: Mapping[str, Any],
) -> np.ndarray:
    scores = np.zeros(len(candidates), dtype=float)
    normalization = str(config.get("score_normalization") or "zscore")
    global_weight = float(config.get("global_weight") or 0.0)

    global_estimator = estimator_entry.get("global_estimator")
    if global_weight > 0.0:
        if global_estimator is None:
            raise ValueError("endpoint global estimator is missing")
        scores += global_weight * _normalize_scores(
            _candidate_scores(global_estimator, candidates, config), normalization
        )

    if global_weight < 1.0:
        type_estimator = estimator_entry.get("type_estimator")
        if type_estimator is None:
            raise ValueError("endpoint type estimator is missing")
        scores += (1.0 - global_weight) * _normalize_scores(
            _candidate_scores(type_estimator, candidates, config), normalization
        )
    return scores


def _predict_analysis_variant(
    artifact: Mapping[str, Any],
    entry: Mapping[str, Any],
    config: Mapping[str, Any],
    analysis_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = generate_union_candidates(analysis_rows)
    if not candidates:
        raise ValueError("recorded sensor sequence produced no endpoint candidates")
    fold_entries = entry.get("fold_estimators")
    fold_volumes: list[float] = []
    fold_frames: list[int] = []
    confirmations: list[int] = []
    if isinstance(fold_entries, Sequence) and fold_entries:
        for fold_entry in fold_entries:
            if not isinstance(fold_entry, Mapping):
                raise ValueError("invalid endpoint fold estimator")
            fold_scores = _combined_candidate_scores(fold_entry, candidates, config)
            fold_frame, confirmation, _ = _aggregate_boundary(
                candidates, fold_scores, config
            )
            fold_frame = max(0, min(fold_frame, len(analysis_rows) - 1))
            fold_volume = _finite_float(
                analysis_rows[fold_frame].get("injected_volume_ml")
            )
            if fold_volume is None or fold_volume <= 0:
                raise ValueError("fold-selected endpoint row has no positive injected volume")
            fold_frames.append(fold_frame)
            fold_volumes.append(fold_volume)
            confirmations.append(confirmation)
        fold_median_volume = float(np.median(np.asarray(fold_volumes, dtype=float)))
        fold_median_frame = min(
            fold_frames,
            key=lambda index: abs(
                float(
                    _finite_float(analysis_rows[index].get("injected_volume_ml"))
                    or 0.0
                )
                - fold_median_volume
            ),
        )
        fold_sd_ml = (
            float(np.std(np.asarray(fold_volumes, dtype=float), ddof=1))
            if len(fold_volumes) > 1
            else 0.0
        )
        deployment_strategy = str(
            artifact.get("deployment_strategy")
            or "median_of_12_leave_one_run_out_rankers"
        )
        if deployment_strategy == "single_full_fit_with_12_fold_dispersion":
            full_scores = _combined_candidate_scores(entry, candidates, config)
            frame, confirmation, _ = _aggregate_boundary(
                candidates, full_scores, config
            )
            frame = max(0, min(frame, len(analysis_rows) - 1))
            predicted_volume = _finite_float(
                analysis_rows[frame].get("injected_volume_ml")
            )
            if predicted_volume is None or predicted_volume <= 0:
                raise ValueError("full-fit endpoint row has no positive injected volume")
        else:
            predicted_volume = fold_median_volume
            frame = fold_median_frame
            confirmation = int(round(float(np.median(confirmations))))
        return {
            "predicted_volume": float(predicted_volume),
            "frame": frame,
            "confirmation": confirmation,
            "fold_sd_ml": fold_sd_ml,
            "fold_count": len(fold_volumes),
            "deployment_strategy": deployment_strategy,
        }

    scores = _combined_candidate_scores(entry, candidates, config)
    frame, confirmation, margin = _aggregate_boundary(candidates, scores, config)
    frame = max(0, min(frame, len(analysis_rows) - 1))
    predicted_volume = _finite_float(
        analysis_rows[frame].get("injected_volume_ml")
    )
    if predicted_volume is None or predicted_volume <= 0:
        raise ValueError("selected endpoint row has no positive injected volume")
    finite_margin = margin if math.isfinite(margin) else 20.0
    return {
        "predicted_volume": float(predicted_volume),
        "frame": frame,
        "confirmation": confirmation,
        "fold_sd_ml": 0.0,
        "fold_count": 0,
        "deployment_strategy": "single_full_fit_ranker",
        "margin_confidence": float(
            1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, finite_margin))))
        ),
    }


def predict_type_conditioned_sensor_equivalence(
    artifact: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    titration_type: str,
) -> dict[str, Any]:
    """Select one endpoint from a completed sensor time series."""

    if artifact.get("artifact_type") != ARTIFACT_TYPE:
        raise ValueError("unsupported type-conditioned sensor artifact")
    if not rows:
        raise ValueError("endpoint prediction requires recorded rows")
    type_key = str(titration_type or "").strip()
    entry = (artifact.get("models") or {}).get(type_key)
    if not isinstance(entry, Mapping):
        raise ValueError(f"no endpoint model for titration_type={type_key!r}")
    config = entry.get("config")
    if not isinstance(config, Mapping):
        raise ValueError(f"endpoint model has no configuration: {type_key}")

    variants = _prepare_runtime_variants(rows, entry)
    results = [
        (
            _predict_analysis_variant(artifact, entry, config, analysis_rows),
            analysis_rows,
            source_indices,
            sampling_mode,
        )
        for analysis_rows, source_indices, sampling_mode in variants
    ]
    predicted_volume = float(
        np.mean([result[0]["predicted_volume"] for result in results])
    )
    representative = min(
        results,
        key=lambda result: abs(result[0]["predicted_volume"] - predicted_volume),
    )
    result, analysis_rows, source_indices, _ = representative
    frame = int(result["frame"])
    confirmation = int(result["confirmation"])
    phase_sd_ml = (
        float(np.std([item[0]["predicted_volume"] for item in results], ddof=1))
        if len(results) > 1
        else 0.0
    )
    instability_ml = max(
        phase_sd_ml,
        max(float(item[0]["fold_sd_ml"]) for item in results),
    )
    confidence = (
        float(result["margin_confidence"])
        if result.get("margin_confidence") is not None and len(results) == 1
        else float(1.0 / (1.0 + max(0.0, instability_ml)))
    )
    sampling_mode = "+".join(item[3] for item in results)
    strategy_evidence = (
        f"strategy={result['deployment_strategy']}; folds={result['fold_count']}; "
        f"fold_or_phase_sd_ml={instability_ml:.6f}; sampling={sampling_mode}"
    )
    source_frame = source_indices[max(0, min(frame, len(source_indices) - 1))]

    model_key = str(artifact.get("model_key") or "type-conditioned-sensor-endpoint-v1")
    return {
        "predicted_equivalence_volume_ml": round(predicted_volume, 6),
        "predicted_equivalence_confidence": round(confidence, 6),
        "predicted_equivalence_source": PREDICTION_SOURCE,
        "predicted_equivalence_evidence": (
            f"{type_key} {config.get('family')} sensor sequence ranker; "
            f"candidate_frame={frame}; confirmation_frame={confirmation}; "
            f"{strategy_evidence}"
        ),
        "candidate_index": source_frame,
        "model_key": model_key,
    }
