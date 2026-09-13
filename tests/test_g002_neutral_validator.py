from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.hik_whole_apk import g002_neutral_validator as validator


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/g002-neutral-normalization-contract.json"
FIXTURES = ROOT / "tests/fixtures/g002_neutral"
MANIFEST = ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/official-artifacts.json"
XAPK = Path("/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk")
VALIDATOR = ROOT / "tools/hik_whole_apk/g002_neutral_validator.py"


def _write_canonical(path: Path, value: object) -> None:
    path.write_bytes(validator.canonical_json_bytes(value) + b"\n")


def _rebind_candidate(root: Path) -> None:
    bundle_path = root / "bundle.json"
    bundle = validator.parse_json_bytes(bundle_path.read_bytes())
    for descriptor in bundle["raw_attachments"]:
        path = root / descriptor["path"]
        data = path.read_bytes()
        descriptor["sha256"] = hashlib.sha256(data).hexdigest()
        descriptor["size_bytes"] = len(data)
        descriptor["attachment_kind"] = validator.parse_json_bytes(data)["attachment_kind"]
    for name in ("inventory", "source_index", "run", "command"):
        descriptor = bundle[name]
        data = (root / descriptor["path"]).read_bytes()
        descriptor["sha256"] = hashlib.sha256(data).hexdigest()
        descriptor["size_bytes"] = len(data)
    review_path = root / bundle["review"]["path"]
    review = validator.parse_json_bytes(review_path.read_bytes())
    review["inventory_sha256"] = bundle["inventory"]["sha256"]
    review["source_index_sha256"] = bundle["source_index"]["sha256"]
    review["attachment_sha256s"] = {
        descriptor["path"]: descriptor["sha256"]
        for descriptor in bundle["raw_attachments"]
    }
    _write_canonical(review_path, review)
    review_data = review_path.read_bytes()
    bundle["review"]["sha256"] = hashlib.sha256(review_data).hexdigest()
    bundle["review"]["size_bytes"] = len(review_data)
    _write_canonical(bundle_path, bundle)


def _rebind_first_primitive(root: Path) -> None:
    path = root / "raw/xapk.json"
    document = validator.parse_json_bytes(path.read_bytes())
    primitive = document["primitives"][0]
    preimage = [
        "g002-primitive/v1",
        document["attachment_kind"],
        primitive["primitive_kind"],
        primitive["origin"],
        primitive["input_artifact_ids"],
        primitive["physical_key"],
        primitive["byte_ranges"],
        primitive["dependency_primitive_ids"],
    ]
    primitive_id = "PRM-" + hashlib.sha256(
        validator.canonical_json_bytes(preimage)
    ).hexdigest().upper()
    primitive["primitive_id"] = primitive_id
    document["decisions"][0]["primitive_id"] = primitive_id
    document["facts"][0]["dependency_primitive_ids"] = [primitive_id]
    _write_canonical(path, document)
    _rebind_candidate(root)


def _build_repair5_whole_candidate(
    root: Path,
    graph_case: str | None = None,
) -> tuple[dict[str, int], list[str]]:
    contract = validator.load_canonical_json(CONTRACT)
    official_rows = validator._load_official_manifest_rows(MANIFEST)
    artifact_id = "xapk-apk:config.in.apk"
    artifact = official_rows[artifact_id]
    bundle_id = "g002-repair5-whole-fixture"
    artifact_set_id = contract["authority"]["artifact_set_id"]

    frozen_payload = artifact_id
    frozen_id = validator.record_id("frozen_artifact", frozen_payload)
    archive_payload = {
        "configuration_kind": "apk_archive_entry",
        "container_artifact_id": artifact_id,
        "central_directory_ordinal": 0,
        "path": "AndroidManifest.xml",
        "compression_method": 0,
        "crc32": 0,
        "compressed_size_bytes": 7,
        "uncompressed_size_bytes": 7,
        "sha256": "2" * 64,
    }
    root_manifest_payload = {
        "apk_artifact_id": artifact_id,
        "attributes": [],
        "event_ordinal": 0,
        "parent_manifest_node_record_id": None,
        "qname": "manifest",
        "xpath": "axmlpath:/manifest[1]",
    }
    root_manifest_id = validator.record_id("manifest_node", root_manifest_payload)
    child_manifest_payload = {
        "apk_artifact_id": artifact_id,
        "attributes": [],
        "event_ordinal": 1,
        "parent_manifest_node_record_id": root_manifest_id,
        "qname": "application",
        "xpath": "axmlpath:/manifest[1]/application[1]",
    }
    if graph_case is None:
        payload_rows = [
            ("frozen_artifact", "frozen_artifact", frozen_payload),
            ("configuration:apk_archive_entry", "configuration", archive_payload),
            ("manifest_node", "manifest_node", root_manifest_payload),
            ("manifest_node", "manifest_node", child_manifest_payload),
        ]
        resource_envelope_source = artifact_id
        configuration_envelope_source = artifact_id
    else:
        assert graph_case in {
            "valid",
            "missing_target",
            "wrong_target_type",
            "linked_source_mismatch",
            "configuration_source_mismatch",
            "wrong_projection",
            "wrong_locator",
            "duplicate_record",
        }
        resource_payload = {
            "apk_artifact_id": artifact_id,
            "entry_id": 1,
            "entry_name": "fixture_1",
            "package_chunk_ordinal": 0,
            "package_id": 127,
            "package_name": "fixture",
            "raw_type_id": 1,
            "resource_id": "0x7f010001",
            "type_id": 1,
            "type_id_offset": 0,
            "type_name": "string",
        }
        resource_id = validator.record_id("resource", resource_payload)
        linked_id = resource_id
        if graph_case == "missing_target":
            linked_id = "INV-" + "F" * 64
        elif graph_case == "wrong_target_type":
            linked_id = frozen_id
        configuration_payload = {
            "configuration": {"bytes_hex": "04000000", "size_bytes": 4},
            "configuration_kind": "resource_configuration",
            "entry_encoding": "full",
            "entry_flags": 0,
            "entry_id": 1,
            "entry_index_ordinal": 1,
            "key_index": 1,
            "package_chunk_ordinal": 0,
            "resource_record_id": linked_id,
            "type_chunk_ordinal": 0,
            "value": {
                "data": 0,
                "data_type": 16,
                "kind": "scalar",
                "string_value": None,
            },
        }
        payload_rows = [
            ("frozen_artifact", "frozen_artifact", frozen_payload),
            ("resource", "resource", resource_payload),
            ("configuration:resource_configuration", "configuration", configuration_payload),
        ]
        if graph_case == "duplicate_record":
            payload_rows.append(("resource", "resource", copy.deepcopy(resource_payload)))
        resource_envelope_source = (
            "xapk-apk:config.fr.apk"
            if graph_case == "linked_source_mismatch"
            else artifact_id
        )
        configuration_envelope_source = (
            "xapk-apk:config.fr.apk"
            if graph_case == "configuration_source_mismatch"
            else artifact_id
        )
    archive_id = validator.record_id("configuration", archive_payload)
    records: list[dict[str, object]] = []
    for family, record_type, payload in payload_rows:
        rid = validator.record_id(record_type, payload)
        if family == "frozen_artifact":
            outer = {
                "artifact_id": artifact_id,
                "sha256": artifact["sha256"],
                "size_bytes": artifact["size_bytes"],
                "official_source": artifact["source"],
            }
            parents: list[str] = []
        elif family == "configuration:apk_archive_entry":
            outer = {
                "artifact_id": None,
                "sha256": archive_payload["sha256"],
                "size_bytes": archive_payload["uncompressed_size_bytes"],
                "official_source": None,
            }
            parents = [frozen_id]
        elif family == "resource":
            outer = {"artifact_id": None, "sha256": None, "size_bytes": None, "official_source": None}
            parents = [frozen_id]
        elif family == "configuration:resource_configuration":
            outer = {"artifact_id": None, "sha256": None, "size_bytes": None, "official_source": None}
            parents = sorted(set([frozen_id, payload["resource_record_id"]]))
        elif payload["parent_manifest_node_record_id"] is None:
            outer = {"artifact_id": None, "sha256": None, "size_bytes": None, "official_source": None}
            parents = sorted([frozen_id, archive_id])
        else:
            outer = {"artifact_id": None, "sha256": None, "size_bytes": None, "official_source": None}
            parents = sorted([frozen_id, root_manifest_id])
        source_artifact_id = artifact_id
        if family == "resource":
            source_artifact_id = resource_envelope_source
        elif family == "configuration:resource_configuration":
            source_artifact_id = configuration_envelope_source
        records.append({
            **outer,
            "classification_status": "classified",
            "dossier_id": None,
            "parent_record_ids": parents,
            "payload": payload,
            "record_id": rid,
            "record_type": record_type,
            "scope_key": validator.canonical_json_bytes(payload).decode("utf-8"),
            "source_artifact_id": source_artifact_id,
            "source_refs": [],
            "_family": family,
        })

    byte_range = {
        "artifact_id": artifact_id,
        "offset_bytes": 0,
        "size_bytes": artifact["size_bytes"],
        "sha256": artifact["sha256"],
    }
    root_preimage = [
        "g002-primitive/v1", "xapk", "artifact.bytes", "artifact",
        [artifact_id], [artifact_id], [byte_range], [],
    ]
    root_primitive_id = "PRM-" + hashlib.sha256(
        validator.canonical_json_bytes(root_preimage)
    ).hexdigest().upper()
    raw_documents = {
        path: {
            "schema_version": "g002-raw-attachment/v1",
            "attachment_kind": kind,
            "artifact_set_id": artifact_set_id,
            "input_artifact_ids": [artifact_id],
            "primitives": [],
            "decisions": [],
            "facts": [],
            "source_rows": [],
            "scope_summaries": [],
        }
        for path, kind in validator.EXPECTED_ATTACHMENT_KINDS.items()
    }
    records_by_path: dict[str, list[dict[str, object]]] = {}
    for record in records:
        path = validator.RAW_ATTACHMENT_FOR_FAMILY[record["_family"]]
        records_by_path.setdefault(path, []).append(record)
    source_index_rows: list[dict[str, object]] = []
    source_refs_by_family: dict[str, dict[str, object]] = {}
    for path, path_records in records_by_path.items():
        document = raw_documents[path]
        prepared = []
        for record in path_records:
            family = record["_family"]
            rid = record["record_id"]
            fact_id = "FCT-" + hashlib.sha256(
                validator.canonical_json_bytes(["g002-fact/v1", rid])
            ).hexdigest().upper()
            prepared.append((fact_id, family, record))
        for index, (fact_id, family, record) in enumerate(sorted(prepared)):
            rid = record["record_id"]
            if family == "frozen_artifact":
                primitive = {
                    "primitive_id": root_primitive_id,
                    "primitive_kind": "artifact.bytes",
                    "origin": "artifact",
                    "input_artifact_ids": [artifact_id],
                    "physical_key": [artifact_id],
                    "byte_ranges": [byte_range],
                    "dependency_primitive_ids": [],
                }
            else:
                primitive_kind = validator.RAW_NORMALIZED_PRIMITIVE_KIND[path]
                primitive_preimage = [
                    "g002-primitive/v1", document["attachment_kind"], primitive_kind,
                    "derived", [artifact_id], [family, rid], [], [root_primitive_id],
                ]
                primitive_id = "PRM-" + hashlib.sha256(
                    validator.canonical_json_bytes(primitive_preimage)
                ).hexdigest().upper()
                primitive = {
                    "primitive_id": primitive_id,
                    "primitive_kind": primitive_kind,
                    "origin": "derived",
                    "input_artifact_ids": [artifact_id],
                    "physical_key": [family, rid],
                    "byte_ranges": [],
                    "dependency_primitive_ids": [root_primitive_id],
                }
            primitive_id = primitive["primitive_id"]
            locator = f"{path}#/source_rows/{index}"
            source_row = {
                key: record[key]
                for key in (
                    "record_type", "scope_key", "artifact_id", "source_artifact_id",
                    "sha256", "size_bytes", "official_source",
                )
            }
            if graph_case == "wrong_projection" and family == "configuration:resource_configuration":
                source_row["source_artifact_id"] = "xapk-apk:config.fr.apk"
            source_row["source_locator"] = locator
            source_hash = hashlib.sha256(validator.canonical_json_bytes(source_row)).hexdigest()
            source_ref = {
                "attachment_path": "source-index.json",
                "bundle_id": bundle_id,
                "source_locator": locator,
                "source_record_sha256": source_hash,
            }
            record["source_refs"] = [source_ref]
            source_refs_by_family.setdefault(family, source_ref)
            document["primitives"].append(primitive)
            document["decisions"].append({
                "primitive_id": primitive_id,
                "disposition": "normalization_root",
                "fact_ids": [fact_id],
                "reason_code": None,
            })
            document["facts"].append({
                "fact_id": fact_id,
                "fact_kind": "normalized",
                "record_id": rid,
                "record_type": record["record_type"],
                "scope_key": record["scope_key"],
                "validation_code": None,
                "dependency_primitive_ids": [primitive_id],
                "source_row_index": index,
            })
            document["source_rows"].append(source_row)
            source_index_rows.append(source_row)
        family_counts: dict[str, int] = {}
        for _, family, _ in prepared:
            family_counts[family] = family_counts.get(family, 0) + 1
        document["scope_summaries"] = [
            {
                "scope": family,
                "observed_count": count,
                "included_count": count,
                "excluded_count": 0,
                "accounted_count": count,
                "normalized_record_count": count,
                "unaccounted_count": 0,
            }
            for family, count in sorted(family_counts.items())
        ]

    if graph_case == "wrong_locator":
        configuration_record = next(
            row
            for row in records
            if row["_family"] == "configuration:resource_configuration"
        )
        configuration_record["source_refs"] = [copy.deepcopy(source_refs_by_family["resource"])]

    for record in records:
        record.pop("_family")
    records.sort(key=lambda row: row["record_id"])
    family_records: dict[str, list[dict[str, object]]] = {}
    for record in records:
        family = validator._payload_variant(record)
        family_records.setdefault(family, []).append(record)
    family_counts = [
        {"family": family, "count": len(rows)}
        for family, rows in sorted(family_records.items())
    ]
    family_memberships = []
    for family, rows in sorted(family_records.items()):
        ordered = sorted(rows, key=lambda row: row["record_id"])
        family_memberships.append({
            "family": family,
            "count": len(ordered),
            "payloads_sha256": validator.canonical_digest([row["payload"] for row in ordered]),
            "record_ids_sha256": validator.canonical_digest([row["record_id"] for row in ordered]),
        })
    inventory = {
        "schema": "g002-normalized-inventory/v2",
        "scope": "whole_inventory",
        "artifact_set_id": artifact_set_id,
        "bundle_id": bundle_id,
        "generated_at": "2026-01-01T00:00:03.000000Z",
        "records": records,
        "summary": {
            "record_count": len(records),
            "family_counts": family_counts,
            "family_memberships": family_memberships,
        },
    }
    source_index = {
        "schema_version": "g002-source-index/v2",
        "bundle_id": bundle_id,
        "rows": sorted(source_index_rows, key=lambda row: row["source_locator"]),
    }
    run = {
        "schema": "g002-run/v1", "bundle_id": bundle_id,
        "operator_id": "repair5-fixture", "started_at": "2026-01-01T00:00:00.000000Z",
        "ended_at": "2026-01-01T00:00:02.000000Z", "status": "succeeded",
    }
    command = {
        "schema": "g002-command/v1", "bundle_id": bundle_id,
        "operator_id": "repair5-fixture", "argv": ["repair5-fixture"],
        "started_at": "2026-01-01T00:00:00.000000Z",
        "ended_at": "2026-01-01T00:00:01.000000Z", "exit_code": 0,
    }
    root.mkdir(parents=True)
    _write_canonical(root / "inventory.json", inventory)
    _write_canonical(root / "source-index.json", source_index)
    _write_canonical(root / "run.json", run)
    _write_canonical(root / "command.json", command)
    raw_descriptors = []
    for path, document in raw_documents.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_canonical(target, document)
        data = target.read_bytes()
        raw_descriptors.append({
            "path": path,
            "media_type": "application/json",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
            "captured_at": "2026-01-01T00:00:01.000000Z",
            "attachment_kind": document["attachment_kind"],
        })
    files = {name: (root / f"{name}.json").read_bytes() for name in ("inventory", "source-index", "run", "command")}
    review = {
        "schema": "g002-review/v1", "bundle_id": bundle_id,
        "reviewer_id": "repair5-fixture-reviewer", "reviewed_at": "2026-01-01T00:00:04.000000Z",
        "inventory_sha256": hashlib.sha256(files["inventory"]).hexdigest(),
        "source_index_sha256": hashlib.sha256(files["source-index"]).hexdigest(),
        "attachment_sha256s": {row["path"]: row["sha256"] for row in raw_descriptors},
        "status": "accepted",
    }
    _write_canonical(root / "review.json", review)

    def descriptor(name: str) -> dict[str, object]:
        data = (root / f"{name}.json").read_bytes()
        return {
            "path": f"{name}.json", "media_type": "application/json",
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
        }

    bundle = {
        "schema": "g002-candidate-bundle/v2", "candidate_scope": "whole_inventory",
        "bundle_id": bundle_id, "artifact_set_id": artifact_set_id,
        "operator_id": "repair5-fixture", "inventory": descriptor("inventory"),
        "source_index": descriptor("source-index"), "raw_attachments": raw_descriptors,
        "run": descriptor("run"), "command": descriptor("command"),
        "review": descriptor("review"),
    }
    _write_canonical(root / "bundle.json", bundle)
    return ({row["family"]: row["count"] for row in family_counts}, [artifact_id])


