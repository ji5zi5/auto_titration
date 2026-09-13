"""Opt-in pump auto-stop based on a model-confirmed visible-ROI color change.

The detector deliberately does not use a theoretical equivalence volume.  It
learns the starting color from the first second of the live run, ignores short
color flashes, and starts its delay only when the causal live classifier also
reports an endpoint-like frame.  Injected volume is used by the trained live
classifier, for audit output, and for the independent physical maximum-volume
safety limit; the run's theoretical equivalence volume is never a stop gate.
"""

from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

import numpy as np

from .typewise_live_model import score_typewise_rows_for_hardware_control


AUTO_STOP_BASELINE_SECONDS = 1.0
AUTO_STOP_CONFIRMATION_SECONDS = 0.4
AUTO_STOP_MAX_VOLUME_ML = 100.0
AUTO_STOP_MIN_COLOR_DISTANCE = 0.018
AUTO_STOP_MIN_ENDPOINT_SCORE = 0.30

# Absolute pump limits are safety ceilings, not calibration or target values.
# A run may request a lower limit, but never a higher one.  Volume enforcement
# requires the caller to supply a measured conservative upper bound for pump
# flow in mL/s; no pump calibration is assumed here.
ABSOLUTE_PUMP_MAX_VOLUME_ML = 100.0
ABSOLUTE_PUMP_MAX_RUN_TIME_S = 120.0
FIRMWARE_GUARD_ARM_PREFIX = "G "
FIRMWARE_GUARD_ACK_PREFIX = "GUARD ARMED "


