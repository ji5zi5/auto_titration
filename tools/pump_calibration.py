#!/usr/bin/env python3
"""Calculate syringe-pump ml/step calibration from water-dispense trials."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path


def format_float(value: float, *, digits: int = 6) -> str:
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class CalibrationTrial:
    trial: int
    commanded_steps: int
    measured_volume_ml: float
    ml_per_step: float
    steps_per_ml: float
    percent_error_from_mean: float


@dataclass(frozen=True)
class CalibrationResult:
    trials: list[CalibrationTrial]
    mean_ml_per_step: float
    mean_steps_per_ml: float
    total_steps: int
    total_volume_ml: float

    @property
    def set_ml_per_step_command(self) -> str:
        return f"SET_ML_PER_STEP {format_float(self.mean_ml_per_step)}"

    @property
    def set_steps_per_ml_command(self) -> str:
        return f"SET_STEPS_PER_ML {format_float(self.mean_steps_per_ml)}"

    def summary_dict(self) -> dict[str, object]:
        return {
            "trial_count": len(self.trials),
            "total_steps": self.total_steps,
            "total_volume_ml": round(self.total_volume_ml, 9),
            "mean_ml_per_step": round(self.mean_ml_per_step, 12),
            "mean_steps_per_ml": round(self.mean_steps_per_ml, 6),
            "set_ml_per_step_command": self.set_ml_per_step_command,
            "set_steps_per_ml_command": self.set_steps_per_ml_command,
            "note": "Use water calibration before acids/bases; repeat after changing syringe, hose, tip, driver, or microstepping.",
        }


def calculate_calibration(*, steps: int, measured_volumes_ml: list[float]) -> CalibrationResult:
    if steps <= 0:
        raise ValueError("steps must be positive")
    if not measured_volumes_ml:
        raise ValueError("at least one measured volume is required")
    if any(volume <= 0 for volume in measured_volumes_ml):
        raise ValueError("all measured volumes must be positive")

    total_steps = steps * len(measured_volumes_ml)
    total_volume = sum(measured_volumes_ml)
    mean_ml_per_step = total_volume / total_steps
    mean_steps_per_ml = total_steps / total_volume
    trials: list[CalibrationTrial] = []
    for index, volume in enumerate(measured_volumes_ml, start=1):
        ml_per_step = volume / steps
        steps_per_ml = steps / volume
        percent_error = ((ml_per_step - mean_ml_per_step) / mean_ml_per_step) * 100.0
        trials.append(
            CalibrationTrial(
                trial=index,
                commanded_steps=steps,
                measured_volume_ml=volume,
                ml_per_step=ml_per_step,
                steps_per_ml=steps_per_ml,
                percent_error_from_mean=percent_error,
            )
        )
    return CalibrationResult(
        trials=trials,
        mean_ml_per_step=mean_ml_per_step,
        mean_steps_per_ml=mean_steps_per_ml,
        total_steps=total_steps,
        total_volume_ml=total_volume,
    )


def write_csv(result: CalibrationResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "trial",
                "commanded_steps",
                "measured_volume_ml",
                "ml_per_step",
                "steps_per_ml",
                "percent_error_from_mean",
            ],
        )
        writer.writeheader()
        for trial in result.trials:
            writer.writerow(
                {
                    "trial": trial.trial,
                    "commanded_steps": trial.commanded_steps,
                    "measured_volume_ml": format_float(trial.measured_volume_ml),
                    "ml_per_step": format_float(trial.ml_per_step, digits=9),
                    "steps_per_ml": format_float(trial.steps_per_ml),
                    "percent_error_from_mean": format_float(trial.percent_error_from_mean),
                }
            )


def write_summary(result: CalibrationResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.summary_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def process(
    *,
    steps: int,
    measured_volumes_ml: list[float],
    output: Path,
    summary_output: Path | None = None,
) -> CalibrationResult:
    result = calculate_calibration(steps=steps, measured_volumes_ml=measured_volumes_ml)
    write_csv(result, output)
    write_summary(result, summary_output or output.with_suffix(".summary.json"))
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, required=True, help="motor steps used for each trial, e.g. 1000")
    parser.add_argument(
        "--measured-ml",
        type=float,
        action="append",
        required=True,
        help="measured dispensed water volume for one trial; repeat for multiple trials",
    )
    parser.add_argument("--output", type=Path, default=Path("data/raw/pump-calibration.csv"))
    parser.add_argument("--summary-output", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = process(
        steps=args.steps,
        measured_volumes_ml=args.measured_ml,
        output=args.output,
        summary_output=args.summary_output,
    )
    print(f"saved calibration CSV: {args.output}")
    print(f"mean ml_per_step: {format_float(result.mean_ml_per_step)}")
    print(f"mean steps_per_ml: {format_float(result.mean_steps_per_ml)}")
    print(result.set_ml_per_step_command)
    print(result.set_steps_per_ml_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
