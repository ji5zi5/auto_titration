import csv
import json
import math
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

from auto_titrator import ml_curve_equivalence as ce
from auto_titrator.ml_typewise_eval import CsvRun


TYPES = [
    "strong_acid_strong_base",
    "weak_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_weak_base",
]


def synthetic_rows(eq_ml: float, *, row_count: int = 81) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    max_volume = eq_ml + 6.0
    for index in range(row_count):
        volume = max_volume * index / (row_count - 1)
        time_s = volume
        # A smooth color transition centered on the equivalence point.
        transition = 1.0 / (1.0 + math.exp(-(volume - eq_ml) * 3.0))
        # A thermal bump/change event centered on the same volume.
        bump = math.exp(-((volume - eq_ml) ** 2) / 1.4)
        heat_spread = 0.2 + 1.8 * bump
        rows.append(
            {
                "time_s": round(time_s, 4),
                "injected_volume_ml": round(volume, 4),
                "visible_R_mean": round(105 + 42 * transition, 6),
                "visible_G_mean": round(92 - 12 * transition, 6),
                "visible_B_mean": round(83 + 7 * transition, 6),
                "visible_H_mean": round(28 + 76 * transition, 6),
                "visible_S_mean": round(0.12 + 0.46 * transition, 6),
                "visible_V_mean": round(0.36 + 0.18 * transition, 6),
                "visible_H_delta": round(76 * transition, 6),
                "visible_S_delta": round(0.46 * transition, 6),
                "visible_V_delta": round(0.18 * transition, 6),
                "visible_color_delta": round(60 * transition, 6),
                "visible_HSV_delta": round(70 * transition, 6),
                "thermal_roi_avg": round(23.0 + 2.8 * bump + 0.02 * volume, 6),
                "thermal_roi_max": round(24.0 + 4.1 * bump + 0.02 * volume, 6),
                "thermal_roi_min": round(22.1 + 1.2 * bump + 0.02 * volume, 6),
                "thermal_roi_std": round(0.12 + 0.7 * bump, 6),
                "thermal_roi_range": round(1.9 + 2.9 * bump, 6),
                "thermal_roi_iqr": round(0.5 + 1.6 * bump, 6),
                "thermal_roi_p05": round(22.2 + 1.1 * bump + 0.02 * volume, 6),
                "thermal_roi_p25": round(22.8 + 1.9 * bump + 0.02 * volume, 6),
                "thermal_roi_p50": round(23.0 + 2.5 * bump + 0.02 * volume, 6),
                "thermal_roi_p75": round(23.3 + 2.9 * bump + 0.02 * volume, 6),
                "thermal_roi_p95": round(23.5 + 3.2 * bump + 0.02 * volume, 6),
                "thermal_roi_hot_fraction": round(min(1.0, 0.08 + 0.5 * bump), 6),
                "thermal_roi_cold_fraction": round(max(0.0, 0.22 - 0.12 * bump), 6),
                "thermal_roi_min_x": round(80 - 8 * bump, 6),
                "thermal_roi_min_y": round(70 - 5 * bump, 6),
                "thermal_roi_max_x": round(110 + 9 * bump, 6),
                "thermal_roi_max_y": round(90 + 6 * bump, 6),
                "thermal_roi_width": 160,
                "thermal_roi_height": 120,
                "thermal_raw_roi_p50": round(4800 + 80 * bump + volume, 6),
                "thermal_raw_roi_range": round(140 + 90 * bump, 6),
                "thermal_raw_roi_iqr": round(70 + 55 * bump, 6),
                "thermal_raw_roi_p05": round(4720 + 30 * bump + volume, 6),
                "thermal_raw_roi_p25": round(4760 + 55 * bump + volume, 6),
                "thermal_raw_roi_p75": round(4840 + 88 * bump + volume, 6),
                "thermal_raw_roi_p95": round(4850 + 95 * bump + volume, 6),
                "thermal_raw_roi_hot_fraction": round(min(1.0, 0.09 + 0.48 * bump), 6),
                "thermal_raw_roi_cold_fraction": round(max(0.0, 0.2 - 0.11 * bump), 6),
                "thermal_raw_roi_min_x": round(76 - 6 * bump, 6),
                "thermal_raw_roi_min_y": round(72 - 4 * bump, 6),
                "thermal_raw_roi_max_x": round(113 + 7 * bump, 6),
                "thermal_raw_roi_max_y": round(94 + 5 * bump, 6),
                "thermal_raw_min": round(4600 + 20 * bump + volume, 6),
                "thermal_raw_max": round(5000 + 120 * bump + volume, 6),
                "thermal_raw_mean": round(4800 + 75 * bump + volume, 6),
                "thermal_raw_std": round(95 + 35 * heat_spread, 6),
                "thermal_raw_range": round(400 + 100 * bump, 6),
                "thermal_raw_iqr": round(160 + 70 * bump, 6),
                "thermal_raw_p05": round(4650 + 26 * bump + volume, 6),
                "thermal_raw_p25": round(4740 + 52 * bump + volume, 6),
                "thermal_raw_p50": round(4800 + 75 * bump + volume, 6),
                "thermal_raw_p75": round(4860 + 93 * bump + volume, 6),
                "thermal_raw_p95": round(4940 + 112 * bump + volume, 6),
                "abs_sync_offset_ms": 8.0,
                "training_quality_score": 0.95,
                "valid_for_training": 1.0,
                "pump_run_rate_ml_per_s": 1.0,
            }
        )
    return rows


