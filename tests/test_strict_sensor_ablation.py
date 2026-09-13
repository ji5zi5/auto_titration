import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun
from tools import strict_sensor_ablation as ablation


def make_run(name: str, actual_ml: float, offset: float) -> CsvRun:
    rows = []
    for index in range(41):
        volume = float(index)
        distance = volume - actual_ml
        rows.append(
            {
                "injected_volume_ml": volume,
                "visible_H_mean": offset + distance * distance,
                "visible_color_delta": abs(distance),
                "visible_H_slope_deg_per_s": distance,
                "thermal_roi_avg": 20.0 + offset - abs(distance),
                "thermal_roi_p95": 21.0 + offset - abs(distance),
                "thermal_roi_avg_slope_c_per_s": -distance,
                "run_volume_max_ml": 40.0,
                "candidate_fraction_of_run": volume / 40.0,
                "distance_to_equivalence_ml": distance,
                "sample_concentration_M": actual_ml / 200.0,
            }
        )
    return CsvRun(
        path=Path(name),
        titration_type="strong_acid_strong_base",
        concentration_m=actual_ml / 200.0,
        theoretical_equivalence_volume_ml=actual_ml,
        rows=rows,
    )


class StrictSensorAblationTests(unittest.TestCase):
    def setUp(self):
        self.runs = [
            make_run("run-20.csv", 20.0, 0.0),
            make_run("run-25.csv", 25.0, 0.1),
            make_run("run-30.csv", 30.0, 0.2),
            make_run("run-35.csv", 35.0, 0.3),
        ]

    def test_feature_groups_are_modality_pure_and_share_current_volume(self):
        columns = set().union(*(row.keys() for run in self.runs for row in run.rows))

        selected = {
            group: ablation.select_feature_columns(columns, group)
            for group in ablation.FEATURE_GROUPS
        }

        self.assertEqual(selected["volume_only"], ["injected_volume_ml"])
        self.assertTrue(all("injected_volume_ml" in values for values in selected.values()))
        self.assertTrue(all(not column.startswith("thermal_") for column in selected["color_plus_volume"]))
        self.assertTrue(all(not column.startswith("visible_") for column in selected["thermal_plus_volume"]))
        self.assertTrue(
            any(column.startswith("visible_") for column in selected["color_thermal_plus_volume"])
        )
        self.assertTrue(
            any(column.startswith("thermal_") for column in selected["color_thermal_plus_volume"])
        )
        self.assertNotIn("visible_thermal_slope_agreement", selected["color_plus_volume"])

    def test_feature_groups_reject_truth_and_end_of_run_columns(self):
        columns = set().union(*(row.keys() for run in self.runs for row in run.rows))

        for group in ablation.FEATURE_GROUPS:
            selected = ablation.select_feature_columns(columns, group)
            self.assertFalse(ablation.forbidden_features(selected), (group, selected))
            self.assertNotIn("run_volume_max_ml", selected)
            self.assertNotIn("candidate_fraction_of_run", selected)
            self.assertNotIn("distance_to_equivalence_ml", selected)
            self.assertNotIn("sample_concentration_M", selected)

    def test_future_rows_do_not_change_an_earlier_frame_feature_vector(self):
        columns = ablation.select_feature_columns(
            self.runs[0].rows[0].keys(), "color_thermal_plus_volume"
        )
        before = ablation.project_row(self.runs[0].rows[5], columns)
        self.runs[0].rows[-1]["visible_H_mean"] = 999999.0
        self.runs[0].rows[-1]["thermal_roi_avg"] = -999999.0

        after = ablation.project_row(self.runs[0].rows[5], columns)

        self.assertEqual(before, after)

    def test_nested_loro_evaluates_same_runs_without_outer_test_selection(self):
        result = ablation.evaluate_runs(
            self.runs,
            grid_ml=1.0,
            zone_window_ml=1.0,
            n_estimators=8,
        )

        expected_paths = {str(run.path) for run in self.runs}
        for group in ablation.FEATURE_GROUPS:
            predictions = result["groups"][group]["predictions"]
            self.assertEqual({row["run_path"] for row in predictions}, expected_paths)
            self.assertEqual(len(predictions), len(self.runs))
            for row in predictions:
                self.assertNotIn(row["run_path"], row["selection_run_paths"])

    def test_evaluate_folder_writes_summary_and_group_prediction_csvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            summary = ablation.evaluate_runs(
                self.runs,
                output_dir=output,
                grid_ml=1.0,
                zone_window_ml=1.0,
                n_estimators=8,
            )

            loaded = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["run_count"], 4)
            self.assertEqual(summary["run_count"], 4)
            self.assertTrue((output / "predictions.csv").exists())
            for group in ablation.FEATURE_GROUPS:
                self.assertTrue((output / f"predictions_{group}.csv").exists())


if __name__ == "__main__":
    unittest.main()
