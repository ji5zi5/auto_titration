import unittest
import csv
import tempfile
from pathlib import Path

from auto_titrator import chemistry


class ChemistryModuleTests(unittest.TestCase):
    def test_module_exposes_supported_titration_types(self):
        self.assertEqual(
            chemistry.SUPPORTED_TITRATION_TYPES,
            (
                "strong_acid_strong_base",
                "weak_acid_strong_base",
                "strong_acid_weak_base",
                "weak_acid_weak_base",
            ),
        )

    def test_calculates_one_to_one_equivalence_volume(self):
        volume = chemistry.calculate_equivalence_volume_ml(
            sample_concentration_m=0.1,
            sample_volume_ml=20.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_valence=1,
        )

        self.assertAlmostEqual(volume, 20.0)

    def test_calculates_non_one_to_one_equivalence_volume(self):
        volume = chemistry.calculate_equivalence_volume_ml(
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=2,
            titrant_concentration_m=0.2,
            titrant_valence=1,
        )

        self.assertAlmostEqual(volume, 10.0)

    def test_calculates_unknown_sample_concentration_from_equivalence_volume(self):
        concentration = chemistry.calculate_unknown_sample_concentration_m(
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_volume_ml=9.2,
            titrant_valence=1,
        )

        self.assertAlmostEqual(concentration, 0.092)

    def test_calculates_unknown_titrant_concentration_from_equivalence_volume(self):
        concentration = chemistry.calculate_unknown_titrant_concentration_m(
            sample_concentration_m=0.1,
            sample_volume_ml=20.0,
            sample_valence=2,
            titrant_volume_ml=10.0,
            titrant_valence=1,
        )

        self.assertAlmostEqual(concentration, 0.4)

    def test_rejects_non_positive_inputs(self):
        with self.assertRaises(ValueError):
            chemistry.calculate_equivalence_volume_ml(
                sample_concentration_m=0.0,
                sample_volume_ml=20.0,
                sample_valence=1,
                titrant_concentration_m=0.1,
                titrant_valence=1,
            )

        with self.assertRaises(ValueError):
            chemistry.calculate_equivalence_volume_ml(
                sample_concentration_m=0.1,
                sample_volume_ml=20.0,
                sample_valence=1,
                titrant_concentration_m=0.1,
                titrant_valence=0,
            )

        with self.assertRaises(ValueError):
            chemistry.calculate_unknown_sample_concentration_m(
                sample_volume_ml=0.0,
                sample_valence=1,
                titrant_concentration_m=0.1,
                titrant_volume_ml=9.2,
                titrant_valence=1,
            )

        with self.assertRaises(ValueError):
            chemistry.calculate_unknown_titrant_concentration_m(
                sample_concentration_m=0.1,
                sample_volume_ml=20.0,
                sample_valence=1,
                titrant_volume_ml=-1.0,
                titrant_valence=1,
            )

