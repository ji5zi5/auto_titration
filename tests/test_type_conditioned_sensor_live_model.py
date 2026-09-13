import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from auto_titrator.type_conditioned_sensor_live_model import (
    ARTIFACT_TYPE,
    load_type_conditioned_sensor_model,
    predict_type_conditioned_sensor_equivalence,
    resample_sensor_rows_by_volume,
    sensor_coverage,
)


class RecordingRegressor:
    def __init__(self):
        self.last_design = None

    def predict(self, design):
        self.last_design = np.asarray(design, dtype=float)
        return self.last_design[:, 0]


def make_artifact(estimator=None):
    return {
        "artifact_type": ARTIFACT_TYPE,
        "model_key": "type-conditioned-sensor-endpoint-v1",
        "development_mape_percent": 0.295,
        "models": {
            "strong_acid_strong_base": {
                "config": {
                    "family": "pls",
                    "feature_indices": [0],
                    "feature_transform": "raw",
                    "score_normalization": "zscore",
                    "global_weight": 1.0,
                    "top_k": 1,
                    "softmax_temperature": 1.0,
                    "top_candidate_weight": 1.0,
                },
                "global_estimator": estimator or RecordingRegressor(),
                "type_estimator": None,
            }
        },
    }


def sensor_row(volume):
    return {
        "injected_volume_ml": volume,
        "visible_H_mean": 20.0 + volume,
        "visible_S_mean": 0.5,
        "visible_V_mean": 0.7,
        "thermal_raw_roi_p50": 1000.0 + volume,
        "thermal_raw_roi_p95": 1010.0 + volume,
    }


class TypeConditionedSensorLiveModelTests(unittest.TestCase):
    def test_volume_resampling_is_invariant_to_duplicate_rows(self):
        rows = [sensor_row(float(index)) for index in range(5)]
        duplicated = [dict(row) for row in rows for _ in range(3)]

        baseline, _ = resample_sensor_rows_by_volume(rows, 0.5)
        repeated, _ = resample_sensor_rows_by_volume(duplicated, 0.5)

        self.assertEqual(baseline, repeated)

    def test_sensor_coverage_rejects_partial_zero_and_inverted_thermal_range(self):
        rows = [sensor_row(1.0), sensor_row(2.0)]
        rows[0]["thermal_raw_roi_p50"] = 0.0
        rows[1]["thermal_raw_roi_p95"] = 900.0

        coverage = sensor_coverage(rows)

        self.assertEqual(coverage["visible"], 1.0)
        self.assertEqual(coverage["thermal"], 0.0)

    def test_loader_accepts_exported_artifact(self):
        artifact = make_artifact()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pkl"
            with path.open("wb") as handle:
                pickle.dump(artifact, handle)

            loaded = load_type_conditioned_sensor_model(path)

        self.assertEqual(loaded["artifact_type"], ARTIFACT_TYPE)

    def test_loader_rejects_old_or_unknown_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.pkl"
            with path.open("wb") as handle:
                pickle.dump({"artifact_type": "other"}, handle)

            with self.assertRaisesRegex(ValueError, "unsupported type-conditioned sensor model"):
                load_type_conditioned_sensor_model(path)

    def test_predicts_volume_from_sensor_selected_candidate(self):
        estimator = RecordingRegressor()
        artifact = make_artifact(estimator)
        candidates = [
            SimpleNamespace(boundary=0, confirmation=0, features=(0.0,)),
            SimpleNamespace(boundary=1, confirmation=1, features=(2.0,)),
            SimpleNamespace(boundary=2, confirmation=2, features=(1.0,)),
        ]
        rows = [sensor_row(8.0), sensor_row(10.0), sensor_row(12.0)]

        with mock.patch(
            "auto_titrator.type_conditioned_sensor_live_model.generate_union_candidates",
            return_value=candidates,
        ):
            result = predict_type_conditioned_sensor_equivalence(
                artifact,
                rows,
                "strong_acid_strong_base",
            )

        self.assertEqual(result["predicted_equivalence_volume_ml"], 10.0)
        self.assertEqual(result["candidate_index"], 1)
        self.assertEqual(
            result["predicted_equivalence_source"],
            "type_conditioned_sensor_endpoint_ranker",
        )
        self.assertEqual(estimator.last_design.shape, (3, 1))

    def test_fold_ensemble_uses_median_endpoint_and_reports_dispersion(self):
        artifact = make_artifact()
        artifact["models"]["strong_acid_strong_base"]["fold_estimators"] = [
            {"global_estimator": RecordingRegressor(), "type_estimator": None},
            {"global_estimator": RecordingRegressor(), "type_estimator": None},
            {"global_estimator": RecordingRegressor(), "type_estimator": None},
        ]
        candidates = [
            SimpleNamespace(boundary=0, confirmation=0, features=(0.0,)),
            SimpleNamespace(boundary=1, confirmation=1, features=(2.0,)),
            SimpleNamespace(boundary=2, confirmation=2, features=(1.0,)),
        ]
        rows = [sensor_row(8.0), sensor_row(10.0), sensor_row(12.0)]

        with mock.patch(
            "auto_titrator.type_conditioned_sensor_live_model.generate_union_candidates",
            return_value=candidates,
        ):
            result = predict_type_conditioned_sensor_equivalence(
                artifact, rows, "strong_acid_strong_base"
            )

        self.assertEqual(result["predicted_equivalence_volume_ml"], 10.0)
        self.assertIn("folds=3", result["predicted_equivalence_evidence"])
        self.assertIn(
            "fold_or_phase_sd_ml=0.000000",
            result["predicted_equivalence_evidence"],
        )

    def test_missing_titration_type_model_fails_without_default(self):
        artifact = make_artifact()
        with self.assertRaisesRegex(ValueError, "no endpoint model"):
            predict_type_conditioned_sensor_equivalence(
                artifact,
                [{"injected_volume_ml": 1.0}],
                "weak_acid_strong_base",
            )

    def test_complete_sensor_dropout_fails_instead_of_returning_high_confidence(self):
        artifact = make_artifact()
        rows = [sensor_row(1.0), sensor_row(2.0)]
        for row in rows:
            row["thermal_raw_roi_p50"] = ""
            row["thermal_raw_roi_p95"] = ""

        with self.assertRaisesRegex(ValueError, "insufficient thermal sensor coverage"):
            predict_type_conditioned_sensor_equivalence(
                artifact, rows, "strong_acid_strong_base"
            )

    def test_saved_site_artifact_contains_all_four_titration_routes(self):
        path = Path("data/labeled/type-conditioned-sensor-endpoint-ranker.pkl")
        if not path.exists():
            self.skipTest("deployed endpoint artifact is not available")

        artifact = load_type_conditioned_sensor_model(path)

        self.assertEqual(
            set(artifact["models"]),
            {
                "strong_acid_strong_base",
                "strong_acid_weak_base",
                "weak_acid_strong_base",
                "weak_acid_weak_base",
            },
        )
        self.assertEqual(artifact["prediction_scope"], "completed_csv_post_run")


if __name__ == "__main__":
    unittest.main()
