#!/usr/bin/env python3
"""Deterministic fail-closed validator for G003 HIKMICRO dossier manifests.

The validator is intentionally stdlib-only and evidence-driven.  It validates
links and hashes that exist; it does not promote producer booleans, placeholder
files, or planned/live-dynamic prose into completion.  Explicit unknown terminal
attempts are accepted only as non-approval records with downstream experiments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
DEFAULT_CONTRACT = ROOT / RESEARCH_REL / "governance/g003-dossier-contract.json"
DOSSIER_IDS = tuple(f"D{i:02d}" for i in range(1, 14))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DOSSIER_RE = re.compile(r"^D(0[1-9]|1[0-3])$")
CLAIM_RE = re.compile(r"^CLM-G003-D(0[1-9]|1[0-3])-[A-F0-9]{16}$|^CLM-G002-[A-Z0-9._-]+$")
EVB_RE = re.compile(r"^EVB-G00[2-6]-[A-Z0-9._-]+$")
INV_RE = re.compile(r"^INV-[A-Z0-9._:-]+$")
SPEC_RE = re.compile(r"^SPEC-G003-D(0[1-9]|1[0-3])-[A-F0-9]{12}$")
RPRO_RE = re.compile(r"^RPRO-G003-D(0[1-9]|1[0-3])-[A-F0-9]{12}$")
REV_RE = re.compile(r"^REV-G003-D(0[1-9]|1[0-3])-[A-Z0-9._-]+-[A-F0-9]{12}$")
ROW_RE = re.compile(r"^ROW-G003-D(0[1-9]|1[0-3])-[A-F0-9]{16}$")
UNKNOWN_RE = re.compile(r"^UNK-G003-D(0[1-9]|1[0-3])-[A-Z0-9._-]+$")
PLACEHOLDER_WORDS = ("placeholder", "todo", "tbd", "stub", "lorem ipsum", "coming soon")
DYNAMIC_CLAIM_WORDS = (
    "runtime", "dynamic", "live", "callback", "frame", "timing", "thread", "buffer",
    "usb transfer", "network", "recovery", "restoration", "reachable", "observed",
)
FAKE_DYNAMIC_WORDS = ("pretend", "assume live", "simulated live", "fake dynamic", "mock live")
CELSIUS_WORDS = ("celsius", "°c", "degc", "temperature_c", "calibrated")
SOURCE_VARIANTS = {"untouched", "root-attached", "patched-gadget", "emulated", "reimplementation"}
DYNAMIC_TIERS = {"E2", "E3"}
REPRO_TIERS = {"E4", "E5"}
VERIFY_TIERS = {"E5"}


class DuplicateKeyError(ValueError):
    pass


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    normalized_seen: dict[str, str] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        normalized = unicodedata.normalize("NFC", key)
        if normalized in normalized_seen and normalized_seen[normalized] != key:
            raise DuplicateKeyError(f"post-NFC-colliding JSON keys {normalized_seen[normalized]!r}/{key!r}")
        normalized_seen[normalized] = key
        out[key] = value
    return out


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs_no_duplicates)
    except DuplicateKeyError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        seen: dict[str, str] = {}
        for key, item in value.items():
            nkey = unicodedata.normalize("NFC", str(key))
            if nkey in seen and seen[nkey] != key:
                raise ValueError(f"post-NFC-colliding JSON keys {seen[nkey]!r}/{key!r}")
            seen[nkey] = str(key)
            normalized[nkey] = _normalize(item)
        return normalized
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def rel_path(root: Path, path_value: str) -> Path:
    if not isinstance(path_value, str) or not path_value:
        raise ValueError("path must be a non-empty repository-relative string")
    pure = PurePosixPath(path_value)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"unsafe non-relative path {path_value!r}")
    return root / Path(*pure.parts)


def is_non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def lower_blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except TypeError:
        return str(value).lower()


def _validated_claim_evidence_bundle_ids(evidence_bundle_ids: Any) -> list[str] | None:
    if not isinstance(evidence_bundle_ids, list) or not evidence_bundle_ids:
        return None
    if any(not isinstance(evb, str) or not EVB_RE.match(evb) for evb in evidence_bundle_ids):
        return None
    if evidence_bundle_ids != sorted(set(evidence_bundle_ids)):
        return None
    return evidence_bundle_ids



def _validated_sorted_ids(value: Any, pattern: re.Pattern[str]) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if any(not isinstance(item, str) or not pattern.match(item) for item in value):
        return None
    if value != sorted(set(value)):
        return None
    return value


def expected_g003_spec_id(dossier_id: str, contract_title: Any, claim_ids: Any) -> str | None:
    if not isinstance(contract_title, str) or not contract_title:
        return None
    validated_ids = _validated_sorted_ids(claim_ids, CLAIM_RE)
    if validated_ids is None:
        return None
    digest_input = contract_title + "\0" + "\0".join(validated_ids)
    return f"SPEC-G003-{dossier_id}-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:12].upper()}"


def expected_g003_reproduction_id(dossier_id: str, test_file: Any, test_name: Any, specification_ids: Any) -> str | None:
    if not isinstance(test_file, str) or not test_file or not isinstance(test_name, str) or not test_name:
        return None
    validated_ids = _validated_sorted_ids(specification_ids, SPEC_RE)
    if validated_ids is None:
        return None
    digest_input = test_file + "\0" + test_name + "\0" + "\0".join(validated_ids)
    return f"RPRO-G003-{dossier_id}-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:12].upper()}"

def expected_g003_claim_id(dossier_id: str, statement: Any, evidence_bundle_ids: Any) -> str | None:
    if not isinstance(statement, str):
        return None
    validated_ids = _validated_claim_evidence_bundle_ids(evidence_bundle_ids)
    if validated_ids is None:
        return None
    digest_input = statement + "\0" + "\0".join(validated_ids)
    return f"CLM-G003-{dossier_id}-{hashlib.sha256(digest_input.encode('utf-8')).hexdigest()[:16].upper()}"


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: set[Path] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


class G003DossierValidator:
    def __init__(self, root: Path = ROOT, contract_path: Path | None = None, *, check_authority: bool = True):
        self.root = root.resolve()
        self.research = self.root / RESEARCH_REL
        self.contract_path = contract_path or self.research / "governance/g003-dossier-contract.json"
        if not self.contract_path.is_absolute():
            self.contract_path = self.root / self.contract_path
        self.check_authority = check_authority
        self.result = ValidationResult()
        self.contract: Mapping[str, Any] = {}
        self.artifact_set_id = ""
        self.roster: list[Mapping[str, Any]] = []
        self.claims: dict[str, Mapping[str, Any]] = {}
        self.evidence: dict[str, Mapping[str, Any]] = {}
        self.specs: dict[str, Mapping[str, Any]] = {}
        self.repros: dict[str, Mapping[str, Any]] = {}
        self.reviews: dict[str, Mapping[str, Any]] = {}
        self.ledger_rows: dict[str, Mapping[str, Any]] = {}
        self.manifests: dict[str, Mapping[str, Any]] = {}
        self.owned_rows: dict[str, str] = {}
        self.referenced_claims: set[str] = set()
        self.referenced_evidence: set[str] = set()
        self.referenced_specs: set[str] = set()
        self.referenced_repros: set[str] = set()
        self.referenced_reviews: set[str] = set()

    def validate(self) -> ValidationResult:
        self._load_contract()
        if not self.result.ok:
            return self.result
        self._validate_contract_authority()
        self._load_indexes()
        self._validate_dossier_index()
        for dossier in DOSSIER_IDS:
            if dossier in self.manifests:
                self._validate_manifest(dossier, self.manifests[dossier])
        self._validate_cross_links_global()
        return self.result

    def _load_contract(self) -> None:
        if not self.contract_path.is_file():
            self.result.error("contract", f"missing {self.contract_path}")
            return
        try:
            contract = load_json(self.contract_path)
        except Exception as exc:
            self.result.error("contract", str(exc))
            return
        self.result.checked_files.add(self.contract_path)
        self.contract = contract
        if contract.get("schema") != "g003-dossier-contract/v1":
            self.result.error("contract", "schema must equal g003-dossier-contract/v1")
        self.artifact_set_id = str(contract.get("artifact_set_id", ""))
        roster = contract.get("dossier_roster")
        if not isinstance(roster, list) or [r.get("dossier_id") for r in roster] != list(DOSSIER_IDS):
            self.result.error("contract", "dossier_roster must be exactly D01-D13 in order")
            self.roster = []
        else:
            self.roster = roster
        needed = self.contract.get("validation_contract", {}).get("minimum_machine_checks", [])
        required_checks = (
            "json_parse_contract",
            "schema_field_equals_g003-dossier-contract/v1",
            "exact_roster_D01_D13",
            "required_field_contracts_present",
            "unknown_terminal_attempt_states_present",
            "cross_link_invariants_present",
            "dont_claim_dynamic_constraints_present",
            "no_fake_celsius_constraints_present",
            "claim_id_recompute_uses_claim_schema_evidence_bundle_ids",
            "cross_link_index_contracts_present",
            "canonical_scope_ledger_path_static_ledger_json",
            "g003_g004_g006_phase_separation_present",
            "evb_internal_attachment_raw_ref_hash_size_media_type_present",
            "evb_internal_attachments_nonempty_immutable_source_evidence",
            "evb_internal_attachments_forbid_generated_dossier_backrefs",
            "acyclic_review_current_subject_and_evidence_coverage",
            "reviews_forbid_reviewed_manifest_hash_backlinks_and_self_review",
            "spec_id_recompute_uses_contract_title_and_sorted_claim_ids",
            "spec_required_fields_and_source_independence_present",
            "rpro_id_recompute_uses_test_file_test_name_and_sorted_spec_ids",
            "rpro_required_fields_and_nonterminal_g003_last_result_states_present",
            "graph_state_artifact_ref_object_raw_hash_and_canonical_digest_present",
            "graph_state_artifact_refs_in_manifest_artifact_hashes",
        )
        for token in required_checks:
            if token not in needed:
                self.result.error("contract", f"minimum machine check {token} missing")
        if not isinstance(self.contract.get("cross_link_index_contracts"), dict):
            self.result.error("contract", "cross_link_index_contracts must be present")
        ledger_path = self.contract.get("canonical_scope_ledger", {}).get("path")
        if ledger_path != str(RESEARCH_REL / "static/ledger.json"):
            self.result.error("contract", "canonical_scope_ledger.path must be static/ledger.json")
        phase_contract = self.contract.get("phase_separation_contract", {})
        if not isinstance(phase_contract, dict) or "g003_nonterminal_manifest_rule" not in phase_contract:
            self.result.error("contract", "phase_separation_contract.g003_nonterminal_manifest_rule missing")

    def _validate_contract_authority(self) -> None:
        if not self.check_authority:
            return
        for row in as_list(self.contract.get("authority_inputs")):
            where = f"authority:{row.get('path')}"
            try:
                path = rel_path(self.root, row.get("path"))
            except Exception as exc:
                self.result.error(where, str(exc))
                continue
            if not path.is_file():
                self.result.error(where, "missing authority input")
                continue
            self.result.checked_files.add(path)
            size = path.stat().st_size
            digest = sha256_file(path)
            if size != row.get("size_bytes"):
                self.result.error(where, f"size mismatch expected {row.get('size_bytes')} got {size}")
            if digest != row.get("sha256"):
                self.result.error(where, f"sha256 mismatch expected {row.get('sha256')} got {digest}")

    def _load_index_file(self, rel: str, key_names: Sequence[str], id_key: str) -> dict[str, Mapping[str, Any]]:
        path = self.research / rel
        if not path.is_file():
            self.result.error(rel, "missing required index")
            return {}
        try:
            data = load_json(path)
        except Exception as exc:
            self.result.error(rel, str(exc))
            return {}
        self.result.checked_files.add(path)
        rows: Any = None
        for name in key_names:
            if isinstance(data, dict) and isinstance(data.get(name), list):
                rows = data[name]
                break
        if rows is None and isinstance(data, list):
            rows = data
        if rows is None:
            self.result.error(rel, f"index must contain one of {key_names}")
            return {}
        out: dict[str, Mapping[str, Any]] = {}
        for item in rows:
            if not isinstance(item, dict):
                self.result.error(rel, "index row is not object")
                continue
            identifier = item.get(id_key)
            if not isinstance(identifier, str):
                self.result.error(rel, f"index row missing {id_key}")
                continue
            if identifier in out:
                self.result.error(rel, f"duplicate {id_key} {identifier}")
            out[identifier] = item
            manifest = None
            if "path" in item and "sha256" in item and "size_bytes" in item:
                manifest = self._validate_artifact_ref(f"{rel}:{identifier}", item, allow_json_parse=True)
            self._validate_cross_link_index_row(rel, item, id_key, identifier, manifest)
        return out

    def _validate_cross_link_index_row(self, rel: str, row: Mapping[str, Any], id_key: str, identifier: str, manifest: Any | None) -> None:
        contracts = self.contract.get("cross_link_index_contracts", {})
        if not isinstance(contracts, dict):
            return
        contract = contracts.get(rel)
        if not isinstance(contract, dict):
            self.result.error(rel, "missing cross-link index contract")
            return
        where = f"{rel}:{identifier}"
        for field_name in contract.get("row_required_fields", []):
            if field_name not in row:
                self.result.error(where, f"index row missing required {field_name}")
        artifact_set_id = row.get("artifact_set_id")
        if artifact_set_id != self.artifact_set_id:
            self.result.error(where, "index row artifact_set_id mismatch")
        subject_ids = row.get("subject_ids")
        if not isinstance(subject_ids, list) or not subject_ids:
            self.result.error(where, "subject_ids must be non-empty sorted unique list")
        elif any(not isinstance(item, str) or not item for item in subject_ids):
            self.result.error(where, "subject_ids must contain non-empty strings")
        elif subject_ids != sorted(set(subject_ids)):
            self.result.error(where, "subject_ids must be sorted unique")
        elif identifier not in subject_ids and rel != "evidence/index.json":
            self.result.error(where, f"subject_ids must include {identifier}")
        pattern = contract.get("primary_id_pattern")
        if isinstance(pattern, str) and not re.match(pattern, identifier):
            self.result.error(where, f"{id_key} does not match contract pattern")
        if isinstance(manifest, dict) and manifest.get("artifact_set_id") not in (None, self.artifact_set_id):
            self.result.error(where, "resolved artifact_set_id mismatch")

    def _load_indexes(self) -> None:
        self.claims = self._load_index_file("claims/index.json", ("claims",), "claim_id")
        self.specs = self._load_index_file("specs/index.json", ("specifications", "specs"), "specification_id")
        self.repros = self._load_index_file("reproduction/index.json", ("reproductions", "tests"), "reproduction_id")
        self.reviews = self._load_index_file("reviews/index.json", ("reviews",), "review_id")
        self.evidence = self._load_index_file("evidence/index.json", ("evidence_bundles", "bundles"), "evidence_bundle_id")
        if not self.evidence:
            # Some producers place EVB manifests under dynamic/reproduction; scan as a fallback,
            # still requiring hash rows when referenced by dossier evidence_index.
            for path in sorted(self.research.glob("**/EVB-*.json")):
                try:
                    data = load_json(path)
                except Exception:
                    continue
                bundle_id = data.get("evidence_bundle_id") or data.get("bundle_id")
                if isinstance(bundle_id, str):
                    self.evidence[bundle_id] = {
                        "evidence_bundle_id": bundle_id,
                        "path": str(path.relative_to(self.root)),
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
        ledger_rel = "static/ledger.json"
        path = self.research / ledger_rel
        if not path.is_file():
            self.result.error(ledger_rel, "missing canonical G003 row ledger at static/ledger.json")
        else:
            try:
                data = load_json(path)
            except Exception as exc:
                self.result.error(ledger_rel, str(exc))
                data = None
            if data is not None:
                self.result.checked_files.add(path)
                rows = data.get("rows") if isinstance(data, dict) else data
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict) and isinstance(row.get("row_id"), str):
                            self.ledger_rows[row["row_id"]] = row
                else:
                    self.result.error(ledger_rel, "canonical ledger rows must be a list")
        if not self.ledger_rows:
            self.result.error("ledger", "missing canonical G003 row ledger index")

    def _validate_dossier_index_row_contract(self, dossier_id: str, entry: Mapping[str, Any]) -> None:
        contract = self.contract.get("cross_link_index_contracts", {}).get("dossiers/index.json", {})
        where = f"dossiers/index.json:{dossier_id}"
        for field_name in contract.get("row_required_fields", []):
            if field_name not in entry:
                self.result.error(where, f"index row missing required {field_name}")
        if entry.get("artifact_set_id") != self.artifact_set_id:
            self.result.error(where, "index row artifact_set_id mismatch")
        expected_subjects = [f"DOS-G003-{dossier_id}", dossier_id]
        if entry.get("subject_ids") != expected_subjects:
            self.result.error(where, f"subject_ids must equal {expected_subjects}")
        if "manifest_path" in entry and "path" in entry and entry.get("manifest_path") != entry.get("path"):
            self.result.error(where, "manifest_path and path must match")

    def _validate_dossier_index(self) -> None:
        path = self.research / "dossiers/index.json"
        if not path.is_file():
            self.result.error("dossiers/index.json", "missing required dossier index")
            return
        try:
            data = load_json(path)
        except Exception as exc:
            self.result.error("dossiers/index.json", str(exc))
            return
        self.result.checked_files.add(path)
        entries = data.get("dossiers") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            self.result.error("dossiers/index.json", "dossiers must be a list")
            return
        if [entry.get("dossier_id") for entry in entries if isinstance(entry, dict)] != list(DOSSIER_IDS):
            self.result.error("dossiers/index.json", "must contain exactly D01-D13 in roster order and no extras")
        expected_paths = {
            roster["dossier_id"]: roster["canonical_manifest"] for roster in self.roster if isinstance(roster, dict)
        }
        for entry in entries:
            if not isinstance(entry, dict):
                self.result.error("dossiers/index.json", "entry is not object")
                continue
            dossier_id = entry.get("dossier_id")
            if isinstance(dossier_id, str):
                self._validate_dossier_index_row_contract(dossier_id, entry)
            manifest_path_value = entry.get("manifest_path") or entry.get("path")
            if dossier_id not in DOSSIER_IDS:
                self.result.error("dossiers/index.json", f"unexpected dossier {dossier_id!r}")
                continue
            expected = expected_paths.get(dossier_id, f"{RESEARCH_REL}/dossiers/{dossier_id}/manifest.json")
            if manifest_path_value != expected:
                self.result.error(f"dossiers/index.json:{dossier_id}", f"manifest path must be {expected}")
                continue
            manifest_path = rel_path(self.root, manifest_path_value)
            if not manifest_path.is_file():
                self.result.error(f"dossiers/{dossier_id}", "missing manifest")
                continue
            try:
                manifest = load_json(manifest_path)
            except Exception as exc:
                self.result.error(f"dossiers/{dossier_id}/manifest.json", str(exc))
                continue
            self.result.checked_files.add(manifest_path)
            if "sha256" in entry and sha256_file(manifest_path) != entry.get("sha256"):
                self.result.error(f"dossiers/index.json:{dossier_id}", "manifest sha256 mismatch")
            if "size_bytes" in entry and manifest_path.stat().st_size != entry.get("size_bytes"):
                self.result.error(f"dossiers/index.json:{dossier_id}", "manifest size mismatch")
            self.manifests[dossier_id] = manifest

    def _validate_manifest(self, dossier_id: str, manifest: Mapping[str, Any]) -> None:
        where = f"{dossier_id}/manifest"
        required = self.contract.get("required_manifest_contract", {}).get("required_top_level_fields", [])
        for field_name in required:
            if field_name not in manifest:
                self.result.error(where, f"missing top-level field {field_name}")
        if manifest.get("schema") not in ("g003-dossier-manifest/v1", "g003-dossier/v1"):
            self.result.error(where, "schema must be g003-dossier-manifest/v1")
        if manifest.get("dossier_id") != dossier_id:
            self.result.error(where, "dossier_id must match directory/index")
        if manifest.get("dossier_manifest_id") != f"DOS-G003-{dossier_id}":
            self.result.error(where, "dossier_manifest_id must be DOS-G003-Dxx")
        expected_name = next((row.get("name") for row in self.roster if row.get("dossier_id") == dossier_id), None)
        if manifest.get("dossier_name") != expected_name:
            self.result.error(where, "dossier_name must match frozen roster")
        if manifest.get("artifact_set_id") != self.artifact_set_id:
            self.result.error(where, "artifact_set_id mismatch")
        status = manifest.get("status")
        status_enum = set(self.contract.get("required_manifest_contract", {}).get("status_enum", []))
        if status not in status_enum:
            self.result.error(where, f"invalid status {status!r}")
        if self._contains_placeholder(manifest):
            self.result.error(where, "contains placeholder/TODO/stub prose")
        self._validate_manifest_hash(where, manifest)
        self._validate_ledger_ownership(dossier_id, manifest.get("ledger_row_ownership"), manifest.get("scope_rows"))
        self._validate_scope_rows(dossier_id, status, manifest.get("scope_rows"))
        self._validate_static_graph(dossier_id, manifest.get("static_graph"))
        self._validate_dynamic_traces(dossier_id, status, manifest.get("dynamic_traces"), manifest.get("unknowns"))
        self._validate_state_machine(dossier_id, status, manifest.get("state_machine"), manifest.get("unknowns"))
        self._validate_evidence_index(dossier_id, manifest.get("evidence_index"))
        self._validate_unknowns(dossier_id, status, manifest.get("unknowns"))
        self._validate_contradictions(dossier_id, manifest.get("unresolved_contradictions"), status)
        self._validate_contracts(dossier_id, manifest.get("source_independent_contracts"))
        self._validate_id_array(dossier_id, "specification_ids", manifest.get("specification_ids"), SPEC_RE, self.referenced_specs)
        self._validate_reproduction_tests(dossier_id, status, manifest.get("reproduction_tests"))
        self._validate_id_array(dossier_id, "review_ids", manifest.get("review_ids"), REV_RE, self.referenced_reviews)
        self._validate_artifact_hashes(dossier_id, manifest.get("artifact_hashes"), manifest)
        self._validate_no_fake_celsius(dossier_id, status, manifest)
        self._validate_no_fake_dynamic(dossier_id, status, manifest)
        for invariant in as_list(manifest.get("cross_link_invariants")):
            if not isinstance(invariant, str) or not invariant:
                self.result.error(f"{dossier_id}/cross_link_invariants", "invariants must be non-empty strings")

    def _contains_placeholder(self, value: Any) -> bool:
        if isinstance(value, str):
            text = value.strip().lower()
            if not text:
                return False
            return any(word in text for word in PLACEHOLDER_WORDS)
        if isinstance(value, list):
            return any(self._contains_placeholder(item) for item in value)
        if isinstance(value, dict):
            return any(self._contains_placeholder(item) for item in value.values())
        return False

    def _validate_manifest_hash(self, where: str, manifest: Mapping[str, Any]) -> None:
        digest = manifest.get("manifest_sha256")
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            self.result.error(where, "manifest_sha256 must be lowercase SHA-256")
            return
        payload = dict(manifest)
        payload.pop("manifest_sha256", None)
        try:
            actual = sha256_bytes(canonical_json_bytes(payload))
        except Exception as exc:
            self.result.error(where, f"cannot canonicalize manifest: {exc}")
            return
        if digest != actual:
            self.result.error(where, f"manifest_sha256 mismatch expected canonical digest {actual}")

    def _validate_artifact_ref(self, where: str, ref: Mapping[str, Any], *, allow_json_parse: bool = False) -> Any | None:
        for field_name in ("path", "size_bytes", "sha256"):
            if field_name not in ref:
                self.result.error(where, f"artifact ref missing {field_name}")
                return None
        try:
            path = rel_path(self.root, ref["path"])
        except Exception as exc:
            self.result.error(where, str(exc))
            return None
        if not path.is_file():
            self.result.error(where, f"artifact path missing {ref['path']}")
            return None
        self.result.checked_files.add(path)
        if path.name.lower() == "readme.md" or any(word in str(ref.get("path", "")).lower() for word in ("placeholder", "stub", "todo")):
            self.result.error(where, "artifact ref points to placeholder/README path")
        size = path.stat().st_size
        digest = sha256_file(path)
        if ref.get("size_bytes") != size:
            self.result.error(where, f"size mismatch expected {ref.get('size_bytes')} got {size}")
        if ref.get("sha256") != digest:
            self.result.error(where, f"sha256 mismatch expected {ref.get('sha256')} got {digest}")
        if allow_json_parse:
            try:
                return load_json(path)
            except Exception as exc:
                self.result.error(where, f"referenced JSON invalid: {exc}")
        return None

    def _validate_ledger_ownership(self, dossier_id: str, ownership: Any, scope_rows: Any) -> None:
        where = f"{dossier_id}/ledger_row_ownership"
        if not isinstance(ownership, dict):
            self.result.error(where, "must be object")
            return
        required = self.contract.get("required_field_contracts", {}).get("ledger_row_ownership", {}).get("required_fields", [])
        for field_name in required:
            if field_name not in ownership:
                self.result.error(where, f"missing {field_name}")
        row_ids = ownership.get("row_ids")
        if not is_non_empty_list(row_ids):
            self.result.error(where, "row_ids must be non-empty")
            return
        if ownership.get("disjoint_owner") is not True:
            self.result.error(where, "disjoint_owner must be true")
        if not ownership.get("owner"):
            self.result.error(where, "owner must be non-empty")
        scope_row_ids = {row.get("row_id") for row in as_list(scope_rows) if isinstance(row, dict)}
        if set(row_ids) != scope_row_ids:
            self.result.error(where, "row_ids must exactly match scope_rows row_id set")
        for row_id in row_ids:
            if not isinstance(row_id, str) or not ROW_RE.match(row_id) or f"ROW-G003-{dossier_id}-" not in row_id:
                self.result.error(where, f"invalid row_id {row_id!r}")
                continue
            previous = self.owned_rows.get(row_id)
            if previous and previous != dossier_id:
                self.result.error(where, f"row {row_id} also owned by {previous}")
            self.owned_rows[row_id] = dossier_id
            ledger_row = self.ledger_rows.get(row_id)
            if ledger_row is None:
                self.result.error(where, f"row {row_id} missing from canonical ledger")
            elif ledger_row.get("dossier_id") != dossier_id:
                self.result.error(where, f"ledger row {row_id} dossier_id mismatch")

    def _validate_scope_rows(self, dossier_id: str, status: Any, scope_rows: Any) -> None:
        where = f"{dossier_id}/scope_rows"
        if not is_non_empty_list(scope_rows):
            self.result.error(where, "must be non-empty list")
            return
        contract = self.contract.get("required_field_contracts", {}).get("scope_rows", {})
        required = contract.get("required_fields", [])
        valid_states = set(contract.get("state_order", [])) | {"blocked"}
        valid_classes = set(contract.get("classification_status_enum", []))
        for row in scope_rows:
            if not isinstance(row, dict):
                self.result.error(where, "row must be object")
                continue
            row_id = row.get("row_id")
            row_where = f"{where}:{row_id}"
            for field_name in required:
                if field_name not in row:
                    self.result.error(row_where, f"missing {field_name}")
            if row.get("dossier_id") != dossier_id:
                self.result.error(row_where, "dossier_id mismatch")
            if row.get("state") not in valid_states:
                self.result.error(row_where, f"invalid state {row.get('state')!r}")
            if row.get("classification_status") not in valid_classes:
                self.result.error(row_where, f"invalid classification_status {row.get('classification_status')!r}")
            for name, pattern, sink in (
                ("claim_ids", CLAIM_RE, self.referenced_claims),
                ("evidence_bundle_ids", EVB_RE, self.referenced_evidence),
                ("specification_ids", SPEC_RE, self.referenced_specs),
                ("reproduction_ids", RPRO_RE, self.referenced_repros),
                ("verification_ids", EVB_RE, self.referenced_evidence),
                ("independent_review_ids", REV_RE, self.referenced_reviews),
            ):
                self._validate_id_array(dossier_id, f"scope_rows:{row_id}:{name}", row.get(name), pattern, sink, allow_empty=True)
            if row.get("state") == "verified":
                if row.get("classification_status") != "classified":
                    self.result.error(row_where, "verified row must be classified")
                for name in ("claim_ids", "evidence_bundle_ids", "specification_ids", "reproduction_ids", "verification_ids", "independent_review_ids"):
                    if not is_non_empty_list(row.get(name)):
                        self.result.error(row_where, f"verified row requires non-empty {name}")
            if row.get("classification_status") == "unknown" and not row.get("blocker"):
                self.result.error(row_where, "unknown row requires explicit blocker/experiment context")
        if status == "verified":
            for row in scope_rows:
                if isinstance(row, dict) and row.get("state") != "verified":
                    self.result.error(where, "verified dossier cannot contain non-verified scope rows")

    def _validate_static_graph(self, dossier_id: str, graph: Any) -> None:
        where = f"{dossier_id}/static_graph"
        if not isinstance(graph, dict):
            self.result.error(where, "must be object")
            return
        contract = self.contract.get("required_field_contracts", {}).get("static_graph", {})
        for field_name in contract.get("required_fields", []):
            if field_name not in graph:
                self.result.error(where, f"missing {field_name}")
        graph_payload = None
        if not isinstance(graph.get("artifact_ref"), dict):
            self.result.error(where, "artifact_ref must be object")
        else:
            graph_payload = self._validate_artifact_ref(where + ":artifact_ref", graph["artifact_ref"], allow_json_parse=True)
            if graph_payload is not None:
                actual = sha256_bytes(canonical_json_bytes(graph_payload))
                if graph.get("graph_sha256") != actual:
                    self.result.error(where, f"graph_sha256 mismatch expected artifact digest {actual}")
        nodes = graph.get("nodes")
        edges = graph.get("edges")
        if not isinstance(nodes, list) or len(nodes) < int(contract.get("min_nodes", 1)):
            self.result.error(where, "nodes must be non-empty")
            nodes = []
        if not isinstance(edges, list) or len(edges) < int(contract.get("min_edges", 1)):
            self.result.error(where, "edges must be non-empty")
            edges = []
        allowed_types = set(contract.get("allowed_static_node_types", [])) | set(contract.get("allowed_runtime_node_types", []))
        allowed_relations = set(contract.get("allowed_relations", []))
        node_ids = set()
        for node in nodes:
            if not isinstance(node, dict):
                self.result.error(where, "node must be object")
                continue
            node_id = node.get("node_id")
            node_ids.add(node_id)
            for field_name in contract.get("node_required_fields", []):
                if field_name not in node:
                    self.result.error(f"{where}:{node_id}", f"node missing {field_name}")
            if node.get("node_type") not in allowed_types:
                self.result.error(f"{where}:{node_id}", f"invalid node_type {node.get('node_type')!r}")
            self._validate_inv_refs(f"{where}:{node_id}", node.get("inv_refs"))
            self._validate_id_array(dossier_id, f"{where}:{node_id}:claim_ids", node.get("claim_ids"), CLAIM_RE, self.referenced_claims)
            self._validate_id_array(dossier_id, f"{where}:{node_id}:evidence_bundle_ids", node.get("evidence_bundle_ids"), EVB_RE, self.referenced_evidence)
            self._validate_id_array(dossier_id, f"{where}:{node_id}:specification_ids", node.get("specification_ids"), SPEC_RE, self.referenced_specs, allow_empty=True)
        for edge in edges:
            if not isinstance(edge, dict):
                self.result.error(where, "edge must be object")
                continue
            edge_id = edge.get("edge_id")
            edge_where = f"{where}:{edge_id}"
            for field_name in contract.get("edge_required_fields", []):
                if field_name not in edge:
                    self.result.error(edge_where, f"edge missing {field_name}")
            if edge.get("from_node_id") not in node_ids or edge.get("to_node_id") not in node_ids:
                self.result.error(edge_where, "edge endpoints must resolve to graph nodes")
            relation = edge.get("relation")
            if relation not in allowed_relations:
                self.result.error(edge_where, f"invalid relation {relation!r}")
            if edge.get("from_node_id") == edge.get("to_node_id") and relation != "transitions_to":
                self.result.error(edge_where, "self-loop rejected unless relation transitions_to")
            self._validate_inv_refs(edge_where, edge.get("inv_refs"))
            self._validate_id_array(dossier_id, edge_where + ":claim_ids", edge.get("claim_ids"), CLAIM_RE, self.referenced_claims)
            self._validate_id_array(dossier_id, edge_where + ":evidence_bundle_ids", edge.get("evidence_bundle_ids"), EVB_RE, self.referenced_evidence)
            self._validate_id_array(dossier_id, edge_where + ":specification_ids", edge.get("specification_ids"), SPEC_RE, self.referenced_specs, allow_empty=True)
        if not isinstance(graph.get("graph_sha256"), str) or not SHA256_RE.match(graph["graph_sha256"]):
            self.result.error(where, "graph_sha256 must be lowercase SHA-256")

    def _validate_dynamic_traces(self, dossier_id: str, status: Any, traces: Any, unknowns: Any) -> None:
        where = f"{dossier_id}/dynamic_traces"
        if not isinstance(traces, dict):
            self.result.error(where, "must be object")
            return
        required = self.contract.get("required_field_contracts", {}).get("dynamic_traces", {}).get("required_fields", [])
        for field_name in required:
            if field_name not in traces:
                self.result.error(where, f"missing {field_name}")
        source_variants = traces.get("source_variants")
        if not isinstance(source_variants, list) or any(item not in SOURCE_VARIANTS for item in source_variants):
            self.result.error(where, "source_variants must use the frozen enum")
        evbs = traces.get("evidence_bundle_ids")
        self._validate_id_array(dossier_id, where + ":evidence_bundle_ids", evbs, EVB_RE, self.referenced_evidence, allow_empty=True)
        has_trace = is_non_empty_list(traces.get("trace_ids")) and is_non_empty_list(evbs)
        has_dynamic_tier = any(self._evidence_tier(evb) in DYNAMIC_TIERS for evb in as_list(evbs))
        has_explicit_unknown = is_non_empty_list(unknowns)
        if has_trace and not has_dynamic_tier:
            self.result.error(where, "dynamic traces cannot be satisfied by E1/static or non-dynamic evidence")
        if not has_trace and not has_explicit_unknown:
            self.result.error(where, "missing dynamic trace evidence or explicit unknown with downstream experiment")
        if status == "verified" and not has_dynamic_tier:
            self.result.error(where, "verified dossier requires E2/E3 dynamic evidence, not future-owned live placeholders")
        if any(variant in {"root-attached", "patched-gadget", "emulated"} for variant in as_list(source_variants)):
            if not traces.get("instrumentation_comparison"):
                self.result.error(where, "instrumented/emulated traces require paired instrumentation_comparison")

    def _validate_state_machine(self, dossier_id: str, status: Any, machine: Any, unknowns: Any) -> None:
        where = f"{dossier_id}/state_machine"
        if not isinstance(machine, dict):
            self.result.error(where, "must be object")
            return
        contract = self.contract.get("required_field_contracts", {}).get("state_machine", {})
        for field_name in contract.get("required_fields", []):
            if field_name not in machine:
                self.result.error(where, f"missing {field_name}")
        machine_payload = None
        if not isinstance(machine.get("artifact_ref"), dict):
            self.result.error(where, "artifact_ref must be object")
        else:
            machine_payload = self._validate_artifact_ref(where + ":artifact_ref", machine["artifact_ref"], allow_json_parse=True)
            if machine_payload is not None:
                actual = sha256_bytes(canonical_json_bytes(machine_payload))
                if machine.get("state_machine_sha256") != actual:
                    self.result.error(where, f"state_machine_sha256 mismatch expected artifact digest {actual}")
        states = machine.get("states") if isinstance(machine.get("states"), list) else []
        transitions = machine.get("transitions") if isinstance(machine.get("transitions"), list) else []
        if len(transitions) < int(contract.get("min_transitions", 1)):
            self.result.error(where, "transitions must be non-empty")
        state_ids = {state.get("state_id") for state in states if isinstance(state, dict)}
        terminal_kinds = set(contract.get("terminal_state_kinds", []))
        unknown_state_names = {u.get("state") for u in as_list(unknowns) if isinstance(u, dict)}
        has_success = False
        has_unknown_terminal = False
        for state in states:
            if not isinstance(state, dict):
                self.result.error(where, "state must be object")
                continue
            state_id = state.get("state_id")
            for field_name in contract.get("state_required_fields", []):
                if field_name not in state:
                    self.result.error(f"{where}:{state_id}", f"state missing {field_name}")
            kind = state.get("kind")
            if kind in terminal_kinds and kind == "success_verified":
                has_success = True
            if kind == "unknown_terminal_attempt":
                has_unknown_terminal = True
                if state.get("name") not in unknown_state_names and state_id not in unknown_state_names:
                    self.result.error(f"{where}:{state_id}", "unknown terminal state lacks matching unknown record")
            self._validate_id_array(dossier_id, f"{where}:{state_id}:claim_ids", state.get("claim_ids"), CLAIM_RE, self.referenced_claims, allow_empty=(kind != "success_verified"))
            self._validate_id_array(dossier_id, f"{where}:{state_id}:evidence_bundle_ids", state.get("evidence_bundle_ids"), EVB_RE, self.referenced_evidence, allow_empty=(kind != "success_verified"))
        for transition in transitions:
            if not isinstance(transition, dict):
                self.result.error(where, "transition must be object")
                continue
            transition_id = transition.get("transition_id")
            tw = f"{where}:{transition_id}"
            for field_name in contract.get("transition_required_fields", []):
                if field_name not in transition:
                    self.result.error(tw, f"transition missing {field_name}")
            if transition.get("from_state_id") not in state_ids or transition.get("to_state_id") not in state_ids:
                self.result.error(tw, "transition endpoints must resolve to states")
            self._validate_id_array(dossier_id, tw + ":claim_ids", transition.get("claim_ids"), CLAIM_RE, self.referenced_claims, allow_empty=True)
            self._validate_id_array(dossier_id, tw + ":evidence_bundle_ids", transition.get("evidence_bundle_ids"), EVB_RE, self.referenced_evidence, allow_empty=True)
            self._validate_id_array(dossier_id, tw + ":specification_ids", transition.get("specification_ids"), SPEC_RE, self.referenced_specs, allow_empty=True)
        if status == "verified" and not has_success:
            self.result.error(where, "verified dossier requires a success_verified state path")
        if status == "verified" and has_unknown_terminal:
            self.result.error(where, "verified dossier cannot retain unknown_terminal_attempt states")

    def _validate_evidence_index(self, dossier_id: str, evidence_index: Any) -> None:
        where = f"{dossier_id}/evidence_index"
        if not isinstance(evidence_index, dict):
            self.result.error(where, "must be object")
            return
        required = self.contract.get("required_field_contracts", {}).get("evidence_index", {}).get("required_fields", [])
        for field_name in required:
            if field_name not in evidence_index:
                self.result.error(where, f"missing {field_name}")
        self._validate_id_array(dossier_id, where + ":bundle_ids", evidence_index.get("bundle_ids"), EVB_RE, self.referenced_evidence)
        self._validate_id_array(dossier_id, where + ":claim_ids", evidence_index.get("claim_ids"), CLAIM_RE, self.referenced_claims)
        for ref in as_list(evidence_index.get("attachment_refs")):
            if not isinstance(ref, dict):
                self.result.error(where, "attachment_ref must be object")
                continue
            for field_name in self.contract.get("required_field_contracts", {}).get("evidence_index", {}).get("attachment_ref_fields", []):
                if field_name not in ref:
                    self.result.error(where, f"attachment_ref missing {field_name}")
            self._validate_artifact_ref(where + ":attachment_ref", ref)
            if ref.get("source_variant") not in SOURCE_VARIANTS:
                self.result.error(where, "attachment_ref source_variant invalid")
            if ref.get("local_only") is not True:
                self.result.error(where, "attachment_ref local_only must be true for proprietary evidence")
        for bundle in as_list(evidence_index.get("bundle_manifests")):
            if isinstance(bundle, dict):
                self._validate_artifact_ref(where + f":bundle:{bundle.get('evidence_bundle_id', bundle.get('bundle_id', ''))}", bundle, allow_json_parse=True)

    def _validate_unknowns(self, dossier_id: str, status: Any, unknowns: Any) -> None:
        where = f"{dossier_id}/unknowns"
        if not isinstance(unknowns, list):
            self.result.error(where, "must be list")
            return
        allowed = set(self.contract.get("required_field_contracts", {}).get("unknowns", {}).get("allowed_terminal_attempt_states", []))
        required = self.contract.get("required_field_contracts", {}).get("unknowns", {}).get("required_fields", [])
        for unknown in unknowns:
            if not isinstance(unknown, dict):
                self.result.error(where, "unknown record must be object")
                continue
            unknown_id = unknown.get("unknown_id")
            uw = f"{where}:{unknown_id}"
            for field_name in required:
                if field_name not in unknown:
                    self.result.error(uw, f"missing {field_name}")
            if not isinstance(unknown_id, str) or not UNKNOWN_RE.match(unknown_id) or f"UNK-G003-{dossier_id}-" not in unknown_id:
                self.result.error(uw, "invalid unknown_id")
            if unknown.get("state") not in allowed:
                self.result.error(uw, f"unknown state {unknown.get('state')!r} not allowed")
            if not isinstance(unknown.get("next_discriminating_experiment"), dict) or not unknown["next_discriminating_experiment"].get("experiment_id"):
                self.result.error(uw, "requires concrete next_discriminating_experiment")
            if unknown.get("closure_effect") not in {"nonterminal", "blocked"}:
                self.result.error(uw, "closure_effect must be nonterminal or blocked")
            self._validate_id_array(dossier_id, uw + ":attempted_evidence_bundle_ids", unknown.get("attempted_evidence_bundle_ids"), EVB_RE, self.referenced_evidence, allow_empty=True)
        if status == "verified" and unknowns:
            self.result.error(where, "verified dossier cannot contain unresolved unknown records")

    def _validate_contradictions(self, dossier_id: str, contradictions: Any, status: Any) -> None:
        where = f"{dossier_id}/unresolved_contradictions"
        if not isinstance(contradictions, dict):
            self.result.error(where, "must be object")
            return
        if contradictions.get("count") != 0:
            self.result.error(where, "count must be exactly 0")
        if contradictions.get("contradiction_ids") != []:
            self.result.error(where, "contradiction_ids must be empty")

    def _validate_contracts(self, dossier_id: str, contracts: Any) -> None:
        where = f"{dossier_id}/source_independent_contracts"
        if not isinstance(contracts, list) or not contracts:
            self.result.error(where, "must be non-empty list")
            return
        required = self.contract.get("required_field_contracts", {}).get("source_independent_contracts", {}).get("required_fields", [])
        forbidden = ("smali", "disassembly", "decompiler", "pseudocode", "secret", "proprietary algorithm", "vendor binary")
        for contract in contracts:
            if not isinstance(contract, dict):
                self.result.error(where, "contract row must be object")
                continue
            cw = f"{where}:{contract.get('contract_id')}"
            for field_name in required:
                if field_name not in contract:
                    self.result.error(cw, f"missing {field_name}")
            blob = lower_blob(contract)
            if any(word in blob for word in forbidden):
                self.result.error(cw, "source-independent contract contains forbidden official/proprietary source terms")
            self._validate_id_array(dossier_id, cw + ":specification_ids", contract.get("specification_ids"), SPEC_RE, self.referenced_specs)
            self._validate_id_array(dossier_id, cw + ":acceptance_test_ids", contract.get("acceptance_test_ids"), RPRO_RE, self.referenced_repros)
            self._validate_id_array(dossier_id, cw + ":clean_room_review_ids", contract.get("clean_room_review_ids"), REV_RE, self.referenced_reviews)

    def _validate_reproduction_tests(self, dossier_id: str, status: Any, tests: Any) -> None:
        where = f"{dossier_id}/reproduction_tests"
        if not isinstance(tests, list) or not tests:
            self.result.error(where, "must be non-empty list")
            return
        required = self.contract.get("required_field_contracts", {}).get("reproduction_tests", {}).get("required_fields", [])
        last_required = self.contract.get("required_field_contracts", {}).get("reproduction_tests", {}).get("last_result_fields", [])
        for test in tests:
            if not isinstance(test, dict):
                self.result.error(where, "test row must be object")
                continue
            rid = test.get("reproduction_id")
            tw = f"{where}:{rid}"
            for field_name in required:
                if field_name not in test:
                    self.result.error(tw, f"missing {field_name}")
            if not isinstance(rid, str) or not RPRO_RE.match(rid) or f"RPRO-G003-{dossier_id}-" not in rid:
                self.result.error(tw, "invalid reproduction_id")
            else:
                self.referenced_repros.add(rid)
            self._validate_id_array(dossier_id, tw + ":specification_ids", test.get("specification_ids"), SPEC_RE, self.referenced_specs)
            self._validate_id_array(dossier_id, tw + ":required_evidence_bundle_ids", test.get("required_evidence_bundle_ids"), EVB_RE, self.referenced_evidence)
            if test.get("test_file"):
                try:
                    path = rel_path(self.root, test["test_file"])
                    if not path.is_file():
                        self.result.error(tw, f"test_file missing {test['test_file']}")
                    else:
                        self.result.checked_files.add(path)
                except Exception as exc:
                    self.result.error(tw, str(exc))
            last = test.get("last_result")
            if not isinstance(last, dict):
                self.result.error(tw, "last_result must be object")
                continue
            for field_name in last_required:
                if field_name not in last:
                    self.result.error(tw, f"last_result missing {field_name}")
            evb = last.get("evidence_bundle_id")
            if isinstance(evb, str):
                self.referenced_evidence.add(evb)
            if status in {"verified", "independently_reproduced"}:
                if last.get("status") != "pass" or last.get("exit_code") != 0:
                    self.result.error(tw, "approved/reproduced dossier requires passing executable result")
                if self._evidence_tier(evb) not in (REPRO_TIERS | VERIFY_TIERS):
                    self.result.error(tw, "passing reproduction result must cite E4/E5 evidence")

    def _validate_artifact_hashes(self, dossier_id: str, artifact_hashes: Any, manifest: Mapping[str, Any]) -> None:
        where = f"{dossier_id}/artifact_hashes"
        if not isinstance(artifact_hashes, list):
            self.result.error(where, "must be list")
            return
        refs: set[tuple[str, int, str]] = set()
        for i, ref in enumerate(artifact_hashes):
            if not isinstance(ref, dict):
                self.result.error(where, f"artifact_hashes[{i}] must be object")
                continue
            self._validate_artifact_ref(f"{where}[{i}]", ref)
            if isinstance(ref.get("path"), str) and isinstance(ref.get("size_bytes"), int) and isinstance(ref.get("sha256"), str):
                refs.add((ref["path"], ref["size_bytes"], ref["sha256"]))
        for section, label in (("static_graph", "static_graph"), ("state_machine", "state_machine")):
            ref = manifest.get(section, {}).get("artifact_ref") if isinstance(manifest.get(section), dict) else None
            if isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("size_bytes"), int) and isinstance(ref.get("sha256"), str):
                if (ref["path"], ref["size_bytes"], ref["sha256"]) not in refs:
                    self.result.error(where, f"missing {label} artifact_ref")

    def _validate_no_fake_celsius(self, dossier_id: str, status: Any, manifest: Mapping[str, Any]) -> None:
        where = f"{dossier_id}/no_fake_celsius_compliance"
        compliance = manifest.get("no_fake_celsius_compliance")
        if not isinstance(compliance, dict):
            self.result.error(where, "must be object")
            return
        publishes = compliance.get("publishes_celsius") is True or compliance.get("calibrated") is True
        cited = as_list(compliance.get("evidence_bundle_ids"))
        self._validate_id_array(dossier_id, where + ":evidence_bundle_ids", cited, EVB_RE, self.referenced_evidence, allow_empty=True)
        if publishes:
            if status != "verified" or not any(self._evidence_tier(evb) == "E5" for evb in cited):
                self.result.error(where, "Celsius publication/calibration requires verified status and E5 fixture/live proof")
        elif dossier_id == "D12" and status == "verified":
            # D12 can verify non-Celsius contract slices, but any manifest mentioning Celsius as complete must prove it.
            blob = lower_blob(manifest)
            if any(word in blob for word in CELSIUS_WORDS) and "publication" in blob and not any(self._evidence_tier(evb) == "E5" for evb in cited):
                self.result.error(where, "D12 Celsius publication language lacks E5 proof chain")

    def _validate_no_fake_dynamic(self, dossier_id: str, status: Any, manifest: Mapping[str, Any]) -> None:
        where = f"{dossier_id}/dynamic_claim_constraints"
        constraints = manifest.get("dynamic_claim_constraints")
        if not isinstance(constraints, dict):
            self.result.error(where, "must be object")
            return
        if constraints.get("claims_live_completion") is True and status != "verified":
            self.result.error(where, "non-verified dossier cannot claim live/dynamic completion")
        blob = lower_blob(manifest)
        if any(word in blob for word in FAKE_DYNAMIC_WORDS):
            self.result.error(where, "fake/pretend dynamic wording is forbidden")
        dynamic_language = any(word in blob for word in DYNAMIC_CLAIM_WORDS)
        if dynamic_language and status == "verified":
            all_evbs = set(as_list(manifest.get("evidence_index", {}).get("bundle_ids")))
            all_evbs |= set(as_list(manifest.get("dynamic_traces", {}).get("evidence_bundle_ids")))
            if not any(self._evidence_tier(evb) in DYNAMIC_TIERS for evb in all_evbs):
                self.result.error(where, "verified dynamic/live language requires E2/E3 evidence")

    def _validate_inv_refs(self, where: str, value: Any) -> None:
        if not is_non_empty_list(value):
            self.result.error(where, "inv_refs must be non-empty")
            return
        for ref in value:
            if not isinstance(ref, str) or not INV_RE.match(ref):
                self.result.error(where, f"invalid INV ref {ref!r}")

    def _validate_id_array(self, dossier_id: str, where: str, value: Any, pattern: re.Pattern[str], sink: set[str], *, allow_empty: bool = False) -> None:
        if value is None:
            if not allow_empty:
                self.result.error(where, "must be non-empty list")
            return
        if not isinstance(value, list):
            self.result.error(where, "must be list")
            return
        if not value and not allow_empty:
            self.result.error(where, "must be non-empty list")
        for identifier in value:
            if not isinstance(identifier, str) or not pattern.match(identifier):
                self.result.error(where, f"invalid id {identifier!r}")
                continue
            if f"-G003-{dossier_id}-" in pattern.pattern and f"-G003-{dossier_id}-" not in identifier:
                self.result.error(where, f"id {identifier} does not belong to {dossier_id}")
            sink.add(identifier)

    def _evidence_tier(self, evb_id: Any) -> str | None:
        if not isinstance(evb_id, str):
            return None
        row = self.evidence.get(evb_id)
        if not row:
            return None
        manifest = self._resolved_index_manifest(row)
        if isinstance(manifest, dict):
            return manifest.get("evidence_tier") or manifest.get("tier")
        return row.get("evidence_tier") or row.get("tier")

    def _resolved_index_manifest(self, row: Mapping[str, Any]) -> Any | None:
        if not all(key in row for key in ("path", "sha256", "size_bytes")):
            return None
        try:
            path = rel_path(self.root, row["path"])
        except Exception:
            return None
        if not path.is_file() or path.stat().st_size != row.get("size_bytes") or sha256_file(path) != row.get("sha256"):
            return None
        try:
            return load_json(path)
        except Exception:
            return None

    def _validate_claim_evidence_bundle_ids(self, where: str, value: Any) -> list[str] | None:
        if not isinstance(value, list) or not value:
            self.result.error(where, "evidence_bundle_ids must be non-empty sorted unique EVB list")
            return None
        valid_ids: list[str] = []
        for evb in value:
            if not isinstance(evb, str) or not EVB_RE.match(evb):
                self.result.error(where, f"invalid evidence_bundle_id {evb!r}")
                return None
            valid_ids.append(evb)
        if valid_ids != sorted(set(valid_ids)):
            self.result.error(where, "evidence_bundle_ids must be sorted unique")
            return None
        return valid_ids

    def _validate_cross_links_global(self) -> None:
        for claim in sorted(self.referenced_claims):
            where = f"CLM:{claim}"
            if claim not in self.claims:
                self.result.error(where, "referenced claim missing from claims/index.json")
                continue
            manifest = self._resolved_index_manifest(self.claims[claim])
            if isinstance(manifest, dict):
                if manifest.get("claim_id") != claim:
                    self.result.error(where, "claim_id mismatch")
                dossier_match = re.match(r"^CLM-G003-(D(?:0[1-9]|1[0-3]))-[A-F0-9]{16}$", claim)
                if dossier_match:
                    claim_evbs = self._validate_claim_evidence_bundle_ids(where, manifest.get("evidence_bundle_ids"))
                    expected = expected_g003_claim_id(dossier_match.group(1), manifest.get("statement"), claim_evbs)
                    if expected is None:
                        self.result.error(where, "claim cannot recompute from statement and evidence_bundle_ids")
                    elif expected != claim:
                        self.result.error(where, f"claim_id recompute mismatch expected {expected}")
                    for evb in claim_evbs or []:
                        self.referenced_evidence.add(evb)
            else:
                self.result.error(where, "claim index row hash-invalid/unparseable")
        # Evidence bundles: referenced IDs resolve after claim manifests have contributed
        # their required evidence_bundle_ids. This closes recomputed-CLM bypasses where
        # a claim cites a new/missing EVB not already present in dossier manifests.
        for evb in sorted(self.referenced_evidence):
            where = f"EVB:{evb}"
            if evb not in self.evidence:
                self.result.error(where, "referenced evidence bundle missing from evidence/index.json or scan")
                continue
            row = self.evidence[evb]
            if "path" in row:
                manifest = self._resolved_index_manifest(row)
                if not isinstance(manifest, dict):
                    self.result.error(where, "evidence bundle manifest missing/hash-invalid/unparseable")
                    continue
                if (manifest.get("evidence_bundle_id") or manifest.get("bundle_id")) != evb:
                    self.result.error(where, "evidence bundle id mismatch")
                if manifest.get("artifact_set_id") != self.artifact_set_id:
                    self.result.error(where, "artifact_set_id mismatch")
                if manifest.get("source_variant") not in SOURCE_VARIANTS:
                    self.result.error(where, "source_variant invalid")
                tier = manifest.get("evidence_tier") or manifest.get("tier")
                if tier not in {"E1", "E2", "E3", "E4", "E5"}:
                    self.result.error(where, "evidence_tier invalid")
                self._validate_evb_attachments(evb, manifest)
            else:
                self.result.error(where, "evidence index row lacks path/hash/size")
        for spec in sorted(self.referenced_specs):
            self._validate_spec(spec)
        for repro in sorted(self.referenced_repros):
            self._validate_reproduction(repro)
        for review in sorted(self.referenced_reviews):
            self._validate_review(review)
        # Ledger completeness for rows explicitly assigned to G003: all canonical rows must be owned exactly once.
        for row_id, row in sorted(self.ledger_rows.items()):
            if row.get("goal_id") == "G003" or str(row_id).startswith("ROW-G003-"):
                if row_id not in self.owned_rows:
                    self.result.error("ledger", f"canonical row {row_id} not owned by any dossier")
                dossier = row.get("dossier_id")
                if dossier in DOSSIER_IDS and self.owned_rows.get(row_id) != dossier:
                    self.result.error("ledger", f"canonical row {row_id} not owned by declared dossier {dossier}")

    def _validate_evb_attachments(self, evb: str, manifest: Mapping[str, Any]) -> None:
        attachments = manifest.get("attachments")
        where = f"EVB:{evb}"
        if not isinstance(attachments, list) or not attachments:
            self.result.error(where, "attachments must be non-empty list")
            return
        validated_paths: set[str] = set()
        for i, attachment in enumerate(attachments):
            aw = f"{where}:attachments[{i}]"
            if not isinstance(attachment, dict):
                self.result.error(aw, "attachment must be object")
                continue
            for field_name in ("path", "size_bytes", "sha256", "media_type"):
                if field_name not in attachment:
                    self.result.error(aw, f"attachment missing {field_name}")
            path_value = attachment.get("path")
            if isinstance(path_value, str):
                lower_path = path_value.lower()
                if "/dossiers/" in lower_path or lower_path.endswith("manifest.json") or lower_path.endswith("source_independent_contracts.json") or "/reviews/" in lower_path:
                    self.result.error(aw, "attachment path must be raw immutable source evidence, not dossier-local generated output")
                validated_paths.add(path_value)
            if not isinstance(attachment.get("media_type"), str) or not attachment.get("media_type"):
                self.result.error(aw, "media_type must be non-empty string")
            self._validate_artifact_ref(aw, attachment)
        normalized = manifest.get("event_stream", {}).get("normalized_attachment") if isinstance(manifest.get("event_stream"), dict) else None
        if isinstance(normalized, str) and "/" in normalized and normalized not in validated_paths:
            self.result.error(where, "event_stream.normalized_attachment must match a validated attachment path")

    def _validate_spec(self, spec: str) -> Any | None:
        where = f"SPEC:{spec}"
        manifest = self._validate_resolved_subject(spec, self.specs, "specification_id", "SPEC")
        if not isinstance(manifest, dict):
            return None
        dossier_match = re.match(r"^SPEC-G003-(D(?:0[1-9]|1[0-3]))-[A-F0-9]{12}$", spec)
        dossier_id = dossier_match.group(1) if dossier_match else ""
        for field_name in ("specification_id", "artifact_set_id", "contract_title", "claim_ids", "evidence_bundle_ids", "source_independent"):
            if field_name not in manifest:
                self.result.error(where, f"missing {field_name}")
        if manifest.get("source_independent") is not True:
            self.result.error(where, "source_independent must be true")
        claim_ids = manifest.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids:
            self.result.error(where, "claim_ids must be non-empty list")
        else:
            self._validate_id_array(dossier_id, f"{where}:claim_ids", claim_ids, CLAIM_RE, self.referenced_claims)
        evb_ids = manifest.get("evidence_bundle_ids")
        if not isinstance(evb_ids, list) or not evb_ids:
            self.result.error(where, "evidence_bundle_ids must be non-empty list")
        else:
            self._validate_id_array(dossier_id, f"{where}:evidence_bundle_ids", evb_ids, EVB_RE, self.referenced_evidence)
        expected = expected_g003_spec_id(dossier_id, manifest.get("contract_title"), claim_ids)
        if expected is None:
            self.result.error(where, "specification_id cannot recompute from contract_title and claim_ids")
        elif expected != spec:
            self.result.error(where, f"specification_id recompute mismatch expected {expected}")
        return manifest

    def _validate_reproduction(self, repro: str) -> Any | None:
        where = f"RPRO:{repro}"
        manifest = self._validate_resolved_subject(repro, self.repros, "reproduction_id", "RPRO")
        if not isinstance(manifest, dict):
            return None
        dossier_match = re.match(r"^RPRO-G003-(D(?:0[1-9]|1[0-3]))-[A-F0-9]{12}$", repro)
        dossier_id = dossier_match.group(1) if dossier_match else ""
        for field_name in ("reproduction_id", "artifact_set_id", "test_file", "test_name", "specification_ids", "required_evidence_bundle_ids", "last_result"):
            if field_name not in manifest:
                self.result.error(where, f"missing {field_name}")
        test_file = manifest.get("test_file")
        if isinstance(test_file, str) and test_file:
            try:
                path = rel_path(self.root, test_file)
                if not path.is_file():
                    self.result.error(where, f"test_file missing {test_file}")
                else:
                    self.result.checked_files.add(path)
            except Exception as exc:
                self.result.error(where, str(exc))
        test_name = manifest.get("test_name")
        if not isinstance(test_name, str) or not test_name:
            self.result.error(where, "test_name must be non-empty string")
        spec_ids = manifest.get("specification_ids")
        if not isinstance(spec_ids, list) or not spec_ids:
            self.result.error(where, "specification_ids must be non-empty list")
        else:
            self._validate_id_array(dossier_id, f"{where}:specification_ids", spec_ids, SPEC_RE, self.referenced_specs)
        req_evbs = manifest.get("required_evidence_bundle_ids")
        if not isinstance(req_evbs, list) or not req_evbs:
            self.result.error(where, "required_evidence_bundle_ids must be non-empty list")
        else:
            self._validate_id_array(dossier_id, f"{where}:required_evidence_bundle_ids", req_evbs, EVB_RE, self.referenced_evidence)
        last = manifest.get("last_result")
        if not isinstance(last, dict):
            self.result.error(where, "last_result must be object")
        else:
            status = last.get("status")
            if status not in {"pass", "fail", "not_run", "blocked", "pending_downstream"}:
                self.result.error(where, "last_result.status invalid")
            evb = last.get("evidence_bundle_id")
            if isinstance(evb, str):
                self.referenced_evidence.add(evb)
        expected = expected_g003_reproduction_id(dossier_id, test_file, test_name, spec_ids)
        if expected is None:
            self.result.error(where, "reproduction_id cannot recompute from test_file, test_name, and specification_ids")
        elif expected != repro:
            self.result.error(where, f"reproduction_id recompute mismatch expected {expected}")
        return manifest

    def _review_requirements(self, review: str) -> tuple[set[str], set[str]]:
        subjects: set[str] = set()
        evbs: set[str] = set()
        for dossier_id, manifest in self.manifests.items():
            linked = review in as_list(manifest.get("review_ids"))
            for row in as_list(manifest.get("scope_rows")):
                if isinstance(row, dict) and review in as_list(row.get("independent_review_ids")):
                    linked = True
            for contract in as_list(manifest.get("source_independent_contracts")):
                if isinstance(contract, dict) and review in as_list(contract.get("clean_room_review_ids")):
                    linked = True
            if not linked:
                continue
            subjects.add(f"DOS-G003-{dossier_id}")
            for spec in as_list(manifest.get("specification_ids")):
                if isinstance(spec, str):
                    subjects.add(spec)
            for row in as_list(manifest.get("scope_rows")):
                if not isinstance(row, dict):
                    continue
                for spec in as_list(row.get("specification_ids")):
                    if isinstance(spec, str):
                        subjects.add(spec)
                for repro in as_list(row.get("reproduction_ids")):
                    if isinstance(repro, str):
                        subjects.add(repro)
                for evb in as_list(row.get("evidence_bundle_ids")) + as_list(row.get("verification_ids")):
                    if isinstance(evb, str):
                        evbs.add(evb)
            for contract in as_list(manifest.get("source_independent_contracts")):
                if not isinstance(contract, dict):
                    continue
                for spec in as_list(contract.get("specification_ids")):
                    if isinstance(spec, str):
                        subjects.add(spec)
                for repro in as_list(contract.get("acceptance_test_ids")):
                    if isinstance(repro, str):
                        subjects.add(repro)
            for test in as_list(manifest.get("reproduction_tests")):
                if not isinstance(test, dict):
                    continue
                rid = test.get("reproduction_id")
                if isinstance(rid, str):
                    subjects.add(rid)
                for spec in as_list(test.get("specification_ids")):
                    if isinstance(spec, str):
                        subjects.add(spec)
                for evb in as_list(test.get("required_evidence_bundle_ids")):
                    if isinstance(evb, str):
                        evbs.add(evb)
                last = test.get("last_result")
                if isinstance(last, dict) and isinstance(last.get("evidence_bundle_id"), str):
                    evbs.add(last["evidence_bundle_id"])
            evidence_index = manifest.get("evidence_index")
            if isinstance(evidence_index, dict):
                for evb in as_list(evidence_index.get("bundle_ids")):
                    if isinstance(evb, str):
                        evbs.add(evb)
            for claim_id in as_list(manifest.get("evidence_index", {}).get("claim_ids") if isinstance(manifest.get("evidence_index"), dict) else []):
                row = self.claims.get(claim_id) if isinstance(claim_id, str) else None
                claim_manifest = self._resolved_index_manifest(row) if isinstance(row, dict) else None
                if isinstance(claim_manifest, dict):
                    for evb in as_list(claim_manifest.get("evidence_bundle_ids")):
                        if isinstance(evb, str):
                            evbs.add(evb)
        return subjects, evbs

    def _validate_review(self, review: str) -> Any | None:
        where = f"REV:{review}"
        manifest = self._validate_resolved_subject(review, self.reviews, "review_id", "REV")
        if not isinstance(manifest, dict):
            return None
        if manifest.get("independent_from_producers") is not True or manifest.get("verdict") not in {"pass", "approved"}:
            self.result.error(where, "review must be independent and passing")
        if review in as_list(manifest.get("subject_ids")):
            self.result.error(where, "review must not approve itself as a subject")
        if review in as_list(manifest.get("evidence_bundle_ids")):
            self.result.error(where, "review must not cite itself as evidence")
        blob_keys = {key for key in manifest if "manifest" in str(key).lower() and ("hash" in str(key).lower() or str(key).lower() == "reviewed_manifest")}
        if blob_keys:
            self.result.error(where, "review must not include reviewed_manifest or manifest-hash backlink")
        subjects = manifest.get("subject_ids")
        evbs = manifest.get("evidence_bundle_ids")
        if not isinstance(subjects, list) or not subjects:
            self.result.error(where, "subject_ids must be non-empty list")
            subjects_set: set[str] = set()
        else:
            subjects_set = set(subjects)
        if not isinstance(evbs, list) or not evbs:
            self.result.error(where, "evidence_bundle_ids must be non-empty list")
            evb_set: set[str] = set()
        else:
            evb_set = set(evbs)
        required_subjects, required_evbs = self._review_requirements(review)
        for subject in sorted(required_subjects):
            if subject not in subjects_set:
                self.result.error(where, f"review subject_ids must cover {subject}")
        if required_subjects and subjects_set != required_subjects:
            self.result.error(where, "review subject_ids must equal current DOS/SPEC/RPRO coverage")
        for evb in sorted(required_evbs):
            if evb not in evb_set:
                self.result.error(where, f"review evidence_bundle_ids must cover {evb}")
        if required_evbs and evb_set != required_evbs:
            self.result.error(where, "review evidence_bundle_ids must equal current EVB coverage")
        row = self.reviews.get(review, {})
        expected_index_subjects = sorted(set([review]) | subjects_set)
        if row.get("subject_ids") != expected_index_subjects:
            self.result.error(f"reviews/index.json:{review}", "subject_ids must match current review coverage")
        return manifest

    def _validate_resolved_subject(self, identifier: str, index: Mapping[str, Mapping[str, Any]], id_key: str, label: str) -> Any | None:
        where = f"{label}:{identifier}"
        if identifier not in index:
            self.result.error(where, f"referenced {label} missing from index")
            return None
        manifest = self._resolved_index_manifest(index[identifier])
        if not isinstance(manifest, dict):
            self.result.error(where, f"{label} index row hash-invalid/unparseable")
            return None
        if manifest.get(id_key) != identifier:
            self.result.error(where, f"{id_key} mismatch")
        if manifest.get("artifact_set_id") not in (None, self.artifact_set_id):
            self.result.error(where, "artifact_set_id mismatch")
        return manifest


def validate(root: Path = ROOT, contract_path: Path | None = None, *, check_authority: bool = True) -> ValidationResult:
    return G003DossierValidator(root, contract_path, check_authority=check_authority).validate()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate G003 dossier manifests fail-closed.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--contract", type=Path, default=None)
    parser.add_argument("--no-authority-check", action="store_true", help="skip contract authority input hash checks")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)
    result = validate(args.root, args.contract, check_authority=not args.no_authority_check)
    payload = {
        "ok": result.ok,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "errors": result.errors,
        "warnings": result.warnings,
        "checked_files": sorted(str(path) for path in result.checked_files),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("PASS" if result.ok else "FAIL")
        for error in result.errors:
            print(f"ERROR: {error}")
        for warning in result.warnings:
            print(f"WARN: {warning}")
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
