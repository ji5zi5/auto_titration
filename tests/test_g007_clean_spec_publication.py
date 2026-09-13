import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
G003_INDEX_REL = RESEARCH_REL / "specs/index.json"
G007_INDEX_REL = RESEARCH_REL / "specs/g007/index.json"
G007_STATUS_REL = RESEARCH_REL / "specs/g007/status.json"
G007_REVIEW_INDEX_REL = RESEARCH_REL / "reviews/g007-index.json"
G007_README_REL = RESEARCH_REL / "specs/g007/README.md"
FIXTURE_MANIFEST_REL = RESEARCH_REL / "reproduction/g007-fixtures-manifest.json"
G003_INDEX = ROOT / G003_INDEX_REL
G003_INDEX_SHA256 = "68abc1f0383306269f2ac015a5ddfdc688fd029723ff9401c7abe82fbc4547f8"
MISSION_SLUG = "hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti"
VALIDATOR = ROOT / "tools/hik_whole_apk/g007_spec_validator.py"

AUTHORITY_INDEX_RELS = (
    RESEARCH_REL / "dossiers/index.json",
    RESEARCH_REL / "claims/index.json",
    RESEARCH_REL / "evidence/index.json",
    G003_INDEX_REL,
    RESEARCH_REL / "reproduction/index.json",
)


def canonical_bytes(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value) + b"\n")


def publication_path(root, rel):
    return root / rel


def canonical_minimum_artifact_paths():
    """Return only files read directly or through a path field by the G007 validator."""
    index = read_json(ROOT / G007_INDEX_REL)
    fixtures = read_json(ROOT / FIXTURE_MANIFEST_REL)
    status = read_json(ROOT / G007_STATUS_REL)

    paths = {
        *AUTHORITY_INDEX_RELS,
        G007_INDEX_REL,
        G007_STATUS_REL,
        G007_README_REL,
        FIXTURE_MANIFEST_REL,
        Path(index["source_index_path"]),
    }
    paths.update(
        RESEARCH_REL / f"dossiers/D{number:02d}/manifest.json"
        for number in range(1, 14)
    )
    paths.update(
        Path(entry["path"])
        for fixture in fixtures["fixtures"]
        for entry in fixture["source_paths"]
    )
    paths.update(Path(entry["path"]) for entry in status["artifact_hashes"])

    research_root = (ROOT / RESEARCH_REL).resolve()
    for rel in paths:
        source = (ROOT / rel).resolve()
        if source != research_root and research_root not in source.parents:
            raise AssertionError(f"canonical G007 artifact escapes research root: {rel}")
        if not source.is_file():
            raise AssertionError(f"canonical G007 artifact is missing: {rel}")
    return tuple(sorted(paths, key=lambda path: path.as_posix()))


def copy_canonical_minimum_publication(destination):
    """Copy the accepted publication without copying unrelated 13 GB research inputs."""
    destination = destination.resolve()
    for rel in canonical_minimum_artifact_paths():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, target)
    return destination


def refresh_status_artifact_hash(root, artifact_rel):
    """Keep the outer publication hash valid so mutations reach semantic checks."""
    status_path = publication_path(root, G007_STATUS_REL)
    status = read_json(status_path)
    artifact = publication_path(root, artifact_rel)
    for entry in status["artifact_hashes"]:
        if entry["path"] == artifact_rel.as_posix():
            data = artifact.read_bytes()
            entry["sha256"] = sha256_bytes(data)
            entry["size_bytes"] = len(data)
            write_json(status_path, status)
            return
    raise AssertionError(f"status does not hash {artifact_rel}")


def write_readme(root, text, *, refresh_status=True):
    publication_path(root, G007_README_REL).write_text(text, encoding="utf-8")
    if refresh_status:
        refresh_status_artifact_hash(root, G007_README_REL)




def recompute_fixture_definition_hash(root, fixture_index=0):
    fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
    fixtures = read_json(fixtures_path)
    row = fixtures["fixtures"][fixture_index]
    definition = dict(row)
    definition.pop("definition_sha256", None)
    row["definition_sha256"] = sha256_bytes(canonical_bytes(definition))
    write_json(fixtures_path, fixtures)
    refresh_status_artifact_hash(root, FIXTURE_MANIFEST_REL)


def refresh_status_artifact_hashes(root):
    status_path = publication_path(root, G007_STATUS_REL)
    status = read_json(status_path)
    for entry in status["artifact_hashes"]:
        artifact = publication_path(root, Path(entry["path"]))
        entry["sha256"] = sha256_bytes(artifact.read_bytes())
        entry["size_bytes"] = artifact.stat().st_size
    write_json(status_path, status)


def status_hash_entry(root, artifact_rel):
    artifact = publication_path(root, artifact_rel)
    return {
        "path": artifact_rel.as_posix(),
        "sha256": sha256_bytes(artifact.read_bytes()),
        "size_bytes": artifact.stat().st_size,
    }


