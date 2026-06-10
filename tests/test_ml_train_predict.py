import csv
import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_predict import load_model, load_optional_model, predict_equivalence_volume, predict_row
from auto_titrator.ml_train import DEFAULT_FEATURE_COLUMNS, train_equivalence_model


class MlTrainPredictTests(unittest.TestCase):
    def test_trains_saves_and_loads_simple_equivalence_regression(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "labeled.csv"
            model_path = Path(tmp) / "model.json"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["visible_R_mean", "reference_equivalence_volume_ml"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"visible_R_mean": 10, "reference_equivalence_volume_ml": 9},
                        {"visible_R_mean": 20, "reference_equivalence_volume_ml": 10},
                        {"visible_R_mean": 30, "reference_equivalence_volume_ml": 11},
                    ]
                )

            model = train_equivalence_model(
                [csv_path],
                model_path=model_path,
                feature_columns=["visible_R_mean"],
            )
            loaded = load_model(model_path)
            prediction = predict_equivalence_volume(loaded, {"visible_R_mean": 40})

        self.assertEqual(model["model_type"], "linear_regression_v1")
        self.assertAlmostEqual(prediction, 12.0, places=6)

    def test_sparse_training_uses_constant_model_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "one-row.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=["visible_R_mean", "reference_equivalence_volume_ml"])
                writer.writeheader()
                writer.writerow({"visible_R_mean": 100, "reference_equivalence_volume_ml": 9})

            model = train_equivalence_model([csv_path], feature_columns=["visible_R_mean"], min_rows=3)

        self.assertEqual(model["model_type"], "constant_mean_v1")
        self.assertIn("sparse", " ".join(model["warnings"]).lower())
        self.assertEqual(predict_equivalence_volume(model, {"visible_R_mean": 500}), 9.0)

    def test_predict_row_adds_schema_prediction_field_without_mutating_input(self):
        model = {
            "model_type": "linear_regression_v1",
            "feature_columns": ["visible_R_mean"],
            "target_column": "reference_equivalence_volume_ml",
            "bias": 8.0,
            "weights": [0.1],
            "training_row_count": 3,
            "warnings": [],
        }
        row = {"visible_R_mean": "20"}

        predicted = predict_row(model, row)

        self.assertNotIn("predicted_equivalence_volume_ml", row)
        self.assertEqual(predicted["predicted_equivalence_volume_ml"], 10.0)

    def test_predict_row_calculates_sample_concentration_from_ml_equivalence_volume(self):
        model = {
            "model_type": "linear_regression_v1",
            "feature_columns": ["visible_R_mean"],
            "target_column": "reference_equivalence_volume_ml",
            "bias": 8.0,
            "weights": [0.1],
            "training_row_count": 3,
            "warnings": [],
        }
        row = {
            "visible_R_mean": "20",
            "sample_concentration_M": "0.100",
            "sample_volume_ml": "10.0",
            "sample_valence": "1",
            "titrant_concentration_M": "0.100",
            "titrant_valence": "1",
        }

        predicted = predict_row(model, row)

        self.assertEqual(predicted["predicted_equivalence_volume_ml"], 10.0)
        self.assertEqual(predicted["sample_concentration_from_predicted_equivalence_M"], 0.1)
        self.assertEqual(predicted["predicted_sample_concentration_error_percent"], 0.0)

    def test_optional_model_is_none_until_labeled_training_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_model = Path(tmp) / "missing-model.json"

            self.assertIsNone(load_optional_model(missing_model))

    def test_saved_model_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "labeled.csv"
            model_path = Path(tmp) / "model.json"
            csv_path.write_text(
                "visible_R_mean,reference_equivalence_volume_ml\n10,9\n20,10\n30,11\n",
                encoding="utf-8",
            )

            train_equivalence_model([csv_path], model_path=model_path, feature_columns=["visible_R_mean"])
            payload = json.loads(model_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["feature_columns"], ["visible_R_mean"])
        self.assertIn("bias", payload)

    def test_default_features_and_model_metadata_include_live_analysis_fields(self):
        self.assertIn("thermal_roi_avg", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_p50", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_iqr", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_hot_fraction", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_matrix_avg", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_matrix_p50", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_raw_mean", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_raw_roi_p50", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("sample_concentration_M", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("visible_H_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("visible_HSV_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_H_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_HSV_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("status_confidence", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("visible_H_baseline_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("visible_color_delta_mean_1s", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_avg_baseline_delta", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("thermal_roi_avg_slope_c_per_s", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("abs_sync_offset_ms", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("training_quality_score", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("valid_for_training", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("titration_is_weak_acid_strong_base", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("selected_pka_value", DEFAULT_FEATURE_COLUMNS)
        self.assertIn("theoretical_equivalence_pH", DEFAULT_FEATURE_COLUMNS)
        self.assertNotIn("estimated_equivalence_volume_ml", DEFAULT_FEATURE_COLUMNS)
        self.assertNotIn("theoretical_equivalence_volume_ml", DEFAULT_FEATURE_COLUMNS)

        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "labeled.csv"
            csv_path.write_text(
                "thermal_roi_avg,status_confidence,estimated_equivalence_volume_ml,reference_equivalence_volume_ml\n"
                "20,0.1,8.8,9\n"
                "22,0.6,9.0,9\n"
                "24,0.8,9.2,9\n",
                encoding="utf-8",
            )

            model = train_equivalence_model(
                [csv_path],
                feature_columns=["thermal_roi_avg", "status_confidence", "estimated_equivalence_volume_ml"],
            )

        self.assertEqual(model["metadata"]["feature_version"], "equivalence_features_v4")
        self.assertIn("model_family_decision", model["metadata"])


if __name__ == "__main__":
    unittest.main()
