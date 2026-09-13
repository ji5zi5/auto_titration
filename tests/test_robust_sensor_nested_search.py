import json
import os
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun
from tools import robust_sensor_nested_search as search


def make_run(index: int) -> CsvRun:
    actual = 10.0 + index
    rows = []
    for step in range(25):
        volume = float(step)
        distance = volume - actual
        rows.append(
            {
                "injected_volume_ml": volume,
                "confirmed_injected_volume_ml": volume,
                "sample_concentration_M": actual / 100.0,
                "theoretical_equivalence_volume_ml": actual,
                "distance_to_equivalence_ml": distance,
                "time_to_equivalence_s": -distance,
                "equivalence_window_label": int(abs(distance) <= 1.0),
                "visible_H_mean": distance * distance + index * 0.01,
                "visible_color_delta": abs(distance),
                "visible_H_slope_deg_per_s": distance,
                "thermal_roi_avg": 30.0 - abs(distance) + index * 0.01,
                "thermal_roi_p95": 31.0 - abs(distance),
                "thermal_raw_roi_p50_baseline_delta": -distance,
                "thermal_roi_min_x": 7,
                "visible_time_s": step,
            }
        )
    return CsvRun(
        path=Path(f"run-{index}.csv"),
        titration_type="strong_acid_strong_base",
        concentration_m=actual / 100.0,
        theoretical_equivalence_volume_ml=actual,
        rows=rows,
    )


class RobustSensorNestedSearchTests(unittest.TestCase):
    def setUp(self):
        self.runs = [make_run(index) for index in range(4)]

    def test_sensor_columns_exclude_all_prohibited_inputs_and_metadata(self):
        columns = set().union(*(row.keys() for run in self.runs for row in run.rows))
        for modality in ("color", "thermal", "fusion"):
            selected = search.select_sensor_columns(columns, modality)
            self.assertFalse(search.forbidden_features(selected))
            self.assertNotIn("injected_volume_ml", selected)
            self.assertNotIn("sample_concentration_M", selected)
            self.assertNotIn("distance_to_equivalence_ml", selected)
            self.assertNotIn("equivalence_window_label", selected)
            self.assertNotIn("visible_time_s", selected)
            self.assertNotIn("thermal_roi_min_x", selected)

    def test_seed_and_parallelism_contracts_are_fixed(self):
        self.assertEqual(search.SEEDS, (42, 1729, 20260728))
        for variable in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            self.assertEqual(os.environ[variable], "1")
        model = search._make_model("extra_trees", seed=42, n_estimators=3)
        estimator = model.steps[-1][1]
        self.assertEqual(estimator.n_jobs, 1)

    def test_nested_selection_never_uses_outer_test_and_is_deterministic(self):
        candidates = (
            search.Candidate("color", "extra_trees", "top1"),
            search.Candidate("fusion", "extra_trees", "top3"),
        )
        first = search.evaluate_runs(
            self.runs,
            seeds=search.SEEDS,
            candidates=candidates,
            grid_ml=1.0,
            n_estimators=4,
            expected_run_count=4,
        )
        second = search.evaluate_runs(
            self.runs,
            seeds=search.SEEDS,
            candidates=candidates,
            grid_ml=1.0,
            n_estimators=4,
            expected_run_count=4,
        )
        self.assertEqual(first["per_seed_metrics"], second["per_seed_metrics"])
        self.assertEqual(len(first["per_seed_metrics"]), 3)
        self.assertTrue(first["leakage_audit"]["passed"])
        for row in first["outer_predictions"]:
            self.assertNotIn(row["run_path"], row["selection_run_paths"])

    def test_output_is_explicitly_exploratory_and_reports_every_seed(self):
        candidates = (search.Candidate("fusion", "extra_trees", "top1"),)
        with tempfile.TemporaryDirectory() as tmp:
            summary = search.evaluate_runs(
                self.runs,
                output_dir=tmp,
                seeds=search.SEEDS,
                candidates=candidates,
                grid_ml=1.0,
                n_estimators=3,
                expected_run_count=4,
            )
            loaded = json.loads(Path(tmp, "summary.json").read_text(encoding="utf-8"))
            report = Path(tmp, "report.md").read_text(encoding="utf-8")
            self.assertEqual(loaded["seeds"], [42, 1729, 20260728])
            self.assertEqual(len(summary["aggregate_robustness"]), 4)
            self.assertIn("not independent external validation", report)
            self.assertTrue(Path(tmp, "outer_predictions.csv").exists())

    def test_requires_exact_existing_run_count_and_prescribed_seeds(self):
        with self.assertRaisesRegex(ValueError, "expected exactly 12"):
            search.evaluate_runs(self.runs)
        with self.assertRaisesRegex(ValueError, "seed list must be exactly"):
            search.evaluate_runs(self.runs, seeds=(42,), expected_run_count=4)


if __name__ == "__main__":
    unittest.main()
