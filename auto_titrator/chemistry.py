"""Chemistry constants and calculations for titration experiments."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_TITRATION_TYPES = (
    "strong_acid_strong_base",
    "weak_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_weak_base",
)

KW_25C = 1.0e-14
DAVIES_A_25C = 0.509


@dataclass(frozen=True)
class StrongElectrolyte:
    """Metadata for species handled by strong-electrolyte model, not pKa lookup."""

    key: str
    display_name: str
    formula: str
    kind: str
    valence: int
    source: str = "strong_electrolyte_model"
    pka: float | None = None
    assumption: str = "near-complete dissociation model; activity effects may shift effective behavior"


@dataclass(frozen=True)
class IonicStrengthClassification:
    ionic_strength_m: float
    label: str
    warning: str


@dataclass(frozen=True)
class UnknownConcentrationResult:
    concentration_m: float
    basis: str
    selected_equivalence_step: int
    titration_type: str
    equivalent_capacity_ratio: float
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TheoreticalTitrationResult:
    titration_type: str
    equivalence_volume_ml: float
    selected_equivalence_step: int
    expected_equivalence_ph: float
    ionic_strength_m: float
    ionic_strength_label: str
    activity_model: str
    activity_warning: str
    basis: str
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TheoreticalPhPoint:
    """One calculated point on a theoretical titration pH curve."""

    titrant_volume_ml: float
    ph: float
    regime: str
    total_volume_ml: float
    acid_equivalents_mol: float
    base_equivalents_mol: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "titrant_volume_ml": self.titrant_volume_ml,
            "ph": self.ph,
            "regime": self.regime,
            "total_volume_ml": self.total_volume_ml,
            "acid_equivalents_mol": self.acid_equivalents_mol,
            "base_equivalents_mol": self.base_equivalents_mol,
        }


STRONG_ELECTROLYTES: dict[str, StrongElectrolyte] = {
    "hcl": StrongElectrolyte("hcl", "Hydrochloric acid", "HCl", "strong_acid", 1),
    "hydrochloric acid": StrongElectrolyte("hcl", "Hydrochloric acid", "HCl", "strong_acid", 1),
    "염산": StrongElectrolyte("hcl", "Hydrochloric acid", "HCl", "strong_acid", 1),
    "naoh": StrongElectrolyte("naoh", "Sodium hydroxide", "NaOH", "strong_base", 1),
    "sodium hydroxide": StrongElectrolyte("naoh", "Sodium hydroxide", "NaOH", "strong_base", 1),
    "수산화나트륨": StrongElectrolyte("naoh", "Sodium hydroxide", "NaOH", "strong_base", 1),
    "koh": StrongElectrolyte("koh", "Potassium hydroxide", "KOH", "strong_base", 1),
    "potassium hydroxide": StrongElectrolyte("koh", "Potassium hydroxide", "KOH", "strong_base", 1),
    "수산화칼륨": StrongElectrolyte("koh", "Potassium hydroxide", "KOH", "strong_base", 1),
}


def get_strong_electrolyte(name: str) -> StrongElectrolyte:
    """Return strong-electrolyte metadata by common name/formula.

    These records are explicit reaction-model metadata; they are not pKa
    placeholders and should not be reported as IUPAC constants.
    """

    key = str(name).casefold().strip()
    try:
        return STRONG_ELECTROLYTES[key]
    except KeyError as exc:
        raise ValueError(f"unknown strong electrolyte: {name}") from exc


def calculate_equivalence_volume_ml(
    *,
    sample_concentration_m: float,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_valence: int,
) -> float:
    """Return theoretical titrant volume in mL from stoichiometric equivalents.

    Formula:
        V_titrant = C_sample * V_sample * sample_valence
                    / (C_titrant * titrant_valence)

    Strong/weak acid-base classification affects pH curve and indicator behavior,
    but not this equivalence-volume stoichiometry.
    """

    _require_positive("sample_concentration_m", sample_concentration_m)
    _require_positive("sample_volume_ml", sample_volume_ml)
    _require_positive("sample_valence", sample_valence)
    _require_positive("titrant_concentration_m", titrant_concentration_m)
    _require_positive("titrant_valence", titrant_valence)

    return (
        float(sample_concentration_m)
        * float(sample_volume_ml)
        * int(sample_valence)
        / (float(titrant_concentration_m) * int(titrant_valence))
    )


def calculate_unknown_sample_concentration_m(
    *,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_volume_ml: float,
    titrant_valence: int,
) -> float:
    """Return unknown sample concentration from measured equivalence volume.

    Rearranged from equivalent balance:
        C_sample * V_sample * sample_valence
        = C_titrant * V_titrant * titrant_valence
    """

    _require_positive("sample_volume_ml", sample_volume_ml)
    _require_positive("sample_valence", sample_valence)
    _require_positive("titrant_concentration_m", titrant_concentration_m)
    _require_positive("titrant_volume_ml", titrant_volume_ml)
    _require_positive("titrant_valence", titrant_valence)

    return (
        float(titrant_concentration_m)
        * float(titrant_volume_ml)
        * int(titrant_valence)
        / (float(sample_volume_ml) * int(sample_valence))
    )


def calculate_unknown_sample_concentration_result(
    *,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_volume_ml: float,
    titrant_valence: int,
    titration_type: str,
    selected_equivalence_step: int = 1,
) -> UnknownConcentrationResult:
    """Return structured unknown-sample concentration result.

    Weak/strong classification does not redefine mole conservation. It is kept in
    the result so UI/report code can explain pH/endpoint reliability separately.
    """

    _require_supported_titration_type(titration_type)
    _require_positive("selected_equivalence_step", selected_equivalence_step)
    concentration = calculate_unknown_sample_concentration_m(
        sample_volume_ml=sample_volume_ml,
        sample_valence=sample_valence,
        titrant_concentration_m=titrant_concentration_m,
        titrant_volume_ml=titrant_volume_ml,
        titrant_valence=titrant_valence,
    )
    warnings = (
        "Weak/strong classification affects pH and endpoint reliability; it does not redefine stoichiometric concentration balance.",
    )
    if titration_type == "weak_acid_weak_base":
        warnings += ("Weak-acid/weak-base titrations can have shallow pH changes; sensor/reference validation is recommended.",)
    return UnknownConcentrationResult(
        concentration_m=round(concentration, 12),
        basis="stoichiometric_equivalent_capacity",
        selected_equivalence_step=int(selected_equivalence_step),
        titration_type=titration_type,
        equivalent_capacity_ratio=float(titrant_valence) / float(sample_valence),
        warnings=warnings,
    )


def calculate_unknown_titrant_concentration_m(
    *,
    sample_concentration_m: float,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_volume_ml: float,
    titrant_valence: int,
) -> float:
    """Return unknown titrant concentration from measured equivalence volume."""

    _require_positive("sample_concentration_m", sample_concentration_m)
    _require_positive("sample_volume_ml", sample_volume_ml)
    _require_positive("sample_valence", sample_valence)
    _require_positive("titrant_volume_ml", titrant_volume_ml)
    _require_positive("titrant_valence", titrant_valence)

    return (
        float(sample_concentration_m)
        * float(sample_volume_ml)
        * int(sample_valence)
        / (float(titrant_volume_ml) * int(titrant_valence))
    )


def calculate_theoretical_titration_result(
    *,
    sample_concentration_m: float,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_valence: int,
    titration_type: str,
    sample_pka: float | None = None,
    titrant_pkb: float | None = None,
    selected_equivalence_step: int = 1,
    activity_model: str = "davies",
) -> TheoreticalTitrationResult:
    """Return structured theoretical titration metadata.

    The pH estimates are deliberately conservative model estimates for UI/report
    explanation. Equivalent volume remains stoichiometric.
    """

    _require_supported_titration_type(titration_type)
    equivalence_volume_ml = calculate_equivalence_volume_ml(
        sample_concentration_m=sample_concentration_m,
        sample_volume_ml=sample_volume_ml,
        sample_valence=sample_valence,
        titrant_concentration_m=titrant_concentration_m,
        titrant_valence=titrant_valence,
    )
    total_volume_l = (float(sample_volume_ml) + equivalence_volume_ml) / 1000.0
    sample_moles = float(sample_concentration_m) * float(sample_volume_ml) / 1000.0
    salt_concentration_m = sample_moles / total_volume_l if total_volume_l > 0 else 0.0
    ionic_strength_m = _estimate_equivalence_ionic_strength(
        titration_type=titration_type,
        salt_concentration_m=salt_concentration_m,
        sample_valence=sample_valence,
        titrant_valence=titrant_valence,
    )
    classification = classify_ionic_strength(ionic_strength_m)
    expected_ph, warnings = _estimate_equivalence_ph(
        titration_type=titration_type,
        salt_concentration_m=salt_concentration_m,
        sample_pka=sample_pka,
        titrant_pkb=titrant_pkb,
    )
    assumptions = (
        "stoichiometric equivalent capacity determines theoretical equivalence volume",
        "pH is a model estimate/reference, not an absolute truth value",
        "Davies activity correction is represented by ionic-strength reliability metadata",
    )
    return TheoreticalTitrationResult(
        titration_type=titration_type,
        equivalence_volume_ml=round(equivalence_volume_ml, 12),
        selected_equivalence_step=int(selected_equivalence_step),
        expected_equivalence_ph=round(expected_ph, 6),
        ionic_strength_m=round(ionic_strength_m, 12),
        ionic_strength_label=classification.label,
        activity_model=activity_model,
        activity_warning=classification.warning,
        basis="stoichiometric_equivalent_capacity_plus_equilibrium_ph_model",
        assumptions=assumptions,
        warnings=tuple(warnings),
    )


def generate_theoretical_ph_curve(
    *,
    sample_concentration_m: float,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_valence: int,
    titration_type: str,
    sample_pka: float | None = None,
    titrant_pkb: float | None = None,
    step_volume_ml: float = 0.1,
    max_titrant_volume_ml: float | None = None,
) -> list[TheoreticalPhPoint]:
    """Return a theoretical pH curve by sweeping titrant volume.

    This is a model curve from concentration/volume/equilibrium constants, not
    measured pH-sensor data. The sample is treated as the acid side and the
    titrant as the base side, matching the project titration-type names.
    """

    _require_supported_titration_type(titration_type)
    _require_positive("sample_concentration_m", sample_concentration_m)
    _require_positive("sample_volume_ml", sample_volume_ml)
    _require_positive("sample_valence", sample_valence)
    _require_positive("titrant_concentration_m", titrant_concentration_m)
    _require_positive("titrant_valence", titrant_valence)
    _require_positive("step_volume_ml", step_volume_ml)
    equivalence_volume_ml = calculate_equivalence_volume_ml(
        sample_concentration_m=sample_concentration_m,
        sample_volume_ml=sample_volume_ml,
        sample_valence=sample_valence,
        titrant_concentration_m=titrant_concentration_m,
        titrant_valence=titrant_valence,
    )
    if max_titrant_volume_ml is None:
        max_titrant_volume_ml = equivalence_volume_ml * 2.0
    _require_positive("max_titrant_volume_ml", max_titrant_volume_ml)

    points: list[TheoreticalPhPoint] = []
    volume = 0.0
    epsilon = max(1e-9, float(step_volume_ml) * 1e-9)
    while volume <= float(max_titrant_volume_ml) + epsilon:
        points.append(
            calculate_theoretical_ph_point(
                sample_concentration_m=sample_concentration_m,
                sample_volume_ml=sample_volume_ml,
                sample_valence=sample_valence,
                titrant_concentration_m=titrant_concentration_m,
                titrant_valence=titrant_valence,
                titration_type=titration_type,
                titrant_volume_ml=volume,
                sample_pka=sample_pka,
                titrant_pkb=titrant_pkb,
            )
        )
        volume += float(step_volume_ml)
    return points


def calculate_theoretical_ph_point(
    *,
    sample_concentration_m: float,
    sample_volume_ml: float,
    sample_valence: int,
    titrant_concentration_m: float,
    titrant_valence: int,
    titration_type: str,
    titrant_volume_ml: float,
    sample_pka: float | None = None,
    titrant_pkb: float | None = None,
) -> TheoreticalPhPoint:
    """Return one theoretical pH curve point at a selected titrant volume."""

    if titrant_volume_ml < 0:
        raise ValueError("titrant_volume_ml must be non-negative")
    acid_eq = float(sample_concentration_m) * float(sample_volume_ml) / 1000.0 * int(sample_valence)
    base_eq = float(titrant_concentration_m) * float(titrant_volume_ml) / 1000.0 * int(titrant_valence)
    total_volume_l = (float(sample_volume_ml) + float(titrant_volume_ml)) / 1000.0
    if total_volume_l <= 0:
        raise ValueError("total volume must be positive")
    equivalence_tolerance = max(acid_eq * 1e-9, 1e-14)

    ph, regime = _estimate_curve_ph(
        titration_type=titration_type,
        acid_eq_mol=acid_eq,
        base_eq_mol=base_eq,
        total_volume_l=total_volume_l,
        sample_pka=sample_pka,
        titrant_pkb=titrant_pkb,
        equivalence_tolerance=equivalence_tolerance,
    )
    return TheoreticalPhPoint(
        titrant_volume_ml=round(float(titrant_volume_ml), 6),
        ph=round(_clamp_ph(ph), 6),
        regime=regime,
        total_volume_ml=round(float(sample_volume_ml) + float(titrant_volume_ml), 6),
        acid_equivalents_mol=round(acid_eq, 12),
        base_equivalents_mol=round(base_eq, 12),
    )


def write_theoretical_ph_curve_csv(curve: list[TheoreticalPhPoint], output_path: str | Path) -> Path:
    """Write a theoretical pH curve to CSV and return the output path."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "titrant_volume_ml",
        "ph",
        "regime",
        "total_volume_ml",
        "acid_equivalents_mol",
        "base_equivalents_mol",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for point in curve:
            writer.writerow(_format_ph_curve_row(point))
    return path


