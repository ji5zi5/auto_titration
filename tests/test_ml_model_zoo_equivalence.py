import csv
import tempfile
import unittest
from pathlib import Path

from auto_titrator import ml_model_zoo_equivalence as mz
from tests.test_ml_curve_equivalence import make_run, write_curve_run


class ModelZooEquivalenceTests(unittest.TestCase):
    def test_volume_resample_uses_injected_volume_grid_and_does_not_interpolate_labels(self):
        run = make_run(concentration=0.1)
        rows = list(run.rows[:5])
        duplicate = dict(rows[-1])
        duplicate["visible_H_mean"] = float(duplicate["visible_H_mean"]) + 10
        duplicate["status_label"] = "must_not_survive"
        rows.append(duplicate)
        leaky_run = type(run)(
            path=run.path,
            titration_type=run.titration_type,
            concentration_m=run.concentration_m,
            theoretical_equivalence_volume_ml=run.theoretical_equivalence_volume_ml,
            rows=rows,
        )

        resampled = mz.volume_resample_run(leaky_run, step_ml=0.1)

        self.assertGreaterEqual(len(resampled.rows), 2)
        self.assertAlmostEqual(float(resampled.rows[1]["injected_volume_ml"]) - float(resampled.rows[0]["injected_volume_ml"]), 0.1, places=6)
        self.assertNotIn("status_label", resampled.rows[0])
        self.assertNotIn("distance_to_equivalence_ml", resampled.rows[0])
        self.assertIn("theoretical_equivalence_volume_ml", resampled.rows[0])  # metadata/target only

    def test_feature_selector_blocks_progress_and_forbidden_patterns(self):
        columns = [
            "candidate_volume_ml",
            "candidate_score",
            "visible_H_mean_peak_slope",
            "thermal_roi_avg_peak_slope",
            "candidate_fraction_of_run",
            "run_volume_max_ml",
            "run_duration_s",
            "actual_equivalence_volume_ml",
            "predicted_equivalence_volume_ml",
            "reference_equivalence_volume_ml",
            "selected_pka_value",
            "manual_label",
            "some_target",
        ]

        selected = mz.select_feature_columns(columns, feature_set="sensor_plus_current_volume")

        self.assertIn("candidate_volume_ml", selected)
        self.assertIn("candidate_score", selected)
        self.assertIn("visible_H_mean_peak_slope", selected)
        self.assertIn("thermal_roi_avg_peak_slope", selected)
        self.assertNotIn("candidate_fraction_of_run", selected)
        self.assertNotIn("run_volume_max_ml", selected)
        self.assertNotIn("run_duration_s", selected)
        self.assertNotIn("actual_equivalence_volume_ml", selected)
        self.assertNotIn("predicted_equivalence_volume_ml", selected)
        self.assertNotIn("reference_equivalence_volume_ml", selected)
        self.assertNotIn("selected_pka_value", selected)
        self.assertNotIn("manual_label", selected)
        self.assertNotIn("some_target", selected)
        with self.assertRaises(ValueError):
            mz.assert_no_forbidden_features(["visible_H_mean_peak_slope", "candidate_error_ml"])

    def test_candidate_rows_use_explicit_sensor_sources_not_protocol_fraction(self):
        run = make_run(concentration=0.1)

        rows = mz.candidate_rows_for_runs([run], volume_grid_ml=0.1, smoothing_window_ml=0.3)
        sources = {row.get("candidate_source") for row in rows}
        selected = mz.select_feature_columns(set().union(*(row.keys() for row in rows)), feature_set="sensor_plus_current_volume")

        self.assertIn("color", sources)
        self.assertIn("thermal", sources)
        self.assertIn("fusion_sensor", sources)
        self.assertNotIn("protocol_fraction", sources)
        self.assertNotIn("candidate_fraction_of_run", selected)
        self.assertNotIn("run_volume_max_ml", selected)
        self.assertNotIn("run_duration_s", selected)

    def test_evaluate_model_zoo_writes_required_schema_and_grouped_split_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            out = Path(tmp) / "out"
            for concentration in (0.1, 0.15, 0.2):
                write_curve_run(root, "strong_acid_strong_base", concentration)

            summary = mz.evaluate_model_zoo(root, out, volume_grid_ml=0.1, smoothing_window_ml=0.3, include_optional=False, max_specs=1)

            self.assertEqual(summary["run_count"], 3)
            comparison_path = out / "model_comparison.csv"
            warnings_path = out / "warnings.csv"
            self.assertTrue(comparison_path.exists())
            self.assertTrue(warnings_path.exists())
            with comparison_path.open(encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(reader.fieldnames, mz.MODEL_COMPARISON_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row["validation_mode"] == "leave_one_concentration_out" for row in rows))
            self.assertTrue(all(row["selection_mode"] for row in rows))
            self.assertTrue(all(row["within_2pct_rate"] != "" for row in rows))
            self.assertTrue(all(row["concentration_error_percent"] != "" for row in rows))
            with warnings_path.open(encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(reader.fieldnames, mz.WARNING_COLUMNS)
            candidate_tables = list((out / "candidate_feature_tables").rglob("*.csv"))
            self.assertTrue(candidate_tables)
            for table in candidate_tables:
                with table.open(encoding="utf-8-sig", newline="") as fh:
                    fields = csv.DictReader(fh).fieldnames or []
                self.assertNotIn("candidate_fraction_of_run", fields)
                self.assertNotIn("run_volume_max_ml", fields)
                self.assertNotIn("run_duration_s", fields)
                self.assertNotIn("candidate_error_ml", fields)

    def test_protocol_candidates_require_progress_at_public_entry_points(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            out = Path(tmp) / "out"
            for concentration in (0.1, 0.15, 0.2):
                write_curve_run(root, "strong_acid_strong_base", concentration)
            runs = mz.load_runs(root)
            fold = mz.build_typewise_run_folds(runs)[0]
            spec = mz.model_specs(include_optional=False)[0][0]

            with self.assertRaises(ValueError):
                mz.evaluate_model_zoo(root, out, include_optional=False, max_specs=1, include_progress=False, include_protocol_candidates=True)
            with self.assertRaises(ValueError):
                mz.evaluate_fold(
                    fold,
                    spec,
                    volume_grid_ml=0.1,
                    smoothing_window_ml=0.3,
                    skipped_optional=[],
                    include_progress=False,
                    include_protocol_candidates=True,
                )

    def test_split_ids_preserve_per_parameter_prediction_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "runs"
            root.mkdir()
            out = Path(tmp) / "out"
            for concentration in (0.1, 0.15, 0.2):
                write_curve_run(root, "strong_acid_strong_base", concentration)

            mz.evaluate_model_zoo(root, out, volume_grid_ml=0.1, smoothing_window_ml=0.3, include_optional=False, max_specs=2)

            with (out / "model_comparison.csv").open(encoding="utf-8-sig", newline="") as fh:
                rows = list(csv.DictReader(fh))
            split_ids = [row["split_id"] for row in rows]
            prediction_files = list((out / "predictions").rglob("*.csv"))
            candidate_feature_files = list((out / "candidate_feature_tables").rglob("*.csv"))
            self.assertEqual(len(split_ids), 6)
            self.assertEqual(len(set(split_ids)), len(split_ids))
            self.assertEqual(len(prediction_files), len(rows))
            self.assertEqual(len(candidate_feature_files), len(rows))
            self.assertTrue((out / "aggregate_by_model.csv").exists())
            self.assertTrue((out / "typewise_best_headline.csv").exists())
            self.assertTrue((out / "candidate_availability_diagnostic.csv").exists())


if __name__ == "__main__":
    unittest.main()
