import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from auto_titrator.live_app import (
    DEFAULT_OPERATIONAL_MODES,
    LatestSampleBuffer,
    classify_status,
    run_simulated_equivalence_analysis,
)
from auto_titrator.feature_history import FeatureSample


class LiveAppTests(unittest.TestCase):
    def test_operational_modes_include_required_fallbacks(self):
        self.assertIn("simulated", DEFAULT_OPERATIONAL_MODES)
        self.assertIn("recorded/replay", DEFAULT_OPERATIONAL_MODES)
        self.assertIn("live_color_only", DEFAULT_OPERATIONAL_MODES)
        self.assertIn("live_color_plus_palette", DEFAULT_OPERATIONAL_MODES)
        self.assertIn("live_color_plus_calibrated_thermal", DEFAULT_OPERATIONAL_MODES)

    def test_latest_sample_buffer_drops_stale_prediction_work(self):
        buffer = LatestSampleBuffer()
        buffer.push(FeatureSample(time_s=0.0, frame_id=0, injected_volume_ml=0.0))
        buffer.push(FeatureSample(time_s=1.0, frame_id=1, injected_volume_ml=1.0))

        latest = buffer.pop_latest()

        self.assertEqual(latest.frame_id, 1)
        self.assertIsNone(buffer.pop_latest())

    def test_classify_status_uses_color_delta_thresholds(self):
        before = classify_status(FeatureSample(time_s=0, frame_id=0, injected_volume_ml=0, visible_features={"visible_color_delta": 0.5}))
        near = classify_status(FeatureSample(time_s=1, frame_id=1, injected_volume_ml=1, visible_features={"visible_color_delta": 7.0}))
        endpoint = classify_status(FeatureSample(time_s=2, frame_id=2, injected_volume_ml=2, visible_features={"visible_color_delta": 15.0}))

        self.assertEqual(before[0], "before")
        self.assertEqual(near[0], "near_endpoint")
        self.assertEqual(endpoint[0], "endpoint")

    def test_classify_status_uses_canonical_thermal_color_delta(self):
        status, _confidence = classify_status(
            FeatureSample(
                time_s=0,
                frame_id=0,
                injected_volume_ml=0,
                thermal_features={"thermal_color_delta": 13.0},
            )
        )

        self.assertEqual(status, "endpoint")


    def test_classify_status_can_emit_overshoot_after_endpoint_seen(self):
        overshoot = classify_status(
            FeatureSample(time_s=3, frame_id=3, injected_volume_ml=3, visible_features={"visible_color_delta": 2.0}),
            endpoint_seen=True,
        )

        self.assertEqual(overshoot[0], "overshoot")

    def test_simulated_run_writes_final_result_without_full_matrix_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "result.json"
            result = run_simulated_equivalence_analysis(output)
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertAlmostEqual(result.estimated_equivalence_volume_ml, 9.0)
        self.assertIn("estimated_equivalence_time_s", payload)
        self.assertIn("feature_history", payload)
        self.assertNotIn("temperature_matrix_c", json.dumps(payload))
        self.assertTrue(payload["warnings"])

    def test_auto_titrator_main_can_run_simulated_analysis_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "main-simulated-result.json"
            completed = subprocess.run(
                [sys.executable, "-m", "auto_titrator.main", "--analyze-simulated", "--analysis-output", str(output)],
                text=True,
                capture_output=True,
            )

            payload = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {}

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(payload["estimated_equivalence_volume_ml"], 9.0)


if __name__ == "__main__":
    unittest.main()
