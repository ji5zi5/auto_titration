import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun
from tools import sensor_sequence_endpoint_search as search


def synthetic_rows(boundary: int = 55, length: int = 110):
    rows = []
    for frame in range(length):
        changed = frame >= boundary
        rows.append({
            "injected_volume_ml": frame * 0.5,
            "sample_concentration_M": 0.1,
            "theoretical_equivalence_volume_ml": boundary * 0.5,
            "equivalence_window_label": int(abs(frame - boundary) < 3),
            "progress_fraction": frame / length,
            "visible_H_mean": 25.0 if not changed else 78.0,
            "visible_S_mean": 0.18 if not changed else 0.48,
            "visible_V_mean": 0.45 if not changed else 0.66,
            "thermal_raw_roi_p50": 28.0 if not changed else 30.0,
            "thermal_raw_roi_p95": 29.0 if not changed else 33.0,
        })
    return rows


def make_run(index: int) -> CsvRun:
    boundary = 50 + index
    rows = synthetic_rows(boundary=boundary, length=105 + index)
    for frame, row in enumerate(rows):
        row["injected_volume_ml"] = frame * 0.5
        row["theoretical_equivalence_volume_ml"] = boundary * 0.5
    return CsvRun(
        path=Path(f"run-{index}.csv"), titration_type="synthetic",
        concentration_m=0.1, theoretical_equivalence_volume_ml=boundary * 0.5,
        rows=rows,
    )


