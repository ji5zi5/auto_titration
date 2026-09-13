import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun
from tools import modality_specific_ablation as ablation


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
                "theoretical_equivalence_volume_ml": actual_ml,
                "status_label": "forbidden",
            }
        )
    return CsvRun(
        path=Path(name),
        titration_type="strong_acid_strong_base",
        concentration_m=actual_ml / 200.0,
        theoretical_equivalence_volume_ml=actual_ml,
        rows=rows,
    )


class ModalitySpecificAblationTests(unittest.TestCase):
    def setUp(self):
        self.runs = [
            make_run("run-20.csv", 20.0, 0.0),
            make_run("run-25.csv", 25.0, 0.1),
            make_run("run-30.csv", 30.0, 0.2),
            make_run("run-35.csv", 35.0, 0.3),
        ]

    def test_feature_groups_are_modality_pure_and_reject_leakage(self):
        columns = set().union(*(row.keys() for run in self.runs for row in run.rows))
        selected = {
            group: ablation.select_feature_columns(columns, group)
            for group in ablation.FEATURE_GROUPS
        }

        self.assertEqual(selected["volume_only"], ["injected_volume_ml"])
        self.assertTrue(all("injected_volume_ml" in values for values in selected.values()))
        self.assertTrue(all(not column.startswith("thermal_") for column in selected["color_plus_volume"]))
        self.assertTrue(all(not column.startswith("visible_") for column in selected["thermal_plus_volume"]))
        for group, values in selected.items():
            self.assertFalse(ablation.forbidden_features(values), (group, values))
            self.assertNotIn("run_volume_max_ml", values)
            self.assertNotIn("candidate_fraction_of_run", values)
            self.assertNotIn("distance_to_equivalence_ml", values)
            self.assertNotIn("sample_concentration_M", values)
            self.assertNotIn("theoretical_equivalence_volume_ml", values)

    def test_candidates_are_modality_specific_and_resource_bounded(self):
        spaces = {
            group: ablation.candidate_space(group, n_estimators=7)
            for group in ablation.FEATURE_GROUPS
        }

        self.assertNotEqual(spaces["volume_only"], spaces["color_plus_volume"])
        self.assertNotEqual(spaces["color_plus_volume"], spaces["thermal_plus_volume"])
        self.assertLessEqual(max(map(len, spaces.values())), 4)
        for candidates in spaces.values():
            for candidate in candidates:
                if candidate.family == "ExtraTreesClassifier":
                    self.assertEqual(candidate.parameters["n_estimators"], 7)
                    self.assertEqual(ablation.build_model(candidate).n_jobs, 1)

    def test_future_rows_do_not_change_earlier_feature_vector(self):
        columns = ablation.select_feature_columns(
            self.runs[0].rows[0].keys(), "color_thermal_plus_volume"
        )
        before = ablation.project_row(self.runs[0].rows[5], columns)
        self.runs[0].rows[-1]["visible_H_mean"] = 999999.0
        self.runs[0].rows[-1]["thermal_roi_avg"] = -999999.0

        self.assertEqual(before, ablation.project_row(self.runs[0].rows[5], columns))

    def test_nested_loro_selects_model_hyperparameters_and_aggregation_without_outer_test(self):
        result = ablation.evaluate_runs(
            self.runs,
            grid_ml=1.0,
            zone_window_ml=1.0,
            n_estimators=7,
        )

        expected_paths = {str(run.path) for run in self.runs}
        self.assertFalse(result["split"]["outer_test_used_for_model_selection"])
        self.assertFalse(result["split"]["outer_test_used_for_hyperparameter_selection"])
        self.assertFalse(result["split"]["outer_test_used_for_aggregation_selection"])
        for group in ablation.FEATURE_GROUPS:
            predictions = result["groups"][group]["predictions"]
            candidate_ids = {
                candidate["candidate_id"] for candidate in result["groups"][group]["candidate_space"]
            }
            self.assertEqual({row["run_path"] for row in predictions}, expected_paths)
            for row in predictions:
                self.assertNotIn(row["run_path"], row["selection_run_paths"])
                self.assertNotIn(row["run_path"], row["inner_validation_run_paths"])
                self.assertEqual(set(row["selection_run_paths"]), expected_paths - {row["run_path"]})
                self.assertIn(row["selected_candidate_id"], candidate_ids)
                self.assertIn(row["selected_aggregation"], ablation.AGGREGATION_MODES)

    def test_writes_auditable_outputs_and_required_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            summary = ablation.evaluate_runs(
                self.runs,
                output_dir=output,
                grid_ml=1.0,
                zone_window_ml=1.0,
                n_estimators=7,
            )

            loaded = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["run_count"], 4)
            self.assertTrue((output / "predictions.csv").exists())
            self.assertTrue((output / "model_selection.csv").exists())
            for group in ablation.FEATURE_GROUPS:
                metrics = summary["groups"][group]["metrics"]
                for key in (
                    "mae_ml",
                    "rmse_ml",
                    "mape_percent",
                    "within_1pct_rate",
                    "within_2pct_rate",
                    "within_5pct_rate",
                ):
                    self.assertIn(key, metrics)
                self.assertTrue(summary["groups"][group]["selected_model_counts"])
                self.assertTrue((output / f"predictions_{group}.csv").exists())


if __name__ == "__main__":
    unittest.main()
