import unittest

import numpy as np

from auto_titrator.color_analysis import Roi
from auto_titrator.thermal_camera import HikmicroTemperatureMatrix
from auto_titrator.thermal_providers import MatrixReplayThermalProvider, NullThermalProvider, PaletteFrameProvider


class ThermalProviderTests(unittest.TestCase):
    def test_null_provider_reports_unavailable_without_temperature_matrix(self):
        packet = NullThermalProvider(reason="Mini2 not connected").read()

        self.assertIsNone(packet.temperature_matrix_c)
        self.assertFalse(packet.calibrated_temperature)
        self.assertIn("Mini2 not connected", "; ".join(packet.warnings))

    def test_matrix_replay_provider_returns_calibrated_matrix_and_roi_features(self):
        matrix = HikmicroTemperatureMatrix(
            values=np.array([[20.0, 22.0], [24.0, 26.0]], dtype=float),
            unit="섭씨",
            metadata={},
            source_path="fixture.csv",
        )
        provider = MatrixReplayThermalProvider(matrix)

        packet = provider.read()
        features = provider.extract_roi_features(Roi(0, 0, 2, 2))

        self.assertTrue(packet.calibrated_temperature)
        self.assertEqual(packet.source_name, "hikmicro_matrix_replay")
        self.assertEqual(features["thermal_source"], "hikmicro_matrix_replay")
        self.assertEqual(features["thermal_roi_avg"], 23.0)
        self.assertTrue(features["thermal_calibrated"])


    def test_matrix_replay_provider_does_not_calibrate_unknown_unit(self):
        matrix = HikmicroTemperatureMatrix(
            values=np.array([[68.0, 70.0]], dtype=float),
            unit="화씨",
            metadata={},
            source_path="fahrenheit.csv",
        )
        provider = MatrixReplayThermalProvider(matrix)

        packet = provider.read()
        features = provider.extract_roi_features(Roi(0, 0, 2, 1))

        self.assertIsNone(packet.temperature_matrix_c)
        self.assertFalse(packet.calibrated_temperature)
        self.assertTrue(packet.warnings)
        self.assertFalse(features["thermal_calibrated"])
        self.assertIn("not verified Celsius", features["warnings"])
        self.assertNotIn("thermal_roi_avg", features)

    def test_palette_frame_provider_is_uncalibrated_temperature(self):
        frame = np.full((2, 2, 3), [10, 20, 30], dtype=np.uint8)
        provider = PaletteFrameProvider(lambda: frame, source_name="usb_palette_uncalibrated")

        packet = provider.read()

        self.assertIs(packet.display_frame, frame)
        self.assertIsNone(packet.temperature_matrix_c)
        self.assertFalse(packet.calibrated_temperature)
        self.assertIn("uncalibrated", packet.source_name)


if __name__ == "__main__":
    unittest.main()
