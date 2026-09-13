import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "validate_existing_data_report_evidence.py"
)
SPEC = importlib.util.spec_from_file_location("validate_existing_data_report_evidence", SCRIPT)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(validator)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class EvidenceFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.raw_dir = root / "raw"
        self.evidence_dir = root / "evidence"
        self.report = root / "report.md"
        self.manifest = root / "claim_source_manifest.json"
        self.source = root / "sources" / "method.md"
        self._write()

    def _write(self) -> None:
        inventory = []
        for index in range(12):
            row_count = 150 if index == 11 else 152
            raw_path = self.raw_dir / f"run-{index + 1:02d}.csv"
            write_csv(raw_path, ["value"], [{"value": row} for row in range(row_count)])
            inventory.append(
                {
                    "run_id": f"session-{index + 1}",
                    "raw_file": raw_path.name,
                    "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                    "row_count": row_count,
                    "recorded_indicator": "methyl_orange" if index >= 9 else "phenolphthalein",
                    "participant_reported_indicator_correction": (
                        "bromothymol_blue (BTB)" if index >= 9 else "phenolphthalein"
                    ),
                    "indicator_metadata_status": (
                        "participant_reported_not_independently_verified_raw_csv_retained"
                        if index >= 9
                        else "raw_metadata_used"
                    ),
                }
            )
        write_csv(
            self.evidence_dir / "raw_inventory.csv",
            list(inventory[0]),
            inventory,
        )

        metric_rows = [
            {"modality": name, "n_runs": 12, **metrics}
            for name, metrics in validator.EXPECTED_METRICS.items()
        ]
        write_csv(
            self.evidence_dir / "reproduced_modality_metrics.csv",
            ["modality", "n_runs", "mae_ml", "rmse_ml", "mape_percent"],
            metric_rows,
        )
        summary = {
            "analysis_scope": "existing_data_only_no_new_wet_experiment",
            "independent_validation": False,
            "raw_run_count": 12,
            "raw_row_count": 1822,
            "invalid_all_zero_thermal_row_count": 11,
            "reproduced_prediction_metrics": {
                name: {"n_runs": 12, **metrics}
                for name, metrics in validator.EXPECTED_METRICS.items()
            },
            "paired_color_vs_fusion": {
                "mean_ape_improvement_percentage_points": 0.02755986111110953,
                "stratified_bootstrap_95_ci_low_percentage_points": -1.2048307777777805,
                "stratified_bootstrap_95_ci_high_percentage_points": 1.1477844444444398,
                "exact_sign_flip_two_sided_p_value": 0.97802734375,
                "exact_sign_test_two_sided_p_value": 0.7744140625,
                "fusion_better_run_count": 7,
                "fusion_worse_run_count": 5,
            },
            "claim_fail_rules": {
                name: {"pass": False}
                for name in (
                    "fusion_improves_color",
                    "fusion_equivalent_to_color",
                    "universal_thermal_benefit",
                    "conditional_thermal_benefit",
                    "thermal_contrast_predicts_improvement",
                )
            },
        }
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        (self.evidence_dir / "summary.json").write_text(
            json.dumps(summary), encoding="utf-8"
        )
        write_csv(self.evidence_dir / "thermal_snr_by_run.csv", ["run_id"], [{"run_id": f"session-{i}"} for i in range(1, 13)])
        write_csv(self.evidence_dir / "thermal_contrast_by_run.csv", ["run_id"], [{"run_id": f"session-{i}"} for i in range(1, 13)])
        write_csv(self.evidence_dir / "thermal_contrast_window_sensitivity.csv", ["run_id"], [{"run_id": f"session-{i}"} for i in range(1, 13)])
        write_csv(self.evidence_dir / "color_vs_fusion_paired_errors.csv", ["run_id"], [{"run_id": f"session-{i}"} for i in range(1, 13)])
        write_csv(self.evidence_dir / "reaction_type_summary.csv", ["titration_type"], [{"titration_type": "fixture"}])
        write_csv(self.evidence_dir / "model_stability_summary.csv", ["probe"], [{"probe": "fixture"}])
        (self.evidence_dir / "paired_endpoint_errors.png").write_bytes(b"fixture-png")
        (self.evidence_dir / "thermal_contrast_by_run.png").write_bytes(b"fixture-png")
        (self.evidence_dir / "thermal_contrast_vs_fusion_improvement.png").write_bytes(b"fixture-png")
        (self.evidence_dir / "report.md").write_text("derived analysis artifact\n", encoding="utf-8")

        self.report.write_text(
            """# Existing-data report

This report uses only the existing 12 wet runs and does not claim independent wet validation.
For weak-acid/weak-base runs, the research participant later reported bromothymol_blue (BTB), while raw metadata says methyl_orange; no contemporaneous run-linked primary record was found, so this correction is not independently verified and raw CSV bytes remain unchanged.
The 0.962 mL/s value is a geometric design estimate, while 0.99 mL/s is a previously recorded empirical calibration value; neither establishes flow precision or repeatability.
The pulse-control module is a dry, software-only simulation and has no demonstrated wet accuracy benefit.
The primary paired APE improvement was 0.0276 percentage points; the stratified 95% interval was -1.205 to 1.148, with exact sign-flip p=0.978 and sign-test p=0.774.
The operational thermal contrast used 0.05 to 0.20 V/Veq as baseline and 0.95 to 1.05 V/Veq as endpoint, with 1.4826 times baseline MAD as noise.
""",
            encoding="utf-8",
        )
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text("method source\n", encoding="utf-8")
        self.manifest.write_text(
            json.dumps(
                {
                    "claims": [
                        {
                            "claim": "existing-data analysis",
                            "sources": ["sources/method.md", "evidence/summary.json"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    def command(self) -> list[str]:
        return [
            sys.executable,
            str(SCRIPT),
            "--json",
            "--root",
            str(self.root),
            "--raw-dir",
            "raw",
            "--evidence-dir",
            "evidence",
            "--report",
            "report.md",
            "--claim-source-manifest",
            "claim_source_manifest.json",
        ]


class ValidateExistingDataReportEvidenceTests(unittest.TestCase):
    def test_valid_fixture_returns_deterministic_json_and_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            first = subprocess.run(fixture.command(), text=True, capture_output=True)
            second = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            payload = json.loads(first.stdout)
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["observed"]["raw_rows"], 1822)

    def test_hash_mismatch_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            (fixture.raw_dir / "run-01.csv").write_text("value\ntampered\n", encoding="utf-8")
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("sha256 mismatch", result.stdout)

    def test_metric_mismatch_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            path = fixture.evidence_dir / "reproduced_modality_metrics.csv"
            text = path.read_text(encoding="utf-8").replace("1.5520562499999986", "1.0")
            path.write_text(text, encoding="utf-8")
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("metric mismatch", result.stdout)

    def test_unsupported_wet_validation_claim_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            fixture.report.write_text(
                fixture.report.read_text(encoding="utf-8")
                + "The pulse controller was independently validated in wet experiments.\n",
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported wet-validation claim", result.stdout)

    def test_unsupported_flow_precision_claim_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            fixture.report.write_text(
                fixture.report.read_text(encoding="utf-8")
                + "The measured 0.99 mL/s proves excellent flow precision.\n",
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported flow-precision claim", result.stdout)

    def test_unqualified_pulse_module_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            text = fixture.report.read_text(encoding="utf-8").replace(
                "a dry, software-only simulation", "an endpoint controller"
            )
            fixture.report.write_text(text, encoding="utf-8")
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pulse module is not marked dry/software-only", result.stdout)

    def test_missing_btb_metadata_correction_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            fixture.report.write_text(
                fixture.report.read_text(encoding="utf-8").replace(
                    "the research participant later reported bromothymol_blue (BTB), while raw metadata says methyl_orange; no contemporaneous run-linked primary record was found, so this correction is not independently verified and raw CSV bytes remain unchanged.",
                    "The indicator metadata was reviewed.",
                ),
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("report lacks complete BTB correction", result.stdout)

    def test_missing_manifest_source_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EvidenceFixture(Path(temporary))
            fixture.manifest.write_text(
                json.dumps({"claims": [{"sources": ["sources/missing.csv"]}]}),
                encoding="utf-8",
            )
            result = subprocess.run(fixture.command(), text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("manifest source does not exist", result.stdout)


if __name__ == "__main__":
    unittest.main()
