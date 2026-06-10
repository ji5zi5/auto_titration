"""Experiment metadata for titration data collection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .chemistry import SUPPORTED_TITRATION_TYPES, calculate_equivalence_volume_ml


@dataclass(frozen=True)
class ExperimentConfig:
    """Chemical setup metadata stored with every collected row."""

    experiment_id: str
    titration_type: str
    sample_name: str
    sample_concentration_m: float
    sample_volume_ml: float
    sample_valence: int
    titrant_name: str
    titrant_concentration_m: float
    titrant_valence: int
    ka: float | None = None
    kb: float | None = None
    indicator: str = ""
    chemistry_model: str = "scientific_equilibrium_davies"
    chemistry_model_version: str = "1.0"
    constants_source: str = ""
    constants_source_id: str = ""
    constants_query: str = ""
    constants_candidate_count: int | None = None
    constants_lookup_ambiguous: bool | None = None
    constants_confirmation_status: str = ""
    constants_warning: str = ""
    selected_pka_type: str = ""
    selected_pka_value: float | None = None
    selected_pka_temperature_c: float | None = None
    activity_model: str = "davies"
    ionic_strength_m: float | None = None
    ionic_strength_label: str = ""
    activity_warning: str = ""
    theoretical_equivalence_ph: float | None = None
    selected_equivalence_step: int = 1
    indicator_transition_low_ph: float | None = None
    indicator_transition_high_ph: float | None = None
    indicator_endpoint_volume_ml: float | None = None
    indicator_endpoint_offset_ml: float | None = None
    indicator_endpoint_confidence: str = ""
    indicator_endpoint_warning: str = ""
    standard_solution_uncertainty_note: str = (
        "standard concentration is user-entered; no standardization experiment is performed in this app"
    )

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "ExperimentConfig":
        """Create config from YAML/dict values.

        Accepts concentration keys using either `_M` (CSV/config-friendly unit
        suffix) or `_m` (Python attribute style).
        """

        return cls(
            experiment_id=str(values["experiment_id"]),
            titration_type=str(values["titration_type"]),
            sample_name=str(values["sample_name"]),
            sample_concentration_m=float(_get(values, "sample_concentration_m", "sample_concentration_M")),
            sample_volume_ml=float(values["sample_volume_ml"]),
            sample_valence=int(values.get("sample_valence", 1)),
            titrant_name=str(values["titrant_name"]),
            titrant_concentration_m=float(_get(values, "titrant_concentration_m", "titrant_concentration_M")),
            titrant_valence=int(values.get("titrant_valence", 1)),
            ka=_optional_float(values.get("ka", values.get("Ka"))),
            kb=_optional_float(values.get("kb", values.get("Kb"))),
            indicator=str(values.get("indicator", "")),
            chemistry_model=str(values.get("chemistry_model", "scientific_equilibrium_davies")),
            chemistry_model_version=str(values.get("chemistry_model_version", "1.0")),
            constants_source=str(values.get("constants_source", "")),
            constants_source_id=str(values.get("constants_source_id", "")),
            constants_query=str(values.get("constants_query", "")),
            constants_candidate_count=_optional_int(values.get("constants_candidate_count")),
            constants_lookup_ambiguous=_optional_bool(values.get("constants_lookup_ambiguous")),
            constants_confirmation_status=str(values.get("constants_confirmation_status", "")),
            constants_warning=str(values.get("constants_warning", "")),
            selected_pka_type=str(values.get("selected_pka_type", "")),
            selected_pka_value=_optional_float(values.get("selected_pka_value")),
            selected_pka_temperature_c=_optional_float(
                values.get("selected_pka_temperature_c", values.get("selected_pka_temperature_C"))
            ),
            activity_model=str(values.get("activity_model", "davies")),
            ionic_strength_m=_optional_float(values.get("ionic_strength_m", values.get("ionic_strength_M"))),
            ionic_strength_label=str(values.get("ionic_strength_label", "")),
            activity_warning=str(values.get("activity_warning", "")),
            theoretical_equivalence_ph=_optional_float(
                values.get("theoretical_equivalence_ph", values.get("theoretical_equivalence_pH"))
            ),
            selected_equivalence_step=int(values.get("selected_equivalence_step", 1)),
            indicator_transition_low_ph=_optional_float(
                values.get("indicator_transition_low_ph", values.get("indicator_transition_low_pH"))
            ),
            indicator_transition_high_ph=_optional_float(
                values.get("indicator_transition_high_ph", values.get("indicator_transition_high_pH"))
            ),
            indicator_endpoint_volume_ml=_optional_float(values.get("indicator_endpoint_volume_ml")),
            indicator_endpoint_offset_ml=_optional_float(values.get("indicator_endpoint_offset_ml")),
            indicator_endpoint_confidence=str(values.get("indicator_endpoint_confidence", "")),
            indicator_endpoint_warning=str(values.get("indicator_endpoint_warning", "")),
            standard_solution_uncertainty_note=str(
                values.get(
                    "standard_solution_uncertainty_note",
                    "standard concentration is user-entered; no standardization experiment is performed in this app",
                )
            ),
        )

    def __post_init__(self) -> None:
        if self.titration_type not in SUPPORTED_TITRATION_TYPES:
            raise ValueError(f"unsupported titration_type: {self.titration_type}")
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if not self.sample_name:
            raise ValueError("sample_name is required")
        if not self.titrant_name:
            raise ValueError("titrant_name is required")
        calculate_equivalence_volume_ml(
            sample_concentration_m=self.sample_concentration_m,
            sample_volume_ml=self.sample_volume_ml,
            sample_valence=self.sample_valence,
            titrant_concentration_m=self.titrant_concentration_m,
            titrant_valence=self.titrant_valence,
        )
        if self.ka is not None and self.ka <= 0:
            raise ValueError("ka must be positive when provided")
        if self.kb is not None and self.kb <= 0:
            raise ValueError("kb must be positive when provided")
        if self.selected_equivalence_step <= 0:
            raise ValueError("selected_equivalence_step must be positive")
        if self.ionic_strength_m is not None and self.ionic_strength_m < 0:
            raise ValueError("ionic_strength_m must be non-negative when provided")
        if self.indicator_transition_low_ph is not None and not (0 <= self.indicator_transition_low_ph <= 14):
            raise ValueError("indicator_transition_low_ph must be between 0 and 14 when provided")
        if self.indicator_transition_high_ph is not None and not (0 <= self.indicator_transition_high_ph <= 14):
            raise ValueError("indicator_transition_high_ph must be between 0 and 14 when provided")
        if self.theoretical_equivalence_ph is not None and not (0 <= self.theoretical_equivalence_ph <= 14):
            raise ValueError("theoretical_equivalence_ph must be between 0 and 14 when provided")

    @property
    def theoretical_equivalence_volume_ml(self) -> float:
        return calculate_equivalence_volume_ml(
            sample_concentration_m=self.sample_concentration_m,
            sample_volume_ml=self.sample_volume_ml,
            sample_valence=self.sample_valence,
            titrant_concentration_m=self.titrant_concentration_m,
            titrant_valence=self.titrant_valence,
        )


def _get(values: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in values:
            return values[key]
    raise KeyError(keys[0])


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")
