import unittest
import tempfile
from pathlib import Path

import numpy as np

from auto_titrator.color_analysis import Roi
from auto_titrator.thermal_camera import HikmicroTemperatureMatrix, ThermalPaletteAnalyzer, load_hikmicro_temperature_csv


class ThermalPaletteAnalyzerTests(unittest.TestCase):
    def test_extracts_prefixed_palette_features(self):
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        frame[:, :] = np.array([0, 255, 0], dtype=np.uint8)

        features = ThermalPaletteAnalyzer().extract(frame, Roi(0, 0, 2, 2))

        self.assertEqual(features["thermal_R_mean"], 0.0)
        self.assertEqual(features["thermal_G_mean"], 255.0)
        self.assertEqual(features["thermal_B_mean"], 0.0)
        self.assertAlmostEqual(features["thermal_H_mean"], 120.0)
        self.assertEqual(features["thermal_source"], "usb_palette_uncalibrated")
        self.assertFalse(features["thermal_calibrated"])
        self.assertEqual(features["source_quality"], "palette_uncalibrated")
        self.assertIn("not calibrated Celsius", features["warnings"])


class HikmicroTemperatureMatrixTests(unittest.TestCase):
    def make_export_csv(self) -> bytes:
        text = (
            "파일 경로:,C:\\\\Users\\\\Public\\\\HIKMICRO Analyzer\\\\ExportedTempMatrix\\\\sample.csv,,,\n"
            "단위,섭씨,,,\n"
            "통계:,,평균:,25.0,\n"
            ",,분:,20.0,\n"
            ",,최대:,30.0,\n"
            "축 X/Y,0,1,2\n"
            "0,20.0,21.0,22.0\n"
            "1,23.0,24.0,25.0\n"
        )
        return text.encode("cp949")

    def test_loads_cp949_hikmicro_exported_temperature_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "HIKMICRO_sample.csv"
            path.write_bytes(self.make_export_csv())

            matrix = load_hikmicro_temperature_csv(path)

            self.assertIsInstance(matrix, HikmicroTemperatureMatrix)
            self.assertEqual(matrix.unit, "섭씨")
            self.assertEqual(matrix.values.shape, (2, 3))
            self.assertEqual(matrix.values[1, 2], 25.0)
            self.assertEqual(matrix.metadata["평균"], 25.0)

    def test_extracts_roi_temperature_stats_from_matrix(self):
        matrix = HikmicroTemperatureMatrix(
            values=np.array([[20.0, 22.0], [24.0, 26.0]], dtype=float),
            unit="섭씨",
            metadata={},
            source_path="sample.csv",
        )

        features = matrix.extract_roi(Roi(0, 0, 2, 2))

        self.assertEqual(features["thermal_source"], "hikmicro_export_csv")
        self.assertEqual(features["thermal_roi_min"], 20.0)
        self.assertEqual(features["thermal_roi_max"], 26.0)
        self.assertEqual(features["thermal_roi_avg"], 23.0)
        self.assertAlmostEqual(features["thermal_roi_std"], 2.23606797749979)
        self.assertTrue(features["thermal_calibrated"])


    def test_non_celsius_matrix_is_not_marked_calibrated(self):
        matrix = HikmicroTemperatureMatrix(
            values=np.array([[68.0, 70.0]], dtype=float),
            unit="화씨",
            metadata={},
            source_path="fahrenheit.csv",
        )

        features = matrix.extract_roi(Roi(0, 0, 2, 1))

        self.assertFalse(features["thermal_calibrated"])
        self.assertIn("not verified Celsius", features["warnings"])
        self.assertNotIn("thermal_roi_avg", features)
        self.assertNotIn("thermal_roi_max", features)

    def test_real_mini2_ir00001_export_fixture_if_present(self):
        path = Path("data/fixtures/mini2/IR_00001_이미지.csv")
        if not path.exists():
            self.skipTest("local Mini2 IR_00001 export fixture not present")

        matrix = load_hikmicro_temperature_csv(path)

        self.assertEqual(matrix.values.shape, (192, 256))
        self.assertAlmostEqual(float(matrix.values.min()), 22.2)
        self.assertAlmostEqual(float(matrix.values.max()), 33.9)
        self.assertAlmostEqual(float(matrix.values.mean()), 25.69256998697917)


if __name__ == "__main__":
    unittest.main()
