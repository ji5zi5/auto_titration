import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import pulse_replay_analysis as replay


SCRIPT = Path("tools/pulse_replay_analysis.py")


def write_csv(path, fieldnames, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class PulseReplayAnalysisTests(unittest.TestCase):
    def test_replay_compares_three_policies_with_one_behavior_per_result(self):
        observations = [
            replay.Observation(0.0, 0.0, False),
            replay.Observation(0.2, 0.2, True),
            replay.Observation(0.3, 0.3, False),
            replay.Observation(0.7, 0.4, True),
            replay.Observation(0.9, 0.5, True),
            replay.Observation(1.1, 0.6, True),
        ]

        results = replay.compare_policies(
            observations,
            confirmation_s=0.4,
            settle_s=0.5,
            pulse_steps=5,
            ml_per_step=0.01,
        )

        by_name = {result.policy: result for result in results}
        self.assertAlmostEqual(by_name["continuous_immediate_stop"].stop_time_s, 0.2)
        self.assertAlmostEqual(by_name["continuous_0.4s_confirmed_stop"].stop_time_s, 1.1)
        self.assertEqual(by_name["step5_0.5s_mixed_wait"].pulse_count, 1)
        self.assertAlmostEqual(by_name["step5_0.5s_mixed_wait"].simulated_stop_volume_ml, 0.25)

    def test_loader_accepts_normalized_column_aliases_and_endpoint_boolean(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "variant.csv"
            write_csv(
                path,
                [" Timestamp (sec) ", "Pump Volume (mL)", "Endpoint Detected"],
                [
                    {" Timestamp (sec) ": "10", "Pump Volume (mL)": "1.0", "Endpoint Detected": "no"},
                    {" Timestamp (sec) ": "10.5", "Pump Volume (mL)": "1.2", "Endpoint Detected": "YES"},
                ],
            )

            loaded = replay.load_trace(path)

        self.assertEqual(loaded.columns["time"], " Timestamp (sec) ")
        self.assertEqual(loaded.columns["volume"], "Pump Volume (mL)")
        self.assertEqual(loaded.columns["endpoint"], "Endpoint Detected")
        self.assertEqual(loaded.observations[-1], replay.Observation(0.5, 1.2, True))

    def test_loader_can_derive_endpoint_from_label_alias_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "labels.csv"
            write_csv(
                path,
                ["elapsed_time_s", "injected_ml", "Prediction Label"],
                [
                    {"elapsed_time_s": "0", "injected_ml": "0", "Prediction Label": "before"},
                    {"elapsed_time_s": "0.5", "injected_ml": "0.2", "Prediction Label": "ENDPOINT"},
                ],
            )

            loaded = replay.load_trace(path)

        self.assertFalse(loaded.observations[0].endpoint)
        self.assertTrue(loaded.observations[1].endpoint)

    def test_incomplete_csv_reports_actionable_missing_column_diagnostic(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "incomplete.csv"
            write_csv(path, ["time_s", "value"], [{"time_s": "0", "value": "1"}])

            with self.assertRaisesRegex(replay.DatasetError, "volume.*endpoint"):
                replay.load_trace(path)

    def test_cli_json_is_deterministic_and_disclaims_wet_performance(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "trace.csv"
            write_csv(
                path,
                ["time_s", "injected_volume_ml", "status_label"],
                [
                    {"time_s": "2.0", "injected_volume_ml": "0", "status_label": "before"},
                    {"time_s": "2.4", "injected_volume_ml": "0.4", "status_label": "endpoint"},
                    {"time_s": "2.8", "injected_volume_ml": "0.8", "status_label": "endpoint"},
                ],
            )
            command = [sys.executable, str(SCRIPT), "--json", str(path)]
            first = subprocess.run(command, text=True, capture_output=True)
            second = subprocess.run(command, text=True, capture_output=True)

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertEqual(payload["analysis_type"], "offline_counterfactual_simulation")
        self.assertFalse(payload["claims_wet_performance"])
        self.assertIn("not actual wet performance", payload["disclaimer"].lower())

    def test_repository_inventory_resolves_twelve_runs_and_diagnoses_missing_endpoint_runs(self):
        inventory = Path("data/analysis/report_evidence_no_new_wet/raw_inventory.csv")
        raw_dir = Path("머신러닝용 파일모음")
        if not inventory.exists() or not raw_dir.exists():
            self.skipTest("repository 12-run evidence is unavailable")

        paths, diagnostics = replay.paths_from_inventory(inventory, raw_dir)
        analyses = replay.analyze_paths(paths)

        self.assertEqual(len(paths), 12)
        self.assertEqual(diagnostics, [])
        self.assertEqual(sum(item["usable"] for item in analyses), 10)
        missing = [item for item in analyses if not item["usable"]]
        self.assertEqual(len(missing), 2)
        self.assertTrue(all("no endpoint-positive rows" in item["diagnostic"] for item in missing))


if __name__ == "__main__":
    unittest.main()