def davies_activity_coefficient(*, charge: int, ionic_strength_m: float, temperature_c: float = 25.0) -> float:
    """Return Davies activity coefficient gamma for an ion.

    The default A value is for water near 25 °C. Temperature is accepted for API
    clarity; this first model intentionally uses the 25 °C constant.
    """

    if ionic_strength_m < 0:
        raise ValueError("ionic_strength_m must be non-negative")
    z = int(charge)
    if z == 0 or ionic_strength_m == 0:
        return 1.0
    sqrt_i = math.sqrt(float(ionic_strength_m))
    term = sqrt_i / (1.0 + sqrt_i) - 0.3 * float(ionic_strength_m)
    log_gamma = -DAVIES_A_25C * (z * z) * term
    return 10.0**log_gamma


def calculate_ionic_strength_m(ions: dict[str, tuple[float, int]] | list[tuple[float, int]]) -> float:
    """Calculate ionic strength I = 1/2 sum(c_i z_i^2)."""

    items = ions.values() if isinstance(ions, dict) else ions
    total = 0.0
    for concentration, charge in items:
        if concentration < 0:
            raise ValueError("ion concentration must be non-negative")
        total += float(concentration) * int(charge) ** 2
    return 0.5 * total


def classify_ionic_strength(ionic_strength_m: float) -> IonicStrengthClassification:
    """Classify Davies-model reliability by ionic strength."""

    if ionic_strength_m < 0:
        raise ValueError("ionic_strength_m must be non-negative")
    value = float(ionic_strength_m)
    if value <= 0.1:
        return IonicStrengthClassification(value, "high_reliability", "Davies activity correction is within the high-confidence project range.")
    if value <= 0.3:
        return IonicStrengthClassification(value, "usable", "Davies activity correction is usable; report as a model estimate/reference.")
    if value <= 0.5:
        return IonicStrengthClassification(value, "caution", "Davies activity correction is near its recommended range limit; interpret cautiously.")
    return IonicStrengthClassification(value, "outside_davies_range", "Davies recommended range exceeded; result is reference-only and dilution is recommended.")


