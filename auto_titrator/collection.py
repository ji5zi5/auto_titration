"""Helpers for building schema-compatible collection rows."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .data_schema import SCHEMA_VERSION
from .experiment_config import ExperimentConfig
from .ml_features import derive_ml_features


def build_collection_row(
    *,
    experiment: ExperimentConfig,
    time_s: float,
    frame_id: int,
    injected_volume_ml: float,
    visible_features: Mapping[str, Any] | None = None,
    thermal_features: Mapping[str, Any] | None = None,
    pump_state: Mapping[str, Any] | None = None,
    extra_fields: Mapping[str, Any] | None = None,
    history_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one CSV row from experiment, pump, and camera feature data."""

    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment.experiment_id,
        "titration_type": experiment.titration_type,
        "sample_name": experiment.sample_name,
        "sample_concentration_M": experiment.sample_concentration_m,
        "sample_volume_ml": experiment.sample_volume_ml,
        "sample_valence": experiment.sample_valence,
        "titrant_name": experiment.titrant_name,
        "titrant_concentration_M": experiment.titrant_concentration_m,
        "titrant_valence": experiment.titrant_valence,
        "Ka": experiment.ka if experiment.ka is not None else "",
        "Kb": experiment.kb if experiment.kb is not None else "",
        "indicator": experiment.indicator,
        "chemistry_model": experiment.chemistry_model,
        "chemistry_model_version": experiment.chemistry_model_version,
        "constants_source": experiment.constants_source,
        "constants_source_id": experiment.constants_source_id,
        "constants_query": experiment.constants_query,
        "constants_candidate_count": _blank_if_none(experiment.constants_candidate_count),
        "constants_lookup_ambiguous": _blank_if_none(experiment.constants_lookup_ambiguous),
        "constants_confirmation_status": experiment.constants_confirmation_status,
        "constants_warning": experiment.constants_warning,
        "selected_pka_type": experiment.selected_pka_type,
        "selected_pka_value": _blank_if_none(experiment.selected_pka_value),
        "selected_pka_temperature_c": _blank_if_none(experiment.selected_pka_temperature_c),
        "activity_model": experiment.activity_model,
        "ionic_strength_m": _blank_if_none(experiment.ionic_strength_m),
        "ionic_strength_label": experiment.ionic_strength_label,
        "activity_warning": experiment.activity_warning,
        "theoretical_equivalence_pH": _blank_if_none(experiment.theoretical_equivalence_ph),
        "selected_equivalence_step": experiment.selected_equivalence_step,
        "indicator_transition_low_pH": _blank_if_none(experiment.indicator_transition_low_ph),
        "indicator_transition_high_pH": _blank_if_none(experiment.indicator_transition_high_ph),
        "indicator_endpoint_volume_ml": _blank_if_none(experiment.indicator_endpoint_volume_ml),
        "indicator_endpoint_offset_ml": _blank_if_none(experiment.indicator_endpoint_offset_ml),
        "indicator_endpoint_confidence": experiment.indicator_endpoint_confidence,
        "indicator_endpoint_warning": experiment.indicator_endpoint_warning,
        "standard_solution_uncertainty_note": experiment.standard_solution_uncertainty_note,
        "theoretical_equivalence_volume_ml": experiment.theoretical_equivalence_volume_ml,
        "reference_equivalence_volume_ml": "",
        "observed_color_endpoint_volume_ml": "",
        "predicted_equivalence_volume_ml": "",
        "time_s": time_s,
        "frame_id": frame_id,
        "injected_volume_ml": injected_volume_ml,
    }
    if pump_state:
        row.update(pump_state)
    if visible_features:
        row.update(visible_features)
    if thermal_features:
        row.update(thermal_features)
    if extra_fields:
        row.update(extra_fields)
    row.update(derive_ml_features(list(history_rows or ()), row))
    return row


def _blank_if_none(value: Any) -> Any:
    return "" if value is None else value
