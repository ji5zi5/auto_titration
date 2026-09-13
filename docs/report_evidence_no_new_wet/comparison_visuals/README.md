# Comparison visual suite

## Reproduction

Run `python3 tools/make_comparison_visuals.py` from the repository root. The generator uses only the Python standard library, matplotlib, CSV, and JSON; it does not use pandas. All PNG files are exported at 300 dpi with a white background and a width of at least 1800 pixels. Every figure has a matching CSV in `source_data/`.

## Provenance and caveats

- **00** — four June 0.15 M CSVs under `머신러닝용 파일모음/`, selected reproducibly by `sample_concentration_M=0.15` and one run per titration type. The plotted channels are `visible_H_mean` and calibrated `thermal_roi_avg` (with a raw ROI median fallback if calibrated ROI temperature is unavailable). The dotted vertical line marks the recorded theoretical 30 mL equivalence volume.
- **01** — `data/ml/curve_equivalence_current/model_algorithm_comparison.csv`, `scope=overall`. This is explicitly the **initial common pipeline**. Its Ridge/KNN/RF/ET scores must not be presented as head-to-head scores from the current final pipeline.
- **02–03, 15** — `data/ml/type_conditioned_sensor_sequence_search/summary.json`. Current final evaluator configuration and seed-42 stratified metrics. The three configured seeds produce identical predictions; seed 42 is used once to avoid triplication. The scope is same-12-run development/configuration selection, not independent external validation.
- **04–11, 14, 16** — current final condition values from `docs/report_evidence_no_new_wet/figures/source_data/01_02_condition_predictions.csv`; current manual values from `data/report/manual_titration_results.csv`; older non-ML and old-pipeline ML values from `data/analysis/non_ml_baseline_comparison/per_run_predictions.csv`. The labels preserve these different generations. Typewise, tolerance, and volume-group summaries are recomputed from the 12 condition rows.
- **06–08** — the three old modality ML series correspond to the same values published in `data/ml/report_modality_sensor_features_only/overall_comparison.csv`; values are recomputed from per-run data so tolerance and error metrics share one denominator. Current manual MAPE is exactly 2.00%; current final MAPE is 0.295% after rounding.
- **12–13** — `data/analysis/july_unknown_repeatability/july_unknown_repeatability_summary.json`. These are three participant-designated repeats of one unknown solution. The actual concentration was not independently standardized, so the figures support repeatability only, not accuracy.
- **03** — the eight explored advanced families are the search families used by the type-conditioned advanced ranker search; the four selected evaluators and their type routing are taken from the current summary. The diagram is deliberately nonnumeric.
- **16** — each 20/30/40 mL group contains one condition from each of four titration types (n=4). It is descriptive and small-sample; it is not a concentration generalization test.

## Placement recommendation

**Report body:** 00 (representative sensor curves; replacement for the legacy-path Fig. 8 asset), 02 (final evaluator by type), 06 (overall MAPE), 08 (tolerance attainment), 09 (manual vs final), 12 (frozen-model repeatability), and 15 (final typewise MAE/RMSE).

**Appendix / methods:** 01 (historical initial pipeline), 03 (search funnel), 04–05 (dense heatmaps), 07 (paired absolute metrics), 10–11 and 14 (condition diagnostics), 13 (old-vs-frozen repeatability CV), and 16 (small-n volume-group diagnostic).

Do not place 01 beside 02 in a way that implies a single shared pipeline. Do not interpret 12–13 as unknown-solution accuracy.
