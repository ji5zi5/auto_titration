import unittest

from auto_titrator.indicator_models import (
    INDICATOR_PRESETS,
    estimate_indicator_endpoint,
    get_indicator,
)


class IndicatorModelTests(unittest.TestCase):
    def test_presets_include_common_indicators(self):
        for key in ["phenolphthalein", "methyl_orange", "bromothymol_blue"]:
            with self.subTest(key=key):
                self.assertIn(key, INDICATOR_PRESETS)
                preset = get_indicator(key)
                self.assertLess(preset.transition_low_ph, preset.transition_high_ph)

    def test_estimates_endpoint_offset_for_increasing_curve(self):
        curve = [(8.0, 6.8), (9.0, 7.2), (10.0, 8.0), (11.0, 9.1), (12.0, 10.3)]
        result = estimate_indicator_endpoint(
            curve,
            indicator="phenolphthalein",
            equivalence_volume_ml=10.0,
        )

        self.assertEqual(result.indicator.key, "phenolphthalein")
        self.assertGreater(result.endpoint_volume_ml, 10.0)
        self.assertGreater(result.endpoint_equivalence_offset_ml, 0.0)
        self.assertEqual(result.confidence, "model_estimate")
        self.assertIn("model estimate/reference", result.warning)

    def test_estimates_endpoint_for_decreasing_curve(self):
        curve = [(8.0, 8.5), (9.0, 7.4), (10.0, 6.7), (11.0, 5.2), (12.0, 3.8)]
        result = estimate_indicator_endpoint(
            curve,
            indicator="bromothymol_blue",
            equivalence_volume_ml=10.0,
        )

        self.assertLess(result.endpoint_volume_ml, 11.5)
        self.assertIsNotNone(result.transition_start_volume_ml)
        self.assertIsNotNone(result.transition_end_volume_ml)

    def test_returns_low_confidence_when_curve_does_not_cross_range(self):
        curve = [(0.0, 2.0), (1.0, 2.5), (2.0, 2.9)]
        result = estimate_indicator_endpoint(
            curve,
            indicator="phenolphthalein",
            equivalence_volume_ml=1.0,
        )

        self.assertEqual(result.confidence, "low")
        self.assertIsNone(result.endpoint_volume_ml)
        self.assertIn("does not clearly cross", result.warning)


if __name__ == "__main__":
    unittest.main()
