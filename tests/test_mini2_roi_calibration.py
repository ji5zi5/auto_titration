import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import mini2_roi_calibration as calibration


class Mini2RoiCalibrationTests(unittest.TestCase):
    def make_raw_sequence(self):
        frames = []
        for base in (5000, 5400, 5800):
            full = np.zeros((344, 256), dtype="<u2")
            full[:192] = base
            full[48:53, 58:63] = base + 10
            frames.append(full.tobytes())
        return b"".join(frames)

    def test_extracts_roi_raw_stats_from_calibration_points(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "seq.raw"
            raw_path.write_bytes(self.make_raw_sequence())
            points_path = Path(temp) / "points.csv"
            points_path.write_text(
                "frame_id,label,x,y,radius,temp_c\n"
                "0,room,60,50,2,20\n"
                "1,warm,60,50,2,30\n",
                encoding="utf-8",
            )

            samples = calibration.extract_samples(raw_path, points_path)

            self.assertEqual(len(samples), 2)
            self.assertEqual(samples[0]["label"], "room")
            self.assertAlmostEqual(samples[0]["raw_mean"], 5010.0)
            self.assertEqual(samples[0]["pixel_count"], 25)

    def test_fits_affine_temperature_formula_from_roi_samples(self):
        samples = [
            {"raw_mean": 5010.0, "temp_c": 20.0, "label": "room"},
            {"raw_mean": 5410.0, "temp_c": 30.0, "label": "warm"},
            {"raw_mean": 5810.0, "temp_c": 40.0, "label": "hot"},
        ]

        model = calibration.fit_affine_model(samples)

        self.assertAlmostEqual(model["slope_c_per_raw"], 0.025)
        self.assertAlmostEqual(model["intercept_c"], -105.25)
        self.assertAlmostEqual(model["scale_raw_per_c"], 40.0)
        self.assertAlmostEqual(model["offset_raw"], 4210.0)

    def test_process_writes_samples_formula_and_template(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "seq.raw"
            raw_path.write_bytes(self.make_raw_sequence())
            points_path = Path(temp) / "points.csv"
            points_path.write_text(
                "frame_id,label,x,y,radius,temp_c\n"
                "0,room,60,50,2,20\n"
                "1,warm,60,50,2,30\n"
                "2,hot,60,50,2,40\n",
                encoding="utf-8",
            )
            out_dir = Path(temp) / "out"

            calibration.process(raw_path, points_path, out_dir)

            samples_path = out_dir / "roi_samples.csv"
            formula_path = out_dir / "roi_formula.json"
            self.assertTrue(samples_path.exists())
            self.assertTrue(formula_path.exists())
            with samples_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 3)
            formula = json.loads(formula_path.read_text(encoding="utf-8"))
            self.assertEqual(formula["sample_count"], 3)
            self.assertIn("not official SDK", formula["warning"])

    def test_missing_points_file_writes_template(self):
        with tempfile.TemporaryDirectory() as temp:
            points_path = Path(temp) / "missing.csv"

            calibration.write_template(points_path)

            text = points_path.read_text(encoding="utf-8")
            self.assertIn("frame_id,label,x,y,radius,temp_c", text)
            self.assertIn("room_reference", text)

    def test_roi_calibration_runner_remains_but_windows_launcher_is_retired(self):
        runner = Path("tools/run_mini2_roi_calibration_wsl.sh").read_text(encoding="utf-8")

        self.assertFalse(Path("launchers/windows/15_mini2_roi_calibration_wsl.bat").exists())
        self.assertIn("mini2_roi_calibration.py", runner)
        self.assertIn("POINTS_CSV", runner)


if __name__ == "__main__":
    unittest.main()
