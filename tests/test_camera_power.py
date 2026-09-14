import unittest

from auto_titrator.camera_power import CameraPowerControl


class CameraPowerTests(unittest.TestCase):
    def test_failed_start_cleans_partial_capture_and_remains_unavailable(self):
        calls = []
        def fail_start():
            calls.append("open")
            raise RuntimeError("no cameras")
        control = CameraPowerControl(start=fail_start, stop=lambda: calls.append("release"))
        control.request(False, recording=False)
        control.reconcile()
        control.request(True, recording=False)
        control.reconcile()
        self.assertEqual(calls, ["release", "open", "release"])
        self.assertEqual(control.status()["state"], "error")
        self.assertFalse(control.status()["enabled"])

    def test_off_is_queued_then_releases_and_on_reopens(self):
        calls = []
        control = CameraPowerControl(start=lambda: calls.append("open"), stop=lambda: calls.append("release"))
        self.assertTrue(control.can_record())
        self.assertEqual(control.request(False, recording=False)["state"], "stopping")
        self.assertEqual(calls, [])
        self.assertFalse(control.can_record())
        control.reconcile()
        self.assertEqual(calls, ["release"])
        self.assertFalse(control.status()["enabled"])
        self.assertFalse(control.reconcile())
        control.request(True, recording=False)
        self.assertFalse(control.can_record())
        control.reconcile()
        self.assertTrue(control.can_record())
        self.assertEqual(calls, ["release", "open"])

    def test_recording_invalid_and_conflicting_changes_do_not_execute(self):
        control = CameraPowerControl(start=lambda: None, stop=lambda: None)
        with self.assertRaisesRegex(ValueError, "recording"):
            control.request(False, recording=True)
        self.assertTrue(control.can_record())
        with self.assertRaisesRegex(ValueError, "boolean"):
            control.request("false", recording=False)
        control.request(False, recording=False)
        control.request(False, recording=False)
        with self.assertRaisesRegex(ValueError, "in progress"):
            control.request(True, recording=False)

    def test_failed_stop_is_not_reported_as_off_or_allowed_to_reopen(self):
        def fail():
            raise RuntimeError("device still closing")
        control = CameraPowerControl(start=lambda: None, stop=fail)
        control.request(False, recording=False)
        control.reconcile()
        self.assertEqual(control.status()["state"], "error")
        self.assertTrue(control.status()["enabled"])
        self.assertFalse(control.can_record())
        with self.assertRaisesRegex(ValueError, "finish stopping"):
            control.request(True, recording=False)
        self.assertEqual(control.request(False, recording=False)["state"], "stopping")


