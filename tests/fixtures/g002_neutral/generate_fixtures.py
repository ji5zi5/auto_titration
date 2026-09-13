#!/usr/bin/env python3
"""Generate the deterministic G002 neutral-validator conformance fixtures."""

from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import unicodedata
from pathlib import Path


def canonical_json(value: object) -> bytes:
    def normalize(item: object) -> object:
        if isinstance(item, str):
            return unicodedata.normalize("NFC", item)
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            result: dict[str, object] = {}
            for key, child in item.items():
                normalized_key = unicodedata.normalize("NFC", key)
                if normalized_key in result:
                    raise ValueError("post-NFC key collision")
                result[normalized_key] = normalize(child)
            return result
        return item

    return json.dumps(
        normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def record_id(record_type: str, payload: object) -> str:
    digest = hashlib.sha256(
        canonical_json(["g002-record/v1", record_type, payload])
    ).hexdigest().upper()
    return f"INV-{digest}"


RAW_PATHS = [
    "raw/xapk.json",
    "raw/apk-entries.json",
    "raw/manifests.json",
    "raw/resources.json",
    "raw/signing.json",
    "raw/dex.json",
    "raw/elf.json",
    "raw/jni.json",
]


def _json_file(value: object) -> bytes:
    return canonical_json(value) + b"\n"


def _descriptor(path: str, data: bytes) -> dict[str, object]:
    return {
        "path": path,
        "media_type": "application/json",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def build_candidate_files(mutation: str | None = None) -> dict[str, bytes]:
    bundle_id = "g002-fixture-bundle"
    artifact_set_id = "hikmicro-viewer-2.6.0-019801077bb42ffb"
    payload = "official-xapk"
    normalized_id = record_id("frozen_artifact", payload)
    source_locator = "raw/xapk.json#/source_rows/0"
    official_source = {
        "path": "/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk",
        "type": "file",
    }
    source_row = {
        "source_locator": source_locator,
        "record_type": "frozen_artifact",
        "scope_key": canonical_json(payload).decode("utf-8"),
        "artifact_id": "official-xapk",
        "source_artifact_id": "official-xapk",
        "sha256": "019801077bb42ffb2d7ca4bda88a87f48324041366d5ade037b7f3bca3616958",
        "size_bytes": 271805591,
        "official_source": official_source,
    }
    source_hash = hashlib.sha256(canonical_json(source_row)).hexdigest()
    record = {
        **{key: source_row[key] for key in ("record_type", "scope_key", "artifact_id", "source_artifact_id", "sha256", "size_bytes", "official_source")},
        "payload": payload,
        "record_id": normalized_id,
        "dossier_id": None,
        "classification_status": "classified",
        "parent_record_ids": [],
        "source_refs": [{
            "bundle_id": bundle_id,
            "attachment_path": "source-index.json",
            "source_locator": source_locator,
            "source_record_sha256": source_hash,
        }],
    }
    byte_range = {
        "artifact_id": "official-xapk",
        "offset_bytes": 0,
        "size_bytes": 271805591,
        "sha256": record["sha256"],
    }
    primitive_preimage = [
        "g002-primitive/v1", "xapk", "artifact.bytes", "artifact",
        ["official-xapk"], ["official-xapk"], [byte_range], [],
    ]
    primitive_id = "PRM-" + hashlib.sha256(canonical_json(primitive_preimage)).hexdigest().upper()
    fact_id = "FCT-" + hashlib.sha256(canonical_json(["g002-fact/v1", normalized_id])).hexdigest().upper()
    raw_docs: dict[str, dict[str, object]] = {}
    for path in RAW_PATHS:
        kind = Path(path).stem
        raw_docs[path] = {
            "schema_version": "g002-raw-attachment/v1",
            "attachment_kind": kind,
            "artifact_set_id": artifact_set_id,
            "input_artifact_ids": ["official-xapk"],
            "primitives": [],
            "decisions": [],
            "facts": [],
            "source_rows": [],
            "scope_summaries": [],
        }
    raw_docs["raw/xapk.json"].update({
        "attachment_kind": "xapk",
        "primitives": [{
            "primitive_id": primitive_id,
            "primitive_kind": "artifact.bytes",
            "origin": "artifact",
            "input_artifact_ids": ["official-xapk"],
            "physical_key": ["official-xapk"],
            "byte_ranges": [byte_range],
            "dependency_primitive_ids": [],
        }],
        "decisions": [{
            "primitive_id": primitive_id,
            "disposition": "normalization_root",
            "fact_ids": [fact_id],
            "reason_code": None,
        }],
        "facts": [{
            "fact_id": fact_id,
            "fact_kind": "normalized",
            "record_id": normalized_id,
            "record_type": "frozen_artifact",
            "scope_key": record["scope_key"],
            "validation_code": None,
            "dependency_primitive_ids": [primitive_id],
            "source_row_index": 0,
        }],
        "source_rows": [source_row],
        "scope_summaries": [{
            "scope": "frozen_artifact",
            "observed_count": 1,
            "included_count": 1,
            "excluded_count": 0,
            "accounted_count": 1,
            "normalized_record_count": 1,
            "unaccounted_count": 0,
        }],
    })
    source_index = {"schema_version": "g002-source-index/v2", "bundle_id": bundle_id, "rows": [source_row]}
    inventory = {
        "schema": "g002-normalized-inventory/v2",
        "scope": "component",
        "artifact_set_id": artifact_set_id,
        "bundle_id": bundle_id,
        "generated_at": "2026-01-01T00:00:03.000000Z",
        "records": [record],
        "summary": {
            "record_count": 1,
            "family_counts": [{"family": "frozen_artifact", "count": 1}],
            "family_memberships": [{
                "family": "frozen_artifact",
                "count": 1,
                "payloads_sha256": hashlib.sha256(canonical_json([payload])).hexdigest(),
                "record_ids_sha256": hashlib.sha256(canonical_json([normalized_id])).hexdigest(),
            }],
        },
    }
    run = {"schema": "g002-run/v1", "bundle_id": bundle_id, "operator_id": "fixture-operator", "started_at": "2026-01-01T00:00:00.000000Z", "ended_at": "2026-01-01T00:00:02.000000Z", "status": "succeeded"}
    command = {"schema": "g002-command/v1", "bundle_id": bundle_id, "operator_id": "fixture-operator", "argv": ["fixture"], "started_at": "2026-01-01T00:00:00.000000Z", "ended_at": "2026-01-01T00:00:01.000000Z", "exit_code": 0}

    if mutation == "duplicate_parent":
        record["parent_record_ids"] = [normalized_id, normalized_id]
    elif mutation == "bad_locator":
        bad = "raw/xapk.json#/source_records/0"
        source_row["source_locator"] = bad
        record["source_refs"][0]["source_locator"] = bad
        source_index["rows"][0]["source_locator"] = bad
        record["source_refs"][0]["source_record_sha256"] = hashlib.sha256(canonical_json(source_row)).hexdigest()
    elif mutation == "missing_decision":
        raw_docs["raw/xapk.json"]["decisions"] = []
    elif mutation == "outer_byte":
        record["size_bytes"] = 271805590
        source_row["size_bytes"] = 271805590
    elif mutation == "review_equality":
        inventory["generated_at"] = "2026-01-01T00:00:04.000000Z"
    elif mutation == "command_argv":
        command["argv"] = 7
    elif mutation == "raw_kind":
        raw_docs["raw/elf.json"]["attachment_kind"] = "xapk"
    elif mutation == "raw_extra":
        raw_docs["raw/elf.json"]["unexpected"] = True
    elif mutation == "source_index_type":
        source_index["rows"] = 7
    elif mutation == "inventory_type":
        inventory["artifact_set_id"] = 7
    elif mutation == "run_type":
        run["status"] = 7
    elif mutation == "record_type":
        record["classification_status"] = 7
    elif mutation == "family_relocation":
        source_row["source_locator"] = "raw/elf.json#/source_rows/0"
        primitive = raw_docs["raw/xapk.json"]["primitives"][0]
        relocated_preimage = [
            "g002-primitive/v1", "elf", primitive["primitive_kind"], primitive["origin"],
            primitive["input_artifact_ids"], primitive["physical_key"], primitive["byte_ranges"],
            primitive["dependency_primitive_ids"],
        ]
        relocated_id = "PRM-" + hashlib.sha256(canonical_json(relocated_preimage)).hexdigest().upper()
        primitive["primitive_id"] = relocated_id
        raw_docs["raw/xapk.json"]["decisions"][0]["primitive_id"] = relocated_id
        raw_docs["raw/xapk.json"]["facts"][0]["dependency_primitive_ids"] = [relocated_id]
        for key in ("primitives", "decisions", "facts", "source_rows", "scope_summaries"):
            raw_docs["raw/elf.json"][key] = raw_docs["raw/xapk.json"][key]
            raw_docs["raw/xapk.json"][key] = []
        record["source_refs"][0]["source_locator"] = source_row["source_locator"]
        record["source_refs"][0]["source_record_sha256"] = hashlib.sha256(canonical_json(source_row)).hexdigest()

    files: dict[str, bytes] = {
        "inventory.json": _json_file(inventory),
        "source-index.json": _json_file(source_index),
        "run.json": _json_file(run),
        "command.json": _json_file(command),
    }
    for path, document in raw_docs.items():
        files[path] = _json_file(document)
    raw_descriptors = [{**_descriptor(path, files[path]), "captured_at": "2026-01-01T00:00:01.000000Z", "attachment_kind": raw_docs[path]["attachment_kind"]} for path in RAW_PATHS]
    review = {
        "schema": "g002-review/v1",
        "bundle_id": bundle_id,
        "reviewer_id": "fixture-reviewer",
        "reviewed_at": "2026-01-01T00:00:04.000000Z",
        "inventory_sha256": hashlib.sha256(files["inventory.json"]).hexdigest(),
        "source_index_sha256": hashlib.sha256(files["source-index.json"]).hexdigest(),
        "attachment_sha256s": {row["path"]: row["sha256"] for row in raw_descriptors},
        "status": "accepted",
    }
    if mutation == "review_type":
        review["reviewer_id"] = 7
    files["review.json"] = _json_file(review)
    bundle = {
        "schema": "g002-candidate-bundle/v2",
        "candidate_scope": "component",
        "bundle_id": bundle_id,
        "artifact_set_id": artifact_set_id,
        "operator_id": "fixture-operator",
        "inventory": _descriptor("inventory.json", files["inventory.json"]),
        "source_index": _descriptor("source-index.json", files["source-index.json"]),
        "raw_attachments": raw_descriptors,
        "run": _descriptor("run.json", files["run.json"]),
        "command": _descriptor("command.json", files["command.json"]),
        "review": _descriptor("review.json", files["review.json"]),
    }
    if mutation == "bundle_extra":
        bundle["unexpected"] = True
    elif mutation == "descriptor_type":
        bundle["inventory"]["size_bytes"] = "wrong"
    files["bundle.json"] = _json_file(bundle)
    if mutation == "attachment_hash":
        hostile = json.loads(files["raw/xapk.json"])
        hostile["artifact_set_id"] = artifact_set_id + "-hash-mutation"
        files["raw/xapk.json"] = _json_file(hostile)
    return files


def build_elf_fixture() -> bytes:
    """Build a little-endian ELF64 section-table fixture with 17 dynsym rows."""
    names = [f"large_symbol_{index}" for index in range(15)] + ["external_symbol"]
    dynstr = bytearray(b"\0")
    name_offsets: dict[str, int] = {}
    for name in names:
        name_offsets[name] = len(dynstr)
        dynstr.extend(name.encode("ascii") + b"\0")

    symbols = [b"\0" * 24]
    symbols.append(struct.pack("<IBBHQQ", 0, 3, 0, 3, 0, 0))
    sizes = [
        196608,
        101544,
        128000,
        196608,
        3298112,
        1961152,
        817232,
        166544,
        524288,
        1048576,
        524288,
        8000000,
        131072,
        2097152,
        1048576,
    ]
    for index, size in enumerate(sizes):
        symbols.append(
            struct.pack(
                "<IBBHQQ",
                name_offsets[f"large_symbol_{index}"],
                0x11,
                0,
                3,
                0x1000 + index * 16,
                size,
            )
        )
    symbols.append(
        struct.pack(
            "<IBBHQQ",
            name_offsets["external_symbol"],
            0x12,
            0,
            0,
            0,
            0,
        )
    )
    dynsym = b"".join(symbols)

    shstr = b"\0.dynstr\0.dynsym\0.data\0.shstrtab\0"
    sh_name = {
        ".dynstr": shstr.index(b".dynstr"),
        ".dynsym": shstr.index(b".dynsym"),
        ".data": shstr.index(b".data"),
        ".shstrtab": shstr.index(b".shstrtab"),
    }

    header_size = 64
    cursor = header_size

    def place(blob: bytes, alignment: int = 8) -> tuple[int, bytes]:
        nonlocal cursor
        padding = (-cursor) % alignment
        offset = cursor + padding
        cursor = offset + len(blob)
        return offset, b"\0" * padding + blob

    body_parts: list[bytes] = []
    dynstr_off, part = place(bytes(dynstr), 1)
    body_parts.append(part)
    dynsym_off, part = place(dynsym, 8)
    body_parts.append(part)
    data = b"\0" * 64
    data_off, part = place(data, 8)
    body_parts.append(part)
    shstr_off, part = place(shstr, 1)
    body_parts.append(part)
    shoff = (cursor + 7) & ~7
    body_parts.append(b"\0" * (shoff - cursor))

    section_headers = [b"\0" * 64]
    section_headers.append(
        struct.pack("<IIQQQQIIQQ", sh_name[".dynstr"], 3, 0x2, 0, dynstr_off, len(dynstr), 0, 0, 1, 0)
    )
    section_headers.append(
        struct.pack("<IIQQQQIIQQ", sh_name[".dynsym"], 11, 0x2, 0, dynsym_off, len(dynsym), 1, 1, 8, 24)
    )
    section_headers.append(
        struct.pack("<IIQQQQIIQQ", sh_name[".data"], 1, 0x3, 0x1000, data_off, len(data), 0, 0, 8, 0)
    )
    section_headers.append(
        struct.pack("<IIQQQQIIQQ", sh_name[".shstrtab"], 3, 0, 0, shstr_off, len(shstr), 0, 0, 1, 0)
    )

    ident = b"\x7fELF" + bytes([2, 1, 1, 0, 0]) + b"\0" * 7
    header = struct.pack(
        "<16sHHIQQQIHHHHHH",
        ident,
        3,
        183,
        1,
        0,
        0,
        shoff,
        0,
        64,
        56,
        0,
        64,
        len(section_headers),
        4,
    )
    return header + b"".join(body_parts) + b"".join(section_headers)


def build_duplicate_zip_fixture() -> bytes:
    name = b"assets/a.bin"
    payload = b"A"
    crc = binascii.crc32(payload) & 0xFFFFFFFF
    local_parts: list[bytes] = []
    central_parts: list[bytes] = []
    offset = 0
    for _ordinal in range(2):
        local = struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            20,
            0x800,
            0,
            0,
            0,
            crc,
            len(payload),
            len(payload),
            len(name),
            0,
        ) + name + payload
        local_parts.append(local)
        central_parts.append(
            struct.pack(
                "<IHHHHHHIIIHHHHHII",
                0x02014B50,
                20,
                20,
                0x800,
                0,
                0,
                0,
                crc,
                len(payload),
                len(payload),
                len(name),
                0,
                0,
                0,
                0,
                0,
                offset,
            ) + name
        )
        offset += len(local)
    central = b"".join(central_parts)
    eocd = struct.pack(
        "<IHHHHIIH",
        0x06054B50,
        0,
        0,
        2,
        2,
        len(central),
        offset,
        0,
    )
    return b"".join(local_parts) + central + eocd


def build_cases() -> list[dict[str, object]]:
    payload = {
        "apk_artifact_id": "xapk-apk:base.apk",
        "archive_entry_record_id": "INV-" + "A" * 64,
        "path": "assets/a.bin",
        "sha256": hashlib.sha256(b"A").hexdigest(),
        "size_bytes": 1,
    }
    valid_id = record_id("asset", payload)
    cases: list[dict[str, object]] = [
        {"id": "CANONICAL-OBJECT", "operation": "canonical_object", "input": {"a": 1, "b": "é"}, "expected": "accept", "code": "ok"},
        {"id": "RECORD-IDENTITY", "operation": "record_identity", "input": {"record_type": "asset", "payload": payload, "record_id": valid_id}, "expected": "accept", "code": "ok"},
        {"id": "RECORD-IDENTITY-MUTATED", "operation": "record_identity", "input": {"record_type": "asset", "payload": payload, "record_id": "INV-" + "0" * 64}, "expected": "reject", "code": "record_id_mismatch"},
        {"id": "OUTER-HALF-BYTE-PAIR", "operation": "outer_bytes", "input": {"family": "asset", "sha256": hashlib.sha256(b"A").hexdigest(), "size_bytes": None}, "expected": "reject", "code": "outer_byte_pair"},
        {"id": "OUTER-STRUCTURAL-BYTES", "operation": "outer_bytes", "input": {"family": "native_symbol", "sha256": hashlib.sha256(b"x").hexdigest(), "size_bytes": 1}, "expected": "reject", "code": "outer_byte_policy"},
        {"id": "RAW-EXTRA-KEY", "operation": "raw_conservation", "input": {"primitives": [{"id": "p1", "note": "hidden"}], "decisions": [{"id": "p1"}], "expected_members": ["p1"]}, "expected": "reject", "code": "raw_schema_extra_key"},
        {"id": "RAW-HIDDEN-PRIMITIVE", "operation": "raw_conservation", "input": {"primitives": [{"id": "p1"}], "decisions": [{"id": "p1"}], "expected_members": ["p1", "p2"]}, "expected": "reject", "code": "raw_primitive_set_mismatch"},
        {"id": "RAW-MISSING-DECISION", "operation": "raw_conservation", "input": {"primitives": [{"id": "p1"}, {"id": "p2"}], "decisions": [{"id": "p1"}], "expected_members": ["p1", "p2"]}, "expected": "reject", "code": "raw_decision_set_mismatch"},
        {"id": "RAW-MEMBERSHIP-SWAP", "operation": "membership", "input": {"expected": [["L", 1], ["L", 2]], "actual": [["L", 1], ["L", 3]]}, "expected": "reject", "code": "membership_digest_mismatch"},
        {"id": "SOURCE-PARENT-CROSSWIRE", "operation": "source_parent", "input": {"source_artifact_id": "lib:A", "payload_source": "lib:B", "parents": ["F:A"], "expected_parents": ["F:A"]}, "expected": "reject", "code": "source_parent_crosswire"},
        {"id": "PARENT-SET-WRONG", "operation": "source_parent", "input": {"source_artifact_id": "lib:A", "payload_source": "lib:A", "parents": ["F:A", "F:B"], "expected_parents": ["F:A"]}, "expected": "reject", "code": "parent_set_mismatch"},
        {"id": "SOURCE-WRONG-ATTACHMENT", "operation": "source_reference", "input": {"attachment_path": "other-index.json", "source_locator": "raw/elf.json#/source_records/0"}, "expected": "reject", "code": "source_index_attachment_mismatch"},
        {"id": "RFC6901-BAD-TILDE", "operation": "source_reference", "input": {"attachment_path": "source-index.json", "source_locator": "raw/elf.json#/source_records/~2"}, "expected": "reject", "code": "source_locator_noncanonical"},
        {"id": "RFC6901-LEADING-ZERO", "operation": "source_reference", "input": {"attachment_path": "source-index.json", "source_locator": "raw/elf.json#/source_records/01"}, "expected": "reject", "code": "source_locator_noncanonical"},
        {"id": "CHRONOLOGY-VALID", "operation": "chronology", "input": {"run_started": "2026-01-01T00:00:00.000000Z", "command_started": "2026-01-01T00:00:00.000000Z", "command_ended": "2026-01-01T00:00:01.000000Z", "captured": "2026-01-01T00:00:01.000000Z", "run_ended": "2026-01-01T00:00:02.000000Z", "generated": "2026-01-01T00:00:03.000000Z", "reviewed": "2026-01-01T00:00:04.000000Z"}, "expected": "accept", "code": "ok"},
        {"id": "CHRONOLOGY-INVENTORY-EQUALITY", "operation": "chronology", "input": {"run_started": "2026-01-01T00:00:00.000000Z", "command_started": "2026-01-01T00:00:00.000000Z", "command_ended": "2026-01-01T00:00:01.000000Z", "captured": "2026-01-01T00:00:01.000000Z", "run_ended": "2026-01-01T00:00:02.000000Z", "generated": "2026-01-01T00:00:02.000000Z", "reviewed": "2026-01-01T00:00:04.000000Z"}, "expected": "reject", "code": "chronology_inventory_not_later"},
        {"id": "CHRONOLOGY-REVIEW-EQUALITY", "operation": "chronology", "input": {"run_started": "2026-01-01T00:00:00.000000Z", "command_started": "2026-01-01T00:00:00.000000Z", "command_ended": "2026-01-01T00:00:01.000000Z", "captured": "2026-01-01T00:00:01.000000Z", "run_ended": "2026-01-01T00:00:02.000000Z", "generated": "2026-01-01T00:00:03.000000Z", "reviewed": "2026-01-01T00:00:03.000000Z"}, "expected": "reject", "code": "chronology_review_not_later"},
        {"id": "ELF-SEMANTIC-MEMBERSHIP", "operation": "elf_fixture", "input": {"path": "elf_semantic_membership.elf", "physical": 18, "included": 17, "unnamed_sections": 1, "exports": 15, "undefined_imports": 1, "large_sizes": 15}, "expected": "accept", "code": "ok"},
        {"id": "ELF-INDEX-ZERO-INCLUDED", "operation": "elf_decision", "input": {"index": 0, "decision": "included_nonzero_dynsym"}, "expected": "reject", "code": "elf_reserved_index_zero"},
        {"id": "ELF-LARGE-SIZE-OMITTED", "operation": "elf_large_rows", "input": {"expected_count": 15, "included_count": 14}, "expected": "reject", "code": "elf_large_size_regression"},
        {"id": "MUTF8-NUL", "operation": "mutf8", "input": {"hex": "01c08000", "identity": False, "expected_units": "0000"}, "expected": "accept", "code": "ok"},
        {"id": "MUTF8-FOUR-BYTE", "operation": "mutf8", "input": {"hex": "02f09f988000", "identity": False}, "expected": "reject", "code": "dex_invalid_mutf8"},
        {"id": "MUTF8-UNPAIRED-IDENTITY", "operation": "mutf8", "input": {"hex": "01eda08000", "identity": True}, "expected": "reject", "code": "dex_identity_surrogate"},
        {"id": "API-WRONG-RETURN", "operation": "api_lookup", "input": {"family": "reflection_target", "owner": "Ljava/lang/Class;", "name": "forName", "descriptor": "(Ljava/lang/String;)Ljava/lang/Object;", "opcode": 113, "expected_matches": 0}, "expected": "accept", "code": "ok"},
        {"id": "PROXY-ORDER-DUPLICATES", "operation": "preserve_list", "input": {"values": ["LB;", "LA;", "LB;"], "expected_values": ["LB;", "LA;", "LB;"]}, "expected": "accept", "code": "ok"},
        {"id": "DEX-PATH-EMPTY-DUPLICATE", "operation": "dex_paths", "input": {"value": "a.dex::b.dex:a.dex", "expected_values": ["a.dex", "", "b.dex", "a.dex"]}, "expected": "accept", "code": "ok"},
        {"id": "FIXPOINT-DIFFERENT-BRANCHES", "operation": "abstract_join", "input": {"values": ["pkg.A", "pkg.B"], "expected_value": {"unresolved_token": "not_statically_resolved"}}, "expected": "accept", "code": "ok"},
        {"id": "JNI-MANGLE-DOLLAR-ARRAY", "operation": "jni_mangle", "input": {"class": "Lpkg/A$B;", "method": "m_n", "descriptor": "([Ljava/lang/String;I)V", "short": "Java_pkg_A_00024B_m_1n", "long": "Java_pkg_A_00024B_m_1n___3Ljava_lang_String_2I"}, "expected": "accept", "code": "ok"},
        {"id": "JNI-ESCAPE-FAILURE", "operation": "jni_mangle", "input": {"class": "Lpkg/0A;", "method": "m", "descriptor": "()V", "escape_failed": True}, "expected": "accept", "code": "ok"},
        {"id": "JNI-REGISTER-PRECEDENCE", "operation": "jni_precedence", "input": {"registrations": 1, "short_exports": 1, "long_exports": 1, "expected_binding": "register_natives"}, "expected": "accept", "code": "ok"},
        {"id": "JNI-UNSUPPORTED-RELOCATION", "operation": "jni_raw_only", "input": {"reason": "unsupported_relocation", "normalized_rows": 0}, "expected": "accept", "code": "ok"},
        {"id": "ZIP-DUP-ASSET-IDENTICAL", "operation": "zip_duplicate", "input": {"path": "zip_duplicate_assets.zip", "member_path": "assets/a.bin", "expected_occurrences": 2, "expected_distinct_ids": 2}, "expected": "accept", "code": "ok"},
        {"id": "AXML-QNAME-SLASH", "operation": "qname", "input": {"namespace": "http://example/한/{x}", "local": "name", "expected": "Q{http%3A%2F%2Fexample%2F%ED%95%9C%2F%7Bx%7D}name"}, "expected": "accept", "code": "ok"},
        {"id": "ARSC-TYPE-ID-OFFSET", "operation": "resource_id", "input": {"package_id": 127, "raw_type_id": 1, "type_id_offset": 2, "entry_id": 1, "expected": "0x7f030001"}, "expected": "accept", "code": "ok"},
        {"id": "FEATURE-XOR-BOTH", "operation": "feature", "input": {"name": "android.hardware.camera", "gl_es_version": 131072}, "expected": "reject", "code": "feature_attribute_xor"},
        {"id": "COMPONENT-MERGE-CONFLICT", "operation": "component_merge", "input": {"explicit_values": ["p:a", "p:b"]}, "expected": "reject", "code": "android_component_merge_conflict"},
        {"id": "PAYLOAD-EXTRA-KEY", "operation": "payload_keys", "input": {"variant": "asset", "keys": ["apk_artifact_id", "archive_entry_record_id", "path", "sha256", "size_bytes", "note"]}, "expected": "reject", "code": "payload_extra_key"},
        {"id": "INTEGER-BOOL", "operation": "integer_domain", "input": {"value": True, "minimum": 0, "maximum": 4294967295}, "expected": "reject", "code": "integer_domain"},
        {"id": "INTEGER-NEGATIVE", "operation": "integer_domain", "input": {"value": -1, "minimum": 0, "maximum": 4294967295}, "expected": "reject", "code": "integer_domain"},
        {"id": "POST-NFC-IDENTITY-COLLISION", "operation": "identity_set", "input": {"values": ["é", "é"]}, "expected": "reject", "code": "post_nfc_identity_collision"},
        {"id": "ARCHIVE-IDENTITY-CHANGE", "operation": "archive_identity", "input": {"original": ["apk", 7], "mutated": ["apk", 9]}, "expected": "reject", "code": "archive_occurrence_identity"},
        {"id": "MALFORMED-NO-PARTIAL", "operation": "inventory_abort", "input": {"required_input_malformed": True, "emitted_rows": 1}, "expected": "reject", "code": "partial_success_forbidden"},
        {"id": "MANIFEST-PARENT-KEYSET", "operation": "payload_keys", "input": {"variant": "manifest_node", "keys": ["apk_artifact_id", "attributes", "event_ordinal", "parent_manifest_node_record_id", "qname", "xpath"]}, "expected": "accept", "code": "ok"},
        {"id": "MANIFEST-PARENT-MISSING", "operation": "payload_keys", "input": {"variant": "manifest_node", "keys": ["apk_artifact_id", "attributes", "event_ordinal", "qname", "xpath"]}, "expected": "reject", "code": "payload_extra_key"},
    ]
    return cases


def write_files(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "elf_semantic_membership.elf": build_elf_fixture(),
        "zip_duplicate_assets.zip": build_duplicate_zip_fixture(),
        "mutf8_cases.bin": bytes.fromhex("01c0800002f09f98800001eda08000"),
        "duplicate_keys.json": b'{"a":1,"a":2}\n',
        "nfc_collision.json": '{"é":1,"é":2}\n'.encode("utf-8"),
        "noncanonical.json": b'{ "b": 2, "a": 1 }\n',
        "cases.json": canonical_json(build_cases()) + b"\n",
    }
    for name, data in sorted(files.items()):
        (output / name).write_bytes(data)
    candidates = {
        "candidate_accept": None,
        "candidate_reject_attachment_hash": "attachment_hash",
        "candidate_reject_bad_locator": "bad_locator",
        "candidate_reject_duplicate_parent": "duplicate_parent",
        "candidate_reject_missing_decision": "missing_decision",
        "candidate_reject_outer_byte": "outer_byte",
        "candidate_reject_review_equality": "review_equality",
        "candidate_reject_command_argv": "command_argv",
        "candidate_reject_bundle_extra": "bundle_extra",
        "candidate_reject_descriptor_type": "descriptor_type",
        "candidate_reject_raw_kind": "raw_kind",
        "candidate_reject_raw_extra": "raw_extra",
        "candidate_reject_source_index_type": "source_index_type",
        "candidate_reject_inventory_type": "inventory_type",
        "candidate_reject_run_type": "run_type",
        "candidate_reject_review_type": "review_type",
        "candidate_reject_record_type": "record_type",
        "candidate_reject_family_relocation": "family_relocation",
    }
    for directory, mutation in candidates.items():
        for relative, data in build_candidate_files(mutation).items():
            path = output / directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    write_files(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