class G002NeutralRepair10RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    @staticmethod
    def _component_records(alias: bool = False) -> tuple[dict[str, str], dict[str, dict[str, object]], dict[str, object]]:
        base_artifact = "xapk-apk:com.hikvision.thermalGoogle.apk"
        package = "com.example"
        frozen = {
            "record_id": validator.record_id("frozen_artifact", base_artifact),
            "record_type": "frozen_artifact",
            "payload": base_artifact,
            "source_artifact_id": base_artifact,
            "parent_record_ids": [],
        }
        manifest_payload = {
            "apk_artifact_id": base_artifact,
            "attributes": [{
                "attribute_ordinal": 0,
                "data": 0,
                "data_type": 3,
                "qname": "Q{}package",
                "raw_value": package,
                "resource_id": None,
                "typed_string": package,
            }],
            "event_ordinal": 0,
            "parent_manifest_node_record_id": None,
            "qname": "Q{}manifest",
            "xpath": "axmlpath:/Q{}manifest[1]",
        }
        manifest = {
            "record_id": validator.record_id("manifest_node", manifest_payload),
            "record_type": "manifest_node",
            "payload": manifest_payload,
            "source_artifact_id": base_artifact,
            "parent_record_ids": [frozen["record_id"]],
        }
        activity_payload = {
            "direct_boot_aware": False,
            "effective_target_sdk": 35,
            "enabled": True,
            "exported": True,
            "foreground_service_type": None,
            "kind": "activity",
            "name": "com.example.TargetActivity",
            "package": package,
            "permission": None,
            "process": package,
            "target_activity": None,
        }
        activity = {
            "record_id": validator.record_id("android_component", activity_payload),
            "record_type": "android_component",
            "payload": activity_payload,
            "source_artifact_id": base_artifact,
            "parent_record_ids": [frozen["record_id"]],
        }
        kind = "activity_alias" if alias else "service"
        qname = "Q{}activity-alias" if alias else "Q{}service"
        name = "com.example.AliasActivity" if alias else "com.example.SyncService"
        decl_attrs = [{
            "attribute_ordinal": 0,
            "data": 0,
            "data_type": 3,
            "qname": "Q{http%3A%2F%2Fschemas.android.com%2Fapk%2Fres%2Fandroid}name",
            "raw_value": name,
            "resource_id": 16842755,
            "typed_string": name,
        }]
        if alias:
            decl_attrs.append({
                "attribute_ordinal": 1,
                "data": 0,
                "data_type": 3,
                "qname": "Q{http%3A%2F%2Fschemas.android.com%2Fapk%2Fres%2Fandroid}targetActivity",
                "raw_value": "com.example.TargetActivity",
                "resource_id": 16843266,
                "typed_string": "com.example.TargetActivity",
            })
        decl_payload = {
            "apk_artifact_id": base_artifact,
            "attributes": decl_attrs,
            "event_ordinal": 1,
            "parent_manifest_node_record_id": manifest["record_id"],
            "qname": qname,
            "xpath": f"axmlpath:/Q{{}}manifest[1]/Q{{}}application[1]/{qname}[1]",
        }
        declaration = {
            "record_id": validator.record_id("manifest_node", decl_payload),
            "record_type": "manifest_node",
            "payload": decl_payload,
            "source_artifact_id": base_artifact,
            "parent_record_ids": [frozen["record_id"], manifest["record_id"]],
        }
        component_payload = {
            "direct_boot_aware": False,
            "effective_target_sdk": 35,
            "enabled": True,
            "exported": True,
            "foreground_service_type": None,
            "kind": kind,
            "name": name,
            "package": package,
            "permission": None,
            "process": package,
            "target_activity": "com.example.TargetActivity" if alias else None,
        }
        component = {
            "record_id": validator.record_id("android_component", component_payload),
            "record_type": "android_component",
            "payload": component_payload,
            "source_artifact_id": base_artifact,
            "parent_record_ids": [frozen["record_id"]],
        }
        official = validator._load_official_manifest_rows(MANIFEST)[base_artifact]
        for row in (manifest, declaration, activity, component):
            row.update({
                "artifact_id": None,
                "classification_status": "classified",
                "dossier_id": None,
                "official_source": None,
                "scope_key": validator.canonical_json_bytes(row["payload"]).decode("utf-8"),
                "sha256": None,
                "size_bytes": None,
                "source_refs": [],
            })
        frozen.update({
            "artifact_id": base_artifact,
            "classification_status": "classified",
            "dossier_id": None,
            "official_source": official["source"],
            "scope_key": validator.canonical_json_bytes(frozen["payload"]).decode("utf-8"),
            "sha256": official["sha256"],
            "size_bytes": official["size_bytes"],
            "source_refs": [],
        })
        records = {row["record_id"]: row for row in (frozen, manifest, declaration, activity, component)}
        return {base_artifact: frozen["record_id"]}, records, component

    def test_android_component_nonalias_expected_parents_include_manifest_declaration(self) -> None:
        frozen, records, component = self._component_records(alias=False)
        index = validator._build_parent_lookup_indexes(records, frozen, {})
        expected = validator._expected_parent_ids(component, frozen, index, {})
        self.assertEqual(expected, sorted([frozen["xapk-apk:com.hikvision.thermalGoogle.apk"], next(rid for rid, row in records.items() if row["record_type"] == "manifest_node" and row["payload"]["qname"] == "Q{}service")]))

    def test_android_component_nonalias_rejects_missing_declaration_parent(self) -> None:
        frozen, records, component = self._component_records(alias=False)
        index = validator._build_parent_lookup_indexes(records, frozen, {})
        expected = validator._expected_parent_ids(component, frozen, index, {})
        self.assertNotEqual(component["parent_record_ids"], expected)
        self.assertIn(next(rid for rid, row in records.items() if row["record_type"] == "manifest_node" and row["payload"]["qname"] == "Q{}service"), expected)

    def test_candidate_parent_path_rejects_nonalias_missing_declaration_parent(self) -> None:
        _frozen, records, _component = self._component_records(alias=False)
        component_rows = [
            row for row in records.values()
            if row["record_type"] == "frozen_artifact" or row["record_id"] == _component["record_id"]
        ]
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_parent_equations(self.contract, component_rows, records, MANIFEST)
        self.assertEqual(caught.exception.code, "candidate_parent_set")
        self.assertEqual(caught.exception.detail, "android_component:nonalias")

    def test_candidate_parent_path_rejects_alias_missing_declaration_parent(self) -> None:
        _frozen, records, component = self._component_records(alias=True)
        declaration_id = next(rid for rid, row in records.items() if row["record_type"] == "manifest_node" and row["payload"]["qname"] == "Q{}activity-alias")
        records.pop(declaration_id)
        component_rows = [
            row for row in records.values()
            if row["record_type"] == "frozen_artifact" or row["record_id"] == component["record_id"]
        ]
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_parent_equations(self.contract, component_rows, records, MANIFEST)
        self.assertEqual(caught.exception.code, "candidate_component_declaration_parent")

    def test_candidate_parent_path_rejects_alias_missing_target_activity_parent(self) -> None:
        _frozen, records, component = self._component_records(alias=True)
        target_id = next(rid for rid, row in records.items() if row["record_type"] == "android_component" and row["payload"]["kind"] == "activity")
        records.pop(target_id)
        component_rows = [
            row for row in records.values()
            if row["record_type"] == "frozen_artifact" or row["record_id"] == component["record_id"]
        ]
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_parent_equations(self.contract, component_rows, records, MANIFEST)
        self.assertEqual(caught.exception.code, "candidate_component_target_parent")

    def test_android_component_alias_expected_parents_include_declaration_and_target_activity(self) -> None:
        frozen, records, component = self._component_records(alias=True)
        index = validator._build_parent_lookup_indexes(records, frozen, {})
        expected = validator._expected_parent_ids(component, frozen, index, {})
        declaration = next(rid for rid, row in records.items() if row["record_type"] == "manifest_node" and row["payload"]["qname"] == "Q{}activity-alias")
        target = next(rid for rid, row in records.items() if row["record_type"] == "android_component" and row["payload"]["kind"] == "activity")
        self.assertEqual(expected, sorted([frozen["xapk-apk:com.hikvision.thermalGoogle.apk"], declaration, target]))

    def test_apk_archive_entry_nested_frozen_match_contract_parity(self) -> None:
        source = "xapk-apk:com.hikvision.thermalGoogle.apk"
        nested = "extracted-dex:classes.dex"
        frozen = {
            source: validator.record_id("frozen_artifact", source),
            nested: validator.record_id("frozen_artifact", nested),
        }
        payload = {
            "configuration_kind": "apk_archive_entry",
            "container_artifact_id": source,
            "central_directory_ordinal": 8,
            "path": "classes.dex",
            "compression_method": 8,
            "crc32": 0,
            "compressed_size_bytes": 10,
            "uncompressed_size_bytes": 20,
            "sha256": "a" * 64,
        }
        record = {"record_type": "configuration", "payload": payload, "source_artifact_id": source}
        records = {rid: {"record_id": rid, "record_type": "frozen_artifact", "payload": aid} for aid, rid in frozen.items()}
        official_rows = {
            nested: {
                "artifact_id": nested,
                "kind": "dex",
                "sha256": payload["sha256"],
                "size_bytes": payload["uncompressed_size_bytes"],
                "source": {"type": "file", "path": ".omx/evidence/apk/classes.dex"},
            }
        }
        index = validator._build_parent_lookup_indexes(records, frozen, official_rows)
        self.assertEqual(validator._expected_parent_ids(record, frozen, index, official_rows), sorted(frozen.values()))

    def test_xapk_member_frozen_parent_uses_authoritative_container_path(self) -> None:
        xapk_path = "/frozen/HIKMICRO Viewer.xapk"
        frozen = {
            "official-xapk": validator.record_id("frozen_artifact", "official-xapk"),
            "xapk-apk:base.apk": validator.record_id("frozen_artifact", "xapk-apk:base.apk"),
        }
        official_rows = {
            "official-xapk": {
                "artifact_id": "official-xapk",
                "kind": "xapk_container",
                "source": {"type": "file", "path": xapk_path},
            },
            "xapk-apk:base.apk": {
                "artifact_id": "xapk-apk:base.apk",
                "kind": "apk_member",
                "source": {"type": "zip_member", "container_path": xapk_path, "member_path": "base.apk"},
            },
        }
        records = {rid: {"record_id": rid, "record_type": "frozen_artifact", "payload": aid} for aid, rid in frozen.items()}
        index = validator._build_parent_lookup_indexes(records, frozen, official_rows)
        payload = {
            "configuration_kind": "xapk_archive_entry",
            "central_directory_ordinal": 0,
            "path": "base.apk",
            "compression_method": 0,
            "crc32": 0,
            "compressed_size_bytes": 1,
            "uncompressed_size_bytes": 1,
            "sha256": "b" * 64,
        }
        record = {"record_type": "configuration", "payload": payload, "source_artifact_id": "official-xapk"}
        self.assertEqual(validator._expected_parent_ids(record, frozen, index, official_rows), sorted(frozen.values()))

    def test_android_component_declaration_parent_is_namespace_aware(self) -> None:
        frozen, records, component = self._component_records(alias=False)
        declaration = next(row for row in records.values() if row["record_type"] == "manifest_node" and row["payload"]["qname"] == "Q{}service")
        declaration["payload"]["attributes"][0]["qname"] = "Q{}name"
        index = validator._build_parent_lookup_indexes(records, frozen, {})
        with self.assertRaises(validator.ValidationError) as caught:
            validator._expected_parent_ids(component, frozen, index, {})
        self.assertEqual(caught.exception.code, "candidate_component_declaration_parent")

    def test_candidate_parent_path_accepts_apk_archive_entry_exact_nested_frozen_parent(self) -> None:
        source = "xapk-apk:com.hikvision.thermalGoogle.apk"
        nested = "extracted-dex:classes.dex"
        official_rows = validator._load_official_manifest_rows(MANIFEST)
        source_frozen = {
            "artifact_id": source,
            "classification_status": "classified",
            "dossier_id": None,
            "official_source": official_rows[source]["source"],
            "parent_record_ids": [],
            "payload": source,
            "record_id": validator.record_id("frozen_artifact", source),
            "record_type": "frozen_artifact",
            "scope_key": validator.canonical_json_bytes(source).decode("utf-8"),
            "sha256": official_rows[source]["sha256"],
            "size_bytes": official_rows[source]["size_bytes"],
            "source_artifact_id": source,
            "source_refs": [],
        }
        nested_frozen = dict(source_frozen, artifact_id=nested, official_source=official_rows[nested]["source"], payload=nested, record_id=validator.record_id("frozen_artifact", nested), scope_key=validator.canonical_json_bytes(nested).decode("utf-8"), sha256=official_rows[nested]["sha256"], size_bytes=official_rows[nested]["size_bytes"], source_artifact_id=nested)
        payload = {
            "configuration_kind": "apk_archive_entry",
            "container_artifact_id": source,
            "central_directory_ordinal": 9,
            "path": "classes.dex",
            "compression_method": 8,
            "crc32": 0,
            "compressed_size_bytes": 1,
            "uncompressed_size_bytes": official_rows[nested]["size_bytes"],
            "sha256": official_rows[nested]["sha256"],
        }
        record = {
            "artifact_id": None,
            "classification_status": "classified",
            "dossier_id": None,
            "official_source": None,
            "parent_record_ids": sorted([source_frozen["record_id"], nested_frozen["record_id"]]),
            "payload": payload,
            "record_id": validator.record_id("configuration", payload),
            "record_type": "configuration",
            "scope_key": validator.canonical_json_bytes(payload).decode("utf-8"),
            "sha256": payload["sha256"],
            "size_bytes": payload["uncompressed_size_bytes"],
            "source_artifact_id": source,
            "source_refs": [],
        }
        records = {row["record_id"]: row for row in (source_frozen, nested_frozen, record)}
        validator.validate_candidate_parent_equations(self.contract, list(records.values()), records, MANIFEST)

    def test_parent_lookup_is_indexed_without_full_list_scans(self) -> None:
        source = "extracted-dex:classes.dex"
        class_payload = {"access_flags": [], "class_idx": 1, "descriptor": "Lx/C;", "dex_artifact_id": source, "source_file": None, "superclass_descriptor": None}
        method_payload = {"class_descriptor": "Lx/C;", "definitions": [{"access_flags": [], "descriptor": "()V", "method_idx": 1}], "dex_artifact_id": source, "method_name": "m"}
        frozen = {source: validator.record_id("frozen_artifact", source)}
        class_record = {"record_id": validator.record_id("class", class_payload), "record_type": "class", "payload": class_payload, "source_artifact_id": source}
        method_record = {"record_id": validator.record_id("method_family", method_payload), "record_type": "method_family", "payload": method_payload, "source_artifact_id": source}
        records = {frozen[source]: {"record_id": frozen[source], "record_type": "frozen_artifact", "payload": source}, class_record["record_id"]: class_record, method_record["record_id"]: method_record}
        class NoValues(dict):
            def values(self):  # type: ignore[override]
                raise AssertionError("per-record full values() scan")
        index = validator._build_parent_lookup_indexes(records, frozen, {})
        no_scan_index = validator.CandidateParentIndex(NoValues(records), index.class_by_declaration, index.method_by_declaration, index.manifest_archive_by_apk, index.xapk_member_frozen_by_path, index.apk_entry_nested_frozen_by_occurrence, index.android_declarations_by_key, index.android_components_by_key)
        self.assertEqual(validator._expected_parent_ids(method_record, frozen, no_scan_index, {}), sorted([frozen[source], class_record["record_id"]]))

    def test_matrix_parent_expressions_have_executable_branches_or_generic_rule(self) -> None:
        summary = validator.validate_record_derivation_consistency(self.contract)
        self.assertEqual(summary["parent_variant_count"], 26)
        matrix = {
            row["variant"]: [parent["expression"] for parent in row["parents"]]
            for row in self.contract["record_model"]["source_parent_byte_matrix"]
        }
        implemented = {
            variant: [item["expression"] for item in rules]
            for variant, rules in validator.PARENT_RULE_IMPLEMENTATION_REGISTRY.items()
        }
        self.assertEqual(implemented, matrix)

    def test_parent_rule_registry_rejects_missing_extra_and_misrouted_expression(self) -> None:
        base = validator.PARENT_RULE_IMPLEMENTATION_REGISTRY
        cases = []
        missing = dict(base)
        missing["android_component:nonalias"] = tuple(
            row for row in missing["android_component:nonalias"]
            if row["expression"] != "manifest_node:all_merge_key_declarations"
        )
        cases.append(("missing", missing))
        extra = dict(base)
        extra["resource"] = extra["resource"] + ({"expression": "manifest_node:all_merge_key_declarations", "handler": "wrong_extra"},)
        cases.append(("extra", extra))
        misrouted = dict(base)
        misrouted["android_component:alias"] = (
            {"expression": "frozen:canonical_base_member", "handler": "source_frozen_seed"},
            {"expression": "android_component:resolved_target_activity", "handler": "android_target_activity_index"},
            {"expression": "manifest_node:all_merge_key_declarations", "handler": "android_declaration_index"},
        )
        cases.append(("misrouted", misrouted))
        for name, registry in cases:
            with self.subTest(name=name), mock.patch.object(validator, "PARENT_RULE_IMPLEMENTATION_REGISTRY", registry):
                with self.assertRaises(validator.ValidationError) as caught:
                    validator.validate_record_derivation_consistency(self.contract)
                self.assertEqual(caught.exception.code, "contract_parent_implementation")


