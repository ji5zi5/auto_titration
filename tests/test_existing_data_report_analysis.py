import csv
import hashlib
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "analyze_existing_data_report_evidence.py"
SPEC = importlib.util.spec_from_file_location("existing_data_report_analysis", SCRIPT)
analysis = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(analysis)


RAW_FIELDS = [
    "csv_session_id",
    "titration_type",
    "sample_concentration_M",
    "theoretical_equivalence_volume_ml",
    "indicator",
    "injected_volume_ml",
    "thermal_roi_avg",
]

PREDICTION_FIELDS = [
    "run_path",
    "titration_type",
    "actual_equivalence_volume_ml",
    "predicted_equivalence_volume_ml",
]


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class ExistingDataReportAnalysisTests(unittest.TestCase):
    def test_thermal_snr_formula_and_statuses(self):
        inventory = {
            "run_id": "session-1",
            "raw_file": "run.csv",
            "titration_type": "strong_acid_strong_base",
            "theoretical_equivalence_volume_ml": 20.0,
        }
        rows = [
            *[
                {"injected_volume_ml": str(volume), "thermal_roi_avg": str(temperature)}
                for volume, temperature in zip(
                    (1.0, 1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8),
                    (10, 10, 10, 11, 11, 12, 12, 12),
                )
            ],
            *[
                {"injected_volume_ml": str(volume), "thermal_roi_avg": "15"}
                for volume in (19.0, 19.5, 20.0, 20.5, 21.0)
            ],
            {"injected_volume_ml": "22", "thermal_roi_avg": "0"},
        ]
        result = analysis.thermal_snr_for_run(inventory, rows)
        self.assertEqual(result["snr_status"], "ok")
        self.assertEqual(result["baseline_n"], 8)
        self.assertEqual(result["endpoint_n"], 5)
        self.assertEqual(result["invalid_all_zero_thermal_rows"], 1)
        self.assertAlmostEqual(result["signal_signed_delta_c"], 4.0)
        self.assertAlmostEqual(result["baseline_noise_scaled_mad_c"], 1.4826)
        self.assertAlmostEqual(result["snr_ratio"], 4.0 / 1.4826)
        self.assertAlmostEqual(result["snr_db"], 20 * math.log10(4.0 / 1.4826))

        flat = [
            *[
                {"injected_volume_ml": str(1 + index * 0.4), "thermal_roi_avg": "10"}
                for index in range(8)
            ],
            *[
                {"injected_volume_ml": str(19 + index * 0.5), "thermal_roi_avg": "12"}
                for index in range(5)
            ],
        ]
        flat_result = analysis.thermal_snr_for_run(inventory, flat)
        self.assertEqual(flat_result["snr_status"], "zero_or_near_zero_baseline_mad")
        self.assertIsNone(flat_result["snr_ratio"])

        missing_endpoint = rows[:8]
        missing_result = analysis.thermal_snr_for_run(inventory, missing_endpoint)
        self.assertEqual(missing_result["snr_status"], "insufficient_endpoint_values")

        missing_thermal = [
            {"injected_volume_ml": "0", "thermal_roi_avg": ""},
            {"injected_volume_ml": "20", "thermal_roi_avg": "not-a-number"},
        ]
        missing_thermal_result = analysis.thermal_snr_for_run(inventory, missing_thermal)
        self.assertEqual(missing_thermal_result["snr_status"], "missing_valid_thermal_values")

    def test_metrics_bootstrap_and_exact_sign_flip_are_deterministic(self):
        rows = [
            {"actual": 10.0, "predicted": 11.0},
            {"actual": 20.0, "predicted": 18.0},
        ]
        metrics = analysis.error_metrics(rows)
        self.assertAlmostEqual(metrics["mae_ml"], 1.5)
        self.assertAlmostEqual(metrics["rmse_ml"], math.sqrt(2.5))
        self.assertAlmostEqual(metrics["mape_percent"], 10.0)

        first = analysis.paired_bootstrap_ci([1.0, 3.0], seed=7, replicates=100)
        second = analysis.paired_bootstrap_ci([1.0, 3.0], seed=7, replicates=100)
        self.assertEqual(first, second)
        self.assertEqual(first, (1.0, 3.0))
        self.assertEqual(analysis.exact_sign_flip_p_value([1.0, 2.0]), 0.5)
        self.assertEqual(analysis.exact_sign_test_p_value([1.0, -2.0]), 1.0)
        stratified_rows = [
            {"titration_type": "a", "value": 1.0},
            {"titration_type": "a", "value": 3.0},
            {"titration_type": "b", "value": 2.0},
            {"titration_type": "b", "value": 4.0},
        ]
        self.assertEqual(
            analysis.stratified_paired_bootstrap_ci(
                stratified_rows, value_field="value", seed=7, replicates=100
            ),
            analysis.stratified_paired_bootstrap_ci(
                stratified_rows, value_field="value", seed=7, replicates=100
            ),
        )

    def test_end_to_end_fixture_outputs_are_reproducible_and_correct_btb_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_dir = root / "raw"
            prediction_dir = root / "predictions"
            output_a = root / "output-a"
            output_b = root / "output-b"
            run_specs = [
                ("run-a.csv", "1", "strong_acid_strong_base", "phenolphthalein", 21.0),
                ("run-b.csv", "2", "weak_acid_weak_base", "methyl_orange", 18.0),
            ]
            for filename, session, titration_type, indicator, endpoint_temperature in run_specs:
                rows = []
                points = [
                    *zip(
                        (1.0, 1.4, 1.8, 2.2, 2.6, 3.0, 3.4, 3.8),
                        (10, 10, 10, 11, 11, 12, 12, 12),
                    ),
                    *((volume, endpoint_temperature) for volume in (19.0, 19.5, 20.0, 20.5, 21.0)),
                ]
                for volume, temperature in points:
                    rows.append(
                        {
                            "csv_session_id": session,
                            "titration_type": titration_type,
                            "sample_concentration_M": "0.1",
                            "theoretical_equivalence_volume_ml": "20",
                            "indicator": indicator,
                            "injected_volume_ml": volume,
                            "thermal_roi_avg": temperature,
                        }
                    )
                write_csv(raw_dir / filename, RAW_FIELDS, rows)

            modality_predictions = {
                "color_only": (22.0, 18.0),
                "thermal_only": (21.0, 23.0),
                "color_thermal_fusion": (20.5, 19.0),
            }
            for modality, predicted_values in modality_predictions.items():
                rows = []
                for spec, predicted in zip(run_specs, predicted_values):
                    rows.append(
                        {
                            "run_path": f"some/source/{spec[0]}",
                            "titration_type": spec[2],
                            "actual_equivalence_volume_ml": 20,
                            "predicted_equivalence_volume_ml": predicted,
                        }
                    )
                write_csv(
                    prediction_dir / analysis.MODALITY_FILES[modality],
                    PREDICTION_FIELDS,
                    rows,
                )

            summary_a = analysis.analyze(
                raw_dir,
                prediction_dir,
                output_a,
                expected_runs=2,
                expected_rows=26,
                bootstrap_seed=11,
                bootstrap_replicates=200,
                correlation_permutation_seed=12,
                correlation_permutations=200,
            )
            summary_b = analysis.analyze(
                raw_dir,
                prediction_dir,
                output_b,
                expected_runs=2,
                expected_rows=26,
                bootstrap_seed=11,
                bootstrap_replicates=200,
                correlation_permutation_seed=12,
                correlation_permutations=200,
            )
            self.assertEqual(summary_a, summary_b)
            self.assertEqual(summary_a["raw_run_count"], 2)
            self.assertEqual(summary_a["raw_row_count"], 26)
            self.assertAlmostEqual(
                summary_a["reproduced_prediction_metrics"]["color_only"]["mae_ml"], 2.0
            )
            self.assertAlmostEqual(
                summary_a["paired_color_vs_fusion"]["mean_improvement_ml"], 1.25
            )

            inventory = analysis.read_csv(output_a / "raw_inventory.csv")
            corrected = next(row for row in inventory if row["raw_file"] == "run-b.csv")
            self.assertEqual(corrected["recorded_indicator"], "methyl_orange")
            self.assertEqual(
                corrected["participant_reported_indicator_correction"],
                "bromothymol_blue (BTB)",
            )
            self.assertEqual(
                corrected["indicator_metadata_status"],
                "participant_reported_not_independently_verified_raw_csv_retained",
            )
            self.assertEqual(
                hashlib.sha256((raw_dir / "run-b.csv").read_bytes()).hexdigest(),
                corrected["sha256"],
            )

            deterministic_names = [
                "raw_inventory.csv",
                "thermal_snr_by_run.csv",
                "thermal_contrast_by_run.csv",
                "thermal_contrast_window_sensitivity.csv",
                "color_vs_fusion_paired_errors.csv",
                "reproduced_modality_metrics.csv",
                "reaction_type_summary.csv",
                "model_stability_summary.csv",
                "summary.json",
                "report.md",
            ]
            for name in deterministic_names:
                self.assertEqual((output_a / name).read_bytes(), (output_b / name).read_bytes())
            parsed = json.loads((output_a / "summary.json").read_text(encoding="utf-8"))
            self.assertFalse(parsed["independent_validation"])
            self.assertIn("not independently revalidated", parsed["indicator_correction"]["validation_limit"])
            self.assertFalse(
                parsed["indicator_correction"]["run_linked_primary_record_available"]
            )


if __name__ == "__main__":
    unittest.main()
