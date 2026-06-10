import unittest

from auto_titrator.collection import build_collection_row
from auto_titrator.data_schema import SCHEMA_VERSION
from auto_titrator.experiment_config import ExperimentConfig


class CollectionRowTests(unittest.TestCase):
    def test_builds_row_with_experiment_pump_and_feature_fields(self):
        experiment = ExperimentConfig(
            experiment_id="trial-001",
            titration_type="strong_acid_strong_base",
            sample_name="HCl",
            sample_concentration_m=0.1,
            sample_volume_ml=20.0,
            sample_valence=1,
            titrant_name="NaOH",
            titrant_concentration_m=0.1,
            titrant_valence=1,
            indicator="phenolphthalein",
            constants_source="IUPAC Dissociation Constants high-confidence local CSV",
            constants_source_id="acid-001",
            constants_query="acetic acid",
            constants_candidate_count=2,
            constants_lookup_ambiguous=True,
            constants_confirmation_status="confirmed_by_user",
            constants_warning="Multiple candidates",
            selected_pka_type="pKa",
            selected_pka_value=4.76,
            selected_pka_temperature_c=25.0,
            activity_model="davies",
            ionic_strength_m=0.05,
            ionic_strength_label="high_reliability",
            activity_warning="Davies activity correction is within range.",
            theoretical_equivalence_ph=7.0,
            indicator_transition_low_ph=8.2,
            indicator_transition_high_ph=10.0,
            indicator_endpoint_volume_ml=20.1,
            indicator_endpoint_offset_ml=0.1,
            indicator_endpoint_confidence="model_estimate",
            indicator_endpoint_warning="indicator differs from equivalence",
        )

        row = build_collection_row(
            experiment=experiment,
            time_s=1.25,
            frame_id=7,
            injected_volume_ml=0.5,
            visible_features={"visible_R_mean": 120.0},
            thermal_features={"thermal_R_mean": 30.0, "thermal_source": "usb_palette"},
            pump_state={"pump_mode": "dry_run", "pump_step_count": 100, "pump_calibrated_ml_per_step": 0.005},
        )

        self.assertEqual(row["schema_version"], SCHEMA_VERSION)
        self.assertEqual(row["experiment_id"], "trial-001")
        self.assertEqual(row["titration_type"], "strong_acid_strong_base")
        self.assertEqual(row["sample_concentration_M"], 0.1)
        self.assertAlmostEqual(row["theoretical_equivalence_volume_ml"], 20.0)
        self.assertEqual(row["chemistry_model"], "scientific_equilibrium_davies")
        self.assertEqual(row["constants_source_id"], "acid-001")
        self.assertEqual(row["constants_candidate_count"], 2)
        self.assertTrue(row["constants_lookup_ambiguous"])
        self.assertEqual(row["constants_confirmation_status"], "confirmed_by_user")
        self.assertEqual(row["constants_warning"], "Multiple candidates")
        self.assertAlmostEqual(row["selected_pka_value"], 4.76)
        self.assertEqual(row["activity_model"], "davies")
        self.assertEqual(row["ionic_strength_label"], "high_reliability")
        self.assertAlmostEqual(row["theoretical_equivalence_pH"], 7.0)
        self.assertAlmostEqual(row["indicator_endpoint_offset_ml"], 0.1)
        self.assertIn("standard concentration", row["standard_solution_uncertainty_note"])
        self.assertEqual(row["pump_mode"], "dry_run")
        self.assertEqual(row["pump_step_count"], 100)
        self.assertEqual(row["visible_R_mean"], 120.0)
        self.assertEqual(row["thermal_source"], "usb_palette")

    def test_includes_reference_label_and_prediction_placeholders(self):
        experiment = ExperimentConfig(
            experiment_id="trial-002",
            titration_type="weak_acid_weak_base",
            sample_name="CH3COOH",
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_name="NH3",
            titrant_concentration_m=0.1,
            titrant_valence=1,
        )

        row = build_collection_row(
            experiment=experiment,
            time_s=0.0,
            frame_id=0,
            injected_volume_ml=0.0,
        )

        self.assertEqual(row["reference_equivalence_volume_ml"], "")
        self.assertEqual(row["observed_color_endpoint_volume_ml"], "")
        self.assertEqual(row["predicted_equivalence_volume_ml"], "")
        self.assertNotIn("manual_label", row)

    def test_build_collection_row_adds_derived_ml_features_when_history_is_supplied(self):
        experiment = ExperimentConfig(
            experiment_id="trial",
            titration_type="weak_acid_strong_base",
            sample_name="acetic acid",
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_name="NaOH",
            titrant_concentration_m=0.1,
            titrant_valence=1,
        )
        history = [
            {"time_s": 0.0, "visible_H_mean": 350, "visible_color_delta": 0, "thermal_roi_avg": 22.0, "thermal_roi_delta": 0.0},
            {"time_s": 0.5, "visible_H_mean": 10, "visible_color_delta": 4, "thermal_roi_avg": 22.4, "thermal_roi_delta": 0.4},
        ]

        row = build_collection_row(
            experiment=experiment,
            time_s=1.5,
            frame_id=3,
            injected_volume_ml=1.5,
            visible_features={"visible_H_mean": 40, "visible_color_delta": 10},
            thermal_features={"thermal_roi_avg": 24.0, "thermal_roi_delta": 1.6, "thermal_calibrated": True},
            extra_fields={"sync_offset_ms": -12, "sync_quality": "good", "roi_state": "recording"},
            history_rows=history,
        )

        self.assertEqual(row["titration_is_weak_acid_strong_base"], 1.0)
        self.assertEqual(row["abs_sync_offset_ms"], 12.0)
        self.assertAlmostEqual(row["visible_H_baseline_delta"], 40.0, places=3)
        self.assertGreater(row["thermal_roi_avg_slope_c_per_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