class G002NeutralRepair8RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    @staticmethod
    def _graph_records(root: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
        inventory = validator.load_canonical_json(root / "inventory.json")
        records = inventory["records"]
        frozen = next(row for row in records if row["record_type"] == "frozen_artifact")
        resource = next(row for row in records if row["record_type"] == "resource")
        configuration = next(
            row
            for row in records
            if validator._record_variant(row) == "configuration:resource_configuration"
        )
        return frozen, resource, configuration

    def test_accepted_v8_direct_source_fields_are_unsatisfiable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-repair8-old-source-", dir="/tmp") as temp:
            root = Path(temp) / "candidate"
            _build_repair5_whole_candidate(root, graph_case="valid")
            _frozen, resource, configuration = self._graph_records(root)
            payload = configuration["payload"]
            for field in ("apk_artifact_id", "container_artifact_id", "library_artifact_id"):
                self.assertNotIn(field, payload)
            legacy_source = (
                payload.get("apk_artifact_id")
                or payload.get("container_artifact_id")
                or payload.get("library_artifact_id")
            )
            self.assertIsNone(legacy_source)
            self.assertEqual(
                configuration["source_artifact_id"],
                resource["payload"]["apk_artifact_id"],
            )
            self.assertNotEqual(configuration["source_artifact_id"], legacy_source)

    def test_direct_candidate_graph_source_and_parents_validate_out_of_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-repair8-graph-positive-", dir="/tmp") as temp:
            root = Path(temp) / "candidate"
            _build_repair5_whole_candidate(root, graph_case="valid")
            frozen, resource, configuration = self._graph_records(root)
            inventory = validator.load_canonical_json(root / "inventory.json")
            self.assertLess(
                inventory["records"].index(configuration),
                inventory["records"].index(resource),
            )
            self.assertEqual(
                configuration["parent_record_ids"],
                sorted([frozen["record_id"], resource["record_id"]]),
            )
            summary = validator.validate_candidate_bundle_components(
                self.contract,
                root,
                MANIFEST,
            )
            self.assertEqual(summary["records"], 3)
            self.assertEqual(summary["source_rows"], 3)

    def test_graph_source_hostiles_reject_with_typed_failures(self) -> None:
        cases = {
            "missing_target": "candidate_linked_resource_missing",
            "wrong_target_type": "candidate_linked_resource_type",
            "linked_source_mismatch": "candidate_linked_resource_source",
            "configuration_source_mismatch": "candidate_source_rule",
            "wrong_projection": "candidate_source_row_fact_binding",
            "wrong_locator": "candidate_source_projection",
            "duplicate_record": "candidate_duplicate_record_id",
        }
        with tempfile.TemporaryDirectory(prefix="g002-repair8-graph-hostile-", dir="/tmp") as temp:
            for case, expected_code in cases.items():
                root = Path(temp) / case
                _build_repair5_whole_candidate(root, graph_case=case)
                with self.subTest(case=case), self.assertRaises(validator.ValidationError) as caught:
                    validator.validate_candidate_bundle_components(self.contract, root, MANIFEST)
                self.assertEqual(caught.exception.code, expected_code)
                if case == "configuration_source_mismatch":
                    self.assertEqual(caught.exception.detail, "configuration:resource_configuration")

    def test_malformed_linked_resource_payload_rejects_before_graph_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-repair8-malformed-graph-", dir="/tmp") as temp:
            root = Path(temp) / "candidate"
            _build_repair5_whole_candidate(root, graph_case="valid")
            inventory_path = root / "inventory.json"
            inventory = validator.load_canonical_json(inventory_path)
            resource = next(row for row in inventory["records"] if row["record_type"] == "resource")
            resource["payload"].pop("apk_artifact_id")
            _write_canonical(inventory_path, inventory)
            _rebind_candidate(root)
            with self.assertRaises(validator.ValidationError) as caught:
                validator.validate_candidate_bundle_components(self.contract, root, MANIFEST)
            self.assertEqual(caught.exception.code, "candidate_schema")

    def test_every_record_variant_has_executable_source_and_parent_derivation(self) -> None:
        summary = validator.validate_record_derivation_consistency(self.contract)
        self.assertEqual(
            summary,
            {
                "graph_linked_variant_count": 1,
                "parent_variant_count": 26,
                "record_variant_count": 26,
                "root_source_variant_count": 1,
            },
        )

    def test_official_replay_cannot_bypass_linked_resource_derivation(self) -> None:
        payload_schema = self.contract["record_model"]["payload_schemas"][
            "configuration:resource_configuration"
        ]["payload"]
        with tempfile.TemporaryDirectory(prefix="g002-repair8-linked-replay-", dir="/tmp") as temp:
            root = Path(temp) / "candidate"
            _build_repair5_whole_candidate(root, graph_case="valid")
            _frozen, _resource, configuration = self._graph_records(root)
            validator.validate_schema_value(
                configuration["payload"],
                payload_schema,
                self.contract["record_model"]["definitions"],
                "configuration:resource_configuration",
            )
            with self.assertRaises(validator.ValidationError) as caught:
                validator._official_payload_source(
                    "configuration:resource_configuration",
                    configuration["payload"],
                )
            self.assertEqual(
                caught.exception.code,
                "official_raw_obligation_linked_source",
            )

    def test_derivation_audit_rejects_impossible_graph_contracts(self) -> None:
        mutations: list[tuple[str, dict[str, object], str]] = []

        stale_source = copy.deepcopy(self.contract)
        row = next(
            item
            for item in stale_source["record_model"]["source_parent_byte_matrix"]
            if item["variant"] == "configuration:resource_configuration"
        )
        row["source"]["expression"] = "containing_canonical_apk_member"
        mutations.append(("stale_source", stale_source, "contract_source_derivation"))

        missing_parent = copy.deepcopy(self.contract)
        row = next(
            item
            for item in missing_parent["record_model"]["source_parent_byte_matrix"]
            if item["variant"] == "configuration:resource_configuration"
        )
        row["parents"] = [
            parent
            for parent in row["parents"]
            if parent["expression"] != "resource:referenced"
        ]
        mutations.append(("missing_parent", missing_parent, "contract_parent_implementation"))

        missing_link_field = copy.deepcopy(self.contract)
        schema = missing_link_field["record_model"]["payload_schemas"][
            "configuration:resource_configuration"
        ]["payload"]
        schema["properties"].pop("resource_record_id")
        schema["required"].remove("resource_record_id")
        mutations.append(("missing_link_field", missing_link_field, "contract_source_derivation"))

        missing_target_source = copy.deepcopy(self.contract)
        schema = missing_target_source["record_model"]["payload_schemas"]["resource"]["payload"]
        schema["properties"].pop("apk_artifact_id")
        schema["required"].remove("apk_artifact_id")
        mutations.append(("missing_target_source", missing_target_source, "contract_source_derivation"))

        for name, mutated, expected_code in mutations:
            with self.subTest(name=name), self.assertRaises(validator.ValidationError) as caught:
                validator.validate_record_derivation_consistency(mutated)
            self.assertEqual(caught.exception.code, expected_code)

    def test_previous_contract_schema_rejects_after_v9(self) -> None:
        self.assertEqual(
            self.contract["schema"],
            "g002-neutral-normalization-contract/v10",
        )
        stale = copy.deepcopy(self.contract)
        stale["schema"] = stale["schema"].rsplit("/", 1)[0] + "/v" + str(9)
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(stale)
        self.assertEqual(caught.exception.code, "contract_schema")


class G002NeutralRepair7RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    @staticmethod
    def _payload() -> dict[str, object]:
        return {
            "api": {
                "class_descriptor": "Ljava/lang/Class;",
                "descriptor": "(Ljava/lang/String;)Ljava/lang/Class;",
                "method_name": "forName",
            },
            "caller": {
                "class_descriptor": "Lfixture/Caller;",
                "descriptor": "()V",
                "dex_artifact_id": "extracted-dex:classes.dex",
                "method_name": "load",
            },
            "instruction_offset_code_units": 0,
            "target": {"unresolved_token": "not_statically_resolved"},
        }

    @classmethod
    def _record(cls, record_type: str) -> dict[str, object]:
        payload = cls._payload()
        return {
            "artifact_id": None,
            "classification_status": "classified",
            "dossier_id": None,
            "official_source": None,
            "parent_record_ids": [],
            "payload": payload,
            "record_id": validator.record_id(record_type, payload),
            "record_type": record_type,
            "scope_key": validator.canonical_json_bytes(payload).decode("utf-8"),
            "sha256": None,
            "size_bytes": None,
            "source_artifact_id": "extracted-dex:classes.dex",
            "source_refs": [],
        }

    @staticmethod
    def _inventory(record: dict[str, object]) -> dict[str, object]:
        return {
            "artifact_set_id": "hikmicro-viewer-2.6.0-019801077bb42ffb",
            "bundle_id": "g002-repair7-dispatch",
            "generated_at": "2026-01-01T00:00:03.000000Z",
            "records": [record],
            "schema": "g002-normalized-inventory/v2",
            "scope": "whole_inventory",
            "summary": {
                "family_counts": [],
                "family_memberships": [],
                "record_count": 1,
            },
        }

    def _assert_old_generic_union_matches_two(self, record_type: str) -> None:
        definitions = self.contract["record_model"]["definitions"]
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_schema_value(
                self._record(record_type),
                definitions["normalized_record"],
                definitions,
                f"repair7.{record_type}",
            )
        self.assertEqual(caught.exception.code, "candidate_union")
        self.assertEqual(
            caught.exception.detail,
            f"repair7.{record_type}.payload:matches=2",
        )

    def test_old_generic_union_reproduces_reflection_target_matches_two(self) -> None:
        self._assert_old_generic_union_matches_two("reflection_target")

    def test_old_generic_union_reproduces_dynamic_loader_matches_two(self) -> None:
        self._assert_old_generic_union_matches_two("dynamic_loader")

    def _assert_direct_candidate_dispatch(self, record_type: str) -> None:
        model = self.contract["record_model"]
        declared_schema = model["payload_schemas"][record_type]["payload"]
        opposite = (
            "dynamic_loader" if record_type == "reflection_target" else "reflection_target"
        )
        opposite_schema = model["payload_schemas"][opposite]["payload"]
        seen: list[str] = []
        original = validator.validate_schema_value

        def capture(
            value: object,
            schema: object,
            definitions: object,
            context: str,
        ) -> None:
            if schema is declared_schema:
                seen.append(record_type)
            if schema is opposite_schema:
                seen.append(opposite)
            original(value, schema, definitions, context)

        with mock.patch.object(validator, "validate_schema_value", side_effect=capture):
            variants = validator.validate_candidate_inventory_schema(
                self.contract,
                self._inventory(self._record(record_type)),
            )
        self.assertEqual(variants, [record_type])
        self.assertEqual(seen, [record_type])

    def test_direct_candidate_path_dispatches_reflection_target_once(self) -> None:
        self._assert_direct_candidate_dispatch("reflection_target")

    def test_direct_candidate_path_dispatches_dynamic_loader_once(self) -> None:
        self._assert_direct_candidate_dispatch("dynamic_loader")

    def test_contract_declares_record_type_discriminator(self) -> None:
        dispatch = self.contract["record_model"]["record_type_dispatch"]
        self.assertEqual(
            self.contract["schema"],
            "g002-neutral-normalization-contract/v10",
        )
        self.assertEqual(dispatch["discriminator"], "record_type")
        self.assertEqual(dispatch["payload_member"], "payload")
        self.assertEqual(dispatch["pre_dispatch_union"], "forbidden")
        self.assertEqual(dispatch["record_families"]["reflection_target"], ["reflection_target"])
        self.assertEqual(dispatch["record_families"]["dynamic_loader"], ["dynamic_loader"])

    def test_previous_contract_schema_rejects(self) -> None:
        stale = copy.deepcopy(self.contract)
        stale["schema"] = stale["schema"].rsplit("/", 1)[0] + "/v" + str(7)
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(stale)
        self.assertEqual(caught.exception.code, "contract_schema")

    def test_unknown_record_type_rejects(self) -> None:
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_record_schema(
                self.contract, self._record("unknown_family"), 0
            )
        self.assertEqual(caught.exception.code, "candidate_payload_variant")

    def test_malformed_outer_record_rejects(self) -> None:
        record = self._record("reflection_target")
        record.pop("source_refs")
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_record_schema(self.contract, record, 0)
        self.assertEqual(caught.exception.code, "candidate_record")

    def test_wrong_family_payload_rejects(self) -> None:
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_record_schema(
                self.contract, self._record("resource"), 0
            )
        self.assertEqual(caught.exception.code, "candidate_schema")

    def test_genuine_payload_union_ambiguity_outside_dispatch_rejects(self) -> None:
        definitions = self.contract["record_model"]["definitions"]
        schema = {
            "type": "union",
            "variants": ["payload_reflection_target", "payload_dynamic_loader"],
        }
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_schema_value(
                self._payload(), schema, definitions, "repair7.generic_union"
            )
        self.assertEqual(caught.exception.code, "candidate_union")
        self.assertEqual(
            caught.exception.detail,
            "repair7.generic_union:matches=2",
        )


class G002NeutralRepair6RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    def test_orphan_java_export_parent_equation_uses_endpoint_library_once(self) -> None:
        library_artifact_id = "extracted-native:arm64-v8a/libfixture.so"
        frozen_id = validator.record_id("frozen_artifact", library_artifact_id)
        symbol_payload = {
            "binding": "STB_GLOBAL",
            "dynamic_symbol_index": 1,
            "library_artifact_id": library_artifact_id,
            "name": "Java_pkg_Fixture_nativeCall",
            "section_index": 1,
            "size_bytes": 16,
            "symbol_type": "STT_FUNC",
            "value": 4096,
            "version": None,
            "visibility": "STV_DEFAULT",
        }
        symbol_id = validator.record_id("native_symbol", symbol_payload)
        export_payload = {
            "dynamic_symbol_index": 1,
            "export_kind": "java_export",
            "library_artifact_id": library_artifact_id,
            "name": "Java_pkg_Fixture_nativeCall",
            "native_symbol_record_id": symbol_id,
            "version": None,
            "virtual_address": 4096,
        }
        export_id = validator.record_id("native_export", export_payload)
        orphan_payload = {
            "binding_form": "orphan_java_export",
            "java_declaration": {"unresolved_token": "no_matching_dex_native_declaration"},
            "native_endpoint": {
                "endpoint_kind": "java_export",
                "library_artifact_id": library_artifact_id,
                "name": "Java_pkg_Fixture_nativeCall",
                "native_export_record_id": export_id,
                "native_symbol_record_id": symbol_id,
                "version": None,
                "virtual_address": 4096,
            },
            "registration_site": None,
            "resolution_status": "orphan",
        }
        orphan_record = {
            "artifact_id": None,
            "classification_status": "classified",
            "dossier_id": None,
            "official_source": None,
            "parent_record_ids": [],
            "payload": orphan_payload,
            "record_id": validator.record_id("jni_edge", orphan_payload),
            "record_type": "jni_edge",
            "scope_key": validator.canonical_json_bytes(orphan_payload).decode("utf-8"),
            "sha256": None,
            "size_bytes": None,
            "source_artifact_id": library_artifact_id,
            "source_refs": [],
        }
        records_by_id = {
            frozen_id: {"record_id": frozen_id, "record_type": "frozen_artifact", "payload": library_artifact_id},
            symbol_id: {"record_id": symbol_id, "record_type": "native_symbol", "payload": symbol_payload},
            export_id: {"record_id": export_id, "record_type": "native_export", "payload": export_payload},
            orphan_record["record_id"]: orphan_record,
        }

        self.assertEqual(
            validator.validate_candidate_record_schema(self.contract, orphan_record, 0),
            "jni_edge:orphan_java_export",
        )
        expected = sorted([frozen_id, export_id])
        frozen = {library_artifact_id: frozen_id}
        parent_index = validator._build_parent_lookup_indexes(records_by_id, frozen, {})
        self.assertEqual(
            validator._expected_parent_ids(orphan_record, frozen, parent_index, {}),
            expected,
        )

    def test_duplicate_distinct_parent_rules_still_reject(self) -> None:
        duplicate_case = {
            "operation": "source_parent",
            "input": {
                "source_artifact_id": "A",
                "payload_source": "A",
                "parents": ["P", "P"],
                "expected_parents": ["P"],
            },
        }
        self.assertEqual(
            validator._fixture_disposition(duplicate_case, self.contract, FIXTURES),
            ("reject", "parent_duplicate"),
        )


class G002NeutralRepair5RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    def test_manifest_node_closed_schema_survives_variant_selection(self) -> None:
        payload_schema = self.contract["record_model"]["payload_schemas"]["manifest_node"]["payload"]
        payload = {
            "apk_artifact_id": "fixture-apk",
            "attributes": [],
            "event_ordinal": 0,
            "qname": "manifest",
            "xpath": "/manifest",
        }
        if "parent_manifest_node_record_id" in payload_schema["properties"]:
            payload["parent_manifest_node_record_id"] = None
        validator.validate_schema_value(
            payload,
            payload_schema,
            self.contract["record_model"]["definitions"],
            "repair5.manifest_node",
        )
        record = {"record_type": "manifest_node", "payload": payload}
        self.assertEqual(validator._record_variant(record), "manifest_node:root")

    def test_official_fact_rows_use_fact_id_order_for_source_indices(self) -> None:
        artifacts = [
            {
                "artifact_id": artifact_id,
                "sha256": digit * 64,
                "size_bytes": index + 1,
                "source": {"type": "file", "path": f"/fixture/{artifact_id}"},
            }
            for index, (artifact_id, digit) in enumerate(
                (("fixture-artifact-0", "0"), ("fixture-artifact-1", "1"))
            )
        ]
        captured: dict[str, object] = {}
        original = validator.raw_membership_oracle

        def capture(documents: object, byte_ranges: object = ()) -> object:
            captured["documents"] = copy.deepcopy(documents)
            return original(documents, byte_ranges)

        with mock.patch.object(validator, "raw_membership_oracle", side_effect=capture):
            validator.build_official_raw_obligation_oracle(
                self.contract,
                {
                    "frozen_artifact": [row["artifact_id"] for row in artifacts],
                    "resource": [],
                },
                artifacts,
                {},
                {},
            )

        documents = captured["documents"]
        self.assertIsInstance(documents, dict)
        xapk = documents["raw/xapk.json"]
        facts = [row for row in xapk["facts"] if row["fact_kind"] == "normalized"]
        identities = [
            (
                validator.record_id("frozen_artifact", row["artifact_id"]),
                "FCT-" + hashlib.sha256(
                    validator.canonical_json_bytes([
                        "g002-fact/v1",
                        validator.record_id("frozen_artifact", row["artifact_id"]),
                    ])
                ).hexdigest().upper(),
            )
            for row in artifacts
        ]
        record_id_order = [rid for rid, _ in sorted(identities)]
        fact_id_order = [rid for rid, _ in sorted(identities, key=lambda row: row[1])]
        self.assertNotEqual(record_id_order, fact_id_order)
        self.assertEqual([row["record_id"] for row in facts], fact_id_order)
        self.assertEqual(facts, sorted(facts, key=lambda row: row["fact_id"]))
        self.assertEqual(
            [row["source_row_index"] for row in facts],
            list(range(len(xapk["source_rows"]))),
        )
        self.assertEqual(
            [row["source_locator"] for row in xapk["source_rows"]],
            [f"raw/xapk.json#/source_rows/{index}" for index in range(len(facts))],
        )

    def test_manifest_and_fact_order_whole_candidate_positive_and_hostile_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-repair5-whole-", dir="/tmp") as temp:
            base = Path(temp) / "candidate"
            expected_counts, artifact_ids = _build_repair5_whole_candidate(base)
            private_fixtures = Path(temp) / "fixtures"
            shutil.copytree(FIXTURES, private_fixtures, ignore=shutil.ignore_patterns("__pycache__"))
            component = validator.validate_candidate_bundle_components(self.contract, base, MANIFEST)
            official_summary = {
                "candidate_family_memberships": component["family_memberships"],
                "raw_obligations": component["raw_obligations"],
            }
            official_rows = validator._load_official_manifest_rows(MANIFEST)
            subset = {artifact_id: official_rows[artifact_id] for artifact_id in artifact_ids}
            with mock.patch.object(
                validator,
                "_expected_candidate_family_counts",
                return_value=expected_counts,
            ), mock.patch.object(
                validator,
                "_load_official_manifest_rows",
                side_effect=[subset],
            ):
                result = validator.validate_candidate_bundle(
                    self.contract, base, MANIFEST, official_summary, component
                )
            self.assertEqual(result["records"], 4)
            self.assertEqual(result["raw_attachments"], 8)

            manifest_document = validator.load_canonical_json(base / "raw/manifests.json")
            fact_record_order = [row["record_id"] for row in manifest_document["facts"]]
            self.assertNotEqual(fact_record_order, sorted(fact_record_order))

            hostile_cases: list[tuple[str, str]] = []
            missing_parent = Path(temp) / "missing-parent"
            shutil.copytree(base, missing_parent)
            inventory_path = missing_parent / "inventory.json"
            inventory = validator.load_canonical_json(inventory_path)
            manifest_record = next(row for row in inventory["records"] if row["record_type"] == "manifest_node")
            manifest_record["payload"].pop("parent_manifest_node_record_id")
            _write_canonical(inventory_path, inventory)
            _rebind_candidate(missing_parent)
            hostile_cases.append((str(missing_parent), "candidate_schema"))

            reordered = Path(temp) / "reordered-facts"
            shutil.copytree(base, reordered)
            raw_path = reordered / "raw/manifests.json"
            raw = validator.load_canonical_json(raw_path)
            raw["facts"].reverse()
            _write_canonical(raw_path, raw)
            _rebind_candidate(reordered)
            hostile_cases.append((str(reordered), "candidate_fact_order"))

            substituted = Path(temp) / "substituted-source"
            shutil.copytree(base, substituted)
            raw_path = substituted / "raw/manifests.json"
            raw = validator.load_canonical_json(raw_path)
            raw["source_rows"][0]["scope_key"] = raw["source_rows"][1]["scope_key"]
            _write_canonical(raw_path, raw)
            _rebind_candidate(substituted)
            hostile_cases.append((str(substituted), "candidate_source_row_fact_binding"))

            for root_value, expected_code in hostile_cases:
                with self.subTest(component_code=expected_code):
                    with self.assertRaises(validator.ValidationError) as caught:
                        validator.validate_candidate_bundle_components(
                            self.contract,
                            Path(root_value),
                            MANIFEST,
                        )
                    self.assertEqual(caught.exception.code, expected_code)

            for root_value, expected_code in hostile_cases:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        (
                            "import sys; from pathlib import Path; "
                            f"sys.path.insert(0,{str(ROOT)!r}); "
                            "from tools.hik_whole_apk import g002_neutral_validator as v; "
                            "raise SystemExit(v.main(sys.argv[1:]))"
                        ),
                        "--contract", str(CONTRACT),
                        "--fixtures", str(private_fixtures),
                        "--official-manifest", str(MANIFEST),
                        "--xapk", str(XAPK),
                        "--candidate-bundle", root_value,
                        "--json",
                    ],
                    cwd=ROOT,
                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                    check=False,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                with self.subTest(code=expected_code):
                    self.assertEqual(completed.returncode, 1)
                    self.assertEqual(completed.stderr, b"")
                    self.assertNotIn(b"Traceback", completed.stdout)
                    failure = json.loads(completed.stdout)
                    failure_json = json.dumps(failure, sort_keys=True, indent=2)
                    self.assertEqual(failure["status"], "error", failure_json)
                    self.assertEqual(failure["code"], expected_code, failure_json)


