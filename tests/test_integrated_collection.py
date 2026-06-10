import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np
import yaml

from auto_titrator.main import _pump_state_for_row, run_collection, run_dry_run_smoke


class FakeCamera:
    def __init__(self, rgb):
        self.rgb = np.array(rgb, dtype=np.uint8)
        self.released = False

    def read_rgb(self):
        return self.rgb

    def release(self):
        self.released = True


class FakePumpStateProvider:
    def __init__(self):
        self.stopped = False
        self.run_rates = []

    def run_rate(self, ml_per_s):
        self.run_rates.append(ml_per_s)

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return {
            "pump_mode": "dry_run",
            "pump_state": "running",
            "pump_step_count": 50,
            "pump_run_rate_ml_per_s": 0.0,
            "pump_calibrated_ml_per_step": 0.005,
            "pump_calibrated_steps_per_ml": 200.0,
            "injected_volume_ml": 0.25,
        }


class IntegratedCollectionTests(unittest.TestCase):
    def test_run_collection_writes_experiment_camera_and_pump_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "experiment": {
                            "experiment_id": "trial-001",
                            "titration_type": "strong_acid_strong_base",
                            "sample_name": "HCl",
                            "sample_concentration_M": 0.1,
                            "sample_volume_ml": 10.0,
                            "sample_valence": 1,
                            "titrant_name": "NaOH",
                            "titrant_concentration_M": 0.1,
                            "titrant_valence": 1,
                            "indicator": "phenolphthalein",
                        },
                        "visible_camera": {
                            "device_index": 0,
                            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
                        },
                        "thermal_camera": {
                            "enabled": True,
                            "device_index": 1,
                            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
                        },
                        "collection": {"sample_interval_s": 0, "max_frames": 1},
                        "output": {"directory": str(output_dir), "filename": "run.csv"},
                    }
                ),
                encoding="utf-8",
            )
            cameras = {
                "visible_camera": FakeCamera([[[10, 20, 30], [10, 20, 30]], [[10, 20, 30], [10, 20, 30]]]),
                "thermal_camera": FakeCamera([[[100, 80, 20], [100, 80, 20]], [[100, 80, 20], [100, 80, 20]]]),
            }

            def camera_factory(config, section, name):
                return cameras[section]

            output_path = run_collection(
                config_path,
                camera_factory=camera_factory,
                pump_state_provider=FakePumpStateProvider(),
                sleep=lambda _: None,
            )

            with output_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["experiment_id"], "trial-001")
        self.assertEqual(rows[0]["titration_type"], "strong_acid_strong_base")
        self.assertEqual(rows[0]["theoretical_equivalence_volume_ml"], "10.0")
        self.assertEqual(rows[0]["pump_mode"], "dry_run")
        self.assertEqual(rows[0]["pump_state"], "running")
        self.assertEqual(rows[0]["injected_volume_ml"], "0.25")
        self.assertEqual(rows[0]["visible_R_mean"], "10.0")
        self.assertEqual(rows[0]["thermal_source"], "usb_palette_uncalibrated")
        self.assertEqual(rows[0]["thermal_calibrated"], "False")
        self.assertEqual(rows[0]["source_quality"], "palette_uncalibrated")
        self.assertIn("not calibrated Celsius", rows[0]["warnings"])
        self.assertTrue(cameras["visible_camera"].released)
        self.assertTrue(cameras["thermal_camera"].released)

    def test_run_collection_supports_auto_roi_for_quick_camera_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "experiment": {
                            "experiment_id": "auto-roi",
                            "titration_type": "strong_acid_strong_base",
                            "sample_name": "water",
                            "sample_concentration_M": 0.1,
                            "sample_volume_ml": 10.0,
                            "sample_valence": 1,
                            "titrant_name": "water",
                            "titrant_concentration_M": 0.1,
                            "titrant_valence": 1,
                        },
                        "visible_camera": {"device_index": 0, "roi": "auto"},
                        "thermal_camera": {"enabled": True, "device_index": 1, "roi": "auto"},
                        "collection": {"sample_interval_s": 0, "max_frames": 1},
                        "output": {"directory": str(output_dir), "filename": "auto.csv"},
                    }
                ),
                encoding="utf-8",
            )
            cameras = {
                "visible_camera": FakeCamera(np.full((4, 4, 3), [40, 50, 60], dtype=np.uint8)),
                "thermal_camera": FakeCamera(np.full((4, 4, 3), [90, 80, 70], dtype=np.uint8)),
            }

            output_path = run_collection(
                config_path,
                camera_factory=lambda config, section, name: cameras[section],
                sleep=lambda _: None,
            )

            with output_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(rows[0]["visible_R_mean"], "40.0")
        self.assertEqual(rows[0]["thermal_R_mean"], "90.0")
        self.assertEqual(rows[0]["thermal_source"], "usb_palette_uncalibrated")
        self.assertEqual(rows[0]["thermal_calibrated"], "False")
        self.assertIn("not calibrated Celsius", rows[0]["warnings"])

    def test_run_collection_does_not_command_or_stop_pump_state_provider_on_camera_failure(self):
        class FailingCamera(FakeCamera):
            def read_rgb(self):
                raise RuntimeError("camera unplugged")

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "experiment": {
                            "experiment_id": "failure-test",
                            "titration_type": "strong_acid_strong_base",
                            "sample_name": "HCl",
                            "sample_concentration_M": 0.1,
                            "sample_volume_ml": 10.0,
                            "sample_valence": 1,
                            "titrant_name": "NaOH",
                            "titrant_concentration_M": 0.1,
                            "titrant_valence": 1,
                        },
                        "visible_camera": {
                            "device_index": 0,
                            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
                        },
                        "thermal_camera": {"enabled": False},
                        "pump": {"run_rate_ml_per_s": 0.02},
                        "collection": {"sample_interval_s": 0, "max_frames": 1},
                        "output": {"directory": str(Path(tmp) / "out"), "filename": "failure.csv"},
                    }
                ),
                encoding="utf-8",
            )
            pump = FakePumpStateProvider()
            camera = FailingCamera([[[10, 20, 30], [10, 20, 30]], [[10, 20, 30], [10, 20, 30]]])

            with self.assertRaises(RuntimeError):
                run_collection(
                    config_path,
                    camera_factory=lambda config, section, name: camera,
                    pump_state_provider=pump,
                    sleep=lambda _: None,
                )

        self.assertEqual(pump.run_rates, [])
        self.assertFalse(pump.stopped)
        self.assertTrue(camera.released)

    def test_run_collection_ignores_start_rate_for_status_only_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "out"
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "experiment": {
                            "experiment_id": "start-failure",
                            "titration_type": "strong_acid_strong_base",
                            "sample_name": "HCl",
                            "sample_concentration_M": 0.1,
                            "sample_volume_ml": 10.0,
                            "sample_valence": 1,
                            "titrant_name": "NaOH",
                            "titrant_concentration_M": 0.1,
                            "titrant_valence": 1,
                        },
                        "visible_camera": {
                            "device_index": 0,
                            "roi": {"x": 0, "y": 0, "width": 2, "height": 2},
                        },
                        "thermal_camera": {"enabled": False},
                        "pump": {"run_rate_ml_per_s": 0.02},
                        "collection": {"sample_interval_s": 0, "max_frames": 1},
                        "output": {"directory": str(output_dir), "filename": "status-only.csv"},
                    }
                ),
                encoding="utf-8",
            )
            camera = FakeCamera([[[10, 20, 30], [10, 20, 30]], [[10, 20, 30], [10, 20, 30]]])
            pump = FakePumpStateProvider()

            output_path = run_collection(
                config_path,
                camera_factory=lambda config, section, name: camera,
                pump_state_provider=pump,
                sleep=lambda _: None,
            )

            with output_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(len(rows), 1)
        self.assertEqual(pump.run_rates, [])
        self.assertFalse(pump.stopped)
        self.assertTrue(camera.released)

    def test_dry_run_smoke_writes_csv_without_real_cameras_or_pump(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = run_dry_run_smoke(Path(tmp) / "smoke.csv")

            with output_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["experiment_id"], "smoke-test")
        self.assertEqual(rows[0]["pump_mode"], "estimated")
        self.assertEqual(rows[0]["pump_state"], "not_connected")
        self.assertEqual(rows[0]["visible_R_mean"], "120.0")
        self.assertEqual(rows[0]["thermal_source"], "usb_palette_uncalibrated")
        self.assertEqual(rows[0]["thermal_calibrated"], "False")
        self.assertIn("not calibrated Celsius", rows[0]["warnings"])

    def test_pump_state_estimates_volume_during_continuous_run_rate(self):
        class RunningPumpStateProvider(FakePumpStateProvider):
            def snapshot(self):
                return {
                    "pump_mode": "manual_snapshot",
                    "pump_state": "running",
                    "pump_run_rate_ml_per_s": 0.05,
                    "injected_volume_ml": 0.05,
                }

        pump = RunningPumpStateProvider()

        state = _pump_state_for_row(
            pump_state_provider=pump,
            elapsed_s=2.0,
            estimated_ml_per_second=0.0,
        )

        self.assertEqual(state["pump_state"], "running")
        self.assertEqual(state["pump_run_rate_ml_per_s"], 0.05)
        self.assertAlmostEqual(state["injected_volume_ml"], 0.15)


if __name__ == "__main__":
    unittest.main()
