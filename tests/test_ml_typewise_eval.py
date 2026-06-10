import csv
import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator import ml_typewise_eval as tw


TYPES = [
    "strong_acid_strong_base",
    "weak_acid_strong_base",
    "strong_acid_weak_base",
    "weak_acid_weak_base",
]


def write_run(folder: Path, titration_type: str, concentration: float, *, session: int = 1) -> Path:
    path = folder / f"{titration_type}-{concentration:.2f}.csv"
    fieldnames = [
        "titration_type",
        "sample_name",
        "sample_concentration_M",
        "sample_volume_ml",
        "titrant_name",
        "titrant_concentration_M",
        "indicator",
        "theoretical_equivalence_volume_ml",
        "status_label",
        "status_confidence",
        "csv_session_id",
        "csv_row_index",
        "time_s",
        "frame_id",
        "injected_volume_ml",
        "distance_to_equivalence_ml",
        "equivalence_window_ml",
        "equivalence_window_label",
        "visible_R_mean",
        "visible_G_mean",
        "visible_B_mean",
        "visible_H_mean",
        "visible_S_mean",
        "visible_V_mean",
        "visible_color_delta",
        "thermal_roi_avg",
        "thermal_roi_p95",
        "thermal_raw_roi_p50",
        "thermal_raw_roi_p95",
        "thermal_raw_mean",
        "thermal_raw_std",
    ]
    eq = concentration * 200.0
    rows = []
    for i, t in enumerate([0.0, 0.11, 0.27, 0.43, 0.59]):
        injected = i * (eq / 4.0)
        rows.append(
            {
                "titration_type": titration_type,
                "sample_name": "synthetic sample",
                "sample_concentration_M": concentration,
                "sample_volume_ml": 20,
                "titrant_name": "synthetic titrant",
                "titrant_concentration_M": 0.1,
                "indicator": "synthetic indicator",
                "theoretical_equivalence_volume_ml": eq,
                "status_label": "overshoot",
                "status_confidence": 0.9,
                "csv_session_id": session,
                "csv_row_index": i + 1,
                "time_s": t,
                "frame_id": 1000 + i,
                "injected_volume_ml": injected,
                "distance_to_equivalence_ml": injected - eq,
                "equivalence_window_ml": 0.1,
                "equivalence_window_label": "leaky-old-label",
                "visible_R_mean": 100 + injected,
                "visible_G_mean": 90 + injected * 0.5,
                "visible_B_mean": 80 + injected * 0.25,
                "visible_H_mean": 30 + injected,
                "visible_S_mean": 0.1 + injected * 0.001,
                "visible_V_mean": 0.4 + injected * 0.002,
                "visible_color_delta": injected * 0.2,
                "thermal_roi_avg": 22 + injected * 0.03,
                "thermal_roi_p95": 23 + injected * 0.04,
                "thermal_raw_roi_p50": 5000 + injected,
                "thermal_raw_roi_p95": 5020 + injected * 1.5,
                "thermal_raw_mean": 5100 + injected,
                "thermal_raw_std": 5 + i,
            }
        )
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


