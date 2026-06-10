import csv
import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator.evaluation import compute_error_metrics, write_metrics_json
from auto_titrator.plot_results import plot_error_comparison_svg


class EvaluationTests(unittest.TestCase):
    def test_compute_color_endpoint_error_vs_ml_prediction_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "experiment_id",
                        "reference_equivalence_volume_ml",
                        "observed_color_endpoint_volume_ml",
                        "predicted_equivalence_volume_ml",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "experiment_id": "a",
                            "reference_equivalence_volume_ml": 9.0,
                            "observed_color_endpoint_volume_ml": 10.0,
                            "predicted_equivalence_volume_ml": 9.2,
                        },
                        {
                            "experiment_id": "b",
                            "reference_equivalence_volume_ml": 8.0,
                            "observed_color_endpoint_volume_ml": 7.0,
                            "predicted_equivalence_volume_ml": 8.5,
                        },
                    ]
                )

            metrics = compute_error_metrics(csv_path)

        self.assertEqual(metrics["row_count"], 2)
        self.assertAlmostEqual(metrics["mean_abs_color_endpoint_error_ml"], 1.0)
        self.assertAlmostEqual(metrics["mean_abs_ml_prediction_error_ml"], 0.35)
        self.assertAlmostEqual(metrics["mean_abs_error_improvement_ml"], 0.65)

    def test_writes_metrics_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            json_path = Path(tmp) / "metrics.json"
            csv_path.write_text(
                "reference_equivalence_volume_ml,observed_color_endpoint_volume_ml,predicted_equivalence_volume_ml\n"
                "9,10,9.5\n",
                encoding="utf-8",
            )

            write_metrics_json(csv_path, json_path)
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["row_count"], 1)
        self.assertEqual(payload["color_endpoint_error_count"], 1)
        self.assertEqual(payload["ml_prediction_error_count"], 1)

    def test_plot_error_comparison_svg(self):
        metrics = {
            "mean_abs_color_endpoint_error_ml": 1.0,
            "mean_abs_ml_prediction_error_ml": 0.35,
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = plot_error_comparison_svg(metrics, Path(tmp) / "errors.svg")
            svg = output.read_text(encoding="utf-8")

        self.assertIn("<svg", svg)
        self.assertIn("Color endpoint", svg)
        self.assertIn("ML prediction", svg)


if __name__ == "__main__":
    unittest.main()
