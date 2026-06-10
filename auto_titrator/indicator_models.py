"""Indicator transition-range models for endpoint/equivalence comparison."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class IndicatorPreset:
    key: str
    display_name: str
    transition_low_ph: float
    transition_high_ph: float
    low_color: str = ""
    high_color: str = ""

    @property
    def transition_midpoint_ph(self) -> float:
        return (self.transition_low_ph + self.transition_high_ph) / 2.0


@dataclass(frozen=True)
class IndicatorEndpointEstimate:
    indicator: IndicatorPreset
    equivalence_volume_ml: float
    endpoint_volume_ml: float | None
    endpoint_equivalence_offset_ml: float | None
    transition_start_volume_ml: float | None
    transition_end_volume_ml: float | None
    confidence: str
    warning: str

    def as_dict(self) -> dict[str, object]:
        return {
            "indicator": self.indicator.key,
            "indicator_name": self.indicator.display_name,
            "indicator_transition_low_ph": self.indicator.transition_low_ph,
            "indicator_transition_high_ph": self.indicator.transition_high_ph,
            "indicator_endpoint_volume_ml": self.endpoint_volume_ml,
            "indicator_endpoint_offset_ml": self.endpoint_equivalence_offset_ml,
            "indicator_transition_start_volume_ml": self.transition_start_volume_ml,
            "indicator_transition_end_volume_ml": self.transition_end_volume_ml,
            "indicator_endpoint_confidence": self.confidence,
            "indicator_endpoint_warning": self.warning,
        }


INDICATOR_PRESETS: dict[str, IndicatorPreset] = {
    "phenolphthalein": IndicatorPreset("phenolphthalein", "Phenolphthalein", 8.2, 10.0, "colorless", "pink"),
    "페놀프탈레인": IndicatorPreset("phenolphthalein", "Phenolphthalein", 8.2, 10.0, "colorless", "pink"),
    "methyl_orange": IndicatorPreset("methyl_orange", "Methyl orange", 3.1, 4.4, "red", "yellow"),
    "메틸오렌지": IndicatorPreset("methyl_orange", "Methyl orange", 3.1, 4.4, "red", "yellow"),
    "bromothymol_blue": IndicatorPreset("bromothymol_blue", "Bromothymol blue", 6.0, 7.6, "yellow", "blue"),
    "btb": IndicatorPreset("bromothymol_blue", "Bromothymol blue", 6.0, 7.6, "yellow", "blue"),
    "브로모티몰블루": IndicatorPreset("bromothymol_blue", "Bromothymol blue", 6.0, 7.6, "yellow", "blue"),
}


def get_indicator(key: str) -> IndicatorPreset:
    normalized = str(key).casefold().strip().replace(" ", "_").replace("-", "_")
    try:
        return INDICATOR_PRESETS[normalized]
    except KeyError as exc:
        raise ValueError(f"unknown indicator: {key}") from exc


def estimate_indicator_endpoint(
    ph_curve: Iterable[tuple[float, float] | Mapping[str, float]],
    *,
    indicator: str | IndicatorPreset,
    equivalence_volume_ml: float,
) -> IndicatorEndpointEstimate:
    """Estimate indicator endpoint volume from a volume/pH curve.

    Endpoint is represented by the transition midpoint crossing. The returned
    value is explicitly a model estimate/reference, not an exact equivalence.
    """

    preset = get_indicator(indicator) if isinstance(indicator, str) else indicator
    points = _normalize_curve(ph_curve)
    if len(points) < 2:
        return _low_confidence(preset, equivalence_volume_ml, "pH curve needs at least two points")

    midpoint = preset.transition_midpoint_ph
    endpoint = _crossing_volume(points, midpoint)
    start = _crossing_volume(points, preset.transition_low_ph)
    end = _crossing_volume(points, preset.transition_high_ph)
    if endpoint is None:
        return _low_confidence(
            preset,
            equivalence_volume_ml,
            f"pH curve does not clearly cross {preset.display_name} transition range; model estimate/reference unavailable",
        )
    offset = endpoint - float(equivalence_volume_ml)
    warning = (
        "Indicator endpoint is a model estimate/reference from transition-range crossing; "
        "it can differ from true equivalence volume."
    )
    return IndicatorEndpointEstimate(
        indicator=preset,
        equivalence_volume_ml=float(equivalence_volume_ml),
        endpoint_volume_ml=round(endpoint, 6),
        endpoint_equivalence_offset_ml=round(offset, 6),
        transition_start_volume_ml=None if start is None else round(start, 6),
        transition_end_volume_ml=None if end is None else round(end, 6),
        confidence="model_estimate",
        warning=warning,
    )


def _normalize_curve(ph_curve: Iterable[tuple[float, float] | Mapping[str, float]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for item in ph_curve:
        if isinstance(item, Mapping):
            volume = item.get("volume_ml", item.get("injected_volume_ml"))
            ph = item.get("pH", item.get("ph"))
        else:
            volume, ph = item
        if volume is None or ph is None:
            continue
        points.append((float(volume), float(ph)))
    return sorted(points, key=lambda pair: pair[0])


def _crossing_volume(points: Sequence[tuple[float, float]], target_ph: float) -> float | None:
    for (v0, ph0), (v1, ph1) in zip(points, points[1:]):
        d0 = ph0 - target_ph
        d1 = ph1 - target_ph
        if d0 == 0:
            return v0
        if d1 == 0:
            return v1
        if (d0 < 0 < d1) or (d1 < 0 < d0):
            fraction = (target_ph - ph0) / (ph1 - ph0)
            return v0 + fraction * (v1 - v0)
    return None


def _low_confidence(preset: IndicatorPreset, equivalence_volume_ml: float, warning: str) -> IndicatorEndpointEstimate:
    return IndicatorEndpointEstimate(
        indicator=preset,
        equivalence_volume_ml=float(equivalence_volume_ml),
        endpoint_volume_ml=None,
        endpoint_equivalence_offset_ml=None,
        transition_start_volume_ml=None,
        transition_end_volume_ml=None,
        confidence="low",
        warning=warning,
    )
