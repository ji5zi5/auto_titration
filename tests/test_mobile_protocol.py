import unittest

from auto_titrator.mobile_protocol import (
    MOBILE_FRAME_SCHEMA_VERSION,
    MobileProtocolError,
    assess_expected_frame_count,
    estimate_clock_sync,
    generate_fake_mobile_frames,
    mobile_payload_to_csv_row,
    validate_mobile_feature_frame,
)


class MobileProtocolTests(unittest.TestCase):
    def _base_payload(self):
        return {
            "schema_version": MOBILE_FRAME_SCHEMA_VERSION,
            "source_platform": "android",
            "device_id": "phone-01",
            "run_id": "run-a",
            "frame_id": 7,
            "phone_monotonic_ns": 1_250_000_000,
            "phone_epoch_s": 2000.25,
            "clock_offset_ms": 12.5,
            "clock_jitter_ms": 3.0,
            "visible": {
                "frame_width": 640,
                "frame_height": 480,
                "roi": {"x": 10, "y": 20, "width": 120, "height": 80, "shape": "mask"},
                "features": {
                    "R_mean": 101.2,
                    "G_mean": 88.5,
                    "B_mean": 70.25,
                    "H_mean": 35.0,
                    "S_mean": 0.4,
                    "V_mean": 0.5,
                    "H_delta": 2.0,
                    "S_delta": 0.02,
                    "V_delta": 0.01,
                    "HSV_delta": 0.03,
                    "color_delta": 4.5,
                },
            },
            "thermal": {
                "frame_width": 256,
                "frame_height": 192,
                "calibrated": False,
                "conversion_model": "android_uvc_raw_unverified",
                "roi": {"x": 11, "y": 12, "width": 40, "height": 30},
                "raw_roi": {"avg": 5000.0, "min": 4900, "max": 5200, "p50": 5012, "p95": 5190},
                "raw_matrix": {"min": 4800, "max": 5300, "mean": 5020.5, "p95": 5250},
                "celsius_roi": {"avg": 24.0, "max": 27.0},
            },
        }

    def test_validates_required_mobile_frame_fields(self):
        normalized = validate_mobile_feature_frame(self._base_payload())

        self.assertEqual(normalized["schema_version"], MOBILE_FRAME_SCHEMA_VERSION)
        self.assertEqual(normalized["source_platform"], "android")
        self.assertEqual(normalized["frame_id"], 7)

    def test_rejects_invalid_roi_dimensions(self):
        payload = self._base_payload()
        payload["visible"]["roi"]["x"] = 600

        with self.assertRaisesRegex(MobileProtocolError, "visible ROI must fit"):
            validate_mobile_feature_frame(payload)

    def test_maps_visible_and_mobile_provenance_to_csv_row(self):
        row = mobile_payload_to_csv_row(self._base_payload(), server_received_epoch_s=2000.27)

        self.assertEqual(row["mobile_source_platform"], "android")
        self.assertEqual(row["mobile_device_id"], "phone-01")
        self.assertEqual(row["mobile_run_id"], "run-a")
        self.assertEqual(row["frame_id"], 7)
        self.assertEqual(row["time_s"], 1.25)
        self.assertEqual(row["visible_R_mean"], 101.2)
        self.assertEqual(row["visible_roi_x"], 10)
        self.assertEqual(row["visible_roi_shape"], "mask")
        self.assertEqual(row["mobile_server_received_epoch_s"], 2000.27)
        self.assertEqual(row["sync_offset_ms"], 12.5)
        self.assertEqual(row["sync_quality"], "good")

    def test_uncalibrated_thermal_payload_keeps_celsius_fields_blank(self):
        row = mobile_payload_to_csv_row(self._base_payload(), server_received_epoch_s=2000.27)

        self.assertFalse(row["thermal_calibrated"])
        self.assertEqual(row["thermal_conversion_model"], "android_uvc_raw_unverified")
        self.assertEqual(row["thermal_raw_roi_avg"], 5000.0)
        self.assertEqual(row["thermal_raw_roi_p50"], 5012.0)
        self.assertEqual(row["thermal_raw_p95"], 5250.0)
        self.assertNotIn("thermal_roi_avg", row)
        self.assertNotIn("thermal_roi_max", row)

    def test_calibrated_thermal_payload_may_emit_celsius_fields(self):
        payload = self._base_payload()
        payload["thermal"]["calibrated"] = True
        payload["thermal"]["conversion_model"] = "hikmicro_android_sdk"
        payload["thermal"]["celsius_roi"] = {"avg": 23.5, "min": 21.0, "max": 26.0, "p95": 25.8}
        payload["thermal"]["celsius_matrix"] = {"avg": 23.0, "min": 20.5, "max": 27.2}

        row = mobile_payload_to_csv_row(payload, server_received_epoch_s=2000.27)

        self.assertTrue(row["thermal_calibrated"])
        self.assertEqual(row["thermal_roi_avg"], 23.5)
        self.assertEqual(row["thermal_roi_p95"], 25.8)
        self.assertEqual(row["thermal_matrix_max"], 27.2)

    def test_clock_sync_uses_lowest_rtt_sample_and_reports_jitter(self):
        result = estimate_clock_sync(
            [
                # server clock is 30 ms ahead; 25 ms one-way network delay.
                {"client_send_epoch_s": 10.0, "server_receive_epoch_s": 10.055, "server_reply_epoch_s": 10.056, "client_receive_epoch_s": 10.051},
                # noisier 35 ms offset sample with higher round-trip time.
                {"client_send_epoch_s": 20.0, "server_receive_epoch_s": 20.075, "server_reply_epoch_s": 20.076, "client_receive_epoch_s": 20.081},
                # 31 ms offset sample with medium round-trip time.
                {"client_send_epoch_s": 30.0, "server_receive_epoch_s": 30.071, "server_reply_epoch_s": 30.073, "client_receive_epoch_s": 30.082},
            ]
        )

        self.assertAlmostEqual(result.offset_ms, 30.0, places=3)
        self.assertGreater(result.jitter_ms, 0.0)
        self.assertEqual(result.sample_count, 3)
        self.assertEqual(result.quality, "good")

    def test_fake_mobile_generator_produces_25hz_training_payloads(self):
        frames = list(generate_fake_mobile_frames(duration_s=30.0, fps=25.0, device_id="fake-phone", run_id="trial"))

        self.assertEqual(len(frames), 750)
        self.assertEqual(frames[-1]["frame_id"], 749)
        accepted = assess_expected_frame_count(actual_count=675, duration_s=30.0, fps=25.0, min_fraction=0.9)
        rejected = assess_expected_frame_count(actual_count=674, duration_s=30.0, fps=25.0, min_fraction=0.9)
        self.assertTrue(accepted.ok)
        self.assertFalse(rejected.ok)


if __name__ == "__main__":
    unittest.main()
