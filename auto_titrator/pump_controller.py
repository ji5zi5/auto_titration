"""Manual syringe-pump command controller with dry-run support and safety checks."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

DEFAULT_CONFIG_ML_PER_STEP = 0.005
DEFAULT_MAX_RATE_ML_PER_S = 0.5
MAX_RUN_RATE_ML_PER_S = 1.0
MAX_STEPS_PER_COMMAND = 200_000
ABSOLUTE_MAX_TOTAL_STEPS = 1_000_000
MAX_VOLUME_ML = 100.0
MIN_ML_PER_STEP = 0.000001
MAX_ML_PER_STEP = 1.0
MAX_STEPS_PER_ML = 1_000_000.0
MAX_STEP_INTERVAL_MICROS = 3_600_000_000.0
DIRECTION_FORWARD = "forward"
DIRECTION_REVERSE = "reverse"


def validate_direction(direction: str) -> str:
    normalized = direction.strip().lower()
    if normalized not in {DIRECTION_FORWARD, DIRECTION_REVERSE}:
        raise ValueError("direction must be forward or reverse")
    return normalized


def validate_firmware_float_range(
    value: float,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Validate a positive finite float against firmware-compatible bounds."""

    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{label} must be positive and finite")
    if minimum is not None and value < minimum:
        raise ValueError(f"{label} is below firmware minimum")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} exceeds firmware maximum")
    return value