REVIEW_SUBJECT_RELS = (
    G007_README_REL,
    G007_INDEX_REL,
    FIXTURE_MANIFEST_REL,
)

REQUIRED_REVIEW_CHECKS = (
    "source_independence",
    "no_decompiler_or_source_body_leakage",
    "no_terminal_live_f2_radiometric_or_celsius_claims",
    "authority_traceability",
    "artifact_hashes_match_indexed_subjects",
)


def subject_artifact_hash(root, artifact_rel):
    return sha256_bytes(publication_path(root, artifact_rel).read_bytes())


def final_subject_artifact_hashes(root):
    return {rel.as_posix(): subject_artifact_hash(root, rel) for rel in REVIEW_SUBJECT_RELS}


def g007_review_artifacts(
    root,
    *,
    stale_hash=False,
    self_review=False,
    wrong_subject=False,
    incomplete_coverage=False,
    omit_subject_artifact_hashes=False,
    stale_subject_artifact_hash=False,
    missing_subject_artifact_hash=False,
    extra_subject_artifact_hash=False,
    omit_checks=False,
    missing_check=False,
    failing_check=False,
):
    index = read_json(publication_path(root, G007_INDEX_REL))
    fixtures = read_json(publication_path(root, FIXTURE_MANIFEST_REL))
    status = read_json(publication_path(root, G007_STATUS_REL))
    review_id = "REV-G007-INDEPENDENT-PUBLICATION-PASS"
    review_rel = RESEARCH_REL / "reviews/g007-independent-publication-pass.json"
    reviews_index_rel = G007_REVIEW_INDEX_REL

    # Promote the subject artifacts before hashing them for the independent
    # review. This keeps the valid reviewed-state fixture non-circular: review
    # bytes depend on final index/fixture/README bytes, while status hashes the
    # resulting review/index artifacts afterwards and is not a review subject.
    index.update({"approved": True, "clean_room_review_id": review_id, "review_ids": [review_id]})
    write_json(publication_path(root, G007_INDEX_REL), index)
    fixtures.update({"approved": True, "independent_review_id": review_id})
    write_json(publication_path(root, FIXTURE_MANIFEST_REL), fixtures)
    status.update({"approved": True, "independent_review": "passed"})
    write_json(publication_path(root, G007_STATUS_REL), status)

    contract_ids = [row["contract_id"] for row in index["contracts"]]
    test_ids = [row["test_id"] for row in index["acceptance_tests"]]
    fixture_ids = [row["fixture_id"] for row in fixtures["fixtures"]]
    if incomplete_coverage:
        contract_ids = contract_ids[:-1]

    subject_hashes = final_subject_artifact_hashes(root)
    if stale_subject_artifact_hash:
        subject_hashes[G007_INDEX_REL.as_posix()] = "0" * 64
    if missing_subject_artifact_hash:
        subject_hashes.pop(G007_README_REL.as_posix())
    if extra_subject_artifact_hash:
        subject_hashes[G007_STATUS_REL.as_posix()] = subject_artifact_hash(root, G007_STATUS_REL)

    checks = {check: "pass" for check in REQUIRED_REVIEW_CHECKS}
    if missing_check:
        checks.pop(REQUIRED_REVIEW_CHECKS[0])
    if failing_check:
        checks[REQUIRED_REVIEW_CHECKS[0]] = "fail"

    review = {
        "schema_version": 1,
        "schema": "g007-independent-publication-review/v1",
        "review_id": review_id,
        "reviewer_id": index["author_id"] if self_review else "independent-g007-reviewer",
        "reviewer_role": "independent-clean-room-verifier",
        "independent_from_author_id": index["author_id"],
        "independent_from_producers": not self_review,
        "subject_specification_id": "SPEC-G007-WRONG-SUBJECT" if wrong_subject else index["specification_id"],
        "covered_contract_ids": contract_ids,
        "covered_acceptance_test_ids": test_ids,
        "covered_fixture_ids": fixture_ids,
        "verdict": "pass",
        "passed": True,
        "reviewed_at": "2026-07-23T00:00:00Z",
    }
    if not omit_subject_artifact_hashes:
        review["subject_artifact_hashes"] = subject_hashes
    if not omit_checks:
        review["checks"] = checks

    write_json(publication_path(root, review_rel), review)
    review_hash = sha256_bytes(publication_path(root, review_rel).read_bytes())
    reviews_index = {
        "artifact_set_id": index["artifact_set_id"],
        "reviews": [
            {
                "review_id": review_id,
                "path": review_rel.as_posix(),
                "sha256": ("0" * 64) if stale_hash else review_hash,
                "size_bytes": publication_path(root, review_rel).stat().st_size,
                "subject_ids": [index["specification_id"]],
            }
        ],
    }
    write_json(publication_path(root, reviews_index_rel), reviews_index)

    status = read_json(publication_path(root, G007_STATUS_REL))
    existing_by_path = {entry["path"]: entry for entry in status["artifact_hashes"]}
    expected_status_paths = (G007_README_REL, G007_INDEX_REL, FIXTURE_MANIFEST_REL, reviews_index_rel, review_rel)
    status["artifact_hashes"] = [
        status_hash_entry(root, rel) if rel.as_posix() not in existing_by_path else status_hash_entry(root, rel)
        for rel in expected_status_paths
    ]
    write_json(publication_path(root, G007_STATUS_REL), status)


