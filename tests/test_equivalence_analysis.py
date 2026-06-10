import unittest

from auto_titrator.equivalence_analysis import estimate_equivalence_point, interpolate_volume_at_time
from auto_titrator.feature_history import FeatureSample


def sample(time_s, color_delta=0.0, thermal_avg=None, label="before"):
    thermal = {}
    if thermal_avg is not None:
        thermal = {"thermal_roi_avg": thermal_avg, "thermal_calibrated": True}
    return FeatureSample(
        time_s=float(time_s),
        frame_id=int(time_s),
        injected_volume_ml=float(time_s),
        visible_features={"visible_color_delta": color_delta},
        thermal_features=thermal,
        status_label=label,
        status_confidence=0.8 if label != "before" else 0.3,
    )


class EquivalenceAnalysisTests(unittest.TestCase):
    def test_estimates_equivalence_from_color_and_thermal_feature_peak(self):
        samples = [sample(t, color_delta=1.0, thermal_avg=22.0 + t * 0.05) for t in range(13)]
        samples[8] = sample(8, color_delta=5.0, thermal_avg=23.0, label="near_endpoint")
        samples[9] = sample(9, color_delta=14.0, thermal_avg=24.4, label="endpoint")
        samples[10] = sample(10, color_delta=4.0, thermal_avg=24.6, label="overshoot")

        result = estimate_equivalence_point(samples, theoretical_equivalence_volume_ml=9.2)

        self.assertAlmostEqual(result.estimated_equivalence_time_s, 9.0)
        self.assertAlmostEqual(result.estimated_equivalence_volume_ml, 9.0)
        self.assertAlmostEqual(result.absolute_volume_error_ml, 0.2)
        self.assertGreater(result.confidence, 0.6)
        self.assertTrue(any("color" in item for item in result.evidence))
        self.assertTrue(any("thermal" in item for item in result.evidence))

    def test_missing_thermal_data_adds_warning_and_lowers_confidence(self):
        samples = [sample(t, color_delta=1.0, thermal_avg=None) for t in range(8)]
        samples[5] = sample(5, color_delta=12.0, thermal_avg=None, label="endpoint")

        result = estimate_equivalence_point(samples, theoretical_equivalence_volume_ml=5.0)

        self.assertAlmostEqual(result.estimated_equivalence_time_s, 5.0)
        self.assertLess(result.confidence, 0.9)
        self.assertTrue(any("thermal" in warning.lower() for warning in result.warnings))

    def test_interpolates_injected_volume_at_target_time(self):
        samples = [sample(0), sample(10)]
        samples[0].injected_volume_ml = 0.0
        samples[1].injected_volume_ml = 5.0

        self.assertAlmostEqual(interpolate_volume_at_time(samples, 4.0), 2.0)


if __name__ == "__main__":
    unittest.main()