def validate_firmware_int_range(value: int, label: str, *, maximum: int | None = None) -> int:
    """Validate a positive integer against firmware-compatible bounds."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    if value <= 0:
        raise ValueError(f"{label} must be positive")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} exceeds firmware maximum")
    return value


def validate_ml_per_step(ml_per_step: float) -> float:
    return validate_firmware_float_range(
        ml_per_step,
        "ml_per_step",
        minimum=MIN_ML_PER_STEP,
        maximum=MAX_ML_PER_STEP,
    )


def validate_steps_per_ml(steps_per_ml: float) -> float:
    return validate_firmware_float_range(
        steps_per_ml,
        "steps_per_ml",
        minimum=1.0 / MAX_ML_PER_STEP,
        maximum=MAX_STEPS_PER_ML,
    )


def validate_step_command_count(steps: int) -> int:
    return validate_firmware_int_range(steps, "steps", maximum=MAX_STEPS_PER_COMMAND)


def validate_max_total_steps(steps: int, *, maximum: int = ABSOLUTE_MAX_TOTAL_STEPS) -> int:
    validate_firmware_int_range(maximum, "max_steps", maximum=ABSOLUTE_MAX_TOTAL_STEPS)
    return validate_firmware_int_range(steps, "max_total_steps", maximum=maximum)


def validate_max_volume_ml(volume_ml: float, *, maximum: float = MAX_VOLUME_ML) -> float:
    validate_firmware_float_range(maximum, "max_volume_ml", maximum=MAX_VOLUME_ML)
    return validate_firmware_float_range(volume_ml, "volume_ml", maximum=maximum)


def validate_calibrated_max_volume_ml(
    volume_ml: float,
    *,
    ml_per_step: float,
    maximum: float = MAX_VOLUME_ML,
    maximum_steps: int = ABSOLUTE_MAX_TOTAL_STEPS,
    minimum_steps: int = 1,
) -> float:
    """Validate a max-volume command against volume and derived firmware steps."""

    validated_volume_ml = validate_max_volume_ml(volume_ml, maximum=maximum)
    validated_ml_per_step = validate_ml_per_step(ml_per_step)
    validate_max_total_steps(maximum_steps)
    validate_firmware_int_range(minimum_steps, "minimum_steps", maximum=maximum_steps)

    derived_steps = validated_volume_ml / validated_ml_per_step
    if derived_steps < minimum_steps:
        raise ValueError("volume_ml is below the current step position")
    if derived_steps > maximum_steps:
        raise ValueError("volume_ml exceeds max_steps after calibration")
    return validated_volume_ml


def min_run_rate_for_step_interval(ml_per_step: float) -> float:
    """Return the slowest run rate whose firmware interval stays in range."""

    return validate_ml_per_step(ml_per_step) * 1_000_000.0 / MAX_STEP_INTERVAL_MICROS


def validate_run_rate_ml_per_s(
    ml_per_s: float,
    *,
    ml_per_step: float,
    max_rate_ml_per_s: float = MAX_RUN_RATE_ML_PER_S,
) -> float:
    validate_firmware_float_range(max_rate_ml_per_s, "max_rate_ml_per_s", maximum=MAX_RUN_RATE_ML_PER_S)
    return validate_firmware_float_range(
        ml_per_s,
        "ml_per_s",
        minimum=min_run_rate_for_step_interval(ml_per_step),
        maximum=max_rate_ml_per_s,
    )


def format_firmware_float(value: float, *, digits: int = 12) -> str:
    """Format a positive finite float without exponent notation for firmware."""

    validate_firmware_float_range(value, "firmware float value")
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    if not text or text == "0":
        raise ValueError("firmware float value is too small for decimal command format")
    return text


class Transport(Protocol):
    def write_command(self, command: str) -> Sequence[str]:
        """Send one command line and return firmware response lines."""
        ...


class DryRunTransport:
    """In-memory transport for tests and no-hardware dry runs."""

    mode = "dry_run"

    def __init__(self) -> None:
        self.commands: list[str] = []

    def write_command(self, command: str) -> Sequence[str]:
        self.commands.append(command)
        return [f"OK DRY_RUN {command}"]


class SerialTransport:
    """Transport adapter for pyserial-like objects with a write(bytes) method."""

    mode = "serial"

    def __init__(self, serial_obj, *, read_lines: int = 4) -> None:  # type: ignore[no-untyped-def]
        if read_lines <= 0:
            raise ValueError("read_lines must be positive")
        self.serial_obj = serial_obj
        self.read_lines = read_lines

    def write_command(self, command: str) -> Sequence[str]:
        self.serial_obj.write(f"{command}\n".encode("ascii"))
        responses: list[str] = []
        for _ in range(self.read_lines):
            raw = self.serial_obj.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                responses.append(line)
        return responses


@dataclass(frozen=True)
class PumpSafetyConfig:
    max_volume_ml: float = MAX_VOLUME_ML
    max_rate_ml_per_s: float = DEFAULT_MAX_RATE_ML_PER_S
    max_steps: int = ABSOLUTE_MAX_TOTAL_STEPS

    def __post_init__(self) -> None:
        validate_firmware_float_range(self.max_volume_ml, "max_volume_ml", maximum=MAX_VOLUME_ML)
        validate_firmware_float_range(self.max_rate_ml_per_s, "max_rate_ml_per_s", maximum=MAX_RUN_RATE_ML_PER_S)
        validate_firmware_int_range(self.max_steps, "max_steps", maximum=ABSOLUTE_MAX_TOTAL_STEPS)


class PumpController:
    """Manual pump command interface; it never auto-stops from camera/ML output."""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        ml_per_step: float,
        safety: PumpSafetyConfig | None = None,
    ) -> None:
        self.transport = transport or DryRunTransport()
        self.ml_per_step = validate_ml_per_step(ml_per_step)
        self.safety = safety or PumpSafetyConfig()
        self.step_count = 0
        self.confirmed_step_count = 0
        self.current_rate_ml_per_s = 0.0
        self.state = "idle"
        self.direction = DIRECTION_FORWARD
        self.mode = getattr(self.transport, "mode", "serial")

    def prime(self) -> None:
        self._ensure_operational()
        self._send("PRIME")
        self.current_rate_ml_per_s = 0.0
        self.state = "priming"

    def step(self, steps: int) -> None:
        self._ensure_operational()
        validate_step_command_count(steps)
        projected_steps = self._project_step_count(steps)
        self._send(f"STEP {steps}")
        self.step_count = projected_steps
        self.current_rate_ml_per_s = 0.0
        self.state = "stepping"

    def run_rate(self, ml_per_s: float) -> None:
        self._ensure_operational()
        validate_run_rate_ml_per_s(
            ml_per_s,
            ml_per_step=self.ml_per_step,
            max_rate_ml_per_s=self.safety.max_rate_ml_per_s,
        )
        self._send(f"RUN_RATE {format_firmware_float(ml_per_s)}")
        self.current_rate_ml_per_s = ml_per_s
        self.state = "running"

    def request_status(self) -> None:
        """Ask firmware to print its current status without changing local state."""

        self._send("STATUS")

    def set_ml_per_step(self, ml_per_step: float) -> None:
        """Update runtime pump calibration in firmware and local volume math."""

        self._ensure_operational()
        validate_ml_per_step(ml_per_step)
        self._ensure_safe_to_recalibrate()
        self._send(f"SET_ML_PER_STEP {format_firmware_float(ml_per_step)}")
        self.ml_per_step = ml_per_step

    def set_steps_per_ml(self, steps_per_ml: float) -> None:
        """Update calibration using the inverse steps/mL value."""

        self._ensure_operational()
        validate_steps_per_ml(steps_per_ml)
        self._ensure_safe_to_recalibrate()
        self._send(f"SET_STEPS_PER_ML {format_firmware_float(steps_per_ml)}")
        self.ml_per_step = 1.0 / steps_per_ml

    def set_max_total_steps(self, steps: int) -> None:
        """Set firmware max-travel limit in motor steps."""

        self._ensure_operational()
        validate_max_total_steps(steps, maximum=self.safety.max_steps)
        self._ensure_safe_to_recalibrate()
        self._send(f"SET_MAX_TOTAL_STEPS {steps}")

    def set_max_volume_ml(self, volume_ml: float) -> None:
        """Set firmware max-travel limit as a calibrated volume."""

        self._ensure_operational()
        validate_calibrated_max_volume_ml(
            volume_ml,
            ml_per_step=self.ml_per_step,
            maximum=self.safety.max_volume_ml,
            maximum_steps=self.safety.max_steps,
            minimum_steps=max(1, self.step_count),
        )
        self._ensure_safe_to_recalibrate()
        self._send(f"SET_MAX_VOLUME_ML {format_firmware_float(volume_ml)}")

    def set_direction(self, direction: str) -> None:
        """Set pump direction while idle/stopped.

        Forward increases commanded syringe position; reverse decreases it and
        is blocked locally if the command would move below the reset/zero point.
        """

        self._ensure_operational()
        self._ensure_safe_to_recalibrate()
        normalized = validate_direction(direction)
        firmware_direction = normalized.upper()
        self._send(f"SET_DIR {firmware_direction}")
        self.direction = normalized

    def reset_steps(self) -> None:
        """Reset firmware and local step counters after manual zeroing."""

        self._ensure_operational()
        self._ensure_safe_to_recalibrate()
        self._send("RESET_STEPS")
        self.step_count = 0
        self.current_rate_ml_per_s = 0.0
        self.state = "idle"

    def clear_fault(self) -> None:
        """Clear a non-emergency firmware fault after the hardware is safe."""

        self._ensure_operational()
        self._ensure_safe_to_recalibrate()
        self._send("CLEAR_FAULT")
        if self.state != "emergency_stop":
            self.current_rate_ml_per_s = 0.0
            self.state = "idle"

    def stop(self) -> None:
        self._send("STOP")
        self.current_rate_ml_per_s = 0.0
        if self.state != "emergency_stop":
            self.state = "stopped"

    def emergency_stop(self) -> None:
        self._send("EMERGENCY_STOP")
        self.current_rate_ml_per_s = 0.0
        self.state = "emergency_stop"

    def snapshot(self) -> dict[str, float | int | str]:
        return {
            "pump_mode": self.mode,
            "pump_state": self.state,
            "pump_direction": self.direction,
            "pump_step_count": self.step_count,
            "pump_commanded_step_count": self.step_count,
            "pump_confirmed_step_count": self.confirmed_step_count,
            "pump_run_rate_ml_per_s": self.current_rate_ml_per_s,
            "pump_calibrated_ml_per_step": self.ml_per_step,
            "pump_calibrated_steps_per_ml": 1.0 / self.ml_per_step,
            "injected_volume_ml": self.step_count * self.ml_per_step,
            "commanded_volume_ml": self.step_count * self.ml_per_step,
            "confirmed_injected_volume_ml": self.confirmed_step_count * self.ml_per_step,
        }

    def _send(self, command: str) -> Sequence[str]:
        try:
            responses = list(self.transport.write_command(command))
        except Exception:
            self.state = "error_stopped"
            raise
        error = next((line for line in responses if line.startswith("ERR")), "")
        if error:
            self.state = "error_stopped"
            raise RuntimeError(f"firmware rejected {command}: {error}")
        if not any(self._is_expected_ack(command, line) for line in responses):
            self.state = "error_stopped"
            raise RuntimeError(f"firmware did not acknowledge {command}")
        return responses

    def _is_expected_ack(self, command: str, line: str) -> bool:
        if self.mode == "dry_run":
            return line == f"OK DRY_RUN {command}"
        if line.startswith("OK DRY_RUN "):
            return False
        if command == "PRIME":
            return line == "OK PRIME_STARTED 50"
        if command.startswith("STEP "):
            return line == f"OK STEP_STARTED {command.removeprefix('STEP ')}"
        if command.startswith("RUN_RATE "):
            return line == "OK RUN_RATE"
        if command == "STOP":
            return line == "OK STOP"
        if command == "EMERGENCY_STOP":
            return line == "OK EMERGENCY_STOP"
        if command == "STATUS":
            return line.startswith("OK STATUS")
        if command.startswith("SET_ML_PER_STEP "):
            return line == f"OK SET_ML_PER_STEP {float(command.removeprefix('SET_ML_PER_STEP ')):.8f}"
        if command.startswith("SET_STEPS_PER_ML "):
            return line == f"OK SET_STEPS_PER_ML {float(command.removeprefix('SET_STEPS_PER_ML ')):.3f}"
        if command.startswith("SET_MAX_TOTAL_STEPS "):
            return line == f"OK SET_MAX_TOTAL_STEPS {command.removeprefix('SET_MAX_TOTAL_STEPS ')}"
        if command.startswith("SET_MAX_VOLUME_ML "):
            return line == f"OK SET_MAX_VOLUME_ML {float(command.removeprefix('SET_MAX_VOLUME_ML ')):.6f}"
        if command.startswith("SET_DIR "):
            return line == f"OK SET_DIR {command.removeprefix('SET_DIR ')}"
        if command == "RESET_STEPS":
            return line == "OK RESET_STEPS"
        if command == "CLEAR_FAULT":
            return line == "OK CLEAR_FAULT"
        return False

    def _ensure_not_emergency(self) -> None:
        if self.state == "emergency_stop":
            raise RuntimeError("pump is in emergency_stop state")

    def _ensure_operational(self) -> None:
        self._ensure_not_emergency()
        if self.state == "error_stopped":
            raise RuntimeError("pump is in error_stopped state")

    def _ensure_safe_to_recalibrate(self) -> None:
        if self.state in {"running", "priming", "stepping"}:
            raise RuntimeError("stop pump before changing calibration")

    def _project_step_count(self, steps: int) -> int:
        if self.direction == DIRECTION_REVERSE:
            projected_steps = self.step_count - steps
            if projected_steps < 0:
                raise ValueError("reverse step command would move below zero")
            return projected_steps
        if steps > self.safety.max_steps:
            raise ValueError("steps exceeds max_steps")
        projected_steps = self.step_count + steps
        if projected_steps > self.safety.max_steps:
            raise ValueError("total step count exceeds max_steps")
        projected_volume = projected_steps * self.ml_per_step
        if projected_volume > self.safety.max_volume_ml:
            raise ValueError("command exceeds max_volume_ml")
        return projected_steps