def demote_to_candidate_publication(root):
    """Convert the promoted canonical fixture into the pre-review candidate lifecycle."""
    index_path = publication_path(root, G007_INDEX_REL)
    index = read_json(index_path)
    index.update({"approved": False, "clean_room_review_id": None, "review_ids": []})
    write_json(index_path, index)

    fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
    fixtures = read_json(fixtures_path)
    fixtures.update({"approved": False, "independent_review_id": None})
    write_json(fixtures_path, fixtures)

    status_path = publication_path(root, G007_STATUS_REL)
    status = read_json(status_path)
    status.update({"approved": False, "independent_review": "pending"})
    status["artifact_hashes"] = [
        status_hash_entry(root, rel)
        for rel in (G007_README_REL, G007_INDEX_REL, FIXTURE_MANIFEST_REL)
    ]
    write_json(status_path, status)

def mutate_json(root, rel, edit, *, refresh_status=True):
    path = publication_path(root, rel)
    value = read_json(path)
    edit(value)
    write_json(path, value)
    if refresh_status and rel in {G007_INDEX_REL, FIXTURE_MANIFEST_REL}:
        refresh_status_artifact_hash(root, rel)


class G007SpecValidatorContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not VALIDATOR.is_file():
            raise AssertionError(f"G007 validator is missing: {VALIDATOR}")

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory(prefix="g007-publication-tests-")
        self.canonical_temp = tempfile.TemporaryDirectory(
            prefix="canonical-",
            dir=self.workspace.name,
        )
        self.root = copy_canonical_minimum_publication(
            Path(self.canonical_temp.name)
        )
        demote_to_candidate_publication(self.root)

    def tearDown(self):
        self.canonical_temp.cleanup()
        self.workspace.cleanup()

    def run_validator(self, root=None):
        target = (root or self.root).resolve()
        result = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--root",
                str(target),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {"raw_stdout": result.stdout, "stderr": result.stderr}
        return result.returncode, payload, result

    def assert_validator_rejects(self, mutator, label):
        # Each mutation root is a sibling of the canonical root. The source can
        # therefore never be recursively copied into one of its own descendants.
        with tempfile.TemporaryDirectory(
            prefix=f"mutation-{label}-",
            dir=self.workspace.name,
        ) as mutation_dir:
            mutated = Path(mutation_dir).resolve()
            self.assertEqual(mutated.parent, self.root.parent)
            self.assertNotIn(self.root, mutated.parents)
            self.assertNotIn(mutated, self.root.parents)
            shutil.copytree(
                self.root,
                mutated,
                dirs_exist_ok=True,
                symlinks=True,
            )
            mutator(mutated)
            rc, payload, result = self.run_validator(mutated)
            self.assertNotEqual(
                rc,
                0,
                f"{label} unexpectedly accepted: {payload}\n{result.stderr}",
            )
            self.assertFalse(
                payload.get("ok", False),
                f"{label} falsely passed: {payload}",
            )

    def test_cli_json_happy_path_accepts_complete_publication_with_g008_pending(self):
        rc, payload, result = self.run_validator()
        self.assertEqual(rc, 0, result.stderr)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("errors"), [], payload)

        index = read_json(publication_path(self.root, G007_INDEX_REL))
        status = read_json(publication_path(self.root, G007_STATUS_REL))
        fixtures = read_json(publication_path(self.root, FIXTURE_MANIFEST_REL))
        self.assertEqual(index["g008_execution_summary"]["status"], "pending")
        self.assertEqual(status["g008_execution"], "pending")
        self.assertEqual(status["independent_review"], "pending")
        self.assertFalse(status["approved"])
        self.assertEqual(fixtures["status"], "definition_only_g008_pending")
        self.assertFalse(fixtures["approved"])
        self.assertTrue(all(not values for values in status["terminal_claims"].values()))

    def test_temp_copy_mutation_matrix_rejects_contract_violations(self):
        def edit_index(root, edit):
            mutate_json(root, G007_INDEX_REL, edit)

        def edit_fixtures(root, edit):
            mutate_json(root, FIXTURE_MANIFEST_REL, edit)

        def edit_status(root, edit):
            mutate_json(root, G007_STATUS_REL, edit, refresh_status=False)

        matrix = {
            "unknown_id": lambda root: edit_index(
                root,
                lambda data: data["acceptance_tests"][0][
                    "verification_claim_ids"
                ].__setitem__(0, "CLM-G003-D01-FFFFFFFFFFFFFFFF"),
            ),
            "duplicate_acceptance_id": lambda root: edit_index(
                root,
                lambda data: data["acceptance_tests"].append(
                    copy.deepcopy(data["acceptance_tests"][0])
                ),
            ),
            "duplicate_canonical_id": lambda root: edit_index(
                root,
                lambda data: data["claim_ids"].append(data["claim_ids"][0]),
            ),
            "unsorted_hash_locked_fixture_ids": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0]["source_claim_ids"].reverse(),
            ),
            "missing_fixture_definition_hash": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0].pop("definition_sha256"),
            ),
            "incorrect_fixture_definition_hash": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0].__setitem__(
                    "definition_sha256",
                    "0" * 64,
                ),
            ),
            "missing_source_hash": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0]["source_paths"][0].pop(
                    "sha256"
                ),
            ),
            "incorrect_source_hash": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0]["source_paths"][0].__setitem__(
                    "sha256",
                    "0" * 64,
                ),
            ),
            "incorrect_source_size": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0]["source_paths"][0].__setitem__(
                    "size_bytes",
                    1,
                ),
            ),
            "path_traversal": lambda root: edit_fixtures(
                root,
                lambda data: data["fixtures"][0]["source_paths"][0].__setitem__(
                    "path",
                    "../escape.json",
                ),
            ),
            "forbidden_source_and_control_flow_content": lambda root: edit_index(
                root,
                lambda data: data["contracts"][0].__setitem__(
                    "title",
                    "jadx smali copied source invoke-virtual",
                ),
            ),
            "terminal_live_claim": lambda root: edit_status(
                root,
                lambda data: data["terminal_claims"]["live_f2_runs"].append(
                    "RUN-G008-LIVE-F2"
                ),
            ),
            "terminal_celsius_claim": lambda root: edit_index(
                root,
                lambda data: data["contracts"][0].__setitem__(
                    "title",
                    "calibrated Celsius result verified",
                ),
            ),
            "missing_privacy_boundary": lambda root: edit_index(
                root,
                lambda data: data["contracts"][0]["boundaries"].pop("privacy"),
            ),
            "missing_no_fake_celsius_boundary": lambda root: edit_index(
                root,
                lambda data: data["contracts"][0]["boundaries"].pop(
                    "no_fake_celsius"
                ),
            ),
            "author_self_approval": lambda root: edit_index(
                root,
                lambda data: data.__setitem__("approved", True),
            ),
            "author_self_review": lambda root: edit_index(
                root,
                lambda data: data.update(
                    {
                        "clean_room_review_id": data["author_id"],
                        "review_ids": [data["author_id"]],
                    }
                ),
            ),
            "acceptance_false_executed_result": lambda root: edit_index(
                root,
                lambda data: data["acceptance_tests"][0].update(
                    {
                        "execution_status": "passed",
                        "run_id": "RUN-G008-FABRICATED",
                        "result_bundle_ids": [
                            "EVB-G008-FABRICATED-RESULT"
                        ],
                    }
                ),
            ),
        }
        for label, mutator in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)

    def test_readme_rejects_leakage_and_fake_terminal_claims_but_accepts_truthful_pending(self):
        write_readme(
            self.root,
            "# G007 pending publication\n\n"
            "No live F2, radiometric, calibrated Celsius, or hardware result "
            "is claimed; independent review remains pending.\n",
        )
        rc, payload, result = self.run_validator()
        self.assertEqual(rc, 0, result.stderr)
        self.assertTrue(payload.get("ok"), payload)

        rejected_readmes = {
            "readme_decompiler_leakage": "# Bad\n\nThis publishes jadx decompiler source listings.",
            "readme_source_body_leakage": "# Bad\n\nCopied source body: package com.hik.viewer; invoke-virtual v0, v1",
            "readme_fake_live_f2_terminal": "# Bad\n\nLive F2 hardware run passed.",
            "readme_fake_radiometric_celsius_terminal": "# Bad\n\nRadiometric calibrated Celsius result verified at 36.5 °C.",
            "readme_fake_f2_result_verified": "# Bad\n\nF2 result verified.",
            "readme_fake_e4_e5_result_bundle_verified": "# Bad\n\nE4/E5 result bundle verified.",
            "readme_fake_g008_execution_result_passed": "# Bad\n\nG008 execution result passed.",
            "readme_fake_equivalent_f2_success": "# Bad\n\nF2 result successful.",
            "readme_fake_equivalent_e4_e5_green": "# Bad\n\nE4 and E5 result bundles are green.",
            "readme_fake_equivalent_g008_completed": "# Bad\n\nG008 execution completed successfully.",
            "readme_fake_standalone_e4_result_bundle_verified": "# Bad\n\nE4 result bundle verified.",
            "readme_fake_standalone_e5_evidence_bundle_passed": "# Bad\n\nE5 evidence bundle passed.",
            "readme_fake_standalone_e4_run_successful": "# Bad\n\nE4 run successful.",
            "readme_fake_standalone_e5_result_verified": "# Bad\n\nE5 result verified.",
        }
        for label, text in rejected_readmes.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(
                    lambda root, content=text: write_readme(root, content),
                    label,
                )

    def test_readme_accepts_explicit_pending_not_claimed_result_wording(self):
        accepted_readmes = {
            "f2_pending": "# Good\n\nF2 remains pending and is not claimed as a verified result.\n",
            "e4_e5_pending": "# Good\n\nE4/E5 result bundle remains pending; no result bundle is verified.\n",
            "e4_pending": "# Good\n\nE4 result bundle remains pending and is not claimed as verified.\n",
            "e5_pending": "# Good\n\nE5 evidence bundle is pending and not claimed as passed.\n",
            "e4_run_pending": "# Good\n\nE4 run is pending; it is not claimed as successful.\n",
            "e5_result_pending": "# Good\n\nE5 result remains pending and is not verified.\n",
            "g008_pending": "# Good\n\nG008 execution result remains pending and not claimed.\n",
        }
        for label, text in accepted_readmes.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(
                    prefix=f"mutation-{label}-",
                    dir=self.workspace.name,
                ) as mutation_dir:
                    mutated = Path(mutation_dir).resolve()
                    shutil.copytree(self.root, mutated, dirs_exist_ok=True, symlinks=True)
                    write_readme(mutated, text)
                    rc, payload, result = self.run_validator(mutated)
                    self.assertEqual(rc, 0, result.stderr)
                    self.assertTrue(payload.get("ok"), payload)

    def test_readme_content_change_without_refreshed_status_hash_is_rejected(self):
        self.assert_validator_rejects(
            lambda root: write_readme(
                root,
                "# G007 pending publication\n\n"
                "This content-only edit keeps all results pending and not claimed.\n",
                refresh_status=False,
            ),
            "readme_stale_status_hash",
        )

    def test_status_rejects_fake_f2_e4_e5_and_g008_result_claim_wording(self):
        matrix = {
            "status_fake_f2_result_verified": ("live_f2_runs", "F2 result verified"),
            "status_fake_e4_e5_result_bundle_verified": ("e4_e5_result_bundles", "E4/E5 result bundle verified"),
            "status_fake_g008_execution_result_passed": ("hardware_runs", "G008 execution result passed"),
            "status_fake_equivalent_f2_success": ("live_f2_runs", "F2 result successful"),
            "status_fake_equivalent_e4_e5_green": ("e4_e5_result_bundles", "E4 and E5 result bundles are green"),
            "status_fake_equivalent_g008_completed": ("hardware_runs", "G008 execution completed successfully"),
            "status_fake_standalone_e4_result_bundle_verified": ("e4_e5_result_bundles", "E4 result bundle verified"),
            "status_fake_standalone_e5_evidence_bundle_passed": ("e4_e5_result_bundles", "E5 evidence bundle passed"),
            "status_fake_standalone_e4_run_successful": ("e4_e5_result_bundles", "E4 run successful"),
            "status_fake_standalone_e5_result_verified": ("e4_e5_result_bundles", "E5 result verified"),
        }
        for label, (field, claim) in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(
                    lambda root, terminal_field=field, text=claim: mutate_json(
                        root,
                        G007_STATUS_REL,
                        lambda data: data["terminal_claims"][terminal_field].append(text),
                        refresh_status=False,
                    ),
                    label,
                )

    def test_index_rejects_standalone_e4_e5_terminal_result_claim_wording(self):
        matrix = {
            "index_fake_standalone_e4_result_bundle_verified": "E4 result bundle verified",
            "index_fake_standalone_e5_evidence_bundle_passed": "E5 evidence bundle passed",
            "index_fake_standalone_e4_run_successful": "E4 run successful",
            "index_fake_standalone_e5_result_verified": "E5 result verified",
        }
        for label, claim in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(
                    lambda root, text=claim: mutate_json(
                        root,
                        G007_INDEX_REL,
                        lambda data: data["contracts"][0].__setitem__("title", text),
                    ),
                    label,
                )

    def test_public_artifacts_reject_prefix_form_terminal_result_claims(self):
        def mutate_fixture_normalization(root, claim):
            fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
            fixtures = read_json(fixtures_path)
            fixtures["fixtures"][0]["normalization"] = claim
            write_json(fixtures_path, fixtures)
            recompute_fixture_definition_hash(root, 0)

        matrix = {
            "readme_prefix_verified_e4_run": lambda root: write_readme(
                root,
                "# Bad\n\nVerified E4 run using representative pending fixture text.\n",
            ),
            "index_prefix_passed_e5_evidence_bundle": lambda root: mutate_json(
                root,
                G007_INDEX_REL,
                lambda data: data["contracts"][0].__setitem__(
                    "title",
                    "Passed E5 evidence bundle using representative pending fixture text",
                ),
            ),
            "fixture_prefix_approved_standalone_f2_run": lambda root: mutate_fixture_normalization(
                root,
                "Approved standalone F2 run using representative pending fixture text",
            ),
            "status_prefix_verified_g008_execution_result": lambda root: mutate_json(
                root,
                G007_STATUS_REL,
                lambda data: data.__setitem__(
                    "specification_id",
                    "Verified G008 execution result using representative pending status text",
                ),
                refresh_status=False,
            ),
        }
        for label, mutator in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)

    def test_readme_accepts_prefix_form_pending_or_negated_result_wording(self):
        accepted_readmes = {
            "prefix_verified_e4_run_negated": "# Good\n\nVerified E4 run is not claimed; E4 run remains pending.\n",
            "prefix_passed_e5_evidence_bundle_pending": "# Good\n\nPassed E5 evidence bundle remains pending and is not claimed.\n",
            "prefix_approved_standalone_f2_run_negated": "# Good\n\nApproved standalone F2 run is not claimed before G008.\n",
            "prefix_verified_g008_execution_result_pending": "# Good\n\nVerified G008 execution result is pending and not claimed.\n",
        }
        for label, text in accepted_readmes.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(
                    prefix=f"mutation-{label}-",
                    dir=self.workspace.name,
                ) as mutation_dir:
                    mutated = Path(mutation_dir).resolve()
                    shutil.copytree(self.root, mutated, dirs_exist_ok=True, symlinks=True)
                    write_readme(mutated, text)
                    rc, payload, result = self.run_validator(mutated)
                    self.assertEqual(rc, 0, result.stderr)
                    self.assertTrue(payload.get("ok"), payload)

    def test_public_artifacts_reject_review_mixed_pending_then_terminal_claims(self):
        def mutate_fixture_normalization(root, claim):
            fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
            fixtures = read_json(fixtures_path)
            fixtures["fixtures"][0]["normalization"] = claim
            write_json(fixtures_path, fixtures)
            recompute_fixture_definition_hash(root, 0)

        matrix = {
            "readme_negated_e4_run_then_terminal": lambda root: write_readme(
                root,
                "# Bad\n\n"
                "Verified E4 run is not claimed; E4 run verified.\n",
            ),
            "index_pending_e5_bundle_then_terminal": lambda root: mutate_json(
                root,
                G007_INDEX_REL,
                lambda data: data["contracts"][0].__setitem__(
                    "title",
                    "Passed E5 evidence bundle remains pending; E5 evidence bundle passed.",
                ),
            ),
            "fixture_negated_standalone_f2_then_terminal": lambda root: mutate_fixture_normalization(
                root,
                "Approved standalone F2 run is not claimed; standalone F2 run approved.",
            ),
            "status_pending_g008_result_then_terminal": lambda root: mutate_json(
                root,
                G007_STATUS_REL,
                lambda data: data.__setitem__(
                    "specification_id",
                    "Verified G008 execution result is pending; G008 execution result verified.",
                ),
                refresh_status=False,
            ),
        }
        for label, mutator in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)

    def test_readme_accepts_review_single_pending_or_negated_phrases(self):
        accepted_readmes = {
            "single_negated_e4_run": "# Good\n\nVerified E4 run is not claimed.\n",
            "single_pending_e5_bundle": "# Good\n\nPassed E5 evidence bundle remains pending.\n",
            "single_negated_standalone_f2": "# Good\n\nApproved standalone F2 run is not claimed.\n",
            "single_pending_g008_result": "# Good\n\nVerified G008 execution result is pending.\n",
        }
        for label, text in accepted_readmes.items():
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory(
                    prefix=f"mutation-{label}-",
                    dir=self.workspace.name,
                ) as mutation_dir:
                    mutated = Path(mutation_dir).resolve()
                    shutil.copytree(self.root, mutated, dirs_exist_ok=True, symlinks=True)
                    write_readme(mutated, text)
                    rc, payload, result = self.run_validator(mutated)
                    self.assertEqual(rc, 0, result.stderr)
                    self.assertTrue(payload.get("ok"), payload)

    def test_status_accepts_empty_terminal_claims_as_explicit_pending_not_claimed_state(self):
        status = read_json(publication_path(self.root, G007_STATUS_REL))
        self.assertEqual(status["g008_execution"], "pending")
        self.assertEqual(status["independent_review"], "pending")
        self.assertTrue(all(value == [] for value in status["terminal_claims"].values()))
        rc, payload, result = self.run_validator()
        self.assertEqual(rc, 0, result.stderr)
        self.assertTrue(payload.get("ok"), payload)

    def test_source_contract_ids_reject_bogus_and_wrong_dossier_values(self):
        matrix = {
            "bogus_source_contract_id": lambda data: data["contracts"][0][
                "source_contract_ids"
            ].__setitem__(0, "CONTRACT-G003-D99-STATIC"),
            "wrong_dossier_source_contract_id": lambda data: data["contracts"][0][
                "source_contract_ids"
            ].__setitem__(0, data["contracts"][1]["source_contract_ids"][0]),
        }
        for label, edit in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(
                    lambda root, mutator=edit: mutate_json(root, G007_INDEX_REL, mutator),
                    label,
                )

    def test_status_counts_and_exact_artifact_hash_set_are_locked(self):
        matrix = {
            "status_count_tampering": lambda status: status["counts"].__setitem__(
                "contracts",
                status["counts"]["contracts"] + 1,
            ),
            "status_hash_missing_index": lambda status: status["artifact_hashes"].pop(0),
            "status_hash_extra_readme": lambda status: status["artifact_hashes"].append(
                status_hash_entry(self.root, G007_README_REL)
            ),
            "status_hash_duplicate_index": lambda status: status["artifact_hashes"].append(
                copy.deepcopy(status["artifact_hashes"][0])
            ),
        }
        for label, edit in matrix.items():
            with self.subTest(label=label):
                def mutate(root, mutator=edit):
                    status_path = publication_path(root, G007_STATUS_REL)
                    status = read_json(status_path)
                    if label == "status_hash_extra_readme":
                        status["artifact_hashes"].append(status_hash_entry(root, G007_README_REL))
                    else:
                        mutator(status)
                    write_json(status_path, status)

                self.assert_validator_rejects(mutate, label)

    def test_recomputed_unsorted_id_arrays_are_still_rejected(self):
        def reverse_first_fixture_claims(root):
            fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
            fixtures = read_json(fixtures_path)
            fixtures["fixtures"][0]["source_claim_ids"].reverse()
            write_json(fixtures_path, fixtures)
            recompute_fixture_definition_hash(root, 0)

        def reverse_first_contract_claims(root):
            mutate_json(
                root,
                G007_INDEX_REL,
                lambda data: data["contracts"][0]["evidence_claim_ids"].reverse(),
            )

        def reverse_first_acceptance_claims(root):
            mutate_json(
                root,
                G007_INDEX_REL,
                lambda data: data["acceptance_tests"][0]["verification_claim_ids"].reverse(),
            )

        matrix = {
            "unsorted_fixture_source_claim_ids": reverse_first_fixture_claims,
            "unsorted_contract_evidence_claim_ids": reverse_first_contract_claims,
            "unsorted_acceptance_verification_claim_ids": reverse_first_acceptance_claims,
        }
        for label, mutator in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)

    def test_symlink_escape_is_rejected_for_hash_locked_source(self):
        def mutate(root):
            fixtures = read_json(publication_path(root, FIXTURE_MANIFEST_REL))
            target = publication_path(
                root,
                Path(fixtures["fixtures"][0]["source_paths"][0]["path"]),
            )
            escaped = root / "escaped-source.json"
            shutil.copy2(target, escaped)
            target.unlink()
            target.symlink_to(escaped)

        self.assert_validator_rejects(mutate, "symlink_escape")

    def test_ancestor_symlink_escape_is_rejected_for_hash_locked_source(self):
        def mutate(root):
            fixtures_path = publication_path(root, FIXTURE_MANIFEST_REL)
            fixtures = read_json(fixtures_path)
            source_entry = fixtures["fixtures"][0]["source_paths"][0]
            original = publication_path(root, Path(source_entry["path"]))
            escaped_dir = root / "escaped-ancestor"
            escaped_dir.mkdir()
            escaped_file = escaped_dir / "source.json"
            shutil.copy2(original, escaped_file)
            link_dir = publication_path(root, RESEARCH_REL / "linked-source-dir")
            link_dir.symlink_to(escaped_dir, target_is_directory=True)
            source_entry["path"] = (RESEARCH_REL / "linked-source-dir/source.json").as_posix()
            source_entry["sha256"] = sha256_bytes(escaped_file.read_bytes())
            source_entry["size_bytes"] = escaped_file.stat().st_size
            write_json(fixtures_path, fixtures)
            recompute_fixture_definition_hash(root, 0)

        self.assert_validator_rejects(mutate, "ancestor_symlink_escape")

    def test_reviewed_state_accepts_only_indexed_hash_matching_independent_pass_review(self):
        def promote(root):
            g007_review_artifacts(root)

        with tempfile.TemporaryDirectory(
            prefix="mutation-reviewed-accepted-",
            dir=self.workspace.name,
        ) as mutation_dir:
            reviewed = Path(mutation_dir).resolve()
            self.assertEqual(reviewed.parent, self.root.parent)
            shutil.copytree(self.root, reviewed, dirs_exist_ok=True, symlinks=True)
            promote(reviewed)
            rc, payload, result = self.run_validator(reviewed)
            self.assertEqual(rc, 0, result.stderr)
            self.assertTrue(payload.get("ok"), payload)

        reject_matrix = {
            "approved_missing_review": lambda root: mutate_json(
                root,
                G007_INDEX_REL,
                lambda data: data.update({"approved": True}),
            ),
            "approved_stale_review_hash": lambda root: g007_review_artifacts(root, stale_hash=True),
            "approved_self_review": lambda root: g007_review_artifacts(root, self_review=True),
            "approved_wrong_subject_review": lambda root: g007_review_artifacts(root, wrong_subject=True),
            "approved_incomplete_review_coverage": lambda root: g007_review_artifacts(root, incomplete_coverage=True),
            "approved_review_missing_subject_artifact_hashes": lambda root: g007_review_artifacts(root, omit_subject_artifact_hashes=True),
            "approved_review_stale_subject_artifact_hash": lambda root: g007_review_artifacts(root, stale_subject_artifact_hash=True),
            "approved_review_missing_subject_artifact_hash_entry": lambda root: g007_review_artifacts(root, missing_subject_artifact_hash=True),
            "approved_review_extra_subject_artifact_hash_entry": lambda root: g007_review_artifacts(root, extra_subject_artifact_hash=True),
            "approved_review_missing_checks": lambda root: g007_review_artifacts(root, omit_checks=True),
            "approved_review_missing_required_check": lambda root: g007_review_artifacts(root, missing_check=True),
            "approved_review_non_pass_required_check": lambda root: g007_review_artifacts(root, failing_check=True),
        }
        for label, mutator in reject_matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)

    def test_reviewed_state_rejects_post_review_subject_mutation_even_with_refreshed_status_hashes(self):
        def promote_then_mutate(root, rel, edit):
            g007_review_artifacts(root)
            path = publication_path(root, rel)
            if rel == G007_README_REL:
                path.write_text(edit(path.read_text(encoding="utf-8")), encoding="utf-8")
            else:
                value = read_json(path)
                edit(value)
                write_json(path, value)
            refresh_status_artifact_hashes(root)

        matrix = {
            "reviewed_index_subject_mutated": lambda root: promote_then_mutate(
                root,
                G007_INDEX_REL,
                lambda data: data.__setitem__("publication_state", data["publication_state"] + " mutated"),
            ),
            "reviewed_readme_subject_mutated": lambda root: promote_then_mutate(
                root,
                G007_README_REL,
                lambda text: text + "\nReview-subject mutation after approval.\n",
            ),
            "reviewed_fixture_manifest_subject_mutated": lambda root: promote_then_mutate(
                root,
                FIXTURE_MANIFEST_REL,
                lambda data: data["safety_boundaries"].append("mutated_after_review"),
            ),
        }
        for label, mutator in matrix.items():
            with self.subTest(label=label):
                self.assert_validator_rejects(mutator, label)