class TypewiseMlEvalTests(unittest.TestCase):
    def test_label_generation_boundaries_use_theory_only_as_target(self):
        rows = [
            {"injected_volume_ml": "8.9", "theoretical_equivalence_volume_ml": "10"},
            {"injected_volume_ml": "9.0", "theoretical_equivalence_volume_ml": "10"},
            {"injected_volume_ml": "9.5", "theoretical_equivalence_volume_ml": "10"},
            {"injected_volume_ml": "10.5", "theoretical_equivalence_volume_ml": "10"},
            {"injected_volume_ml": "11.1", "theoretical_equivalence_volume_ml": "10"},
        ]
        labeled = tw.generate_labels(rows, window_ml=0.5)

        self.assertEqual([row["zone_label"] for row in labeled], ["far_before", "approaching", "equivalence_zone", "equivalence_zone", "overshoot"])
        self.assertAlmostEqual(labeled[2]["delta_ml"], -0.5)

    def test_resampling_interpolates_raw_only_and_recomputes_derived_features(self):
        run = tw.CsvRun(
            path=Path("synthetic.csv"),
            titration_type="strong_acid_strong_base",
            concentration_m=0.1,
            theoretical_equivalence_volume_ml=10.0,
            rows=[
                {"time_s": "0.0", "injected_volume_ml": "0", "visible_R_mean": "10", "visible_color_delta": "0", "thermal_roi_avg": "20", "status_label": "bad", "distance_to_equivalence_ml": "-10"},
                {"time_s": "0.1", "injected_volume_ml": "1", "visible_R_mean": "20", "visible_color_delta": "2", "thermal_roi_avg": "21", "status_label": "bad", "distance_to_equivalence_ml": "-9"},
                {"time_s": "0.3", "injected_volume_ml": "3", "visible_R_mean": "40", "visible_color_delta": "6", "thermal_roi_avg": "23", "status_label": "bad", "distance_to_equivalence_ml": "-7"},
            ],
        )

        resampled = tw.resample_run(run, fps=25.0)

        self.assertGreater(len(resampled.rows), len(run.rows))
        self.assertAlmostEqual(float(resampled.rows[1]["time_s"]), 0.04, places=6)
        self.assertAlmostEqual(float(resampled.rows[2]["injected_volume_ml"]), 0.8, places=6)
        self.assertNotIn("status_label", resampled.rows[1])
        self.assertNotIn("distance_to_equivalence_ml", resampled.rows[1])
        self.assertIn("visible_color_baseline_delta", resampled.rows[-1])
        self.assertIn("zone_label", resampled.rows[-1])

    def test_feature_selector_blocks_legacy_leaky_columns_and_patterns(self):
        columns = [
            "time_s",
            "injected_volume_ml",
            "visible_R_mean",
            "thermal_roi_avg",
            "sample_concentration_M",
            "status_confidence",
            "estimated_equivalence_volume_ml",
            "actual_delta_ml",
            "reference_equivalence_volume_ml",
            "csv_row_index",
            "titration_is_strong_acid_strong_base",
        ]

        selected = tw.select_feature_columns(columns, feature_set="full")

        self.assertIn("visible_R_mean", selected)
        self.assertIn("thermal_roi_avg", selected)
        self.assertNotIn("sample_concentration_M", selected)
        self.assertNotIn("status_confidence", selected)
        self.assertNotIn("estimated_equivalence_volume_ml", selected)
        self.assertNotIn("actual_delta_ml", selected)
        self.assertNotIn("reference_equivalence_volume_ml", selected)
        self.assertNotIn("csv_row_index", selected)
        self.assertNotIn("titration_is_strong_acid_strong_base", selected)
        self.assertFalse(hasattr(tw, "DEFAULT_FEATURE_COLUMNS"))
        with self.assertRaises(ValueError):
            tw.assert_no_forbidden_features(["visible_R_mean", "status_confidence"])

    def test_typewise_fold_builder_holds_out_concentration_inside_each_type(self):
        runs = [
            tw.CsvRun(Path(f"{kind}-{conc}.csv"), kind, conc, conc * 100, [{"time_s": 0}])
            for kind in TYPES
            for conc in (0.1, 0.15, 0.2)
        ]

        folds = tw.build_typewise_folds(runs)

        self.assertEqual(len(folds), 12)
        for fold in folds:
            self.assertEqual({run.titration_type for run in fold.train_runs}, {fold.titration_type})
            self.assertEqual({run.titration_type for run in fold.test_runs}, {fold.titration_type})
            self.assertNotIn(fold.held_out_concentration_m, {run.concentration_m for run in fold.train_runs})
            self.assertEqual({fold.held_out_concentration_m}, {run.concentration_m for run in fold.test_runs})

    def test_synthetic_end_to_end_writes_artifacts_and_metadata_without_leaky_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "runs"
            output_dir = root / "ml"
            input_dir.mkdir()
            session = 1
            for kind in TYPES:
                for concentration in (0.1, 0.15, 0.2):
                    write_run(input_dir, kind, concentration, session=session)
                    session += 1

            summary = tw.evaluate_folder(input_dir, output_dir=output_dir, fps=25, window_ml=0.5, quick=True)

            self.assertEqual(set(summary["types"].keys()), set(TYPES))
            self.assertTrue((output_dir / "typewise_summary.json").exists())
            self.assertTrue((output_dir / "typewise_summary.csv").exists())
            self.assertTrue((output_dir / "report.md").exists())
            self.assertTrue(list((output_dir / "predictions").glob("*/*/*.csv")))
            self.assertTrue(list((output_dir / "selected_models").glob("*/*.json")))
            payload = json.loads((output_dir / "typewise_summary.json").read_text(encoding="utf-8"))
            for titration_type, type_payload in payload["types"].items():
                self.assertIn("folds", type_payload)
                self.assertEqual({fold["feature_set"] for fold in type_payload["folds"]}, set(tw.FEATURE_SETS))
                self.assertEqual(len(type_payload["folds"]), 12)
                self.assertEqual(set(type_payload["feature_set_macro"].keys()), set(tw.FEATURE_SETS))
                classifier_meta = json.loads(
                    (output_dir / "selected_models" / titration_type / "classifier.json").read_text(encoding="utf-8")
                )
                regressor_meta = json.loads(
                    (output_dir / "selected_models" / titration_type / "regressor.json").read_text(encoding="utf-8")
                )
                self.assertIn(classifier_meta["feature_set"], tw.FEATURE_SETS)
                self.assertIn(regressor_meta["feature_set"], tw.FEATURE_SETS)
                self.assertEqual(classifier_meta["forbidden_feature_audit"]["status"], "passed")
                self.assertTrue(classifier_meta["fold_run_identifiers"])
                for fold in type_payload["folds"]:
                    self.assertGreater(fold["resampled_row_count"], 0)
                    self.assertGreater(fold["original_row_count"], 0)
                    self.assertEqual(fold["observation_unit"], "frame_level_observations_not_independent_experiments")
                    self.assertTrue(fold["classifier_candidates"])
                    self.assertTrue(fold["regressor_candidates"])
                    self.assertTrue(fold["train_run_paths"])
                    self.assertTrue(fold["test_run_paths"])
                    for feature in fold["feature_columns"]:
                        self.assertFalse(tw.is_forbidden_feature(feature), feature)
            report = (output_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("fold-first", report)
            self.assertIn("held-out", report)
            self.assertIn("통합 모델", report)
            self.assertIn("proof-of-concept", report)


if __name__ == "__main__":
    unittest.main()
