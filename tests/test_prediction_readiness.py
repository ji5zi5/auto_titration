import csv
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import windows_live_collect


def complete_rows(*, count=8, time_step=0.5, flat=False):
    rows = []
    for index in range(count):
        change = 0.0 if flat else index * 0.25
        rows.append(
            {
                "frame_id": index + 1,
                "time_s": index * time_step,
                "injected_volume_ml": index * 0.1,
                "visible_H_mean": 20.0 + change,
                "visible_S_mean": 0.5 + change * 0.01,
                "visible_V_mean": 0.7 + change * 0.01,
            }
        )
    return rows


class PredictionReadinessTests(unittest.TestCase):
    def test_exact_short_fourteen_row_regression_is_withheld_before_every_path(self):
        rows = complete_rows(count=14, time_step=0.557 / 13.0)
        rows[-1]["predicted_equivalence_volume_ml"] = 0.22588
        buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("unused.csv"),
            endpoint_prediction_model={"artifact_type": "endpoint"},
            typewise_prediction_model={"artifact_type": "typewise"},
            prediction_model={"model_type": "linear"},
        )
        buffer.start_recording(
            experiment_metadata={"sample_concentration_M": 0.0022588},
        )
        for row in rows:
            row["theoretical_equivalence_volume_ml"] = 0.22588
            buffer.add(row)

        with mock.patch.object(windows_live_collect, "predict_type_conditioned_sensor_equivalence") as endpoint, \
             mock.patch.object(windows_live_collect, "predict_typewise_equivalence") as typewise, \
             mock.patch.object(windows_live_collect, "predict_row") as regression, \
             mock.patch.object(windows_live_collect, "estimate_equivalence_point") as peak:
            status = buffer.stop_recording()

        self.assertEqual(status["predicted_equivalence_status"], "withheld")
        self.assertEqual(status["predicted_equivalence_reason"], "insufficient_recording_time_span")
        self.assertNotIn("predicted_equivalence_volume_ml", status)
        self.assertNotIn("sample_concentration_from_predicted_equivalence_M", status)
        endpoint.assert_not_called()
        typewise.assert_not_called()
        regression.assert_not_called()
        peak.assert_not_called()
        exported = list(csv.DictReader(io.StringIO(buffer.to_csv_bytes().decode("utf-8-sig"))))
        self.assertEqual(len(exported), 14)
        self.assertEqual(float(exported[-1]["visible_H_mean"]), rows[-1]["visible_H_mean"])
        self.assertFalse(exported[-1].get("predicted_equivalence_volume_ml"))
        payload = windows_live_collect.build_live_payload({}, rows[-1], csv_status=status)
        self.assertIsNone(payload["predicted_equivalence_volume_ml"])
        self.assertIsNone(payload["sample_concentration_from_predicted_equivalence_M"])
        self.assertEqual(payload["predicted_equivalence_status"], "withheld")

    def test_requires_complete_sensor_group_and_rejects_flat_signals(self):
        incomplete = complete_rows()
        for row in incomplete:
            row.pop("visible_S_mean")
            row["theoretical_equivalence_volume_ml"] = 10.0
            row["sample_concentration_M"] = 0.1
        readiness = windows_live_collect.evaluate_prediction_readiness(incomplete)
        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "insufficient_usable_sensor_time_volume_observations")

        flat = windows_live_collect.evaluate_prediction_readiness(complete_rows(flat=True))
        self.assertFalse(flat.ready)
        self.assertEqual(flat.reason, "flat_recorded_sensor_signals")

        non_finite = complete_rows()
        for row in non_finite:
            row["time_s"] = float("nan")
            row["injected_volume_ml"] = float("inf")
        invalid = windows_live_collect.evaluate_prediction_readiness(non_finite)
        self.assertFalse(invalid.ready)
        self.assertEqual(invalid.usable_observation_count, 0)

    def test_existing_full_run_remains_prediction_ready_without_unknown_concentration(self):
        path = Path("data/labeled/session-16-theory-holdout-predicted.csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            row.pop("sample_concentration_M", None)
            row.pop("theoretical_equivalence_volume_ml", None)

        readiness = windows_live_collect.evaluate_prediction_readiness(rows)

        self.assertTrue(readiness.ready)
        self.assertGreaterEqual(readiness.usable_observation_count, 8)
        self.assertGreaterEqual(readiness.time_span_s, 3.0)

    def test_ready_runs_cover_each_terminal_prediction_path(self):
        expected = {
            "endpoint": "type_conditioned_sensor_model_succeeded",
            "typewise": "typewise_model_succeeded",
            "regression": "json_regression_model_succeeded",
            "peak": "peak_estimator_succeeded",
        }
        for selected, expected_reason in expected.items():
            with self.subTest(selected=selected):
                buffer = windows_live_collect.LiveCsvBuffer(
                    output_path=Path("unused.csv"),
                    endpoint_prediction_model={} if selected in {"endpoint", "typewise", "regression"} else None,
                    typewise_prediction_model={} if selected in {"typewise", "regression"} else None,
                    prediction_model={} if selected == "regression" else None,
                )
                buffer.start_recording(experiment_metadata={"titration_type": "strong_acid_strong_base"})
                for row in complete_rows():
                    buffer.add(row)
                prediction = {
                    "predicted_equivalence_volume_ml": 0.4,
                    "candidate_index": 4,
                    "predicted_equivalence_source": f"{selected}_source",
                }
                endpoint_result = prediction if selected == "endpoint" else ValueError("skip endpoint")
                typewise_result = prediction if selected == "typewise" else ValueError("skip typewise")
                regression_result = prediction if selected == "regression" else ValueError("skip regression")
                with mock.patch.object(
                    windows_live_collect, "predict_type_conditioned_sensor_equivalence",
                    side_effect=endpoint_result if isinstance(endpoint_result, Exception) else None,
                    return_value=None if isinstance(endpoint_result, Exception) else endpoint_result,
                ), mock.patch.object(
                    windows_live_collect, "predict_typewise_equivalence",
                    side_effect=typewise_result if isinstance(typewise_result, Exception) else None,
                    return_value=None if isinstance(typewise_result, Exception) else typewise_result,
                ), mock.patch.object(
                    windows_live_collect, "predict_row",
                    side_effect=regression_result if isinstance(regression_result, Exception) else None,
                    return_value=None if isinstance(regression_result, Exception) else regression_result,
                ), mock.patch.object(
                    windows_live_collect,
                    "estimate_equivalence_point",
                    return_value=SimpleNamespace(
                        estimated_equivalence_volume_ml=0.4,
                        confidence=0.75,
                        evidence=("dynamic sensor progression",),
                        candidate_index=4,
                    ),
                ):
                    status = buffer.stop_recording()

                self.assertEqual(status["predicted_equivalence_status"], "available")
                self.assertEqual(status["predicted_equivalence_reason"], expected_reason)
                self.assertEqual(status["predicted_equivalence_volume_ml"], 0.4)

    def test_ready_run_reports_unavailable_when_every_path_fails(self):
        buffer = windows_live_collect.LiveCsvBuffer(
            output_path=Path("unused.csv"),
            endpoint_prediction_model={},
            typewise_prediction_model={},
            prediction_model={},
        )
        buffer.start_recording(experiment_metadata={"titration_type": "strong_acid_strong_base"})
        for row in complete_rows():
            buffer.add(row)

        with mock.patch.object(
            windows_live_collect, "predict_type_conditioned_sensor_equivalence", side_effect=ValueError("endpoint failed")
        ), mock.patch.object(
            windows_live_collect, "predict_typewise_equivalence", side_effect=ValueError("typewise failed")
        ), mock.patch.object(
            windows_live_collect, "predict_row", side_effect=ValueError("regression failed")
        ), mock.patch.object(
            windows_live_collect, "estimate_equivalence_point", side_effect=ValueError("peak failed")
        ):
            status = buffer.stop_recording()

        self.assertEqual(status["predicted_equivalence_status"], "unavailable")
        self.assertEqual(status["predicted_equivalence_reason"], "no_prediction_path_succeeded")
        self.assertNotIn("predicted_equivalence_volume_ml", status)


if __name__ == "__main__":
    unittest.main()
