import io
import struct
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from auto_titrator.mini2_live import MINI2_MATRIX_SHAPE
from auto_titrator.official_hikmicro import (
    OfficialDllUnavailable,
    CtypesMtlibRuntime,
    Mini2OfficialMetadata,
    OfficialMtlibConverter,
    POINT_SIZE,
    PIXELS,
    analyzer_csv_truncate_0p1,
    worker_loop,
)


FIXTURE_JPEG = Path("data/fixtures/mini2/IR_00001.jpeg")


class FakeMtlibRuntime:
    def __init__(self):
        self.configs = []
        self.processed = []
        self.closed = []

    def create_handle(self, width, height):
        self.created = (width, height)
        return 1234

    def set_config(self, handle, config_type, data):
        self.configs.append((handle, config_type, bytes(data)))
        return 0

    def process_points(self, handle, process_type, point_bytes, count):
        self.processed.append((handle, process_type, count, point_bytes))
        out = bytearray(point_bytes)
        for index in range(count):
            gray = struct.unpack_from("<i", out, index * POINT_SIZE + 0x04)[0]
            # Fake DLL behavior only for tests: official converter must read
            # the MT_Process_INT int32 Celsius*64 output at offset +0x10.
            struct.pack_into("<i", out, index * POINT_SIZE + 0x10, int(gray) * 64)
        return 0, bytes(out)

    def close(self, handle):
        self.closed.append(handle)


class FastPointFakeMtlibRuntime(FakeMtlibRuntime):
    def __init__(self):
        super().__init__()
        self.fast_processed = []

    def process_single_point_scaled_int(
        self,
        handle,
        process_type,
        gray,
        emissivity_q13,
        reflected_q13,
        distance_q13,
    ):
        self.fast_processed.append(
            (handle, process_type, gray, emissivity_q13, reflected_q13, distance_q13)
        )
        return 0, int(gray) * 64

    def process_points(self, handle, process_type, point_bytes, count):
        raise AssertionError("fast single-point runtime path should avoid byte-buffer processing")


class ConcurrentFastPointFakeMtlibRuntime(FastPointFakeMtlibRuntime):
    def __init__(self):
        super().__init__()
        self._active_lock = threading.Lock()
        self.active_calls = 0
        self.max_active_calls = 0

    def process_single_point_scaled_int(self, *args):
        with self._active_lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            time.sleep(0.002)
            return super().process_single_point_scaled_int(*args)
        finally:
            with self._active_lock:
                self.active_calls -= 1


def fake_metadata() -> Mini2OfficialMetadata:
    tag1_words = np.zeros(512, dtype="<u2")
    tag1_words[284] = 5109
    tag519 = bytearray(64)
    struct.pack_into("<I", tag519, 0x08, 83)
    return Mini2OfficialMetadata(
        tag519=bytes(tag519),
        tag1=tag1_words.tobytes(),
        radiometric_q13={
            "atmospheric_q13": 204800,
            "humidity_q13": 4096,
            "window_trans_q13": 8192,
            "window_temp_milli_c": 25000,
            "emissivity_q13": 8192,
            "reflected_q13": 204800,
            "distance_q13": 8192,
        },
        source_jpeg="fake-mini2.jpeg",
    )


