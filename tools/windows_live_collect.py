#!/usr/bin/env python3
"""Windows-native Mini2 + visible-camera live feature collector.

This is the production path for the science-fair demo when Mini2 must run at
25 fps.  WSL/usbipd is useful for development, but the Mini2 raw UVC stream was
measured at ~9 fps there; Windows OpenCV reaches ~25 fps.

Example:

    py -3 tools\\windows_live_collect.py --frames 250 --mini2-index 0 --visible-index 1

The output CSV contains scalar features only.  Full 256x192 temperature
matrices remain in memory unless optional debug snapshots are requested.
"""

from __future__ import annotations

import argparse
import csv
import gc
import io
import importlib
import json
import math
import os
import pickle
import queue
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auto_titrator.camera import CameraConfig, UsbCamera  # noqa: E402
from auto_titrator.auto_stop import (  # noqa: E402
    ABSOLUTE_PUMP_MAX_RUN_TIME_S,
    ABSOLUTE_PUMP_MAX_VOLUME_ML,
    AUTO_STOP_CONFIRMATION_SECONDS,
    AUTO_STOP_MAX_VOLUME_ML,
    AbsolutePumpSafetyGuard,
    AutoStopDecision,
    ColorChangeAutoStopController,
)
from auto_titrator.chemistry import SUPPORTED_TITRATION_TYPES, calculate_theoretical_titration_result  # noqa: E402
from auto_titrator.chemical_constants import DEFAULT_IUPAC_CSV_PATH, lookup_iupac_pka  # noqa: E402
from auto_titrator.color_analysis import ColorFeatureExtractor, Roi, prefix_features, rgb_to_hsv  # noqa: E402
from auto_titrator.data_schema import DEFAULT_COLUMNS  # noqa: E402
from auto_titrator.equivalence_analysis import estimate_equivalence_point  # noqa: E402
from auto_titrator.ml_features import DERIVED_ML_COLUMNS, derive_ml_features, select_online_history_rows  # noqa: E402
from auto_titrator.ml_predict import load_optional_model, predict_row  # noqa: E402
from auto_titrator.type_conditioned_sensor_live_model import (  # noqa: E402
    load_type_conditioned_sensor_model,
    predict_type_conditioned_sensor_equivalence,
)
from auto_titrator.typewise_live_model import load_typewise_model, predict_typewise_equivalence  # noqa: E402
from auto_titrator.feature_history import FeatureSample  # noqa: E402
from auto_titrator.live_app import classify_status  # noqa: E402
from auto_titrator.mobile_bridge import MobileBridge, MobileBridgeError  # noqa: E402
from auto_titrator.mobile_protocol import MobileProtocolError  # noqa: E402
from auto_titrator.mini2_live import (  # noqa: E402
    MINI2_FRAME_RATE_HZ,
    MINI2_INPUT_FORMAT,
    MINI2_RAW_FRAME_BYTES,
    MINI2_UVC_HEIGHT,
    MINI2_UVC_WIDTH,
    ThermalConversionUnavailable,
    build_temperature_frame,
    extract_mini2_frame_parts,
    extract_temperature_features,
    load_raw_to_celsius_converter,
)
from auto_titrator.official_hikmicro import DLL_DIR_DEFAULT  # noqa: E402
from auto_titrator.pulse_control import (  # noqa: E402
    ABC_FIRMWARE_MAX_PULSE_STEPS,
    PulseControlConfig,
    PulseController,
    PulseObservation,
    PulseState,
)


BACKEND_NAMES = {
    "ANY": None,
    "AUTO": None,
    "DSHOW": "CAP_DSHOW",
    "DIRECTSHOW": "CAP_DSHOW",
    "MSMF": "CAP_MSMF",
    "MEDIAFOUNDATION": "CAP_MSMF",
}

DEFAULT_YOLO_VISIBLE_CLASSES = frozenset(
    {
        "cup",
        "bottle",
        "wine glass",
        "bowl",
        "vase",
        "beaker",
        "flask",
        "glass",
        "container",
    }
)

CSV_START_METADATA_KEYS = frozenset(
    {
        "titration_type",
        "sample_name",
        "sample_concentration_M",
        "sample_volume_ml",
        "sample_valence",
        "titrant_name",
        "titrant_concentration_M",
        "titrant_valence",
        "Ka",
        "Kb",
        "indicator",
        "chemistry_model",
        "chemistry_model_version",
        "constants_source",
        "constants_source_id",
        "constants_query",
        "constants_candidate_count",
        "constants_lookup_ambiguous",
        "constants_confirmation_status",
        "constants_warning",
        "selected_pka_type",
        "selected_pka_value",
        "selected_pka_temperature_c",
        "selected_pkb_value",
        "activity_model",
        "ionic_strength_m",
        "ionic_strength_label",
        "activity_warning",
        "theoretical_equivalence_pH",
        "selected_equivalence_step",
        "indicator_transition_low_pH",
        "indicator_transition_high_pH",
        "indicator_endpoint_volume_ml",
        "indicator_endpoint_offset_ml",
        "indicator_endpoint_confidence",
        "indicator_endpoint_warning",
        "standard_solution_uncertainty_note",
        "equivalence_formula",
        "calculated_theoretical_equivalence_volume_ml",
        "sample_concentration_from_theoretical_equivalence_M",
        "auto_stop_enabled",
        "auto_stop_confirmation_delay_s",
        "auto_stop_maximum_volume_ml",
        "auto_stop_pulse_enabled",
        "auto_stop_pulse_approach_score",
        "auto_stop_pulse_steps",
        "auto_stop_pulse_settle_time_s",
        "auto_stop_slow_stage_enabled",
        "auto_stop_slow_onset_score",
        "auto_stop_slow_onset_duration_s",
        "auto_stop_slow_rate_steps_per_s",
        "maximum_pump_rate_ml_per_s",
        "absolute_maximum_volume_ml",
        "absolute_maximum_run_time_s",
        "pulse_nominal_ml_per_step",
        "pulse_ml_per_step_upper_bound",
    }
)

REJECTED_YOLO_VISIBLE_CLASSES = frozenset({"person", "face", "hand"})
DEFAULT_LIVE_ML_MODEL = ""
DEFAULT_ENDPOINT_ML_MODEL = ROOT / "data" / "labeled" / "type-conditioned-sensor-endpoint-ranker.pkl"
DEFAULT_TYPEWISE_LIVE_ML_MODEL = ROOT / "data" / "labeled" / "typewise-current-volume-classifier.pkl"
ARDUINO_FULL_STEPS_PER_SECOND = 100.0
ENDPOINT_PULSE_DEFAULT_STEPS = 5
ENDPOINT_PULSE_MAX_STEPS = ABC_FIRMWARE_MAX_PULSE_STEPS


class CollectorInstanceLock:
    """Process-wide file lock preventing two collectors from opening cameras/COM."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise RuntimeError(
                "another Windows live collector is already running"
            ) from exc
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
ENDPOINT_PULSE_DEFAULT_SETTLE_S = 0.50
ENDPOINT_PULSE_DEFAULT_APPROACH_SCORE = 0.20
AUTO_STOP_BASELINE_START_TIMEOUT_S = 3.0
PREDICTION_MIN_USABLE_OBSERVATIONS = 8
PREDICTION_MIN_RECORDING_SPAN_S = 3.0
PREDICTION_STATUS_PENDING = "pending"
PREDICTION_STATUS_AVAILABLE = "available"
PREDICTION_STATUS_WITHHELD = "withheld"
PREDICTION_STATUS_UNAVAILABLE = "unavailable"
FINAL_PREDICTION_FIELDS = (
    "predicted_equivalence_volume_ml",
    "sample_concentration_from_predicted_equivalence_M",
    "predicted_sample_concentration_error_percent",
    "predicted_equivalence_pH",
    "predicted_equivalence_pH_model",
    "predicted_equivalence_pH_warning",
    "predicted_equivalence_confidence",
    "predicted_equivalence_source",
    "predicted_equivalence_evidence",
    "predicted_equivalence_model_key",
)

# Eligibility is deliberately based only on recorded coordinates and sensor
# observations. Typed/derived chemistry values (including theoretical volume
# and unknown concentration) must not make an unusable run prediction-ready.
PREDICTION_SENSOR_GROUPS = (
    ("visible_R_mean", "visible_G_mean", "visible_B_mean"),
    ("visible_H_mean", "visible_S_mean", "visible_V_mean"),
    ("thermal_roi_avg", "thermal_roi_min", "thermal_roi_max"),
    ("thermal_raw_roi_p50", "thermal_raw_roi_p95"),
)
PREDICTION_SENSOR_COLUMNS = tuple(dict.fromkeys(column for group in PREDICTION_SENSOR_GROUPS for column in group))

# These columns are valid for CSV audit/diagnostics, but must never be inputs to
# a live prediction model.  Several of them directly encode the user's typed
# concentration, the calculated theoretical equivalence point, or a label made
# from that theoretical value.  Loading such a model made the dashboard show the
# theory value as if it were an ML prediction.
LIVE_ML_FORBIDDEN_FEATURE_COLUMNS = frozenset(
    {
        "sample_concentration_M",
        "sample_concentration_from_theoretical_equivalence_M",
        "sample_concentration_from_predicted_equivalence_M",
        "calculated_theoretical_equivalence_volume_ml",
        "theoretical_equivalence_volume_ml",
        "theoretical_equivalence_time_s",
        "theoretical_equivalence_pH",
        "distance_to_equivalence_ml",
        "time_to_equivalence_s",
        "equivalence_window_label",
        "equivalence_window_ml",
        "sample_concentration_error_percent",
        "predicted_sample_concentration_error_percent",
        "actual_equivalence_volume_ml",
        "reference_equivalence_volume_ml",
        "candidate_error_ml",
        "candidate_abs_error_ml",
        "is_good_candidate",
        "zone_label",
        "progress",
        "candidate_fraction_of_run",
        "run_volume_max_ml",
        "run_duration_s",
        "row_count",
    }
)


@dataclass(frozen=True)
class PredictionReadiness:
    """Engineering eligibility guard for attempting a post-run prediction."""

    ready: bool
    reason: str
    usable_row_indices: tuple[int, ...]
    usable_observation_count: int
    time_span_s: float
    volume_span_ml: float


def evaluate_prediction_readiness(rows: list[dict[str, Any]]) -> PredictionReadiness:
    """Check minimum recorded progression; this is not chemical endpoint proof."""

    usable: list[tuple[int, float, float]] = []
    for index, row in enumerate(rows):
        time_s = _finite_float_or_none(row.get("time_s"))
        volume_ml = _finite_float_or_none(row.get("injected_volume_ml"))
        has_sensor_group = any(
            all(
                not isinstance(row.get(column), bool)
                and _finite_float_or_none(row.get(column)) is not None
                for column in group
            )
            for group in PREDICTION_SENSOR_GROUPS
        )
        if time_s is None or volume_ml is None or time_s < 0 or volume_ml < 0 or not has_sensor_group:
            continue
        usable.append((index, time_s, volume_ml))

    indices = tuple(item[0] for item in usable)
    times = [item[1] for item in usable]
    volumes = [item[2] for item in usable]
    time_span = max(times) - min(times) if times else 0.0
    volume_span = max(volumes) - min(volumes) if volumes else 0.0
    if len(usable) < PREDICTION_MIN_USABLE_OBSERVATIONS:
        return PredictionReadiness(
            False,
            "insufficient_usable_sensor_time_volume_observations",
            indices,
            len(usable),
            time_span,
            volume_span,
        )

    if time_span < PREDICTION_MIN_RECORDING_SPAN_S or times[-1] <= times[0]:
        reason = "insufficient_recording_time_span"
    elif volume_span <= 0 or volumes[-1] <= volumes[0]:
        reason = "insufficient_recorded_volume_progression"
    else:
        sensor_progression = False
        for column in PREDICTION_SENSOR_COLUMNS:
            values = [
                value
                for index in indices
                if (value := _finite_float_or_none(rows[index].get(column))) is not None
            ]
            if len(values) >= 2 and max(values) - min(values) > 1e-12:
                sensor_progression = True
                break
        if not sensor_progression:
            return PredictionReadiness(
                False,
                "flat_recorded_sensor_signals",
                indices,
                len(usable),
                time_span,
                volume_span,
            )
        return PredictionReadiness(
            True,
            "minimum_recorded_progression_met",
            indices,
            len(usable),
            time_span,
            volume_span,
        )
    return PredictionReadiness(False, reason, indices, len(usable), time_span, volume_span)
class Mini2PartsReader(Protocol):
    def read_frame_parts(self): ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class CapturedMini2Frame:
    frame_id: int
    timestamp_s: float
    parts: Any
    recording_session_id: int = 0


@dataclass(frozen=True)
class TimestampedVisibleFrame:
    frame_id: int
    timestamp_s: float
    frame_rgb: np.ndarray
    received_s: float | None = None

    @property
    def preview_timestamp_s(self) -> float:
        return self.timestamp_s if self.received_s is None else self.received_s


@dataclass(frozen=True)
class RoiAnchor:
    seed_xy: tuple[int, int]
    roi: Roi
    frame_shape: tuple[int, int]


@dataclass(frozen=True)
class RoiMask:
    mask: np.ndarray
    bbox: Roi
    confidence: float
    source: str
    shape: str = "mask"
    component_count: int = 1
    stability: str = "fresh"

    @property
    def area_px(self) -> int:
        return int(np.count_nonzero(self.mask))

    @property
    def centroid_xy(self) -> tuple[float, float]:
        ys, xs = np.where(self.mask)
        if len(xs) == 0:
            return (float(self.bbox.x + self.bbox.width / 2.0), float(self.bbox.y + self.bbox.height / 2.0))
        return (float(np.mean(xs)), float(np.mean(ys)))

    @property
    def bbox_string(self) -> str:
        return roi_to_string(self.bbox)


@dataclass(frozen=True)
class RoiDetectionResult:
    roi: Roi | None
    confidence: float
    reason: str
    mask: RoiMask | None = None


@dataclass(frozen=True)
class AutoRoiSettingsSnapshot:
    """Immutable settings attached to an async auto-ROI request/result."""

    mode: str
    visible_detector: str
    min_confidence: float
    link_mode: str
    settings_updated_epoch_s: float | None = None

    @classmethod
    def from_values(
        cls,
        *,
        mode: str,
        visible_detector: str,
        min_confidence: float,
        link_mode: str,
        settings_updated_epoch_s: Any = None,
    ) -> "AutoRoiSettingsSnapshot":
        parsed_epoch: float | None
        try:
            parsed_epoch = None if settings_updated_epoch_s is None else round(float(settings_updated_epoch_s), 6)
        except (TypeError, ValueError):
            parsed_epoch = None
        return cls(
            mode=str(mode or "off").strip().lower(),
            visible_detector=str(visible_detector or "yolo").strip().lower(),
            min_confidence=round(float(min_confidence), 6),
            link_mode=str(link_mode or "anchor").strip().lower(),
            settings_updated_epoch_s=parsed_epoch,
        )

    @property
    def key(self) -> tuple[str, str, float, str, float | None]:
        return (self.mode, self.visible_detector, self.min_confidence, self.link_mode, self.settings_updated_epoch_s)


@dataclass(frozen=True)
class AutoRoiWorkerResult:
    """Candidate-only ROI result produced outside the 25fps hot path."""

    sequence: int
    settings: AutoRoiSettingsSnapshot
    visible_frame_id: int | None
    visible_timestamp_s: float | None
    thermal_frame_id: int | None
    thermal_timestamp_s: float | None
    submitted_epoch_s: float
    completed_epoch_s: float
    visible_result: RoiDetectionResult | None = None
    thermal_result: RoiDetectionResult | None = None
    error: str = ""

    @property
    def result_age_ms(self) -> float:
        return round(max(0.0, time.time() - self.completed_epoch_s) * 1000.0, 3)


class RoiSelectionState:
    """Thread-safe ROI state shared by the collector loop and browser API."""

    def __init__(self, *, visible_roi: Roi | None = None, thermal_roi: Roi | None = None) -> None:
        self._lock = threading.Lock()
        self.visible_roi = visible_roi
        self.thermal_roi = thermal_roi
        self.visible_mask: RoiMask | None = None
        self.thermal_mask: RoiMask | None = None
        self.visible_anchor: RoiAnchor | None = None
        self.thermal_anchor: RoiAnchor | None = None
        self.visible_shape: tuple[int, int] | None = None
        self.thermal_shape: tuple[int, int] | None = None
        self.roi_state = "setup"
        self.roi_session_id = 0
        self.locked_epoch_s: float | None = None
        self.recording_epoch_s: float | None = None
        self.stopped_epoch_s: float | None = None
        self.last_source = "initial"
        self.last_error = ""
        self._pending_clicks: deque[tuple[str, int, int]] = deque()
        self._pending_auto_candidate_requests: deque[str] = deque()

    def _editable_locked(self) -> bool:
        return self.roi_state == "setup"

    def _require_editable_locked(self, action: str) -> None:
        if not self._editable_locked():
            raise ValueError(f"ROI is {self.roi_state}; unlock/reset before {action}")

    def _shape_for_target_locked(self, target: str, fallback: tuple[int, int] | None = None) -> tuple[int, int] | None:
        if fallback is not None:
            return tuple(fallback[:2])
        return self.visible_shape if target == "visible" else self.thermal_shape

    def set_latest_shapes(
        self,
        *,
        visible_shape: tuple[int, int] | None = None,
        thermal_shape: tuple[int, int] | None = None,
    ) -> None:
        with self._lock:
            if visible_shape is not None:
                self.visible_shape = tuple(visible_shape[:2])
            if thermal_shape is not None:
                self.thermal_shape = tuple(thermal_shape[:2])

    def update_visible(
        self,
        roi: Roi,
        *,
        seed: tuple[int, int],
        frame_shape: tuple[int, int],
        mask: RoiMask | None = None,
    ) -> None:
        with self._lock:
            self._require_editable_locked("editing visible ROI")
            self.visible_shape = tuple(frame_shape[:2])
            self.visible_roi = roi
            self.visible_mask = mask
            self.visible_anchor = RoiAnchor(seed, roi, tuple(frame_shape[:2]))
            self.last_source = "visible_click"
            self.last_error = ""

    def update_thermal(
        self,
        roi: Roi,
        *,
        seed: tuple[int, int],
        frame_shape: tuple[int, int],
        mask: RoiMask | None = None,
    ) -> None:
        with self._lock:
            self._require_editable_locked("editing thermal ROI")
            self.thermal_shape = tuple(frame_shape[:2])
            self.thermal_roi = roi
            self.thermal_mask = mask
            self.thermal_anchor = RoiAnchor(seed, roi, tuple(frame_shape[:2]))
            self.last_source = "thermal_click"
            self.last_error = ""

    def update_rect(self, target: str, roi: Roi, *, frame_shape: tuple[int, int] | None = None) -> Roi:
        target = target.strip().lower()
        if target not in {"visible", "thermal"}:
            raise ValueError("ROI rectangle target must be visible or thermal")
        if roi.width <= 0 or roi.height <= 0:
            raise ValueError("ROI rectangle width and height must be positive")
        if roi.x < 0 or roi.y < 0:
            raise ValueError("ROI rectangle coordinates must be non-negative")
        with self._lock:
            self._require_editable_locked(f"editing {target} ROI")
            shape = self._shape_for_target_locked(target, frame_shape)
            selected = clamp_roi_to_shape(roi, shape) if shape is not None else roi
            seed = (selected.x + selected.width // 2, selected.y + selected.height // 2)
            if target == "visible":
                if shape is not None:
                    self.visible_shape = shape
                self.visible_roi = selected
                self.visible_mask = None
                self.visible_anchor = None if shape is None else RoiAnchor(seed, selected, shape)
                self.last_source = "visible_rect"
            else:
                if shape is not None:
                    self.thermal_shape = shape
                self.thermal_roi = selected
                self.thermal_mask = None
                self.thermal_anchor = None if shape is None else RoiAnchor(seed, selected, shape)
                self.last_source = "thermal_rect"
            self.last_error = ""
            return selected

    def update_polygon_mask(self, target: str, mask: np.ndarray, *, source: str = "manual_lasso") -> RoiMask:
        target = target.strip().lower()
        if target not in {"visible", "thermal"}:
            raise ValueError("ROI polygon target must be visible or thermal")
        roi_mask = roi_mask_from_bool(mask, confidence=1.0, source=source)
        shape = roi_mask.mask.shape[:2]
        cx, cy = roi_mask.centroid_xy
        seed = (int(round(cx)), int(round(cy)))
        with self._lock:
            self._require_editable_locked(f"editing {target} ROI")
            if target == "visible":
                self.visible_shape = shape
                self.visible_roi = roi_mask.bbox
                self.visible_mask = roi_mask
                self.visible_anchor = RoiAnchor(seed, roi_mask.bbox, shape)
                self.last_source = "visible_lasso"
            else:
                self.thermal_shape = shape
                self.thermal_roi = roi_mask.bbox
                self.thermal_mask = roi_mask
                self.thermal_anchor = RoiAnchor(seed, roi_mask.bbox, shape)
                self.last_source = "thermal_lasso"
            self.last_error = ""
            return roi_mask

    def update_auto(
        self,
        *,
        visible_roi: Roi | None = None,
        thermal_roi: Roi | None = None,
        visible_mask: RoiMask | None = None,
        thermal_mask: RoiMask | None = None,
        reason: str = "auto",
        allow_manual_lasso_overwrite: bool = False,
    ) -> bool:
        with self._lock:
            if not self._editable_locked():
                self.last_error = f"ignored auto ROI update while {self.roi_state}"
                return False
            skipped_manual: list[str] = []
            visible_requested = visible_roi is not None or visible_mask is not None
            thermal_requested = thermal_roi is not None or thermal_mask is not None
            if (
                visible_requested
                and not allow_manual_lasso_overwrite
                and self.visible_mask is not None
                and self.visible_mask.source.startswith("manual_lasso")
            ):
                visible_roi = None
                visible_mask = None
                skipped_manual.append("visible")
            if (
                thermal_requested
                and not allow_manual_lasso_overwrite
                and self.thermal_mask is not None
                and self.thermal_mask.source.startswith("manual_lasso")
            ):
                thermal_roi = None
                thermal_mask = None
                skipped_manual.append("thermal")
            if visible_roi is not None:
                self.visible_roi = visible_roi
                self.visible_mask = visible_mask
            elif visible_mask is not None:
                self.visible_roi = visible_mask.bbox
                self.visible_mask = visible_mask
            if thermal_roi is not None:
                self.thermal_roi = thermal_roi
                self.thermal_mask = thermal_mask
            elif thermal_mask is not None:
                self.thermal_roi = thermal_mask.bbox
                self.thermal_mask = thermal_mask
            if visible_roi is not None or thermal_roi is not None or visible_mask is not None or thermal_mask is not None:
                self.last_source = reason
                self.last_error = (
                    f"kept manual lasso ROI for {', '.join(skipped_manual)}"
                    if skipped_manual
                    else ""
                )
                return True
            if skipped_manual:
                self.last_error = f"kept manual lasso ROI for {', '.join(skipped_manual)}"
            return False

    def snapshot(self) -> tuple[Roi | None, Roi | None]:
        with self._lock:
            return self.visible_roi, self.thermal_roi

    def snapshot_masks(self) -> tuple[RoiMask | None, RoiMask | None]:
        with self._lock:
            return self.visible_mask, self.thermal_mask

    def snapshot_anchors(self) -> tuple[RoiAnchor | None, RoiAnchor | None]:
        with self._lock:
            return self.visible_anchor, self.thermal_anchor

    def push_click(self, target: str, x: int, y: int) -> None:
        target = target.strip().lower()
        if target not in {"visible", "thermal"}:
            raise ValueError("ROI click target must be visible or thermal")
        if x < 0 or y < 0:
            raise ValueError("ROI click coordinates must be non-negative")
        with self._lock:
            self._require_editable_locked("editing ROI")
            self._pending_clicks.append((target, int(x), int(y)))

    def pop_clicks(self) -> list[tuple[str, int, int]]:
        with self._lock:
            clicks = list(self._pending_clicks)
            self._pending_clicks.clear()
            return clicks

    def set_error(self, message: str) -> None:
        with self._lock:
            self.last_error = message

    def reuse_last_good_masks(self, reason: str = "auto:reuse_last_good") -> None:
        with self._lock:
            if not self._editable_locked():
                self.last_error = f"ignored mask reuse while {self.roi_state}"
                return
            if self.visible_mask is not None:
                self.visible_mask = replace(self.visible_mask, stability="reused_last_good", source=self.visible_mask.source)
                self.visible_roi = self.visible_mask.bbox
            if self.thermal_mask is not None:
                self.thermal_mask = replace(self.thermal_mask, stability="reused_last_good", source=self.thermal_mask.source)
                self.thermal_roi = self.thermal_mask.bbox
            if self.visible_mask is not None or self.thermal_mask is not None:
                self.last_source = reason
                self.last_error = ""

    def lock(self) -> dict[str, Any]:
        with self._lock:
            if self.visible_roi is None or self.thermal_roi is None:
                missing = []
                if self.visible_roi is None:
                    missing.append("visible")
                if self.thermal_roi is None:
                    missing.append("thermal")
                raise ValueError(f"cannot lock ROI before selecting {', '.join(missing)} ROI")
            if self.roi_state == "recording":
                raise ValueError("ROI is recording; stop recording before locking again")
            if self.roi_state != "locked":
                self.roi_session_id += 1
            self.roi_state = "locked"
            self.locked_epoch_s = round(time.time(), 6)
            self.recording_epoch_s = None
            self.stopped_epoch_s = None
            self.last_source = "roi_locked"
            self.last_error = ""
            return self.status_locked()

    def unlock(self, *, reset: bool = False) -> dict[str, Any]:
        with self._lock:
            if self.roi_state == "recording":
                raise ValueError("stop recording before unlocking ROI")
            self.roi_state = "setup"
            self.locked_epoch_s = None
            self.recording_epoch_s = None
            self.stopped_epoch_s = None
            if reset:
                self.visible_roi = None
                self.thermal_roi = None
                self.visible_mask = None
                self.thermal_mask = None
                self.visible_anchor = None
                self.thermal_anchor = None
                self.last_source = "roi_reset"
            else:
                self.last_source = "roi_unlocked"
            self.last_error = ""
            return self.status_locked()

    def start_recording(self) -> dict[str, Any]:
        with self._lock:
            if self.roi_state not in {"locked", "stopped"}:
                raise ValueError("lock both visible and thermal ROIs before recording")
            if self.visible_roi is None or self.thermal_roi is None:
                raise ValueError("lock both visible and thermal ROIs before recording")
            self.roi_state = "recording"
            self.recording_epoch_s = round(time.time(), 6)
            self.stopped_epoch_s = None
            self.last_source = "roi_recording"
            self.last_error = ""
            return self.status_locked()

    def stop_recording(self) -> dict[str, Any]:
        with self._lock:
            if self.roi_state == "recording":
                self.roi_state = "stopped"
                self.stopped_epoch_s = round(time.time(), 6)
                self.last_source = "roi_stopped"
                self.last_error = ""
            return self.status_locked()

    @staticmethod
    def _normalize_auto_candidate_target(target: str | None) -> str:
        normalized = str(target or "both").strip().lower()
        if normalized not in {"visible", "thermal", "both"}:
            raise ValueError("auto ROI candidate target must be visible, thermal, or both")
        return normalized

    def request_auto_candidate(self, target: str | None = "both") -> dict[str, Any]:
        target = self._normalize_auto_candidate_target(target)
        with self._lock:
            self._require_editable_locked("requesting auto ROI candidate")
            self._pending_auto_candidate_requests.append(target)
            self.last_source = f"auto_candidate_requested:{target}"
            self.last_error = ""
            return self.status_locked()

    def pop_auto_candidate_request(
        self,
        *,
        visible_available: bool = True,
        thermal_available: bool = True,
        visible_expected: bool = True,
        thermal_expected: bool = True,
    ) -> str | None:
        with self._lock:
            if not self._pending_auto_candidate_requests:
                return None
            if not self._editable_locked():
                self._pending_auto_candidate_requests.popleft()
                self.last_error = f"ignored auto ROI candidate while {self.roi_state}"
                return None
            target = self._pending_auto_candidate_requests[0]
            visible_needed = target in {"visible", "both"} and bool(visible_expected)
            thermal_needed = target in {"thermal", "both"} and bool(thermal_expected)
            if target == "visible" and not visible_needed:
                self._pending_auto_candidate_requests.popleft()
                self.last_error = "visible auto candidate requested but no visible camera is active"
                return target
            if target == "thermal" and not thermal_needed:
                self._pending_auto_candidate_requests.popleft()
                self.last_error = "thermal auto candidate requested but no Mini2 frame is active"
                return target
            if visible_needed and not visible_available:
                self.last_source = f"auto_candidate_waiting:{target}:visible_frame"
                return None
            if thermal_needed and not thermal_available:
                self.last_source = f"auto_candidate_waiting:{target}:thermal_frame"
                return None
            self._pending_auto_candidate_requests.popleft()
            return target

    def auto_updates_allowed(self) -> bool:
        with self._lock:
            return self._editable_locked()

    def status_locked(self) -> dict[str, Any]:
        visible_ready = self.visible_roi is not None
        thermal_ready = self.thermal_roi is not None
        complete = visible_ready and thermal_ready
        locked = self.roi_state in {"locked", "recording", "stopped"}
        recordable = self.roi_state in {"locked", "stopped"} and complete
        return {
            "roi_source": self.last_source,
            "roi_error": self.last_error,
            "roi_state": self.roi_state,
            "roi_locked": locked,
            "roi_editable": self._editable_locked(),
            "roi_recordable": recordable,
            "roi_recording": self.roi_state == "recording",
            "roi_session_id": self.roi_session_id,
            "roi_complete": complete,
            "visible_roi_ready": visible_ready,
            "thermal_roi_ready": thermal_ready,
            "roi_locked_epoch_s": self.locked_epoch_s,
            "roi_recording_epoch_s": self.recording_epoch_s,
            "roi_stopped_epoch_s": self.stopped_epoch_s,
            "visible_roi": roi_to_string(self.visible_roi),
            "thermal_roi": roi_to_string(self.thermal_roi),
            "pending_auto_candidate_requests": len(self._pending_auto_candidate_requests),
            "pending_auto_candidate_target": self._pending_auto_candidate_requests[0]
            if self._pending_auto_candidate_requests
            else "",
            "visible_roi_shape": "mask" if self.visible_mask is not None else ("rectangle" if visible_ready else ""),
            "thermal_roi_shape": "mask" if self.thermal_mask is not None else ("rectangle" if thermal_ready else ""),
            "visible_mask_source": "" if self.visible_mask is None else self.visible_mask.source,
            "thermal_mask_source": "" if self.thermal_mask is None else self.thermal_mask.source,
            "visible_mask_area_px": 0 if self.visible_mask is None else self.visible_mask.area_px,
            "thermal_mask_area_px": 0 if self.thermal_mask is None else self.thermal_mask.area_px,
            "visible_mask_stability": "" if self.visible_mask is None else self.visible_mask.stability,
            "thermal_mask_stability": "" if self.thermal_mask is None else self.thermal_mask.stability,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.status_locked()

    def row_metadata(self, *, visible_roi: Roi | None = None, thermal_roi: Roi | None = None) -> dict[str, Any]:
        with self._lock:
            visible = self.visible_roi if visible_roi is None else visible_roi
            thermal = self.thermal_roi if thermal_roi is None else thermal_roi

            def fields(prefix: str, roi: Roi | None) -> dict[str, Any]:
                if roi is None:
                    return {
                        f"{prefix}_roi_x": "",
                        f"{prefix}_roi_y": "",
                        f"{prefix}_roi_width": "",
                        f"{prefix}_roi_height": "",
                    }
                return {
                    f"{prefix}_roi_x": int(roi.x),
                    f"{prefix}_roi_y": int(roi.y),
                    f"{prefix}_roi_width": int(roi.width),
                    f"{prefix}_roi_height": int(roi.height),
                }

            payload: dict[str, Any] = {
                "roi_state": self.roi_state,
                "roi_locked": self.roi_state in {"locked", "recording", "stopped"},
                "roi_editable": self._editable_locked(),
                "roi_recordable": self.roi_state in {"locked", "stopped"} and visible is not None and thermal is not None,
                "roi_session_id": self.roi_session_id,
                "roi_source": self.last_source,
                "roi_error": self.last_error,
                "pending_auto_candidate_requests": len(self._pending_auto_candidate_requests),
                "pending_auto_candidate_target": self._pending_auto_candidate_requests[0]
                if self._pending_auto_candidate_requests
                else "",
            }
            payload.update(fields("visible", visible))
            payload.update(fields("thermal", thermal))
            return payload


class LiveStreamState:
    """In-memory latest-frame store for low-latency browser streaming."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._metadata_sequence = 0
        self._visible_sequence = 0
        self._thermal_sequence = 0
        self._visible_jpeg: bytes | None = None
        self._thermal_jpeg: bytes | None = None
        self._visible_updated_epoch_s: float | None = None
        self._thermal_updated_epoch_s: float | None = None
        self._metadata: dict[str, Any] = {"frame_id": None, "sync_quality": "waiting"}
        self._metadata_updated_epoch_s: float | None = None

    def publish(
        self,
        *,
        visible_jpeg: bytes | None = None,
        thermal_jpeg: bytes | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._condition:
            now = round(time.time(), 6)
            if visible_jpeg is not None:
                self._visible_jpeg = bytes(visible_jpeg)
                self._visible_sequence += 1
                self._visible_updated_epoch_s = now
            if thermal_jpeg is not None:
                self._thermal_jpeg = bytes(thermal_jpeg)
                self._thermal_sequence += 1
                self._thermal_updated_epoch_s = now
            if metadata is not None:
                self._metadata_sequence += 1
                latest = dict(metadata)
                visible_age_ms = None
                thermal_age_ms = None
                if self._visible_updated_epoch_s is not None:
                    visible_age_ms = round(max(0.0, now - self._visible_updated_epoch_s) * 1000.0, 3)
                if self._thermal_updated_epoch_s is not None:
                    thermal_age_ms = round(max(0.0, now - self._thermal_updated_epoch_s) * 1000.0, 3)
                latest["stream_sequence"] = self._metadata_sequence
                latest["visible_stream_sequence"] = self._visible_sequence
                latest["thermal_stream_sequence"] = self._thermal_sequence
                latest["latency_visible_stream_age_ms"] = visible_age_ms
                latest["latency_thermal_stream_age_ms"] = thermal_age_ms
                latest["stream_updated_epoch_s"] = now
                self._metadata = latest
                self._metadata_updated_epoch_s = now
            self._condition.notify_all()

    def publish_visible(self, jpeg: bytes) -> None:
        self.publish(visible_jpeg=jpeg)

    def publish_thermal(self, jpeg: bytes) -> None:
        self.publish(thermal_jpeg=jpeg)

    def publish_metadata(self, metadata: dict[str, Any]) -> None:
        self.publish(metadata=metadata)

    def wait_jpeg(self, kind: str, *, last_sequence: int, timeout_s: float = 5.0) -> tuple[int, bytes] | None:
        if kind not in {"visible", "thermal"}:
            raise ValueError("kind must be visible or thermal")
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while True:
                if kind == "visible":
                    sequence = self._visible_sequence
                    data = self._visible_jpeg
                else:
                    sequence = self._thermal_sequence
                    data = self._thermal_jpeg
                if sequence > last_sequence and data is not None:
                    return sequence, data
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def wait_metadata(self, *, last_sequence: int, timeout_s: float = 5.0) -> tuple[int, dict[str, Any]] | None:
        deadline = time.monotonic() + max(0.0, timeout_s)
        with self._condition:
            while True:
                if self._metadata_sequence > last_sequence:
                    return self._metadata_sequence, dict(self._metadata)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    def snapshot_metadata(self) -> dict[str, Any]:
        with self._condition:
            return dict(self._metadata)

    def snapshot_health(self) -> dict[str, Any]:
        now = round(time.time(), 6)

        def age_ms(updated_epoch_s: float | None) -> float | None:
            if updated_epoch_s is None:
                return None
            return round(max(0.0, now - updated_epoch_s) * 1000.0, 3)

        with self._condition:
            metadata = dict(self._metadata)
            return {
                "ok": True,
                "collector_running": True,
                "updated_epoch_s": now,
                "metadata_sequence": self._metadata_sequence,
                "visible_sequence": self._visible_sequence,
                "thermal_sequence": self._thermal_sequence,
                "metadata_ready": self._metadata_sequence > 0 and metadata.get("frame_id") is not None,
                "visible_stream_ready": self._visible_sequence > 0,
                "thermal_stream_ready": self._thermal_sequence > 0,
                "metadata_age_ms": age_ms(self._metadata_updated_epoch_s),
                "visible_age_ms": age_ms(self._visible_updated_epoch_s),
                "thermal_age_ms": age_ms(self._thermal_updated_epoch_s),
                "latest": metadata,
            }


def _repo_relative_path(path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(candidate).replace("\\", "/")


def csv_fieldnames_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    fieldnames = sorted({key for row in rows for key in row.keys()})
    preferred = [name for name in DEFAULT_COLUMNS if name in fieldnames]
    return preferred + [name for name in fieldnames if name not in preferred]


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(parsed):
        return None
    return parsed


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _strict_optional_bool(payload: Mapping[str, Any], key: str, *, default: bool) -> bool:
    if key not in payload:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be boolean")
    return value


def _validate_remote_recording_config(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("원격 설정은 JSON 객체여야 합니다")
    rate = _finite_float_or_none(payload.get("pump_rate_ml_per_s"))
    if rate is None or rate <= 0:
        raise ValueError("원격 설정에 유효한 펌프 유량이 필요합니다")
    if str(payload.get("titration_type") or "") not in SUPPORTED_TITRATION_TYPES:
        raise ValueError("원격 설정에 적정 종류가 필요합니다")
    for key in ("auto_stop_enabled", "auto_stop_pulse_enabled", "auto_stop_slow_stage_enabled"):
        _strict_optional_bool(payload, key, default=False)
    return dict(payload)


def _load_remote_recording_config(
    path: str | Path | None,
) -> tuple[dict[str, Any] | None, bool]:
    if path is None:
        return None, True
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        if payload is None:
            return None, False
        return _validate_remote_recording_config(payload), False
    except FileNotFoundError:
        return None, True
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None, False


def _persist_remote_recording_config(
    path: str | Path | None,
    config: dict[str, Any] | None,
) -> None:
    if path is None:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(config, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _strict_optional_int(
    payload: Mapping[str, Any], key: str, *, default: int, minimum: int, maximum: int
) -> int:
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be in {minimum}..{maximum}")
    return value


def _strict_optional_number(
    payload: Mapping[str, Any], key: str, *, default: float
) -> float:
    if key not in payload:
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{key} must be finite")
    return parsed


def start_payload_experiment_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Return CSV-safe experiment/science metadata from a recording start payload."""

    metadata: dict[str, Any] = {}
    for key in sorted(CSV_START_METADATA_KEYS):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = sanitize_csv_metadata_text(value.strip())
        if value == "":
            continue
        metadata[key] = value
    return metadata


def sanitize_csv_metadata_text(value: str) -> str:
    """Neutralize spreadsheet formulas in user-supplied CSV metadata text."""

    text = str(value)
    stripped = text.lstrip()
    if stripped and stripped[0] in {"=", "+", "-", "@"}:
        return "'" + text
    if text[:1] in {"\t", "\r", "\n"}:
        return "'" + text
    return text


def build_constants_lookup_payload(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Build browser JSON for local IUPAC pKa lookup without network access."""

    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("substance query is required")
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = 8
    parsed_limit = min(50, max(1, parsed_limit))
    result = lookup_iupac_pka(normalized_query, limit=parsed_limit)
    candidates = [candidate.as_dict() for candidate in result.candidates]
    return {
        "ok": True,
        "query": result.query,
        "source": "IUPAC Dissociation Constants high-confidence local CSV",
        "source_path": _repo_relative_path(DEFAULT_IUPAC_CSV_PATH),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "warning": result.warning,
        "fallback": result.fallback,
        "requires_manual_confirmation": result.requires_manual_confirmation,
        "ambiguous": result.ambiguous,
    }


def _equivalence_window_label(distance_ml: float, window_ml: float) -> str:
    near_window = max(window_ml * 6.0, window_ml)
    if distance_ml < -near_window:
        return "before"
    if distance_ml < -window_ml:
        return "near_before"
    if distance_ml <= window_ml:
        return "equivalence"
    if distance_ml <= near_window:
        return "near_after"
    return "after"


def _concentration_from_titrant_volume(
    *,
    titrant_volume_ml: float | None,
    titrant_concentration_M: float | None,
    titrant_valence: float | None,
    sample_volume_ml: float | None,
    sample_valence: float | None,
) -> float | None:
    """Return sample concentration from nMV=n'M'V' for a titrant volume."""

    volume = _finite_float_or_none(titrant_volume_ml)
    titrant_conc = _finite_float_or_none(titrant_concentration_M)
    titrant_n = _finite_float_or_none(titrant_valence)
    sample_volume = _finite_float_or_none(sample_volume_ml)
    sample_n = _finite_float_or_none(sample_valence)
    if (
        volume is None
        or titrant_conc is None
        or titrant_n is None
        or sample_volume is None
        or sample_n is None
        or volume < 0
        or titrant_conc <= 0
        or titrant_n <= 0
        or sample_volume <= 0
        or sample_n <= 0
    ):
        return None
    return titrant_conc * volume * titrant_n / (sample_volume * sample_n)


def _concentration_error_percent(calculated: float | None, reference: float | None) -> float | None:
    value = _finite_float_or_none(calculated)
    expected = _finite_float_or_none(reference)
    if value is None or expected is None or expected <= 0:
        return None
    return (value - expected) / expected * 100.0


def _context_value(row: dict[str, Any], metadata: dict[str, Any], key: str, default: Any = None) -> Any:
    value = metadata.get(key)
    if value not in (None, ""):
        return value
    value = row.get(key)
    if value not in (None, ""):
        return value
    return default


def _predicted_concentration_fields_from_row(row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    predicted_volume = _finite_float_or_none(row.get("predicted_equivalence_volume_ml"))
    calculated = _concentration_from_titrant_volume(
        titrant_volume_ml=predicted_volume,
        titrant_concentration_M=_context_value(row, metadata, "titrant_concentration_M"),
        titrant_valence=_context_value(row, metadata, "titrant_valence", 1),
        sample_volume_ml=_context_value(row, metadata, "sample_volume_ml"),
        sample_valence=_context_value(row, metadata, "sample_valence", 1),
    )
    if calculated is None:
        return {}
    error = _concentration_error_percent(calculated, _context_value(row, metadata, "sample_concentration_M"))
    return {
        "sample_concentration_from_predicted_equivalence_M": round(calculated, 8),
        "predicted_sample_concentration_error_percent": "" if error is None else round(error, 6),
    }


def _predicted_result_fields_from_row(row: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    predicted_volume = _finite_float_or_none(row.get("predicted_equivalence_volume_ml"))
    fields = _predicted_concentration_fields_from_row(row, metadata)
    if predicted_volume is None:
        return fields
    fields.setdefault("predicted_equivalence_volume_ml", round(predicted_volume, 6))
    calculated_concentration = _finite_float_or_none(
        fields.get("sample_concentration_from_predicted_equivalence_M")
        or row.get("sample_concentration_from_predicted_equivalence_M")
    )
    if calculated_concentration is None:
        return fields
    try:
        result = calculate_theoretical_titration_result(
            sample_concentration_m=calculated_concentration,
            sample_volume_ml=float(_context_value(row, metadata, "sample_volume_ml")),
            sample_valence=int(float(_context_value(row, metadata, "sample_valence", 1))),
            titrant_concentration_m=float(_context_value(row, metadata, "titrant_concentration_M")),
            titrant_valence=int(float(_context_value(row, metadata, "titrant_valence", 1))),
            titration_type=str(_context_value(row, metadata, "titration_type", "strong_acid_strong_base")),
            sample_pka=_finite_float_or_none(_context_value(row, metadata, "selected_pka_value")),
            titrant_pkb=_finite_float_or_none(_context_value(row, metadata, "selected_pkb_value")),
        )
    except (TypeError, ValueError) as exc:
        fields["predicted_equivalence_pH_warning"] = f"pH 계산 보류: {exc}"
        return fields
    fields["predicted_equivalence_pH"] = round(result.expected_equivalence_ph, 6)
    fields["predicted_equivalence_pH_model"] = result.basis
    if result.warnings:
        fields["predicted_equivalence_pH_warning"] = "; ".join(result.warnings)
    else:
        fields["predicted_equivalence_pH_warning"] = ""
    return fields


def _theoretical_equivalence_volume_from_metadata(metadata: dict[str, Any]) -> float | None:
    sample_conc = _finite_float_or_none(metadata.get("sample_concentration_M"))
    sample_volume = _finite_float_or_none(metadata.get("sample_volume_ml"))
    sample_n = _finite_float_or_none(metadata.get("sample_valence"))
    titrant_conc = _finite_float_or_none(metadata.get("titrant_concentration_M"))
    titrant_n = _finite_float_or_none(metadata.get("titrant_valence"))
    if (
        sample_conc is None
        or sample_volume is None
        or sample_n is None
        or titrant_conc is None
        or titrant_n is None
        or sample_conc <= 0
        or sample_volume <= 0
        or sample_n <= 0
        or titrant_conc <= 0
        or titrant_n <= 0
    ):
        return None
    return sample_conc * sample_volume * sample_n / (titrant_conc * titrant_n)


def _theoretical_titration_fields_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return theoretical equivalence pH/activity fields from experiment metadata."""

    sample_conc = _finite_float_or_none(metadata.get("sample_concentration_M"))
    sample_volume = _finite_float_or_none(metadata.get("sample_volume_ml"))
    sample_n = _finite_float_or_none(metadata.get("sample_valence"))
    titrant_conc = _finite_float_or_none(metadata.get("titrant_concentration_M"))
    titrant_n = _finite_float_or_none(metadata.get("titrant_valence"))
    if (
        sample_conc is None
        or sample_volume is None
        or sample_n is None
        or titrant_conc is None
        or titrant_n is None
        or sample_conc <= 0
        or sample_volume <= 0
        or sample_n <= 0
        or titrant_conc <= 0
        or titrant_n <= 0
    ):
        return {}
    try:
        result = calculate_theoretical_titration_result(
            sample_concentration_m=sample_conc,
            sample_volume_ml=sample_volume,
            sample_valence=int(float(sample_n)),
            titrant_concentration_m=titrant_conc,
            titrant_valence=int(float(titrant_n)),
            titration_type=str(metadata.get("titration_type") or "strong_acid_strong_base"),
            sample_pka=_finite_float_or_none(metadata.get("selected_pka_value")),
            titrant_pkb=_finite_float_or_none(metadata.get("selected_pkb_value")),
        )
    except (TypeError, ValueError):
        return {}
    fields: dict[str, Any] = {
        "theoretical_equivalence_pH": round(result.expected_equivalence_ph, 6),
        "selected_equivalence_step": result.selected_equivalence_step,
        "activity_model": result.activity_model,
        "ionic_strength_m": round(result.ionic_strength_m, 12),
        "ionic_strength_label": result.ionic_strength_label,
        "activity_warning": result.activity_warning,
        "chemistry_model": result.basis,
    }
    if result.warnings:
        fields.setdefault("constants_warning", "; ".join(result.warnings))
    return fields


def build_pump_timeline_fields(
    *,
    pump_elapsed_s: float,
    pump_rate_ml_per_s: float | None,
    theoretical_equivalence_volume_ml: float | None,
    equivalence_window_ml: float = 0.05,
    experiment_metadata: dict[str, Any] | None = None,
    injected_volume_ml: float | None = None,
    pump_mode: str | None = None,
    pump_state: str = "running",
) -> dict[str, Any]:
    """Build per-frame pump/equivalence target fields from pump start time."""

    elapsed = max(0.0, float(pump_elapsed_s))
    rate = _finite_float_or_none(pump_rate_ml_per_s)
    theory_volume = _finite_float_or_none(theoretical_equivalence_volume_ml)
    window = _finite_float_or_none(equivalence_window_ml)
    metadata = experiment_metadata or {}
    if window is None or window <= 0:
        window = 0.05
    fields: dict[str, Any] = {
        "pump_mode": str(pump_mode or ("timed_rate" if rate is not None and rate > 0 else "")),
        "pump_state": str(pump_state or "stopped"),
        "pump_elapsed_s": round(elapsed, 6),
        "pump_run_rate_ml_per_s": "" if rate is None else round(rate, 6),
        "equivalence_window_ml": round(window, 6),
    }
    if rate is None or rate <= 0:
        fields.update(
            {
                "injected_volume_ml": "",
                "theoretical_equivalence_volume_ml": "" if theory_volume is None else round(theory_volume, 6),
                "theoretical_equivalence_time_s": "",
                "distance_to_equivalence_ml": "",
                "time_to_equivalence_s": "",
                "equivalence_window_label": "",
            }
        )
        return fields

    injected_override = _finite_float_or_none(injected_volume_ml)
    injected = elapsed * rate if injected_override is None else max(0.0, injected_override)
    fields["injected_volume_ml"] = round(injected, 6)
    calculated_concentration = _concentration_from_titrant_volume(
        titrant_volume_ml=injected,
        titrant_concentration_M=metadata.get("titrant_concentration_M"),
        titrant_valence=metadata.get("titrant_valence"),
        sample_volume_ml=metadata.get("sample_volume_ml"),
        sample_valence=metadata.get("sample_valence"),
    )
    if calculated_concentration is not None:
        fields["sample_concentration_from_injected_M"] = round(calculated_concentration, 8)
        concentration_error = _concentration_error_percent(calculated_concentration, metadata.get("sample_concentration_M"))
        fields["sample_concentration_error_percent"] = "" if concentration_error is None else round(concentration_error, 6)
    else:
        fields["sample_concentration_from_injected_M"] = ""
        fields["sample_concentration_error_percent"] = ""
    if theory_volume is None:
        fields.update(
            {
                "theoretical_equivalence_volume_ml": "",
                "theoretical_equivalence_time_s": "",
                "distance_to_equivalence_ml": "",
                "time_to_equivalence_s": "",
                "equivalence_window_label": "",
            }
        )
        return fields

    theory_time = theory_volume / rate
    distance = injected - theory_volume
    time_to = elapsed - theory_time
    fields.update(
        {
            "theoretical_equivalence_volume_ml": round(theory_volume, 6),
            "theoretical_equivalence_time_s": round(theory_time, 6),
            "distance_to_equivalence_ml": round(distance, 6),
            "time_to_equivalence_s": round(time_to, 6),
            "equivalence_window_label": _equivalence_window_label(distance, window),
        }
    )
    return fields


class LiveCsvBuffer:
    """Thread-safe scalar CSV buffer exposed to the browser for ML training data."""

    def __init__(
        self,
        *,
        output_path: str | Path,
        prediction_model: dict[str, Any] | None = None,
        endpoint_prediction_model: dict[str, Any] | None = None,
        typewise_prediction_model: dict[str, Any] | None = None,
    ) -> None:
        self.output_path = Path(output_path)
        self._prediction_model = prediction_model
        self._endpoint_prediction_model = endpoint_prediction_model
        self._typewise_prediction_model = typewise_prediction_model
        self._condition = threading.Condition()
        self._rows: list[dict[str, Any]] = []
        self._fieldnames: list[str] = []
        self._updated_epoch_s: float | None = None
        self._started_epoch_s: float | None = None
        self._started_monotonic_s: float | None = None
        self._stopped_epoch_s: float | None = None
        self._stopped_monotonic_s: float | None = None
        self._recording = False
        self._finalizing = False
        self._capture_session_required = False
        self._state = "idle"
        self._session_id = 0
        self._roi_session_id = 0
        self._pump_rate_ml_per_s: float | None = None
        self._pump_current_rate_ml_per_s: float | None = None
        self._pump_stage = "fast"
        self._pump_rate_basis = "configured_calibrated_fast_rate"
        self._pump_command_tracking_enabled = False
        self._pump_continuous_started_monotonic_s: float | None = None
        self._pump_active_elapsed_s = 0.0
        self._pump_commanded_volume_ml = 0.0
        self._pump_state = "running"
        self._pump_pulse_count = 0
        self._pump_pulse_steps_total = 0
        self._pump_nominal_ml_per_step: float | None = None
        self._pump_last_nominal_pulse_volume_ml: float | None = None
        self._theoretical_equivalence_volume_ml: float | None = None
        self._equivalence_window_ml = 0.05
        self._experiment_metadata: dict[str, Any] = {}
        self._auto_stop_status: dict[str, Any] = {}
        self._csv_event_note = ""
        self._csv_mark_sequence = 0
        self._predicted_equivalence_status = PREDICTION_STATUS_PENDING
        self._predicted_equivalence_reason = "recording_not_finalized"

    def start_recording(
        self,
        *,
        roi_session_id: int | None = None,
        pump_rate_ml_per_s: float | None = None,
        theoretical_equivalence_volume_ml: float | None = None,
        equivalence_window_ml: float = 0.05,
        experiment_metadata: dict[str, Any] | None = None,
        event_note: str | None = None,
        started_epoch_s: float | None = None,
        started_monotonic_s: float | None = None,
        capture_session_required: bool = False,
    ) -> dict[str, Any]:
        with self._condition:
            if self._state in {"recording", "finalizing"}:
                raise RuntimeError(f"cannot start a new CSV session while state is {self._state}")
            self._session_id += 1
            if roi_session_id is not None:
                self._roi_session_id = int(roi_session_id)
            self._rows.clear()
            self._fieldnames.clear()
            now = round(float(started_epoch_s) if started_epoch_s is not None else time.time(), 6)
            self._started_epoch_s = now
            self._started_monotonic_s = float(started_monotonic_s) if started_monotonic_s is not None else time.perf_counter()
            self._stopped_epoch_s = None
            self._stopped_monotonic_s = None
            self._updated_epoch_s = now
            self._recording = True
            self._finalizing = False
            self._capture_session_required = bool(capture_session_required)
            self._state = "recording"
            self._pump_rate_ml_per_s = _finite_float_or_none(pump_rate_ml_per_s)
            self._pump_current_rate_ml_per_s = self._pump_rate_ml_per_s
            self._pump_stage = "fast"
            self._pump_rate_basis = "configured_calibrated_fast_rate"
            self._pump_command_tracking_enabled = False
            self._pump_continuous_started_monotonic_s = None
            self._pump_active_elapsed_s = 0.0
            self._pump_commanded_volume_ml = 0.0
            self._pump_state = "running"
            self._pump_pulse_count = 0
            self._pump_pulse_steps_total = 0
            self._pump_nominal_ml_per_step = None
            self._pump_last_nominal_pulse_volume_ml = None
            self._experiment_metadata = dict(experiment_metadata or {})
            self._auto_stop_status = {
                key: value for key, value in self._experiment_metadata.items() if str(key).startswith("auto_stop_")
            }
            calculated_theory = _theoretical_equivalence_volume_from_metadata(self._experiment_metadata)
            for key, value in _theoretical_titration_fields_from_metadata(self._experiment_metadata).items():
                self._experiment_metadata.setdefault(key, value)
            if calculated_theory is not None:
                self._experiment_metadata.setdefault("equivalence_formula", "nMV=n'M'V'")
                self._experiment_metadata.setdefault("calculated_theoretical_equivalence_volume_ml", round(calculated_theory, 6))
                calculated_from_theory = _concentration_from_titrant_volume(
                    titrant_volume_ml=_finite_float_or_none(theoretical_equivalence_volume_ml) or calculated_theory,
                    titrant_concentration_M=self._experiment_metadata.get("titrant_concentration_M"),
                    titrant_valence=self._experiment_metadata.get("titrant_valence"),
                    sample_volume_ml=self._experiment_metadata.get("sample_volume_ml"),
                    sample_valence=self._experiment_metadata.get("sample_valence"),
                )
                if calculated_from_theory is not None:
                    self._experiment_metadata.setdefault(
                        "sample_concentration_from_theoretical_equivalence_M",
                        round(calculated_from_theory, 8),
                    )
            self._theoretical_equivalence_volume_ml = _finite_float_or_none(theoretical_equivalence_volume_ml)
            if self._theoretical_equivalence_volume_ml is None:
                self._theoretical_equivalence_volume_ml = calculated_theory
            parsed_window = _finite_float_or_none(equivalence_window_ml)
            self._equivalence_window_ml = 0.05 if parsed_window is None or parsed_window <= 0 else parsed_window
            self._csv_event_note = self._sanitize_note(event_note)
            self._csv_mark_sequence = 1 if self._csv_event_note else 0
            self._predicted_equivalence_status = PREDICTION_STATUS_PENDING
            self._predicted_equivalence_reason = "recording_not_finalized"
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=self._started_monotonic_s)

    def update_auto_stop_status(self, status: dict[str, Any]) -> None:
        """Attach controller state to live status and the latest audit row."""

        safe = {str(key): value for key, value in dict(status).items() if str(key).startswith("auto_stop_")}
        if not safe:
            return
        with self._condition:
            self._auto_stop_status.update(safe)
            if self._rows:
                self._rows[-1].update(safe)
                self._refresh_fieldnames_locked()
            self._updated_epoch_s = round(time.time(), 6)
            self._condition.notify_all()

    def begin_commanded_pump_timeline(
        self,
        *,
        now_monotonic_s: float | None = None,
        running: bool = True,
    ) -> dict[str, Any]:
        """Track commanded motor-active time instead of wall-clock recording time."""

        with self._condition:
            if not self._recording:
                raise RuntimeError("cannot start commanded pump tracking outside a recording")
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
            self._pump_command_tracking_enabled = True
            self._pump_active_elapsed_s = 0.0
            self._pump_commanded_volume_ml = 0.0
            self._pump_pulse_count = 0
            self._pump_pulse_steps_total = 0
            self._pump_nominal_ml_per_step = None
            self._pump_last_nominal_pulse_volume_ml = None
            self._pump_continuous_started_monotonic_s = now if running else None
            self._pump_state = "continuous" if running else "stopped"
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=now)

    def pause_commanded_pump_timeline(
        self,
        *,
        now_monotonic_s: float | None = None,
        state: str = "stopped",
    ) -> dict[str, Any]:
        with self._condition:
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
            self._close_continuous_segment_locked(now)
            if self._pump_command_tracking_enabled:
                self._pump_state = str(state or "stopped")
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=now)

    def resume_commanded_pump_timeline(
        self,
        *,
        now_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        with self._condition:
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
            if not self._recording or not self._pump_command_tracking_enabled:
                raise RuntimeError("commanded pump tracking is not active")
            if self._pump_continuous_started_monotonic_s is None:
                self._pump_continuous_started_monotonic_s = now
            self._pump_state = "continuous"
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=now)

    def start_commanded_continuous_segment(
        self,
        *,
        rate_ml_per_s: float,
        stage: str,
        rate_basis: str,
        now_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        """Close the prior segment and start a new active-rate segment."""

        rate = _finite_float_or_none(rate_ml_per_s)
        if rate is None or rate <= 0:
            raise ValueError("rate_ml_per_s must be positive and finite")
        with self._condition:
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
            if not self._recording or not self._pump_command_tracking_enabled:
                raise RuntimeError("commanded pump tracking is not active")
            self._close_continuous_segment_locked(now)
            self._pump_current_rate_ml_per_s = rate
            self._pump_stage = str(stage or "continuous")
            self._pump_rate_basis = str(rate_basis or "configured")
            self._pump_continuous_started_monotonic_s = now
            self._pump_state = "continuous"
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=now)

    def record_commanded_pulse(
        self,
        *,
        steps: int,
        nominal_ml_per_step: float,
        now_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        if isinstance(steps, bool) or not isinstance(steps, int) or not 0 < steps <= ENDPOINT_PULSE_MAX_STEPS:
            raise ValueError(f"steps must be in 1..{ENDPOINT_PULSE_MAX_STEPS}")
        ml_per_step = _finite_float_or_none(nominal_ml_per_step)
        if ml_per_step is None or ml_per_step <= 0:
            raise ValueError("nominal_ml_per_step must be positive and finite")
        with self._condition:
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
            if not self._pump_command_tracking_enabled:
                raise RuntimeError("commanded pump tracking is not enabled")
            self._close_continuous_segment_locked(now)
            pulse_volume_ml = steps * ml_per_step
            self._pump_commanded_volume_ml += pulse_volume_ml
            # Firmware STEP remains fixed at 100 full steps/s regardless of a
            # previously configured continuous RATE.
            self._pump_active_elapsed_s += steps / ARDUINO_FULL_STEPS_PER_SECOND
            self._pump_pulse_count += 1
            self._pump_pulse_steps_total += steps
            self._pump_nominal_ml_per_step = ml_per_step
            self._pump_last_nominal_pulse_volume_ml = pulse_volume_ml
            self._pump_state = "pulse_settling"
            self._pump_stage = "step_pulse"
            self._pump_current_rate_ml_per_s = None
            self._pump_rate_basis = "nominal_calibrated_ml_per_step_at_fixed_100_steps_per_s"
            self._condition.notify_all()
            return self._status_locked(now_monotonic_s=now)

    def _close_continuous_segment_locked(self, now_monotonic_s: float) -> None:
        started = self._pump_continuous_started_monotonic_s
        if not self._pump_command_tracking_enabled or started is None:
            return
        elapsed = max(0.0, float(now_monotonic_s) - started)
        self._pump_active_elapsed_s += elapsed
        if self._pump_current_rate_ml_per_s is not None and self._pump_current_rate_ml_per_s > 0:
            self._pump_commanded_volume_ml += elapsed * self._pump_current_rate_ml_per_s
        self._pump_continuous_started_monotonic_s = None

    def _commanded_pump_snapshot_locked(self, now_monotonic_s: float) -> tuple[float, float]:
        elapsed = self._pump_active_elapsed_s
        volume = self._pump_commanded_volume_ml
        started = self._pump_continuous_started_monotonic_s
        if started is not None:
            active_delta = max(0.0, float(now_monotonic_s) - started)
            elapsed += active_delta
            if self._pump_current_rate_ml_per_s is not None and self._pump_current_rate_ml_per_s > 0:
                volume += active_delta * self._pump_current_rate_ml_per_s
        return elapsed, volume

    def request_stop(self) -> dict[str, Any]:
        with self._condition:
            if self._state == "finalizing":
                # Stop is intentionally idempotent. A second browser click must
                # not expose a partial CSV while the preserved FIFO is draining.
                self._recording = False
                self._finalizing = True
                return self._status_locked()
            now = round(time.time(), 6)
            stopped_monotonic_s = time.perf_counter()
            self._close_continuous_segment_locked(stopped_monotonic_s)
            if self._pump_command_tracking_enabled:
                self._pump_state = "stopped"
            self._recording = False
            self._finalizing = self._state == "recording"
            self._state = "finalizing" if self._finalizing else self._state
            self._stopped_epoch_s = now
            self._stopped_monotonic_s = stopped_monotonic_s
            self._updated_epoch_s = now
            self._condition.notify_all()
            return self._status_locked()

    def complete_stop(self) -> dict[str, Any]:
        with self._condition:
            now = round(time.time(), 6)
            self._recording = False
            self._finalizing = False
            self._state = "stopped" if self._state in {"recording", "finalizing"} else self._state
            self._finalize_predicted_equivalence_locked()
            self._updated_epoch_s = now
            self._condition.notify_all()
            return self._status_locked()

    def stop_recording(self) -> dict[str, Any]:
        self.request_stop()
        return self.complete_stop()

    def _pump_timeline_configured_locked(self) -> bool:
        return self._pump_rate_ml_per_s is not None or self._theoretical_equivalence_volume_ml is not None

    @staticmethod
    def _row_to_feature_sample(row: dict[str, Any]) -> FeatureSample | None:
        time_s = _finite_float_or_none(row.get("time_s"))
        volume = _finite_float_or_none(row.get("injected_volume_ml"))
        frame_id = _finite_float_or_none(row.get("frame_id"))
        if time_s is None or volume is None:
            return None
        visible_features = {key: value for key, value in row.items() if str(key).startswith(("visible_", "rgb", "hsv"))}
        thermal_features = {key: value for key, value in row.items() if str(key).startswith(("thermal_", "temperature", "raw_"))}
        warnings_text = str(row.get("warnings") or row.get("sync_warning") or "")
        warnings = tuple(part.strip() for part in warnings_text.split(";") if part.strip())
        return FeatureSample(
            time_s=float(time_s),
            frame_id=int(frame_id or 0),
            injected_volume_ml=float(volume),
            visible_features=visible_features,
            thermal_features=thermal_features,
            status_label=str(row.get("status_label") or "unknown"),
            status_confidence=float(_finite_float_or_none(row.get("status_confidence")) or 0.0),
            source_quality=str(row.get("source_quality") or "live_csv"),
            warnings=warnings,
        )

    def _refresh_fieldnames_locked(self) -> None:
        self._fieldnames = csv_fieldnames_for_rows(self._rows) if self._rows else list(DEFAULT_COLUMNS)

    def _apply_typewise_prediction_model_locked(self, prediction_rows: list[dict[str, Any]]) -> bool:
        if self._typewise_prediction_model is None or not prediction_rows:
            return False
        titration_type = str(
            self._experiment_metadata.get("titration_type")
            or self._rows[-1].get("titration_type")
            or "strong_acid_strong_base"
        )
        try:
            predicted = predict_typewise_equivalence(self._typewise_prediction_model, prediction_rows, titration_type)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            print(f"Warning: typewise live ML prediction failed; using fallback. Reason: {exc}", flush=True)
            return False
        predicted_volume = _finite_float_or_none(predicted.get("predicted_equivalence_volume_ml"))
        if predicted_volume is None or predicted_volume <= 0:
            return False
        candidate_index = predicted.pop("candidate_index", None)
        if candidate_index is None:
            target = prediction_rows[-1]
        else:
            target = prediction_rows[max(0, min(int(candidate_index), len(prediction_rows) - 1))]
        target.update({key: value for key, value in predicted.items() if key != "model_key"})
        if predicted.get("model_key"):
            target["predicted_equivalence_model_key"] = predicted["model_key"]
        target.update(_predicted_result_fields_from_row(target, self._experiment_metadata))
        self._refresh_fieldnames_locked()
        return True

    def _apply_endpoint_prediction_model_locked(self, prediction_rows: list[dict[str, Any]]) -> bool:
        if self._endpoint_prediction_model is None or not prediction_rows:
            return False
        titration_type = str(
            self._experiment_metadata.get("titration_type")
            or self._rows[-1].get("titration_type")
            or ""
        )
        try:
            predicted = predict_type_conditioned_sensor_equivalence(
                self._endpoint_prediction_model,
                prediction_rows,
                titration_type,
            )
        except (TypeError, ValueError, KeyError, AttributeError, IndexError) as exc:
            print(
                "Warning: type-conditioned sensor endpoint prediction failed; "
                f"using live classifier fallback. Reason: {exc}",
                flush=True,
            )
            return False
        predicted_volume = _finite_float_or_none(
            predicted.get("predicted_equivalence_volume_ml")
        )
        if predicted_volume is None or predicted_volume <= 0:
            return False
        candidate_index = predicted.pop("candidate_index", None)
        target = (
            prediction_rows[-1]
            if candidate_index is None
            else prediction_rows[max(0, min(int(candidate_index), len(prediction_rows) - 1))]
        )
        target.update({key: value for key, value in predicted.items() if key != "model_key"})
        if predicted.get("model_key"):
            target["predicted_equivalence_model_key"] = predicted["model_key"]
        target.update(_predicted_result_fields_from_row(target, self._experiment_metadata))
        self._refresh_fieldnames_locked()
        return True

    def _apply_prediction_model_locked(self, prediction_rows: list[dict[str, Any]]) -> bool:
        if self._prediction_model is None or not prediction_rows:
            return False
        target = prediction_rows[-1]
        try:
            predicted = predict_row(self._prediction_model, target)
        except (TypeError, ValueError, KeyError):
            return False
        predicted_volume = _finite_float_or_none(predicted.get("predicted_equivalence_volume_ml"))
        if predicted_volume is None or predicted_volume <= 0:
            return False
        target.update(predicted)
        target["predicted_equivalence_source"] = "ml_json_regression_model"
        target["predicted_equivalence_evidence"] = "saved regression model applied to final live row"
        target.update(_predicted_result_fields_from_row(target, self._experiment_metadata))
        self._refresh_fieldnames_locked()
        return True

    def _set_prediction_outcome_locked(self, status: str, reason: str) -> None:
        self._predicted_equivalence_status = status
        self._predicted_equivalence_reason = reason
        if self._rows:
            self._rows[-1]["predicted_equivalence_status"] = status
            self._rows[-1]["predicted_equivalence_reason"] = reason
            self._refresh_fieldnames_locked()

    def _clear_final_prediction_fields_locked(self) -> None:
        for row in self._rows:
            for key in FINAL_PREDICTION_FIELDS:
                row.pop(key, None)
        self._refresh_fieldnames_locked()

    def _finalize_predicted_equivalence_locked(self) -> None:
        readiness = evaluate_prediction_readiness(self._rows)
        if not readiness.ready:
            self._clear_final_prediction_fields_locked()
            self._set_prediction_outcome_locked(PREDICTION_STATUS_WITHHELD, readiness.reason)
            return
        prediction_rows = [self._rows[index] for index in readiness.usable_row_indices]
        for row in reversed(self._rows):
            if _finite_float_or_none(row.get("predicted_equivalence_volume_ml")) is None:
                continue
            row.update(_predicted_result_fields_from_row(row, self._experiment_metadata))
            self._set_prediction_outcome_locked(PREDICTION_STATUS_AVAILABLE, "prediction_already_recorded")
            return
        if self._apply_endpoint_prediction_model_locked(prediction_rows):
            self._set_prediction_outcome_locked(PREDICTION_STATUS_AVAILABLE, "type_conditioned_sensor_model_succeeded")
            return
        if self._apply_typewise_prediction_model_locked(prediction_rows):
            self._set_prediction_outcome_locked(PREDICTION_STATUS_AVAILABLE, "typewise_model_succeeded")
            return
        if self._apply_prediction_model_locked(prediction_rows):
            self._set_prediction_outcome_locked(PREDICTION_STATUS_AVAILABLE, "json_regression_model_succeeded")
            return
        samples_with_rows: list[tuple[FeatureSample, dict[str, Any]]] = []
        for row in prediction_rows:
            sample = self._row_to_feature_sample(row)
            if sample is not None:
                samples_with_rows.append((sample, row))
        if not samples_with_rows:
            self._set_prediction_outcome_locked(PREDICTION_STATUS_UNAVAILABLE, "no_prediction_path_succeeded")
            return
        try:
            result = estimate_equivalence_point(
                [sample for sample, _ in samples_with_rows],
                theoretical_equivalence_volume_ml=self._theoretical_equivalence_volume_ml,
            )
        except ValueError:
            self._set_prediction_outcome_locked(PREDICTION_STATUS_UNAVAILABLE, "no_prediction_path_succeeded")
            return
        row_index = result.candidate_index if result.candidate_index is not None else len(samples_with_rows) - 1
        row_index = max(0, min(int(row_index), len(samples_with_rows) - 1))
        target = samples_with_rows[row_index][1]
        target["predicted_equivalence_volume_ml"] = round(result.estimated_equivalence_volume_ml, 6)
        target["predicted_equivalence_confidence"] = round(result.confidence, 6)
        target["predicted_equivalence_source"] = "live_feature_peak_estimator"
        target["predicted_equivalence_evidence"] = "; ".join(result.evidence)
        target.update(_predicted_result_fields_from_row(target, self._experiment_metadata))
        self._set_prediction_outcome_locked(PREDICTION_STATUS_AVAILABLE, "peak_estimator_succeeded")
        self._refresh_fieldnames_locked()

    @staticmethod
    def _sanitize_note(value: Any) -> str:
        text = sanitize_csv_metadata_text(str(value or "").strip())
        return text[:240]

    def _recording_elapsed_locked(self, *, now_monotonic_s: float | None = None) -> float | None:
        if self._started_monotonic_s is None:
            return None
        if now_monotonic_s is None and not self._recording and self._stopped_monotonic_s is not None:
            now = self._stopped_monotonic_s
        else:
            now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
        return round(max(0.0, now - self._started_monotonic_s), 6)

    def _pump_timeline_fields_locked(self, *, now_monotonic_s: float | None = None) -> dict[str, Any]:
        if self._started_monotonic_s is None or not self._pump_timeline_configured_locked():
            return {}
        now = time.perf_counter() if now_monotonic_s is None else float(now_monotonic_s)
        if self._pump_command_tracking_enabled:
            elapsed, injected = self._commanded_pump_snapshot_locked(now)
            reporting_rate = self._pump_current_rate_ml_per_s or self._pump_rate_ml_per_s
            fields = build_pump_timeline_fields(
                pump_elapsed_s=elapsed,
                pump_rate_ml_per_s=reporting_rate,
                theoretical_equivalence_volume_ml=self._theoretical_equivalence_volume_ml,
                equivalence_window_ml=self._equivalence_window_ml,
                experiment_metadata=self._experiment_metadata,
                injected_volume_ml=injected,
                pump_mode="commanded_continuous_then_step_pulse",
                pump_state=self._pump_state,
            )
            fields.update(
                {
                    "pump_pulse_count": self._pump_pulse_count,
                    "pump_pulse_steps_total": self._pump_pulse_steps_total,
                    "pump_nominal_ml_per_step": ""
                    if self._pump_nominal_ml_per_step is None
                    else round(self._pump_nominal_ml_per_step, 9),
                    "pump_nominal_pulse_volume_ml": ""
                    if self._pump_last_nominal_pulse_volume_ml is None
                    else round(self._pump_last_nominal_pulse_volume_ml, 9),
                    "pump_volume_basis": "commanded_time_and_nominal_full_steps_not_direct_flow_measurement",
                    "pump_dosing_stage": self._pump_stage,
                    "pump_nominal_rate_ml_per_s": ""
                    if self._pump_current_rate_ml_per_s is None
                    else round(self._pump_current_rate_ml_per_s, 9),
                    "pump_rate_basis": self._pump_rate_basis,
                }
            )
            return fields
        return build_pump_timeline_fields(
            pump_elapsed_s=now - self._started_monotonic_s,
            pump_rate_ml_per_s=self._pump_rate_ml_per_s,
            theoretical_equivalence_volume_ml=self._theoretical_equivalence_volume_ml,
            equivalence_window_ml=self._equivalence_window_ml,
            experiment_metadata=self._experiment_metadata,
        )

    def pump_timeline_fields(self, *, now_monotonic_s: float | None = None) -> dict[str, Any]:
        with self._condition:
            if not self._recording:
                return {}
            return self._pump_timeline_fields_locked(now_monotonic_s=now_monotonic_s)

    def add(self, row: dict[str, Any], *, now_monotonic_s: float | None = None) -> bool:
        with self._condition:
            if not (self._recording or self._finalizing):
                return False
            copied = dict(row)
            capture_session_id = int(_finite_float_or_none(copied.get("capture_recording_session_id")) or 0)
            if self._capture_session_required and capture_session_id != self._session_id:
                return False
            for removed_key in ("manual_label", "predicted_manual_label", "predicted_manual_label_confidence"):
                copied.pop(removed_key, None)
            copied.update(self._experiment_metadata)
            copied.update(self._auto_stop_status)
            copied.update(self._pump_timeline_fields_locked(now_monotonic_s=now_monotonic_s))
            copied.update(
                {
                    "csv_session_id": self._session_id,
                    "csv_row_index": len(self._rows) + 1,
                    "csv_recording_started_epoch_s": "" if self._started_epoch_s is None else self._started_epoch_s,
                    "csv_recording_elapsed_s": self._recording_elapsed_locked(now_monotonic_s=now_monotonic_s),
                    "csv_mark_sequence": self._csv_mark_sequence,
                    "csv_event_note": self._csv_event_note,
                }
            )
            if not all(column in copied for column in DERIVED_ML_COLUMNS):
                history = select_online_history_rows(self._rows, copied)
                copied.update(derive_ml_features(history, copied))
            # The main loop may have calculated temporal features before the
            # recording-start metadata was merged. Always refresh the only
            # metadata-dependent derived fields after that merge.
            titration_type = str(copied.get("titration_type") or "").strip()
            for name in SUPPORTED_TITRATION_TYPES:
                copied[f"titration_is_{name}"] = 1.0 if titration_type == name else 0.0
            self._rows.append(copied)
            if not self._fieldnames:
                self._fieldnames = csv_fieldnames_for_rows([copied])
            else:
                known = set(self._fieldnames)
                missing = [key for key in copied.keys() if key not in known]
                if missing:
                    self._fieldnames = csv_fieldnames_for_rows(self._rows)
            self._updated_epoch_s = round(time.time(), 6)
            self._condition.notify_all()
            return True

    def latest_recorded_row(self, session_id: int) -> dict[str, Any] | None:
        """Return the accepted CSV observation with its recording clock and metadata."""
        with self._condition:
            if self._session_id != session_id or not self._rows:
                return None
            if not self._recording:
                return None
            return dict(self._rows[-1])

    def _latest_predicted_result_fields_locked(self) -> dict[str, Any]:
        if self._predicted_equivalence_status != PREDICTION_STATUS_AVAILABLE:
            return {}
        keys = (
            "predicted_equivalence_volume_ml",
            "sample_concentration_from_predicted_equivalence_M",
            "predicted_sample_concentration_error_percent",
            "predicted_equivalence_pH",
            "predicted_equivalence_pH_model",
            "predicted_equivalence_pH_warning",
            "predicted_equivalence_confidence",
            "predicted_equivalence_source",
            "predicted_equivalence_evidence",
            "predicted_equivalence_model_key",
        )
        for row in reversed(self._rows):
            if _finite_float_or_none(row.get("predicted_equivalence_volume_ml")) is None:
                continue
            fields = {key: row.get(key) for key in keys if row.get(key) not in (None, "")}
            fields.update(_predicted_result_fields_from_row(row, self._experiment_metadata))
            return fields
        return {}

    def status(self, *, now_monotonic_s: float | None = None) -> dict[str, Any]:
        with self._condition:
            return self._status_locked(now_monotonic_s=now_monotonic_s)

    def _status_locked(self, *, now_monotonic_s: float | None = None) -> dict[str, Any]:
        recording_elapsed_s = self._recording_elapsed_locked(now_monotonic_s=now_monotonic_s)
        if recording_elapsed_s is not None and recording_elapsed_s > 0:
            csv_rows_per_s: float | int = round(len(self._rows) / recording_elapsed_s, 6)
        else:
            csv_rows_per_s = 0.0
        status = {
            "path": _repo_relative_path(self.output_path),
            "row_count": len(self._rows),
            "csv_rows_per_s": csv_rows_per_s,
            "updated_epoch_s": self._updated_epoch_s,
            "started_epoch_s": self._started_epoch_s,
            "stopped_epoch_s": self._stopped_epoch_s,
            "recording": self._recording,
            "finalizing": self._finalizing,
            "state": self._state,
            "session_id": self._session_id,
            "roi_session_id": self._roi_session_id,
            "columns": list(self._fieldnames),
            "recording_elapsed_s": recording_elapsed_s,
            "csv_event_note": self._csv_event_note,
            "csv_mark_sequence": self._csv_mark_sequence,
            "predicted_equivalence_status": self._predicted_equivalence_status,
            "predicted_equivalence_reason": self._predicted_equivalence_reason,
        }
        status.update(self._experiment_metadata)
        status.update(self._auto_stop_status)
        status.update(self._latest_predicted_result_fields_locked())
        if self._pump_timeline_configured_locked():
            if self._recording:
                status.update(self._pump_timeline_fields_locked(now_monotonic_s=now_monotonic_s))
            elif self._pump_command_tracking_enabled:
                status.update(
                    self._pump_timeline_fields_locked(
                        now_monotonic_s=self._stopped_monotonic_s
                    )
                )
            else:
                status.update(
                    {
                        "pump_run_rate_ml_per_s": "" if self._pump_rate_ml_per_s is None else round(self._pump_rate_ml_per_s, 6),
                        "theoretical_equivalence_volume_ml": ""
                        if self._theoretical_equivalence_volume_ml is None
                        else round(self._theoretical_equivalence_volume_ml, 6),
                        "equivalence_window_ml": round(self._equivalence_window_ml, 6),
                    }
                )
        return status

    def to_csv_bytes(self) -> bytes:
        with self._condition:
            rows = [dict(row) for row in self._rows]
            fieldnames = list(self._fieldnames) or list(DEFAULT_COLUMNS)
        handle = io.StringIO(newline="")
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return handle.getvalue().encode("utf-8-sig")

    def download_filename(self) -> str:
        with self._condition:
            stamp_epoch = self._started_epoch_s or time.time()
            session_id = self._session_id
        try:
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(float(stamp_epoch)))
        except (TypeError, ValueError, OSError):
            stamp = time.strftime("%Y%m%d-%H%M%S")
        return f"auto-titration-live-{stamp}-session-{session_id}.csv"


class EndpointPulseRuntime:
    """Translate live endpoint scores into bounded STEP pulses.

    The recorded pulse volume is a nominal motor-step conversion, not a direct
    flow measurement. Final endpoint confirmation remains the existing
    model-confirmed persistent visible-color detector.
    """

    def __init__(
        self,
        *,
        command_sender: Callable[[str], Any],
        stop_continuous: Callable[[str], Any],
        csv_buffer: LiveCsvBuffer,
        on_safety_stop: Callable[[int, str, float | None, float], None],
        start_slow_continuous: Callable[..., Any] | None = None,
    ) -> None:
        self._command_sender = command_sender
        self._stop_continuous = stop_continuous
        self._csv_buffer = csv_buffer
        self._on_safety_stop = on_safety_stop
        self._start_slow_continuous = start_slow_continuous
        self._lock = threading.Lock()
        self._controller: PulseController | None = None
        self._controller_started = False
        self._session_id = 0
        self._enabled = False
        self._state = "disabled"
        self._reason = "default_off"
        self._pulse_complete_at_s: float | None = None
        self._pulse_count = 0
        self._pulse_steps = ENDPOINT_PULSE_DEFAULT_STEPS
        self._nominal_ml_per_step = 0.0
        self._ml_per_step_upper_bound = 0.0
        self._nominal_pulse_volume_ml = 0.0
        self._maximum_pump_rate_ml_per_s = 0.0
        self._conservative_volume_ml = 0.0
        self._continuous_guard_active = False
        self._settle_time_s = ENDPOINT_PULSE_DEFAULT_SETTLE_S
        self._approach_score = ENDPOINT_PULSE_DEFAULT_APPROACH_SCORE
        self._maximum_volume_ml = AUTO_STOP_MAX_VOLUME_ML
        self._last_command = ""
        self._error = ""
        self._cancel_event = threading.Event()
        self._slow_stage_enabled = False
        self._slow_rate_steps_per_s = 100
        self._slow_nominal_rate_ml_per_s = 0.0
        self._absolute_maximum_run_time_s = ABSOLUTE_PUMP_MAX_RUN_TIME_S
        self._absolute_deadline_monotonic_s: float | None = None

    def arm(
        self,
        *,
        session_id: int,
        requested: bool,
        pump_started: bool,
        pump_rate_ml_per_s: float | None,
        maximum_pump_rate_ml_per_s: float | None,
        pulse_ml_per_step_upper_bound: float | None,
        maximum_volume_ml: float,
        pulse_nominal_ml_per_step: float | None = None,
        dispense_direction: str = "b",
        approach_score: float = ENDPOINT_PULSE_DEFAULT_APPROACH_SCORE,
        pulse_steps: int = ENDPOINT_PULSE_DEFAULT_STEPS,
        settle_time_s: float = ENDPOINT_PULSE_DEFAULT_SETTLE_S,
        slow_stage_enabled: bool = False,
        slow_onset_score: float = 0.0,
        slow_onset_duration_s: float = 0.0,
        slow_rate_steps_per_s: int = 100,
        absolute_maximum_run_time_s: float = ABSOLUTE_PUMP_MAX_RUN_TIME_S,
        absolute_deadline_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        rate = _finite_float_or_none(pump_rate_ml_per_s)
        maximum_rate = _finite_float_or_none(maximum_pump_rate_ml_per_s)
        ml_per_step_upper_bound = _finite_float_or_none(pulse_ml_per_step_upper_bound)
        nominal_ml_per_step = _finite_float_or_none(pulse_nominal_ml_per_step)
        if nominal_ml_per_step is None:
            nominal_ml_per_step = ml_per_step_upper_bound
        maximum = _finite_float_or_none(maximum_volume_ml)
        approach = _finite_float_or_none(approach_score)
        settle = _finite_float_or_none(settle_time_s)
        slow_onset = _finite_float_or_none(slow_onset_score)
        slow_duration = _finite_float_or_none(slow_onset_duration_s)
        absolute_time = _finite_float_or_none(absolute_maximum_run_time_s)
        absolute_deadline = _finite_float_or_none(absolute_deadline_monotonic_s)
        with self._lock:
            self._cancel_event = threading.Event()
            self._session_id = int(session_id)
            self._controller = None
            self._controller_started = False
            self._enabled = bool(requested)
            self._pulse_complete_at_s = None
            self._pulse_count = 0
            self._maximum_pump_rate_ml_per_s = 0.0
            self._conservative_volume_ml = 0.0
            self._continuous_guard_active = False
            self._nominal_ml_per_step = 0.0
            self._ml_per_step_upper_bound = 0.0
            self._nominal_pulse_volume_ml = 0.0
            self._last_command = ""
            self._error = ""
            self._slow_stage_enabled = bool(slow_stage_enabled)
            self._slow_rate_steps_per_s = int(slow_rate_steps_per_s) if not isinstance(slow_rate_steps_per_s, bool) else 0
            self._slow_nominal_rate_ml_per_s = 0.0
            self._absolute_maximum_run_time_s = min(
                absolute_time or ABSOLUTE_PUMP_MAX_RUN_TIME_S,
                ABSOLUTE_PUMP_MAX_RUN_TIME_S,
            )
            self._absolute_deadline_monotonic_s = absolute_deadline
            if not requested:
                self._state = "disabled"
                self._reason = "user_disabled"
            elif not pump_started:
                self._state = "unavailable"
                self._reason = "pump_not_started"
            elif str(dispense_direction) not in {"a", "b"}:
                self._state = "unavailable"
                self._reason = "pulse_direction_invalid"
            elif (
                rate is None
                or rate <= 0
                or maximum_rate is None
                or maximum_rate <= 0
                or maximum_rate < rate
                or ml_per_step_upper_bound is None
                or ml_per_step_upper_bound <= 0
                or nominal_ml_per_step is None
                or nominal_ml_per_step <= 0
                or nominal_ml_per_step > ml_per_step_upper_bound
                or maximum is None
                or maximum <= 0
                or approach is None
                or not 0 < approach < 1
                or settle is None
                or settle < 0
                or isinstance(pulse_steps, bool)
                or not isinstance(pulse_steps, int)
                or not 0 < pulse_steps <= ENDPOINT_PULSE_MAX_STEPS
                or (
                    self._slow_stage_enabled
                    and (
                        self._start_slow_continuous is None
                        or slow_onset is None
                        or not 0 <= slow_onset < approach
                        or slow_duration is None
                        or slow_duration < 0
                        or not 1 <= self._slow_rate_steps_per_s <= 100
                        or absolute_time is None
                        or absolute_time <= 0
                        or absolute_deadline is None
                    )
                )
            ):
                self._state = "unavailable"
                self._reason = "invalid_pulse_settings"
            else:
                # This is deliberately supplied separately from the operating
                # flow rate.  It must be the conservative upper bound obtained
                # from water calibration, not a value inferred from 100 step/s.
                try:
                    self._controller = PulseController(
                        PulseControlConfig(
                            approach_score=approach,
                            endpoint_score=1.0,
                            confirmation_duration_s=0.0,
                            pulse_steps=pulse_steps,
                            settle_time_s=settle,
                            max_volume_ml=min(maximum, ABSOLUTE_PUMP_MAX_VOLUME_ML),
                            ml_per_step=ml_per_step_upper_bound,
                            fast_rate_ml_per_s=rate,
                            endpoint_confirmation_enabled=False,
                            slow_stage_enabled=self._slow_stage_enabled,
                            slow_onset_score=slow_onset or 0.0,
                            slow_onset_duration_s=slow_duration or 0.0,
                            slow_rate_steps_per_s=self._slow_rate_steps_per_s,
                        )
                    )
                except ValueError as exc:
                    self._controller = None
                    self._state = "unavailable"
                    self._reason = "invalid_pulse_settings"
                    self._error = str(exc)
                else:
                    self._pulse_steps = pulse_steps
                    self._maximum_pump_rate_ml_per_s = maximum_rate
                    self._continuous_guard_active = True
                    self._nominal_ml_per_step = nominal_ml_per_step
                    self._ml_per_step_upper_bound = ml_per_step_upper_bound
                    self._nominal_pulse_volume_ml = pulse_steps * nominal_ml_per_step
                    self._settle_time_s = settle
                    self._approach_score = approach
                    self._maximum_volume_ml = min(maximum, ABSOLUTE_PUMP_MAX_VOLUME_ML)
                    self._slow_nominal_rate_ml_per_s = (
                        rate * self._slow_rate_steps_per_s / ARDUINO_FULL_STEPS_PER_SECOND
                    )
                    self._state = "armed_continuous"
                    self._reason = "waiting_for_model_approach"
            status = self._status_locked()
        self._csv_buffer.update_auto_stop_status(status)
        return status

    def disarm(self, reason: str = "manual_stop") -> dict[str, Any]:
        # Set before taking the runtime lock so an in-flight STOP/RATE/G
        # sequence can observe cancellation before writing a new direction.
        self._cancel_event.set()
        with self._lock:
            self._enabled = False
            self._controller = None
            self._controller_started = False
            self._pulse_complete_at_s = None
            if self._state not in {"stopped", "error"}:
                self._state = "disabled"
                self._reason = str(reason or "manual_stop")
            status = self._status_locked()
        self._csv_buffer.update_auto_stop_status(status)
        return status

    def handle_auto_stop_status(self, status: Mapping[str, Any]) -> None:
        if str(status.get("auto_stop_state") or "") == "triggered":
            return
        session_id = int(_finite_float_or_none(status.get("auto_stop_session_id")) or 0)
        now_s = _finite_float_or_none(status.get("auto_stop_observation_elapsed_s"))
        volume_ml = _finite_float_or_none(status.get("auto_stop_observation_volume_ml"))
        score = _finite_float_or_none(status.get("auto_stop_endpoint_score"))
        baseline_ready = bool(status.get("auto_stop_baseline_ready"))
        if now_s is None or volume_ml is None or score is None or not baseline_ready:
            return
        safety_stop: tuple[int, str, float | None, float] | None = None
        with self._lock:
            controller = self._controller
            if not self._enabled or controller is None or session_id != self._session_id:
                return
            try:
                # While the continuous firmware guard is active, account at
                # the independently supplied maximum flow rate.  Once STOP
                # retires that guard, freeze this continuous bound; the pulse
                # controller then reserves every STEP at the separately
                # calibrated per-step upper bound before transmission.
                if self._continuous_guard_active:
                    self._conservative_volume_ml = max(
                        self._conservative_volume_ml,
                        now_s * self._maximum_pump_rate_ml_per_s,
                        volume_ml,
                    )
                else:
                    self._conservative_volume_ml = max(
                        self._conservative_volume_ml,
                        volume_ml,
                    )
                if not self._controller_started:
                    controller.start(
                        now_s=now_s,
                        injected_volume_ml=self._conservative_volume_ml,
                    )
                    self._controller_started = True
                if controller.state is PulseState.PULSE_INJECT:
                    complete_at = self._pulse_complete_at_s
                    if complete_at is None or now_s < complete_at:
                        return
                    completed = controller.update(
                        PulseObservation(
                            now_s=now_s,
                            score=max(0.0, min(1.0, score)),
                            injected_volume_ml=self._conservative_volume_ml,
                            pulse_complete=True,
                        )
                    )
                    self._apply_transition_locked(completed, now_s=now_s)
                    if completed.state is PulseState.STOPPED:
                        safety_stop = (session_id, completed.reason, volume_ml, now_s)
                if safety_stop is None and controller.state is not PulseState.STOPPED:
                    transition = controller.update(
                        PulseObservation(
                            now_s=now_s,
                            score=max(0.0, min(1.0, score)),
                            injected_volume_ml=self._conservative_volume_ml,
                        )
                    )
                    self._apply_transition_locked(transition, now_s=now_s)
                    if transition.state is PulseState.STOPPED:
                        safety_stop = (session_id, transition.reason, volume_ml, now_s)
            except Exception as exc:  # noqa: BLE001 - a dosing failure must fail closed.
                self._error = str(exc)
                self._state = "error"
                self._reason = "pulse_control_failed"
                try:
                    self._stop_continuous("pulse_control_failed")
                except Exception:
                    pass
                safety_stop = (session_id, self._reason, volume_ml, now_s)
            pulse_status = self._status_locked()
        self._csv_buffer.update_auto_stop_status(pulse_status)
        if safety_stop is not None:
            self._on_safety_stop(*safety_stop)

    def _apply_transition_locked(self, transition, *, now_s: float) -> None:  # type: ignore[no-untyped-def]
        self._reason = transition.reason
        if transition.state is PulseState.FAST_CONTINUOUS:
            self._state = "continuous"
        elif transition.state is PulseState.SLOW_CONTINUOUS:
            self._state = "slow_continuous"
        elif transition.state is PulseState.PULSE_WAIT:
            self._state = "pulse_settling"
        elif transition.state is PulseState.PULSE_INJECT:
            self._state = "pulse_injecting"
        else:
            self._state = "stopped"
        for intent in transition.intents:
            command = intent.command
            self._last_command = command
            if command == "STOP":
                self._stop_continuous(intent.reason)
                confirmed_stop_elapsed = _finite_float_or_none(
                    self._csv_buffer.status().get("recording_elapsed_s")
                )
                if confirmed_stop_elapsed is not None:
                    self._conservative_volume_ml = max(
                        self._conservative_volume_ml,
                        confirmed_stop_elapsed * self._maximum_pump_rate_ml_per_s,
                    )
                self._continuous_guard_active = False
                self._csv_buffer.pause_commanded_pump_timeline(
                    state="pulse_settling",
                )
            elif command.startswith("RATE "):
                # RATE is sent by the slow-rearm callback immediately before G;
                # handling it here would split the required atomic sequence.
                continue
            elif command.startswith("RUN_RATE "):
                if transition.state is not PulseState.SLOW_CONTINUOUS:
                    continue
                if self._start_slow_continuous is None or self._cancel_event.is_set():
                    raise RuntimeError("slow-stage restart was cancelled after stop")
                remaining_volume_ml = self._maximum_volume_ml - self._conservative_volume_ml
                if remaining_volume_ml <= 0:
                    raise RuntimeError("slow-stage absolute session budget is exhausted")
                response = self._start_slow_continuous(
                    rate_steps_per_s=self._slow_rate_steps_per_s,
                    nominal_rate_ml_per_s=self._slow_nominal_rate_ml_per_s,
                    maximum_rate_ml_per_s=self._maximum_pump_rate_ml_per_s,
                    remaining_volume_ml=remaining_volume_ml,
                    absolute_deadline_monotonic_s=self._absolute_deadline_monotonic_s,
                    can_restart=lambda: not self._cancel_event.is_set(),
                )
                if self._cancel_event.is_set():
                    raise RuntimeError("slow-stage restart was cancelled")
                self._continuous_guard_active = True
                self._csv_buffer.start_commanded_continuous_segment(
                    rate_ml_per_s=self._slow_nominal_rate_ml_per_s,
                    stage="slow_continuous",
                    rate_basis="nominal_uncalibrated_fast_rate_times_steps_per_100",
                    now_monotonic_s=_finite_float_or_none(
                        response.get("direction_written_monotonic_s")
                        if isinstance(response, Mapping)
                        else None
                    ),
                )
            elif command.startswith("STEP "):
                steps = int(command.split(" ", 1)[1])
                # Reserve the full conservative pulse before transmission.  If
                # acknowledgement is lost, assuming the dose was delivered is
                # the only fail-safe accounting choice.
                self._conservative_volume_ml += steps * self._ml_per_step_upper_bound
                response = self._command_sender(f"STEP {steps}\n")
                expected_ack = f"STEP ACCEPTED {steps}"
                acknowledgement = (
                    str(response.get("firmware_ack") or "")
                    if isinstance(response, Mapping)
                    else str(response or "")
                )
                if acknowledgement != expected_ack:
                    raise RuntimeError(
                        "firmware did not confirm completed pulse command: "
                        f"{acknowledgement or 'no acknowledgement'}"
                    )
                self._csv_buffer.record_commanded_pulse(
                    steps=steps,
                    nominal_ml_per_step=self._nominal_ml_per_step,
                )
                self._pulse_count += 1
                # The serial bridge returns only after receiving the firmware's
                # PUMP STOPPED PULSE_COMPLETE line, so no time-based completion
                # guess is needed.  The next observation advances the state.
                self._pulse_complete_at_s = now_s
            elif command == "EMERGENCY_STOP":
                self._stop_continuous(intent.reason)

    def _status_locked(self) -> dict[str, Any]:
        return {
            "auto_stop_pulse_enabled": self._enabled,
            "auto_stop_pulse_state": self._state,
            "auto_stop_pulse_reason": self._reason,
            "auto_stop_pulse_session_id": self._session_id,
            "auto_stop_pulse_approach_score": round(self._approach_score, 6),
            "auto_stop_pulse_steps": self._pulse_steps,
            "auto_stop_pulse_settle_time_s": round(self._settle_time_s, 6),
            "auto_stop_pulse_count": self._pulse_count,
            "auto_stop_pulse_last_command": self._last_command,
            "auto_stop_pulse_nominal_ml_per_step": round(self._nominal_ml_per_step, 9),
            "auto_stop_pulse_configured_ml_per_step_upper_bound": round(
                self._ml_per_step_upper_bound,
                9,
            ),
            "auto_stop_pulse_nominal_volume_ml": round(self._nominal_pulse_volume_ml, 9),
            "auto_stop_pulse_maximum_volume_ml": round(self._maximum_volume_ml, 6),
            "auto_stop_pulse_maximum_pump_rate_ml_per_s": round(
                self._maximum_pump_rate_ml_per_s,
                6,
            ),
            "auto_stop_pulse_conservative_volume_ml": round(
                self._conservative_volume_ml,
                9,
            ),
            "auto_stop_pulse_volume_basis": "configured_conservative_upper_bound_not_direct_drop_measurement",
            "auto_stop_pulse_error": self._error,
            "auto_stop_slow_stage_enabled": self._slow_stage_enabled,
            "auto_stop_slow_rate_steps_per_s": self._slow_rate_steps_per_s,
            "auto_stop_slow_nominal_rate_ml_per_s": round(self._slow_nominal_rate_ml_per_s, 9),
            "auto_stop_slow_rate_basis": "nominal_uncalibrated_fast_rate_times_steps_per_100",
        }


class LiveControlState:
    """Thread-safe runtime controls changed from the browser dashboard."""

    VALID_AUTO_MODES = {"off", "visible", "thermal", "both"}
    VALID_VISIBLE_DETECTORS = {"yolo"}
    VALID_THERMAL_ROTATIONS = {0, 180}

    def __init__(
        self,
        *,
        roi_auto_detect: str = "off",
        visible_roi_detector: str = "yolo",
        yolo_available: bool = False,
        thermal_rotation_degrees: int = 0,
    ) -> None:
        self._lock = threading.Lock()
        self._roi_auto_detect = self._validate_auto_mode(roi_auto_detect)
        self._visible_roi_detector = self._validate_visible_detector(visible_roi_detector)
        self._yolo_available = bool(yolo_available)
        self._thermal_rotation_degrees = self._validate_thermal_rotation(thermal_rotation_degrees)
        self._updated_epoch_s = round(time.time(), 6)

    @classmethod
    def _validate_auto_mode(cls, value: Any) -> str:
        mode = str(value or "off").strip().lower()
        if mode not in cls.VALID_AUTO_MODES:
            raise ValueError(f"roi_auto_detect must be one of {sorted(cls.VALID_AUTO_MODES)}")
        return mode

    @classmethod
    def _validate_visible_detector(cls, value: Any) -> str:
        detector = str(value or "yolo").strip().lower()
        if detector not in cls.VALID_VISIBLE_DETECTORS:
            raise ValueError(f"visible_roi_detector must be one of {sorted(cls.VALID_VISIBLE_DETECTORS)}")
        return detector

    @classmethod
    def _validate_thermal_rotation(cls, value: Any) -> int:
        try:
            degrees = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("thermal_rotation_degrees must be 0 or 180") from exc
        if degrees not in cls.VALID_THERMAL_ROTATIONS:
            raise ValueError("thermal_rotation_degrees must be 0 or 180")
        return degrees

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "roi_auto_detect": self._roi_auto_detect,
                "visible_roi_detector": self._visible_roi_detector,
                "yolo_enabled": self._visible_roi_detector == "yolo",
                "yolo_available": self._yolo_available,
                "thermal_rotation_degrees": self._thermal_rotation_degrees,
                "allowed_roi_auto_detect": sorted(self.VALID_AUTO_MODES),
                "allowed_visible_roi_detector": sorted(self.VALID_VISIBLE_DETECTORS),
                "allowed_thermal_rotation_degrees": sorted(self.VALID_THERMAL_ROTATIONS),
                "settings_updated_epoch_s": self._updated_epoch_s,
            }

    def update_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("settings payload must be a JSON object")
        with self._lock:
            if "yolo_enabled" in payload and "visible_roi_detector" not in payload:
                self._visible_roi_detector = "yolo"
            if "visible_roi_detector" in payload:
                self._visible_roi_detector = self._validate_visible_detector(payload["visible_roi_detector"])
            if "roi_auto_detect" in payload:
                self._roi_auto_detect = self._validate_auto_mode(payload["roi_auto_detect"])
            if "thermal_rotation_degrees" in payload:
                self._thermal_rotation_degrees = self._validate_thermal_rotation(payload["thermal_rotation_degrees"])
            self._updated_epoch_s = round(time.time(), 6)
        return self.snapshot()

    def set_yolo_available(self, available: bool) -> dict[str, Any]:
        """Publish optional setup-detector availability after lazy loading."""

        with self._lock:
            self._yolo_available = bool(available)
            self._updated_epoch_s = round(time.time(), 6)
        return self.snapshot()


@dataclass(frozen=True)
class LiveStreamServerHandle:
    server: ThreadingHTTPServer
    thread: threading.Thread

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        absolute_guard = getattr(self.server, "absolute_pump_safety_guard", None)
        if isinstance(absolute_guard, AbsolutePumpSafetyGuard):
            absolute_guard.close()


class PulseDeliveryUncertainError(RuntimeError):
    """A STEP command may have moved the pump but was not fully acknowledged."""


def _serial_response_line(serial_obj: Any) -> str:
    readline = getattr(serial_obj, "readline", None)
    if not callable(readline):
        raise RuntimeError("pump serial transport cannot read firmware acknowledgement")
    response = readline()
    return (
        response.decode("ascii", errors="replace").strip()
        if isinstance(response, bytes)
        else str(response or "").strip()
    )


def _best_effort_serial_stop(serial_obj: Any) -> None:
    """Request the legacy immediate stop without masking the original error."""

    try:
        serial_obj.write(b"c")
        flush = getattr(serial_obj, "flush", None)
        if callable(flush):
            flush()
    except Exception:
        pass


def _wait_for_step_completion(serial_obj: Any, *, steps: int) -> str:
    """Require both STEP acceptance and firmware-confirmed pulse completion.

    Retrying a pulse after an acknowledgement loss could double-dose the
    solution.  Therefore every failure after STEP transmission is reported as
    delivery-uncertain and a best-effort immediate stop is sent.
    """

    expected_ack = f"STEP ACCEPTED {steps}"
    try:
        acknowledgement = _serial_response_line(serial_obj)
        if acknowledgement != expected_ack:
            raise RuntimeError(
                f"firmware rejected or mismatched pulse command: {acknowledgement or 'no acknowledgement'}"
            )
        deadline_s = time.monotonic() + steps / ARDUINO_FULL_STEPS_PER_SECOND + 0.50
        while time.monotonic() <= deadline_s:
            line = _serial_response_line(serial_obj)
            if line == "PUMP STOPPED PULSE_COMPLETE":
                return acknowledgement
            if line.startswith("PUMP STOPPED "):
                raise RuntimeError(f"pulse ended for an unexpected reason: {line}")
            if not line:
                time.sleep(0.005)
        raise RuntimeError("firmware pulse-completion acknowledgement timed out")
    except Exception as exc:
        _best_effort_serial_stop(serial_obj)
        raise PulseDeliveryUncertainError(str(exc)) from exc


def _wait_for_legacy_pump_ack(
    serial_obj: Any,
    *,
    command: str,
    expected_run_limit_ms: int | None = None,
) -> str:
    acknowledgement = _serial_response_line(serial_obj)
    if command in {"a", "b"}:
        match = re.fullmatch(r"PUMP RUNNING ([ab]) ([0-9]+)", acknowledgement)
        if match is None or match.group(1) != command:
            raise RuntimeError(
                f"firmware did not confirm pump command {command}: "
                f"{acknowledgement or 'no acknowledgement'}"
            )
        actual_limit_ms = int(match.group(2))
        if expected_run_limit_ms is not None and actual_limit_ms != expected_run_limit_ms:
            raise RuntimeError(
                "firmware started with a different safety deadline: "
                f"requested={expected_run_limit_ms}ms actual={actual_limit_ms}ms"
            )
        return acknowledgement
    elif command == "c":
        expected_prefix = "PUMP STOPPED "
    else:  # pragma: no cover - guarded by callers.
        raise ValueError(f"unsupported legacy pump command: {command}")
    if not acknowledgement.startswith(expected_prefix):
        raise RuntimeError(
            f"firmware did not confirm pump command {command}: "
            f"{acknowledgement or 'no acknowledgement'}"
        )
    return acknowledgement


def start_guarded_continuous_at_rate(
    *,
    command_sender: Callable[[str], Any],
    guard: AbsolutePumpSafetyGuard,
    direction_command: str,
    rate_steps_per_s: int,
    maximum_rate_ml_per_s: float,
    remaining_volume_ml: float,
    absolute_deadline_monotonic_s: float,
    can_restart: Callable[[], bool],
) -> dict[str, Any]:
    """On a stopped pump, configure RATE then rearm G and direction safely."""

    if not can_restart():
        raise RuntimeError("slow-stage restart cancelled before RATE")
    expected_rate_ack = f"RATE ACCEPTED {rate_steps_per_s}"
    rate_ack = command_sender(f"RATE {rate_steps_per_s}\n")
    acknowledgement = (
        str(rate_ack.get("firmware_ack") or "")
        if isinstance(rate_ack, Mapping)
        else str(rate_ack or "")
    )
    if acknowledgement != expected_rate_ack:
        raise RuntimeError("firmware did not acknowledge the exact slow RATE")
    if not can_restart():
        guard.stop("slow_stage_restart_cancelled_after_rate")
        raise RuntimeError("slow-stage restart cancelled after RATE")
    status = guard.start(
        direction_command=direction_command,
        maximum_pump_rate_ml_per_s=maximum_rate_ml_per_s,
        requested_maximum_volume_ml=remaining_volume_ml,
        requested_maximum_run_time_s=ABSOLUTE_PUMP_MAX_RUN_TIME_S,
        can_start_direction=can_restart,
        absolute_deadline_monotonic_s=absolute_deadline_monotonic_s,
    )
    if not status.get("absolute_guard_armed") or not can_restart():
        guard.stop("slow_stage_restart_cancelled")
        raise RuntimeError("slow-stage guarded restart was not confirmed")
    return status


class ArduinoAbcPumpSerialBridge:
    """Lazy serial bridge for a/b/c plus acknowledged firmware guard arming."""

    def __init__(
        self,
        *,
        port: str,
        baud: int = 9600,
        serial_factory: Callable[..., Any] | None = None,
        open_reset_delay_s: float = 2.0,
    ) -> None:
        normalized_port = str(port or "").strip()
        if not normalized_port:
            raise ValueError("pump serial port is required")
        if int(baud) <= 0:
            raise ValueError("pump serial baud must be positive")
        self.port = normalized_port
        self.baud = int(baud)
        self._serial_factory = serial_factory
        self._open_reset_delay_s = max(0.0, float(open_reset_delay_s))
        self._serial_obj = None
        self._lock = threading.Lock()
        self._emergency_write_lock = threading.Lock()
        self._armed_guard_timeout_ms: int | None = None

    def _open_locked(self):  # type: ignore[no-untyped-def]
        if self._serial_obj is not None:
            return self._serial_obj
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on local Windows install.
                raise RuntimeError("pyserial is required for Arduino pump control: python -m pip install pyserial") from exc
            factory = serial.Serial
        self._serial_obj = factory(self.port, self.baud, timeout=0.2, write_timeout=0.5)
        # Uno/Nano-style Arduinos reset when the serial port is opened.  Open
        # once at collector startup and wait here so the first browser "녹화 시작"
        # command is not swallowed by the bootloader reset window.
        if self._open_reset_delay_s > 0:
            time.sleep(self._open_reset_delay_s)
        return self._serial_obj

    def warmup(self) -> None:
        with self._lock:
            self._open_locked()

    def send(self, command: str) -> Any:
        guard_command = command.startswith("G ") and command.endswith("\n")
        step_command = _validated_step_serial_command(command)
        rate_steps = _rate_steps_per_second(command)
        if command not in {"a", "b", "c"} and not guard_command and not step_command and rate_steps is None:
            raise ValueError(
                "pump command must be one of a, b, c, G <milliseconds>\\n, RATE <1..100>\\n, or STEP <steps>\\n"
            )
        with self._lock:
            serial_obj = self._open_locked()
            if guard_command or step_command or rate_steps is not None or command in {"a", "b", "c"}:
                reset_input = getattr(serial_obj, "reset_input_buffer", None)
                if callable(reset_input):
                    reset_input()
            try:
                with self._emergency_write_lock:
                    serial_obj.write(command.encode("ascii"))
                    flush = getattr(serial_obj, "flush", None)
                    if callable(flush):
                        flush()
            except Exception as exc:
                if step_command:
                    _best_effort_serial_stop(serial_obj)
                    raise PulseDeliveryUncertainError(str(exc)) from exc
                raise
            if guard_command or step_command or rate_steps is not None:
                readline = getattr(serial_obj, "readline", None)
                if not callable(readline):
                    raise RuntimeError("pump serial transport cannot read firmware acknowledgement")
                if step_command:
                    steps = int(command[5:-1])
                    return _wait_for_step_completion(serial_obj, steps=steps)
                acknowledgement = _serial_response_line(serial_obj)
                if not acknowledgement:
                    raise RuntimeError("firmware acknowledgement timed out")
                if rate_steps is not None:
                    expected_rate_ack = f"RATE ACCEPTED {rate_steps}"
                    if acknowledgement != expected_rate_ack:
                        _best_effort_serial_stop(serial_obj)
                        raise RuntimeError(
                            "firmware did not acknowledge the exact requested rate: "
                            f"{acknowledgement}"
                        )
                    return acknowledgement
                requested_timeout_ms = int(command[2:-1])
                expected_guard_ack = f"GUARD ARMED {requested_timeout_ms}"
                if acknowledgement != expected_guard_ack:
                    self._armed_guard_timeout_ms = None
                    raise RuntimeError(
                        "firmware did not acknowledge the exact requested guard deadline: "
                        f"{acknowledgement}"
                    )
                self._armed_guard_timeout_ms = requested_timeout_ms
                return acknowledgement
            try:
                acknowledgement = _wait_for_legacy_pump_ack(
                    serial_obj,
                    command=command,
                    expected_run_limit_ms=(
                        self._armed_guard_timeout_ms if command in {"a", "b"} else None
                    ),
                )
            except Exception as exc:
                if command in {"a", "b"}:
                    _best_effort_serial_stop(serial_obj)
                self._armed_guard_timeout_ms = None
                raise
            self._armed_guard_timeout_ms = None
        return {"port": self.port, "baud": self.baud, "firmware_ack": acknowledgement}

    def send_guarded_direction(
        self,
        command: str,
        can_send: Callable[[], bool],
    ) -> dict[str, Any]:
        """Atomically arbitrate a/b against the lock-free emergency c write.

        The generation predicate is evaluated while holding the same byte-write
        lock used by :meth:`emergency_stop`.  Therefore either a/b reaches the
        wire first and c follows it, or cancellation wins and a/b is never
        written.  The lock is released before waiting for the firmware ACK so
        emergency c can still pre-empt a blocked acknowledgement wait.
        """

        if command not in {"a", "b"}:
            raise ValueError("guarded direction command must be a or b")
        if not callable(can_send):
            raise TypeError("can_send must be callable")
        with self._lock:
            serial_obj = self._open_locked()
            if self._armed_guard_timeout_ms is None:
                raise RuntimeError("firmware guard must be armed before a guarded direction")
            armed_guard_timeout_ms = self._armed_guard_timeout_ms
            reset_input = getattr(serial_obj, "reset_input_buffer", None)
            if callable(reset_input):
                reset_input()
            direction_written = False
            try:
                with self._emergency_write_lock:
                    if not can_send():
                        return {
                            "direction_cancelled": True,
                            "direction_written": False,
                        }
                    direction_written_monotonic_s = time.perf_counter()
                    serial_obj.write(command.encode("ascii"))
                    flush = getattr(serial_obj, "flush", None)
                    if callable(flush):
                        flush()
                    direction_written = True
                acknowledgement = _wait_for_legacy_pump_ack(
                    serial_obj,
                    command=command,
                    expected_run_limit_ms=armed_guard_timeout_ms,
                )
            except Exception:
                if direction_written:
                    with self._emergency_write_lock:
                        _best_effort_serial_stop(serial_obj)
                self._armed_guard_timeout_ms = None
                raise
            self._armed_guard_timeout_ms = None
            return {
                "port": self.port,
                "baud": self.baud,
                "firmware_ack": acknowledgement,
                "direction_written": True,
                "direction_written_monotonic_s": direction_written_monotonic_s,
            }

    def emergency_stop(self) -> dict[str, Any]:
        """Preempt a blocking STEP acknowledgement wait with the legacy stop byte."""

        serial_obj = self._serial_obj
        if serial_obj is None:
            return {"sent": False, "status": "not_connected", "error": "pump serial is not open"}
        try:
            with self._emergency_write_lock:
                serial_obj.write(b"c")
                flush = getattr(serial_obj, "flush", None)
                if callable(flush):
                    flush()
        except Exception as exc:  # noqa: BLE001 - caller must see an unconfirmed emergency stop.
            return {"sent": False, "status": "failed", "error": str(exc)}
        self._armed_guard_timeout_ms = None
        return {"sent": True, "status": "sent", "command": "c"}

    def close(self) -> None:
        with self._lock:
            serial_obj = self._serial_obj
            self._serial_obj = None
        close = getattr(serial_obj, "close", None)
        if callable(close):
            close()


def resolve_pump_serial_port(requested: str | None) -> str:
    """Resolve a configured Arduino serial port; empty/off disables pump I/O."""

    value = str(requested or "").strip()
    if value.lower() in {"", "0", "off", "none", "disabled", "disable"}:
        return ""
    if value.lower() != "auto":
        return value
    try:
        from serial.tools import list_ports  # type: ignore[import-not-found]
    except ImportError:
        return ""
    keywords = ("arduino", "ch340", "wch", "cp210", "silicon labs", "ftdi", "usb serial")
    candidates: list[str] = []
    for port in list_ports.comports():
        haystack = " ".join(
            str(part or "")
            for part in (
                getattr(port, "device", ""),
                getattr(port, "description", ""),
                getattr(port, "manufacturer", ""),
                getattr(port, "hwid", ""),
            )
        ).lower()
        if any(keyword in haystack for keyword in keywords):
            candidates.append(str(getattr(port, "device", "")))
    return next((candidate for candidate in candidates if candidate), "")


def _validated_step_serial_command(command: str) -> bool:
    if not command.startswith("STEP ") or not command.endswith("\n"):
        return False
    argument = command[5:-1]
    if not argument.isdigit():
        raise ValueError("STEP command requires a positive integer")
    steps = int(argument)
    if not 0 < steps <= ENDPOINT_PULSE_MAX_STEPS:
        raise ValueError(f"STEP command must be in 1..{ENDPOINT_PULSE_MAX_STEPS}")
    return True


def _rate_steps_per_second(command: str) -> int | None:
    match = re.fullmatch(r"RATE ([0-9]+)\n", str(command or ""))
    if match is None:
        return None
    rate = int(match.group(1))
    if not 1 <= rate <= 100:
        raise ValueError("RATE steps per second must be in 1..100")
    return rate




def _pump_serial_error_likely_busy(error: object) -> bool:
    text = str(error or "").lower()
    busy_tokens = (
        "access is denied",
        "permissionerror",
        "permission denied",
        "device or resource busy",
        "resource busy",
        "busy",
        "already in use",
        "used by another process",
        "액세스가 거부",
        "사용 중",
    )
    return any(token in text for token in busy_tokens)


def _pump_serial_user_message(*, status: str, requested: str, port: str, error: object = "") -> str:
    if status == "waiting_for_port":
        return "아두이노 펌프 대기 중: USB를 연결하면 자동으로 다시 시도합니다."
    if _pump_serial_error_likely_busy(error):
        target = port or requested or "Arduino COM 포트"
        return f"{target} 포트를 열 수 없습니다. Arduino IDE/Serial Monitor가 사용 중이면 닫으면 자동으로 다시 연결됩니다."
    error_text = str(error or "")
    acknowledgement_missing = (
        "no acknowledgement" in error_text.lower()
        or "acknowledgement timed out" in error_text.lower()
    )
    if acknowledgement_missing:
        target = port or requested or "Arduino COM 포트"
        return (
            f"{target}에서 웹 제어용 펌웨어 응답이 없습니다. "
            "auto_titrator/arduino_stepper/arduino_stepper.ino를 Arduino에 업로드하고 "
            "Arduino IDE의 Serial Monitor를 닫은 뒤 USB를 다시 연결하세요. "
            "original_working 스케치는 모터는 움직이지만 웹 확인 응답을 보내지 않습니다."
        )
    if error:
        return f"아두이노 펌프 연결 실패: {error}"
    return "아두이노 펌프 상태 확인 중"


class AutoReconnectArduinoAbcPumpSerialBridge:
    """Auto-retrying bridge for acknowledged and original a/b/c firmware.

    The existing fixed bridge works only if a COM port is present when the
    collector starts.  This bridge keeps the pump path enabled in `auto` mode so
    connecting the Arduino after server startup can recover without restarting
    the dashboard.  ``protocol_mode=auto`` probes ``Q`` once after the Arduino
    reset window.  A current firmware reply enables firmware guard/STEP support;
    no reply selects the original byte-only firmware for manual web control with
    the existing host watchdog as a clearly reported host-only guard.
    """

    def __init__(
        self,
        *,
        requested_port: str = "auto",
        baud: int = 9600,
        serial_factory: Callable[..., Any] | None = None,
        resolver: Callable[[str | None], str] = resolve_pump_serial_port,
        retry_interval_s: float = 2.0,
        open_reset_delay_s: float = 2.0,
        protocol_mode: str = "ack",
        start_background: bool = True,
    ) -> None:
        self.requested_port = str(requested_port or "auto").strip() or "auto"
        self.baud = int(baud)
        if self.baud <= 0:
            raise ValueError("pump serial baud must be positive")
        self._serial_factory = serial_factory
        self._resolver = resolver
        self._retry_interval_s = max(0.2, float(retry_interval_s))
        self._open_reset_delay_s = max(0.0, float(open_reset_delay_s))
        requested_protocol = str(protocol_mode or "auto").strip().lower()
        if requested_protocol not in {"auto", "ack", "legacy"}:
            raise ValueError("pump serial protocol must be auto, ack, or legacy")
        self._requested_protocol = requested_protocol
        self._active_protocol = (
            "ack_v2"
            if requested_protocol == "ack"
            else "legacy_abc"
            if requested_protocol == "legacy"
            else "detecting"
        )
        self._firmware_pulse_direction = ""
        self._supports_variable_rate = False
        self._serial_obj = None
        self._resolved_port = ""
        self._status = "waiting_for_port"
        self._last_error = ""
        self._retry_count = 0
        self._connected_epoch_s: float | None = None
        self._last_attempt_epoch_s: float | None = None
        self._last_command = ""
        self._last_command_epoch_s: float | None = None
        self._lock = threading.Lock()
        self._emergency_write_lock = threading.Lock()
        self._armed_guard_timeout_ms: int | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if start_background:
            self._thread = threading.Thread(target=self._retry_loop, name="pump-serial-auto-reconnect", daemon=True)
            self._thread.start()

    def _factory(self) -> Callable[..., Any]:
        factory = self._serial_factory
        if factory is None:
            try:
                import serial  # type: ignore[import-not-found]
            except ImportError as exc:  # pragma: no cover - depends on local Windows install.
                raise RuntimeError("pyserial is required for Arduino pump control: python -m pip install pyserial") from exc
            factory = serial.Serial
        return factory

    def _close_serial_locked(self) -> None:
        serial_obj = self._serial_obj
        self._serial_obj = None
        self._armed_guard_timeout_ms = None
        if self._requested_protocol == "auto":
            self._active_protocol = "detecting"
            self._firmware_pulse_direction = ""
            self._supports_variable_rate = False
        close = getattr(serial_obj, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass

    def _connect_once_locked(self) -> bool:
        if self._serial_obj is not None:
            return True
        self._retry_count += 1
        self._last_attempt_epoch_s = time.time()
        requested = self.requested_port
        resolved = self._resolver(requested)
        if not resolved:
            self._resolved_port = ""
            self._status = "waiting_for_port"
            self._last_error = ""
            return False
        self._resolved_port = str(resolved)
        try:
            serial_obj = self._factory()(self._resolved_port, self.baud, timeout=0.2, write_timeout=0.5)
            self._serial_obj = serial_obj
            self._status = "connected"
            self._last_error = ""
            self._connected_epoch_s = time.time()
            if self._open_reset_delay_s > 0:
                time.sleep(self._open_reset_delay_s)
            if self._requested_protocol == "auto":
                self._active_protocol = self._detect_protocol_locked(serial_obj)
            return True
        except Exception as exc:  # noqa: BLE001 - surface hardware/port diagnostics to browser.
            self._close_serial_locked()
            self._status = "busy" if _pump_serial_error_likely_busy(exc) else "error"
            self._last_error = str(exc)
            return False

    def _detect_protocol_locked(self, serial_obj: Any) -> str:
        reset_input = getattr(serial_obj, "reset_input_buffer", None)
        if callable(reset_input):
            reset_input()
        # A query can be lost while the board finishes resetting. Retry only Q,
        # never a motion command; unknown firmware still cannot use STEP.
        for _attempt in range(3):
            serial_obj.write(b"Q\n")
            flush = getattr(serial_obj, "flush", None)
            if callable(flush):
                flush()
            for _ in range(3):
                line = _serial_response_line(serial_obj)
                version = re.fullmatch(
                    r"PUMP FW 2 PULSE ([ab]) GUARD 1",
                    str(line or ""),
                )
                if version is not None:
                    self._firmware_pulse_direction = version.group(1)
                    self._supports_variable_rate = self._probe_variable_rate_locked(serial_obj)
                    return "ack_v2"
                if re.fullmatch(r"GUARD (?:IDLE|RUNNING) [0-9]+", str(line or "")):
                    return "ack_v1"
        return "legacy_abc"

    def _probe_variable_rate_locked(self, serial_obj: Any) -> bool:
        """A read-only V query is the capability gate for optional slow dosing."""

        serial_obj.write(b"V\n")
        flush = getattr(serial_obj, "flush", None)
        if callable(flush):
            flush()
        return _serial_response_line(serial_obj) == "PUMP SPEED 1"

    def _send_legacy_locked(self, serial_obj: Any, command: str) -> dict[str, Any]:
        guard_command = command.startswith("G ") and command.endswith("\n")
        step_command = _validated_step_serial_command(command)
        if step_command:
            raise RuntimeError(
                "legacy a/b/c firmware does not support STEP pulses; "
                "upload auto_titrator/arduino_stepper/arduino_stepper.ino"
            )
        if guard_command:
            requested_timeout_ms = int(command[2:-1])
            self._armed_guard_timeout_ms = requested_timeout_ms
            return {
                "guard_armed": True,
                "guard_timeout_ms": requested_timeout_ms,
                "guard_scope": "host_only",
                "firmware_ack": "",
            }
        if command not in {"a", "b", "c"}:
            raise ValueError("legacy pump command must be a, b, or c")
        with self._emergency_write_lock:
            self._last_command = command
            self._last_command_epoch_s = time.time()
            serial_obj.write(command.encode("ascii"))
            flush = getattr(serial_obj, "flush", None)
            if callable(flush):
                flush()
        if command == "c":
            self._armed_guard_timeout_ms = None
            return {
                "port": self._resolved_port,
                "baud": self.baud,
                "auto_retry": True,
                "pump_serial_status": "connected_legacy",
                "firmware_protocol": "legacy_abc",
                "firmware_ack": "",
                "acknowledged": False,
                "stop_sent": True,
            }
        timeout_ms = self._armed_guard_timeout_ms or int(ABSOLUTE_PUMP_MAX_RUN_TIME_S * 1000)
        return {
            "port": self._resolved_port,
            "baud": self.baud,
            "auto_retry": True,
            "pump_serial_status": "connected_legacy",
            "firmware_protocol": "legacy_abc",
            "acknowledged": False,
            "pump_running": True,
            "pump_direction": command,
            "guard_timeout_ms": timeout_ms,
            "guard_scope": "host_only",
        }

    def _retry_loop(self) -> None:
        while not self._stop_event.wait(self._retry_interval_s):
            with self._lock:
                if self._serial_obj is None:
                    self._connect_once_locked()

    def warmup(self) -> None:
        with self._lock:
            self._connect_once_locked()

    def send(self, command: str) -> Any:
        guard_command = command.startswith("G ") and command.endswith("\n")
        step_command = _validated_step_serial_command(command)
        rate_steps = _rate_steps_per_second(command)
        if command not in {"a", "b", "c"} and not guard_command and not step_command and rate_steps is None:
            raise ValueError(
                "pump command must be one of a, b, c, G <milliseconds>\\n, RATE <1..100>\\n, or STEP <steps>\\n"
            )
        if rate_steps is not None and not self._supports_variable_rate:
            raise RuntimeError("connected firmware does not advertise RATE support via V query")
        last_exc: Exception | None = None
        for _attempt in range(2):
            step_delivery_attempted = False
            run_start_delivery_attempted = False
            with self._lock:
                if self._serial_obj is None:
                    self._connect_once_locked()
                serial_obj = self._serial_obj
                if serial_obj is None:
                    status = self.status_locked()
                    raise RuntimeError(status["message"])
                try:
                    if self._active_protocol == "legacy_abc":
                        result = self._send_legacy_locked(serial_obj, command)
                        self._status = "connected"
                        self._last_error = ""
                        return result
                    if guard_command or step_command or rate_steps is not None or command in {"a", "b", "c"}:
                        reset_input = getattr(serial_obj, "reset_input_buffer", None)
                        if callable(reset_input):
                            reset_input()
                    step_delivery_attempted = bool(step_command)
                    run_start_delivery_attempted = command in {"a", "b"}
                    with self._emergency_write_lock:
                        self._last_command = command
                        self._last_command_epoch_s = time.time()
                        serial_obj.write(command.encode("ascii"))
                        flush = getattr(serial_obj, "flush", None)
                        if callable(flush):
                            flush()
                    if guard_command or step_command or rate_steps is not None:
                        readline = getattr(serial_obj, "readline", None)
                        if not callable(readline):
                            raise RuntimeError(
                                "pump serial transport cannot read firmware acknowledgement"
                            )
                        if step_command:
                            steps = int(command[5:-1])
                            acknowledgement = _wait_for_step_completion(serial_obj, steps=steps)
                            self._status = "connected"
                            self._last_error = ""
                            return acknowledgement
                        if rate_steps is not None:
                            acknowledgement = _serial_response_line(serial_obj)
                            expected_rate_ack = f"RATE ACCEPTED {rate_steps}"
                            if acknowledgement != expected_rate_ack:
                                _best_effort_serial_stop(serial_obj)
                                raise RuntimeError(
                                    "firmware did not acknowledge the exact requested rate: "
                                    f"{acknowledgement or 'no acknowledgement'}"
                                )
                            self._status = "connected"
                            self._last_error = ""
                            return acknowledgement
                        acknowledgement = _serial_response_line(serial_obj)
                        if not acknowledgement:
                            raise RuntimeError("firmware acknowledgement timed out")
                        requested_timeout_ms = int(command[2:-1])
                        expected_guard_ack = f"GUARD ARMED {requested_timeout_ms}"
                        if acknowledgement != expected_guard_ack:
                            self._armed_guard_timeout_ms = None
                            raise RuntimeError(
                                "firmware did not acknowledge the exact requested guard deadline: "
                                f"{acknowledgement}"
                            )
                        self._armed_guard_timeout_ms = requested_timeout_ms
                        self._status = "connected"
                        self._last_error = ""
                        return acknowledgement
                    acknowledgement = _wait_for_legacy_pump_ack(
                        serial_obj,
                        command=command,
                        expected_run_limit_ms=(
                            self._armed_guard_timeout_ms if command in {"a", "b"} else None
                        ),
                    )
                    self._armed_guard_timeout_ms = None
                    self._status = "connected"
                    self._last_error = ""
                    return {
                        "port": self._resolved_port,
                        "baud": self.baud,
                        "auto_retry": True,
                        "pump_serial_status": self._status,
                        "firmware_ack": acknowledgement,
                    }
                except Exception as exc:  # noqa: BLE001 - retry once after dropping stale port handle.
                    last_exc = exc
                    self._status = "busy" if _pump_serial_error_likely_busy(exc) else "error"
                    self._last_error = str(exc)
                    if (step_delivery_attempted or run_start_delivery_attempted) and not isinstance(
                        exc, PulseDeliveryUncertainError
                    ):
                        _best_effort_serial_stop(serial_obj)
                    self._close_serial_locked()
                    # Never replay a STEP after bytes may have reached the
                    # firmware: an acknowledgement loss must not double-dose.
                    if step_delivery_attempted or run_start_delivery_attempted or rate_steps is not None:
                        break
        raise RuntimeError(
            _pump_serial_user_message(
                status=self._status,
                requested=self.requested_port,
                port=self._resolved_port,
                error=last_exc or self._last_error,
            )
        )

    def send_guarded_direction(
        self,
        command: str,
        can_send: Callable[[], bool],
    ) -> dict[str, Any]:
        """Send one non-replayable guarded a/b command with emergency arbitration."""

        if command not in {"a", "b"}:
            raise ValueError("guarded direction command must be a or b")
        if not callable(can_send):
            raise TypeError("can_send must be callable")
        direction_written = False
        with self._lock:
            if self._serial_obj is None:
                self._connect_once_locked()
            serial_obj = self._serial_obj
            if serial_obj is None:
                raise RuntimeError(self.status_locked()["message"])
            if self._armed_guard_timeout_ms is None:
                raise RuntimeError("firmware guard must be armed before a guarded direction")
            armed_guard_timeout_ms = self._armed_guard_timeout_ms
            if self._active_protocol == "legacy_abc":
                with self._emergency_write_lock:
                    if not can_send():
                        return {
                            "direction_cancelled": True,
                            "direction_written": False,
                        }
                    direction_written_monotonic_s = time.perf_counter()
                    self._last_command = command
                    self._last_command_epoch_s = time.time()
                    serial_obj.write(command.encode("ascii"))
                    flush = getattr(serial_obj, "flush", None)
                    if callable(flush):
                        flush()
                self._armed_guard_timeout_ms = None
                self._status = "connected"
                self._last_error = ""
                return {
                    "port": self._resolved_port,
                    "baud": self.baud,
                    "auto_retry": True,
                    "pump_serial_status": "connected_legacy",
                    "firmware_protocol": "legacy_abc",
                    "acknowledged": False,
                    "pump_running": True,
                    "pump_direction": command,
                    "guard_timeout_ms": armed_guard_timeout_ms,
                    "guard_scope": "host_only",
                    "direction_written": True,
                    "direction_written_monotonic_s": direction_written_monotonic_s,
                }
            try:
                reset_input = getattr(serial_obj, "reset_input_buffer", None)
                if callable(reset_input):
                    reset_input()
                with self._emergency_write_lock:
                    if not can_send():
                        return {
                            "direction_cancelled": True,
                            "direction_written": False,
                        }
                    direction_written_monotonic_s = time.perf_counter()
                    self._last_command = command
                    self._last_command_epoch_s = time.time()
                    serial_obj.write(command.encode("ascii"))
                    flush = getattr(serial_obj, "flush", None)
                    if callable(flush):
                        flush()
                    direction_written = True
                acknowledgement = _wait_for_legacy_pump_ack(
                    serial_obj,
                    command=command,
                    expected_run_limit_ms=armed_guard_timeout_ms,
                )
                self._armed_guard_timeout_ms = None
                self._status = "connected"
                self._last_error = ""
                return {
                    "port": self._resolved_port,
                    "baud": self.baud,
                    "auto_retry": True,
                    "pump_serial_status": self._status,
                    "firmware_ack": acknowledgement,
                    "direction_written": True,
                    "direction_written_monotonic_s": direction_written_monotonic_s,
                }
            except Exception as exc:
                self._status = "busy" if _pump_serial_error_likely_busy(exc) else "error"
                self._last_error = str(exc)
                if direction_written:
                    with self._emergency_write_lock:
                        _best_effort_serial_stop(serial_obj)
                self._close_serial_locked()
                raise RuntimeError(
                    _pump_serial_user_message(
                        status=self._status,
                        requested=self.requested_port,
                        port=self._resolved_port,
                        error=exc,
                    )
                ) from exc

    def emergency_stop(self) -> dict[str, Any]:
        """Write ``c`` without waiting for the reconnect/ACK lock."""

        serial_obj = self._serial_obj
        if serial_obj is None:
            return {"sent": False, "status": "not_connected", "error": "pump serial is not open"}
        try:
            with self._emergency_write_lock:
                self._last_command = "c"
                self._last_command_epoch_s = time.time()
                serial_obj.write(b"c")
                flush = getattr(serial_obj, "flush", None)
                if callable(flush):
                    flush()
        except Exception as exc:  # noqa: BLE001 - expose failure to the stop caller.
            return {"sent": False, "status": "failed", "error": str(exc)}
        self._armed_guard_timeout_ms = None
        return {"sent": True, "status": "sent", "command": "c"}

    def status_locked(self) -> dict[str, Any]:
        connected = self._serial_obj is not None and self._status == "connected"
        message = _pump_serial_user_message(
            status=self._status,
            requested=self.requested_port,
            port=self._resolved_port,
            error=self._last_error,
        )
        if connected and self._active_protocol == "legacy_abc":
            message = (
                "기존 a/b/c 펌웨어로 연결됨: 웹 수동 밀기·되감기·정지는 사용 가능하며 "
                "STEP 자동정지는 웹 제어용 펌웨어 업로드 후 사용할 수 있습니다."
            )
        elif connected and self._active_protocol == "ack_v2":
            message = "웹 제어용 Arduino 펌웨어가 확인되었습니다."
        elif connected and self._active_protocol == "ack_v1":
            message = "이전 ACK 펌웨어로 연결됨: 수동 제어만 사용하고 최신 펌웨어를 업로드하세요."
        return {
            "enabled": True,
            "auto_retry": True,
            "connected": connected,
            "status": self._status,
            "requested_port": self.requested_port,
            "port": self._resolved_port,
            "baud": self.baud,
            "retry_count": self._retry_count,
            "last_error": self._last_error,
            "likely_busy": _pump_serial_error_likely_busy(self._last_error),
            "message": message,
            "last_attempt_epoch_s": self._last_attempt_epoch_s,
            "connected_epoch_s": self._connected_epoch_s,
            "firmware_protocol": self._active_protocol,
            "supports_firmware_guard": self._active_protocol in {"ack_v1", "ack_v2"},
            "supports_step_pulse": self._active_protocol == "ack_v2",
            "supports_variable_rate": self._active_protocol == "ack_v2" and self._supports_variable_rate,
            "manual_host_guard_only": self._active_protocol == "legacy_abc",
            "firmware_pulse_direction": self._firmware_pulse_direction,
            "last_command": self._last_command,
            "last_command_epoch_s": self._last_command_epoch_s,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self.status_locked()

    def close(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        with self._lock:
            self._close_serial_locked()

def build_pump_serial_bridge_from_args(args: argparse.Namespace) -> ArduinoAbcPumpSerialBridge | AutoReconnectArduinoAbcPumpSerialBridge | None:
    requested = str(getattr(args, "pump_serial_port", "") or "").strip()
    if requested.lower() in {"", "0", "off", "none", "disabled", "disable"}:
        return None
    baud = int(getattr(args, "pump_serial_baud", 9600) or 9600)
    retry_interval_s = float(getattr(args, "pump_serial_retry_interval_s", 2.0) or 2.0)
    protocol_mode = str(getattr(args, "pump_serial_protocol", "auto") or "auto").strip().lower()
    if protocol_mode not in {"auto", "ack", "legacy"}:
        raise ValueError("pump serial protocol must be auto, ack, or legacy")
    if requested.lower() == "auto" or protocol_mode in {"auto", "legacy"}:
        print(
            f"Pump serial: reconnect enabled @ {baud} baud, protocol={protocol_mode} "
            f"b=start c=stop a=retract, retry={retry_interval_s:g}s",
            flush=True,
        )
        bridge = AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port=requested,
            baud=baud,
            retry_interval_s=retry_interval_s,
            protocol_mode=protocol_mode,
        )
        bridge.warmup()
        status = bridge.status()
        if status.get("connected"):
            print(f"Pump serial: connected {status.get('port')} @ {baud} baud", flush=True)
        else:
            print(f"Pump serial: {status.get('message')}", flush=True)
        return bridge
    resolved = resolve_pump_serial_port(requested)
    if not resolved:
        return None
    print(f"Pump serial: {resolved} @ {baud} baud, protocol b=start c=stop a=retract", flush=True)
    bridge = ArduinoAbcPumpSerialBridge(port=resolved, baud=baud)
    try:
        bridge.warmup()
    except Exception as exc:  # noqa: BLE001 - keep collector visible; recording start will report retry failure.
        print(f"Warning: pump serial warmup failed; start command will retry and block recording if still failing. Reason: {exc}", flush=True)
    return bridge


class LiveStreamPublisher:
    """Latest-only async JPEG encoder feeding the MJPEG/SSE stream state."""

    def __init__(self, state: LiveStreamState, *, jpeg_quality: int = 75, encoder: Any | None = None) -> None:
        self.state = state
        self.jpeg_quality = int(jpeg_quality)
        self.encoder = jpeg_bytes if encoder is None else encoder
        self._condition = threading.Condition()
        self._latest: tuple[np.ndarray | None, np.ndarray | None, dict[str, Any]] | None = None
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="live-stream-publisher", daemon=True)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._thread.start()
            self._started = True

    def submit(
        self,
        *,
        visible_frame: np.ndarray | None,
        thermal_frame: np.ndarray | None,
        metadata: dict[str, Any],
    ) -> None:
        with self._condition:
            visible_copy = None if visible_frame is None else np.asarray(visible_frame).copy()
            thermal_copy = None if thermal_frame is None else np.asarray(thermal_frame).copy()
            self._latest = (visible_copy, thermal_copy, dict(metadata))
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._started:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while True:
            with self._condition:
                while self._latest is None and not self._stop:
                    self._condition.wait()
                if self._latest is None and self._stop:
                    return
                visible_frame, thermal_frame, metadata = self._latest
                self._latest = None
            visible_jpeg = None if visible_frame is None else self.encoder(visible_frame, quality=self.jpeg_quality)
            thermal_jpeg = None if thermal_frame is None else self.encoder(thermal_frame, quality=self.jpeg_quality)
            self.state.publish(visible_jpeg=visible_jpeg, thermal_jpeg=thermal_jpeg, metadata=metadata)


class LiveJpegStreamPublisher:
    """Latest-only JPEG publisher for one stream kind.

    This is used to keep visible/thermal preview video independent from the
    slower analysis/SSE metadata loop.
    """

    def __init__(
        self,
        state: LiveStreamState,
        *,
        kind: str,
        jpeg_quality: int = 75,
        encoder: Any | None = None,
        transform: Callable[[np.ndarray], np.ndarray] | None = None,
        copy_frame: bool = True,
    ) -> None:
        if kind not in {"visible", "thermal"}:
            raise ValueError("kind must be visible or thermal")
        self.state = state
        self.kind = kind
        self.jpeg_quality = int(jpeg_quality)
        self.encoder = jpeg_bytes if encoder is None else encoder
        self.transform = transform
        self.copy_frame = bool(copy_frame)
        self._condition = threading.Condition()
        self._latest: np.ndarray | None = None
        self._stop = False
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._loop, name=f"{kind}-jpeg-publisher", daemon=True)
        self._started = False

    def start(self) -> None:
        if not self._started:
            self._thread.start()
            self._started = True

    def submit(self, frame: np.ndarray | None) -> None:
        if frame is None:
            return
        with self._condition:
            arr = np.asarray(frame)
            self._latest = arr.copy() if self.copy_frame else arr
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        if self._started:
            self._thread.join(timeout=2.0)

    @property
    def error(self) -> BaseException | None:
        return self._error

    def _loop(self) -> None:
        while True:
            with self._condition:
                while self._latest is None and not self._stop:
                    self._condition.wait()
                if self._latest is None and self._stop:
                    return
                frame = self._latest
                self._latest = None
            try:
                out_frame = self.transform(frame) if self.transform is not None else frame
                jpeg = self.encoder(out_frame, quality=self.jpeg_quality)
            except BaseException as exc:  # noqa: BLE001 - keep streaming thread alive after one bad overlay.
                self._error = exc
                continue
            if self.kind == "visible":
                self.state.publish_visible(jpeg)
            else:
                self.state.publish_thermal(jpeg)


class StopIntentCoordinator:
    """Keep motion blocked until every overlapping stop path has finished.

    A plain ``threading.Event`` has no ownership.  If manual and automatic
    stops overlap, either path can clear it while the other is still between
    the physical stop and the CSV transition lock.  Tokens prevent that early
    clear, while the latch keeps motion blocked until deferred CSV finalization
    has actually completed.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._next_token = 0
        self._active: dict[int, str] = {}
        self._latched_session_id: int | None = None

    def begin(self, reason: str) -> int:
        with self._lock:
            self._next_token += 1
            token = self._next_token
            self._active[token] = str(reason or "stop")
            self._event.set()
            return token

    def finish(self, token: int) -> None:
        with self._lock:
            self._active.pop(int(token), None)
            self._refresh_event_locked()

    def latch_session(self, session_id: int) -> None:
        """Keep motion blocked while one specific CSV session finalizes."""

        parsed_session_id = int(session_id)
        if parsed_session_id <= 0:
            raise ValueError("session_id must be positive")
        with self._lock:
            if (
                self._latched_session_id is not None
                and self._latched_session_id != parsed_session_id
            ):
                raise RuntimeError(
                    "cannot replace an active stop latch for another CSV session"
                )
            self._latched_session_id = parsed_session_id
            self._event.set()

    def clear_latch(self, session_id: int) -> bool:
        """Release only the matching session latch after finalization ends."""

        parsed_session_id = int(session_id)
        with self._lock:
            if self._latched_session_id != parsed_session_id:
                return False
            self._latched_session_id = None
            self._refresh_event_locked()
            return True

    def is_set(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._event.wait(timeout)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "stop_intent_active": self._event.is_set(),
                "stop_intent_latched": self._latched_session_id is not None,
                "stop_intent_latch_session_id": self._latched_session_id,
                "stop_intent_owner_count": len(self._active),
                "stop_intent_reasons": tuple(self._active.values()),
            }

    def _refresh_event_locked(self) -> None:
        if self._latched_session_id is not None or self._active:
            self._event.set()
        else:
            self._event.clear()


class LiveStreamHandler(BaseHTTPRequestHandler):
    server_version = "AutoTitrationLiveStream/1.0"

    @property
    def state(self) -> LiveStreamState:
        return self.server.live_state  # type: ignore[attr-defined]

    @property
    def roi_state(self) -> RoiSelectionState:
        return self.server.roi_state  # type: ignore[attr-defined]

    @property
    def controls(self) -> LiveControlState:
        return self.server.live_controls  # type: ignore[attr-defined]

    @property
    def csv_buffer(self) -> LiveCsvBuffer | None:
        return getattr(self.server, "csv_buffer", None)  # type: ignore[attr-defined]

    @property
    def capture_controller(self) -> "Mini2CaptureThread | None":
        controller = getattr(self.server, "capture_controller", None)  # type: ignore[attr-defined]
        return controller if isinstance(controller, Mini2CaptureThread) else None

    @property
    def csv_control_lock(self) -> Any:
        return self.server.csv_control_lock  # type: ignore[attr-defined]

    @property
    def csv_stop_intent(self) -> StopIntentCoordinator:
        return self.server.csv_stop_intent  # type: ignore[attr-defined]

    @property
    def mobile_bridge(self) -> MobileBridge | None:
        return getattr(self.server, "mobile_bridge", None)  # type: ignore[attr-defined]

    @property
    def pump_command_sender(self) -> Callable[[str], Any] | None:
        sender = getattr(self.server, "pump_command_sender", None)  # type: ignore[attr-defined]
        return sender if callable(sender) else None

    @property
    def pump_status_provider(self) -> Callable[[], dict[str, Any]] | None:
        provider = getattr(self.server, "pump_status_provider", None)  # type: ignore[attr-defined]
        return provider if callable(provider) else None

    @property
    def pump_emergency_stop_sender(self) -> Callable[[], dict[str, Any]] | None:
        sender = getattr(self.server, "pump_emergency_stop_sender", None)  # type: ignore[attr-defined]
        return sender if callable(sender) else None

    def _preemptive_pump_stop(self) -> dict[str, Any] | None:
        sender = self.pump_emergency_stop_sender
        if sender is None:
            return None
        try:
            return sender()
        except Exception as exc:  # noqa: BLE001 - continue to the acknowledged guard stop path.
            return {"sent": False, "status": "failed", "error": str(exc)}

    @property
    def auto_stop_controller(self) -> ColorChangeAutoStopController | None:
        controller = getattr(self.server, "auto_stop_controller", None)  # type: ignore[attr-defined]
        return controller if isinstance(controller, ColorChangeAutoStopController) else None

    @property
    def endpoint_pulse_runtime(self) -> EndpointPulseRuntime | None:
        runtime = getattr(self.server, "endpoint_pulse_runtime", None)  # type: ignore[attr-defined]
        return runtime if isinstance(runtime, EndpointPulseRuntime) else None

    @property
    def absolute_pump_safety_guard(self) -> AbsolutePumpSafetyGuard | None:
        guard = getattr(self.server, "absolute_pump_safety_guard", None)  # type: ignore[attr-defined]
        return guard if isinstance(guard, AbsolutePumpSafetyGuard) else None

    @property
    def roi_click_enabled(self) -> bool:
        return bool(getattr(self.server, "roi_click_enabled", True))

    def handle_one_request(self) -> None:  # noqa: D401 - stdlib API shape.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            # Browser MJPEG/EventSource clients routinely reset sockets during
            # refresh/reconnect.  This is not a collector failure.
            return

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D401 - keep stdlib API shape.
        if self.path != "/api/live":
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib API.
        if not self._origin_allowed():
            self.send_response(HTTPStatus.FORBIDDEN.value)
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802 - stdlib API.
        path = urlparse(self.path).path
        if path == "/api/live":
            self._send_json(self.state.snapshot_metadata())
        elif path in {"/api/health", "/api/collector-health"}:
            self._send_json(self._collector_health())
        elif path == "/api/remote/config":
            config = getattr(self.server, "remote_recording_config", None)
            self._send_json(
                {
                    "ok": True,
                    "config": config,
                    "defaults_allowed": bool(
                        getattr(self.server, "remote_config_defaults_allowed", True)
                    ),
                }
            )
        elif path == "/api/settings":
            self._send_json({"ok": True, "settings": self.controls.snapshot()})
        elif path == "/api/csv/status":
            self._send_csv_status()
        elif path == "/api/csv":
            self._send_csv_download()
        elif path == "/api/mobile/status":
            self._send_mobile_status()
        elif path == "/stream/visible.mjpg":
            self._send_mjpeg("visible")
        elif path == "/stream/thermal.mjpg":
            self._send_mjpeg("thermal")
        elif path == "/stream/events":
            self._send_events()
        else:
            self.send_error(HTTPStatus.NOT_FOUND.value)

    def _collector_health(self) -> dict[str, Any]:
        payload = self.state.snapshot_health()
        latest = payload.get("latest") if isinstance(payload.get("latest"), dict) else {}
        thermal_mode = str(latest.get("thermal_mode") or latest.get("thermal_source") or "")
        warnings = str(latest.get("warnings") or latest.get("sync_warning") or "")
        mini2_unavailable = thermal_mode == "mini2_unavailable" or str(latest.get("source_quality", "")) == "mini2_unavailable"
        hints: list[str] = []
        if not payload["visible_stream_ready"]:
            hints.append("일반 카메라 스트림 대기: 카메라 권한/인덱스/다른 앱 점유를 확인하세요.")
        if mini2_unavailable or not payload["thermal_stream_ready"]:
            hints.append("Mini2 대기: USB 연결, HIKMICRO/카메라 앱 종료, Collector 재연결 로그를 확인하세요.")
        if payload["metadata_age_ms"] is not None and float(payload["metadata_age_ms"]) > 2500:
            hints.append("메타데이터가 멈췄습니다: Collector 창 오류와 포트 8766 사용 여부를 확인하세요.")
        if not hints:
            hints.append("수집기, 스트림, 메타데이터가 동작 중입니다.")
        mobile_status = None if self.mobile_bridge is None else self.mobile_bridge.status().get("mobile")
        pump_status_provider = self.pump_status_provider
        pump_status = None if pump_status_provider is None else pump_status_provider()
        absolute_guard_status = (
            None
            if self.absolute_pump_safety_guard is None
            else self.absolute_pump_safety_guard.status()
        )
        if isinstance(pump_status, dict) and pump_status.get("enabled") and not pump_status.get("connected"):
            pump_message = str(pump_status.get("message") or "")
            if pump_message:
                hints.insert(0, pump_message)
        if (
            isinstance(absolute_guard_status, dict)
            and absolute_guard_status.get("absolute_guard_state") == "error"
        ):
            guard_error = str(absolute_guard_status.get("absolute_guard_error") or "")
            hints.insert(0, f"펌프 절대 안전 가드 오류: {guard_error}")
        payload.update(
            {
                "settings": self.controls.snapshot(),
                "csv": None if self.csv_buffer is None else self.csv_buffer.status(),
                "mobile": mobile_status,
                "pump": pump_status,
                "absolute_pump_guard": absolute_guard_status,
                "mini2_unavailable": mini2_unavailable,
                "action_hints": hints,
                "warning": warnings,
            }
        )
        return payload

    def do_POST(self) -> None:  # noqa: N802 - stdlib API.
        if not self._origin_allowed():
            self._send_json(
                {"ok": False, "error": "cross-origin POSTs are restricted to localhost dashboard origins"},
                status=HTTPStatus.FORBIDDEN,
            )
            return
        path = urlparse(self.path).path
        if path == "/api/remote/config":
            self._handle_remote_config_post()
            return
        if path == "/api/settings":
            self._handle_settings_post()
            return
        if path == "/api/roi-rect":
            self._handle_roi_rect_post()
            return
        if path == "/api/roi-lock":
            self._handle_roi_lock_post()
            return
        if path == "/api/roi-unlock":
            self._handle_roi_unlock_post()
            return
        if path == "/api/roi-polygon":
            self._handle_roi_polygon_post()
            return
        if path == "/api/roi-auto-candidate":
            self._handle_roi_auto_candidate_post()
            return
        if path == "/api/chemistry/constants/lookup":
            self._handle_chemistry_constants_lookup_post()
            return
        if path == "/api/csv/start":
            self._handle_csv_start_post()
            return
        if path == "/api/csv/stop":
            self._handle_csv_stop_post()
            return
        if path == "/api/pump/dispense":
            self._handle_pump_command_post("start")
            return
        if path == "/api/pump/retract":
            self._handle_pump_command_post("retract")
            return
        if path == "/api/pump/stop":
            self._handle_pump_command_post("stop")
            return
        if path == "/api/pump/reset":
            self._handle_pump_command_post("reset")
            return
        if path == "/api/mobile/pair":
            self._handle_mobile_pair_post()
            return
        if path == "/api/mobile/ingest":
            self._handle_mobile_ingest_post()
            return
        if path != "/api/roi-click":
            self.send_error(HTTPStatus.NOT_FOUND.value)
            return
        if not self.roi_click_enabled:
            self._send_json({"ok": False, "error": "ROI click selection is disabled"}, status=HTTPStatus.FORBIDDEN)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                raise ValueError("invalid ROI click payload length")
            target, x, y = parse_roi_click_payload(self.rfile.read(length))
            self.roi_state.push_click(target, x, y)
        except Exception as exc:  # noqa: BLE001 - return compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "target": target, "x": x, "y": y})

    def _read_json_object(self, *, max_bytes: int = 4096) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > max_bytes:
            raise ValueError("invalid JSON payload length")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON payload must be an object")
        return payload

    def _handle_remote_config_post(self) -> None:
        """Stage explicit notebook settings without issuing any pump commands."""
        try:
            payload = self._read_json_object()
            clear = payload == {"clear": True}
            if clear:
                config = None
            else:
                config = _validate_remote_recording_config(payload)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        with self.csv_control_lock:
            if self.csv_buffer is not None and self.csv_buffer.status().get("state") in {"recording", "finalizing"}:
                self._send_json({"ok": False, "error": "녹화 종료 후 원격 설정을 저장하세요"}, status=HTTPStatus.CONFLICT)
                return
            try:
                _persist_remote_recording_config(
                    getattr(self.server, "remote_config_path", None),
                    config,
                )
            except OSError as exc:
                self._send_json(
                    {"ok": False, "error": f"원격 설정을 저장하지 못했습니다: {exc}"},
                    status=HTTPStatus.INTERNAL_SERVER_ERROR,
                )
                return
            self.server.remote_recording_config = config
            self.server.remote_config_defaults_allowed = False
        self._send_json({"ok": True})

    def _handle_settings_post(self) -> None:
        try:
            settings = self.controls.update_from_payload(self._read_json_object())
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "settings": settings})

    def _handle_roi_rect_post(self) -> None:
        try:
            target, roi = parse_roi_rect_payload(self._read_json_object())
            applied = self.roi_state.update_rect(target, roi)
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc), "roi": self.roi_state.status()}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "target": target, "roi_rect": roi_to_string(applied), "roi": self.roi_state.status()})

    def _handle_roi_lock_post(self) -> None:
        try:
            status = self.roi_state.lock()
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc), "roi": self.roi_state.status()}, status=HTTPStatus.CONFLICT)
            return
        self._send_json({"ok": True, "roi": status})

    def _handle_roi_unlock_post(self) -> None:
        try:
            payload = self._read_json_object()
        except Exception:
            payload = {}
        try:
            status = self.roi_state.unlock(reset=bool(payload.get("reset", False)))
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc), "roi": self.roi_state.status()}, status=HTTPStatus.CONFLICT)
            return
        self._send_json({"ok": True, "roi": status})

    def _handle_roi_polygon_post(self) -> None:
        try:
            payload = self._read_json_object(max_bytes=262144)
            target, points, frame_shape = parse_roi_polygon_payload(payload)
            mask = polygon_mask_from_points(points, frame_shape)
            source = "manual_lasso"
            if bool(payload.get("boundary_refine", True)):
                visible_provider = getattr(self.server, "visible_frame_provider", None)  # type: ignore[attr-defined]
                thermal_provider = getattr(self.server, "thermal_matrix_provider", None)  # type: ignore[attr-defined]
                visible_frame = visible_provider() if target == "visible" and callable(visible_provider) else None
                thermal_matrix = thermal_provider() if target == "thermal" and callable(thermal_provider) else None
                mask, source = refine_lasso_mask_to_local_boundary(
                    mask,
                    visible_frame=visible_frame,
                    thermal_matrix=thermal_matrix,
                )
            applied = self.roi_state.update_polygon_mask(target, mask, source=source)
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc), "roi": self.roi_state.status()}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(
            {
                "ok": True,
                "target": target,
                "roi_polygon": applied.bbox_string,
                "mask_area_px": applied.area_px,
                "roi": self.roi_state.status(),
            }
        )

    def _handle_roi_auto_candidate_post(self) -> None:
        try:
            try:
                payload = self._read_json_object()
            except Exception:
                payload = {}
            target = RoiSelectionState._normalize_auto_candidate_target(str(payload.get("target", "both")))
            target_visible = target in {"visible", "both"}
            target_thermal = target in {"thermal", "both"}
            visible_provider = getattr(self.server, "visible_frame_provider", None)  # type: ignore[attr-defined]
            thermal_provider = getattr(self.server, "thermal_matrix_provider", None)  # type: ignore[attr-defined]
            visible_frame = visible_provider() if target_visible and callable(visible_provider) else None
            thermal_matrix = thermal_provider() if target_thermal and callable(thermal_provider) else None
            visible_missing = target_visible and visible_frame is None
            thermal_missing = target_thermal and thermal_matrix is None
            visible_available = target_visible and not visible_missing
            thermal_available = target_thermal and not thermal_missing
            if visible_available or thermal_available:
                settings = self.controls.snapshot()
                min_confidence = float(getattr(self.server, "roi_candidate_min_confidence", 0.5))  # type: ignore[attr-defined]
                visible_result = None
                thermal_result = None
                if visible_available:
                    detector = getattr(self.server, "visible_candidate_detector", None)  # type: ignore[attr-defined]
                    if callable(detector):
                        visible_result = detector(visible_frame)
                    else:
                        visible_result = auto_detect_visible_roi_setup_candidate(
                            visible_frame,
                            visible_detector=str(settings.get("visible_roi_detector", "yolo")),
                            min_confidence=min_confidence,
                        )
                if thermal_available:
                    thermal_result = auto_detect_thermal_roi(thermal_matrix)
                applied = apply_auto_roi_detection_results(
                    self.roi_state,
                    visible_result=visible_result,
                    thermal_result=thermal_result,
                    visible_frame=visible_frame,
                    thermal_matrix=thermal_matrix,
                    min_confidence=min_confidence,
                    allow_manual_lasso_overwrite=True,
                )
                status = self.roi_state.status()
                results = [result for result in (visible_result, thermal_result) if result is not None]
                confidences = [float(result.confidence) for result in results]
                reason_parts = [result.reason for result in results]
                missing_targets = []
                if visible_missing:
                    missing_targets.append("visible")
                if thermal_missing:
                    missing_targets.append("thermal")
                if missing_targets:
                    queued_target = missing_targets[0] if len(missing_targets) == 1 else "both"
                    status = self.roi_state.request_auto_candidate(queued_target)
                    reason_parts.append(f"queued_waiting_for_{'_and_'.join(missing_targets)}_frame")
                self._send_json(
                    {
                        "ok": True,
                        "target": target,
                        "applied_now": applied,
                        "reason": ",".join(reason_parts) or status.get("roi_source", ""),
                        "confidence": min(confidences) if confidences else None,
                        "roi": status,
                    }
                )
                return
            status = self.roi_state.request_auto_candidate(target)
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc), "roi": self.roi_state.status()}, status=HTTPStatus.CONFLICT)
            return
        missing_parts = []
        if target in {"visible", "both"} and visible_missing:
            missing_parts.append("visible")
        if target in {"thermal", "both"} and thermal_missing:
            missing_parts.append("thermal")
        if not missing_parts:
            missing_parts.append(target)
        reason = f"queued_waiting_for_{'_and_'.join(missing_parts)}_frame"
        self._send_json({"ok": True, "target": target, "applied_now": False, "reason": reason, "roi": status})

    def _handle_chemistry_constants_lookup_post(self) -> None:
        try:
            payload = self._read_json_object(max_bytes=2048)
            response_payload = build_constants_lookup_payload(payload.get("query", ""), limit=payload.get("limit", 8))
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(response_payload)

    def _pump_command_for_action(self, action: str, *, direction_mode: str = "normal") -> str:
        command_map = getattr(self.server, "pump_command_map", {})  # type: ignore[attr-defined]
        if isinstance(command_map, dict) and action in command_map:
            command = str(command_map[action])
        else:
            command = {"start": "b", "retract": "a", "stop": "c", "reset": "r"}[action]
        normalized_mode = str(direction_mode or "normal").strip().lower()
        if normalized_mode not in {"normal", "reversed"}:
            raise ValueError("pump_direction_mode must be normal or reversed")
        if normalized_mode == "reversed" and action in {"start", "retract"}:
            command = "a" if command == "b" else "b"
        if command not in {"a", "b", "c", "r"}:
            raise ValueError(f"invalid pump command for {action}: {command}")
        return command

    def _dispatch_pump_command(
        self,
        action: str,
        *,
        safety_limits: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        limits = safety_limits or {}
        direction_mode = str(limits.get("pump_direction_mode") or "normal")
        command = self._pump_command_for_action(action, direction_mode=direction_mode)
        sender = self.pump_command_sender
        base = {
            "enabled": sender is not None,
            "sent": False,
            "action": action,
            "command": command,
            "protocol": "arduino_abc_serial",
        }
        if sender is None:
            return {**base, "status": "disabled", "message": "PUMP_SERIAL_PORT 미설정"}
        if action in {"start", "retract"} and bool(limits.get("manual_unbounded")):
            try:
                result = sender(command)
            except Exception as exc:  # noqa: BLE001 - pump failure must be browser-readable.
                provider = self.pump_status_provider
                diagnostic = None if provider is None else provider()
                return {**base, "status": "error", "error": str(exc), "diagnostic": diagnostic}
            extra = result if isinstance(result, dict) else {}
            return {
                **base,
                **extra,
                "enabled": True,
                "sent": True,
                "status": "sent",
                "manual_unbounded": True,
            }
        guard = self.absolute_pump_safety_guard
        if guard is None:
            return {
                **base,
                "status": "error",
                "error": "absolute pump safety guard is unavailable; pump command rejected",
            }
        if action in {"start", "retract"}:
            current_csv = None
            if self.csv_buffer is not None:
                current_csv = self.csv_buffer.status()
                if current_csv.get("finalizing") or current_csv.get("state") == "finalizing":
                    return {
                        **base,
                        "status": "error",
                        "error": (
                            "CSV finalization is in progress; pump start/retract is rejected "
                            "until the session is fully closed"
                        ),
                    }
            rate = _finite_float_or_none(limits.get("maximum_pump_rate_ml_per_s"))
            if rate is None or rate <= 0:
                return {
                    **base,
                    "status": "error",
                    "error": (
                        "maximum_pump_rate_ml_per_s (mL/s) is required to arm "
                        "the absolute volume guard"
                    ),
                    "absolute_guard": guard.status(),
                }
            existing_guard = guard.status()
            if existing_guard.get("absolute_guard_state") in {
                "arming",
                "armed_running",
                "stopping",
                "stop_unconfirmed",
            } or existing_guard.get("absolute_guard_armed"):
                return {
                    **base,
                    "status": "error",
                    "error": "pump is already active; stop it explicitly before another start",
                    "absolute_guard": existing_guard,
                }
            requested_volume = limits.get(
                "absolute_maximum_volume_ml",
                ABSOLUTE_PUMP_MAX_VOLUME_ML,
            )
            requested_volume_value = _finite_float_or_none(requested_volume)
            session_used_volume = 0.0
            if current_csv is not None:
                if current_csv.get("recording"):
                    session_used_volume = (
                        _finite_float_or_none(current_csv.get("injected_volume_ml")) or 0.0
                    )
                    if requested_volume_value is not None:
                        requested_volume = requested_volume_value - session_used_volume
                        if requested_volume <= 0:
                            return {
                                **base,
                                "status": "error",
                                "error": "recording-session pump volume budget is exhausted",
                                "session_used_volume_ml": round(session_used_volume, 6),
                                "session_maximum_volume_ml": round(requested_volume_value, 6),
                                "absolute_guard": existing_guard,
                            }
            try:
                guard_status = guard.start(
                    direction_command=command,
                    maximum_pump_rate_ml_per_s=rate,
                    requested_maximum_volume_ml=requested_volume,
                    requested_maximum_run_time_s=limits.get(
                        "absolute_maximum_run_time_s",
                        ABSOLUTE_PUMP_MAX_RUN_TIME_S,
                    ),
                    absolute_deadline_monotonic_s=_finite_float_or_none(
                        limits.get("_absolute_session_deadline_monotonic_s")
                    ),
                )
            except (TypeError, ValueError, RuntimeError) as exc:
                return {
                    **base,
                    "status": "error",
                    "error": str(exc),
                    "absolute_guard": guard.status(),
                }
            if not guard_status.get("absolute_guard_armed"):
                return {
                    **base,
                    "status": "error",
                    "error": guard_status.get("absolute_guard_error")
                    or "firmware guard could not be armed",
                    "absolute_guard": guard_status,
                }
            return {
                **base,
                "enabled": True,
                "sent": True,
                "status": "sent",
                "session_used_volume_ml": round(session_used_volume, 6),
                "session_remaining_volume_ml": round(
                    float(guard_status.get("absolute_guard_effective_maximum_volume_ml") or 0.0),
                    6,
                ),
                "absolute_guard": guard_status,
            }
        if action == "stop":
            preemptive = None

            def emergency_stop() -> None:
                nonlocal preemptive
                preemptive = self._preemptive_pump_stop()

            guard_status = guard.stop(
                "manual_pump_stop",
                emergency_stop=emergency_stop,
            )
            sent = guard_status.get("absolute_guard_stop_status") == "sent"
            return {
                **base,
                "enabled": True,
                "sent": sent,
                "status": "sent" if sent else "error",
                "error": "" if sent else guard_status.get("absolute_guard_error", ""),
                "preemptive_stop": preemptive,
                "absolute_guard": guard_status,
            }
        if action == "reset":
            try:
                result = sender(command)
            except Exception as exc:  # noqa: BLE001 - pump failure must be browser-readable.
                provider = self.pump_status_provider
                diagnostic = None if provider is None else provider()
                return {**base, "status": "error", "error": str(exc), "diagnostic": diagnostic}
            extra = result if isinstance(result, dict) else {}
            return {**base, **extra, "enabled": True, "sent": True, "status": "sent"}
        try:
            result = sender(command)
        except Exception as exc:  # noqa: BLE001 - pump failure must be browser-readable.
            provider = self.pump_status_provider
            diagnostic = None if provider is None else provider()
            return {**base, "status": "error", "error": str(exc), "diagnostic": diagnostic}
        extra = result if isinstance(result, dict) else {}
        return {**base, **extra, "enabled": True, "sent": True, "status": "sent"}

    def _handle_pump_command_post(self, action: str) -> None:
        # Start/retract must never queue behind a CSV start/stop transition.
        # In particular, CSV stop drains the capture FIFO before it exposes
        # finalizing/stopped state. Rejecting a concurrent motion request here
        # prevents it from starting immediately after that drain completes.
        payload: dict[str, Any] = {}
        if action in {"start", "retract"}:
            try:
                payload = self._read_json_object()
            except Exception as exc:
                self._send_json(
                    {"ok": False, "error": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        if action == "retract":
            # Match the automatic callback's callback-gate -> CSV-lock order.
            # Waiting for controller callbacks while holding csv_control_lock
            # would deadlock against an on_trigger callback finishing a stop.
            if self.auto_stop_controller is not None:
                self.auto_stop_controller.disarm("manual_pump_retract")
            if self.endpoint_pulse_runtime is not None:
                self.endpoint_pulse_runtime.disarm("manual_pump_retract")
        if action in {"start", "retract"}:
            acquired = self.csv_control_lock.acquire(blocking=False)
            if not acquired:
                self._send_json(
                    {
                        "ok": False,
                        "pump": {
                            "action": action,
                            "status": "error",
                            "error": (
                                "CSV start/stop transition is in progress; "
                                "pump start/retract is rejected"
                            ),
                        },
                    },
                    status=HTTPStatus.CONFLICT,
                )
                return
            try:
                if self.csv_stop_intent.is_set():
                    self._send_json(
                        {
                            "ok": False,
                            "pump": {
                                "action": action,
                                "status": "error",
                                "error": (
                                    "CSV stop/finalization intent is active; "
                                    "pump start/retract is rejected"
                                ),
                            },
                        },
                        status=HTTPStatus.CONFLICT,
                    )
                    return
                self._handle_pump_command_post_unlocked(action, payload=payload)
            finally:
                self.csv_control_lock.release()
            return
        self._handle_pump_command_post_unlocked(action, payload=payload)

    def _handle_pump_command_post_unlocked(
        self,
        action: str,
        *,
        payload: dict[str, Any],
    ) -> None:
        try:
            pump_status = self._dispatch_pump_command(action, safety_limits=payload)
            if self.csv_buffer is not None and self.csv_buffer.status().get("recording"):
                if action == "start" and pump_status.get("sent"):
                    direction_written_s = _finite_float_or_none(
                        (pump_status.get("absolute_guard") or {}).get(
                            "direction_written_monotonic_s"
                        )
                    )
                    try:
                        self.csv_buffer.resume_commanded_pump_timeline(
                            now_monotonic_s=direction_written_s
                        )
                    except RuntimeError:
                        self.csv_buffer.begin_commanded_pump_timeline(
                            now_monotonic_s=direction_written_s, running=True
                        )
                elif action in {"stop", "retract"}:
                    self.csv_buffer.pause_commanded_pump_timeline(state=action)
            if action == "stop" and self.auto_stop_controller is not None:
                self.auto_stop_controller.disarm(f"manual_pump_{action}")
            if action == "stop" and self.endpoint_pulse_runtime is not None:
                self.endpoint_pulse_runtime.disarm(f"manual_pump_{action}")
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": pump_status.get("status") != "error", "pump": pump_status})

    def _handle_csv_start_post(self) -> None:
        with self.csv_control_lock:
            self._handle_csv_start_post_locked()

    def _handle_csv_start_post_locked(self) -> None:
        if self.csv_buffer is None:
            self._send_json(
                {"ok": False, "error": "CSV buffer is not enabled", "csv": None},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        if self.csv_stop_intent.is_set():
            self._send_json(
                {
                    "ok": False,
                    "error": "CSV stop/finalization intent is active",
                    "csv": self.csv_buffer.status(),
                },
                status=HTTPStatus.CONFLICT,
            )
            return
        try:
            payload = self._read_json_object()
            auto_stop_requested = _strict_optional_bool(
                payload, "auto_stop_enabled", default=False
            )
            pulse_requested = _strict_optional_bool(
                payload, "auto_stop_pulse_enabled", default=auto_stop_requested
            )
            slow_stage_requested = _strict_optional_bool(
                payload, "auto_stop_slow_stage_enabled", default=False
            )
            pulse_steps = _strict_optional_int(
                payload, "auto_stop_pulse_steps", default=ENDPOINT_PULSE_DEFAULT_STEPS,
                minimum=1, maximum=ENDPOINT_PULSE_MAX_STEPS,
            )
            slow_rate_steps = _strict_optional_int(
                payload, "auto_stop_slow_rate_steps_per_s", default=25,
                minimum=1, maximum=100,
            )
            slow_onset_score = _strict_optional_number(
                payload, "auto_stop_slow_onset_score", default=0.10
            )
            slow_onset_duration_s = _strict_optional_number(
                payload, "auto_stop_slow_onset_duration_s", default=0.50
            )
            pulse_approach_score = _strict_optional_number(
                payload, "auto_stop_pulse_approach_score",
                default=ENDPOINT_PULSE_DEFAULT_APPROACH_SCORE,
            )
            pulse_settle_time_s = _strict_optional_number(
                payload, "auto_stop_pulse_settle_time_s",
                default=ENDPOINT_PULSE_DEFAULT_SETTLE_S,
            )
            absolute_run_time_s = _strict_optional_number(
                payload, "absolute_maximum_run_time_s",
                default=ABSOLUTE_PUMP_MAX_RUN_TIME_S,
            )
            if not 0 < pulse_approach_score < 1:
                raise ValueError("auto_stop_pulse_approach_score must be in 0..1 exclusive")
            if pulse_settle_time_s < 0 or slow_onset_duration_s < 0:
                raise ValueError("staged dosing durations must be non-negative")
            if absolute_run_time_s <= 0:
                raise ValueError("absolute_maximum_run_time_s must be positive")
            if slow_stage_requested and not 0 <= slow_onset_score < pulse_approach_score:
                raise ValueError(
                    "auto_stop_slow_onset_score must be lower than auto_stop_pulse_approach_score"
                )
        except Exception as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        csv_started_here = False
        roi_started_here = False
        capture_started_here = False
        pump_started_here = False
        csv_status: dict[str, Any] = {}
        roi_status: dict[str, Any] = {}
        capture_status: dict[str, Any] | None = None
        pump_status: dict[str, Any] = {}
        auto_stop_status: dict[str, Any] | None = None
        recording_origin_monotonic_s = time.monotonic()
        recording_origin_perf_s = time.perf_counter()
        absolute_session_deadline_s = recording_origin_monotonic_s + min(
            absolute_run_time_s, ABSOLUTE_PUMP_MAX_RUN_TIME_S
        )
        payload = {
            **payload,
            "_absolute_session_deadline_monotonic_s": absolute_session_deadline_s,
        }

        def rollback_started_session(reason: str) -> None:
            if self.endpoint_pulse_runtime is not None:
                self.endpoint_pulse_runtime.disarm(reason)
            if self.auto_stop_controller is not None:
                self.auto_stop_controller.disarm(reason)
            guard = self.absolute_pump_safety_guard
            if pump_started_here and guard is not None:
                guard.stop(reason)
            if csv_started_here:
                try:
                    self.csv_buffer.pause_commanded_pump_timeline(state="stopped")
                except RuntimeError:
                    pass
            if capture_started_here and self.capture_controller is not None:
                try:
                    drained = self.capture_controller.end_recording(
                        int(csv_status.get("session_id") or 0)
                    )
                    if csv_started_here:
                        self.csv_buffer.request_stop()
                        if bool(drained.get("drained")):
                            self.csv_buffer.complete_stop()
                except Exception:
                    if csv_started_here:
                        self.csv_buffer.stop_recording()
            elif csv_started_here and self.csv_buffer.status().get("state") in {
                "recording",
                "finalizing",
            }:
                self.csv_buffer.stop_recording()
            if roi_started_here and self.roi_state.status().get("roi_recording"):
                self.roi_state.stop_recording()

        try:
            current_csv = self.csv_buffer.status()
            if current_csv.get("state") in {"recording", "finalizing"}:
                raise RuntimeError(f"CSV session is already {current_csv['state']}")

            maximum_flow_rate = _finite_float_or_none(
                payload.get("maximum_pump_rate_ml_per_s")
            )
            nominal_flow_rate = _finite_float_or_none(payload.get("pump_rate_ml_per_s"))
            absolute_maximum_volume = _finite_float_or_none(
                payload.get("absolute_maximum_volume_ml")
            )
            pulse_ml_per_step_upper_bound = _finite_float_or_none(
                payload.get("pulse_ml_per_step_upper_bound")
            )
            pulse_nominal_ml_per_step = _finite_float_or_none(
                payload.get("pulse_nominal_ml_per_step")
            )
            if auto_stop_requested:
                if self.pump_command_sender is None:
                    raise RuntimeError("automatic stop requires a connected Arduino pump")
                provider = self.pump_status_provider
                pump_diagnostic = None if provider is None else provider()
                if (
                    isinstance(pump_diagnostic, Mapping)
                    and pump_diagnostic.get("supports_step_pulse") is False
                ):
                    raise RuntimeError(
                        "automatic STEP stop requires the acknowledged web-control firmware; "
                        "legacy a/b/c firmware remains available for manual pump buttons only"
                    )
                if slow_stage_requested and (
                    not isinstance(pump_diagnostic, Mapping)
                    or pump_diagnostic.get("supports_variable_rate") is not True
                ):
                    raise RuntimeError(
                        "optional slow stage is unsupported by the connected firmware; "
                        "the V query must return exactly PUMP SPEED 1 before any pump movement"
                    )
                if self.auto_stop_controller is None or self.endpoint_pulse_runtime is None:
                    raise RuntimeError("automatic stop controller is unavailable")
                if maximum_flow_rate is None or maximum_flow_rate <= 0:
                    raise ValueError(
                        "maximum_pump_rate_ml_per_s is required for automatic pumping"
                    )
                if nominal_flow_rate is not None and maximum_flow_rate < nominal_flow_rate:
                    raise ValueError(
                        "maximum_pump_rate_ml_per_s must be at least pump_rate_ml_per_s"
                    )
                if absolute_maximum_volume is None or absolute_maximum_volume <= 0:
                    raise ValueError(
                        "absolute_maximum_volume_ml is required for automatic pumping"
                    )
                if pulse_requested and (
                    pulse_ml_per_step_upper_bound is None
                    or pulse_ml_per_step_upper_bound <= 0
                ):
                    raise ValueError(
                        "pulse_ml_per_step_upper_bound is required for pulse dosing"
                    )
                configured_pulse_direction = str(
                    getattr(self.server, "pump_pulse_direction", "b")
                )
                detected_pulse_direction = (
                    str(pump_diagnostic.get("firmware_pulse_direction") or "")
                    if isinstance(pump_diagnostic, Mapping)
                    else ""
                )
                if (
                    pulse_requested
                    and detected_pulse_direction
                    and detected_pulse_direction != configured_pulse_direction
                ):
                    raise ValueError(
                        "connected firmware STEP direction does not match the configured "
                        f"direction: firmware={detected_pulse_direction} "
                        f"configured={configured_pulse_direction}"
                    )
                if pulse_requested and self._pump_command_for_action(
                    "start",
                    direction_mode=str(payload.get("pump_direction_mode") or "normal"),
                ) != configured_pulse_direction:
                    raise ValueError(
                        "automatic pulse dosing direction does not match the configured "
                        f"firmware STEP direction {configured_pulse_direction}"
                    )

            roi_status = self.roi_state.start_recording()
            roi_started_here = True
            csv_status = self.csv_buffer.start_recording(
                roi_session_id=roi_status["roi_session_id"],
                pump_rate_ml_per_s=payload.get("pump_rate_ml_per_s"),
                theoretical_equivalence_volume_ml=payload.get(
                    "theoretical_equivalence_volume_ml"
                ),
                equivalence_window_ml=payload.get("equivalence_window_ml", 0.05),
                experiment_metadata=start_payload_experiment_metadata(payload),
                event_note=payload.get("event_note"),
                started_monotonic_s=recording_origin_perf_s,
                capture_session_required=self.capture_controller is not None,
            )
            csv_started_here = True
            # Baseline frames are recorded while the motor is physically
            # stopped, so the first second contributes exactly 0 mL.
            self.csv_buffer.begin_commanded_pump_timeline(running=False)
            if self.capture_controller is not None:
                capture_status = self.capture_controller.begin_recording(
                    int(csv_status["session_id"])
                )
                capture_started_here = True

            confirmation_delay_s = _finite_float_or_none(
                payload.get("auto_stop_confirmation_delay_s")
            )
            requested_auto_maximum = _finite_float_or_none(
                payload.get("auto_stop_maximum_volume_ml")
            )
            if requested_auto_maximum is None:
                requested_auto_maximum = absolute_maximum_volume
            maximum_volume_ml = (
                AUTO_STOP_MAX_VOLUME_ML
                if requested_auto_maximum is None
                else min(requested_auto_maximum, ABSOLUTE_PUMP_MAX_VOLUME_ML)
            )

            if self.auto_stop_controller is not None:
                auto_stop_status = self.auto_stop_controller.arm(
                    session_id=int(csv_status["session_id"]),
                    requested=auto_stop_requested,
                    recording_started=True,
                    titration_type=str(payload.get("titration_type") or ""),
                    confirmation_delay_s=AUTO_STOP_CONFIRMATION_SECONDS
                    if confirmation_delay_s is None
                    else confirmation_delay_s,
                    maximum_volume_ml=maximum_volume_ml,
                )

            if auto_stop_requested:
                deadline = time.monotonic() + AUTO_STOP_BASELINE_START_TIMEOUT_S
                while time.monotonic() < deadline:
                    auto_stop_status = self.auto_stop_controller.status()
                    state = str(auto_stop_status.get("auto_stop_state") or "")
                    if bool(auto_stop_status.get("auto_stop_baseline_ready")):
                        if state in {"armed", "armed_confirming"}:
                            break
                        if state in {"armed_safety_only", "error", "unavailable"}:
                            raise RuntimeError(
                                "automatic stop baseline/model validation failed: "
                                f"{auto_stop_status.get('auto_stop_reason') or state}"
                            )
                    elif state in {"error", "unavailable"}:
                        raise RuntimeError(
                            "automatic stop calibration failed: "
                            f"{auto_stop_status.get('auto_stop_reason') or state}"
                        )
                    time.sleep(0.02)
                else:
                    raise RuntimeError(
                        "automatic stop baseline timed out before the pump was started"
                    )

            pump_status = self._dispatch_pump_command("start", safety_limits=payload)
            pump_started_here = bool(pump_status.get("sent"))
            if pump_started_here:
                self.csv_buffer.resume_commanded_pump_timeline(
                    now_monotonic_s=_finite_float_or_none(
                        (pump_status.get("absolute_guard") or {}).get(
                            "direction_written_monotonic_s"
                        )
                    )
                )
            elif auto_stop_requested:
                raise RuntimeError(
                    str(
                        pump_status.get("error")
                        or pump_status.get("message")
                        or "pump command failed"
                    )
                )

            if self.endpoint_pulse_runtime is not None:
                pulse_status = self.endpoint_pulse_runtime.arm(
                    session_id=int(csv_status["session_id"]),
                    requested=auto_stop_requested and pulse_requested,
                    pump_started=pump_started_here,
                    pump_rate_ml_per_s=nominal_flow_rate,
                    maximum_pump_rate_ml_per_s=maximum_flow_rate,
                    pulse_ml_per_step_upper_bound=pulse_ml_per_step_upper_bound,
                    maximum_volume_ml=maximum_volume_ml,
                    pulse_nominal_ml_per_step=pulse_nominal_ml_per_step,
                    dispense_direction=self._pump_command_for_action(
                        "start",
                        direction_mode=str(payload.get("pump_direction_mode") or "normal"),
                    ),
                    approach_score=pulse_approach_score,
                    pulse_steps=pulse_steps,
                    settle_time_s=pulse_settle_time_s,
                    slow_stage_enabled=slow_stage_requested,
                    slow_onset_score=slow_onset_score,
                    slow_onset_duration_s=slow_onset_duration_s,
                    slow_rate_steps_per_s=slow_rate_steps,
                    absolute_maximum_run_time_s=_finite_float_or_none(
                        payload.get("absolute_maximum_run_time_s")
                    )
                    or ABSOLUTE_PUMP_MAX_RUN_TIME_S,
                    absolute_deadline_monotonic_s=absolute_session_deadline_s,
                )
                if auto_stop_requested and pulse_requested and str(
                    pulse_status.get("auto_stop_pulse_state") or ""
                ) == "unavailable":
                    raise RuntimeError(
                        "pulse dosing could not be armed: "
                        f"{pulse_status.get('auto_stop_pulse_reason') or 'invalid settings'}"
                    )

            csv_status = self.csv_buffer.status()
        except Exception as exc:  # noqa: BLE001 - compact browser-readable error.
            rollback_started_session("recording_start_failed")
            self._send_json(
                {
                    "ok": False,
                    "error": str(exc),
                    "csv": self.csv_buffer.status(),
                    "roi": self.roi_state.status(),
                    "pump": pump_status or None,
                    "auto_stop": auto_stop_status,
                },
                status=HTTPStatus.CONFLICT,
            )
            return

        if pump_status.get("enabled") and not pump_started_here:
            pump_status["recording_continues_without_pump"] = True
            pump_status["message"] = (
                pump_status.get("error")
                or pump_status.get("message")
                or "pump command failed"
            )
            self._send_json(
                {
                    "ok": True,
                    "warning": "pump command failed; CSV recording continues",
                    "csv": csv_status,
                    "roi": roi_status,
                    "pump": pump_status,
                    "capture": capture_status,
                    "auto_stop": auto_stop_status,
                }
            )
            return
        self._send_json(
            {
                "ok": True,
                "csv": csv_status,
                "roi": roi_status,
                "pump": pump_status,
                "capture": capture_status,
                "auto_stop": auto_stop_status,
            }
        )

    def _handle_csv_stop_post(self) -> None:
        if self.csv_buffer is None:
            self._send_json(
                {"ok": False, "error": "CSV buffer is not enabled", "csv": None},
                status=HTTPStatus.NOT_FOUND,
            )
            return
        # Publish stop intent before any serial or CSV-lock operation. Motion
        # requests observe this latch after acquiring the transition lock, so
        # none can enter the pre-lock stop gap.
        stop_token = self.csv_stop_intent.begin("manual_recording_stop")
        stop_session_id = 0
        try:
            current_before_stop = self.csv_buffer.status()
            if current_before_stop.get("state") in {"recording", "finalizing"}:
                stop_session_id = int(
                    current_before_stop.get("session_id") or 0
                )
                if stop_session_id > 0:
                    self.csv_stop_intent.latch_session(stop_session_id)
            # Cancel an in-flight pump start before waiting for the CSV
            # transition lock. AbsolutePumpSafetyGuard.stop() increments its
            # generation before waiting on the serial command lock, so a start
            # that has only armed G cannot continue into a direction command.
            # The emergency sender also puts c on the wire immediately if
            # motion was already attempted.
            pump_status = self._dispatch_pump_command("stop")
            auto_stop_status = None
            if self.auto_stop_controller is not None:
                auto_stop_status = self.auto_stop_controller.disarm(
                    "manual_recording_stop"
                )
            if self.endpoint_pulse_runtime is not None:
                self.endpoint_pulse_runtime.disarm("manual_recording_stop")
            with self.csv_control_lock:
                self._handle_csv_stop_post_locked(
                    pump_status=pump_status,
                    auto_stop_status=auto_stop_status,
                    stop_session_id=stop_session_id,
                )
        finally:
            self.csv_stop_intent.finish(stop_token)

    def _handle_csv_stop_post_locked(
        self,
        *,
        pump_status: dict[str, Any],
        auto_stop_status: dict[str, Any] | None,
        stop_session_id: int,
    ) -> None:
        assert self.csv_buffer is not None
        self.csv_buffer.pause_commanded_pump_timeline(state="stopped")
        current_status = self.csv_buffer.status()
        capture_status = None
        if self.capture_controller is None:
            csv_status = self.csv_buffer.stop_recording()
        else:
            capture_status = self.capture_controller.end_recording(int(current_status.get("session_id") or 0))
            csv_status = self.csv_buffer.request_stop()
            if bool(capture_status.get("drained")):
                csv_status = self.csv_buffer.complete_stop()
        if not csv_status.get("recording") and not csv_status.get("finalizing"):
            self.csv_stop_intent.clear_latch(stop_session_id)
        roi_status = self.roi_state.stop_recording()
        self._send_json({"ok": True, "csv": csv_status, "roi": roi_status, "pump": pump_status, "capture": capture_status, "auto_stop": auto_stop_status})

    def _send_mobile_status(self) -> None:
        if self.mobile_bridge is None:
            self._send_json({"ok": False, "error": "mobile bridge is not enabled", "mobile": {"enabled": False}}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(self.mobile_bridge.status())

    def _handle_mobile_pair_post(self) -> None:
        if self.mobile_bridge is None:
            self._send_json({"ok": False, "error": "mobile bridge is not enabled", "mobile": {"enabled": False}}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json({"ok": True, "mobile": self.mobile_bridge.create_pairing()})

    def _handle_mobile_ingest_post(self) -> None:
        if self.mobile_bridge is None:
            self._send_json({"ok": False, "error": "mobile bridge is not enabled", "mobile": {"enabled": False}}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json_object(max_bytes=262144)
            token = str(payload.get("token") or "")
            frame = payload.get("frame") if "frame" in payload else payload
            result = self.mobile_bridge.ingest(frame, token=token, server_received_epoch_s=time.time())
        except MobileBridgeError as exc:
            self._send_json({"ok": False, "error": str(exc), "mobile": self.mobile_bridge.status()["mobile"]}, status=HTTPStatus.FORBIDDEN)
            return
        except (MobileProtocolError, Exception) as exc:  # noqa: BLE001 - compact browser/mobile error.
            self._send_json({"ok": False, "error": str(exc), "mobile": self.mobile_bridge.status()["mobile"]}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin and self._origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        elif not origin:
            self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _origin_allowed(self, origin: str | None = None) -> bool:
        origin = self.headers.get("Origin") if origin is None else origin
        if not origin:
            return True
        try:
            parsed = urlparse(origin)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status.value)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_csv_status(self) -> None:
        if self.csv_buffer is None:
            self._send_json({"ok": False, "error": "CSV buffer is not enabled", "csv": None}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(
            {
                "ok": True,
                "csv": self.csv_buffer.status(),
                "absolute_pump_guard": None
                if self.absolute_pump_safety_guard is None
                else self.absolute_pump_safety_guard.status(),
            }
        )

    def _send_csv_download(self) -> None:
        if self.csv_buffer is None:
            self._send_json({"ok": False, "error": "CSV buffer is not enabled"}, status=HTTPStatus.NOT_FOUND)
            return
        with self.csv_control_lock:
            status = self.csv_buffer.status()
            if status.get("finalizing") or status.get("state") == "finalizing":
                self._send_json(
                    {"ok": False, "error": "CSV is finalizing preserved 25 fps frames", "csv": status},
                    status=HTTPStatus.CONFLICT,
                )
                return
            body = self.csv_buffer.to_csv_bytes()
            filename = self.csv_buffer.download_filename()
        self.send_response(HTTPStatus.OK.value)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_mjpeg(self, kind: str) -> None:
        boundary = "autotitrationframe"
        self.send_response(HTTPStatus.OK.value)
        self._send_cors_headers()
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={boundary}")
        self.send_header("Cache-Control", "no-store, no-cache, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        last_sequence = 0
        try:
            while True:
                item = self.state.wait_jpeg(kind, last_sequence=last_sequence, timeout_s=15.0)
                if item is None:
                    continue
                last_sequence, jpeg = item
                self.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpeg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return

    def _send_events(self) -> None:
        self.send_response(HTTPStatus.OK.value)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, max-age=0")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_sequence = 0
        try:
            while True:
                item = self.state.wait_metadata(last_sequence=last_sequence, timeout_s=15.0)
                if item is None:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                last_sequence, payload = item
                body = json.dumps(payload, ensure_ascii=False)
                self.wfile.write(f"event: live\ndata: {body}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            return


def start_live_stream_server(
    host: str,
    port: int,
    state: LiveStreamState,
    *,
    roi_state: RoiSelectionState | None = None,
    roi_click_enabled: bool = True,
    controls: LiveControlState | None = None,
    csv_buffer: LiveCsvBuffer | None = None,
    enable_mobile_bridge: bool = True,
    pump_command_sender: Callable[[str], Any] | None = None,
    pump_guarded_direction_sender: Callable[
        [str, Callable[[], bool]], Any
    ] | None = None,
    pump_emergency_stop_sender: Callable[[], dict[str, Any]] | None = None,
    pump_command_map: dict[str, str] | None = None,
    pump_pulse_direction: str = "b",
    pump_status_provider: Callable[[], dict[str, Any]] | None = None,
    auto_stop_controller: ColorChangeAutoStopController | None = None,
    endpoint_pulse_runtime: EndpointPulseRuntime | None = None,
    absolute_pump_safety_guard: AbsolutePumpSafetyGuard | None = None,
    remote_config_path: str | Path | None = None,
) -> LiveStreamServerHandle:
    server = ThreadingHTTPServer((host, port), LiveStreamHandler)
    server.live_state = state  # type: ignore[attr-defined]
    server.roi_state = roi_state if roi_state is not None else RoiSelectionState()  # type: ignore[attr-defined]
    server.roi_click_enabled = bool(roi_click_enabled)  # type: ignore[attr-defined]
    server.live_controls = controls if controls is not None else LiveControlState()  # type: ignore[attr-defined]
    server.csv_buffer = csv_buffer  # type: ignore[attr-defined]
    server.csv_control_lock = threading.RLock()  # type: ignore[attr-defined]
    server.csv_stop_intent = StopIntentCoordinator()  # type: ignore[attr-defined]
    server.remote_config_path = (  # type: ignore[attr-defined]
        None if remote_config_path is None else Path(remote_config_path)
    )
    (
        server.remote_recording_config,  # type: ignore[attr-defined]
        server.remote_config_defaults_allowed,  # type: ignore[attr-defined]
    ) = _load_remote_recording_config(server.remote_config_path)  # type: ignore[attr-defined]
    server.mobile_bridge = MobileBridge(csv_buffer=csv_buffer) if enable_mobile_bridge and csv_buffer is not None else None  # type: ignore[attr-defined]
    server.pump_command_sender = pump_command_sender  # type: ignore[attr-defined]
    server.pump_emergency_stop_sender = pump_emergency_stop_sender  # type: ignore[attr-defined]
    server.pump_status_provider = pump_status_provider  # type: ignore[attr-defined]
    server.auto_stop_controller = auto_stop_controller  # type: ignore[attr-defined]
    server.endpoint_pulse_runtime = endpoint_pulse_runtime  # type: ignore[attr-defined]
    server.absolute_pump_safety_guard = (  # type: ignore[attr-defined]
        absolute_pump_safety_guard
        if absolute_pump_safety_guard is not None
        else (
            AbsolutePumpSafetyGuard(
                pump_command_sender,
                direction_sender=pump_guarded_direction_sender,
            )
            if pump_command_sender is not None
            else None
        )
    )
    server.pump_command_map = pump_command_map or {"start": "b", "retract": "a", "stop": "c", "reset": "r"}  # type: ignore[attr-defined]
    normalized_pulse_direction = str(pump_pulse_direction or "b").strip().lower()
    if normalized_pulse_direction not in {"a", "b"}:
        raise ValueError("pump_pulse_direction must be a or b")
    server.pump_pulse_direction = normalized_pulse_direction  # type: ignore[attr-defined]
    server.capture_controller = None  # type: ignore[attr-defined]
    server.visible_frame_provider = None  # type: ignore[attr-defined]
    server.thermal_matrix_provider = None  # type: ignore[attr-defined]
    server.visible_candidate_detector = None  # type: ignore[attr-defined]
    server.roi_candidate_min_confidence = 0.5  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="live-stream-http", daemon=True)
    thread.start()
    actual_host, actual_port = server.server_address[:2]
    print(f"Live MJPEG/SSE stream: http://{actual_host}:{actual_port}/stream/visible.mjpg", flush=True)
    return LiveStreamServerHandle(server=server, thread=thread)


class VisibleFrameBuffer:
    def __init__(self, *, maxlen: int = 128) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._frames: deque[TimestampedVisibleFrame] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, frame: TimestampedVisibleFrame) -> None:
        with self._lock:
            self._frames.append(frame)

    def latest(self) -> TimestampedVisibleFrame | None:
        with self._lock:
            if not self._frames:
                return None
            return self._frames[-1]

    def first_after(self, frame_id: int) -> TimestampedVisibleFrame | None:
        with self._lock:
            for frame in self._frames:
                if frame.frame_id > int(frame_id):
                    return frame
            return None

    def nearest(self, timestamp_s: float, *, max_age_s: float | None = None) -> TimestampedVisibleFrame | None:
        with self._lock:
            if not self._frames:
                return None
            nearest = min(self._frames, key=lambda frame: abs(frame.timestamp_s - timestamp_s))
            if max_age_s is not None and abs(nearest.timestamp_s - timestamp_s) > max(0.0, float(max_age_s)):
                return None
            return nearest


class Mini2CaptureThread:
    """Background Mini2 capture with separate preview and recording paths.

    Preview delivery remains latest-only so the browser never accumulates stale
    video.  Frames captured during an explicit recording session are also put in
    an ordered FIFO and are never silently evicted.
    """

    def __init__(
        self,
        reader: Mini2PartsReader,
        *,
        start_time: float,
        max_queue: int = 1,
        max_recording_queue: int = 2048,
        on_frame: Callable[[CapturedMini2Frame], None] | None = None,
    ) -> None:
        if max_queue <= 0:
            raise ValueError("max_queue must be positive")
        if max_recording_queue <= 0:
            raise ValueError("max_recording_queue must be positive")
        self.reader = reader
        self.start_time = start_time
        self.on_frame = on_frame
        self.queue: queue.Queue[CapturedMini2Frame] = queue.Queue(maxsize=max_queue)
        self.max_recording_queue = int(max_recording_queue)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="mini2-capture", daemon=True)
        self._error: BaseException | None = None
        self._preview_dropped_frames = 0
        self._recording_dropped_frames = 0
        self._condition = threading.Condition()
        self._latest_capture: CapturedMini2Frame | None = None
        self._recording_frames: deque[CapturedMini2Frame] = deque()
        self._active_recording_session_id = 0
        self._last_recording_session_id = 0
        self._last_recording_frame_id: int | None = None
        self._processed_recording_frame_id: int | None = None
        self._recording_captured_frames = 0
        self._recording_processed_frames = 0
        self._recording_inflight_frames = 0
        self._max_recording_backlog = 0
        self._capture_count = 0
        self._first_capture_timestamp_s: float | None = None
        self._last_capture_timestamp_s: float | None = None

    def start(self) -> None:
        self._thread.start()

    def read(self, *, timeout_s: float = 5.0) -> CapturedMini2Frame:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        while True:
            with self._condition:
                if self._recording_frames:
                    captured = self._recording_frames.popleft()
                    self._recording_inflight_frames += 1
                    self._discard_preview_notifications()
                    self._condition.notify_all()
                    return captured
                if self._error is not None and self.queue.empty():
                    raise RuntimeError(f"Mini2 capture thread failed: {self._error}") from self._error
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for Mini2 frame")
            try:
                captured = self.queue.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            with self._condition:
                if self._recording_frames:
                    recorded = self._recording_frames.popleft()
                    self._recording_inflight_frames += 1
                    self._discard_preview_notifications()
                    self._condition.notify_all()
                    return recorded
            while True:
                try:
                    newer = self.queue.get_nowait()
                except queue.Empty:
                    return captured
                self._preview_dropped_frames += 1
                captured = newer

    def latest(self, *, timeout_s: float = 0.5) -> CapturedMini2Frame | None:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while self._latest_capture is None:
                if self._error is not None:
                    raise RuntimeError(f"Mini2 capture thread failed: {self._error}") from self._error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest_capture

    @property
    def dropped_frames(self) -> int:
        """Legacy total; use split counters for recording-loss decisions."""

        return self._preview_dropped_frames + self._recording_dropped_frames

    @property
    def preview_dropped_frames(self) -> int:
        return self._preview_dropped_frames

    @property
    def recording_dropped_frames(self) -> int:
        return self._recording_dropped_frames

    def begin_recording(self, session_id: int) -> dict[str, Any]:
        parsed = int(session_id)
        if parsed <= 0:
            raise ValueError("recording session_id must be positive")
        with self._condition:
            if self._active_recording_session_id:
                raise RuntimeError("Mini2 recording capture is already active")
            if self._recording_frames or self._recording_inflight_frames:
                raise RuntimeError("previous Mini2 recording backlog is still draining")
            self._active_recording_session_id = parsed
            self._last_recording_session_id = parsed
            self._last_recording_frame_id = None
            self._processed_recording_frame_id = None
            self._recording_captured_frames = 0
            self._recording_processed_frames = 0
            self._recording_dropped_frames = 0
            self._max_recording_backlog = 0
            self._condition.notify_all()
            return self.recording_status_locked()

    def end_recording(self, session_id: int) -> dict[str, Any]:
        parsed = int(session_id)
        with self._condition:
            if self._active_recording_session_id not in {0, parsed}:
                raise RuntimeError("Mini2 recording session does not match active CSV session")
            if self._last_recording_session_id not in {0, parsed}:
                raise RuntimeError("Mini2 recording session does not match latest capture session")
            self._active_recording_session_id = 0
            self._condition.notify_all()
            return self.recording_status_locked()

    def mark_processed(self, captured: CapturedMini2Frame, *, stored: bool = True) -> None:
        if captured.recording_session_id <= 0:
            return
        with self._condition:
            self._recording_inflight_frames = max(0, self._recording_inflight_frames - 1)
            self._recording_processed_frames += 1
            if not stored:
                self._recording_dropped_frames += 1
            self._processed_recording_frame_id = int(captured.frame_id)
            self._condition.notify_all()

    def recording_drained(self, session_id: int) -> bool:
        parsed = int(session_id)
        with self._condition:
            return self._recording_drained_locked(parsed)

    def recording_status(self) -> dict[str, Any]:
        with self._condition:
            return self.recording_status_locked()

    def recording_status_locked(self) -> dict[str, Any]:
        capture_span_s = 0.0
        if self._first_capture_timestamp_s is not None and self._last_capture_timestamp_s is not None:
            capture_span_s = max(0.0, self._last_capture_timestamp_s - self._first_capture_timestamp_s)
        capture_fps = 0.0
        if self._capture_count > 1 and capture_span_s > 0:
            capture_fps = (self._capture_count - 1) / capture_span_s
        backlog = len(self._recording_frames) + self._recording_inflight_frames
        return {
            "active_session_id": self._active_recording_session_id,
            "latest_session_id": self._last_recording_session_id,
            "last_recording_frame_id": self._last_recording_frame_id,
            "processed_recording_frame_id": self._processed_recording_frame_id,
            "recording_captured_frames": self._recording_captured_frames,
            "recording_processed_frames": self._recording_processed_frames,
            "recording_backlog_frames": backlog,
            "recording_max_backlog_frames": self._max_recording_backlog,
            "recording_dropped_frames": self._recording_dropped_frames,
            "preview_dropped_frames": self._preview_dropped_frames,
            "capture_count": self._capture_count,
            "capture_fps": round(capture_fps, 6),
            "drained": self._recording_drained_locked(self._last_recording_session_id),
        }

    def _recording_drained_locked(self, session_id: int) -> bool:
        if session_id <= 0 or session_id != self._last_recording_session_id:
            return True
        return (
            self._active_recording_session_id == 0
            and not self._recording_frames
            and self._recording_inflight_frames == 0
            and self._recording_processed_frames >= self._recording_captured_frames
        )

    def close(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        self._thread.join(timeout=2.0)
        self.reader.release()

    def _loop(self) -> None:
        frame_id = 0
        try:
            while not self._stop.is_set():
                parts = self.reader.read_frame_parts()
                timestamp_s = time.perf_counter() - self.start_time
                with self._condition:
                    recording_session_id = self._active_recording_session_id
                    captured = CapturedMini2Frame(frame_id, timestamp_s, parts, recording_session_id)
                    self._latest_capture = captured
                    self._capture_count += 1
                    if self._first_capture_timestamp_s is None:
                        self._first_capture_timestamp_s = timestamp_s
                    self._last_capture_timestamp_s = timestamp_s
                    if recording_session_id > 0:
                        while len(self._recording_frames) >= self.max_recording_queue and not self._stop.is_set():
                            self._condition.wait(timeout=0.1)
                        if self._stop.is_set():
                            return
                        self._recording_frames.append(captured)
                        self._recording_captured_frames += 1
                        self._last_recording_frame_id = frame_id
                        backlog = len(self._recording_frames) + self._recording_inflight_frames
                        self._max_recording_backlog = max(self._max_recording_backlog, backlog)
                    self._condition.notify_all()
                self._put_latest(captured)
                if self.on_frame is not None:
                    self.on_frame(captured)
                frame_id += 1
        except BaseException as exc:  # noqa: BLE001 - propagated through read().
            self._error = exc
            with self._condition:
                self._condition.notify_all()

    def _put_latest(self, captured: CapturedMini2Frame) -> None:
        while not self._stop.is_set():
            try:
                self.queue.put_nowait(captured)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self._preview_dropped_frames += 1
                except queue.Empty:
                    pass

    def _discard_preview_notifications(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return


def start_mini2_capture_thread(
    reader: Mini2PartsReader,
    *,
    start_time: float,
    thermal_stream_publisher: "LiveJpegStreamPublisher | None" = None,
    thermal_rotation_getter: Callable[[], int] | None = None,
    max_recording_queue: int = 2048,
) -> Mini2CaptureThread:
    """Start the Mini2 reader thread and wire raw frames to the live thermal preview."""

    def publish_thermal(captured: CapturedMini2Frame) -> None:
        if thermal_stream_publisher is None:
            return
        # Rotation, palette conversion, overlays, and JPEG encoding belong to
        # the latest-only preview worker, never the lossless UVC capture thread.
        thermal_stream_publisher.submit(captured.parts.raw_matrix)

    worker = Mini2CaptureThread(
        reader,
        start_time=start_time,
        max_recording_queue=max_recording_queue,
        on_frame=publish_thermal if thermal_stream_publisher is not None else None,
    )
    worker.start()
    return worker


class VisibleLatestFrameThread:
    """Continuously read visible camera frames and expose timestamped RGB frames."""

    def __init__(self, camera: Any, *, start_time: float, max_buffer: int = 32) -> None:
        self.camera = camera
        self.start_time = start_time
        self.frames = VisibleFrameBuffer(maxlen=max_buffer)
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._condition = threading.Condition()
        self._latest_frame: TimestampedVisibleFrame | None = None
        self._error: BaseException | None = None
        self._count = 0
        self._thread = threading.Thread(target=self._loop, name="visible-capture", daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def count(self) -> int:
        return self._count

    def latest_timestamped(self, *, timeout_s: float = 2.0) -> TimestampedVisibleFrame | None:
        self._ready.wait(timeout_s)
        if self._error is not None and self.frames.latest() is None:
            raise RuntimeError(f"visible camera thread failed: {self._error}") from self._error
        return self.frames.latest()

    def wait_next(self, *, last_frame_id: int, timeout_s: float = 2.0) -> TimestampedVisibleFrame:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while True:
                available = self.frames.first_after(int(last_frame_id))
                if available is not None:
                    return available
                if self._error is not None:
                    raise RuntimeError(f"visible camera thread failed: {self._error}") from self._error
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for next visible frame")
                self._condition.wait(remaining)

    def nearest(
        self,
        timestamp_s: float,
        *,
        timeout_s: float = 2.0,
        max_age_s: float | None = None,
        future_wait_s: float = 0.0,
        future_wait_min_gap_s: float = 0.0,
    ) -> TimestampedVisibleFrame | None:
        self._ready.wait(timeout_s)
        if self._error is not None and self.frames.latest() is None:
            raise RuntimeError(f"visible camera thread failed: {self._error}") from self._error
        wait_s = max(0.0, float(future_wait_s))
        min_gap_s = max(0.0, float(future_wait_min_gap_s))
        if wait_s > 0.0:
            deadline = time.monotonic() + wait_s
            while True:
                latest = self.frames.latest()
                if latest is None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0.0:
                        break
                    with self._condition:
                        self._condition.wait(remaining)
                    continue
                latest_gap_s = float(timestamp_s) - float(latest.timestamp_s)
                if latest_gap_s <= min_gap_s:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    break
                with self._condition:
                    self._condition.wait(remaining)
        return self.frames.nearest(timestamp_s, max_age_s=max_age_s)

    def latest(self, *, timeout_s: float = 2.0) -> np.ndarray | None:
        frame = self.latest_timestamped(timeout_s=timeout_s)
        return None if frame is None else frame.frame_rgb.copy()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self.camera.release()

    def _loop(self) -> None:
        try:
            while not self._stop.is_set():
                read_start = time.perf_counter()
                frame = self.camera.read_rgb()
                read_end = time.perf_counter()
                timestamp_s = ((read_start + read_end) / 2.0) - self.start_time
                received_s = read_end - self.start_time
                # UsbCamera.read_rgb() returns a fresh cvtColor result.  Keep it
                # directly; another full-frame copy here only adds bandwidth and
                # latency before the ring buffer/preview paths split.
                captured = TimestampedVisibleFrame(self._count, timestamp_s, np.ascontiguousarray(frame), received_s)
                self.frames.add(captured)
                with self._condition:
                    self._latest_frame = captured
                    self._condition.notify_all()
                self._count += 1
                self._ready.set()
        except BaseException as exc:  # noqa: BLE001 - propagated if no frame is available.
            self._error = exc
            self._ready.set()
            with self._condition:
                self._condition.notify_all()


class VisiblePreviewStreamThread:
    """Forward visible capture frames directly to a JPEG publisher.

    The analysis loop still asks ``VisibleLatestFrameThread`` for the nearest
    timestamped frame, but browser preview no longer waits for a Mini2 frame or
    ROI/ML processing pass before it can display a fresh visible-camera image.
    """

    def __init__(
        self,
        visible_worker: VisibleLatestFrameThread,
        publisher: Any,
        *,
        wait_timeout_s: float = 0.5,
    ) -> None:
        self.visible_worker = visible_worker
        self.publisher = publisher
        self.wait_timeout_s = max(0.01, float(wait_timeout_s))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="visible-preview-stream", daemon=True)
        self._started = False
        self._error: BaseException | None = None

    def start(self) -> None:
        if not self._started:
            self._thread.start()
            self._started = True

    @property
    def error(self) -> BaseException | None:
        return self._error

    def close(self) -> None:
        self._stop.set()
        if self._started:
            self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        last_frame_id = -1
        while not self._stop.is_set():
            try:
                frame = self.visible_worker.wait_next(last_frame_id=last_frame_id, timeout_s=self.wait_timeout_s)
            except TimeoutError:
                continue
            except BaseException as exc:  # noqa: BLE001 - stored for diagnostics; close path remains best-effort.
                if not self._stop.is_set():
                    self._error = exc
                return
            last_frame_id = frame.frame_id
            self.publisher.submit(frame.frame_rgb)


@dataclass
class WindowsMini2OpenCvRawCapture:
    """Read Mini2 256x344 YUY2 raw bytes from Windows OpenCV."""

    index: int = 0
    backend: str = "MSMF"
    width: int = MINI2_UVC_WIDTH
    height: int = MINI2_UVC_HEIGHT
    fps: float = MINI2_FRAME_RATE_HZ
    fourcc: str = "YUY2"

    def __post_init__(self) -> None:
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised on Windows setup failures.
            raise RuntimeError("opencv-python is required for Windows Mini2 capture") from exc
        self._cv2 = cv2
        backend_value = opencv_backend_value(cv2, self.backend)
        self._capture = (
            cv2.VideoCapture(self.index, backend_value)
            if backend_value is not None
            else cv2.VideoCapture(self.index)
        )
        self._capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(self.width))
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(self.height))
        self._capture.set(cv2.CAP_PROP_FPS, float(self.fps))
        self._capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
            self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self._capture.isOpened():
            raise RuntimeError(f"could not open Mini2 at Windows camera index {self.index}")

    def read_frame_parts(self):
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("failed to read Mini2 raw frame from Windows OpenCV")
        raw_bytes = mini2_raw_bytes_from_opencv_frame(frame, width=self.width, height=self.height)
        return extract_mini2_frame_parts(raw_bytes, width=self.width, height=self.height)

    def release(self) -> None:
        self._capture.release()


def mini2_backend_candidates(backend: str | None) -> list[str]:
    normalized = str(backend or "AUTO").strip().upper()
    if normalized in {"", "AUTO"}:
        return ["MSMF", "ANY", "DSHOW"]
    return [normalized]


def open_mini2_capture(args: argparse.Namespace, *, capture_factory=WindowsMini2OpenCvRawCapture) -> tuple[Mini2PartsReader, int]:
    """Open a Mini2 raw stream, auto-detecting the camera index when requested."""

    requested = str(getattr(args, "mini2_index", "auto")).strip().lower()
    max_index = int(getattr(args, "mini2_max_index", 10))
    backend_candidates = mini2_backend_candidates(getattr(args, "mini2_backend", "AUTO"))
    common_kwargs_base = {
        "width": args.mini2_width,
        "height": args.mini2_height,
        "fps": args.frame_rate_hz,
        "fourcc": args.mini2_fourcc,
    }
    if requested not in {"", "auto"}:
        index = int(requested)
        last_error: Exception | None = None
        for backend in backend_candidates:
            try:
                reader = capture_factory(index=index, backend=backend, **common_kwargs_base)
                args.mini2_backend = backend
                return reader, index
            except Exception as exc:  # noqa: BLE001 - try requested index with all requested backends.
                last_error = exc
        raise RuntimeError(f"could not open Mini2 at Windows camera index {index}: {last_error}")

    errors: list[str] = []
    for index in range(max_index):
        for backend in backend_candidates:
            reader: Mini2PartsReader | None = None
            try:
                reader = capture_factory(index=index, backend=backend, **common_kwargs_base)
                reader.read_frame_parts()
                args.mini2_backend = backend
                print(f"Auto-detected Mini2 raw stream: index={index} backend={backend}", flush=True)
                return reader, index
            except Exception as exc:  # noqa: BLE001 - probe all indices/backends and report compact evidence.
                errors.append(f"{index}/{backend}: {exc}")
                if reader is not None:
                    try:
                        reader.release()
                    except Exception:
                        pass
    detail = " | ".join(errors[-5:])
    raise RuntimeError(
        f"could not auto-detect Mini2 raw stream in camera indices 0..{max_index - 1}. "
        f"Tried backends {','.join(backend_candidates)}. Set MINI2_INDEX manually if needed. Last errors: {detail}"
    )


def open_visible_camera(
    args: argparse.Namespace,
    *,
    skip_indices: set[int] | None = None,
    camera_factory=UsbCamera,
) -> tuple[Any | None, int | None]:
    """Open a visible camera, auto-detecting one that is not the Mini2 stream."""

    requested = str(getattr(args, "visible_index", "auto")).strip().lower()
    skip_indices = skip_indices or set()
    max_index = int(getattr(args, "visible_max_index", 10))

    def build(index: int) -> Any:
        return camera_factory(
            CameraConfig(
                device_index=index,
                width=args.visible_width if args.visible_width > 0 else None,
                height=args.visible_height if args.visible_height > 0 else None,
                backend=args.visible_backend,
                name="visible-camera",
            )
        )

    if requested not in {"", "auto"}:
        index = int(requested)
        return build(index), index

    errors: list[str] = []
    for index in range(max_index):
        if index in skip_indices:
            continue
        camera = None
        try:
            camera = build(index)
            camera.read_rgb()
            print(f"Auto-detected visible camera: index={index} backend={args.visible_backend}", flush=True)
            return camera, index
        except Exception as exc:  # noqa: BLE001 - probe all indices and continue thermal-only if needed.
            errors.append(f"{index}: {exc}")
            if camera is not None:
                try:
                    camera.release()
                except Exception:
                    pass
    detail = " | ".join(errors[-5:])
    print(
        f"Warning: could not auto-detect visible camera in indices 0..{max_index - 1}; continuing thermal-only. "
        f"Set VISIBLE_INDEX manually if needed. Last errors: {detail}",
        flush=True,
    )
    return None, None


def opencv_backend_value(cv2, backend: str | None) -> int | None:  # type: ignore[no-untyped-def]
    if backend is None:
        return None
    normalized = backend.strip().upper()
    attr = BACKEND_NAMES.get(normalized)
    if attr is None:
        if normalized in {"", "ANY", "AUTO"}:
            return None
        raise ValueError(f"unsupported OpenCV backend: {backend}")
    if not hasattr(cv2, attr):
        raise ValueError(f"OpenCV build does not expose backend {attr}")
    return int(getattr(cv2, attr))


def mini2_raw_bytes_from_opencv_frame(
    frame: np.ndarray,
    *,
    width: int = MINI2_UVC_WIDTH,
    height: int = MINI2_UVC_HEIGHT,
) -> bytes:
    """Normalize OpenCV raw YUY2 output to one 256x344x2 byte frame.

    With Windows MSMF/ANY and ``CAP_PROP_CONVERT_RGB=0``, OpenCV commonly
    returns shape ``(1, width*height*2)``.  Some builds may return a flat vector
    or a ``(height, width, 2)`` array.  BGR-converted 3-channel frames are
    rejected because they no longer contain the radiometric uint16 stream.
    """

    expected = int(width) * int(height) * 2
    arr = np.asarray(frame)
    if arr.dtype != np.uint8:
        raise ValueError(f"Mini2 raw OpenCV frame must be uint8, got {arr.dtype}")
    if arr.nbytes != expected:
        raise ValueError(
            f"expected {expected} raw bytes for Mini2 {width}x{height} YUY2 frame, "
            f"got shape {arr.shape} with {arr.nbytes} bytes; use backend MSMF/ANY with raw conversion disabled"
        )
    return np.ascontiguousarray(arr).reshape(-1).tobytes()


def parse_roi(value: str) -> Roi:
    parts = [int(part.strip()) for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("ROI must be x,y,width,height")
    return Roi(parts[0], parts[1], parts[2], parts[3])


def resolve_visible_roi(value: str, frame_rgb: np.ndarray) -> Roi:
    if value.strip().lower() == "auto":
        h, w = frame_rgb.shape[:2]
        roi_w = max(1, w // 2)
        roi_h = max(1, h // 2)
        return Roi((w - roi_w) // 2, (h - roi_h) // 2, roi_w, roi_h)
    roi = parse_roi(value)
    roi.validate_for(frame_rgb)
    return roi


def _shape_hw(shape: tuple[int, ...] | list[int] | np.ndarray) -> tuple[int, int]:
    if isinstance(shape, np.ndarray):
        shape = shape.shape
    if len(shape) < 2:
        raise ValueError("shape must contain height and width")
    h, w = int(shape[0]), int(shape[1])
    if h <= 0 or w <= 0:
        raise ValueError("shape height and width must be positive")
    return h, w


def clamp_roi_to_shape(roi: Roi, shape: tuple[int, ...] | list[int] | np.ndarray) -> Roi:
    h, w = _shape_hw(shape)
    x = max(0, min(int(roi.x), w - 1))
    y = max(0, min(int(roi.y), h - 1))
    width = max(1, min(int(roi.width), w - x))
    height = max(1, min(int(roi.height), h - y))
    return Roi(x, y, width, height)


def seed_center_roi(
    seed: tuple[int, int],
    shape: tuple[int, ...] | list[int] | np.ndarray,
    *,
    width: int,
    height: int,
) -> Roi:
    h, w = _shape_hw(shape)
    sx = max(0, min(int(seed[0]), w - 1))
    sy = max(0, min(int(seed[1]), h - 1))
    return clamp_roi_to_shape(Roi(sx - int(width) // 2, sy - int(height) // 2, int(width), int(height)), (h, w))


def _bbox_from_mask(mask: np.ndarray, *, offset_x: int = 0, offset_y: int = 0, padding: int = 0) -> Roi | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    x0 = int(xs.min()) + int(offset_x) - int(padding)
    x1 = int(xs.max()) + int(offset_x) + int(padding)
    y0 = int(ys.min()) + int(offset_y) - int(padding)
    y1 = int(ys.max()) + int(offset_y) + int(padding)
    return Roi(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


def roi_mask_from_bool(
    mask: np.ndarray,
    *,
    confidence: float,
    source: str,
    padding: int = 0,
    component_count: int = 1,
    stability: str = "fresh",
) -> RoiMask:
    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("ROI mask must be a 2D boolean array")
    bbox = _bbox_from_mask(arr, padding=padding)
    if bbox is None:
        raise ValueError("ROI mask must contain at least one selected pixel")
    h, w = arr.shape
    bbox = clamp_roi_to_shape(bbox, (h, w))
    clipped = np.zeros((h, w), dtype=bool)
    clipped[bbox.y : bbox.y + bbox.height, bbox.x : bbox.x + bbox.width] = arr[
        bbox.y : bbox.y + bbox.height,
        bbox.x : bbox.x + bbox.width,
    ]
    return RoiMask(
        mask=clipped,
        bbox=bbox,
        confidence=round(float(max(0.0, min(1.0, confidence))), 6),
        source=str(source),
        component_count=max(1, int(component_count)),
        stability=str(stability),
    )


def keep_largest_mask_component(mask: np.ndarray, *, min_area_px: int = 1) -> tuple[np.ndarray, int]:
    """Keep the largest 4-connected component and report detected component count."""

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = arr.shape
    visited = np.zeros((h, w), dtype=bool)
    largest: list[tuple[int, int]] = []
    component_count = 0
    min_area = max(1, int(min_area_px))
    for y in range(h):
        for x in range(w):
            if not arr[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            coords: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                coords.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            if len(coords) >= min_area:
                component_count += 1
                if len(coords) > len(largest):
                    largest = coords
    cleaned = np.zeros((h, w), dtype=bool)
    for y, x in largest:
        cleaned[y, x] = True
    return cleaned, component_count


def keep_mask_component_containing(
    mask: np.ndarray,
    seed_xy: tuple[int, int],
    *,
    min_area_px: int = 1,
) -> tuple[np.ndarray, int]:
    """Keep the 4-connected mask component containing the clicked seed."""

    arr = np.asarray(mask, dtype=bool)
    if arr.ndim != 2:
        raise ValueError("mask must be 2D")
    h, w = arr.shape
    sx = max(0, min(int(seed_xy[0]), w - 1))
    sy = max(0, min(int(seed_xy[1]), h - 1))
    visited = np.zeros((h, w), dtype=bool)
    selected: list[tuple[int, int]] = []
    component_count = 0
    min_area = max(1, int(min_area_px))
    for y in range(h):
        for x in range(w):
            if not arr[y, x] or visited[y, x]:
                continue
            stack = [(y, x)]
            visited[y, x] = True
            coords: list[tuple[int, int]] = []
            contains_seed = False
            while stack:
                cy, cx = stack.pop()
                coords.append((cy, cx))
                contains_seed = contains_seed or (cy == sy and cx == sx)
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
            if len(coords) >= min_area:
                component_count += 1
                if contains_seed:
                    selected = coords
    cleaned = np.zeros((h, w), dtype=bool)
    for y, x in selected:
        cleaned[y, x] = True
    return cleaned, component_count


def _dilate_mask(mask: np.ndarray) -> np.ndarray:
    arr = np.asarray(mask, dtype=bool)
    padded = np.pad(arr, 1, mode="constant", constant_values=False)
    out = np.zeros_like(arr, dtype=bool)
    for dy in range(3):
        for dx in range(3):
            out |= padded[dy : dy + arr.shape[0], dx : dx + arr.shape[1]]
    return out


def _erode_mask(mask: np.ndarray) -> np.ndarray:
    arr = np.asarray(mask, dtype=bool)
    padded = np.pad(arr, 1, mode="constant", constant_values=False)
    out = np.ones_like(arr, dtype=bool)
    for dy in range(3):
        for dx in range(3):
            out &= padded[dy : dy + arr.shape[0], dx : dx + arr.shape[1]]
    return out


def smooth_mask_shape(mask: np.ndarray) -> np.ndarray:
    """Remove single-pixel noise and fill tiny holes while keeping shape."""

    arr = np.asarray(mask, dtype=bool)
    if not bool(np.any(arr)):
        return arr.copy()
    closed = _erode_mask(_dilate_mask(arr))
    opened = _dilate_mask(_erode_mask(closed))
    return opened if bool(np.any(opened)) else arr.copy()


def _as_numpy_array(value: Any) -> np.ndarray:
    """Convert NumPy/torch-like Ultralytics tensors to a NumPy array."""

    obj = value
    for attr in ("detach", "cpu"):
        method = getattr(obj, attr, None)
        if callable(method):
            obj = method()
    to_numpy = getattr(obj, "numpy", None)
    if callable(to_numpy):
        obj = to_numpy()
    return np.asarray(obj)


def _resize_mask_nearest(mask: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    src = np.asarray(mask, dtype=bool)
    src_h, src_w = _shape_hw(src.shape)
    dst_h, dst_w = _shape_hw(target_shape)
    y_idx = np.minimum(src_h - 1, np.floor(np.arange(dst_h) * src_h / max(1, dst_h)).astype(int))
    x_idx = np.minimum(src_w - 1, np.floor(np.arange(dst_w) * src_w / max(1, dst_w)).astype(int))
    return src[y_idx[:, None], x_idx[None, :]]


def scale_mask_to_shape(roi_mask: RoiMask, target_shape: tuple[int, int], *, source: str | None = None) -> RoiMask:
    scaled = _resize_mask_nearest(roi_mask.mask, target_shape)
    if not bool(np.any(scaled)):
        # Tiny masks can disappear under down-scaling. Preserve the centroid.
        src_h, src_w = _shape_hw(roi_mask.mask.shape)
        dst_h, dst_w = _shape_hw(target_shape)
        cx, cy = roi_mask.centroid_xy
        x = max(0, min(dst_w - 1, int(round(cx * dst_w / max(1, src_w)))))
        y = max(0, min(dst_h - 1, int(round(cy * dst_h / max(1, src_h)))))
        scaled[y, x] = True
    return roi_mask_from_bool(
        scaled,
        confidence=roi_mask.confidence,
        source=source or f"scaled:{roi_mask.source}",
        component_count=roi_mask.component_count,
        stability=roi_mask.stability,
    )


def parse_yolo_classes(value: str | set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    if value is None:
        return set(DEFAULT_YOLO_VISIBLE_CLASSES)
    if isinstance(value, set):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    if isinstance(value, (list, tuple)):
        return {str(item).strip().lower() for item in value if str(item).strip()}
    text = str(value).strip()
    if not text:
        return set(DEFAULT_YOLO_VISIBLE_CLASSES)
    return {part.strip().lower() for part in text.split(",") if part.strip()}


def load_yolo_model(model_name: str, *, importer=importlib.import_module) -> Any:
    """Load Ultralytics YOLO lazily so normal collection/tests do not require it."""

    try:
        module = importer("ultralytics")
        yolo_cls = getattr(module, "YOLO")
    except Exception as exc:  # noqa: BLE001 - normalize optional dependency failure.
        raise RuntimeError(
            "Optional YOLO detector requires ultralytics. Install with: "
            "python -m pip install -r requirements-yolo.txt"
        ) from exc
    return yolo_cls(model_name)


def _yolo_class_name(names: Any, cls_index: int) -> str:
    if isinstance(names, dict):
        return str(names.get(cls_index, cls_index)).strip().lower()
    if isinstance(names, (list, tuple)) and 0 <= cls_index < len(names):
        return str(names[cls_index]).strip().lower()
    return str(cls_index)


def _box_to_roi(box_xyxy: np.ndarray, shape: tuple[int, int]) -> Roi:
    h, w = _shape_hw(shape)
    x1, y1, x2, y2 = [int(round(float(v))) for v in box_xyxy[:4]]
    x1 = max(0, min(w - 1, x1))
    y1 = max(0, min(h - 1, y1))
    x2 = max(x1, min(w - 1, x2))
    y2 = max(y1, min(h - 1, y2))
    return Roi(x1, y1, x2 - x1 + 1, y2 - y1 + 1)


def _visible_candidate_is_oversized(mask: np.ndarray, roi: Roi) -> bool:
    h, w = _shape_hw(mask.shape)
    frame_area = float(h * w)
    bbox_area_fraction = (roi.width * roi.height) / frame_area
    mask_area_fraction = int(np.count_nonzero(mask)) / frame_area
    edge_touches = int(roi.x <= 1) + int(roi.y <= 1) + int(roi.x + roi.width >= w - 1) + int(roi.y + roi.height >= h - 1)
    return (
        bbox_area_fraction > 0.45
        or mask_area_fraction > 0.38
        or roi.width > int(w * 0.85)
        or roi.height > int(h * 0.85)
        or (edge_touches >= 2 and bbox_area_fraction > 0.18)
    )


def auto_detect_visible_roi_yolo(
    frame_rgb: np.ndarray,
    yolo_model: Any,
    *,
    allowed_classes: set[str] | list[str] | tuple[str, ...] | str | None = None,
    min_confidence: float = 0.25,
    max_area_fraction: float = 0.45,
    inference_size: int = 0,
) -> RoiDetectionResult:
    """Detect visible ROI with an optional Ultralytics YOLO segmentation/detection model."""

    frame = np.asarray(frame_rgb)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("visible frame must have shape HxWx3")
    h, w = frame.shape[:2]
    allowed = parse_yolo_classes(allowed_classes)
    predict_kwargs: dict[str, Any] = {"source": frame, "verbose": False, "conf": float(min_confidence)}
    if int(inference_size or 0) > 0:
        predict_kwargs["imgsz"] = int(inference_size)
    try:
        raw_results = yolo_model.predict(**predict_kwargs)
    except TypeError:
        raw_results = yolo_model.predict(frame)
    if raw_results is None:
        return RoiDetectionResult(None, 0.0, "no_yolo_visible_candidate")
    results = list(raw_results) if isinstance(raw_results, (list, tuple)) else [raw_results]
    best: tuple[float, RoiDetectionResult] | None = None
    oversized_seen = False
    mask_unavailable_seen = False
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        xyxy = _as_numpy_array(getattr(boxes, "xyxy", []))
        confs = _as_numpy_array(getattr(boxes, "conf", []))
        classes = _as_numpy_array(getattr(boxes, "cls", []))
        if xyxy.ndim == 1 and xyxy.size >= 4:
            xyxy = xyxy.reshape(1, -1)
        names = getattr(result, "names", None) or getattr(yolo_model, "names", {})
        masks_obj = getattr(result, "masks", None)
        masks_data = None if masks_obj is None else getattr(masks_obj, "data", None)
        masks_arr = None if masks_data is None else _as_numpy_array(masks_data)
        if masks_arr is not None and masks_arr.ndim == 2:
            masks_arr = masks_arr.reshape(1, *masks_arr.shape)
        for idx, box in enumerate(xyxy):
            confidence = float(confs[idx]) if idx < len(confs) else 0.0
            if confidence < float(min_confidence):
                continue
            cls_index = int(round(float(classes[idx]))) if idx < len(classes) else -1
            class_name = _yolo_class_name(names, cls_index)
            if class_name in REJECTED_YOLO_VISIBLE_CLASSES:
                continue
            if allowed and class_name not in allowed:
                continue
            roi = _box_to_roi(box, (h, w))
            if (roi.width * roi.height) / float(h * w) > float(max_area_fraction):
                oversized_seen = True
                continue
            if masks_arr is None or idx >= len(masks_arr):
                mask_unavailable_seen = True
                continue
            mask = np.asarray(masks_arr[idx], dtype=np.float64) > 0.5
            if mask.shape != (h, w):
                mask = _resize_mask_nearest(mask, (h, w))
            if not bool(np.any(mask)):
                mask_unavailable_seen = True
                continue
            source = f"yolo_mask:{class_name}"
            min_area = max(20, int(h * w * 0.0005))
            cleaned, raw_component_count = keep_largest_mask_component(mask, min_area_px=1)
            cleaned = smooth_mask_shape(cleaned)
            cleaned, component_count = keep_largest_mask_component(cleaned, min_area_px=min_area)
            component_count = max(component_count, raw_component_count)
            if int(np.count_nonzero(cleaned)) < max(40, int(h * w * 0.002)):
                continue
            bbox = _bbox_from_mask(cleaned)
            if bbox is None:
                continue
            roi = clamp_roi_to_shape(bbox, (h, w))
            if _visible_candidate_is_oversized(cleaned, roi):
                oversized_seen = True
                continue
            roi_mask = roi_mask_from_bool(
                cleaned,
                confidence=confidence,
                source=source,
                component_count=component_count,
            )
            score = confidence + 0.05
            candidate = RoiDetectionResult(roi, round(confidence, 6), f"yolo_visible_candidate:{class_name}", mask=roi_mask)
            if best is None or score > best[0]:
                best = (score, candidate)
    if best is not None:
        return best[1]
    if mask_unavailable_seen:
        return RoiDetectionResult(None, 0.1, "yolo_segmentation_mask_unavailable")
    reason = "oversized_yolo_visible_candidate" if oversized_seen else "no_yolo_visible_candidate"
    return RoiDetectionResult(None, 0.1, reason)


class YoloVisibleRoiWorker:
    """Latest-only background YOLO ROI worker.

    YOLO inference is intentionally kept out of the 25fps collector loop.  The
    loop submits the latest visible frame and consumes the latest completed ROI
    result if one is ready; stale submitted frames are dropped.
    """

    def __init__(
        self,
        yolo_model: Any,
        *,
        allowed_classes: set[str] | list[str] | tuple[str, ...] | str | None = None,
        min_confidence: float = 0.25,
        max_area_fraction: float = 0.45,
        min_interval_s: float = 1.0,
        success_interval_s: float = 5.0,
        inference_size: int = 256,
    ) -> None:
        self.yolo_model = yolo_model
        self.allowed_classes = parse_yolo_classes(allowed_classes)
        self.min_confidence = float(min_confidence)
        self.max_area_fraction = float(max_area_fraction)
        self.min_interval_s = max(0.0, float(min_interval_s))
        self.success_interval_s = max(self.min_interval_s, float(success_interval_s))
        self.inference_size = max(0, int(inference_size or 0))
        self._condition = threading.Condition()
        self._pending_frame: np.ndarray | None = None
        self._latest_result: RoiDetectionResult | None = None
        self._latest_error: str = ""
        self._sequence = 0
        self._busy = False
        self._last_submit_time = -1.0e9
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="yolo-visible-roi", daemon=True)
        self._thread.start()

    def submit(self, frame_rgb: np.ndarray) -> bool:
        """Queue one frame for YOLO if the worker is ready.

        Returns False when a previous inference is still running or when the
        throttle interval has not elapsed.  This keeps YOLO from continuously
        competing with the 25fps capture/display path.
        """

        now = time.monotonic()
        with self._condition:
            interval_s = self.min_interval_s
            if self._latest_result is not None and self._latest_result.roi is not None:
                interval_s = self.success_interval_s
            if self._busy or self._pending_frame is not None or (now - self._last_submit_time) < interval_s:
                return False
            self._pending_frame = np.asarray(frame_rgb).copy()
            self._last_submit_time = now
            self._condition.notify()
            return True

    def latest_result(self, *, timeout_s: float = 0.0) -> RoiDetectionResult | None:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while self._latest_result is None and not self._latest_error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return self._latest_result

    @property
    def latest_error(self) -> str:
        with self._condition:
            return self._latest_error

    @property
    def sequence(self) -> int:
        with self._condition:
            return self._sequence

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while True:
            with self._condition:
                while self._pending_frame is None and not self._stop:
                    self._condition.wait()
                if self._pending_frame is None and self._stop:
                    return
                frame = self._pending_frame
                self._pending_frame = None
                self._busy = True
            try:
                result = auto_detect_visible_roi_yolo(
                    frame,
                    self.yolo_model,
                    allowed_classes=self.allowed_classes,
                    min_confidence=self.min_confidence,
                    max_area_fraction=self.max_area_fraction,
                    inference_size=self.inference_size,
                )
                error = ""
            except Exception as exc:  # noqa: BLE001 - report through live status, keep collector alive.
                result = RoiDetectionResult(None, 0.0, f"yolo_error:{exc}")
                error = str(exc)
            with self._condition:
                self._latest_result = result
                self._latest_error = error
                self._sequence += 1
                self._busy = False
                self._condition.notify_all()


class AutoRoiWorker:
    """Latest-only background ROI detector that never mutates ROI state.

    Visible-camera automatic ROI is YOLO-only and normally handled by
    YoloVisibleRoiWorker. This worker is kept for thermal ROI work and for
    tests that inject an explicit visible detector; it has no RGB/contrast
    visible detector fallback.
    """

    def __init__(
        self,
        *,
        visible_detector_fn: Callable[[np.ndarray], RoiDetectionResult] | None = None,
        thermal_detector_fn: Callable[[np.ndarray], RoiDetectionResult] | None = None,
    ) -> None:
        self.visible_detector_fn = visible_detector_fn
        self.thermal_detector_fn = auto_detect_thermal_roi if thermal_detector_fn is None else thermal_detector_fn
        self._condition = threading.Condition()
        self._pending: tuple[
            int,
            AutoRoiSettingsSnapshot,
            np.ndarray | None,
            np.ndarray | None,
            int | None,
            float | None,
            int | None,
            float | None,
            float,
        ] | None = None
        self._latest_result: AutoRoiWorkerResult | None = None
        self._sequence = 0
        self._busy = False
        self._dropped_pending = 0
        self._stop = False
        self._thread = threading.Thread(target=self._loop, name="auto-roi-worker", daemon=True)
        self._thread.start()

    def submit(
        self,
        *,
        visible_frame: np.ndarray | None,
        thermal_matrix: np.ndarray | None,
        settings: AutoRoiSettingsSnapshot,
        visible_frame_id: int | None = None,
        visible_timestamp_s: float | None = None,
        thermal_frame_id: int | None = None,
        thermal_timestamp_s: float | None = None,
    ) -> int | None:
        """Submit the latest source data and return its worker sequence.

        Pending, not-yet-started work is replaced.  Work already running is not
        interrupted, but only the newest pending request will run next.
        """

        mode = str(settings.mode or "off").strip().lower()
        if mode == "off":
            return None
        visible_copy: np.ndarray | None = None
        thermal_copy: np.ndarray | None = None
        if mode in {"visible", "both"} and self.visible_detector_fn is not None and visible_frame is not None:
            visible_copy = np.asarray(visible_frame).copy()
        if mode in {"thermal", "both"} and thermal_matrix is not None:
            thermal_copy = np.asarray(thermal_matrix).copy()
        if visible_copy is None and thermal_copy is None:
            return None
        with self._condition:
            self._sequence += 1
            sequence = self._sequence
            if self._pending is not None:
                self._dropped_pending += 1
            self._pending = (
                sequence,
                settings,
                visible_copy,
                thermal_copy,
                visible_frame_id,
                visible_timestamp_s,
                thermal_frame_id,
                thermal_timestamp_s,
                time.time(),
            )
            self._condition.notify()
            return sequence

    def latest_result(self, *, after_sequence: int = 0, timeout_s: float = 0.0) -> AutoRoiWorkerResult | None:
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._condition:
            while True:
                if self._latest_result is not None and self._latest_result.sequence > int(after_sequence):
                    return self._latest_result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

    @property
    def dropped_pending(self) -> int:
        with self._condition:
            return self._dropped_pending

    @property
    def busy(self) -> bool:
        with self._condition:
            return self._busy

    def close(self) -> None:
        with self._condition:
            self._stop = True
            self._condition.notify_all()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._stop:
                    self._condition.wait()
                if self._pending is None and self._stop:
                    return
                (
                    sequence,
                    settings,
                    visible_frame,
                    thermal_matrix,
                    visible_frame_id,
                    visible_timestamp_s,
                    thermal_frame_id,
                    thermal_timestamp_s,
                    submitted_epoch_s,
                ) = self._pending
                self._pending = None
                self._busy = True
            visible_result: RoiDetectionResult | None = None
            thermal_result: RoiDetectionResult | None = None
            error = ""
            try:
                if visible_frame is not None:
                    visible_result = self.visible_detector_fn(visible_frame)
                if thermal_matrix is not None:
                    thermal_result = self.thermal_detector_fn(thermal_matrix)
            except Exception as exc:  # noqa: BLE001 - surfaced in metadata; capture must continue.
                error = str(exc)
            result = AutoRoiWorkerResult(
                sequence=sequence,
                settings=settings,
                visible_frame_id=visible_frame_id,
                visible_timestamp_s=visible_timestamp_s,
                thermal_frame_id=thermal_frame_id,
                thermal_timestamp_s=thermal_timestamp_s,
                submitted_epoch_s=submitted_epoch_s,
                completed_epoch_s=time.time(),
                visible_result=visible_result,
                thermal_result=thermal_result,
                error=error,
            )
            with self._condition:
                self._latest_result = result
                self._busy = False
                self._condition.notify_all()


def detect_visible_roi_from_seed(frame_rgb: np.ndarray, seed: tuple[int, int]) -> Roi:
    """Return a fast bounded visible ROI around the user-clicked solution area."""

    result = detect_visible_mask_from_seed(frame_rgb, seed)
    if result.roi is None:
        raise ValueError(result.reason)
    return result.roi


def _rect_mask_for_roi(
    shape: tuple[int, int],
    roi: Roi,
    *,
    confidence: float,
    source: str,
    stability: str = "fresh",
) -> RoiMask:
    h, w = _shape_hw(shape)
    selected = clamp_roi_to_shape(roi, (h, w))
    mask = np.zeros((h, w), dtype=bool)
    mask[selected.y : selected.y + selected.height, selected.x : selected.x + selected.width] = True
    return roi_mask_from_bool(mask, confidence=confidence, source=source, stability=stability)


def detect_visible_mask_from_seed(frame_rgb: np.ndarray, seed: tuple[int, int]) -> RoiDetectionResult:
    """Return a fast visible-camera area mask around the clicked solution area."""

    frame = np.asarray(frame_rgb)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("visible frame must have shape HxWx3")
    h, w = frame.shape[:2]
    fallback = seed_center_roi(seed, (h, w), width=max(40, w // 2), height=max(30, h // 2))
    fallback_mask = _rect_mask_for_roi(
        (h, w),
        fallback,
        confidence=0.35,
        source="visible_click_center_mask_fallback",
        stability="fallback",
    )
    crop = seed_center_roi(seed, (h, w), width=max(40, w // 2), height=max(30, h // 2))
    region = frame[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width].astype(np.float64)
    if region.size == 0:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "visible_click_empty_region_fallback", mask=fallback_mask)
    gray = np.mean(region, axis=2)
    median = float(np.median(gray))
    std = float(np.std(gray))
    if not np.isfinite(std) or std < 3.0:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "visible_click_low_contrast_fallback", mask=fallback_mask)
    local_x = max(0, min(crop.width - 1, int(seed[0]) - crop.x))
    local_y = max(0, min(crop.height - 1, int(seed[1]) - crop.y))
    seed_gray = float(gray[local_y, local_x])
    mask = np.abs(gray - seed_gray) <= max(10.0, std * 0.55)
    raw_component_count = keep_largest_mask_component(mask, min_area_px=1)[1]
    mask = smooth_mask_shape(mask)
    mask, component_count = keep_mask_component_containing(
        mask,
        (local_x, local_y),
        min_area_px=max(20, int(h * w * 0.0005)),
    )
    full_mask = np.zeros((h, w), dtype=bool)
    full_mask[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width] = mask
    bbox = _bbox_from_mask(full_mask, padding=8)
    if bbox is None:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "visible_click_no_mask_fallback", mask=fallback_mask)
    roi = clamp_roi_to_shape(bbox, (h, w))
    sx, sy = int(seed[0]), int(seed[1])
    if not (roi.x <= sx <= roi.x + roi.width and roi.y <= sy <= roi.y + roi.height):
        return RoiDetectionResult(fallback, fallback_mask.confidence, "visible_click_seed_outside_mask_fallback", mask=fallback_mask)
    roi_mask = roi_mask_from_bool(
        full_mask,
        confidence=0.65,
        source="visible_click_contrast_mask",
        padding=8,
        component_count=max(component_count, raw_component_count),
    )
    return RoiDetectionResult(roi_mask.bbox, roi_mask.confidence, "visible_click_contrast_mask", mask=roi_mask)


def detect_thermal_roi_from_seed(raw_matrix: np.ndarray, seed: tuple[int, int]) -> Roi:
    """Return a fast bounded thermal ROI around the user-clicked Mini2 point."""

    result = detect_thermal_mask_from_seed(raw_matrix, seed)
    if result.roi is None:
        raise ValueError(result.reason)
    return result.roi


def detect_thermal_mask_from_seed(raw_matrix: np.ndarray, seed: tuple[int, int]) -> RoiDetectionResult:
    """Return a fast Mini2 area mask around the clicked thermal point."""

    matrix = np.asarray(raw_matrix)
    if matrix.ndim != 2:
        raise ValueError("thermal matrix must be 2D")
    h, w = matrix.shape[:2]
    fallback = seed_center_roi(seed, (h, w), width=64, height=48)
    fallback_mask = _rect_mask_for_roi(
        (h, w),
        fallback,
        confidence=0.35,
        source="thermal_click_center_mask_fallback",
        stability="fallback",
    )
    crop = seed_center_roi(seed, (h, w), width=80, height=60)
    region = matrix[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width].astype(np.float64)
    if region.size == 0:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "thermal_click_empty_region_fallback", mask=fallback_mask)
    median = float(np.median(region))
    std = float(np.std(region))
    if not np.isfinite(std) or std < 1.0:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "thermal_click_low_contrast_fallback", mask=fallback_mask)
    local_x = max(0, min(crop.width - 1, int(seed[0]) - crop.x))
    local_y = max(0, min(crop.height - 1, int(seed[1]) - crop.y))
    seed_value = float(region[local_y, local_x])
    mask = np.abs(region - seed_value) <= max(8.0, std * 0.55)
    if int(np.count_nonzero(mask)) < 12:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "thermal_click_not_enough_mask_fallback", mask=fallback_mask)
    raw_component_count = keep_largest_mask_component(mask, min_area_px=1)[1]
    mask = smooth_mask_shape(mask)
    mask, component_count = keep_mask_component_containing(
        mask,
        (local_x, local_y),
        min_area_px=max(12, int(h * w * 0.0005)),
    )
    full_mask = np.zeros((h, w), dtype=bool)
    full_mask[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width] = mask
    bbox = _bbox_from_mask(full_mask, padding=4)
    if bbox is None:
        return RoiDetectionResult(fallback, fallback_mask.confidence, "thermal_click_no_mask_fallback", mask=fallback_mask)
    roi = clamp_roi_to_shape(bbox, (h, w))
    sx, sy = int(seed[0]), int(seed[1])
    if not (roi.x <= sx <= roi.x + roi.width and roi.y <= sy <= roi.y + roi.height):
        return RoiDetectionResult(fallback, fallback_mask.confidence, "thermal_click_seed_outside_mask_fallback", mask=fallback_mask)
    roi_mask = roi_mask_from_bool(
        full_mask,
        confidence=0.65,
        source="thermal_click_contrast_mask",
        padding=4,
        component_count=max(component_count, raw_component_count),
    )
    return RoiDetectionResult(roi_mask.bbox, roi_mask.confidence, "thermal_click_contrast_mask", mask=roi_mask)


def auto_detect_visible_roi_setup_candidate(
    frame_rgb: np.ndarray,
    *,
    visible_detector: str = "yolo",
    yolo_model: Any | None = None,
    yolo_classes: set[str] | list[str] | tuple[str, ...] | str | None = None,
    min_confidence: float = 0.5,
    yolo_min_confidence: float = 0.25,
    yolo_max_area_fraction: float = 0.45,
) -> RoiDetectionResult:
    """Visible ROI for the setup button using YOLO only.

    RGB/contrast auto-candidates were intentionally removed because they
    over-selected faces/backgrounds in the real dashboard.  If YOLO is missing
    or cannot find an accepted vessel class, report that reason instead of
    silently creating a fake center box.
    """

    frame = np.asarray(frame_rgb)
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError("visible frame must have shape HxWx3")
    detector = str(visible_detector or "yolo").strip().lower()
    if detector != "yolo":
        return RoiDetectionResult(None, 0.0, "visible_detector_not_supported:yolo_only")
    if yolo_model is None:
        return RoiDetectionResult(None, 0.0, "yolo_model_unavailable")
    result = auto_detect_visible_roi_yolo(
        frame,
        yolo_model,
        allowed_classes=yolo_classes,
        min_confidence=float(yolo_min_confidence),
        max_area_fraction=float(yolo_max_area_fraction),
    )
    if result.roi is not None and result.confidence >= float(min_confidence):
        return result
    return result



def auto_detect_thermal_roi(raw_matrix: np.ndarray) -> RoiDetectionResult:
    matrix = np.asarray(raw_matrix)
    if matrix.ndim != 2:
        raise ValueError("thermal matrix must be 2D")
    h, w = matrix.shape[:2]
    matrix_f = matrix.astype(np.float64)
    std = float(np.std(matrix_f))
    if not np.isfinite(std) or std < 1.0:
        return RoiDetectionResult(None, 0.0, "flat_thermal_matrix")
    median = float(np.median(matrix_f))
    mask = np.abs(matrix_f - median) >= max(8.0, std * 0.7)
    min_area = max(12, int(h * w * 0.0005))
    _, raw_component_count = keep_largest_mask_component(mask, min_area_px=1)
    mask = smooth_mask_shape(mask)
    mask, component_count = keep_largest_mask_component(mask, min_area_px=min_area)
    component_count = max(component_count, raw_component_count)
    count = int(np.count_nonzero(mask))
    if count < max(40, int(h * w * 0.003)):
        return RoiDetectionResult(None, 0.1, "not_enough_thermal_contrast")
    bbox = _bbox_from_mask(mask, padding=4)
    if bbox is None:
        return RoiDetectionResult(None, 0.0, "no_thermal_candidate")
    roi = clamp_roi_to_shape(bbox, (h, w))
    area_fraction = (roi.width * roi.height) / float(h * w)
    confidence = min(0.95, max(0.5, 0.45 + min(0.35, area_fraction) + min(0.15, std / max(1.0, float(np.ptp(matrix_f))))))
    roi_mask = roi_mask_from_bool(
        mask,
        confidence=confidence,
        source="thermal_contrast_candidate",
        component_count=component_count,
    )
    return RoiDetectionResult(roi, round(float(confidence), 6), "thermal_contrast_candidate", mask=roi_mask)


def parse_roi_click_payload(body: bytes) -> tuple[str, int, int]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalized as ValueError for callers/tests.
        raise ValueError("ROI click payload must be valid JSON") from exc
    target = str(payload.get("target", "")).strip().lower()
    if target not in {"visible", "thermal"}:
        raise ValueError("ROI click target must be visible or thermal")
    try:
        x = int(round(float(payload["x"])))
        y = int(round(float(payload["y"])))
    except Exception as exc:  # noqa: BLE001 - normalized as ValueError for callers/tests.
        raise ValueError("ROI click payload must include numeric x and y") from exc
    if x < 0 or y < 0:
        raise ValueError("ROI click coordinates must be non-negative")
    return target, x, y


def parse_roi_rect_payload(payload: dict[str, Any]) -> tuple[str, Roi]:
    if not isinstance(payload, dict):
        raise ValueError("ROI rectangle payload must be a JSON object")
    target = str(payload.get("target", "")).strip().lower()
    if target not in {"visible", "thermal"}:
        raise ValueError("ROI rectangle target must be visible or thermal")
    try:
        x = int(round(float(payload["x"])))
        y = int(round(float(payload["y"])))
        width = int(round(float(payload["width"])))
        height = int(round(float(payload["height"])))
    except Exception as exc:  # noqa: BLE001 - normalized as ValueError for callers/tests.
        raise ValueError("ROI rectangle payload must include numeric x, y, width, and height") from exc
    if x < 0 or y < 0:
        raise ValueError("ROI rectangle coordinates must be non-negative")
    if width <= 0 or height <= 0:
        raise ValueError("ROI rectangle width and height must be positive")
    return target, Roi(x, y, width, height)


def parse_roi_polygon_payload(payload: dict[str, Any]) -> tuple[str, list[tuple[float, float]], tuple[int, int]]:
    if not isinstance(payload, dict):
        raise ValueError("ROI polygon payload must be a JSON object")
    target = str(payload.get("target", "")).strip().lower()
    if target not in {"visible", "thermal"}:
        raise ValueError("ROI polygon target must be visible or thermal")
    try:
        frame_width = int(round(float(payload["frame_width"])))
        frame_height = int(round(float(payload["frame_height"])))
    except Exception as exc:  # noqa: BLE001 - normalized as ValueError for callers/tests.
        raise ValueError("ROI polygon payload must include numeric frame_width and frame_height") from exc
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("ROI polygon frame dimensions must be positive")
    if frame_width > 4096 or frame_height > 4096:
        raise ValueError("ROI polygon frame dimensions are too large")
    raw_points = payload.get("points")
    if not isinstance(raw_points, list) or len(raw_points) < 3:
        raise ValueError("ROI polygon payload must include at least three points")
    if len(raw_points) > 2000:
        raise ValueError("ROI polygon has too many points")
    points: list[tuple[float, float]] = []
    for item in raw_points:
        if not isinstance(item, dict):
            raise ValueError("ROI polygon points must be objects with x and y")
        try:
            x = float(item["x"])
            y = float(item["y"])
        except Exception as exc:  # noqa: BLE001 - normalized as ValueError for callers/tests.
            raise ValueError("ROI polygon points must include numeric x and y") from exc
        if not np.isfinite(x) or not np.isfinite(y):
            raise ValueError("ROI polygon point coordinates must be finite")
        if x < 0 or y < 0 or x > frame_width or y > frame_height:
            raise ValueError("ROI polygon point coordinates must be inside the frame")
        points.append((x, y))
    return target, points, (frame_height, frame_width)


def polygon_mask_from_points(points: list[tuple[float, float]] | tuple[tuple[float, float], ...], shape: tuple[int, int]) -> np.ndarray:
    """Rasterize a browser-drawn lasso polygon into a boolean mask."""

    h, w = _shape_hw(shape)
    if h <= 0 or w <= 0:
        raise ValueError("ROI polygon frame shape must be positive")
    if len(points) < 3:
        raise ValueError("ROI polygon must include at least three points")
    pts = [(float(x), float(y)) for x, y in points]
    min_x = max(0, int(np.floor(min(x for x, _ in pts))))
    max_x = min(w, int(np.ceil(max(x for x, _ in pts))))
    min_y = max(0, int(np.floor(min(y for _, y in pts))))
    max_y = min(h, int(np.ceil(max(y for _, y in pts))))
    if max_x <= min_x or max_y <= min_y:
        raise ValueError("ROI polygon did not enclose any pixels")
    grid_y, grid_x = np.mgrid[min_y:max_y, min_x:max_x]
    px = grid_x.astype(np.float64) + 0.5
    py = grid_y.astype(np.float64) + 0.5
    inside_crop = np.zeros((max_y - min_y, max_x - min_x), dtype=bool)
    for index, (x1, y1) in enumerate(pts):
        x2, y2 = pts[(index + 1) % len(pts)]
        if y1 == y2:
            continue
        crosses = ((y1 > py) != (y2 > py)) & (px < ((x2 - x1) * (py - y1) / (y2 - y1) + x1))
        inside_crop ^= crosses
    inside = np.zeros((h, w), dtype=bool)
    inside[min_y:max_y, min_x:max_x] = inside_crop
    if not bool(np.any(inside)):
        raise ValueError("ROI polygon did not enclose any pixels")
    return inside


def _repeat_mask_op(mask: np.ndarray, op: Callable[[np.ndarray], np.ndarray], iterations: int) -> np.ndarray:
    result = np.asarray(mask, dtype=bool)
    for _ in range(max(0, int(iterations))):
        result = op(result)
    return result


def _local_boundary_score(
    *,
    visible_frame: np.ndarray | None = None,
    thermal_matrix: np.ndarray | None = None,
) -> np.ndarray | None:
    if visible_frame is not None:
        frame = np.asarray(visible_frame)
        if frame.ndim != 3 or frame.shape[2] != 3:
            return None
        rgb = frame.astype(np.float64)
        gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
        chroma = np.max(rgb, axis=2) - np.min(rgb, axis=2)
        return gray + 0.6 * chroma
    if thermal_matrix is not None:
        matrix = np.asarray(thermal_matrix)
        if matrix.ndim != 2:
            return None
        return matrix.astype(np.float64)
    return None


def _refine_visible_lasso_by_rgb_hsv_context(
    initial_mask: np.ndarray,
    visible_frame: np.ndarray,
    *,
    search_px: int = 8,
) -> tuple[np.ndarray, str] | None:
    """Keep lasso pixels whose RGB/HSV color differs from the nearby background.

    This is a visible-camera fallback for transparent glass/liquid cases where
    a single grayscale/chroma edge score is too weak.  The lasso remains the
    hard search boundary: the algorithm estimates the local background from the
    ring just outside the lasso, then keeps only interior pixels whose RGB/HSV
    distance from that local background is large enough.
    """

    initial = np.asarray(initial_mask, dtype=bool)
    frame = np.asarray(visible_frame)
    if initial.ndim != 2 or frame.ndim != 3 or frame.shape[2] != 3 or frame.shape[:2] != initial.shape:
        return None
    if not bool(np.any(initial)):
        return None

    search_region = _repeat_mask_op(initial, _dilate_mask, max(1, int(search_px)))
    outside_ring = search_region & ~initial
    if not bool(np.any(outside_ring)):
        outside_ring = ~initial
    if not bool(np.any(outside_ring)):
        return None

    ys, xs = np.nonzero(search_region | initial)
    if ys.size == 0 or xs.size == 0:
        return None
    y0, y1 = max(0, int(ys.min()) - 2), min(initial.shape[0], int(ys.max()) + 3)
    x0, x1 = max(0, int(xs.min()) - 2), min(initial.shape[1], int(xs.max()) + 3)
    initial_crop = initial[y0:y1, x0:x1]
    outside_crop = outside_ring[y0:y1, x0:x1]
    if not bool(np.any(initial_crop)) or not bool(np.any(outside_crop)):
        return None

    frame_crop = frame[y0:y1, x0:x1].astype(np.float64)
    hsv_crop = rgb_to_hsv(frame[y0:y1, x0:x1])
    background_rgb = np.median(frame_crop[outside_crop], axis=0)
    background_hsv = np.median(hsv_crop[outside_crop], axis=0)

    rgb_delta = np.linalg.norm((frame_crop - background_rgb) / 255.0, axis=2) / np.sqrt(3.0)
    hue_delta = np.abs(((hsv_crop[..., 0] - background_hsv[0] + 180.0) % 360.0) - 180.0) / 180.0
    saturation_delta = np.abs(hsv_crop[..., 1] - background_hsv[1])
    value_delta = np.abs(hsv_crop[..., 2] - background_hsv[2])
    hsv_delta = np.sqrt((0.75 * hue_delta) ** 2 + saturation_delta**2 + (0.5 * value_delta) ** 2)
    color_distance = 0.58 * rgb_delta + 0.42 * hsv_delta

    outside_values = color_distance[outside_crop]
    inside_values = color_distance[initial_crop]
    if inside_values.size == 0 or outside_values.size == 0:
        return None
    threshold = max(
        float(np.percentile(outside_values, 95)) + 0.04,
        float(np.median(outside_values)) + max(0.08, float(np.std(outside_values)) * 3.0),
    )
    if float(np.percentile(inside_values, 90)) < threshold:
        return None

    candidate_crop = (color_distance >= threshold) & initial_crop
    initial_count = int(np.count_nonzero(initial))
    min_area = max(9, int(initial_count * 0.04))
    candidate_crop = smooth_mask_shape(candidate_crop)
    candidate_crop, component_count = keep_largest_mask_component(candidate_crop, min_area_px=min_area)
    candidate_count = int(np.count_nonzero(candidate_crop))
    if component_count < 1 or candidate_count < min_area:
        return None
    if candidate_count > int(initial_count * 1.15):
        return None

    candidate = np.zeros_like(initial, dtype=bool)
    candidate[y0:y1, x0:x1] = candidate_crop
    return candidate, "manual_lasso_color_refined"


def refine_lasso_mask_to_local_boundary(
    initial_mask: np.ndarray,
    *,
    visible_frame: np.ndarray | None = None,
    thermal_matrix: np.ndarray | None = None,
    search_px: int = 8,
) -> tuple[np.ndarray, str]:
    """Snap a manual lasso mask to a nearby color/brightness/thermal boundary.

    The refinement is deliberately local: it can only choose pixels in a small
    band around the drawn lasso and falls back to the original lasso when the
    frame has weak or ambiguous contrast. This keeps transparent glass/reflection
    cases from jumping to unrelated background edges.
    """

    initial = np.asarray(initial_mask, dtype=bool)
    if initial.ndim != 2 or not bool(np.any(initial)):
        return initial.copy(), "manual_lasso"

    def fallback_refinement() -> tuple[np.ndarray, str]:
        if visible_frame is not None:
            color_refined = _refine_visible_lasso_by_rgb_hsv_context(
                initial,
                visible_frame,
                search_px=search_px,
            )
            if color_refined is not None:
                return color_refined
        return smooth_mask_shape(initial), "manual_lasso"

    score = _local_boundary_score(visible_frame=visible_frame, thermal_matrix=thermal_matrix)
    if score is None or score.shape != initial.shape:
        return initial.copy(), "manual_lasso"

    initial_count = int(np.count_nonzero(initial))
    search_region = _repeat_mask_op(initial, _dilate_mask, max(1, int(search_px)))
    outside_ring = search_region & ~initial
    inside_values = score[initial]
    outside_values = score[outside_ring] if bool(np.any(outside_ring)) else score[~initial]
    if inside_values.size == 0 or outside_values.size == 0:
        return initial.copy(), "manual_lasso"
    baseline = float(np.median(outside_values))
    high = float(np.percentile(inside_values, 90))
    low = float(np.percentile(inside_values, 10))
    high_delta = abs(high - baseline)
    low_delta = abs(baseline - low)
    noise_floor = max(4.0, float(np.std(outside_values)) * 1.5)
    if max(high_delta, low_delta) < noise_floor:
        return fallback_refinement()

    if high_delta >= low_delta:
        threshold = (baseline + high) / 2.0
        candidate = score >= threshold if high >= baseline else score <= threshold
    else:
        threshold = (baseline + low) / 2.0
        candidate = score <= threshold if low <= baseline else score >= threshold
    candidate = np.asarray(candidate, dtype=bool) & search_region
    ys, xs = np.nonzero(search_region)
    if ys.size == 0 or xs.size == 0:
        return fallback_refinement()
    y0, y1 = max(0, int(ys.min()) - 2), min(initial.shape[0], int(ys.max()) + 3)
    x0, x1 = max(0, int(xs.min()) - 2), min(initial.shape[1], int(xs.max()) + 3)
    candidate_crop = smooth_mask_shape(candidate[y0:y1, x0:x1])
    min_area = max(9, int(initial_count * 0.04))
    candidate_crop, component_count = keep_largest_mask_component(candidate_crop, min_area_px=min_area)
    candidate = np.zeros_like(initial, dtype=bool)
    candidate[y0:y1, x0:x1] = candidate_crop
    candidate_count = int(np.count_nonzero(candidate))
    if component_count < 1 or candidate_count < min_area:
        return fallback_refinement()
    if candidate_count > int(initial_count * 1.4):
        return fallback_refinement()
    overlap = int(np.count_nonzero(candidate & search_region))
    if overlap < int(candidate_count * 0.95):
        return fallback_refinement()
    return candidate, "manual_lasso_edge_refined"


def apply_roi_click(
    state: RoiSelectionState,
    target: str,
    seed: tuple[int, int],
    *,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
) -> Roi:
    target = target.strip().lower()
    if target == "visible":
        if visible_frame is None:
            raise ValueError("visible ROI click received before a visible frame is available")
        result = detect_visible_mask_from_seed(visible_frame, seed)
        if result.roi is None:
            raise ValueError(result.reason)
        roi = result.roi
        state.update_visible(roi, seed=(int(seed[0]), int(seed[1])), frame_shape=visible_frame.shape[:2], mask=result.mask)
        return roi
    if target == "thermal":
        if thermal_matrix is None:
            raise ValueError("thermal ROI click received before a thermal matrix is available")
        result = detect_thermal_mask_from_seed(thermal_matrix, seed)
        if result.roi is None:
            raise ValueError(result.reason)
        roi = result.roi
        state.update_thermal(roi, seed=(int(seed[0]), int(seed[1])), frame_shape=thermal_matrix.shape[:2], mask=result.mask)
        return roi
    raise ValueError("ROI click target must be visible or thermal")


def map_visible_roi_to_thermal(
    state: RoiSelectionState,
    visible_roi: Roi,
    *,
    visible_shape: tuple[int, int],
    thermal_shape: tuple[int, int],
) -> Roi:
    """Map a visible ROI into Mini2 coordinates using clicked anchor delta."""

    visible_h, visible_w = _shape_hw(visible_shape)
    thermal_h, thermal_w = _shape_hw(thermal_shape)
    visible_anchor, thermal_anchor = state.snapshot_anchors()
    if visible_anchor is not None and thermal_anchor is not None:
        sx_scale = thermal_w / max(1, visible_w)
        sy_scale = thermal_h / max(1, visible_h)
        visible_center_x = visible_roi.x + visible_roi.width / 2.0
        visible_center_y = visible_roi.y + visible_roi.height / 2.0
        delta_x = (visible_center_x - visible_anchor.seed_xy[0]) * sx_scale
        delta_y = (visible_center_y - visible_anchor.seed_xy[1]) * sy_scale
        width_scale = thermal_anchor.roi.width / max(1, visible_anchor.roi.width)
        height_scale = thermal_anchor.roi.height / max(1, visible_anchor.roi.height)
        mapped_width = max(1, int(round(visible_roi.width * width_scale)))
        mapped_height = max(1, int(round(visible_roi.height * height_scale)))
        mapped_center_x = thermal_anchor.seed_xy[0] + delta_x
        mapped_center_y = thermal_anchor.seed_xy[1] + delta_y
        return clamp_roi_to_shape(
            Roi(
                int(round(mapped_center_x - mapped_width / 2.0)),
                int(round(mapped_center_y - mapped_height / 2.0)),
                mapped_width,
                mapped_height,
            ),
            (thermal_h, thermal_w),
        )

    x_scale = thermal_w / max(1, visible_w)
    y_scale = thermal_h / max(1, visible_h)
    return clamp_roi_to_shape(
        Roi(
            int(round(visible_roi.x * x_scale)),
            int(round(visible_roi.y * y_scale)),
            max(1, int(round(visible_roi.width * x_scale))),
            max(1, int(round(visible_roi.height * y_scale))),
        ),
        (thermal_h, thermal_w),
    )


def process_pending_roi_clicks(
    state: RoiSelectionState,
    *,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
    link_mode: str = "anchor",
) -> None:
    """Apply queued browser ROI clicks to the latest synchronized frames."""

    for target, x, y in state.pop_clicks():
        try:
            roi = apply_roi_click(
                state,
                target,
                (x, y),
                visible_frame=visible_frame,
                thermal_matrix=thermal_matrix,
            )
            if (
                target == "visible"
                and link_mode == "anchor"
                and thermal_matrix is not None
                and visible_frame is not None
                and state.snapshot_anchors()[1] is not None
            ):
                linked = map_visible_roi_to_thermal(
                    state,
                    roi,
                    visible_shape=visible_frame.shape[:2],
                    thermal_shape=thermal_matrix.shape[:2],
                )
                # Keep the original thermal seed anchor because it defines the
                # cross-sensor relationship; only move the active thermal ROI.
                state.update_auto(thermal_roi=linked, reason="linked_visible_click")
        except Exception as exc:  # noqa: BLE001 - defer error to live metadata instead of killing capture.
            state.set_error(str(exc))


def apply_auto_roi_detection_results(
    state: RoiSelectionState,
    *,
    visible_result: RoiDetectionResult | None,
    thermal_result: RoiDetectionResult | None,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
    min_confidence: float,
    allow_manual_lasso_overwrite: bool = False,
) -> bool:
    """Apply already-computed ROI candidates from the main loop only."""

    if not state.auto_updates_allowed():
        state.set_error("ignored auto ROI result while ROI is locked/recording")
        return False
    update_kwargs: dict[str, Any] = {}
    reasons: list[str] = []
    if visible_result is not None and visible_result.roi is not None and visible_result.confidence >= min_confidence:
        update_kwargs["visible_roi"] = visible_result.roi
        if visible_result.mask is not None:
            update_kwargs["visible_mask"] = visible_result.mask
        reasons.append(f"visible:{visible_result.reason}:{visible_result.confidence:.2f}")
    if thermal_result is not None and thermal_result.roi is not None and thermal_result.confidence >= min_confidence:
        update_kwargs["thermal_roi"] = thermal_result.roi
        if thermal_result.mask is not None:
            update_kwargs["thermal_mask"] = thermal_result.mask
        reasons.append(f"thermal:{thermal_result.reason}:{thermal_result.confidence:.2f}")
    if update_kwargs:
        return state.update_auto(
            **update_kwargs,
            reason="auto:" + ",".join(reasons),
            allow_manual_lasso_overwrite=allow_manual_lasso_overwrite,
        )
    if visible_result is not None or thermal_result is not None:
        state.reuse_last_good_masks()
    return False


def auto_roi_result_is_current(
    result: AutoRoiWorkerResult,
    current_settings: AutoRoiSettingsSnapshot,
    *,
    max_result_age_s: float = 2.0,
    roi_state: RoiSelectionState | None = None,
) -> tuple[bool, str]:
    """Return whether a worker result can be applied to current ROI settings."""

    if roi_state is not None and not roi_state.auto_updates_allowed():
        return False, "roi_locked_or_recording"
    if result.settings.key != current_settings.key:
        return False, "stale_auto_roi_settings"
    age_s = max(0.0, time.time() - result.completed_epoch_s)
    if age_s > max(0.0, float(max_result_age_s)):
        return False, "stale_auto_roi_age"
    if result.error:
        return False, f"auto_roi_error:{result.error}"
    return True, "current"


def apply_auto_roi_worker_result(
    state: RoiSelectionState,
    result: AutoRoiWorkerResult,
    *,
    current_settings: AutoRoiSettingsSnapshot,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
    max_result_age_s: float = 2.0,
) -> tuple[bool, str]:
    """Apply a current worker result, or return a discard reason."""

    current, reason = auto_roi_result_is_current(
        result,
        current_settings,
        max_result_age_s=max_result_age_s,
        roi_state=state,
    )
    if not current:
        return False, reason
    applied = apply_auto_roi_detection_results(
        state,
        visible_result=result.visible_result,
        thermal_result=result.thermal_result,
        visible_frame=visible_frame,
        thermal_matrix=thermal_matrix,
        min_confidence=current_settings.min_confidence,
    )
    return applied, "applied" if applied else "no_candidate"


def maybe_auto_update_rois(
    state: RoiSelectionState,
    *,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
    mode: str,
    min_confidence: float,
    link_mode: str = "anchor",
    visible_detector: str = "yolo",
    yolo_model: Any | None = None,
    yolo_classes: set[str] | list[str] | tuple[str, ...] | str | None = None,
    yolo_min_confidence: float = 0.25,
    yolo_max_area_fraction: float = 0.45,
    visible_result_override: RoiDetectionResult | None = None,
    thermal_result_override: RoiDetectionResult | None = None,
) -> None:
    mode = str(mode or "off").strip().lower()
    if mode == "off":
        return
    visible_result = None
    thermal_result = None
    if mode in {"visible", "both"} and visible_frame is not None:
        if visible_result_override is not None:
            visible_result = visible_result_override
        else:
            detector = str(visible_detector or "yolo").strip().lower()
            if detector != "yolo":
                visible_result = RoiDetectionResult(None, 0.0, "visible_detector_not_supported:yolo_only")
            elif yolo_model is None:
                visible_result = RoiDetectionResult(None, 0.0, "yolo_model_unavailable")
            else:
                visible_result = auto_detect_visible_roi_yolo(
                    visible_frame,
                    yolo_model,
                    allowed_classes=yolo_classes,
                    min_confidence=float(yolo_min_confidence),
                    max_area_fraction=float(yolo_max_area_fraction),
                )
    elif mode in {"visible", "both"} and visible_result_override is not None:
        visible_result = visible_result_override
    if thermal_result_override is not None:
        thermal_result = thermal_result_override
    elif mode in {"thermal", "both"} and thermal_matrix is not None:
        thermal_result = auto_detect_thermal_roi(thermal_matrix)
    apply_auto_roi_detection_results(
        state,
        visible_result=visible_result,
        thermal_result=thermal_result,
        visible_frame=visible_frame,
        thermal_matrix=thermal_matrix,
        min_confidence=min_confidence,
    )


def apply_setup_auto_candidate_rois(
    state: RoiSelectionState,
    *,
    visible_frame: np.ndarray | None,
    thermal_matrix: np.ndarray | None,
    min_confidence: float,
    visible_detector: str = "yolo",
    yolo_model: Any | None = None,
    yolo_classes: set[str] | list[str] | tuple[str, ...] | str | None = None,
    yolo_min_confidence: float = 0.25,
    yolo_max_area_fraction: float = 0.45,
) -> bool:
    """Apply a user-requested setup candidate using YOLO-visible and thermal candidates."""

    visible_result = None
    thermal_result = None
    if visible_frame is not None:
        visible_result = auto_detect_visible_roi_setup_candidate(
            visible_frame,
            visible_detector=visible_detector,
            yolo_model=yolo_model,
            yolo_classes=yolo_classes,
            min_confidence=min_confidence,
            yolo_min_confidence=yolo_min_confidence,
            yolo_max_area_fraction=yolo_max_area_fraction,
        )
    if thermal_matrix is not None:
        thermal_result = auto_detect_thermal_roi(thermal_matrix)
    return apply_auto_roi_detection_results(
        state,
        visible_result=visible_result,
        thermal_result=thermal_result,
        visible_frame=visible_frame,
        thermal_matrix=thermal_matrix,
        min_confidence=min_confidence,
        allow_manual_lasso_overwrite=True,
    )


def validate_matrix_roi(matrix: np.ndarray, roi: Roi) -> None:
    if matrix.ndim != 2:
        raise ValueError("temperature/raw matrix must be 2D")
    h, w = matrix.shape
    if roi.width <= 0 or roi.height <= 0:
        raise ValueError("ROI width and height must be positive")
    if roi.x < 0 or roi.y < 0 or roi.x + roi.width > w or roi.y + roi.height > h:
        raise ValueError("ROI must be fully inside the matrix")


@lru_cache(maxsize=64)
def _cached_rect_coords_yx(x: int, y: int, width: int, height: int) -> np.ndarray:
    yy, xx = np.indices((height, width), dtype=np.int64)
    yy += int(y)
    xx += int(x)
    coords = np.column_stack([yy.ravel(), xx.ravel()])
    coords.setflags(write=False)
    return coords


def _rect_coords_yx(roi: Roi) -> np.ndarray:
    """Return immutable cached coordinates for a normally fixed experiment ROI."""

    return _cached_rect_coords_yx(int(roi.x), int(roi.y), int(roi.width), int(roi.height))


def _distribution_features(
    prefix: str,
    values: np.ndarray,
    *,
    coords_yx: np.ndarray | None = None,
    include_moments: bool = False,
    mean_suffix: str = "avg",
) -> dict[str, object]:
    arr = np.asarray(values, dtype=np.float64).reshape(-1)
    if arr.size == 0:
        return {}
    p05, p25, p50, p75, p95 = np.percentile(arr, [5, 25, 50, 75, 95])
    avg = float(np.mean(arr))
    std = float(np.std(arr))
    min_index = int(np.argmin(arr))
    max_index = int(np.argmax(arr))
    min_value = float(arr[min_index])
    max_value = float(arr[max_index])
    features: dict[str, object] = {
        f"{prefix}_range": round(max_value - min_value, 6),
        f"{prefix}_iqr": round(float(p75 - p25), 6),
        f"{prefix}_p05": round(float(p05), 6),
        f"{prefix}_p25": round(float(p25), 6),
        f"{prefix}_p50": round(float(p50), 6),
        f"{prefix}_p75": round(float(p75), 6),
        f"{prefix}_p95": round(float(p95), 6),
        f"{prefix}_hot_fraction": 0.0 if std == 0.0 else round(float(np.mean(arr > avg + std)), 6),
        f"{prefix}_cold_fraction": 0.0 if std == 0.0 else round(float(np.mean(arr < avg - std)), 6),
    }
    if include_moments:
        features.update(
            {
                f"{prefix}_{mean_suffix}": round(avg, 6),
                f"{prefix}_min": round(min_value, 6),
                f"{prefix}_max": round(max_value, 6),
                f"{prefix}_std": round(std, 12 if prefix == "thermal_roi" else 6),
            }
        )
    if coords_yx is not None:
        coords = np.asarray(coords_yx, dtype=np.int64).reshape(-1, 2)
        if coords.shape[0] == arr.size:
            min_y, min_x = coords[min_index]
            max_y, max_x = coords[max_index]
            features.update(
                {
                    f"{prefix}_min_x": int(min_x),
                    f"{prefix}_min_y": int(min_y),
                    f"{prefix}_max_x": int(max_x),
                    f"{prefix}_max_y": int(max_y),
                }
            )
    return features


THERMAL_CONVERSION_OK = "ok"
THERMAL_CONVERSION_SUSPECT_ALL_ZERO = "suspect_all_zero"
THERMAL_CONVERSION_NON_FINITE = "non_finite"
THERMAL_CONVERSION_EMPTY = "empty"
THERMAL_CONVERSION_RAW = "raw"
THERMAL_CONVERSION_CONVERTER_UNAVAILABLE = "converter_unavailable"
THERMAL_CONVERSION_CONVERTER_ERROR = "converter_error"
THERMAL_CONVERSION_MINI2_UNAVAILABLE = "mini2_unavailable"

THERMAL_CONVERSION_FALLBACK_MESSAGES = {
    THERMAL_CONVERSION_SUSPECT_ALL_ZERO: "official Celsius converter returned suspect all-zero output; using raw preview only",
    THERMAL_CONVERSION_NON_FINITE: "official Celsius converter returned non-finite output; using raw preview only",
    THERMAL_CONVERSION_EMPTY: "official Celsius converter returned empty output; using raw preview only",
}


def _official_celsius_output_status(values: np.ndarray, raw_values: np.ndarray) -> str:
    celsius = np.asarray(values, dtype=np.float64).reshape(-1)
    if celsius.size == 0:
        return THERMAL_CONVERSION_EMPTY
    if not bool(np.all(np.isfinite(celsius))):
        return THERMAL_CONVERSION_NON_FINITE
    raw = np.asarray(raw_values)
    raw_has_signal = raw.size > 0 and float(np.nanmean(np.abs(raw.astype(np.float64, copy=False)))) > 1.0
    if raw_has_signal and bool(np.all(np.abs(celsius) <= 1e-9)):
        return THERMAL_CONVERSION_SUSPECT_ALL_ZERO
    return THERMAL_CONVERSION_OK


def _add_celsius_fallback_warning(features: dict[str, object], converter: Any, status: str) -> dict[str, object]:
    message = THERMAL_CONVERSION_FALLBACK_MESSAGES.get(status, f"official Celsius converter failed with status={status}; using raw preview only")
    features["warnings"] = message
    features["thermal_conversion_status"] = status
    features["thermal_celsius_fallback_reason"] = message
    features["thermal_conversion_model"] = str(getattr(converter, "model_name", "unknown"))
    features["thermal_conversion_calibration_source"] = str(getattr(converter, "calibration_source", "unknown"))
    return features


def _add_converter_exception_warning(features: dict[str, object], converter: Any, exc: BaseException) -> dict[str, object]:
    message = f"official Celsius converter raised {type(exc).__name__}: {exc}; using raw preview only"
    features["warnings"] = message
    features["thermal_conversion_status"] = THERMAL_CONVERSION_CONVERTER_ERROR
    features["thermal_celsius_fallback_reason"] = message
    features["thermal_conversion_model"] = str(getattr(converter, "model_name", "unknown"))
    features["thermal_conversion_calibration_source"] = str(getattr(converter, "calibration_source", "unknown"))
    return features


def extract_roi_only_thermal_features(
    *,
    raw_matrix: np.ndarray,
    addline_tag1: bytes,
    converter: Any,
    roi: Roi,
    previous: dict[str, object] | None,
    frame_rate_hz: float,
) -> dict[str, object]:
    """Compute official Celsius ROI features without full-frame conversion."""

    validate_matrix_roi(raw_matrix, roi)
    raw_roi = raw_matrix[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
    roi_coords_yx = _rect_coords_yx(roi)
    convert_values = getattr(converter, "convert_values_with_addline", None)
    try:
        if not callable(convert_values):
            full = converter.convert_with_addline(raw_matrix, addline_tag1)
            roi_c = full[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
        else:
            roi_c = convert_values(raw_roi, addline_tag1)
    except Exception as exc:  # noqa: BLE001 - keep live collector running with explicit raw fallback evidence.
        return _add_converter_exception_warning(
            extract_raw_thermal_features(
                raw_matrix=raw_matrix,
                roi=roi,
                previous=previous,
                frame_rate_hz=frame_rate_hz,
            ),
            converter,
            exc,
        )
    conversion_status = _official_celsius_output_status(roi_c, raw_roi)
    if conversion_status != THERMAL_CONVERSION_OK:
        return _add_celsius_fallback_warning(
            extract_raw_thermal_features(
                raw_matrix=raw_matrix,
                roi=roi,
                previous=previous,
                frame_rate_hz=frame_rate_hz,
            ),
            converter,
            conversion_status,
        )
    roi_features = _distribution_features(
        "thermal_roi",
        roi_c,
        coords_yx=roi_coords_yx,
        include_moments=True,
    )
    raw_roi_features = _distribution_features(
        "thermal_raw_roi",
        raw_roi,
        coords_yx=roi_coords_yx,
        include_moments=True,
    )
    raw_features = _distribution_features(
        "thermal_raw",
        raw_matrix,
        include_moments=True,
        mean_suffix="mean",
    )
    for key in ("thermal_raw_roi_min", "thermal_raw_roi_max"):
        raw_roi_features[key] = int(raw_roi_features[key])
    for key in ("thermal_raw_min", "thermal_raw_max"):
        raw_features[key] = int(raw_features[key])
    roi_avg = float(roi_features["thermal_roi_avg"])
    prev_avg_raw = None if previous is None else previous.get("thermal_roi_avg")
    try:
        prev_avg = None if prev_avg_raw is None else float(prev_avg_raw)
    except (TypeError, ValueError):
        prev_avg = None
    features: dict[str, object] = {
        "thermal_source": "mini2_uvc_raw_official_roi_celsius",
        "thermal_calibrated": True,
        "source_quality": "mini2_uvc_raw_calibrated_roi_temperature",
        "thermal_conversion_model": str(getattr(converter, "model_name", "unknown")),
        "thermal_conversion_calibration_source": str(getattr(converter, "calibration_source", "unknown")),
        "thermal_conversion_status": THERMAL_CONVERSION_OK,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": f"roi-only:{raw_matrix.shape[0]}x{raw_matrix.shape[1]}",
        "thermal_roi_avg": roi_avg,
        "thermal_roi_delta": 0.0 if prev_avg is None else round(roi_avg - prev_avg, 6),
    }
    features.update(roi_features)
    features.update(raw_roi_features)
    features.update(raw_features)
    return features


def _mask_metadata(prefix: str, roi_mask: RoiMask) -> dict[str, object]:
    cx, cy = roi_mask.centroid_xy
    return {
        f"{prefix}_roi_shape": roi_mask.shape,
        f"{prefix}_mask_area_px": roi_mask.area_px,
        f"{prefix}_mask_confidence": roi_mask.confidence,
        f"{prefix}_mask_centroid_x": round(cx, 6),
        f"{prefix}_mask_centroid_y": round(cy, 6),
        f"{prefix}_mask_bbox": roi_mask.bbox_string,
        f"{prefix}_mask_source": roi_mask.source,
        f"{prefix}_mask_component_count": roi_mask.component_count,
        f"{prefix}_mask_stability": roi_mask.stability,
    }


def extract_mask_color_features(
    frame_rgb: np.ndarray,
    roi_mask: RoiMask,
    previous: dict[str, float] | None = None,
) -> dict[str, float]:
    arr = np.asarray(frame_rgb)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("visible frame must have shape HxWx3")
    if roi_mask.mask.shape != arr.shape[:2]:
        raise ValueError("visible mask shape must match visible frame shape")
    selected = arr[roi_mask.mask]
    if selected.size == 0:
        raise ValueError("visible mask contains no selected pixels")
    rgb_mean = selected.astype(np.float64).mean(axis=0)
    hsv_mean = rgb_to_hsv(selected.reshape(-1, 1, 3)).reshape(-1, 3).mean(axis=0)
    features: dict[str, float] = {
        "R_mean": round(float(rgb_mean[0]), 6),
        "G_mean": round(float(rgb_mean[1]), 6),
        "B_mean": round(float(rgb_mean[2]), 6),
        "H_mean": round(float(hsv_mean[0]), 6),
        "S_mean": round(float(hsv_mean[1]), 6),
        "V_mean": round(float(hsv_mean[2]), 6),
    }
    features["color_delta"] = round(ColorFeatureExtractor._color_delta(features, previous), 6)
    features.update(ColorFeatureExtractor._hsv_delta(features, previous))
    cx, cy = roi_mask.centroid_xy
    features.update(
        {
            "roi_shape": roi_mask.shape,
            "mask_area_px": roi_mask.area_px,
            "mask_confidence": roi_mask.confidence,
            "mask_centroid_x": round(cx, 6),
            "mask_centroid_y": round(cy, 6),
            "mask_bbox": roi_mask.bbox_string,
            "mask_source": roi_mask.source,
            "mask_component_count": roi_mask.component_count,
            "mask_stability": roi_mask.stability,
        }
    )
    return features


def extract_roi_mask_thermal_features(
    *,
    raw_matrix: np.ndarray,
    addline_tag1: bytes,
    converter: Any,
    roi_mask: RoiMask,
    previous: dict[str, object] | None,
    frame_rate_hz: float,
) -> dict[str, object]:
    matrix = np.asarray(raw_matrix)
    if roi_mask.mask.shape != matrix.shape[:2]:
        raise ValueError("thermal mask shape must match raw matrix shape")
    raw_roi = matrix[roi_mask.bbox.y : roi_mask.bbox.y + roi_mask.bbox.height, roi_mask.bbox.x : roi_mask.bbox.x + roi_mask.bbox.width]
    mask_roi = roi_mask.mask[
        roi_mask.bbox.y : roi_mask.bbox.y + roi_mask.bbox.height,
        roi_mask.bbox.x : roi_mask.bbox.x + roi_mask.bbox.width,
    ]
    convert_values = getattr(converter, "convert_values_with_addline", None)
    try:
        if callable(convert_values):
            roi_c_full = convert_values(raw_roi, addline_tag1)
            values = roi_c_full[mask_roi]
        else:
            full = converter.convert_with_addline(matrix, addline_tag1)
            values = full[roi_mask.mask]
    except Exception as exc:  # noqa: BLE001 - keep live collector running with explicit raw fallback evidence.
        return _add_converter_exception_warning(
            extract_raw_mask_thermal_features(
                raw_matrix=raw_matrix,
                roi_mask=roi_mask,
                previous=previous,
                frame_rate_hz=frame_rate_hz,
            ),
            converter,
            exc,
        )
    coords_yx = np.argwhere(roi_mask.mask)
    raw_values = matrix[roi_mask.mask]
    conversion_status = _official_celsius_output_status(values, raw_values)
    if conversion_status != THERMAL_CONVERSION_OK:
        return _add_celsius_fallback_warning(
            extract_raw_mask_thermal_features(
                raw_matrix=raw_matrix,
                roi_mask=roi_mask,
                previous=previous,
                frame_rate_hz=frame_rate_hz,
            ),
            converter,
            conversion_status,
        )
    roi_avg = round(float(np.mean(values)), 6)
    prev_avg_raw = None if previous is None else previous.get("thermal_roi_avg")
    try:
        prev_avg = None if prev_avg_raw is None else float(prev_avg_raw)
    except (TypeError, ValueError):
        prev_avg = None
    features = {
        "thermal_source": "mini2_uvc_raw_official_mask_celsius",
        "thermal_calibrated": True,
        "source_quality": "mini2_uvc_raw_calibrated_mask_temperature",
        "thermal_conversion_model": str(getattr(converter, "model_name", "unknown")),
        "thermal_conversion_calibration_source": str(getattr(converter, "calibration_source", "unknown")),
        "thermal_conversion_status": THERMAL_CONVERSION_OK,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": f"mask:{matrix.shape[0]}x{matrix.shape[1]}",
        "thermal_roi_avg": roi_avg,
        "thermal_roi_max": round(float(np.max(values)), 6),
        "thermal_roi_min": round(float(np.min(values)), 6),
        "thermal_roi_std": round(float(np.std(values)), 12),
        "thermal_roi_delta": 0.0 if prev_avg is None else round(roi_avg - prev_avg, 6),
        "thermal_raw_min": int(np.min(matrix)),
        "thermal_raw_max": int(np.max(matrix)),
        "thermal_raw_mean": round(float(np.mean(matrix)), 6),
        "thermal_raw_std": round(float(np.std(matrix)), 6),
    }
    features.update(_distribution_features("thermal_roi", values, coords_yx=coords_yx))
    features.update(_distribution_features("thermal_raw_roi", raw_values, coords_yx=coords_yx))
    features.update(_distribution_features("thermal_raw", matrix))
    features.update(_mask_metadata("thermal", roi_mask))
    return features


def extract_raw_thermal_features(
    *,
    raw_matrix: np.ndarray,
    roi: Roi,
    previous: dict[str, object] | None,
    frame_rate_hz: float,
) -> dict[str, object]:
    """Compute Mini2 raw-value ROI features without Celsius conversion."""

    validate_matrix_roi(raw_matrix, roi)
    raw_roi = raw_matrix[roi.y : roi.y + roi.height, roi.x : roi.x + roi.width]
    roi_coords_yx = _rect_coords_yx(roi)
    raw_roi_features = _distribution_features(
        "thermal_raw_roi",
        raw_roi,
        coords_yx=roi_coords_yx,
        include_moments=True,
    )
    raw_features = _distribution_features(
        "thermal_raw",
        raw_matrix,
        include_moments=True,
        mean_suffix="mean",
    )
    for key in ("thermal_raw_roi_min", "thermal_raw_roi_max"):
        raw_roi_features[key] = int(raw_roi_features[key])
    for key in ("thermal_raw_min", "thermal_raw_max"):
        raw_features[key] = int(raw_features[key])
    raw_avg = float(raw_roi_features["thermal_raw_roi_avg"])
    prev_avg_raw = None if previous is None else previous.get("thermal_raw_roi_avg")
    try:
        prev_avg = None if prev_avg_raw in (None, "") else float(prev_avg_raw)
    except (TypeError, ValueError):
        prev_avg = None
    raw_delta = 0.0 if prev_avg is None else round(raw_avg - prev_avg, 6)
    features: dict[str, object] = {
        "thermal_source": "mini2_uvc_raw_uncalibrated_preview",
        "thermal_calibrated": False,
        "source_quality": "mini2_uvc_raw_uncalibrated_preview",
        "thermal_conversion_status": THERMAL_CONVERSION_RAW,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": f"{raw_matrix.shape[0]}x{raw_matrix.shape[1]}",
        "thermal_raw_roi_avg": raw_avg,
        "thermal_raw_roi_delta": raw_delta,
        "thermal_delta": raw_delta,
    }
    features.update(raw_roi_features)
    features.update(raw_features)
    return features


def extract_raw_mask_thermal_features(
    *,
    raw_matrix: np.ndarray,
    roi_mask: RoiMask,
    previous: dict[str, object] | None,
    frame_rate_hz: float,
) -> dict[str, object]:
    matrix = np.asarray(raw_matrix)
    if matrix.ndim != 2:
        raise ValueError("raw matrix must be 2D")
    if roi_mask.mask.shape != matrix.shape:
        raise ValueError("thermal mask shape must match raw matrix shape")
    values = matrix[roi_mask.mask].astype(np.float64)
    if values.size == 0:
        raise ValueError("thermal mask contains no selected pixels")
    raw_avg = round(float(np.mean(values)), 6)
    prev_avg_raw = None if previous is None else previous.get("thermal_raw_roi_avg")
    try:
        prev_avg = None if prev_avg_raw in (None, "") else float(prev_avg_raw)
    except (TypeError, ValueError):
        prev_avg = None
    raw_delta = 0.0 if prev_avg is None else round(raw_avg - prev_avg, 6)
    features: dict[str, object] = {
        "thermal_source": "mini2_uvc_raw_uncalibrated_mask_preview",
        "thermal_calibrated": False,
        "source_quality": "mini2_uvc_raw_uncalibrated_mask_preview",
        "thermal_conversion_status": THERMAL_CONVERSION_RAW,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": f"mask:{matrix.shape[0]}x{matrix.shape[1]}",
        "thermal_raw_roi_avg": raw_avg,
        "thermal_raw_roi_max": int(np.max(values)),
        "thermal_raw_roi_min": int(np.min(values)),
        "thermal_raw_roi_std": round(float(np.std(values)), 6),
        "thermal_raw_roi_delta": raw_delta,
        "thermal_delta": raw_delta,
        "thermal_raw_min": int(np.min(matrix)),
        "thermal_raw_max": int(np.max(matrix)),
        "thermal_raw_mean": round(float(np.mean(matrix)), 6),
        "thermal_raw_std": round(float(np.std(matrix)), 6),
    }
    features.update(_distribution_features("thermal_raw_roi", values, coords_yx=np.argwhere(roi_mask.mask)))
    features.update(_distribution_features("thermal_raw", matrix))
    features.update(_mask_metadata("thermal", roi_mask))
    return features


def default_dll_dir() -> str:
    repo_vendor = ROOT / "vendor" / "hikmicro_analyzer"
    if (repo_vendor / "MTlib_OL.dll").exists():
        return str(repo_vendor)
    return str(DLL_DIR_DEFAULT)


def default_metadata_jpeg() -> str:
    return str(ROOT / "data" / "fixtures" / "mini2" / "IR_00001.jpeg")


def build_official_converter(args: argparse.Namespace):
    return load_raw_to_celsius_converter(
        {
            "type": "official_mtlib",
            "metadata_jpeg": args.metadata_jpeg,
            "dll_dir": args.dll_dir,
            "batch_size": 1,
        }
    )


def orient_thermal_matrix(raw_matrix: np.ndarray, rotation_degrees: int) -> np.ndarray:
    """Return the Mini2 matrix in the user-facing thermal-camera orientation."""

    try:
        degrees = int(rotation_degrees)
    except (TypeError, ValueError) as exc:
        raise ValueError("thermal_rotation_degrees must be 0 or 180") from exc
    matrix = np.asarray(raw_matrix)
    if degrees == 0:
        return matrix
    if degrees == 180:
        return matrix[::-1, ::-1]
    raise ValueError("thermal_rotation_degrees must be 0 or 180")


def orient_mini2_frame_parts(parts: Any, rotation_degrees: int) -> Any:
    """Orient Mini2 frame parts while preserving per-frame addline metadata."""

    oriented_matrix = orient_thermal_matrix(parts.raw_matrix, rotation_degrees)
    if oriented_matrix is parts.raw_matrix:
        return parts
    return replace(parts, raw_matrix=oriented_matrix)


def unavailable_thermal_features(reason: str, *, frame_rate_hz: float) -> dict[str, object]:
    return {
        "thermal_source": "mini2_unavailable",
        "thermal_calibrated": False,
        "source_quality": "mini2_unavailable",
        "thermal_conversion_status": THERMAL_CONVERSION_MINI2_UNAVAILABLE,
        "thermal_frame_rate_hz": float(frame_rate_hz),
        "thermal_matrix_shape": "",
        "thermal_delta": 0.0,
        "thermal_roi_delta": 0.0,
        "warnings": reason,
    }


def build_sync_metadata(
    *,
    thermal_time_s: float | None,
    visible_time_s: float | None,
    max_sync_offset_ms: float,
) -> dict[str, object]:
    if thermal_time_s is None:
        return {
            "thermal_time_s": "",
            "visible_time_s": "" if visible_time_s is None else round(float(visible_time_s), 6),
            "sync_offset_ms": "",
            "sync_method": "visible_only_no_thermal",
            "sync_quality": "missing",
            "sync_warning": "Mini2 frame unavailable",
        }
    if visible_time_s is None:
        return {
            "thermal_time_s": round(float(thermal_time_s), 6),
            "visible_time_s": "",
            "sync_offset_ms": "",
            "sync_method": "nearest_visible_frame",
            "sync_quality": "missing",
            "sync_warning": "visible frame unavailable",
        }
    offset_ms = (float(visible_time_s) - float(thermal_time_s)) * 1000.0
    warning = "" if abs(offset_ms) <= max_sync_offset_ms else f"sync offset exceeds {max_sync_offset_ms:g} ms"
    return {
        "thermal_time_s": round(float(thermal_time_s), 6),
        "visible_time_s": round(float(visible_time_s), 6),
        "sync_offset_ms": round(offset_ms, 6),
        "sync_method": "nearest_visible_frame",
        "sync_quality": "good" if not warning else "warning",
        "sync_warning": warning,
    }


def summarize_sync(rows: list[dict[str, Any]]) -> dict[str, object]:
    offsets: list[float] = []
    warning_rows = 0
    missing_rows = 0
    for row in rows:
        if row.get("sync_quality") == "warning":
            warning_rows += 1
        if row.get("sync_quality") == "missing":
            missing_rows += 1
        value = row.get("sync_offset_ms")
        if value not in ("", None):
            offsets.append(abs(float(value)))
    return {
        "sync_method": "nearest_visible_frame",
        "sync_offset_abs_mean_ms": round(sum(offsets) / len(offsets), 6) if offsets else None,
        "sync_offset_abs_max_ms": round(max(offsets), 6) if offsets else None,
        "sync_warning_rows": warning_rows,
        "sync_missing_rows": missing_rows,
    }



def load_live_prediction_model(path: Any) -> dict[str, Any] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        model = load_optional_model(raw)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Warning: live ML model unavailable; using peak fallback. Reason: {exc}", flush=True)
        return None
    if model is None:
        return None
    feature_columns = {str(column) for column in model.get("feature_columns", [])}
    offenders = sorted(feature_columns & LIVE_ML_FORBIDDEN_FEATURE_COLUMNS)
    if offenders:
        print(
            "Warning: live ML model rejected because it uses label/theory leakage columns; "
            f"using typewise/peak fallback. Columns: {', '.join(offenders[:12])}",
            flush=True,
        )
        return None
    return model


def load_typewise_live_prediction_model(path: Any) -> dict[str, Any] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return load_typewise_model(raw)
    except (OSError, ValueError, AttributeError, pickle.UnpicklingError, ImportError) as exc:
        print(f"Warning: typewise live ML model unavailable; using regression/peak fallback. Reason: {exc}", flush=True)
        return None


def load_endpoint_prediction_model(path: Any) -> dict[str, Any] | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    try:
        return load_type_conditioned_sensor_model(raw)
    except (OSError, ValueError, AttributeError, pickle.UnpicklingError, ImportError) as exc:
        print(
            "Warning: post-run sensor endpoint model unavailable; "
            f"using live classifier fallback. Reason: {exc}",
            flush=True,
        )
        return None


def finish_live_automatic_stop(
    *,
    server: Any,
    csv_buffer: LiveCsvBuffer,
    roi_state: RoiSelectionState,
    auto_stop_controller: ColorChangeAutoStopController | None,
    endpoint_pulse_runtime: EndpointPulseRuntime | None,
    session_id: int,
    status: Mapping[str, Any],
    guard_reason: str,
) -> None:
    """Fail closed for one live session without touching a newer session.

    The stop-intent token is acquired before the first session read.  Once a
    callback can observe its session as current, no new recording/pump start
    can pass the intent gate until that callback stops the session or proves it
    stale.  A callback that resumes after a newer session has started exits
    before touching the pump guard.
    """

    stop_intent: StopIntentCoordinator = getattr(server, "csv_stop_intent")
    stop_token = stop_intent.begin(guard_reason)
    latched_session = False
    try:
        current = csv_buffer.status()
        if (
            not current.get("recording")
            or int(current.get("session_id") or 0) != int(session_id)
        ):
            # Do not write an old callback's status into a newer active run.
            if not current.get("recording"):
                csv_buffer.update_auto_stop_status(
                    {**status, "auto_stop_action_status": "ignored_stale_session"}
                )
            return

        stop_intent.latch_session(session_id)
        latched_session = True

        emergency_sender = getattr(server, "pump_emergency_stop_sender", None)
        pump_stop_status = "disabled"
        pump_stop_error = ""
        absolute_guard = getattr(server, "absolute_pump_safety_guard", None)
        if isinstance(absolute_guard, AbsolutePumpSafetyGuard):

            def emergency_stop() -> None:
                if callable(emergency_sender):
                    emergency_sender()

            guard_status = absolute_guard.stop(
                guard_reason,
                emergency_stop=emergency_stop,
            )
            pump_stop_status = str(
                guard_status.get("absolute_guard_stop_status") or "failed"
            )
            pump_stop_error = str(guard_status.get("absolute_guard_error") or "")
        elif callable(emergency_sender):
            try:
                emergency_sender()
                pump_stop_status = "sent"
            except Exception as exc:  # noqa: BLE001 - record the stop failure.
                pump_stop_status = "failed"
                pump_stop_error = str(exc)

        control_lock = getattr(server, "csv_control_lock")
        with control_lock:
            current = csv_buffer.status()
            if (
                not current.get("recording")
                or int(current.get("session_id") or 0) != int(session_id)
            ):
                if not current.get("recording"):
                    csv_buffer.update_auto_stop_status(
                        {**status, "auto_stop_action_status": "ignored_stale_session"}
                    )
                if latched_session and not current.get("finalizing"):
                    stop_intent.clear_latch(session_id)
                return
            csv_buffer.update_auto_stop_status(dict(status))
            if endpoint_pulse_runtime is not None:
                endpoint_pulse_runtime.disarm(guard_reason)
            if auto_stop_controller is not None:
                auto_stop_controller.disarm(guard_reason)
            csv_buffer.pause_commanded_pump_timeline(state="stopped")
            capture_controller = getattr(server, "capture_controller", None)
            if isinstance(capture_controller, Mini2CaptureThread):
                capture_status = capture_controller.end_recording(int(session_id))
                csv_buffer.request_stop()
                if bool(capture_status.get("drained")):
                    csv_buffer.complete_stop()
            else:
                csv_buffer.stop_recording()
            final_csv_status = csv_buffer.status()
            if (
                not final_csv_status.get("recording")
                and not final_csv_status.get("finalizing")
            ):
                stop_intent.clear_latch(session_id)
            roi_state.stop_recording()
            csv_buffer.update_auto_stop_status(
                {
                    "auto_stop_action_status": "completed"
                    if pump_stop_status == "sent"
                    else "pump_stop_failed",
                    "auto_stop_pump_command": "c",
                    "auto_stop_pump_status": pump_stop_status,
                    "auto_stop_pump_error": pump_stop_error,
                }
            )
    finally:
        stop_intent.finish(stop_token)


def run(args: argparse.Namespace, *, mini2_reader: Mini2PartsReader | None = None, visible_camera: Any | None = None) -> Path:
    converter = None
    injected_mini2 = mini2_reader is not None
    injected_visible = visible_camera is not None
    mini2_requested_index = getattr(args, "mini2_index", "auto")
    mini2_requested_backend = getattr(args, "mini2_backend", "AUTO")
    allow_mini2_missing = bool(int(getattr(args, "allow_mini2_missing", 1)))
    resolved_mini2_index = args.mini2_index
    resolved_visible_index = None if args.no_visible else args.visible_index
    mini2_unavailable_reason = ""
    converter_unavailable_reason = ""
    if mini2_reader is None:
        try:
            mini2_reader, resolved_mini2_index = open_mini2_capture(args)
            args.mini2_index = resolved_mini2_index
        except Exception as exc:  # noqa: BLE001 - keep the dashboard usable when Mini2 is unplugged/busy.
            if not allow_mini2_missing:
                raise
            mini2_unavailable_reason = str(exc)
            resolved_mini2_index = ""
            print(
                "Warning: Mini2 raw stream unavailable; continuing visible/status-only. "
                f"Reason: {mini2_unavailable_reason}",
                flush=True,
            )
    if mini2_reader is not None and args.thermal_processing != "raw":
        try:
            converter = build_official_converter(args)
        except Exception as exc:  # noqa: BLE001 - keep the live demo visible; never fake Celsius without the converter.
            converter_unavailable_reason = str(exc)
            args.thermal_processing = "raw"
            print(
                "Warning: official Mini2 Celsius converter unavailable; "
                "continuing raw thermal preview only. "
                f"Reason: {converter_unavailable_reason}",
                flush=True,
            )
    if visible_camera is None and not args.no_visible:
        skip_indices = {resolved_mini2_index} if isinstance(resolved_mini2_index, int) else set()
        visible_camera, resolved_visible_index = open_visible_camera(
            args,
            skip_indices=skip_indices,
        )
        args.visible_index = "" if resolved_visible_index is None else resolved_visible_index

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    endpoint_prediction_model = load_endpoint_prediction_model(
        getattr(args, "endpoint_ml_model", DEFAULT_ENDPOINT_ML_MODEL)
    )
    typewise_prediction_model = load_typewise_live_prediction_model(
        getattr(args, "typewise_ml_model", DEFAULT_TYPEWISE_LIVE_ML_MODEL)
    )
    prediction_model = load_live_prediction_model(getattr(args, "ml_model", DEFAULT_LIVE_ML_MODEL))
    live_csv_buffer = LiveCsvBuffer(
        output_path=output,
        prediction_model=prediction_model,
        endpoint_prediction_model=endpoint_prediction_model,
        typewise_prediction_model=typewise_prediction_model,
    )
    color_extractor = ColorFeatureExtractor()
    visible_roi_detector = str(getattr(args, "visible_roi_detector", "yolo")).strip().lower()
    live_stream_port = int(getattr(args, "live_stream_port", 0) or 0)
    pump_serial_bridge = build_pump_serial_bridge_from_args(args)
    yolo_model = None
    yolo_setup_load_lock = threading.Lock()
    yolo_setup_load_attempted = False
    yolo_setup_load_error = ""
    yolo_worker: YoloVisibleRoiWorker | None = None
    yolo_classes = parse_yolo_classes(getattr(args, "yolo_classes", None))
    auto_roi_worker_requested = bool(int(getattr(args, "auto_roi_worker", 1 if live_stream_port > 0 else 0) or 0))
    startup_auto_mode = str(getattr(args, "roi_auto_detect", "off") or "off").strip().lower()
    yolo_needed = (
        visible_roi_detector == "yolo"
        and visible_camera is not None
        and startup_auto_mode in {"visible", "both"}
        and (
            int(getattr(args, "live_stream_port", 0) or 0) > 0
            or not auto_roi_worker_requested
        )
    )
    if yolo_needed:
        yolo_model = load_yolo_model(str(getattr(args, "yolo_model", "yolo11n-seg.pt")))
        yolo_setup_load_attempted = True
        if int(getattr(args, "live_stream_port", 0) or 0) > 0:
            yolo_worker = YoloVisibleRoiWorker(
                yolo_model,
                allowed_classes=yolo_classes,
                min_confidence=float(getattr(args, "yolo_min_confidence", 0.25)),
                max_area_fraction=float(getattr(args, "yolo_max_area_fraction", 0.45)),
                min_interval_s=float(getattr(args, "yolo_min_interval_ms", 1000.0)) / 1000.0,
                success_interval_s=float(getattr(args, "yolo_success_interval_ms", 5000.0)) / 1000.0,
                inference_size=int(getattr(args, "yolo_input_size", 256) or 0),
            )
    live_controls = LiveControlState(
        roi_auto_detect=str(getattr(args, "roi_auto_detect", "off")),
        visible_roi_detector=visible_roi_detector,
        yolo_available=yolo_model is not None,
        thermal_rotation_degrees=int(getattr(args, "thermal_rotation_degrees", 0) or 0),
    )
    rows: list[dict[str, Any]] = []
    feature_history: list[dict[str, Any]] = []
    retained_recording_session_id = 0
    previous_thermal: dict[str, object] | None = None
    previous_visible: dict[str, float] | None = None
    roi_state = RoiSelectionState()
    endpoint_seen = False
    visible_frames = 0
    start = time.perf_counter()
    mini2_worker: Mini2CaptureThread | None = None
    visible_worker: VisibleLatestFrameThread | None = None
    mini2_retry_interval_s = max(0.0, float(getattr(args, "mini2_retry_interval_s", 3.0) or 0.0))
    next_mini2_retry_s = 0.0 if mini2_reader is None and not injected_mini2 and allow_mini2_missing else float("inf")
    mini2_retry_count = 0
    mini2_reconnect_count = 0
    gc_enabled_before_run = gc.isenabled()
    gc_suspended_for_recording = False
    live_state: LiveStreamState | None = None
    live_server: LiveStreamServerHandle | None = None
    visible_stream_publisher: LiveJpegStreamPublisher | None = None
    thermal_stream_publisher: LiveJpegStreamPublisher | None = None
    visible_preview_worker: VisiblePreviewStreamThread | None = None
    auto_roi_worker: AutoRoiWorker | None = None
    auto_roi_worker_enabled = auto_roi_worker_requested
    auto_roi_last_result_sequence = 0
    auto_roi_status: dict[str, Any] = {
        "auto_roi_worker_enabled": auto_roi_worker_enabled,
        "auto_roi_result_sequence": 0,
        "auto_roi_result_age_ms": None,
        "auto_roi_result_status": "not_started" if auto_roi_worker_enabled else "sync_inline_or_disabled",
        "auto_roi_result_reason": "",
        "auto_roi_dropped_pending": 0,
    }
    if auto_roi_worker_enabled:
        auto_roi_worker = AutoRoiWorker()
    auto_stop_controller: ColorChangeAutoStopController | None = None
    endpoint_pulse_runtime: EndpointPulseRuntime | None = None
    if live_stream_port > 0:
        def finish_automatic_stop(
            session_id: int,
            status: dict[str, Any],
            *,
            guard_reason: str,
        ) -> None:
            if live_server is None:
                return
            finish_live_automatic_stop(
                server=live_server.server,
                csv_buffer=live_csv_buffer,
                roi_state=roi_state,
                auto_stop_controller=auto_stop_controller,
                endpoint_pulse_runtime=endpoint_pulse_runtime,
                session_id=session_id,
                status=status,
                guard_reason=guard_reason,
            )

        def handle_auto_stop(decision: AutoStopDecision) -> None:
            """Stop pump and recording once for the still-active CSV session."""

            finish_automatic_stop(
                decision.session_id,
                decision.as_status(),
                guard_reason="optional_auto_stop_triggered",
            )

        def handle_pulse_safety_stop(
            session_id: int,
            reason: str,
            volume_ml: float | None,
            elapsed_s: float,
        ) -> None:
            finish_automatic_stop(
                session_id,
                {
                    "auto_stop_state": "triggered",
                    "auto_stop_triggered": True,
                    "auto_stop_reason": reason,
                    "auto_stop_trigger_volume_ml": ""
                    if volume_ml is None
                    else round(volume_ml, 6),
                    "auto_stop_trigger_elapsed_s": round(elapsed_s, 6),
                    "auto_stop_action_source": "endpoint_pulse_runtime",
                },
                guard_reason=reason,
            )

        def handle_auto_stop_status(status: dict[str, Any]) -> None:
            live_csv_buffer.update_auto_stop_status(status)
            if endpoint_pulse_runtime is not None:
                endpoint_pulse_runtime.handle_auto_stop_status(status)

        auto_stop_controller = ColorChangeAutoStopController(
            typewise_prediction_model,
            on_trigger=handle_auto_stop,
            on_status=handle_auto_stop_status,
        )
    if live_stream_port > 0:
        live_state = LiveStreamState()
        jpeg_quality = int(getattr(args, "live_stream_jpeg_quality", 75))
        visible_stream_publisher = LiveJpegStreamPublisher(
            live_state,
            kind="visible",
            jpeg_quality=jpeg_quality,
            transform=lambda frame: build_visible_stream_frame(frame, roi_state),
            copy_frame=False,
        )
        thermal_stream_publisher = LiveJpegStreamPublisher(
            live_state,
            kind="thermal",
            jpeg_quality=jpeg_quality,
            transform=lambda frame: build_thermal_stream_frame(
                orient_thermal_matrix(
                    frame,
                    int(live_controls.snapshot().get("thermal_rotation_degrees", 0) or 0),
                ),
                roi_state,
            ),
            copy_frame=False,
        )
        visible_stream_publisher.start()
        thermal_stream_publisher.start()
        live_server = start_live_stream_server(
            str(getattr(args, "live_stream_host", "127.0.0.1")),
            live_stream_port,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=bool(int(getattr(args, "roi_click_enabled", 1))),
            controls=live_controls,
            csv_buffer=live_csv_buffer,
            pump_command_sender=None if pump_serial_bridge is None else pump_serial_bridge.send,
            pump_guarded_direction_sender=(
                None
                if pump_serial_bridge is None
                else pump_serial_bridge.send_guarded_direction
            ),
            pump_emergency_stop_sender=(
                None
                if pump_serial_bridge is None
                else pump_serial_bridge.emergency_stop
            ),
            pump_status_provider=None if pump_serial_bridge is None or not hasattr(pump_serial_bridge, "status") else pump_serial_bridge.status,
            auto_stop_controller=auto_stop_controller,
            endpoint_pulse_runtime=endpoint_pulse_runtime,
            pump_command_map={
                "start": str(getattr(args, "pump_start_command", "b") or "b"),
                "retract": str(getattr(args, "pump_retract_command", "a") or "a"),
                "stop": str(getattr(args, "pump_stop_command", "c") or "c"),
            },
            pump_pulse_direction=str(
                getattr(args, "pump_pulse_direction", "b") or "b"
            ),
            remote_config_path=(
                ROOT
                / ".runtime"
                / f"remote-recording-config-{live_stream_port}.json"
            ),
        )
        if pump_serial_bridge is not None:
            def stop_continuous_for_endpoint_pulse(reason: str) -> dict[str, Any]:
                if live_server is None:
                    raise RuntimeError("live server is unavailable")
                guard = getattr(live_server.server, "absolute_pump_safety_guard", None)
                if not isinstance(guard, AbsolutePumpSafetyGuard):
                    raise RuntimeError("absolute pump safety guard is unavailable")
                stopped = guard.stop(str(reason or "endpoint_pulse_mode"))
                if stopped.get("absolute_guard_stop_status") != "sent":
                    raise RuntimeError(
                        str(stopped.get("absolute_guard_error") or "pump stop command failed")
                    )
                live_csv_buffer.pause_commanded_pump_timeline(state="pulse_settling")
                return stopped

            def start_slow_continuous_for_endpoint(
                *,
                rate_steps_per_s: int,
                nominal_rate_ml_per_s: float,
                maximum_rate_ml_per_s: float,
                remaining_volume_ml: float,
                absolute_deadline_monotonic_s: float,
                can_restart: Callable[[], bool],
            ) -> dict[str, Any]:
                """After STOP, require RATE ACK, then arm G and direction."""

                if live_server is None:
                    raise RuntimeError("live server is unavailable")
                guard = getattr(live_server.server, "absolute_pump_safety_guard", None)
                if not isinstance(guard, AbsolutePumpSafetyGuard):
                    raise RuntimeError("absolute pump safety guard is unavailable")
                status = start_guarded_continuous_at_rate(
                    command_sender=pump_serial_bridge.send,
                    guard=guard,
                    direction_command=str(getattr(live_server.server, "pump_pulse_direction", "b")),
                    rate_steps_per_s=rate_steps_per_s,
                    maximum_rate_ml_per_s=maximum_rate_ml_per_s,
                    remaining_volume_ml=remaining_volume_ml,
                    absolute_deadline_monotonic_s=absolute_deadline_monotonic_s,
                    can_restart=can_restart,
                )
                status.update(
                    {
                        "rate_steps_per_s": rate_steps_per_s,
                        "nominal_rate_ml_per_s": nominal_rate_ml_per_s,
                        "rate_basis": "nominal_uncalibrated_fast_rate_times_steps_per_100",
                    }
                )
                return status

            endpoint_pulse_runtime = EndpointPulseRuntime(
                command_sender=pump_serial_bridge.send,
                stop_continuous=stop_continuous_for_endpoint_pulse,
                csv_buffer=live_csv_buffer,
                on_safety_stop=handle_pulse_safety_stop,
                start_slow_continuous=start_slow_continuous_for_endpoint,
            )
            live_server.server.endpoint_pulse_runtime = endpoint_pulse_runtime  # type: ignore[attr-defined]
        live_server.server.roi_candidate_min_confidence = float(getattr(args, "roi_auto_min_confidence", 0.5))  # type: ignore[attr-defined]
    if live_server is not None:
        def yolo_visible_candidate_for_setup(frame: np.ndarray) -> RoiDetectionResult:
            nonlocal yolo_model, yolo_setup_load_attempted, yolo_setup_load_error
            if yolo_model is None:
                with yolo_setup_load_lock:
                    if yolo_model is None and not yolo_setup_load_attempted:
                        yolo_setup_load_attempted = True
                        try:
                            yolo_model = load_yolo_model(str(getattr(args, "yolo_model", "yolo11n-seg.pt")))
                            live_controls.set_yolo_available(True)
                            print("Optional YOLO ROI model loaded on demand.", flush=True)
                        except Exception as exc:  # noqa: BLE001 - optional setup aid must not stop collection.
                            yolo_setup_load_error = str(exc)
                            live_controls.set_yolo_available(False)
                            print(
                                "Optional YOLO ROI unavailable; use manual visible ROI. "
                                f"Reason: {yolo_setup_load_error}",
                                flush=True,
                            )
            if yolo_model is None:
                return RoiDetectionResult(None, 0.0, "yolo_runtime_unavailable")
            return auto_detect_visible_roi_setup_candidate(
                frame,
                visible_detector=visible_roi_detector,
                yolo_model=yolo_model,
                yolo_classes=yolo_classes,
                min_confidence=float(getattr(args, "roi_auto_min_confidence", 0.5)),
                yolo_min_confidence=float(getattr(args, "yolo_min_confidence", 0.25)),
                yolo_max_area_fraction=float(getattr(args, "yolo_max_area_fraction", 0.45)),
            )

        live_server.server.visible_candidate_detector = yolo_visible_candidate_for_setup  # type: ignore[attr-defined]
        def latest_thermal_matrix_for_roi() -> np.ndarray | None:
            if mini2_worker is None:
                return None
            latest = mini2_worker.latest(timeout_s=0.5)
            if latest is None:
                return None
            degrees = int(live_controls.snapshot().get("thermal_rotation_degrees", 0) or 0)
            return orient_thermal_matrix(latest.parts.raw_matrix, degrees).copy()

        live_server.server.thermal_matrix_provider = latest_thermal_matrix_for_roi  # type: ignore[attr-defined]
    if mini2_reader is not None and not injected_mini2:
        mini2_worker = start_mini2_capture_thread(
            mini2_reader,
            start_time=start,
            thermal_stream_publisher=thermal_stream_publisher,
            thermal_rotation_getter=lambda: int(live_controls.snapshot().get("thermal_rotation_degrees", 0) or 0),
            max_recording_queue=int(getattr(args, "mini2_recording_queue_frames", 2048) or 2048),
        )
        if live_server is not None:
            live_server.server.capture_controller = mini2_worker  # type: ignore[attr-defined]
    if visible_camera is not None and not injected_visible:
        visible_worker = VisibleLatestFrameThread(visible_camera, start_time=start)
        visible_worker.start()
        if live_server is not None:
            def latest_visible_frame_for_roi() -> np.ndarray | None:
                if visible_worker is None:
                    return None
                latest = visible_worker.latest_timestamped(timeout_s=0.5)
                return None if latest is None else latest.frame_rgb.copy()

            live_server.server.visible_frame_provider = latest_visible_frame_for_roi  # type: ignore[attr-defined]
        if visible_stream_publisher is not None:
            visible_preview_worker = VisiblePreviewStreamThread(visible_worker, visible_stream_publisher)
            visible_preview_worker.start()

    def close_current_converter() -> None:
        nonlocal converter
        close = getattr(converter, "close", None)
        if callable(close):
            close()
        converter = None

    def mark_mini2_unavailable(reason: str, *, retry_at_s: float) -> None:
        nonlocal mini2_reader, mini2_worker, resolved_mini2_index, mini2_unavailable_reason, next_mini2_retry_s
        mini2_unavailable_reason = reason
        resolved_mini2_index = ""
        failed_worker = mini2_worker
        mini2_worker = None
        if live_server is not None:
            live_server.server.capture_controller = None  # type: ignore[attr-defined]
        failed_reader = mini2_reader
        mini2_reader = None
        close_current_converter()
        try:
            if failed_worker is not None:
                failed_worker.close()
            elif failed_reader is not None and not injected_mini2:
                failed_reader.release()
        except Exception as close_exc:  # noqa: BLE001 - losing the camera should not stop visible/status collection.
            mini2_unavailable_reason = f"{reason}; close failed: {close_exc}"
        next_mini2_retry_s = retry_at_s

    def retry_mini2_if_due(now_s: float) -> bool:
        nonlocal mini2_reader, mini2_worker, converter, resolved_mini2_index
        nonlocal mini2_unavailable_reason, converter_unavailable_reason
        nonlocal next_mini2_retry_s, mini2_retry_count, mini2_reconnect_count
        if injected_mini2 or mini2_reader is not None or not allow_mini2_missing:
            return False
        if now_s < next_mini2_retry_s:
            return False

        mini2_retry_count += 1
        probe_args = argparse.Namespace(**vars(args))
        probe_args.mini2_index = mini2_requested_index
        probe_args.mini2_backend = mini2_requested_backend
        candidate_reader: Mini2PartsReader | None = None
        candidate_converter = None
        try:
            candidate_reader, candidate_index = open_mini2_capture(probe_args)
            if probe_args.thermal_processing != "raw":
                try:
                    candidate_converter = build_official_converter(probe_args)
                except Exception as exc:  # noqa: BLE001 - Mini2 image stream is still useful as raw preview.
                    converter_unavailable_reason = str(exc)
                    probe_args.thermal_processing = "raw"
                    args.thermal_processing = "raw"
                    print(
                        "Warning: official Mini2 Celsius converter unavailable after reconnect; "
                        "continuing raw thermal preview only. "
                        f"Reason: {converter_unavailable_reason}",
                        flush=True,
                    )
            args.mini2_index = candidate_index
            args.mini2_backend = probe_args.mini2_backend
            mini2_reader = candidate_reader
            converter = candidate_converter
            resolved_mini2_index = candidate_index
            mini2_worker = start_mini2_capture_thread(
                candidate_reader,
                start_time=start,
                thermal_stream_publisher=thermal_stream_publisher,
                thermal_rotation_getter=lambda: int(live_controls.snapshot().get("thermal_rotation_degrees", 0) or 0),
                max_recording_queue=int(getattr(args, "mini2_recording_queue_frames", 2048) or 2048),
            )
            if live_server is not None:
                live_server.server.capture_controller = mini2_worker  # type: ignore[attr-defined]
            mini2_unavailable_reason = ""
            mini2_reconnect_count += 1
            next_mini2_retry_s = now_s + mini2_retry_interval_s
            print(
                f"Mini2 reconnected: index={candidate_index} backend={args.mini2_backend} "
                f"after {mini2_retry_count} retry attempt(s).",
                flush=True,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - retry later while keeping visible/status live.
            if candidate_reader is not None:
                try:
                    candidate_reader.release()
                except Exception:
                    pass
            close = getattr(candidate_converter, "close", None)
            if callable(close):
                close()
            mini2_unavailable_reason = str(exc)
            next_mini2_retry_s = now_s + mini2_retry_interval_s
            return False

    try:
        for frame_id in range(args.frames):
            csv_loop_status = live_csv_buffer.status()
            low_latency_recording = bool(csv_loop_status.get("recording") or csv_loop_status.get("finalizing"))
            if low_latency_recording and not gc_suspended_for_recording:
                if gc.isenabled():
                    gc.disable()
                gc_suspended_for_recording = True
            elif not low_latency_recording and gc_suspended_for_recording:
                if gc_enabled_before_run:
                    gc.enable()
                    gc.collect()
                gc_suspended_for_recording = False
            parts: Mini2RawFrameParts | None = None
            thermal_time_s: float | None = None
            captured: CapturedMini2Frame | None = None
            capture_recording_session_id = 0
            retry_mini2_if_due(time.perf_counter() - start)
            if mini2_reader is None:
                target_time = start + (frame_id / max(0.001, float(args.frame_rate_hz)))
                sleep_s = target_time - time.perf_counter()
                if sleep_s > 0:
                    time.sleep(sleep_s)
                elapsed_s = time.perf_counter() - start
                captured_frame_id = frame_id
                processing_latency_ms = 0.0
            elif mini2_worker is None:
                parts = mini2_reader.read_frame_parts()
                elapsed_s = time.perf_counter() - start
                captured_frame_id = frame_id
                thermal_time_s = elapsed_s
                processing_latency_ms = max(0.0, ((time.perf_counter() - start) - float(elapsed_s)) * 1000.0)
            else:
                try:
                    captured = mini2_worker.read()
                    parts = captured.parts
                    elapsed_s = captured.timestamp_s
                    captured_frame_id = captured.frame_id
                    capture_recording_session_id = captured.recording_session_id
                    thermal_time_s = elapsed_s
                    processing_latency_ms = max(0.0, ((time.perf_counter() - start) - float(elapsed_s)) * 1000.0)
                except Exception as exc:  # noqa: BLE001 - let the collector recover if Mini2 is unplugged/busy.
                    if injected_mini2 or not allow_mini2_missing:
                        raise
                    elapsed_s = time.perf_counter() - start
                    captured_frame_id = frame_id
                    processing_latency_ms = 0.0
                    mark_mini2_unavailable(
                        f"Mini2 stream lost; retrying: {exc}",
                        retry_at_s=elapsed_s,
                    )
            control_snapshot = live_controls.snapshot()
            thermal_rotation_degrees = int(control_snapshot.get("thermal_rotation_degrees", 0) or 0)
            if parts is not None:
                parts = orient_mini2_frame_parts(parts, thermal_rotation_degrees)
            visible_features: dict[str, float] = {}
            frame_rgb: np.ndarray | None = None
            preview_frame_rgb: np.ndarray | None = None
            matched_visible_time_s: float | None = None
            preview_visible_time_s: float | None = None
            matched_visible_frame_id: int | None = None
            preview_visible_frame_id: int | None = None
            if visible_camera is not None:
                if visible_worker is not None:
                    visible_sync_max_age_ms = float(getattr(args, "visible_sync_max_age_ms", 1000.0) or 0.0)
                    visible_future_wait_s = max(
                        0.0,
                        float(getattr(args, "visible_future_wait_ms", 10.0) or 0.0) / 1000.0,
                    )
                    visible_future_wait_min_gap_s = max(0.0, 0.5 / max(1.0, float(args.frame_rate_hz)))
                    matched_visible = visible_worker.nearest(
                        elapsed_s,
                        max_age_s=None if visible_sync_max_age_ms <= 0 else visible_sync_max_age_ms / 1000.0,
                        future_wait_s=visible_future_wait_s,
                        future_wait_min_gap_s=visible_future_wait_min_gap_s,
                    )
                    # Captured visible frames are immutable snapshots owned by
                    # the ring buffer.  Reuse them instead of copying two full
                    # RGB images on every thermal frame.
                    frame_rgb = None if matched_visible is None else matched_visible.frame_rgb
                    matched_visible_time_s = None if matched_visible is None else matched_visible.timestamp_s
                    matched_visible_frame_id = None if matched_visible is None else matched_visible.frame_id
                    try:
                        latest_visible = visible_worker.latest_timestamped(timeout_s=0.0)
                    except RuntimeError:
                        latest_visible = None
                    preview_frame_rgb = None if latest_visible is None else latest_visible.frame_rgb
                    preview_visible_time_s = None if latest_visible is None else latest_visible.preview_timestamp_s
                    preview_visible_frame_id = None if latest_visible is None else latest_visible.frame_id
                else:
                    read_start = time.perf_counter()
                    frame_rgb = visible_camera.read_rgb()
                    read_end = time.perf_counter()
                    matched_visible_time_s = ((read_start + read_end) / 2.0) - start
                    preview_frame_rgb = frame_rgb
                    preview_visible_time_s = read_end - start
                    matched_visible_frame_id = frame_id
                    preview_visible_frame_id = frame_id
                    if visible_stream_publisher is not None:
                        visible_stream_publisher.submit(preview_frame_rgb)
                configured_visible_roi = str(getattr(args, "visible_roi", "auto") or "auto").strip().lower()
                if frame_rgb is not None and roi_state.snapshot()[0] is None and configured_visible_roi != "auto":
                    roi_state.update_rect(
                        "visible",
                        resolve_visible_roi(args.visible_roi, frame_rgb),
                        frame_shape=frame_rgb.shape[:2],
                    )
            roi_state.set_latest_shapes(
                visible_shape=None
                if (frame_rgb is None and preview_frame_rgb is None)
                else (frame_rgb if frame_rgb is not None else preview_frame_rgb).shape[:2],
                thermal_shape=None if parts is None else parts.raw_matrix.shape[:2],
            )

            process_pending_roi_clicks(
                roi_state,
                visible_frame=frame_rgb if frame_rgb is not None else preview_frame_rgb,
                thermal_matrix=None if parts is None else parts.raw_matrix,
                link_mode=str(getattr(args, "roi_link_mode", "anchor")),
            )
            auto_mode = str(control_snapshot["roi_auto_detect"]).strip().lower()
            active_visible_detector = str(control_snapshot["visible_roi_detector"]).strip().lower()
            auto_every = int(getattr(args, "roi_auto_every", 25) or 25)
            auto_min_confidence = float(getattr(args, "roi_auto_min_confidence", 0.5))
            roi_link_mode = str(getattr(args, "roi_link_mode", "anchor"))
            auto_settings = AutoRoiSettingsSnapshot.from_values(
                mode=auto_mode,
                visible_detector=active_visible_detector,
                min_confidence=auto_min_confidence,
                link_mode=roi_link_mode,
                settings_updated_epoch_s=control_snapshot.get("settings_updated_epoch_s"),
            )
            if auto_roi_worker is not None:
                worker_result = auto_roi_worker.latest_result(
                    after_sequence=auto_roi_last_result_sequence,
                    timeout_s=0.0,
                )
                if worker_result is not None:
                    auto_roi_last_result_sequence = worker_result.sequence
                    applied, worker_reason = apply_auto_roi_worker_result(
                        roi_state,
                        worker_result,
                        current_settings=auto_settings,
                        visible_frame=frame_rgb if frame_rgb is not None else preview_frame_rgb,
                        thermal_matrix=None if parts is None else parts.raw_matrix,
                        max_result_age_s=float(getattr(args, "auto_roi_result_max_age_ms", 2000.0) or 0.0) / 1000.0,
                    )
                    auto_roi_status = {
                        "auto_roi_worker_enabled": True,
                        "auto_roi_result_sequence": worker_result.sequence,
                        "auto_roi_result_age_ms": worker_result.result_age_ms,
                        "auto_roi_result_status": worker_reason,
                        "auto_roi_result_reason": (
                            worker_reason
                            if not applied
                            else ",".join(
                                result.reason
                                for result in (worker_result.visible_result, worker_result.thermal_result)
                                if result is not None
                            )
                        ),
                        "auto_roi_dropped_pending": auto_roi_worker.dropped_pending,
                        "auto_roi_visible_frame_id": worker_result.visible_frame_id,
                        "auto_roi_thermal_frame_id": worker_result.thermal_frame_id,
                    }
            visible_for_roi = frame_rgb if frame_rgb is not None else preview_frame_rgb
            auto_candidate_target = roi_state.pop_auto_candidate_request(
                visible_available=visible_for_roi is not None,
                thermal_available=parts is not None,
                visible_expected=visible_camera is not None,
                thermal_expected=mini2_reader is not None or parts is not None,
            )
            if auto_candidate_target is not None:
                target_visible = auto_candidate_target in {"visible", "both"}
                target_thermal = auto_candidate_target in {"thermal", "both"}
                setup_candidate_applied = apply_setup_auto_candidate_rois(
                    roi_state,
                    visible_frame=visible_for_roi if target_visible else None,
                    thermal_matrix=parts.raw_matrix if target_thermal and parts is not None else None,
                    min_confidence=auto_min_confidence,
                    visible_detector=active_visible_detector,
                    yolo_model=yolo_model,
                    yolo_classes=yolo_classes,
                    yolo_min_confidence=float(getattr(args, "yolo_min_confidence", 0.25)),
                    yolo_max_area_fraction=float(getattr(args, "yolo_max_area_fraction", 0.45)),
                )
                auto_roi_status.update(
                    {
                        "auto_roi_result_status": "setup_candidate_applied" if setup_candidate_applied else "setup_candidate_not_found",
                        "auto_roi_result_reason": f"{auto_candidate_target}:{roi_state.status().get('roi_source', '')}",
                    }
                )
            continuous_auto_allowed = roi_state.auto_updates_allowed()
            if continuous_auto_allowed and auto_mode != "off" and auto_every > 0 and frame_id % auto_every == 0:
                yolo_result = None
                if (
                    active_visible_detector == "yolo"
                    and yolo_worker is not None
                    and visible_for_roi is not None
                    and auto_mode in {"visible", "both"}
                ):
                    yolo_worker.submit(visible_for_roi)
                    yolo_result = yolo_worker.latest_result(timeout_s=0.0)
                if yolo_result is not None:
                    apply_auto_roi_detection_results(
                        roi_state,
                        visible_result=yolo_result,
                        thermal_result=None,
                        visible_frame=visible_for_roi,
                        thermal_matrix=None,
                        min_confidence=auto_min_confidence,
                    )
                if auto_roi_worker is not None:
                    submitted_sequence = auto_roi_worker.submit(
                        visible_frame=visible_for_roi,
                        thermal_matrix=None if parts is None else parts.raw_matrix,
                        settings=auto_settings,
                        visible_frame_id=matched_visible_frame_id if frame_rgb is not None else preview_visible_frame_id,
                        visible_timestamp_s=matched_visible_time_s if frame_rgb is not None else preview_visible_time_s,
                        thermal_frame_id=captured_frame_id if parts is not None else None,
                        thermal_timestamp_s=thermal_time_s if parts is not None else None,
                    )
                    if submitted_sequence is not None:
                        auto_roi_status.update(
                            {
                                "auto_roi_worker_enabled": True,
                                "auto_roi_submitted_sequence": submitted_sequence,
                                "auto_roi_result_status": "submitted",
                                "auto_roi_dropped_pending": auto_roi_worker.dropped_pending,
                            }
                        )
                else:
                    maybe_auto_update_rois(
                        roi_state,
                        visible_frame=visible_for_roi,
                        thermal_matrix=None if parts is None else parts.raw_matrix,
                        mode=auto_mode,
                        min_confidence=auto_min_confidence,
                        link_mode=roi_link_mode,
                        visible_detector=active_visible_detector,
                        yolo_model=None if yolo_worker is not None else yolo_model,
                        yolo_classes=yolo_classes,
                        yolo_min_confidence=float(getattr(args, "yolo_min_confidence", 0.25)),
                        yolo_max_area_fraction=float(getattr(args, "yolo_max_area_fraction", 0.45)),
                        visible_result_override=yolo_result,
                    )
            elif not continuous_auto_allowed and auto_mode != "off":
                auto_roi_status.update(
                    {
                        "auto_roi_result_status": "roi_locked_or_recording",
                        "auto_roi_result_reason": "continuous auto ROI disabled while ROI is locked/recording",
                    }
                )

            visible_roi, thermal_roi = roi_state.snapshot()
            visible_mask, thermal_mask = roi_state.snapshot_masks()
            if thermal_roi is None:
                thermal_roi = args.thermal_roi
            if parts is None:
                thermal_features = unavailable_thermal_features(
                    mini2_unavailable_reason or "Mini2 raw stream unavailable",
                    frame_rate_hz=args.frame_rate_hz,
                )
            elif args.thermal_processing == "raw":
                if thermal_mask is not None and thermal_mask.mask.shape == parts.raw_matrix.shape:
                    thermal_features = extract_raw_mask_thermal_features(
                        raw_matrix=parts.raw_matrix,
                        roi_mask=thermal_mask,
                        previous=previous_thermal,
                        frame_rate_hz=args.frame_rate_hz,
                    )
                else:
                    thermal_features = extract_raw_thermal_features(
                        raw_matrix=parts.raw_matrix,
                        roi=thermal_roi,
                        previous=previous_thermal,
                        frame_rate_hz=args.frame_rate_hz,
                    )
                if converter_unavailable_reason:
                    thermal_features["thermal_conversion_status"] = THERMAL_CONVERSION_CONVERTER_UNAVAILABLE
                    thermal_features["warnings"] = (
                        "official Celsius converter unavailable; raw preview only: "
                        f"{converter_unavailable_reason}"
                    )
            elif args.thermal_processing == "roi":
                if thermal_mask is not None and thermal_mask.mask.shape == parts.raw_matrix.shape:
                    thermal_features = extract_roi_mask_thermal_features(
                        raw_matrix=parts.raw_matrix,
                        addline_tag1=parts.addline_tag1,
                        converter=converter,
                        roi_mask=thermal_mask,
                        previous=previous_thermal,
                        frame_rate_hz=args.frame_rate_hz,
                    )
                else:
                    thermal_features = extract_roi_only_thermal_features(
                        raw_matrix=parts.raw_matrix,
                        addline_tag1=parts.addline_tag1,
                        converter=converter,
                        roi=thermal_roi,
                        previous=previous_thermal,
                        frame_rate_hz=args.frame_rate_hz,
                    )
            else:
                try:
                    thermal_frame = build_temperature_frame(
                        raw_matrix=parts.raw_matrix,
                        converter=converter,
                        frame_id=captured_frame_id,
                        addline_tag1=parts.addline_tag1,
                        timestamp_s=elapsed_s,
                        frame_rate_hz=args.frame_rate_hz,
                    )
                except Exception as exc:  # noqa: BLE001 - keep live collector running with explicit raw fallback evidence.
                    if thermal_mask is not None and thermal_mask.mask.shape == parts.raw_matrix.shape:
                        thermal_features = _add_converter_exception_warning(
                            extract_raw_mask_thermal_features(
                                raw_matrix=parts.raw_matrix,
                                roi_mask=thermal_mask,
                                previous=previous_thermal,
                                frame_rate_hz=args.frame_rate_hz,
                            ),
                            converter,
                            exc,
                        )
                    else:
                        thermal_features = _add_converter_exception_warning(
                            extract_raw_thermal_features(
                                raw_matrix=parts.raw_matrix,
                                roi=thermal_roi,
                                previous=previous_thermal,
                                frame_rate_hz=args.frame_rate_hz,
                            ),
                            converter,
                            exc,
                        )
                    thermal_frame = None
                if thermal_frame is None:
                    pass
                elif thermal_mask is not None and thermal_mask.mask.shape == thermal_frame.temperature_matrix_c.shape:
                    values = thermal_frame.temperature_matrix_c[thermal_mask.mask]
                    coords_yx = np.argwhere(thermal_mask.mask)
                    raw_values = thermal_frame.raw_matrix[thermal_mask.mask]
                    conversion_status = _official_celsius_output_status(values, raw_values)
                    if conversion_status != THERMAL_CONVERSION_OK:
                        thermal_features = _add_celsius_fallback_warning(
                            extract_raw_mask_thermal_features(
                                raw_matrix=thermal_frame.raw_matrix,
                                roi_mask=thermal_mask,
                                previous=previous_thermal,
                                frame_rate_hz=thermal_frame.frame_rate_hz,
                            ),
                            converter,
                            conversion_status,
                        )
                    else:
                        roi_avg = round(float(np.mean(values)), 6)
                        prev_avg_raw = None if previous_thermal is None else previous_thermal.get("thermal_roi_avg")
                        try:
                            prev_avg = None if prev_avg_raw is None else float(prev_avg_raw)
                        except (TypeError, ValueError):
                            prev_avg = None
                        thermal_features = {
                            "thermal_source": "mini2_uvc_raw_official_full_mask_celsius",
                            "thermal_calibrated": True,
                            "source_quality": "mini2_uvc_raw_calibrated_full_mask_temperature",
                            "thermal_conversion_model": thermal_frame.converter_name,
                            "thermal_conversion_calibration_source": thermal_frame.calibration_source,
                            "thermal_conversion_status": THERMAL_CONVERSION_OK,
                            "thermal_frame_rate_hz": thermal_frame.frame_rate_hz,
                            "thermal_matrix_shape": f"full-mask:{thermal_frame.temperature_matrix_c.shape[0]}x{thermal_frame.temperature_matrix_c.shape[1]}",
                            "thermal_roi_avg": roi_avg,
                            "thermal_roi_max": round(float(np.max(values)), 6),
                            "thermal_roi_min": round(float(np.min(values)), 6),
                            "thermal_roi_std": round(float(np.std(values)), 12),
                            "thermal_roi_delta": 0.0 if prev_avg is None else round(roi_avg - prev_avg, 6),
                            "thermal_raw_min": int(np.min(thermal_frame.raw_matrix)),
                            "thermal_raw_max": int(np.max(thermal_frame.raw_matrix)),
                            "thermal_raw_mean": round(float(np.mean(thermal_frame.raw_matrix)), 6),
                            "thermal_raw_std": round(float(np.std(thermal_frame.raw_matrix)), 6),
                        }
                        thermal_features.update(_distribution_features("thermal_roi", values, coords_yx=coords_yx))
                        thermal_features.update(_distribution_features("thermal_matrix", thermal_frame.temperature_matrix_c))
                        thermal_features.update(_distribution_features("thermal_raw_roi", raw_values, coords_yx=coords_yx))
                        thermal_features.update(_distribution_features("thermal_raw", thermal_frame.raw_matrix))
                        thermal_features.update(_mask_metadata("thermal", thermal_mask))
                else:
                    raw_roi = thermal_frame.raw_matrix[
                        thermal_roi.y : thermal_roi.y + thermal_roi.height,
                        thermal_roi.x : thermal_roi.x + thermal_roi.width,
                    ]
                    celsius_roi = thermal_frame.temperature_matrix_c[
                        thermal_roi.y : thermal_roi.y + thermal_roi.height,
                        thermal_roi.x : thermal_roi.x + thermal_roi.width,
                    ]
                    conversion_status = _official_celsius_output_status(celsius_roi, raw_roi)
                    if conversion_status != THERMAL_CONVERSION_OK:
                        thermal_features = _add_celsius_fallback_warning(
                            extract_raw_thermal_features(
                                raw_matrix=thermal_frame.raw_matrix,
                                roi=thermal_roi,
                                previous=previous_thermal,
                                frame_rate_hz=thermal_frame.frame_rate_hz,
                            ),
                            converter,
                            conversion_status,
                        )
                    else:
                        thermal_features = extract_temperature_features(
                            thermal_frame.temperature_matrix_c,
                            thermal_roi,
                            raw_matrix=thermal_frame.raw_matrix,
                            previous=previous_thermal,
                            converter_name=thermal_frame.converter_name,
                            calibration_source=thermal_frame.calibration_source,
                            frame_rate_hz=thermal_frame.frame_rate_hz,
                        )
                        thermal_features["thermal_conversion_status"] = THERMAL_CONVERSION_OK
            if visible_camera is not None:
                if frame_rgb is not None and visible_roi is not None:
                    if visible_mask is not None and visible_mask.mask.shape == frame_rgb.shape[:2]:
                        base_visible = extract_mask_color_features(frame_rgb, visible_mask, previous=previous_visible)
                    else:
                        base_visible = color_extractor.extract(frame_rgb, visible_roi, previous=previous_visible)
                    visible_features = prefix_features(base_visible, "visible")
                    previous_visible = base_visible
                    visible_frames += 1

            frame_monotonic_s = start + float(elapsed_s)
            pump_timeline = live_csv_buffer.pump_timeline_fields(now_monotonic_s=frame_monotonic_s)
            injected_volume = _finite_float_or_none(pump_timeline.get("injected_volume_ml"))
            sample = FeatureSample(
                time_s=elapsed_s,
                frame_id=captured_frame_id,
                injected_volume_ml=0.0 if injected_volume is None else injected_volume,
                visible_features=visible_features,
                thermal_features=thermal_features,
                source_quality=str(thermal_features["source_quality"]),
            )
            label, confidence = classify_status(sample, endpoint_seen=endpoint_seen)
            endpoint_seen = endpoint_seen or label == "endpoint"
            sample.status_label = label
            sample.status_confidence = round(confidence, 6)
            row = sample.to_serializable_row()
            row.update(pump_timeline)
            row.update(
                build_sync_metadata(
                    thermal_time_s=thermal_time_s,
                    visible_time_s=matched_visible_time_s,
                    max_sync_offset_ms=args.max_sync_offset_ms,
                )
            )
            row["processing_latency_ms"] = round(processing_latency_ms, 6)
            row["capture_recording_session_id"] = capture_recording_session_id
            if preview_visible_time_s is not None:
                row["preview_visible_latency_ms"] = round(
                    max(0.0, ((time.perf_counter() - start) - float(preview_visible_time_s)) * 1000.0),
                    6,
                )
            capture_status = {} if mini2_worker is None else mini2_worker.recording_status()
            row["mini2_dropped_frames"] = int(capture_status.get("recording_dropped_frames", 0) or 0)
            row["mini2_preview_dropped_frames"] = int(capture_status.get("preview_dropped_frames", 0) or 0)
            row["mini2_recording_dropped_frames"] = int(capture_status.get("recording_dropped_frames", 0) or 0)
            row["mini2_recording_backlog_frames"] = int(capture_status.get("recording_backlog_frames", 0) or 0)
            row["mini2_recording_max_backlog_frames"] = int(capture_status.get("recording_max_backlog_frames", 0) or 0)
            row["mini2_capture_fps"] = capture_status.get("capture_fps", 0.0)
            row["mini2_retry_count"] = mini2_retry_count
            row["mini2_reconnect_count"] = mini2_reconnect_count
            row["mini2_retry_interval_s"] = mini2_retry_interval_s
            row["mini2_capture_backend"] = args.mini2_backend
            row["mini2_capture_index"] = resolved_mini2_index
            row["thermal_rotation_degrees"] = thermal_rotation_degrees
            row["visible_capture_index"] = "" if visible_camera is None else resolved_visible_index
            row.update(roi_state.row_metadata(visible_roi=visible_roi, thermal_roi=thermal_roi))
            row.update(auto_roi_status)
            csv_status_before_add = live_csv_buffer.status()
            row_recording_session_id = int(capture_recording_session_id or 0)
            if row_recording_session_id <= 0 and mini2_worker is None and bool(
                csv_status_before_add.get("recording") or csv_status_before_add.get("finalizing")
            ):
                row_recording_session_id = int(csv_status_before_add.get("session_id") or 0)
            if row_recording_session_id > 0 and row_recording_session_id != retained_recording_session_id:
                # A new experiment gets a new one-second baseline.  Do not use
                # idle frames captured before the user pressed Record.
                rows.clear()
                feature_history.clear()
                retained_recording_session_id = row_recording_session_id
            selected_history = select_online_history_rows(feature_history, row)
            row.update(derive_ml_features(selected_history, row))
            feature_history = [*selected_history, row]
            retain_output_row = live_stream_port <= 0 or row_recording_session_id > 0
            if retain_output_row:
                rows.append(row)
            csv_row_added = live_csv_buffer.add(row, now_monotonic_s=frame_monotonic_s)
            if csv_row_added and auto_stop_controller is not None and row_recording_session_id > 0:
                # The model also needs experiment metadata merged by
                # LiveCsvBuffer; status already holds that immutable metadata.
                accepted_row = live_csv_buffer.latest_recorded_row(row_recording_session_id)
                if accepted_row is not None:
                    auto_stop_controller.submit(row_recording_session_id, accepted_row)
            if mini2_worker is not None and captured is not None:
                mini2_worker.mark_processed(captured, stored=csv_row_added)
                csv_status_after_add = live_csv_buffer.status()
                if csv_status_after_add.get("finalizing") and mini2_worker.recording_drained(
                    int(csv_status_after_add.get("session_id") or 0)
                ):
                    completed_session_id = int(
                        csv_status_after_add.get("session_id") or 0
                    )
                    live_csv_buffer.complete_stop()
                    if live_server is not None:
                        getattr(
                            live_server.server,
                            "csv_stop_intent",
                        ).clear_latch(completed_session_id)
            stream_every = int(getattr(args, "stream_every", 0) or 0)
            if stream_every > 0 and rows and len(rows) % stream_every == 0:
                write_rows(output, rows)
            live_payload = build_live_payload(
                thermal_features,
                row,
                visible_roi=visible_roi,
                thermal_roi=thermal_roi,
                visible_mask=visible_mask,
                thermal_mask=thermal_mask,
                csv_status=live_csv_buffer.status(),
            )
            live_payload.update(roi_state.status())
            live_payload.update(control_snapshot)
            live_payload["roi_link_mode"] = str(getattr(args, "roi_link_mode", "anchor"))
            if live_state is not None:
                live_state.publish_metadata(live_payload)
                if mini2_worker is None and thermal_stream_publisher is not None and parts is not None:
                    thermal_stream_publisher.submit(parts.raw_matrix)
            preview_every = int(getattr(args, "preview_every", 0) or 0)
            preview_dir = getattr(args, "preview_dir", "")
            if preview_every > 0 and preview_dir and (frame_id + 1) % preview_every == 0:
                write_live_preview(
                    Path(preview_dir),
                    preview_frame_rgb,
                    thermal_features,
                    row,
                    raw_matrix=None if parts is None else parts.raw_matrix,
                    visible_roi=visible_roi,
                    thermal_roi=thermal_roi,
                    visible_mask=visible_mask,
                    thermal_mask=thermal_mask,
                )
            previous_thermal = thermal_features
            if args.print_every and (frame_id % args.print_every == 0):
                visible_msg = (
                    f" visible_rgb=({visible_features.get('visible_R_mean')},"
                    f"{visible_features.get('visible_G_mean')},{visible_features.get('visible_B_mean')})"
                    if visible_features
                    else " visible=off"
                )
                if parts is None:
                    thermal_msg = " thermal=unavailable"
                elif (
                    thermal_features.get("thermal_conversion_status") != THERMAL_CONVERSION_OK
                    or "thermal_roi_avg" not in thermal_features
                ):
                    thermal_msg = (
                        f" thermal_raw_avg={thermal_features.get('thermal_raw_roi_avg', '-')}"
                        f" raw_min={thermal_features.get('thermal_raw_roi_min', '-')}"
                        f" raw_max={thermal_features.get('thermal_raw_roi_max', '-')}"
                        f" conversion={thermal_features.get('thermal_conversion_status', '-')}"
                    )
                else:
                    thermal_msg = (
                        f" thermal_roi_avg={thermal_features['thermal_roi_avg']}C"
                        f" thermal_min={thermal_features.get('thermal_matrix_min', thermal_features['thermal_roi_min'])}C"
                        f" thermal_max={thermal_features.get('thermal_matrix_max', thermal_features['thermal_roi_max'])}C"
                    )
                print(f"frame={frame_id}{thermal_msg}{visible_msg} status={label}", flush=True)
    finally:
        if gc_enabled_before_run and not gc.isenabled():
            gc.enable()
        elif not gc_enabled_before_run and gc.isenabled():
            gc.disable()
        if visible_preview_worker is not None:
            visible_preview_worker.close()
        if mini2_worker is not None:
            mini2_worker.close()
        elif mini2_reader is not None:
            mini2_reader.release()
        if visible_worker is not None:
            visible_worker.close()
        elif visible_camera is not None:
            visible_camera.release()
        if visible_stream_publisher is not None:
            visible_stream_publisher.close()
        if thermal_stream_publisher is not None:
            thermal_stream_publisher.close()
        if yolo_worker is not None:
            yolo_worker.close()
        if auto_roi_worker is not None:
            auto_roi_worker.close()
        if endpoint_pulse_runtime is not None:
            endpoint_pulse_runtime.disarm("collector_shutdown")
        if auto_stop_controller is not None:
            auto_stop_controller.close()
        if live_server is not None:
            live_server.close()
        if pump_serial_bridge is not None:
            pump_serial_bridge.close()
        close = getattr(converter, "close", None)
        if callable(close):
            close()

    total_elapsed_s = time.perf_counter() - start
    write_rows(output, rows)
    first_time_s = float(rows[0]["time_s"]) if rows else 0.0
    last_time_s = float(rows[-1]["time_s"]) if rows else 0.0
    capture_span_s = max(0.0, last_time_s - first_time_s)
    sync_summary = summarize_sync(rows)
    final_visible_roi, final_thermal_roi = roi_state.snapshot()
    final_roi_status = roi_state.status()
    final_controls = live_controls.snapshot()
    if final_thermal_roi is None:
        final_thermal_roi = args.thermal_roi
    summary = {
        "output_csv": str(output),
        "frames": len(rows),
        "visible_frames": visible_worker.count if visible_worker is not None else visible_frames,
        "elapsed_s": round(total_elapsed_s, 6),
        "measured_loop_fps": round(len(rows) / total_elapsed_s, 6) if total_elapsed_s > 0 and rows else 0.0,
        "first_frame_time_s": round(first_time_s, 6),
        "last_frame_time_s": round(last_time_s, 6),
        "capture_span_s": round(capture_span_s, 6),
        "capture_span_fps": round((len(rows) - 1) / capture_span_s, 6) if len(rows) > 1 and capture_span_s > 0 else 0.0,
        "target_frame_rate_hz": float(args.frame_rate_hz),
        "mini2_index": resolved_mini2_index,
        "mini2_backend": args.mini2_backend,
        "mini2_frame": f"{args.mini2_width}x{args.mini2_height} {args.mini2_fourcc}",
        "visible_index": None if visible_camera is None else resolved_visible_index,
        "mini2_dropped_frames": 0 if mini2_worker is None else mini2_worker.recording_dropped_frames,
        "mini2_preview_dropped_frames": 0 if mini2_worker is None else mini2_worker.preview_dropped_frames,
        "mini2_recording_dropped_frames": 0 if mini2_worker is None else mini2_worker.recording_dropped_frames,
        "mini2_recording_status": {} if mini2_worker is None else mini2_worker.recording_status(),
        "mini2_retry_count": mini2_retry_count,
        "mini2_reconnect_count": mini2_reconnect_count,
        "mini2_retry_interval_s": mini2_retry_interval_s,
        "visible_roi": args.visible_roi if final_visible_roi is None else roi_to_string(final_visible_roi),
        "thermal_roi": roi_to_string(final_thermal_roi),
        "roi_state": final_roi_status.get("roi_state", ""),
        "roi_locked": final_roi_status.get("roi_locked", False),
        "roi_session_id": final_roi_status.get("roi_session_id", 0),
        "roi_link_mode": str(getattr(args, "roi_link_mode", "anchor")),
        "roi_auto_detect": str(getattr(args, "roi_auto_detect", "off")),
        "visible_roi_detector": visible_roi_detector,
        "yolo_model": str(getattr(args, "yolo_model", "")) if visible_roi_detector == "yolo" else "",
        "converter": "mini2_unavailable" if mini2_reader is None else ("none_raw_preview" if converter is None else converter.model_name),
        "calibration_source": "mini2_unavailable" if mini2_reader is None else ("none_raw_preview" if converter is None else converter.calibration_source),
        "full_matrix_csv_saved": False,
        "thermal_processing": args.thermal_processing,
        "thermal_rotation_degrees": int(final_controls.get("thermal_rotation_degrees", 0) or 0),
        **sync_summary,
    }
    output.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved Windows live feature CSV: {output}")
    print(f"saved summary: {output.with_suffix('.summary.json')}")
    return output


def write_rows(output: Path, rows: list[dict[str, Any]]) -> None:
    ordered = csv_fieldnames_for_rows(rows)
    temp_output = output.with_name(f"{output.name}.tmp")
    with temp_output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ordered)
        writer.writeheader()
        writer.writerows(rows)
    temp_output.replace(output)


def rgb_bmp_bytes(frame_rgb: np.ndarray) -> bytes:
    """Return an RGB uint8 frame as browser-readable 24-bit BMP bytes."""

    arr = np.asarray(frame_rgb)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("visible preview frame must have shape HxWx3")
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    height, width = arr.shape[:2]
    row_bytes = width * 3
    padding = (4 - (row_bytes % 4)) % 4
    pixel_rows = []
    for y in range(height - 1, -1, -1):
        pixel_rows.append(np.ascontiguousarray(arr[y, :, ::-1]).tobytes() + (b"\x00" * padding))
    pixel_data = b"".join(pixel_rows)
    file_size = 54 + len(pixel_data)
    header = bytearray()
    header.extend(b"BM")
    header.extend(int(file_size).to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend((54).to_bytes(4, "little"))
    header.extend((40).to_bytes(4, "little"))
    header.extend(int(width).to_bytes(4, "little", signed=True))
    header.extend(int(height).to_bytes(4, "little", signed=True))
    header.extend((1).to_bytes(2, "little"))
    header.extend((24).to_bytes(2, "little"))
    header.extend((0).to_bytes(4, "little"))
    header.extend(int(len(pixel_data)).to_bytes(4, "little"))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((2835).to_bytes(4, "little", signed=True))
    header.extend((0).to_bytes(4, "little"))
    header.extend((0).to_bytes(4, "little"))
    return bytes(header) + pixel_data


def jpeg_bytes(frame_rgb: np.ndarray, *, quality: int = 75) -> bytes:
    """Return an RGB frame encoded as JPEG for MJPEG browser streaming."""

    arr = np.asarray(frame_rgb)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("stream frame must have shape HxWx3")
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - OpenCV is a runtime dependency for this tool.
        raise RuntimeError("OpenCV is required for MJPEG streaming") from exc
    bgr = np.ascontiguousarray(arr[:, :, ::-1])
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), max(1, min(100, int(quality)))]
    ok, encoded = cv2.imencode(".jpg", bgr, encode_params)
    if not ok:
        raise RuntimeError("failed to encode live stream JPEG frame")
    return encoded.tobytes()


def write_rgb_bmp(path: Path, frame_rgb: np.ndarray) -> None:
    """Write an RGB uint8 frame as a browser-readable 24-bit BMP without extra deps."""

    path.write_bytes(rgb_bmp_bytes(frame_rgb))


def write_live_bytes(path: Path, data: bytes, *, attempts: int = 12, delay_s: float = 0.04) -> bool:
    """Best-effort live-file update that tolerates Windows browser/server locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    last_error: OSError | None = None
    for _ in range(max(1, attempts)):
        try:
            tmp_path.write_bytes(data)
            os.replace(tmp_path, path)
            return True
        except OSError as exc:
            last_error = exc
            time.sleep(delay_s)

    # If replacing is blocked because the web server/browser is briefly reading
    # the destination on Windows, try an in-place write.  This is less atomic,
    # but the next 25 fps frame will correct any transient partial read.
    for _ in range(max(1, attempts)):
        try:
            path.write_bytes(data)
            try:
                tmp_path.unlink()
            except OSError:
                pass
            return True
        except OSError as exc:
            last_error = exc
            time.sleep(delay_s)

    print(f"Warning: could not update live preview file {path}: {last_error}", flush=True)
    return False


def _json_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(parsed):
        return None
    return round(parsed, 6)


def raw_matrix_to_rgb_preview(raw_matrix: np.ndarray) -> np.ndarray:
    """Convert a Mini2 raw uint16 matrix to an 8-bit grayscale RGB preview."""

    matrix = np.asarray(raw_matrix)
    if matrix.ndim != 2:
        raise ValueError("Mini2 raw preview matrix must be 2D")
    matrix_f = matrix.astype(np.float32)
    # Percentile limits are only for the browser palette.  Estimate them from a
    # regular sample while still rendering every pixel; this keeps 25 fps JPEG
    # preview work away from the scientific feature path.
    sample_step = max(1, int(np.sqrt(max(1, matrix_f.size // 4096))))
    sample = matrix_f[::sample_step, ::sample_step]
    low = float(np.percentile(sample, 1))
    high = float(np.percentile(sample, 99))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        low = float(np.min(matrix_f))
        high = float(np.max(matrix_f))
    if high <= low:
        gray = np.zeros(matrix.shape, dtype=np.uint8)
    else:
        gray = np.clip((matrix_f - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
    return np.repeat(gray[:, :, None], 3, axis=2)


def roi_to_string(roi: Roi | None) -> str:
    if roi is None:
        return ""
    return f"{roi.x},{roi.y},{roi.width},{roi.height}"


def draw_roi_overlay(frame_rgb: np.ndarray, roi: Roi | None, *, color: tuple[int, int, int] = (0, 255, 80), thickness: int = 2) -> np.ndarray:
    """Draw an ROI rectangle on an RGB preview frame without OpenCV dependency."""

    arr = np.asarray(frame_rgb).copy()
    if roi is None:
        return arr
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("ROI overlay frame must have shape HxWx3")
    h, w = arr.shape[:2]
    x0 = max(0, min(w - 1, int(roi.x)))
    y0 = max(0, min(h - 1, int(roi.y)))
    x1 = max(0, min(w, int(roi.x + roi.width)))
    y1 = max(0, min(h, int(roi.y + roi.height)))
    if x1 <= x0 or y1 <= y0:
        return arr
    t = max(1, int(thickness))
    rgb = np.array(color, dtype=np.uint8)
    arr[y0 : min(y0 + t, y1), x0:x1] = rgb
    arr[max(y0, y1 - t) : y1, x0:x1] = rgb
    arr[y0:y1, x0 : min(x0 + t, x1)] = rgb
    arr[y0:y1, max(x0, x1 - t) : x1] = rgb
    return arr


def draw_mask_overlay(
    frame_rgb: np.ndarray,
    roi_mask: RoiMask | None,
    *,
    color: tuple[int, int, int] = (0, 255, 80),
    alpha: float = 0.35,
) -> np.ndarray:
    """Draw a shape mask overlay without converting it back to a rectangle."""

    arr = np.asarray(frame_rgb).copy()
    if roi_mask is None:
        return arr
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError("mask overlay frame must have shape HxWx3")
    if roi_mask.mask.shape != arr.shape[:2]:
        raise ValueError("mask shape must match overlay frame shape")
    mask = roi_mask.mask.astype(bool)
    if not bool(np.any(mask)):
        return arr
    rgb = np.array(color, dtype=np.float64)
    a = max(0.0, min(1.0, float(alpha)))
    arr_f = arr.astype(np.float64)
    arr_f[mask] = arr_f[mask] * (1.0 - a) + rgb * a

    # Compute a cheap 4-neighbor contour so the shown ROI follows the object
    # outline instead of only its bounding box.
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    neighbors = (
        padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )
    contour = mask & ~neighbors
    arr_f[contour] = rgb
    return np.clip(arr_f, 0, 255).astype(np.uint8)


def build_visible_stream_frame(frame_rgb: np.ndarray, roi_state: RoiSelectionState) -> np.ndarray:
    """Return a visible-camera preview frame with the latest visible ROI overlay."""

    visible_roi, _ = roi_state.snapshot()
    visible_mask, _ = roi_state.snapshot_masks()
    if visible_mask is not None and visible_mask.mask.shape == frame_rgb.shape[:2]:
        return draw_mask_overlay(frame_rgb, visible_mask, color=(0, 102, 255))
    return draw_roi_overlay(frame_rgb, visible_roi, color=(0, 102, 255))


def build_thermal_stream_frame(raw_matrix: np.ndarray, roi_state: RoiSelectionState) -> np.ndarray:
    """Return a Mini2 raw preview frame with the latest thermal ROI overlay."""

    thermal_preview = raw_matrix_to_rgb_preview(raw_matrix)
    _, thermal_roi = roi_state.snapshot()
    _, thermal_mask = roi_state.snapshot_masks()
    if thermal_mask is not None and thermal_mask.mask.shape == raw_matrix.shape:
        return draw_mask_overlay(thermal_preview, thermal_mask, color=(0, 255, 80))
    return draw_roi_overlay(thermal_preview, thermal_roi, color=(0, 255, 80))


def build_live_payload(
    thermal_features: dict[str, object],
    row: dict[str, Any],
    *,
    visible_roi: Roi | None = None,
    thermal_roi: Roi | None = None,
    visible_mask: RoiMask | None = None,
    thermal_mask: RoiMask | None = None,
    csv_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the metadata shared by live files, SSE, and JSON API."""
    primary_mask = thermal_mask or visible_mask
    thermal_calibrated = bool(thermal_features.get("thermal_calibrated", False))
    thermal_conversion_status = str(
        thermal_features.get(
            "thermal_conversion_status",
            THERMAL_CONVERSION_OK if thermal_calibrated else THERMAL_CONVERSION_RAW,
        )
    )
    temperature_avg_c = _json_float(thermal_features.get("thermal_roi_avg"))
    temperature_min_c = _json_float(thermal_features.get("thermal_roi_min"))
    temperature_max_c = _json_float(thermal_features.get("thermal_roi_max"))
    celsius_allowed = (
        thermal_calibrated
        and thermal_conversion_status == THERMAL_CONVERSION_OK
        and all(value is not None and math.isfinite(value) for value in (
            temperature_avg_c,
            temperature_min_c,
            temperature_max_c,
        ))
        and temperature_min_c <= temperature_avg_c <= temperature_max_c
    )
    payload = {
        "frame_id": row.get("frame_id"),
        "time_s": _json_float(row.get("time_s")),
        "updated_epoch_s": round(time.time(), 6),
        "pump_elapsed_s": _json_float(row.get("pump_elapsed_s")),
        "pump_run_rate_ml_per_s": _json_float(row.get("pump_run_rate_ml_per_s")),
        "pump_dosing_stage": row.get("pump_dosing_stage", ""),
        "pump_nominal_rate_ml_per_s": _json_float(row.get("pump_nominal_rate_ml_per_s")),
        "pump_rate_basis": row.get("pump_rate_basis", ""),
        "injected_volume_ml": _json_float(row.get("injected_volume_ml")),
        "theoretical_equivalence_volume_ml": _json_float(row.get("theoretical_equivalence_volume_ml")),
        "theoretical_equivalence_time_s": _json_float(row.get("theoretical_equivalence_time_s")),
        "distance_to_equivalence_ml": _json_float(row.get("distance_to_equivalence_ml")),
        "time_to_equivalence_s": _json_float(row.get("time_to_equivalence_s")),
        "equivalence_window_ml": _json_float(row.get("equivalence_window_ml")),
        "equivalence_window_label": row.get("equivalence_window_label", ""),
        "sample_concentration_from_injected_M": _json_float(row.get("sample_concentration_from_injected_M")),
        "sample_concentration_error_percent": _json_float(row.get("sample_concentration_error_percent")),
        "predicted_equivalence_volume_ml": _json_float(row.get("predicted_equivalence_volume_ml")),
        "sample_concentration_from_predicted_equivalence_M": _json_float(row.get("sample_concentration_from_predicted_equivalence_M")),
        "predicted_sample_concentration_error_percent": _json_float(row.get("predicted_sample_concentration_error_percent")),
        "predicted_equivalence_pH": _json_float(row.get("predicted_equivalence_pH")),
        "predicted_equivalence_pH_model": row.get("predicted_equivalence_pH_model", ""),
        "predicted_equivalence_pH_warning": row.get("predicted_equivalence_pH_warning", ""),
        "predicted_equivalence_confidence": _json_float(row.get("predicted_equivalence_confidence")),
        "predicted_equivalence_source": row.get("predicted_equivalence_source", ""),
        "predicted_equivalence_evidence": row.get("predicted_equivalence_evidence", ""),
        "predicted_equivalence_model_key": row.get("predicted_equivalence_model_key", ""),
        "predicted_equivalence_status": row.get("predicted_equivalence_status", PREDICTION_STATUS_PENDING),
        "predicted_equivalence_reason": row.get("predicted_equivalence_reason", "recording_not_finalized"),
        "thermal_mode": thermal_features.get("thermal_source", ""),
        "thermal_calibrated": thermal_calibrated,
        "thermal_conversion_status": thermal_conversion_status,
        "thermal_warning": str(thermal_features.get("warnings", "")),
        "thermal_celsius_fallback_reason": str(thermal_features.get("thermal_celsius_fallback_reason", "")),
        "thermal_conversion_model": str(thermal_features.get("thermal_conversion_model", "")),
        "thermal_conversion_calibration_source": str(thermal_features.get("thermal_conversion_calibration_source", "")),
        "celsius_allowed": celsius_allowed,
        "temperature_provenance": "windows_official_mini2_roi_scalar" if celsius_allowed else "",
        "temperature_scope": "thermal_roi" if celsius_allowed else "",
        "full_matrix_celsius_allowed": False,
        "temperature_avg_c": temperature_avg_c,
        "temperature_min_c": temperature_min_c,
        "temperature_max_c": temperature_max_c,
        "temperature_delta_c": _json_float(thermal_features.get("thermal_roi_delta")),
        "temperature_std_c": _json_float(thermal_features.get("thermal_roi_std")),
        "thermal_roi_range": _json_float(thermal_features.get("thermal_roi_range")),
        "thermal_roi_iqr": _json_float(thermal_features.get("thermal_roi_iqr")),
        "thermal_roi_p05": _json_float(thermal_features.get("thermal_roi_p05")),
        "thermal_roi_p50": _json_float(thermal_features.get("thermal_roi_p50")),
        "thermal_roi_p95": _json_float(thermal_features.get("thermal_roi_p95")),
        "thermal_roi_hot_fraction": _json_float(thermal_features.get("thermal_roi_hot_fraction")),
        "thermal_roi_cold_fraction": _json_float(thermal_features.get("thermal_roi_cold_fraction")),
        "raw_avg": _json_float(thermal_features.get("thermal_raw_roi_avg")),
        "raw_min": _json_float(thermal_features.get("thermal_raw_roi_min")),
        "raw_max": _json_float(thermal_features.get("thermal_raw_roi_max")),
        "raw_delta": _json_float(thermal_features.get("thermal_raw_roi_delta")),
        "thermal_raw_roi_p50": _json_float(thermal_features.get("thermal_raw_roi_p50")),
        "thermal_raw_roi_iqr": _json_float(thermal_features.get("thermal_raw_roi_iqr")),
        "status_label": row.get("status_label", ""),
        "status_confidence": _json_float(row.get("status_confidence")),
        "sync_quality": row.get("sync_quality", ""),
        "sync_offset_ms": _json_float(row.get("sync_offset_ms")),
        "processing_latency_ms": _json_float(row.get("processing_latency_ms")),
        "preview_visible_latency_ms": _json_float(row.get("preview_visible_latency_ms")),
        "latency_mini2_age_ms": _json_float(row.get("processing_latency_ms")),
        "latency_visible_age_ms": _json_float(row.get("preview_visible_latency_ms")),
        "latency_sync_offset_ms": _json_float(row.get("sync_offset_ms")),
        "roi_result_age_ms": _json_float(row.get("auto_roi_result_age_ms")),
        "auto_roi_worker_enabled": bool(row.get("auto_roi_worker_enabled", False)),
        "auto_roi_result_sequence": row.get("auto_roi_result_sequence", 0),
        "auto_roi_result_status": row.get("auto_roi_result_status", ""),
        "auto_roi_result_reason": row.get("auto_roi_result_reason", ""),
        "auto_roi_dropped_pending": row.get("auto_roi_dropped_pending", 0),
        "mini2_dropped_frames": row.get("mini2_dropped_frames", 0),
        "mini2_preview_dropped_frames": row.get("mini2_preview_dropped_frames", 0),
        "mini2_recording_dropped_frames": row.get("mini2_recording_dropped_frames", 0),
        "mini2_recording_backlog_frames": row.get("mini2_recording_backlog_frames", 0),
        "mini2_recording_max_backlog_frames": row.get("mini2_recording_max_backlog_frames", 0),
        "mini2_capture_fps": _json_float(row.get("mini2_capture_fps")),
        "mini2_retry_count": row.get("mini2_retry_count", 0),
        "mini2_reconnect_count": row.get("mini2_reconnect_count", 0),
        "mini2_retry_interval_s": _json_float(row.get("mini2_retry_interval_s")),
        "thermal_roi": roi_to_string(thermal_roi),
        "visible_roi": roi_to_string(visible_roi),
        "roi_state": row.get("roi_state", ""),
        "roi_locked": bool(row.get("roi_locked", False)),
        "roi_session_id": row.get("roi_session_id", 0),
        "roi_source": row.get("roi_source", ""),
        "roi_error": row.get("roi_error", ""),
        "pending_auto_candidate_requests": row.get("pending_auto_candidate_requests", 0),
        "pending_auto_candidate_target": row.get("pending_auto_candidate_target", ""),
        "visible_roi_x": row.get("visible_roi_x", ""),
        "visible_roi_y": row.get("visible_roi_y", ""),
        "visible_roi_width": row.get("visible_roi_width", ""),
        "visible_roi_height": row.get("visible_roi_height", ""),
        "thermal_roi_x": row.get("thermal_roi_x", ""),
        "thermal_roi_y": row.get("thermal_roi_y", ""),
        "thermal_roi_width": row.get("thermal_roi_width", ""),
        "thermal_roi_height": row.get("thermal_roi_height", ""),
        "visible_capture_index": row.get("visible_capture_index", ""),
        "mini2_capture_index": row.get("mini2_capture_index", ""),
        "visible_R_mean": _json_float(row.get("visible_R_mean")),
        "visible_G_mean": _json_float(row.get("visible_G_mean")),
        "visible_B_mean": _json_float(row.get("visible_B_mean")),
        "visible_H_mean": _json_float(row.get("visible_H_mean")),
        "visible_S_mean": _json_float(row.get("visible_S_mean")),
        "visible_V_mean": _json_float(row.get("visible_V_mean")),
        "visible_H_delta": _json_float(row.get("visible_H_delta")),
        "visible_S_delta": _json_float(row.get("visible_S_delta")),
        "visible_V_delta": _json_float(row.get("visible_V_delta")),
        "visible_HSV_delta": _json_float(row.get("visible_HSV_delta")),
        "visible_color_delta": _json_float(row.get("visible_color_delta")),
    }
    if csv_status is None:
        payload.update(
            {
                "csv_session_id": None,
                "csv_row_count": None,
                "csv_rows_per_s": None,
                "csv_path": "",
                "csv_updated_epoch_s": None,
                "csv_recording": False,
                "csv_finalizing": False,
                "csv_state": "idle",
                "csv_download_url": "/api/csv",
                "csv_event_note": "",
                "csv_mark_sequence": 0,
                "csv_recording_elapsed_s": None,
                "csv_recording_started_epoch_s": None,
                "predicted_equivalence_status": PREDICTION_STATUS_PENDING,
                "predicted_equivalence_reason": "recording_not_finalized",
            }
        )
    else:
        for key in (
            "pump_elapsed_s",
            "pump_run_rate_ml_per_s",
            "pump_dosing_stage",
            "pump_nominal_rate_ml_per_s",
            "pump_rate_basis",
            "auto_stop_slow_stage_enabled",
            "auto_stop_slow_rate_steps_per_s",
            "auto_stop_slow_nominal_rate_ml_per_s",
            "injected_volume_ml",
            "theoretical_equivalence_volume_ml",
            "theoretical_equivalence_time_s",
            "distance_to_equivalence_ml",
            "time_to_equivalence_s",
            "equivalence_window_ml",
            "equivalence_window_label",
            "titration_type",
            "sample_name",
            "sample_concentration_M",
            "sample_volume_ml",
            "sample_valence",
            "titrant_name",
            "titrant_concentration_M",
            "titrant_valence",
            "indicator",
            "constants_source",
            "constants_source_id",
            "constants_query",
            "constants_candidate_count",
            "constants_lookup_ambiguous",
            "constants_confirmation_status",
            "constants_warning",
            "selected_pka_type",
            "selected_pka_value",
            "selected_pkb_value",
            "activity_model",
            "ionic_strength_label",
            "activity_warning",
            "theoretical_equivalence_pH",
            "calculated_theoretical_equivalence_volume_ml",
            "sample_concentration_from_theoretical_equivalence_M",
            "equivalence_formula",
            "predicted_equivalence_volume_ml",
            "sample_concentration_from_predicted_equivalence_M",
            "predicted_sample_concentration_error_percent",
            "predicted_equivalence_pH",
            "predicted_equivalence_pH_model",
            "predicted_equivalence_pH_warning",
            "predicted_equivalence_confidence",
            "predicted_equivalence_source",
            "predicted_equivalence_evidence",
            "predicted_equivalence_model_key",
            "indicator_endpoint_volume_ml",
            "indicator_endpoint_offset_ml",
            "standard_solution_uncertainty_note",
        ):
            if payload.get(key) in (None, "") and key in csv_status:
                payload[key] = csv_status.get(key)
        payload.update(
            {
                "csv_session_id": csv_status.get("session_id"),
                "csv_row_count": csv_status.get("row_count"),
                "csv_rows_per_s": _json_float(csv_status.get("csv_rows_per_s")),
                "csv_path": csv_status.get("path", ""),
                "csv_updated_epoch_s": _json_float(csv_status.get("updated_epoch_s")),
                "csv_recording": bool(csv_status.get("recording")),
                "csv_finalizing": bool(csv_status.get("finalizing")),
                "csv_state": csv_status.get("state", ""),
                "csv_download_url": "/api/csv",
                "csv_event_note": csv_status.get("csv_event_note", ""),
                "csv_mark_sequence": csv_status.get("csv_mark_sequence", 0),
                "csv_recording_elapsed_s": _json_float(csv_status.get("recording_elapsed_s")),
                "csv_recording_started_epoch_s": _json_float(csv_status.get("started_epoch_s")),
                "predicted_equivalence_status": csv_status.get(
                    "predicted_equivalence_status", PREDICTION_STATUS_PENDING
                ),
                "predicted_equivalence_reason": csv_status.get(
                    "predicted_equivalence_reason", "recording_not_finalized"
                ),
            }
        )
        if csv_status.get("predicted_equivalence_status") != PREDICTION_STATUS_AVAILABLE:
            for key in (
                "predicted_equivalence_volume_ml",
                "sample_concentration_from_predicted_equivalence_M",
                "predicted_sample_concentration_error_percent",
                "predicted_equivalence_pH",
                "predicted_equivalence_confidence",
            ):
                payload[key] = None
            for key in (
                "predicted_equivalence_pH_model",
                "predicted_equivalence_pH_warning",
                "predicted_equivalence_source",
                "predicted_equivalence_evidence",
                "predicted_equivalence_model_key",
            ):
                payload[key] = ""
    if primary_mask is not None:
        payload.update(
            {
                "roi_shape": "mask",
                "mask_area_px": primary_mask.area_px,
                "mask_confidence": primary_mask.confidence,
                "mask_bbox": primary_mask.bbox_string,
                "mask_component_count": primary_mask.component_count,
                "mask_stability": primary_mask.stability,
            }
        )
    else:
        payload.update(
            {
                "roi_shape": "rectangle",
                "mask_area_px": None,
                "mask_confidence": None,
                "mask_bbox": "",
                "mask_component_count": 0,
                "mask_stability": "",
            }
        )
    if visible_mask is not None:
        payload.update(
            {
                "visible_roi_shape": visible_mask.shape,
                "visible_mask_area_px": visible_mask.area_px,
                "visible_mask_confidence": visible_mask.confidence,
                "visible_mask_bbox": visible_mask.bbox_string,
                "visible_mask_source": visible_mask.source,
                "visible_mask_component_count": visible_mask.component_count,
                "visible_mask_stability": visible_mask.stability,
            }
        )
    else:
        payload.update(
            {
                "visible_roi_shape": "rectangle" if visible_roi is not None else "",
                "visible_mask_area_px": None,
                "visible_mask_confidence": None,
                "visible_mask_bbox": "",
                "visible_mask_source": "",
                "visible_mask_component_count": 0,
                "visible_mask_stability": "",
            }
        )
    if thermal_mask is not None:
        payload.update(
            {
                "thermal_roi_shape": thermal_mask.shape,
                "thermal_mask_area_px": thermal_mask.area_px,
                "thermal_mask_confidence": thermal_mask.confidence,
                "thermal_mask_bbox": thermal_mask.bbox_string,
                "thermal_mask_source": thermal_mask.source,
                "thermal_mask_component_count": thermal_mask.component_count,
                "thermal_mask_stability": thermal_mask.stability,
            }
        )
    else:
        payload.update(
            {
                "thermal_roi_shape": "rectangle" if thermal_roi is not None else "",
                "thermal_mask_area_px": None,
                "thermal_mask_confidence": None,
                "thermal_mask_bbox": "",
                "thermal_mask_source": "",
                "thermal_mask_component_count": 0,
                "thermal_mask_stability": "",
            }
        )
    return payload


def write_live_preview(
    preview_dir: Path,
    frame_rgb: np.ndarray | None,
    thermal_features: dict[str, object],
    row: dict[str, Any],
    *,
    raw_matrix: np.ndarray | None = None,
    visible_roi: Roi | None = None,
    thermal_roi: Roi | None = None,
    visible_mask: RoiMask | None = None,
    thermal_mask: RoiMask | None = None,
) -> None:
    """Write latest visible camera image, Mini2 raw image, and scalar values."""

    preview_dir.mkdir(parents=True, exist_ok=True)
    if frame_rgb is not None:
        visible_overlay = (
            draw_mask_overlay(frame_rgb, visible_mask, color=(0, 102, 255))
            if visible_mask is not None and visible_mask.mask.shape == frame_rgb.shape[:2]
            else draw_roi_overlay(frame_rgb, visible_roi, color=(0, 102, 255))
        )
        write_live_bytes(preview_dir / "visible.bmp", rgb_bmp_bytes(visible_overlay))
    if raw_matrix is not None:
        thermal_preview = raw_matrix_to_rgb_preview(raw_matrix)
        thermal_overlay = (
            draw_mask_overlay(thermal_preview, thermal_mask, color=(0, 255, 80))
            if thermal_mask is not None and thermal_mask.mask.shape == raw_matrix.shape[:2]
            else draw_roi_overlay(thermal_preview, thermal_roi, color=(0, 255, 80))
        )
        write_live_bytes(preview_dir / "thermal.bmp", rgb_bmp_bytes(thermal_overlay))
    payload = build_live_payload(
        thermal_features,
        row,
        visible_roi=visible_roi,
        thermal_roi=thermal_roi,
        visible_mask=visible_mask,
        thermal_mask=thermal_mask,
    )
    write_live_bytes(
        preview_dir / "thermal.json",
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=125)
    parser.add_argument("--frame-rate-hz", type=float, default=MINI2_FRAME_RATE_HZ)
    parser.add_argument(
        "--mini2-recording-queue-frames",
        type=int,
        default=2048,
        help="bounded lossless Mini2 recording FIFO; preview remains latest-only",
    )
    parser.add_argument("--mini2-index", default="auto", help="Mini2 OpenCV camera index, or auto")
    parser.add_argument("--mini2-max-index", type=int, default=10, help="camera indices to probe when --mini2-index auto")
    parser.add_argument("--mini2-backend", default="AUTO", choices=["AUTO", "ANY", "DSHOW", "MSMF"])
    parser.add_argument("--mini2-width", type=int, default=MINI2_UVC_WIDTH)
    parser.add_argument("--mini2-height", type=int, default=MINI2_UVC_HEIGHT)
    parser.add_argument("--mini2-fourcc", default=MINI2_INPUT_FORMAT.upper().replace("YUYV422", "YUY2"))
    parser.add_argument("--allow-mini2-missing", type=int, choices=[0, 1], default=1, help="keep the live website running visible/status-only if Mini2 auto-detection fails")
    parser.add_argument("--mini2-retry-interval-s", type=float, default=3.0, help="seconds between Mini2 reconnect attempts after detection fails; 0 retries every frame")
    parser.add_argument("--visible-index", default="auto", help="visible OpenCV camera index, or auto")
    parser.add_argument("--visible-max-index", type=int, default=10, help="camera indices to probe when --visible-index auto")
    parser.add_argument("--visible-backend", default="MSMF")
    parser.add_argument("--visible-width", type=int, default=640)
    parser.add_argument("--visible-height", type=int, default=480)
    parser.add_argument("--no-visible", action="store_true")
    parser.add_argument("--thermal-roi", type=parse_roi, default=Roi(96, 72, 64, 48))
    parser.add_argument("--thermal-processing", choices=["raw", "roi", "full"], default="raw")
    parser.add_argument("--thermal-rotation-degrees", type=int, choices=[0, 180], default=0, help="rotate Mini2 thermal matrix, ROI, and preview by 0 or 180 degrees")
    parser.add_argument("--visible-roi", default="auto", help="x,y,width,height or auto")
    parser.add_argument("--metadata-jpeg", default=default_metadata_jpeg())
    parser.add_argument("--dll-dir", default=default_dll_dir())
    parser.add_argument("--output", default=str(ROOT / "data" / "raw" / "windows-live-mini2-visible.csv"))
    parser.add_argument(
        "--endpoint-ml-model",
        default=str(DEFAULT_ENDPOINT_ML_MODEL),
        help="trusted type-conditioned sensor ranker used after CSV recording stops; empty disables",
    )
    parser.add_argument(
        "--typewise-ml-model",
        default=str(DEFAULT_TYPEWISE_LIVE_ML_MODEL),
        help="trusted causal classifier used by optional auto-stop and as post-run fallback; empty disables",
    )
    parser.add_argument(
        "--ml-model",
        default=str(DEFAULT_LIVE_ML_MODEL),
        help="legacy simple JSON regression model used only after leakage safety checks; empty disables",
    )
    parser.add_argument("--stream-every", type=int, default=0, help="legacy whole-CSV rewrite interval; keep 0 for low-latency SSE/in-memory recording")
    parser.add_argument("--preview-dir", default=str(ROOT / "website" / "live"), help="write latest visible.bmp and thermal.json for the web app; empty disables")
    parser.add_argument("--preview-every", type=int, default=0, help="legacy BMP/JSON preview interval; keep 0 when MJPEG/SSE is enabled")
    parser.add_argument("--live-stream-host", default="127.0.0.1", help="host for low-latency MJPEG/SSE browser stream")
    parser.add_argument("--live-stream-port", type=int, default=0, help="port for low-latency MJPEG/SSE browser stream; 0 disables")
    parser.add_argument("--live-stream-jpeg-quality", type=int, default=75, help="JPEG quality for MJPEG preview frames")
    parser.add_argument("--roi-click-enabled", type=int, choices=[0, 1], default=1, help="enable browser /api/roi-click selection")
    parser.add_argument("--roi-link-mode", choices=["off", "anchor"], default="anchor", help="how to link visible ROI clicks to thermal ROI")
    parser.add_argument("--roi-auto-detect", choices=["off", "visible", "thermal", "both"], default="off", help="optional setup-only automatic ROI recognition; keep off during locked recording")
    parser.add_argument("--visible-roi-detector", choices=["yolo"], default="yolo", help="visible-camera ROI detector: YOLO only")
    parser.add_argument("--yolo-model", default="yolo11n-seg.pt", help="Ultralytics YOLO model used when --visible-roi-detector yolo")
    parser.add_argument("--yolo-classes", default="cup,bottle,wine glass,bowl,vase,beaker,flask,glass,container", help="comma-separated YOLO class names accepted as flask/beaker candidates")
    parser.add_argument("--yolo-min-confidence", type=float, default=0.25, help="minimum YOLO detection confidence before ROI filtering")
    parser.add_argument("--yolo-max-area-fraction", type=float, default=0.45, help="reject YOLO visible candidates covering more than this frame fraction")
    parser.add_argument("--yolo-min-interval-ms", type=float, default=1000.0, help="minimum milliseconds between YOLO attempts while no stable ROI exists")
    parser.add_argument("--yolo-success-interval-ms", type=float, default=5000.0, help="minimum milliseconds between YOLO refreshes after a valid ROI is found")
    parser.add_argument("--yolo-input-size", type=int, default=256, help="YOLO inference image size; lower values reduce latency")
    parser.add_argument("--roi-auto-min-confidence", type=float, default=0.5, help="minimum confidence required to accept automatic ROI")
    parser.add_argument("--roi-auto-every", type=int, default=25, help="run optional automatic ROI recognition every N frames while ROI is unlocked; 0 disables")
    parser.add_argument("--auto-roi-worker", type=int, choices=[0, 1], default=0, help="move thermal auto ROI detection to a latest-only background worker")
    parser.add_argument("--auto-roi-result-max-age-ms", type=float, default=2000.0, help="discard background auto ROI results older than this many milliseconds")
    parser.add_argument("--sync-method", choices=["nearest"], default="nearest")
    parser.add_argument("--max-sync-offset-ms", type=float, default=40.0)
    parser.add_argument("--visible-sync-max-age-ms", type=float, default=1000.0, help="reject visible frames older than this sync window; 0 disables the age guard")
    parser.add_argument(
        "--visible-future-wait-ms",
        type=float,
        default=10.0,
        help="maximum wait for a closer visible frame; bounded to protect live latency",
    )
    parser.add_argument("--pump-serial-port", default=os.environ.get("PUMP_SERIAL_PORT", ""), help="Arduino pump serial port, COM3, auto, or empty/off to disable")
    parser.add_argument("--pump-serial-baud", type=int, default=int(os.environ.get("PUMP_SERIAL_BAUD", "9600") or 9600), help="Arduino pump serial baud; original sketch uses 9600")
    parser.add_argument("--pump-serial-retry-interval-s", type=float, default=float(os.environ.get("PUMP_SERIAL_RETRY_INTERVAL_S", "2.0") or 2.0), help="seconds between Arduino auto-port reconnect attempts when --pump-serial-port=auto")
    parser.add_argument("--pump-serial-protocol", choices=["auto", "ack", "legacy"], default=os.environ.get("PUMP_SERIAL_PROTOCOL", "auto"), help="auto-detect current acknowledged firmware or original byte-only a/b/c firmware")
    parser.add_argument("--pump-start-command", choices=["a", "b", "c"], default=os.environ.get("PUMP_START_COMMAND", "b"), help="command sent when CSV recording starts")
    parser.add_argument("--pump-retract-command", choices=["a", "b", "c"], default=os.environ.get("PUMP_RETRACT_COMMAND", "a"), help="command sent by the pull-back button")
    parser.add_argument("--pump-stop-command", choices=["a", "b", "c"], default=os.environ.get("PUMP_STOP_COMMAND", "c"), help="command sent when CSV recording stops")
    parser.add_argument("--pump-pulse-direction", choices=["a", "b"], default=os.environ.get("PUMP_PULSE_DIRECTION", "b"), help="physical direction used by firmware STEP pulses")
    parser.add_argument("--print-every", type=int, default=5)
    args = parser.parse_args(argv)
    if args.frames <= 0:
        parser.error("--frames must be positive")
    if args.mini2_index.strip().lower() != "auto":
        try:
            args.mini2_index = int(args.mini2_index)
        except ValueError:
            parser.error("--mini2-index must be an integer camera index or auto")
        if args.mini2_index < 0:
            parser.error("--mini2-index must be non-negative or auto")
    else:
        args.mini2_index = "auto"
    if args.mini2_max_index <= 0:
        parser.error("--mini2-max-index must be positive")
    if args.visible_index.strip().lower() != "auto":
        try:
            args.visible_index = int(args.visible_index)
        except ValueError:
            parser.error("--visible-index must be an integer camera index or auto")
        if args.visible_index < 0:
            parser.error("--visible-index must be non-negative or auto")
    else:
        args.visible_index = "auto"
    if args.visible_max_index <= 0:
        parser.error("--visible-max-index must be positive")
    if args.stream_every < 0:
        parser.error("--stream-every must be zero or positive")
    if args.preview_every < 0:
        parser.error("--preview-every must be zero or positive")
    if args.live_stream_port < 0:
        parser.error("--live-stream-port must be zero or positive")
    if not 1 <= args.live_stream_jpeg_quality <= 100:
        parser.error("--live-stream-jpeg-quality must be between 1 and 100")
    if args.mini2_recording_queue_frames <= 0:
        parser.error("--mini2-recording-queue-frames must be positive")
    if not 0.0 <= args.yolo_min_confidence <= 1.0:
        parser.error("--yolo-min-confidence must be between 0 and 1")
    if not 0.0 < args.yolo_max_area_fraction <= 1.0:
        parser.error("--yolo-max-area-fraction must be in (0, 1]")
    if args.yolo_min_interval_ms < 0:
        parser.error("--yolo-min-interval-ms must be non-negative")
    if args.yolo_success_interval_ms < 0:
        parser.error("--yolo-success-interval-ms must be non-negative")
    if args.yolo_input_size < 0:
        parser.error("--yolo-input-size must be non-negative")
    if not 0.0 <= args.roi_auto_min_confidence <= 1.0:
        parser.error("--roi-auto-min-confidence must be between 0 and 1")
    if args.roi_auto_every < 0:
        parser.error("--roi-auto-every must be non-negative")
    if args.auto_roi_result_max_age_ms < 0:
        parser.error("--auto-roi-result-max-age-ms must be non-negative")
    if args.max_sync_offset_ms <= 0:
        parser.error("--max-sync-offset-ms must be positive")
    if args.visible_sync_max_age_ms < 0:
        parser.error("--visible-sync-max-age-ms must be non-negative")
    if args.visible_future_wait_ms < 0:
        parser.error("--visible-future-wait-ms must be non-negative")
    if args.pump_serial_baud <= 0:
        parser.error("--pump-serial-baud must be positive")
    if args.mini2_fourcc.lower() in {"yuyv422", "yuyv"}:
        args.mini2_fourcc = "YUY2"
    if len(args.mini2_fourcc) != 4:
        parser.error("--mini2-fourcc must be a 4-character OpenCV FOURCC, e.g. YUY2")
    instance_lock = CollectorInstanceLock(
        ROOT / ".runtime" / "windows_live_collect.lock"
    )
    try:
        instance_lock.acquire()
    except RuntimeError as exc:
        print(f"Collector start rejected: {exc}", file=sys.stderr, flush=True)
        return 2
    try:
        run(args)
        return 0
    finally:
        instance_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