def _finite_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first_finite(row: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _finite_float(row.get(key))
        if value is not None:
            return value
    return None


def _visible_color_vector(row: Mapping[str, Any]) -> np.ndarray | None:
    values = [
        _finite_float(row.get("visible_R_mean")),
        _finite_float(row.get("visible_G_mean")),
        _finite_float(row.get("visible_B_mean")),
        _finite_float(row.get("visible_H_mean")),
        _finite_float(row.get("visible_S_mean")),
        _finite_float(row.get("visible_V_mean")),
    ]
    if any(value is None for value in values):
        return None
    return np.asarray(values, dtype=np.float64)


def _configure_single_row_model_inference(model: Mapping[str, Any] | None) -> None:
    """Avoid joblib thread-pool overhead when predicting one live row."""

    if model is None:
        return
    models = model.get("models") or {}
    if not isinstance(models, Mapping):
        return
    for entry in models.values():
        if not isinstance(entry, Mapping):
            continue
        estimator = entry.get("estimator")
        candidates = [estimator]
        candidates.extend(step for _, step in getattr(estimator, "steps", []) if step is not None)
        for candidate in candidates:
            if candidate is not None and hasattr(candidate, "n_jobs"):
                try:
                    candidate.n_jobs = 1
                except (AttributeError, TypeError, ValueError):
                    continue


def _color_distance(current: np.ndarray, baseline: np.ndarray) -> float:
    """Return a lighting-resistant RGB/HSV chromatic distance in 0..~1.

    RGB luminance is removed before comparison, hue is down-weighted when the
    ROI is nearly colorless, and value/brightness contributes only 10%.  This
    makes a lamp flicker less likely to look like an indicator transition.
    """

    current_rgb = current[:3] / 255.0
    baseline_rgb = baseline[:3] / 255.0
    current_chroma = current_rgb - float(np.mean(current_rgb))
    baseline_chroma = baseline_rgb - float(np.mean(baseline_rgb))
    rgb_chroma_distance = float(np.linalg.norm(current_chroma - baseline_chroma) / math.sqrt(3.0))

    hue_distance = abs((float(current[3]) - float(baseline[3]) + 180.0) % 360.0 - 180.0) / 180.0
    hue_distance *= max(float(current[4]), float(baseline[4]), 0.02)
    saturation_distance = abs(float(current[4]) - float(baseline[4]))
    hsv_chroma_distance = math.sqrt(hue_distance**2 + saturation_distance**2) / math.sqrt(2.0)
    value_distance = abs(float(current[5]) - float(baseline[5]))
    return 0.45 * rgb_chroma_distance + 0.45 * hsv_chroma_distance + 0.10 * value_distance


class AbsolutePumpSafetyGuard:
    """Own an absolute pump deadline independent of camera/model telemetry.

    ``command_sender`` is a request/response transport for the firmware
    protocol in ``arduino_stepper.ino``.  Guard and direction commands must
    return the exact firmware acknowledgements (or equivalent structured
    mappings).  A pump direction command is sent only after the requested
    guard deadline is confirmed, and the run is considered active only after
    the firmware confirms the same direction and deadline.  Missing or
    mismatched acknowledgements fail closed and attempt ``c``.

    Requested volume is converted to a time ceiling using
    ``maximum_pump_rate_ml_per_s``, a caller-supplied measured conservative
    upper flow bound.  The host monotonic watchdog and firmware deadline use
    the same effective duration, so neither camera rows nor optional color/model
    auto-stop are required for this guard.
    """

    def __init__(
        self,
        command_sender: Callable[[str], Any],
        *,
        direction_sender: Callable[[str, Callable[[], bool]], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        watchdog_interval_s: float = 0.02,
    ) -> None:
        if not callable(command_sender):
            raise TypeError("command_sender must be callable")
        if direction_sender is not None and not callable(direction_sender):
            raise TypeError("direction_sender must be callable")
        self._command_sender = command_sender
        self._direction_sender = direction_sender
        self._monotonic = monotonic
        self._watchdog_interval_s = max(0.001, float(watchdog_interval_s))
        self.application_maximum_volume_ml = ABSOLUTE_PUMP_MAX_VOLUME_ML
        self.application_maximum_run_time_s = ABSOLUTE_PUMP_MAX_RUN_TIME_S
        self._lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._starting = False
        self._running = False
        self._generation = 0
        self._state = "idle"
        self._reason = "not_started"
        self._error = ""
        self._stop_status = "not_requested"
        self._requested_volume_ml = self.application_maximum_volume_ml
        self._effective_volume_ml = self.application_maximum_volume_ml
        self._requested_time_s = self.application_maximum_run_time_s
        self._effective_time_s = self.application_maximum_run_time_s
        self._maximum_pump_rate_ml_per_s = 0.0
        self._firmware_timeout_ms = 0
        self._guard_scope = "firmware_and_host"
        self._deadline_s: float | None = None
        self._direction_written_monotonic_s: float | None = None
        self._limits_clamped = False
        self._thread = threading.Thread(
            target=self._watchdog_loop,
            name="absolute-pump-safety-watchdog",
            daemon=True,
        )
        self._thread.start()

    def start(
        self,
        *,
        direction_command: str,
        maximum_pump_rate_ml_per_s: float,
        requested_maximum_volume_ml: float = ABSOLUTE_PUMP_MAX_VOLUME_ML,
        requested_maximum_run_time_s: float = ABSOLUTE_PUMP_MAX_RUN_TIME_S,
        can_start_direction: Callable[[], bool] | None = None,
        absolute_deadline_monotonic_s: float | None = None,
    ) -> dict[str, Any]:
        """Arm firmware first, then start a bounded ``a`` or ``b`` pump run."""

        if direction_command not in {"a", "b"}:
            raise ValueError("direction_command must be 'a' or 'b'")
        if can_start_direction is not None and not callable(can_start_direction):
            raise TypeError("can_start_direction must be callable")
        rate = _finite_float(maximum_pump_rate_ml_per_s)
        requested_volume = _finite_float(requested_maximum_volume_ml)
        requested_time = _finite_float(requested_maximum_run_time_s)
        absolute_deadline = (
            None
            if absolute_deadline_monotonic_s is None
            else _finite_float(absolute_deadline_monotonic_s)
        )
        if rate is None or rate <= 0:
            raise ValueError("maximum_pump_rate_ml_per_s must be positive and finite")
        if requested_volume is None or requested_volume <= 0:
            raise ValueError("requested_maximum_volume_ml must be positive and finite")
        if requested_time is None or requested_time <= 0:
            raise ValueError("requested_maximum_run_time_s must be positive and finite")
        if absolute_deadline_monotonic_s is not None and absolute_deadline is None:
            raise ValueError("absolute_deadline_monotonic_s must be finite")

        effective_volume = min(requested_volume, self.application_maximum_volume_ml)
        effective_time = min(
            requested_time,
            self.application_maximum_run_time_s,
            effective_volume / rate,
        )
        # Round down so transport quantization cannot increase the safety limit.
        firmware_timeout_ms = int(math.floor(effective_time * 1000.0))
        if firmware_timeout_ms < 1:
            raise ValueError("effective guard duration is below the 1 ms firmware resolution")
        effective_time = firmware_timeout_ms / 1000.0
        with self._lock:
            if self._closed:
                raise RuntimeError("absolute pump safety guard is closed")
            if self._starting or self._running:
                raise RuntimeError("absolute pump safety guard is already running")
            self._generation += 1
            generation = self._generation
            self._starting = True
            self._state = "arming"
            self._reason = "arming_firmware_guard"
            self._error = ""
            self._stop_status = "not_requested"
            self._requested_volume_ml = requested_volume
            self._effective_volume_ml = effective_volume
            self._requested_time_s = requested_time
            self._effective_time_s = effective_time
            self._maximum_pump_rate_ml_per_s = rate
            self._firmware_timeout_ms = firmware_timeout_ms
            self._guard_scope = "firmware_and_host"
            self._deadline_s = None
            self._direction_written_monotonic_s = None
            self._limits_clamped = (
                requested_volume > self.application_maximum_volume_ml
                or requested_time > self.application_maximum_run_time_s
            )

        direction_attempted = False
        started_s: float | None = None
        target_deadline_s: float | None = None
        direction_written_s: float | None = None
        try:
            with self._command_lock:
                guard_command_s = float(self._monotonic())
                if not math.isfinite(guard_command_s):
                    raise RuntimeError("monotonic clock returned a non-finite value")
                target_deadline_s = guard_command_s + effective_time
                if absolute_deadline is not None:
                    target_deadline_s = min(target_deadline_s, absolute_deadline)
                remaining_s = target_deadline_s - guard_command_s
                firmware_timeout_ms = int(math.floor(remaining_s * 1000.0))
                if firmware_timeout_ms < 1:
                    raise RuntimeError("absolute session deadline expired before guard arm")
                effective_time = firmware_timeout_ms / 1000.0
                with self._lock:
                    if self._closed or self._generation != generation:
                        self._starting = False
                        return self._status_locked()
                    self._firmware_timeout_ms = firmware_timeout_ms
                    self._effective_time_s = effective_time
                acknowledgement = self._command_sender(
                    f"{FIRMWARE_GUARD_ARM_PREFIX}{firmware_timeout_ms}\n"
                )
                if not self._guard_acknowledged(acknowledgement, firmware_timeout_ms):
                    raise RuntimeError("firmware did not acknowledge the requested guard deadline")
                guard_scope = self._guard_scope_from_response(acknowledgement)
                with self._lock:
                    if self._closed or self._generation != generation:
                        self._starting = False
                        return self._status_locked()
                    self._guard_scope = guard_scope
                started_s = float(self._monotonic())
                if not math.isfinite(started_s):
                    raise RuntimeError("monotonic clock returned a non-finite value")
                if self._direction_sender is None:
                    # An opaque request/response sender cannot expose the exact
                    # byte-write boundary.  Keep the generation check and the
                    # complete call under the state lock so stop() can never
                    # place c on the wire and then be overtaken by a late a/b.
                    # Production serial bridges use ``direction_sender`` below
                    # to retain emergency-stop pre-emption during ACK waits.
                    with self._lock:
                        if self._closed or self._generation != generation:
                            self._starting = False
                            return self._status_locked()
                        if (
                            float(self._monotonic()) >= float(target_deadline_s)
                            or (can_start_direction is not None and not can_start_direction())
                        ):
                            raise RuntimeError("guarded direction cancelled before write")
                        direction_attempted = True
                        direction_written_s = float(self._monotonic())
                        direction_acknowledgement = self._command_sender(
                            direction_command
                        )
                else:
                    def direction_still_allowed() -> bool:
                        with self._lock:
                            return (
                                not self._closed
                                and self._generation == generation
                                and float(self._monotonic()) < float(target_deadline_s)
                                and (
                                    can_start_direction is None
                                    or can_start_direction()
                                )
                            )

                    direction_attempted = True
                    direction_acknowledgement = self._direction_sender(
                        direction_command,
                        direction_still_allowed,
                    )
                    if isinstance(direction_acknowledgement, Mapping):
                        direction_written_s = _finite_float(
                            direction_acknowledgement.get("direction_written_monotonic_s")
                        )
                    if (
                        isinstance(direction_acknowledgement, Mapping)
                        and direction_acknowledgement.get("direction_cancelled") is True
                    ):
                        direction_attempted = False
                        with self._lock:
                            if not self._closed and self._generation == generation:
                                raise RuntimeError("guarded direction cancelled before write")
                            self._starting = False
                            return self._status_locked()
                if not self._direction_acknowledged(
                    direction_acknowledgement,
                    direction_command,
                    firmware_timeout_ms,
                ):
                    raise RuntimeError(
                        "firmware did not confirm the requested pump direction and guard deadline"
                    )
        except Exception as exc:  # noqa: BLE001 - any arm/start failure must fail closed.
            with self._command_lock:
                with self._lock:
                    if self._closed or self._generation != generation:
                        self._starting = False
                        return self._status_locked()
                stop_status, stop_error = self._attempt_stop()
            with self._lock:
                self._starting = False
                possibly_running = direction_attempted and bool(stop_error)
                self._running = possibly_running
                self._deadline_s = (
                    target_deadline_s
                    if possibly_running
                    else None
                )
                self._state = "stop_unconfirmed" if possibly_running else "error"
                self._reason = "possibly_running" if possibly_running else "guard_arm_or_start_failed"
                self._error = str(exc) if not stop_error else f"{exc}; stop failed: {stop_error}"
                self._stop_status = stop_status
                status = self._status_locked()
            if possibly_running:
                self._wake.set()
            return status

        with self._lock:
            self._starting = False
            if self._closed or self._generation != generation:
                return self._status_locked()
            self._running = True
            assert started_s is not None
            self._deadline_s = target_deadline_s
            self._direction_written_monotonic_s = direction_written_s or started_s
            self._state = "armed_running"
            self._reason = (
                "absolute_limits_armed_host_only"
                if self._guard_scope == "host_only"
                else "absolute_limits_armed"
            )
            status = self._status_locked()
        self._wake.set()
        return status

    def stop(
        self,
        reason: str = "manual_stop",
        *,
        emergency_stop: Callable[[], Any] | None = None,
    ) -> dict[str, Any]:
        """Send the compatible ``c`` stop command and expose delivery failure."""

        with self._lock:
            self._generation += 1
            generation = self._generation
            was_active = self._starting or self._running
            self._state = "stopping"
            self._reason = str(reason or "manual_stop")
        # Publish cancellation before the lock-free emergency write. An
        # in-flight start checks this generation after its G acknowledgement,
        # so it cannot send a/b after the emergency callback has put c on the
        # wire. The acknowledged c below remains the authoritative stop.
        if emergency_stop is not None:
            try:
                emergency_stop()
            except Exception:
                # The normal acknowledged stop path must still run. Callers
                # may capture emergency transport diagnostics separately.
                pass
        with self._command_lock:
            stop_status, stop_error = self._attempt_stop()
        with self._lock:
            if generation != self._generation:
                return self._status_locked()
            self._stop_status = stop_status
            if stop_error and was_active:
                self._running = True
                self._state = "stop_unconfirmed"
                self._reason = "possibly_running"
                self._error = stop_error
            elif stop_error:
                self._state = "error"
                self._reason = "stop_command_failed"
                self._error = stop_error
            else:
                self._starting = False
                self._running = False
                self._deadline_s = None
                self._state = "stopped"
                self._reason = str(reason or "manual_stop")
                self._error = ""
            status = self._status_locked()
        self._wake.set()
        return status

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def close(self) -> None:
        with self._lock:
            should_stop = self._starting or self._running
            self._closed = True
        if should_stop:
            self.stop("guard_closed")
        self._wake.set()
        self._thread.join(timeout=2.0)

    @staticmethod
    def _guard_acknowledged(response: Any, requested_timeout_ms: int) -> bool:
        if isinstance(response, str):
            expected = f"{FIRMWARE_GUARD_ACK_PREFIX}{requested_timeout_ms}"
            return response.strip() == expected
        if isinstance(response, Mapping):
            acknowledged = response.get("guard_armed") is True
            timeout = _finite_float(response.get("guard_timeout_ms"))
            return (
                acknowledged
                and timeout is not None
                and timeout == requested_timeout_ms
            )
        return False

    @staticmethod
    def _guard_scope_from_response(response: Any) -> str:
        if isinstance(response, Mapping) and response.get("guard_scope") == "host_only":
            return "host_only"
        return "firmware_and_host"

    @staticmethod
    def _direction_acknowledged(
        response: Any,
        direction_command: str,
        requested_timeout_ms: int,
    ) -> bool:
        expected = f"PUMP RUNNING {direction_command} {requested_timeout_ms}"
        if isinstance(response, str):
            return response.strip() == expected
        if isinstance(response, Mapping):
            firmware_ack = response.get("firmware_ack")
            if isinstance(firmware_ack, str):
                return firmware_ack.strip() == expected
            running = response.get("pump_running") is True
            direction = str(response.get("pump_direction") or "").strip()
            timeout = _finite_float(response.get("guard_timeout_ms"))
            return (
                running
                and direction == direction_command
                and timeout is not None
                and timeout == requested_timeout_ms
            )
        return False

    def _watchdog_loop(self) -> None:
        while True:
            self._wake.wait(self._watchdog_interval_s)
            self._wake.clear()
            with self._lock:
                if self._closed:
                    return
                running = self._running
                deadline_s = self._deadline_s
            if not running or deadline_s is None:
                continue
            try:
                expired = float(self._monotonic()) >= deadline_s
            except Exception as exc:  # noqa: BLE001 - clock failure must request a stop.
                self._deadline_stop("host_monotonic_clock_failed", str(exc))
                continue
            if expired:
                self._deadline_stop("absolute_deadline_reached", "")

    def _deadline_stop(self, reason: str, clock_error: str) -> None:
        with self._lock:
            if not self._running:
                return
            self._generation += 1
            generation = self._generation
            self._state = "stopping"
            self._reason = reason
        with self._command_lock:
            stop_status, stop_error = self._attempt_stop()
        with self._lock:
            if generation != self._generation:
                return
            self._stop_status = stop_status
            self._reason = reason
            if stop_error:
                self._state = "stop_unconfirmed"
                self._reason = "possibly_running"
                details = f"stop failed: {stop_error}"
                self._error = f"{clock_error}; {details}" if clock_error else details
            else:
                self._running = False
                self._deadline_s = None
                self._state = "triggered"
                self._error = clock_error

    def _attempt_stop(self) -> tuple[str, str]:
        try:
            self._command_sender("c")
        except Exception as exc:  # noqa: BLE001 - status must retain transport failure.
            return "failed", str(exc)
        return "sent", ""

    def _status_locked(self) -> dict[str, Any]:
        return {
            "absolute_guard_armed": self._running,
            "absolute_guard_possibly_running": self._running,
            "absolute_guard_state": self._state,
            "absolute_guard_reason": self._reason,
            "absolute_guard_error": self._error,
            "absolute_guard_stop_status": self._stop_status,
            "absolute_guard_units": {
                "volume": "mL",
                "time": "s",
                "flow_rate": "mL/s",
                "firmware_timeout": "ms",
            },
            "absolute_guard_requested_maximum_volume_ml": round(self._requested_volume_ml, 6),
            "absolute_guard_effective_maximum_volume_ml": round(self._effective_volume_ml, 6),
            "absolute_guard_application_maximum_volume_ml": round(
                self.application_maximum_volume_ml, 6
            ),
            "absolute_guard_requested_maximum_run_time_s": round(self._requested_time_s, 6),
            "absolute_guard_effective_maximum_run_time_s": round(self._effective_time_s, 6),
            "absolute_guard_application_maximum_run_time_s": round(
                self.application_maximum_run_time_s, 6
            ),
            "absolute_guard_maximum_pump_rate_ml_per_s": round(
                self._maximum_pump_rate_ml_per_s, 6
            ),
            "absolute_guard_firmware_timeout_ms": self._firmware_timeout_ms,
            "absolute_guard_deadline_monotonic_s": self._deadline_s,
            "direction_written_monotonic_s": self._direction_written_monotonic_s,
            "absolute_guard_scope": self._guard_scope,
            "absolute_guard_limits_clamped": self._limits_clamped,
        }


@dataclass(frozen=True)
class AutoStopDecision:
    session_id: int
    reason: str
    trigger_volume_ml: float | None
    trigger_elapsed_s: float
    color_change_started_volume_ml: float | None
    color_change_started_elapsed_s: float | None
    color_distance: float | None
    color_threshold: float | None
    endpoint_score: float | None
    endpoint_score_threshold: float
    confirmation_delay_s: float
    maximum_volume_ml: float

    def as_status(self) -> dict[str, Any]:
        values = asdict(self)
        return {
            "auto_stop_state": "triggered",
            "auto_stop_triggered": True,
            "auto_stop_reason": values["reason"],
            "auto_stop_trigger_volume_ml": ""
            if values["trigger_volume_ml"] is None
            else round(float(values["trigger_volume_ml"]), 6),
            "auto_stop_trigger_elapsed_s": round(float(values["trigger_elapsed_s"]), 6),
            "auto_stop_color_change_started_volume_ml": ""
            if values["color_change_started_volume_ml"] is None
            else round(float(values["color_change_started_volume_ml"]), 6),
            "auto_stop_color_change_started_elapsed_s": ""
            if values["color_change_started_elapsed_s"] is None
            else round(float(values["color_change_started_elapsed_s"]), 6),
            "auto_stop_color_distance": ""
            if values["color_distance"] is None
            else round(float(values["color_distance"]), 6),
            "auto_stop_color_threshold": ""
            if values["color_threshold"] is None
            else round(float(values["color_threshold"]), 6),
            "auto_stop_endpoint_score": ""
            if values["endpoint_score"] is None
            else round(float(values["endpoint_score"]), 6),
            "auto_stop_endpoint_score_threshold": round(float(values["endpoint_score_threshold"]), 6),
            "auto_stop_confirmation_delay_s": round(float(values["confirmation_delay_s"]), 6),
            "auto_stop_maximum_volume_ml": round(float(values["maximum_volume_ml"]), 6),
        }


class PersistentColorAutoStopDetector:
    """Detect a stable color transition relative to the live starting color."""

    def __init__(
        self,
        *,
        session_id: int,
        baseline_seconds: float = AUTO_STOP_BASELINE_SECONDS,
        confirmation_delay_s: float = AUTO_STOP_CONFIRMATION_SECONDS,
        maximum_volume_ml: float = AUTO_STOP_MAX_VOLUME_ML,
        minimum_color_distance: float = AUTO_STOP_MIN_COLOR_DISTANCE,
        minimum_endpoint_score: float = AUTO_STOP_MIN_ENDPOINT_SCORE,
        minimum_baseline_samples: int = 8,
        noise_multiplier: float = 8.0,
        release_ratio: float = 0.65,
        dropout_tolerance_s: float = 0.12,
        maximum_sample_gap_s: float | None = None,
        baseline_adaptation_time_s: float = 12.0,
    ) -> None:
        if session_id <= 0:
            raise ValueError("session_id must be positive")
        if baseline_seconds <= 0 or confirmation_delay_s <= 0:
            raise ValueError("auto-stop timing values must be positive")
        if maximum_volume_ml <= 0 or minimum_color_distance <= 0:
            raise ValueError("auto-stop limits must be positive")
        if not 0 < minimum_endpoint_score <= 1:
            raise ValueError("minimum_endpoint_score must be in 0..1")
        if minimum_baseline_samples < 3:
            raise ValueError("minimum_baseline_samples must be at least 3")
        if not 0 < release_ratio < 1:
            raise ValueError("release_ratio must be between 0 and 1")
        if maximum_sample_gap_s is not None and maximum_sample_gap_s <= 0:
            raise ValueError("maximum_sample_gap_s must be positive")
        self.session_id = int(session_id)
        self.baseline_seconds = float(baseline_seconds)
        self.confirmation_delay_s = float(confirmation_delay_s)
        self.maximum_volume_ml = float(maximum_volume_ml)
        self.minimum_color_distance = float(minimum_color_distance)
        self.minimum_endpoint_score = float(minimum_endpoint_score)
        self.minimum_baseline_samples = int(minimum_baseline_samples)
        self.noise_multiplier = float(noise_multiplier)
        self.release_ratio = float(release_ratio)
        self.dropout_tolerance_s = float(dropout_tolerance_s)
        self.maximum_sample_gap_s = (
            max(self.dropout_tolerance_s, min(0.2, self.confirmation_delay_s))
            if maximum_sample_gap_s is None
            else float(maximum_sample_gap_s)
        )
        self.baseline_adaptation_time_s = float(baseline_adaptation_time_s)

        self._time_origin_s: float | None = None
        self._last_elapsed_s: float | None = None
        self._last_valid_color_elapsed_s: float | None = None
        self._baseline_samples: list[np.ndarray] = []
        self._baseline: np.ndarray | None = None
        self._threshold: float | None = None
        self._latest_distance: float | None = None
        self._latest_elapsed_s: float | None = None
        self._latest_volume_ml: float | None = None
        self._change_started_elapsed_s: float | None = None
        self._change_started_volume_ml: float | None = None
        self._last_above_elapsed_s: float | None = None
        self._candidate_peak_distance: float | None = None
        self._candidate_endpoint_score: float | None = None
        self._latest_endpoint_score: float | None = None
        self._triggered = False
        self._missing_color_samples = 0

    def observe(
        self,
        row: Mapping[str, Any],
        *,
        endpoint_score: float | None = None,
    ) -> AutoStopDecision | None:
        if self._triggered:
            return None
        source_elapsed = _first_finite(row, "csv_recording_elapsed_s", "pump_elapsed_s", "time_s")
        if source_elapsed is None:
            return None
        if self._time_origin_s is None:
            self._time_origin_s = source_elapsed
        elapsed_s = max(0.0, source_elapsed - self._time_origin_s)
        volume_ml = _finite_float(row.get("injected_volume_ml"))
        self._latest_elapsed_s = elapsed_s
        self._latest_volume_ml = volume_ml

        if volume_ml is not None and volume_ml >= self.maximum_volume_ml:
            return self._trigger(
                reason="safety_maximum_volume",
                elapsed_s=elapsed_s,
                volume_ml=volume_ml,
            )

        color = _visible_color_vector(row)
        if color is None:
            self._missing_color_samples += 1
            self._reset_candidate()
            self._last_valid_color_elapsed_s = None
            self._last_elapsed_s = elapsed_s
            return None

        previous_valid_elapsed_s = self._last_valid_color_elapsed_s
        sample_gap_s = (
            None
            if previous_valid_elapsed_s is None
            else elapsed_s - previous_valid_elapsed_s
        )
        continuous_sample = (
            sample_gap_s is None
            or 0.0 < sample_gap_s <= self.maximum_sample_gap_s + 1e-9
        )
        if not continuous_sample:
            self._reset_candidate()
        self._last_valid_color_elapsed_s = elapsed_s

        if self._baseline is None:
            self._baseline_samples.append(color)
            enough_time = elapsed_s >= self.baseline_seconds
            enough_samples = len(self._baseline_samples) >= self.minimum_baseline_samples
            if enough_time and enough_samples:
                self._finish_baseline_calibration()
            self._last_elapsed_s = elapsed_s
            return None

        distance = _color_distance(color, self._baseline)
        self._latest_distance = distance
        parsed_score = _finite_float(endpoint_score)
        if parsed_score is not None:
            parsed_score = max(0.0, min(1.0, parsed_score))
        self._latest_endpoint_score = parsed_score
        threshold = float(self._threshold or self.minimum_color_distance)
        release_threshold = threshold * self.release_ratio
        endpoint_candidate = (
            distance >= threshold
            and parsed_score is not None
            and parsed_score >= self.minimum_endpoint_score
        )

        if self._change_started_elapsed_s is None and endpoint_candidate:
            self._change_started_elapsed_s = elapsed_s
            self._change_started_volume_ml = volume_ml
            self._candidate_peak_distance = distance
            self._candidate_endpoint_score = parsed_score
            self._last_above_elapsed_s = elapsed_s
        elif self._change_started_elapsed_s is not None:
            if distance >= threshold:
                self._candidate_peak_distance = max(float(self._candidate_peak_distance or 0.0), distance)
                self._last_above_elapsed_s = elapsed_s
            if parsed_score is not None:
                self._candidate_endpoint_score = max(float(self._candidate_endpoint_score or 0.0), parsed_score)
            last_above = self._last_above_elapsed_s
            if distance < release_threshold and (
                last_above is None or elapsed_s - last_above > self.dropout_tolerance_s
            ):
                self._reset_candidate()
            elif elapsed_s - self._change_started_elapsed_s >= self.confirmation_delay_s:
                return self._trigger(
                    reason="persistent_color_change",
                    elapsed_s=elapsed_s,
                    volume_ml=volume_ml,
                )
        elif distance < release_threshold:
            self._adapt_baseline(color, elapsed_s)

        self._last_elapsed_s = elapsed_s
        return None

    def _finish_baseline_calibration(self) -> None:
        samples = np.asarray(self._baseline_samples, dtype=np.float64)
        baseline = np.median(samples, axis=0)
        noise = np.asarray([_color_distance(sample, baseline) for sample in samples], dtype=np.float64)
        median_noise = float(np.median(noise))
        mad = float(np.median(np.abs(noise - median_noise)))
        robust_sigma = 1.4826 * mad
        self._baseline = baseline
        self._threshold = max(
            self.minimum_color_distance,
            median_noise + self.noise_multiplier * robust_sigma,
        )

    def _adapt_baseline(self, color: np.ndarray, elapsed_s: float) -> None:
        if self._baseline is None:
            return
        previous_elapsed = self._last_elapsed_s
        delta_s = 0.04 if previous_elapsed is None else max(0.001, elapsed_s - previous_elapsed)
        alpha = min(0.05, 1.0 - math.exp(-delta_s / self.baseline_adaptation_time_s))
        # Hue needs circular interpolation; the remaining components are linear.
        hue_delta = (float(color[3]) - float(self._baseline[3]) + 180.0) % 360.0 - 180.0
        self._baseline[:3] += alpha * (color[:3] - self._baseline[:3])
        self._baseline[3] = (float(self._baseline[3]) + alpha * hue_delta) % 360.0
        self._baseline[4:] += alpha * (color[4:] - self._baseline[4:])

    def _reset_candidate(self) -> None:
        self._change_started_elapsed_s = None
        self._change_started_volume_ml = None
        self._last_above_elapsed_s = None
        self._candidate_peak_distance = None
        self._candidate_endpoint_score = None

    def _trigger(self, *, reason: str, elapsed_s: float, volume_ml: float | None) -> AutoStopDecision:
        self._triggered = True
        return AutoStopDecision(
            session_id=self.session_id,
            reason=reason,
            trigger_volume_ml=volume_ml,
            trigger_elapsed_s=elapsed_s,
            color_change_started_volume_ml=self._change_started_volume_ml,
            color_change_started_elapsed_s=self._change_started_elapsed_s,
            color_distance=self._candidate_peak_distance or self._latest_distance,
            color_threshold=self._threshold,
            endpoint_score=self._candidate_endpoint_score or self._latest_endpoint_score,
            endpoint_score_threshold=self.minimum_endpoint_score,
            confirmation_delay_s=self.confirmation_delay_s,
            maximum_volume_ml=self.maximum_volume_ml,
        )

    def status(self) -> dict[str, Any]:
        candidate_elapsed = None
        if self._change_started_elapsed_s is not None and self._last_elapsed_s is not None:
            candidate_elapsed = max(0.0, self._last_elapsed_s - self._change_started_elapsed_s)
        return {
            "auto_stop_mode": "model_confirmed_persistent_visible_color_change",
            "auto_stop_baseline_ready": self._baseline is not None,
            "auto_stop_baseline_samples": len(self._baseline_samples),
            "auto_stop_color_distance": ""
            if self._latest_distance is None
            else round(self._latest_distance, 6),
            "auto_stop_color_threshold": ""
            if self._threshold is None
            else round(self._threshold, 6),
            "auto_stop_color_change_pending": self._change_started_elapsed_s is not None,
            "auto_stop_color_change_elapsed_s": ""
            if candidate_elapsed is None
            else round(candidate_elapsed, 6),
            "auto_stop_color_change_started_volume_ml": ""
            if self._change_started_volume_ml is None
            else round(self._change_started_volume_ml, 6),
            "auto_stop_missing_color_samples": self._missing_color_samples,
            "auto_stop_endpoint_score": ""
            if self._latest_endpoint_score is None
            else round(self._latest_endpoint_score, 6),
            "auto_stop_endpoint_score_threshold": round(self.minimum_endpoint_score, 6),
            "auto_stop_maximum_sample_gap_s": round(self.maximum_sample_gap_s, 6),
            "auto_stop_observation_elapsed_s": ""
            if self._latest_elapsed_s is None
            else round(self._latest_elapsed_s, 6),
            "auto_stop_observation_volume_ml": ""
            if self._latest_volume_ml is None
            else round(self._latest_volume_ml, 6),
        }


class ColorChangeAutoStopController:
    """Run model scoring and color confirmation off the capture thread."""

    def __init__(
        self,
        model: Mapping[str, Any] | None,
        *,
        on_trigger: Callable[[AutoStopDecision], None],
        on_status: Callable[[dict[str, Any]], None] | None = None,
        sample_interval_s: float = 0.04,
    ) -> None:
        self._model = model
        _configure_single_row_model_inference(self._model)
        self._on_trigger = on_trigger
        self._on_status = on_status
        self._sample_interval_s = max(0.01, float(sample_interval_s))
        self._lock = threading.Lock()
        self._queue: queue.Queue[tuple[int, int, dict[str, Any]] | None] = queue.Queue(maxsize=1)
        self._stop = threading.Event()
        self._callback_gate = threading.RLock()
        self._thread = threading.Thread(target=self._loop, name="color-change-auto-stop", daemon=True)
        self._generation = 0
        self._session_id = 0
        self._titration_type = ""
        self._detector: PersistentColorAutoStopDetector | None = None
        self._enabled = False
        self._armed = False
        self._pump_started = False
        self._sticky_fault: tuple[int, int, str, str, dict[str, Any]] | None = None
        self._state = "disabled"
        self._reason = "default_off"
        self._last_submitted_elapsed_s: float | None = None
        self._error = ""
        self._confirmation_delay_s = AUTO_STOP_CONFIRMATION_SECONDS
        self._maximum_volume_ml = AUTO_STOP_MAX_VOLUME_ML
        self._thread.start()

    def arm(
        self,
        *,
        session_id: int,
        requested: bool,
        recording_started: bool,
        titration_type: str,
        confirmation_delay_s: float = AUTO_STOP_CONFIRMATION_SECONDS,
        maximum_volume_ml: float = AUTO_STOP_MAX_VOLUME_ML,
    ) -> dict[str, Any]:
        delay = _finite_float(confirmation_delay_s)
        maximum = _finite_float(maximum_volume_ml)
        with self._callback_gate:
            with self._lock:
                self._generation += 1
                self._session_id = int(session_id)
                self._titration_type = str(titration_type or "")
                self._enabled = bool(requested)
                self._armed = False
                self._pump_started = False
                self._sticky_fault = None
                self._detector = None
                self._last_submitted_elapsed_s = None
                self._error = ""
                self._drain_queue_locked()
                if delay is not None:
                    self._confirmation_delay_s = delay
                if maximum is not None:
                    self._maximum_volume_ml = maximum
                if not requested:
                    self._state = "disabled"
                    self._reason = "user_disabled"
                elif not recording_started:
                    self._state = "unavailable"
                    self._reason = "recording_not_started"
                elif delay is None or delay <= 0 or maximum is None or maximum <= 0:
                    self._state = "unavailable"
                    self._reason = "invalid_color_stop_settings"
                else:
                    self._detector = PersistentColorAutoStopDetector(
                        session_id=self._session_id,
                        confirmation_delay_s=delay,
                        maximum_volume_ml=maximum,
                    )
                    self._armed = True
                    if self._model is None:
                        self._state = "armed_safety_only"
                        self._reason = "model_unavailable_maximum_only"
                    else:
                        self._state = "armed_calibrating"
                        self._reason = "calibrating_initial_color"
                status = self._status_locked()
            self._publish_status(status)
        return status

    def disarm(self, reason: str = "manual_stop") -> dict[str, Any]:
        with self._callback_gate:
            with self._lock:
                self._generation += 1
                self._armed = False
                self._pump_started = False
                self._sticky_fault = None
                if self._state != "triggered":
                    self._state = "disabled"
                    self._reason = str(reason or "manual_stop")
                self._drain_queue_locked()
                status = self._status_locked()
            self._publish_status(status)
        return status

    def submit(self, session_id: int, row: Mapping[str, Any]) -> bool:
        if self._stop.is_set():
            return False
        elapsed = _first_finite(row, "csv_recording_elapsed_s", "pump_elapsed_s", "time_s")
        volume = _finite_float(row.get("injected_volume_ml"))
        with self._lock:
            detector = self._detector
            if not self._armed or detector is None or int(session_id) != self._session_id:
                return False
            if self._row_indicates_pump_started(row):
                self._pump_started = True
            if self._pump_started:
                fault = self._required_input_fault(row)
                if fault is not None:
                    if self._sticky_fault is None:
                        generation = self._generation
                        reason, error = fault
                        fault_row = dict(row)
                        item = (generation, int(session_id), fault_row)
                        self._sticky_fault = (generation, int(session_id), reason, error, fault_row)
                        self._replace_queue_item_locked(item)
                    return True
            if self._sticky_fault is not None:
                return False
            if elapsed is None and not self._pump_started:
                return False
            due = (
                elapsed is None
                or self._last_submitted_elapsed_s is None
                or elapsed - self._last_submitted_elapsed_s >= self._sample_interval_s
                or (volume is not None and volume >= detector.maximum_volume_ml)
            )
            if not due:
                return False
            if elapsed is not None:
                self._last_submitted_elapsed_s = elapsed
            generation = self._generation
        item = (generation, int(session_id), dict(row))
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(item)
        return True

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def close(self) -> None:
        with self._callback_gate:
            with self._lock:
                self._generation += 1
                self._armed = False
                self._pump_started = False
                self._sticky_fault = None
            self._stop.set()
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    continue
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                return
            generation, session_id, row = item
            with self._lock:
                detector = self._detector
                titration_type = self._titration_type
                sticky_fault = self._sticky_fault
                fault_is_current = bool(
                    sticky_fault is not None
                    and sticky_fault[0] == generation
                    and sticky_fault[1] == session_id
                )
                active = self._observation_is_current_locked(
                    generation,
                    session_id,
                    detector,
                    allow_sticky_fault=fault_is_current,
                )
            if not active or detector is None:
                continue
            if fault_is_current and sticky_fault is not None:
                _, _, reason, error, fault_row = sticky_fault
                self._fail_closed(
                    generation,
                    session_id,
                    detector,
                    reason=reason,
                    error=error,
                    row=fault_row,
                    allow_sticky_fault=True,
                )
                continue

            elapsed = _first_finite(row, "csv_recording_elapsed_s", "pump_elapsed_s", "time_s")
            volume = _finite_float(row.get("injected_volume_ml"))
            with self._lock:
                fail_closed = (
                    self._observation_is_current_locked(generation, session_id, detector)
                    and self._pump_started
                    and (elapsed is None or volume is None)
                )
            if fail_closed:
                missing_fields = []
                if elapsed is None:
                    missing_fields.append("elapsed time")
                if volume is None:
                    missing_fields.append("injected volume")
                self._fail_closed(
                    generation,
                    session_id,
                    detector,
                    reason="required_sensor_missing",
                    error=f"required pump telemetry is missing or non-finite: {', '.join(missing_fields)}",
                    row=row,
                )
                continue

            if _visible_color_vector(row) is None:
                with self._lock:
                    fail_closed = (
                        self._observation_is_current_locked(generation, session_id, detector)
                        and self._pump_started
                    )
                if fail_closed:
                    self._fail_closed(
                        generation,
                        session_id,
                        detector,
                        reason="required_color_missing",
                        error="required visible ROI color values are missing or non-finite",
                        row=row,
                    )
                    continue

            score = None
            score_error = ""
            if self._model is not None:
                try:
                    scored = score_typewise_rows_for_hardware_control(
                        self._model,
                        [row],
                        titration_type,
                    )
                    score = _finite_float(scored["scores"][0])
                    if score is None:
                        raise ValueError("model returned a non-finite endpoint score")
                except Exception as exc:  # noqa: BLE001 - required scoring must fail closed.
                    score_error = str(exc)
            else:
                score_error = "required endpoint model is unavailable"

            with self._lock:
                if not self._observation_is_current_locked(generation, session_id, detector):
                    continue
                fail_closed = self._pump_started and bool(score_error)
            if fail_closed:
                self._fail_closed(
                    generation,
                    session_id,
                    detector,
                    reason="model_score_failed",
                    error=score_error,
                    row=row,
                )
                continue

            with self._lock:
                if not self._observation_is_current_locked(generation, session_id, detector):
                    continue
            try:
                decision = detector.observe(row, endpoint_score=score)
            except Exception as exc:  # noqa: BLE001 - required detector must fail closed.
                with self._lock:
                    fail_closed = (
                        self._observation_is_current_locked(generation, session_id, detector)
                        and self._pump_started
                    )
                if fail_closed:
                    self._fail_closed(
                        generation,
                        session_id,
                        detector,
                        reason="color_detector_failed",
                        error=str(exc),
                        row=row,
                    )
                else:
                    self._publish_prestart_detector_error(
                        generation,
                        session_id,
                        detector,
                        str(exc),
                    )
                continue
            if decision is not None:
                self._commit_decision(generation, session_id, detector, decision)
            else:
                self._publish_observation_status(
                    generation,
                    session_id,
                    detector,
                    score_error=score_error,
                )

    @staticmethod
    def _row_indicates_pump_started(row: Mapping[str, Any]) -> bool:
        pump_state = str(row.get("pump_state") or "").strip().lower()
        if pump_state in {
            "running",
            "continuous",
            "pulsing",
            "pulse_settling",
            "step_commanded",
        }:
            return True
        pump_elapsed_s = _finite_float(row.get("pump_elapsed_s"))
        injected_volume_ml = _finite_float(row.get("injected_volume_ml"))
        return bool(
            (pump_elapsed_s is not None and pump_elapsed_s > 0.0)
            or (injected_volume_ml is not None and injected_volume_ml > 0.0)
        )

    @staticmethod
    def _required_input_fault(row: Mapping[str, Any]) -> tuple[str, str] | None:
        missing_fields = []
        if _first_finite(row, "csv_recording_elapsed_s", "pump_elapsed_s", "time_s") is None:
            missing_fields.append("elapsed time")
        if _finite_float(row.get("injected_volume_ml")) is None:
            missing_fields.append("injected volume")
        if missing_fields:
            return (
                "required_sensor_missing",
                f"required pump telemetry is missing or non-finite: {', '.join(missing_fields)}",
            )
        if _visible_color_vector(row) is None:
            return (
                "required_color_missing",
                "required visible ROI color values are missing or non-finite",
            )
        return None

    def _observation_is_current_locked(
        self,
        generation: int,
        session_id: int,
        detector: PersistentColorAutoStopDetector | None,
        *,
        allow_sticky_fault: bool = False,
    ) -> bool:
        return bool(
            self._armed
            and self._generation == generation
            and self._session_id == session_id
            and self._detector is detector
            and detector is not None
            and (allow_sticky_fault or self._sticky_fault is None)
        )

    def _failure_decision(
        self,
        detector: PersistentColorAutoStopDetector,
        *,
        session_id: int,
        reason: str,
        row: Mapping[str, Any],
    ) -> AutoStopDecision:
        detector_status = detector.status()
        elapsed_s = _first_finite(row, "csv_recording_elapsed_s", "pump_elapsed_s", "time_s")
        if elapsed_s is None:
            elapsed_s = _finite_float(detector_status.get("auto_stop_observation_elapsed_s")) or 0.0
        volume_ml = _finite_float(row.get("injected_volume_ml"))
        if volume_ml is None:
            volume_ml = _finite_float(detector_status.get("auto_stop_observation_volume_ml"))
        return AutoStopDecision(
            session_id=session_id,
            reason=reason,
            trigger_volume_ml=volume_ml,
            trigger_elapsed_s=max(0.0, elapsed_s),
            color_change_started_volume_ml=None,
            color_change_started_elapsed_s=None,
            color_distance=_finite_float(detector_status.get("auto_stop_color_distance")),
            color_threshold=_finite_float(detector_status.get("auto_stop_color_threshold")),
            endpoint_score=_finite_float(detector_status.get("auto_stop_endpoint_score")),
            endpoint_score_threshold=detector.minimum_endpoint_score,
            confirmation_delay_s=detector.confirmation_delay_s,
            maximum_volume_ml=detector.maximum_volume_ml,
        )

    def _fail_closed(
        self,
        generation: int,
        session_id: int,
        detector: PersistentColorAutoStopDetector,
        *,
        reason: str,
        error: str,
        row: Mapping[str, Any],
        allow_sticky_fault: bool = False,
    ) -> None:
        decision = self._failure_decision(
            detector,
            session_id=session_id,
            reason=reason,
            row=row,
        )
        self._commit_decision(
            generation,
            session_id,
            detector,
            decision,
            diagnostic=error,
            allow_sticky_fault=allow_sticky_fault,
        )

    def _commit_decision(
        self,
        generation: int,
        session_id: int,
        detector: PersistentColorAutoStopDetector,
        decision: AutoStopDecision,
        *,
        diagnostic: str = "",
        allow_sticky_fault: bool = False,
    ) -> None:
        with self._callback_gate:
            with self._lock:
                if not self._observation_is_current_locked(
                    generation,
                    session_id,
                    detector,
                    allow_sticky_fault=allow_sticky_fault,
                ):
                    return
                self._armed = False
                self._sticky_fault = None
                self._state = "triggered"
                self._reason = decision.reason
                self._error = diagnostic
                status = self._status_locked()
            # Publishing the triggered state first disarms the pulse controller
            # through the existing status callback before the pump-stop callback.
            self._publish_status(status)
            with self._lock:
                current = bool(
                    self._generation == generation
                    and self._session_id == session_id
                    and self._detector is detector
                    and self._state == "triggered"
                    and self._reason == decision.reason
                )
            if not current:
                return
            try:
                self._on_trigger(decision)
            except Exception as exc:  # noqa: BLE001 - preserve worker and expose action failure.
                with self._lock:
                    if self._generation != generation or self._detector is not detector:
                        return
                    self._state = "error"
                    self._reason = "stop_action_failed"
                    stop_error = str(exc)
                    self._error = (
                        f"{diagnostic}; stop action failed: {stop_error}"
                        if diagnostic
                        else stop_error
                    )
                    status = self._status_locked()
                self._publish_status(status)

    def _publish_prestart_detector_error(
        self,
        generation: int,
        session_id: int,
        detector: PersistentColorAutoStopDetector,
        error: str,
    ) -> None:
        with self._callback_gate:
            with self._lock:
                if not self._observation_is_current_locked(generation, session_id, detector):
                    return
                self._error = error
                self._state = "error"
                self._reason = "color_detector_failed"
                status = self._status_locked()
            self._publish_status(status)

    def _publish_observation_status(
        self,
        generation: int,
        session_id: int,
        detector: PersistentColorAutoStopDetector,
        *,
        score_error: str,
    ) -> None:
        with self._callback_gate:
            with self._lock:
                if not self._observation_is_current_locked(generation, session_id, detector):
                    return
                detector_status = detector.status()
                if not detector_status["auto_stop_baseline_ready"]:
                    self._state = "armed_calibrating"
                    self._reason = "calibrating_initial_color"
                elif self._model is None or score_error:
                    self._state = "armed_safety_only"
                    self._reason = (
                        "model_unavailable_maximum_only"
                        if self._model is None
                        else "model_score_failed_maximum_only"
                    )
                    self._error = score_error
                elif detector_status["auto_stop_color_change_pending"]:
                    self._state = "armed_confirming"
                    self._reason = "confirming_persistent_color_change"
                else:
                    self._state = "armed"
                    self._reason = "waiting_for_color_model_confirmation"
                status = self._status_locked()
            self._publish_status(status)

    def _status_locked(self) -> dict[str, Any]:
        detector_status = {} if self._detector is None else self._detector.status()
        return {
            "auto_stop_enabled": self._enabled,
            "auto_stop_armed": self._armed,
            "auto_stop_state": self._state,
            "auto_stop_reason": self._reason,
            "auto_stop_session_id": self._session_id,
            "auto_stop_confirmation_delay_s": round(self._confirmation_delay_s, 6),
            "auto_stop_maximum_volume_ml": round(self._maximum_volume_ml, 6),
            "auto_stop_error": self._error,
            **detector_status,
        }

    def _drain_queue_locked(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    def _replace_queue_item_locked(self, item: tuple[int, int, dict[str, Any]]) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        self._queue.put_nowait(item)

    def _publish_status(self, status: dict[str, Any]) -> None:
        if self._on_status is not None:
            self._on_status(dict(status))