class G002NeutralRepair4RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    def _candidate_copy(self, temp: str) -> Path:
        target = Path(temp) / "candidate"
        shutil.copytree(FIXTURES / "candidate_accept", target)
        return target

    def test_hash_rebound_fabricated_artifact_range_rejects_before_completeness(self) -> None:
        """Exact recheck-3 raw_grounding_probe must fail at frozen bytes."""

        with tempfile.TemporaryDirectory(prefix="g002-repair4-grounding-", dir="/tmp") as temp:
            root = self._candidate_copy(temp)
            path = root / "raw/xapk.json"
            document = validator.parse_json_bytes(path.read_bytes())
            document["primitives"][0]["byte_ranges"] = [{
                "artifact_id": "official-xapk",
                "offset_bytes": 0,
                "size_bytes": 1,
                "sha256": "0" * 64,
            }]
            _write_canonical(path, document)
            _rebind_first_primitive(root)
            with self.assertRaises(validator.ValidationError) as caught:
                validator.validate_candidate_bundle_components(self.contract, root, MANIFEST)
            self.assertEqual(caught.exception.code, "candidate_raw_byte_sha256")

    def test_count_preserving_raw_member_substitution_rejects(self) -> None:
        expected = validator.raw_membership_oracle({
            "raw/xapk.json": {
                "primitives": [{"primitive_id": "PRM-" + "A" * 64}],
                "decisions": [{"primitive_id": "PRM-" + "A" * 64}],
                "facts": [{"fact_id": "FCT-" + "A" * 64}],
                "source_rows": [{"source_locator": "raw/xapk.json#/source_rows/0"}],
                "input_artifact_ids": ["official-xapk"],
                "scope_summaries": [{"scope": "frozen_artifact", "observed_count": 1}],
            }
        })
        substituted = validator.raw_membership_oracle({
            "raw/xapk.json": {
                "primitives": [{"primitive_id": "PRM-" + "B" * 64}],
                "decisions": [{"primitive_id": "PRM-" + "B" * 64}],
                "facts": [{"fact_id": "FCT-" + "B" * 64}],
                "source_rows": [{"source_locator": "raw/xapk.json#/source_rows/0"}],
                "input_artifact_ids": ["official-xapk"],
                "scope_summaries": [{"scope": "frozen_artifact", "observed_count": 1}],
            }
        })
        self.assertEqual(expected["global"]["primitive_ids"]["count"], substituted["global"]["primitive_ids"]["count"])
        with self.assertRaises(validator.ValidationError) as caught:
            validator.compare_raw_obligation_oracles(substituted, expected)
        self.assertEqual(caught.exception.code, "candidate_official_raw_obligation")

    def test_designated_ranges_require_known_in_bounds_exact_official_bytes(self) -> None:
        with XAPK.open("rb") as stream:
            first_byte_sha256 = hashlib.sha256(stream.read(1)).hexdigest()
        mutations = [
            ("unknown", {"artifact_id": "missing-artifact", "offset_bytes": 0, "size_bytes": 1, "sha256": "0" * 64}, "candidate_raw_byte_artifact"),
            ("bounds", {"artifact_id": "official-xapk", "offset_bytes": 271805591, "size_bytes": 1, "sha256": "0" * 64}, "candidate_raw_byte_bounds"),
            ("digest", {"artifact_id": "official-xapk", "offset_bytes": 0, "size_bytes": 1, "sha256": "0" * 64}, "candidate_raw_byte_sha256"),
            ("partial", {"artifact_id": "official-xapk", "offset_bytes": 0, "size_bytes": 1, "sha256": first_byte_sha256}, "candidate_raw_byte_obligation"),
        ]
        for name, byte_range, code in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix=f"g002-repair4-{name}-", dir="/tmp") as temp:
                root = self._candidate_copy(temp)
                path = root / "raw/xapk.json"
                document = validator.parse_json_bytes(path.read_bytes())
                primitive = document["primitives"][0]
                primitive["byte_ranges"] = [byte_range]
                primitive["input_artifact_ids"] = [byte_range["artifact_id"]]
                primitive["physical_key"] = [byte_range["artifact_id"]]
                document["input_artifact_ids"] = [byte_range["artifact_id"]]
                _write_canonical(path, document)
                _rebind_first_primitive(root)
                with self.assertRaises(validator.ValidationError) as caught:
                    validator.validate_candidate_bundle_components(self.contract, root, MANIFEST)
                self.assertEqual(caught.exception.code, code)

    def test_raw_oracle_exactly_binds_every_membership_category(self) -> None:
        base = {
            "raw/xapk.json": {
                "primitives": [{"primitive_id": "PRM-" + "A" * 64}],
                "decisions": [{"primitive_id": "PRM-" + "A" * 64, "disposition": "support"}],
                "facts": [{"fact_id": "FCT-" + "A" * 64, "fact_kind": "validation"}],
                "source_rows": [{"source_locator": "raw/xapk.json#/source_rows/0", "record_type": "frozen_artifact"}],
                "input_artifact_ids": ["official-xapk"],
                "scope_summaries": [{"scope": "frozen_artifact", "observed_count": 1}],
            },
            "raw/elf.json": {
                "primitives": [{"primitive_id": "PRM-" + "C" * 64}],
                "decisions": [{"primitive_id": "PRM-" + "C" * 64, "disposition": "excluded"}],
                "facts": [],
                "source_rows": [],
                "input_artifact_ids": ["extracted-native:arm64-v8a/liba.so"],
                "scope_summaries": [{"scope": "native_symbol", "observed_count": 1}],
            },
        }
        expected = validator.raw_membership_oracle(base)
        categories = ("primitive_ids", "decisions", "facts", "source_rows", "input_artifact_ids", "scope_summaries")
        for category in categories:
            changed = copy.deepcopy(base)
            key = {
                "primitive_ids": "primitives",
                "decisions": "decisions",
                "facts": "facts",
                "source_rows": "source_rows",
                "input_artifact_ids": "input_artifact_ids",
                "scope_summaries": "scope_summaries",
            }[category]
            rows = changed["raw/xapk.json"][key]
            if category == "primitive_ids":
                rows[0]["primitive_id"] = "PRM-" + "D" * 64
            elif isinstance(rows[0], str):
                rows[0] += "-substituted"
            else:
                rows[0] = {**rows[0], "substitution": True}
            actual = validator.raw_membership_oracle(changed)
            self.assertNotEqual(actual["global"][category], expected["global"][category], category)
            with self.assertRaises(validator.ValidationError) as caught:
                validator.compare_raw_obligation_oracles(actual, expected)
            self.assertEqual(caught.exception.code, "candidate_official_raw_obligation")
        self.assertEqual(set(expected["attachments"]), set(base))


