#!/usr/bin/env python3
"""Calculate syringe-pump ml/step calibration from water-dispense trials."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CALIBRATION_POSITIONS = ("early", "middle", "late")
CALIBRATION_COMMAND_STEPS = (5, 10, 20, 50)
MIN_REPETITIONS_PER_POSITION_COMMAND = 10
TEMPLATE_PULSE_COUNT = 100


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


@dataclass(frozen=True)
class CalibrationObservation:
    """One independently measured water-dispense observation.

    ``position`` identifies the syringe-plunger region (for example early,
    middle, or late).  ``pulse_count`` and ``pulse_steps`` are optional because
    continuous-flow calibration trials may only have a total step count.
    """

    position: str
    trial: int
    commanded_steps: int
    measured_volume_ml: float
    pulse_count: int | None = None
    pulse_steps: int | None = None

    def __post_init__(self) -> None:
        if not str(self.position).strip():
            raise ValueError("position must not be empty")
        if isinstance(self.trial, bool) or not isinstance(self.trial, int) or self.trial <= 0:
            raise ValueError("trial must be a positive integer")
        if (
            isinstance(self.commanded_steps, bool)
            or not isinstance(self.commanded_steps, int)
            or self.commanded_steps <= 0
        ):
            raise ValueError("commanded_steps must be a positive integer")
        if not math.isfinite(self.measured_volume_ml) or self.measured_volume_ml <= 0:
            raise ValueError("measured_volume_ml must be positive and finite")
        for name in ("pulse_count", "pulse_steps"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer when provided")
        if (
            self.pulse_count is not None
            and self.pulse_steps is not None
            and self.pulse_count * self.pulse_steps != self.commanded_steps
        ):
            raise ValueError("pulse_count * pulse_steps must equal commanded_steps")

    @property
    def ml_per_step(self) -> float:
        return self.measured_volume_ml / self.commanded_steps

    @property
    def volume_per_pulse_ml(self) -> float | None:
        if self.pulse_count is None:
            return None
        return self.measured_volume_ml / self.pulse_count

    @property
    def command_steps(self) -> int:
        """Return the individual STEP command size represented by this trial."""

        if self.pulse_steps is not None:
            return self.pulse_steps
        if self.pulse_count is not None and self.commanded_steps % self.pulse_count == 0:
            return self.commanded_steps // self.pulse_count
        return self.commanded_steps


@dataclass(frozen=True)
class CalibrationStatistics:
    trial_count: int
    total_steps: int
    total_volume_ml: float
    weighted_ml_per_step: float
    mean_trial_ml_per_step: float
    sample_sd_ml_per_step: float
    cv_percent: float
    minimum_ml_per_step: float
    maximum_ml_per_step: float
    mean_volume_per_pulse_ml: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "trial_count": self.trial_count,
            "total_steps": self.total_steps,
            "total_volume_ml": round(self.total_volume_ml, 9),
            "weighted_ml_per_step": round(self.weighted_ml_per_step, 12),
            "mean_trial_ml_per_step": round(self.mean_trial_ml_per_step, 12),
            "sample_sd_ml_per_step": round(self.sample_sd_ml_per_step, 12),
            "cv_percent": round(self.cv_percent, 6),
            "minimum_ml_per_step": round(self.minimum_ml_per_step, 12),
            "maximum_ml_per_step": round(self.maximum_ml_per_step, 12),
            "mean_volume_per_pulse_ml": (
                None
                if self.mean_volume_per_pulse_ml is None
                else round(self.mean_volume_per_pulse_ml, 9)
            ),
        }


@dataclass(frozen=True)
class PositionCalibrationResult:
    observations: tuple[CalibrationObservation, ...]
    overall: CalibrationStatistics
    by_position: dict[str, CalibrationStatistics]
    nominal_ml_per_step: float | None
    nominal_bias_percent: float | None
    position_drift_percent: float
    linearity_slope_ml_per_step: float | None
    linearity_intercept_ml: float | None
    linearity_r_squared: float | None

    def position_command_group_counts(self) -> list[dict[str, Any]]:
        counts: dict[tuple[str, int], int] = defaultdict(int)
        for observation in self.observations:
            counts[(observation.position.strip(), observation.command_steps)] += 1

        groups = []
        for position in CALIBRATION_POSITIONS:
            for command_steps in CALIBRATION_COMMAND_STEPS:
                observed_count = counts[(position, command_steps)]
                groups.append(
                    {
                        "position": position,
                        "command_steps": command_steps,
                        "observed_count": observed_count,
                        "required_count": MIN_REPETITIONS_PER_POSITION_COMMAND,
                        "missing_count": max(
                            0,
                            MIN_REPETITIONS_PER_POSITION_COMMAND - observed_count,
                        ),
                        "sufficient": observed_count >= MIN_REPETITIONS_PER_POSITION_COMMAND,
                    }
                )
        return groups

    def summary_dict(self) -> dict[str, Any]:
        group_counts = self.position_command_group_counts()
        return {
            "evidence_scope": "measured_water_trials",
            "claims_actual_single_drop_volume": False,
            "trial_count": len(self.observations),
            "overall": self.overall.as_dict(),
            "by_position": {
                position: stats.as_dict() for position, stats in sorted(self.by_position.items())
            },
            "minimum_repetitions_per_position_command": MIN_REPETITIONS_PER_POSITION_COMMAND,
            "position_command_group_counts": group_counts,
            "insufficient_position_command_groups": [
                group for group in group_counts if not group["sufficient"]
            ],
            "nominal_ml_per_step": (
                None if self.nominal_ml_per_step is None else round(self.nominal_ml_per_step, 12)
            ),
            "nominal_bias_percent": (
                None if self.nominal_bias_percent is None else round(self.nominal_bias_percent, 6)
            ),
            "position_drift_percent": round(self.position_drift_percent, 6),
            "linearity_slope_ml_per_step": (
                None
                if self.linearity_slope_ml_per_step is None
                else round(self.linearity_slope_ml_per_step, 12)
            ),
            "linearity_intercept_ml": (
                None if self.linearity_intercept_ml is None else round(self.linearity_intercept_ml, 9)
            ),
            "linearity_r_squared": (
                None if self.linearity_r_squared is None else round(self.linearity_r_squared, 9)
            ),
            "interpretation": (
                "Values quantify repeated water-dispense trials. A pulse-volume value is an aggregate "
                "measurement divided by commanded pulse count, not a direct optical measurement of one drop."
            ),
        }


def _statistics_for(observations: list[CalibrationObservation]) -> CalibrationStatistics:
    if not observations:
        raise ValueError("at least one calibration observation is required")
    values = [item.ml_per_step for item in observations]
    mean_trial = statistics.fmean(values)
    sample_sd = statistics.stdev(values) if len(values) > 1 else 0.0
    total_steps = sum(item.commanded_steps for item in observations)
    total_volume = sum(item.measured_volume_ml for item in observations)
    total_pulses = sum(item.pulse_count or 0 for item in observations)
    pulsed_volume = sum(
        item.measured_volume_ml for item in observations if item.pulse_count is not None
    )
    return CalibrationStatistics(
        trial_count=len(observations),
        total_steps=total_steps,
        total_volume_ml=total_volume,
        weighted_ml_per_step=total_volume / total_steps,
        mean_trial_ml_per_step=mean_trial,
        sample_sd_ml_per_step=sample_sd,
        cv_percent=0.0 if mean_trial == 0 else sample_sd / mean_trial * 100.0,
        minimum_ml_per_step=min(values),
        maximum_ml_per_step=max(values),
        mean_volume_per_pulse_ml=(None if total_pulses == 0 else pulsed_volume / total_pulses),
    )


def _linearity(
    observations: list[CalibrationObservation],
) -> tuple[float | None, float | None, float | None]:
    if len(observations) < 2 or len({item.commanded_steps for item in observations}) < 2:
        return None, None, None
    x = [float(item.commanded_steps) for item in observations]
    y = [item.measured_volume_ml for item in observations]
    x_mean = statistics.fmean(x)
    y_mean = statistics.fmean(y)
    x_variance_sum = sum((value - x_mean) ** 2 for value in x)
    if x_variance_sum <= 0:
        return None, None, None
    slope = sum((xv - x_mean) * (yv - y_mean) for xv, yv in zip(x, y)) / x_variance_sum
    intercept = y_mean - slope * x_mean
    residual_sum = sum((yv - (intercept + slope * xv)) ** 2 for xv, yv in zip(x, y))
    total_sum = sum((yv - y_mean) ** 2 for yv in y)
    r_squared = 1.0 if total_sum <= 0 else 1.0 - residual_sum / total_sum
    return slope, intercept, r_squared


def analyze_observations(
    observations: list[CalibrationObservation],
    *,
    nominal_ml_per_step: float | None = None,
) -> PositionCalibrationResult:
    if not observations:
        raise ValueError("at least one calibration observation is required")
    if nominal_ml_per_step is not None and (
        not math.isfinite(nominal_ml_per_step) or nominal_ml_per_step <= 0
    ):
        raise ValueError("nominal_ml_per_step must be positive and finite")
    grouped: dict[str, list[CalibrationObservation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.position.strip()].append(observation)
    overall = _statistics_for(observations)
    by_position = {position: _statistics_for(items) for position, items in grouped.items()}
    position_means = [stats.weighted_ml_per_step for stats in by_position.values()]
    position_drift = (
        0.0
        if len(position_means) < 2
        else (max(position_means) - min(position_means)) / overall.weighted_ml_per_step * 100.0
    )
    nominal_bias = (
        None
        if nominal_ml_per_step is None
        else (overall.weighted_ml_per_step - nominal_ml_per_step) / nominal_ml_per_step * 100.0
    )
    slope, intercept, r_squared = _linearity(observations)
    return PositionCalibrationResult(
        observations=tuple(observations),
        overall=overall,
        by_position=by_position,
        nominal_ml_per_step=nominal_ml_per_step,
        nominal_bias_percent=nominal_bias,
        position_drift_percent=position_drift,
        linearity_slope_ml_per_step=slope,
        linearity_intercept_ml=intercept,
        linearity_r_squared=r_squared,
    )


def _optional_positive_int(row: dict[str, str], key: str) -> int | None:
    raw = str(row.get(key, "") or "").strip()
    if not raw:
        return None
    value = int(raw)
    if value <= 0:
        raise ValueError(f"{key} must be positive")
    return value


def read_observations(path: Path) -> list[CalibrationObservation]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"position", "trial", "commanded_steps", "measured_volume_ml"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise ValueError(f"calibration CSV is missing columns: {', '.join(missing)}")
        observations: list[CalibrationObservation] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                observations.append(
                    CalibrationObservation(
                        position=str(row["position"]).strip(),
                        trial=int(str(row["trial"]).strip()),
                        commanded_steps=int(str(row["commanded_steps"]).strip()),
                        measured_volume_ml=float(str(row["measured_volume_ml"]).strip()),
                        pulse_count=_optional_positive_int(row, "pulse_count"),
                        pulse_steps=_optional_positive_int(row, "pulse_steps"),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid calibration CSV row {row_number}: {exc}") from exc
    if not observations:
        raise ValueError("calibration CSV has no data rows")
    return observations


def write_observation_analysis_csv(result: PositionCalibrationResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "position",
        "trial",
        "commanded_steps",
        "pulse_count",
        "pulse_steps",
        "measured_volume_ml",
        "measured_ml_per_step",
        "measured_steps_per_ml",
        "measured_volume_per_pulse_ml",
        "deviation_from_overall_percent",
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in result.observations:
            deviation = (
                (item.ml_per_step - result.overall.weighted_ml_per_step)
                / result.overall.weighted_ml_per_step
                * 100.0
            )
            writer.writerow(
                {
                    "position": item.position,
                    "trial": item.trial,
                    "commanded_steps": item.commanded_steps,
                    "pulse_count": "" if item.pulse_count is None else item.pulse_count,
                    "pulse_steps": "" if item.pulse_steps is None else item.pulse_steps,
                    "measured_volume_ml": format_float(item.measured_volume_ml, digits=9),
                    "measured_ml_per_step": format_float(item.ml_per_step, digits=12),
                    "measured_steps_per_ml": format_float(1.0 / item.ml_per_step, digits=9),
                    "measured_volume_per_pulse_ml": (
                        ""
                        if item.volume_per_pulse_ml is None
                        else format_float(item.volume_per_pulse_ml, digits=9)
                    ),
                    "deviation_from_overall_percent": format_float(deviation, digits=6),
                }
            )


def process_observation_csv(
    *,
    input_path: Path,
    output: Path,
    summary_output: Path,
    nominal_ml_per_step: float | None = None,
) -> PositionCalibrationResult:
    result = analyze_observations(
        read_observations(input_path),
        nominal_ml_per_step=nominal_ml_per_step,
    )
    write_observation_analysis_csv(result, output)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(result.summary_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def write_position_template(
    path: Path,
    *,
    repeats: int = MIN_REPETITIONS_PER_POSITION_COMMAND,
) -> None:
    """Write the documented position/STEP aggregate-pulse calibration template."""

    if repeats < MIN_REPETITIONS_PER_POSITION_COMMAND:
        raise ValueError(
            "repeats must be at least "
            f"{MIN_REPETITIONS_PER_POSITION_COMMAND} per piston position/command"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "position",
                "trial",
                "commanded_steps",
                "pulse_count",
                "pulse_steps",
                "measured_volume_ml",
                "notes",
            ],
        )
        writer.writeheader()
        for position in CALIBRATION_POSITIONS:
            for command_steps in CALIBRATION_COMMAND_STEPS:
                for trial in range(1, repeats + 1):
                    writer.writerow(
                        {
                            "position": position,
                            "trial": trial,
                            "commanded_steps": TEMPLATE_PULSE_COUNT * command_steps,
                            "pulse_count": TEMPLATE_PULSE_COUNT,
                            "pulse_steps": command_steps,
                            "measured_volume_ml": "",
                            "notes": (
                                f"{TEMPLATE_PULSE_COUNT} x STEP {command_steps} "
                                "aggregate water measurement"
                            ),
                        }
                    )


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--input-csv",
        type=Path,
        help="early/middle/late water-trial CSV to analyze",
    )
    mode.add_argument(
        "--write-position-template",
        type=Path,
        help="write the documented STEP 5/10/20/50 position template and exit",
    )
    parser.add_argument("--steps", type=int, help="motor steps used for each legacy trial, e.g. 1000")
    parser.add_argument(
        "--measured-ml",
        type=float,
        action="append",
        help="measured dispensed water volume for one trial; repeat for multiple trials",
    )
    parser.add_argument("--output", type=Path, default=Path("data/raw/pump-calibration.csv"))
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument(
        "--nominal-ml-per-step",
        type=float,
        default=None,
        help="optional nominal conversion used only to calculate bias",
    )
    parser.add_argument(
        "--template-repeats",
        type=int,
        default=MIN_REPETITIONS_PER_POSITION_COMMAND,
        help=(
            "repetitions per piston position/STEP command "
            f"(minimum {MIN_REPETITIONS_PER_POSITION_COMMAND})"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_position_template is not None:
        write_position_template(args.write_position_template, repeats=args.template_repeats)
        print(f"saved position calibration template: {args.write_position_template}")
        return 0
    if args.input_csv is not None:
        summary_output = args.summary_output or args.output.with_suffix(".summary.json")
        result = process_observation_csv(
            input_path=args.input_csv,
            output=args.output,
            summary_output=summary_output,
            nominal_ml_per_step=args.nominal_ml_per_step,
        )
        print(f"saved calibration analysis CSV: {args.output}")
        print(f"saved calibration summary JSON: {summary_output}")
        print(f"measured weighted ml_per_step: {format_float(result.overall.weighted_ml_per_step, digits=9)}")
        print(f"repeatability CV: {format_float(result.overall.cv_percent)}%")
        print(f"position drift: {format_float(result.position_drift_percent)}%")
        insufficient_groups = [
            group
            for group in result.position_command_group_counts()
            if not group["sufficient"]
        ]
        if insufficient_groups:
            print(
                "WARNING: insufficient repetitions for "
                f"{len(insufficient_groups)} position/command group(s):"
            )
            for group in insufficient_groups:
                print(
                    f"  {group['position']} STEP {group['command_steps']}: "
                    f"{group['observed_count']}/{group['required_count']}"
                )
        else:
            print("position/command repetition counts: sufficient")
        if result.linearity_r_squared is not None:
            print(f"time/step-volume linearity R^2: {format_float(result.linearity_r_squared, digits=9)}")
        return 0
    if args.steps is None or not args.measured_ml:
        raise SystemExit(
            "legacy mode requires --steps and at least one --measured-ml; "
            "otherwise use --input-csv or --write-position-template"
        )
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
