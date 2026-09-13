import pickle
import tempfile
import unittest
from pathlib import Path

import numpy as np

from auto_titrator.typewise_live_model import (
    forbidden_hardware_control_features,
    load_typewise_model,
    score_typewise_rows,
    score_typewise_rows_for_hardware_control,
    validate_hardware_control_model,
)


class RecordingEstimator:
    classes_ = [0, 1]

    def __init__(self, score=0.75):
        self.score = score
        self.features = []

    def predict_proba(self, features):
        self.features = list(features)
        scores = np.full(len(features), self.score, dtype=float)
        return np.column_stack([1.0 - scores, scores])


def make_model(*, feature_columns=None, models=None):
    return {
        "artifact_type": "typewise_frame_zone_classifier_v1",
        "feature_columns": feature_columns
        or ["injected_volume_ml", "visible_color_delta", "titration_type"],
        "categorical_columns": ["titration_type"],
        "models": models
        or {
            "strong_acid_strong_base": {
                "estimator": RecordingEstimator(),
                "model_name": "recording",
            }
        },
    }


class TypewiseHardwareControlSafetyTests(unittest.TestCase):
    def test_loading_rejects_forbidden_endpoint_truth_feature(self):
        model = make_model(
            feature_columns=["visible_color_delta", "theoretical_equivalence_volume_ml"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe.pkl"
            with path.open("wb") as fh:
                pickle.dump(model, fh)

            with self.assertRaisesRegex(ValueError, "forbidden typewise live model feature"):
                load_typewise_model(path)

    def test_hardware_control_rejects_unknown_sample_concentration_and_zone_features(self):
        for forbidden in ("sample_concentration_M", "progress_fraction", "zone_label"):
            with self.subTest(feature=forbidden):
                model = make_model(feature_columns=["visible_color_delta", forbidden])
                with self.assertRaisesRegex(ValueError, "forbidden hardware-control model feature"):
                    score_typewise_rows_for_hardware_control(
                        model,
                        [{"visible_color_delta": 1.0, forbidden: 1.0}],
                        "strong_acid_strong_base",
                    )

    def test_hardware_control_rejects_endpoint_theory_and_leakage_alias_bypasses(self):
        aliases = (
            "endpoint_volume_ml",
            "final_run_volume_ml",
            "known_sample_molarity",
            "visible_endpoint_volume_ml",
            "thermal_theory_volume_ml",
        )
        for alias in aliases:
            with self.subTest(feature=alias):
                model = make_model(feature_columns=["visible_color_delta", alias])
                with self.assertRaisesRegex(
                    ValueError, "forbidden hardware-control model feature"
                ):
                    score_typewise_rows_for_hardware_control(
                        model,
                        [{"visible_color_delta": 1.0, alias: 2.0}],
                        "strong_acid_strong_base",
                    )

    def test_hardware_control_rejects_unknown_non_sensor_numeric_feature(self):
        model = make_model(
            feature_columns=["visible_color_delta", "unreviewed_numeric_metric"]
        )

        with self.assertRaisesRegex(
            ValueError, "forbidden hardware-control model feature"
        ):
            score_typewise_rows_for_hardware_control(
                model,
                [
                    {
                        "visible_color_delta": 0.2,
                        "unreviewed_numeric_metric": 123.0,
                    }
                ],
                "strong_acid_strong_base",
            )

    def test_hardware_control_preserves_sensor_and_current_command_features(self):
        feature_columns = [
            "visible_new_camera_metric",
            "thermal_new_camera_metric",
            "injected_volume_ml",
            "confirmed_injected_volume_ml",
            "commanded_volume_ml",
            "pump_run_rate_ml_per_s",
            "titrant_concentration_M",
            "titrant_valence",
            "titration_type",
        ]

        self.assertEqual(forbidden_hardware_control_features(feature_columns), [])

    def test_hardware_control_allows_known_standard_solution_concentration(self):
        model = make_model(
            feature_columns=[
                "visible_color_delta",
                "titrant_concentration_M",
                "titration_type",
            ]
        )
        scored = score_typewise_rows_for_hardware_control(
            model,
            [
                {
                    "visible_color_delta": 0.2,
                    "titrant_concentration_M": 0.1,
                    "titration_type": "strong_acid_strong_base",
                }
            ],
            "strong_acid_strong_base",
        )
        self.assertEqual(list(scored["scores"]), [0.75])

    def test_hardware_control_rejects_missing_or_nonfinite_required_sensor_feature(self):
        model = make_model()
        base = {"injected_volume_ml": 1.0, "titration_type": "strong_acid_strong_base"}
        for invalid in (None, "", float("nan"), float("inf")):
            with self.subTest(value=invalid):
                row = {**base, "visible_color_delta": invalid}
                with self.assertRaisesRegex(
                    ValueError, "missing or non-finite required sensor feature 'visible_color_delta'"
                ):
                    score_typewise_rows_for_hardware_control(
                        model, [row], "strong_acid_strong_base"
                    )

    def test_hardware_control_requires_numeric_sensor_input_even_if_artifact_marks_it_categorical(self):
        model = make_model(feature_columns=["visible_color_delta"])
        model["categorical_columns"] = ["visible_color_delta"]

        with self.assertRaisesRegex(ValueError, "required sensor feature"):
            score_typewise_rows_for_hardware_control(
                model,
                [{"visible_color_delta": "not-a-number"}],
                "strong_acid_strong_base",
            )

    def test_hardware_control_requires_at_least_one_sensor_feature(self):
        model = make_model(feature_columns=["injected_volume_ml"])

        with self.assertRaisesRegex(ValueError, "requires at least one sensor feature"):
            score_typewise_rows_for_hardware_control(
                model,
                [{"injected_volume_ml": 1.0}],
                "strong_acid_strong_base",
            )

    def test_hardware_control_does_not_fall_back_to_default_model(self):
        model = make_model(
            models={"default": {"estimator": RecordingEstimator(), "model_name": "default"}}
        )
        row = {
            "injected_volume_ml": 1.0,
            "visible_color_delta": 0.2,
            "titration_type": "weak_acid_strong_base",
        }

        with self.assertRaisesRegex(
            ValueError, "no typewise model for titration_type='weak_acid_strong_base'"
        ):
            score_typewise_rows_for_hardware_control(
                model, [row], "weak_acid_strong_base"
            )

        legacy = score_typewise_rows(model, [row], "weak_acid_strong_base")
        self.assertEqual(legacy["model_name"], "default")

    def test_legacy_prediction_keeps_zero_fill_but_strict_option_fails_closed(self):
        estimator = RecordingEstimator()
        model = make_model(
            models={
                "strong_acid_strong_base": {
                    "estimator": estimator,
                    "model_name": "recording",
                }
            }
        )
        row = {"injected_volume_ml": 1.0, "titration_type": "strong_acid_strong_base"}

        score_typewise_rows(model, [row], "strong_acid_strong_base")
        self.assertEqual(estimator.features[0]["visible_color_delta"], 0.0)
        with self.assertRaises(ValueError):
            score_typewise_rows(
                model,
                [row],
                "strong_acid_strong_base",
                strict_hardware_control=True,
            )

    def test_hardware_control_rejects_nonfinite_estimator_score(self):
        model = make_model(
            models={
                "strong_acid_strong_base": {
                    "estimator": RecordingEstimator(float("nan")),
                    "model_name": "broken",
                }
            }
        )
        row = {
            "injected_volume_ml": 1.0,
            "visible_color_delta": 0.2,
            "titration_type": "strong_acid_strong_base",
        }
        with self.assertRaisesRegex(ValueError, "invalid hardware-control scores"):
            score_typewise_rows_for_hardware_control(
                model, [row], "strong_acid_strong_base"
            )

    def test_saved_typewise_model_matches_hardware_control_manifest(self):
        path = Path("data/labeled/typewise-current-volume-classifier.pkl")
        if not path.exists():
            self.skipTest("saved typewise classifier is not available")

        try:
            model = load_typewise_model(path)
        except ModuleNotFoundError as exc:
            if exc.name == "sklearn":
                self.skipTest("scikit-learn is required to load the saved classifier")
            raise

        self.assertIsNotNone(model)
        validate_hardware_control_model(model)


if __name__ == "__main__":
    unittest.main()