def make_run(titration_type: str = "strong_acid_strong_base", concentration: float = 0.1) -> CsvRun:
    eq = concentration * 100.0
    rows = synthetic_rows(eq)
    for row in rows:
        row.update(
            {
                "titration_type": titration_type,
                "sample_concentration_M": concentration,
                "sample_volume_ml": 20.0,
                "sample_name": "synthetic",
                "titrant_name": "NaOH",
                "titrant_concentration_M": 0.1,
                "indicator": "phenolphthalein",
                "theoretical_equivalence_volume_ml": eq,
                # These columns are intentionally leaky and must never be model features.
                "delta_ml": round(float(row["injected_volume_ml"]) - eq, 6),
                "zone_label": "leaky",
                "status_label": "leaky",
                "distance_to_equivalence_ml": round(float(row["injected_volume_ml"]) - eq, 6),
                "theoretical_equivalence_time_s": eq,
                "theoretical_equivalence_pH": 7.0,
                "estimated_equivalence_volume_ml": eq,
                "actual_equivalence_volume_ml": eq,
                "indicator_endpoint_offset_ml": 0.0,
                "indicator_endpoint_volume_ml": eq,
                "selected_pka_value": 4.76,
            }
        )
    return CsvRun(
        path=Path(f"{titration_type}-{concentration:.2f}.csv"),
        titration_type=titration_type,
        concentration_m=concentration,
        theoretical_equivalence_volume_ml=eq,
        rows=rows,
    )


