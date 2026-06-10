import csv
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools import mini2_formula_research as research


class Mini2FormulaResearchTests(unittest.TestCase):
    def make_frame(self, raw_min=4925, raw_max=5418, offset=4354, scale_source=24, bad_scale_source=2671):
        full = np.zeros((344, 256), dtype="<u2")
        matrix = np.full((192, 256), 5025, dtype=np.uint16)
        matrix[0, 0] = raw_min
        matrix[191, 0] = raw_max
        full[:192] = matrix
        full[340, 5] = offset
        full[340, 10] = bad_scale_source
        full[340, 14] = scale_source
        return full.tobytes()

    def make_frame_with_metadata_positions(
        self,
        *,
        raw_min=4925,
        raw_max=5418,
        offset=4354,
        scale_source=24,
        offset_pos=(200, 7),
        scale_pos=(201, 9),
    ):
        full = np.frombuffer(self.make_frame(raw_min=raw_min, raw_max=raw_max), dtype="<u2").copy().reshape(344, 256)
        full[340, 5] = 0
        full[340, 14] = 0
        full[offset_pos] = offset
        full[scale_pos] = scale_source
        return full.tobytes()

    def test_scores_candidate_formulas_against_app_max_without_near_match_language(self):
        frames = [research.decode_frame(self.make_frame())]

        scores = research.score_builtin_formulas(frames, app_min_c=20.0, app_max_c=37.0)
        by_name = {row["formula_name"]: row for row in scores}

        self.assertEqual(by_name["offset_col5_scale_col10_div100"]["status"], "fail")
        self.assertGreater(float(by_name["offset_col5_scale_col10_div100"]["max_over_app_max_c"]), 2.0)
        self.assertEqual(by_name["offset_col5_scale_col14_plus4"]["status"], "candidate")
        self.assertLessEqual(float(by_name["offset_col5_scale_col14_plus4"]["max_over_app_max_c"]), 2.0)

    def test_process_sequence_writes_formula_scores_and_metadata_search(self):
        with tempfile.TemporaryDirectory() as temp:
            raw_path = Path(temp) / "seq.raw"
            raw_path.write_bytes(self.make_frame() + self.make_frame(raw_min=4936, raw_max=5428, offset=4368, scale_source=25, bad_scale_source=2787))
            out_dir = Path(temp) / "out"

            research.process_sequence(raw_path, out_dir, app_min_c=20.0, app_max_c=37.0)

            score_path = out_dir / "formula_candidate_scores.csv"
            search_path = out_dir / "metadata_affine_search.csv"
            frame_diag_path = out_dir / "frame_level_diagnostics.csv"
            inventory_path = out_dir / "metadata_field_inventory.csv"
            readme_path = out_dir / "READ_ME_FIRST.txt"
            self.assertTrue(score_path.exists())
            self.assertTrue(search_path.exists())
            self.assertTrue(frame_diag_path.exists())
            self.assertTrue(inventory_path.exists())
            self.assertTrue(readme_path.exists())

            with score_path.open(newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            names = {row["formula_name"] for row in rows}
            self.assertIn("offset_col5_scale_col14_plus4", names)
            self.assertIn("offset_col5_scale_col10_div100", names)

            readme = readme_path.read_text(encoding="utf-8")
            self.assertIn("not proven", readme)
            self.assertIn("40C false positive", readme)
            self.assertNotIn("거의", readme)

    def test_metadata_search_scans_bottom_rows_beyond_fixed_row340(self):
        frames = [
            research.decode_frame(
                self.make_frame_with_metadata_positions(raw_min=4925, raw_max=5418, offset=4354, scale_source=24)
            ),
            research.decode_frame(
                self.make_frame_with_metadata_positions(raw_min=4936, raw_max=5428, offset=4368, scale_source=25)
            ),
        ]

        rows = research.search_affine_metadata(frames, app_min_c=20.0, app_max_c=37.0, max_rows=20)

        self.assertTrue(
            any(
                row["offset_row"] == 200
                and row["offset_col"] == 7
                and row["scale_row"] == 201
                and row["scale_col"] == 9
                and row["scale_transform"] == "value_plus_4"
                for row in rows
            ),
            rows[:5],
        )

    def test_formula_research_runner_remains_but_windows_launcher_is_retired(self):
        runner = Path("tools/run_mini2_formula_research_wsl.sh").read_text(encoding="utf-8")
        self.assertFalse(Path("launchers/windows/14_mini2_formula_research_wsl.bat").exists())
        self.assertIn("mini2_formula_research.py", runner)
        self.assertIn("--app-min-c \"$APP_MIN_C\"", runner)
        self.assertIn("--app-max-c \"$APP_MAX_C\"", runner)


if __name__ == "__main__":
    unittest.main()