def _estimate_equivalence_ionic_strength(
    *,
    titration_type: str,
    salt_concentration_m: float,
    sample_valence: int,
    titrant_valence: int,
) -> float:
    # For current high-school scope, most examples are monovalent. This estimate
    # keeps multivalent ions visible through z^2 without pretending to be a full
    # speciation engine.
    anion_charge = max(1, int(sample_valence))
    cation_charge = max(1, int(titrant_valence))
    return calculate_ionic_strength_m([(salt_concentration_m, anion_charge), (salt_concentration_m, cation_charge)])


def _estimate_equivalence_ph(
    *,
    titration_type: str,
    salt_concentration_m: float,
    sample_pka: float | None,
    titrant_pkb: float | None,
) -> tuple[float, list[str]]:
    warnings: list[str] = []
    concentration = max(float(salt_concentration_m), 1e-12)
    if titration_type == "strong_acid_strong_base":
        return 7.0, warnings
    if titration_type == "weak_acid_strong_base":
        if sample_pka is None:
            warnings.append("sample_pka missing; using acetic-acid reference pKa only as a placeholder estimate")
        pka = 4.76 if sample_pka is None else float(sample_pka)
        ka = 10.0 ** (-pka)
        kb = KW_25C / ka
        oh = _solve_weak_base_oh(kb=kb, concentration=concentration)
        ph = 14.0 + math.log10(max(oh, 1e-14))
        return _clamp_ph(ph), warnings
    if titration_type == "strong_acid_weak_base":
        if titrant_pkb is None:
            warnings.append("titrant_pkb missing; using ammonia reference pKb only as a placeholder estimate")
        pkb = 4.75 if titrant_pkb is None else float(titrant_pkb)
        kb = 10.0 ** (-pkb)
        ka = KW_25C / kb
        h = _solve_weak_acid_h(ka=ka, concentration=concentration)
        ph = -math.log10(max(h, 1e-14))
        return _clamp_ph(ph), warnings
    if titration_type == "weak_acid_weak_base":
        if sample_pka is None:
            warnings.append("sample_pka missing; using acetic-acid reference pKa only as a placeholder estimate")
        if titrant_pkb is None:
            warnings.append("titrant_pkb missing; using ammonia reference pKb only as a placeholder estimate")
        pka = 4.76 if sample_pka is None else float(sample_pka)
        pkb = 4.75 if titrant_pkb is None else float(titrant_pkb)
        ph = 7.0 + 0.5 * (pkb - pka)
        warnings.append("weak-weak titration may have shallow pH jump; report pH as model estimate/reference")
        return _clamp_ph(ph), warnings
    _require_supported_titration_type(titration_type)
    return 7.0, warnings


