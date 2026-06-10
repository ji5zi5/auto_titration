"""Simple live-status and simulated equivalence analysis helpers.

The first implementation is deliberately status/report-only. It has no pump
imports and no authority to stop or command a motor.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Mapping

from .equivalence_analysis import EquivalenceResult, estimate_equivalence_point
from .feature_history import FeatureHistory, FeatureSample


DEFAULT_OPERATIONAL_MODES = (
    "simulated",
    "recorded/replay",
    "live_color_only",
    "live_color_plus_palette",
    "live_color_plus_calibrated_thermal",
)


class LatestSampleBuffer:
    """Backpressure helper: prediction consumes only the newest sample."""

    def __init__(self) -> None:
        self._latest: FeatureSample | None = None

    def push(self, sample: FeatureSample) -> None:
        self._latest = sample

    def pop_latest(self) -> FeatureSample | None:
        latest = self._latest
        self._latest = None
        return latest


def classify_status(
    sample: FeatureSample,
    *,
    near_delta: float = 5.0,
    endpoint_delta: float = 12.0,
    endpoint_seen: bool = False,
) -> tuple[str, float]:
    """Return a transparent baseline status label from scalar feature values."""

    delta = _feature(sample.visible_features, "visible_color_delta", "color_delta") or 0.0
    thermal_delta = _feature(sample.thermal_features, "thermal_color_delta", "thermal_roi_delta", "thermal_delta") or 0.0
    combined = max(delta, thermal_delta)
    if combined >= endpoint_delta:
        return "endpoint", min(0.95, 0.65 + combined / 100.0)
    if endpoint_seen:
        return "overshoot", min(0.85, 0.45 + max(0.0, endpoint_delta - combined) / 100.0)
    if combined >= near_delta:
        return "near_endpoint", min(0.85, 0.45 + combined / 100.0)
    return "before", max(0.1, 0.35 - combined / 100.0)


def run_simulated_equivalence_analysis(output_path: str | Path) -> EquivalenceResult:
    """Run a hardware-free simulated titration and write a final result JSON."""

    history = FeatureHistory(max_recent=50)
    endpoint_seen = False
    for sample in _simulated_samples():
        label, confidence = classify_status(sample, endpoint_seen=endpoint_seen)
        sample.status_label = label
        sample.status_confidence = confidence
        endpoint_seen = endpoint_seen or label == "endpoint"
        sample.source_quality = "simulated_color_only"
        sample.warnings = ("thermal data unavailable in simulated color-only mode",)
        history.add(sample)

    result = estimate_equivalence_point(history.full_history(), theoretical_equivalence_volume_ml=9.2)
    payload = {
        **result.to_dict(),
        "evidence": list(result.evidence),
        "warnings": list(result.warnings),
        "operational_mode": "simulated",
        "feature_history": history.to_serializable_rows(),
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _simulated_samples() -> Iterable[FeatureSample]:
    color_deltas = [0.3, 0.4, 0.4, 0.5, 0.7, 1.0, 2.0, 4.5, 7.0, 15.0, 5.0, 2.0, 1.0]
    for frame_id, color_delta in enumerate(color_deltas):
        yield FeatureSample(
            time_s=float(frame_id),
            frame_id=frame_id,
            injected_volume_ml=float(frame_id),
            visible_features={"visible_color_delta": color_delta},
        )


def _feature(mapping: Mapping[str, object] | object, *keys: str) -> float | None:
    if not isinstance(mapping, Mapping):
        return None
    for key in keys:
        value = mapping.get(key)
        if value in (None, ""):
            continue
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except ValueError:
                return None
        return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run status-only equivalence-point analysis helpers")
    parser.add_argument("--simulated", action="store_true", help="Run hardware-free simulated analysis")
    parser.add_argument("--output", default="data/raw/simulated-equivalence-result.json")
    args = parser.parse_args(argv)
    if args.simulated:
        result = run_simulated_equivalence_analysis(args.output)
        print(f"estimated equivalence: {result.estimated_equivalence_volume_ml:g} mL at {result.estimated_equivalence_time_s:g} s")
        print(f"saved result: {args.output}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
