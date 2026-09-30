import csv
import io
import json
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from argparse import Namespace
from pathlib import Path
from unittest import mock

import numpy as np

from auto_titrator.color_analysis import Roi
from auto_titrator.mini2_live import MINI2_IR_HEIGHT, MINI2_MATRIX_SHAPE, MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH, Mini2RawFrameParts
from tools import windows_live_collect


def rgb_frame(red):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[..., 0] = red
    frame[..., 1] = 20
    frame[..., 2] = 30
    return frame




class FakeAbcSerial:
    def __init__(self, responses=None):
        self.writes = []
        self.closed = False
        self.responses = list(responses or [])

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        pass

    def readline(self):
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.closed = True


def acknowledged_test_pump_firmware(command, state):
    """Return exact guard/run acknowledgements for server-level safety tests."""

    if command.startswith("G "):
        timeout_ms = int(command.split()[1])
        state["guard_timeout_ms"] = timeout_ms
        return f"GUARD ARMED {timeout_ms}"
    if command in {"a", "b"}:
        timeout_ms = state.get("guard_timeout_ms")
        return {"firmware_ack": f"PUMP RUNNING {command} {timeout_ms}"}
    if command == "c":
        state["guard_timeout_ms"] = None
        return {"firmware_ack": "PUMP STOPPED COMMAND"}
    raise AssertionError(f"unexpected pump command: {command!r}")


class FakeOfficialConverter:
    model_name = "fake_official_mtprocess_int"
    calibrated = True
    calibration_source = "fake_ir.jpeg"

    def convert_with_addline(self, raw_matrix, addline_tag1):
        return raw_matrix.astype(np.float64) * 0.01 - 28.0

    def close(self):
        self.closed = True


class ZeroOfficialConverter:
    model_name = "zero_official_mtprocess_int"
    calibrated = True
    calibration_source = "fake_ir.jpeg"

    def convert_values_with_addline(self, raw_values, addline_tag1):
        return np.zeros_like(np.asarray(raw_values, dtype=np.float64))


class NonFiniteOfficialConverter:
    model_name = "nan_official_mtprocess_int"
    calibrated = True
    calibration_source = "fake_ir.jpeg"

    def convert_values_with_addline(self, raw_values, addline_tag1):
        return np.full_like(np.asarray(raw_values, dtype=np.float64), np.nan)


class RaisingOfficialConverter:
    model_name = "raising_official_mtprocess_int"
    calibrated = True
    calibration_source = "fake_ir.jpeg"

    def convert_values_with_addline(self, raw_values, addline_tag1):
        raise RuntimeError("MT_Process failed during frame")

    def convert_with_addline(self, raw_matrix, addline_tag1):
        raise RuntimeError("MT_Process failed during full frame")


class FakeMini2Reader:
    def __init__(self):
        self.released = False
        self.count = 0

    def read_frame_parts(self):
        full = np.zeros((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), dtype="<u2")
        full[:MINI2_IR_HEIGHT, :] = 5000 + self.count
        full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :] = np.arange(512, dtype=np.uint16).reshape(2, 256)
        self.count += 1
        return Mini2RawFrameParts(
            raw_matrix=full[:MINI2_IR_HEIGHT, :].copy(),
            addline_tag1=full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :].tobytes(),
            full_frame_u16=full,
        )

    def release(self):
        self.released = True


class FakeVisibleCamera:
    def __init__(self):
        self.released = False
        self.count = 0

    def read_rgb(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        frame[..., 0] = 10 + self.count
        frame[..., 1] = 20
        frame[..., 2] = 30
        self.count += 1
        return frame

    def release(self):
        self.released = True


class ShortVisibleCamera:
    def __init__(self):
        self.count = 0
        self.released = False

    def read_rgb(self):
        if self.count >= 2:
            raise RuntimeError("stop")
        frame = rgb_frame(20 + self.count)
        self.count += 1
        return frame

    def release(self):
        self.released = True


class DelayedSecondVisibleCamera:
    def __init__(self):
        self.count = 0
        self.released = False

    def read_rgb(self):
        if self.count == 1:
            time.sleep(0.02)
        if self.count >= 2:
            raise RuntimeError("stop")
        frame = rgb_frame(30 + self.count)
        self.count += 1
        return frame

    def release(self):
        self.released = True


class FastMini2Reader(FakeMini2Reader):
    def read_frame_parts(self):
        time.sleep(0.001)
        return super().read_frame_parts()


class MaskCandidateVisibleCamera(FakeVisibleCamera):
    def read_rgb(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        yy, xx = np.ogrid[:120, :160]
        mask = (xx - 80) ** 2 + (yy - 60) ** 2 <= 25**2
        frame[mask] = [210, 210, 210]
        self.count += 1
        return frame


class MaskCandidateMini2Reader(FakeMini2Reader):
    def read_frame_parts(self):
        full = np.full((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), 5000 + self.count, dtype="<u2")
        yy, xx = np.ogrid[:MINI2_IR_HEIGHT, :MINI2_UVC_WIDTH]
        mask = (xx - 150) ** 2 + (yy - 85) ** 2 <= 28**2
        full[:MINI2_IR_HEIGHT, :][mask] = 5400 + self.count
        full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :] = np.arange(512, dtype=np.uint16).reshape(2, 256)
        self.count += 1
        return Mini2RawFrameParts(
            raw_matrix=full[:MINI2_IR_HEIGHT, :].copy(),
            addline_tag1=full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :].tobytes(),
            full_frame_u16=full,
        )


class FakeYoloBoxes:
    def __init__(self, *, xyxy, conf, cls):
        self.xyxy = np.asarray(xyxy, dtype=np.float64)
        self.conf = np.asarray(conf, dtype=np.float64)
        self.cls = np.asarray(cls, dtype=np.float64)


class FakeYoloMasks:
    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float64)


class FakeYoloResult:
    def __init__(self, *, boxes, masks=None, names=None):
        self.boxes = boxes
        self.masks = masks
        self.names = names or {0: "cup", 1: "person", 2: "bottle"}


class FakeYoloModel:
    def __init__(self, results):
        self._results = results
        self.calls = []
        self.names = {0: "cup", 1: "person", 2: "bottle"}

    def predict(self, source, **kwargs):
        self.calls.append((source, kwargs))
        return self._results


class SlowFakeYoloModel(FakeYoloModel):
    def __init__(self, results, *, delay_s=0.05):
        super().__init__(results)
        self.delay_s = delay_s

    def predict(self, source, **kwargs):
        time.sleep(self.delay_s)
        return super().predict(source, **kwargs)


def fake_cup_yolo_model(*, shape=(120, 160), center=(80, 60), radius=18, confidence=0.82):
    h, w = shape
    yy, xx = np.ogrid[:h, :w]
    cx, cy = center
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
    return FakeYoloModel(
        [
            FakeYoloResult(
                boxes=FakeYoloBoxes(xyxy=[[cx - radius, cy - radius, cx + radius, cy + radius]], conf=[confidence], cls=[0]),
                masks=FakeYoloMasks([mask]),
            )
        ]
    )


