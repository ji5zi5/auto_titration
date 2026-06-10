import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import mini2_detailed_raw_test as detailed


class Mini2DetailedRawTestTests(unittest.TestCase):
    def make_frame(self, matrix_min=4989, matrix_max=5400):
        full = np.zeros((344, 256), dtype="<u2")
        matrix = np.full((192, 256), 5014, dtype=np.uint16)
        matrix[10, 20] = matrix_min
        matrix[191, 0] = matrix_max
        full[:192, :] = matrix
        # Candidate-like metadata values. These are deliberately not exact.
        full[340, 15] = matrix_max - 1
        full[340, 16] = matrix_min + 5
        full[192, 0] = 1622
        full[192, 1] = 1676
        full[193, 2] = 192
        full[193, 4] = 256
        return full.tobytes()

    def test_analyzes_matrix_and_records_exact_candidate_deltas(self):
        report = detailed.analyze_frame(self.make_frame(), frame_id=3, threshold=8)

        self.assertEqual(report.summary["frame_id"], 3)
        self.assertEqual(report.summary["matrix_shape"], "192x256")
        self.assertEqual(report.summary["matrix_min"], 4989)
        self.assertEqual(report.summary["matrix_max"], 5400)
        self.assertEqual(report.summary["matrix_min_yx"], "10,20")
        self.assertEqual(report.summary["matrix_max_yx"], "191,0")

        row340_max = [row for row in report.candidates if row["row"] == 340 and row["col"] == 15][0]
        row340_min = [row for row in report.candidates if row["row"] == 340 and row["col"] == 16][0]
        self.assertEqual(row340_max["delta_from_matrix_max"], -1)
        self.assertEqual(row340_min["delta_from_matrix_min"], 5)
        self.assertIn("within_threshold_of_matrix_max", row340_max["candidate_flags"])
        self.assertIn("within_threshold_of_matrix_min", row340_min["candidate_flags"])

    def test_rejects_bad_frame_size_without_guessing(self):
        with self.assertRaisesRegex(ValueError, "expected 176128 bytes"):
            detailed.analyze_frame(b"bad", frame_id=0)

    def test_writes_detailed_outputs_without_claiming_calibrated_temperature(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "sequence.raw"
            raw_path.write_bytes(self.make_frame() + self.make_frame(matrix_min=4992, matrix_max=5410))
            out_dir = Path(temp) / "out"

            detailed.process_raw_sequence(raw_path, out_dir, threshold=8)

            summary_csv = out_dir / "frame_summary.csv"
            candidate_csv = out_dir / "metadata_candidate_scan.csv"
            readme = out_dir / "READ_ME_FIRST.txt"
            summary_json = out_dir / "run_summary.json"
            self.assertTrue(summary_csv.exists())
            self.assertTrue(candidate_csv.exists())
            self.assertTrue(readme.exists())
            self.assertTrue(summary_json.exists())

            with summary_csv.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["matrix_min"], "4989")
            self.assertEqual(rows[1]["matrix_max"], "5410")

            candidate_text = candidate_csv.read_text(encoding="utf-8")
            self.assertIn("delta_from_matrix_min", candidate_text)
            self.assertIn("within_threshold_of_matrix_max", candidate_text)

            readme_text = readme.read_text(encoding="utf-8")
            self.assertIn("calibrated Celsius: NO", readme_text)
            self.assertIn("candidate only", readme_text)
            self.assertNotIn("거의 일치", readme_text)
            self.assertNotIn("확정", readme_text)

            loaded = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(loaded["frame_count"], 2)
            self.assertEqual(loaded["calibrated_celsius"], False)


    def test_capture_sequence_opens_v4l2_device_once_for_multiple_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            out_dir = Path(temp) / "out"
            calls = []

            def fake_run(command, capture_output, text, timeout, check):
                calls.append(command)
                output_path = Path(command[-1])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(self.make_frame() + self.make_frame(matrix_min=4992, matrix_max=5410))

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Result()

            original_run = detailed.subprocess.run
            detailed.subprocess.run = fake_run
            try:
                sequence_path = detailed.capture_sequence("/dev/video0", out_dir, frame_count=2, delay_s=0.5)
            finally:
                detailed.subprocess.run = original_run

            self.assertEqual(len(calls), 1)
            self.assertIn("-frames:v", calls[0])
            self.assertIn("2", calls[0])
            self.assertEqual(sequence_path.stat().st_size, detailed.FRAME_BYTES * 2)
            self.assertTrue((out_dir / "raw_frames" / "frame_000.raw").exists())
            self.assertTrue((out_dir / "raw_frames" / "frame_001.raw").exists())

    def test_wsl_runner_exists_but_windows_launcher_is_retired(self):
        runner = Path("tools/run_mini2_detailed_raw_test_wsl.sh").read_text(encoding="utf-8")

        self.assertFalse(Path("launchers/windows/13_mini2_detailed_raw_test_wsl.bat").exists())
        self.assertIn("mini2_detailed_raw_test.py", runner)
        self.assertIn("--frame-count", runner)
        self.assertIn("--delay-s", runner)


if __name__ == "__main__":
    unittest.main()