def _estimate_curve_ph(
    *,
    titration_type: str,
    acid_eq_mol: float,
    base_eq_mol: float,
    total_volume_l: float,
    sample_pka: float | None,
    titrant_pkb: float | None,
    equivalence_tolerance: float,
) -> tuple[float, str]:
    acid_remaining = acid_eq_mol - base_eq_mol
    base_excess = base_eq_mol - acid_eq_mol
    if titration_type == "strong_acid_strong_base":
        if acid_remaining > equivalence_tolerance:
            h = acid_remaining / total_volume_l
            return -math.log10(max(h, 1e-14)), "excess_strong_acid"
        if base_excess > equivalence_tolerance:
            oh = base_excess / total_volume_l
            return 14.0 + math.log10(max(oh, 1e-14)), "excess_strong_base"
        return 7.0, "equivalence"

    if titration_type == "weak_acid_strong_base":
        pka = 4.76 if sample_pka is None else float(sample_pka)
        ka = 10.0 ** (-pka)
        if base_eq_mol <= equivalence_tolerance:
            formal_acid = acid_eq_mol / total_volume_l
            h = _solve_weak_acid_h(ka=ka, concentration=max(formal_acid, 1e-12))
            return -math.log10(max(h, 1e-14)), "initial_weak_acid"
        if acid_remaining > equivalence_tolerance:
            ph = pka + math.log10(max(base_eq_mol, 1e-14) / max(acid_remaining, 1e-14))
            return ph, "buffer"
        if base_excess > equivalence_tolerance:
            oh = base_excess / total_volume_l
            return 14.0 + math.log10(max(oh, 1e-14)), "excess_strong_base"
        salt_concentration = acid_eq_mol / total_volume_l
        kb = KW_25C / ka
        oh = _solve_weak_base_oh(kb=kb, concentration=max(salt_concentration, 1e-12))
        return 14.0 + math.log10(max(oh, 1e-14)), "equivalence"

    if titration_type == "strong_acid_weak_base":
        pkb = 4.75 if titrant_pkb is None else float(titrant_pkb)
        kb = 10.0 ** (-pkb)
        if acid_remaining > equivalence_tolerance:
            h = acid_remaining / total_volume_l
            return -math.log10(max(h, 1e-14)), "excess_strong_acid"
        conjugate_acid_pka = 14.0 - pkb
        if base_excess > equivalence_tolerance:
            ph = conjugate_acid_pka + math.log10(max(base_excess, 1e-14) / max(acid_eq_mol, 1e-14))
            return ph, "buffer"
        salt_concentration = acid_eq_mol / total_volume_l
        ka = KW_25C / kb
        h = _solve_weak_acid_h(ka=ka, concentration=max(salt_concentration, 1e-12))
        return -math.log10(max(h, 1e-14)), "equivalence"

    if titration_type == "weak_acid_weak_base":
        pka = 4.76 if sample_pka is None else float(sample_pka)
        pkb = 4.75 if titrant_pkb is None else float(titrant_pkb)
        ka = 10.0 ** (-pka)
        if base_eq_mol <= equivalence_tolerance:
            formal_acid = acid_eq_mol / total_volume_l
            h = _solve_weak_acid_h(ka=ka, concentration=max(formal_acid, 1e-12))
            return -math.log10(max(h, 1e-14)), "initial_weak_acid"
        if acid_remaining > equivalence_tolerance:
            ph = pka + math.log10(max(base_eq_mol, 1e-14) / max(acid_remaining, 1e-14))
            return ph, "buffer"
        if base_excess > equivalence_tolerance:
            conjugate_acid_pka = 14.0 - pkb
            ph = conjugate_acid_pka + math.log10(max(base_excess, 1e-14) / max(acid_eq_mol, 1e-14))
            return ph, "buffer"
        return 7.0 + 0.5 * (pkb - pka), "equivalence_reference"

    _require_supported_titration_type(titration_type)
    return 7.0, "unknown"


