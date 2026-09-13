#!/usr/bin/env python3
"""Sensor-sequence endpoint localization with outer run validation.

Candidate frames are generated from causal sensor history.  Volumes and
ground truth are attached only after a frame has been generated/selected:
they are never used for smoothing, candidate generation, or model features.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import resource
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

for _variable in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ[_variable] = "1"

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.ml_curve_equivalence import _to_float, run_level_metrics  # noqa: E402
from auto_titrator.ml_typewise_eval import CsvRun, load_runs  # noqa: E402

DEFAULT_INPUT_DIR = Path("머신러닝용 파일모음")
DEFAULT_OUTPUT_DIR = Path("data/ml/exploratory_sensor_sequence_search")
SEEDS = (42, 1729, 20260728)
BASELINE_MAPE_PERCENT = 13.901184

FORBIDDEN_TOKENS = (
    "volume", "concentration", "equivalence", "endpoint", "progress",
    "fraction", "position", "frame", "time", "elapsed", "duration",
    "label", "target", "actual", "predicted", "distance", "remaining",
)
MODEL_FEATURE_NAMES = (
    "abs_color_shift_circular_x", "abs_color_shift_circular_y", "abs_color_shift_value",
    "abs_thermal_shift_p50", "abs_thermal_shift_spread", "color_baseline_departure",
    "thermal_baseline_departure", "color_shift_norm", "thermal_shift_norm",
    "cross_sensor_agreement", "transition_salience", "thermal_available",
    "persistent_departure",
    "color_terminal_aligned_shift", "color_terminal_direction_cosine",
    "color_state_coordinate", "color_orthogonal_departure",
    "thermal_terminal_aligned_shift", "thermal_terminal_direction_cosine",
    "thermal_state_coordinate", "thermal_orthogonal_departure",
)


@dataclass(frozen=True, order=True)
class Arm:
    name: str
    model: str
    feature_group: str
    transform: str
    baseline_frames: int
    window_frames: int
    regularization: float


@dataclass(frozen=True)
class TransitionCandidate:
    boundary_frame: int
    confirmation_frame: int
    features: tuple[float, ...]


ARMS = (
    Arm(
        "pairwise_sensor_context_log", "pairwise_logistic", "sensor_context",
        "signed_log1p", 12, 16, 0.30,
    ),
)

FEATURE_GROUP_INDICES = {
    "all": tuple(range(13)),
    "separate": tuple(range(10)),
    "color": (0, 1, 2, 5, 7),
    "sensor_context": tuple(range(10)) + tuple(range(13, 21)),
}

SOFT_CENTROID_TEMPERATURE = 1.0
TOP_CENTROID_BLEND = 0.5


def _number(value: Any) -> float | None:
    result = _to_float(value)
    return None if result is None else float(result)


def forbidden_features(columns: Iterable[str]) -> list[str]:
    return sorted(
        str(column) for column in columns
        if any(token in str(column).lower() for token in FORBIDDEN_TOKENS)
    )


def audit_model_features(columns: Iterable[str]) -> dict[str, Any]:
    columns = list(columns)
    blocked = forbidden_features(columns)
    return {
        "feature_count": len(columns),
        "feature_names": columns,
        "forbidden_features_found": blocked,
        "passed": not blocked and 10 <= len(columns) <= 20,
    }


def _causal_fill(values: np.ndarray) -> np.ndarray:
    """Forward-fill from past observations without consulting future rows."""

    result = values.astype(float, copy=True)
    for column in range(result.shape[1]):
        previous = 0.0
        for row in range(len(result)):
            if np.isfinite(result[row, column]):
                previous = float(result[row, column])
            else:
                result[row, column] = previous
    return result


def sensor_matrix(rows: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    """Return circular-HSV plus thermal signals without consulting metadata."""

    hue = np.asarray([_number(row.get("visible_H_mean")) for row in rows], dtype=float)
    saturation = np.asarray([_number(row.get("visible_S_mean")) for row in rows], dtype=float)
    value = np.asarray([_number(row.get("visible_V_mean")) for row in rows], dtype=float)
    # CSV hue is already expressed in degrees on [0, 360); S and V are [0, 1].
    radians = np.deg2rad(hue)
    color = np.column_stack(
        (saturation * np.cos(radians), saturation * np.sin(radians), value)
    )
    p50 = np.asarray([_number(row.get("thermal_raw_roi_p50")) for row in rows], dtype=float)
    p95 = np.asarray([_number(row.get("thermal_raw_roi_p95")) for row in rows], dtype=float)
    thermal = np.column_stack((p50, p95 - p50))
    thermal_valid = np.all(np.isfinite(thermal), axis=1) & np.any(np.abs(thermal) > 1e-12, axis=1)
    thermal[~thermal_valid] = np.nan
    return _causal_fill(np.column_stack((color, thermal))), thermal_valid


def generate_transition_candidates(
    rows: Sequence[Mapping[str, Any]], *, baseline_frames: int = 12,
    window_frames: int = 16, threshold: float = 0.2,
    confirmation_frames: int = 2, refractory_frames: int = 3,
    max_candidates: int = 64, modality: str = "fusion",
) -> list[TransitionCandidate]:
    """Generate bounded transition boundaries using current/past frames only.

    A candidate is emitted after a local trailing-window shift peak is
    confirmed.  Its frame is backdated to the first frame of the shifted
    window, rather than the later confirmation frame.
    """

    if baseline_frames < 3 or window_frames < 2 or confirmation_frames < 1:
        raise ValueError("invalid causal window configuration")
    if modality not in {"color", "fusion"}:
        raise ValueError(f"unknown modality: {modality}")
    matrix, thermal_valid = sensor_matrix(rows)
    first_score_frame = baseline_frames + 2 * window_frames - 1
    if len(matrix) <= first_score_frame + confirmation_frames:
        return []
    baseline = np.median(matrix[:baseline_frames], axis=0)
    mad = np.median(np.abs(matrix[:baseline_frames] - baseline), axis=0) * 1.4826
    # HSV is normalized; thermal fields are raw uint16-like counts.  Floors
    # below one raw count turn quantization into a false high-confidence event.
    scale = np.maximum(mad, np.asarray((0.02, 0.02, 0.02, 3.0, 3.0)))
    thermal_baseline_available = bool(
        modality == "fusion" and np.mean(thermal_valid[:baseline_frames]) >= 0.75
    )
    scored: list[tuple[int, float, float, tuple[float, ...]]] = []
    for frame in range(first_score_frame, len(matrix)):
        before = np.median(matrix[frame - 2 * window_frames + 1:frame - window_frames + 1], axis=0)
        after = np.median(matrix[frame - window_frames + 1:frame + 1], axis=0)
        shift = (after - before) / scale
        departure = (after - baseline) / scale
        thermal_available = bool(
            thermal_baseline_available
            and np.mean(thermal_valid[frame - 2 * window_frames + 1:frame + 1]) >= 0.75
        )
        color_shift = float(np.linalg.norm(shift[:3]) / np.sqrt(3.0))
        thermal_shift = (
            float(np.linalg.norm(shift[3:]) / np.sqrt(2.0)) if thermal_available else 0.0
        )
        color_departure = float(np.linalg.norm(departure[:3]) / np.sqrt(3.0))
        thermal_departure = (
            float(np.linalg.norm(departure[3:]) / np.sqrt(2.0)) if thermal_available else 0.0
        )
        salience = max(color_shift, thermal_shift)
        agreement_denominator = 2.0 if thermal_available else 1.0
        agreement = ((color_shift > 0.7) + (thermal_available and thermal_shift > 0.7)) / agreement_denominator
        persistent = max(color_departure, thermal_departure)
        features = tuple(float(value) for value in (
            abs(shift[0]), abs(shift[1]), abs(shift[2]),
            abs(shift[3]) if thermal_available else 0.0,
            abs(shift[4]) if thermal_available else 0.0,
            color_departure, thermal_departure, color_shift, thermal_shift, agreement,
            salience, float(thermal_available), persistent,
        ))
        scored.append((frame, salience, persistent, features))

    candidates: list[TransitionCandidate] = []
    last_boundary = -refractory_frames
    for cursor in range(confirmation_frames, len(scored)):
        peak_index = cursor - confirmation_frames
        frame, salience, persistent, features = scored[peak_index]
        neighborhood = scored[max(0, cursor - 2 * confirmation_frames):cursor + 1]
        lasting_departure = min(item[2] for item in scored[peak_index:cursor + 1])
        if salience < threshold or persistent < threshold or salience < max(item[1] for item in neighborhood):
            continue
        boundary = frame - window_frames + 1
        if boundary - last_boundary < refractory_frames:
            continue
        candidate_features = list(features)
        candidate_features[-1] = float(lasting_departure)
        candidates.append(TransitionCandidate(boundary, scored[cursor][0], tuple(candidate_features)))
        last_boundary = boundary
    return candidates[:max_candidates]


def deterministic_select_frame(candidates: Sequence[TransitionCandidate]) -> int:
    """Causal rule arm: first persistent, cross-sensor-supported boundary."""

    if not candidates:
        raise ValueError("no transition candidates")
    eligible = [
        candidate for candidate in candidates
        if candidate.features[10] >= 1.0 and candidate.features[12] >= 1.0
        and (not candidate.features[11] or candidate.features[9] >= 0.5)
    ]
    return (eligible[0] if eligible else candidates[0]).boundary_frame


def _make_model(arm: Arm, seed: int):
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if arm.model != "pairwise_logistic":
        raise ValueError(f"unknown model: {arm.model}")
    return make_pipeline(
        StandardScaler(),
        LogisticRegression(
            C=arm.regularization, class_weight="balanced", max_iter=2000,
            random_state=seed, solver="liblinear", fit_intercept=False,
        ),
    )


def _arm_features(
    candidates: Sequence[TransitionCandidate], arm: Arm,
) -> np.ndarray:
    try:
        indices = FEATURE_GROUP_INDICES[arm.feature_group]
    except KeyError as exc:
        raise ValueError(f"unknown feature group: {arm.feature_group}") from exc
    values = np.asarray([candidate.features for candidate in candidates], dtype=float)
    values = values[:, indices]
    if arm.transform == "signed_log1p":
        return np.sign(values) * np.log1p(np.abs(values))
    if arm.transform == "raw":
        return values
    raise ValueError(f"unknown feature transform: {arm.transform}")


def _candidate_sets(runs: Sequence[CsvRun], arm: Arm) -> dict[str, list[TransitionCandidate]]:
    result = {}
    for run in runs:
        candidates = generate_transition_candidates(
            run.rows, baseline_frames=arm.baseline_frames,
            window_frames=arm.window_frames, modality="fusion",
        )
        result[str(run.path)] = _augment_sensor_context(
            run.rows, candidates, baseline_frames=arm.baseline_frames,
            window_frames=arm.window_frames,
        )
    empty = [path for path, candidates in result.items() if not candidates]
    if empty:
        raise ValueError(f"runs contain no transition candidates: {empty}")
    return result


def _augment_sensor_context(
    rows: Sequence[Mapping[str, Any]], candidates: Sequence[TransitionCandidate],
    *, baseline_frames: int, window_frames: int,
) -> list[TransitionCandidate]:
    """Add complete-record sensor-state geometry without using experiment metadata."""

    matrix, thermal_valid = sensor_matrix(rows)
    initial = np.median(matrix[:baseline_frames], axis=0)
    final = np.median(matrix[-baseline_frames:], axis=0)
    mad = np.median(np.abs(matrix[:baseline_frames] - initial), axis=0) * 1.4826
    scale = np.maximum(mad, np.asarray((0.02, 0.02, 0.02, 3.0, 3.0)))
    direction = (final - initial) / scale
    thermal_record_available = bool(
        np.mean(thermal_valid[:baseline_frames]) >= 0.75
        and np.mean(thermal_valid[-baseline_frames:]) >= 0.75
    )
    augmented: list[TransitionCandidate] = []
    for candidate in candidates:
        boundary = candidate.boundary_frame
        before = np.median(matrix[max(0, boundary - window_frames):boundary], axis=0)
        after = np.median(
            matrix[boundary:min(len(matrix), boundary + window_frames)], axis=0
        )
        shift = (after - before) / scale
        departure = (after - initial) / scale
        extras: list[float] = []
        for modality_index, modality_slice in enumerate((slice(0, 3), slice(3, 5))):
            modality_allowed = modality_index == 0 or (
                thermal_record_available and bool(candidate.features[11])
            )
            if not modality_allowed:
                extras.extend((0.0, 0.0, 0.0, 0.0))
                continue
            modality_direction = direction[modality_slice]
            modality_shift = shift[modality_slice]
            modality_departure = departure[modality_slice]
            direction_squared = float(np.dot(modality_direction, modality_direction))
            direction_norm = float(np.sqrt(direction_squared))
            shift_norm = float(np.linalg.norm(modality_shift))
            coordinate = float(
                np.dot(modality_departure, modality_direction)
                / (direction_squared + 1e-9)
            )
            extras.extend((
                float(np.dot(modality_shift, modality_direction) / (direction_norm + 1e-9)),
                float(
                    np.dot(modality_shift, modality_direction)
                    / (shift_norm * direction_norm + 1e-9)
                ),
                coordinate,
                float(
                    np.linalg.norm(modality_departure - coordinate * modality_direction)
                    / np.sqrt(len(modality_direction))
                ),
            ))
        augmented.append(TransitionCandidate(
            candidate.boundary_frame, candidate.confirmation_frame,
            candidate.features + tuple(extras),
        ))
    return augmented


def _labels(run: CsvRun, candidates: Sequence[TransitionCandidate]) -> list[int]:
    actual = float(run.theoretical_equivalence_volume_ml)
    errors = [
        abs(float(run.rows[candidate.boundary_frame]["injected_volume_ml"]) - actual)
        for candidate in candidates
    ]
    best = min(range(len(candidates)), key=lambda index: (errors[index], index))
    return [int(index == best) for index in range(len(candidates))]


def _fit_ranker(
    train_runs: Sequence[CsvRun], candidate_sets: Mapping[str, Sequence[TransitionCandidate]],
    arm: Arm, seed: int,
):
    model = _make_model(arm, seed)
    x: list[np.ndarray] = []
    y: list[int] = []
    sample_weight: list[float] = []
    for run in train_runs:
        candidates = candidate_sets[str(run.path)]
        labels = _labels(run, candidates)
        positive = labels.index(1)
        run_features = _arm_features(candidates, arm)
        negatives = max(1, len(candidates) - 1)
        for index in range(len(candidates)):
            if index == positive:
                continue
            difference = run_features[positive] - run_features[index]
            x.extend((difference, -difference))
            y.extend((1, 0))
            sample_weight.extend((0.5 / negatives, 0.5 / negatives))
    model.fit(
        np.asarray(x, dtype=float), np.asarray(y, dtype=int),
        logisticregression__sample_weight=np.asarray(sample_weight, dtype=float),
    )
    return model


def _select_frame(model: Any, arm: Arm, candidates: Sequence[TransitionCandidate]) -> int:
    scores = model.decision_function(_arm_features(candidates, arm))
    selected = max(range(len(candidates)), key=lambda index: (float(scores[index]), -index))
    return candidates[selected].boundary_frame


def _standardized_scores(model: Any, arm: Arm, candidates: Sequence[TransitionCandidate]) -> np.ndarray:
    scores = np.asarray(model.decision_function(_arm_features(candidates, arm)), dtype=float)
    deviation = float(np.std(scores))
    if deviation <= 1e-12:
        return np.zeros_like(scores)
    return (scores - float(np.mean(scores))) / deviation


def _predict_frame_ensemble(
    train_runs: Sequence[CsvRun], test_run: CsvRun,
    sets_by_arm: Mapping[str, Mapping[str, Sequence[TransitionCandidate]]],
    arms: Sequence[Arm], seed: int,
) -> tuple[int, int, float]:
    """Rank candidates and stabilize the strongest event with a soft centroid."""

    reference = list(sets_by_arm[arms[0].name][str(test_run.path)])
    reference_frames = [candidate.boundary_frame for candidate in reference]
    score_vectors: list[np.ndarray] = []
    for arm in arms:
        candidates = list(sets_by_arm[arm.name][str(test_run.path)])
        if [candidate.boundary_frame for candidate in candidates] != reference_frames:
            raise ValueError("fixed ensemble members must score identical candidate frames")
        model = _fit_ranker(train_runs, sets_by_arm[arm.name], arm, seed)
        raw_scores = np.asarray(
            model.decision_function(_arm_features(candidates, arm)), dtype=float
        )
        score_vectors.append(
            raw_scores if len(arms) == 1 else _standardized_scores(model, arm, candidates)
        )
    ensemble_scores = np.mean(np.vstack(score_vectors), axis=0)
    order = sorted(
        range(len(reference)),
        key=lambda index: (-float(ensemble_scores[index]), index),
    )
    selected = reference[order[0]]
    centered = (
        ensemble_scores - float(np.max(ensemble_scores))
    ) / SOFT_CENTROID_TEMPERATURE
    weights = np.exp(centered)
    weights /= float(np.sum(weights))
    centroid_frame = float(np.dot(
        weights,
        np.asarray([candidate.boundary_frame for candidate in reference], dtype=float),
    ))
    stabilized_frame = int(round(
        TOP_CENTROID_BLEND * selected.boundary_frame
        + (1.0 - TOP_CENTROID_BLEND) * centroid_frame
    ))
    stabilized_frame = max(0, min(stabilized_frame, len(test_run.rows) - 1))
    margin = (
        float(ensemble_scores[order[0]] - ensemble_scores[order[1]])
        if len(order) > 1 else float("inf")
    )
    return stabilized_frame, selected.confirmation_frame, margin


def _metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = dict(run_level_metrics(rows))
    metrics["mape_percent"] = metrics["mae_percent_of_equivalence"]
    metrics["max_absolute_error_ml"] = round(max(float(row["absolute_error_ml"]) for row in rows), 6)
    return metrics


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    columns = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (list, dict)) else value for key, value in row.items()
            })


def evaluate_runs(
    runs: Sequence[CsvRun], *, output_dir: str | Path | None = None,
    seeds: Sequence[int] = SEEDS, arms: Sequence[Arm] = ARMS,
    expected_run_count: int = 12,
) -> dict[str, Any]:
    started = time.perf_counter()
    if len(runs) != expected_run_count:
        raise ValueError(f"expected exactly {expected_run_count} existing runs, found {len(runs)}")
    if tuple(seeds) != SEEDS:
        raise ValueError(f"seed list must be exactly {SEEDS}")
    if len({str(run.path) for run in runs}) != len(runs):
        raise ValueError("run paths must be unique")
    if not arms:
        raise ValueError("arm set must not be empty")
    active_indices = sorted({
        index for arm in arms for index in FEATURE_GROUP_INDICES[arm.feature_group]
    })
    active_feature_names = tuple(MODEL_FEATURE_NAMES[index] for index in active_indices)
    feature_audit = audit_model_features(active_feature_names)
    if not feature_audit["passed"]:
        raise AssertionError(f"model feature leakage audit failed: {feature_audit}")
    sets_by_arm = {arm.name: _candidate_sets(runs, arm) for arm in arms}

    predictions: list[dict[str, Any]] = []
    per_seed: list[dict[str, Any]] = []
    for seed in seeds:
        seed_rows: list[dict[str, Any]] = []
        for test_run in runs:
            outer_train = [run for run in runs if run.path != test_run.path]
            frame, confirmation_frame, score_margin = _predict_frame_ensemble(
                outer_train, test_run, sets_by_arm, arms, seed
            )
            # The first volume access on the outer-test path occurs after the
            # sensor-based row localization is complete.
            predicted = _number(test_run.rows[frame].get("injected_volume_ml"))
            confirmation_volume = _number(
                test_run.rows[confirmation_frame].get("injected_volume_ml")
            )
            if predicted is None or confirmation_volume is None:
                raise ValueError("selected/confirmation frame has no audit mapping volume")
            actual = float(test_run.theoretical_equivalence_volume_ml)
            error = predicted - actual
            row = {
                "seed": seed, "run_path": str(test_run.path),
                "titration_type_audit_only": test_run.titration_type,
                "actual_equivalence_volume_ml": actual,
                "predicted_equivalence_volume_ml": round(predicted, 6),
                "selected_frame_audit_only": frame,
                "signed_error_ml": round(error, 6),
                "absolute_error_ml": round(abs(error), 6),
                "absolute_error_percent_of_equivalence": round(abs(error) / actual * 100.0, 6),
                "model_variant": "fixed_sensor_context_soft_centroid_ranker",
                "ensemble_members": [arm.name for arm in arms],
                "top_two_score_margin_audit_only": round(score_margin, 9),
                "confirmation_frame_audit_only": confirmation_frame,
                "confirmation_lag_ml_audit_only": round(confirmation_volume - predicted, 6),
                "selection_run_paths": [str(run.path) for run in outer_train],
            }
            predictions.append(row)
            seed_rows.append(row)
        per_seed.append({"seed": seed, **_metrics(seed_rows)})

    aggregate = []
    for metric in ("mae_ml", "rmse_ml", "mape_percent", "max_absolute_error_ml"):
        values = np.asarray([row[metric] for row in per_seed], dtype=float)
        aggregate.append({
            "metric": metric, "mean_across_seeds": round(float(np.mean(values)), 6),
            "std_across_seeds": round(float(np.std(values)), 6),
            "min_across_seeds": round(float(np.min(values)), 6),
            "max_across_seeds": round(float(np.max(values)), 6),
        })
    stratified = []
    for seed in seeds:
        seed_predictions = [row for row in predictions if row["seed"] == seed]
        types = sorted({str(row["titration_type_audit_only"]) for row in seed_predictions})
        for titration_type in types:
            type_rows = [
                row for row in seed_predictions
                if row["titration_type_audit_only"] == titration_type
            ]
            stratified.append({
                "seed": seed, "titration_type": titration_type, **_metrics(type_rows)
            })
    counts = Counter(row["model_variant"] for row in predictions)
    summary: dict[str, Any] = {
        "schema_version": "exploratory_sensor_sequence_outer_loro_v2",
        "claim_scope": "exploratory_development_analysis_not_independent_external_validation",
        "prediction_scope": "complete_record_sensor_sequence_endpoint_localization",
        "run_count": len(runs), "seeds": list(seeds),
        "seed_policy": "all prescribed seeds reported; no seed selection",
        "split": {"outer": "leave_one_run_out", "inner": "none_fixed_model", "outer_test_labels_used_for_selection": False},
        "sequence_policy": "local candidates use ordered sensor windows; sensor-state context and final ranking use the complete recorded sequence",
        "model_input_policy": "fixed sensor-context ranker; volume/truth/type/concentration/time/progress metadata excluded",
        "prediction_aggregation": {
            "method": "equal blend of strongest candidate and softmax candidate centroid",
            "softmax_temperature": SOFT_CENTROID_TEMPERATURE,
            "strongest_candidate_weight": TOP_CENTROID_BLEND,
            "candidate_centroid_weight": 1.0 - TOP_CENTROID_BLEND,
        },
        "leakage_audit": {**feature_audit, "test_volume_access": "only after selected frame", "training_volume_access": "candidate labels only"},
        "arms": [asdict(arm) for arm in arms],
        "per_seed_metrics": per_seed, "stratified_metrics_audit_only": stratified,
        "aggregate_robustness": aggregate,
        "outer_predictions": predictions,
        "selection_counts": [{"model_variant": name, "count": count} for name, count in sorted(counts.items())],
        "baseline_comparison": {
            "prior_strict_search_mape_percent": BASELINE_MAPE_PERCENT,
            "new_fixed_model_outer_loro_mape_percent": next(
                row["mean_across_seeds"] for row in aggregate
                if row["metric"] == "mape_percent"
            ),
            "acceptance_passed": next(
                row["mean_across_seeds"] for row in aggregate
                if row["metric"] == "mape_percent"
            ) < BASELINE_MAPE_PERCENT,
        },
        "limitations": [
            "Only 12 development runs are available; there is no independent external validation set.",
            "Each chemistry/concentration condition has one run, so condition shift and run variation are confounded.",
            "Training labels use theoretical rather than independently observed endpoints.",
            "The sensor-state context and candidate centroid use the complete recorded sequence; the result is an endpoint estimate and is not a measured physical stop-volume error.",
            "Candidate boundaries are backdated from later confirmation frames, so boundary-volume error must not be reported as physical stop-volume error.",
            "The prescribed seeds produce identical deterministic predictions and are not independent observations.",
            "Fixed frame windows correspond to different physical durations when capture cadence changes.",
        ],
    }
    summary["resource_usage"] = {"evaluation_seconds": round(time.perf_counter() - started, 6), "max_rss_kb": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)}
    try:
        import sklearn
        sklearn_version = sklearn.__version__
    except Exception:
        sklearn_version = None
    summary["versions"] = {"python": platform.python_version(), "numpy": np.__version__, "scikit_learn": sklearn_version}
    if output_dir is not None:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        _write_csv(output / "outer_predictions.csv", predictions)
        _write_csv(output / "per_seed_metrics.csv", per_seed)
        _write_csv(output / "stratified_metrics.csv", stratified)
        _write_csv(output / "aggregate_robustness.csv", aggregate)
        _write_csv(output / "selection_counts.csv", summary["selection_counts"])
        _write_csv(output / "feature_manifest.csv", [{"feature": name} for name in active_feature_names])
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        report = [
            "# Sensor-sequence endpoint estimation", "",
            "**Development analysis only — not independent external validation.**", "",
            "- Outer validation: leave one complete run out",
            "- Model: fixed sensor-context pairwise ranker; no inner arm selection",
            "- Scope: endpoint estimation from the recorded sensor sequence",
            "- Candidate features: ordered sensor windows and sensor-state geometry; no volume-axis resampling/smoothing",
            f"- Active inputs: {len(active_feature_names)} interpretable morphology features; volume/truth/type excluded", "",
            "## Metrics", "", "| Seed | MAE (mL) | RMSE (mL) | MAPE (%) |", "|---:|---:|---:|---:|",
        ]
        report.extend(f"| {row['seed']} | {row['mae_ml']:.6f} | {row['rmse_ml']:.6f} | {row['mape_percent']:.6f} |" for row in per_seed)
        report.extend(["", "## Limitations", ""] + [f"- {item}" for item in summary["limitations"]])
        (output / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def evaluate_folder(input_dir: str | Path = DEFAULT_INPUT_DIR, *, output_dir: str | Path = DEFAULT_OUTPUT_DIR) -> dict[str, Any]:
    summary = evaluate_runs(load_runs(input_dir), output_dir=output_dir)
    summary["input_dir"] = str(input_dir)
    Path(output_dir, "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args(argv)
    summary = evaluate_folder(args.input_dir, output_dir=args.output_dir)
    print(json.dumps({"per_seed": summary["per_seed_metrics"], "aggregate": summary["aggregate_robustness"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
