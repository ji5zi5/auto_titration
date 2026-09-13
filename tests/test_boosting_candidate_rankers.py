import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from auto_titrator.ml_typewise_eval import CsvRun
from tools.compare_boosting_candidate_rankers import (
    FEATURE_NAMES,
    aggregate_prediction,
    continuous_quality_labels,
    relevance_labels,
)


class BoostingCandidateRankerTests(unittest.TestCase):
    def test_model_feature_manifest_excludes_answer_and_progress_fields(self):
        blocked = (
            "injected_volume",
            "equivalence",
            "concentration",
            "progress",
            "time_s",
            "actual",
            "predicted",
        )
        self.assertFalse(
            [name for name in FEATURE_NAMES if any(token in name.lower() for token in blocked)]
        )

    def test_relevance_and_continuous_quality_rank_nearest_candidate_highest(self):
        rows = [
            {"injected_volume_ml": 8.0},
            {"injected_volume_ml": 10.0},
            {"injected_volume_ml": 13.0},
        ]
        run = CsvRun(
            path=Path("example.csv"),
            titration_type="strong_acid_strong_base",
            concentration_m=0.1,
            theoretical_equivalence_volume_ml=10.0,
            rows=rows,
        )
        candidates = [SimpleNamespace(boundary=index) for index in range(3)]

        relevance = relevance_labels(run, candidates)
        quality = continuous_quality_labels(run, candidates)

        self.assertEqual(int(np.argmax(relevance)), 1)
        self.assertEqual(int(np.argmax(quality)), 1)

    def test_top1_aggregation_maps_only_selected_candidate_to_volume(self):
        run = CsvRun(
            path=Path("example.csv"),
            titration_type="strong_acid_strong_base",
            concentration_m=0.1,
            theoretical_equivalence_volume_ml=10.0,
            rows=[
                {"injected_volume_ml": 8.0},
                {"injected_volume_ml": 10.0},
                {"injected_volume_ml": 13.0},
            ],
        )
        candidates = [SimpleNamespace(boundary=index) for index in range(3)]

        predicted = aggregate_prediction(
            run,
            candidates,
            np.asarray([0.1, 0.9, 0.2]),
            "top1",
        )

        self.assertEqual(predicted, 10.0)

    def test_saved_comparison_contains_all_three_libraries_without_failures(self):
        path = Path("data/labeled/boosting-candidate-ranker-comparison.json")
        if not path.exists():
            self.skipTest("boosting comparison has not been generated")
        result = json.loads(path.read_text(encoding="utf-8"))
        families = {row["family"].split("_", 1)[0] for row in result["comparison"]}

        self.assertEqual(families, {"xgboost", "lightgbm", "catboost"})
        self.assertEqual(result["failures"], [])
        self.assertEqual(
            result["best_full_12_run_fit_replay"]["family"],
            "lightgbm",
        )
        self.assertLess(
            result["best_full_12_run_fit_replay"]["mean_mape_across_seeds"],
            0.5,
        )


if __name__ == "__main__":
    unittest.main()