def _format_ph_curve_row(point: TheoreticalPhPoint) -> dict[str, str]:
    return {
        "titrant_volume_ml": f"{point.titrant_volume_ml:.6f}",
        "ph": f"{point.ph:.6f}",
        "regime": point.regime,
        "total_volume_ml": f"{point.total_volume_ml:.6f}",
        "acid_equivalents_mol": f"{point.acid_equivalents_mol:.12f}",
        "base_equivalents_mol": f"{point.base_equivalents_mol:.12f}",
    }


def _solve_weak_base_oh(*, kb: float, concentration: float) -> float:
    # Kb = x^2 / (C - x). Solve x^2 + Kb*x - Kb*C = 0.
    return (-kb + math.sqrt(kb * kb + 4.0 * kb * concentration)) / 2.0


def _solve_weak_acid_h(*, ka: float, concentration: float) -> float:
    # Ka = x^2 / (C - x). Solve x^2 + Ka*x - Ka*C = 0.
    return (-ka + math.sqrt(ka * ka + 4.0 * ka * concentration)) / 2.0


def _clamp_ph(ph: float) -> float:
    return max(0.0, min(14.0, float(ph)))


def _require_supported_titration_type(titration_type: str) -> None:
    if titration_type not in SUPPORTED_TITRATION_TYPES:
        raise ValueError(f"unsupported titration_type: {titration_type}")


def _require_positive(name: str, value: float | int) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