class ScientificChemistryModelTests(unittest.TestCase):
    def test_strong_electrolytes_are_model_metadata_not_pka(self):
        hcl = chemistry.get_strong_electrolyte("HCl")
        naoh = chemistry.get_strong_electrolyte("sodium hydroxide")

        self.assertEqual(hcl.kind, "strong_acid")
        self.assertEqual(naoh.kind, "strong_base")
        self.assertIsNone(hcl.pka)
        self.assertEqual(hcl.source, "strong_electrolyte_model")
        self.assertIn("near-complete dissociation", hcl.assumption)

    def test_davies_activity_coefficient_and_ionic_strength_warnings(self):
        gamma = chemistry.davies_activity_coefficient(charge=1, ionic_strength_m=0.2)
        self.assertGreater(gamma, 0.0)
        self.assertLess(gamma, 1.0)

        self.assertEqual(chemistry.classify_ionic_strength(0.05).label, "high_reliability")
        self.assertEqual(chemistry.classify_ionic_strength(0.2).label, "usable")
        self.assertEqual(chemistry.classify_ionic_strength(0.4).label, "caution")
        self.assertEqual(chemistry.classify_ionic_strength(0.8).label, "outside_davies_range")

    def test_unknown_concentration_result_is_structured_equivalent_balance(self):
        result = chemistry.calculate_unknown_sample_concentration_result(
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_volume_ml=9.2,
            titrant_valence=1,
            titration_type="weak_acid_strong_base",
        )

        self.assertAlmostEqual(result.concentration_m, 0.092)
        self.assertEqual(result.basis, "stoichiometric_equivalent_capacity")
        self.assertEqual(result.selected_equivalence_step, 1)
        self.assertIn("does not redefine", " ".join(result.warnings))

    def test_theoretical_result_covers_four_titration_classes(self):
        cases = {
            "strong_acid_strong_base": 7.0,
            "weak_acid_strong_base": 8.0,
            "strong_acid_weak_base": 6.0,
            "weak_acid_weak_base": 7.0,
        }
        for titration_type, threshold in cases.items():
            with self.subTest(titration_type=titration_type):
                result = chemistry.calculate_theoretical_titration_result(
                    sample_concentration_m=0.1,
                    sample_volume_ml=10.0,
                    sample_valence=1,
                    titrant_concentration_m=0.1,
                    titrant_valence=1,
                    titration_type=titration_type,
                    sample_pka=4.76,
                    titrant_pkb=4.75,
                )
                self.assertAlmostEqual(result.equivalence_volume_ml, 10.0)
                self.assertIn(result.titration_type, chemistry.SUPPORTED_TITRATION_TYPES)
                self.assertGreaterEqual(result.ionic_strength_m, 0.0)
                if titration_type == "weak_acid_strong_base":
                    self.assertGreater(result.expected_equivalence_ph, threshold)
                elif titration_type == "strong_acid_weak_base":
                    self.assertLess(result.expected_equivalence_ph, threshold)
                elif titration_type == "weak_acid_weak_base":
                    self.assertIn("shallow", " ".join(result.warnings))
                else:
                    self.assertAlmostEqual(result.expected_equivalence_ph, threshold, delta=0.2)

    def test_missing_weak_species_constants_are_reported_as_placeholder_estimates(self):
        result = chemistry.calculate_theoretical_titration_result(
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_valence=1,
            titration_type="weak_acid_strong_base",
        )

        self.assertIn("sample_pka missing", " ".join(result.warnings))

    def test_generates_strong_acid_strong_base_theoretical_ph_curve(self):
        curve = chemistry.generate_theoretical_ph_curve(
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_valence=1,
            titration_type="strong_acid_strong_base",
            step_volume_ml=10.0,
            max_titrant_volume_ml=20.0,
        )

        self.assertEqual([point.titrant_volume_ml for point in curve], [0.0, 10.0, 20.0])
        self.assertAlmostEqual(curve[0].ph, 1.0, delta=0.02)
        self.assertAlmostEqual(curve[1].ph, 7.0, delta=0.02)
        self.assertGreater(curve[2].ph, 12.0)
        self.assertEqual(curve[1].regime, "equivalence")

    def test_weak_acid_strong_base_curve_uses_pka_and_exports_csv(self):
        curve = chemistry.generate_theoretical_ph_curve(
            sample_concentration_m=0.1,
            sample_volume_ml=10.0,
            sample_valence=1,
            titrant_concentration_m=0.1,
            titrant_valence=1,
            titration_type="weak_acid_strong_base",
            sample_pka=4.76,
            step_volume_ml=5.0,
            max_titrant_volume_ml=10.0,
        )

        self.assertAlmostEqual(curve[1].ph, 4.76, delta=0.03)
        self.assertGreater(curve[2].ph, 8.0)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ph-curve.csv"
            chemistry.write_theoretical_ph_curve_csv(curve, output)
            with output.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(rows[0]["titrant_volume_ml"], "0.000000")
        self.assertIn("ph", rows[0])
        self.assertEqual(rows[1]["regime"], "buffer")


if __name__ == "__main__":
    unittest.main()