class G002NeutralRepair3RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = validator.load_canonical_json(CONTRACT)

    def _candidate_copy(self, temp: str) -> Path:
        target = Path(temp) / "candidate"
        shutil.copytree(FIXTURES / "candidate_accept", target)
        return target

    def test_public_gate_rejects_component_only_miniature_as_incomplete(self) -> None:
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_bundle(self.contract, FIXTURES / "candidate_accept", MANIFEST)
        self.assertEqual(caught.exception.code, "candidate_incomplete_record_counts")

    def test_hash_consistent_cross_family_relocation_rejects_before_completeness(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-family-relocation-", dir="/tmp") as temp:
            root = self._candidate_copy(temp)
            xapk_path = root / "raw/xapk.json"
            elf_path = root / "raw/elf.json"
            xapk = validator.parse_json_bytes(xapk_path.read_bytes())
            elf = validator.parse_json_bytes(elf_path.read_bytes())
            source_row = xapk["source_rows"][0]
            source_row["source_locator"] = "raw/elf.json#/source_rows/0"
            primitive = xapk["primitives"][0]
            preimage = [
                "g002-primitive/v1", "elf", primitive["primitive_kind"],
                primitive["origin"], primitive["input_artifact_ids"],
                primitive["physical_key"], primitive["byte_ranges"],
                primitive["dependency_primitive_ids"],
            ]
            primitive_id = "PRM-" + hashlib.sha256(validator.canonical_json_bytes(preimage)).hexdigest().upper()
            primitive["primitive_id"] = primitive_id
            xapk["decisions"][0]["primitive_id"] = primitive_id
            xapk["facts"][0]["dependency_primitive_ids"] = [primitive_id]
            for key in ("primitives", "decisions", "facts", "source_rows", "scope_summaries"):
                elf[key] = xapk[key]
                xapk[key] = []
            _write_canonical(xapk_path, xapk)
            _write_canonical(elf_path, elf)
            source_index_path = root / "source-index.json"
            source_index = validator.parse_json_bytes(source_index_path.read_bytes())
            source_index["rows"][0] = source_row
            _write_canonical(source_index_path, source_index)
            inventory_path = root / "inventory.json"
            inventory = validator.parse_json_bytes(inventory_path.read_bytes())
            ref = inventory["records"][0]["source_refs"][0]
            ref["source_locator"] = source_row["source_locator"]
            ref["source_record_sha256"] = hashlib.sha256(validator.canonical_json_bytes(source_row)).hexdigest()
            _write_canonical(inventory_path, inventory)
            _rebind_candidate(root)
            with self.assertRaises(validator.ValidationError) as caught:
                validator.validate_candidate_bundle(self.contract, root, MANIFEST)
            self.assertEqual(caught.exception.code, "candidate_attachment_family")

    def test_recursive_evidence_schema_rejects_integer_argv(self) -> None:
        with tempfile.TemporaryDirectory(prefix="g002-command-schema-", dir="/tmp") as temp:
            root = self._candidate_copy(temp)
            command_path = root / "command.json"
            command = validator.parse_json_bytes(command_path.read_bytes())
            command["argv"] = 7
            _write_canonical(command_path, command)
            _rebind_candidate(root)
            with self.assertRaises(validator.ValidationError) as caught:
                validator.validate_candidate_bundle_components(self.contract, root, MANIFEST)
            self.assertEqual(caught.exception.code, "candidate_schema")

    def test_jni_common_payload_dispatch_and_specific_semantic_errors(self) -> None:
        payload = {
            "binding_form": "static_short",
            "java_declaration": {"dex_artifact_id": "extracted-dex:classes.dex", "class_descriptor": "Lpkg/A;", "method_name": "nativeCall", "descriptor": "(I)V"},
            "native_endpoint": {"endpoint_kind": "java_export", "library_artifact_id": "extracted-native:arm64-v8a/liba.so", "native_export_record_id": "INV-" + "A" * 64, "native_symbol_record_id": "INV-" + "B" * 64, "name": "Java_pkg_A_nativeCall", "version": None, "virtual_address": 4096},
            "registration_site": None,
            "resolution_status": "resolved",
        }
        record = {
            "artifact_id": None, "classification_status": "classified", "dossier_id": None,
            "official_source": None, "parent_record_ids": [],
            "record_id": validator.record_id("jni_edge", payload), "record_type": "jni_edge",
            "scope_key": validator.canonical_json_bytes(payload).decode("utf-8"),
            "sha256": None, "size_bytes": None, "source_artifact_id": "extracted-dex:classes.dex",
            "source_refs": [{"attachment_path": "source-index.json", "bundle_id": "component", "source_locator": "raw/jni.json#/source_rows/0", "source_record_sha256": "0" * 64}],
            "payload": payload,
        }
        self.assertEqual(validator.validate_candidate_record_schema(self.contract, record, 0), "jni_edge:static")
        invalid_descriptor = copy.deepcopy(record)
        invalid_descriptor["payload"]["java_declaration"]["descriptor"] = "(Q)V"
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_record_schema(self.contract, invalid_descriptor, 0)
        self.assertEqual(caught.exception.code, "jni_descriptor")
        invalid_endpoint = copy.deepcopy(record)
        invalid_endpoint["payload"]["native_endpoint"]["endpoint_kind"] = "function_address"
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_candidate_record_schema(self.contract, invalid_endpoint, 0)
        self.assertEqual(caught.exception.code, "jni_endpoint")

    def test_registration_candidates_have_exact_decision_conservation(self) -> None:
        excluded = {
            "candidate_id": "JRC-" + "1" * 64,
            "raw_evidence": {
                "library_artifact_id": "extracted-native:arm64-v8a/liba.so",
                "section_index": 1,
                "function_virtual_address": 4096,
                "function_size_bytes": 12,
                "register_natives_call_virtual_address": 4104,
            },
            "proofs": {
                "relocation": {"status": "excluded", "reason_code": "unsupported_relocation"},
                "function": {"status": "not_reached"}, "cfg": {"status": "not_reached"},
                "abi": {"status": "not_reached"}, "table": {"status": "not_reached"},
                "class": {"status": "not_reached"},
            },
            "proposed_edges": [],
        }
        result = validator.evaluate_jni_registration_candidates([excluded], self.contract)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["proven_edge_count"], 0)
        self.assertEqual(result["exclusion_count"], 1)
        self.assertEqual(result["candidate_count"], result["proven_candidate_count"] + result["exclusion_count"])
        self.assertEqual(len(result["decisions"]), 1)
        edge_payload = {
            "binding_form": "register_natives",
            "java_declaration": {"dex_artifact_id": "extracted-dex:classes.dex", "class_descriptor": "Lpkg/A;", "method_name": "nativeCall", "descriptor": "(I)V"},
            "native_endpoint": {"endpoint_kind": "function_address", "library_artifact_id": "extracted-native:arm64-v8a/liba.so", "virtual_address": 8192, "aliases": []},
            "registration_site": {"library_artifact_id": "extracted-native:arm64-v8a/liba.so", "register_natives_call_virtual_address": 4104, "registering_symbol_record_ids": ["INV-" + "A" * 64], "section_index": 1, "table_entry_ordinal": 0, "table_entry_virtual_address": 12288},
            "resolution_status": "resolved",
        }
        proven = copy.deepcopy(excluded)
        proven["candidate_id"] = "JRC-" + "2" * 64
        proven["proofs"] = {stage: {"status": "proven"} for stage in ("relocation", "function", "cfg", "abi", "table", "class")}
        proven["proposed_edges"] = [edge_payload]
        result = validator.evaluate_jni_registration_candidates([proven], self.contract)
        self.assertEqual((result["candidate_count"], result["proven_candidate_count"], result["proven_edge_count"], result["exclusion_count"]), (1, 1, 1, 0))
        membership = validator.derive_static_jni_membership([], [], self.contract, result)
        self.assertEqual(membership["register_natives_edge_count"], result["proven_edge_count"])

    def test_every_raw_schema_locator_resolves_and_family_mapping_is_closed(self) -> None:
        raw = self.contract["provenance"]["raw_attachments"]
        self.assertNotIn("elf.raw_schema", raw.get("specialized_paths", {}).values())
        mapping = raw["family_mapping"]
        self.assertEqual(set(mapping), set(validator.EXPECTED_ATTACHMENT_KINDS.values()))
        for path, kind in validator.EXPECTED_ATTACHMENT_KINDS.items():
            self.assertEqual(mapping[kind]["path"], path)