class CameraPowerHttpTests(unittest.TestCase):
    def test_cleared_preview_is_not_reported_ready_from_old_sequence_number(self):
        from tools import windows_live_collect as live
        state = live.LiveStreamState()
        state.publish_visible(b"old-frame")
        self.assertTrue(state.snapshot_health()["visible_stream_ready"])
        state.clear_previews()
        self.assertFalse(state.snapshot_health()["visible_stream_ready"])
        self.assertFalse(state.snapshot_health()["thermal_stream_ready"])
        self.assertIsNone(state.wait_jpeg("visible", last_sequence=0, timeout_s=0))
        state.publish_visible(b"new-frame")
        self.assertTrue(state.snapshot_health()["visible_stream_ready"])

    def test_run_closes_real_capture_threads_while_off_and_reopens_fresh_sources(self):
        from argparse import Namespace
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        import csv
        import time
        from tools import windows_live_collect as live
        from tests.test_windows_live_collect import FakeMini2Reader, FakeVisibleCamera

        readers, cameras, off_counts = [], [], []
        class Reader(FakeMini2Reader):
            def read_frame_parts(self):
                time.sleep(0.02)
                return super().read_frame_parts()
        class Visible(FakeVisibleCamera):
            def read_rgb(self):
                time.sleep(0.02)
                return super().read_rgb()
        def open_thermal(args):
            source = Reader()
            readers.append(source)
            return source, 1
        def open_visible(args, **kwargs):
            source = Visible()
            cameras.append(source)
            return source, 0
        class ScriptedPower(CameraPowerControl):
            step = 0
            def reconcile(self):
                self.step += 1
                if self.step == 2:
                    self.request(False, recording=False)
                if self.step == 5:
                    self.request(True, recording=False)
                changed = super().reconcile()
                if self.status()["state"] == "off":
                    off_counts.append((readers[0].count, cameras[0].count))
                return changed
        actual_server = live.start_live_stream_server
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "power.csv"
            args = Namespace(frames=8, frame_rate_hz=25.0, mini2_index="auto",
                mini2_backend="AUTO", mini2_width=256, mini2_height=344, mini2_fourcc="YUY2",
                no_visible=False, visible_index="auto", visible_roi="0,0,40,40",
                thermal_roi=live.Roi(0, 0, 16, 16), thermal_processing="raw",
                output=str(output), print_every=0, max_sync_offset_ms=40,
                live_stream_port=1, auto_roi_worker=0, roi_auto_detect="off")
            with patch.object(live, "open_mini2_capture", side_effect=open_thermal), \
                 patch.object(live, "open_visible_camera", side_effect=open_visible), \
                 patch.object(live, "CameraPowerControl", ScriptedPower), \
                 patch.object(live, "start_live_stream_server", side_effect=lambda host, port, state, **kw: actual_server(host, 0, state, **kw)), \
                 patch.object(live, "build_pump_serial_bridge_from_args", return_value=None), \
                 patch.object(live, "load_endpoint_prediction_model", return_value=None), \
                 patch.object(live, "load_typewise_live_prediction_model", return_value=None), \
                 patch.object(live, "load_live_prediction_model", return_value=None), \
                 patch.object(live, "classify_status", wraps=live.classify_status) as classify:
                live.run(args)
                self.assertEqual(classify.call_count, 5, "OFF iterations still ran feature analysis")
            with output.open() as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 0, "idle capture wrote recording rows")
        self.assertEqual(len(off_counts), 3)
        self.assertEqual(len(set(off_counts)), 1, "capture reads continued while OFF")
        self.assertEqual(len(readers), 2)
        self.assertEqual(len(cameras), 2)
        self.assertTrue(all(source.released for source in readers + cameras))

    def test_mini2_probe_never_opens_active_visible_index(self):
        import argparse
        from tools import windows_live_collect as live
        attempts = []
        class Reader:
            def __init__(self, **kwargs):
                attempts.append(kwargs["index"])
            def read_frame_parts(self):
                return None
        args = argparse.Namespace(mini2_index="auto", mini2_max_index=3,
            mini2_backend="DSHOW", mini2_skip_indices=[0], mini2_width=256,
            mini2_height=344, frame_rate_hz=25, mini2_fourcc="YUY2")
        _, index = live.open_mini2_capture(args, capture_factory=Reader)
        self.assertEqual(index, 1)
        self.assertEqual(attempts, [1])
        args.mini2_index = 0
        with self.assertRaisesRegex(ValueError, "active visible"):
            live.open_mini2_capture(args, capture_factory=Reader)
        self.assertEqual(attempts, [1])

    def test_http_power_is_recording_fenced_and_start_waits_for_on(self):
        import json
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError
        from tools import windows_live_collect as live

        events = []
        power = CameraPowerControl(start=lambda: events.append("open"), stop=lambda: events.append("release"))
        roi = live.RoiSelectionState()
        server = live.start_live_stream_server("127.0.0.1", 0, live.LiveStreamState(), roi_state=roi)
        server.server.camera_power = power
        port = server.server.server_address[1]
        def post(path, data):
            req = Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
            try:
                with urlopen(req, timeout=2) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.load(exc)
        try:
            self.assertEqual(post("/api/camera-power", {"enabled": "false"})[0], 409)
            roi.roi_state = "recording"
            self.assertEqual(post("/api/camera-power", {"enabled": False})[0], 409)
            self.assertEqual(events, [])
            roi.roi_state = "setup"
            from types import SimpleNamespace
            server.server.csv_buffer = SimpleNamespace(status=lambda: {"recording": False, "finalizing": True})
            self.assertEqual(post("/api/camera-power", {"enabled": False})[0], 409)
            server.server.csv_buffer = None
            code, data = post("/api/camera-power", {"enabled": False})
            self.assertEqual(code, 202)
            self.assertEqual(data["camera_power"]["state"], "stopping")
            self.assertEqual(events, [])
            self.assertEqual(post("/api/csv/start", {})[0], 409)
            power.reconcile()
            self.assertEqual(events, ["release"])
            self.assertEqual(post("/api/csv/start", {})[0], 409)
            with urlopen(f"http://127.0.0.1:{port}/api/collector-health", timeout=2) as response:
                self.assertEqual(json.load(response)["camera_power"]["state"], "off")
            self.assertEqual(post("/api/camera-power", {"enabled": True})[0], 202)
            power.reconcile()
            self.assertTrue(power.can_record())
        finally:
            server.close()
