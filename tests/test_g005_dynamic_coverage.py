import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.hik_whole_apk import g005_dynamic_coverage as g005


HEX0 = "0" * 64


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(g005.canonical_json_bytes(value))
    return path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def critic_hash(value):
    return g005.critic_canonical_sha256(value)


class G005DynamicCoverageTests(unittest.TestCase):
    def test_parser_has_exactly_five_subcommands(self):
        parser = g005.build_parser()
        subparsers = next(action for action in parser._actions if action.dest == "command")
        self.assertEqual(
            set(subparsers.choices),
            {"probe", "prepare-session", "record-session", "build-convergence", "validate"},
        )

    def test_all_commands_accept_max_filesize_option(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "id.json", {"artifact_set_id": "ART"})
            write_json(root / "ledger.json", {"rows": []})
            write_json(root / "run.json", self.run_manifest())
            write_json(root / "bundles.json", self.bundle_index())
            commands = [
                ["probe", "--output", str(root / "probe.json"), "--max-filesize", "1M"],
                ["prepare-session", "--root", str(root), "--official-identity", "id.json", "--ledger", "ledger.json", "--out", "prep.json", "--max-filesize", "1M"],
                ["record-session", "--root", str(root), "--session-id", "S1", "--run", "run.json", "--bundle-index", "bundles.json", "--ledger-before", "ledger.json", "--ledger-after", "ledger.json", "--out", "proof.json", "--max-filesize", "1M"],
                ["build-convergence", "--root", str(root), "--session-proof", "missing.json", "--canonical-ledger", "ledger.json", "--max-filesize", "1M"],
                ["validate", "--root", str(root), "--convergence", str(g005.CONVERGENCE_REL), "--max-filesize", "1M"],
            ]
            for argv in commands:
                with self.subTest(command=argv[0]):
                    result = g005.run(argv)
                    self.assertIn("ok", result)
                    self.assertNotIn("unrecognized arguments", json.dumps(result))

    def test_argparse_errors_are_bounded_json_with_empty_stderr(self):
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            result = g005.run(["probe"])
        encoded = g005.canonical_json_bytes(result)
        self.assertLess(len(encoded), g005.MAX_BYTES)
        self.assertEqual(stderr.getvalue(), "")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["errors"][0]["field"], "input")

    def test_probe_requires_output_and_writes_deterministic_passive_nonterminal(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "probe.json"
            with mock.patch.object(g005.shutil, "which", return_value=None), mock.patch("pathlib.Path.exists", return_value=False), mock.patch("subprocess.Popen") as popen, mock.patch("subprocess.run") as run:
                first = g005.run(["probe", "--output", str(out)])
                written_first = out.read_bytes()
                second = g005.run(["probe", "--output", str(out)])
                written_second = out.read_bytes()
            self.assertFalse(first["ok"])
            self.assertEqual(first["status"], "nonterminal_readiness")
            self.assertTrue(first["passive"])
            self.assertEqual(first["probes"]["commands"], {"adb": False, "frida": False, "frida-ps": False})
            self.assertEqual(first, second)
            self.assertEqual(written_first, written_second)
            popen.assert_not_called()
            run.assert_not_called()

    def test_path_escape_and_input_size_guards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "id.json", {"artifact_set_id": "ART"})
            huge = root / "huge.json"
            huge.write_bytes(b"{" + b" " * (g005.MAX_BYTES + 1) + b"}")
            result = g005.run(["prepare-session", "--root", str(root), "--official-identity", "../id.json", "--ledger", "huge.json", "--out", "out.json"])
            self.assertFalse(result["ok"])
            self.assertIn("path escape", result["errors"][0]["message"])
            result = g005.run(["prepare-session", "--root", str(root), "--official-identity", "id.json", "--ledger", "huge.json", "--out", "out.json"])
            self.assertFalse(result["ok"])
            self.assertIn("exceeds max size", result["errors"][0]["message"])

    def test_prepare_session_writes_not_live_unsigned_hash_skeleton(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / "id.json", {"artifact_set_id": "ART"})
            write_json(root / "ledger.json", {"rows": []})
            result = g005.run(["prepare-session", "--root", str(root), "--official-identity", "id.json", "--ledger", "ledger.json", "--out", "prep.json"])
            self.assertTrue(result["ok"], result)
            payload = read_json(root / "prep.json")
            self.assertFalse(payload["live"])
            self.assertFalse(payload["signed"])
            self.assertEqual(payload["status"], "prepared_not_live_unsigned")
            self.assertRegex(payload["official_identity"]["sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(payload["ledger"]["canonical_sha256"], r"^[0-9a-f]{64}$")

    @staticmethod
    def env():
        return {
            "device_fingerprint": "dev",
            "camera_fingerprint": "cam",
            "os_build": "os",
            "abi": "arm64",
            "network_profile": "offline",
        }

    def run_manifest(self, *, run_id="RUN-1", variant="untouched", tier="E2", start="2026-01-01T00:00:00Z", end="2026-01-01T00:01:00Z", delta=None):
        run = {
            "artifact_set_id": "ART",
            "run_id": run_id,
            "experiment_id": f"EXP-{run_id}",
            "source_variant": variant,
            "evidence_tier": tier,
            "environment": self.env(),
            "baseline_id": "BASELINE-1",
            "data_state_snapshot": {"sha256": "a" * 64},
            "started_at": start,
            "ended_at": end,
        }
        if delta is not None:
            run["instrumentation_delta"] = delta
        return run

    def bundle_index(self, *, variant="untouched", tier="E2", bundle_id="EVB-1", start="2026-01-01T00:00:30Z", delta=None):
        bundle = dict(self.env(), artifact_set_id="ART", evidence_bundle_id=bundle_id, evidence_tier=tier, source_variant=variant, captured_at=start, claim_ids=["CLAIM-1"], normalized_attachment=f"events/{bundle_id}.json", event_ids=[f"EV-{bundle_id}"])
        if delta is not None:
            bundle["instrumentation_delta"] = delta
        return {"artifact_set_id": "ART", "bundles": [bundle]}

    def write_record_fixture(self, root: Path, *, run=None, bundles=None, before_rows=None, after_rows=None, paired=None):
        write_json(root / "run.json", run or self.run_manifest())
        write_json(root / "bundles.json", bundles or self.bundle_index())
        write_json(root / "before.json", {"rows": [] if before_rows is None else before_rows})
        write_json(root / "after.json", {"rows": [] if after_rows is None else after_rows})
        if paired is not None:
            write_json(root / "paired.json", paired)

    def record_args(self, root: Path, *extra):
        return ["record-session", "--root", str(root), "--session-id", "S1", "--run", "run.json", "--bundle-index", "bundles.json", "--ledger-before", "before.json", "--ledger-after", "after.json", "--out", "proof.json", *extra]

    def test_record_accepts_standalone_untouched_e2_and_writes_meta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_record_fixture(root, before_rows=[{"row_id": "ROW-1"}], after_rows=[{"row_id": "ROW-1"}, {"row_id": "ROW-2", "value": 3}])
            result = g005.run(self.record_args(root))
            self.assertTrue(result["ok"], result)
            proof = read_json(root / "proof.json")
            meta = read_json(root / "proof.json.meta.json")
            self.assertEqual(proof["source_variant"], "untouched")
            self.assertEqual(meta["evidence_tier"], "E2")
            self.assertEqual(meta["new_rows"], 1)
            self.assertEqual(meta["added_row_ids"], ["ROW-2"])
            self.assertEqual(set(proof), g005.PROOF_KEYS)
            self.assertEqual(proof["canonical_sha256"], critic_hash({k: v for k, v in proof.items() if k != "canonical_sha256"}))
            self.assertEqual(
                meta["raw_hashes"],
                {
                    "run": g005.file_hash(root / "run.json"),
                    "bundle_index": g005.file_hash(root / "bundles.json"),
                    "ledger_before": g005.file_hash(root / "before.json"),
                    "ledger_after": g005.file_hash(root / "after.json"),
                    "proof": g005.file_hash(root / "proof.json"),
                },
            )

    def test_record_rejects_fake_live_markers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_record_fixture(root, run=self.run_manifest(variant="synthetic"))
            result = g005.run(self.record_args(root))
            self.assertFalse(result["ok"])
            self.assertIn("not acceptable live", result["errors"][0]["message"])

    def test_record_allows_null_and_empty_temperature_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty_temperature_fields = {
                "temperature_c": None,
                "temperature_note": "",
                "celsius_samples": [],
                "temperature_metadata": {},
                "temperature_enabled": False,
            }
            run = self.run_manifest()
            run.update(empty_temperature_fields)
            bundles = self.bundle_index()
            bundles["bundles"][0].update(empty_temperature_fields)
            self.write_record_fixture(root, run=run, bundles=bundles)
            result = g005.run(self.record_args(root))
            self.assertTrue(result["ok"], result)

    def test_record_rejects_populated_temperature_claims_without_approved_proof(self):
        cases = (
            (
                "numeric bundle field",
                {},
                {"temperature_c": 23.5},
                "bundle 0 contains Celsius/temperature claim without canonical approved radiometric proof",
            ),
            (
                "free-text run claim",
                {"notes": "Measured surface temperature was 23.5 °C"},
                {},
                "run contains Celsius/temperature claim without canonical approved radiometric proof",
            ),
        )
        for label, run_fields, bundle_fields, expected_message in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                run = self.run_manifest()
                run.update(run_fields)
                bundles = self.bundle_index()
                bundles["bundles"][0].update(bundle_fields)
                self.write_record_fixture(root, run=run, bundles=bundles)
                result = g005.run(self.record_args(root))
                self.assertFalse(result["ok"])
                self.assertEqual(result["errors"][0]["message"], expected_message)

    def test_temperature_claims_require_canonical_radiometric_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.run_manifest()
            run.update(
                {
                    "temperature_c": 23.5,
                    "approved_radiometric_proof": True,
                    "radiometric_validation": "approved",
                }
            )
            self.write_record_fixture(root, run=run)
            result = g005.run(self.record_args(root))
            self.assertFalse(result["ok"])
            self.assertIn("canonical approved radiometric proof", result["errors"][0]["message"])

            with mock.patch.object(
                g005.critic,
                "validate_radiometric_truthfulness",
                return_value=("radiometric-validation.json", "celsius_publication_allowed=true"),
            ) as validate:
                result = g005.run(self.record_args(root))
            self.assertTrue(result["ok"], result)
            validate.assert_called()

    def test_untouched_e2_rejects_instrumentation_and_replay_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.run_manifest(delta={"hooks": ["hook-a"]})
            self.write_record_fixture(root, run=run)
            result = g005.run(self.record_args(root))
            self.assertFalse(result["ok"])
            self.assertIn("untouched E2 run declares instrumentation", result["errors"][0]["message"])

            self.write_record_fixture(root, run=self.run_manifest(variant="replay-only"))
            result = g005.run(self.record_args(root))
            self.assertFalse(result["ok"])
            self.assertIn("not acceptable live", result["errors"][0]["message"])

    def test_record_rejects_e3_without_pairing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_record_fixture(
                root,
                run=self.run_manifest(
                    variant="root-attached",
                    tier="E3",
                    delta={"hook": "enabled", "paired_untouched_run_id": "RUN-0"},
                ),
                bundles=self.bundle_index(variant="root-attached", tier="E3", delta={"hook": "enabled"}),
            )
            result = g005.run(self.record_args(root))
            self.assertFalse(result["ok"])
            self.assertIn("--paired-untouched-run", result["errors"][0]["message"])

    def test_record_accepts_instrumented_e3_only_with_immediately_prior_untouched_e2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            instrumentation_delta = {
                "hook": "enabled",
                "paired_untouched_run_id": "RUN-0",
            }
            self.write_record_fixture(
                root,
                run=self.run_manifest(
                    variant="root-attached",
                    tier="E3",
                    start="2026-01-01T00:01:00Z",
                    end="2026-01-01T00:02:00Z",
                    delta=instrumentation_delta,
                ),
                bundles=self.bundle_index(variant="root-attached", tier="E3", start="2026-01-01T00:01:30Z", delta={"hook": "enabled"}),
                paired=self.run_manifest(run_id="RUN-0", variant="untouched", tier="E2", start="2026-01-01T00:00:00Z", end="2026-01-01T00:01:00Z"),
            )
            result = g005.run(self.record_args(root, "--paired-untouched-run", "paired.json"))
            self.assertTrue(result["ok"], result)
            self.assertEqual(read_json(root / "proof.json")["source_variant"], "root-attached")
            self.assertEqual(read_json(root / "run.json")["instrumentation_delta"], instrumentation_delta)
            meta = read_json(root / "proof.json.meta.json")
            self.assertEqual(meta["evidence_tier"], "E3")
            self.assertEqual(meta["paired_untouched_run"], "paired.json")
            self.assertEqual(meta["paired_untouched_run_id"], "RUN-0")
            self.assertEqual(meta["paired_untouched_run_path"], "paired.json")

    def test_record_rejects_e3_with_inexact_paired_untouched_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_record_fixture(
                root,
                run=self.run_manifest(
                    variant="root-attached",
                    tier="E3",
                    start="2026-01-01T00:01:00Z",
                    end="2026-01-01T00:02:00Z",
                    delta={"hook": "enabled", "paired_untouched_run_id": "RUN-WRONG"},
                ),
                bundles=self.bundle_index(
                    variant="root-attached",
                    tier="E3",
                    start="2026-01-01T00:01:30Z",
                    delta={"hook": "enabled"},
                ),
                paired=self.run_manifest(
                    run_id="RUN-0",
                    variant="untouched",
                    tier="E2",
                    start="2026-01-01T00:00:00Z",
                    end="2026-01-01T00:01:00Z",
                ),
            )
            result = g005.run(self.record_args(root, "--paired-untouched-run", "paired.json"))
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["errors"][0]["message"],
                "run instrumentation_delta.paired_untouched_run_id does not match paired untouched run",
            )

    def test_record_rejects_e3_pair_from_different_environment_or_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            run = self.run_manifest(
                variant="root-attached",
                tier="E3",
                start="2026-01-01T00:01:00Z",
                end="2026-01-01T00:02:00Z",
                delta={"hook": "enabled", "paired_untouched_run_id": "RUN-0"},
            )
            paired = self.run_manifest(
                run_id="RUN-0",
                start="2026-01-01T00:00:00Z",
                end="2026-01-01T00:01:00Z",
            )
            paired["environment"]["camera_fingerprint"] = "different-camera"
            self.write_record_fixture(
                root,
                run=run,
                bundles=self.bundle_index(
                    variant="root-attached",
                    tier="E3",
                    start="2026-01-01T00:01:30Z",
                    delta={"hook": "enabled"},
                ),
                paired=paired,
            )
            result = g005.run(self.record_args(root, "--paired-untouched-run", "paired.json"))
            self.assertFalse(result["ok"])
            self.assertIn("environment mismatch", result["errors"][0]["message"])

            paired = self.run_manifest(
                run_id="RUN-0",
                start="2026-01-01T00:00:00Z",
                end="2026-01-01T00:01:00Z",
            )
            paired["data_state_snapshot"]["sha256"] = "b" * 64
            write_json(root / "paired.json", paired)
            result = g005.run(self.record_args(root, "--paired-untouched-run", "paired.json"))
            self.assertFalse(result["ok"])
            self.assertIn("baseline or data-state snapshot mismatch", result["errors"][0]["message"])

    def make_proof_pair(
        self,
        root: Path,
        name: str,
        *,
        run_id: str,
        variant: str,
        tier: str,
        before_doc,
        after_doc,
        start: str,
        end: str,
        new_rows=0,
        bundle_id=None,
        paired="",
        paired_run_id="",
        divergence=None,
        extra_key=False,
        bad_hash=False,
    ):
        bundle_id = bundle_id or f"EVB-{run_id}"
        before_rel = f"ledgers/{run_id}-before.json"
        after_rel = f"ledgers/{run_id}-after.json"
        before_path = write_json(root / before_rel, before_doc)
        after_path = write_json(root / after_rel, after_doc)
        bundle_index_rel = f"bundles/{run_id}.json"
        bundle_index_path = write_json(
            root / bundle_index_rel,
            self.bundle_index(
                variant=variant,
                tier=tier,
                bundle_id=bundle_id,
                start=start,
                delta={"hook": "enabled"} if tier == "E3" else None,
            ),
        )
        observation = {"observation_id": f"OBS-{run_id}", "claim_ids": ["CLAIM-1"], "ledger_row_ids": [], "evidence_bundle_ids": [bundle_id], "instrumentation_label": variant, "event_refs": [{"bundle_id": bundle_id, "path": f"events/{bundle_id}.json", "event_ids": [f"EV-{bundle_id}"]}]}
        proof_base = {"schema_version": 1, "proof_id": f"DYN-{run_id}", "artifact_set_id": "ART", "run_id": run_id, "experiment_id": f"EXP-{run_id}", "source_variant": variant, "ledger_before": {"bundle_id": bundle_id, "path": before_rel}, "ledger_after": {"bundle_id": bundle_id, "path": after_rel}, "observations": [observation], "instrumented_observations_labeled": True, "unexplained_baseline_divergence_ids": divergence or []}
        proof = dict(proof_base)
        proof["canonical_sha256"] = "f" * 64 if bad_hash else critic_hash(proof_base)
        if extra_key:
            proof["extra"] = True
        proof_path = write_json(root / name, proof)
        run_delta = None
        if tier == "E3":
            run_delta = {
                "hook": "enabled",
                "paired_untouched_run_id": paired_run_id,
            }
        run_path = write_json(
            root / "runs" / f"{run_id}.json",
            self.run_manifest(
                run_id=run_id,
                variant="untouched" if tier == "E2" else "root-attached",
                tier=tier,
                start=start,
                end=end,
                delta=run_delta,
            ),
        )
        write_json(
            root / f"{name}.meta.json",
            {
                "schema_version": 1,
                "proof_path": name,
                "run_manifest": f"runs/{run_id}.json",
                "bundle_index": bundle_index_rel,
                "evidence_tier": tier,
                "new_rows": new_rows,
                "added_row_ids": [f"ROW-{run_id}-{index + 1}" for index in range(new_rows)],
                "raw_hashes": {
                    "run": g005.file_hash(run_path),
                    "bundle_index": g005.file_hash(bundle_index_path),
                    "ledger_before": g005.file_hash(before_path),
                    "ledger_after": g005.file_hash(after_path),
                    "proof": g005.file_hash(proof_path),
                },
                "ledger_before_sha256": g005.file_hash(before_path),
                "ledger_after_sha256": g005.file_hash(after_path),
                "started_at": start,
                "ended_at": end,
                "source_variant": variant,
                "artifact_set_id": "ART",
                "paired_untouched_run": paired,
                "paired_untouched_run_id": paired_run_id,
                "paired_untouched_run_path": paired,
            },
        )
        return name

    def valid_build_fixture(self, root: Path):
        ledger_0 = {"artifact_set_id": "ART", "revision": 0, "rows": []}
        ledger_1 = {"artifact_set_id": "ART", "revision": 1, "rows": []}
        ledger_2 = {"artifact_set_id": "ART", "revision": 2, "rows": []}
        ledger_final = {"artifact_set_id": "ART", "rows": []}
        write_json(root / "ledger-final.json", ledger_final)
        p1 = self.make_proof_pair(root, "p1.json", run_id="RUN-1", variant="untouched", tier="E2", before_doc=ledger_0, after_doc=ledger_1, start="2026-01-01T00:00:00Z", end="2026-01-01T00:01:00Z", new_rows=1)
        p2 = self.make_proof_pair(root, "p2.json", run_id="RUN-2", variant="root-attached", tier="E3", before_doc=ledger_1, after_doc=ledger_2, start="2026-01-01T00:01:00Z", end="2026-01-01T00:02:00Z", new_rows=1, paired="runs/RUN-1.json", paired_run_id="RUN-1")
        p3 = self.make_proof_pair(root, "p3.json", run_id="RUN-3", variant="untouched", tier="E2", before_doc=ledger_2, after_doc=ledger_final, start="2026-01-01T00:02:00Z", end="2026-01-01T00:03:00Z", new_rows=0)
        p4 = self.make_proof_pair(root, "p4.json", run_id="RUN-4", variant="untouched", tier="E2", before_doc=ledger_final, after_doc=ledger_final, start="2026-01-01T00:03:00Z", end="2026-01-01T00:04:00Z", new_rows=0)
        return [p1, p2, p3, p4]

    def build_args(self, root: Path, proofs, out="conv.json"):
        args = ["build-convergence", "--root", str(root)]
        for proof in proofs:
            args += ["--session-proof", proof]
        return args + ["--canonical-ledger", "ledger-final.json", "--out", out]

    def write_terminal_validation_fixture(self, root: Path):
        convergence = write_json(root / g005.CONVERGENCE_REL, {"schema_version": 1})
        ledger = write_json(
            root / g005.RESEARCH_REL / "static/ledger.json",
            {"artifact_set_id": "ART", "rows": []},
        )
        sidecar = g005._closure_sidecar_payload(
            convergence,
            root.resolve(),
            ledger,
            read_json(ledger),
            max_bytes=g005.MAX_BYTES,
        )
        write_json(convergence.with_name(convergence.name + ".closure.json"), sidecar)
        return convergence, ledger

    def test_build_requires_targeted_e2_e3_pair_before_final_two_e2(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proofs = self.valid_build_fixture(root)
            result = g005.run(self.build_args(root, [proofs[0], proofs[2], proofs[3]]))
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["errors"][0]["message"],
                "at least four proofs are required in E2,E3,E2,E2 order",
            )
            meta = read_json(root / "p2.json.meta.json")
            meta["paired_untouched_run_id"] = "RUN-OTHER"
            write_json(root / "p2.json.meta.json", meta)
            result = g005.run(self.build_args(root, proofs))
            self.assertFalse(result["ok"])
            self.assertIn("paired run reference", result["errors"][0]["message"])

            proofs = self.valid_build_fixture(root)
            run_path = root / "runs/RUN-2.json"
            run = read_json(run_path)
            run["instrumentation_delta"]["paired_untouched_run_id"] = "RUN-OTHER"
            write_json(run_path, run)
            meta = read_json(root / "p2.json.meta.json")
            meta["raw_hashes"]["run"] = g005.file_hash(run_path)
            write_json(root / "p2.json.meta.json", meta)
            result = g005.run(self.build_args(root, proofs))
            self.assertFalse(result["ok"])
            self.assertEqual(
                result["errors"][0]["message"],
                "instrumented E3 run instrumentation_delta.paired_untouched_run_id mismatch",
            )

    def test_build_enforces_final_two_e2_hash_chain_distinct_nonoverlap_no_divergence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proofs = self.valid_build_fixture(root)
            self.assertTrue(g005.run(self.build_args(root, proofs))["ok"])

            meta = read_json(root / "p1.json.meta.json")
            self.assertEqual(
                meta["raw_hashes"],
                {
                    "run": g005.file_hash(root / "runs/RUN-1.json"),
                    "bundle_index": g005.file_hash(root / "bundles/RUN-1.json"),
                    "ledger_before": g005.file_hash(root / "ledgers/RUN-1-before.json"),
                    "ledger_after": g005.file_hash(root / "ledgers/RUN-1-after.json"),
                    "proof": g005.file_hash(root / "p1.json"),
                },
            )
            meta["raw_hashes"]["run"] = HEX0
            write_json(root / "p1.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "session proof sidecar run raw hash mismatch",
            )
            self.valid_build_fixture(root)

            meta = read_json(root / "p1.json.meta.json")
            meta["raw_hashes"]["proof"] = HEX0
            write_json(root / "p1.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "session proof sidecar proof raw hash mismatch",
            )
            self.valid_build_fixture(root)

            ledger_before_path = root / "ledgers/RUN-4-before.json"
            write_json(
                ledger_before_path,
                {"artifact_set_id": "ART", "revision": "fork", "rows": []},
            )
            meta = read_json(root / "p4.json.meta.json")
            meta["raw_hashes"]["ledger_before"] = g005.file_hash(ledger_before_path)
            meta["ledger_before_sha256"] = g005.file_hash(ledger_before_path)
            write_json(root / "p4.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "successive session proofs do not form a ledger hash chain",
            )
            self.valid_build_fixture(root)

            p4 = read_json(root / "p4.json")
            p4["run_id"] = "RUN-3"
            base = {k: v for k, v in p4.items() if k != "canonical_sha256"}
            p4["canonical_sha256"] = critic_hash(base)
            write_json(root / "p4.json", p4)
            run_path = root / "runs/RUN-4.json"
            run = read_json(run_path)
            run["run_id"] = "RUN-3"
            write_json(run_path, run)
            meta = read_json(root / "p4.json.meta.json")
            meta["raw_hashes"]["run"] = g005.file_hash(run_path)
            meta["raw_hashes"]["proof"] = g005.file_hash(root / "p4.json")
            write_json(root / "p4.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "session proofs reuse a run ID or run manifest path",
            )
            self.valid_build_fixture(root)

            meta = read_json(root / "p4.json.meta.json")
            meta["started_at"] = "2026-01-01T00:02:30Z"
            run_path = root / "runs/RUN-4.json"
            run = read_json(run_path)
            run["started_at"] = meta["started_at"]
            write_json(run_path, run)
            meta["raw_hashes"]["run"] = g005.file_hash(run_path)
            write_json(root / "p4.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "session proof intervals overlap",
            )
            self.valid_build_fixture(root)

            p1 = read_json(root / "p1.json")
            p1["unexplained_baseline_divergence_ids"] = ["DIV-1"]
            base = {k: v for k, v in p1.items() if k != "canonical_sha256"}
            p1["canonical_sha256"] = critic_hash(base)
            write_json(root / "p1.json", p1)
            meta = read_json(root / "p1.json.meta.json")
            meta["raw_hashes"]["proof"] = g005.file_hash(root / "p1.json")
            write_json(root / "p1.json.meta.json", meta)
            self.assertEqual(
                g005.run(self.build_args(root, proofs))["errors"][0]["message"],
                "unexplained baseline divergence is nonzero",
            )

    def test_build_rejects_non_critic_compatible_exact_keys_and_bad_canonical_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proofs = self.valid_build_fixture(root)
            p1 = read_json(root / "p1.json")
            p1["extra"] = True
            write_json(root / "p1.json", p1)
            result = g005.run(self.build_args(root, proofs))
            self.assertFalse(result["ok"])
            self.assertIn("exact-key shape", result["errors"][0]["message"])
            proofs = self.valid_build_fixture(root)
            p1 = read_json(root / "p1.json")
            p1["canonical_sha256"] = "f" * 64
            write_json(root / "p1.json", p1)
            result = g005.run(self.build_args(root, proofs))
            self.assertFalse(result["ok"])
            self.assertIn("canonical_sha256 mismatch", result["errors"][0]["message"])

    def test_build_rejects_malformed_metadata_as_bounded_json_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proofs = self.valid_build_fixture(root)
            meta = read_json(root / "p1.json.meta.json")
            meta["new_rows"] = "not-an-integer"
            write_json(root / "p1.json.meta.json", meta)
            result = g005.run(self.build_args(root, proofs))
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "rejected")
            self.assertIn("new_rows must be a nonnegative integer", result["errors"][0]["message"])

    def test_build_success_outputs_critic_compatible_session_proofs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            proofs = self.valid_build_fixture(root)
            result = g005.run(self.build_args(root, proofs))
            self.assertTrue(result["ok"], result)
            conv = read_json(root / "conv.json")
            self.assertEqual(set(conv), {"schema_version", "artifact_set_id", "sessions", "instrumented_observations_labeled", "unexplained_baseline_divergences"})
            self.assertEqual([s["source_variant"] for s in conv["sessions"]], ["untouched", "root-attached", "untouched", "untouched"])
            self.assertEqual([s["new_rows"] for s in conv["sessions"]][-2:], [0, 0])
            closure_path = root / "conv.json.closure.json"
            self.assertEqual(result["closure_sidecar"], str(closure_path))
            self.assertEqual(result["closure_sha256"], g005.file_hash(closure_path))
            empty_unresolved = {
                "blocked": [],
                "missing": [],
                "nonterminal": [],
                "public_proprietary_material_leaks": [],
                "replay_failures": [],
                "stale_evidence": [],
                "unclassified": [],
                "unlabeled_unknown_observations": [],
                "unresolved_contradictions": [],
            }
            self.assertEqual(
                read_json(closure_path),
                {
                    "schema_version": 1,
                    "artifact_set_id": "ART",
                    "convergence_path": "conv.json",
                    "computed_from_ledger": "ledger-final.json",
                    "ledger_sha256": g005.file_hash(root / "ledger-final.json"),
                    "counters": {key: 0 for key in empty_unresolved},
                    "current_causal_frontier_count": 0,
                    "unresolved_row_ids": empty_unresolved,
                },
            )

    def test_validate_requires_canonical_convergence_path_and_delegates_to_critic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_terminal_validation_fixture(root)
            write_json(root / "other.json", {"schema_version": 1})
            with mock.patch.object(g005.critic, "validate_dynamic_convergence", return_value=("ok",)) as validate:
                result = g005.run(["validate", "--root", str(root), "--convergence", str(g005.CONVERGENCE_REL)])
            self.assertTrue(result["ok"], result)
            validate.assert_called_once_with(root.resolve())
            with mock.patch.object(g005.critic, "validate_dynamic_convergence") as validate:
                result = g005.run(["validate", "--root", str(root), "--convergence", "other.json"])
            self.assertFalse(result["ok"])
            self.assertIn("canonical dynamic exploration convergence path", result["errors"][0]["message"])
            validate.assert_not_called()

    def test_validate_rejects_self_attested_or_nonterminal_closure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            convergence, ledger = self.write_terminal_validation_fixture(root)
            sidecar_path = convergence.with_name(convergence.name + ".closure.json")
            sidecar = read_json(sidecar_path)
            sidecar["counters"]["blocked"] = 0
            sidecar["unresolved_row_ids"]["blocked"] = []
            sidecar["ledger_sha256"] = "0" * 64
            write_json(sidecar_path, sidecar)
            with mock.patch.object(g005.critic, "validate_dynamic_convergence", return_value=("ok",)):
                result = g005.run(
                    ["validate", "--root", str(root), "--convergence", str(g005.CONVERGENCE_REL)]
                )
            self.assertFalse(result["ok"])
            self.assertIn("not derived from the canonical ledger", result["errors"][0]["message"])

            nonterminal = {
                "row_id": "ROW-1",
                "state": "blocked",
                "classification_status": "unknown",
            }
            write_json(ledger, {"artifact_set_id": "ART", "rows": [nonterminal]})
            derived = g005._closure_sidecar_payload(
                convergence,
                root.resolve(),
                ledger,
                read_json(ledger),
                max_bytes=g005.MAX_BYTES,
            )
            write_json(sidecar_path, derived)
            with mock.patch.object(g005.critic, "validate_dynamic_convergence", return_value=("ok",)):
                result = g005.run(
                    ["validate", "--root", str(root), "--convergence", str(g005.CONVERGENCE_REL)]
                )
            self.assertFalse(result["ok"])
            self.assertIn("not terminal for G005", result["errors"][0]["message"])

    def test_validate_reports_critic_rejection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_json(root / g005.CONVERGENCE_REL, {"schema_version": 1})
            with mock.patch.object(g005.critic, "validate_dynamic_convergence", side_effect=RuntimeError("bad convergence")):
                result = g005.run(["validate", "--root", str(root), "--convergence", str(g005.CONVERGENCE_REL)])
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "rejected")
            self.assertIn("bad convergence", result["errors"][0]["message"])


if __name__ == "__main__":
    unittest.main()