class SensorSequenceEndpointSearchTests(unittest.TestCase):
    def test_sensor_matrix_uses_degree_hue_and_normalized_saturation_value(self):
        matrix, thermal_valid = search.sensor_matrix([{
            "visible_H_mean": 90.0,
            "visible_S_mean": 0.5,
            "visible_V_mean": 0.625,
            "thermal_raw_roi_p50": 28.0,
            "thermal_raw_roi_p95": 29.5,
        }])
        self.assertAlmostEqual(matrix[0, 0], 0.0, places=12)
        self.assertAlmostEqual(matrix[0, 1], 0.5, places=12)
        self.assertAlmostEqual(matrix[0, 2], 0.625, places=12)
        self.assertAlmostEqual(matrix[0, 3], 28.0, places=12)
        self.assertAlmostEqual(matrix[0, 4], 1.5, places=12)
        self.assertTrue(thermal_valid[0])

    def test_sensor_prefix_is_invariant_to_late_thermal_availability(self):
        prefix = synthetic_rows(length=70)
        for row in prefix:
            row["thermal_raw_roi_p50"] = ""
            row["thermal_raw_roi_p95"] = ""
        extended = copy.deepcopy(prefix) + synthetic_rows(length=20)
        for row in extended[70:]:
            row["thermal_raw_roi_p50"] = 5000.0
            row["thermal_raw_roi_p95"] = 5040.0
        prefix_matrix, prefix_valid = search.sensor_matrix(prefix)
        extended_matrix, extended_valid = search.sensor_matrix(extended)
        self.assertTrue((prefix_matrix == extended_matrix[:70]).all())
        self.assertTrue((prefix_valid == extended_valid[:70]).all())
        self.assertFalse(prefix_valid.any())

    def test_raw_thermal_single_count_quantization_does_not_emit_transition(self):
        rows = synthetic_rows(length=100)
        for frame, row in enumerate(rows):
            row["visible_H_mean"] = 60.0
            row["visible_S_mean"] = 0.2
            row["visible_V_mean"] = 0.5
            row["thermal_raw_roi_p50"] = 5000.0 + (frame % 2)
            row["thermal_raw_roi_p95"] = 5040.0 + (frame % 2)
        self.assertEqual(search.generate_transition_candidates(rows, modality="fusion"), [])

    def test_forbidden_feature_audit_is_strict_and_manifest_passes(self):
        active = tuple(
            search.MODEL_FEATURE_NAMES[index]
            for index in search.FEATURE_GROUP_INDICES["sensor_context"]
        )
        self.assertTrue(search.audit_model_features(active)["passed"])
        blocked = search.forbidden_features([
            "injected_volume_ml", "sample_concentration_M", "frame_fraction",
            "time_s", "equivalence_window_label", "progress",
        ])
        self.assertEqual(len(blocked), 6)

    def test_candidates_backdate_persistent_synthetic_transition(self):
        candidates = search.generate_transition_candidates(synthetic_rows())
        self.assertLessEqual(len(candidates), 64)
        selected = min(candidates, key=lambda candidate: abs(candidate.boundary_frame - 55))
        self.assertLessEqual(abs(selected.boundary_frame - 55), 2)
        self.assertGreater(selected.confirmation_frame, selected.boundary_frame)
        self.assertEqual(len(selected.features), 13)

    def test_blanking_forbidden_fields_does_not_change_selected_frame(self):
        rows = synthetic_rows()
        original = search.deterministic_select_frame(search.generate_transition_candidates(rows))
        blanked = copy.deepcopy(rows)
        forbidden = (
            "injected_volume_ml", "sample_concentration_M",
            "theoretical_equivalence_volume_ml", "equivalence_window_label",
            "progress_fraction",
        )
        for row in blanked:
            for field in forbidden:
                row[field] = ""
        selected = search.deterministic_select_frame(search.generate_transition_candidates(blanked))
        self.assertEqual(selected, original)

    def test_sensor_context_uses_sensor_state_but_not_forbidden_metadata(self):
        run = make_run(0)
        arm = search.ARMS[0]
        original = search._candidate_sets([run], arm)[str(run.path)]
        self.assertTrue(original)
        self.assertEqual(len(original[0].features), 21)

        changed_rows = copy.deepcopy(run.rows)
        for row in changed_rows[-12:]:
            row["visible_H_mean"] = 160.0
            row["visible_S_mean"] = 0.8
            row["thermal_raw_roi_p50"] = 60.0
            row["thermal_raw_roi_p95"] = 68.0
        changed = CsvRun(
            path=run.path, titration_type="synthetic", concentration_m=0.1,
            theoretical_equivalence_volume_ml=run.theoretical_equivalence_volume_ml,
            rows=changed_rows,
        )
        changed_candidates = search._candidate_sets([changed], arm)[str(run.path)]
        self.assertNotEqual(original[0].features[13:], changed_candidates[0].features[13:])

    def test_future_truncation_and_perturbation_leave_causal_selection_unchanged(self):
        rows = synthetic_rows(length=130)
        full = search.deterministic_select_frame(search.generate_transition_candidates(rows))
        truncated = rows[:85]
        self.assertEqual(
            search.deterministic_select_frame(search.generate_transition_candidates(truncated)), full
        )
        perturbed = copy.deepcopy(rows)
        for row in perturbed[90:]:
            row["visible_H_mean"] = 170.0
            row["visible_S_mean"] = 0.95
            row["visible_V_mean"] = 0.02
            row["thermal_raw_roi_p50"] = 1000.0
            row["thermal_raw_roi_p95"] = 2000.0
        self.assertEqual(
            search.deterministic_select_frame(search.generate_transition_candidates(perturbed)), full
        )

    def test_sequence_ranker_ignores_forbidden_test_fields(self):
        runs = [make_run(index) for index in range(4)]
        train_runs, test_run = runs[:-1], runs[-1]
        arms = (
            search.Arm(
                "test_color", "pairwise_logistic", "color", "signed_log1p", 8, 10, 0.1
            ),
            search.Arm(
                "test_separate", "pairwise_logistic", "separate", "signed_log1p", 8, 10, 0.1
            ),
        )
        original_sets = {arm.name: search._candidate_sets(runs, arm) for arm in arms}
        original_frame, _, _ = search._predict_frame_ensemble(
            train_runs, test_run, original_sets, arms, 42
        )

        blanked_rows = copy.deepcopy(test_run.rows)
        forbidden = (
            "injected_volume_ml", "sample_concentration_M",
            "theoretical_equivalence_volume_ml", "equivalence_window_label",
            "progress_fraction",
        )
        for row in blanked_rows:
            for field in forbidden:
                row[field] = ""
        blanked_run = CsvRun(
            path=test_run.path, titration_type="changed_audit_metadata",
            concentration_m=9.9, theoretical_equivalence_volume_ml=999.0,
            rows=blanked_rows,
        )
        blanked_sets = {arm.name: dict(original_sets[arm.name]) for arm in arms}
        for arm in arms:
            blanked_sets[arm.name][str(test_run.path)] = search.generate_transition_candidates(
                blanked_rows, baseline_frames=arm.baseline_frames,
                window_frames=arm.window_frames, modality="fusion",
            )
        blanked_frame, _, _ = search._predict_frame_ensemble(
            train_runs, blanked_run, blanked_sets, arms, 42
        )
        self.assertEqual(blanked_frame, original_frame)

    def test_output_structure_is_deterministic_and_outer_run_held_out(self):
        runs = [make_run(index) for index in range(4)]
        arms = (
            search.Arm(
                "test_color", "pairwise_logistic", "color", "signed_log1p", 8, 10, 0.1
            ),
            search.Arm(
                "test_separate", "pairwise_logistic", "separate", "signed_log1p", 8, 10, 0.1
            ),
        )
        first = search.evaluate_runs(runs, expected_run_count=4, arms=arms)
        second = search.evaluate_runs(runs, expected_run_count=4, arms=arms)
        self.assertEqual(first["per_seed_metrics"], second["per_seed_metrics"])
        self.assertEqual(first["seeds"], [42, 1729, 20260728])
        self.assertTrue(first["leakage_audit"]["passed"])
        self.assertEqual(first["split"]["inner"], "none_fixed_model")
        self.assertIn("endpoint_localization", first["prediction_scope"])
        self.assertEqual(len(first["outer_predictions"]), 12)
        for row in first["outer_predictions"]:
            self.assertNotIn(row["run_path"], row["selection_run_paths"])

    def test_written_output_reports_every_seed(self):
        runs = [make_run(index) for index in range(4)]
        arms = (
            search.Arm(
                "test_color", "pairwise_logistic", "color", "signed_log1p", 8, 10, 0.1
            ),
            search.Arm(
                "test_separate", "pairwise_logistic", "separate", "signed_log1p", 8, 10, 0.1
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            search.evaluate_runs(
                runs, expected_run_count=4, arms=arms, output_dir=temporary
            )
            loaded = json.loads(Path(temporary, "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(len(loaded["per_seed_metrics"]), 3)
            self.assertTrue(Path(temporary, "outer_predictions.csv").exists())
            self.assertIn("not independent external validation", Path(temporary, "report.md").read_text(encoding="utf-8"))
            self.assertNotIn("retrospective", Path(temporary, "report.md").read_text(encoding="utf-8"))

    def test_seed_and_single_thread_contract(self):
        self.assertEqual(search.SEEDS, (42, 1729, 20260728))
        for variable in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            self.assertEqual(os.environ[variable], "1")
        with self.assertRaisesRegex(ValueError, "seed list must be exactly"):
            search.evaluate_runs([make_run(i) for i in range(4)], expected_run_count=4, seeds=(42,))


if __name__ == "__main__":
    unittest.main()
