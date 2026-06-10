# Compact Plus Candidate Reliability Design

## Problem

Current `current_fusion` keeps the feature set compact, but weak-acid/weak-base types still show about 3 mL MAE. Candidate inspection shows the candidate pool often contains a near-equivalence candidate, but the ranker/correction model sometimes chooses or corrects the wrong candidate.

## Goal

Improve run-level equivalence prediction without adding broad noisy RGB/thermal feature dumps. Add a small, interpretable `compact_plus` feature set focused on candidate reliability: whether color, thermal, and fusion evidence agree around the same volume and whether the signal is locally sharp/stable.

## Design

Add theory-free candidate reliability features to candidate rows:

- `nearest_color_candidate_distance_ml`
- `nearest_thermal_candidate_distance_ml`
- `nearest_fusion_candidate_distance_ml`
- `color_thermal_agreement_ml`
- `source_agreement_count_0p5ml`
- `source_agreement_count_1p0ml`
- `candidate_score_rank`
- `candidate_score_gap_to_best`
- `candidate_score_gap_to_next`
- `candidate_local_density_0p5ml`
- `candidate_local_density_1p0ml`
- `visible_thermal_slope_agreement`
- `visible_thermal_delta_agreement`

Add feature set:

- `compact_plus`: `current_fusion` plus the new reliability features.

Do not add theoretical equivalence, pKa, indicator endpoint, label, target, or post-hoc actual error as inputs.

## Evaluation

Keep existing type-wise leave-one-concentration-out validation. Compare:

- `current_fusion`
- `compact_plus`
- `compact_plus_no_progress` (sensor-only ablation that intentionally removes fixed-ratio candidates and otherwise valid progress/volume inputs)
- `fusion_expanded`
- `fusion_no_progress`

Success criterion is not guaranteed improvement on all types; success means the code reports whether `compact_plus` improves, worsens, or ties against `current_fusion` honestly.

## Reporting

Update output artifacts and Korean report to include `compact_plus` and `compact_plus_no_progress` in primary comparison. If `compact_plus` improves, report the improvement as exploratory; if `compact_plus_no_progress` performs worse, explicitly state that volume/progress inputs are legitimate collected signals for the final model, while the sensor-only ablation is not enough for a pure sensor-only generalization claim.
