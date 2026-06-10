import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import mini2_uvc_matrix_probe as probe


class Mini2UvcMatrixProbeTests(unittest.TestCase):
    def make_frame_bytes(self):
        full = np.zeros((344, 256), dtype="<u2")
        full[:192, :] = np.arange(192 * 256, dtype=np.uint16).reshape(192, 256)
        full[192, :8] = [1587, 1645, 0, 36, 7, 1, 0, 0]
        full[193, :8] = [52445, 43707, 192, 0, 256, 0, 192, 0]
        return full.tobytes()

    def test_extracts_top_256x192_uint16_matrix_from_256x344_frame(self):
        matrix = probe.extract_raw_matrix_candidate(self.make_frame_bytes())

        self.assertEqual(matrix.shape, (192, 256))
        self.assertEqual(matrix.dtype, np.dtype("<u2"))
        self.assertEqual(int(matrix[0, 0]), 0)
        self.assertEqual(int(matrix[191, 255]), 192 * 256 - 1)

    def test_rejects_wrong_raw_frame_size(self):
        with self.assertRaisesRegex(ValueError, "expected 176128 bytes"):
            probe.extract_raw_matrix_candidate(b"too small")

    def test_writes_csv_and_summary_for_candidate_matrix(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "frame.raw"
            out_dir = Path(temp) / "out"
            raw_path.write_bytes(self.make_frame_bytes())

            summary = probe.process_raw_file(raw_path, out_dir)

            csv_path = out_dir / "mini2_raw_matrix_candidate.csv"
            summary_path = out_dir / "summary.json"
            self.assertTrue(csv_path.exists())
            self.assertTrue(summary_path.exists())
            self.assertEqual(summary["matrix_shape"], "192x256")
            self.assertEqual(summary["source_width"], 256)
            self.assertEqual(summary["source_height"], 344)
            self.assertIn("matrix_mean", summary)
            loaded = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["matrix_shape"], "192x256")
            with csv_path.open(newline="", encoding="utf-8") as fh:
                first_row = next(csv.reader(fh))
            self.assertEqual(first_row[:4], ["0", "1", "2", "3"])

    def test_launcher_and_runner_reference_matrix_probe(self):
        runner = Path("tools/run_mini2_uvc_matrix_probe_wsl.sh").read_text(encoding="utf-8")

        self.assertIn("mini2_uvc_matrix_probe.py", runner)
        self.assertIn("256x344", runner)
        self.assertFalse(Path("launchers/windows/12_mini2_uvc_matrix_probe_wsl.bat").exists())

    def test_live_temperature_launcher_and_runner_exist(self):
        runner = Path("tools/run_mini2_live_temperature_matrix_wsl.sh").read_text(encoding="utf-8")

        self.assertIn("mini2_live_temperature_matrix.py", runner)
        self.assertIn("FRAME_RATE_HZ", runner)
        self.assertIn("AFFINE_JSON", runner)
        self.assertIn("LOOKUP_CSV", runner)
        self.assertFalse(Path("launchers/windows/19_mini2_live_temperature_matrix_wsl.bat").exists())


if __name__ == "__main__":
    unittest.main()
