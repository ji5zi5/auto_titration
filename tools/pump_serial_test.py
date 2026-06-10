#!/usr/bin/env python3
"""Small serial command helper for the syringe-pump Arduino firmware.

Examples:
    py tools/pump_serial_test.py --port COM3 status
    py tools/pump_serial_test.py --port COM3 step 100
    py tools/pump_serial_test.py --port COM3 set-dir reverse
    py tools/pump_serial_test.py --port COM3 emergency-stop
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Protocol

from auto_titrator.pump_controller import (
    ABSOLUTE_MAX_TOTAL_STEPS,
    DEFAULT_CONFIG_ML_PER_STEP,
    format_firmware_float,
    validate_calibrated_max_volume_ml,
    validate_max_total_steps,
    validate_ml_per_step,
    validate_run_rate_ml_per_s,
    validate_step_command_count,
    validate_steps_per_ml,
)


class SerialLike(Protocol):
    def write(self, data: bytes, /) -> object: ...
    def readline(self) -> bytes: ...
    def close(self) -> object: ...


def pyserial_factory(*, port: str, baudrate: int, timeout: float) -> SerialLike:
    try:
        import serial  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on local hardware env.
        raise RuntimeError(
            "pyserial is required for real pump serial I/O. Install with: python -m pip install pyserial"
        ) from exc
    return serial.Serial(port=port, baudrate=baudrate, timeout=timeout)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM3 on Windows or /dev/ttyACM0 on Linux")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout-s", type=float, default=2.0)
    parser.add_argument("--read-lines", type=int, default=6, help="maximum response lines to read after sending")
    parser.add_argument(
        "--ml-per-step",
        type=float,
        default=DEFAULT_CONFIG_ML_PER_STEP,
        help="config/default calibration used only to validate run-rate lower bounds before send",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=ABSOLUTE_MAX_TOTAL_STEPS,
        help="step limit used to validate calibrated max-volume commands before send",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    for name in ["status", "prime", "stop", "emergency-stop", "reset-steps", "clear-fault"]:
        sub.add_parser(name)
    sub.add_parser("step").add_argument("value")
    sub.add_parser("run-rate").add_argument("value")
    sub.add_parser("set-ml-per-step").add_argument("value")
    sub.add_parser("set-steps-per-ml").add_argument("value")
    sub.add_parser("set-max-total-steps").add_argument("value")
    sub.add_parser("set-max-volume-ml").add_argument("value")
    sub.add_parser("set-dir").add_argument("value", choices=("forward", "reverse"))
    sub.add_parser("send", help="send a raw firmware command").add_argument("value")
    return parser.parse_args(argv)


def _positive_int_text(value: str, label: str, validator: Callable[[int], int]) -> str:
    parsed = int(value)
    return str(validator(parsed))


def _positive_float_text(value: str, label: str, validator: Callable[[float], float]) -> str:
    parsed = float(value)
    try:
        validator(parsed)
        return format_firmware_float(parsed)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc


def command_from_args(args: argparse.Namespace) -> str:
    action = args.action
    if action == "status":
        return "STATUS"
    if action == "prime":
        return "PRIME"
    if action == "step":
        return f"STEP {_positive_int_text(args.value, 'steps', validate_step_command_count)}"
    if action == "run-rate":
        return (
            "RUN_RATE "
            f"{_positive_float_text(args.value, 'ml_per_s', lambda value: validate_run_rate_ml_per_s(value, ml_per_step=args.ml_per_step))}"
        )
    if action == "stop":
        return "STOP"
    if action == "emergency-stop":
        return "EMERGENCY_STOP"
    if action == "set-ml-per-step":
        return f"SET_ML_PER_STEP {_positive_float_text(args.value, 'ml_per_step', validate_ml_per_step)}"
    if action == "set-steps-per-ml":
        return f"SET_STEPS_PER_ML {_positive_float_text(args.value, 'steps_per_ml', validate_steps_per_ml)}"
    if action == "set-max-total-steps":
        return f"SET_MAX_TOTAL_STEPS {_positive_int_text(args.value, 'max_total_steps', lambda value: validate_max_total_steps(value, maximum=args.max_steps))}"
    if action == "set-max-volume-ml":
        return (
            "SET_MAX_VOLUME_ML "
            f"{_positive_float_text(args.value, 'max_volume_ml', lambda value: validate_calibrated_max_volume_ml(value, ml_per_step=args.ml_per_step, maximum_steps=args.max_steps))}"
        )
    if action == "set-dir":
        return f"SET_DIR {str(args.value).upper()}"
    if action == "reset-steps":
        return "RESET_STEPS"
    if action == "clear-fault":
        return "CLEAR_FAULT"
    if action == "send":
        command = str(args.value).strip()
        if not command:
            raise ValueError("raw command must not be empty")
        return command
    raise ValueError(f"unsupported action: {action}")


def run_serial_command(
    *,
    port: str,
    firmware_command: str,
    baudrate: int = 115200,
    timeout_s: float = 2.0,
    read_lines: int = 6,
    serial_factory: Callable[..., SerialLike] = pyserial_factory,
) -> list[str]:
    if read_lines < 0:
        raise ValueError("read_lines must be zero or positive")
    serial_obj = serial_factory(port=port, baudrate=baudrate, timeout=timeout_s)
    try:
        serial_obj.write(f"{firmware_command}\n".encode("ascii"))
        responses: list[str] = []
        for _ in range(read_lines):
            raw = serial_obj.readline()
            if not raw:
                break
            responses.append(raw.decode("utf-8", errors="replace").strip())
        return [line for line in responses if line]
    finally:
        serial_obj.close()


def main(argv: list[str] | None = None, *, serial_factory: Callable[..., SerialLike] = pyserial_factory) -> int:
    try:
        args = parse_args(argv)
        firmware_command = command_from_args(args)
        print(f"> {firmware_command}")
        responses = run_serial_command(
            port=args.port,
            firmware_command=firmware_command,
            baudrate=args.baud,
            timeout_s=args.timeout_s,
            read_lines=args.read_lines,
            serial_factory=serial_factory,
        )
        for line in responses:
            print(line)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI reports concise hardware/setup errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
