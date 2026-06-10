import tempfile
import unittest
from pathlib import Path

from tools import protocol_calibrated_equivalence as pce


class ProtocolCalibratedEquivalenceTests(unittest.TestCase):
    def test_current_runs_reproduce_nested_mape_under_5_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = pce.run(output_dir=Path(tmp) / "protocol", doc_path=None, svg_path=None)
        nested = next(row for row in summary["overall"] if row["dataset"] == "nested_protocol_calibrated_max_volume")
        self.assertEqual(nested["target_mape_under_5pct"], "yes")
        self.assertLessEqual(float(nested["mape_percent"]), 5.0)
        self.assertEqual(int(nested["run_count"]), 12)

    def test_protocol_model_is_explicitly_not_sensor_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "protocol"
            pce.run(output_dir=out, doc_path=None, svg_path=None)
            rows = (out / "protocol_calibrated_predictions.csv").read_text(encoding="utf-8-sig")
        self.assertIn("protocol_assisted_post_experiment", rows)
        self.assertIn("run_volume_max_ml", rows)


if __name__ == "__main__":
    unittest.main()
