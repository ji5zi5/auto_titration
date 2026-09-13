import unittest

from auto_titrator.ml_features import derive_ml_features, select_online_history_rows


class MlFeaturesTests(unittest.TestCase):
    def test_online_history_selection_preserves_full_feature_result(self):
        history = []
        for index in range(250):
            time_s = index * 0.04
            history.append(
                {
                    "time_s": time_s,
                    "visible_H_mean": 20.0 + index * 0.1,
                    "visible_S_mean": 0.3,
                    "visible_V_mean": 0.7,
                    "thermal_roi_avg": 25.0 + index * 0.01,
                    "thermal_roi_p95": 26.0 + index * 0.01,
                }
            )
        current = {
            "time_s": 10.0,
            "visible_H_mean": 45.0,
            "visible_S_mean": 0.31,
            "visible_V_mean": 0.71,
            "thermal_roi_avg": 27.5,
            "thermal_roi_p95": 28.5,
        }

        selected = select_online_history_rows(history, current)

        self.assertLess(len(selected), 60)
        self.assertEqual(derive_ml_features(selected, current), derive_ml_features(history, current))

    def test_derives_baseline_window_slope_and_quality_features(self):
        history = [
            {
                "time_s": 0.0,
                "visible_H_mean": 350.0,
                "visible_S_mean": 0.20,
                "visible_V_mean": 0.40,
                "visible_color_delta": 0.0,
                "visible_HSV_delta": 0.0,
                "thermal_roi_avg": 22.0,
                "thermal_roi_p95": 23.0,
                "thermal_roi_delta": 0.0,
                "thermal_raw_roi_p50": 5000,
                "thermal_raw_roi_p95": 5010,
                "thermal_raw_roi_delta": 0.0,
            },
            {
                "time_s": 0.5,
                "visible_H_mean": 10.0,
                "visible_S_mean": 0.30,
                "visible_V_mean": 0.50,
                "visible_color_delta": 4.0,
                "visible_HSV_delta": 0.2,
                "thermal_roi_avg": 22.4,
                "thermal_roi_p95": 23.4,
                "thermal_roi_delta": 0.4,
                "thermal_raw_roi_p50": 5020,
                "thermal_raw_roi_p95": 5030,
                "thermal_raw_roi_delta": 20,
            },
            {
                "time_s": 1.4,
                "visible_H_mean": 20.0,
                "visible_S_mean": 0.40,
                "visible_V_mean": 0.60,
                "visible_color_delta": 6.0,
                "visible_HSV_delta": 0.5,
                "thermal_roi_avg": 23.0,
                "thermal_roi_p95": 24.0,
                "thermal_roi_delta": 0.6,
                "thermal_raw_roi_p50": 5050,
                "thermal_raw_roi_p95": 5070,
                "thermal_raw_roi_delta": 30,
            },
        ]
        current = {
            "time_s": 2.0,
            "visible_H_mean": 40.0,
            "visible_S_mean": 0.70,
            "visible_V_mean": 0.90,
            "visible_color_delta": 12.0,
            "visible_HSV_delta": 0.9,
            "thermal_roi_avg": 24.2,
            "thermal_roi_p95": 25.5,
            "thermal_roi_delta": 1.2,
            "thermal_raw_roi_p50": 5100,
            "thermal_raw_roi_p95": 5150,
            "thermal_raw_roi_delta": 50,
            "sync_offset_ms": "-37.5",
            "sync_quality": "good",
            "thermal_calibrated": True,
            "roi_state": "recording",
            "source_quality": "mini2_uvc_raw_calibrated_roi_temperature",
            "titration_type": "weak_acid_strong_base",
        }

        features = derive_ml_features(history, current, window_s=1.0, baseline_s=1.0)

        # Hue baseline mean is circular mean of 350 and 10 => near 0; current 40 => +40 degrees.
        self.assertAlmostEqual(features["visible_H_baseline_delta"], 40.0, places=3)
        self.assertAlmostEqual(features["visible_S_baseline_delta"], 0.45, places=6)
        self.assertAlmostEqual(features["thermal_roi_avg_baseline_delta"], 2.0, places=6)
        self.assertAlmostEqual(features["thermal_roi_p95_baseline_delta"], 2.3, places=6)
        self.assertAlmostEqual(features["visible_color_delta_mean_1s"], 9.0, places=6)
        self.assertAlmostEqual(features["visible_color_delta_max_1s"], 12.0, places=6)
        self.assertAlmostEqual(features["thermal_roi_delta_mean_1s"], 0.9, places=6)
        self.assertAlmostEqual(features["thermal_roi_delta_max_1s"], 1.2, places=6)
        self.assertAlmostEqual(features["visible_H_slope_deg_per_s"], 33.333333, places=5)
        self.assertAlmostEqual(features["thermal_roi_avg_slope_c_per_s"], 2.0, places=6)
        self.assertEqual(features["abs_sync_offset_ms"], 37.5)
        self.assertEqual(features["titration_is_weak_acid_strong_base"], 1.0)
        self.assertEqual(features["titration_is_strong_acid_strong_base"], 0.0)
        self.assertEqual(features["valid_for_training"], 1.0)
        self.assertGreaterEqual(features["training_quality_score"], 0.95)

    def test_marks_low_quality_rows_when_sync_or_calibration_is_bad(self):
        features = derive_ml_features(
            [],
            {
                "time_s": 0.0,
                "sync_offset_ms": 150,
                "sync_quality": "bad",
                "thermal_calibrated": False,
                "roi_state": "draft",
                "source_quality": "mini2 unavailable",
                "warnings": "thermal unavailable",
            },
        )

        self.assertEqual(features["abs_sync_offset_ms"], 150.0)
        self.assertEqual(features["valid_for_training"], 0.0)
        self.assertLess(features["training_quality_score"], 0.5)


if __name__ == "__main__":
    unittest.main()
