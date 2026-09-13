---
title: "Code Map ml 01"
tags: ["코드", "함수", "파일지도"]
created: 2026-09-10T11:13:05.486Z
updated: 2026-09-10T11:13:05.486Z
sources: []
links: ["code-and-data-atlas.md"]
category: architecture
confidence: medium
schemaVersion: 1
---

# Code Map ml 01

현재 코드의 AST 정적 색인. 함수 존재는 작동 검증과 다르다. 줄 번호·해시는 이 스냅샷 기준.
[[code-and-data-atlas]]

## [auto_titrator/type_conditioned_sensor_live_model.py](../auto_titrator/type_conditioned_sensor_live_model.py)
SHA256: `22b9bbbb71b8a11ef1ac12f928a516f3d07bbd29b563a7ddb1512c0b5af79ce4`

Post-run endpoint prediction with the frozen type-conditioned sensor ranker.

The deployed artifact contains estimators fitted on the completed June
development runs.  Runtime candidate generation reads sensor channels only;
the injected volume is looked up after a sensor frame has been selected.
This model is intended for final CSV analysis, not causal pump control.

- L46: `_sensor_scores`
- L91: `_precompute_window_statistics`
- L112: `_detect_from_scores`
- L136: `generate_union_candidates`
- L202: `_finite_float`
- L210: `resample_sensor_rows_by_volume`
- L298: `load_type_conditioned_sensor_model`
- L318: `sensor_coverage`
- L343: `_prepare_runtime_variants`
- L383: `_transform_design`
- L401: `_candidate_scores`
- L422: `_normalize_scores`
- L435: `_aggregate_boundary`
- L476: `_combined_candidate_scores`
- L503: `_predict_analysis_variant`
- L599: `predict_type_conditioned_sensor_equivalence`

## [auto_titrator/typewise_live_model.py](../auto_titrator/typewise_live_model.py)
SHA256: `1840441b59fe860cd73217301870534ee0a9a30aa1ed652fd2f82f7c78d675f2`

Live typewise classifier prediction for equivalence volume.

The artifact loaded here is trained from completed experiment CSVs, but live
prediction uses only values that can be observed during/after the current run:
current injected volume, visible/thermal sensor features, and experiment
metadata. It must not use theoretical equivalence, progress fraction, final run
length, or known sample concentration as input features.

- L91: `_safe_float`
- L103: `forbidden_hardware_control_features`
- L122: `validate_hardware_control_model`
- L140: `load_typewise_model`
- L162: `feature_dict_from_row`
- L172: `_hardware_control_feature_dict_from_row`
- L201: `_model_entry`
- L220: `_weighted_median`
- L232: `aggregate_classifier_scores`
- L302: `_positive_scores`
- L312: `score_typewise_rows`
- L354: `score_typewise_rows_for_hardware_control`
- L369: `predict_typewise_equivalence`

## [tools/search_advanced_type_conditioned_sensor_rankers.py](../tools/search_advanced_type_conditioned_sensor_rankers.py)
SHA256: `b7fe5450cab2654aac82b6cf6b9dd0c11a2fe51486211577d8b6af9dd993ea3a`

Deterministic follow-up rankers on the frozen sensor candidate union.

Only candidate sensor features and known titration_type enter rankers. Injected
volume and theoretical equivalence volume are read only to construct training
labels and to map final selected boundaries for the audit. Every score is
outer leave-one-run-out: the held-out run is excluded from fit and scaling.

- L65: `Spec` (class)
- L76: `source_sha256`
- L80: `union_signature`
- L88: `candidate_error`
- L94: `raw_design`
- L105: `training_arrays`
- L116: `rank_quality`
- L121: `fit_regressor_scores`
- L158: `fit_discriminant_scores`
- L197: `fit_prototype_scores`
- L233: `fit_pairwise_regression_scores`
- L263: `specs`
- L290: `score_one`
- L305: `normalize`
- L316: `aggregate`
- L330: `evaluate`
- L352: `write_csv`
- L361: `main`

## [tools/compare_boosting_candidate_rankers.py](../tools/compare_boosting_candidate_rankers.py)
SHA256: `96911dc71b9d70d389e95057ba156c1ce8793d3dae80fc5387d925be19e0aeac`

Run-level LORO comparison of XGBoost, LightGBM, and CatBoost rankers.

- L49: `transformed_features`
- L58: `relevance_labels`
- L78: `continuous_quality_labels`
- L94: `training_arrays`
- L119: `make_model`
- L221: `fit_model`
- L238: `aggregate_prediction`
- L272: `summarize`
- L289: `feature_importance`
- L308: `evaluate`
- L580: `main`