def write_curve_run(folder: Path, titration_type: str, concentration: float) -> Path:
    run = make_run(titration_type, concentration)
    path = folder / run.path.name
    fieldnames = sorted({key for row in run.rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(run.rows)
    return path


class CurveEquivalenceMlTests(unittest.TestCase):
    def test_curve_candidates_find_color_thermal_and_fusion_events_near_equivalence(self):
        run = make_run(concentration=0.1)

        curve = ce.build_run_curve(run, smoothing_window=5)
        candidates = ce.extract_candidates(curve, max_candidates_per_source=3)

        self.assertGreater(len(curve.volume_ml), 30)
        self.assertIn("visible_color_delta_smooth", curve.series)
        self.assertIn("thermal_roi_avg_slope", curve.series)
        sources = {candidate.source for candidate in candidates}
        self.assertIn("color", sources)
        self.assertIn("thermal", sources)
        self.assertIn("fusion", sources)
        self.assertLess(
            min(abs(candidate.volume_ml - run.theoretical_equivalence_volume_ml) for candidate in candidates),
            0.45,
        )
        self.assertTrue(all(candidate.volume_ml >= 0 for candidate in candidates))

    def test_candidate_features_use_theory_only_as_targets_not_inputs(self):
        run = make_run(concentration=0.15)
        curve = ce.build_run_curve(run)
        candidates = ce.extract_candidates(curve)

        candidate_rows = ce.build_candidate_rows(run, curve, candidates, good_window_ml=0.5)
        feature_columns = ce.select_candidate_feature_columns(candidate_rows[0].keys(), feature_set="fusion")

        self.assertTrue(candidate_rows)
        self.assertIn("candidate_error_ml", candidate_rows[0])
        self.assertIn("candidate_abs_error_ml", candidate_rows[0])
        self.assertIn("is_good_candidate", candidate_rows[0])
        self.assertIn("visible_pre_post_delta", feature_columns)
        self.assertIn("thermal_pre_post_delta", feature_columns)
        self.assertIn("source_is_fusion", feature_columns)
        self.assertNotIn("theoretical_equivalence_volume_ml", feature_columns)
        self.assertNotIn("candidate_error_ml", feature_columns)
        self.assertNotIn("candidate_abs_error_ml", feature_columns)
        self.assertNotIn("is_good_candidate", feature_columns)
        self.assertNotIn("delta_ml", feature_columns)
        self.assertTrue(ce.is_forbidden_candidate_feature("selected_pka_value"))
        self.assertTrue(ce.is_forbidden_candidate_feature("pka_value"))
        self.assertTrue(ce.is_forbidden_candidate_feature("acid_pka"))
        self.assertTrue(ce.is_forbidden_candidate_feature("solution_pKa"))
        self.assertTrue(ce.is_forbidden_candidate_feature("indicator_endpoint_volume_ml"))
        self.assertTrue(ce.is_forbidden_candidate_feature("theoretical_equivalence_time_s"))
        self.assertTrue(ce.is_forbidden_candidate_feature("candidate_offset_from_theory_ml"))
        ce.assert_no_forbidden_candidate_features(feature_columns)
        with self.assertRaises(ValueError):
            ce.assert_no_forbidden_candidate_features(["visible_pre_post_delta", "candidate_abs_error_ml"])

    def test_expanded_candidate_features_include_thermal_distribution_color_channels_and_coordinates(self):
        run = make_run(concentration=0.12)
        curve = ce.build_run_curve(run)
        candidates = ce.extract_candidates(curve)

        candidate_rows = ce.build_candidate_rows(run, curve, candidates)
        row = candidate_rows[0]
        fusion_features = ce.select_candidate_feature_columns(row.keys(), feature_set="fusion_expanded")
        thermal_features = ce.select_candidate_feature_columns(row.keys(), feature_set="thermal_expanded")
        color_features = ce.select_candidate_feature_columns(row.keys(), feature_set="color_expanded")
        no_progress_features = ce.select_candidate_feature_columns(row.keys(), feature_set="fusion_no_progress")

        self.assertIn("thermal_roi_range_pre_post_delta", row)
        self.assertIn("thermal_roi_iqr_local_std", row)
        self.assertIn("thermal_raw_mean_curvature", row)
        self.assertIn("thermal_raw_roi_p95_plateau_delta", row)
        self.assertIn("thermal_roi_max_x_norm_peak_slope", row)
        self.assertIn("visible_R_mean_pre_post_delta", row)
        self.assertIn("visible_H_mean_curvature", row)
        self.assertIn("visible_S_delta_peak_slope", row)

        self.assertIn("thermal_roi_range_pre_post_delta", thermal_features)
        self.assertIn("thermal_raw_roi_p95_plateau_delta", fusion_features)
        self.assertIn("visible_R_mean_pre_post_delta", color_features)
        self.assertIn("visible_H_mean_curvature", fusion_features)
        self.assertNotIn("candidate_fraction_of_run", no_progress_features)
        self.assertNotIn("candidate_volume_ml", no_progress_features)
        self.assertNotIn("run_volume_max_ml", no_progress_features)
        self.assertNotIn("run_duration_s", no_progress_features)
        no_progress_rows = ce._filter_candidate_rows_for_feature_set(candidate_rows, "fusion_no_progress")
        self.assertLess(len(no_progress_rows), len(candidate_rows))
        self.assertTrue(
            all(
                not (row.get("candidate_source") == "fusion" and float(row.get("candidate_score", 0.0)) > 1.0)
                for row in no_progress_rows
            )
        )

    def test_missing_optional_expanded_columns_do_not_crash(self):
        run = make_run(concentration=0.11)
        stripped_rows = [
            {
                key: value
                for key, value in row.items()
                if key
                in {
                    "time_s",
                    "injected_volume_ml",
                    "visible_color_delta",
                    "visible_HSV_delta",
                    "thermal_roi_avg",
                    "thermal_roi_p95",
                    "thermal_raw_roi_p50",
                    "titration_type",
                    "sample_concentration_M",
                    "theoretical_equivalence_volume_ml",
                }
            }
            for row in run.rows
        ]
        minimal = CsvRun(
            path=Path("minimal.csv"),
            titration_type=run.titration_type,
            concentration_m=run.concentration_m,
            theoretical_equivalence_volume_ml=run.theoretical_equivalence_volume_ml,
            rows=stripped_rows,
        )

        curve = ce.build_run_curve(minimal)
        candidates = ce.extract_candidates(curve)
        rows = ce.build_candidate_rows(minimal, curve, candidates)
        features = ce.select_candidate_feature_columns(rows[0].keys(), feature_set="fusion_expanded")

        self.assertTrue(rows)
        self.assertIn("thermal_roi_avg_pre_post_delta", features)
        self.assertIn("visible_color_delta_pre_post_delta", features)

    def test_compact_plus_adds_bounded_candidate_reliability_features(self):
        run = make_run(concentration=0.12)
        curve = ce.build_run_curve(run)
        candidates = ce.extract_candidates(curve)

        candidate_rows = ce.build_candidate_rows(run, curve, candidates)
        row = candidate_rows[0]
        compact_plus_features = ce.select_candidate_feature_columns(row.keys(), feature_set="compact_plus")

        self.assertIn("compact_plus", ce.FEATURE_SETS)
        for expected in (
            "nearest_color_candidate_distance_ml",
            "nearest_thermal_candidate_distance_ml",
            "nearest_fusion_candidate_distance_ml",
            "color_thermal_agreement_ml",
            "source_agreement_count_0p5ml",
            "source_agreement_count_1p0ml",
            "candidate_score_rank",
            "candidate_score_gap_to_best",
            "candidate_score_gap_to_next",
            "candidate_local_density_0p5ml",
            "candidate_local_density_1p0ml",
            "visible_thermal_slope_agreement",
            "visible_thermal_delta_agreement",
        ):
            self.assertIn(expected, row)
            self.assertIn(expected, compact_plus_features)

        self.assertIn("visible_pre_post_delta", compact_plus_features)
        self.assertIn("thermal_peak_slope", compact_plus_features)
        self.assertNotIn("thermal_roi_iqr_local_std", compact_plus_features)
        self.assertNotIn("visible_R_mean_pre_post_delta", compact_plus_features)
        ce.assert_no_forbidden_candidate_features(compact_plus_features)

    def test_compact_plus_no_progress_removes_protocol_proxies_and_uses_sensor_reliability(self):
        run = make_run(concentration=0.12)
        curve = ce.build_run_curve(run)
        candidates = ce.extract_candidates(curve)

        candidate_rows = ce.build_candidate_rows(run, curve, candidates)
        row = candidate_rows[0]
        features = ce.select_candidate_feature_columns(row.keys(), feature_set="compact_plus_no_progress")
        filtered = ce._filter_candidate_rows_for_feature_set(candidate_rows, "compact_plus_no_progress")

        self.assertIn("compact_plus_no_progress", ce.FEATURE_SETS)
        self.assertTrue(filtered)
        self.assertTrue(all(not ce._is_protocol_fraction_candidate_row(row) for row in filtered))
        for blocked in ce.PROTOCOL_PROXY_COLUMNS:
            self.assertNotIn(blocked, features)
        for expected in (
            "sensor_nearest_color_candidate_distance_ml",
            "sensor_nearest_thermal_candidate_distance_ml",
            "sensor_nearest_fusion_candidate_distance_ml",
            "sensor_color_thermal_agreement_ml",
            "sensor_source_agreement_count_0p5ml",
            "sensor_source_agreement_count_1p0ml",
            "sensor_candidate_local_density_0p5ml",
            "sensor_candidate_local_density_1p0ml",
        ):
            self.assertIn(expected, row)
            self.assertIn(expected, features)
        self.assertIn("visible_pre_post_delta", features)
        self.assertIn("thermal_peak_slope", features)
        ce.assert_no_forbidden_candidate_features(features)

    def test_source_specific_candidate_filter_does_not_substitute_unrelated_modality(self):
        thermal_only_rows = [
            {
                "run_path": "train.csv",
                "candidate_source": "thermal",
                "candidate_score": 0.9,
                "candidate_volume_ml": 8.0,
                "actual_equivalence_volume_ml": 9.0,
            }
        ]
        self.assertEqual(ce._filter_candidate_rows_for_feature_set(thermal_only_rows, "color_expanded"), [])

        fold = ce.TypewiseRunFold(
            titration_type="strong_acid_strong_base",
            held_out_concentration_m=0.1,
            train_runs=[make_run(concentration=0.1)],
            test_runs=[make_run(concentration=0.2)],
        )
        with mock.patch.object(ce, "_candidate_rows_for_runs", return_value=thermal_only_rows):
            result = ce.predict_fold(fold, feature_set="color_expanded")

        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["predictions"], [])
        self.assertEqual(result["model"]["model"], "unevaluable_no_candidate_rows")
        self.assertIn("no fallback", result["model"]["warning"])

    def test_typewise_run_folds_and_run_level_metrics_are_experiment_level(self):
        runs = [make_run(titration_type, concentration) for titration_type in TYPES for concentration in (0.1, 0.15, 0.2)]

        folds = ce.build_typewise_run_folds(runs)
        metrics = ce.run_level_metrics(
            [
                {"predicted_equivalence_volume_ml": 9.9, "actual_equivalence_volume_ml": 10.0},
                {"predicted_equivalence_volume_ml": 15.3, "actual_equivalence_volume_ml": 15.0},
                {"predicted_equivalence_volume_ml": 20.8, "actual_equivalence_volume_ml": 20.0},
            ]
        )

        self.assertEqual(len(folds), 12)
        for fold in folds:
            self.assertEqual({run.titration_type for run in fold.train_runs}, {fold.titration_type})
            self.assertEqual({run.titration_type for run in fold.test_runs}, {fold.titration_type})
            self.assertNotIn(fold.held_out_concentration_m, {run.concentration_m for run in fold.train_runs})
        self.assertAlmostEqual(metrics["mae_ml"], 0.4, places=6)
        self.assertAlmostEqual(metrics["median_abs_error_ml"], 0.3, places=6)
        self.assertAlmostEqual(metrics["mae_percent_of_equivalence"], 2.333333, places=6)
        self.assertAlmostEqual(metrics["concentration_mae_percent"], 2.333333, places=6)
        self.assertAlmostEqual(metrics["within_1pct_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(metrics["within_2pct_rate"], 2 / 3, places=6)
        self.assertAlmostEqual(metrics["within_5pct_rate"], 1.0, places=6)
        self.assertAlmostEqual(metrics["within_0.2ml_rate"], 1 / 3, places=6)
        self.assertAlmostEqual(metrics["within_0.5ml_rate"], 2 / 3, places=6)
        self.assertEqual(metrics["prediction_unit"], "one_prediction_per_run")

    def test_end_to_end_curve_equivalence_evaluation_writes_run_level_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "runs"
            output_dir = root / "curve_ml"
            input_dir.mkdir()
            for titration_type in TYPES:
                for concentration in (0.1, 0.15, 0.2):
                    write_curve_run(input_dir, titration_type, concentration)

            summary = ce.evaluate_folder(input_dir, output_dir=output_dir, fps=25.0, quick=True)

            self.assertEqual(set(summary["types"].keys()), set(TYPES))
            self.assertTrue((output_dir / "curve_equivalence_summary.json").exists())
            self.assertTrue((output_dir / "curve_equivalence_summary.csv").exists())
            self.assertTrue((output_dir / "feature_set_comparison.csv").exists())
            self.assertTrue((output_dir / "primary_comparison.csv").exists())
            self.assertTrue((output_dir / "typewise_run_metrics.csv").exists())
            self.assertTrue((output_dir / "feature_importance.csv").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertTrue(list((output_dir / "candidate_tables").glob("*/*.csv")))
            self.assertTrue(list((output_dir / "candidate_feature_tables").glob("*/*.csv")))
            self.assertTrue(list((output_dir / "predictions").glob("*/*.csv")))
            self.assertTrue(list((output_dir / "selected_models").glob("*/*.json")))

            payload = json.loads((output_dir / "curve_equivalence_summary.json").read_text(encoding="utf-8"))
            for titration_type, type_payload in payload["types"].items():
                self.assertEqual(set(type_payload["feature_set_metrics"].keys()), set(ce.FEATURE_SETS))
                self.assertEqual(set(type_payload["primary_comparison"].keys()), set(ce.PRIMARY_COMPARISON_SETS))
                self.assertIn("compact_plus", type_payload["primary_comparison"])
                self.assertIn("compact_plus_no_progress", type_payload["primary_comparison"])
                self.assertIn("run_level_metrics", type_payload)
                self.assertEqual(
                    type_payload["selected_model"]["selection_scope"],
                    "exploratory_best_across_feature_sets",
                )
                self.assertEqual(type_payload["run_level_metrics"]["prediction_unit"], "one_prediction_per_run")
                self.assertLess(type_payload["run_level_metrics"]["mae_ml"], 1.0)
                for fold in type_payload["folds"]:
                    self.assertEqual(fold["prediction_unit"], "one_prediction_per_run")
                    self.assertGreater(fold["candidate_count"], 0)
                    for feature in fold["feature_columns"]:
                        self.assertFalse(ce.is_forbidden_candidate_feature(feature), feature)
                    for prediction in fold["predictions"]:
                        self.assertIn("absolute_error_percent_of_equivalence", prediction)
                        self.assertIn("equivalence_derived_concentration_error_percent", prediction)

            with (output_dir / "typewise_run_metrics.csv").open(newline="", encoding="utf-8") as fh:
                typewise_rows = list(csv.DictReader(fh))
            self.assertEqual({row["titration_type"] for row in typewise_rows}, set(TYPES))
            for row in typewise_rows:
                self.assertIn("selected_feature_set", row)
                self.assertIn("mae_percent_of_equivalence", row)
                self.assertIn("concentration_mae_percent", row)
                self.assertIn("within_1pct_rate", row)
                self.assertIn("within_2pct_rate", row)
                self.assertIn("within_5pct_rate", row)

            report = (output_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("당량점 부피 오차", report)
            self.assertIn("상대오차", report)
            self.assertIn("농도 환산 오차", report)
            self.assertIn("타입별 핵심 지표", report)
            self.assertIn("프레임별 delta_ml 회귀", report)
            self.assertIn("1차 핵심 비교", report)
            self.assertIn("compact_plus", report)
            self.assertIn("compact_plus_no_progress", report)
            self.assertIn("candidate_feature_tables", report)
            self.assertIn("fusion_no_progress", report)
            self.assertIn("탐색적 최저 MAE", report)
            self.assertIn("proof-of-concept", report)


if __name__ == "__main__":
    unittest.main()
