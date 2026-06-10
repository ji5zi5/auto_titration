import unittest

from auto_titrator.data_schema import DEFAULT_COLUMNS, SCHEMA_VERSION, UNITS_BY_COLUMN


class DataSchemaTests(unittest.TestCase):
    def test_schema_version_exists(self):
        self.assertEqual(SCHEMA_VERSION, "1.8")

    def test_schema_contains_experiment_pump_camera_and_ml_fields(self):
        required = {
            "schema_version",
            "experiment_id",
            "titration_type",
            "sample_concentration_M",
            "sample_volume_ml",
            "titrant_concentration_M",
            "theoretical_equivalence_volume_ml",
            "chemistry_model",
            "constants_source_id",
            "constants_candidate_count",
            "constants_lookup_ambiguous",
            "constants_confirmation_status",
            "constants_warning",
            "selected_pka_value",
            "activity_model",
            "ionic_strength_label",
            "theoretical_equivalence_pH",
            "indicator_transition_low_pH",
            "indicator_endpoint_volume_ml",
            "standard_solution_uncertainty_note",
            "equivalence_formula",
            "calculated_theoretical_equivalence_volume_ml",
            "sample_concentration_from_theoretical_equivalence_M",
            "reference_equivalence_volume_ml",
            "observed_color_endpoint_volume_ml",
            "predicted_equivalence_volume_ml",
            "sample_concentration_from_predicted_equivalence_M",
            "predicted_sample_concentration_error_percent",
            "pump_step_count",
            "pump_commanded_step_count",
            "pump_confirmed_step_count",
            "pump_run_rate_ml_per_s",
            "pump_elapsed_s",
            "pump_calibrated_ml_per_step",
            "commanded_volume_ml",
            "confirmed_injected_volume_ml",
            "csv_session_id",
            "csv_row_index",
            "csv_recording_started_epoch_s",
            "csv_recording_elapsed_s",
            "csv_mark_sequence",
            "csv_event_note",
            "time_s",
            "frame_id",
            "visible_R_mean",
            "visible_H_delta",
            "visible_HSV_delta",
            "thermal_R_mean",
            "thermal_H_delta",
            "thermal_HSV_delta",
            "theoretical_equivalence_time_s",
            "distance_to_equivalence_ml",
            "time_to_equivalence_s",
            "equivalence_window_label",
            "sample_concentration_from_injected_M",
            "sample_concentration_error_percent",
            "visible_H_baseline_delta",
            "visible_color_delta_mean_1s",
            "thermal_roi_avg_baseline_delta",
            "thermal_roi_avg_slope_c_per_s",
            "abs_sync_offset_ms",
            "training_quality_score",
            "valid_for_training",
            "titration_is_weak_acid_strong_base",
        }

        self.assertTrue(required.issubset(set(DEFAULT_COLUMNS)))
        self.assertNotIn("volume_source", DEFAULT_COLUMNS)
        self.assertNotIn("manual_volume_anchor_ml", DEFAULT_COLUMNS)
        self.assertNotIn("manual_volume_delta_ml", DEFAULT_COLUMNS)
        self.assertNotIn("manual_volume_note", DEFAULT_COLUMNS)
        self.assertNotIn("manual_label", DEFAULT_COLUMNS)
        self.assertNotIn("predicted_manual_label", DEFAULT_COLUMNS)

    def test_units_include_core_scientific_fields(self):
        self.assertEqual(UNITS_BY_COLUMN["sample_concentration_M"], "mol/L")
        self.assertEqual(UNITS_BY_COLUMN["sample_volume_ml"], "mL")
        self.assertEqual(UNITS_BY_COLUMN["theoretical_equivalence_volume_ml"], "mL")
        self.assertEqual(UNITS_BY_COLUMN["selected_pka_value"], "pKa")
        self.assertEqual(UNITS_BY_COLUMN["ionic_strength_m"], "mol/L")
        self.assertEqual(UNITS_BY_COLUMN["theoretical_equivalence_pH"], "pH")
        self.assertEqual(UNITS_BY_COLUMN["indicator_endpoint_volume_ml"], "mL")
        self.assertEqual(UNITS_BY_COLUMN["calculated_theoretical_equivalence_volume_ml"], "mL")
        self.assertEqual(UNITS_BY_COLUMN["sample_concentration_from_theoretical_equivalence_M"], "mol/L")
        self.assertEqual(UNITS_BY_COLUMN["sample_concentration_from_predicted_equivalence_M"], "mol/L")
        self.assertEqual(UNITS_BY_COLUMN["predicted_sample_concentration_error_percent"], "%")
        self.assertEqual(UNITS_BY_COLUMN["pump_run_rate_ml_per_s"], "mL/s")
        self.assertEqual(UNITS_BY_COLUMN["pump_elapsed_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["csv_recording_elapsed_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["time_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["theoretical_equivalence_time_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["distance_to_equivalence_ml"], "mL")
        self.assertEqual(UNITS_BY_COLUMN["time_to_equivalence_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["sample_concentration_from_injected_M"], "mol/L")
        self.assertEqual(UNITS_BY_COLUMN["sample_concentration_error_percent"], "%")
        self.assertEqual(UNITS_BY_COLUMN["visible_H_delta"], "degree")
        self.assertEqual(UNITS_BY_COLUMN["thermal_H_delta"], "degree")
        self.assertEqual(UNITS_BY_COLUMN["visible_H_slope_deg_per_s"], "degree/s")
        self.assertEqual(UNITS_BY_COLUMN["thermal_roi_avg_slope_c_per_s"], "degC/s")
        self.assertEqual(UNITS_BY_COLUMN["abs_sync_offset_ms"], "ms")

    def test_schema_contains_live_status_and_temperature_roi_fields(self):
        required = {
            "thermal_roi_avg",
            "thermal_roi_max",
            "thermal_roi_min",
            "thermal_roi_std",
            "thermal_roi_delta",
            "thermal_roi_p05",
            "thermal_roi_p50",
            "thermal_roi_p95",
            "thermal_roi_iqr",
            "thermal_roi_hot_fraction",
            "thermal_roi_min_x",
            "thermal_roi_max_y",
            "thermal_matrix_avg",
            "thermal_matrix_p50",
            "thermal_matrix_iqr",
            "thermal_raw_roi_p50",
            "thermal_raw_roi_iqr",
            "thermal_matrix_max",
            "thermal_matrix_min",
            "thermal_raw_mean",
            "thermal_frame_rate_hz",
            "thermal_conversion_model",
            "thermal_calibrated",
            "status_label",
            "status_confidence",
            "source_quality",
            "warnings",
            "estimated_equivalence_time_s",
            "estimated_equivalence_volume_ml",
            "equivalence_confidence",
            "absolute_volume_error_ml",
            "relative_volume_error_percent",
        }

        self.assertTrue(required.issubset(set(DEFAULT_COLUMNS)))
        self.assertEqual(UNITS_BY_COLUMN["thermal_roi_avg"], "degC")
        self.assertEqual(UNITS_BY_COLUMN["thermal_roi_p50"], "degC")
        self.assertEqual(UNITS_BY_COLUMN["thermal_matrix_avg"], "degC")
        self.assertEqual(UNITS_BY_COLUMN["thermal_matrix_p95"], "degC")
        self.assertEqual(UNITS_BY_COLUMN["thermal_frame_rate_hz"], "Hz")
        self.assertEqual(UNITS_BY_COLUMN["estimated_equivalence_time_s"], "s")
        self.assertEqual(UNITS_BY_COLUMN["absolute_volume_error_ml"], "mL")

    def test_schema_contains_sensor_sync_fields(self):
        for column in [
            "thermal_time_s",
            "visible_time_s",
            "sync_offset_ms",
            "sync_method",
            "sync_quality",
            "sync_warning",
        ]:
            with self.subTest(column=column):
                self.assertIn(column, DEFAULT_COLUMNS)


if __name__ == "__main__":
    unittest.main()
