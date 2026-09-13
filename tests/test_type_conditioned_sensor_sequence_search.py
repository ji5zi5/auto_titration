import copy
import json
import tempfile
import unittest
from pathlib import Path

from auto_titrator.ml_typewise_eval import CsvRun, load_runs
from tools import search_advanced_type_conditioned_sensor_rankers as advanced_search
from tools import search_type_conditioned_sensor_union as grid_search
from tools import sensor_transition_candidate_union as candidate_union
from tools import type_conditioned_sensor_sequence_search as search


def synthetic_rows(boundary: int, length: int = 120):
    rows = []
    for frame in range(length):
        changed = frame >= boundary
        rows.append({
            "injected_volume_ml": frame * 0.5,
            "sample_concentration_M": 0.1,
            "theoretical_equivalence_volume_ml": boundary * 0.5,
            "time_s": frame / 25.0,
            "progress_fraction": frame / length,
            "indicator": "legacy_value",
            "visible_H_mean": 25.0 if not changed else 78.0,
            "visible_S_mean": 0.18 if not changed else 0.48,
            "visible_V_mean": 0.45 if not changed else 0.66,
            "thermal_raw_roi_p50": 28.0 if not changed else 30.0,
            "thermal_raw_roi_p95": 29.0 if not changed else 33.0,
        })
    return rows


def make_run(index: int, titration_type: str = "synthetic") -> CsvRun:
    boundary = 50 + index
    return CsvRun(
        path=Path(f"run-{index}.csv"),
        titration_type=titration_type,
        concentration_m=0.1,
        theoretical_equivalence_volume_ml=boundary * 0.5,
        rows=synthetic_rows(boundary),
    )


def synthetic_config(global_weight: float = 0.5) -> search.TypeConditionedConfig:
    return search.TypeConditionedConfig(
        family="pls",
        parameter="rank@1",
        feature_subset="state",
        feature_transform="raw",
        score_normalization="zscore",
        global_weight=global_weight,
        top_k=3,
        softmax_temperature=0.3,
        top_candidate_weight=0.0,
    )


def fake_candidate_sets(runs):
    result = {}
    for run_index, run in enumerate(runs):
        result[str(run.path)] = [
            candidate_union.Candidate(
                boundary=boundary,
                confirmation=boundary + 1,
                features=tuple(
                    (feature + 1) * (candidate_index + 1) + run_index * 0.01
                    for feature in range(34)
                ),
                support=candidate_index + 1,
                sources=("color:test", "thermal:test"),
            )
            for candidate_index, boundary in enumerate((40, 52, 64))
        ]
    return result


class TypeConditionedSensorSequenceSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        runs = load_runs(search.DEFAULT_INPUT_DIR)
        cls.summary = search.evaluate_runs(runs, output_dir=cls.temporary.name)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_context_and_forbidden_input_contract(self):
        self.assertEqual(search.KNOWN_CONTEXT_INPUTS, ("titration_type",))
        for field in (
            "sample_concentration_M", "injected_volume_ml",
            "theoretical_equivalence_volume_ml", "time_s",
            "progress_fraction", "indicator",
        ):
            self.assertIn(field, search.FORBIDDEN_MODEL_INPUTS)
        for config in search.TYPE_CONFIGS.values():
            self.assertEqual(search.forbidden_features(
                search.active_feature_names(config)
            ), [])

    def test_advanced_search_is_bounded_and_matches_final_families(self):
        self.assertEqual(len(advanced_search.specs()), 1242)
        self.assertEqual(
            advanced_search.EXPECTED_SIGNATURE,
            grid_search.EXPECTED_UNION_SIGNATURE,
        )
        self.assertEqual(
            advanced_search.source_sha256(),
            advanced_search.EXPECTED_UNION_SHA256,
        )
        self.assertEqual(
            {key: value.family for key, value in search.TYPE_CONFIGS.items()},
            {
                "strong_acid_strong_base": "pls",
                "weak_acid_strong_base": "lda",
                "strong_acid_weak_base": "kernel_ridge_rbf",
                "weak_acid_weak_base": "qda",
            },
        )
        dense_config = search.TYPE_CONFIGS["weak_acid_strong_base"]
        self.assertEqual(dense_config.global_weight, 0.64)
        self.assertEqual(dense_config.top_k, 26)
        self.assertEqual(dense_config.softmax_temperature, 0.2)

    def test_candidate_generation_ignores_forbidden_metadata(self):
        rows = synthetic_rows(55)
        original = candidate_union.generate_union_candidates(rows)
        changed = copy.deepcopy(rows)
        for frame, row in enumerate(changed):
            row["injected_volume_ml"] = 9999.0 - frame
            row["sample_concentration_M"] = 9.9
            row["theoretical_equivalence_volume_ml"] = -100.0
            row["time_s"] = 5000.0 + frame
            row["progress_fraction"] = -frame
            row["indicator"] = "BTB"
        regenerated = candidate_union.generate_union_candidates(changed)
        self.assertEqual(original, regenerated)

    def test_outer_test_run_is_rejected_from_ranker_fit(self):
        runs = [make_run(index) for index in range(4)]
        with self.assertRaisesRegex(ValueError, "outer test run leaked"):
            search.select_frame(
                runs, runs[-1], fake_candidate_sets(runs), synthetic_config()
            )

    def test_type_model_uses_only_other_same_type_runs(self):
        types = ["a", "a", "a", "b", "b", "b"]
        runs = [make_run(index, value) for index, value in enumerate(types)]
        sets = fake_candidate_sets(runs)
        config = synthetic_config(global_weight=0.5)
        for test_run in runs:
            outer = [run for run in runs if run.path != test_run.path]
            _, _, _, global_paths, type_paths = search.select_frame(
                outer, test_run, sets, config
            )
            self.assertNotIn(str(test_run.path), global_paths)
            self.assertNotIn(str(test_run.path), type_paths)
            self.assertEqual(
                set(type_paths),
                {
                    str(run.path) for run in outer
                    if run.titration_type == test_run.titration_type
                },
            )

    def test_real_data_reproduces_deterministic_0_2950_percent(self):
        summary = self.summary
        self.assertTrue(summary["seed_predictions_identical"])
        self.assertEqual(len(summary["outer_predictions"]), 36)
        for row in summary["per_seed_metrics"]:
            self.assertAlmostEqual(row["mae_ml"], 0.077543, places=6)
            self.assertAlmostEqual(row["rmse_ml"], 0.090773, places=6)
            self.assertAlmostEqual(row["mape_percent"], 0.295000, places=6)
        expected_type_mape = {
            "strong_acid_strong_base": 0.248597,
            "strong_acid_weak_base": 0.315683,
            "weak_acid_strong_base": 0.162756,
            "weak_acid_weak_base": 0.452964,
        }
        for row in summary["stratified_metrics"]:
            self.assertAlmostEqual(
                row["mape_percent"], expected_type_mape[row["titration_type"]], places=6
            )
        self.assertAlmostEqual(
            summary["candidate_union"]["oracle_mape_percent_audit_only"],
            0.295000,
            places=6,
        )
        self.assertAlmostEqual(
            summary["per_seed_metrics"][0]["mape_percent"],
            summary["candidate_union"]["oracle_mape_percent_audit_only"],
            places=6,
        )

    def test_frozen_candidate_signature_matches_runtime_and_grid_search(self):
        self.assertEqual(
            self.summary["candidate_union"]["signature"],
            grid_search.EXPECTED_UNION_SIGNATURE,
        )
        runs = load_runs(search.DEFAULT_INPUT_DIR)
        candidate_sets = {
            str(run.path): candidate_union.generate_union_candidates(run.rows)
            for run in runs
        }
        self.assertEqual(
            search.candidate_union_signature(candidate_sets),
            grid_search.EXPECTED_UNION_SIGNATURE,
        )

    def test_real_output_is_traceable_and_honestly_scoped(self):
        output = Path(self.temporary.name)
        loaded = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            loaded["schema_version"],
            "type_conditioned_sensor_union_development_v3",
        )
        self.assertEqual(loaded["known_context_inputs"], ["titration_type"])
        self.assertEqual(loaded["constant_context_not_used"], {
            "titrant_concentration_M": 0.1,
        })
        self.assertEqual(
            loaded["titrant_context_audit"]["observed_values_M"], [0.1]
        )
        self.assertTrue(
            loaded["titrant_context_audit"]["constant_across_all_recorded_rows"]
        )
        self.assertEqual(loaded["titrant_context_audit"]["total_row_count"], 1822)
        self.assertEqual(
            loaded["titrant_context_audit"]["numeric_value_count"], 1822
        )
        self.assertEqual(
            loaded["titrant_context_audit"]["missing_or_invalid_count"], 0
        )
        self.assertFalse(
            loaded["titrant_context_audit"]["used_as_model_input"]
        )
        self.assertEqual(
            loaded["configuration_search"]["total_combinations_compared"],
            2_030_370,
        )
        self.assertFalse(
            loaded["configuration_search"]
            ["outer_test_truth_excluded_from_configuration_selection"]
        )
        self.assertIn("deterministic repeat check only", loaded["seed_policy"])
        self.assertEqual(len(loaded["provenance"]["input_csv_sha256"]), 12)
        self.assertGreaterEqual(len(loaded["provenance"]["script_sha256"]), 4)
        for digest in (
            list(loaded["provenance"]["input_csv_sha256"].values())
            + list(loaded["provenance"]["script_sha256"].values())
        ):
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertTrue(loaded["leakage_audit"]["passed"])
        self.assertFalse(loaded["split"]["independent_external_validation"])
        for row in loaded["outer_predictions"]:
            self.assertEqual(
                row["model_variant"],
                "type_conditioned_sensor_union_dense_aggregation_ranker",
            )
            self.assertNotIn(row["run_path"], row["global_model_run_paths"])
            self.assertNotIn(row["run_path"], row["type_model_run_paths"])
        self.assertTrue((output / "outer_predictions.csv").exists())
        self.assertTrue((output / "candidate_oracle_audit.csv").exists())
        self.assertTrue((output / "feature_manifest.csv").exists())
        report = (output / "report.md").read_text(encoding="utf-8")
        self.assertIn("독립 검증값은 아니다", report)
        self.assertNotIn("사후분석용", report)

    def test_korean_report_matches_generated_metrics_and_scope(self):
        report_path = (
            search.ROOT / "docs/report_evidence_no_new_wet"
            / "적정종류_조건부_모델_추가결과.md"
        )
        report = report_path.read_text(encoding="utf-8")
        metrics = self.summary["per_seed_metrics"][0]
        self.assertIn(f"{metrics['mae_ml']:.3f} mL", report)
        self.assertIn(f"{metrics['rmse_ml']:.3f} mL", report)
        # The report uses conventional half-up display for the exact
        # 0.295000...% result rather than Python's binary/banker's rounding.
        self.assertIn("0.30%", report)
        self.assertIn("12/12회", report)
        self.assertIn("독립 검증 정확도로 해석하지 않았다", report)
        self.assertIn("현재 주입량과 이론 당량점은 학습 자료", report)
        self.assertIn("2,030,370개 설정 조합", report)
        self.assertNotIn("판별하는 데 유리하였다", report)
        self.assertNotIn("사후분석용", report)


if __name__ == "__main__":
    unittest.main()