class OfficialHikmicroTests(unittest.TestCase):
    def test_extracts_official_metadata_from_mini2_jpeg(self):
        self.assertTrue(FIXTURE_JPEG.exists(), "Mini2 fixture JPEG is required for metadata extraction")

        metadata = Mini2OfficialMetadata.from_jpeg(FIXTURE_JPEG)

        self.assertGreater(len(metadata.tag519), 1000)
        self.assertEqual(len(metadata.tag1), 1024)
        self.assertGreater(metadata.tag1_u16_284, 0)
        self.assertIn("emissivity_q13", metadata.radiometric_q13)
        self.assertIn("reflected_q13", metadata.radiometric_q13)
        self.assertEqual(metadata.source_jpeg, str(FIXTURE_JPEG))

    def test_ctypes_runtime_refuses_windows_dll_on_linux(self):
        if Path("/mnt/c").exists():
            pass
        if __import__("os").name == "nt":
            self.skipTest("runtime refusal is only for non-Windows test runs")
        with self.assertRaises(OfficialDllUnavailable):
            CtypesMtlibRuntime()

    def test_official_converter_uses_mtlib_configs_and_output_scale(self):
        runtime = FakeMtlibRuntime()
        converter = OfficialMtlibConverter(metadata=fake_metadata(), runtime=runtime, batch_size=PIXELS)
        raw = np.arange(PIXELS, dtype=np.uint16).reshape(MINI2_MATRIX_SHAPE)
        addline_words = np.zeros(512, dtype="<u2")
        addline_words[284] = 777

        matrix = converter.convert_with_addline(raw, addline_words.tobytes())

        self.assertEqual(runtime.created, (256, 192))
        config_types = [item[1] for item in runtime.configs]
        self.assertIn(6, config_types)
        self.assertIn(1, config_types)
        self.assertIn(189, config_types)
        self.assertIn(12, config_types)
        type1_payloads = [data for _h, typ, data in runtime.configs if typ == 1]
        self.assertTrue(any(struct.unpack_from("<II", payload) == (5, 204800) for payload in type1_payloads))
        self.assertTrue(any(struct.unpack_from("<II", payload) == (152, 1) for payload in type1_payloads))
        type189_payloads = [data for _h, typ, data in runtime.configs if typ == 189]
        self.assertEqual(struct.unpack_from("<I", type189_payloads[-1])[0], 777)
        type12_payloads = [data for _h, typ, data in runtime.configs if typ == 12]
        self.assertEqual(len(type12_payloads[-1]), 1024)
        self.assertEqual(type12_payloads[-1], addline_words.tobytes())
        self.assertAlmostEqual(float(matrix[0, 0]), 0.0)
        self.assertAlmostEqual(float(matrix[0, 10]), 10.0)
        self.assertAlmostEqual(float(matrix[-1, -1]), float(raw[-1, -1]))

    def test_official_converter_batches_only_unique_raw_values(self):
        runtime = FakeMtlibRuntime()
        converter = OfficialMtlibConverter(metadata=fake_metadata(), runtime=runtime, batch_size=2)
        raw = np.full(MINI2_MATRIX_SHAPE, 10, dtype=np.uint16)
        raw[0, 2] = 12
        raw[1, 1] = 13
        raw[5, 5] = 12

        matrix = converter.convert_with_addline(raw, fake_metadata().tag1)

        processed_counts = [count for _handle, _process_type, count, _point_bytes in runtime.processed]
        self.assertEqual(processed_counts, [1, 1, 1])
        self.assertEqual(sorted({int(v) for v in raw.reshape(-1)}), [10, 12, 13])
        self.assertAlmostEqual(float(matrix[0, 0]), 10.0)
        self.assertAlmostEqual(float(matrix[0, 2]), 12.0)
        self.assertAlmostEqual(float(matrix[1, 1]), 13.0)

    def test_official_converter_can_convert_roi_raw_values_without_full_matrix(self):
        runtime = FakeMtlibRuntime()
        converter = OfficialMtlibConverter(metadata=fake_metadata(), runtime=runtime, batch_size=PIXELS)
        raw_values = np.array([[10, 12, 10], [13, 12, 14]], dtype=np.uint16)

        converted = converter.convert_values_with_addline(raw_values, fake_metadata().tag1)

        self.assertEqual(converted.shape, raw_values.shape)
        np.testing.assert_allclose(converted, raw_values.astype(np.float64))
        processed_counts = [count for _handle, _process_type, count, _point_bytes in runtime.processed]
        self.assertEqual(processed_counts, [1, 1, 1, 1])

    def test_official_converter_uses_allocation_free_single_point_runtime_when_available(self):
        runtime = FastPointFakeMtlibRuntime()
        metadata = fake_metadata()
        converter = OfficialMtlibConverter(metadata=metadata, runtime=runtime, batch_size=PIXELS)
        raw_values = np.array([[10, 12, 10], [13, 12, 14]], dtype=np.uint16)

        converted = converter.convert_values_with_addline(raw_values, metadata.tag1)

        np.testing.assert_allclose(converted, raw_values.astype(np.float64))
        self.assertEqual([item[2] for item in runtime.fast_processed], [10, 12, 13, 14])
        self.assertTrue(all(item[3] == metadata.radiometric_q13["emissivity_q13"] for item in runtime.fast_processed))

    def test_official_converter_serializes_shared_dll_handle_conversions(self):
        runtime = ConcurrentFastPointFakeMtlibRuntime()
        metadata = fake_metadata()
        converter = OfficialMtlibConverter(metadata=metadata, runtime=runtime)
        barrier = threading.Barrier(3)
        results = []

        def convert(values):
            barrier.wait()
            results.append(converter.convert_values_with_addline(values, metadata.tag1))

        threads = [
            threading.Thread(target=convert, args=(np.array([10, 11, 12], dtype=np.uint16),)),
            threading.Thread(target=convert, args=(np.array([20, 21, 22], dtype=np.uint16),)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=1.0)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(results), 2)
        self.assertEqual(runtime.max_active_calls, 1)

    def test_worker_loop_returns_float64_matrix_payload(self):
        runtime = FakeMtlibRuntime()
        converter = OfficialMtlibConverter(metadata=fake_metadata(), runtime=runtime, batch_size=PIXELS)
        raw = np.ones(MINI2_MATRIX_SHAPE, dtype="<u2") * 12
        addline = fake_metadata().tag1
        request = io.BytesIO(struct.pack("<II", raw.nbytes, len(addline)) + raw.tobytes() + addline)
        response = io.BytesIO()

        worker_loop(converter, request, response)

        response.seek(0)
        status, payload_len = struct.unpack("<II", response.read(8))
        payload = response.read(payload_len)
        matrix = np.frombuffer(payload, dtype="<f8").reshape(MINI2_MATRIX_SHAPE)
        self.assertEqual(status, 0)
        self.assertEqual(payload_len, PIXELS * 8)
        self.assertAlmostEqual(float(matrix[0, 0]), 12.0)

    def test_analyzer_csv_truncate_0p1_matches_floor_semantics(self):
        vals = np.array([20.000, 20.099, 20.100, 20.199, -1.01], dtype=np.float64)
        actual = analyzer_csv_truncate_0p1(vals)
        np.testing.assert_allclose(actual, np.array([20.0, 20.0, 20.1, 20.1, -1.1]))


if __name__ == "__main__":
    unittest.main()
