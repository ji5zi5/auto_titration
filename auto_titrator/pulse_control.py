"""Pure endpoint-near pulse-control state machine.

This module emits command *intents* only.  It does not send serial commands,
estimate delivered volume, or claim that a pulse has completed.  Callers must
provide monotonic timestamps, a conservative measured/commanded volume, and an
explicit pulse-completion event from their eventual hardware integration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .pump_controller import (
    MAX_RUN_RATE_ML_PER_S,
    MAX_VOLUME_ML,
    format_firmware_float,
    validate_ml_per_step,
    validate_run_rate_ml_per_s,
)


# The small a/b/c firmware used by the Windows collector deliberately accepts
# much smaller pulses than the generic PumpController protocol.
ABC_FIRMWARE_MAX_PULSE_STEPS = 200


class PulseState(str, Enum):
    FAST_CONTINUOUS = "FAST_CONTINUOUS"
    SLOW_CONTINUOUS = "SLOW_CONTINUOUS"
    PULSE_WAIT = "PULSE_WAIT"
    PULSE_INJECT = "PULSE_INJECT"
    STOPPED = "STOPPED"


@dataclass(frozen=True)
class PulseControlConfig:
    """Thresholds, timing, calibration, and hard limits for one run."""

    approach_score: float
    endpoint_score: float
    confirmation_duration_s: float
    pulse_steps: int
    settle_time_s: float
    max_volume_ml: float
    ml_per_step: float
    fast_rate_ml_per_s: float
    endpoint_confirmation_enabled: bool = True
    slow_stage_enabled: bool = False
    slow_onset_score: float = 0.0
    slow_onset_duration_s: float = 0.0
    slow_rate_steps_per_s: int = 100

    def __post_init__(self) -> None:
        for name in ("approach_score", "endpoint_score"):
            value = getattr(self, name)
            if not _is_finite_number(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and in 0..1")
        if self.endpoint_score < self.approach_score:
            raise ValueError("endpoint_score must be greater than or equal to approach_score")
        for name in ("confirmation_duration_s", "settle_time_s"):
            value = getattr(self, name)
            if not _is_finite_number(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if isinstance(self.pulse_steps, bool) or not isinstance(self.pulse_steps, int):
            raise ValueError("pulse_steps must be an integer")
        if not 0 < self.pulse_steps <= ABC_FIRMWARE_MAX_PULSE_STEPS:
            raise ValueError(f"pulse_steps must be in 1..{ABC_FIRMWARE_MAX_PULSE_STEPS}")
        if not _is_finite_number(self.max_volume_ml) or not 0.0 < self.max_volume_ml <= MAX_VOLUME_ML:
            raise ValueError(f"max_volume_ml must be positive and no greater than {MAX_VOLUME_ML}")
        if not _is_finite_number(self.ml_per_step):
            raise ValueError("ml_per_step must be positive and finite")
        validate_ml_per_step(float(self.ml_per_step))
        if not _is_finite_number(self.fast_rate_ml_per_s):
            raise ValueError("fast_rate_ml_per_s must be positive and finite")
        validate_run_rate_ml_per_s(
            float(self.fast_rate_ml_per_s),
            ml_per_step=float(self.ml_per_step),
            max_rate_ml_per_s=MAX_RUN_RATE_ML_PER_S,
        )
        if not isinstance(self.endpoint_confirmation_enabled, bool):
            raise ValueError("endpoint_confirmation_enabled must be boolean")
        if not isinstance(self.slow_stage_enabled, bool):
            raise ValueError("slow_stage_enabled must be boolean")
        if not _is_finite_number(self.slow_onset_score) or not 0.0 <= self.slow_onset_score <= 1.0:
            raise ValueError("slow_onset_score must be finite and in 0..1")
        if self.slow_stage_enabled and self.slow_onset_score >= self.approach_score:
            raise ValueError("slow_onset_score must be lower than approach_score")
        if not _is_finite_number(self.slow_onset_duration_s) or self.slow_onset_duration_s < 0.0:
            raise ValueError("slow_onset_duration_s must be finite and non-negative")
        if (
            isinstance(self.slow_rate_steps_per_s, bool)
            or not isinstance(self.slow_rate_steps_per_s, int)
            or not 1 <= self.slow_rate_steps_per_s <= 100
        ):
            raise ValueError("slow_rate_steps_per_s must be an integer in 1..100")
        if self.pulse_volume_ml > self.max_volume_ml:
            raise ValueError("one pulse exceeds max_volume_ml")

    @property
    def pulse_volume_ml(self) -> float:
        return self.pulse_steps * self.ml_per_step

    @property
    def slow_rate_ml_per_s(self) -> float:
        """Nominal, uncalibrated slow flow inferred from the step-rate ratio."""

        return self.fast_rate_ml_per_s * self.slow_rate_steps_per_s / 100.0


@dataclass(frozen=True)
class CommandIntent:
    """A validated, explicit firmware command that a separate layer may send."""

    command: str
    reason: str

    def __post_init__(self) -> None:
        if self.command != self.command.upper():
            raise ValueError("command intents must be uppercase")
        valid = self.command in {"STOP", "EMERGENCY_STOP"} or self.command.startswith(
            ("RUN_RATE ", "RATE ", "STEP ")
        )
        if not valid:
            raise ValueError(f"unsupported command intent: {self.command}")


@dataclass(frozen=True)
class PulseObservation:
    now_s: float
    score: float
    injected_volume_ml: float
    pulse_complete: bool = False
    emergency_stop: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.pulse_complete, bool):
            raise ValueError("pulse_complete must be boolean")
        if not isinstance(self.emergency_stop, bool):
            raise ValueError("emergency_stop must be boolean")


@dataclass(frozen=True)
class PulseTransition:
    state: PulseState
    intents: tuple[CommandIntent, ...]
    reason: str
    endpoint_confirmation_started_s: float | None


class PulseController:
    """Deterministic controller for continuous approach and endpoint pulses."""

    def __init__(self, config: PulseControlConfig) -> None:
        self.config = config
        self.state = PulseState.FAST_CONTINUOUS
        self.stop_reason: str | None = None
        self._started = False
        self._last_now_s: float | None = None
        self._last_reported_volume_ml: float | None = None
        self._accounted_volume_ml = 0.0
        self._wait_started_s: float | None = None
        self._endpoint_started_s: float | None = None
        self._slow_onset_started_s: float | None = None

    def start(self, *, now_s: float = 0.0, injected_volume_ml: float = 0.0) -> PulseTransition:
        """Emit the initial continuous-run intent exactly once."""

        self._validate_time_and_volume(now_s, injected_volume_ml)
        if self._started:
            raise RuntimeError("pulse controller has already started")
        self._started = True
        self._last_now_s = float(now_s)
        self._last_reported_volume_ml = float(injected_volume_ml)
        self._accounted_volume_ml = float(injected_volume_ml)
        if injected_volume_ml >= self.config.max_volume_ml:
            return self._stop("maximum_volume_reached", emergency=False)
        command = f"RUN_RATE {format_firmware_float(self.config.fast_rate_ml_per_s)}"
        return self._transition((CommandIntent(command, "start_fast_continuous"),), "started")

    def update(self, observation: PulseObservation) -> PulseTransition:
        """Consume one event and return zero or more command intents."""

        if self.state is PulseState.STOPPED:
            return self._transition((), self.stop_reason or "stopped")
        if not self._started:
            raise RuntimeError("start must be called before update")
        # Emergency stop has priority over malformed or stale telemetry.
        if observation.emergency_stop:
            return self._stop("emergency_stop", emergency=True)

        self._validate_observation(observation)
        self._last_now_s = float(observation.now_s)
        self._last_reported_volume_ml = float(observation.injected_volume_ml)
        self._accounted_volume_ml = max(
            self._accounted_volume_ml, float(observation.injected_volume_ml)
        )

        if self._accounted_volume_ml >= self.config.max_volume_ml:
            return self._stop("maximum_volume_reached", emergency=False)

        if self.state in {PulseState.FAST_CONTINUOUS, PulseState.SLOW_CONTINUOUS}:
            if observation.pulse_complete:
                raise ValueError("pulse_complete is invalid during continuous dosing")
            # Pulse transition always wins when both thresholds are satisfied.
            if observation.score >= self.config.approach_score:
                self.state = PulseState.PULSE_WAIT
                self._wait_started_s = observation.now_s
                self._update_endpoint_confirmation(observation)
                if self._endpoint_confirmed(observation.now_s):
                    return self._stop("endpoint_confirmed", emergency=False)
                return self._transition(
                    (CommandIntent("STOP", "approach_threshold_reached"),),
                    "approach_threshold_reached",
                )
            if self.state is PulseState.FAST_CONTINUOUS and self.config.slow_stage_enabled:
                if observation.score >= self.config.slow_onset_score:
                    if self._slow_onset_started_s is None:
                        self._slow_onset_started_s = observation.now_s
                    if (
                        observation.now_s + 1e-12
                        >= self._slow_onset_started_s + self.config.slow_onset_duration_s
                    ):
                        self.state = PulseState.SLOW_CONTINUOUS
                        self._slow_onset_started_s = None
                        return self._transition(
                            (
                                CommandIntent("STOP", "slow_onset_sustained"),
                                CommandIntent(
                                    f"RATE {self.config.slow_rate_steps_per_s}",
                                    "configure_slow_rate",
                                ),
                                CommandIntent(
                                    f"RUN_RATE {format_firmware_float(self.config.slow_rate_ml_per_s)}",
                                    "start_slow_continuous",
                                ),
                            ),
                            "slow_onset_sustained",
                        )
                else:
                    self._slow_onset_started_s = None
            return self._transition(
                (),
                "slow_continuous" if self.state is PulseState.SLOW_CONTINUOUS else "fast_continuous",
            )

        if self.state is PulseState.PULSE_INJECT:
            if not observation.pulse_complete:
                return self._transition((), "pulse_in_progress")
            self.state = PulseState.PULSE_WAIT
            self._wait_started_s = observation.now_s
            self._update_endpoint_confirmation(observation)
            return self._transition((), "pulse_complete")

        if observation.pulse_complete:
            raise ValueError("pulse_complete is valid only during PULSE_INJECT")
        self._update_endpoint_confirmation(observation)
        if self._endpoint_confirmed(observation.now_s):
            return self._stop("endpoint_confirmed", emergency=False)
        if observation.now_s - float(self._wait_started_s) < self.config.settle_time_s:
            return self._transition((), "settling")
        projected_volume = self._accounted_volume_ml + self.config.pulse_volume_ml
        if projected_volume > self.config.max_volume_ml:
            return self._stop("maximum_volume_would_be_exceeded", emergency=False)
        # Reserve the full calibrated pulse before emitting its command.  A
        # stale external volume report can therefore never authorize it twice.
        self._accounted_volume_ml = projected_volume
        self.state = PulseState.PULSE_INJECT
        return self._transition(
            (CommandIntent(f"STEP {self.config.pulse_steps}", "endpoint_not_confirmed"),),
            "pulse_requested",
        )

    def _validate_observation(self, observation: PulseObservation) -> None:
        self._validate_time_and_volume(observation.now_s, observation.injected_volume_ml)
        if observation.now_s < float(self._last_now_s):
            raise ValueError("now_s must be monotonic")
        if observation.injected_volume_ml < float(self._last_reported_volume_ml):
            raise ValueError("injected_volume_ml must be monotonic")
        if not _is_finite_number(observation.score) or not 0.0 <= observation.score <= 1.0:
            raise ValueError("score must be finite and in 0..1")

    def _validate_time_and_volume(self, now_s: float, injected_volume_ml: float) -> None:
        if not _is_finite_number(now_s) or now_s < 0.0:
            raise ValueError("now_s must be finite and non-negative")
        if not _is_finite_number(injected_volume_ml) or injected_volume_ml < 0.0:
            raise ValueError("injected_volume_ml must be finite and non-negative")

    def _update_endpoint_confirmation(self, observation: PulseObservation) -> None:
        if not self.config.endpoint_confirmation_enabled:
            self._endpoint_started_s = None
            return
        if observation.score >= self.config.endpoint_score:
            if self._endpoint_started_s is None:
                self._endpoint_started_s = observation.now_s
        else:
            self._endpoint_started_s = None

    def _endpoint_confirmed(self, now_s: float) -> bool:
        return self.config.endpoint_confirmation_enabled and self._endpoint_started_s is not None and (
            now_s + 1e-12
            >= self._endpoint_started_s + self.config.confirmation_duration_s
        )

    def _stop(self, reason: str, *, emergency: bool) -> PulseTransition:
        self.state = PulseState.STOPPED
        self.stop_reason = reason
        command = "EMERGENCY_STOP" if emergency else "STOP"
        self._endpoint_started_s = None
        self._slow_onset_started_s = None
        return self._transition((CommandIntent(command, reason),), reason)

    def _transition(self, intents: tuple[CommandIntent, ...], reason: str) -> PulseTransition:
        return PulseTransition(self.state, intents, reason, self._endpoint_started_s)


def simulate_trace(
    config: PulseControlConfig,
    observations: Iterable[PulseObservation],
    *,
    start_time_s: float = 0.0,
    start_volume_ml: float = 0.0,
) -> tuple[PulseTransition, ...]:
    """Run a reproducible hardware-free event trace, including start."""

    controller = PulseController(config)
    transitions = [controller.start(now_s=start_time_s, injected_volume_ml=start_volume_ml)]
    transitions.extend(controller.update(observation) for observation in observations)
    return tuple(transitions)


def _is_finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