class G002NeutralValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract_bytes = CONTRACT.read_bytes()
        cls.contract = validator.load_canonical_json(CONTRACT)
        cls.contract_summary = validator.validate_contract(cls.contract, cls.contract_bytes)
        cls.fixture_summary = validator.validate_fixtures(cls.contract, FIXTURES)
        cls.official_summary = validator.validate_official_anchors(cls.contract, MANIFEST, XAPK)

    def test_contract_bytes_and_generator_are_deterministic(self) -> None:
        first = validator.canonical_json_bytes(self.contract) + b"\n"
        second = validator.canonical_json_bytes(validator.parse_json_bytes(first)) + b"\n"
        self.assertEqual(self.contract_bytes, first)
        self.assertEqual(first, second)
        self.assertEqual(
            hashlib.sha256(first).hexdigest(),
            hashlib.sha256(second).hexdigest(),
        )

        with tempfile.TemporaryDirectory(prefix="g002-fixture-rebuild-", dir="/tmp") as temp:
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            subprocess.run(
                [sys.executable, str(FIXTURES / "generate_fixtures.py"), "--output", temp],
                check=True,
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            rebuilt = Path(temp)
            committed = {
                path.relative_to(FIXTURES).as_posix(): path.read_bytes()
                for path in FIXTURES.rglob("*")
                if path.is_file() and path.name != "generate_fixtures.py"
            }
            regenerated = {
                path.relative_to(rebuilt).as_posix(): path.read_bytes()
                for path in rebuilt.rglob("*")
                if path.is_file()
            }
            self.assertEqual(committed, regenerated)

    def test_corrected_elf_universe_and_fifteen_row_regression(self) -> None:
        elf = self.official_summary["elf"]
        self.assertEqual(
            elf,
            {
                "physical_dynsym_entries": 111731,
                "reserved_index_zero": 88,
                "included_nonzero_native_symbol": 111643,
                "unnamed_nonzero_stt_section": 92,
                "defined_global_weak_native_export": 99414,
                "undefined_named_import": 12137,
                "dt_needed": 490,
                "native_import": 12627,
                "java_export": 3227,
            },
        )
        self.assertEqual(len(self.contract["elf"]["per_library_anchors"]), 88)
        self.assertEqual(
            set(self.official_summary["elf_membership_oracles"]),
            set(self.contract["membership_oracles"]["digests"]),
        )
        self.assertEqual(self.official_summary["large_size_regression_rows"], 15)
        self.assertEqual(len(self.contract["elf"]["large_size_regression_rows"]), 15)
        self.assertEqual(
            validator.canonical_digest(self.contract["elf"]["large_size_regression_rows"]),
            self.contract["elf"]["large_size_regression_membership_sha256"],
        )
        self.assertEqual(
            self.official_summary["elf_membership_oracles"],
            {
                key: self.contract["membership_oracles"]["digests"][key]
                for key in self.official_summary["elf_membership_oracles"]
            },
        )

    def test_all_hostile_fixture_dispositions_and_codes(self) -> None:
        expected = (
            self.contract["hostile_fixtures"]["cases"]
            + self.contract["hostile_fixtures"]["file_tests"]
            + self.contract["hostile_fixtures"]["candidate_bundles"]
        )
        actual = self.fixture_summary["results"]
        self.assertEqual(len(actual), len(expected))
        self.assertEqual({row["id"] for row in actual}, {row["id"] for row in expected})
        expected_by_id = {row["id"]: (row["expected"], row["code"]) for row in expected}
        for row in actual:
            self.assertEqual(
                (row["disposition"], row["code"]),
                expected_by_id[row["id"]],
                row["id"],
            )

    def test_independent_official_anchor_validation(self) -> None:
        summary = self.official_summary
        self.assertEqual(summary["official_artifacts_rehashed"], 121)
        self.assertEqual(summary["xapk_entries"], 21)
        self.assertEqual(summary["apk_entries"], 4314)
        self.assertEqual(summary["manifest_nodes"], 188)
        self.assertEqual(summary["resources"], 33431)
        self.assertEqual(summary["resource_configurations"], 36498)
        self.assertEqual(summary["features"], 3)
        self.assertEqual(summary["android_components"], 32)
        self.assertEqual(summary["certificates"], 56)
        self.assertEqual(summary["dex"], validator.EXPECTED_DEX_COUNTS)
        self.assertEqual(summary["dex_membership"], self.contract["dex"]["byte_membership_oracles"])
        self.assertEqual(summary["jni_membership"], self.contract["jni"]["byte_membership_oracles"])
        self.assertEqual(summary["jni_membership"]["dex_native_declaration_count"], 3266)
        self.assertEqual(summary["jni_membership"]["java_export_count"], 3227)
        self.assertEqual(summary["jni_membership"]["raw_register_natives_candidate_count"], 1)
        self.assertEqual(summary["jni_membership"]["register_natives_edge_count"], 0)
        self.assertEqual(summary["android_membership"], self.contract["android"]["normalized_membership_oracles"])
        self.assertEqual(
            summary["raw_obligations"],
            self.contract["provenance"]["whole_candidate"]["raw_obligation_oracle"],
        )
        self.assertEqual(summary["raw_obligations"]["global"]["source_rows"]["count"], 519437)
        self.assertEqual(summary["raw_obligations"]["global"]["byte_ranges"]["count"], 121)

    def test_exact_no_extra_key_and_nfc_collision_behavior(self) -> None:
        mutated = copy.deepcopy(self.contract)
        mutated["unexpected"] = True
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(mutated)
        self.assertEqual(caught.exception.code, "contract_top_keys")

        with self.assertRaises(validator.ValidationError) as caught:
            validator.parse_json_bytes((FIXTURES / "duplicate_keys.json").read_bytes())
        self.assertEqual(caught.exception.code, "json_duplicate_key")

        with self.assertRaises(validator.ValidationError) as caught:
            validator.parse_json_bytes((FIXTURES / "nfc_collision.json").read_bytes())
        self.assertEqual(caught.exception.code, "json_nfc_key_collision")

        parsed = validator.parse_json_bytes((FIXTURES / "noncanonical.json").read_bytes())
        self.assertNotEqual(
            (FIXTURES / "noncanonical.json").read_bytes(),
            validator.canonical_json_bytes(parsed) + b"\n",
        )

    def test_floor_source_parent_raw_and_chronology_rules(self) -> None:
        counts = self.contract["counts"]
        self.assertEqual(sum(counts["fixed_terms"].values()), 514431)
        self.assertEqual(sum(counts["configuration_terms"].values()), 41011)
        self.assertEqual(111731, 88 + 92 + 99414 + 12137)
        self.assertEqual(12627, 12137 + 490)
        self.assertEqual(
            counts["record_count_equation"],
            "514431 + jni_edge_count + reflection_target_count + dynamic_loader_count",
        )

        parent_rows = self.contract["record_model"]["source_parent_byte_matrix"]
        self.assertEqual(len(parent_rows), 26)
        self.assertEqual(
            {row["variant"] for row in parent_rows},
            validator.EXPECTED_PARENT_VARIANTS,
        )
        for row in parent_rows:
            encoded = [validator.canonical_json_bytes(parent) for parent in row["parents"]]
            self.assertEqual(len(encoded), len(set(encoded)))

        self.assertEqual(
            self.contract["provenance"]["set_equalities"],
            [
                "physical primitive IDs = decision primitive IDs",
                "fact IDs = union decision fact_ids",
                "normalized facts biject source rows",
                "normalized facts and source rows are ordered by fact_id; source_row_index is the exact zero-based source-row position",
                "raw source locators = source-index locators = normalized source-ref locators",
                "every normalized record consumes source reference exactly once",
                "candidate primitive ID membership = official replay primitive ID membership",
                "candidate decision, fact, source-row, input, scope-summary, per-attachment, and byte-range memberships = official replay memberships",
            ],
        )
        validator.validate_source_locator("raw/elf.json#/source_rows/0")
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_source_locator("raw/elf.json#/source_rows/01")
        self.assertEqual(caught.exception.code, "source_locator_noncanonical")

        valid = {
            "run_started": "2026-01-01T00:00:00.000000Z",
            "command_started": "2026-01-01T00:00:00.000000Z",
            "command_ended": "2026-01-01T00:00:01.000000Z",
            "captured": "2026-01-01T00:00:01.000000Z",
            "run_ended": "2026-01-01T00:00:02.000000Z",
            "generated": "2026-01-01T00:00:03.000000Z",
            "reviewed": "2026-01-01T00:00:04.000000Z",
        }
        validator.validate_chronology(valid)
        invalid = dict(valid, generated=valid["run_ended"])
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_chronology(invalid)
        self.assertEqual(caught.exception.code, "chronology_inventory_not_later")

    def test_recursive_schema_closure_and_reviewed_contract_digest(self) -> None:
        validator.validate_schema_closure(self.contract["record_model"])
        official_source = self.contract["record_model"]["outer_envelope"]["properties"]["official_source"]
        self.assertEqual(official_source["of"]["type"], "union")
        self.assertIn("official_source_file", official_source["of"]["variants"])

        mutations: list[tuple[str, object]] = [
            ("canonical_json.encoding", "UTF-16"),
            ("elf.export_predicate", []),
            ("dex.admission", "sha1 disabled"),
            ("callsites.abstract_interpreter.join", "first predecessor wins"),
            ("jni.precedence", list(reversed(self.contract["jni"]["precedence"]))),
            ("android.zip.methods", [0, 8, 99]),
            ("provenance.set_equalities", []),
            ("provenance.chronology.strict_boundaries", []),
            ("hostile_fixtures.files", {}),
        ]
        for dotted, replacement in mutations:
            mutated = copy.deepcopy(self.contract)
            target = mutated
            parts = dotted.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = replacement
            data = validator.canonical_json_bytes(mutated) + b"\n"
            with self.subTest(dotted=dotted), self.assertRaises(validator.ValidationError) as caught:
                validator.validate_contract(mutated, data)
            self.assertEqual(caught.exception.code, "contract_reviewed_digest")

        combined = copy.deepcopy(self.contract)
        combined["canonical_json"]["encoding"] = "UTF-16"
        combined["elf"]["export_predicate"] = []
        combined["callsites"]["abstract_interpreter"]["join"] = "first predecessor wins"
        combined["android"]["zip"]["methods"] = [0, 8, 99]
        combined["provenance"]["set_equalities"] = []
        combined_bytes = validator.canonical_json_bytes(combined) + b"\n"
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(combined, combined_bytes)
        self.assertEqual(caught.exception.code, "contract_reviewed_digest")

        large = copy.deepcopy(self.contract)
        large["elf"]["large_size_regression_rows"] = large["elf"]["large_size_regression_rows"][:14]
        large["elf"]["large_size_regression_membership_sha256"] = validator.canonical_digest(large["elf"]["large_size_regression_rows"])
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(large, validator.canonical_json_bytes(large) + b"\n")
        self.assertEqual(caught.exception.code, "contract_reviewed_digest")

        base = copy.deepcopy(self.contract)
        base["android"]["components"]["canonical_base_artifact_id"] = "xapk-apk:wrong.apk"
        base["provenance"]["canonical_base_role"]["artifact_id"] = "xapk-apk:wrong.apk"
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_contract(base, validator.canonical_json_bytes(base) + b"\n")
        self.assertEqual(caught.exception.code, "contract_reviewed_digest")

        broken = copy.deepcopy(self.contract["record_model"])
        broken["payload_schemas"]["asset"]["payload"]["properties"]["path"] = {"ref": "missing"}
        with self.assertRaises(validator.ValidationError) as caught:
            validator.validate_schema_closure(broken)
        self.assertEqual(caught.exception.code, "contract_schema_undefined_ref")

    def test_candidate_bundle_acceptance_and_typed_rejections(self) -> None:
        cases = self.contract["hostile_fixtures"]["candidate_bundles"]
        for case in cases:
            try:
                summary = validator.validate_candidate_bundle(self.contract, FIXTURES / case["path"], MANIFEST)
                disposition, code = "accept", "ok"
                if disposition == "accept":
                    self.assertEqual(summary["records"], 1)
                    self.assertEqual(summary["raw_attachments"], 8)
            except validator.ValidationError as exc:
                disposition, code = "reject", exc.code
            with self.subTest(case=case["id"]):
                self.assertEqual((disposition, code), (case["expected"], case["code"]))

        duplicate_case = {
            "operation": "source_parent",
            "input": {"source_artifact_id": "A", "payload_source": "A", "parents": ["P", "P"], "expected_parents": ["P"]},
        }
        self.assertEqual(
            validator._fixture_disposition(duplicate_case, self.contract, FIXTURES),
            ("reject", "parent_duplicate"),
        )

    def test_jni_descriptor_and_aarch64_typed_boundaries(self) -> None:
        with self.assertRaises(validator.ValidationError) as caught:
            validator.jni_names("Lx;", "m", "(Q)V")
        self.assertEqual(caught.exception.code, "jni_descriptor")
        bl = validator.decode_aarch64_instruction(0x94000002, 0x1000)
        self.assertEqual(bl, {"op": "BL", "target": 0x1008})
        ldr0 = 0xF9400000 | (0 << 10) | (0 << 5) | 9
        ldr_slot = 0xF9400000 | (215 << 10) | (9 << 5) | 10
        blr = 0xD63F0000 | (10 << 5)
        code = b"".join(word.to_bytes(4, "little") for word in (ldr0, ldr_slot, blr))
        result = validator.analyze_aarch64_register_natives(code, 0x2000)
        self.assertEqual(result["calls"], [{"kind": "jni_table_slot", "slot": 215, "call_virtual_address": 0x2008}])
        with self.assertRaises(validator.ValidationError) as caught:
            validator.decode_aarch64_instruction(0, 2)
        self.assertEqual(caught.exception.code, "jni_aarch64_word")

    def test_dex_fixpoint_derives_target_from_instruction_bytes(self) -> None:
        units = (0x001A, 0x0000, 0x1071, 0x0000, 0x0000, 0x000E)
        methods = [("Ljava/lang/Class;", "forName", "(Ljava/lang/String;)Ljava/lang/Class;")]
        result = validator.interpret_dex_code(
            units,
            1,
            ["pkg.A"],
            [],
            methods,
            self.contract["callsites"],
        )
        self.assertEqual(
            result[("reflection_target", 2)],
            {"target_kind": "class", "class_descriptor": "Lpkg/A;"},
        )

    def test_malformed_android_paths_have_stable_typed_errors(self) -> None:
        with self.assertRaises(validator.ValidationError) as caught:
            validator.parse_axml(b"\x03\x00\x08\x00\x08\x00\x00\x00")
        self.assertEqual(caught.exception.code, "axml_string_pool")
        def lp32(blob: bytes) -> bytes:
            return len(blob).to_bytes(4, "little") + blob

        signed_data_without_suffix = lp32(b"") + lp32(b"") + lp32(b"")
        signer = lp32(signed_data_without_suffix) + lp32(b"") + lp32(b"")
        with self.assertRaises(validator.ValidationError) as caught:
            validator.count_scheme_certificates(lp32(lp32(signer)), "v2")
        self.assertEqual(caught.exception.code, "signing_v2_suffix")

        data = bytearray((FIXTURES / "zip_duplicate_assets.zip").read_bytes())
        central = data.find(b"PK\x01\x02")
        local = data.find(b"PK\x03\x04")
        data[central + 10 : central + 12] = (99).to_bytes(2, "little")
        data[local + 8 : local + 10] = (99).to_bytes(2, "little")
        with self.assertRaises(validator.ValidationError) as caught:
            validator.parse_zip_directory_bytes(bytes(data))
        self.assertEqual(caught.exception.code, "zip_compression_unsupported")

        data = bytearray((FIXTURES / "zip_duplicate_assets.zip").read_bytes())
        central = data.find(b"PK\x01\x02")
        local = data.find(b"PK\x03\x04")
        data[central + 8 : central + 10] = (0x8010).to_bytes(2, "little")
        data[local + 6 : local + 8] = (0x8010).to_bytes(2, "little")
        with self.assertRaises(validator.ValidationError) as caught:
            validator.parse_zip_directory_bytes(bytes(data))
        self.assertEqual(caught.exception.code, "zip_flags_unsupported")

    def test_validator_has_no_external_or_inventory_builder_imports(self) -> None:
        tree = ast.parse(VALIDATOR.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        allowed = set(sys.stdlib_module_names) | {"__future__"}
        self.assertTrue(imports <= allowed, sorted(imports - allowed))

        neutral_files = [
            CONTRACT,
            VALIDATOR,
            ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/static-inventory-contract.md",
            ROOT / ".omx/handoff/g002-architecture.md",
            ROOT / ".omx/handoff/g002-test-verification-design.md",
            ROOT / ".omx/handoff/g002-neutral-normalization-schema.md",
        ]
        forbidden = [re.compile(rb"g002_method_[ab]", re.I), re.compile(rb"inventory-[ab]\.json", re.I)]
        for path in neutral_files:
            data = path.read_bytes()
            for pattern in forbidden:
                self.assertIsNone(pattern.search(data), f"{path}: {pattern.pattern!r}")
        for path in neutral_files[0:1] + neutral_files[2:]:
            self.assertNotIn(b"/tmp/", path.read_bytes(), str(path))

    def test_cli_output_is_byte_identical_across_two_clean_passes(self) -> None:
        command = [
            sys.executable,
            str(VALIDATOR),
            "--contract",
            str(CONTRACT),
            "--fixtures",
            str(FIXTURES),
            "--official-manifest",
            str(MANIFEST),
            "--xapk",
            str(XAPK),
            "--json",
        ]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        first = subprocess.run(command, cwd=ROOT, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        second = subprocess.run(command, cwd=ROOT, env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
        self.assertEqual(first, second)
        summary = json.loads(first)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["official"]["official_artifacts_rehashed"], 121)
        self.assertNotIn("candidate", summary)

    def test_candidate_cli_rejections_are_typed_json_without_tracebacks(self) -> None:
        base_command = [
            sys.executable,
            str(VALIDATOR),
            "--contract",
            str(CONTRACT),
            "--fixtures",
            str(FIXTURES),
            "--official-manifest",
            str(MANIFEST),
            "--xapk",
            str(XAPK),
        ]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        for case in self.contract["hostile_fixtures"]["candidate_bundles"]:
            if case["expected"] != "reject":
                continue
            completed = subprocess.run(
                base_command
                + ["--candidate-bundle", str(FIXTURES / case["path"]), "--json"],
                cwd=ROOT,
                env=env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with self.subTest(case=case["id"]):
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(completed.stderr, b"")
                self.assertNotIn(b"Traceback", completed.stdout)
                failure = json.loads(completed.stdout)
                self.assertEqual(failure["status"], "error")
                self.assertEqual(failure["code"], case["code"])


if __name__ == "__main__":
    unittest.main()