class WindowsLiveCollectTests(unittest.TestCase):
    def test_collector_instance_lock_rejects_concurrent_second_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "collector.lock"
            first = windows_live_collect.CollectorInstanceLock(path)
            second = windows_live_collect.CollectorInstanceLock(path)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    second.acquire()
            finally:
                first.release()

            second.acquire()
            second.release()

    def test_auto_mini2_index_finds_first_valid_raw_stream(self):
        attempts = []
        released = []

        class BadReader:
            def __init__(self, index):
                self.index = index

            def read_frame_parts(self):
                raise RuntimeError(f"not Mini2 raw stream: {self.index}")

            def release(self):
                released.append(self.index)

        def factory(**kwargs):
            index = kwargs["index"]
            attempts.append(index)
            if index == 2:
                return FakeMini2Reader()
            return BadReader(index)

        args = Namespace(
            mini2_index="auto",
            mini2_max_index=4,
            mini2_backend="MSMF",
            mini2_width=MINI2_UVC_WIDTH,
            mini2_height=MINI2_UVC_HEIGHT,
            frame_rate_hz=25.0,
            mini2_fourcc="YUY2",
        )

        reader, index = windows_live_collect.open_mini2_capture(args, capture_factory=factory)
        reader.release()

        self.assertEqual(index, 2)
        self.assertEqual(attempts, [0, 1, 2])
        self.assertEqual(released, [0, 1])

    def test_auto_mini2_backend_auto_tries_candidate_backends(self):
        attempts = []

        class BadReader:
            def read_frame_parts(self):
                raise RuntimeError("not raw")

            def release(self):
                pass

        def factory(**kwargs):
            attempts.append((kwargs["index"], kwargs["backend"]))
            if kwargs["index"] == 1 and kwargs["backend"] == "ANY":
                return FakeMini2Reader()
            return BadReader()

        args = Namespace(
            mini2_index="auto",
            mini2_max_index=3,
            mini2_backend="AUTO",
            mini2_width=MINI2_UVC_WIDTH,
            mini2_height=MINI2_UVC_HEIGHT,
            frame_rate_hz=25.0,
            mini2_fourcc="YUY2",
        )

        reader, index = windows_live_collect.open_mini2_capture(args, capture_factory=factory)
        reader.release()

        self.assertEqual(index, 1)
        self.assertEqual(args.mini2_backend, "ANY")
        self.assertIn((0, "MSMF"), attempts)
        self.assertIn((0, "ANY"), attempts)
        self.assertIn((1, "ANY"), attempts)

    def test_windows_live_collect_launcher_uses_auto_mini2_index_by_default(self):
        launcher = Path("launchers/windows/20_windows_live_collect.bat").read_text(encoding="utf-8")

        self.assertIn('set "MINI2_INDEX=auto"', launcher)
        self.assertIn('set "MINI2_BACKEND=AUTO"', launcher)
        self.assertIn('set "ALLOW_MINI2_MISSING=1"', launcher)
        self.assertIn('set "MINI2_RETRY_INTERVAL_S=3"', launcher)
        self.assertIn('set "VISIBLE_INDEX=auto"', launcher)
        self.assertIn('set "VISIBLE_BACKEND=DSHOW"', launcher)
        self.assertIn('set "VISIBLE_WIDTH=320"', launcher)
        self.assertIn('set "VISIBLE_HEIGHT=240"', launcher)
        self.assertIn('set "THERMAL_PROCESSING=roi"', launcher)
        self.assertIn('set "THERMAL_ROTATION_DEGREES=180"', launcher)
        self.assertIn('set "STREAM_EVERY=0"', launcher)
        self.assertIn('set "PREVIEW_EVERY=0"', launcher)
        self.assertIn('set "LIVE_STREAM_PORT=8766"', launcher)
        self.assertIn('set "LIVE_STREAM_JPEG_QUALITY=60"', launcher)
        self.assertIn('set "ROI_CLICK_ENABLED=1"', launcher)

    def test_default_legacy_json_model_is_disabled(self):
        self.assertEqual(windows_live_collect.DEFAULT_LIVE_ML_MODEL, "")

    def test_live_prediction_model_rejects_theory_leakage_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "leaky-model.json"
            model_path.write_text(
                json.dumps(
                    {
                        "model_type": "linear_regression_v1",
                        "feature_columns": ["sample_concentration_M", "visible_color_delta"],
                        "target_column": "theoretical_equivalence_volume_ml",
                        "bias": 0.0,
                        "weights": [200.0, 0.1],
                    }
                ),
                encoding="utf-8",
            )

            model = windows_live_collect.load_live_prediction_model(model_path)

        self.assertIsNone(model)

    def test_live_prediction_model_accepts_sensor_only_json_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "sensor-model.json"
            model_path.write_text(
                json.dumps(
                    {
                        "model_type": "linear_regression_v1",
                        "feature_columns": ["visible_color_delta", "thermal_roi_avg"],
                        "target_column": "reference_equivalence_volume_ml",
                        "bias": 1.0,
                        "weights": [2.0, 0.01],
                    }
                ),
                encoding="utf-8",
            )

            model = windows_live_collect.load_live_prediction_model(model_path)

        self.assertIsNotNone(model)
        self.assertEqual(model["feature_columns"], ["visible_color_delta", "thermal_roi_avg"])

    def test_main_allows_roi_processing_to_fallback_when_converter_files_are_missing(self):
        seen = {}

        def fake_run(args):
            seen["thermal_processing"] = args.thermal_processing
            seen["metadata_jpeg"] = args.metadata_jpeg
            seen["dll_dir"] = args.dll_dir

        old_run = windows_live_collect.run
        windows_live_collect.run = fake_run
        try:
            result = windows_live_collect.main(
                [
                    "--frames",
                    "1",
                    "--thermal-processing",
                    "roi",
                    "--metadata-jpeg",
                    "missing-metadata.jpeg",
                    "--dll-dir",
                    "missing-dll-dir",
                ]
            )
        finally:
            windows_live_collect.run = old_run

        self.assertEqual(result, 0)
        self.assertEqual(seen["thermal_processing"], "roi")
        self.assertEqual(seen["metadata_jpeg"], "missing-metadata.jpeg")
        self.assertEqual(seen["dll_dir"], "missing-dll-dir")

        launcher = Path("launchers/windows/20_windows_live_collect.bat").read_text(encoding="utf-8")
        app_launcher = Path("launchers/windows/21_open_dashboard_server.bat").read_text(encoding="utf-8")
        self.assertIn('set "ROI_LINK_MODE=anchor"', launcher)
        self.assertIn('set "ROI_AUTO_DETECT=off"', launcher)
        self.assertIn('set "VISIBLE_ROI_DETECTOR=yolo"', launcher)
        self.assertIn('set "YOLO_MODEL=yolo11n-seg.pt"', launcher)
        self.assertIn('set "AUTO_INSTALL_YOLO=0"', launcher)
        self.assertIn('set "AUTO_INSTALL_YOLO=0"', app_launcher)
        self.assertIn("--visible-roi-detector %VISIBLE_ROI_DETECTOR%", launcher)
        self.assertIn("--yolo-model \"%YOLO_MODEL%\"", launcher)
        self.assertIn('set "YOLO_MIN_INTERVAL_MS=200"', launcher)
        self.assertIn('set "YOLO_SUCCESS_INTERVAL_MS=200"', launcher)
        self.assertIn('set "YOLO_INPUT_SIZE=256"', launcher)
        self.assertIn("--yolo-min-interval-ms %YOLO_MIN_INTERVAL_MS%", launcher)
        self.assertIn("--yolo-success-interval-ms %YOLO_SUCCESS_INTERVAL_MS%", launcher)
        self.assertIn("--yolo-input-size %YOLO_INPUT_SIZE%", launcher)
        self.assertIn('set "ROI_AUTO_MIN_CONFIDENCE=0.25"', launcher)
        self.assertIn('set "ROI_AUTO_EVERY=5"', launcher)
        self.assertIn('set "AUTO_ROI_WORKER=0"', launcher)
        self.assertIn('set "MAX_SYNC_OFFSET_MS=40"', launcher)
        self.assertIn("--auto-roi-worker %AUTO_ROI_WORKER%", launcher)
        self.assertIn("--auto-roi-result-max-age-ms %AUTO_ROI_RESULT_MAX_AGE_MS%", launcher)
        self.assertIn("--max-sync-offset-ms %MAX_SYNC_OFFSET_MS%", launcher)
        self.assertIn("--visible-sync-max-age-ms %VISIBLE_SYNC_MAX_AGE_MS%", launcher)
        self.assertIn("--mini2-index %MINI2_INDEX%", launcher)
        self.assertIn("--allow-mini2-missing %ALLOW_MINI2_MISSING%", launcher)
        self.assertIn("--mini2-retry-interval-s %MINI2_RETRY_INTERVAL_S%", launcher)
        self.assertIn("--visible-index %VISIBLE_INDEX%", launcher)
        self.assertIn("--visible-width %VISIBLE_WIDTH%", launcher)
        self.assertIn("--visible-height %VISIBLE_HEIGHT%", launcher)
        self.assertIn("--thermal-rotation-degrees %THERMAL_ROTATION_DEGREES%", launcher)
        self.assertIn("--live-stream-port %LIVE_STREAM_PORT%", launcher)
        self.assertIn("--live-stream-jpeg-quality %LIVE_STREAM_JPEG_QUALITY%", launcher)
        self.assertIn("--roi-click-enabled %ROI_CLICK_ENABLED%", launcher)
        self.assertIn("--roi-link-mode %ROI_LINK_MODE%", launcher)
        self.assertIn("--roi-auto-detect %ROI_AUTO_DETECT%", launcher)

    def test_thermal_matrix_orientation_supports_180_degree_rotation(self):
        matrix = np.arange(12, dtype=np.uint16).reshape(3, 4)

        self.assertTrue(np.array_equal(windows_live_collect.orient_thermal_matrix(matrix, 0), matrix))
        self.assertTrue(np.array_equal(windows_live_collect.orient_thermal_matrix(matrix, 180), np.rot90(matrix, 2)))

        with self.assertRaises(ValueError):
            windows_live_collect.orient_thermal_matrix(matrix, 90)

    def test_live_control_state_tracks_thermal_rotation_degrees(self):
        controls = windows_live_collect.LiveControlState(thermal_rotation_degrees=180)

        self.assertEqual(controls.snapshot()["thermal_rotation_degrees"], 180)
        self.assertEqual(controls.update_from_payload({"thermal_rotation_degrees": 0})["thermal_rotation_degrees"], 0)
        with self.assertRaises(ValueError):
            controls.update_from_payload({"thermal_rotation_degrees": 90})

    def test_roi_selection_state_updates_visible_and_thermal_rois(self):
        state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(80, 60, 160, 120),
            thermal_roi=Roi(96, 72, 64, 48),
        )

        state.update_visible(Roi(20, 30, 80, 60), seed=(50, 60), frame_shape=(240, 320))
        state.update_thermal(Roi(100, 80, 40, 30), seed=(120, 95), frame_shape=(192, 256))

        self.assertEqual(state.visible_roi, Roi(20, 30, 80, 60))
        self.assertEqual(state.thermal_roi, Roi(100, 80, 40, 30))
        self.assertEqual(state.visible_anchor.seed_xy, (50, 60))
        self.assertEqual(state.thermal_anchor.seed_xy, (120, 95))
        self.assertEqual(state.snapshot(), (Roi(20, 30, 80, 60), Roi(100, 80, 40, 30)))

    def test_detect_visible_roi_from_seed_returns_bounded_roi(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[70:170, 90:230] = 180

        roi = windows_live_collect.detect_visible_roi_from_seed(frame, seed=(150, 120))

        self.assertGreaterEqual(roi.x, 0)
        self.assertGreaterEqual(roi.y, 0)
        self.assertLessEqual(roi.x + roi.width, 320)
        self.assertLessEqual(roi.y + roi.height, 240)
        self.assertTrue(roi.x <= 150 <= roi.x + roi.width)
        self.assertTrue(roi.y <= 120 <= roi.y + roi.height)

    def test_detect_thermal_roi_from_seed_returns_bounded_roi(self):
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        matrix[60:120, 100:160] = 5400

        roi = windows_live_collect.detect_thermal_roi_from_seed(matrix, seed=(130, 90))

        self.assertGreaterEqual(roi.x, 0)
        self.assertGreaterEqual(roi.y, 0)
        self.assertLessEqual(roi.x + roi.width, 256)
        self.assertLessEqual(roi.y + roi.height, 192)
        self.assertTrue(roi.x <= 130 <= roi.x + roi.width)
        self.assertTrue(roi.y <= 90 <= roi.y + roi.height)

    def test_parse_roi_click_payload_accepts_visible_click(self):
        payload = windows_live_collect.parse_roi_click_payload(b'{"target":"visible","x":120,"y":80}')

        self.assertEqual(payload, ("visible", 120, 80))

    def test_parse_roi_click_payload_rejects_bad_target(self):
        with self.assertRaises(ValueError):
            windows_live_collect.parse_roi_click_payload(b'{"target":"bad","x":1,"y":2}')

    def test_parse_roi_rect_payload_accepts_and_rejects_invalid_rectangles(self):
        target, roi = windows_live_collect.parse_roi_rect_payload(
            {"target": "thermal", "x": 10.2, "y": 12.6, "width": 30, "height": 40}
        )

        self.assertEqual(target, "thermal")
        self.assertEqual(roi, Roi(10, 13, 30, 40))
        with self.assertRaisesRegex(ValueError, "width and height"):
            windows_live_collect.parse_roi_rect_payload({"target": "visible", "x": 1, "y": 2, "width": 0, "height": 5})
        with self.assertRaisesRegex(ValueError, "visible or thermal"):
            windows_live_collect.parse_roi_rect_payload({"target": "bad", "x": 1, "y": 2, "width": 3, "height": 4})

    def test_polygon_roi_payload_creates_mask_bbox_for_lasso_selection(self):
        target, points, frame_shape = windows_live_collect.parse_roi_polygon_payload(
            {
                "target": "visible",
                "frame_width": 12,
                "frame_height": 12,
                "points": [
                    {"x": 2, "y": 2},
                    {"x": 8, "y": 2},
                    {"x": 8, "y": 8},
                    {"x": 2, "y": 8},
                ],
            }
        )

        mask = windows_live_collect.polygon_mask_from_points(points, frame_shape)
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=1.0, source="manual_lasso")

        self.assertEqual(target, "visible")
        self.assertEqual(frame_shape, (12, 12))
        self.assertEqual(roi_mask.bbox, Roi(2, 2, 6, 6))
        self.assertEqual(roi_mask.area_px, 36)

    def test_polygon_mask_rasterizes_only_lasso_bbox_on_large_visible_frame(self):
        points = [(100.0, 80.0), (180.0, 80.0), (180.0, 150.0), (100.0, 150.0)]
        mask = windows_live_collect.polygon_mask_from_points(points, (1080, 1920))
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=1.0, source="manual_lasso")

        self.assertEqual(mask.shape, (1080, 1920))
        self.assertEqual(roi_mask.bbox, Roi(100, 80, 80, 70))
        self.assertEqual(roi_mask.area_px, 80 * 70)

    def test_roi_selection_state_accepts_manual_lasso_mask(self):
        state = windows_live_collect.RoiSelectionState()
        mask = windows_live_collect.polygon_mask_from_points(
            [(2, 2), (8, 2), (8, 8), (2, 8)],
            (12, 12),
        )

        applied = state.update_polygon_mask("visible", mask, source="manual_lasso")
        status = state.status()

        self.assertEqual(applied.bbox, Roi(2, 2, 6, 6))
        self.assertEqual(status["visible_roi"], "2,2,6,6")
        self.assertEqual(status["visible_roi_shape"], "mask")
        self.assertEqual(status["visible_mask_source"], "manual_lasso")

    def test_manual_lasso_roi_is_not_overwritten_by_continuous_auto_roi(self):
        state = windows_live_collect.RoiSelectionState()
        mask = windows_live_collect.polygon_mask_from_points(
            [(2, 2), (8, 2), (8, 8), (2, 8)],
            (12, 12),
        )
        state.update_polygon_mask("thermal", mask, source="manual_lasso_edge_refined")
        auto_mask = windows_live_collect.roi_mask_from_bool(
            windows_live_collect.polygon_mask_from_points(
                [(9, 9), (12, 9), (12, 12), (9, 12)],
                (12, 12),
            ),
            confidence=0.95,
            source="thermal_contrast_candidate",
        )

        changed = windows_live_collect.apply_auto_roi_detection_results(
            state,
            visible_result=None,
            thermal_result=windows_live_collect.RoiDetectionResult(
                auto_mask.bbox,
                0.95,
                "thermal_contrast_candidate",
                mask=auto_mask,
            ),
            visible_frame=None,
            thermal_matrix=np.zeros((12, 12), dtype=np.uint16),
            min_confidence=0.5,
        )

        status = state.status()
        self.assertFalse(changed)
        self.assertEqual(state.snapshot()[1], Roi(2, 2, 6, 6))
        self.assertEqual(status["thermal_mask_source"], "manual_lasso_edge_refined")
        self.assertIn("kept manual lasso ROI", status["roi_error"])

    def test_explicit_auto_candidate_can_replace_manual_lasso_roi(self):
        state = windows_live_collect.RoiSelectionState()
        mask = windows_live_collect.polygon_mask_from_points(
            [(2, 2), (8, 2), (8, 8), (2, 8)],
            (12, 12),
        )
        state.update_polygon_mask("thermal", mask, source="manual_lasso")
        auto_mask = windows_live_collect.roi_mask_from_bool(
            windows_live_collect.polygon_mask_from_points(
                [(9, 9), (12, 9), (12, 12), (9, 12)],
                (12, 12),
            ),
            confidence=0.95,
            source="thermal_contrast_candidate",
        )

        changed = windows_live_collect.apply_auto_roi_detection_results(
            state,
            visible_result=None,
            thermal_result=windows_live_collect.RoiDetectionResult(
                auto_mask.bbox,
                0.95,
                "thermal_contrast_candidate",
                mask=auto_mask,
            ),
            visible_frame=None,
            thermal_matrix=np.zeros((12, 12), dtype=np.uint16),
            min_confidence=0.5,
            allow_manual_lasso_overwrite=True,
        )

        status = state.status()
        self.assertTrue(changed)
        self.assertEqual(state.snapshot()[1], Roi(9, 9, 3, 3))
        self.assertEqual(status["thermal_mask_source"], "thermal_contrast_candidate")

    def test_refines_visible_lasso_to_local_color_boundary_without_global_yolo(self):
        frame = np.zeros((24, 24, 3), dtype=np.uint8)
        frame[8:16, 8:16] = [190, 50, 50]
        initial = windows_live_collect.polygon_mask_from_points(
            [(5, 5), (19, 5), (19, 19), (5, 19)],
            frame.shape[:2],
        )

        refined, source = windows_live_collect.refine_lasso_mask_to_local_boundary(
            initial,
            visible_frame=frame,
        )
        roi_mask = windows_live_collect.roi_mask_from_bool(refined, confidence=1.0, source=source)

        self.assertEqual(source, "manual_lasso_edge_refined")
        self.assertLess(roi_mask.area_px, int(np.count_nonzero(initial)))
        self.assertGreaterEqual(roi_mask.bbox.x, 7)
        self.assertGreaterEqual(roi_mask.bbox.y, 7)
        self.assertLessEqual(roi_mask.bbox.x + roi_mask.bbox.width, 17)
        self.assertLessEqual(roi_mask.bbox.y + roi_mask.bbox.height, 17)

    def test_refines_visible_lasso_by_rgb_hsv_difference_when_gray_score_matches_background(self):
        frame = np.full((28, 28, 3), [100, 100, 100], dtype=np.uint8)
        frame[10:18, 10:18] = [0, 84, 0]
        initial = windows_live_collect.polygon_mask_from_points(
            [(6, 6), (22, 6), (22, 22), (6, 22)],
            frame.shape[:2],
        )

        refined, source = windows_live_collect.refine_lasso_mask_to_local_boundary(
            initial,
            visible_frame=frame,
        )
        roi_mask = windows_live_collect.roi_mask_from_bool(refined, confidence=1.0, source=source)

        self.assertEqual(source, "manual_lasso_color_refined")
        self.assertLess(roi_mask.area_px, int(np.count_nonzero(initial)))
        self.assertGreaterEqual(roi_mask.bbox.x, 9)
        self.assertGreaterEqual(roi_mask.bbox.y, 9)
        self.assertLessEqual(roi_mask.bbox.x + roi_mask.bbox.width, 19)
        self.assertLessEqual(roi_mask.bbox.y + roi_mask.bbox.height, 19)

    def test_refines_thermal_lasso_to_local_raw_boundary(self):
        matrix = np.full((24, 24), 5000, dtype=np.uint16)
        matrix[8:16, 8:16] = 5350
        initial = windows_live_collect.polygon_mask_from_points(
            [(5, 5), (19, 5), (19, 19), (5, 19)],
            matrix.shape,
        )

        refined, source = windows_live_collect.refine_lasso_mask_to_local_boundary(
            initial,
            thermal_matrix=matrix,
        )
        roi_mask = windows_live_collect.roi_mask_from_bool(refined, confidence=1.0, source=source)

        self.assertEqual(source, "manual_lasso_edge_refined")
        self.assertLess(roi_mask.area_px, int(np.count_nonzero(initial)))
        self.assertGreaterEqual(roi_mask.bbox.x, 7)
        self.assertGreaterEqual(roi_mask.bbox.y, 7)
        self.assertLessEqual(roi_mask.bbox.x + roi_mask.bbox.width, 17)
        self.assertLessEqual(roi_mask.bbox.y + roi_mask.bbox.height, 17)

    def test_roi_auto_candidate_queue_keeps_visible_request_until_visible_frame_available(self):
        state = windows_live_collect.RoiSelectionState()
        requested = state.request_auto_candidate("visible")

        first_pop = state.pop_auto_candidate_request(
            visible_available=False,
            thermal_available=True,
            visible_expected=True,
            thermal_expected=True,
        )
        waiting = state.status()
        second_pop = state.pop_auto_candidate_request(
            visible_available=True,
            thermal_available=True,
            visible_expected=True,
            thermal_expected=True,
        )

        self.assertEqual(requested["pending_auto_candidate_requests"], 1)
        self.assertIsNone(first_pop)
        self.assertEqual(waiting["pending_auto_candidate_requests"], 1)
        self.assertEqual(waiting["pending_auto_candidate_target"], "visible")
        self.assertIn("visible_frame", waiting["roi_source"])
        self.assertEqual(second_pop, "visible")
        self.assertEqual(state.status()["pending_auto_candidate_requests"], 0)

    def test_roi_auto_candidate_queue_supports_thermal_and_rejects_bad_target(self):
        state = windows_live_collect.RoiSelectionState()
        state.request_auto_candidate("thermal")

        self.assertEqual(
            state.pop_auto_candidate_request(
                visible_available=True,
                thermal_available=True,
                visible_expected=True,
                thermal_expected=True,
            ),
            "thermal",
        )
        with self.assertRaisesRegex(ValueError, "visible, thermal, or both"):
            state.request_auto_candidate("bad")

    def test_roi_selection_state_locks_unlocks_and_blocks_auto_updates(self):
        state = windows_live_collect.RoiSelectionState()
        state.update_rect("visible", Roi(10, 20, 30, 40), frame_shape=(120, 160))
        state.update_rect("thermal", Roi(50, 60, 20, 15), frame_shape=(192, 256))

        locked = state.lock()
        changed = state.update_auto(visible_roi=Roi(1, 2, 3, 4), reason="auto:test")

        self.assertTrue(locked["roi_locked"])
        self.assertEqual(locked["roi_state"], "locked")
        self.assertEqual(locked["roi_session_id"], 1)
        self.assertFalse(changed)
        self.assertEqual(state.snapshot(), (Roi(10, 20, 30, 40), Roi(50, 60, 20, 15)))
        recording = state.start_recording()
        self.assertEqual(recording["roi_state"], "recording")
        with self.assertRaisesRegex(ValueError, "stop recording"):
            state.unlock()
        stopped = state.stop_recording()
        self.assertEqual(stopped["roi_state"], "stopped")
        self.assertTrue(stopped["roi_locked"])
        self.assertFalse(stopped["roi_editable"])
        self.assertTrue(stopped["roi_recordable"])
        self.assertFalse(state.update_auto(visible_roi=Roi(2, 3, 4, 5), reason="auto:after_stop"))
        with self.assertRaisesRegex(ValueError, "unlock/reset"):
            state.update_rect("visible", Roi(1, 1, 5, 5), frame_shape=(120, 160))
        restarted = state.start_recording()
        self.assertEqual(restarted["roi_state"], "recording")
        state.stop_recording()
        unlocked = state.unlock()
        self.assertEqual(unlocked["roi_state"], "setup")

    def test_apply_auto_roi_worker_result_rejects_locked_roi_state(self):
        state = windows_live_collect.RoiSelectionState()
        state.update_rect("visible", Roi(10, 10, 20, 20), frame_shape=(120, 160))
        state.update_rect("thermal", Roi(30, 30, 20, 20), frame_shape=(192, 256))
        state.lock()
        settings = windows_live_collect.AutoRoiSettingsSnapshot.from_values(
            mode="visible",
            visible_detector="yolo",
            min_confidence=0.5,
            link_mode="anchor",
            settings_updated_epoch_s=1.0,
        )
        result = windows_live_collect.AutoRoiWorkerResult(
            sequence=1,
            settings=settings,
            visible_frame_id=1,
            visible_timestamp_s=0.0,
            thermal_frame_id=None,
            thermal_timestamp_s=None,
            submitted_epoch_s=time.time(),
            completed_epoch_s=time.time(),
            visible_result=windows_live_collect.RoiDetectionResult(Roi(1, 1, 10, 10), 0.9, "yolo_visible_candidate:cup"),
        )

        applied, reason = windows_live_collect.apply_auto_roi_worker_result(
            state,
            result,
            current_settings=settings,
            visible_frame=rgb_frame(50),
            thermal_matrix=None,
        )

        self.assertFalse(applied)
        self.assertEqual(reason, "roi_locked_or_recording")
        self.assertEqual(state.snapshot()[0], Roi(10, 10, 20, 20))

    def test_apply_roi_click_updates_visible_and_thermal_state(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[80:180, 100:240] = 180
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        matrix[65:125, 105:165] = 5400

        windows_live_collect.apply_roi_click(state, "visible", (150, 120), visible_frame=frame, thermal_matrix=matrix)
        windows_live_collect.apply_roi_click(state, "thermal", (130, 90), visible_frame=frame, thermal_matrix=matrix)

        visible_roi, thermal_roi = state.snapshot()
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(thermal_roi)
        self.assertTrue(visible_roi.x <= 150 <= visible_roi.x + visible_roi.width)
        self.assertTrue(thermal_roi.x <= 130 <= thermal_roi.x + thermal_roi.width)
        visible_mask, thermal_mask = state.snapshot_masks()
        self.assertIsNotNone(visible_mask)
        self.assertIsNotNone(thermal_mask)
        self.assertEqual(visible_mask.shape, "mask")
        self.assertEqual(thermal_mask.shape, "mask")
        self.assertTrue(visible_mask.mask[120, 150])
        self.assertTrue(thermal_mask.mask[90, 130])

    def test_map_visible_roi_to_thermal_uses_anchor_delta(self):
        state = windows_live_collect.RoiSelectionState()
        state.update_visible(Roi(100, 80, 80, 60), seed=(140, 110), frame_shape=(240, 320))
        state.update_thermal(Roi(90, 70, 40, 30), seed=(110, 85), frame_shape=(192, 256))

        mapped = windows_live_collect.map_visible_roi_to_thermal(
            state,
            Roi(120, 95, 80, 60),
            visible_shape=(240, 320),
            thermal_shape=(192, 256),
        )

        self.assertEqual(mapped.width, 40)
        self.assertEqual(mapped.height, 30)
        self.assertEqual(mapped.x, 106)
        self.assertEqual(mapped.y, 82)

    def test_setup_auto_candidate_requires_yolo_model_for_visible_roi(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.full((120, 160, 3), 20, dtype=np.uint8)

        applied = windows_live_collect.apply_setup_auto_candidate_rois(
            state,
            visible_frame=frame,
            thermal_matrix=None,
            min_confidence=0.5,
        )

        visible_roi, thermal_roi = state.snapshot()
        self.assertFalse(applied)
        self.assertIsNone(visible_roi)
        self.assertIsNone(thermal_roi)

    def test_setup_auto_candidate_uses_yolo_model_for_visible_roi(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        model = fake_cup_yolo_model()

        applied = windows_live_collect.apply_setup_auto_candidate_rois(
            state,
            visible_frame=frame,
            thermal_matrix=None,
            min_confidence=0.5,
            yolo_model=model,
            yolo_classes={"cup"},
        )

        visible_roi, thermal_roi = state.snapshot()
        visible_mask, thermal_mask = state.snapshot_masks()
        self.assertTrue(applied)
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(visible_mask)
        self.assertEqual(visible_mask.source, "yolo_mask:cup")
        self.assertIsNone(thermal_roi)
        self.assertIsNone(thermal_mask)

    def test_auto_detect_thermal_roi_rejects_flat_matrix(self):
        matrix = np.full((192, 256), 5000, dtype=np.uint16)

        result = windows_live_collect.auto_detect_thermal_roi(matrix)

        self.assertIsNone(result.roi)
        self.assertLess(result.confidence, 0.5)

    def test_auto_visible_mode_does_not_clone_visible_roi_to_thermal_without_clicking(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        model = fake_cup_yolo_model()

        windows_live_collect.maybe_auto_update_rois(
            state,
            visible_frame=frame,
            thermal_matrix=matrix,
            mode="visible",
            min_confidence=0.5,
            link_mode="anchor",
            visible_detector="yolo",
            yolo_model=model,
            yolo_classes={"cup"},
        )

        visible_roi, thermal_roi = state.snapshot()
        visible_mask, thermal_mask = state.snapshot_masks()
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(visible_mask)
        self.assertEqual(visible_mask.source, "yolo_mask:cup")
        self.assertIsNone(thermal_roi)
        self.assertIsNone(thermal_mask)

    def test_auto_both_detects_visible_and_thermal_roi_independently(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        matrix[60:112, 140:190] = 5400
        model = fake_cup_yolo_model()

        windows_live_collect.maybe_auto_update_rois(
            state,
            visible_frame=frame,
            thermal_matrix=matrix,
            mode="both",
            min_confidence=0.5,
            link_mode="anchor",
            visible_detector="yolo",
            yolo_model=model,
            yolo_classes={"cup"},
        )

        visible_roi, thermal_roi = state.snapshot()
        visible_mask, thermal_mask = state.snapshot_masks()
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(thermal_roi)
        self.assertIsNotNone(visible_mask)
        self.assertIsNotNone(thermal_mask)
        self.assertNotEqual(visible_mask.mask.shape, thermal_mask.mask.shape)
        self.assertNotEqual(visible_roi, thermal_roi)
        self.assertEqual(visible_mask.source, "yolo_mask:cup")
        self.assertEqual(thermal_mask.source, "thermal_contrast_candidate")

    def test_setup_auto_candidate_does_not_fallback_for_oversized_visible_yolo_region(self):
        state = windows_live_collect.RoiSelectionState()
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        oversized_mask = np.ones((120, 160), dtype=bool)
        model = FakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[0, 0, 159, 119]], conf=[0.92], cls=[0]),
                    masks=FakeYoloMasks([oversized_mask]),
                )
            ]
        )

        applied = windows_live_collect.apply_setup_auto_candidate_rois(
            state,
            visible_frame=frame,
            thermal_matrix=None,
            min_confidence=0.5,
            yolo_model=model,
            yolo_classes={"cup"},
        )

        visible_roi, thermal_roi = state.snapshot()
        self.assertFalse(applied)
        self.assertIsNone(visible_roi)
        self.assertIsNone(thermal_roi)

    def test_auto_detect_visible_roi_yolo_uses_segmentation_mask_and_class_filter(self):
        yy, xx = np.ogrid[:120, :160]
        cup_mask = (xx - 80) ** 2 + (yy - 60) ** 2 <= 18**2
        person_mask = np.ones((120, 160), dtype=bool)
        model = FakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(
                        xyxy=[[0, 0, 159, 119], [62, 42, 98, 78]],
                        conf=[0.99, 0.82],
                        cls=[1, 0],
                    ),
                    masks=FakeYoloMasks([person_mask, cup_mask]),
                )
            ]
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        result = windows_live_collect.auto_detect_visible_roi_yolo(frame, model, allowed_classes={"cup"})

        self.assertIsNotNone(result.mask)
        self.assertEqual(result.mask.source, "yolo_mask:cup")
        self.assertTrue(result.mask.mask[60, 80])
        self.assertFalse(result.mask.mask[2, 2])
        self.assertLess(result.mask.area_px, 1500)
        self.assertIn("cup", result.reason)

    def test_auto_detect_visible_roi_yolo_rejects_person_only_candidate(self):
        model = FakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[0, 0, 159, 119]], conf=[0.95], cls=[1]),
                    masks=FakeYoloMasks([np.ones((120, 160), dtype=bool)]),
                )
            ]
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        result = windows_live_collect.auto_detect_visible_roi_yolo(frame, model, allowed_classes={"cup"})

        self.assertIsNone(result.roi)
        self.assertLess(result.confidence, 0.5)

    def test_auto_detect_visible_roi_yolo_rejects_detection_box_without_segmentation_mask(self):
        model = FakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[30, 25, 90, 85]], conf=[0.78], cls=[2]),
                    masks=None,
                )
            ]
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        result = windows_live_collect.auto_detect_visible_roi_yolo(frame, model, allowed_classes={"bottle"})

        self.assertIsNone(result.mask)
        self.assertIsNone(result.roi)
        self.assertEqual(result.reason, "yolo_segmentation_mask_unavailable")

    def test_auto_update_rois_yolo_keeps_thermal_independent(self):
        state = windows_live_collect.RoiSelectionState()
        yy, xx = np.ogrid[:120, :160]
        cup_mask = (xx - 80) ** 2 + (yy - 60) ** 2 <= 18**2
        model = FakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[62, 42, 98, 78]], conf=[0.82], cls=[0]),
                    masks=FakeYoloMasks([cup_mask]),
                )
            ]
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        matrix[60:112, 140:190] = 5400

        windows_live_collect.maybe_auto_update_rois(
            state,
            visible_frame=frame,
            thermal_matrix=matrix,
            mode="both",
            min_confidence=0.5,
            visible_detector="yolo",
            yolo_model=model,
            yolo_classes={"cup"},
        )

        visible_roi, thermal_roi = state.snapshot()
        visible_mask, thermal_mask = state.snapshot_masks()
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(thermal_roi)
        self.assertEqual(visible_mask.source, "yolo_mask:cup")
        self.assertEqual(thermal_mask.source, "thermal_contrast_candidate")
        self.assertNotEqual(visible_mask.mask.shape, thermal_mask.mask.shape)

    def test_load_yolo_model_reports_missing_optional_dependency(self):
        def missing_importer(_name):
            raise ImportError("no ultralytics")

        with self.assertRaisesRegex(RuntimeError, "pip install"):
            windows_live_collect.load_yolo_model("yolo11n-seg.pt", importer=missing_importer)

    def test_yolo_visible_roi_worker_submit_is_non_blocking_and_publishes_result(self):
        yy, xx = np.ogrid[:120, :160]
        cup_mask = (xx - 80) ** 2 + (yy - 60) ** 2 <= 18**2
        model = SlowFakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[62, 42, 98, 78]], conf=[0.82], cls=[0]),
                    masks=FakeYoloMasks([cup_mask]),
                )
            ],
            delay_s=0.06,
        )
        worker = windows_live_collect.YoloVisibleRoiWorker(
            model,
            allowed_classes={"cup"},
            min_confidence=0.25,
            max_area_fraction=0.45,
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        try:
            started = time.perf_counter()
            accepted = worker.submit(frame)
            submit_elapsed = time.perf_counter() - started
            result = worker.latest_result(timeout_s=0.5)
        finally:
            worker.close()

        self.assertTrue(accepted)
        self.assertLess(submit_elapsed, 0.02)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.mask)
        self.assertEqual(result.mask.source, "yolo_mask:cup")

    def test_yolo_visible_roi_worker_throttles_repeated_successful_inference(self):
        yy, xx = np.ogrid[:120, :160]
        cup_mask = (xx - 80) ** 2 + (yy - 60) ** 2 <= 18**2
        model = SlowFakeYoloModel(
            [
                FakeYoloResult(
                    boxes=FakeYoloBoxes(xyxy=[[62, 42, 98, 78]], conf=[0.82], cls=[0]),
                    masks=FakeYoloMasks([cup_mask]),
                )
            ],
            delay_s=0.02,
        )
        worker = windows_live_collect.YoloVisibleRoiWorker(
            model,
            allowed_classes={"cup"},
            min_confidence=0.25,
            max_area_fraction=0.45,
            min_interval_s=1.0,
            success_interval_s=5.0,
            inference_size=256,
        )
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        try:
            self.assertTrue(worker.submit(frame))
            self.assertFalse(worker.submit(frame))
            self.assertIsNotNone(worker.latest_result(timeout_s=0.5))
            self.assertFalse(worker.submit(frame))
        finally:
            worker.close()

        self.assertEqual(len(model.calls), 1)
        self.assertEqual(model.calls[0][1].get("imgsz"), 256)

    def test_keep_largest_mask_component_preserves_shape_not_rectangle(self):
        mask = np.zeros((30, 30), dtype=bool)
        mask[3:6, 3:6] = True
        mask[10:20, 12:22] = True
        mask[25:27, 25:27] = True

        cleaned, component_count = windows_live_collect.keep_largest_mask_component(mask, min_area_px=4)

        self.assertEqual(component_count, 3)
        self.assertFalse(cleaned[4, 4])
        self.assertTrue(cleaned[15, 15])
        self.assertFalse(cleaned[26, 26])
        self.assertEqual(int(np.count_nonzero(cleaned)), 100)

    def test_extract_mask_color_features_uses_mask_pixels_not_bbox(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        frame[4:16, 4:16] = [200, 0, 0]
        mask = np.zeros((20, 20), dtype=bool)
        mask[8:12, 8:12] = True
        frame[mask] = [0, 0, 180]
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.9, source="test")

        features = windows_live_collect.extract_mask_color_features(frame, roi_mask)

        self.assertLess(features["R_mean"], 1.0)
        self.assertGreater(features["B_mean"], 170.0)
        self.assertEqual(features["mask_area_px"], 16)

    def test_extract_raw_mask_thermal_features_uses_mask_pixels_not_bbox(self):
        matrix = np.full((20, 20), 1000, dtype=np.uint16)
        matrix[4:16, 4:16] = 2000
        mask = np.zeros((20, 20), dtype=bool)
        mask[8:12, 8:12] = True
        matrix[mask] = 5000
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.8, source="thermal_test")

        features = windows_live_collect.extract_raw_mask_thermal_features(
            raw_matrix=matrix,
            roi_mask=roi_mask,
            previous=None,
            frame_rate_hz=25.0,
        )

        self.assertEqual(features["thermal_raw_roi_avg"], 5000.0)
        self.assertEqual(features["thermal_mask_area_px"], 16)
        self.assertEqual(features["thermal_roi_shape"], "mask")
        self.assertEqual(features["thermal_raw_roi_p50"], 5000.0)
        self.assertEqual(features["thermal_raw_roi_range"], 0.0)
        self.assertEqual(features["thermal_raw_roi_min_x"], 8)
        self.assertEqual(features["thermal_raw_roi_max_y"], 8)

    def test_extract_roi_only_thermal_features_adds_distribution_summaries(self):
        matrix = np.arange(400, dtype=np.uint16).reshape(20, 20)
        roi = Roi(2, 3, 4, 4)

        features = windows_live_collect.extract_roi_only_thermal_features(
            raw_matrix=matrix,
            addline_tag1=b"",
            converter=FakeOfficialConverter(),
            roi=roi,
            previous=None,
            frame_rate_hz=25.0,
        )

        self.assertIn("thermal_roi_p05", features)
        self.assertIn("thermal_roi_p50", features)
        self.assertIn("thermal_roi_p95", features)
        self.assertIn("thermal_roi_iqr", features)
        self.assertIn("thermal_roi_hot_fraction", features)
        self.assertEqual(features["thermal_roi_min_x"], 2)
        self.assertEqual(features["thermal_roi_min_y"], 3)
        self.assertEqual(features["thermal_roi_max_x"], 5)
        self.assertEqual(features["thermal_roi_max_y"], 6)
        self.assertEqual(features["thermal_raw_roi_p50"], 93.5)

    def test_zero_celsius_converter_output_falls_back_to_raw_temperature_preview(self):
        matrix = np.full((20, 20), 5000, dtype=np.uint16)
        roi = Roi(2, 3, 4, 4)

        features = windows_live_collect.extract_roi_only_thermal_features(
            raw_matrix=matrix,
            addline_tag1=b"",
            converter=ZeroOfficialConverter(),
            roi=roi,
            previous=None,
            frame_rate_hz=25.0,
        )
        payload = windows_live_collect.build_live_payload(features, {"frame_id": 1})

        self.assertFalse(features["thermal_calibrated"])
        self.assertEqual(features["thermal_source"], "mini2_uvc_raw_uncalibrated_preview")
        self.assertEqual(features["thermal_conversion_status"], "suspect_all_zero")
        self.assertIn("suspect all-zero", features["warnings"])
        self.assertNotIn("thermal_roi_avg", features)
        self.assertFalse(payload["thermal_calibrated"])
        self.assertEqual(payload["thermal_conversion_status"], "suspect_all_zero")
        self.assertIn("suspect all-zero", payload["thermal_warning"])
        self.assertIsNone(payload["temperature_avg_c"])
        self.assertEqual(payload["raw_avg"], 5000.0)

    def test_zero_celsius_mask_converter_output_falls_back_to_raw_temperature_preview(self):
        matrix = np.full((20, 20), 5000, dtype=np.uint16)
        mask = np.zeros((20, 20), dtype=bool)
        mask[8:12, 8:12] = True
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.8, source="thermal_test")

        features = windows_live_collect.extract_roi_mask_thermal_features(
            raw_matrix=matrix,
            addline_tag1=b"",
            converter=ZeroOfficialConverter(),
            roi_mask=roi_mask,
            previous=None,
            frame_rate_hz=25.0,
        )
        payload = windows_live_collect.build_live_payload(features, {"frame_id": 1})

        self.assertFalse(features["thermal_calibrated"])
        self.assertEqual(features["thermal_source"], "mini2_uvc_raw_uncalibrated_mask_preview")
        self.assertEqual(features["thermal_mask_area_px"], 16)
        self.assertEqual(features["thermal_conversion_status"], "suspect_all_zero")
        self.assertIn("suspect all-zero", features["warnings"])
        self.assertFalse(payload["thermal_calibrated"])
        self.assertEqual(payload["thermal_conversion_status"], "suspect_all_zero")
        self.assertIn("suspect all-zero", payload["thermal_warning"])
        self.assertIsNone(payload["temperature_avg_c"])
        self.assertEqual(payload["raw_avg"], 5000.0)

    def test_non_finite_celsius_converter_output_reports_specific_status(self):
        matrix = np.full((20, 20), 5000, dtype=np.uint16)
        roi = Roi(2, 3, 4, 4)

        features = windows_live_collect.extract_roi_only_thermal_features(
            raw_matrix=matrix,
            addline_tag1=b"",
            converter=NonFiniteOfficialConverter(),
            roi=roi,
            previous=None,
            frame_rate_hz=25.0,
        )
        payload = windows_live_collect.build_live_payload(features, {"frame_id": 1})

        self.assertFalse(features["thermal_calibrated"])
        self.assertEqual(features["thermal_conversion_status"], "non_finite")
        self.assertIn("non-finite", features["warnings"])
        self.assertEqual(payload["thermal_conversion_status"], "non_finite")
        self.assertIn("non-finite", payload["thermal_warning"])
        self.assertIsNone(payload["temperature_avg_c"])
        self.assertEqual(payload["raw_avg"], 5000.0)

    def test_raising_celsius_converter_output_reports_specific_status(self):
        matrix = np.full((20, 20), 5000, dtype=np.uint16)
        roi = Roi(2, 3, 4, 4)

        features = windows_live_collect.extract_roi_only_thermal_features(
            raw_matrix=matrix,
            addline_tag1=b"",
            converter=RaisingOfficialConverter(),
            roi=roi,
            previous=None,
            frame_rate_hz=25.0,
        )
        payload = windows_live_collect.build_live_payload(features, {"frame_id": 1})

        self.assertFalse(features["thermal_calibrated"])
        self.assertEqual(features["thermal_conversion_status"], "converter_error")
        self.assertIn("MT_Process failed during frame", features["warnings"])
        self.assertEqual(payload["thermal_conversion_status"], "converter_error")
        self.assertIsNone(payload["temperature_avg_c"])
        self.assertEqual(payload["raw_avg"], 5000.0)

    def test_draw_mask_overlay_marks_shape_without_bbox_corners(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        mask = np.zeros((20, 20), dtype=bool)
        mask[8:12, 8:12] = True
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.75, source="overlay")

        marked = windows_live_collect.draw_mask_overlay(frame, roi_mask, color=(0, 255, 80))

        self.assertEqual(marked[8, 8].tolist(), [0, 255, 80])
        self.assertEqual(marked[4, 4].tolist(), [0, 0, 0])

    def test_build_live_payload_exposes_mask_metadata(self):
        thermal_features = {"thermal_raw_roi_avg": 5000.0, "thermal_raw_roi_min": 4990, "thermal_raw_roi_max": 5010}
        row = {"frame_id": 1, "time_s": 0.04, "status_label": "before"}
        mask = np.zeros((20, 20), dtype=bool)
        mask[8:12, 8:12] = True
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.75, source="payload")

        payload = windows_live_collect.build_live_payload(
            thermal_features,
            row,
            visible_roi=roi_mask.bbox,
            thermal_roi=roi_mask.bbox,
            visible_mask=roi_mask,
            thermal_mask=roi_mask,
        )

        self.assertEqual(payload["roi_shape"], "mask")
        self.assertEqual(payload["visible_mask_area_px"], 16)
        self.assertEqual(payload["thermal_mask_area_px"], 16)
        self.assertEqual(payload["mask_bbox"], "8,8,4,4")
        self.assertEqual(payload["mask_confidence"], 0.75)
        self.assertEqual(payload["mask_component_count"], 1)
        self.assertEqual(payload["mask_stability"], "fresh")
        self.assertEqual(payload["visible_roi_shape"], "mask")
        self.assertEqual(payload["thermal_roi_shape"], "mask")
        self.assertEqual(payload["visible_mask_source"], "payload")
        self.assertEqual(payload["thermal_mask_source"], "payload")

    def test_build_live_payload_exposes_visible_rgb_metrics(self):
        thermal_features = {"thermal_raw_roi_avg": 5000.0, "thermal_raw_roi_min": 4990, "thermal_raw_roi_max": 5010}
        row = {
            "frame_id": 1,
            "time_s": 0.04,
            "status_label": "before",
            "visible_R_mean": 121.25,
            "visible_G_mean": 83.5,
            "visible_B_mean": 44.75,
            "visible_H_mean": 31.5,
            "visible_S_mean": 0.48,
            "visible_V_mean": 0.76,
            "visible_H_delta": 2.5,
            "visible_S_delta": 0.04,
            "visible_V_delta": 0.03,
            "visible_HSV_delta": 0.052,
            "visible_color_delta": 6.125,
        }

        payload = windows_live_collect.build_live_payload(thermal_features, row)

        self.assertEqual(payload["visible_R_mean"], 121.25)
        self.assertEqual(payload["visible_G_mean"], 83.5)
        self.assertEqual(payload["visible_B_mean"], 44.75)
        self.assertEqual(payload["visible_H_mean"], 31.5)
        self.assertEqual(payload["visible_S_mean"], 0.48)
        self.assertEqual(payload["visible_V_mean"], 0.76)
        self.assertEqual(payload["visible_H_delta"], 2.5)
        self.assertEqual(payload["visible_S_delta"], 0.04)
        self.assertEqual(payload["visible_V_delta"], 0.03)
        self.assertEqual(payload["visible_HSV_delta"], 0.052)
        self.assertEqual(payload["visible_color_delta"], 6.125)

    def test_build_live_payload_exposes_latency_breakdown_metrics(self):
        thermal_features = {"thermal_raw_roi_avg": 5000.0, "thermal_raw_roi_min": 4990, "thermal_raw_roi_max": 5010}
        row = {
            "frame_id": 1,
            "time_s": 0.04,
            "status_label": "before",
            "processing_latency_ms": 14.5,
            "preview_visible_latency_ms": 42.25,
            "sync_offset_ms": -8.75,
            "auto_roi_result_age_ms": 125.0,
            "auto_roi_worker_enabled": True,
            "auto_roi_result_status": "applied",
            "auto_roi_result_reason": "yolo_visible_candidate:cup",
            "auto_roi_dropped_pending": 2,
        }

        payload = windows_live_collect.build_live_payload(thermal_features, row)

        self.assertEqual(payload["latency_mini2_age_ms"], 14.5)
        self.assertEqual(payload["latency_visible_age_ms"], 42.25)
        self.assertEqual(payload["latency_sync_offset_ms"], -8.75)
        self.assertEqual(payload["roi_result_age_ms"], 125.0)
        self.assertTrue(payload["auto_roi_worker_enabled"])
        self.assertEqual(payload["auto_roi_result_status"], "applied")
        self.assertEqual(payload["auto_roi_result_reason"], "yolo_visible_candidate:cup")
        self.assertEqual(payload["auto_roi_dropped_pending"], 2)

    def test_live_csv_buffer_exports_training_rows_for_browser_download(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording()

        buffer.add(
            {
                "frame_id": 1,
                "time_s": 0.04,
                "visible_R_mean": 121.25,
                "thermal_roi_avg": 23.5,
            }
        )

        status = buffer.status()
        body = buffer.to_csv_bytes().decode("utf-8")

        self.assertEqual(status["row_count"], 1)
        self.assertEqual(status["path"], "data/raw/live-training.csv")
        self.assertIn("visible_R_mean", body)
        self.assertIn("thermal_roi_avg", body)
        self.assertIn("121.25", body)
        self.assertNotIn("manual_label", body)

    def test_auto_stop_observation_uses_recording_clock_while_pump_stopped(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv"))
        started = buffer.start_recording(
            pump_rate_ml_per_s=0.99, theoretical_equivalence_volume_ml=20,
            started_monotonic_s=100, started_epoch_s=200,
        )
        buffer.begin_commanded_pump_timeline(running=False)
        buffer.add({"time_s": 999, "pump_elapsed_s": 0}, now_monotonic_s=101.2)
        row = buffer.latest_recorded_row(started["session_id"])
        self.assertAlmostEqual(row["csv_recording_elapsed_s"], 1.2)
        self.assertEqual(row["pump_elapsed_s"], 0)
        self.assertEqual(row["injected_volume_ml"], 0)
        self.assertIsNone(buffer.latest_recorded_row(started["session_id"] + 1))
        row["csv_recording_elapsed_s"] = -1
        self.assertGreater(buffer.latest_recorded_row(started["session_id"])["csv_recording_elapsed_s"], 1)

    def test_live_csv_buffer_adds_pump_equivalence_timeline_fields(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        started = buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=9.0,
            equivalence_window_ml=0.05,
            started_monotonic_s=100.0,
            started_epoch_s=200.0,
        )
        buffer.add({"frame_id": 1, "time_s": 9.02}, now_monotonic_s=109.02)
        status = buffer.status(now_monotonic_s=109.02)
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertEqual(started["pump_run_rate_ml_per_s"], 1.0)
        self.assertEqual(started["theoretical_equivalence_volume_ml"], 9.0)
        self.assertEqual(status["pump_elapsed_s"], 9.02)
        self.assertEqual(status["injected_volume_ml"], 9.02)
        self.assertEqual(status["distance_to_equivalence_ml"], 0.02)
        self.assertEqual(status["equivalence_window_label"], "equivalence")
        self.assertEqual(rows[0]["pump_elapsed_s"], "9.02")
        self.assertEqual(rows[0]["injected_volume_ml"], "9.02")
        self.assertEqual(rows[0]["theoretical_equivalence_time_s"], "9.0")
        self.assertEqual(rows[0]["distance_to_equivalence_ml"], "0.02")
        self.assertEqual(rows[0]["time_to_equivalence_s"], "0.02")
        self.assertEqual(rows[0]["equivalence_window_label"], "equivalence")

    def test_live_csv_buffer_tracks_continuous_time_and_nominal_step_pulses(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=2.0,
            started_monotonic_s=100.0,
        )
        buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=True)

        running = buffer.status(now_monotonic_s=101.0)
        buffer.pause_commanded_pump_timeline(now_monotonic_s=101.0, state="pulse_settling")
        buffer.record_commanded_pulse(
            steps=5,
            nominal_ml_per_step=0.01,
            now_monotonic_s=101.1,
        )
        settled = buffer.status(now_monotonic_s=110.0)

        self.assertEqual(running["injected_volume_ml"], 1.0)
        self.assertEqual(settled["injected_volume_ml"], 1.05)
        self.assertEqual(settled["pump_elapsed_s"], 1.05)
        self.assertEqual(settled["pump_state"], "pulse_settling")
        self.assertEqual(settled["pump_pulse_count"], 1)
        self.assertEqual(settled["pump_pulse_steps_total"], 5)
        self.assertEqual(settled["pump_nominal_pulse_volume_ml"], 0.05)
        self.assertEqual(
            settled["pump_volume_basis"],
            "commanded_time_and_nominal_full_steps_not_direct_flow_measurement",
        )

    def test_live_csv_buffer_accumulates_piecewise_rates_and_excludes_idle_time(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(pump_rate_ml_per_s=1.0, started_monotonic_s=100.0)
        buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=True)
        buffer.pause_commanded_pump_timeline(now_monotonic_s=102.0, state="stopped")
        buffer.start_commanded_continuous_segment(
            rate_ml_per_s=0.25,
            stage="slow_continuous",
            rate_basis="nominal_uncalibrated_fast_rate_times_steps_per_100",
            now_monotonic_s=105.0,
        )
        buffer.pause_commanded_pump_timeline(now_monotonic_s=109.0, state="stopped")

        status = buffer.status(now_monotonic_s=120.0)

        self.assertEqual(status["injected_volume_ml"], 3.0)
        self.assertEqual(status["pump_elapsed_s"], 6.0)
        self.assertEqual(status["pump_dosing_stage"], "slow_continuous")
        self.assertEqual(status["pump_nominal_rate_ml_per_s"], 0.25)
        self.assertIn("nominal_uncalibrated", status["pump_rate_basis"])

    def test_live_csv_buffer_pulse_elapsed_stays_steps_over_100_after_slow_rate(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(pump_rate_ml_per_s=1.0, started_monotonic_s=100.0)
        buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=False)
        buffer.start_commanded_continuous_segment(
            rate_ml_per_s=0.10, stage="slow_continuous", rate_basis="nominal", now_monotonic_s=100.0
        )
        buffer.pause_commanded_pump_timeline(now_monotonic_s=101.0)
        buffer.record_commanded_pulse(steps=5, nominal_ml_per_step=0.01, now_monotonic_s=101.0)

        status = buffer.status(now_monotonic_s=110.0)

        self.assertEqual(status["pump_elapsed_s"], 1.05)
        self.assertEqual(status["injected_volume_ml"], 0.15)

    def test_live_csv_buffer_persists_auto_stop_audit_fields(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=10.0,
            experiment_metadata={"auto_stop_enabled": True},
        )
        buffer.add({"frame_id": 1, "time_s": 1.0})
        buffer.update_auto_stop_status(
            {
                "auto_stop_state": "triggered",
                "auto_stop_reason": "persistent_color_change",
                "auto_stop_trigger_volume_ml": 10.1,
            }
        )

        status = buffer.status()
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertTrue(status["auto_stop_enabled"])
        self.assertEqual(status["auto_stop_state"], "triggered")
        self.assertEqual(rows[-1]["auto_stop_reason"], "persistent_color_change")
        self.assertEqual(rows[-1]["auto_stop_trigger_volume_ml"], "10.1")

    def test_live_csv_buffer_calculates_concentration_fields_from_recording_metadata(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        started = buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=10.0,
            equivalence_window_ml=0.05,
            started_monotonic_s=100.0,
            started_epoch_s=200.0,
            experiment_metadata={
                "titration_type": "strong_acid_strong_base",
                "sample_concentration_M": 0.1,
                "sample_volume_ml": 10.0,
                "sample_valence": 1,
                "titrant_concentration_M": 0.1,
                "titrant_valence": 1,
            },
        )
        buffer.add({"frame_id": 1, "time_s": 10.0, "predicted_equivalence_volume_ml": 10.0}, now_monotonic_s=110.0)
        status = buffer.status(now_monotonic_s=110.0)
        stopped = buffer.stop_recording()
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertEqual(started["equivalence_formula"], "nMV=n'M'V'")
        self.assertEqual(started["calculated_theoretical_equivalence_volume_ml"], 10.0)
        self.assertEqual(started["sample_concentration_from_theoretical_equivalence_M"], 0.1)
        self.assertEqual(rows[0]["sample_concentration_from_injected_M"], "0.1")
        self.assertEqual(rows[0]["sample_concentration_error_percent"], "0.0")
        self.assertFalse(rows[0].get("sample_concentration_from_predicted_equivalence_M"))
        self.assertNotIn("predicted_equivalence_volume_ml", status)
        self.assertEqual(status["predicted_equivalence_status"], "pending")
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(stopped["predicted_equivalence_status"], "withheld")
        self.assertEqual(
            stopped["predicted_equivalence_reason"],
            "insufficient_usable_sensor_time_volume_observations",
        )
        self.assertNotIn("sample_concentration_from_predicted_equivalence_M", stopped)

    def test_live_csv_buffer_stop_estimates_prediction_when_ml_column_is_empty(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=10.0,
            equivalence_window_ml=0.05,
            started_monotonic_s=100.0,
            started_epoch_s=200.0,
            experiment_metadata={
                "titration_type": "strong_acid_strong_base",
                "sample_concentration_M": 0.1,
                "sample_volume_ml": 10.0,
                "sample_valence": 1,
                "titrant_concentration_M": 0.1,
                "titrant_valence": 1,
            },
        )
        for index, volume, color_delta in [
            (1, 8.0, 0.1), (2, 8.5, 0.15), (3, 9.0, 0.2),
            (4, 9.5, 0.4), (5, 10.0, 1.0), (6, 10.5, 0.5),
            (7, 11.0, 0.3), (8, 11.5, 0.25), (9, 12.0, 0.2),
        ]:
            buffer.add(
                {
                    "frame_id": index,
                    "time_s": float(index),
                    "injected_volume_ml": volume,
                    "visible_color_delta": color_delta,
                    "visible_H_mean": 20.0 + color_delta,
                    "visible_S_mean": 0.5 + color_delta * 0.01,
                    "visible_V_mean": 0.7 + color_delta * 0.01,
                    "thermal_roi_avg": 25.0 + color_delta,
                    "thermal_roi_min": 24.0 + color_delta,
                    "thermal_roi_max": 26.0 + color_delta,
                    "status_label": "unknown",
                },
                now_monotonic_s=100.0 + volume,
            )

        stopped = buffer.stop_recording()
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))
        predicted_rows = [row for row in rows if row.get("predicted_equivalence_volume_ml")]

        self.assertEqual(stopped["state"], "stopped")
        self.assertAlmostEqual(stopped["predicted_equivalence_volume_ml"], 10.0)
        self.assertEqual(stopped["sample_concentration_from_predicted_equivalence_M"], 0.1)
        self.assertEqual(stopped["predicted_equivalence_pH"], 7.0)
        self.assertEqual(stopped["predicted_equivalence_source"], "live_feature_peak_estimator")
        self.assertEqual(len(predicted_rows), 1)
        self.assertEqual(predicted_rows[0]["predicted_equivalence_volume_ml"], "10.0")
        self.assertEqual(predicted_rows[0]["sample_concentration_from_predicted_equivalence_M"], "0.1")
        self.assertEqual(predicted_rows[0]["predicted_equivalence_pH"], "7.0")

    def test_live_csv_buffer_prefers_typewise_classifier_before_peak_fallback(self):
        class FakeTypewiseEstimator:
            classes_ = [0, 1]

            def predict_proba(self, features):
                scores = np.array([float(row.get("visible_color_delta") or 0.0) for row in features], dtype=float)
                if scores.max() > 0:
                    scores = scores / scores.max()
                return np.column_stack([1.0 - scores, scores])

        model = {
            "artifact_type": "typewise_frame_zone_classifier_v1",
            "feature_columns": ["injected_volume_ml", "visible_color_delta", "titration_type"],
            "categorical_columns": ["titration_type"],
            "models": {
                "strong_acid_strong_base": {
                    "estimator": FakeTypewiseEstimator(),
                    "model_name": "fake_extra_trees",
                    "window_ml": 0.3,
                    "aggregate_mode": "top1",
                    "development_mape_percent": 0.47,
                    "selected_method_key": "fake:typewise",
                }
            },
        }
        buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv"),
            typewise_prediction_model=model,
        )
        buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=10.0,
            started_monotonic_s=100.0,
            started_epoch_s=200.0,
            experiment_metadata={
                "titration_type": "strong_acid_strong_base",
                "sample_concentration_M": 0.1,
                "sample_volume_ml": 10.0,
                "sample_valence": 1,
                "titrant_concentration_M": 0.1,
                "titrant_valence": 1,
            },
        )
        for index, volume, color_delta in [
            (1, 8.0, 0.1), (2, 8.5, 0.15), (3, 9.0, 0.2),
            (4, 9.5, 0.4), (5, 10.0, 1.0), (6, 10.5, 0.5),
            (7, 11.0, 0.3), (8, 11.5, 0.25), (9, 12.0, 0.2),
        ]:
            buffer.add(
                {
                    "frame_id": index,
                    "time_s": float(index),
                    "injected_volume_ml": volume,
                    "visible_color_delta": color_delta,
                    "visible_H_mean": 20.0 + color_delta,
                    "visible_S_mean": 0.5 + color_delta * 0.01,
                    "visible_V_mean": 0.7 + color_delta * 0.01,
                    "titration_type": "strong_acid_strong_base",
                },
                now_monotonic_s=100.0 + volume,
            )

        stopped = buffer.stop_recording()
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))
        predicted_rows = [row for row in rows if row.get("predicted_equivalence_volume_ml")]

        self.assertEqual(stopped["predicted_equivalence_source"], "typewise_frame_zone_classifier")
        self.assertEqual(stopped["predicted_equivalence_volume_ml"], 10.0)
        self.assertEqual(stopped["sample_concentration_from_predicted_equivalence_M"], 0.1)
        self.assertEqual(len(predicted_rows), 1)
        self.assertEqual(predicted_rows[0]["predicted_equivalence_model_key"], "fake:typewise")

    def test_live_csv_buffer_prefers_post_run_sensor_ranker_before_old_classifier(self):
        endpoint_model = {"artifact_type": "type_conditioned_sensor_endpoint_ranker_v1"}
        old_model = {"artifact_type": "typewise_frame_zone_classifier_v1"}
        buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv"),
            endpoint_prediction_model=endpoint_model,
            typewise_prediction_model=old_model,
        )
        buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=100.0,
            started_epoch_s=200.0,
            experiment_metadata={
                "titration_type": "strong_acid_strong_base",
                "sample_volume_ml": 10.0,
                "sample_valence": 1,
                "titrant_concentration_M": 0.1,
                "titrant_valence": 1,
            },
        )
        for index in range(1, 9):
            buffer.add(
                {
                    "frame_id": index,
                    "time_s": float(index),
                    "injected_volume_ml": 8.4 + index * 0.2,
                    "visible_H_mean": 20.0 + index * 0.1,
                    "visible_S_mean": 0.5 + index * 0.01,
                    "visible_V_mean": 0.7 + index * 0.01,
                    "thermal_raw_roi_p50": 1000.0 + index,
                    "thermal_raw_roi_p95": 1010.0 + index,
                },
                now_monotonic_s=100.0 + index,
            )
        expected = {
            "predicted_equivalence_volume_ml": 9.8,
            "predicted_equivalence_confidence": 0.8,
            "predicted_equivalence_source": "type_conditioned_sensor_endpoint_ranker",
            "predicted_equivalence_evidence": "fixed sensor ranker",
            "candidate_index": 4,
            "model_key": "type-conditioned-sensor-endpoint-v1",
        }

        with mock.patch.object(
            windows_live_collect,
            "predict_type_conditioned_sensor_equivalence",
            return_value=expected,
        ) as ranker, mock.patch.object(
            windows_live_collect,
            "predict_typewise_equivalence",
            side_effect=AssertionError("old classifier must not run"),
        ):
            stopped = buffer.stop_recording()

        ranker.assert_called_once()
        self.assertEqual(
            stopped["predicted_equivalence_source"],
            "type_conditioned_sensor_endpoint_ranker",
        )
        self.assertEqual(stopped["predicted_equivalence_volume_ml"], 9.8)
        self.assertEqual(stopped["sample_concentration_from_predicted_equivalence_M"], 0.098)
        self.assertEqual(
            stopped["predicted_equivalence_model_key"],
            "type-conditioned-sensor-endpoint-v1",
        )

    def test_live_csv_buffer_records_experiment_metadata_from_start_payload(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        metadata = windows_live_collect.start_payload_experiment_metadata(
            {
                "titrant_name": "NaOH",
                "titrant_concentration_M": 0.1,
                "titration_type": "weak_acid_strong_base",
                "sample_concentration_M": 0.1,
                "sample_volume_ml": 10.0,
                "sample_valence": 1,
                "titrant_valence": 1,
                "indicator": "phenolphthalein",
                "sample_name": "=HYPERLINK(\"http://example.invalid\")",
                "constants_source_id": "serjeant2043",
                "constants_candidate_count": 2,
                "constants_lookup_ambiguous": True,
                "constants_confirmation_status": "confirmed_by_user",
                "constants_warning": "+ambiguous",
                "selected_pka_value": 4.772,
                "activity_model": "davies",
                "standard_solution_uncertainty_note": "표준용액 농도는 사용자가 입력한 값",
                "ignored": "not written",
            }
        )

        started = buffer.start_recording(experiment_metadata=metadata)
        buffer.add({"frame_id": 1, "time_s": 0.04})
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertEqual(started["sample_name"], "'=HYPERLINK(\"http://example.invalid\")")
        self.assertEqual(rows[0]["sample_name"], "'=HYPERLINK(\"http://example.invalid\")")
        self.assertEqual(rows[0]["titrant_concentration_M"], "0.1")
        self.assertEqual(rows[0]["indicator"], "phenolphthalein")
        self.assertEqual(rows[0]["constants_source_id"], "serjeant2043")
        self.assertEqual(rows[0]["constants_candidate_count"], "2")
        self.assertEqual(rows[0]["constants_lookup_ambiguous"], "True")
        self.assertEqual(rows[0]["constants_confirmation_status"], "confirmed_by_user")
        self.assertEqual(rows[0]["constants_warning"], "'+ambiguous")
        self.assertEqual(rows[0]["selected_pka_value"], "4.772")
        self.assertGreater(float(started["theoretical_equivalence_pH"]), 8.0)
        self.assertEqual(rows[0]["theoretical_equivalence_pH"], str(started["theoretical_equivalence_pH"]))
        self.assertNotIn("ignored", rows[0])

    def test_build_pump_timeline_fields_labels_before_near_and_after(self):
        before = windows_live_collect.build_pump_timeline_fields(
            pump_elapsed_s=8.4,
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=9.0,
            equivalence_window_ml=0.05,
        )
        near = windows_live_collect.build_pump_timeline_fields(
            pump_elapsed_s=8.8,
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=9.0,
            equivalence_window_ml=0.05,
        )
        after = windows_live_collect.build_pump_timeline_fields(
            pump_elapsed_s=9.4,
            pump_rate_ml_per_s=1.0,
            theoretical_equivalence_volume_ml=9.0,
            equivalence_window_ml=0.05,
        )

        self.assertEqual(before["equivalence_window_label"], "before")
        self.assertEqual(near["equivalence_window_label"], "near_before")
        self.assertEqual(after["equivalence_window_label"], "after")

    def test_live_csv_buffer_records_only_between_start_and_stop(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        buffer.add({"frame_id": 0, "visible_R_mean": 10})
        started = buffer.start_recording()
        buffer.add({"frame_id": 1, "visible_R_mean": 20})
        stopped = buffer.stop_recording()
        buffer.add({"frame_id": 2, "visible_R_mean": 30})

        status = buffer.status()
        body = buffer.to_csv_bytes().decode("utf-8")
        rows = list(csv.DictReader(io.StringIO(body.lstrip("\ufeff"))))

        self.assertTrue(started["recording"])
        self.assertFalse(stopped["recording"])
        self.assertFalse(status["recording"])
        self.assertEqual(status["state"], "stopped")
        self.assertEqual(status["row_count"], 1)
        self.assertEqual(rows[0]["visible_R_mean"], "20")
        self.assertEqual([row["frame_id"] for row in rows], ["1"])

    def test_live_csv_buffer_duplicate_stop_keeps_finalizing_and_rejects_restart(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        started = buffer.start_recording(capture_session_required=True)
        self.assertTrue(
            buffer.add(
                {
                    "frame_id": 1,
                    "time_s": 0.04,
                    "capture_recording_session_id": started["session_id"],
                }
            )
        )

        first_stop = buffer.request_stop()
        second_stop = buffer.request_stop()

        self.assertTrue(first_stop["finalizing"])
        self.assertTrue(second_stop["finalizing"])
        self.assertEqual(second_stop["state"], "finalizing")
        self.assertEqual(second_stop["row_count"], 1)
        with self.assertRaisesRegex(RuntimeError, "while state is finalizing"):
            buffer.start_recording()
        self.assertEqual(buffer.status()["row_count"], 1)

    def test_live_csv_buffer_adds_session_row_index_elapsed_without_manual_label(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        buffer.start_recording(started_epoch_s=200.0, started_monotonic_s=100.0)
        buffer.add({"frame_id": 1, "time_s": 0.04}, now_monotonic_s=101.25)
        buffer.add({"frame_id": 2, "time_s": 0.08, "manual_label": "endpoint"}, now_monotonic_s=101.29)
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))
        status = buffer.status(now_monotonic_s=101.5)

        self.assertEqual(status["recording_elapsed_s"], 1.5)
        self.assertNotIn("manual_label", status)
        self.assertEqual(rows[0]["csv_session_id"], "1")
        self.assertEqual(rows[0]["csv_row_index"], "1")
        self.assertEqual(rows[0]["csv_recording_started_epoch_s"], "200.0")
        self.assertEqual(rows[0]["csv_recording_elapsed_s"], "1.25")
        self.assertNotIn("manual_label", rows[0])
        self.assertEqual(rows[0]["csv_mark_sequence"], "0")
        self.assertEqual(rows[1]["csv_row_index"], "2")
        self.assertNotIn("manual_label", rows[1])

    def test_live_csv_buffer_reports_rows_per_second_during_recording(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        buffer.start_recording(started_monotonic_s=100.0)
        for idx in range(1, 11):
            buffer.add({"frame_id": idx, "time_s": idx / 25.0}, now_monotonic_s=100.0 + idx / 25.0)

        status = buffer.status(now_monotonic_s=100.4)

        self.assertEqual(status["row_count"], 10)
        self.assertAlmostEqual(status["csv_rows_per_s"], 25.0, places=3)


    def test_live_csv_buffer_derives_temporal_ml_features(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        buffer.start_recording(started_monotonic_s=100.0, experiment_metadata={"titration_type": "weak_acid_strong_base"})
        buffer.add({"frame_id": 1, "time_s": 0.0, "visible_H_mean": 350, "visible_color_delta": 0, "thermal_roi_avg": 22.0, "thermal_roi_delta": 0.0, "sync_offset_ms": 5, "sync_quality": "good", "thermal_calibrated": True, "roi_state": "recording"}, now_monotonic_s=100.0)
        buffer.add({"frame_id": 2, "time_s": 0.5, "visible_H_mean": 10, "visible_color_delta": 4, "thermal_roi_avg": 22.5, "thermal_roi_delta": 0.5, "sync_offset_ms": -7, "sync_quality": "good", "thermal_calibrated": True, "roi_state": "recording"}, now_monotonic_s=100.5)
        buffer.add({"frame_id": 3, "time_s": 1.2, "visible_H_mean": 40, "visible_color_delta": 10, "thermal_roi_avg": 24.0, "thermal_roi_delta": 1.5, "sync_offset_ms": 9, "sync_quality": "good", "thermal_calibrated": True, "roi_state": "recording"}, now_monotonic_s=101.2)

        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertEqual(rows[-1]["titration_is_weak_acid_strong_base"], "1.0")
        self.assertEqual(rows[-1]["abs_sync_offset_ms"], "9.0")
        self.assertAlmostEqual(float(rows[-1]["visible_H_baseline_delta"]), 40.0, places=3)
        self.assertGreater(float(rows[-1]["thermal_roi_avg_slope_c_per_s"]), 0.0)
        self.assertEqual(rows[-1]["valid_for_training"], "1.0")

    def test_live_csv_buffer_refreshes_titration_one_hot_after_metadata_merge(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(experiment_metadata={"titration_type": "weak_acid_strong_base"})
        precomputed = {column: 0.0 for column in windows_live_collect.DERIVED_ML_COLUMNS}

        buffer.add({"frame_id": 1, "time_s": 0.04, **precomputed})
        rows = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))

        self.assertEqual(rows[0]["titration_is_weak_acid_strong_base"], "1.0")
        self.assertEqual(rows[0]["titration_is_strong_acid_strong_base"], "0.0")

    def test_build_live_payload_exposes_csv_download_status(self):
        thermal_features = {"thermal_raw_roi_avg": 5000.0, "thermal_raw_roi_min": 4990, "thermal_raw_roi_max": 5010}
        row = {"frame_id": 1, "time_s": 0.04, "status_label": "before"}

        payload = windows_live_collect.build_live_payload(
            thermal_features,
            row,
            csv_status={
                "session_id": 7,
                "row_count": 12,
                "path": "data/raw/live-training.csv",
                "recording": True,
                "state": "recording",
                "updated_epoch_s": 1779782400.0,
                "started_epoch_s": 1779782396.75,
                "csv_event_note": "trial 1",
                "csv_mark_sequence": 2,
                "recording_elapsed_s": 3.25,
                "csv_rows_per_s": 3.692308,
            },
        )

        self.assertEqual(payload["csv_session_id"], 7)
        self.assertEqual(payload["csv_row_count"], 12)
        self.assertEqual(payload["csv_path"], "data/raw/live-training.csv")
        self.assertEqual(payload["csv_download_url"], "/api/csv")
        self.assertTrue(payload["csv_recording"])
        self.assertEqual(payload["csv_state"], "recording")
        self.assertNotIn("csv_manual_label", payload)
        self.assertEqual(payload["csv_event_note"], "trial 1")
        self.assertEqual(payload["csv_mark_sequence"], 2)
        self.assertEqual(payload["csv_recording_elapsed_s"], 3.25)
        self.assertEqual(payload["csv_recording_started_epoch_s"], 1779782396.75)
        self.assertEqual(payload["csv_updated_epoch_s"], 1779782400.0)
        self.assertEqual(payload["csv_rows_per_s"], 3.692308)

        no_csv_payload = windows_live_collect.build_live_payload(thermal_features, row)
        self.assertIsNone(no_csv_payload["csv_updated_epoch_s"])
        self.assertIsNone(no_csv_payload["csv_session_id"])

    def test_live_control_state_updates_roi_settings(self):
        controls = windows_live_collect.LiveControlState(roi_auto_detect="both", visible_roi_detector="yolo")

        updated = controls.update_from_payload({"roi_auto_detect": "visible", "visible_roi_detector": "yolo"})

        self.assertEqual(updated["roi_auto_detect"], "visible")
        self.assertEqual(updated["visible_roi_detector"], "yolo")
        with self.assertRaisesRegex(ValueError, "visible_roi_detector"):
            controls.update_from_payload({"visible_roi_detector": "contrast"})
        with self.assertRaisesRegex(ValueError, "visible_roi_detector"):
            controls.update_from_payload({"visible_roi_detector": "unknown"})

        self.assertFalse(controls.snapshot()["yolo_available"])
        self.assertTrue(controls.set_yolo_available(True)["yolo_available"])

    def test_auto_update_reuses_last_good_mask_when_detection_is_flat(self):
        state = windows_live_collect.RoiSelectionState()
        mask = np.zeros((40, 40), dtype=bool)
        mask[10:25, 12:27] = True
        roi_mask = windows_live_collect.roi_mask_from_bool(mask, confidence=0.88, source="seed")
        state.update_auto(visible_mask=roi_mask, reason="auto:seed")
        flat_frame = np.full((40, 40, 3), 120, dtype=np.uint8)

        windows_live_collect.maybe_auto_update_rois(
            state,
            visible_frame=flat_frame,
            thermal_matrix=None,
            mode="visible",
            min_confidence=0.5,
        )

        visible_mask, _ = state.snapshot_masks()
        self.assertIsNotNone(visible_mask)
        self.assertEqual(visible_mask.area_px, roi_mask.area_px)
        self.assertEqual(visible_mask.stability, "reused_last_good")
        self.assertIn("reuse_last_good", state.status()["roi_source"])

    def test_process_pending_roi_clicks_links_visible_click_to_thermal_roi(self):
        state = windows_live_collect.RoiSelectionState(thermal_roi=Roi(96, 72, 64, 48))
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[70:175, 90:230] = 180
        matrix = np.full((192, 256), 5000, dtype=np.uint16)
        matrix[65:125, 105:165] = 5400

        state.push_click("thermal", 130, 90)
        state.push_click("visible", 150, 120)

        windows_live_collect.process_pending_roi_clicks(
            state,
            visible_frame=frame,
            thermal_matrix=matrix,
            link_mode="anchor",
        )

        visible_roi, thermal_roi = state.snapshot()
        self.assertIsNotNone(visible_roi)
        self.assertIsNotNone(thermal_roi)
        self.assertTrue(visible_roi.x <= 150 <= visible_roi.x + visible_roi.width)
        self.assertTrue(thermal_roi.x <= 130 <= thermal_roi.x + thermal_roi.width)
        self.assertEqual(state.status()["roi_error"], "")

    def test_auto_visible_index_skips_detected_mini2_stream(self):
        attempts = []
        released = []

        class BadVisibleCamera:
            def __init__(self, config):
                self.config = config

            def read_rgb(self):
                raise RuntimeError("not visible")

            def release(self):
                released.append(self.config.device_index)

        def factory(config):
            attempts.append(config.device_index)
            if config.device_index == 3:
                return FakeVisibleCamera()
            return BadVisibleCamera(config)

        args = Namespace(
            visible_index="auto",
            visible_max_index=5,
            visible_width=160,
            visible_height=120,
            visible_backend="MSMF",
        )

        camera, index = windows_live_collect.open_visible_camera(args, skip_indices={2}, camera_factory=factory)
        camera.release()

        self.assertEqual(index, 3)
        self.assertEqual(attempts, [0, 1, 3])
        self.assertEqual(released, [0, 1])

    def test_auto_visible_index_can_continue_without_visible_camera(self):
        class BadVisibleCamera:
            def __init__(self, config):
                self.config = config

            def read_rgb(self):
                raise RuntimeError("not visible")

            def release(self):
                pass

        args = Namespace(
            visible_index="auto",
            visible_max_index=2,
            visible_width=160,
            visible_height=120,
            visible_backend="MSMF",
        )

        camera, index = windows_live_collect.open_visible_camera(args, skip_indices=set(), camera_factory=BadVisibleCamera)

        self.assertIsNone(camera)
        self.assertIsNone(index)

    def test_timestamped_visible_buffer_returns_nearest_frame(self):
        buffer = windows_live_collect.VisibleFrameBuffer(maxlen=4)
        buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=0, timestamp_s=0.90, frame_rgb=rgb_frame(10)))
        buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=1, timestamp_s=1.03, frame_rgb=rgb_frame(40)))
        buffer.add(windows_live_collect.TimestampedVisibleFrame(frame_id=2, timestamp_s=1.10, frame_rgb=rgb_frame(90)))

        matched = buffer.nearest(1.00)

        self.assertIsNotNone(matched)
        self.assertEqual(matched.frame_id, 1)
        self.assertAlmostEqual(matched.timestamp_s, 1.03)

    def test_sync_metadata_uses_40ms_default_warning_boundary_for_25fps(self):
        good = windows_live_collect.build_sync_metadata(
            thermal_time_s=1.0,
            visible_time_s=1.039,
            max_sync_offset_ms=40.0,
        )
        warning = windows_live_collect.build_sync_metadata(
            thermal_time_s=1.0,
            visible_time_s=1.041,
            max_sync_offset_ms=40.0,
        )

        self.assertEqual(good["sync_quality"], "good")
        self.assertEqual(good["sync_warning"], "")
        self.assertEqual(warning["sync_quality"], "warning")
        self.assertIn("40", warning["sync_warning"])

    def test_timestamped_visible_buffer_returns_none_when_empty(self):
        buffer = windows_live_collect.VisibleFrameBuffer(maxlen=4)

        self.assertIsNone(buffer.nearest(1.00))

    def test_visible_thread_stores_timestamped_frames(self):
        camera = ShortVisibleCamera()
        start = time.perf_counter()
        worker = windows_live_collect.VisibleLatestFrameThread(camera, start_time=start)
        worker.start()
        time.sleep(0.05)

        latest = worker.latest_timestamped(timeout_s=0.1)
        worker.close()

        self.assertIsNotNone(latest)
        self.assertGreaterEqual(latest.timestamp_s, 0.0)
        self.assertGreaterEqual(latest.received_s, latest.timestamp_s)
        self.assertGreaterEqual(worker.count, 1)

    def test_mini2_capture_thread_drops_stale_frames_for_low_latency_preview(self):
        reader = FastMini2Reader()
        start = time.perf_counter()
        worker = windows_live_collect.Mini2CaptureThread(reader, start_time=start, max_queue=1)
        worker.start()
        time.sleep(0.04)

        captured = worker.read(timeout_s=0.2)
        worker.close()

        self.assertGreater(captured.frame_id, 0)
        self.assertGreater(worker.dropped_frames, 0)
        self.assertTrue(reader.released)

    def test_mini2_capture_thread_preserves_every_recording_frame_in_order(self):
        reader = FastMini2Reader()
        worker = windows_live_collect.Mini2CaptureThread(
            reader,
            start_time=time.perf_counter(),
            max_queue=1,
            max_recording_queue=128,
        )
        worker.start()
        worker.begin_recording(7)
        time.sleep(0.04)
        stopped = worker.end_recording(7)
        expected = int(stopped["recording_captured_frames"])
        captured = []
        for _ in range(expected):
            frame = worker.read(timeout_s=0.5)
            captured.append(frame)
            worker.mark_processed(frame)
        final = worker.recording_status()
        worker.close()

        self.assertGreater(expected, 1)
        self.assertEqual([frame.recording_session_id for frame in captured], [7] * expected)
        frame_ids = [frame.frame_id for frame in captured]
        self.assertEqual(frame_ids, list(range(frame_ids[0], frame_ids[0] + expected)))
        self.assertEqual(final["recording_processed_frames"], expected)
        self.assertEqual(final["recording_dropped_frames"], 0)
        self.assertEqual(final["recording_backlog_frames"], 0)
        self.assertTrue(final["drained"])

    def test_mini2_capture_thread_counts_a_rejected_csv_row_as_recording_loss(self):
        worker = windows_live_collect.Mini2CaptureThread(
            FastMini2Reader(),
            start_time=time.perf_counter(),
            max_recording_queue=8,
        )
        worker.begin_recording(3)
        worker.start()
        captured = worker.read(timeout_s=0.5)
        worker.end_recording(3)
        worker.mark_processed(captured, stored=False)
        final = worker.recording_status()
        worker.close()

        self.assertEqual(final["recording_dropped_frames"], 1)
        self.assertEqual(final["recording_processed_frames"], 1)

    def test_live_csv_buffer_accepts_session_backlog_while_finalizing(self):
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        started = buffer.start_recording(started_monotonic_s=100.0, capture_session_required=True)
        session_id = int(started["session_id"])

        self.assertFalse(buffer.add({"time_s": 0.0, "capture_recording_session_id": 0}, now_monotonic_s=100.0))
        self.assertTrue(
            buffer.add(
                {"time_s": 0.04, "capture_recording_session_id": session_id},
                now_monotonic_s=100.04,
            )
        )
        requested = buffer.request_stop()
        self.assertTrue(requested["finalizing"])
        self.assertTrue(
            buffer.add(
                {"time_s": 0.08, "capture_recording_session_id": session_id},
                now_monotonic_s=100.08,
            )
        )
        self.assertFalse(buffer.add({"time_s": 0.12, "capture_recording_session_id": 0}, now_monotonic_s=100.12))
        stopped = buffer.complete_stop()

        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(stopped["finalizing"])
        self.assertEqual(stopped["row_count"], 2)

    def test_normalizes_raw_opencv_vector_frames(self):
        raw = np.arange(MINI2_UVC_WIDTH * MINI2_UVC_HEIGHT * 2, dtype=np.uint8).reshape(1, -1)

        got = windows_live_collect.mini2_raw_bytes_from_opencv_frame(raw)

        self.assertEqual(len(got), MINI2_UVC_WIDTH * MINI2_UVC_HEIGHT * 2)
        self.assertEqual(got[:4], raw.reshape(-1).tobytes()[:4])

    def test_rejects_bgr_preview_instead_of_raw_bytes(self):
        bgr = np.zeros((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH, 3), dtype=np.uint8)

        with self.assertRaises(ValueError):
            windows_live_collect.mini2_raw_bytes_from_opencv_frame(bgr)

    def test_draw_roi_overlay_marks_rectangle_border(self):
        frame = np.zeros((12, 14, 3), dtype=np.uint8)
        marked = windows_live_collect.draw_roi_overlay(frame, Roi(3, 4, 5, 4), color=(0, 255, 80), thickness=2)

        self.assertEqual(marked[4, 3].tolist(), [0, 255, 80])
        self.assertEqual(marked[7, 7].tolist(), [0, 255, 80])
        self.assertEqual(marked[0, 0].tolist(), [0, 0, 0])

    def test_run_writes_merged_visible_and_thermal_feature_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "windows-live.csv"
            args = Namespace(
                frames=2,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="0,0,40,40",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.build_official_converter = lambda _args: FakeOfficialConverter()
            mini2 = FakeMini2Reader()
            visible = MaskCandidateVisibleCamera()
            try:
                windows_live_collect.run(args, mini2_reader=mini2, visible_camera=visible)
            finally:
                windows_live_collect.build_official_converter = old_builder

            self.assertTrue(out.exists())
            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertIn("thermal_roi_avg", rows[0])
            self.assertIn("visible_R_mean", rows[0])
            self.assertIn("thermal_time_s", rows[0])
            self.assertIn("visible_time_s", rows[0])
            self.assertIn("sync_offset_ms", rows[0])
            self.assertEqual(rows[0]["sync_method"], "nearest_visible_frame")
            self.assertIn(rows[0]["sync_quality"], {"good", "warning"})
            self.assertEqual(rows[0]["thermal_matrix_shape"], "roi-only:192x256")
            self.assertEqual(rows[0]["visible_capture_index"], "1")
            self.assertTrue(mini2.released)
            self.assertTrue(visible.released)
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["frames"], 2)
            self.assertEqual(summary["visible_frames"], 2)
            self.assertEqual(summary["full_matrix_csv_saved"], False)
            self.assertIn("sync_offset_abs_mean_ms", summary)
            self.assertIn("sync_offset_abs_max_ms", summary)
            self.assertIn("sync_warning_rows", summary)
            self.assertEqual(summary["sync_method"], "nearest_visible_frame")

    def test_run_auto_visible_mode_writes_mask_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "mask-live.csv"
            args = Namespace(
                frames=2,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="raw",
                visible_roi="auto",
                metadata_jpeg="missing.jpeg",
                dll_dir="missing_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="both",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            mini2 = MaskCandidateMini2Reader()
            visible = MaskCandidateVisibleCamera()
            old_loader = windows_live_collect.load_yolo_model
            windows_live_collect.load_yolo_model = lambda _model: fake_cup_yolo_model()
            try:
                windows_live_collect.run(args, mini2_reader=mini2, visible_camera=visible)
            finally:
                windows_live_collect.load_yolo_model = old_loader

            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["thermal_roi_shape"], "mask")
            self.assertEqual(rows[0]["visible_roi_shape"], "mask")
            self.assertGreater(int(float(rows[0]["thermal_mask_area_px"])), 0)
            self.assertGreater(int(float(rows[0]["visible_mask_area_px"])), 0)
            self.assertEqual(rows[0]["thermal_mask_source"], "thermal_contrast_candidate")
            self.assertEqual(rows[0]["visible_mask_source"], "yolo_mask:cup")
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["roi_auto_detect"], "both")

    def test_run_auto_roi_worker_path_does_not_call_sync_detectors_in_hot_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "worker-live.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="raw",
                visible_roi="auto",
                metadata_jpeg="missing.jpeg",
                dll_dir="missing_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="both",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                auto_roi_worker=1,
                auto_roi_result_max_age_ms=2000.0,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                visible_sync_max_age_ms=1000.0,
                print_every=0,
            )
            old_loader = windows_live_collect.load_yolo_model
            windows_live_collect.load_yolo_model = lambda _model: (_ for _ in ()).throw(AssertionError("YOLO should not load for thermal-only auto worker path"))
            try:
                windows_live_collect.run(
                    args,
                    mini2_reader=MaskCandidateMini2Reader(),
                    visible_camera=MaskCandidateVisibleCamera(),
                )
            finally:
                windows_live_collect.load_yolo_model = old_loader

            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["auto_roi_worker_enabled"], "True")
            self.assertIn(row["auto_roi_result_status"], {"submitted", "not_started"})

    def test_raw_preview_mode_does_not_build_official_converter_and_writes_thermal_bmp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw-live.csv"
            preview_dir = Path(tmp) / "preview"
            args = Namespace(
                frames=2,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="raw",
                visible_roi="auto",
                metadata_jpeg="missing.jpeg",
                dll_dir="missing_dll",
                output=str(out),
                stream_every=1,
                preview_dir=str(preview_dir),
                preview_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter

            def fail_builder(_args):
                raise AssertionError("raw preview must not build official Celsius converter")

            windows_live_collect.build_official_converter = fail_builder
            mini2 = FakeMini2Reader()
            visible = MaskCandidateVisibleCamera()
            try:
                windows_live_collect.run(args, mini2_reader=mini2, visible_camera=visible)
            finally:
                windows_live_collect.build_official_converter = old_builder

            self.assertTrue((preview_dir / "visible.bmp").is_file())
            self.assertTrue((preview_dir / "thermal.bmp").is_file())
            self.assertEqual((preview_dir / "thermal.bmp").read_bytes()[:2], b"BM")
            payload = json.loads((preview_dir / "thermal.json").read_text(encoding="utf-8"))
            self.assertIsNone(payload["temperature_avg_c"])
            self.assertEqual(payload["raw_avg"], 5001.0)
            self.assertEqual(payload["thermal_mode"], "mini2_uvc_raw_uncalibrated_preview")
            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["thermal_calibrated"], "False")
            self.assertIn("thermal_raw_roi_avg", rows[0])

    def test_write_live_preview_files_outputs_camera_bmp_and_temperature_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            preview_dir = Path(tmp) / "live"
            frame = rgb_frame(77)
            raw_matrix = np.arange(MINI2_MATRIX_SHAPE[0] * MINI2_MATRIX_SHAPE[1], dtype=np.uint16).reshape(MINI2_MATRIX_SHAPE)
            thermal_features = {
                "thermal_calibrated": True,
                "thermal_conversion_status": "ok",
                "thermal_roi_avg": 23.5,
                "thermal_roi_min": 22.0,
                "thermal_roi_max": 25.0,
                "thermal_roi_delta": 0.4,
                "thermal_raw_roi_avg": 5100,
                "thermal_raw_roi_min": 5000,
                "thermal_raw_roi_max": 5200,
                "thermal_raw_roi_delta": 12,
            }
            row = {
                "frame_id": 7,
                "time_s": 1.25,
                "status_label": "before",
                "sync_quality": "good",
                "sync_offset_ms": 3.2,
                "visible_capture_index": 1,
                "mini2_capture_index": 2,
            }

            windows_live_collect.write_live_preview(
                preview_dir,
                frame,
                thermal_features,
                row,
                raw_matrix=raw_matrix,
                visible_roi=Roi(10, 10, 20, 20),
                thermal_roi=Roi(96, 72, 64, 48),
            )

            visible = preview_dir / "visible.bmp"
            thermal_bmp = preview_dir / "thermal.bmp"
            thermal = preview_dir / "thermal.json"
            self.assertTrue(visible.is_file())
            self.assertTrue(thermal_bmp.is_file())
            self.assertEqual(visible.read_bytes()[:2], b"BM")
            self.assertEqual(thermal_bmp.read_bytes()[:2], b"BM")
            payload = json.loads(thermal.read_text(encoding="utf-8"))
            self.assertEqual(payload["frame_id"], 7)
            self.assertEqual(payload["temperature_avg_c"], 23.5)
            self.assertEqual(payload["temperature_min_c"], 22.0)
            self.assertEqual(payload["temperature_max_c"], 25.0)
            self.assertTrue(payload["celsius_allowed"])
            self.assertEqual(payload["temperature_provenance"], "windows_official_mini2_roi_scalar")
            self.assertEqual(payload["temperature_scope"], "thermal_roi")
            self.assertFalse(payload["full_matrix_celsius_allowed"])
            self.assertEqual(payload["raw_avg"], 5100.0)
            self.assertEqual(payload["sync_quality"], "good")
            self.assertEqual(payload["thermal_roi"], "96,72,64,48")
            self.assertEqual(payload["visible_roi"], "10,10,20,20")

    def test_windows_live_payload_is_accepted_by_shared_celsius_consumer(self):
        payload = windows_live_collect.build_live_payload(
            {
                "thermal_calibrated": True,
                "thermal_conversion_status": "ok",
                "thermal_roi_avg": 23.5,
                "thermal_roi_min": 22.0,
                "thermal_roi_max": 25.0,
            },
            {"frame_id": 7},
        )
        script = f"""
const fs = require('fs');
const assert = require('assert');
const code = fs.readFileSync('website/app.js', 'utf8');
eval(code.slice(code.indexOf('function parseFiniteNumber'), code.indexOf('function formatNumber')));
const payload = {json.dumps(payload)};
assert.strictEqual(hasTrustedCelsiusTemperature(payload), true);
assert.strictEqual(hasTrustedCelsiusTemperature({{...payload, temperature_provenance: ''}}), false);
"""
        subprocess.run(["node", "-e", script], check=True)

    def test_jpeg_bytes_encodes_stream_frame_without_bmp_file_polling(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is required for JPEG stream encoding")
        encoded = windows_live_collect.jpeg_bytes(rgb_frame(88), quality=70)

        self.assertTrue(encoded.startswith(b"\xff\xd8"))
        self.assertTrue(encoded.endswith(b"\xff\xd9"))

    def test_live_stream_state_publishes_latest_jpeg_and_sse_payload(self):
        state = windows_live_collect.LiveStreamState()
        visible_jpeg = b"\xff\xd8visible\xff\xd9"
        thermal_jpeg = b"\xff\xd8thermal\xff\xd9"
        payload = {"frame_id": 3, "temperature_avg_c": 22.5}

        state.publish(visible_jpeg=visible_jpeg, thermal_jpeg=thermal_jpeg, metadata=payload)

        visible = state.wait_jpeg("visible", last_sequence=0, timeout_s=0.1)
        thermal = state.wait_jpeg("thermal", last_sequence=0, timeout_s=0.1)
        metadata = state.wait_metadata(last_sequence=0, timeout_s=0.1)
        self.assertIsNotNone(visible)
        self.assertIsNotNone(thermal)
        self.assertIsNotNone(metadata)
        self.assertEqual(visible[1], visible_jpeg)
        self.assertEqual(thermal[1], thermal_jpeg)
        self.assertEqual(metadata[1]["frame_id"], 3)
        self.assertEqual(metadata[1]["visible_stream_sequence"], visible[0])
        self.assertEqual(metadata[1]["thermal_stream_sequence"], thermal[0])
        self.assertIsNotNone(metadata[1]["latency_visible_stream_age_ms"])
        self.assertIsNotNone(metadata[1]["latency_thermal_stream_age_ms"])

    def test_live_stream_state_uses_independent_jpeg_sequences(self):
        state = windows_live_collect.LiveStreamState()

        state.publish_visible(b"\xff\xd8visible-a\xff\xd9")
        visible = state.wait_jpeg("visible", last_sequence=0, timeout_s=0.1)
        self.assertIsNotNone(visible)

        state.publish_thermal(b"\xff\xd8thermal-a\xff\xd9")
        stale_visible = state.wait_jpeg("visible", last_sequence=visible[0], timeout_s=0.01)
        fresh_thermal = state.wait_jpeg("thermal", last_sequence=0, timeout_s=0.1)

        self.assertIsNone(stale_visible)
        self.assertIsNotNone(fresh_thermal)
        self.assertEqual(fresh_thermal[1], b"\xff\xd8thermal-a\xff\xd9")

    def test_visible_latest_thread_can_wait_for_next_frame_without_mini2_loop(self):
        camera = ShortVisibleCamera()
        worker = windows_live_collect.VisibleLatestFrameThread(camera, start_time=time.perf_counter())
        worker.start()
        try:
            first = worker.wait_next(last_frame_id=-1, timeout_s=0.5)
            second = worker.wait_next(last_frame_id=first.frame_id, timeout_s=0.5)
        finally:
            worker.close()

        self.assertEqual(first.frame_id, 0)
        self.assertEqual(second.frame_id, 1)

    def test_visible_latest_thread_waits_briefly_for_closer_future_sync_frame(self):
        camera = DelayedSecondVisibleCamera()
        worker = windows_live_collect.VisibleLatestFrameThread(camera, start_time=time.perf_counter())
        worker.start()
        try:
            first = worker.wait_next(last_frame_id=-1, timeout_s=0.5)
            target_s = first.timestamp_s + 0.015

            matched = worker.nearest(
                target_s,
                timeout_s=0.5,
                future_wait_s=0.2,
                future_wait_min_gap_s=0.0,
            )
        finally:
            worker.close()

        self.assertIsNotNone(matched)
        self.assertEqual(matched.frame_id, 1)
        self.assertLess(abs(matched.timestamp_s - target_s), abs(first.timestamp_s - target_s))

    def test_single_stream_publisher_updates_visible_without_metadata_or_thermal(self):
        state = windows_live_collect.LiveStreamState()
        encoded = []

        def fake_encoder(frame, *, quality=75):
            encoded.append((quality, int(frame[0, 0, 0])))
            return f"jpeg-{encoded[-1][1]}".encode("ascii")

        publisher = windows_live_collect.LiveJpegStreamPublisher(
            state,
            kind="visible",
            jpeg_quality=55,
            encoder=fake_encoder,
        )
        publisher.start()
        try:
            publisher.submit(rgb_frame(77))
            visible = state.wait_jpeg("visible", last_sequence=0, timeout_s=0.5)
            thermal = state.wait_jpeg("thermal", last_sequence=0, timeout_s=0.01)
            metadata = state.wait_metadata(last_sequence=0, timeout_s=0.01)
        finally:
            publisher.close()

        self.assertIsNotNone(visible)
        self.assertEqual(visible[1], b"jpeg-77")
        self.assertIsNone(thermal)
        self.assertIsNone(metadata)
        self.assertEqual(encoded, [(55, 77)])

    def test_single_stream_publisher_can_skip_extra_frame_copy_for_low_latency(self):
        state = windows_live_collect.LiveStreamState()
        frame = rgb_frame(91)
        seen_ids = []

        def fake_encoder(encoded_frame, *, quality=75):
            seen_ids.append(id(encoded_frame))
            return b"jpeg-no-copy"

        publisher = windows_live_collect.LiveJpegStreamPublisher(
            state,
            kind="visible",
            encoder=fake_encoder,
            copy_frame=False,
        )
        publisher.start()
        try:
            publisher.submit(frame)
            visible = state.wait_jpeg("visible", last_sequence=0, timeout_s=0.5)
        finally:
            publisher.close()

        self.assertIsNotNone(visible)
        self.assertEqual(seen_ids, [id(frame)])

    def test_visible_preview_stream_thread_publishes_frames_without_analysis_loop(self):
        camera = ShortVisibleCamera()
        visible_worker = windows_live_collect.VisibleLatestFrameThread(camera, start_time=time.perf_counter())
        published_red_values = []

        class RecordingPublisher:
            def submit(self, frame):
                published_red_values.append(int(frame[0, 0, 0]))

        preview_worker = windows_live_collect.VisiblePreviewStreamThread(
            visible_worker,
            RecordingPublisher(),
            wait_timeout_s=0.1,
        )
        preview_worker.start()
        visible_worker.start()
        try:
            deadline = time.monotonic() + 1.0
            while len(published_red_values) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
        finally:
            preview_worker.close()
            visible_worker.close()

        self.assertEqual(published_red_values[:2], [20, 21])

    def test_live_stream_server_accepts_roi_click_post(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-click",
                data=b'{"target":"visible","x":120,"y":80}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(payload["ok"])
        self.assertEqual(roi_state.pop_clicks(), [("visible", 120, 80)])

    def test_live_stream_server_applies_visible_auto_candidate_immediately_from_latest_visible_frame(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        handle.server.visible_frame_provider = lambda: np.full((120, 160, 3), 24, dtype=np.uint8)
        handle.server.visible_candidate_detector = lambda frame: windows_live_collect.RoiDetectionResult(
            Roi(40, 30, 80, 60),
            0.9,
            "yolo_visible_candidate:cup",
            mask=windows_live_collect.roi_mask_from_bool(
                np.pad(np.ones((60, 80), dtype=bool), ((30, 30), (40, 40))),
                confidence=0.9,
                source="yolo_mask:cup",
            ),
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-auto-candidate",
                data=b'{"target":"visible"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, thermal_roi = roi_state.snapshot()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applied_now"])
        self.assertEqual(visible_roi, Roi(40, 30, 80, 60))
        self.assertIsNone(thermal_roi)
        self.assertEqual(payload["roi"]["visible_roi"], "40,30,80,60")
        self.assertEqual(payload["reason"], "yolo_visible_candidate:cup")
        self.assertEqual(payload["confidence"], 0.9)

    def test_live_stream_server_applies_both_auto_candidates_immediately_from_latest_frames(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        handle.server.visible_frame_provider = lambda: np.full((120, 160, 3), 24, dtype=np.uint8)
        handle.server.thermal_matrix_provider = lambda: np.pad(
            np.full((52, 64), 5000, dtype=np.uint16),
            ((70, 70), (96, 96)),
            constant_values=5600,
        )
        handle.server.visible_candidate_detector = lambda frame: windows_live_collect.RoiDetectionResult(
            Roi(40, 30, 80, 60),
            0.9,
            "yolo_visible_candidate:cup",
            mask=windows_live_collect.roi_mask_from_bool(
                np.pad(np.ones((60, 80), dtype=bool), ((30, 30), (40, 40))),
                confidence=0.9,
                source="yolo_mask:cup",
            ),
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-auto-candidate",
                data=b'{"target":"both"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, thermal_roi = roi_state.snapshot()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applied_now"])
        self.assertEqual(visible_roi, Roi(40, 30, 80, 60))
        self.assertIsNotNone(thermal_roi)
        self.assertEqual(payload["roi"]["visible_roi"], "40,30,80,60")
        self.assertIn("yolo_visible_candidate:cup", payload["reason"])
        self.assertIn("thermal_contrast_candidate", payload["reason"])

    def test_live_stream_server_applies_visible_candidate_from_both_request_even_when_thermal_waits(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        handle.server.visible_frame_provider = lambda: np.full((120, 160, 3), 24, dtype=np.uint8)
        handle.server.thermal_matrix_provider = lambda: None
        handle.server.visible_candidate_detector = lambda frame: windows_live_collect.RoiDetectionResult(
            Roi(40, 30, 80, 60),
            0.9,
            "yolo_visible_candidate:cup",
            mask=windows_live_collect.roi_mask_from_bool(
                np.pad(np.ones((60, 80), dtype=bool), ((30, 30), (40, 40))),
                confidence=0.9,
                source="yolo_mask:cup",
            ),
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-auto-candidate",
                data=b'{"target":"both"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, thermal_roi = roi_state.snapshot()
        status = roi_state.status()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["applied_now"])
        self.assertEqual(visible_roi, Roi(40, 30, 80, 60))
        self.assertIsNone(thermal_roi)
        self.assertEqual(payload["roi"]["visible_roi"], "40,30,80,60")
        self.assertIn("yolo_visible_candidate:cup", payload["reason"])
        self.assertIn("queued_waiting_for_thermal_frame", payload["reason"])
        self.assertEqual(status["pending_auto_candidate_requests"], 1)
        self.assertEqual(status["pending_auto_candidate_target"], "thermal")

    def test_live_stream_server_accepts_manual_lasso_polygon_roi(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-polygon",
                data=json.dumps(
                    {
                        "target": "visible",
                        "frame_width": 12,
                        "frame_height": 12,
                        "points": [
                            {"x": 2, "y": 2},
                            {"x": 8, "y": 2},
                            {"x": 8, "y": 8},
                            {"x": 2, "y": 8},
                        ],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, thermal_roi = roi_state.snapshot()
        visible_mask, _ = roi_state.snapshot_masks()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["roi_polygon"], "2,2,6,6")
        self.assertEqual(payload["roi"]["visible_roi_shape"], "mask")
        self.assertEqual(payload["roi"]["visible_mask_source"], "manual_lasso")
        self.assertEqual(visible_roi, Roi(2, 2, 6, 6))
        self.assertIsNone(thermal_roi)
        self.assertIsNotNone(visible_mask)
        self.assertEqual(visible_mask.area_px, 36)

    def test_live_stream_server_refines_manual_lasso_with_latest_visible_frame_boundary(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        frame = np.zeros((24, 24, 3), dtype=np.uint8)
        frame[8:16, 8:16] = [190, 50, 50]
        handle.server.visible_frame_provider = lambda: frame
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-polygon",
                data=json.dumps(
                    {
                        "target": "visible",
                        "frame_width": 24,
                        "frame_height": 24,
                        "boundary_refine": True,
                        "points": [
                            {"x": 5, "y": 5},
                            {"x": 19, "y": 5},
                            {"x": 19, "y": 19},
                            {"x": 5, "y": 19},
                        ],
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, _ = roi_state.snapshot()
        visible_mask, _ = roi_state.snapshot_masks()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["roi"]["visible_mask_source"], "manual_lasso_edge_refined")
        self.assertIsNotNone(visible_roi)
        self.assertGreaterEqual(visible_roi.x, 7)
        self.assertGreaterEqual(visible_roi.y, 7)
        self.assertLessEqual(visible_roi.x + visible_roi.width, 17)
        self.assertLessEqual(visible_roi.y + visible_roi.height, 17)
        self.assertIsNotNone(visible_mask)
        self.assertLess(visible_mask.area_px, 14 * 14)

    def test_live_stream_server_reports_visible_yolo_candidate_failure_reason(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            roi_click_enabled=True,
        )
        handle.server.visible_frame_provider = lambda: np.full((120, 160, 3), 24, dtype=np.uint8)
        handle.server.visible_candidate_detector = lambda frame: windows_live_collect.RoiDetectionResult(
            None,
            0.0,
            "no_yolo_visible_candidate",
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-auto-candidate",
                data=b'{"target":"visible"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        visible_roi, thermal_roi = roi_state.snapshot()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["applied_now"])
        self.assertEqual(payload["reason"], "no_yolo_visible_candidate")
        self.assertEqual(payload["confidence"], 0.0)
        self.assertIsNone(visible_roi)
        self.assertIsNone(thermal_roi)


    def test_live_stream_server_accepts_runtime_settings_post(self):
        live_state = windows_live_collect.LiveStreamState()
        controls = windows_live_collect.LiveControlState(roi_auto_detect="both", visible_roi_detector="yolo")
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            controls=controls,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/settings",
                data=b'{"roi_auto_detect":"visible","visible_roi_detector":"yolo"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["settings"]["roi_auto_detect"], "visible")
        self.assertEqual(payload["settings"]["visible_roi_detector"], "yolo")
        self.assertEqual(controls.snapshot()["visible_roi_detector"], "yolo")

    def test_live_stream_server_rejects_rgb_contrast_visible_detector_setting(self):
        live_state = windows_live_collect.LiveStreamState()
        controls = windows_live_collect.LiveControlState(roi_auto_detect="both", visible_roi_detector="yolo")
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            controls=controls,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/settings",
                data=b'{"visible_roi_detector":"contrast"}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=1.0)
        finally:
            handle.close()

        self.assertEqual(ctx.exception.code, 400)
        self.assertEqual(controls.snapshot()["visible_roi_detector"], "yolo")

    def test_live_stream_server_accepts_roi_rectangle_and_lock_posts(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(thermal_roi=Roi(96, 72, 64, 48))
        roi_state.set_latest_shapes(visible_shape=(120, 160), thermal_shape=(192, 256))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
        )
        try:
            port = handle.server.server_address[1]
            rect_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-rect",
                data=b'{"target":"visible","x":12,"y":16,"width":40,"height":30}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(rect_request, timeout=1.0) as response:
                rect_payload = json.loads(response.read().decode("utf-8"))
            lock_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-lock",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(lock_request, timeout=1.0) as response:
                lock_payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(rect_payload["ok"])
        self.assertEqual(rect_payload["roi_rect"], "12,16,40,30")
        self.assertTrue(lock_payload["roi"]["roi_locked"])
        self.assertEqual(lock_payload["roi"]["roi_state"], "locked")
        self.assertEqual(lock_payload["roi"]["roi_session_id"], 1)

    def test_visible_frame_buffer_rejects_frames_outside_max_age(self):
        buffer = windows_live_collect.VisibleFrameBuffer(maxlen=4)
        buffer.add(windows_live_collect.TimestampedVisibleFrame(0, 0.0, rgb_frame(10)))
        buffer.add(windows_live_collect.TimestampedVisibleFrame(1, 1.0, rgb_frame(20)))

        close = buffer.nearest(1.05, max_age_s=0.1)
        stale = buffer.nearest(2.5, max_age_s=0.25)

        self.assertIsNotNone(close)
        self.assertEqual(close.frame_id, 1)
        self.assertIsNone(stale)

    def test_auto_roi_worker_replaces_pending_work_and_returns_candidates(self):
        calls = []

        def slow_visible(frame):
            red = int(frame[0, 0, 0])
            calls.append(red)
            time.sleep(0.04)
            return windows_live_collect.RoiDetectionResult(Roi(red, 1, 2, 3), 0.9, f"visible-{red}")

        worker = windows_live_collect.AutoRoiWorker(visible_detector_fn=slow_visible)
        settings = windows_live_collect.AutoRoiSettingsSnapshot.from_values(
            mode="visible",
            visible_detector="yolo",
            min_confidence=0.5,
            link_mode="anchor",
            settings_updated_epoch_s=1.0,
        )
        try:
            first_seq = worker.submit(visible_frame=rgb_frame(1), thermal_matrix=None, settings=settings, visible_frame_id=1)
            time.sleep(0.01)
            worker.submit(visible_frame=rgb_frame(2), thermal_matrix=None, settings=settings, visible_frame_id=2)
            latest_seq = worker.submit(visible_frame=rgb_frame(3), thermal_matrix=None, settings=settings, visible_frame_id=3)
            first = worker.latest_result(after_sequence=0, timeout_s=1.0)
            second = worker.latest_result(after_sequence=first.sequence, timeout_s=1.0)
        finally:
            worker.close()

        self.assertEqual(first_seq, 1)
        self.assertEqual(latest_seq, 3)
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(calls, [1, 3])
        self.assertEqual(second.visible_frame_id, 3)
        self.assertGreaterEqual(worker.dropped_pending, 1)

    def test_apply_auto_roi_worker_result_rejects_stale_settings_generation(self):
        state = windows_live_collect.RoiSelectionState()
        old_settings = windows_live_collect.AutoRoiSettingsSnapshot.from_values(
            mode="visible",
            visible_detector="yolo",
            min_confidence=0.5,
            link_mode="anchor",
            settings_updated_epoch_s=1.0,
        )
        new_settings = windows_live_collect.AutoRoiSettingsSnapshot.from_values(
            mode="thermal",
            visible_detector="yolo",
            min_confidence=0.5,
            link_mode="anchor",
            settings_updated_epoch_s=2.0,
        )
        result = windows_live_collect.AutoRoiWorkerResult(
            sequence=1,
            settings=old_settings,
            visible_frame_id=7,
            visible_timestamp_s=0.28,
            thermal_frame_id=None,
            thermal_timestamp_s=None,
            submitted_epoch_s=time.time(),
            completed_epoch_s=time.time(),
            visible_result=windows_live_collect.RoiDetectionResult(Roi(10, 10, 20, 20), 0.9, "yolo_visible_candidate:cup"),
        )

        applied, reason = windows_live_collect.apply_auto_roi_worker_result(
            state,
            result,
            current_settings=new_settings,
            visible_frame=rgb_frame(50),
            thermal_matrix=None,
        )

        self.assertFalse(applied)
        self.assertEqual(reason, "stale_auto_roi_settings")
        self.assertEqual(state.snapshot(), (None, None))

    def test_live_stream_server_serves_current_training_csv(self):
        live_state = windows_live_collect.LiveStreamState()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        csv_buffer.start_recording()
        csv_buffer.add({"frame_id": 1, "visible_R_mean": 121.25, "thermal_roi_avg": 23.5})
        csv_buffer.stop_recording()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            csv_buffer=csv_buffer,
        )
        try:
            port = handle.server.server_address[1]
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/csv/status", timeout=1.0) as response:
                status_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/csv", timeout=1.0) as response:
                csv_body = response.read().decode("utf-8")
                content_type = response.headers.get("Content-Type", "")
                disposition = response.headers.get("Content-Disposition", "")
        finally:
            handle.close()

        self.assertTrue(status_payload["ok"])
        self.assertEqual(status_payload["csv"]["row_count"], 1)
        self.assertIn("text/csv", content_type)
        self.assertIn("attachment", disposition)
        self.assertIn("visible_R_mean", csv_body)
        self.assertIn("121.25", csv_body)

    def test_auto_reconnect_pump_bridge_retries_after_startup_missing_port(self):
        serials = []
        resolver_calls = []

        def resolver(requested):
            resolver_calls.append(requested)
            return "" if len(resolver_calls) == 1 else "COM9"

        def serial_factory(port, baud, timeout, write_timeout):
            serial_obj = FakeAbcSerial([b"PUMP RUNNING b 120000\n"])
            serial_obj.port = port
            serial_obj.baud = baud
            serials.append(serial_obj)
            return serial_obj

        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            baud=9600,
            resolver=resolver,
            serial_factory=serial_factory,
            open_reset_delay_s=0,
            start_background=False,
        )
        try:
            bridge.warmup()
            self.assertFalse(bridge.status()["connected"])

            result = bridge.send("b")

            self.assertEqual(result["port"], "COM9")
            self.assertTrue(bridge.status()["connected"])
            self.assertEqual(serials[-1].writes, [b"b"])
        finally:
            bridge.close()

    def test_auto_reconnect_bridge_auto_detects_original_legacy_firmware(self):
        serial_obj = FakeAbcSerial()
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
            protocol_mode="auto",
            start_background=False,
        )
        try:
            bridge.warmup()
            status = bridge.status()
            self.assertTrue(status["connected"])
            self.assertEqual(status["firmware_protocol"], "legacy_abc")
            self.assertFalse(status["supports_firmware_guard"])
            self.assertFalse(status["supports_step_pulse"])

            armed = bridge.send("G 2500\n")
            started = bridge.send_guarded_direction("b", lambda: True)
            stopped = bridge.send("c")
        finally:
            bridge.close()

        self.assertEqual(armed["guard_scope"], "host_only")
        self.assertTrue(started["pump_running"])
        self.assertFalse(started["acknowledged"])
        self.assertTrue(stopped["stop_sent"])
        self.assertEqual(serial_obj.writes, [b"Q\n", b"Q\n", b"Q\n", b"b", b"c"])

    def test_auto_reconnect_bridge_retries_lost_version_query_without_motion(self):
        class LostQuerySerial(FakeAbcSerial):
            def readline(self):
                if self.writes.count(b"Q\n") >= 2:
                    return b"PUMP FW 2 PULSE b GUARD 1\r\n"
                return b""

        serial_obj = LostQuerySerial()
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto", resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0, protocol_mode="auto", start_background=False,
        )
        try:
            bridge.warmup()
            self.assertTrue(bridge.status()["supports_step_pulse"])
            self.assertEqual(serial_obj.writes, [b"Q\n", b"Q\n", b"V\n"])
        finally:
            bridge.close()

    def test_auto_reconnect_bridge_auto_detects_acknowledged_firmware(self):
        serial_obj = FakeAbcSerial(
            [
                b"PUMP FW 2 PULSE b GUARD 1\r\n",
                b"",
                b"GUARD ARMED 2500\r\n",
            ]
        )
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
            protocol_mode="auto",
            start_background=False,
        )
        try:
            bridge.warmup()
            status = bridge.status()
            self.assertEqual(status["firmware_protocol"], "ack_v2")
            self.assertTrue(status["supports_firmware_guard"])
            self.assertTrue(status["supports_step_pulse"])
            self.assertEqual(status["firmware_pulse_direction"], "b")
            acknowledgement = bridge.send("G 2500\n")
        finally:
            bridge.close()

        self.assertEqual(acknowledgement, "GUARD ARMED 2500")
        self.assertEqual(serial_obj.writes, [b"Q\n", b"V\n", b"G 2500\n"])

    def test_auto_reconnect_bridge_does_not_claim_step_for_unversioned_ack_firmware(self):
        serial_obj = FakeAbcSerial([b"GUARD IDLE 0\r\n"])
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
            protocol_mode="auto",
            start_background=False,
        )
        try:
            bridge.warmup()
            status = bridge.status()
        finally:
            bridge.close()

        self.assertEqual(status["firmware_protocol"], "ack_v1")
        self.assertTrue(status["supports_firmware_guard"])
        self.assertFalse(status["supports_step_pulse"])
        self.assertEqual(status["firmware_pulse_direction"], "")

    def test_original_legacy_firmware_manual_start_uses_host_only_guard(self):
        serial_obj = FakeAbcSerial()
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
            protocol_mode="auto",
            start_background=False,
        )
        guard = windows_live_collect.AbsolutePumpSafetyGuard(
            bridge.send,
            direction_sender=bridge.send_guarded_direction,
            watchdog_interval_s=0.01,
        )
        try:
            bridge.warmup()
            started = guard.start(
                direction_command="b",
                maximum_pump_rate_ml_per_s=1.0,
                requested_maximum_volume_ml=1.0,
                requested_maximum_run_time_s=10.0,
            )
            stopped = guard.stop("test_stop")
        finally:
            guard.close()
            bridge.close()

        self.assertTrue(started["absolute_guard_armed"])
        self.assertEqual(started["absolute_guard_scope"], "host_only")
        self.assertEqual(started["absolute_guard_reason"], "absolute_limits_armed_host_only")
        self.assertEqual(stopped["absolute_guard_stop_status"], "sent")
        self.assertIn(b"b", serial_obj.writes)
        self.assertIn(b"c", serial_obj.writes)

    def test_pump_serial_bridge_returns_firmware_guard_acknowledgement(self):
        serial_obj = FakeAbcSerial([b"GUARD ARMED 2500\r\n"])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            acknowledgement = bridge.send("G 2500\n")
        finally:
            bridge.close()

        self.assertEqual(acknowledgement, "GUARD ARMED 2500")
        self.assertEqual(serial_obj.writes, [b"G 2500\n"])

    def test_pump_serial_bridge_requires_exact_rate_ack_and_fails_stopped(self):
        accepted_serial = FakeAbcSerial([b"RATE ACCEPTED 25\r\n"])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8", serial_factory=lambda *args, **kwargs: accepted_serial,
            open_reset_delay_s=0,
        )
        try:
            self.assertEqual(bridge.send("RATE 25\n"), "RATE ACCEPTED 25")
        finally:
            bridge.close()
        self.assertEqual(accepted_serial.writes, [b"RATE 25\n"])

        mismatched_serial = FakeAbcSerial([b"RATE ACCEPTED 24\r\n"])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8", serial_factory=lambda *args, **kwargs: mismatched_serial,
            open_reset_delay_s=0,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "exact requested rate"):
                bridge.send("RATE 25\n")
        finally:
            bridge.close()
        self.assertEqual(mismatched_serial.writes, [b"RATE 25\n", b"c"])

    def test_variable_rate_capability_requires_exact_v_query_response(self):
        serial_obj = FakeAbcSerial([
            b"PUMP FW 2 PULSE b GUARD 1\r\n",
            b"PUMP SPEED 1\r\n",
        ])
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto", resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0, protocol_mode="auto", start_background=False,
        )
        try:
            bridge.warmup()
            self.assertTrue(bridge.status()["supports_variable_rate"])
        finally:
            bridge.close()
        self.assertEqual(serial_obj.writes, [b"Q\n", b"V\n"])

    def test_slow_restart_wire_order_is_stop_rate_guard_direction(self):
        serial_obj = FakeAbcSerial([
            b"PUMP STOPPED COMMAND\r\n",
            b"RATE ACCEPTED 25\r\n",
            b"GUARD ARMED 4000\r\n",
            b"PUMP RUNNING b 4000\r\n",
            b"PUMP STOPPED COMMAND\r\n",
        ])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8", serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        guard = windows_live_collect.AbsolutePumpSafetyGuard(
            bridge.send, direction_sender=bridge.send_guarded_direction,
            monotonic=lambda: 100.0,
        )
        try:
            bridge.send("c")
            status = windows_live_collect.start_guarded_continuous_at_rate(
                command_sender=bridge.send, guard=guard, direction_command="b",
                rate_steps_per_s=25, maximum_rate_ml_per_s=1.0,
                remaining_volume_ml=10.0, absolute_deadline_monotonic_s=104.0,
                can_restart=lambda: True,
            )
            guard.stop("test_complete")
        finally:
            guard.close()
            bridge.close()

        self.assertTrue(status["absolute_guard_armed"])
        self.assertEqual(
            serial_obj.writes,
            [b"c", b"RATE 25\n", b"G 4000\n", b"b", b"c"],
        )

    def test_csv_continuous_time_begins_at_direction_write_not_ack(self):
        clock = {"now": 100.0}

        class DelayedDirectionAckSerial(FakeAbcSerial):
            def readline(self):
                response = super().readline()
                if response.startswith(b"PUMP RUNNING"):
                    clock["now"] = 100.5
                return response

        serial_obj = DelayedDirectionAckSerial([
            b"GUARD ARMED 9500\r\n", b"PUMP RUNNING b 9500\r\n",
            b"PUMP STOPPED COMMAND\r\n",
        ])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8", serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        guard = windows_live_collect.AbsolutePumpSafetyGuard(
            bridge.send, direction_sender=bridge.send_guarded_direction,
            monotonic=lambda: clock["now"],
        )
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv"))
        buffer.start_recording(pump_rate_ml_per_s=1.0, started_monotonic_s=100.0)
        buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=False)
        try:
            clock["now"] = 100.5
            with mock.patch.object(windows_live_collect.time, "perf_counter", return_value=100.2):
                status = guard.start(
                    direction_command="b", maximum_pump_rate_ml_per_s=1.0,
                    absolute_deadline_monotonic_s=110.0,
                )
            buffer.resume_commanded_pump_timeline(
                now_monotonic_s=status["direction_written_monotonic_s"]
            )
            timeline = buffer.status(now_monotonic_s=100.5)
        finally:
            guard.stop("test")
            guard.close()
            bridge.close()

        self.assertEqual(status["direction_written_monotonic_s"], 100.2)
        self.assertAlmostEqual(timeline["pump_elapsed_s"], 0.3)
        self.assertAlmostEqual(timeline["injected_volume_ml"], 0.3)

    def test_pump_serial_bridge_requires_direction_ack_with_same_guard_deadline(self):
        serial_obj = FakeAbcSerial(
            [b"GUARD ARMED 2500\r\n", b"PUMP RUNNING b 2500\r\n"]
        )
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            bridge.send("G 2500\n")
            result = bridge.send("b")
        finally:
            bridge.close()

        self.assertEqual(result["firmware_ack"], "PUMP RUNNING b 2500")
        self.assertEqual(serial_obj.writes, [b"G 2500\n", b"b"])

    def test_pump_serial_bridge_guarded_direction_cancellation_writes_no_direction(self):
        serial_obj = FakeAbcSerial([b"GUARD ARMED 2500\r\n"])
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            bridge.send("G 2500\n")
            result = bridge.send_guarded_direction("b", lambda: False)
        finally:
            bridge.close()

        self.assertTrue(result["direction_cancelled"])
        self.assertFalse(result["direction_written"])
        self.assertEqual(serial_obj.writes, [b"G 2500\n"])

    def test_pump_serial_bridge_guarded_direction_keeps_exact_guard_deadline_check(self):
        serial_obj = FakeAbcSerial(
            [b"GUARD ARMED 2500\r\n", b"PUMP RUNNING b 120000\r\n"]
        )
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            bridge.send("G 2500\n")
            with self.assertRaisesRegex(RuntimeError, "different safety deadline"):
                bridge.send_guarded_direction("b", lambda: True)
        finally:
            bridge.close()

        self.assertEqual(serial_obj.writes, [b"G 2500\n", b"b", b"c"])

    def test_auto_reconnect_bridge_guarded_direction_requires_armed_firmware(self):
        serial_obj = FakeAbcSerial()
        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            resolver=lambda requested: "COM9",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
            start_background=False,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "guard must be armed"):
                bridge.send_guarded_direction("b", lambda: True)
        finally:
            bridge.close()

        self.assertEqual(serial_obj.writes, [])

    def test_pump_serial_bridge_stops_when_direction_ack_uses_wrong_deadline(self):
        serial_obj = FakeAbcSerial(
            [b"GUARD ARMED 2500\r\n", b"PUMP RUNNING b 120000\r\n"]
        )
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            bridge.send("G 2500\n")
            with self.assertRaisesRegex(RuntimeError, "different safety deadline"):
                bridge.send("b")
        finally:
            bridge.close()

        self.assertEqual(serial_obj.writes, [b"G 2500\n", b"b", b"c"])

    def test_auto_reconnect_bridge_stops_without_replaying_wrong_direction_ack(self):
        serials = []

        def serial_factory(port, baud, timeout, write_timeout):
            serial_obj = FakeAbcSerial(
                [b"GUARD ARMED 2500\r\n", b"PUMP RUNNING b 120000\r\n"]
            )
            serials.append(serial_obj)
            return serial_obj

        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            baud=9600,
            resolver=lambda requested: "COM9",
            serial_factory=serial_factory,
            open_reset_delay_s=0,
            start_background=False,
        )
        try:
            bridge.send("G 2500\n")
            with self.assertRaisesRegex(RuntimeError, "different safety deadline"):
                bridge.send("b")
        finally:
            bridge.close()

        self.assertEqual(len(serials), 1)
        self.assertEqual(serials[0].writes, [b"G 2500\n", b"b", b"c"])

    def test_pump_serial_bridge_accepts_acknowledged_bounded_step_pulse(self):
        serial_obj = FakeAbcSerial(
            [b"STEP ACCEPTED 5\r\n", b"PUMP STOPPED PULSE_COMPLETE\r\n"]
        )
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            acknowledgement = bridge.send("STEP 5\n")
            with self.assertRaisesRegex(ValueError, "1..200"):
                bridge.send("STEP 201\n")
        finally:
            bridge.close()

        self.assertEqual(acknowledgement, "STEP ACCEPTED 5")
        self.assertEqual(serial_obj.writes, [b"STEP 5\n"])

    def test_pump_serial_bridge_fails_closed_when_step_completion_is_not_confirmed(self):
        serial_obj = FakeAbcSerial(
            [b"STEP ACCEPTED 5\r\n", b"PUMP STOPPED ABSOLUTE_TIMEOUT\r\n"]
        )
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )
        try:
            with self.assertRaisesRegex(
                windows_live_collect.PulseDeliveryUncertainError,
                "unexpected reason",
            ):
                bridge.send("STEP 5\n")
        finally:
            bridge.close()

        self.assertEqual(serial_obj.writes, [b"STEP 5\n", b"c"])

    def test_emergency_stop_preempts_blocked_step_acknowledgement_wait(self):
        waiting_for_stop = threading.Event()
        stop_written = threading.Event()
        outcome = {}

        class BlockingStepSerial(FakeAbcSerial):
            def __init__(self):
                super().__init__()
                self.read_count = 0

            def write(self, data):
                super().write(data)
                if data == b"c":
                    stop_written.set()

            def readline(self):
                self.read_count += 1
                if self.read_count == 1:
                    return b"STEP ACCEPTED 200\r\n"
                waiting_for_stop.set()
                if not stop_written.wait(1.0):
                    raise RuntimeError("emergency stop did not preempt STEP wait")
                return b"PUMP STOPPED COMMAND\r\n"

        serial_obj = BlockingStepSerial()
        bridge = windows_live_collect.ArduinoAbcPumpSerialBridge(
            port="COM8",
            serial_factory=lambda *args, **kwargs: serial_obj,
            open_reset_delay_s=0,
        )

        def run_step():
            try:
                bridge.send("STEP 200\n")
            except Exception as exc:  # noqa: BLE001 - captured for thread assertion.
                outcome["error"] = exc

        thread = threading.Thread(target=run_step)
        try:
            thread.start()
            self.assertTrue(waiting_for_stop.wait(1.0))
            emergency = bridge.emergency_stop()
            thread.join(1.0)
        finally:
            bridge.close()

        self.assertTrue(emergency["sent"])
        self.assertTrue(stop_written.is_set())
        self.assertFalse(thread.is_alive())
        self.assertIsInstance(
            outcome.get("error"),
            windows_live_collect.PulseDeliveryUncertainError,
        )
        self.assertEqual(serial_obj.writes[:2], [b"STEP 200\n", b"c"])

    def test_auto_reconnect_bridge_never_replays_an_uncertain_step(self):
        serials = []

        def serial_factory(port, baud, timeout, write_timeout):
            serial_obj = FakeAbcSerial(
                [b"STEP ACCEPTED 5\r\n", b"PUMP STOPPED COMMAND\r\n"]
            )
            serials.append(serial_obj)
            return serial_obj

        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            baud=9600,
            resolver=lambda requested: "COM9",
            serial_factory=serial_factory,
            open_reset_delay_s=0,
            start_background=False,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "unexpected reason"):
                bridge.send("STEP 5\n")
        finally:
            bridge.close()

        self.assertEqual(len(serials), 1)
        self.assertEqual(serials[0].writes, [b"STEP 5\n", b"c"])

    def test_endpoint_pulse_runtime_stops_continuous_then_steps_and_waits(self):
        commands = []
        safety_stops = []
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(pump_rate_ml_per_s=1.0)
        buffer.begin_commanded_pump_timeline(running=True)

        def sender(command):
            commands.append(command)
            return f"STEP ACCEPTED {command.split()[1]}" if command.startswith("STEP ") else {"sent": True}

        def stop_continuous(reason):
            commands.append("c")
            buffer.pause_commanded_pump_timeline(state="pulse_settling")
            return {"absolute_guard_stop_status": "sent", "reason": reason}

        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=sender,
            stop_continuous=stop_continuous,
            csv_buffer=buffer,
            on_safety_stop=lambda *values: safety_stops.append(values),
        )
        runtime.arm(
            session_id=1,
            requested=True,
            pump_started=True,
            pump_rate_ml_per_s=1.0,
            maximum_pump_rate_ml_per_s=1.0,
            pulse_ml_per_step_upper_bound=0.01,
            maximum_volume_ml=10.0,
            approach_score=0.2,
            pulse_steps=5,
            settle_time_s=0.5,
        )

        def observe(elapsed, score, volume=0.0, state="armed"):
            runtime.handle_auto_stop_status(
                {
                    "auto_stop_session_id": 1,
                    "auto_stop_state": state,
                    "auto_stop_baseline_ready": True,
                    "auto_stop_observation_elapsed_s": elapsed,
                    "auto_stop_observation_volume_ml": volume,
                    "auto_stop_endpoint_score": score,
                }
            )

        observe(0.0, 0.1)
        observe(0.1, 0.25)
        observe(0.59, 0.1)
        observe(0.60, 0.1)
        observe(0.66, 0.1, 0.05)
        observe(1.17, 0.1, 0.05)

        status = buffer.status()
        self.assertEqual(commands, ["c", "STEP 5\n", "STEP 5\n"])
        self.assertEqual(status["auto_stop_pulse_count"], 2)
        self.assertEqual(status["pump_pulse_steps_total"], 10)
        self.assertFalse(safety_stops)

    def test_endpoint_runtime_optional_slow_stage_preserves_conservative_budget(self):
        events = []
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv"))
        recording_start = time.perf_counter()
        buffer.start_recording(pump_rate_ml_per_s=1.0, started_monotonic_s=recording_start)
        buffer.begin_commanded_pump_timeline(now_monotonic_s=recording_start, running=True)

        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=lambda command: events.append(("command", command)),
            stop_continuous=lambda reason: events.append(("stop", reason)) or {},
            csv_buffer=buffer,
            on_safety_stop=lambda *values: events.append(("safety", values)),
            start_slow_continuous=lambda **kwargs: events.append(("restart", kwargs)) or {},
        )
        runtime.arm(
            session_id=1, requested=True, pump_started=True,
            pump_rate_ml_per_s=1.0, maximum_pump_rate_ml_per_s=1.2,
            pulse_ml_per_step_upper_bound=0.01, maximum_volume_ml=10.0,
            approach_score=0.6, slow_stage_enabled=True,
            slow_onset_score=0.3, slow_onset_duration_s=0.4,
            slow_rate_steps_per_s=25, absolute_maximum_run_time_s=20.0,
            absolute_deadline_monotonic_s=120.0,
        )

        for elapsed in (1.0, 1.4):
            runtime.handle_auto_stop_status({
                "auto_stop_session_id": 1, "auto_stop_state": "armed",
                "auto_stop_baseline_ready": True,
                "auto_stop_observation_elapsed_s": elapsed,
                "auto_stop_observation_volume_ml": 0.2,
                "auto_stop_endpoint_score": 0.35,
            })

        restart = next(value for kind, value in events if kind == "restart")
        status = buffer.status(now_monotonic_s=100.0)
        self.assertEqual(restart["rate_steps_per_s"], 25)
        self.assertEqual(restart["nominal_rate_ml_per_s"], 0.25)
        self.assertEqual(restart["absolute_deadline_monotonic_s"], 120.0)
        self.assertAlmostEqual(restart["remaining_volume_ml"], 8.32)
        self.assertEqual(status["auto_stop_pulse_conservative_volume_ml"], 1.68)
        self.assertEqual(status["pump_dosing_stage"], "slow_continuous")

    def test_confirmed_stop_time_refreshes_conservative_volume_before_slow_restart(self):
        clock = {"now": 100.0}
        restart_calls = []
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv"))
        buffer.start_recording(pump_rate_ml_per_s=1.0, started_monotonic_s=100.0)
        buffer.begin_commanded_pump_timeline(now_monotonic_s=100.0, running=True)

        def stop_continuous(reason):
            clock["now"] = 103.0  # STOP acknowledgement arrives 2 s after telemetry.
            return {"absolute_guard_stop_status": "sent"}

        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=lambda command: None,
            stop_continuous=stop_continuous,
            csv_buffer=buffer,
            on_safety_stop=lambda *values: None,
            start_slow_continuous=lambda **kwargs: restart_calls.append(kwargs) or {
                "direction_written_monotonic_s": 103.0
            },
        )
        runtime.arm(
            session_id=1, requested=True, pump_started=True,
            pump_rate_ml_per_s=1.0, maximum_pump_rate_ml_per_s=1.2,
            pulse_ml_per_step_upper_bound=0.01, maximum_volume_ml=10.0,
            approach_score=0.6, slow_stage_enabled=True,
            slow_onset_score=0.3, slow_onset_duration_s=0.0,
            slow_rate_steps_per_s=25, absolute_deadline_monotonic_s=120.0,
        )
        with mock.patch.object(windows_live_collect.time, "perf_counter", side_effect=lambda: clock["now"]):
            runtime.handle_auto_stop_status({
                "auto_stop_session_id": 1, "auto_stop_state": "armed",
                "auto_stop_baseline_ready": True,
                "auto_stop_observation_elapsed_s": 1.0,
                "auto_stop_observation_volume_ml": 0.1,
                "auto_stop_endpoint_score": 0.35,
            })

        self.assertAlmostEqual(restart_calls[0]["remaining_volume_ml"], 6.4)
        self.assertEqual(
            buffer.status(now_monotonic_s=103.0)["auto_stop_pulse_conservative_volume_ml"],
            3.6,
        )
        self.assertAlmostEqual(
            buffer.status(now_monotonic_s=104.0)["injected_volume_ml"], 3.25
        )

    def test_endpoint_pulse_runtime_uses_conservative_rate_and_pulse_ceiling(self):
        commands = []
        safety_stops = []
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        buffer.start_recording(pump_rate_ml_per_s=0.5)
        buffer.begin_commanded_pump_timeline(running=True)

        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=lambda command: commands.append(command) or f"STEP ACCEPTED {command.split()[1]}",
            stop_continuous=lambda reason: commands.append("c") or {"absolute_guard_stop_status": "sent"},
            csv_buffer=buffer,
            on_safety_stop=lambda *values: safety_stops.append(values),
        )
        runtime.arm(
            session_id=1,
            requested=True,
            pump_started=True,
            pump_rate_ml_per_s=0.5,
            maximum_pump_rate_ml_per_s=1.0,
            pulse_ml_per_step_upper_bound=0.01,
            maximum_volume_ml=0.151,
            approach_score=0.2,
            pulse_steps=5,
            settle_time_s=0.0,
        )

        def observe(elapsed, score, volume=0.0):
            runtime.handle_auto_stop_status(
                {
                    "auto_stop_session_id": 1,
                    "auto_stop_state": "armed",
                    "auto_stop_baseline_ready": True,
                    "auto_stop_observation_elapsed_s": elapsed,
                    "auto_stop_observation_volume_ml": volume,
                    "auto_stop_endpoint_score": score,
                }
            )

        observe(0.0, 0.1)
        observe(0.10, 0.25, 0.05)  # conservative continuous bound is 0.10 mL
        observe(0.10, 0.1, 0.05)   # one 0.05 mL upper-bound pulse is allowed
        observe(0.10, 0.1, 0.05)   # a second pulse would exceed 0.151 mL

        self.assertEqual(commands.count("STEP 5\n"), 1)
        self.assertTrue(safety_stops)
        status = buffer.status()
        self.assertEqual(status["auto_stop_pulse_conservative_volume_ml"], 0.15)
        self.assertEqual(status["auto_stop_pulse_reason"], "maximum_volume_would_be_exceeded")

    def test_endpoint_pulse_runtime_separates_nominal_csv_volume_from_safety_ceiling(self):
        commands = []
        buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )
        buffer.start_recording(
            pump_rate_ml_per_s=0.99,
            started_monotonic_s=100.0,
        )
        buffer.begin_commanded_pump_timeline(
            now_monotonic_s=100.0,
            running=False,
        )
        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=lambda command: commands.append(command)
            or f"STEP ACCEPTED {command.split()[1]}",
            stop_continuous=lambda reason: commands.append("c")
            or {"absolute_guard_stop_status": "sent"},
            csv_buffer=buffer,
            on_safety_stop=lambda *values: None,
        )
        armed = runtime.arm(
            session_id=1,
            requested=True,
            pump_started=True,
            pump_rate_ml_per_s=0.99,
            maximum_pump_rate_ml_per_s=1.05,
            pulse_ml_per_step_upper_bound=0.0105,
            pulse_nominal_ml_per_step=0.0099,
            maximum_volume_ml=10.0,
            dispense_direction="a",
            approach_score=0.2,
            pulse_steps=5,
            settle_time_s=0.0,
        )

        def observe(score):
            runtime.handle_auto_stop_status(
                {
                    "auto_stop_session_id": 1,
                    "auto_stop_state": "armed",
                    "auto_stop_baseline_ready": True,
                    "auto_stop_observation_elapsed_s": 0.0,
                    "auto_stop_observation_volume_ml": 0.0,
                    "auto_stop_endpoint_score": score,
                }
            )

        with mock.patch.object(windows_live_collect.time, "perf_counter", return_value=100.0):
            observe(0.1)
            observe(0.25)
            observe(0.1)

        status = buffer.status(now_monotonic_s=100.0)
        self.assertEqual(commands, ["c", "STEP 5\n"])
        self.assertEqual(armed["auto_stop_pulse_nominal_ml_per_step"], 0.0099)
        self.assertEqual(
            armed["auto_stop_pulse_configured_ml_per_step_upper_bound"],
            0.0105,
        )
        self.assertEqual(armed["auto_stop_pulse_nominal_volume_ml"], 0.0495)
        self.assertEqual(status["injected_volume_ml"], 0.0495)
        self.assertEqual(status["pump_elapsed_s"], 0.05)
        self.assertEqual(status["pump_nominal_pulse_volume_ml"], 0.0495)
        self.assertEqual(
            status["auto_stop_pulse_conservative_volume_ml"],
            0.0525,
        )

    def test_endpoint_pulse_runtime_rejects_invalid_dispense_direction(self):
        commands = []
        buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=commands.append,
            stop_continuous=commands.append,
            csv_buffer=buffer,
            on_safety_stop=lambda *values: None,
        )

        status = runtime.arm(
            session_id=1,
            requested=True,
            pump_started=True,
            pump_rate_ml_per_s=1.0,
            maximum_pump_rate_ml_per_s=1.0,
            pulse_ml_per_step_upper_bound=0.01,
            maximum_volume_ml=10.0,
            dispense_direction="x",
        )

        self.assertEqual(status["auto_stop_pulse_state"], "unavailable")
        self.assertEqual(status["auto_stop_pulse_reason"], "pulse_direction_invalid")
        self.assertEqual(commands, [])

    def test_auto_reconnect_pump_bridge_background_thread_connects_late_port(self):
        serials = []
        resolver_calls = []
        port_ready = {"value": False}

        def resolver(requested):
            resolver_calls.append(requested)
            return "COM7" if port_ready["value"] else ""

        def serial_factory(port, baud, timeout, write_timeout):
            serial_obj = FakeAbcSerial([b"PUMP RUNNING a 120000\n"])
            serial_obj.port = port
            serial_obj.baud = baud
            serials.append(serial_obj)
            return serial_obj

        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            baud=9600,
            resolver=resolver,
            serial_factory=serial_factory,
            retry_interval_s=0.2,
            open_reset_delay_s=0,
            start_background=True,
        )
        try:
            deadline = time.time() + 1.0
            while time.time() < deadline and bridge.status()["retry_count"] == 0:
                time.sleep(0.02)
            self.assertFalse(bridge.status()["connected"])

            port_ready["value"] = True
            deadline = time.time() + 1.2
            while time.time() < deadline and not bridge.status()["connected"]:
                time.sleep(0.02)

            self.assertTrue(bridge.status()["connected"])
            self.assertGreaterEqual(len(resolver_calls), 2)
            result = bridge.send("a")
            self.assertEqual(result["port"], "COM7")
            self.assertEqual(serials[-1].writes, [b"a"])
        finally:
            bridge.close()

    def test_auto_reconnect_pump_bridge_reports_likely_ide_port_busy(self):
        def resolver(requested):
            return "COM4"

        def serial_factory(port, baud, timeout, write_timeout):
            raise PermissionError("Access is denied")

        bridge = windows_live_collect.AutoReconnectArduinoAbcPumpSerialBridge(
            requested_port="auto",
            baud=9600,
            resolver=resolver,
            serial_factory=serial_factory,
            open_reset_delay_s=0,
            start_background=False,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "Arduino IDE/Serial Monitor"):
                bridge.send("b")
            status = bridge.status()
            self.assertEqual(status["status"], "busy")
            self.assertTrue(status["likely_busy"])
            self.assertIn("COM4", status["message"])
        finally:
            bridge.close()

    def test_pump_serial_message_explains_web_firmware_ack_requirement(self):
        message = windows_live_collect._pump_serial_user_message(
            status="error",
            requested="auto",
            port="COM4",
            error="firmware did not confirm pump command c: no acknowledgement",
        )

        self.assertIn("웹 제어용 펌웨어 응답", message)
        self.assertIn("auto_titrator/arduino_stepper/arduino_stepper.ino", message)
        self.assertIn("Serial Monitor", message)

    def test_live_stream_server_health_exposes_pump_reconnect_status(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=None,
            pump_status_provider=lambda: {
                "enabled": True,
                "auto_retry": True,
                "connected": False,
                "status": "waiting_for_port",
                "message": "아두이노 펌프 대기 중: USB를 연결하면 자동으로 다시 시도합니다.",
            },
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/collector-health")
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertEqual(payload["pump"]["status"], "waiting_for_port")
        self.assertIn("아두이노 펌프 대기", payload["action_hints"][0])

    def test_live_stream_server_starts_and_stops_training_csv_recording(self):
        pump_commands = []
        firmware_state = {}
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "maximum_pump_rate_ml_per_s": 1.0,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                start_payload = json.loads(response.read().decode("utf-8"))
            csv_buffer.add({"frame_id": 1, "visible_R_mean": 121.25})
            stop_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(stop_request, timeout=1.0) as response:
                stop_payload = json.loads(response.read().decode("utf-8"))
            restart_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "maximum_pump_rate_ml_per_s": 1.0,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(restart_request, timeout=1.0) as response:
                restart_payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(start_payload["csv"]["recording"])
        self.assertEqual(start_payload["roi"]["roi_state"], "recording")
        self.assertEqual(start_payload["csv"]["roi_session_id"], 1)
        self.assertFalse(stop_payload["csv"]["recording"])
        self.assertEqual(stop_payload["roi"]["roi_state"], "stopped")
        self.assertTrue(stop_payload["roi"]["roi_recordable"])
        self.assertEqual(restart_payload["roi"]["roi_state"], "recording")
        self.assertEqual(stop_payload["csv"]["state"], "stopped")
        self.assertEqual(stop_payload["csv"]["row_count"], 1)
        self.assertEqual(
            pump_commands,
            ["G 100000\n", "b", "c", "G 100000\n", "b", "c"],
        )

    def test_live_stream_server_finalizes_lossless_capture_backlog_before_download(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        worker = windows_live_collect.Mini2CaptureThread(
            FastMini2Reader(),
            start_time=time.perf_counter(),
            max_recording_queue=64,
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
        )
        handle.server.capture_controller = worker
        worker.start()
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                started = json.loads(response.read().decode("utf-8"))
            time.sleep(0.02)
            stop_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(stop_request, timeout=1.0) as response:
                stopping = json.loads(response.read().decode("utf-8"))

            self.assertTrue(stopping["csv"]["finalizing"])
            duplicate_stop_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(duplicate_stop_request, timeout=1.0) as response:
                duplicate_stopping = json.loads(response.read().decode("utf-8"))
            self.assertTrue(duplicate_stopping["csv"]["finalizing"])
            self.assertEqual(duplicate_stopping["csv"]["session_id"], started["csv"]["session_id"])

            premature_restart_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as restart_error:
                urllib.request.urlopen(premature_restart_request, timeout=1.0)
            self.assertEqual(restart_error.exception.code, 409)
            restart_payload = json.loads(restart_error.exception.read().decode("utf-8"))
            self.assertTrue(restart_payload["csv"]["finalizing"])
            self.assertEqual(restart_payload["csv"]["session_id"], started["csv"]["session_id"])

            with self.assertRaises(urllib.error.HTTPError) as download_error:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/csv", timeout=1.0)
            self.assertEqual(download_error.exception.code, 409)

            session_id = int(started["csv"]["session_id"])
            captured_count = int(stopping["capture"]["recording_captured_frames"])
            for _ in range(captured_count):
                captured = worker.read(timeout_s=0.5)
                self.assertTrue(
                    csv_buffer.add(
                        {
                            "frame_id": captured.frame_id,
                            "time_s": captured.timestamp_s,
                            "capture_recording_session_id": session_id,
                        }
                    )
                )
                worker.mark_processed(captured)
            self.assertTrue(worker.recording_drained(session_id))
            csv_buffer.complete_stop()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/csv", timeout=1.0) as response:
                downloaded = response.read().decode("utf-8-sig")
        finally:
            worker.close()
            handle.close()

        self.assertGreater(captured_count, 0)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(downloaded)))), captured_count)

    def test_live_stream_server_starts_csv_when_arduino_pump_is_missing(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))

        def missing_pump_sender(command):
            raise RuntimeError("아두이노 펌프 대기 중: USB를 연결하면 자동으로 다시 시도합니다.")

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=missing_pump_sender,
            pump_status_provider=lambda: {
                "enabled": True,
                "auto_retry": True,
                "connected": False,
                "status": "waiting_for_port",
                "message": "아두이노 펌프 대기 중: USB를 연결하면 자동으로 다시 시도합니다.",
            },
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                start_payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(start_payload["ok"])
        self.assertTrue(start_payload["csv"]["recording"])
        self.assertEqual(start_payload["roi"]["roi_state"], "recording")
        self.assertEqual(start_payload["pump"]["status"], "error")
        self.assertTrue(start_payload["pump"]["recording_continues_without_pump"])
        self.assertIn("CSV recording continues", start_payload["warning"])

    def test_live_stream_server_exposes_manual_abc_pump_buttons(self):
        pump_commands = []
        firmware_state = {}
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]
            dispense_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(dispense_request, timeout=1.0) as response:
                dispense_payload = json.loads(response.read().decode("utf-8"))
            stop_before_retract_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(stop_before_retract_request, timeout=1.0) as response:
                stop_before_retract_payload = json.loads(response.read().decode("utf-8"))
            retract_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/retract",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(retract_request, timeout=1.0) as response:
                retract_payload = json.loads(response.read().decode("utf-8"))
            stop_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(stop_request, timeout=1.0) as response:
                stop_payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(dispense_payload["ok"])
        self.assertTrue(stop_before_retract_payload["ok"])
        self.assertTrue(retract_payload["ok"])
        self.assertTrue(stop_payload["ok"])
        self.assertEqual(dispense_payload["pump"]["action"], "start")
        self.assertEqual(dispense_payload["pump"]["command"], "b")
        self.assertEqual(retract_payload["pump"]["command"], "a")
        self.assertEqual(stop_payload["pump"]["command"], "c")
        self.assertEqual(
            pump_commands,
            ["G 100000\n", "b", "c", "G 100000\n", "a", "c"],
        )

    def test_live_stream_server_can_reverse_manual_pump_direction_mapping(self):
        pump_commands = []
        firmware_state = {}

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]

            def post(path):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(
                        {
                            "maximum_pump_rate_ml_per_s": 1.0,
                            "pump_direction_mode": "reversed",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=1.0) as response:
                    return json.loads(response.read().decode("utf-8"))

            dispense = post("/api/pump/dispense")
            stop_one = post("/api/pump/stop")
            retract = post("/api/pump/retract")
            stop_two = post("/api/pump/stop")
        finally:
            handle.close()

        self.assertEqual(dispense["pump"]["command"], "a")
        self.assertEqual(retract["pump"]["command"], "b")
        self.assertTrue(stop_one["ok"])
        self.assertTrue(stop_two["ok"])
        self.assertEqual(
            pump_commands,
            ["G 100000\n", "a", "c", "G 100000\n", "b", "c"],
        )

    def test_manual_web_pump_buttons_bypass_time_and_volume_guard(self):
        pump_commands = []

        def sender(command):
            pump_commands.append(command)
            return {"legacy_command_sent": command}

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=sender,
            pump_command_map={"start": "b", "retract": "a", "stop": "c"},
        )
        try:
            port = handle.server.server_address[1]

            def post(path, payload):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=1.0) as response:
                    return json.loads(response.read().decode("utf-8"))

            dispense = post("/api/pump/dispense", {"manual_unbounded": True})
            stop_one = post("/api/pump/stop", {})
            retract = post("/api/pump/retract", {"manual_unbounded": True})
            stop_two = post("/api/pump/stop", {})
            reset = post("/api/pump/reset", {})
        finally:
            handle.close()

        self.assertTrue(dispense["pump"]["manual_unbounded"])
        self.assertTrue(retract["pump"]["manual_unbounded"])
        self.assertEqual(dispense["pump"]["command"], "b")
        self.assertEqual(retract["pump"]["command"], "a")
        self.assertTrue(stop_one["ok"])
        self.assertTrue(stop_two["ok"])
        self.assertTrue(reset["ok"])
        self.assertEqual(reset["pump"]["command"], "r")
        self.assertEqual(pump_commands, ["b", "c", "a", "c", "r"])
        self.assertFalse(any(command.startswith("G ") for command in pump_commands))

    def test_live_stream_server_rejects_duplicate_start_without_refreshing_guard(self):
        pump_commands = []
        firmware_state = {}

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps(
                    {
                        "maximum_pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 10.0,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                first = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(request, timeout=1.0) as response:
                duplicate = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(first["ok"])
        self.assertFalse(duplicate["ok"])
        self.assertIn("already active", duplicate["pump"]["error"])
        self.assertEqual(pump_commands, ["G 10000\n", "b", "c"])

    def test_recording_session_volume_budget_survives_explicit_stop_and_restart(self):
        pump_commands = []
        firmware_state = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        with mock.patch.object(windows_live_collect.time, "perf_counter", return_value=100.0):
            csv_buffer.start_recording(
                pump_rate_ml_per_s=1.0,
                started_monotonic_s=100.0,
            )
            handle = windows_live_collect.start_live_stream_server(
                "127.0.0.1",
                0,
                windows_live_collect.LiveStreamState(),
                csv_buffer=csv_buffer,
                pump_command_sender=guarded_sender,
            )
            try:
                port = handle.server.server_address[1]

                def post(path, payload):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}{path}",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=1.0) as response:
                        return json.loads(response.read().decode("utf-8"))

                first = post(
                    "/api/pump/dispense",
                    {
                        "maximum_pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 10.0,
                    },
                )
                stopped = post("/api/pump/stop", {})
                csv_buffer.record_commanded_pulse(
                    steps=200,
                    nominal_ml_per_step=0.01,
                    now_monotonic_s=100.0,
                )
                restarted = post(
                    "/api/pump/dispense",
                    {
                        "maximum_pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 10.0,
                    },
                )
            finally:
                handle.close()

        self.assertTrue(first["ok"])
        self.assertTrue(stopped["ok"])
        self.assertTrue(restarted["ok"])
        self.assertEqual(restarted["pump"]["session_used_volume_ml"], 2.0)
        self.assertEqual(restarted["pump"]["session_remaining_volume_ml"], 8.0)
        self.assertEqual(
            pump_commands,
            ["G 10000\n", "b", "c", "G 8000\n", "b", "c"],
        )

    def test_pump_start_and_retract_are_rejected_while_csv_is_finalizing(self):
        pump_commands = []
        firmware_state = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=100.0,
        )
        stopping = csv_buffer.request_stop()
        self.assertTrue(stopping["finalizing"])
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]

            def post(path):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}{path}",
                    data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=1.0) as response:
                    return json.loads(response.read().decode("utf-8"))

            dispense = post("/api/pump/dispense")
            retract = post("/api/pump/retract")
            commands_before_close = list(pump_commands)
        finally:
            handle.close()

        self.assertFalse(dispense["ok"])
        self.assertFalse(retract["ok"])
        self.assertIn("finalization is in progress", dispense["pump"]["error"])
        self.assertIn("finalization is in progress", retract["pump"]["error"])
        self.assertEqual(commands_before_close, [])
        self.assertNotIn("a", pump_commands)
        self.assertNotIn("b", pump_commands)
        self.assertFalse(any(command.startswith("G ") for command in pump_commands))

    def test_pump_start_is_rejected_while_csv_stop_is_draining_capture(self):
        pump_commands = []
        firmware_state = {}
        drain_entered = threading.Event()
        release_drain = threading.Event()
        stop_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class BlockingCaptureController(windows_live_collect.Mini2CaptureThread):
            def __init__(self):
                pass

            def end_recording(self, session_id):
                drain_entered.set()
                if not release_drain.wait(timeout=3.0):
                    raise TimeoutError("test capture drain was not released")
                return {"drained": True, "recording_session_id": session_id}

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
        )
        handle.server.capture_controller = BlockingCaptureController()
        port = handle.server.server_address[1]

        def stop_csv():
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    stop_result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after the thread joins.
                stop_result["error"] = exc

        stop_thread = threading.Thread(target=stop_csv, daemon=True)
        stop_thread.start()
        try:
            self.assertTrue(drain_entered.wait(timeout=1.0))
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as start_error:
                urllib.request.urlopen(start_request, timeout=1.0)
            self.assertEqual(start_error.exception.code, 409)
            start_payload = json.loads(start_error.exception.read().decode("utf-8"))
            self.assertIn("transition is in progress", start_payload["pump"]["error"])
            self.assertEqual(pump_commands, ["c"])
        finally:
            release_drain.set()
            stop_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(stop_thread.is_alive())
        self.assertNotIn("error", stop_result)
        self.assertTrue(stop_result["payload"]["ok"])
        self.assertNotIn("a", pump_commands)
        self.assertNotIn("b", pump_commands)
        self.assertFalse(any(command.startswith("G ") for command in pump_commands))

    def test_csv_stop_preempts_an_inflight_pump_start_before_waiting_for_csv_lock(self):
        pump_commands = []
        wire_write_lock = threading.Lock()
        direction_entered = threading.Event()
        release_direction = threading.Event()
        emergency_sent = threading.Event()
        start_result = {}
        stop_result = {}
        firmware_timeout = {"ms": None}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        def sender(command):
            pump_commands.append(command)
            if command.startswith("G "):
                timeout_ms = int(command.split()[1])
                firmware_timeout["ms"] = timeout_ms
                return f"GUARD ARMED {timeout_ms}"
            if command == "c":
                return "PUMP STOPPED COMMAND"
            raise AssertionError(f"unexpected command: {command!r}")

        def guarded_direction(command, can_send):
            with wire_write_lock:
                if not can_send():
                    return {"direction_cancelled": True}
                pump_commands.append(command)
                direction_entered.set()
            if not release_direction.wait(timeout=3.0):
                raise TimeoutError("test direction acknowledgement was not released")
            return f"PUMP RUNNING {command} {firmware_timeout['ms']}"

        def emergency_stop():
            with wire_write_lock:
                pump_commands.append("EMERGENCY_C")
                emergency_sent.set()
            return {"sent": True, "status": "sent"}

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=sender,
            pump_guarded_direction_sender=guarded_direction,
            pump_emergency_stop_sender=emergency_stop,
        )
        port = handle.server.server_address[1]

        def post(path, payload, result):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after the thread joins.
                result["error"] = exc

        start_thread = threading.Thread(
            target=post,
            args=(
                "/api/pump/dispense",
                {"maximum_pump_rate_ml_per_s": 1.0},
                start_result,
            ),
            daemon=True,
        )
        stop_thread = threading.Thread(
            target=post,
            args=("/api/csv/stop", {}, stop_result),
            daemon=True,
        )
        start_thread.start()
        try:
            self.assertTrue(direction_entered.wait(timeout=1.0))
            stop_thread.start()
            self.assertTrue(emergency_sent.wait(timeout=1.0))
            self.assertTrue(start_thread.is_alive())
        finally:
            release_direction.set()
            start_thread.join(timeout=4.0)
            stop_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(start_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertNotIn("error", start_result)
        self.assertNotIn("error", stop_result)
        self.assertFalse(start_result["payload"]["ok"])
        self.assertTrue(stop_result["payload"]["ok"])
        self.assertEqual(pump_commands[1:], ["b", "EMERGENCY_C", "c"])
        self.assertRegex(pump_commands[0], r"^G [1-9][0-9]*\n$")
        guard_status = stop_result["payload"]["pump"]["absolute_guard"]
        self.assertFalse(guard_status["absolute_guard_armed"])
        self.assertEqual(guard_status["absolute_guard_state"], "stopped")

    def test_stop_intent_rejects_start_in_prelock_stop_gap(self):
        pump_commands = []
        emergency_entered = threading.Event()
        release_emergency = threading.Event()
        stop_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        def sender(command):
            pump_commands.append(command)
            if command == "c":
                return "PUMP STOPPED COMMAND"
            if command.startswith("G "):
                timeout_ms = int(command.split()[1])
                return f"GUARD ARMED {timeout_ms}"
            if command == "b":
                timeout_ms = int(pump_commands[-2].split()[1])
                return f"PUMP RUNNING b {timeout_ms}"
            raise AssertionError(command)

        def emergency_stop():
            pump_commands.append("EMERGENCY_C")
            emergency_entered.set()
            if not release_emergency.wait(timeout=3.0):
                raise TimeoutError("test emergency stop was not released")
            return {"sent": True, "status": "sent"}

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=sender,
            pump_emergency_stop_sender=emergency_stop,
        )
        port = handle.server.server_address[1]

        def stop_csv():
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    stop_result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after join.
                stop_result["error"] = exc

        stop_thread = threading.Thread(target=stop_csv, daemon=True)
        stop_thread.start()
        try:
            self.assertTrue(emergency_entered.wait(timeout=1.0))
            # The stop handler has published intent and is still before its CSV
            # lock acquisition. A motion request must not enter this gap.
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as start_error:
                urllib.request.urlopen(start_request, timeout=1.0)
            self.assertEqual(start_error.exception.code, 409)
            payload = json.loads(start_error.exception.read().decode("utf-8"))
            self.assertIn("stop/finalization intent", payload["pump"]["error"])
            self.assertEqual(pump_commands, ["EMERGENCY_C"])
        finally:
            release_emergency.set()
            stop_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(stop_thread.is_alive())
        self.assertNotIn("error", stop_result)
        self.assertTrue(stop_result["payload"]["ok"])
        self.assertEqual(pump_commands, ["EMERGENCY_C", "c"])
        self.assertFalse(handle.server.csv_stop_intent.is_set())

    def test_stop_intent_coordinator_requires_all_owners_and_latch_to_finish(self):
        coordinator = windows_live_collect.StopIntentCoordinator()
        manual_token = coordinator.begin("manual")
        automatic_token = coordinator.begin("automatic")
        coordinator.latch_session(7)

        self.assertFalse(coordinator.clear_latch(8))
        coordinator.finish(automatic_token)
        self.assertTrue(coordinator.is_set())
        self.assertEqual(coordinator.status()["stop_intent_owner_count"], 1)

        coordinator.finish(manual_token)
        self.assertTrue(coordinator.is_set())
        self.assertEqual(coordinator.status()["stop_intent_latch_session_id"], 7)
        self.assertTrue(coordinator.clear_latch(7))
        self.assertFalse(coordinator.is_set())
        self.assertEqual(coordinator.status()["stop_intent_owner_count"], 0)

    def test_stale_session_cannot_clear_another_sessions_finalization_latch(self):
        coordinator = windows_live_collect.StopIntentCoordinator()
        coordinator.latch_session(22)
        stale_token = coordinator.begin("stale_session_21")

        self.assertFalse(coordinator.clear_latch(21))
        coordinator.finish(stale_token)

        self.assertTrue(coordinator.is_set())
        self.assertEqual(coordinator.status()["stop_intent_latch_session_id"], 22)
        self.assertTrue(coordinator.clear_latch(22))
        self.assertFalse(coordinator.is_set())

    def test_delayed_stale_auto_stop_callback_does_not_stop_new_session(self):
        pump_commands = []
        firmware_state = {}
        stale_begin_entered = threading.Event()
        release_stale_begin = threading.Event()
        callback_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class DelayedBeginStopIntent(windows_live_collect.StopIntentCoordinator):
            def begin(self, reason):
                if reason == "stale_session_1":
                    stale_begin_entered.set()
                    if not release_stale_begin.wait(timeout=3.0):
                        raise TimeoutError("stale callback begin was not released")
                return super().begin(reason)

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
        )
        coordinator = DelayedBeginStopIntent()
        handle.server.csv_stop_intent = coordinator
        port = handle.server.server_address[1]

        def post(path, payload):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=4.0) as response:
                return json.loads(response.read().decode("utf-8"))

        first_csv = csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        first_session_id = int(first_csv["session_id"])
        first_pump = post(
            "/api/pump/dispense",
            {
                "maximum_pump_rate_ml_per_s": 1.0,
                "absolute_maximum_volume_ml": 10.0,
            },
        )

        def stale_callback():
            try:
                windows_live_collect.finish_live_automatic_stop(
                    server=handle.server,
                    csv_buffer=csv_buffer,
                    roi_state=handle.server.roi_state,
                    auto_stop_controller=None,
                    endpoint_pulse_runtime=None,
                    session_id=first_session_id,
                    status={"auto_stop_state": "triggered"},
                    guard_reason="stale_session_1",
                )
            except BaseException as exc:  # noqa: BLE001 - surfaced after join.
                callback_result["error"] = exc

        callback_thread = threading.Thread(target=stale_callback, daemon=True)
        callback_thread.start()
        commands_before_cleanup = []
        csv_before_cleanup = {}
        guard_before_cleanup = {}
        intent_before_cleanup = True
        try:
            self.assertTrue(first_pump["ok"])
            self.assertTrue(stale_begin_entered.wait(timeout=1.0))

            stopped = post("/api/csv/stop", {})
            self.assertTrue(stopped["ok"])
            second_csv = csv_buffer.start_recording(
                pump_rate_ml_per_s=1.0,
                started_monotonic_s=time.perf_counter(),
            )
            second_session_id = int(second_csv["session_id"])
            self.assertNotEqual(second_session_id, first_session_id)
            second_pump = post(
                "/api/pump/dispense",
                {
                    "maximum_pump_rate_ml_per_s": 1.0,
                    "absolute_maximum_volume_ml": 10.0,
                },
            )
            self.assertTrue(second_pump["ok"])

            release_stale_begin.set()
            callback_thread.join(timeout=3.0)
            commands_before_cleanup = list(pump_commands)
            csv_before_cleanup = csv_buffer.status()
            guard_before_cleanup = handle.server.absolute_pump_safety_guard.status()
            intent_before_cleanup = coordinator.is_set()
        finally:
            release_stale_begin.set()
            callback_thread.join(timeout=3.0)
            if csv_buffer.status().get("recording"):
                try:
                    post("/api/csv/stop", {})
                except Exception:
                    pass
            handle.close()

        self.assertFalse(callback_thread.is_alive())
        self.assertNotIn("error", callback_result)
        self.assertEqual(len(commands_before_cleanup), 5)
        self.assertRegex(commands_before_cleanup[0], r"^G [1-9][0-9]*\n$")
        self.assertEqual(commands_before_cleanup[1], "b")
        self.assertEqual(commands_before_cleanup[2], "c")
        self.assertRegex(commands_before_cleanup[3], r"^G [1-9][0-9]*\n$")
        self.assertEqual(commands_before_cleanup[4], "b")
        self.assertTrue(csv_before_cleanup["recording"])
        self.assertEqual(csv_before_cleanup["session_id"], second_session_id)
        self.assertEqual(guard_before_cleanup["absolute_guard_state"], "armed_running")
        self.assertFalse(intent_before_cleanup)

    def test_overlapping_auto_and_manual_stop_keep_restart_blocked(self):
        pump_commands = []
        firmware_state = {}
        callback_gate_held = threading.Event()
        disarm_called = threading.Event()
        automatic_owner_finished = threading.Event()
        release_callback_gate = threading.Event()
        automatic_result = {}
        stop_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class GateControlledAutoStop(windows_live_collect.ColorChangeAutoStopController):
            def __init__(self):
                self._callback_gate = threading.RLock()

            def disarm(self, reason):
                disarm_called.set()
                with self._callback_gate:
                    return {
                        "auto_stop_state": "disabled",
                        "auto_stop_reason": reason,
                    }

        auto_stop = GateControlledAutoStop()

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        initial_csv_status = csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        initial_session_id = int(initial_csv_status["session_id"])
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
            auto_stop_controller=auto_stop,
        )
        port = handle.server.server_address[1]
        coordinator = handle.server.csv_stop_intent

        def simulate_automatic_stop_completion():
            with auto_stop._callback_gate:
                token = coordinator.begin("automatic_stop")
                coordinator.latch_session(initial_session_id)
                callback_gate_held.set()
                try:
                    if not disarm_called.wait(timeout=2.0):
                        automatic_result["error"] = "manual disarm was not attempted"
                        return
                    with handle.server.csv_control_lock:
                        csv_buffer.stop_recording()
                        coordinator.clear_latch(initial_session_id)
                finally:
                    coordinator.finish(token)
                    automatic_owner_finished.set()
                # Widen the exact race window from the real callback: its stop
                # token is finished, but manual stop still owns another token
                # and is blocked on this callback gate.
                if not release_callback_gate.wait(timeout=3.0):
                    automatic_result["error"] = "callback gate was not released"

        def stop_csv():
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    stop_result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after joins.
                stop_result["error"] = exc

        automatic_thread = threading.Thread(
            target=simulate_automatic_stop_completion,
            daemon=True,
        )
        stop_thread = threading.Thread(target=stop_csv, daemon=True)
        automatic_thread.start()
        self.assertTrue(callback_gate_held.wait(timeout=1.0))
        stop_thread.start()
        try:
            self.assertTrue(automatic_owner_finished.wait(timeout=2.0))
            self.assertTrue(stop_thread.is_alive())
            self.assertTrue(coordinator.is_set())
            self.assertEqual(coordinator.status()["stop_intent_owner_count"], 1)

            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps(
                    {"maximum_pump_rate_ml_per_s": 1.0}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as start_error:
                urllib.request.urlopen(start_request, timeout=1.0)
            self.assertEqual(start_error.exception.code, 409)
            start_payload = json.loads(start_error.exception.read().decode("utf-8"))
            self.assertIn("stop/finalization intent", start_payload["pump"]["error"])
            self.assertFalse(any(command.startswith("G ") for command in pump_commands))
            self.assertNotIn("b", pump_commands)
        finally:
            release_callback_gate.set()
            automatic_thread.join(timeout=3.0)
            stop_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(automatic_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertNotIn("error", automatic_result)
        self.assertNotIn("error", stop_result)
        self.assertTrue(stop_result["payload"]["ok"])
        self.assertEqual(pump_commands, ["c"])
        self.assertFalse(coordinator.is_set())
        self.assertEqual(coordinator.status()["stop_intent_owner_count"], 0)

    def test_manual_csv_stop_does_not_deadlock_with_auto_stop_callback(self):
        pump_commands = []
        firmware_state = {}
        pump_stop_sent = threading.Event()
        callback_gate_held = threading.Event()
        disarm_called = threading.Event()
        automatic_csv_lock_acquired = threading.Event()
        automatic_result = {}
        stop_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class GateControlledAutoStop(windows_live_collect.ColorChangeAutoStopController):
            def __init__(self):
                self._callback_gate = threading.RLock()

            def disarm(self, reason):
                # Signal before waiting for the callback gate.  If the HTTP
                # handler holds csv_control_lock here, the simulated automatic
                # callback below creates the historical AB/BA deadlock.
                disarm_called.set()
                with self._callback_gate:
                    return {
                        "auto_stop_state": "disabled",
                        "auto_stop_reason": reason,
                    }

        auto_stop = GateControlledAutoStop()

        def guarded_sender(command):
            pump_commands.append(command)
            response = acknowledged_test_pump_firmware(command, firmware_state)
            if command == "c":
                pump_stop_sent.set()
            return response

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
            auto_stop_controller=auto_stop,
        )
        port = handle.server.server_address[1]

        def simulate_automatic_callback():
            with auto_stop._callback_gate:
                callback_gate_held.set()
                if not pump_stop_sent.wait(timeout=2.0):
                    automatic_result["error"] = "manual stop command was not sent"
                    return
                if not disarm_called.wait(timeout=2.0):
                    automatic_result["error"] = "manual disarm was not attempted"
                    return
                acquired = handle.server.csv_control_lock.acquire(timeout=1.0)
                automatic_result["csv_lock_acquired"] = acquired
                if acquired:
                    automatic_csv_lock_acquired.set()
                    handle.server.csv_control_lock.release()

        def stop_csv():
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    stop_result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after joins.
                stop_result["error"] = exc

        automatic_thread = threading.Thread(
            target=simulate_automatic_callback,
            daemon=True,
        )
        stop_thread = threading.Thread(target=stop_csv, daemon=True)
        automatic_thread.start()
        self.assertTrue(callback_gate_held.wait(timeout=1.0))
        stop_thread.start()
        try:
            self.assertTrue(automatic_csv_lock_acquired.wait(timeout=2.0))
        finally:
            automatic_thread.join(timeout=3.0)
            stop_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(automatic_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertNotIn("error", automatic_result)
        self.assertNotIn("error", stop_result)
        self.assertTrue(automatic_result["csv_lock_acquired"])
        self.assertTrue(stop_result["payload"]["ok"])
        self.assertEqual(pump_commands, ["c"])

    def test_manual_retract_does_not_deadlock_with_auto_stop_callback(self):
        pump_commands = []
        firmware_state = {}
        callback_gate_held = threading.Event()
        disarm_called = threading.Event()
        automatic_csv_lock_acquired = threading.Event()
        automatic_result = {}
        retract_result = {}
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class GateControlledAutoStop(windows_live_collect.ColorChangeAutoStopController):
            def __init__(self):
                self._callback_gate = threading.RLock()

            def disarm(self, reason):
                disarm_called.set()
                with self._callback_gate:
                    return {
                        "auto_stop_state": "disabled",
                        "auto_stop_reason": reason,
                    }

        auto_stop = GateControlledAutoStop()

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        csv_buffer.start_recording(
            pump_rate_ml_per_s=1.0,
            started_monotonic_s=time.perf_counter(),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
            auto_stop_controller=auto_stop,
        )
        port = handle.server.server_address[1]

        def simulate_automatic_callback():
            with auto_stop._callback_gate:
                callback_gate_held.set()
                if not disarm_called.wait(timeout=2.0):
                    automatic_result["error"] = "manual disarm was not attempted"
                    return
                acquired = handle.server.csv_control_lock.acquire(timeout=1.0)
                automatic_result["csv_lock_acquired"] = acquired
                if acquired:
                    automatic_csv_lock_acquired.set()
                    handle.server.csv_control_lock.release()

        def retract_pump():
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/retract",
                data=json.dumps(
                    {"maximum_pump_rate_ml_per_s": 1.0}
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=4.0) as response:
                    retract_result["payload"] = json.loads(response.read().decode("utf-8"))
            except BaseException as exc:  # noqa: BLE001 - surfaced after joins.
                retract_result["error"] = exc

        automatic_thread = threading.Thread(
            target=simulate_automatic_callback,
            daemon=True,
        )
        retract_thread = threading.Thread(target=retract_pump, daemon=True)
        automatic_thread.start()
        self.assertTrue(callback_gate_held.wait(timeout=1.0))
        retract_thread.start()
        try:
            self.assertTrue(automatic_csv_lock_acquired.wait(timeout=2.0))
        finally:
            automatic_thread.join(timeout=3.0)
            retract_thread.join(timeout=4.0)
            handle.close()

        self.assertFalse(automatic_thread.is_alive())
        self.assertFalse(retract_thread.is_alive())
        self.assertNotIn("error", automatic_result)
        self.assertNotIn("error", retract_result)
        self.assertTrue(automatic_result["csv_lock_acquired"])
        self.assertTrue(retract_result["payload"]["ok"])
        self.assertRegex(pump_commands[0], r"^G [1-9][0-9]*\n$")
        self.assertEqual(pump_commands[1], "a")
        self.assertEqual(pump_commands[-1], "c")

    def test_live_stream_server_starts_csv_with_pump_equivalence_payload(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "theoretical_equivalence_volume_ml": 9.0,
                        "equivalence_window_ml": 0.05,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                start_payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(start_payload["ok"])
        self.assertEqual(start_payload["csv"]["pump_run_rate_ml_per_s"], 1.0)
        self.assertEqual(start_payload["csv"]["theoretical_equivalence_volume_ml"], 9.0)
        self.assertEqual(start_payload["csv"]["theoretical_equivalence_time_s"], 9.0)

    def test_slow_stage_unsupported_capability_is_rejected_before_motion(self):
        commands = []
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(1, 1, 5, 5), thermal_roi=Roi(1, 1, 5, 5)
        )
        roi_state.lock()
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1", 0, windows_live_collect.LiveStreamState(),
            roi_state=roi_state,
            csv_buffer=windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv")),
            pump_command_sender=lambda command: commands.append(command),
            pump_status_provider=lambda: {
                "supports_step_pulse": True,
                "supports_variable_rate": False,
                "firmware_pulse_direction": "b",
            },
            auto_stop_controller=object(),
            endpoint_pulse_runtime=object(),
        )
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{handle.server.server_address[1]}/api/csv/start",
                data=json.dumps({
                    "auto_stop_enabled": True,
                    "auto_stop_pulse_enabled": True,
                    "auto_stop_slow_stage_enabled": True,
                    "pump_rate_ml_per_s": 1.0,
                    "maximum_pump_rate_ml_per_s": 1.05,
                    "absolute_maximum_volume_ml": 10.0,
                    "pulse_ml_per_step_upper_bound": 0.01,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=1.0)
            body = json.loads(caught.exception.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertIn("unsupported", body["error"])
        self.assertIn("PUMP SPEED 1", body["error"])
        self.assertEqual(commands, [])

    def test_csv_start_rejects_malformed_and_fractional_staged_values_without_side_effects(self):
        commands = []
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(1, 1, 5, 5), thermal_roi=Roi(1, 1, 5, 5)
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("unused.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1", 0, windows_live_collect.LiveStreamState(),
            roi_state=roi_state, csv_buffer=csv_buffer,
            pump_command_sender=lambda command: commands.append(command),
        )
        try:
            port = handle.server.server_address[1]
            bodies = [b"{", b"[]", json.dumps({
                "auto_stop_slow_stage_enabled": "true"
            }).encode(), json.dumps({
                "auto_stop_slow_stage_enabled": True,
                "auto_stop_slow_rate_steps_per_s": 25.5,
            }).encode()]
            for body in bodies:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/csv/start", data=body,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=1.0)
                self.assertEqual(caught.exception.code, 400)
        finally:
            handle.close()

        self.assertEqual(commands, [])
        self.assertEqual(csv_buffer.status()["state"], "idle")
        self.assertFalse(roi_state.status()["roi_recording"])

    def test_pump_start_and_retract_reject_malformed_json_before_motion(self):
        commands = []
        disarms = []

        class DisarmSpy:
            def __init__(self, name):
                self.name = name

            def disarm(self, reason):
                disarms.append((self.name, reason))

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1", 0, windows_live_collect.LiveStreamState(),
            pump_command_sender=lambda command: commands.append(command),
            auto_stop_controller=DisarmSpy("auto"),
            endpoint_pulse_runtime=DisarmSpy("pulse"),
        )
        try:
            port = handle.server.server_address[1]
            for _ in range(5):
                for path in ("/api/pump/dispense", "/api/pump/retract"):
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}{path}", data=b"[]",
                        headers={"Content-Type": "application/json"}, method="POST",
                    )
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(request, timeout=1.0)
                    self.assertEqual(caught.exception.code, 400)
        finally:
            handle.close()
        self.assertEqual(commands, [])
        self.assertEqual(disarms, [])

    def test_live_stream_server_calibrates_auto_stop_before_pump_start(self):
        pump_commands = []
        firmware_state = {}
        events = []
        baseline_volumes = []
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class ReadyAutoStop(windows_live_collect.ColorChangeAutoStopController):
            def __init__(self):
                self.current = {
                    "auto_stop_enabled": True,
                    "auto_stop_state": "armed",
                    "auto_stop_reason": "waiting_for_color_model_confirmation",
                    "auto_stop_baseline_ready": True,
                    "auto_stop_session_id": 1,
                }

            def arm(self, **kwargs):
                events.append("baseline_ready")
                baseline_volumes.append(csv_buffer.status().get("injected_volume_ml"))
                self.current = {**self.current, "auto_stop_session_id": kwargs["session_id"]}
                return dict(self.current)

            def status(self):
                return dict(self.current)

            def disarm(self, reason):
                self.current = {
                    **self.current,
                    "auto_stop_state": "disabled",
                    "auto_stop_reason": reason,
                }
                return dict(self.current)

        class ReadyPulseRuntime(windows_live_collect.EndpointPulseRuntime):
            def __init__(self):
                pass

            def arm(self, **kwargs):
                events.append("pulse_armed")
                return {
                    "auto_stop_pulse_state": "armed_continuous",
                    "auto_stop_pulse_reason": "waiting_for_model_approach",
                }

            def disarm(self, reason):
                return {
                    "auto_stop_pulse_state": "disabled",
                    "auto_stop_pulse_reason": reason,
                }

        def guarded_sender(command):
            pump_commands.append(command)
            events.append(command.strip())
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
            auto_stop_controller=ReadyAutoStop(),
            endpoint_pulse_runtime=ReadyPulseRuntime(),
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "maximum_pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 15.0,
                        "titration_type": "strong_acid_strong_base",
                        "auto_stop_enabled": True,
                        "auto_stop_confirmation_delay_s": 0.4,
                        "auto_stop_maximum_volume_ml": 15.0,
                        "auto_stop_pulse_enabled": True,
                        "pulse_ml_per_step_upper_bound": 0.011,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                started = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertEqual(pump_commands, ["G 15000\n", "b", "c"])
        self.assertLess(events.index("baseline_ready"), events.index("G 15000"))
        self.assertLess(events.index("b"), events.index("pulse_armed"))
        self.assertTrue(started["auto_stop"]["auto_stop_enabled"])
        self.assertEqual(started["auto_stop"]["auto_stop_state"], "armed")
        self.assertEqual(started["csv"]["auto_stop_confirmation_delay_s"], 0.4)
        self.assertEqual(started["csv"]["auto_stop_maximum_volume_ml"], 15.0)
        self.assertEqual(baseline_volumes, [0.0])

    def test_live_stream_server_rejects_auto_stop_without_independent_maximum_rate(self):
        pump_commands = []
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )

        class UnusedAutoStop(windows_live_collect.ColorChangeAutoStopController):
            def __init__(self):
                pass

            def disarm(self, reason):
                return {"auto_stop_state": "disabled", "auto_stop_reason": reason}

        pulse_runtime = windows_live_collect.EndpointPulseRuntime(
            command_sender=pump_commands.append,
            stop_continuous=pump_commands.append,
            csv_buffer=csv_buffer,
            on_safety_stop=lambda *values: None,
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=pump_commands.append,
            auto_stop_controller=UnusedAutoStop(),
            endpoint_pulse_runtime=pulse_runtime,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 10.0,
                        "auto_stop_enabled": True,
                        "auto_stop_pulse_enabled": True,
                        "pulse_ml_per_step_upper_bound": 0.01,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=1.0)
            error_payload = json.loads(raised.exception.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertEqual(raised.exception.code, 409)
        self.assertIn("maximum_pump_rate_ml_per_s", error_payload["error"])
        self.assertEqual(pump_commands, [])
        self.assertEqual(csv_buffer.status()["state"], "idle")

    def test_live_stream_server_does_not_start_pump_when_auto_stop_baseline_times_out(self):
        pump_commands = []
        firmware_state = {}
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("data/raw/live-training.csv")
        )
        auto_stop = windows_live_collect.ColorChangeAutoStopController(
            {},
            on_trigger=lambda decision: None,
            on_status=csv_buffer.update_auto_stop_status,
        )

        class ReadyPulseRuntime(windows_live_collect.EndpointPulseRuntime):
            def __init__(self):
                pass

            def arm(self, **kwargs):
                return {"auto_stop_pulse_state": "armed_continuous"}

            def disarm(self, reason):
                return {"auto_stop_pulse_state": "disabled"}

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        original_timeout = windows_live_collect.AUTO_STOP_BASELINE_START_TIMEOUT_S
        windows_live_collect.AUTO_STOP_BASELINE_START_TIMEOUT_S = 0.05
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            roi_state=roi_state,
            csv_buffer=csv_buffer,
            pump_command_sender=guarded_sender,
            auto_stop_controller=auto_stop,
            endpoint_pulse_runtime=ReadyPulseRuntime(),
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "maximum_pump_rate_ml_per_s": 1.0,
                        "absolute_maximum_volume_ml": 15.0,
                        "titration_type": "strong_acid_strong_base",
                        "auto_stop_enabled": True,
                        "auto_stop_pulse_enabled": True,
                        "pulse_ml_per_step_upper_bound": 0.011,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request, timeout=1.0)
            payload = json.loads(error.exception.read().decode("utf-8"))
        finally:
            windows_live_collect.AUTO_STOP_BASELINE_START_TIMEOUT_S = original_timeout
            auto_stop.close()
            handle.close()

        self.assertEqual(error.exception.code, 409)
        self.assertIn("baseline timed out", payload["error"])
        self.assertEqual(pump_commands, [])
        self.assertEqual(payload["csv"]["state"], "stopped")

    def test_live_stream_server_fails_closed_when_firmware_guard_cannot_arm(self):
        pump_commands = []

        def unacknowledged_sender(command):
            pump_commands.append(command)
            return None

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=unacknowledged_sender,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pump"]["status"], "error")
        self.assertEqual(pump_commands, ["G 100000\n", "c"])
        self.assertNotIn("b", pump_commands)

    def test_live_stream_server_clamps_oversized_absolute_limits(self):
        pump_commands = []
        firmware_state = {}

        def guarded_sender(command):
            pump_commands.append(command)
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=guarded_sender,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps(
                    {
                        "maximum_pump_rate_ml_per_s": 0.5,
                        "absolute_maximum_volume_ml": 1000.0,
                        "absolute_maximum_run_time_s": 1000.0,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        guard_status = payload["pump"]["absolute_guard"]
        self.assertTrue(payload["ok"])
        self.assertTrue(guard_status["absolute_guard_limits_clamped"])
        self.assertEqual(guard_status["absolute_guard_effective_maximum_volume_ml"], 100.0)
        self.assertEqual(guard_status["absolute_guard_effective_maximum_run_time_s"], 120.0)
        self.assertEqual(pump_commands, ["G 120000\n", "b", "c"])

    def test_live_stream_server_records_stop_command_failure(self):
        firmware_state = {}

        def sender(command):
            if command == "c":
                raise OSError("serial stop failed")
            return acknowledged_test_pump_firmware(command, firmware_state)

        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            windows_live_collect.LiveStreamState(),
            pump_command_sender=sender,
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/dispense",
                data=json.dumps({"maximum_pump_rate_ml_per_s": 1.0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0):
                pass
            stop_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/pump/stop",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(stop_request, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/collector-health",
                timeout=1.0,
            ) as response:
                health = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["pump"]["absolute_guard"]["absolute_guard_stop_status"], "failed")
        self.assertIn("serial stop failed", payload["pump"]["absolute_guard"]["absolute_guard_error"])
        self.assertEqual(
            health["absolute_pump_guard"]["absolute_guard_stop_status"],
            "failed",
        )

    def test_live_stream_server_rejects_removed_csv_manual_label_endpoint(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
        )
        try:
            port = handle.server.server_address[1]
            label_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/label",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(label_request, timeout=1.0)
        finally:
            handle.close()

        self.assertEqual(ctx.exception.code, 404)


    def test_live_stream_server_looks_up_local_iupac_constants(self):
        live_state = windows_live_collect.LiveStreamState()
        handle = windows_live_collect.start_live_stream_server("127.0.0.1", 0, live_state)
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/chemistry/constants/lookup",
                data=json.dumps({"query": "acetic acid", "limit": 2}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        finally:
            handle.close()

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["query"], "acetic acid")
        self.assertGreaterEqual(payload["candidate_count"], 1)
        self.assertLessEqual(payload["candidate_count"], 2)
        self.assertIn("IUPAC", payload["source"])
        self.assertIn("pka_value", payload["candidates"][0])

    def test_live_stream_server_rejects_removed_manual_volume_endpoint(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        roi_state.lock()
        csv_buffer = windows_live_collect.LiveCsvBuffer(output_path=Path("data/raw/live-training.csv"))
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
            csv_buffer=csv_buffer,
        )
        try:
            port = handle.server.server_address[1]
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=json.dumps(
                    {
                        "pump_rate_ml_per_s": 1.0,
                        "theoretical_equivalence_volume_ml": 9.0,
                        "equivalence_window_ml": 0.05,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(start_request, timeout=1.0) as response:
                start_payload = json.loads(response.read().decode("utf-8"))
            volume_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/manual-volume",
                data=json.dumps({"delta_ml": 0.5, "note": "수동 +0.5 mL"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(volume_request, timeout=1.0)
        finally:
            handle.close()

        self.assertTrue(start_payload["ok"])
        self.assertEqual(start_payload["csv"]["pump_run_rate_ml_per_s"], 1.0)
        self.assertEqual(raised.exception.code, 404)

    def test_live_stream_server_rejects_cross_origin_mutation_posts(self):
        live_state = windows_live_collect.LiveStreamState()
        roi_state = windows_live_collect.RoiSelectionState(
            visible_roi=Roi(10, 20, 30, 40),
            thermal_roi=Roi(50, 60, 20, 15),
        )
        handle = windows_live_collect.start_live_stream_server(
            "127.0.0.1",
            0,
            live_state,
            roi_state=roi_state,
        )
        try:
            port = handle.server.server_address[1]
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/roi-lock",
                data=b"{}",
                headers={"Content-Type": "application/json", "Origin": "https://example.invalid"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(request, timeout=1.0)
            body = ctx.exception.read().decode("utf-8")
        finally:
            handle.close()

        self.assertEqual(ctx.exception.code, 403)
        self.assertFalse(json.loads(body)["ok"])

    def test_live_stream_server_rejects_csv_start_until_roi_locked(self):
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
            start_request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/csv/start",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(start_request, timeout=1.0)
            body = ctx.exception.read().decode("utf-8")
        finally:
            handle.close()

        self.assertEqual(ctx.exception.code, 409)
        payload = json.loads(body)
        self.assertFalse(payload["ok"])
        self.assertIn("lock both visible and thermal", payload["error"])

    def test_live_stream_publisher_encodes_off_main_loop_and_keeps_latest_frame(self):
        state = windows_live_collect.LiveStreamState()
        encoded_ids = []

        def fake_encoder(frame, *, quality=75):
            encoded_ids.append(int(frame[0, 0, 0]))
            return f"jpeg-{encoded_ids[-1]}".encode("ascii")

        publisher = windows_live_collect.LiveStreamPublisher(state, jpeg_quality=60, encoder=fake_encoder)
        publisher.submit(
            visible_frame=rgb_frame(1),
            thermal_frame=rgb_frame(2),
            metadata={"frame_id": 1},
        )
        publisher.submit(
            visible_frame=rgb_frame(3),
            thermal_frame=rgb_frame(4),
            metadata={"frame_id": 2},
        )
        publisher.start()
        try:
            metadata = state.wait_metadata(last_sequence=0, timeout_s=1.0)
        finally:
            publisher.close()

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata[1]["frame_id"], 2)
        self.assertEqual(encoded_ids, [3, 4])

    def test_run_writes_live_preview_files_when_preview_dir_is_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "windows-live.csv"
            preview_dir = Path(tmp) / "preview"
            args = Namespace(
                frames=2,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                preview_dir=str(preview_dir),
                preview_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.build_official_converter = lambda _args: FakeOfficialConverter()
            mini2 = FakeMini2Reader()
            visible = FakeVisibleCamera()
            try:
                windows_live_collect.run(args, mini2_reader=mini2, visible_camera=visible)
            finally:
                windows_live_collect.build_official_converter = old_builder

            self.assertTrue((preview_dir / "visible.bmp").is_file())
            self.assertTrue((preview_dir / "thermal.bmp").is_file())
            self.assertTrue((preview_dir / "thermal.json").is_file())

    def test_no_visible_mode_writes_thermal_only_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "thermal-only.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=True,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.build_official_converter = lambda _args: FakeOfficialConverter()
            mini2 = FakeMini2Reader()
            try:
                windows_live_collect.run(args, mini2_reader=mini2, visible_camera=None)
            finally:
                windows_live_collect.build_official_converter = old_builder

            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertIn("thermal_roi_avg", row)
            self.assertNotIn("visible_R_mean", row)
            self.assertEqual(row["visible_capture_index"], "")
            self.assertEqual(row["sync_quality"], "missing")
            self.assertEqual(row["sync_warning"], "visible frame unavailable")

    def test_run_logs_raw_after_zero_celsius_fallback_without_keyerror(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "zero-fallback.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                allow_mini2_missing=1,
                mini2_retry_interval_s=3.0,
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=True,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="off",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=1,
            )
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.build_official_converter = lambda _args: ZeroOfficialConverter()
            try:
                windows_live_collect.run(args, mini2_reader=FakeMini2Reader(), visible_camera=None)
            finally:
                windows_live_collect.build_official_converter = old_builder

            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["thermal_conversion_status"], "suspect_all_zero")
            self.assertEqual(row["thermal_calibrated"], "False")
            self.assertIn("thermal_raw_roi_avg", row)

    def test_official_converter_failure_keeps_collector_alive_as_raw_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "raw-after-converter-fail.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index=0,
                mini2_backend="MSMF",
                allow_mini2_missing=1,
                mini2_retry_interval_s=3.0,
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=True,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="off",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.build_official_converter = lambda _args: (_ for _ in ()).throw(RuntimeError("DLL missing"))
            try:
                windows_live_collect.run(args, mini2_reader=FakeMini2Reader(), visible_camera=None)
            finally:
                windows_live_collect.build_official_converter = old_builder

            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["thermal_source"], "mini2_uvc_raw_uncalibrated_preview")
            self.assertEqual(row["thermal_calibrated"], "False")
            self.assertIn("raw preview only", row["warnings"])
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["thermal_processing"], "raw")

    def test_run_keeps_visible_rows_when_mini2_auto_detection_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "visible-only.csv"
            args = Namespace(
                frames=2,
                frame_rate_hz=25.0,
                mini2_index="auto",
                mini2_max_index=2,
                mini2_backend="AUTO",
                allow_mini2_missing=1,
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="0,0,40,40",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="off",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            visible = MaskCandidateVisibleCamera()
            old_open = windows_live_collect.open_mini2_capture
            old_builder = windows_live_collect.build_official_converter
            windows_live_collect.open_mini2_capture = lambda _args: (_ for _ in ()).throw(RuntimeError("Mini2 busy"))

            def fail_builder(_args):
                raise AssertionError("official converter should not be built when Mini2 is unavailable")

            windows_live_collect.build_official_converter = fail_builder
            try:
                windows_live_collect.run(args, visible_camera=visible)
            finally:
                windows_live_collect.open_mini2_capture = old_open
                windows_live_collect.build_official_converter = old_builder

            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 2)
            self.assertIn("visible_R_mean", rows[0])
            self.assertEqual(rows[0]["thermal_source"], "mini2_unavailable")
            self.assertEqual(rows[0]["thermal_calibrated"], "False")
            self.assertEqual(rows[0]["source_quality"], "mini2_unavailable")
            self.assertEqual(rows[0]["mini2_capture_index"], "")
            self.assertEqual(rows[0]["sync_method"], "visible_only_no_thermal")
            self.assertEqual(rows[0]["sync_warning"], "Mini2 frame unavailable")
            self.assertTrue(visible.released)
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["frames"], 2)
            self.assertEqual(summary["mini2_index"], "")
            self.assertEqual(summary["converter"], "mini2_unavailable")

    def test_run_does_not_seed_default_visible_roi_when_auto_roi_is_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "manual-roi-required.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index="auto",
                mini2_max_index=1,
                mini2_backend="AUTO",
                allow_mini2_missing=1,
                mini2_retry_interval_s=3.0,
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=False,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="off",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            visible = FakeVisibleCamera()
            old_open = windows_live_collect.open_mini2_capture
            old_builder = windows_live_collect.build_official_converter
            old_yolo_loader = windows_live_collect.load_yolo_model
            windows_live_collect.open_mini2_capture = lambda _args: (_ for _ in ()).throw(RuntimeError("Mini2 busy"))
            windows_live_collect.build_official_converter = lambda _args: (_ for _ in ()).throw(
                AssertionError("converter should not be built when Mini2 is unavailable")
            )
            windows_live_collect.load_yolo_model = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("YOLO must not load while automatic ROI is off")
            )
            try:
                windows_live_collect.run(args, visible_camera=visible)
            finally:
                windows_live_collect.open_mini2_capture = old_open
                windows_live_collect.build_official_converter = old_builder
                windows_live_collect.load_yolo_model = old_yolo_loader

            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertNotIn("visible_R_mean", row)
            self.assertEqual(row["visible_roi_x"], "")
            self.assertEqual(row["roi_state"], "setup")
            self.assertEqual(row["roi_locked"], "False")

    def test_run_retries_and_recovers_mini2_after_startup_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "recovered-mini2.csv"
            args = Namespace(
                frames=3,
                frame_rate_hz=200.0,
                mini2_index="auto",
                mini2_max_index=2,
                mini2_backend="AUTO",
                allow_mini2_missing=1,
                mini2_retry_interval_s=0.0,
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=True,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="raw",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                roi_link_mode="anchor",
                roi_auto_detect="off",
                roi_auto_min_confidence=0.5,
                roi_auto_every=1,
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            calls = 0
            old_open = windows_live_collect.open_mini2_capture

            def flaky_open(_args):
                nonlocal calls
                calls += 1
                if calls <= 2:
                    raise RuntimeError("Mini2 not ready")
                _args.mini2_backend = "MSMF"
                return FakeMini2Reader(), 4

            windows_live_collect.open_mini2_capture = flaky_open
            try:
                windows_live_collect.run(args, visible_camera=None)
            finally:
                windows_live_collect.open_mini2_capture = old_open

            with out.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertGreaterEqual(calls, 3)
            self.assertEqual(rows[0]["thermal_source"], "mini2_unavailable")
            self.assertTrue(any(row["thermal_source"].startswith("mini2_uvc_raw") for row in rows[1:]))
            self.assertEqual(rows[-1]["mini2_capture_index"], "4")
            self.assertGreaterEqual(int(rows[-1]["mini2_retry_count"]), 2)
            self.assertEqual(int(rows[-1]["mini2_reconnect_count"]), 1)
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["mini2_index"], 4)
            self.assertGreaterEqual(summary["mini2_retry_count"], 2)
            self.assertEqual(summary["mini2_reconnect_count"], 1)

    def test_run_uses_auto_detected_mini2_index_when_no_reader_is_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "auto-index.csv"
            args = Namespace(
                frames=1,
                frame_rate_hz=25.0,
                mini2_index="auto",
                mini2_max_index=5,
                mini2_backend="MSMF",
                mini2_width=MINI2_UVC_WIDTH,
                mini2_height=MINI2_UVC_HEIGHT,
                mini2_fourcc="YUY2",
                visible_index=1,
                visible_backend="MSMF",
                visible_width=160,
                visible_height=120,
                no_visible=True,
                thermal_roi=Roi(0, 0, 16, 16),
                thermal_processing="roi",
                visible_roi="auto",
                metadata_jpeg="fake.jpeg",
                dll_dir="fake_dll",
                output=str(out),
                sync_method="nearest",
                max_sync_offset_ms=20.0,
                print_every=0,
            )
            old_builder = windows_live_collect.build_official_converter
            old_open = windows_live_collect.open_mini2_capture
            windows_live_collect.build_official_converter = lambda _args: FakeOfficialConverter()
            windows_live_collect.open_mini2_capture = lambda _args: (FakeMini2Reader(), 3)
            try:
                windows_live_collect.run(args, visible_camera=None)
            finally:
                windows_live_collect.build_official_converter = old_builder
                windows_live_collect.open_mini2_capture = old_open

            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["mini2_index"], 3)


if __name__ == "__main__":
    unittest.main()
