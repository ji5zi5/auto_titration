import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from auto_titrator.color_analysis import Roi
from auto_titrator.feature_history import FeatureSample
from auto_titrator.mini2_live import (
    MINI2_FRAME_RATE_HZ,
    MINI2_IR_HEIGHT,
    MINI2_MATRIX_SHAPE,
    MINI2_RAW_FRAME_BYTES,
    MINI2_UVC_HEIGHT,
    MINI2_UVC_WIDTH,
    Mini2FfmpegRawFrameReader,
    RawAffineCelsiusConverter,
    RawLookupCelsiusConverter,
    ThermalConversionUnavailable,
    _split_worker_command,
    build_temperature_frame,
    extract_mini2_frame_parts,
    extract_mini2_raw_matrix,
    extract_temperature_features,
    load_raw_to_celsius_converter,
)
from auto_titrator.thermal_providers import Mini2RawTemperatureProvider
from tools import mini2_live_temperature_matrix as live_tool


class Mini2LiveTemperatureTests(unittest.TestCase):
    def make_raw_bytes(self, value: int = 5000) -> bytes:
        full = np.zeros((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), dtype="<u2")
        full[:MINI2_IR_HEIGHT, :] = value
        full[10, 20] = value + 100
        full[191, 255] = value + 200
        return full.tobytes()

    def test_extracts_256x192_matrix_from_256x344_raw_frame(self):
        matrix = extract_mini2_raw_matrix(self.make_raw_bytes(5000))

        self.assertEqual(matrix.shape, MINI2_MATRIX_SHAPE)
        self.assertEqual(matrix.dtype, np.dtype("<u2"))
        self.assertEqual(int(matrix[0, 0]), 5000)
        self.assertEqual(int(matrix[10, 20]), 5100)
        self.assertEqual(int(matrix[191, 255]), 5200)

    def test_extracts_addline_tag1_from_two_rows_after_matrix(self):
        full = np.zeros((MINI2_UVC_HEIGHT, MINI2_UVC_WIDTH), dtype="<u2")
        full[:MINI2_IR_HEIGHT, :] = 5000
        full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :] = np.arange(512, dtype=np.uint16).reshape(2, 256)

        parts = extract_mini2_frame_parts(full.tobytes())

        self.assertEqual(parts.raw_matrix.shape, MINI2_MATRIX_SHAPE)
        self.assertEqual(len(parts.addline_tag1), 1024)
        self.assertEqual(parts.addline_tag1, full[MINI2_IR_HEIGHT : MINI2_IR_HEIGHT + 2, :].tobytes())

    def test_affine_converter_builds_celsius_matrix_and_features_without_serializing_array(self):
        raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))
        converter = RawAffineCelsiusConverter(slope_c_per_raw=0.1, intercept_c=-480.0)
        frame = build_temperature_frame(raw_matrix=raw, converter=converter, frame_id=3, timestamp_s=1.25)

        self.assertEqual(frame.temperature_matrix_c.shape, MINI2_MATRIX_SHAPE)
        self.assertAlmostEqual(float(frame.temperature_matrix_c[0, 0]), 20.0)
        self.assertAlmostEqual(float(frame.temperature_matrix_c[191, 255]), 40.0)

        features = extract_temperature_features(
            frame.temperature_matrix_c,
            Roi(0, 0, 32, 32),
            raw_matrix=raw,
            converter_name=frame.converter_name,
            calibration_source=frame.calibration_source,
        )
        self.assertEqual(features["thermal_matrix_shape"], "192x256")
        self.assertEqual(features["thermal_calibrated"], True)
        self.assertEqual(features["thermal_conversion_model"], "raw_affine_celsius")
        self.assertIn("thermal_matrix_max", features)
        self.assertIn("thermal_raw_mean", features)

        row = FeatureSample(time_s=1.25, frame_id=3, injected_volume_ml=0.0, thermal_features=features).to_serializable_row()
        self.assertNotIn("temperature_matrix_c", row)
        self.assertEqual(row["thermal_roi_avg"], features["thermal_roi_avg"])

    def test_temperature_features_include_roi_delta_from_previous_frame(self):
        raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))
        converter = RawAffineCelsiusConverter(slope_c_per_raw=0.1, intercept_c=-480.0)
        first = extract_temperature_features(converter.convert(raw), Roi(0, 0, 16, 16))
        second = extract_temperature_features(converter.convert(raw + 10), Roi(0, 0, 16, 16), previous=first)

        self.assertAlmostEqual(float(second["thermal_roi_delta"]), 1.0)

    def test_missing_converter_refuses_to_create_celsius_matrix(self):
        raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))

        with self.assertRaises(ThermalConversionUnavailable):
            build_temperature_frame(raw_matrix=raw, converter=None, frame_id=0)

    def test_lookup_converter_loads_celsius_column_and_rejects_extrapolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lookup.csv"
            path.write_text("raw_u16,celsius_from_same_csv\n5000,20\n5100,30\n5200,40\n", encoding="utf-8")
            converter = RawLookupCelsiusConverter.from_csv(path)
            raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))

            converted = converter.convert(raw)

            self.assertAlmostEqual(float(converted[0, 0]), 20.0)
            self.assertAlmostEqual(float(converted[10, 20]), 30.0)
            self.assertAlmostEqual(float(converted[191, 255]), 40.0)
            with self.assertRaises(ThermalConversionUnavailable):
                converter.convert(raw + 1000)

    def test_loads_affine_converter_from_roi_calibration_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "roi_formula.json"
            path.write_text(json.dumps({"slope_c_per_raw": 0.025, "intercept_c": -105.25}), encoding="utf-8")

            converter = load_raw_to_celsius_converter({"type": "affine", "path": str(path)})

            self.assertEqual(converter.model_name, "raw_affine_celsius")
            self.assertEqual(converter.calibration_source, str(path))

    def test_worker_command_split_preserves_windows_backslashes(self):
        command = (
            'py.exe -3 tools/mini2_official_mtlib_worker_win.py '
            '--dll-dir "C:\\Program Files\\HIKMICRO Analyzer\\HIKMICRO Analyzer" '
            '--metadata-jpeg "\\\\wsl.localhost\\Ubuntu\\repo\\IR_00001.jpeg"'
        )

        parts = _split_worker_command(command)

        self.assertIn("C:\\Program Files\\HIKMICRO Analyzer\\HIKMICRO Analyzer", parts)
        self.assertIn("\\\\wsl.localhost\\Ubuntu\\repo\\IR_00001.jpeg", parts)

    def test_ffmpeg_reader_uses_25fps_rawvideo_pipe_and_reads_exact_frames(self):
        raw_bytes = self.make_raw_bytes(5000)
        calls = []

        class FakeProcess:
            def __init__(self, command):
                self.command = command
                self.stdout = io.BytesIO(raw_bytes)
                self.stderr = io.BytesIO()
                self.terminated = False

            def poll(self):
                return None if not self.terminated else 0

            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                return 0

            def kill(self):
                self.terminated = True

        def fake_popen(command, stdout, stderr):
            calls.append(command)
            return FakeProcess(command)

        reader = Mini2FfmpegRawFrameReader(device="/dev/video9", popen_factory=fake_popen)
        parts = reader.read_frame_parts()
        reader.close()

        self.assertEqual(parts.raw_matrix.shape, MINI2_MATRIX_SHAPE)
        self.assertEqual(len(parts.addline_tag1), 1024)
        command = calls[0]
        self.assertIn("-framerate", command)
        self.assertIn(str(int(MINI2_FRAME_RATE_HZ)), command)
        self.assertIn("-video_size", command)
        self.assertIn(f"{MINI2_UVC_WIDTH}x{MINI2_UVC_HEIGHT}", command)
        self.assertIn("pipe:1", command)
        self.assertEqual(MINI2_RAW_FRAME_BYTES, len(raw_bytes))

    def test_provider_returns_full_temperature_matrix_and_scalar_roi_features(self):
        raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))

        class Reader:
            def read_raw_matrix(self):
                return raw

            def close(self):
                pass

        provider = Mini2RawTemperatureProvider(
            converter=RawAffineCelsiusConverter(slope_c_per_raw=0.1, intercept_c=-480.0),
            reader=Reader(),
        )
        packet = provider.read()
        features = provider.extract_roi_features(Roi(0, 0, 10, 10), packet=packet)

        self.assertEqual(packet.temperature_matrix_c.shape, MINI2_MATRIX_SHAPE)
        self.assertEqual(features["thermal_source"], "mini2_uvc_raw_celsius")
        self.assertEqual(features["thermal_calibrated"], True)
        self.assertIn("thermal_matrix_avg", features)
        self.assertIn("thermal_roi_p50", features)
        self.assertIn("thermal_roi_range", features)
        self.assertIn("thermal_matrix_p95", features)
        self.assertIn("thermal_raw_p50", features)

    def test_live_tool_writes_feature_csv_without_full_matrix_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "features.csv"
            raw = extract_mini2_raw_matrix(self.make_raw_bytes(5000))

            class FakeReader:
                def __init__(self, *args, **kwargs):
                    self.closed = False

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    self.close()

                def read_raw_matrix(self):
                    return raw

                def close(self):
                    self.closed = True

            original_reader = live_tool.Mini2FfmpegRawFrameReader
            live_tool.Mini2FfmpegRawFrameReader = FakeReader
            try:
                live_tool.main(
                    [
                        "--frames",
                        "1",
                        "--output",
                        str(out),
                        "--slope-c-per-raw",
                        "0.1",
                        "--intercept-c",
                        "-480",
                        "--roi",
                        "0,0,16,16",
                        "--print-every",
                        "0",
                    ]
                )
            finally:
                live_tool.Mini2FfmpegRawFrameReader = original_reader

            self.assertTrue(out.exists())
            self.assertTrue(out.with_suffix(".summary.json").exists())
            self.assertFalse((Path(tmp) / "mini2_raw_matrix_candidate.csv").exists())
            with out.open(newline="", encoding="utf-8") as handle:
                row = next(csv.DictReader(handle))
            self.assertEqual(row["thermal_calibrated"], "True")
            self.assertEqual(row["thermal_matrix_shape"], "192x256")
            summary = json.loads(out.with_suffix(".summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["full_matrix_csv_saved"], False)
