import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun
from tools import report_modality_development_selector as comparison


class ReportModalityDevelopmentSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = Path("data/ml/current_volume_no_progress")
        cls.columns = comparison.load_reference_feature_columns(cls.reference)

    def test_three_groups_ablate_only_requested_sensor_modality(self):
        color = comparison.select_group_columns(self.columns, "color_only")
        thermal = comparison.select_group_columns(self.columns, "thermal_only")
        fusion = comparison.select_group_columns(self.columns, "color_thermal_fusion")

        self.assertTrue(any(column.startswith("visible_") for column in color))
        self.assertFalse(any(column.startswith("thermal_") for column in color))
        self.assertTrue(any(column.startswith("thermal_") for column in thermal))
        self.assertFalse(any(column.startswith("visible_") for column in thermal))
        self.assertEqual(fusion, self.columns)
        self.assertEqual(
            comparison.shared_control_columns(color),
            comparison.shared_control_columns(thermal),
        )

    def test_sensor_only_mode_excludes_current_volume_from_model_features(self):
        for group in comparison.GROUPS:
            columns = comparison.select_group_columns(
                self.columns,
                group,
                include_current_volume_feature=False,
            )
            self.assertNotIn("injected_volume_ml", columns)

        color = comparison.select_group_columns(
            self.columns,
            "color_only",
            include_current_volume_feature=False,
        )
        thermal = comparison.select_group_columns(
            self.columns,
            "thermal_only",
            include_current_volume_feature=False,
        )
        fusion = comparison.select_group_columns(
            self.columns,
            "color_thermal_fusion",
            include_current_volume_feature=False,
        )
        self.assertTrue(any(column.startswith("visible_") for column in color))
        self.assertFalse(any(column.startswith("thermal_") for column in color))
        self.assertTrue(any(column.startswith("thermal_") for column in thermal))
        self.assertFalse(any(column.startswith("visible_") for column in thermal))
        self.assertTrue(any(column.startswith("visible_") for column in fusion))
        self.assertTrue(any(column.startswith("thermal_") for column in fusion))

    def test_sensor_only_records_keep_volume_outside_model_feature_dict(self):
        run = CsvRun(
            path=Path("run.csv"),
            titration_type="strong_acid_strong_base",
            concentration_m=0.1,
            theoretical_equivalence_volume_ml=20.0,
            rows=[
                {
                    "injected_volume_ml": 1.0,
                    "visible_H_mean": 42.0,
                }
            ],
        )
        records = comparison.build_group_records(
            [run],
            ["visible_H_mean"],
            grid_ml=0.25,
        )

        self.assertEqual(records[0]["current_volume_ml"], 1.0)
        self.assertEqual(records[0]["features"], {"visible_H_mean": 42.0})
        self.assertNotIn("injected_volume_ml", records[0]["features"])

    def test_groups_exclude_forbidden_truth_progress_and_end_fields(self):
        for group in comparison.GROUPS:
            columns = comparison.select_group_columns(self.columns, group)
            offenders = [
                column
                for column in columns
                if comparison.trainer.is_forbidden_column(column)
            ]
            self.assertEqual(offenders, [], (group, offenders))
            self.assertNotIn("sample_concentration_M", columns)
            self.assertNotIn("theoretical_equivalence_volume_ml", columns)
            self.assertNotIn("run_volume_max_ml", columns)
            self.assertNotIn("candidate_fraction_of_run", columns)

    def test_candidate_registry_matches_historical_frame_candidate_space(self):
        registry = comparison.load_candidate_registry(self.reference)
        method_count = sum(
            len(keys) for modes in registry.values() for keys in modes.values()
        )
        self.assertEqual(method_count, 3075)
        self.assertEqual(len(registry), 105)
        self.assertEqual(
            {signature.model_name for signature in registry},
            {
                "extra_trees",
                "extra_trees_leaf3",
                "random_forest",
                "gradient_boosting",
                "logistic",
            },
        )

    def test_parse_candidate_key_supports_legacy_and_explicit_scopes(self):
        legacy, mode = comparison.parse_candidate_key(
            "frame_zone_classifier:extra_trees:window0.5:top25"
        )
        explicit, explicit_mode = comparison.parse_candidate_key(
            "frame_zone_classifier:extra_trees:same_type:window0.15:weighted_median_top10"
        )

        self.assertEqual(legacy.scope, "all_types")
        self.assertEqual(legacy.window_ml, 0.5)
        self.assertEqual(mode, "top25")
        self.assertEqual(explicit.scope, "same_type")
        self.assertEqual(explicit.window_ml, 0.15)
        self.assertEqual(explicit_mode, "weighted_median_top10")

    def test_locked_fusion_reference_is_exactly_1p271147_percent(self):
        reference = comparison._reference_summary(self.reference)
        best = reference["best"]["metrics"]
        self.assertEqual(best["mae_ml"], 0.392472)
        self.assertEqual(best["rmse_ml"], 0.685276)
        self.assertEqual(best["mape_percent"], 1.271147)
        self.assertEqual(
            reference["typewise_development_selector"]["comparison_row"]["mape_percent"],
            1.271147,
        )


if __name__ == "__main__":
    unittest.main()
