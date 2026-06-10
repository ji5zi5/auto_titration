import unittest

import numpy as np

from auto_titrator.feature_history import FeatureHistory, FeatureSample


class FeatureHistoryTests(unittest.TestCase):
    def test_ring_buffer_keeps_recent_samples_and_full_history(self):
        history = FeatureHistory(max_recent=2)

        for frame_id in range(3):
            history.add(
                FeatureSample(
                    time_s=float(frame_id),
                    frame_id=frame_id,
                    injected_volume_ml=float(frame_id) * 0.5,
                    visible_features={"visible_color_delta": float(frame_id)},
                )
            )

        self.assertEqual([sample.frame_id for sample in history.recent_samples()], [1, 2])
        self.assertEqual([sample.frame_id for sample in history.full_history()], [0, 1, 2])
        self.assertEqual(history.latest().frame_id, 2)

    def test_serializable_rows_flatten_features_and_warnings(self):
        history = FeatureHistory(max_recent=5)
        history.add(
            FeatureSample(
                time_s=1.25,
                frame_id=7,
                injected_volume_ml=3.5,
                visible_features={"visible_color_delta": 12.0},
                thermal_features={"thermal_roi_avg": 24.5, "thermal_roi_std": 0.4},
                status_label="near_endpoint",
                status_confidence=0.75,
                source_quality="calibrated",
                warnings=("thermal ok",),
            )
        )

        row = history.to_serializable_rows()[0]

        self.assertEqual(row["time_s"], 1.25)
        self.assertEqual(row["frame_id"], 7)
        self.assertEqual(row["visible_color_delta"], 12.0)
        self.assertEqual(row["thermal_roi_avg"], 24.5)
        self.assertEqual(row["status_label"], "near_endpoint")
        self.assertEqual(row["status_confidence"], 0.75)
        self.assertEqual(row["source_quality"], "calibrated")
        self.assertEqual(row["warnings"], "thermal ok")

    def test_default_serialization_rejects_full_numpy_matrices(self):
        history = FeatureHistory(max_recent=5)
        history.add(
            FeatureSample(
                time_s=0.0,
                frame_id=0,
                injected_volume_ml=0.0,
                thermal_features={"temperature_matrix_c": np.zeros((2, 2), dtype=float)},
            )
        )

        with self.assertRaises(ValueError):
            history.to_serializable_rows()


if __name__ == "__main__":
    unittest.main()
