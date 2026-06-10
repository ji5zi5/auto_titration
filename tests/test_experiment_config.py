import unittest

from auto_titrator.chemistry import SUPPORTED_TITRATION_TYPES
from auto_titrator.experiment_config import ExperimentConfig


BASE_MAPPING = {
    "experiment_id": "trial-001",
    "sample_name": "HCl",
    "sample_concentration_M": 0.1,
    "sample_volume_ml": 20.0,
    "sample_valence": 1,
    "titrant_name": "NaOH",
    "titrant_concentration_M": 0.1,
    "titrant_valence": 1,
}


class ExperimentConfigTests(unittest.TestCase):
    def test_stores_metadata_and_computes_theoretical_equivalence_volume(self):
        experiment = ExperimentConfig(
            experiment_id="trial-001",
            titration_type="weak_acid_strong_base",
            sample_name="CH3COOH",
            sample_concentration_m=0.1,
            sample_volume_ml=20.0,
            sample_valence=1,
            titrant_name="NaOH",
            titrant_concentration_m=0.1,
            titrant_valence=1,
            ka=1.8e-5,
            constants_source="IUPAC Dissociation Constants high-confidence local CSV",
            constants_source_id="acid-001",
            constants_query="acetic acid",
            selected_pka_type="pKa",
            selected_pka_value=4.76,
            selected_pka_temperature_c=25.0,
            activity_model="davies",
            ionic_strength_m=0.05,
            ionic_strength_label="high_reliability",
            theoretical_equivalence_ph=8.72,
            indicator_transition_low_ph=8.2,
            indicator_transition_high_ph=10.0,
            indicator_endpoint_volume_ml=20.1,
            indicator_endpoint_offset_ml=0.1,
            indicator_endpoint_confidence="model_estimate",
        )

        self.assertEqual(experiment.experiment_id, "trial-001")
        self.assertEqual(experiment.titration_type, "weak_acid_strong_base")
        self.assertAlmostEqual(experiment.theoretical_equivalence_volume_ml, 20.0)
        self.assertEqual(experiment.constants_source_id, "acid-001")
        self.assertAlmostEqual(experiment.selected_pka_value, 4.76)
        self.assertEqual(experiment.ionic_strength_label, "high_reliability")
        self.assertAlmostEqual(experiment.indicator_endpoint_offset_ml, 0.1)

    def test_accepts_all_supported_titration_types_from_mapping(self):
        for titration_type in SUPPORTED_TITRATION_TYPES:
            with self.subTest(titration_type=titration_type):
                experiment = ExperimentConfig.from_mapping({**BASE_MAPPING, "titration_type": titration_type})
                self.assertEqual(experiment.titration_type, titration_type)

    def test_from_mapping_accepts_pythonic_or_yaml_style_concentration_keys(self):
        experiment = ExperimentConfig.from_mapping({**BASE_MAPPING, "titration_type": "strong_acid_strong_base"})

        self.assertAlmostEqual(experiment.sample_concentration_m, 0.1)
        self.assertAlmostEqual(experiment.titrant_concentration_m, 0.1)
        self.assertAlmostEqual(experiment.theoretical_equivalence_volume_ml, 20.0)

    def test_from_mapping_accepts_scientific_model_metadata(self):
        experiment = ExperimentConfig.from_mapping(
            {
                **BASE_MAPPING,
                "titration_type": "weak_acid_strong_base",
                "indicator": "phenolphthalein",
                "constants_source_id": "IUPAC-123",
                "constants_query": "acetic acid",
                "constants_candidate_count": "3",
                "constants_lookup_ambiguous": "true",
                "constants_confirmation_status": "confirmed_by_user",
                "constants_warning": "Multiple candidates",
                "selected_pka_type": "pKa",
                "selected_pka_value": "4.76",
                "selected_pka_temperature_C": "25",
                "ionic_strength_M": "0.05",
                "theoretical_equivalence_pH": "8.72",
                "indicator_transition_low_pH": "8.2",
                "indicator_transition_high_pH": "10.0",
                "indicator_endpoint_volume_ml": "20.12",
                "indicator_endpoint_offset_ml": "0.12",
                "standard_solution_uncertainty_note": "표준용액 농도는 사용자가 입력한 값",
            }
        )

        self.assertEqual(experiment.indicator, "phenolphthalein")
        self.assertEqual(experiment.constants_source_id, "IUPAC-123")
        self.assertEqual(experiment.constants_query, "acetic acid")
        self.assertEqual(experiment.constants_candidate_count, 3)
        self.assertTrue(experiment.constants_lookup_ambiguous)
        self.assertEqual(experiment.constants_confirmation_status, "confirmed_by_user")
        self.assertIn("Multiple", experiment.constants_warning)
        self.assertAlmostEqual(experiment.selected_pka_value, 4.76)
        self.assertAlmostEqual(experiment.ionic_strength_m, 0.05)
        self.assertAlmostEqual(experiment.theoretical_equivalence_ph, 8.72)
        self.assertAlmostEqual(experiment.indicator_transition_high_ph, 10.0)
        self.assertIn("사용자가 입력", experiment.standard_solution_uncertainty_note)

    def test_rejects_unsupported_titration_type(self):
        with self.assertRaises(ValueError):
            ExperimentConfig(
                experiment_id="trial-002",
                titration_type="unknown",
                sample_name="HCl",
                sample_concentration_m=0.1,
                sample_volume_ml=20.0,
                sample_valence=1,
                titrant_name="NaOH",
                titrant_concentration_m=0.1,
                titrant_valence=1,
            )


if __name__ == "__main__":
    unittest.main()
