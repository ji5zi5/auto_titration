import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import load_runs
from tools import train_equivalence_current_volume as trainer


class CurrentVolumeNoProgressTrainingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runs = load_runs("머신러닝용 파일모음")

    def test_frame_features_allow_current_volume_but_not_progress_or_labels(self):
        columns = trainer.all_frame_feature_columns(self.runs)
        self.assertIn("injected_volume_ml", columns)
        forbidden = {
            "theoretical_equivalence_volume_ml",
            "distance_to_equivalence_ml",
            "time_to_equivalence_s",
            "sample_concentration_M",
            "csv_row_index",
            "frame_id",
            "time_s",
            "csv_recording_elapsed_s",
            "pump_elapsed_s",
        }
        self.assertTrue(forbidden.isdisjoint(columns), sorted(forbidden.intersection(columns)))
        self.assertFalse(any("fraction" in column.lower() or "progress" in column.lower() for column in columns))

    def test_candidate_features_allow_candidate_volume_but_not_final_run_progress(self):
        rows = trainer._candidate_rows_for_runs(self.runs, max_candidates_per_source=4, good_window_ml=0.5)
        rows = [row for row in rows if not trainer._is_protocol_fraction_candidate_row(row)]
        columns = trainer.safe_candidate_feature_columns(rows)
        self.assertIn("candidate_volume_ml", columns)
        forbidden = {
            "candidate_fraction_of_run",
            "run_volume_max_ml",
            "run_duration_s",
            "candidate_error_ml",
            "candidate_abs_error_ml",
            "actual_equivalence_volume_ml",
            "held_out_concentration_m",
        }
        self.assertTrue(forbidden.isdisjoint(columns), sorted(forbidden.intersection(columns)))

    def test_frame_records_build_with_current_volume(self):
        records, columns = trainer.build_frame_records(self.runs, grid_ml=2.0)
        self.assertGreater(len(records), len(self.runs))
        self.assertIn("injected_volume_ml", columns)
        first = records[0]
        self.assertIn("current_volume_ml", first)
        self.assertIn("actual_ml", first)
        self.assertIn("features", first)



if __name__ == "__main__":
    unittest.main()
