---
title: "Code Map chemistry 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:04.446Z
updated: 2026-09-10T11:13:04.446Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map chemistry 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [auto_titrator/chemistry.py](../auto_titrator/chemistry.py)
SHA256: `3dd8874b5bcab8bdf2329d910fa95e143d01fdeb397f4fa5b716fd1ec3d84c83`

Chemistry constants and calculations for titration experiments.

- L22: `StrongElectrolyte` (class)
- L36: `IonicStrengthClassification` (class)
- L43: `UnknownConcentrationResult` (class)
- L53: `TheoreticalTitrationResult` (class)
- L68: `TheoreticalPhPoint` (class)
- L102: `get_strong_electrolyte`
- L116: `calculate_equivalence_volume_ml`
- L148: `calculate_unknown_sample_concentration_m`
- L177: `calculate_unknown_sample_concentration_result`
- L217: `calculate_unknown_titrant_concentration_m`
- L241: `calculate_theoretical_titration_result`
- L304: `generate_theoretical_ph_curve`
- L363: `calculate_theoretical_ph_point`
- L405: `write_theoretical_ph_curve_csv`
- L426: `davies_activity_coefficient`
- L444: `calculate_ionic_strength_m`
- L456: `classify_ionic_strength`
- L471: `_estimate_equivalence_ionic_strength`
- L486: `_estimate_equivalence_ph`
- L529: `_estimate_curve_ph`
- L604: `_format_ph_curve_row`
- L615: `_solve_weak_base_oh`
- L620: `_solve_weak_acid_h`
- L625: `_clamp_ph`
- L629: `_require_supported_titration_type`
- L634: `_require_positive`

## [auto_titrator/chemical_constants.py](../auto_titrator/chemical_constants.py)
SHA256: `d140c94504b5cecbdd357b8abc864aded24fbb1fc024ef76f2249490d1cdb1e7`

Local chemical constant lookup helpers for titration calculations.

The primary data source is the IUPAC Digitized pKa Dataset CSV stored under
``data/chemistry_constants/iupac``.  This module intentionally performs local
CSV lookup only; network-backed fallbacks should be explicit and separately
mocked so data collection never depends on the internet.

- L24: `ParsedPkaValue` (class)
- L33: `PkaCandidate` (class)
- L94: `ConstantsLookupResult` (class)
- L114: `IupacPkaDatabase` (class)
- L163: `lookup_iupac_pka`
- L169: `parse_pka_value`
- L185: `_candidate_from_row`
- L217: `_match_type`
- L243: `_normalize`
- L248: `_match_score`
- L261: `_quality_score`
- L302: `_looks_deuterated_or_non_aqueous_isotope`
- L318: `_sort_key`
- L322: `_parse_temperature`

## [auto_titrator/indicator_models.py](../auto_titrator/indicator_models.py)
SHA256: `4f455887c58e25551388cce26a442442f9c3d9be865b42b040a4d4efe8a7de17`

Indicator transition-range models for endpoint/equivalence comparison.

- L10: `IndicatorPreset` (class)
- L24: `IndicatorEndpointEstimate` (class)
- L60: `get_indicator`
- L68: `estimate_indicator_endpoint`
- L112: `_normalize_curve`
- L126: `_crossing_volume`
- L140: `_low_confidence`

## [auto_titrator/experiment_config.py](../auto_titrator/experiment_config.py)
SHA256: `1c937114d4f40ada7fc8059a94beb514ed41760c6748c099e50669a98d56c1f4`

Experiment metadata for titration data collection.

- L12: `ExperimentConfig` (class)
- L158: `_get`
- L165: `_optional_float`
- L171: `_optional_int`
- L177: `_optional_bool`


