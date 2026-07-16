import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.mini2_official_vs_ours_trace import compare_traces, normalize_trace


FIXTURE_DIR = Path("tests/fixtures/mini2")
OFFICIAL = FIXTURE_DIR / "official_expected_trace.json"
OURS = FIXTURE_DIR / "ours_trace_fixture.json"
TOOL = Path("tools/mini2_official_vs_ours_trace.py")


def load_fixture(path=OURS):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Mini2OfficialVsOursTraceTests(unittest.TestCase):
    def test_equal_static_fixture_is_static_fixture_only_compatible(self):
        result = compare_traces(OFFICIAL, OURS)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "static_fixture_only")
        self.assertEqual(result["verdict"], "static_fixture_only")
        self.assertFalse(result["live_parity"])
        self.assertFalse(result["unsupported_hardware_success"])
        self.assertEqual(result["mismatched_fields"], [])

    def test_field_mismatch_is_reported_structurally(self):
        ours = load_fixture()
        ours["steps"][16]["command_id"] = 3999

        result = compare_traces(OFFICIAL, ours)

        self.assertEqual(result["comparison_result"], "mismatch")
        self.assertEqual(result["verdict"], "fail_closed")
        self.assertTrue(any(m.get("field") == "command_id" for m in result["mismatched_fields"]))

    def test_step_ordering_mismatch_fails(self):
        ours = load_fixture()
        ours["steps"][15], ours["steps"][16] = ours["steps"][16], ours["steps"][15]
        # Preserve list order mismatch by changing the official route order numbers too.
        ours["steps"][15]["official_order"] = 16
        ours["steps"][16]["official_order"] = 17
        ours["steps"][15]["name"] = "video_parameters"
        ours["steps"][16]["name"] = "stream_type"

        result = compare_traces(OFFICIAL, ours)

        self.assertEqual(result["comparison_result"], "mismatch")
        self.assertTrue(any(m["kind"] == "step_order" for m in result["mismatched_fields"]))

    def test_missing_provenance_fails_closed_for_live_device(self):
        official = load_fixture(OFFICIAL)
        ours = load_fixture()
        official["evidence_scope"] = "live_device"
        ours["evidence_scope"] = "live_device"
        official["provenance"] = {}
        ours["provenance"] = {}

        result = compare_traces(official, ours)

        self.assertEqual(result["scope_result"], "fail_closed")
        self.assertIn("official_missing_live_provenance", result["scope_errors"])
        self.assertIn("ours_missing_live_provenance", result["scope_errors"])
        self.assertFalse(result["live_parity"])


    def test_missing_static_provenance_fails_closed(self):
        official = load_fixture(OFFICIAL)
        ours = load_fixture()
        official["provenance"] = {}
        official["metadata"].pop("trace_kind", None)
        official["metadata"].pop("sources", None)

        result = compare_traces(official, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "fail_closed")
        self.assertEqual(result["verdict"], "fail_closed")
        self.assertIn("official_missing_static_fixture_provenance", result["scope_errors"])

    def test_app_captured_without_capture_provenance_fails_closed(self):
        official = load_fixture(OFFICIAL)
        ours = load_fixture()
        official["evidence_scope"] = "app_captured"
        ours["evidence_scope"] = "app_captured"
        official["provenance"] = {"app_captured_snapshot": True}
        ours["provenance"] = {"app_captured_snapshot": True}
        official["metadata"].pop("capture_id", None)
        official["metadata"].pop("artifact", None)
        official["metadata"]["capture_kind"] = "app_captured_static_snapshot"
        ours["metadata"].pop("capture_id", None)
        ours["metadata"].pop("artifact", None)
        ours["metadata"]["capture_kind"] = "app_captured_static_snapshot"

        result = compare_traces(official, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "fail_closed")
        self.assertIn("official_missing_app_capture_provenance", result["scope_errors"])
        self.assertIn("ours_missing_app_capture_provenance", result["scope_errors"])

    def test_scope_mismatch_fails_closed(self):
        ours = load_fixture()
        ours["evidence_scope"] = "app_captured"

        result = compare_traces(OFFICIAL, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "fail_closed")
        self.assertIn("scope_mismatch", result["scope_errors"])
        self.assertFalse(result["live_parity"])

    def test_live_without_proof_fails_even_if_route_matches(self):
        official = load_fixture(OFFICIAL)
        ours = load_fixture()
        official["evidence_scope"] = "live_device"
        ours["evidence_scope"] = "live_device"
        official["provenance"] = {"live_device_observation": True}
        ours["provenance"] = {"live_device_observation": True}

        result = compare_traces(official, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "fail_closed")
        self.assertFalse(result["live_parity"])

    def test_explicit_live_proof_allows_live_parity_not_celsius_promotion(self):
        official = load_fixture(OFFICIAL)
        ours = load_fixture()
        proof = {
            "live_device_observation": True,
            "live_observation_proof": {
                "observation_id": "obs-001",
                "captured_at": "2026-07-15T03:00:00Z",
                "device_vid_pid": "11231:258"
            }
        }
        official["evidence_scope"] = "live_device"
        ours["evidence_scope"] = "live_device"
        official["provenance"] = dict(proof)
        ours["provenance"] = dict(proof)

        result = compare_traces(official, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertEqual(result["scope_result"], "live_parity")
        self.assertTrue(result["live_parity"])
        self.assertFalse(result["unsupported_hardware_success"])
        self.assertFalse(result["celsius_promotion_allowed"])

    def test_no_celsius_promotion_from_abi_packet_or_route_similarity(self):
        ours = load_fixture()
        ours["metadata"]["abi_similarity"] = "identical"
        ours["metadata"]["packet_similarity"] = "identical"
        ours["metadata"]["claimed_celsius_matrix"] = "success"

        result = compare_traces(OFFICIAL, ours)

        self.assertEqual(result["comparison_result"], "match")
        self.assertFalse(result["unsupported_hardware_success"])
        self.assertFalse(result["celsius_promotion_allowed"])
        self.assertFalse(result["live_parity"])

    def test_jsonl_events_are_normalized(self):
        trace = normalize_trace(FIXTURE_DIR / "trace_event_fixture.jsonl")

        self.assertEqual(trace.trace_id, "ours-jsonl-fixture")
        self.assertEqual(trace.evidence_scope, "fixture")
        self.assertEqual([step["name"] for step in trace.steps], ["usb_broadcast_dispatch", "main_attach_reaction"])

    def test_cli_behavior_success_and_failure_exit_codes(self):
        success = subprocess.run(
            [sys.executable, str(TOOL), "--official", str(OFFICIAL), "--ours", str(OURS)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(success.returncode, 0, success.stderr)
        success_payload = json.loads(success.stdout)
        self.assertEqual(success_payload["comparison_result"], "match")
        self.assertEqual(success_payload["scope_result"], "static_fixture_only")

        with tempfile.TemporaryDirectory() as tmp:
            mismatch_path = Path(tmp) / "ours_mismatch.json"
            ours = load_fixture()
            ours["steps"][16]["command_id"] = 3999
            mismatch_path.write_text(json.dumps(ours), encoding="utf-8")
            failure = subprocess.run(
                [sys.executable, str(TOOL), "--official", str(OFFICIAL), "--ours", str(mismatch_path)],
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        self.assertEqual(failure.returncode, 1, failure.stderr)
        failure_payload = json.loads(failure.stdout)
        self.assertEqual(failure_payload["comparison_result"], "mismatch")
        self.assertEqual(failure_payload["verdict"], "fail_closed")


if __name__ == "__main__":
    unittest.main()
