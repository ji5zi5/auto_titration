import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.hik_whole_apk import critic
from tools.hik_whole_apk import g006_f2_frontier as g006


class G006F2FrontierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def out(self, name="out.json"):
        return self.root / g006.ALLOWED_OUTPUT_ROOT_REL / name

    def read(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def run_ok(self, argv):
        rc = g006.main(argv)
        self.assertEqual(rc, 0)

    def run_cli_error(self, argv):
        with self.assertRaises(SystemExit) as caught:
            g006.main(argv)
        self.assertEqual(caught.exception.code, 2)

    def assert_no_live_or_celsius_success_claims(self, doc):
        text = json.dumps(doc, sort_keys=True).lower()
        forbidden_success_markers = [
            "live_pass",
            "live_success",
            "live proof accepted",
            "celsius_pass",
            "celsius_success",
            "celsius publication allowed",
            '"passed":true',
            '"verdict":"pass"',
        ]
        for marker in forbidden_success_markers:
            self.assertNotIn(marker, text)
        self.assertFalse(doc.get("accepted"), doc)
        self.assertFalse(doc.get("canonical"), doc)


    def assert_all_writing_commands_reject_output_before_side_effects(self, output, proof_ref_path=None):
        if proof_ref_path is None:
            proof_ref_path = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "proof-ref.json"
        command_args = {
            "probe": [],
            "prepare-frontier": [],
            "record-frontier": [
                "--checkpoint-proof-ref", str(proof_ref_path),
                "--owner", "owner",
                "--next-discriminating-experiment", "next",
            ],
            "validate": [],
        }
        with mock.patch.object(
            g006.shutil,
            "which",
            side_effect=AssertionError("probe must reject before probing"),
        ) as which, \
             mock.patch.object(g006, "_read_bounded_json", side_effect=AssertionError("record must reject before reading proof refs")) as read_json, \
             mock.patch.object(g006.critic, "_validate_f2_checkpoint_proof") as validate_proof, \
             mock.patch.object(g006.critic, "validate_f2_frontier") as validate_frontier, \
             mock.patch.object(g006.critic, "validate_f2_live_e2e") as validate_live, \
             mock.patch.object(g006.critic, "validate_radiometric_truthfulness") as validate_radio:
            for command, extra_args in command_args.items():
                with self.subTest(command=command, output=output):
                    self.run_cli_error([
                        command,
                        "--root", str(self.root),
                        "--output", str(output),
                        *extra_args,
                    ])

        which.assert_not_called()
        read_json.assert_not_called()
        validate_proof.assert_not_called()
        validate_frontier.assert_not_called()
        validate_live.assert_not_called()
        validate_radio.assert_not_called()

    def assert_prepare_frontier_swap_fails_closed(self, swap_path, output):
        authority = self.root / critic.RESEARCH_REL / "static" / "race-authority"
        authority.mkdir(parents=True, exist_ok=True)
        sentinel = authority / output.name
        original = json.dumps({"protected": "race authority"}, sort_keys=True)
        sentinel.write_text(original, encoding="utf-8")
        real_require_allowed_output = g006._require_allowed_output

        def validate_then_swap(root, validated_output):
            real_require_allowed_output(root, validated_output)
            shutil.rmtree(swap_path)
            swap_path.symlink_to(authority, target_is_directory=True)

        with mock.patch.object(
            g006,
            "_require_allowed_output",
            side_effect=validate_then_swap,
        ):
            self.run_cli_error([
                "prepare-frontier",
                "--root", str(self.root),
                "--output", str(output),
            ])

        self.assertTrue(swap_path.is_symlink())
        self.assertEqual(sentinel.read_text(encoding="utf-8"), original)

    def test_parser_exposes_exactly_four_commands(self):
        parser = g006.build_parser()
        subparsers = next(action for action in parser._actions if action.dest == "command")
        self.assertEqual(
            sorted(subparsers.choices),
            ["prepare-frontier", "probe", "record-frontier", "validate"],
        )

    def test_exact_12_checkpoint_order_is_sourced_from_critic(self):
        self.assertEqual(len(critic.F2_CHECKPOINTS), 12)
        output = self.out("template.json")
        self.run_ok([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", str(output),
        ])
        doc = self.read(output)
        self.assertEqual(doc["checkpoint_order"], list(critic.F2_CHECKPOINTS))
        self.assertEqual([row["checkpoint_id"] for row in doc["checkpoints"]], list(critic.F2_CHECKPOINTS))

    def test_path_containment_and_bounded_json_failures(self):
        self.run_cli_error([
            "prepare-frontier",
            "--root", ".",
            "--output", str(self.out("root-relative-fail.json")),
        ])
        self.run_cli_error([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", "relative.json",
        ])
        outside = Path(tempfile.gettempdir()) / "g006-outside.json"
        self.run_cli_error([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", str(outside),
        ])
        oversized = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "oversized-proof-ref.json"
        oversized.write_text("{" + " " * 20 + "}\n", encoding="utf-8")
        self.run_cli_error([
            "record-frontier",
            "--root", str(self.root),
            "--output", str(self.out("draft.json")),
            "--checkpoint-proof-ref", str(oversized),
            "--owner", "owner",
            "--next-discriminating-experiment", "next",
            "--max-json-bytes", "8",
        ])

    def test_nonpositive_max_json_bytes_is_rejected_before_reading(self):
        proof_ref_path = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "proof-ref.json"
        proof_ref_path.write_text("{}", encoding="utf-8")
        for limit in ("0", "-1"):
            with self.subTest(limit=limit), \
                 mock.patch.object(g006, "_read_bounded_json") as read_json, \
                 mock.patch.object(g006.critic, "_validate_f2_checkpoint_proof") as validate_proof:
                output = self.out(f"nonpositive-{limit}.json")
                self.run_cli_error([
                    "record-frontier",
                    "--root", str(self.root),
                    "--output", str(output),
                    "--checkpoint-proof-ref", str(proof_ref_path),
                    "--owner", "owner",
                    "--next-discriminating-experiment", "next",
                    "--max-json-bytes", limit,
                ])
                read_json.assert_not_called()
                validate_proof.assert_not_called()
                self.assertFalse(output.exists())

    def test_direct_script_invocation_bootstraps_repo_root_sys_path(self):
        output = self.out("direct-template.json")
        script = Path(__file__).resolve().parents[1] / "tools/hik_whole_apk/g006_f2_frontier.py"
        result = subprocess.run(
            [
                "python3",
                str(script),
                "prepare-frontier",
                "--root", str(self.root),
                "--output", str(output),
            ],
            cwd=tempfile.gettempdir(),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read(output)["checkpoint_order"], list(critic.F2_CHECKPOINTS))

    def test_probe_is_passive_no_subprocess_and_no_device_nonterminal(self):
        output = self.out("probe.json")
        with mock.patch.object(g006.shutil, "which", return_value=None) as which, \
             mock.patch.object(g006.os.path, "exists", return_value=False) as exists, \
             mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")):
            rc = g006.main([
                "probe",
                "--root", str(self.root),
                "--output", str(output),
            ])
        self.assertEqual(rc, 1)
        which.assert_has_calls([mock.call("adb"), mock.call("frida"), mock.call("frida-ps")], any_order=False)
        exists.assert_called_with("/dev/bus/usb")
        doc = self.read(output)
        self.assertEqual(doc["status"], "nonterminal_readiness")
        self.assertTrue(doc["passive"])
        self.assertFalse(doc["subprocess_used"])
        self.assertFalse(doc["device_writes"])
        self.assertIn("adb", doc["missing"])
        self.assertIn("frida", doc["missing"])
        self.assertIn("frida-ps", doc["missing"])
        self.assertIn("/dev/bus/usb", doc["missing"])

    def test_probe_returns_zero_only_when_every_tool_and_usb_bus_are_available(self):
        output = self.out("probe-ready.json")
        tool_paths = {
            "adb": "/opt/bin/adb",
            "frida": "/opt/bin/frida",
            "frida-ps": "/opt/bin/frida-ps",
        }
        with mock.patch.object(g006.shutil, "which", side_effect=tool_paths.get), \
             mock.patch.object(g006.os.path, "exists", return_value=True), \
             mock.patch.object(subprocess, "run", side_effect=AssertionError("subprocess forbidden")):
            rc = g006.main([
                "probe",
                "--root", str(self.root),
                "--output", str(output),
            ])
        self.assertEqual(rc, 0)
        doc = self.read(output)
        self.assertEqual(doc["status"], "ready")
        self.assertEqual(doc["missing"], [])

    def test_prepare_frontier_is_unsigned_non_live_template_and_mutates_no_canonical_state(self):
        output = self.out("template.json")
        self.run_ok([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", str(output),
            "--owner", "owner-a",
            "--next-discriminating-experiment", "attach an official untouched run proof",
        ])
        doc = self.read(output)
        self.assertEqual(doc["envelope"], "frontier_draft_template")
        self.assertEqual(doc["status"], "draft_untrusted_unsigned_non_live")
        self.assertEqual(doc["last_proven_checkpoint"], "none")
        self.assertEqual(doc["first_missing_checkpoint"], critic.F2_CHECKPOINTS[0])
        self.assertEqual(doc["supporting_bundle_ids"], [])
        self.assertIsNone(doc["updated_by_run_id"])
        self.assertFalse(doc["mutates_canonical_frontier"])
        self.assertFalse(doc["mutates_canonical_ledger"])
        self.assertTrue(all(row["status"] == "missing" for row in doc["checkpoints"]))
        self.assertTrue(all(row["evidence_bundle_ids"] == [] and row["event_refs"] == [] for row in doc["checkpoints"]))
        self.assert_no_live_or_celsius_success_claims(doc)

    def test_record_derives_fields_via_critic_and_remains_draft_only(self):
        proof_ref_path = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "proof-ref.json"
        proof_ref = {"bundle_id": "EVB-PROOF", "path": "proof.json"}
        proof_ref_path.write_text(json.dumps(proof_ref), encoding="utf-8")
        checkpoints = [
            {
                "checkpoint_id": checkpoint,
                "status": "proven" if i < 2 else "missing",
                "claim_id": f"CLM-C{i}" if i < 2 else None,
                "run_id": f"RUN-R{i}" if i < 2 else None,
                "evidence_bundle_ids": [f"EVB-E{i}"] if i < 2 else [],
                "event_refs": [{"event_id": f"EVT-{i}"}] if i < 2 else [],
            }
            for i, checkpoint in enumerate(critic.F2_CHECKPOINTS)
        ]
        proof = {"updated_by_run_id": "RUN-R1", "checkpoints": checkpoints}
        with mock.patch.object(
            g006.critic,
            "_validate_f2_checkpoint_proof",
            return_value=(proof, {"EVB-PROOF", "EVB-E0", "EVB-E1"}, critic.F2_CHECKPOINTS[1], critic.F2_CHECKPOINTS[2], "a" * 64),
        ) as validate_proof:
            output = self.out("recorded.json")
            self.run_ok([
                "record-frontier",
                "--root", str(self.root),
                "--output", str(output),
                "--checkpoint-proof-ref", str(proof_ref_path),
                "--owner", "frontier-owner",
                "--next-discriminating-experiment", "prove checkpoint three on untouched hardware",
            ])
        validate_proof.assert_called_once_with(self.root, proof_ref, require_terminal=False)
        doc = self.read(output)
        self.assertEqual(doc["envelope"], "frontier_draft_recorded")
        self.assertEqual(doc["last_proven_checkpoint"], critic.F2_CHECKPOINTS[1])
        self.assertEqual(doc["first_missing_checkpoint"], critic.F2_CHECKPOINTS[2])
        self.assertEqual(doc["supporting_bundle_ids"], ["EVB-E0", "EVB-E1", "EVB-PROOF"])
        self.assertEqual(doc["updated_by_run_id"], "RUN-R1")
        self.assertFalse(doc["accepted"])
        self.assertFalse(doc["canonical"])
        self.assertFalse(doc["mutates_canonical_frontier"])
        self.assertFalse(doc["mutates_canonical_ledger"])
        self.assert_no_live_or_celsius_success_claims(doc)

    def test_record_rejects_invalid_or_reordered_proof_via_critic(self):
        proof_ref_path = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "proof-ref.json"
        proof_ref_path.write_text(json.dumps({"bundle_id": "EVB-PROOF", "path": "proof.json"}), encoding="utf-8")
        with mock.patch.object(
            g006.critic,
            "_validate_f2_checkpoint_proof",
            side_effect=critic.ContractError("F2 checkpoint proof row 0 identity/status is invalid"),
        ) as validate_proof:
            self.run_cli_error([
                "record-frontier",
                "--root", str(self.root),
                "--output", str(self.out("bad-record.json")),
                "--checkpoint-proof-ref", str(proof_ref_path),
                "--owner", "owner",
                "--next-discriminating-experiment", "next",
            ])
        validate_proof.assert_called_once()
        self.assertFalse(self.out("bad-record.json").exists())

    def test_all_writing_commands_reject_outputs_outside_dedicated_g006_subtree_before_side_effects(self):
        proof_ref_path = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "inputs" / "proof-ref.json"
        proof_ref_path.write_text(json.dumps({"bundle_id": "EVB-PROOF", "path": "proof.json"}), encoding="utf-8")
        expected_draft_root = critic.RESEARCH_REL / "dynamic/g006"
        self.assertEqual(g006.ALLOWED_OUTPUT_ROOT_REL, expected_draft_root)
        protected_relatives = (
            critic.RESEARCH_REL / "governance/official-artifacts.json",
            critic.RESEARCH_REL / "specs/index.json",
            critic.RESEARCH_REL / "dynamic/evidence/EVB-HOSTILE/manifest.json",
            Path("tools/hik_whole_apk/g006_f2_frontier.py"),
            critic.RESEARCH_REL / "dynamic/f2-current-causal-frontier.json",
            critic.RESEARCH_REL / "dynamic/f2-live-e2e.json",
            critic.RESEARCH_REL / "reproduction/radiometric-validation.json",
            critic.RESEARCH_REL / "static/ledger.json",
        )
        sentinels = {}
        for relative_path in protected_relatives:
            protected = self.root / relative_path
            protected.parent.mkdir(parents=True, exist_ok=True)
            sentinel = json.dumps({"protected": relative_path.as_posix()}, sort_keys=True)
            protected.write_text(sentinel, encoding="utf-8")
            sentinels[protected] = sentinel

        command_args = {
            "probe": [],
            "prepare-frontier": [],
            "record-frontier": [
                "--checkpoint-proof-ref", str(proof_ref_path),
                "--owner", "owner",
                "--next-discriminating-experiment", "next",
            ],
            "validate": [],
        }
        with mock.patch.object(
            g006.shutil,
            "which",
            side_effect=AssertionError("probe must reject before probing"),
        ) as which, \
             mock.patch.object(g006, "_read_bounded_json", side_effect=AssertionError("record must reject before reading proof refs")) as read_json, \
             mock.patch.object(g006.critic, "_validate_f2_checkpoint_proof") as validate_proof, \
             mock.patch.object(g006.critic, "validate_f2_frontier") as validate_frontier, \
             mock.patch.object(g006.critic, "validate_f2_live_e2e") as validate_live, \
             mock.patch.object(g006.critic, "validate_radiometric_truthfulness") as validate_radio:
            for command, extra_args in command_args.items():
                for relative_path in protected_relatives:
                    with self.subTest(command=command, relative_path=relative_path):
                        protected = self.root / relative_path
                        self.run_cli_error([
                            command,
                            "--root", str(self.root),
                            "--output", str(protected),
                            *extra_args,
                        ])
                        self.assertEqual(protected.read_text(encoding="utf-8"), sentinels[protected])

        which.assert_not_called()
        read_json.assert_not_called()
        validate_proof.assert_not_called()
        validate_frontier.assert_not_called()
        validate_live.assert_not_called()
        validate_radio.assert_not_called()


    def test_symlinked_dedicated_output_root_rejects_all_writes_before_side_effects(self):
        if os.name != "posix":
            self.skipTest("symlink security tests require POSIX")
        allowed_root = self.root / g006.ALLOWED_OUTPUT_ROOT_REL
        targets = [
            critic.RESEARCH_REL / "governance",
            critic.RESEARCH_REL / "static",
        ]
        for target_relative in targets:
            with self.subTest(target=target_relative):
                if allowed_root.exists() or allowed_root.is_symlink():
                    if allowed_root.is_symlink():
                        allowed_root.unlink()
                    else:
                        shutil.rmtree(allowed_root)
                target = self.root / target_relative
                target.mkdir(parents=True, exist_ok=True)
                sentinel = target / "authority-sentinel.json"
                original = json.dumps({"protected": target_relative.as_posix()}, sort_keys=True)
                sentinel.write_text(original, encoding="utf-8")
                allowed_root.symlink_to(target, target_is_directory=True)
                self.assert_all_writing_commands_reject_output_before_side_effects(
                    allowed_root / sentinel.name,
                    proof_ref_path=self.root / "proof-ref-does-not-need-to-exist.json",
                )
                self.assertEqual(sentinel.read_text(encoding="utf-8"), original)
                allowed_root.unlink()

        allowed_root.mkdir(parents=True, exist_ok=True)
        (allowed_root / "inputs").mkdir()

    def test_symlinked_output_file_rejects_all_writes_before_side_effects(self):
        if os.name != "posix":
            self.skipTest("symlink security tests require POSIX")
        protected = self.root / critic.RESEARCH_REL / "static" / "authority-sentinel.json"
        protected.parent.mkdir(parents=True, exist_ok=True)
        original = json.dumps({"protected": "static authority"}, sort_keys=True)
        protected.write_text(original, encoding="utf-8")
        output = self.out("linked-authority.json")
        output.symlink_to(protected)

        self.assert_all_writing_commands_reject_output_before_side_effects(output)
        self.assertEqual(protected.read_text(encoding="utf-8"), original)

    def test_non_directory_output_parent_rejects_all_writes_before_side_effects(self):
        parent = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "not-a-directory"
        original = json.dumps({"protected": "ordinary file parent"}, sort_keys=True)
        parent.write_text(original, encoding="utf-8")

        self.assert_all_writing_commands_reject_output_before_side_effects(parent / "out.json")
        self.assertEqual(parent.read_text(encoding="utf-8"), original)

    def test_fd_anchored_writer_rejects_allowed_root_swap_after_validation(self):
        if os.name != "posix":
            self.skipTest("directory-FD security tests require POSIX")
        allowed_root = self.root / g006.ALLOWED_OUTPUT_ROOT_REL
        self.assert_prepare_frontier_swap_fails_closed(
            allowed_root,
            allowed_root / "authority-sentinel.json",
        )

    def test_fd_anchored_writer_rejects_nested_parent_swap_after_validation(self):
        if os.name != "posix":
            self.skipTest("directory-FD security tests require POSIX")
        nested_parent = self.root / g006.ALLOWED_OUTPUT_ROOT_REL / "race-parent"
        nested_parent.mkdir()
        self.assert_prepare_frontier_swap_fails_closed(
            nested_parent,
            nested_parent / "authority-sentinel.json",
        )

    def test_fd_anchored_writer_atomically_replaces_existing_regular_output(self):
        if os.name != "posix":
            self.skipTest("directory-FD security tests require POSIX")
        output = self.out("replace-existing.json")
        output.write_text('{"old":true}\n', encoding="utf-8")
        real_replace = os.replace
        replace_calls = []

        def anchored_replace(src, dst, *, src_dir_fd=None, dst_dir_fd=None):
            replace_calls.append((src, dst, src_dir_fd, dst_dir_fd))
            return real_replace(
                src,
                dst,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
            )

        with mock.patch.object(g006.os, "replace", new=anchored_replace):
            self.run_ok([
                "prepare-frontier",
                "--root", str(self.root),
                "--output", str(output),
            ])

        self.assertEqual(len(replace_calls), 1)
        src, dst, src_dir_fd, dst_dir_fd = replace_calls[0]
        self.assertEqual(Path(src).name, src)
        self.assertEqual(dst, output.name)
        self.assertIsNotNone(src_dir_fd)
        self.assertEqual(src_dir_fd, dst_dir_fd)
        self.assertEqual(self.read(output)["envelope"], "frontier_draft_template")
        self.assertFalse(any(output.parent.glob(".g006-tmp-*")))

    def test_output_must_be_a_file_below_dedicated_g006_subtree(self):
        allowed_root = self.root / g006.ALLOWED_OUTPUT_ROOT_REL
        self.run_cli_error([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", str(allowed_root),
        ])
        output = allowed_root / "nested" / "draft.json"
        self.run_ok([
            "prepare-frontier",
            "--root", str(self.root),
            "--output", str(output),
        ])
        self.assertEqual(self.read(output)["envelope"], "frontier_draft_template")

    def test_validate_delegates_to_all_three_critics_and_accepts_only_when_all_pass(self):
        output = self.out("validate.json")
        with mock.patch.object(g006.critic, "validate_f2_frontier", return_value=("frontier",)) as f2, \
             mock.patch.object(g006.critic, "validate_f2_live_e2e", return_value=("live",)) as live, \
             mock.patch.object(g006.critic, "validate_radiometric_truthfulness", return_value=("radiometric",)) as radio:
            self.run_ok([
                "validate",
                "--root", str(self.root),
                "--output", str(output),
            ])
        f2.assert_called_once_with(self.root)
        live.assert_called_once_with(self.root)
        radio.assert_called_once_with(self.root)
        doc = self.read(output)
        self.assertEqual(doc["status"], "accepted")
        self.assertTrue(doc["accepted"])
        self.assertEqual(doc["delegated_critics"], [
            "validate_f2_frontier",
            "validate_f2_live_e2e",
            "validate_radiometric_truthfulness",
        ])


    def test_validate_real_missing_canonical_documents_is_explicit_fail_closed(self):
        output = self.out("validate-real-missing.json")
        rc = g006.main([
            "validate",
            "--root", str(self.root),
            "--output", str(output),
        ])
        self.assertEqual(rc, 1)
        doc = self.read(output)
        self.assertEqual(doc["status"], "rejected")
        self.assertFalse(doc["accepted"])
        self.assertEqual(set(doc["failures"]), {
            "validate_f2_frontier",
            "validate_f2_live_e2e",
            "validate_radiometric_truthfulness",
        })
        self.assertIn("dynamic/f2-current-causal-frontier.json", doc["failures"]["validate_f2_frontier"])
        self.assertIn("dynamic/f2-live-e2e.json", doc["failures"]["validate_f2_live_e2e"])
        self.assertIn("reproduction/radiometric-validation.json", doc["failures"]["validate_radiometric_truthfulness"])

    def test_validate_failure_propagates_and_is_not_accepted(self):
        output = self.out("validate-fail.json")
        with mock.patch.object(g006.critic, "validate_f2_frontier", return_value=("frontier",)), \
             mock.patch.object(g006.critic, "validate_f2_live_e2e", side_effect=critic.ContractError("synthetic replay rejected")), \
             mock.patch.object(g006.critic, "validate_radiometric_truthfulness", return_value=("radiometric",)):
            rc = g006.main([
                "validate",
                "--root", str(self.root),
                "--output", str(output),
            ])
        self.assertEqual(rc, 1)
        doc = self.read(output)
        self.assertEqual(doc["status"], "rejected")
        self.assertFalse(doc["accepted"])
        self.assertIn("validate_f2_live_e2e", doc["failures"])
        self.assertFalse(doc["self_attestation_bypass"])
        self.assertFalse(doc["replay_synthetic_static_native_start_only_live_proof_accepted"])


if __name__ == "__main__":
    unittest.main()
