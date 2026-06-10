import unittest
from math import sqrt

import numpy as np

from auto_titrator.color_analysis import ColorFeatureExtractor, Roi


class ColorFeatureExtractorTests(unittest.TestCase):
    def test_extracts_rgb_hsv_means_from_roi(self):
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        frame[1:3, 1:3] = np.array([255, 0, 0], dtype=np.uint8)

        features = ColorFeatureExtractor().extract(frame, Roi(x=1, y=1, width=2, height=2))

        self.assertEqual(features["R_mean"], 255.0)
        self.assertEqual(features["G_mean"], 0.0)
        self.assertEqual(features["B_mean"], 0.0)
        self.assertAlmostEqual(features["H_mean"], 0.0)
        self.assertAlmostEqual(features["S_mean"], 1.0)
        self.assertAlmostEqual(features["V_mean"], 1.0)
        self.assertAlmostEqual(features["color_delta"], 0.0)
        self.assertAlmostEqual(features["H_delta"], 0.0)
        self.assertAlmostEqual(features["S_delta"], 0.0)
        self.assertAlmostEqual(features["V_delta"], 0.0)
        self.assertAlmostEqual(features["HSV_delta"], 0.0)

    def test_color_delta_compares_current_rgb_mean_to_previous(self):
        extractor = ColorFeatureExtractor()
        previous = {"R_mean": 10.0, "G_mean": 20.0, "B_mean": 30.0}
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        frame[:, :] = np.array([13, 24, 30], dtype=np.uint8)

        features = extractor.extract(frame, Roi(x=0, y=0, width=2, height=2), previous=previous)

        self.assertAlmostEqual(features["color_delta"], 5.0)

    def test_hsv_delta_uses_circular_hue_distance(self):
        extractor = ColorFeatureExtractor()
        previous = {
            "R_mean": 255.0,
            "G_mean": 0.0,
            "B_mean": 0.0,
            "H_mean": 359.0,
            "S_mean": 0.7,
            "V_mean": 0.8,
        }
        frame = np.zeros((2, 2, 3), dtype=np.uint8)
        frame[:, :] = np.array([255, 0, 0], dtype=np.uint8)

        features = extractor.extract(frame, Roi(x=0, y=0, width=2, height=2), previous=previous)

        self.assertAlmostEqual(features["H_delta"], 1.0)
        self.assertAlmostEqual(features["S_delta"], 0.3)
        self.assertAlmostEqual(features["V_delta"], 0.2)
        self.assertAlmostEqual(features["HSV_delta"], sqrt((1.0 / 180.0) ** 2 + 0.3**2 + 0.2**2), places=6)

    def test_rejects_roi_outside_frame(self):
        frame = np.zeros((3, 3, 3), dtype=np.uint8)

        with self.assertRaises(ValueError):
            ColorFeatureExtractor().extract(frame, Roi(x=2, y=2, width=3, height=3))


if __name__ == "__main__":
    unittest.main()
