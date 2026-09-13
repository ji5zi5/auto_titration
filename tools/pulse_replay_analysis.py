#!/usr/bin/env python3
"""Replay recorded endpoint labels under three hypothetical stop schedules.

This is deliberately a dependency-free, offline counterfactual calculation.  It
does not recreate mixing, pump mechanics, sensor response after a hypothetical
pause, or any other wet-lab behavior.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


DISCLAIMER = (
    "Offline counterfactual simulation from recorded CSV labels; this is not actual wet "
    "performance, pump validation, delivered-volume measurement, or evidence that one "
    "policy improves titration accuracy."
)


class DatasetError(ValueError):
    """The CSV cannot support the requested replay."""


@dataclass(frozen=True)
class Observation:
    time_s: float
    volume_ml: float
    endpoint: bool


@dataclass(frozen=True)
class LoadedTrace:
    path: Path
    observations: tuple[Observation, ...]
    columns: dict[str, str]
    sha256: str
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    stopped: bool
    stop_time_s: float | None
    recorded_stop_volume_ml: float | None
    simulated_stop_volume_ml: float | None
    pulse_count: int
    nominal_pulse_volume_ml: float
    diagnostic: str


def _normalized(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.strip().lower())


ALIASES = {
    "time": (
        "times",
        "timestamps",
        "timestampsec",
        "elapsedtimes",
        "csvrecordingelapseds",
        "pumpelapseds",
    ),
    "volume": (
        "injectedvolumeml",
        "injectedml",
        "pumpvolumeml",
        "volumeml",
        "deliveredvolumeml",
    ),
    "endpoint": (
        "endpointdetected",
        "isendpoint",
        "endpoint",
        "endpointcandidate",
        "stopcandidate",
    ),
    "label": (
        "statuslabel",
        "predictionlabel",
        "predictedlabel",
        "phaselabel",
        "state",
    ),
}

TRUE_VALUES = {"1", "true", "t", "yes", "y", "on", "endpoint", "detected"}
FALSE_VALUES = {"0", "false", "f", "no", "n", "off", "", "before", "overshoot"}
DEFAULT_ENDPOINT_LABELS = {"endpoint", "atendpoint", "equivalence", "equivalencepoint"}


def _find_column(fieldnames: Sequence[str], role: str) -> str | None:
    normalized = {_normalized(name): name for name in fieldnames}
    for alias in ALIASES[role]:
        if alias in normalized:
            return normalized[alias]
    return None


def _finite_float(value: object, *, column: str, row_number: int) -> float:
    try:
        result = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise DatasetError(f"row {row_number}: {column!r} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise DatasetError(f"row {row_number}: {column!r} must be finite")
    return result


def _boolean(value: object, *, column: str, row_number: int) -> bool:
    raw = str(value).strip().lower()
    try:
        numeric = float(raw)
    except ValueError:
        numeric = None
    if numeric in (0.0, 1.0):
        return bool(numeric)
    normalized = _normalized(raw)
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise DatasetError(
        f"row {row_number}: {column!r} has unsupported boolean value {value!r}"
    )


def load_trace(
    path: Path | str,
    *,
    endpoint_labels: Iterable[str] = DEFAULT_ENDPOINT_LABELS,
) -> LoadedTrace:
    """Load a trace while tolerating common case, spacing, and unit-name variants."""

    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise DatasetError(f"cannot read CSV {path}: {exc}") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DatasetError(f"CSV is not UTF-8/UTF-8-BOM: {path}") from exc

    reader = csv.DictReader(io.StringIO(text, newline=""))
    fieldnames = reader.fieldnames or []
    if not fieldnames:
        raise DatasetError("CSV has no header")
    columns = {role: _find_column(fieldnames, role) for role in ("time", "volume", "endpoint", "label")}
    missing = [role for role in ("time", "volume") if columns[role] is None]
    if columns["endpoint"] is None and columns["label"] is None:
        missing.append("endpoint or label")
    if missing:
        available = ", ".join(repr(name) for name in fieldnames)
        raise DatasetError(
            f"missing required column(s): {', '.join(missing)}; available columns: {available}"
        )

    accepted_labels = {_normalized(label) for label in endpoint_labels}
    parsed: list[tuple[float, float, bool]] = []
    for row_number, row in enumerate(reader, start=2):
        if not any(str(value or "").strip() for value in row.values()):
            continue
        time_s = _finite_float(row[columns["time"]], column=columns["time"], row_number=row_number)
        volume_ml = _finite_float(
            row[columns["volume"]], column=columns["volume"], row_number=row_number
        )
        if volume_ml < 0:
            raise DatasetError(f"row {row_number}: volume must be non-negative")
        if columns["endpoint"] is not None:
            endpoint = _boolean(
                row[columns["endpoint"]], column=columns["endpoint"], row_number=row_number
            )
        else:
            endpoint = _normalized(row[columns["label"]]) in accepted_labels
        parsed.append((time_s, volume_ml, endpoint))

    if not parsed:
        raise DatasetError("CSV has no data rows")
    for previous, current in zip(parsed, parsed[1:]):
        if current[0] < previous[0]:
            raise DatasetError("time column is not monotonic")
        if current[1] < previous[1] - 1e-9:
            raise DatasetError("volume column is not monotonic")

    origin = parsed[0][0]
    observations = tuple(Observation(time - origin, volume, endpoint) for time, volume, endpoint in parsed)
    used_columns = {
        role: name
        for role, name in columns.items()
        if name is not None and (role != "label" or columns["endpoint"] is None)
    }
    return LoadedTrace(
        path=path,
        observations=observations,
        columns=used_columns,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def _confirmed_stop(
    observations: Sequence[Observation], confirmation_s: float
) -> Observation | None:
    started: float | None = None
    for observation in observations:
        if observation.endpoint:
            if started is None:
                started = observation.time_s
            if observation.time_s - started + 1e-12 >= confirmation_s:
                return observation
        else:
            started = None
    return None


def compare_policies(
    observations: Sequence[Observation],
    *,
    confirmation_s: float = 0.4,
    settle_s: float = 0.5,
    pulse_steps: int = 5,
    ml_per_step: float = 0.0099,
) -> tuple[PolicyResult, ...]:
    """Compare scheduling policies without asserting physical counterfactual response."""

    if not observations:
        raise ValueError("observations must not be empty")
    if confirmation_s < 0 or settle_s <= 0 or pulse_steps <= 0 or ml_per_step <= 0:
        raise ValueError("durations, pulse_steps, and ml_per_step must be positive (confirmation may be zero)")
    pulse_volume = pulse_steps * ml_per_step
    immediate = next((item for item in observations if item.endpoint), None)
    confirmed = _confirmed_stop(observations, confirmation_s)

    def continuous_result(name: str, stop: Observation | None) -> PolicyResult:
        return PolicyResult(
            policy=name,
            stopped=stop is not None,
            stop_time_s=None if stop is None else stop.time_s,
            recorded_stop_volume_ml=None if stop is None else stop.volume_ml,
            simulated_stop_volume_ml=None if stop is None else stop.volume_ml,
            pulse_count=0,
            nominal_pulse_volume_ml=pulse_volume,
            diagnostic="stopped on replayed label" if stop else "no qualifying endpoint-positive sequence",
        )

    mixed_stop: Observation | None = None
    pulse_count = 0
    approach_volume: float | None = None
    candidate_started: float | None = None
    next_pulse_at: float | None = None
    if immediate is not None:
        approach_volume = immediate.volume_ml
        next_pulse_at = immediate.time_s + settle_s
        for observation in observations[observations.index(immediate) :]:
            if observation.endpoint:
                if candidate_started is None:
                    candidate_started = observation.time_s
                if observation.time_s - candidate_started + 1e-12 >= confirmation_s:
                    mixed_stop = observation
                    break
            else:
                candidate_started = None
            while next_pulse_at is not None and observation.time_s + 1e-12 >= next_pulse_at:
                pulse_count += 1
                next_pulse_at += settle_s

    mixed = PolicyResult(
        policy="step5_0.5s_mixed_wait",
        stopped=mixed_stop is not None,
        stop_time_s=None if mixed_stop is None else mixed_stop.time_s,
        recorded_stop_volume_ml=None if mixed_stop is None else mixed_stop.volume_ml,
        simulated_stop_volume_ml=(
            None if mixed_stop is None else float(approach_volume) + pulse_count * pulse_volume
        ),
        pulse_count=pulse_count,
        nominal_pulse_volume_ml=pulse_volume,
        diagnostic=(
            "nominal command-volume schedule only; replayed labels retain their original wet-run timing"
            if mixed_stop
            else "no 0.4 s endpoint-positive sequence; no simulated stop"
        ),
    )
    return (
        continuous_result("continuous_immediate_stop", immediate),
        continuous_result("continuous_0.4s_confirmed_stop", confirmed),
        mixed,
    )


def paths_from_inventory(inventory: Path | str, raw_dir: Path | str) -> tuple[list[Path], list[str]]:
    inventory = Path(inventory)
    raw_dir = Path(raw_dir)
    diagnostics: list[str] = []
    try:
        with inventory.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as exc:
        raise DatasetError(f"cannot read inventory {inventory}: {exc}") from exc
    if not rows or "raw_file" not in rows[0]:
        raise DatasetError("inventory must contain a raw_file column and at least one row")
    paths: list[Path] = []
    for index, row in enumerate(rows, start=2):
        filename = str(row.get("raw_file") or "").strip()
        if not filename:
            diagnostics.append(f"inventory row {index}: empty raw_file")
            continue
        path = raw_dir / filename
        if not path.is_file():
            diagnostics.append(f"inventory row {index}: missing CSV {path}")
            continue
        paths.append(path)
    return paths, diagnostics


def analyze_paths(
    paths: Iterable[Path | str],
    *,
    confirmation_s: float = 0.4,
    settle_s: float = 0.5,
    pulse_steps: int = 5,
    ml_per_step: float = 0.0099,
) -> list[dict[str, object]]:
    analyses: list[dict[str, object]] = []
    for path_value in paths:
        path = Path(path_value)
        try:
            trace = load_trace(path)
            endpoint_rows = sum(item.endpoint for item in trace.observations)
            if endpoint_rows == 0:
                analyses.append(
                    {
                        "path": str(path),
                        "usable": False,
                        "diagnostic": "no endpoint-positive rows; policies cannot produce a stop",
                        "row_count": len(trace.observations),
                        "sha256": trace.sha256,
                        "columns": trace.columns,
                        "policies": [],
                    }
                )
                continue
            policies = compare_policies(
                trace.observations,
                confirmation_s=confirmation_s,
                settle_s=settle_s,
                pulse_steps=pulse_steps,
                ml_per_step=ml_per_step,
            )
            analyses.append(
                {
                    "path": str(path),
                    "usable": True,
                    "diagnostic": "",
                    "row_count": len(trace.observations),
                    "endpoint_positive_rows": endpoint_rows,
                    "sha256": trace.sha256,
                    "columns": trace.columns,
                    "policies": [asdict(policy) for policy in policies],
                }
            )
        except DatasetError as exc:
            analyses.append(
                {"path": str(path), "usable": False, "diagnostic": str(exc), "policies": []}
            )
    return analyses


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="CSV traces; defaults to the 12-run inventory")
    parser.add_argument("--inventory", type=Path, default=Path("data/analysis/report_evidence_no_new_wet/raw_inventory.csv"))
    parser.add_argument("--raw-dir", type=Path, default=Path("머신러닝용 파일모음"))
    parser.add_argument("--confirmation-s", type=float, default=0.4)
    parser.add_argument("--settle-s", type=float, default=0.5)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--ml-per-step", type=float, default=0.0099)
    parser.add_argument("--json", action="store_true", help="emit deterministic JSON (default output is a text summary)")
    parser.add_argument("--output", type=Path, help="also write the complete JSON artifact to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    inventory_diagnostics: list[str] = []
    try:
        paths = list(args.paths)
        if not paths:
            paths, inventory_diagnostics = paths_from_inventory(args.inventory, args.raw_dir)
        analyses = analyze_paths(
            paths,
            confirmation_s=args.confirmation_s,
            settle_s=args.settle_s,
            pulse_steps=args.pulse_steps,
            ml_per_step=args.ml_per_step,
        )
    except (DatasetError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "analysis_type": "offline_counterfactual_simulation",
        "claims_wet_performance": False,
        "disclaimer": DISCLAIMER,
        "parameters": {
            "confirmation_s": args.confirmation_s,
            "settle_s": args.settle_s,
            "pulse_steps": args.pulse_steps,
            "ml_per_step": args.ml_per_step,
            "nominal_pulse_volume_ml": args.pulse_steps * args.ml_per_step,
        },
        "inventory_diagnostics": inventory_diagnostics,
        "runs": analyses,
        "summary": {
            "requested_run_count": len(paths) + len(inventory_diagnostics),
            "loaded_run_count": len(paths),
            "usable_run_count": sum(bool(item["usable"]) for item in analyses),
            "diagnosed_run_count": len(inventory_diagnostics)
            + sum(not bool(item["usable"]) for item in analyses),
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    if args.json:
        sys.stdout.write(encoded)
    else:
        print(DISCLAIMER)
        print(
            f"runs: requested={payload['summary']['requested_run_count']}, "
            f"usable={payload['summary']['usable_run_count']}, "
            f"diagnosed={payload['summary']['diagnosed_run_count']}"
        )
        for item in analyses:
            if not item["usable"]:
                print(f"DIAGNOSTIC {item['path']}: {item['diagnostic']}")
                continue
            compact = ", ".join(
                f"{policy['policy']}={policy['simulated_stop_volume_ml']} mL"
                for policy in item["policies"]
            )
            print(f"{item['path']}: {compact}")
    return 0 if analyses and any(item["usable"] for item in analyses) else 2


if __name__ == "__main__":
    raise SystemExit(main())
