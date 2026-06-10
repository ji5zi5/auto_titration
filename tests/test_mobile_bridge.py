import csv
import io
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from auto_titrator.mobile_protocol import MOBILE_FRAME_SCHEMA_VERSION, generate_fake_mobile_frames
from auto_titrator.mobile_bridge import MobileBridge, MobileBridgeError
from tools import windows_live_collect


class MobileBridgeTests(unittest.TestCase):
    def test_pairing_token_required_before_ingest(self):
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/mobile.csv"))
        bridge = MobileBridge(csv_buffer=csv_buffer, token_ttl_s=60.0)
        csv_buffer.start_recording(started_epoch_s=1000.0, started_monotonic_s=10.0)
        frame = next(generate_fake_mobile_frames(duration_s=0.04, fps=25.0))

        with self.assertRaisesRegex(MobileBridgeError, "pairing token"):
            bridge.ingest(frame, token="wrong", server_received_epoch_s=1000.04, now_monotonic_s=10.04)

    def test_ingest_adds_mobile_frame_to_live_csv_buffer(self):
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/mobile.csv"))
        bridge = MobileBridge(csv_buffer=csv_buffer, token_ttl_s=60.0)
        pair = bridge.create_pairing(now_epoch_s=1000.0)
        csv_buffer.start_recording(started_epoch_s=1000.0, started_monotonic_s=10.0)
        frame = next(generate_fake_mobile_frames(duration_s=0.04, fps=25.0, device_id="phone", run_id="trial"))

        result = bridge.ingest(frame, token=pair["token"], server_received_epoch_s=1000.04, now_monotonic_s=10.04)

        self.assertTrue(result["ok"])
        self.assertEqual(result["mobile"]["source"], "android_mobile")
        self.assertEqual(result["csv"]["row_count"], 1)
        body = csv_buffer.to_csv_bytes().decode("utf-8-sig")
        row = next(csv.DictReader(io.StringIO(body)))
        self.assertEqual(row["mobile_source_platform"], "android")
        self.assertEqual(row["mobile_device_id"], "phone")
        self.assertEqual(row["thermal_calibrated"], "False")
        self.assertIn("thermal_raw_roi_avg", row)
        self.assertNotIn("thermal_roi_avg", row)

    def test_status_reports_stale_mobile_source(self):
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/mobile.csv"))
        bridge = MobileBridge(csv_buffer=csv_buffer, stale_after_s=2.0)
        pair = bridge.create_pairing(now_epoch_s=1000.0)
        csv_buffer.start_recording(started_epoch_s=1000.0, started_monotonic_s=10.0)
        frame = next(generate_fake_mobile_frames(duration_s=0.04, fps=25.0))
        bridge.ingest(frame, token=pair["token"], server_received_epoch_s=1000.04, now_monotonic_s=10.04)

        fresh = bridge.status(now_epoch_s=1001.0)
        stale = bridge.status(now_epoch_s=1005.0)

        self.assertEqual(fresh["mobile"]["state"], "streaming")
        self.assertEqual(stale["mobile"]["state"], "stale")

    def test_live_stream_server_exposes_mobile_pair_status_and_ingest(self):
        live_state = windows_live_collect.LiveStreamState()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            csv_buffer=csv_buffer,
            enable_mobile_bridge=True,
        )
        try:
            port = handle.server.server_address[1]
            pair_request = Request(
                f"http://127.0.0.1:{port}/api/mobile/pair",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            pair = json.loads(urlopen(pair_request, timeout=1.0).read().decode("utf-8"))
            token = pair["mobile"]["token"]
            csv_buffer.start_recording(started_epoch_s=1000.0, started_monotonic_s=10.0)
            frame = next(generate_fake_mobile_frames(duration_s=0.04, fps=25.0, device_id="phone"))
            ingest_request = Request(
                f"http://127.0.0.1:{port}/api/mobile/ingest",
                data=json.dumps({"token": token, "frame": frame}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            ingest = json.loads(urlopen(ingest_request, timeout=1.0).read().decode("utf-8"))
            status = json.loads(urlopen(f"http://127.0.0.1:{port}/api/mobile/status", timeout=1.0).read().decode("utf-8"))
            with self.assertRaises(HTTPError) as ctx:
                bad_request = Request(
                    f"http://127.0.0.1:{port}/api/mobile/ingest",
                    data=json.dumps({"token": "wrong", "frame": frame}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urlopen(bad_request, timeout=1.0)
        finally:
            handle.close()

        self.assertTrue(ingest["ok"])
        self.assertEqual(ingest["csv"]["row_count"], 1)
        self.assertEqual(status["mobile"]["source"], "android_mobile")
        self.assertEqual(ctx.exception.code, 403)

    def test_live_stream_server_enables_mobile_bridge_by_default_when_csv_buffer_present(self):
        live_state = windows_live_collect.LiveStreamState()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            csv_buffer=csv_buffer,
        )
        try:
            port = handle.server.server_address[1]
            pair_request = Request(
                f"http://127.0.0.1:{port}/api/mobile/pair",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            pair = json.loads(urlopen(pair_request, timeout=1.0).read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(pair["ok"])
        self.assertIn("token", pair["mobile"])


if __name__ == "__main__":
    unittest.main()