class G007PublicationRegressionBoundaryTests(unittest.TestCase):
    def test_legacy_g003_index_remains_g003_and_byte_stable(self):
        data = G003_INDEX.read_bytes()
        self.assertEqual(G003_INDEX_SHA256, sha256_bytes(data))
        index = json.loads(data)
        self.assertEqual(index["schema"], "g003-specs-index/v1")
        ids = [row["specification_id"] for row in index["specifications"]]
        self.assertTrue(ids)
        self.assertTrue(
            all(specification_id.startswith("SPEC-G003-") for specification_id in ids)
        )
        self.assertNotIn("G007", data.decode("utf-8"))

    def test_g003_dossier_validator_still_passes_legacy_publication(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.hik_whole_apk.g003_dossier_validator",
                "--root",
                str(ROOT),
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload.get("ok"), payload)

    def test_acceptance_traceability_uses_hash_locked_fixture_definitions(self):
        index = read_json(ROOT / G007_INDEX_REL)
        fixtures = read_json(ROOT / FIXTURE_MANIFEST_REL)
        fixture_ids = [row["fixture_id"] for row in fixtures["fixtures"]]
        self.assertEqual(fixture_ids, sorted(set(fixture_ids)))

        for row in fixtures["fixtures"]:
            recorded = row["definition_sha256"]
            definition = dict(row)
            definition.pop("definition_sha256")
            self.assertEqual(
                recorded,
                sha256_bytes(canonical_bytes(definition)),
                row["fixture_id"],
            )
            for source in row["source_paths"]:
                data = publication_path(ROOT, Path(source["path"])).read_bytes()
                self.assertEqual(source["sha256"], sha256_bytes(data))
                self.assertEqual(source["size_bytes"], len(data))

        contract_test_ids = {
            test_id
            for contract in index["contracts"]
            for test_id in contract["acceptance_test_ids"]
        }
        acceptance_test_ids = {
            test["test_id"] for test in index["acceptance_tests"]
        }
        self.assertEqual(contract_test_ids, acceptance_test_ids)
        self.assertTrue(
            all(test["contract_ids"] for test in index["acceptance_tests"])
        )
        self.assertTrue(
            all(test["fixture_ids"] for test in index["acceptance_tests"])
        )
        referenced_fixture_ids = {
            fixture_id
            for test in index["acceptance_tests"]
            for fixture_id in test["fixture_ids"]
        }
        self.assertEqual(referenced_fixture_ids, set(fixture_ids))

    def test_final_critic_remains_nonzero_before_g008_without_message_coupling(self):
        result = subprocess.run(
            [
                sys.executable,
                "tools/hik_whole_apk/critic.py",
                "--mission",
                MISSION_SLUG,
                "--repo-root",
                str(ROOT),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload.get("passed"), payload)
        self.assertGreater(
            payload.get("gate_counts", {}).get("failed", 0),
            0,
            payload,
        )


if __name__ == "__main__":
    unittest.main()
