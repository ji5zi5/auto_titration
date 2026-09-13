import unittest

from tools.compare_endpoint_baselines import (
    ColorSlopeConfig,
    FusionThresholdConfig,
    evaluate,
    metric_summary,
    predict_color_max_slope,
    predict_color_thermal_threshold,
)


def row(volume, hue, thermal):
    return {
        "titration_type": "",
        "injected_volume_ml": volume,
        "visible_R_mean": hue,
        "visible_G_mean": hue,
        "visible_B_mean": hue,
        "visible_H_mean": hue,
        "visible_S_mean": hue,
        "visible_V_mean": hue,
        "thermal_roi_avg": thermal,
    }


class EndpointBaselineComparisonTests(unittest.TestCase):
    def test_color_max_slope_finds_step_transition(self):
        rows = [
            row(index / 10.0, 10 if index < 8 else 90, 20)
            for index in range(16)
        ]
        config = ColorSlopeConfig(
            signal="hue",
            baseline_fraction=0.10,
            smoothing_ml=0.1,
            major_slope_fraction=1.0,
            selection="max",
        )

        predicted = predict_color_max_slope(rows, config)

        self.assertGreaterEqual(predicted, 0.7)
        self.assertLessEqual(predicted, 0.9)

    def test_threshold_requires_sustained_color_and_thermal_change(self):
        rows = [
            row(index / 10.0, 0 if index < 9 else 100, 20 if index < 9 else 22)
            for index in range(16)
        ]
        config = FusionThresholdConfig(
            baseline_fraction=0.10,
            smoothing_ml=0.1,
            color_threshold=0.80,
            fusion_threshold=0.70,
            color_weight=0.70,
            sustained_ml=0.3,
        )

        predicted = predict_color_thermal_threshold(rows, config)

        self.assertGreaterEqual(predicted, 0.8)
        self.assertLessEqual(predicted, 1.0)

    def test_threshold_ignores_short_spike(self):
        rows = []
        for index in range(20):
            changed = index == 4 or index >= 12
            rows.append(
                row(
                    index / 10.0,
                    100 if changed else 0,
                    22 if changed else 20,
                )
            )
        config = FusionThresholdConfig(
            baseline_fraction=0.10,
            smoothing_ml=0.1,
            color_threshold=0.80,
            fusion_threshold=0.70,
            color_weight=0.70,
            sustained_ml=0.3,
        )

        predicted = predict_color_thermal_threshold(rows, config)

        self.assertGreaterEqual(predicted, 1.1)
        self.assertLessEqual(predicted, 1.3)

    def test_development_fixture_metrics_are_reproducible(self):
        _, comparison = evaluate()
        by_method = {row["method"]: row for row in comparison}

        self.assertEqual(
            by_method["manual_titration_user_provided"]["mape_percent"],
            1.215278,
        )
        self.assertEqual(
            by_method["manual_titration_user_provided"]["mae_ml"],
            0.366667,
        )
        self.assertEqual(by_method["color_major_slope"]["mape_percent"], 4.673611)
        self.assertEqual(
            by_method["color_thermal_adaptive_threshold"]["mape_percent"],
            5.645833,
        )
        self.assertEqual(
            by_method["machine_learning_color"]["mape_percent"],
            1.552056,
        )
        self.assertEqual(
            by_method["machine_learning_thermal"]["mape_percent"],
            3.661547,
        )
        self.assertEqual(
            by_method["machine_learning_fusion"]["mape_percent"],
            1.524496,
        )
        self.assertEqual(
            by_method["machine_learning_fusion_with_volume"]["mape_percent"],
            1.271147,
        )

    def test_metric_summary_reports_mape_and_rates(self):
        rows = [
            {"absolute_error_ml": 1.0, "absolute_percentage_error": 2.0},
            {"absolute_error_ml": 2.0, "absolute_percentage_error": 4.0},
        ]

        result = metric_summary(rows)

        self.assertEqual(result["mae_ml"], 1.5)
        self.assertEqual(result["mape_percent"], 3.0)
        self.assertEqual(result["within_5pct_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
