import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.hik_whole_apk import g003_dossier_validator as validator

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/g003-dossier-contract.json"
RESEARCH_REL = validator.RESEARCH_REL
ARTIFACT_SET_ID = "hikmicro-viewer-2.6.0-019801077bb42ffb"


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_ref(root, path):
    return {
        "path": str(path.relative_to(root)),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def canonical_hash_without_manifest(value):
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    return hashlib.sha256(validator.canonical_json_bytes(payload)).hexdigest()


def suffix(dossier, width):
    return f"{int(dossier[1:]):0{width}X}"[-width:]


def claim_statement(dossier):
    return f"Bounded static dossier statement for {dossier}."


def claim_id(dossier, evidence_bundle_ids):
    return validator.expected_g003_claim_id(dossier, claim_statement(dossier), evidence_bundle_ids)


def legacy_claim_id(dossier, evidence_bundle_ids):
    digest_input = claim_statement(dossier) + "\0" + "\0".join(sorted(evidence_bundle_ids))
    return f"CLM-G003-{dossier}-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:16].upper()}"


def spec_title(dossier):
    return f"Source-independent bounded contract for {dossier}"


def test_file_rel(dossier):
    return f"tests/fixtures/g003/test_{dossier.lower()}.py"


def test_name(dossier):
    return "test_contract"


def spec_id(dossier, claim_ids):
    return validator.expected_g003_spec_id(dossier, spec_title(dossier), sorted(claim_ids))


def rpro_id(dossier, specification_ids):
    return validator.expected_g003_reproduction_id(dossier, test_file_rel(dossier), test_name(dossier), sorted(specification_ids))


def ids(dossier):
    s16 = suffix(dossier, 16)
    s12 = suffix(dossier, 12)
    evb = f"EVB-G003-{dossier}-STATIC"
    claim = claim_id(dossier, [evb])
    spec = spec_id(dossier, [claim])
    rpro = rpro_id(dossier, [spec])
    return {
        "row": f"ROW-G003-{dossier}-{s16}",
        "claim": claim,
        "spec": spec,
        "rpro": rpro,
        "review": f"REV-G003-{dossier}-INDEPENDENT-{s12}",
        "evb": evb,
        "dyn": f"EVB-G003-{dossier}-DYN",
        "repr": f"EVB-G003-{dossier}-RPRO",
        "unknown": f"UNK-G003-{dossier}-HW",
    }


class G003Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.research = self.root / RESEARCH_REL
        (self.research / "governance").mkdir(parents=True, exist_ok=True)
        (self.research / "governance/g003-dossier-contract.json").write_text(CONTRACT.read_text(encoding="utf-8"), encoding="utf-8")
        self.dossier_entries = []
        self.ledger_rows = []
        self.claim_rows = []
        self.evb_rows = []
        self.spec_rows = []
        self.rpro_rows = []
        self.review_rows = []

    def make_all(self, *, verified=False):
        for dossier in validator.DOSSIER_IDS:
            self.add_dossier(dossier, verified=verified)
        self.write_indexes()
        return self

    def add_indexed_json(self, rel, key, value, rows, id_key, subject_ids=None):
        path = self.root / rel
        write_json(path, value)
        subjects = sorted(set(subject_ids or [key]))
        row = {id_key: key, **file_ref(self.root, path), "artifact_set_id": ARTIFACT_SET_ID, "subject_ids": subjects}
        rows.append(row)
        return path

    def add_evidence(self, dossier, evb_id, tier="E1", source_variant="untouched"):
        raw = self.root / RESEARCH_REL / "raw" / dossier / f"{evb_id}.txt"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(f"immutable raw evidence for {evb_id}\n", encoding="utf-8")
        value = {
            "evidence_bundle_id": evb_id,
            "artifact_set_id": ARTIFACT_SET_ID,
            "source_variant": source_variant,
            "evidence_tier": tier,
            "experiment_id": f"EXP-{evb_id}",
            "attachments": [{**file_ref(self.root, raw), "media_type": "text/plain"}],
        }
        return self.add_indexed_json(
            f"{RESEARCH_REL}/evidence/{evb_id}.json", evb_id, value, self.evb_rows, "evidence_bundle_id"
        )

    def add_dossier(self, dossier, *, verified=False):
        names = {r["dossier_id"]: r["name"] for r in json.loads(CONTRACT.read_text(encoding="utf-8"))["dossier_roster"]}
        d = ids(dossier)
        test_file = self.root / test_file_rel(dossier)
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("def test_contract():\n    assert True\n", encoding="utf-8")
        self.add_evidence(dossier, d["evb"], "E1")
        if verified:
            self.add_evidence(dossier, d["dyn"], "E2")
            self.add_evidence(dossier, d["repr"], "E4", "reimplementation")
        claim_value = {
            "claim_id": d["claim"],
            "artifact_set_id": ARTIFACT_SET_ID,
            "statement": claim_statement(dossier),
            "evidence_bundle_ids": [d["evb"]],
        }
        self.add_indexed_json(f"{RESEARCH_REL}/claims/{d['claim']}.json", d["claim"], claim_value, self.claim_rows, "claim_id", [d["claim"], f"DOS-G003-{dossier}"])
        spec_value = {
            "specification_id": d["spec"],
            "artifact_set_id": ARTIFACT_SET_ID,
            "contract_title": spec_title(dossier),
            "claim_ids": [d["claim"]],
            "evidence_bundle_ids": [d["evb"]],
            "source_independent": True,
        }
        self.add_indexed_json(f"{RESEARCH_REL}/specs/{d['spec']}.json", d["spec"], spec_value, self.spec_rows, "specification_id", [d["spec"], d["claim"]])
        rpro_value = {
            "reproduction_id": d["rpro"],
            "artifact_set_id": ARTIFACT_SET_ID,
            "test_file": test_file_rel(dossier),
            "test_name": test_name(dossier),
            "specification_ids": [d["spec"]],
            "required_evidence_bundle_ids": [d["evb"]],
            "last_result": {
                "evidence_bundle_id": d["evb"],
                "status": "not_run",
                "command": "python3 -m unittest",
                "exit_code": None,
                "captured_at": "2026-07-23T00:00:00Z",
            },
        }
        self.add_indexed_json(f"{RESEARCH_REL}/reproduction/{d['rpro']}.json", d["rpro"], rpro_value, self.rpro_rows, "reproduction_id", [d["rpro"], d["spec"]])
        review_subjects = [f"DOS-G003-{dossier}", d["spec"], d["rpro"]]
        review_evbs = [d["evb"]] + ([d["dyn"], d["repr"]] if verified else [])
        review_value = {
            "review_id": d["review"],
            "artifact_set_id": ARTIFACT_SET_ID,
            "independent_from_producers": True,
            "verdict": "pass",
            "subject_ids": sorted(review_subjects),
            "evidence_bundle_ids": sorted(review_evbs),
        }
        self.add_indexed_json(f"{RESEARCH_REL}/reviews/{d['review']}.json", d["review"], review_value, self.review_rows, "review_id", sorted([d["review"]] + review_subjects))

        graph_file = self.root / RESEARCH_REL / "dossiers" / dossier / "static_graph.json"
        graph_payload = {"kind": "static_graph", "dossier_id": dossier}
        write_json(graph_file, graph_payload)
        state_file = self.root / RESEARCH_REL / "dossiers" / dossier / "state_machine.json"
        state_payload = {"kind": "state_machine", "dossier_id": dossier}
        write_json(state_file, state_payload)
        attachment = self.root / RESEARCH_REL / "dossiers" / dossier / "evidence-note.txt"
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_text(f"evidence note {dossier}\n", encoding="utf-8")
        trace_ids = [f"TRACE-{dossier}-UNT"] if verified else []
        dynamic_evbs = [d["dyn"]] if verified else []
        unknowns = [] if verified else [{
            "unknown_id": d["unknown"],
            "state": "unknown_hardware_unavailable",
            "scope_row_ids": [d["row"]],
            "reason": "Authorized hardware is not present in this story.",
            "attempted_evidence_bundle_ids": [d["evb"]],
            "next_discriminating_experiment": {"experiment_id": f"G004-{dossier}-LIVE", "owner": "G004"},
            "owner": "G004",
            "closure_effect": "nonterminal",
        }]
        status = "verified" if verified else "specified"
        state_kind = "success_verified" if verified else "unknown_terminal_attempt"
        state_name = "verified_success" if verified else "unknown_hardware_unavailable"
        row_state = "verified" if verified else "specified"
        classification = "classified" if verified else "unknown"
        review_ids = [d["review"]] if verified else []
        verification_ids = [d["repr"]] if verified else []
        rpro_result_evb = d["repr"] if verified else d["evb"]
        rpro_status = "pass" if verified else "not_run"
        rpro_exit = 0 if verified else None

        manifest = {
            "schema": "g003-dossier-manifest/v1",
            "schema_version": 1,
            "dossier_id": dossier,
            "dossier_manifest_id": f"DOS-G003-{dossier}",
            "dossier_name": names[dossier],
            "artifact_set_id": ARTIFACT_SET_ID,
            "owner": f"owner-{dossier}",
            "status": status,
            "ledger_row_ownership": {
                "row_ids": [d["row"]],
                "scope_keys": [f"scope-{dossier}"],
                "disjoint_owner": True,
                "complete_for_dossier": True,
                "source_inventory_refs": [f"INV-{dossier}-A"],
                "owner": f"owner-{dossier}",
            },
            "scope_rows": [{
                "row_id": d["row"],
                "scope_type": "class",
                "scope_key": f"scope-{dossier}",
                "dossier_id": dossier,
                "owner": f"owner-{dossier}",
                "state": row_state,
                "classification_status": classification,
                "claim_ids": [d["claim"]],
                "evidence_bundle_ids": [d["evb"]] + dynamic_evbs,
                "specification_ids": [d["spec"]],
                "reproduction_ids": [d["rpro"]],
                "verification_ids": verification_ids,
                "independent_review_ids": review_ids,
                "history": [{"state": row_state, "at": "2026-07-23T00:00:00Z"}],
                "reopen_reason": None,
                "blocker": None if verified else {"unknown_id": d["unknown"]},
            }],
            "static_graph": {
                "artifact_ref": file_ref(self.root, graph_file),
                "nodes": [{
                    "node_id": f"GRN-G003-{dossier}-A",
                    "node_type": "class",
                    "stable_node_key": f"scope-{dossier}",
                    "label": f"Scope {dossier}",
                    "inv_refs": [f"INV-{dossier}-A"],
                    "claim_ids": [d["claim"]],
                    "evidence_bundle_ids": [d["evb"]],
                    "specification_ids": [d["spec"]],
                }, {
                    "node_id": f"GRN-G003-{dossier}-B",
                    "node_type": "feature",
                    "stable_node_key": f"feature-{dossier}",
                    "label": f"Feature {dossier}",
                    "inv_refs": [f"INV-{dossier}-B"],
                    "claim_ids": [d["claim"]],
                    "evidence_bundle_ids": [d["evb"]],
                    "specification_ids": [d["spec"]],
                }],
                "edges": [{
                    "edge_id": f"GRE-G003-{dossier}-A",
                    "from_node_id": f"GRN-G003-{dossier}-A",
                    "to_node_id": f"GRN-G003-{dossier}-B",
                    "relation": "references",
                    "stable_edge_key": f"edge-{dossier}",
                    "inv_refs": [f"INV-{dossier}-EDGE"],
                    "claim_ids": [d["claim"]],
                    "evidence_bundle_ids": [d["evb"]],
                    "specification_ids": [d["spec"]],
                }],
                "graph_sha256": hashlib.sha256(validator.canonical_json_bytes(graph_payload)).hexdigest(),
            },
            "dynamic_traces": {
                "trace_ids": trace_ids,
                "evidence_bundle_ids": dynamic_evbs,
                "source_variants": ["untouched"],
                "coverage_matrix": {"scope_rows": [d["row"]]},
                "loss_accounting": {"missing_live_owned_by": [] if verified else ["G004"]},
                "instrumentation_comparison": None,
            },
            "state_machine": {
                "artifact_ref": file_ref(self.root, state_file),
                "states": [{
                    "state_id": f"S-{dossier}-START",
                    "name": "start",
                    "kind": "intermediate",
                    "claim_ids": [],
                    "evidence_bundle_ids": [],
                }, {
                    "state_id": f"S-{dossier}-END",
                    "name": state_name,
                    "kind": state_kind,
                    "claim_ids": [d["claim"]] if verified else [],
                    "evidence_bundle_ids": dynamic_evbs if verified else [],
                }],
                "transitions": [{
                    "transition_id": f"T-{dossier}-1",
                    "from_state_id": f"S-{dossier}-START",
                    "to_state_id": f"S-{dossier}-END",
                    "trigger": "authorized attempt",
                    "observable_input": "bounded fixture",
                    "observable_output": "classified outcome" if verified else "explicit unknown",
                    "error_state": None,
                    "claim_ids": [d["claim"]],
                    "evidence_bundle_ids": dynamic_evbs if verified else [d["evb"]],
                    "specification_ids": [d["spec"]],
                }],
                "initial_states": [f"S-{dossier}-START"],
                "terminal_states": [f"S-{dossier}-END"],
                "state_machine_sha256": hashlib.sha256(validator.canonical_json_bytes(state_payload)).hexdigest(),
            },
            "evidence_index": {
                "bundle_ids": [d["evb"]] + dynamic_evbs + ([d["repr"]] if verified else []),
                "claim_ids": [d["claim"]],
                "attachment_refs": [{**file_ref(self.root, attachment), "content_role": "bounded-note", "source_variant": "untouched", "local_only": True}],
                "tier_coverage": {"E1": [d["evb"]]},
                "replay_commands": ["python3 -m unittest tests.test_g003_dossier_validator"],
            },
            "unknowns": unknowns,
            "unresolved_contradictions": {"contradiction_ids": [], "count": 0, "resolved_claim_ids": []},
            "source_independent_contracts": [{
                "contract_id": f"CONTRACT-G003-{dossier}",
                "specification_ids": [d["spec"]],
                "observable_inputs": ["public Android event"],
                "observable_outputs": ["bounded output"],
                "state_requirements": ["state is explicit"],
                "timing_lifetime_requirements": ["not claimed by G003"],
                "error_recovery_requirements": ["unknowns name next experiment"],
                "acceptance_test_ids": [d["rpro"]],
                "clean_room_review_ids": [d["review"]],
            }],
            "specification_ids": [d["spec"]],
            "reproduction_tests": [{
                "reproduction_id": d["rpro"],
                "test_file": test_file_rel(dossier),
                "test_name": test_name(dossier),
                "specification_ids": [d["spec"]],
                "required_evidence_bundle_ids": [d["evb"]],
                "last_result": {
                    "evidence_bundle_id": rpro_result_evb,
                    "status": rpro_status,
                    "command": "python3 -m unittest",
                    "exit_code": rpro_exit,
                    "captured_at": "2026-07-23T00:00:00Z",
                },
            }],
            "review_ids": [d["review"]],
            "cross_link_invariants": ["resolved locally"],
            "no_fake_celsius_compliance": {"publishes_celsius": False, "calibrated": False, "evidence_bundle_ids": []},
            "dynamic_claim_constraints": {"claims_live_completion": False, "downstream_live_owned_by": [] if verified else ["G004"]},
            "artifact_hashes": [file_ref(self.root, graph_file), file_ref(self.root, state_file)],
            "manifest_sha256": "0" * 64,
        }
        manifest["manifest_sha256"] = canonical_hash_without_manifest(manifest)
        manifest_path = self.root / RESEARCH_REL / "dossiers" / dossier / "manifest.json"
        write_json(manifest_path, manifest)
        manifest_rel = str(manifest_path.relative_to(self.root))
        self.dossier_entries.append({
            "dossier_id": dossier,
            "manifest_path": manifest_rel,
            "path": manifest_rel,
            **file_ref(self.root, manifest_path),
            "artifact_set_id": ARTIFACT_SET_ID,
            "subject_ids": [f"DOS-G003-{dossier}", dossier],
        })
        self.ledger_rows.append({"row_id": d["row"], "dossier_id": dossier, "goal_id": "G003", "scope_key": f"scope-{dossier}"})
        return manifest_path

    def write_indexes(self):
        write_json(self.research / "dossiers/index.json", {"dossiers": self.dossier_entries})
        write_json(self.research / "static/ledger.json", {"rows": self.ledger_rows})
        write_json(self.research / "claims/index.json", {"claims": self.claim_rows})
        write_json(self.research / "evidence/index.json", {"evidence_bundles": self.evb_rows})
        write_json(self.research / "specs/index.json", {"specifications": self.spec_rows})
        write_json(self.research / "reproduction/index.json", {"reproductions": self.rpro_rows})
        write_json(self.research / "reviews/index.json", {"reviews": self.review_rows})


    def replace_claim_evidence_ids(self, dossier, evidence_bundle_ids):
        d = ids(dossier)
        old_claim = d["claim"]
        new_claim = claim_id(dossier, evidence_bundle_ids) or legacy_claim_id(dossier, evidence_bundle_ids)
        old_path = self.root / RESEARCH_REL / "claims" / f"{old_claim}.json"
        old_data = json.loads(old_path.read_text(encoding="utf-8"))
        old_data["claim_id"] = new_claim
        old_data["evidence_bundle_ids"] = evidence_bundle_ids
        new_path = self.root / RESEARCH_REL / "claims" / f"{new_claim}.json"
        write_json(new_path, old_data)
        if new_path != old_path:
            old_path.unlink()

        def replace_value(value):
            if isinstance(value, str):
                return new_claim if value == old_claim else value
            if isinstance(value, list):
                return [replace_value(item) for item in value]
            if isinstance(value, dict):
                return {key: replace_value(item) for key, item in value.items()}
            return value

        manifest_path = self.root / RESEARCH_REL / "dossiers" / dossier / "manifest.json"
        manifest = replace_value(json.loads(manifest_path.read_text(encoding="utf-8")))
        manifest["manifest_sha256"] = canonical_hash_without_manifest(manifest)
        write_json(manifest_path, manifest)
        for entry in self.dossier_entries:
            if entry["dossier_id"] == dossier:
                entry.update(file_ref(self.root, manifest_path))

        for row in self.claim_rows:
            if row["claim_id"] == old_claim:
                row["claim_id"] = new_claim
                row["path"] = str(new_path.relative_to(self.root))
                row.update(file_ref(self.root, new_path))
                row["subject_ids"] = sorted(new_claim if item == old_claim else item for item in row["subject_ids"])
        for row in self.spec_rows:
            spec_path = self.root / row["path"]
            spec = replace_value(json.loads(spec_path.read_text(encoding="utf-8")))
            write_json(spec_path, spec)
            row.update(file_ref(self.root, spec_path))
            row["subject_ids"] = sorted(new_claim if item == old_claim else item for item in row["subject_ids"])
        self.write_indexes()
        return new_claim


    def mutate_indexed_json(self, rows, id_key, identifier, mutator):
        for row in rows:
            if row[id_key] == identifier:
                path = self.root / row["path"]
                data = json.loads(path.read_text(encoding="utf-8"))
                mutator(data)
                write_json(path, data)
                row.update(file_ref(self.root, path))
                return data
        raise AssertionError(f"missing {identifier}")

    def mutate_evidence(self, evb_id, mutator):
        data = self.mutate_indexed_json(self.evb_rows, "evidence_bundle_id", evb_id, mutator)
        self.write_indexes()
        return data

    def mutate_spec(self, spec_id_value, mutator):
        data = self.mutate_indexed_json(self.spec_rows, "specification_id", spec_id_value, mutator)
        self.write_indexes()
        return data

    def mutate_rpro(self, rpro_id_value, mutator):
        data = self.mutate_indexed_json(self.rpro_rows, "reproduction_id", rpro_id_value, mutator)
        self.write_indexes()
        return data

    def mutate_review(self, review_id_value, mutator):
        data = self.mutate_indexed_json(self.review_rows, "review_id", review_id_value, mutator)
        self.write_indexes()
        return data

    def mutate_manifest(self, dossier, mutator):
        path = self.root / RESEARCH_REL / "dossiers" / dossier / "manifest.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        mutator(data)
        data["manifest_sha256"] = canonical_hash_without_manifest(data)
        write_json(path, data)
        for entry in self.dossier_entries:
            if entry["dossier_id"] == dossier:
                entry.update(file_ref(self.root, path))
        self.write_indexes()


class TestG003DossierValidator(unittest.TestCase):
    def validate_fixture(self, fixture):
        return validator.validate(fixture.root, check_authority=False)

    def assertFailsWith(self, result, text):
        self.assertFalse(result.ok, "validator unexpectedly passed")
        self.assertIn(text, "\n".join(result.errors))

    def test_accepts_all_13_specified_dossiers_with_explicit_unknown_downstream_experiments(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all(verified=False)
            result = self.validate_fixture(fx)
            self.assertEqual([], result.errors)
            self.assertTrue(result.ok)

    def test_rejects_missing_dossier_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            (fx.research / "dossiers/index.json").unlink()
            self.assertFailsWith(self.validate_fixture(fx), "missing required dossier index")

    def test_rejects_static_graph_free_form_relation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D01", lambda m: m["static_graph"]["edges"][0].update({"relation": "trust me"}))
            self.assertFailsWith(self.validate_fixture(fx), "invalid relation 'trust me'")

    def test_rejects_unknown_terminal_state_without_unknown_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D02", lambda m: m.update({"unknowns": []}))
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "unknown terminal state lacks matching unknown record")

    def test_rejects_verified_dynamic_completion_without_dynamic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all(verified=True)
            def mutate(m):
                d = ids("D03")
                m["dynamic_traces"]["evidence_bundle_ids"] = [d["evb"]]
                m["evidence_index"]["bundle_ids"] = [d["evb"]]
            fx.mutate_manifest("D03", mutate)
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "verified dossier requires E2/E3 dynamic evidence")

    def test_rejects_ledger_row_owned_by_wrong_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.ledger_rows[0]["dossier_id"] = "D02"
            fx.write_indexes()
            self.assertFailsWith(self.validate_fixture(fx), "dossier_id mismatch")

    def test_rejects_placeholder_manifest_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D04", lambda m: m.update({"owner": "TODO placeholder owner"}))
            self.assertFailsWith(self.validate_fixture(fx), "contains placeholder/TODO/stub prose")

    def test_rejects_fake_dynamic_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D05", lambda m: m["dynamic_claim_constraints"].update({"claims_live_completion": True, "note": "pretend live complete"}))
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "non-verified dossier cannot claim live/dynamic completion")
            self.assertFailsWith(result, "fake/pretend dynamic wording is forbidden")

    def test_rejects_no_fake_celsius_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D12", lambda m: m["no_fake_celsius_compliance"].update({"publishes_celsius": True, "calibrated": True}))
            self.assertFailsWith(self.validate_fixture(fx), "Celsius publication/calibration requires verified status and E5 fixture/live proof")

    def test_rejects_unresolved_contradictions(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D06", lambda m: m["unresolved_contradictions"].update({"count": 1, "contradiction_ids": ["CLM-X"]}))
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "count must be exactly 0")
            self.assertFailsWith(result, "contradiction_ids must be empty")

    def test_rejects_missing_claim_cross_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.claim_rows = [row for row in fx.claim_rows if row["claim_id"] != ids("D07")["claim"]]
            fx.write_indexes()
            self.assertFailsWith(self.validate_fixture(fx), "referenced claim missing from claims/index.json")

    def test_rejects_hash_mismatch_for_graph_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            graph = fx.root / RESEARCH_REL / "dossiers/D08/static_graph.json"
            graph.write_text('{"changed": true}\n', encoding="utf-8")
            self.assertFailsWith(self.validate_fixture(fx), "sha256 mismatch")

    def test_rejects_unsupported_unknown_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D09", lambda m: m["unknowns"][0].update({"state": "unknown_because_we_said_so"}))
            self.assertFailsWith(self.validate_fixture(fx), "not allowed")

    def test_rejects_tampered_claim_statement_even_when_index_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            claim = ids("D01")["claim"]
            claim_path = fx.root / RESEARCH_REL / "claims" / f"{claim}.json"
            data = json.loads(claim_path.read_text(encoding="utf-8"))
            data["statement"] = "Tampered statement keeps stale claim_id."
            write_json(claim_path, data)
            for row in fx.claim_rows:
                if row["claim_id"] == claim:
                    row.update(file_ref(fx.root, claim_path))
            fx.write_indexes()
            self.assertFailsWith(self.validate_fixture(fx), "claim_id recompute mismatch")

    def test_rejects_tampered_claim_evidence_ids_even_when_index_hash_is_updated(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            claim = ids("D02")["claim"]
            claim_path = fx.root / RESEARCH_REL / "claims" / f"{claim}.json"
            data = json.loads(claim_path.read_text(encoding="utf-8"))
            data["evidence_bundle_ids"] = ["EVB-G003-D02-EXTRA", ids("D02")["evb"]]
            write_json(claim_path, data)
            for row in fx.claim_rows:
                if row["claim_id"] == claim:
                    row.update(file_ref(fx.root, claim_path))
            fx.write_indexes()
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "claim_id recompute mismatch")

    def test_rejects_recomputed_claim_with_missing_evidence_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            d = ids("D01")
            fx.replace_claim_evidence_ids("D01", ["EVB-G003-D01-MISSING", d["evb"]])
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "referenced evidence bundle missing from evidence/index.json or scan")

    def test_rejects_recomputed_claim_with_duplicate_evidence_bundle_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            d = ids("D02")
            fx.replace_claim_evidence_ids("D02", [d["evb"], d["evb"]])
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "evidence_bundle_ids must be sorted unique")

    def test_rejects_recomputed_claim_with_invalid_non_evb_evidence_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            d = ids("D03")
            fx.replace_claim_evidence_ids("D03", [d["evb"], "NOT-EVB"])
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "invalid evidence_bundle_id 'NOT-EVB'")

    def test_rejects_recomputed_claim_with_missing_evidence_bundle_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.replace_claim_evidence_ids("D04", [])
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "evidence_bundle_ids must be non-empty sorted unique EVB list")

    def test_rejects_under_specified_cross_link_index_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.claim_rows[0].pop("artifact_set_id")
            fx.claim_rows[0].pop("subject_ids")
            fx.write_indexes()
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "index row missing required artifact_set_id")
            self.assertFailsWith(result, "index row missing required subject_ids")

    def test_rejects_unsorted_or_duplicate_subject_ids_in_cross_link_index_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            claim = fx.claim_rows[0]["claim_id"]
            fx.claim_rows[0]["subject_ids"] = [claim, claim]
            fx.write_indexes()
            self.assertFailsWith(self.validate_fixture(fx), "subject_ids must be sorted unique")

    def test_rejects_dossier_index_without_required_path_alias_and_subjects(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.dossier_entries[0].pop("path")
            fx.dossier_entries[0]["subject_ids"] = ["D01"]
            fx.write_indexes()
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "index row missing required path")
            self.assertFailsWith(result, "subject_ids must equal")

    def test_rejects_noncanonical_ledger_alias_when_static_ledger_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            static_ledger = fx.research / "static/ledger.json"
            rows = json.loads(static_ledger.read_text(encoding="utf-8"))["rows"]
            static_ledger.unlink()
            write_json(fx.research / "ledger/index.json", {"rows": rows})
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "missing canonical G003 row ledger at static/ledger.json")

    def test_rejects_contract_missing_repaired_minimum_machine_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            contract_path = fx.research / "governance/g003-dossier-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["validation_contract"]["minimum_machine_checks"].remove("claim_id_recompute_uses_claim_schema_evidence_bundle_ids")
            write_json(contract_path, contract)
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "minimum machine check claim_id_recompute_uses_claim_schema_evidence_bundle_ids missing")

    def test_rejects_contract_missing_phase_separation_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            contract_path = fx.research / "governance/g003-dossier-contract.json"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract.pop("phase_separation_contract")
            write_json(contract_path, contract)
            result = self.validate_fixture(fx)
            self.assertFailsWith(result, "phase_separation_contract.g003_nonterminal_manifest_rule missing")

    def test_rejects_evb_manifest_attachment_sha256_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            evb = ids("D01")["evb"]
            fx.mutate_evidence(evb, lambda m: m["attachments"][0].update({"sha256": "0" * 64}))
            self.assertFailsWith(self.validate_fixture(fx), f"EVB:{evb}:attachments[0]: sha256 mismatch expected {'0' * 64}")

    def test_rejects_evb_manifest_attachment_size_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            evb = ids("D02")["evb"]
            fx.mutate_evidence(evb, lambda m: m["attachments"][0].update({"size_bytes": 999999}))
            self.assertFailsWith(self.validate_fixture(fx), f"EVB:{evb}:attachments[0]: size mismatch expected 999999")

    def test_rejects_evb_manifest_attachment_missing_required_media_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            evb = ids("D03")["evb"]
            fx.mutate_evidence(evb, lambda m: m["attachments"][0].pop("media_type"))
            self.assertFailsWith(self.validate_fixture(fx), f"EVB:{evb}:attachments[0]: attachment missing media_type")

    def test_rejects_evb_manifest_without_required_attachments(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            evb = ids("D04")["evb"]
            fx.mutate_evidence(evb, lambda m: m.update({"attachments": []}))
            self.assertFailsWith(self.validate_fixture(fx), f"EVB:{evb}: attachments must be non-empty list")

    def test_rejects_evb_attachment_to_generated_dossier_local_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            evb = ids("D05")["evb"]
            ref = file_ref(fx.root, fx.root / RESEARCH_REL / "dossiers/D05/manifest.json")
            fx.mutate_evidence(evb, lambda m: m["attachments"][0].update({**ref, "media_type": "application/json"}))
            self.assertFailsWith(self.validate_fixture(fx), "attachment path must be raw immutable source evidence")

    def test_rejects_review_missing_current_dossier_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D01")["review"]
            fx.mutate_review(review, lambda m: m["subject_ids"].remove("DOS-G003-D01"))
            self.assertFailsWith(self.validate_fixture(fx), f"REV:{review}: review subject_ids must cover DOS-G003-D01")

    def test_rejects_review_missing_current_evidence_bundle_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            d = ids("D02")
            fx.mutate_review(d["review"], lambda m: m.update({"evidence_bundle_ids": []}))
            self.assertFailsWith(self.validate_fixture(fx), f"REV:{d['review']}: review evidence_bundle_ids must cover {d['evb']}")

    def test_rejects_review_index_subject_ids_stale_against_review_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D03")["review"]
            for row in fx.review_rows:
                if row["review_id"] == review:
                    row["subject_ids"] = [review]
            fx.write_indexes()
            self.assertFailsWith(self.validate_fixture(fx), f"reviews/index.json:{review}: subject_ids must match current review coverage")

    def test_rejects_review_that_lists_itself_as_reviewed_subject(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D04")["review"]
            fx.mutate_review(review, lambda m: m["subject_ids"].append(review))
            self.assertFailsWith(self.validate_fixture(fx), f"REV:{review}: review must not approve itself as a subject")

    def test_rejects_review_with_reviewed_manifest_backlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D05")["review"]
            fx.mutate_review(review, lambda m: m.update({"reviewed_manifest": {"sha256": "0" * 64}}))
            self.assertFailsWith(self.validate_fixture(fx), "review must not include reviewed_manifest or manifest-hash backlink")

    def test_rejects_review_extra_stale_subject_not_in_current_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D06")["review"]
            fx.mutate_review(review, lambda m: m["subject_ids"].append("SPEC-G003-D06-FFFFFFFFFFFF"))
            self.assertFailsWith(self.validate_fixture(fx), "review subject_ids must equal current DOS/SPEC/RPRO coverage")

    def test_rejects_review_extra_stale_evb_not_in_current_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            review = ids("D07")["review"]
            fx.mutate_review(review, lambda m: m["evidence_bundle_ids"].append("EVB-G003-D07-STALE"))
            self.assertFailsWith(self.validate_fixture(fx), "review evidence_bundle_ids must equal current EVB coverage")

    def test_rejects_spec_missing_contract_title_required_for_id_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            spec = ids("D06")["spec"]
            fx.mutate_spec(spec, lambda m: m.pop("contract_title"))
            self.assertFailsWith(self.validate_fixture(fx), f"SPEC:{spec}: missing contract_title")

    def test_rejects_spec_id_not_recomputed_from_contract_title_and_claim_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            spec = ids("D07")["spec"]
            fx.mutate_spec(spec, lambda m: m.update({"contract_title": "changed contract title"}))
            self.assertFailsWith(self.validate_fixture(fx), f"SPEC:{spec}: specification_id recompute mismatch expected")

    def test_rejects_spec_missing_claim_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            spec = ids("D08")["spec"]
            fx.mutate_spec(spec, lambda m: m.update({"claim_ids": []}))
            self.assertFailsWith(self.validate_fixture(fx), f"SPEC:{spec}: claim_ids must be non-empty list")

    def test_rejects_spec_missing_evidence_bundle_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            spec = ids("D09")["spec"]
            fx.mutate_spec(spec, lambda m: m.update({"evidence_bundle_ids": []}))
            self.assertFailsWith(self.validate_fixture(fx), f"SPEC:{spec}: evidence_bundle_ids must be non-empty list")

    def test_rejects_spec_not_source_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            spec = ids("D10")["spec"]
            fx.mutate_spec(spec, lambda m: m.update({"source_independent": False}))
            self.assertFailsWith(self.validate_fixture(fx), f"SPEC:{spec}: source_independent must be true")

    def test_rejects_rpro_missing_test_file_required_for_id_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            rpro = ids("D11")["rpro"]
            fx.mutate_rpro(rpro, lambda m: m.pop("test_file"))
            self.assertFailsWith(self.validate_fixture(fx), f"RPRO:{rpro}: missing test_file")

    def test_rejects_rpro_missing_test_name_required_for_id_recompute(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            rpro = ids("D12")["rpro"]
            fx.mutate_rpro(rpro, lambda m: m.pop("test_name"))
            self.assertFailsWith(self.validate_fixture(fx), f"RPRO:{rpro}: missing test_name")

    def test_rejects_rpro_id_not_recomputed_from_test_file_test_name_and_specs(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            rpro = ids("D13")["rpro"]
            fx.mutate_rpro(rpro, lambda m: m.update({"test_name": "test_changed"}))
            self.assertFailsWith(self.validate_fixture(fx), f"RPRO:{rpro}: reproduction_id recompute mismatch expected")

    def test_rejects_rpro_missing_specification_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            rpro = ids("D01")["rpro"]
            fx.mutate_rpro(rpro, lambda m: m.update({"specification_ids": []}))
            self.assertFailsWith(self.validate_fixture(fx), f"RPRO:{rpro}: specification_ids must be non-empty list")

    def test_allows_nonterminal_g003_pending_downstream_rpro_last_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            rpro = ids("D02")["rpro"]
            fx.mutate_rpro(rpro, lambda m: m["last_result"].update({"status": "pending_downstream"}))
            result = self.validate_fixture(fx)
            self.assertEqual([], result.errors)

    def test_rejects_static_graph_missing_artifact_ref_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D03", lambda m: m["static_graph"].update({"artifact_ref": "not-an-object"}))
            self.assertFailsWith(self.validate_fixture(fx), "D03/static_graph: artifact_ref must be object")

    def test_rejects_state_machine_missing_artifact_ref_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D04", lambda m: m["state_machine"].update({"artifact_ref": None}))
            self.assertFailsWith(self.validate_fixture(fx), "D04/state_machine: artifact_ref must be object")

    def test_rejects_static_graph_sha256_not_matching_artifact_ref_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D05", lambda m: m["static_graph"].update({"graph_sha256": "0" * 64}))
            self.assertFailsWith(self.validate_fixture(fx), "D05/static_graph: graph_sha256 mismatch expected artifact digest")

    def test_rejects_state_machine_sha256_not_matching_artifact_ref_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D06", lambda m: m["state_machine"].update({"state_machine_sha256": "0" * 64}))
            self.assertFailsWith(self.validate_fixture(fx), "D06/state_machine: state_machine_sha256 mismatch expected artifact digest")

    def test_rejects_artifact_hashes_missing_static_graph_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D07", lambda m: m.update({"artifact_hashes": [m["state_machine"]["artifact_ref"]]}))
            self.assertFailsWith(self.validate_fixture(fx), "D07/artifact_hashes: missing static_graph artifact_ref")

    def test_rejects_artifact_hashes_missing_state_machine_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            fx = G003Fixture(tmp).make_all()
            fx.mutate_manifest("D08", lambda m: m.update({"artifact_hashes": [m["static_graph"]["artifact_ref"]]}))
            self.assertFailsWith(self.validate_fixture(fx), "D08/artifact_hashes: missing state_machine artifact_ref")


if __name__ == "__main__":
    unittest.main()
