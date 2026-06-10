import csv
import tempfile
import unittest
from pathlib import Path

import run


class SimpleLauncherTests(unittest.TestCase):
    def test_quick_config_defaults_to_safe_visible_only_auto_roi(self):
        config = run.quick_config(visible_index=2, frames=5, visible_backend="msmf")

        self.assertEqual(config["visible_camera"]["device_index"], 2)
        self.assertEqual(config["visible_camera"]["backend"], "msmf")
        self.assertEqual(config["visible_camera"]["roi"], "auto")
        self.assertFalse(config["thermal_camera"]["enabled"])
        self.assertFalse(config["pump"]["enabled"])
        self.assertEqual(config["collection"]["max_frames"], 5)

    def test_quick_config_sets_mini2_backend_when_thermal_enabled(self):
        config = run.quick_config(thermal_index=1, thermal_backend="msmf")

        self.assertTrue(config["thermal_camera"]["enabled"])
        self.assertEqual(config["thermal_camera"]["device_index"], 1)
        self.assertEqual(config["thermal_camera"]["backend"], "msmf")

    def test_default_smoke_command_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "smoke.csv"

            exit_code = run.main_with_args(["smoke", "--output", str(output)])

            with output.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["experiment_id"], "smoke-test")

    def test_no_args_defaults_to_smoke(self):
        self.assertEqual(run.main_with_args([]), 0)
        Path("data/raw/smoke.csv").unlink(missing_ok=True)

    def test_simulated_analysis_command_writes_result_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "simulated-result.json"

            exit_code = run.main_with_args(["analyze-simulated", "--output", str(output)])

            payload = output.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("estimated_equivalence_volume_ml", payload)
        self.assertNotIn("temperature_matrix_c", payload)

    def test_ph_curve_command_exports_theoretical_curve_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "ph-curve.csv"

            exit_code = run.main_with_args(
                [
                    "ph-curve",
                    "--config",
                    "auto_titrator/config.yaml",
                    "--output",
                    str(output),
                    "--step-ml",
                    "10",
                    "--max-ml",
                    "20",
                ]
            )

            with output.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["regime"], "equivalence")
        self.assertIn("ph", rows[1])


if __name__ == "__main__":
    unittest.main()
