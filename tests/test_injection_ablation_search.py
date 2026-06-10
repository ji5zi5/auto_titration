import csv
import tempfile
import unittest
from pathlib import Path

from tools import injection_ablation_search as ias


class InjectionAblationSearchTests(unittest.TestCase):
    def test_current_data_separates_no_volume_failure_from_protocol_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ablation"
            summary = ias.run(output_dir=out)
            self.assertTrue((out / "protocol_calibrated_reference" / "summary.json").exists())
            self.assertFalse((out / "doc.md").exists())
            self.assertFalse((out / "plot.svg").exists())
        best_sensor = summary["best"]["best_sensor_no_volume"]
        best_protocol = summary["best"]["best_protocol_final_volume"]
        self.assertFalse(summary["claim"]["no_injection_volume_under_5pct"])
        self.assertGreater(float(best_sensor["mape_percent"]), 5.0)
        self.assertTrue(summary["claim"]["protocol_assisted_diagnostic_under_5pct"])
        self.assertTrue(summary["claim"]["protocol_assisted_nested_reference_under_5pct"])
        self.assertEqual(summary["claim"]["recommended_report_metric"], "nested_protocol_calibrated_max_volume")
        self.assertLessEqual(float(best_protocol["mape_percent"]), 1.0)
        self.assertIn("posthoc model search", summary["claim"]["diagnostic_best_model_warning"])
        self.assertIn("final max injected volume", summary["claim"]["strict_warning"])

    def test_output_rows_label_scope_and_do_not_put_volume_in_sensor_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ablation"
            ias.run(output_dir=out)
            with (out / "selected_predictions.csv").open(encoding="utf-8-sig") as fh:
                rows = list(csv.DictReader(fh))
        self.assertTrue(rows)
        sensor_rows = [row for row in rows if row["mode"] in {"sensor_no_volume", "sensor_type_no_volume"}]
        protocol_rows = [row for row in rows if row["mode"].startswith("max_volume")]
        self.assertTrue(sensor_rows)
        self.assertTrue(protocol_rows)
        self.assertTrue(all(row["run_volume_max_ml"] == "excluded" for row in sensor_rows))
        self.assertTrue(all("no_injection_volume" in row["claim_scope"] for row in sensor_rows))
        self.assertTrue(all("protocol_assisted" in row["claim_scope"] for row in protocol_rows))
        self.assertTrue(all(row["diagnostic_only"] == "yes" for row in protocol_rows))
        self.assertTrue(all("posthoc_model_search" in row["model_search_scope"] for row in protocol_rows))
        self.assertTrue(all(row["row_count"] == "excluded" for row in rows))

    def test_sensor_column_filter_rejects_obvious_leakage_and_protocol_fields(self):
        self.assertTrue(ias._is_sensor_column("visible_H_mean"))
        self.assertTrue(ias._is_sensor_column("thermal_roi_avg"))
        self.assertFalse(ias._is_sensor_column("injected_volume_ml"))
        self.assertFalse(ias._is_sensor_column("theoretical_equivalence_volume_ml"))
        self.assertFalse(ias._is_sensor_column("sample_concentration_M"))
        self.assertFalse(ias._is_sensor_column("thermal_roi_x"))


if __name__ == "__main__":
    unittest.main()
