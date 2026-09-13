#!/usr/bin/env python3
"""Independent validator for the G002 neutral normalization contract.

The implementation uses only Python's standard library and direct file-format
parsing.  It intentionally has no dependency on an inventory producer.
"""

from __future__ import annotations

import argparse
import binascii
import datetime as dt
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import unicodedata
import urllib.parse
import zipfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/g002-neutral-normalization-contract.json"
DEFAULT_FIXTURES = ROOT / "tests/fixtures/g002_neutral"
DEFAULT_MANIFEST = ROOT / ".omx/research/hikmicro-viewer-2.6.0/governance/official-artifacts.json"

# This is the independently reviewed canonical contract byte digest.  It is an
# authority pin, not a replacement for the recursive and semantic checks below.
# The value is updated only when the complete neutral contract and its hostile
# fixtures are reviewed as one unit.
REVIEWED_CONTRACT_SHA256 = "c378fe00e906fbf492d970d3cdc02df30601b416e61449de271ac4433087da29"

CONTRACT_TOP_KEYS = {
    "schema",
    "authority",
    "canonical_json",
    "record_model",
    "counts",
    "elf",
    "dex",
    "callsites",
    "jni",
    "android",
    "provenance",
    "reason_codes",
    "membership_oracles",
    "hostile_fixtures",
}

EXPECTED_AUTHORITY = {
    "artifact_set_id": "hikmicro-viewer-2.6.0-019801077bb42ffb",
    "official_manifest_sha256": "c7d9e466aa20d33142992e101b3824f0c7f2c431c2c5c458eda8bb44e82b4538",
    "official_xapk_sha256": "019801077bb42ffb2d7ca4bda88a87f48324041366d5ade037b7f3bca3616958",
    "official_xapk_size_bytes": 271805591,
    "artifact_count": 121,
    "adjudication_sha256": {
        "elf": "e19256d4d971daeee83acc4a7147fb6e3c62e1e7d7e55b296c0f828a042d22b5",
        "dex_jni": "99741c5846acf119b7dafd2a8be1e228d425866876e8578d9dd12fbff5f84e32",
        "android_provenance": "40c643f51dc2e6dd06d9bf3c52a018005e966736b93d594c33af9c7bb816cecb",
    },
}

EXPECTED_FIXED_TERMS = {
    "frozen_artifact": 121,
    "configuration": 41011,
    "manifest_node": 188,
    "resource": 33431,
    "asset": 762,
    "certificate": 56,
    "android_component": 32,
    "class": 30635,
    "method_family": 184508,
    "native_symbol": 111643,
    "native_export": 99414,
    "native_import": 12627,
    "feature": 3,
}

EXPECTED_CONFIGURATION_TERMS = {
    "xapk_archive_entry": 21,
    "apk_archive_entry": 4314,
    "arm32_native_library": 90,
    "resource_configuration": 36498,
    "native_library_summary": 88,
}

EXPECTED_ELF_COUNTS = {
    "physical_dynsym_entries": 111731,
    "reserved_index_zero": 88,
    "included_nonzero_native_symbol": 111643,
    "unnamed_nonzero_stt_section": 92,
    "defined_global_weak_native_export": 99414,
    "undefined_named_import": 12137,
    "dt_needed": 490,
    "native_import": 12627,
    "java_export": 3227,
}

EXPECTED_DEX_COUNTS = {
    "classes": 30635,
    "defined_methods": 207025,
    "method_families": 184508,
    "native_declarations": 3266,
}

EXPECTED_DEX_PER_ARTIFACT = [
    {"artifact_id": "extracted-dex:classes.dex", "classes": 7786, "defined_methods": 59006, "method_families": 53219, "native_declarations": 15},
    {"artifact_id": "extracted-dex:classes2.dex", "classes": 8746, "defined_methods": 58974, "method_families": 51589, "native_declarations": 2227},
    {"artifact_id": "extracted-dex:classes3.dex", "classes": 9535, "defined_methods": 59102, "method_families": 52845, "native_declarations": 788},
    {"artifact_id": "extracted-dex:classes4.dex", "classes": 4568, "defined_methods": 29943, "method_families": 26855, "native_declarations": 236},
]

EXPECTED_XAPK_ORDER = [
    "com.hikvision.thermalGoogle.apk",
    "icon.png",
    "config.es.apk",
    "config.ja.apk",
    "config.vi.apk",
    "config.zh.apk",
    "config.ar.apk",
    "config.de.apk",
    "config.th.apk",
    "config.tr.apk",
    "config.tvdpi.apk",
    "config.fr.apk",
    "config.it.apk",
    "config.ko.apk",
    "config.my.apk",
    "config.pt.apk",
    "config.en.apk",
    "config.hi.apk",
    "config.in.apk",
    "config.ru.apk",
    "manifest.json",
]

EXPECTED_APK_ENTRY_COUNTS = {
    "com.hikvision.thermalGoogle.apk": 3402,
    "config.ar.apk": 6,
    "config.de.apk": 6,
    "config.en.apk": 6,
    "config.es.apk": 6,
    "config.fr.apk": 6,
    "config.hi.apk": 6,
    "config.in.apk": 6,
    "config.it.apk": 6,
    "config.ja.apk": 8,
    "config.ko.apk": 6,
    "config.my.apk": 6,
    "config.pt.apk": 6,
    "config.ru.apk": 6,
    "config.th.apk": 6,
    "config.tr.apk": 6,
    "config.tvdpi.apk": 799,
    "config.vi.apk": 6,
    "config.zh.apk": 15,
}

EXPECTED_ARCHIVE_CATEGORIES = {
    "AndroidManifest.xml": 19,
    "resources.arsc": 19,
    "dex": 4,
    "arm64": 88,
    "armeabi-v7a": 90,
    "res": 2602,
    "assets": 762,
    "META-INF": 187,
    "other": 543,
}

EXPECTED_PAYLOAD_VARIANTS = {
    "frozen_artifact",
    "configuration:xapk_archive_entry",
    "configuration:apk_archive_entry",
    "configuration:arm32_native_library",
    "configuration:resource_configuration",
    "configuration:native_library_summary",
    "manifest_node",
    "resource",
    "asset",
    "certificate",
    "feature",
    "android_component",
    "class",
    "method_family",
    "reflection_target",
    "dynamic_loader",
    "native_symbol",
    "native_export",
    "native_import:undefined_dynsym",
    "native_import:dt_needed",
    "jni_edge",
}

EXPECTED_RECORD_TYPE_FAMILIES = {
    "android_component": ["android_component"],
    "asset": ["asset"],
    "certificate": ["certificate"],
    "class": ["class"],
    "configuration": [
        "configuration:apk_archive_entry",
        "configuration:arm32_native_library",
        "configuration:native_library_summary",
        "configuration:resource_configuration",
        "configuration:xapk_archive_entry",
    ],
    "dynamic_loader": ["dynamic_loader"],
    "feature": ["feature"],
    "frozen_artifact": ["frozen_artifact"],
    "jni_edge": ["jni_edge"],
    "manifest_node": ["manifest_node"],
    "method_family": ["method_family"],
    "native_export": ["native_export"],
    "native_import": [
        "native_import:dt_needed",
        "native_import:undefined_dynsym",
    ],
    "native_symbol": ["native_symbol"],
    "reflection_target": ["reflection_target"],
    "resource": ["resource"],
}

EXPECTED_PARENT_VARIANTS = {
    "frozen_artifact",
    "configuration:xapk_archive_entry",
    "configuration:apk_archive_entry",
    "configuration:arm32_native_library",
    "configuration:resource_configuration",
    "configuration:native_library_summary",
    "manifest_node:root",
    "manifest_node:nonroot",
    "resource",
    "asset",
    "certificate",
    "feature",
    "android_component:nonalias",
    "android_component:alias",
    "class",
    "method_family",
    "reflection_target",
    "dynamic_loader",
    "native_symbol",
    "native_export",
    "native_import:undefined_dynsym",
    "native_import:dt_needed",
    "jni_edge:static",
    "jni_edge:register_natives",
    "jni_edge:unresolved_declaration",
    "jni_edge:orphan_java_export",
}

LINKED_RESOURCE_SOURCE_EXPRESSION = (
    "linked_resource(payload.resource_record_id).payload.apk_artifact_id"
)


@dataclass(frozen=True)
class SourceDerivation:
    payload_variant: str
    expression: str
    mode: str
    path: tuple[str, ...] = ()
    constant: str | None = None
    linked_payload_variant: str | None = None
    linked_source_path: tuple[str, ...] = ()
    linked_parent_expression: str | None = None


PARENT_RULE_IMPLEMENTATION_REGISTRY: dict[str, tuple[dict[str, str], ...]] = {
    "frozen_artifact": (),
    "configuration:xapk_archive_entry": ({"expression": "frozen:official-xapk", "handler": "source_frozen_seed"}, {"expression": "frozen:exact_xapk_member_match", "handler": "xapk_member_frozen_index"}),
    "configuration:apk_archive_entry": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "frozen:exact_nested_match_if_frozen_namespace", "handler": "apk_entry_nested_frozen_index"}),
    "configuration:arm32_native_library": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "configuration:archive_occurrence", "handler": "direct_payload_record_id"}),
    "configuration:resource_configuration": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "resource:referenced", "handler": "linked_resource_record_id"}),
    "configuration:native_library_summary": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "manifest_node:root": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "configuration:AndroidManifest.xml_occurrence", "handler": "manifest_archive_index"}),
    "manifest_node:nonroot": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "manifest_node:payload.parent_manifest_node_record_id_immediate_parent", "handler": "validated_direct_record_id"}),
    "resource": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "asset": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "configuration:payload.archive_entry_record_id", "handler": "direct_payload_record_id"}),
    "certificate": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "feature": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "manifest_node:payload.declaration_manifest_node_record_id", "handler": "direct_payload_record_id"}),
    "android_component:nonalias": ({"expression": "frozen:canonical_base_member", "handler": "source_frozen_seed"}, {"expression": "manifest_node:all_merge_key_declarations", "handler": "android_declaration_index"}),
    "android_component:alias": ({"expression": "frozen:canonical_base_member", "handler": "source_frozen_seed"}, {"expression": "manifest_node:all_merge_key_declarations", "handler": "android_declaration_index"}, {"expression": "android_component:resolved_target_activity", "handler": "android_target_activity_index"}),
    "class": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "method_family": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "class:declaring", "handler": "class_declaration_index"}),
    "reflection_target": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "class:caller", "handler": "class_declaration_index"}, {"expression": "method_family:caller", "handler": "method_declaration_index"}),
    "dynamic_loader": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "class:caller", "handler": "class_declaration_index"}, {"expression": "method_family:caller", "handler": "method_declaration_index"}),
    "native_symbol": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "native_export": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "native_symbol:payload.native_symbol_record_id", "handler": "direct_payload_record_id"}),
    "native_import:undefined_dynsym": ({"expression": "frozen:source", "handler": "source_frozen_seed"}, {"expression": "native_symbol:payload.native_symbol_record_id", "handler": "direct_payload_record_id"}),
    "native_import:dt_needed": ({"expression": "frozen:source", "handler": "source_frozen_seed"},),
    "jni_edge:static": ({"expression": "frozen:declaration_dex", "handler": "source_frozen_seed"}, {"expression": "class:declaration", "handler": "class_declaration_index"}, {"expression": "method_family:declaration", "handler": "method_declaration_index"}, {"expression": "frozen:endpoint_library", "handler": "endpoint_frozen_seed"}, {"expression": "native_export:selected", "handler": "endpoint_direct_record_id"}),
    "jni_edge:register_natives": ({"expression": "frozen:declaration_dex", "handler": "source_frozen_seed"}, {"expression": "class:declaration", "handler": "class_declaration_index"}, {"expression": "method_family:declaration", "handler": "method_declaration_index"}, {"expression": "frozen:endpoint_library", "handler": "endpoint_frozen_seed"}, {"expression": "native_symbol_or_export:all_endpoint_aliases", "handler": "endpoint_alias_record_ids"}, {"expression": "native_symbol:all_registering_aliases", "handler": "registering_symbol_record_ids"}),
    "jni_edge:unresolved_declaration": ({"expression": "frozen:declaration_dex", "handler": "source_frozen_seed"}, {"expression": "class:declaration", "handler": "class_declaration_index"}, {"expression": "method_family:declaration", "handler": "method_declaration_index"}),
    "jni_edge:orphan_java_export": ({"expression": "frozen:endpoint_library", "handler": "source_frozen_seed"}, {"expression": "native_export:selected", "handler": "endpoint_direct_record_id"}),
}

SOURCE_DERIVATION_SPECS = {
    "frozen_artifact": SourceDerivation(
        "frozen_artifact", "payload artifact_id", "root"
    ),
    "configuration:xapk_archive_entry": SourceDerivation(
        "configuration:xapk_archive_entry",
        "official-xapk",
        "constant",
        constant="official-xapk",
    ),
    "configuration:apk_archive_entry": SourceDerivation(
        "configuration:apk_archive_entry",
        "containing_canonical_apk_member",
        "payload",
        ("container_artifact_id",),
    ),
    "configuration:arm32_native_library": SourceDerivation(
        "configuration:arm32_native_library",
        "containing_canonical_apk_member",
        "payload",
        ("apk_artifact_id",),
    ),
    "configuration:resource_configuration": SourceDerivation(
        "configuration:resource_configuration",
        LINKED_RESOURCE_SOURCE_EXPRESSION,
        "linked",
        ("resource_record_id",),
        linked_payload_variant="resource",
        linked_source_path=("apk_artifact_id",),
        linked_parent_expression="resource:referenced",
    ),
    "configuration:native_library_summary": SourceDerivation(
        "configuration:native_library_summary",
        "payload.library_artifact_id",
        "payload",
        ("library_artifact_id",),
    ),
    "manifest_node:root": SourceDerivation(
        "manifest_node", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "manifest_node:nonroot": SourceDerivation(
        "manifest_node", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "resource": SourceDerivation(
        "resource", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "asset": SourceDerivation(
        "asset", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "certificate": SourceDerivation(
        "certificate", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "feature": SourceDerivation(
        "feature", "payload.apk_artifact_id", "payload", ("apk_artifact_id",)
    ),
    "android_component:nonalias": SourceDerivation(
        "android_component",
        "xapk-apk:com.hikvision.thermalGoogle.apk",
        "constant",
        constant="xapk-apk:com.hikvision.thermalGoogle.apk",
    ),
    "android_component:alias": SourceDerivation(
        "android_component",
        "xapk-apk:com.hikvision.thermalGoogle.apk",
        "constant",
        constant="xapk-apk:com.hikvision.thermalGoogle.apk",
    ),
    "class": SourceDerivation(
        "class", "payload.dex_artifact_id", "payload", ("dex_artifact_id",)
    ),
    "method_family": SourceDerivation(
        "method_family", "payload.dex_artifact_id", "payload", ("dex_artifact_id",)
    ),
    "reflection_target": SourceDerivation(
        "reflection_target",
        "payload.caller.dex_artifact_id",
        "payload",
        ("caller", "dex_artifact_id"),
    ),
    "dynamic_loader": SourceDerivation(
        "dynamic_loader",
        "payload.caller.dex_artifact_id",
        "payload",
        ("caller", "dex_artifact_id"),
    ),
    "native_symbol": SourceDerivation(
        "native_symbol",
        "payload.library_artifact_id",
        "payload",
        ("library_artifact_id",),
    ),
    "native_export": SourceDerivation(
        "native_export",
        "payload.library_artifact_id",
        "payload",
        ("library_artifact_id",),
    ),
    "native_import:undefined_dynsym": SourceDerivation(
        "native_import:undefined_dynsym",
        "payload.library_artifact_id",
        "payload",
        ("library_artifact_id",),
    ),
    "native_import:dt_needed": SourceDerivation(
        "native_import:dt_needed",
        "payload.library_artifact_id",
        "payload",
        ("library_artifact_id",),
    ),
    "jni_edge:static": SourceDerivation(
        "jni_edge",
        "java_declaration.dex_artifact_id",
        "payload",
        ("java_declaration", "dex_artifact_id"),
    ),
    "jni_edge:register_natives": SourceDerivation(
        "jni_edge",
        "java_declaration.dex_artifact_id",
        "payload",
        ("java_declaration", "dex_artifact_id"),
    ),
    "jni_edge:unresolved_declaration": SourceDerivation(
        "jni_edge",
        "java_declaration.dex_artifact_id",
        "payload",
        ("java_declaration", "dex_artifact_id"),
    ),
    "jni_edge:orphan_java_export": SourceDerivation(
        "jni_edge",
        "native_endpoint.library_artifact_id",
        "payload",
        ("native_endpoint", "library_artifact_id"),
    ),
}

EXPECTED_ATTACHMENT_KINDS = {
    "raw/xapk.json": "xapk",
    "raw/apk-entries.json": "apk-entries",
    "raw/manifests.json": "manifests",
    "raw/resources.json": "resources",
    "raw/signing.json": "signing",
    "raw/dex.json": "dex",
    "raw/elf.json": "elf",
    "raw/jni.json": "jni",
}

RAW_ATTACHMENT_FOR_FAMILY = {
    "frozen_artifact": "raw/xapk.json",
    "configuration:xapk_archive_entry": "raw/xapk.json",
    "configuration:apk_archive_entry": "raw/apk-entries.json",
    "configuration:arm32_native_library": "raw/apk-entries.json",
    "asset": "raw/apk-entries.json",
    "manifest_node": "raw/manifests.json",
    "android_component": "raw/manifests.json",
    "feature": "raw/manifests.json",
    "resource": "raw/resources.json",
    "configuration:resource_configuration": "raw/resources.json",
    "certificate": "raw/signing.json",
    "class": "raw/dex.json",
    "method_family": "raw/dex.json",
    "reflection_target": "raw/dex.json",
    "dynamic_loader": "raw/dex.json",
    "native_symbol": "raw/elf.json",
    "native_export": "raw/elf.json",
    "native_import:undefined_dynsym": "raw/elf.json",
    "native_import:dt_needed": "raw/elf.json",
    "configuration:native_library_summary": "raw/elf.json",
    "jni_edge": "raw/jni.json",
}

RAW_NORMALIZED_PRIMITIVE_KIND = {
    "raw/xapk.json": "zip.normalized_record",
    "raw/apk-entries.json": "apk.normalized_record",
    "raw/manifests.json": "android.normalized_record",
    "raw/resources.json": "arsc.normalized_record",
    "raw/signing.json": "signing.normalized_record",
    "raw/dex.json": "dex.normalized_record",
    "raw/elf.json": "elf.normalized_record",
    "raw/jni.json": "jni.normalized_record",
}

EXPECTED_SECTION_DIGESTS = {
    "outer_envelope": "70b0d80b3fb9ddf42a472e6cee5f1132ca173b82abf689ab4363a2a18ae7dbec",
    "payload_schemas": "9c7b78ad327b20c6ea6e264f93f40ddd4775bd5dc5fee6ed9501234a03a4a0a7",
    "record_type_dispatch": "924ed2e79bce0f58bbd4eb74ad8222bb828dec00f33f08143f672d52c12c972b",
    "source_parent_byte_matrix": "b1c07c84af128487f9a8244ae980f921dce0b6a59840ede326c66ca819cbafb7",
    "reflection_target": "ea1263ac0187852964415148541e915216b998b178af4b797a8bd894cf576530",
    "dynamic_loader": "f8a8c268254479f9d732a126a306a72fd3245d439b9a915bdfdb10cf9e48ddac",
    "primitive_slots": "c78223291f032636b70c8ccebf1ae18af0123ee45ff8e45148afb437aee0fc91",
}

EXPECTED_REASON_CODES = {
    "callsite_exclusion": ["not_in_closed_allowlist"],
    "elf_symbol_decision": ["reserved_stn_undef", "included_nonzero_dynsym"],
    "elf_dynamic_decision": [
        "other_dynamic_tag",
        "included_dt_needed",
        "terminator",
        "after_first_dt_null",
    ],
    "jni_exclusion_precedence": [
        "function_region_absent",
        "ambiguous_function_region",
        "analysis_limit_exceeded",
        "unsupported_opcode_on_reaching_path",
        "unsupported_relocation",
        "not_used_as_call_target",
        "jni_environment_not_proven",
        "class_not_proven",
        "runtime_class_not_exact",
        "table_origin_not_static_contiguous",
        "count_not_positive_int32",
        "count_limit_exceeded",
        "table_alignment_invalid",
        "table_section_not_unique",
        "table_range_out_of_bounds",
        "name_pointer_not_resolved",
        "name_not_nul_terminated",
        "name_invalid_mutf8",
        "descriptor_pointer_not_resolved",
        "descriptor_not_nul_terminated",
        "descriptor_invalid_mutf8",
        "descriptor_invalid_grammar",
        "function_pointer_not_resolved",
        "function_not_local_executable",
        "dex_match_none",
        "dex_match_ambiguous",
        "shadowed_by_register_precedence",
        "shadowed_by_short_precedence",
    ],
    "android_exclusion": [
        "alignment_padding",
        "archive_nonsemantic_gap",
        "arsc_library_metadata",
        "arsc_overlayable_metadata",
        "arsc_overlay_policy_metadata",
        "arsc_staged_alias_metadata",
        "signing_non_certificate_pair",
        "signing_source_stamp_material",
        "signing_unselected_metadata",
        "format_metadata_outside_normalized_scope",
    ],
    "normalized_unresolved": [
        "not_statically_resolved",
        "no_static_export_or_proven_register_natives",
        "no_matching_dex_native_declaration",
    ],
    "unknown_reason": "reject",
}

EXPECTED_MEMBERSHIP_DIGESTS = {
    "physical_symbol_decisions_by_manifest_then_index_sha256": "b945f26a858b2bc5b2a0421a066739b9a7d3f4312a51ae0378586aa685193060",
    "normalized_symbol_keys_sorted_sha256": "f3e3587ec55ce6eeb394987ef90a4864e1ba59dac32eb11639b024a47622fc0b",
    "export_symbol_keys_sorted_sha256": "3b8c27900167e5d9591d43377b4cb5bcdc736d8cd9a240f131c6598e27786ad4",
    "undefined_symbol_keys_sorted_sha256": "67c590b5a5ab88095c8f0faccd9c0fa6e8b84556ebaa500ca978a28dddc8602e",
    "dynamic_entry_decisions_by_manifest_then_index_sha256": "ffa5ca45781b36b26d9f97fb2fb3d8e8c45f7c0b7cb284cd380ff6d6aed9b81e",
    "needed_keys_sorted_sha256": "c3bc0c4f335140858b780d0cff767a7b1bd58006d20b135ddc8997d0dc793d90",
    "native_symbol_payloads_sorted_by_record_id_sha256": "69ea003f586027493407c998239c5e80afedc7e62f4ff1de3e75bf7f3723487e",
    "native_export_payloads_sorted_by_record_id_sha256": "39aee67ef721ef2e4b7d0bd64f4f259aa58784fc3680f8e77bea2a7fbe5421cc",
    "native_import_payloads_sorted_by_record_id_sha256": "1f2aa7a574d4758164d28b92a5eae25a3fc00a0a77a05777d59fca079d416987",
    "native_summary_payloads_sorted_by_record_id_sha256": "14c10a6d6dddf99f49f1b234cf5ecbef72ce6bf16990de40a5391dec234d5699",
    "all_elf_record_type_id_payload_sorted_by_record_id_sha256": "5f91cf006f6134dce694628d09474b7f9df2f634515fa7e34631b034d3f5243d",
    "all_elf_record_ids_sorted_sha256": "04041275214a532252105e8ded2a69d280484cd801c7d1e59db29475a9f944f8",
}


class ValidationError(Exception):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ValidationError(code, detail)


def exact_keys(value: Mapping[str, Any], keys: Iterable[str], code: str) -> None:
    expected = set(keys)
    actual = set(value)
    require(actual == expected, code, f"expected={sorted(expected)!r} actual={sorted(actual)!r}")


def normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in result:
                raise ValidationError("json_nfc_key_collision", normalized_key)
            result[normalized_key] = normalize_value(item)
        return result
    return value


def _pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    raw_seen: set[str] = set()
    normalized_seen: set[str] = set()
    for key, value in pairs:
        if key in raw_seen:
            raise ValidationError("json_duplicate_key", key)
        raw_seen.add(key)
        normalized_key = unicodedata.normalize("NFC", key)
        if normalized_key in normalized_seen:
            raise ValidationError("json_nfc_key_collision", normalized_key)
        normalized_seen.add(normalized_key)
        result[normalized_key] = value
    return result


def parse_json_bytes(data: bytes) -> Any:
    try:
        text = data.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("json_invalid_utf8", str(exc)) from exc

    def reject_float(token: str) -> Any:
        raise ValidationError("json_noninteger_number", token)

    def reject_constant(token: str) -> Any:
        raise ValidationError("json_nonfinite_number", token)

    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs_hook,
            parse_float=reject_float,
            parse_constant=reject_constant,
        )
    except ValidationError:
        raise
    except json.JSONDecodeError as exc:
        raise ValidationError("json_syntax", f"line={exc.lineno} column={exc.colno}") from exc
    return normalize_value(value)


def canonical_json_bytes(value: Any) -> bytes:
    normalized = normalize_value(value)
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError("json_not_canonicalizable", str(exc)) from exc


def load_canonical_json(path: Path) -> Any:
    data = path.read_bytes()
    value = parse_json_bytes(data)
    require(data == canonical_json_bytes(value) + b"\n", "json_not_canonical", str(path))
    return value


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _membership_digest(rows: Iterable[Any]) -> dict[str, Any]:
    ordered = sorted(rows, key=canonical_json_bytes)
    return {"count": len(ordered), "sha256": canonical_digest(ordered)}


def raw_membership_oracle(
    raw_documents: Mapping[str, Mapping[str, Any]],
    byte_range_obligations: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Digest exact raw memberships, retaining attachment identity.

    Counts are descriptive only.  Equality of this closed object, including
    every SHA-256, is the authority used by the whole-candidate comparator.
    """

    field_rows = {
        "primitive_ids": lambda document: [row["primitive_id"] for row in document["primitives"]],
        "decisions": lambda document: document["decisions"],
        "facts": lambda document: document["facts"],
        "source_rows": lambda document: document["source_rows"],
        "input_artifact_ids": lambda document: document["input_artifact_ids"],
        "scope_summaries": lambda document: document["scope_summaries"],
    }
    attachments: dict[str, Any] = {}
    global_rows: dict[str, list[Any]] = {key: [] for key in field_rows}
    for path, document in sorted(raw_documents.items()):
        attachment: dict[str, Any] = {}
        for category, select in field_rows.items():
            rows = list(select(document))
            attachment[category] = _membership_digest(rows)
            global_rows[category].extend([[path, row] for row in rows])
        normalized_ids = [
            row["record_id"]
            for row in document["facts"]
            if row.get("fact_kind") == "normalized" and row.get("record_id") is not None
        ]
        attachment["normalized_record_ids"] = _membership_digest(normalized_ids)
        attachments[path] = attachment
    return {
        "schema": "g002-raw-obligation-oracle/v1",
        "global": {
            **{category: _membership_digest(rows) for category, rows in global_rows.items()},
            "byte_ranges": _membership_digest(byte_range_obligations),
        },
        "attachments": attachments,
    }


def compare_raw_obligation_oracles(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    require(actual == expected, "candidate_official_raw_obligation")


def record_id(record_type: str, payload: Any) -> str:
    digest = hashlib.sha256(
        canonical_json_bytes(["g002-record/v1", record_type, payload])
    ).hexdigest().upper()
    return f"INV-{digest}"


def sha256_path(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def sha256_stream(stream: BinaryIO, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    return digest.hexdigest(), total


def _validate_schema_object(schema: Mapping[str, Any], context: str) -> None:
    exact_keys(schema, {"type", "additional_properties", "required", "properties"}, "contract_payload_schema")
    require(schema["type"] == "object", "contract_payload_schema", context)
    require(schema["additional_properties"] is False, "contract_payload_schema", context)
    require(schema["required"] == sorted(schema["properties"]), "contract_payload_schema", context)


SCALAR_SCHEMA_TYPES = {"boolean", "integer", "string", "enum", "null"}


def _validate_schema_definition(
    schema: Mapping[str, Any],
    definitions: Mapping[str, Any],
    context: str,
    stack: tuple[str, ...] = (),
) -> None:
    """Recursively prove that a schema node is closed and every ref resolves."""

    require(isinstance(schema, Mapping), "contract_schema_node", context)
    schema_type = schema.get("type")
    if "ref" in schema:
        exact_keys(schema, {"ref"}, "contract_schema_ref")
        name = schema["ref"]
        require(isinstance(name, str) and name in definitions, "contract_schema_undefined_ref", f"{context}:{name}")
        require(name not in stack, "contract_schema_recursive_ref", f"{context}:{name}")
        _validate_schema_definition(definitions[name], definitions, f"definitions.{name}", stack + (name,))
        return
    require(isinstance(schema_type, str), "contract_schema_type", context)
    if schema_type == "object":
        _validate_schema_object(schema, context)
        for key, child in schema["properties"].items():
            _validate_schema_definition(child, definitions, f"{context}.{key}", stack)
        return
    if schema_type == "array":
        allowed = {"type", "items", "order", "duplicates", "minimum_items", "maximum_items"}
        require(set(schema) <= allowed and "items" in schema, "contract_schema_array", context)
        _validate_schema_definition(schema["items"], definitions, f"{context}[]", stack)
        return
    if schema_type == "nullable":
        exact_keys(schema, {"type", "of"}, "contract_schema_nullable")
        _validate_schema_definition(schema["of"], definitions, f"{context} nullable", stack)
        return
    if schema_type == "union":
        exact_keys(schema, {"type", "variants"}, "contract_schema_union")
        variants = schema["variants"]
        require(isinstance(variants, list) and variants, "contract_schema_union", context)
        require(len(variants) == len(set(variants)), "contract_schema_union_duplicate", context)
        for name in variants:
            require(isinstance(name, str) and name in definitions, "contract_schema_undefined_variant", f"{context}:{name}")
            require(name not in stack, "contract_schema_recursive_ref", f"{context}:{name}")
            _validate_schema_definition(definitions[name], definitions, f"definitions.{name}", stack + (name,))
        return
    if schema_type in SCALAR_SCHEMA_TYPES:
        allowed_by_type = {
            "boolean": {"type"},
            "integer": {"type", "minimum", "maximum", "booleans"},
            "string": {"type", "min_length", "max_length", "pattern"},
            "enum": {"type", "values"},
            "null": {"type"},
        }
        require(set(schema) <= allowed_by_type[schema_type], "contract_schema_scalar", context)
        if schema_type == "enum":
            values = schema.get("values")
            require(isinstance(values, list) and values and len(values) == len({canonical_json_bytes(v) for v in values}), "contract_schema_enum", context)
        return
    raise ValidationError("contract_schema_type", f"{context}:{schema_type}")


def validate_schema_closure(model: Mapping[str, Any]) -> None:
    definitions = model["definitions"]
    require(isinstance(definitions, Mapping) and definitions, "contract_schema_definitions")
    for name, schema in definitions.items():
        require(isinstance(name, str) and name, "contract_schema_definition_name")
        _validate_schema_definition(schema, definitions, f"definitions.{name}", (name,))
    _validate_schema_definition(model["outer_envelope"], definitions, "outer_envelope")
    for name, definition in model["payload_schemas"].items():
        _validate_schema_definition(definition["payload"], definitions, f"payload_schemas.{name}")


def _schema_path_candidates(
    schema: Mapping[str, Any],
    definitions: Mapping[str, Any],
    path: Sequence[str],
    seen_refs: tuple[str, ...] = (),
) -> list[Mapping[str, Any]]:
    if "ref" in schema:
        name = schema["ref"]
        if name in seen_refs or name not in definitions:
            return []
        return _schema_path_candidates(
            definitions[name], definitions, path, seen_refs + (name,)
        )
    schema_type = schema.get("type")
    if schema_type == "nullable":
        return _schema_path_candidates(schema["of"], definitions, path, seen_refs)
    if schema_type == "union":
        candidates: list[Mapping[str, Any]] = []
        for name in schema["variants"]:
            if name not in definitions or name in seen_refs:
                continue
            candidates.extend(
                _schema_path_candidates(
                    definitions[name], definitions, path, seen_refs + (name,)
                )
            )
        return candidates
    if not path:
        return [schema]
    if schema_type != "object":
        return []
    key = path[0]
    if key not in schema.get("required", ()) or key not in schema.get("properties", {}):
        return []
    return _schema_path_candidates(
        schema["properties"][key], definitions, path[1:], seen_refs
    )


def _schema_has_nonempty_string_path(
    schema: Mapping[str, Any],
    definitions: Mapping[str, Any],
    path: Sequence[str],
) -> bool:
    for candidate in _schema_path_candidates(schema, definitions, path):
        if candidate.get("type") != "string":
            continue
        minimum = max(1, candidate.get("min_length", 0))
        maximum = candidate.get("max_length")
        if maximum is None or maximum >= minimum:
            return True
    return False


def validate_record_derivation_consistency(
    contract: Mapping[str, Any],
) -> dict[str, int]:
    """Prove every normalized variant has an executable source/parent rule."""

    model = contract["record_model"]
    payload_schemas = model["payload_schemas"]
    definitions = model["definitions"]
    parent_rows = {
        row["variant"]: row for row in model["source_parent_byte_matrix"]
    }
    require(
        set(parent_rows) == EXPECTED_PARENT_VARIANTS == set(SOURCE_DERIVATION_SPECS) == set(PARENT_RULE_IMPLEMENTATION_REGISTRY),
        "contract_parent_derivation",
    )
    for variant, row in parent_rows.items():
        matrix_expressions = [parent["expression"] for parent in row["parents"]]
        implemented = PARENT_RULE_IMPLEMENTATION_REGISTRY[variant]
        implementation_expressions = [item["expression"] for item in implemented]
        implementation_handlers = [item["handler"] for item in implemented]
        require(
            matrix_expressions == implementation_expressions
            and all(isinstance(handler, str) and handler for handler in implementation_handlers),
            "contract_parent_implementation",
            variant,
        )
    graph_linked = 0
    root_sources = 0
    for variant, derivation in SOURCE_DERIVATION_SPECS.items():
        row = parent_rows[variant]
        require(
            row["source"]
            == {
                "expression": derivation.expression,
                "many": "reject",
                "op": "exact_source_rule",
                "zero": "reject",
            },
            "contract_source_derivation",
            variant,
        )
        require(
            derivation.payload_variant in payload_schemas,
            "contract_source_derivation",
            variant,
        )
        payload_schema = payload_schemas[derivation.payload_variant]["payload"]
        if derivation.mode == "root":
            root_sources += 1
            require(
                variant == "frozen_artifact"
                and not row["parents"]
                and _schema_has_nonempty_string_path(payload_schema, definitions, ()),
                "contract_source_derivation",
                variant,
            )
            continue
        require(row["parents"], "contract_parent_derivation", variant)
        require(
            any(
                parent.get("expression", "").startswith("frozen:")
                for parent in row["parents"]
            ),
            "contract_parent_derivation",
            variant,
        )
        if derivation.mode == "constant":
            require(
                isinstance(derivation.constant, str) and bool(derivation.constant),
                "contract_source_derivation",
                variant,
            )
        elif derivation.mode == "payload":
            require(
                _schema_has_nonempty_string_path(
                    payload_schema, definitions, derivation.path
                ),
                "contract_source_derivation",
                variant,
            )
        elif derivation.mode == "linked":
            graph_linked += 1
            require(
                _schema_has_nonempty_string_path(
                    payload_schema, definitions, derivation.path
                ),
                "contract_source_derivation",
                variant,
            )
            target_variant = derivation.linked_payload_variant
            require(
                target_variant in payload_schemas,
                "contract_source_derivation",
                variant,
            )
            target_schema = payload_schemas[target_variant]["payload"]
            require(
                _schema_has_nonempty_string_path(
                    target_schema, definitions, derivation.linked_source_path
                ),
                "contract_source_derivation",
                variant,
            )
            require(
                any(
                    parent.get("expression") == derivation.linked_parent_expression
                    for parent in row["parents"]
                ),
                "contract_parent_derivation",
                variant,
            )
        else:
            raise ValidationError("contract_source_derivation", variant)
    return {
        "graph_linked_variant_count": graph_linked,
        "parent_variant_count": len(parent_rows),
        "record_variant_count": len(SOURCE_DERIVATION_SPECS),
        "root_source_variant_count": root_sources,
    }


def _schema_error(context: str) -> ValidationError:
    return ValidationError("candidate_schema", context)


def validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    definitions: Mapping[str, Any],
    context: str,
) -> None:
    if "ref" in schema:
        validate_schema_value(value, definitions[schema["ref"]], definitions, context)
        return
    schema_type = schema["type"]
    if schema_type == "nullable":
        if value is None:
            return
        validate_schema_value(value, schema["of"], definitions, context)
        return
    if schema_type == "union":
        matches = 0
        for name in schema["variants"]:
            try:
                validate_schema_value(value, definitions[name], definitions, context)
                matches += 1
            except ValidationError:
                pass
        require(matches == 1, "candidate_union", f"{context}:matches={matches}")
        return
    if schema_type == "object":
        require(isinstance(value, dict), "candidate_schema", context)
        exact_keys(value, schema["required"], "candidate_schema")
        for key, child in schema["properties"].items():
            validate_schema_value(value[key], child, definitions, f"{context}.{key}")
        return
    if schema_type == "array":
        require(isinstance(value, list), "candidate_schema", context)
        if "minimum_items" in schema:
            require(len(value) >= schema["minimum_items"], "candidate_schema", context)
        if "maximum_items" in schema:
            require(len(value) <= schema["maximum_items"], "candidate_schema", context)
        for index, item in enumerate(value):
            validate_schema_value(item, schema["items"], definitions, f"{context}[{index}]")
        encoded = [canonical_json_bytes(item) for item in value]
        if schema.get("duplicates") == "reject":
            require(len(encoded) == len(set(encoded)), "candidate_duplicate", context)
        if schema.get("order") in {"sorted_unique", "canonical_J_unique"}:
            require(encoded == sorted(encoded) and len(encoded) == len(set(encoded)), "candidate_order", context)
        return
    if schema_type == "boolean":
        require(isinstance(value, bool), "candidate_schema", context)
        return
    if schema_type == "integer":
        require(isinstance(value, int) and not isinstance(value, bool), "candidate_schema", context)
        require(schema.get("minimum", value) <= value <= schema.get("maximum", value), "candidate_schema", context)
        return
    if schema_type == "string":
        require(isinstance(value, str), "candidate_schema", context)
        require(len(value) >= schema.get("min_length", 0), "candidate_schema", context)
        require(len(value) <= schema.get("max_length", len(value)), "candidate_schema", context)
        if "pattern" in schema:
            require(re.fullmatch(schema["pattern"], value) is not None, "candidate_schema", context)
        return
    if schema_type == "enum":
        require(value in schema["values"], "candidate_schema", context)
        return
    if schema_type == "null":
        require(value is None, "candidate_schema", context)
        return
    raise _schema_error(context)


def validate_contract(contract: Mapping[str, Any], contract_bytes: bytes | None = None) -> dict[str, Any]:
    if contract_bytes is not None:
        require(
            hashlib.sha256(contract_bytes).hexdigest() == REVIEWED_CONTRACT_SHA256,
            "contract_reviewed_digest",
        )
    exact_keys(contract, CONTRACT_TOP_KEYS, "contract_top_keys")
    require(contract["schema"] == "g002-neutral-normalization-contract/v10", "contract_schema")
    require(contract["authority"] == EXPECTED_AUTHORITY, "contract_authority")

    counts = contract["counts"]
    exact_keys(
        counts,
        {
            "fixed_floor",
            "record_count_equation",
            "fixed_terms",
            "configuration_terms",
            "elf_equations",
            "dex_equations",
            "variable_terms",
        },
        "contract_count_keys",
    )
    require(counts["fixed_terms"] == EXPECTED_FIXED_TERMS, "contract_fixed_terms")
    require(sum(counts["fixed_terms"].values()) == 514431, "contract_fixed_floor_arithmetic")
    require(counts["fixed_floor"] == 514431, "contract_fixed_floor")
    require(counts["configuration_terms"] == EXPECTED_CONFIGURATION_TERMS, "contract_configuration_terms")
    require(sum(counts["configuration_terms"].values()) == 41011, "contract_configuration_arithmetic")
    for key, expected in EXPECTED_ELF_COUNTS.items():
        require(counts["elf_equations"].get(key) == expected, "contract_elf_equations", key)
    require(111731 == 88 + 92 + 99414 + 12137, "contract_elf_partition")
    require(12627 == 12137 + 490, "contract_import_arithmetic")
    require(counts["dex_equations"] == EXPECTED_DEX_COUNTS, "contract_dex_equations")
    require(contract["dex"]["per_artifact_anchors"] == EXPECTED_DEX_PER_ARTIFACT, "contract_dex_per_artifact")
    require(counts["variable_terms"] == ["jni_edge", "reflection_target", "dynamic_loader"], "contract_variable_terms")
    require(
        counts["record_count_equation"]
        == "514431 + jni_edge_count + reflection_target_count + dynamic_loader_count",
        "contract_record_count_equation",
    )

    model = contract["record_model"]
    exact_keys(
        model,
        {
            "outer_envelope",
            "payload_schemas",
            "record_type_dispatch",
            "definitions",
            "comparison_rule",
            "discovered_defaults",
            "outer_byte_families",
            "source_parent_byte_matrix",
        },
        "contract_record_model_keys",
    )
    validate_schema_closure(model)
    _validate_schema_object(model["outer_envelope"], "outer_envelope")
    require(canonical_digest(model["outer_envelope"]) == EXPECTED_SECTION_DIGESTS["outer_envelope"], "contract_outer_envelope")
    require(set(model["payload_schemas"]) == EXPECTED_PAYLOAD_VARIANTS, "contract_payload_union")
    for name, definition in model["payload_schemas"].items():
        exact_keys(definition, {"record_type", "payload"}, "contract_payload_definition")
        payload = definition["payload"]
        if isinstance(payload, dict) and payload.get("type") == "object":
            _validate_schema_object(payload, name)
    require(canonical_digest(model["payload_schemas"]) == EXPECTED_SECTION_DIGESTS["payload_schemas"], "contract_payload_schemas")
    dispatch = model["record_type_dispatch"]
    exact_keys(
        dispatch,
        {"discriminator", "payload_member", "pre_dispatch_union", "record_families"},
        "contract_record_type_dispatch",
    )
    require(dispatch["discriminator"] == "record_type", "contract_record_type_dispatch")
    require(dispatch["payload_member"] == "payload", "contract_record_type_dispatch")
    require(dispatch["pre_dispatch_union"] == "forbidden", "contract_record_type_dispatch")
    require(
        dispatch["record_families"] == EXPECTED_RECORD_TYPE_FAMILIES,
        "contract_record_type_dispatch",
    )
    require(
        canonical_digest(dispatch) == EXPECTED_SECTION_DIGESTS["record_type_dispatch"],
        "contract_record_type_dispatch",
    )
    dispatched_variants: set[str] = set()
    for record_type, variants in dispatch["record_families"].items():
        require(variants == sorted(variants) and variants, "contract_record_type_dispatch", record_type)
        for variant in variants:
            require(variant not in dispatched_variants, "contract_record_type_dispatch", variant)
            require(
                model["payload_schemas"].get(variant, {}).get("record_type") == record_type,
                "contract_record_type_dispatch",
                variant,
            )
            dispatched_variants.add(variant)
    require(dispatched_variants == EXPECTED_PAYLOAD_VARIANTS, "contract_record_type_dispatch")
    parent_matrix = model["source_parent_byte_matrix"]
    require(len(parent_matrix) == len(EXPECTED_PARENT_VARIANTS), "contract_parent_matrix_cardinality")
    require({row["variant"] for row in parent_matrix} == EXPECTED_PARENT_VARIANTS, "contract_parent_matrix_variants")
    for row in parent_matrix:
        exact_keys(row, {"variant", "source", "parents", "byte_owner"}, "contract_parent_matrix_row")
        encoded_parents = [canonical_json_bytes(parent) for parent in row["parents"]]
        require(len(encoded_parents) == len(set(encoded_parents)), "contract_parent_duplicate", row["variant"])
    derivation_summary = validate_record_derivation_consistency(contract)
    require(canonical_digest(parent_matrix) == EXPECTED_SECTION_DIGESTS["source_parent_byte_matrix"], "contract_parent_matrix")
    require(
        model["outer_byte_families"]
        == [
            "configuration:xapk_archive_entry",
            "configuration:apk_archive_entry",
            "configuration:arm32_native_library",
            "asset",
            "certificate",
        ],
        "contract_byte_ownership",
    )

    callsites = contract["callsites"]
    require(callsites["reflection_count"] == 59, "contract_reflection_cardinality")
    require(callsites["loader_count"] == 34, "contract_loader_cardinality")
    require(len(callsites["reflection_target"]) == 59, "contract_reflection_cardinality")
    require(len(callsites["dynamic_loader"]) == 34, "contract_loader_cardinality")
    for family in ("reflection_target", "dynamic_loader"):
        rows = callsites[family]
        for row in rows:
            exact_keys(
                row,
                {"owner", "name", "descriptor", "opcode_family", "owner_policy", "target_recipe"},
                "contract_api_row",
            )
        identities = [(r["owner"], r["name"], r["descriptor"], r["opcode_family"]) for r in rows]
        require(len(identities) == len(set(identities)), "contract_api_duplicate", family)
        require(canonical_digest(rows) == EXPECTED_SECTION_DIGESTS[family], "contract_api_membership", family)
    api_projection = {
        "schema": callsites["api_table_schema"],
        "opcode_families": contract["dex"]["invoke_opcodes"],
        "reflection_target": callsites["reflection_target"],
        "dynamic_loader": callsites["dynamic_loader"],
    }
    require(canonical_digest(api_projection) == callsites["api_table_sha256"], "contract_api_digest")

    require(contract["reason_codes"] == EXPECTED_REASON_CODES, "contract_reason_codes")
    require(contract["membership_oracles"]["digests"] == EXPECTED_MEMBERSHIP_DIGESTS, "contract_membership_oracles")
    require(
        contract["membership_oracles"]["counts"]
        == {
            "physical_dynsym_entries": 111731,
            "native_symbols": 111643,
            "native_exports": 99414,
            "undefined_dynsym_imports": 12137,
            "dt_needed_imports": 490,
            "native_imports": 12627,
            "native_library_summaries": 88,
            "all_elf_derived_normalized_rows_including_summaries": 223772,
        },
        "contract_membership_counts",
    )
    require(
        contract["membership_oracles"]["serialization"]
        == {
            "physical_symbol_decision_labels": ["excluded_reserved_index_zero", "included_nonzero_dynamic_symbol"],
            "dynamic_decision_labels": ["excluded_other_tag_before_null", "included_dt_needed", "excluded_first_dt_null_terminator", "excluded_after_first_dt_null"],
            "note": "oracle labels are frozen digest serialization only; normative raw reason codes are reason_codes.elf_*",
        },
        "contract_membership_serialization",
    )

    require(len(contract["elf"]["large_size_regression_rows"]) == 15, "contract_large_size_rows")
    require(
        canonical_digest(contract["elf"]["large_size_regression_rows"])
        == contract["elf"]["large_size_regression_membership_sha256"],
        "contract_large_size_digest",
    )
    require(contract["elf"]["malformed_policy"] == "abort_complete_inventory_no_partial_rows", "contract_elf_malformed_policy")
    require(contract["dex"]["malformed_policy"] == "abort_complete_inventory_no_partial_rows", "contract_dex_malformed_policy")
    require(contract["callsites"]["malformed_policy"] == "abort_complete_inventory_no_partial_rows", "contract_callsite_malformed_policy")
    require("abort_complete_inventory" in contract["android"]["malformed_policy"], "contract_android_malformed_policy")
    require("abort complete inventory" in contract["provenance"]["malformed_policy"], "contract_provenance_malformed_policy")

    jni_oracle = contract["jni"]["byte_membership_oracles"]
    exact_keys(
        jni_oracle,
        {
            "aarch64_analyzed_function_count",
            "aarch64_unsupported_instruction_count",
            "dex_native_declaration_count",
            "java_export_count",
            "static_short_edge_count",
            "static_long_edge_count",
            "register_natives_edge_count",
            "register_natives_declaration_count",
            "unresolved_declaration_edge_count",
            "orphan_java_export_edge_count",
            "raw_register_natives_candidate_count",
            "declaration_membership_sha256",
            "java_export_endpoint_membership_sha256",
            "jni_edge_payloads_sorted_by_record_id_sha256",
            "jni_edge_record_ids_sorted_sha256",
            "raw_register_natives_candidates_sha256",
            "registration_candidate_decisions_sha256",
            "registration_proven_edges_sha256",
            "registration_exclusions_sha256",
        },
        "contract_jni_oracle_keys",
    )
    jni_count_keys = [key for key in jni_oracle if key.endswith("_count")]
    require(all(type(jni_oracle[key]) is int and jni_oracle[key] >= 0 for key in jni_count_keys), "contract_jni_oracle_count")
    require(
        jni_oracle["dex_native_declaration_count"]
        == jni_oracle["static_short_edge_count"]
        + jni_oracle["static_long_edge_count"]
        + jni_oracle["register_natives_declaration_count"]
        + jni_oracle["unresolved_declaration_edge_count"],
        "contract_jni_declaration_conservation",
    )
    require(
        jni_oracle["register_natives_edge_count"] <= jni_oracle["raw_register_natives_candidate_count"],
        "contract_jni_registration_conservation",
    )
    require(
        all(re.fullmatch(r"[0-9a-f]{64}", value) for key, value in jni_oracle.items() if key.endswith("_sha256")),
        "contract_jni_oracle_digest",
    )
    evaluator = contract["jni"]["registration_evaluator"]
    require(evaluator["stages"] == ["relocation", "function", "cfg", "abi", "table", "class"], "contract_jni_registration_stages")
    require(evaluator["stage_statuses"] == ["proven", "excluded", "not_reached"], "contract_jni_registration_statuses")

    anchor_details = contract["android"]["official_anchor_details"]
    exact_keys(
        anchor_details,
        {
            "xapk_physical_order",
            "apk_entry_counts",
            "archive_categories",
            "base_signing_pair_order",
            "split_signing_pair_order",
            "component_counts",
            "features",
            "resource_package",
            "effective_sdk",
        },
        "contract_android_anchor_keys",
    )
    require(anchor_details["xapk_physical_order"] == EXPECTED_XAPK_ORDER, "contract_xapk_order")
    require(anchor_details["apk_entry_counts"] == EXPECTED_APK_ENTRY_COUNTS, "contract_apk_entry_counts")
    require(anchor_details["archive_categories"] == EXPECTED_ARCHIVE_CATEGORIES, "contract_archive_categories")
    require(sum(anchor_details["apk_entry_counts"].values()) == 4314, "contract_apk_entry_arithmetic")
    require(
        anchor_details["base_signing_pair_order"]
        == ["0x7109871a", "0xf05368c0", "0x6dff800d", "0x2146444e", "0x42726577"],
        "contract_base_signing_order",
    )
    require(
        anchor_details["split_signing_pair_order"]
        == ["0x7109871a", "0xf05368c0", "0x6dff800d", "0x42726577"],
        "contract_split_signing_order",
    )
    require(
        anchor_details["component_counts"]
        == {"application": 1, "activity": 15, "activity_alias": 0, "service": 9, "receiver": 3, "provider": 4},
        "contract_component_counts",
    )
    require(
        anchor_details["features"]
        == [
            {"name": "android.hardware.bluetooth_le", "gl_es_version": None, "required": False},
            {"name": "android.hardware.usb.host", "gl_es_version": None, "required": True},
            {"name": None, "gl_es_version": 131072, "required": True},
        ],
        "contract_feature_anchors",
    )
    require(
        contract["android"]["signing"]["frozen_v2_signed_data_suffix"]
        == "exactly one uint32 zero after the attributes field; any other suffix rejects",
        "contract_v2_suffix",
    )

    raw = contract["provenance"]["raw_attachments"]
    exact_keys(raw, {"family_mapping", "generic_paths", "generic_schema", "schema_locator", "specialized_paths", "primitive_physical_key_slots", "record_bearing_other_json"}, "contract_raw_keys")
    require(raw["generic_paths"] == list(EXPECTED_ATTACHMENT_KINDS), "contract_raw_generic_paths")
    require(raw["specialized_paths"] == {}, "contract_raw_specialized_paths")
    require(raw["schema_locator"] == "record_model.definitions.raw_attachment", "contract_raw_schema_locator")
    locator_value: Any = contract
    for token in raw["schema_locator"].split("."):
        require(isinstance(locator_value, Mapping) and token in locator_value, "contract_raw_schema_locator", token)
        locator_value = locator_value[token]
    require(locator_value == model["definitions"]["raw_attachment"], "contract_raw_schema_locator")
    require(set(raw["family_mapping"]) == set(EXPECTED_ATTACHMENT_KINDS.values()), "contract_attachment_family_mapping")
    for path, kind in EXPECTED_ATTACHMENT_KINDS.items():
        row = raw["family_mapping"][kind]
        exact_keys(row, {"path", "primitive_kind_prefixes", "record_families"}, "contract_attachment_family_row")
        require(row["path"] == path and row["primitive_kind_prefixes"] and row["record_families"], "contract_attachment_family_row", kind)
    require(canonical_digest(raw["primitive_physical_key_slots"]) == EXPECTED_SECTION_DIGESTS["primitive_slots"], "contract_primitive_slots")
    generic_schema = raw["generic_schema"]
    _validate_schema_object(generic_schema, "generic_raw_attachment")
    require(
        set(generic_schema["properties"])
        == {"schema_version", "attachment_kind", "artifact_set_id", "input_artifact_ids", "primitives", "decisions", "facts", "source_rows", "scope_summaries"},
        "contract_generic_raw_schema",
    )
    require(
        contract["provenance"]["source_index"]["row_keys"]
        == sorted(["source_locator", "record_type", "scope_key", "artifact_id", "source_artifact_id", "sha256", "size_bytes", "official_source"]),
        "contract_source_index_row",
    )
    require(
        contract["provenance"]["source_index"]["normalized_fact_order"]
        == "facts are ordered by fact_id; source_rows are ordered by normalized fact_id; source_row_index is the exact zero-based source_rows position",
        "contract_source_index_order",
    )
    require(
        contract["provenance"]["chronology"]["chain"]
        == "run.started_at <= command.started_at < command.ended_at <= attachment.captured_at <= run.ended_at < inventory.generated_at < review.reviewed_at",
        "contract_chronology",
    )
    whole = contract["provenance"]["whole_candidate"]
    exact_keys(
        whole,
        {
            "component_scope_value", "family_membership_serialization", "family_memberships",
            "official_obligation_groups", "public_component_disposition",
            "raw_obligation_equations", "raw_obligation_oracle",
            "raw_obligation_serialization", "required_family_variants", "scope_value",
        },
        "contract_whole_candidate",
    )
    require(whole["scope_value"] == "whole_inventory" and whole["component_scope_value"] == "component", "contract_whole_candidate_scope")
    require(whole["required_family_variants"] == sorted(EXPECTED_PAYLOAD_VARIANTS), "contract_whole_candidate_families")
    require(
        {row["family"]: row["count"] for row in whole["family_memberships"]} == _expected_candidate_family_counts(contract),
        "contract_whole_candidate_counts",
    )
    require(len(whole["family_memberships"]) == len(EXPECTED_PAYLOAD_VARIANTS), "contract_whole_candidate_memberships")
    require(
        whole["raw_obligation_equations"]
        == [
            "candidate raw oracle = official-byte replay raw oracle",
            "primitive IDs, decisions, facts, source rows, inputs, scope summaries, byte ranges, attachment memberships, and normalized record IDs compare exactly",
            "candidate-declared counts and digests are recomputed and are never authority",
            "every designated range resolves through the frozen manifest and equals SHA-256(frozen logical artifact bytes[offset:offset+size])",
        ],
        "contract_raw_obligation_equations",
    )
    require(
        whole["raw_obligation_serialization"]
        == "each membership is sorted by canonical J; SHA-256 authenticates the complete sorted list; attachment path is part of every global member",
        "contract_raw_obligation_serialization",
    )
    raw_oracle = whole["raw_obligation_oracle"]
    exact_keys(raw_oracle, {"schema", "global", "attachments"}, "contract_raw_obligation_oracle")
    require(raw_oracle["schema"] == "g002-raw-obligation-oracle/v1", "contract_raw_obligation_oracle")
    global_categories = {
        "primitive_ids", "decisions", "facts", "source_rows",
        "input_artifact_ids", "scope_summaries", "byte_ranges",
    }
    exact_keys(raw_oracle["global"], global_categories, "contract_raw_obligation_oracle")
    require(set(raw_oracle["attachments"]) == set(EXPECTED_ATTACHMENT_KINDS), "contract_raw_obligation_attachments")
    attachment_categories = global_categories - {"byte_ranges"} | {"normalized_record_ids"}
    for metric in raw_oracle["global"].values():
        exact_keys(metric, {"count", "sha256"}, "contract_raw_obligation_metric")
        require(type(metric["count"]) is int and metric["count"] >= 0, "contract_raw_obligation_metric")
        require(re.fullmatch(r"[0-9a-f]{64}", metric["sha256"]) is not None, "contract_raw_obligation_metric")
    for path, attachment in raw_oracle["attachments"].items():
        exact_keys(attachment, attachment_categories, "contract_raw_obligation_attachment")
        for metric in attachment.values():
            exact_keys(metric, {"count", "sha256"}, "contract_raw_obligation_metric")
            require(type(metric["count"]) is int and metric["count"] >= 0, "contract_raw_obligation_metric")
            require(re.fullmatch(r"[0-9a-f]{64}", metric["sha256"]) is not None, "contract_raw_obligation_metric")
    require(
        {key: raw_oracle["global"][key]["count"] for key in global_categories}
        == {
            "primitive_ids": 519445,
            "decisions": 519445,
            "facts": 519445,
            "source_rows": 519437,
            "input_artifact_ids": 301,
            "scope_summaries": 21,
            "byte_ranges": 121,
        },
        "contract_raw_obligation_counts",
    )

    fixture = contract["hostile_fixtures"]
    exact_keys(
        fixture,
        {"root", "files", "case_file", "cases", "file_tests", "candidate_bundles", "all_cases_mandatory", "generator", "generator_output_must_match_committed_bytes"},
        "contract_fixture_keys",
    )
    require(fixture["root"] == "tests/fixtures/g002_neutral", "contract_fixture_root")
    require(fixture["case_file"] == "cases.json", "contract_fixture_case_file")
    require(fixture["generator"] == "generate_fixtures.py", "contract_fixture_generator")
    require(fixture["all_cases_mandatory"] is True, "contract_fixture_mandatory")
    ids = [row["id"] for key in ("cases", "file_tests", "candidate_bundles") for row in fixture[key]]
    require(len(ids) == len(set(ids)), "contract_fixture_duplicate_id")
    for row in fixture["cases"]:
        exact_keys(row, {"id", "case_index", "expected", "code"}, "contract_fixture_case")
        require(row["expected"] in {"accept", "reject"}, "contract_fixture_expected")
    for row in fixture["file_tests"]:
        exact_keys(row, {"id", "path", "expected", "code"}, "contract_fixture_file_test")
    for row in fixture["candidate_bundles"]:
        exact_keys(row, {"id", "path", "expected", "code"}, "contract_fixture_candidate")
        require(row["expected"] in {"accept", "reject"}, "contract_fixture_expected")

    if contract_bytes is not None:
        forbidden = [rb"g002_" + rb"method_" + rb"[ab]", rb"/tmp/", rb"inventory-[ab]\.json", rb"private[-_ ]lane"]
        for pattern in forbidden:
            require(re.search(pattern, contract_bytes, flags=re.IGNORECASE) is None, "contract_not_neutral", pattern.decode())

    return {
        **derivation_summary,
        "payload_schema_count": len(model["payload_schemas"]),
        "parent_matrix_count": len(parent_matrix),
        "reflection_api_count": len(callsites["reflection_target"]),
        "loader_api_count": len(callsites["dynamic_loader"]),
        "fixture_case_count": len(fixture["cases"]) + len(fixture["file_tests"]) + len(fixture["candidate_bundles"]),
    }


def validate_source_locator(locator: str) -> None:
    require(locator.count("#") == 1, "source_locator_noncanonical")
    attachment, pointer = locator.split("#", 1)
    require(
        attachment in {
            "raw/xapk.json",
            "raw/apk-entries.json",
            "raw/manifests.json",
            "raw/resources.json",
            "raw/dex.json",
            "raw/signing.json",
            "raw/elf.json",
            "raw/jni.json",
        },
        "source_locator_noncanonical",
    )
    require(pointer.startswith("/"), "source_locator_noncanonical")
    tokens = pointer.split("/")[1:]
    require(tokens and tokens[0] == "source_rows", "source_locator_noncanonical")
    require(len(tokens) == 2, "source_locator_noncanonical")
    for token in tokens:
        index = 0
        while index < len(token):
            if token[index] == "~":
                require(index + 1 < len(token) and token[index + 1] in "01", "source_locator_noncanonical")
                index += 2
            else:
                index += 1
    require(re.fullmatch(r"0|[1-9][0-9]*", tokens[1]) is not None, "source_locator_noncanonical")


def parse_timestamp(value: str) -> dt.datetime:
    require(re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value) is not None, "chronology_format")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.timezone.utc)


def validate_chronology(values: Mapping[str, str]) -> None:
    exact_keys(values, {"run_started", "command_started", "command_ended", "captured", "run_ended", "generated", "reviewed"}, "chronology_keys")
    r0 = parse_timestamp(values["run_started"])
    c0 = parse_timestamp(values["command_started"])
    c1 = parse_timestamp(values["command_ended"])
    cap = parse_timestamp(values["captured"])
    r1 = parse_timestamp(values["run_ended"])
    gen = parse_timestamp(values["generated"])
    rev = parse_timestamp(values["reviewed"])
    require(r0 <= c0, "chronology_run_command")
    require(c0 < c1, "chronology_command_order")
    require(c1 <= cap <= r1, "chronology_capture_order")
    require(r1 < gen, "chronology_inventory_not_later")
    require(gen < rev, "chronology_review_not_later")


def _safe_bundle_path(root: Path, value: str) -> Path:
    require(isinstance(value, str) and value and "\\" not in value, "candidate_path")
    pure = Path(value)
    require(not pure.is_absolute() and all(part not in {"", ".", ".."} for part in pure.parts), "candidate_path")
    resolved = (root / pure).resolve()
    require(resolved == root or root in resolved.parents, "candidate_path")
    return resolved


def _load_bound_json(root: Path, descriptor: Mapping[str, Any], context: str) -> Any:
    exact_keys(descriptor, {"path", "media_type", "sha256", "size_bytes"}, "candidate_descriptor")
    require(descriptor["media_type"] == "application/json", "candidate_media_type", context)
    path = _safe_bundle_path(root, descriptor["path"])
    require(path.is_file(), "candidate_missing_attachment", descriptor["path"])
    digest, size = sha256_path(path)
    require((digest, size) == (descriptor["sha256"], descriptor["size_bytes"]), "candidate_attachment_hash", context)
    return load_canonical_json(path)


def _record_variant(record: Mapping[str, Any]) -> str:
    record_type = record["record_type"]
    payload = record["payload"]
    if record_type == "configuration":
        return f"configuration:{payload['configuration_kind']}"
    if record_type == "manifest_node":
        return "manifest_node:root" if payload["parent_manifest_node_record_id"] is None else "manifest_node:nonroot"
    if record_type == "android_component":
        return "android_component:alias" if payload["kind"] == "activity_alias" else "android_component:nonalias"
    if record_type == "native_import":
        return f"native_import:{payload['import_kind']}"
    if record_type == "jni_edge":
        binding = record["payload"]["binding_form"]
        if binding in {"static_short", "static_long"}:
            return "jni_edge:static"
        return f"jni_edge:{binding}"
    return record_type


def _payload_variant(record: Mapping[str, Any]) -> str:
    """Select the common payload schema independently from parent/source shape."""

    record_type = record["record_type"]
    payload = record["payload"]
    if record_type == "configuration":
        return f"configuration:{payload['configuration_kind']}"
    if record_type == "native_import":
        return f"native_import:{payload['import_kind']}"
    return record_type


def validate_jni_edge_payload(
    payload: Mapping[str, Any],
    schema: Mapping[str, Any],
    definitions: Mapping[str, Any],
    context: str,
) -> None:
    """Validate JNI semantics before the generic unions can obscure the cause."""

    require(isinstance(payload, Mapping), "jni_endpoint", context)
    java = payload.get("java_declaration")
    endpoint = payload.get("native_endpoint")
    binding = payload.get("binding_form")
    if isinstance(java, Mapping) and "descriptor" in java:
        try:
            validate_method_descriptor(java["descriptor"])
            class_descriptor = java["class_descriptor"]
            require(
                isinstance(class_descriptor, str)
                and class_descriptor.startswith("L")
                and class_descriptor.endswith(";"),
                "jni_descriptor",
                class_descriptor if isinstance(class_descriptor, str) else context,
            )
        except (KeyError, TypeError):
            raise ValidationError("jni_descriptor", context)
    static = binding in {"static_short", "static_long"}
    if static:
        require(isinstance(java, Mapping) and "descriptor" in java, "jni_endpoint", context)
        require(isinstance(endpoint, Mapping) and endpoint.get("endpoint_kind") == "java_export", "jni_endpoint", context)
        require(payload.get("registration_site") is None and payload.get("resolution_status") == "resolved", "jni_endpoint", context)
    elif binding == "register_natives":
        require(isinstance(java, Mapping) and "descriptor" in java, "jni_endpoint", context)
        require(isinstance(endpoint, Mapping) and endpoint.get("endpoint_kind") == "function_address", "jni_endpoint", context)
        require(isinstance(payload.get("registration_site"), Mapping) and payload.get("resolution_status") == "resolved", "jni_endpoint", context)
    elif binding == "unresolved_declaration":
        require(isinstance(java, Mapping) and "descriptor" in java, "jni_endpoint", context)
        require(isinstance(endpoint, Mapping) and endpoint.get("unresolved_token") == "no_static_export_or_proven_register_natives", "jni_endpoint", context)
        require(payload.get("registration_site") is None and payload.get("resolution_status") == "unresolved", "jni_endpoint", context)
    elif binding == "orphan_java_export":
        require(isinstance(java, Mapping) and java.get("unresolved_token") == "no_matching_dex_native_declaration", "jni_endpoint", context)
        require(isinstance(endpoint, Mapping) and endpoint.get("endpoint_kind") == "java_export", "jni_endpoint", context)
        require(payload.get("registration_site") is None and payload.get("resolution_status") == "orphan", "jni_endpoint", context)
    else:
        raise ValidationError("jni_endpoint", context)
    validate_schema_value(payload, schema, definitions, context)


def validate_candidate_record_schema(
    contract: Mapping[str, Any],
    record: Mapping[str, Any],
    index: int,
) -> str:
    """Execute the full record envelope and the common type payload schema."""

    require(isinstance(record, dict), "candidate_record", str(index))
    model = contract["record_model"]
    definitions = model["definitions"]
    exact_keys(record, set(model["outer_envelope"]["properties"]) | {"payload"}, "candidate_record")
    envelope = {key: record[key] for key in model["outer_envelope"]["properties"]}
    validate_schema_value(envelope, model["outer_envelope"], definitions, f"records[{index}]")
    record_type = record["record_type"]
    record_families = model["record_type_dispatch"]["record_families"]
    require(record_type in record_families, "candidate_payload_variant", record_type)
    payload_variants = record_families[record_type]

    def validate_payload_variant(payload_variant: str) -> None:
        definition = model["payload_schemas"][payload_variant]
        require(record_type == definition["record_type"], "candidate_record_type", payload_variant)
        if payload_variant == "jni_edge":
            validate_jni_edge_payload(
                record["payload"],
                definition["payload"],
                definitions,
                f"records[{index}].payload",
            )
        else:
            validate_schema_value(
                record["payload"],
                definition["payload"],
                definitions,
                f"records[{index}].payload",
            )

    if len(payload_variants) == 1:
        validate_payload_variant(payload_variants[0])
    else:
        matches = 0
        for payload_variant in payload_variants:
            try:
                validate_payload_variant(payload_variant)
                matches += 1
            except ValidationError:
                pass
        require(matches == 1, "candidate_union", f"records[{index}].payload:matches={matches}")
    return _record_variant(record)


def validate_candidate_inventory_schema(
    contract: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> list[str]:
    """Validate inventory structure without executing the generic payload union."""

    require(isinstance(inventory, dict), "candidate_schema", "inventory")
    records = inventory.get("records")
    require(isinstance(records, list), "candidate_schema", "inventory.records")
    model = contract["record_model"]
    definitions = model["definitions"]
    inventory_without_records = dict(inventory)
    inventory_without_records["records"] = []
    validate_schema_value(
        inventory_without_records,
        definitions["inventory_evidence"],
        definitions,
        "inventory",
    )
    return [
        validate_candidate_record_schema(contract, record, index)
        for index, record in enumerate(records)
    ]


def _value_at_payload_path(payload: Any, path: Sequence[str], variant: str) -> str:
    value = payload
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            raise ValidationError("candidate_source_rule", variant)
        value = value[key]
    require(isinstance(value, str) and bool(value), "candidate_source_rule", variant)
    return value


def _linked_resource_source(
    record: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[Mapping[str, Any], str]:
    variant = _record_variant(record)
    linked_id = record["payload"]["resource_record_id"]
    linked = records_by_id.get(linked_id)
    require(linked is not None, "candidate_linked_resource_missing", linked_id)
    require(
        linked.get("record_type") == "resource",
        "candidate_linked_resource_type",
        linked_id,
    )
    linked_payload = linked.get("payload")
    require(
        isinstance(linked_payload, Mapping),
        "candidate_linked_resource_source",
        linked_id,
    )
    linked_source = linked_payload.get("apk_artifact_id")
    require(
        isinstance(linked_source, str)
        and bool(linked_source)
        and linked.get("source_artifact_id") == linked_source,
        "candidate_linked_resource_source",
        linked_id,
    )
    require(variant == "configuration:resource_configuration", "candidate_source_rule", variant)
    return linked, linked_source


def _source_from_payload(
    record: Mapping[str, Any],
    records_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    payload = record["payload"]
    variant = _record_variant(record)
    derivation = SOURCE_DERIVATION_SPECS.get(variant)
    require(derivation is not None, "candidate_source_rule", variant)
    if derivation.mode == "root":
        require(isinstance(payload, str) and bool(payload), "candidate_source_rule", variant)
        return payload
    if derivation.mode == "constant":
        require(
            isinstance(derivation.constant, str) and bool(derivation.constant),
            "candidate_source_rule",
            variant,
        )
        return derivation.constant
    if derivation.mode == "payload":
        return _value_at_payload_path(payload, derivation.path, variant)
    if derivation.mode == "linked":
        return _linked_resource_source(record, records_by_id)[1]
    raise ValidationError("candidate_source_rule", variant)


@dataclass(frozen=True)
class CandidateParentIndex:
    """Immutable record lookup tables for parent-equation validation."""

    records_by_id: Mapping[str, Mapping[str, Any]]
    class_by_declaration: Mapping[tuple[str, str], tuple[str, ...]]
    method_by_declaration: Mapping[tuple[str, str, str, str], tuple[str, ...]]
    manifest_archive_by_apk: Mapping[str, tuple[str, ...]]
    xapk_member_frozen_by_path: Mapping[str, tuple[str, ...]]
    apk_entry_nested_frozen_by_occurrence: Mapping[tuple[str, str, str, int], tuple[str, ...]]
    android_declarations_by_key: Mapping[tuple[str, str, str], tuple[str, ...]]
    android_components_by_key: Mapping[tuple[str, str, str], tuple[str, ...]]


def _tuple_index(values: Mapping[Any, list[str]]) -> dict[Any, tuple[str, ...]]:
    return {key: tuple(sorted(set(items))) for key, items in values.items()}


ANDROID_MANIFEST_NAMESPACE = "http://schemas.android.com/apk/res/android"


def _qname_parts(qname: str) -> tuple[str, str]:
    if qname.startswith("Q{") and "}" in qname:
        namespace, local = qname[2:].split("}", 1)
        return urllib.parse.unquote(namespace), urllib.parse.unquote(local)
    return "", urllib.parse.unquote(qname)


def _qname_local(qname: str) -> str:
    return _qname_parts(qname)[1]


def _manifest_attr(payload: Mapping[str, Any], name: str, namespace: str) -> Any:
    for attr in payload.get("attributes", []):
        if not isinstance(attr, Mapping):
            continue
        attr_namespace, attr_name = _qname_parts(str(attr.get("qname", "")))
        if attr_namespace == namespace and attr_name == name:
            return attr.get("typed_string") if attr.get("typed_string") is not None else attr.get("raw_value")
    return None


def _expand_component_name(package_name: str, name: str) -> str:
    if name.startswith("."):
        return package_name + name
    if "." not in name:
        return f"{package_name}.{name}"
    return name


def _component_manifest_kind(kind: str) -> str:
    return "activity-alias" if kind == "activity_alias" else kind


def _manifest_package_by_apk(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    packages: dict[str, str] = {}
    for record in records:
        if record.get("record_type") != "manifest_node":
            continue
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or _qname_local(str(payload.get("qname", ""))) != "manifest":
            continue
        package = _manifest_attr(payload, "package", "")
        if isinstance(package, str) and package:
            apk = payload.get("apk_artifact_id")
            if isinstance(apk, str) and (apk not in packages or payload.get("parent_manifest_node_record_id") is None):
                packages[apk] = package
    return packages


def _build_parent_lookup_indexes(
    records_by_id: Mapping[str, Mapping[str, Any]],
    frozen_by_artifact: Mapping[str, str],
    official_rows: Mapping[str, Mapping[str, Any]],
) -> CandidateParentIndex:
    class_index: dict[tuple[str, str], list[str]] = defaultdict(list)
    method_index: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    manifest_archive_index: dict[str, list[str]] = defaultdict(list)
    component_decl_index: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    apk_nested_index: dict[tuple[str, str, str, int], list[str]] = defaultdict(list)
    component_index: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    records = tuple(records_by_id.values())
    package_by_apk = _manifest_package_by_apk(records)

    for record in records:
        payload = record["payload"]
        if record["record_type"] == "class":
            class_index[(payload["dex_artifact_id"], payload["descriptor"])].append(record["record_id"])
        elif record["record_type"] == "method_family":
            for definition in payload["definitions"]:
                method_index[(
                    payload["dex_artifact_id"],
                    payload["class_descriptor"],
                    payload["method_name"],
                    definition["descriptor"],
                )].append(record["record_id"])
        elif _record_variant(record) == "configuration:apk_archive_entry" and payload["path"] == "AndroidManifest.xml":
            manifest_archive_index[payload["container_artifact_id"]].append(record["record_id"])
        elif record["record_type"] == "android_component":
            component_index[(payload["kind"], payload["package"], payload["name"])].append(record["record_id"])

    for record in records:
        if record.get("record_type") != "manifest_node":
            continue
        payload = record["payload"]
        kind = _qname_local(payload["qname"])
        apk = payload["apk_artifact_id"]
        package = package_by_apk.get(apk)
        if not package:
            continue
        if kind == "application":
            component_decl_index[("application", package, package)].append(record["record_id"])
            name = _manifest_attr(payload, "name", ANDROID_MANIFEST_NAMESPACE)
            if isinstance(name, str) and name:
                component_decl_index[("application", package, name)].append(record["record_id"])
            continue
        normalized_kind = kind.replace("-", "_")
        if normalized_kind not in {"activity", "activity_alias", "service", "receiver", "provider"}:
            continue
        name = _manifest_attr(payload, "name", ANDROID_MANIFEST_NAMESPACE)
        if isinstance(name, str) and name:
            component_decl_index[(normalized_kind, package, _expand_component_name(package, name))].append(record["record_id"])

    xapk_member_index: dict[str, list[str]] = defaultdict(list)
    official_xapk_path = None
    official_xapk = official_rows.get("official-xapk")
    if isinstance(official_xapk, Mapping):
        official_xapk_source = official_xapk.get("source", {})
        if isinstance(official_xapk_source, Mapping):
            official_xapk_path = official_xapk_source.get("path")
    for artifact_id, artifact in official_rows.items():
        source = artifact.get("source", {})
        if (
            isinstance(source, Mapping)
            and artifact.get("kind") in {"apk_member", "xapk_icon", "xapk_metadata"}
            and source.get("type") == "zip_member"
            and source.get("container_path") == official_xapk_path
            and artifact_id in frozen_by_artifact
        ):
            xapk_member_index[str(source.get("member_path"))].append(frozen_by_artifact[artifact_id])
        if artifact_id in frozen_by_artifact and artifact.get("kind") in {"dex", "native_library", "official_fixture"}:
            path = str(source.get("path", "")) if isinstance(source, Mapping) else ""
            marker = "/evidence/apk/"
            if marker in path:
                entry_path = path.split(marker, 1)[1]
                apk_nested_index[(
                    "xapk-apk:com.hikvision.thermalGoogle.apk",
                    entry_path,
                    artifact["sha256"],
                    artifact["size_bytes"],
                )].append(frozen_by_artifact[artifact_id])

    return CandidateParentIndex(
        records_by_id=records_by_id,
        class_by_declaration=_tuple_index(class_index),
        method_by_declaration=_tuple_index(method_index),
        manifest_archive_by_apk=_tuple_index(manifest_archive_index),
        xapk_member_frozen_by_path=_tuple_index(xapk_member_index),
        apk_entry_nested_frozen_by_occurrence=_tuple_index(apk_nested_index),
        android_declarations_by_key=_tuple_index(component_decl_index),
        android_components_by_key=_tuple_index(component_index),
    )


def _expected_parent_ids(
    record: Mapping[str, Any],
    frozen_by_artifact: Mapping[str, str],
    parent_index: CandidateParentIndex,
    official_rows: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    payload = record["payload"]
    variant = _record_variant(record)
    if variant == "frozen_artifact":
        return []
    source = record["source_artifact_id"]
    require(source in frozen_by_artifact, "candidate_parent_missing_frozen", source)
    parents = [frozen_by_artifact[source]]
    records_by_id = parent_index.records_by_id

    def add_index_matches(matches: Sequence[str], code: str, minimum: int = 1) -> None:
        require(len(matches) >= minimum, code)
        parents.extend(matches)

    if variant == "configuration:xapk_archive_entry":
        matches = parent_index.xapk_member_frozen_by_path.get(payload["path"], ())
        if matches:
            require(len(matches) == 1, "candidate_xapk_member_multiplicity")
            parents.extend(matches)
    elif variant == "configuration:apk_archive_entry":
        nested_key = (
            payload["container_artifact_id"],
            payload["path"],
            payload["sha256"],
            payload["uncompressed_size_bytes"],
        )
        nested_matches = parent_index.apk_entry_nested_frozen_by_occurrence.get(nested_key, ())
        if nested_matches:
            require(len(nested_matches) == 1, "candidate_apk_nested_frozen_multiplicity")
            parents.extend(nested_matches)
    direct_fields: list[str] = []
    if variant in {"asset", "configuration:arm32_native_library"}:
        direct_fields.append("archive_entry_record_id")
    if variant == "configuration:resource_configuration":
        linked, _linked_source = _linked_resource_source(record, records_by_id)
        parents.append(linked["record_id"])
    if variant == "feature":
        direct_fields.append("declaration_manifest_node_record_id")
    if variant == "manifest_node:nonroot":
        parent_path = payload["xpath"].rsplit("/", 1)[0]
        parent_id = payload["parent_manifest_node_record_id"]
        parent = records_by_id.get(parent_id)
        require(
            parent is not None
            and parent["record_type"] == "manifest_node"
            and parent["payload"]["apk_artifact_id"] == payload["apk_artifact_id"]
            and parent["payload"]["xpath"] == parent_path,
            "candidate_manifest_parent",
        )
        parents.append(parent_id)
    elif variant == "manifest_node:root":
        require(payload["parent_manifest_node_record_id"] is None, "candidate_manifest_parent")
        add_index_matches(
            parent_index.manifest_archive_by_apk.get(payload["apk_artifact_id"], ()),
            "candidate_manifest_archive_parent",
        )
    if variant in {"android_component:nonalias", "android_component:alias"}:
        declaration_key = (payload["kind"], payload["package"], payload["package"] if payload["kind"] == "application" else payload["name"])
        add_index_matches(
            parent_index.android_declarations_by_key.get(declaration_key, ()),
            "candidate_component_declaration_parent",
        )
        if variant == "android_component:alias":
            target = payload.get("target_activity")
            require(isinstance(target, str) and target, "candidate_component_target_parent")
            target_matches = parent_index.android_components_by_key.get(("activity", payload["package"], target), ())
            require(len(target_matches) == 1, "candidate_component_target_parent")
            parents.extend(target_matches)
    if record["record_type"] in {"native_export"} or variant == "native_import:undefined_dynsym":
        direct_fields.append("native_symbol_record_id")
    for field in direct_fields:
        parent = payload[field]
        require(parent in records_by_id, "candidate_parent_missing", parent)
        parents.append(parent)
    if record["record_type"] == "method_family":
        add_index_matches(
            parent_index.class_by_declaration.get((payload["dex_artifact_id"], payload["class_descriptor"]), ()),
            "candidate_method_class_parent",
        )
    if record["record_type"] in {"reflection_target", "dynamic_loader"}:
        caller = payload["caller"]
        add_index_matches(
            parent_index.class_by_declaration.get((caller["dex_artifact_id"], caller["class_descriptor"]), ()),
            "candidate_callsite_class_parent",
        )
        add_index_matches(
            parent_index.method_by_declaration.get((caller["dex_artifact_id"], caller["class_descriptor"], caller["method_name"], caller["descriptor"]), ()),
            "candidate_callsite_method_parent",
        )
    if record["record_type"] == "jni_edge":
        java = payload["java_declaration"]
        endpoint = payload["native_endpoint"]
        if payload["binding_form"] == "orphan_java_export":
            require(endpoint["library_artifact_id"] == source, "candidate_source_rule", variant)
            parent = endpoint.get("native_export_record_id")
            require(parent in records_by_id, "candidate_parent_missing")
            parents.append(parent)
            require(len(parents) == len(set(parents)), "candidate_parent_equation_duplicate")
            return sorted(parents)
        if "dex_artifact_id" in java:
            add_index_matches(
                parent_index.class_by_declaration.get((java["dex_artifact_id"], java["class_descriptor"]), ()),
                "candidate_jni_class_parent",
            )
            add_index_matches(
                parent_index.method_by_declaration.get((java["dex_artifact_id"], java["class_descriptor"], java["method_name"], java["descriptor"]), ()),
                "candidate_jni_method_parent",
            )
        if "library_artifact_id" in endpoint:
            require(endpoint["library_artifact_id"] in frozen_by_artifact, "candidate_parent_missing_frozen")
            parents.append(frozen_by_artifact[endpoint["library_artifact_id"]])
        for key in ("native_symbol_record_id", "native_export_record_id"):
            if endpoint.get(key) is not None:
                require(endpoint[key] in records_by_id, "candidate_parent_missing")
                parents.append(endpoint[key])
        for alias in endpoint.get("aliases", []):
            for key in ("native_symbol_record_id", "native_export_record_id"):
                if alias.get(key) is not None:
                    require(alias[key] in records_by_id, "candidate_parent_missing")
                    parents.append(alias[key])
        site = payload.get("registration_site")
        if site is not None:
            for parent in site["registering_symbol_record_ids"]:
                require(parent in records_by_id, "candidate_parent_missing")
                parents.append(parent)
    require(len(parents) == len(set(parents)), "candidate_parent_equation_duplicate")
    return sorted(parents)


def _load_official_manifest_rows(path: Path) -> dict[str, Mapping[str, Any]]:
    manifest = parse_json_bytes(path.read_bytes())
    rows = manifest.get("artifacts") if isinstance(manifest, dict) else None
    require(isinstance(rows, list), "official_manifest_schema")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        aid = row.get("artifact_id") if isinstance(row, dict) else None
        require(isinstance(aid, str) and aid not in result, "official_artifact_ids")
        result[aid] = row
    return result


def _physical_locator(source: Mapping[str, Any]) -> dict[str, Any]:
    source_type = source.get("type")
    if source_type == "file":
        exact_keys(source, {"type", "path"}, "official_manifest_schema")
        return {"type": "file", "path": source["path"]}
    if source_type == "zip_member":
        exact_keys(source, {"type", "container_path", "member_path"}, "official_manifest_schema")
        return {
            "type": "zip_member",
            "container_path": source["container_path"],
            "member_path": source["member_path"],
        }
    raise ValidationError("official_manifest_schema", "artifact source")


def _hash_official_artifact_range(
    artifact: Mapping[str, Any],
    offset: int,
    size: int,
) -> str:
    """Hash a logical frozen-artifact range from its frozen local authority."""

    source = artifact["source"]
    remaining = size
    digest = hashlib.sha256()
    try:
        if source["type"] == "file":
            path = _manifest_file_path(source)
            with path.open("rb") as stream:
                stream.seek(offset)
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    require(bool(chunk), "candidate_raw_byte_bounds", artifact["artifact_id"])
                    digest.update(chunk)
                    remaining -= len(chunk)
        elif source["type"] == "zip_member":
            container = Path(source["container_path"])
            if not container.is_absolute():
                container = ROOT / container
            with zipfile.ZipFile(container) as archive, archive.open(source["member_path"], "r") as stream:
                skipped = 0
                while skipped < offset:
                    chunk = stream.read(min(1024 * 1024, offset - skipped))
                    require(bool(chunk), "candidate_raw_byte_bounds", artifact["artifact_id"])
                    skipped += len(chunk)
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    require(bool(chunk), "candidate_raw_byte_bounds", artifact["artifact_id"])
                    digest.update(chunk)
                    remaining -= len(chunk)
        else:
            raise ValidationError("candidate_raw_byte_authority", artifact["artifact_id"])
    except ValidationError:
        raise
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        raise ValidationError("candidate_raw_byte_authority", artifact.get("artifact_id", str(exc)))
    return digest.hexdigest()


def validate_candidate_byte_range(
    primitive: Mapping[str, Any],
    byte_range: Mapping[str, Any],
    official_rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    artifact_id = byte_range["artifact_id"]
    artifact = official_rows.get(artifact_id)
    require(artifact is not None, "candidate_raw_byte_artifact", artifact_id)
    require(artifact_id in primitive["input_artifact_ids"], "candidate_raw_byte_artifact", artifact_id)
    offset = byte_range["offset_bytes"]
    size = byte_range["size_bytes"]
    require(
        type(offset) is int and type(size) is int and offset >= 0 and size >= 0,
        "candidate_raw_byte_bounds",
        artifact_id,
    )
    artifact_size = artifact["size_bytes"]
    require(offset <= artifact_size and size <= artifact_size - offset, "candidate_raw_byte_bounds", artifact_id)
    actual = _hash_official_artifact_range(artifact, offset, size)
    require(actual == byte_range["sha256"], "candidate_raw_byte_sha256", artifact_id)
    return {
        "artifact_id": artifact_id,
        "physical_locator": _physical_locator(artifact["source"]),
        "offset_bytes": offset,
        "size_bytes": size,
        "sha256": actual,
    }


def _official_payload_source(family: str, payload: Any) -> str:
    if family == "frozen_artifact":
        return payload
    if family == "configuration:xapk_archive_entry":
        return "official-xapk"
    if family == "configuration:apk_archive_entry":
        return payload["container_artifact_id"]
    if family == "configuration:arm32_native_library":
        return payload["apk_artifact_id"]
    if family == "configuration:resource_configuration":
        raise ValidationError("official_raw_obligation_linked_source", family)
    if family == "configuration:native_library_summary":
        return payload["library_artifact_id"]
    if family in {"manifest_node", "resource", "asset", "certificate", "feature"}:
        return payload["apk_artifact_id"]
    if family in {"class", "method_family"}:
        return payload["dex_artifact_id"]
    if family in {"reflection_target", "dynamic_loader"}:
        return payload["caller"]["dex_artifact_id"]
    if family in {"native_symbol", "native_export", "native_import:undefined_dynsym", "native_import:dt_needed"}:
        return payload["library_artifact_id"]
    if family == "android_component":
        return "xapk-apk:com.hikvision.thermalGoogle.apk"
    if family == "jni_edge":
        if payload["binding_form"] == "orphan_java_export":
            return payload["native_endpoint"]["library_artifact_id"]
        return payload["java_declaration"]["dex_artifact_id"]
    raise ValidationError("official_raw_obligation_family", family)


def _official_source_row(
    family: str,
    payload: Any,
    source: str,
    locator: str,
    official_rows: Mapping[str, Mapping[str, Any]],
    record_type: str,
    certificate_sizes: Mapping[str, int],
) -> dict[str, Any]:
    sha256: str | None = None
    size_bytes: int | None = None
    artifact_id: str | None = None
    official_source: Mapping[str, Any] | None = None
    if family == "frozen_artifact":
        artifact = official_rows[source]
        artifact_id = source
        sha256 = artifact["sha256"]
        size_bytes = artifact["size_bytes"]
        official_source = artifact["source"]
    elif family == "certificate":
        sha256 = payload["der_sha256"]
        size_bytes = certificate_sizes[sha256]
    elif family in {
        "configuration:xapk_archive_entry",
        "configuration:apk_archive_entry",
        "configuration:arm32_native_library",
        "asset",
    }:
        sha256 = payload["sha256"]
        size_key = "size_bytes" if "size_bytes" in payload else "uncompressed_size_bytes"
        size_bytes = payload[size_key]
    return {
        "source_locator": locator,
        "record_type": record_type,
        "scope_key": canonical_json_bytes(payload).decode("utf-8"),
        "artifact_id": artifact_id,
        "source_artifact_id": source,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "official_source": official_source,
    }


def build_official_raw_obligation_oracle(
    contract: Mapping[str, Any],
    family_payloads: Mapping[str, Sequence[Any]],
    artifacts: Sequence[Mapping[str, Any]],
    derivation_groups: Mapping[str, Any],
    certificate_sizes: Mapping[str, int],
) -> dict[str, Any]:
    """Replay the v9 canonical raw derivation obligations from official bytes."""

    official_rows = {row["artifact_id"]: row for row in artifacts}
    root_primitive_ids: dict[str, str] = {}
    root_primitives: dict[str, Mapping[str, Any]] = {}
    byte_obligations: list[Mapping[str, Any]] = []
    for artifact_id, artifact in sorted(official_rows.items()):
        byte_range = {
            "artifact_id": artifact_id,
            "offset_bytes": 0,
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
        }
        preimage = [
            "g002-primitive/v1", "xapk", "artifact.bytes", "artifact",
            [artifact_id], [artifact_id], [byte_range], [],
        ]
        primitive_id = "PRM-" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest().upper()
        root_primitive_ids[artifact_id] = primitive_id
        root_primitives[artifact_id] = {
            "primitive_id": primitive_id,
            "primitive_kind": "artifact.bytes",
            "origin": "artifact",
            "input_artifact_ids": [artifact_id],
            "physical_key": [artifact_id],
            "byte_ranges": [byte_range],
            "dependency_primitive_ids": [],
        }
        byte_obligations.append({
            "attachment_path": "raw/xapk.json",
            "primitive_id": primitive_id,
            "primitive_kind": "artifact.bytes",
            "physical_key": [artifact_id],
            "artifact_id": artifact_id,
            "physical_locator": _physical_locator(artifact["source"]),
            "offset_bytes": 0,
            "size_bytes": artifact["size_bytes"],
            "sha256": artifact["sha256"],
        })

    documents: dict[str, dict[str, Any]] = {
        path: {
            "schema_version": "g002-raw-attachment/v1",
            "attachment_kind": kind,
            "artifact_set_id": contract["authority"]["artifact_set_id"],
            "input_artifact_ids": [],
            "primitives": [],
            "decisions": [],
            "facts": [],
            "source_rows": [],
            "scope_summaries": [],
        }
        for path, kind in EXPECTED_ATTACHMENT_KINDS.items()
    }
    records_by_path: dict[str, list[tuple[str, str, str, Any, str]]] = defaultdict(list)
    resource_source_by_id = {
        record_id("resource", payload): payload["apk_artifact_id"]
        for payload in family_payloads["resource"]
    }
    for family, payloads in family_payloads.items():
        path = RAW_ATTACHMENT_FOR_FAMILY[family]
        record_type = contract["record_model"]["payload_schemas"][family]["record_type"]
        for payload in payloads:
            rid = record_id(record_type, payload)
            source = (
                resource_source_by_id[payload["resource_record_id"]]
                if family == "configuration:resource_configuration"
                else _official_payload_source(family, payload)
            )
            require(source in official_rows, "official_raw_obligation_source", f"{family}:{source!r}")
            records_by_path[path].append((rid, family, record_type, payload, source))

    for path, rows in sorted(records_by_path.items()):
        document = documents[path]
        for source in sorted({row[4] for row in rows}):
            document["input_artifact_ids"].append(source)
        normalized_rows = []
        for rid, family, record_type, payload, source in rows:
            fact_id = "FCT-" + hashlib.sha256(canonical_json_bytes(["g002-fact/v1", rid])).hexdigest().upper()
            normalized_rows.append((fact_id, rid, family, record_type, payload, source))
        for index, (fact_id, rid, family, record_type, payload, source) in enumerate(sorted(normalized_rows)):
            if family == "frozen_artifact":
                primitive = root_primitives[source]
            else:
                primitive_kind = RAW_NORMALIZED_PRIMITIVE_KIND[path]
                dependency_ids = [root_primitive_ids[source]]
                preimage = [
                    "g002-primitive/v1", document["attachment_kind"], primitive_kind,
                    "derived", [source], [family, rid], [], dependency_ids,
                ]
                primitive_id = "PRM-" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest().upper()
                primitive = {
                    "primitive_id": primitive_id,
                    "primitive_kind": primitive_kind,
                    "origin": "derived",
                    "input_artifact_ids": [source],
                    "physical_key": [family, rid],
                    "byte_ranges": [],
                    "dependency_primitive_ids": dependency_ids,
                }
            primitive_id = primitive["primitive_id"]
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
                "record_type": record_type,
                "scope_key": canonical_json_bytes(payload).decode("utf-8"),
                "validation_code": None,
                "dependency_primitive_ids": [primitive_id],
                "source_row_index": index,
            })
            locator = f"{path}#/source_rows/{index}"
            document["source_rows"].append(
                _official_source_row(
                    family, payload, source, locator, official_rows, record_type,
                    certificate_sizes,
                )
            )
        family_counts = Counter(row[1] for row in rows)
        document["scope_summaries"].extend({
            "scope": family,
            "observed_count": count,
            "included_count": count,
            "excluded_count": 0,
            "accounted_count": count,
            "normalized_record_count": count,
            "unaccounted_count": 0,
        } for family, count in sorted(family_counts.items()))

    for path, value in sorted(derivation_groups.items()):
        document = documents[path]
        digest = canonical_digest(value)
        inputs = sorted(document["input_artifact_ids"])
        dependency_ids = sorted(root_primitive_ids[artifact_id] for artifact_id in inputs)
        primitive_kind = RAW_NORMALIZED_PRIMITIVE_KIND[path].rsplit(".", 1)[0] + ".official_obligation"
        physical_key = [path, digest]
        preimage = [
            "g002-primitive/v1", document["attachment_kind"], primitive_kind,
            "derived", inputs, physical_key, [], dependency_ids,
        ]
        primitive_id = "PRM-" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest().upper()
        fact_id = "FCT-" + hashlib.sha256(
            canonical_json_bytes(["g002-obligation-fact/v1", path, digest])
        ).hexdigest().upper()
        document["primitives"].append({
            "primitive_id": primitive_id,
            "primitive_kind": primitive_kind,
            "origin": "derived",
            "input_artifact_ids": inputs,
            "physical_key": physical_key,
            "byte_ranges": [],
            "dependency_primitive_ids": dependency_ids,
        })
        document["decisions"].append({
            "primitive_id": primitive_id,
            "disposition": "support",
            "fact_ids": [fact_id],
            "reason_code": None,
        })
        document["facts"].append({
            "fact_id": fact_id,
            "fact_kind": "validation",
            "record_id": None,
            "record_type": None,
            "scope_key": None,
            "validation_code": f"official_obligation:{digest}",
            "dependency_primitive_ids": [primitive_id],
            "source_row_index": None,
        })

    for document in documents.values():
        document["input_artifact_ids"] = sorted(set(document["input_artifact_ids"]))
        document["facts"].sort(key=lambda row: row["fact_id"])
    return raw_membership_oracle(documents, byte_obligations)


def validate_candidate_parent_equations(
    contract: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    records_by_id: Mapping[str, Mapping[str, Any]],
    official_manifest: Path,
) -> None:
    """Validate candidate byte/source parent equations using the public candidate path."""

    official_rows = _load_official_manifest_rows(official_manifest)
    frozen_by_artifact = {
        record["payload"]: record["record_id"]
        for record in records
        if record["record_type"] == "frozen_artifact"
    }
    parent_index = _build_parent_lookup_indexes(records_by_id, frozen_by_artifact, official_rows)
    byte_families = set(contract["record_model"]["outer_byte_families"])
    for record in records:
        variant = _record_variant(record)
        if variant == "frozen_artifact":
            artifact = official_rows.get(record["payload"])
            require(artifact is not None, "candidate_unknown_frozen_artifact", record["payload"])
            require(record["artifact_id"] == record["payload"], "candidate_frozen_artifact_id")
            require((record["sha256"], record["size_bytes"], record["official_source"]) == (artifact["sha256"], artifact["size_bytes"], artifact["source"]), "candidate_frozen_bytes")
        elif variant in byte_families:
            require(record["sha256"] is not None and record["size_bytes"] is not None, "candidate_outer_byte_policy")
            require(record["official_source"] is None, "candidate_official_source_policy")
            if isinstance(record["payload"], dict) and "sha256" in record["payload"]:
                require(record["payload"]["sha256"] == record["sha256"], "candidate_outer_byte_equation")
            size_key = "size_bytes" if "size_bytes" in record["payload"] else "uncompressed_size_bytes"
            if size_key in record["payload"]:
                require(record["payload"][size_key] == record["size_bytes"], "candidate_outer_byte_equation")
        else:
            require(record["sha256"] is None and record["size_bytes"] is None and record["official_source"] is None, "candidate_structural_bytes")
        expected_parents = _expected_parent_ids(record, frozen_by_artifact, parent_index, official_rows)
        require(record["parent_record_ids"] == expected_parents, "candidate_parent_set", variant)
        require(all(parent != record["record_id"] for parent in expected_parents), "candidate_parent_self")


def validate_candidate_bundle_components(
    contract: Mapping[str, Any],
    bundle_root: Path,
    official_manifest: Path,
) -> dict[str, Any]:
    """Validate one bundle below the public whole-inventory completeness gate."""

    root = bundle_root.resolve()
    require(root.is_dir(), "candidate_bundle_root")
    manifest_path = root / "bundle.json"
    bundle = load_canonical_json(manifest_path)
    definitions = contract["record_model"]["definitions"]
    validate_schema_value(bundle, definitions["candidate_bundle_evidence"], definitions, "bundle")
    require(bundle["schema"] == "g002-candidate-bundle/v2", "candidate_bundle_schema")
    require(bundle["artifact_set_id"] == contract["authority"]["artifact_set_id"], "candidate_artifact_set")
    require(isinstance(bundle["bundle_id"], str) and bundle["bundle_id"], "candidate_bundle_id")
    require(isinstance(bundle["operator_id"], str) and bundle["operator_id"], "candidate_operator")

    inventory = _load_bound_json(root, bundle["inventory"], "inventory")
    source_index = _load_bound_json(root, bundle["source_index"], "source-index")
    run = _load_bound_json(root, bundle["run"], "run")
    command = _load_bound_json(root, bundle["command"], "command")
    review = _load_bound_json(root, bundle["review"], "review")
    raw_descriptors = bundle["raw_attachments"]
    require(isinstance(raw_descriptors, list) and raw_descriptors, "candidate_raw_attachments")
    raw_paths = [row.get("path") for row in raw_descriptors if isinstance(row, dict)]
    require(len(raw_paths) == len(raw_descriptors) == len(set(raw_paths)), "candidate_duplicate_attachment")
    expected_raw_paths = set(EXPECTED_ATTACHMENT_KINDS)
    require(set(raw_paths) == expected_raw_paths, "candidate_attachment_topology")
    raw_documents: dict[str, Mapping[str, Any]] = {}
    captured_times: list[str] = []
    for descriptor in raw_descriptors:
        validate_schema_value(descriptor, definitions["raw_attachment_descriptor"], definitions, "raw descriptor")
        require(EXPECTED_ATTACHMENT_KINDS.get(descriptor["path"]) == descriptor["attachment_kind"], "candidate_attachment_family", descriptor["path"])
        basic = {key: descriptor[key] for key in ("path", "media_type", "sha256", "size_bytes")}
        document = _load_bound_json(root, basic, descriptor["path"])
        require(isinstance(document, dict), "candidate_raw_schema", descriptor["path"])
        raw_documents[descriptor["path"]] = document
        captured_times.append(descriptor["captured_at"])
        parse_timestamp(descriptor["captured_at"])
        require(document.get("attachment_kind") == descriptor["attachment_kind"], "candidate_attachment_kind")

    record_variants = validate_candidate_inventory_schema(contract, inventory)
    require(inventory["schema"] == "g002-normalized-inventory/v2", "candidate_inventory_schema")
    require(inventory["scope"] == bundle["candidate_scope"], "candidate_bundle_crosswire")
    require(inventory["artifact_set_id"] == bundle["artifact_set_id"] and inventory["bundle_id"] == bundle["bundle_id"], "candidate_bundle_crosswire")
    records = inventory["records"]
    require(isinstance(records, list), "candidate_inventory_records")
    payload_schemas = contract["record_model"]["payload_schemas"]
    ids: list[str] = []
    scope_pairs: list[tuple[str, str]] = []
    records_by_id: dict[str, Mapping[str, Any]] = {}
    for record, variant in zip(records, record_variants):
        require(record["scope_key"] == canonical_json_bytes(record["payload"]).decode("utf-8"), "candidate_scope_key")
        require(record["record_id"] == record_id(record["record_type"], record["payload"]), "candidate_record_id")
        parent_ids = record["parent_record_ids"]
        require(len(parent_ids) == len(set(parent_ids)), "candidate_duplicate_parent", record["record_id"])
        require(parent_ids == sorted(parent_ids), "candidate_parent_order", record["record_id"])
        ids.append(record["record_id"])
        scope_pairs.append((record["record_type"], record["scope_key"]))
        require(record["record_id"] not in records_by_id, "candidate_duplicate_record_id")
        records_by_id[record["record_id"]] = record
    require(ids == sorted(ids), "candidate_record_order")
    require(len(ids) == len(set(ids)) == len(records_by_id), "candidate_duplicate_record_id")
    require(len(scope_pairs) == len(set(scope_pairs)), "candidate_duplicate_scope")
    for record, variant in zip(records, record_variants):
        if variant == "configuration:resource_configuration":
            _linked_resource_source(record, records_by_id)
    for record, variant in zip(records, record_variants):
        require(
            record["source_artifact_id"] == _source_from_payload(record, records_by_id),
            "candidate_source_rule",
            variant,
        )

    validate_candidate_parent_equations(contract, records, records_by_id, official_manifest)
    official_rows = _load_official_manifest_rows(official_manifest)

    validate_schema_value(source_index, definitions["source_index_evidence"], definitions, "source-index")
    require(source_index["schema_version"] == "g002-source-index/v2" and source_index["bundle_id"] == bundle["bundle_id"], "candidate_source_index_schema")
    index_rows = source_index["rows"]
    require(isinstance(index_rows, list), "candidate_source_index_schema")
    locators = [row.get("source_locator") for row in index_rows if isinstance(row, dict)]
    require(locators == sorted(locators) and len(locators) == len(set(locators)), "candidate_source_locator_order")

    all_primitive_ids: list[str] = []
    all_decision_ids: list[str] = []
    all_fact_ids: list[str] = []
    normalized_facts: list[Mapping[str, Any]] = []
    all_input_artifact_ids: set[str] = set()
    all_scope_summaries: list[Mapping[str, Any]] = []
    byte_range_obligations: list[Mapping[str, Any]] = []
    raw_source_rows: dict[str, Mapping[str, Any]] = {}
    raw_source_record_digests: dict[str, str] = {}
    generic_schema = contract["provenance"]["raw_attachments"]["generic_schema"]
    for path, document in raw_documents.items():
        validate_schema_value(document, generic_schema, definitions, path)
        kind = EXPECTED_ATTACHMENT_KINDS[path]
        family_rule = contract["provenance"]["raw_attachments"]["family_mapping"][kind]
        require(document["attachment_kind"] == kind and family_rule["path"] == path, "candidate_attachment_family", path)
        require(document["artifact_set_id"] == bundle["artifact_set_id"], "candidate_artifact_set")
        all_input_artifact_ids.update(document["input_artifact_ids"])
        primitives = document["primitives"]
        decisions = document["decisions"]
        facts = document["facts"]
        primitive_ids = [row["primitive_id"] for row in primitives]
        decision_ids = [row["primitive_id"] for row in decisions]
        require(len(primitive_ids) == len(set(primitive_ids)), "candidate_duplicate_primitive")
        require(len(decision_ids) == len(set(decision_ids)), "candidate_duplicate_decision")
        require(set(primitive_ids) == set(decision_ids), "candidate_primitive_decision_bijection")
        for primitive in primitives:
            require(
                any(primitive["primitive_kind"].startswith(prefix) for prefix in family_rule["primitive_kind_prefixes"]),
                "candidate_attachment_family",
                f"{path}:{primitive['primitive_kind']}",
            )
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
            expected_primitive_id = "PRM-" + hashlib.sha256(canonical_json_bytes(preimage)).hexdigest().upper()
            require(primitive["primitive_id"] == expected_primitive_id, "candidate_primitive_id")
            slots = contract["provenance"]["raw_attachments"]["primitive_physical_key_slots"].get(primitive["primitive_kind"])
            require(slots is not None, "candidate_raw_physical_key", primitive["primitive_kind"])
            require(len(primitive["physical_key"]) == len(slots), "candidate_raw_physical_key", primitive["primitive_kind"])
            require(
                set(primitive["input_artifact_ids"]) <= set(document["input_artifact_ids"]),
                "candidate_raw_input_artifact",
            )
            for byte_range in primitive["byte_ranges"]:
                validated_range = validate_candidate_byte_range(primitive, byte_range, official_rows)
                require(
                    primitive["physical_key"] and primitive["physical_key"][0] == byte_range["artifact_id"],
                    "candidate_raw_physical_key",
                    primitive["primitive_kind"],
                )
                byte_range_obligations.append({
                    "attachment_path": path,
                    "primitive_id": primitive["primitive_id"],
                    "primitive_kind": primitive["primitive_kind"],
                    "physical_key": primitive["physical_key"],
                    **validated_range,
                })
            if primitive["origin"] == "artifact":
                require(len(primitive["byte_ranges"]) == 1 and primitive["byte_ranges"][0]["offset_bytes"] == 0 and not primitive["dependency_primitive_ids"], "candidate_primitive_origin")
                byte_range = primitive["byte_ranges"][0]
                require(
                    primitive["physical_key"] == [byte_range["artifact_id"]]
                    and primitive["input_artifact_ids"] == [byte_range["artifact_id"]],
                    "candidate_raw_physical_key",
                )
                artifact = official_rows[byte_range["artifact_id"]]
                require(
                    byte_range["size_bytes"] == artifact["size_bytes"]
                    and byte_range["sha256"] == artifact["sha256"],
                    "candidate_raw_byte_obligation",
                    byte_range["artifact_id"],
                )
            elif primitive["origin"] == "occurrence":
                require(primitive["byte_ranges"] and primitive["dependency_primitive_ids"], "candidate_primitive_origin")
            else:
                require(primitive["dependency_primitive_ids"], "candidate_primitive_origin")
        require(
            all(artifact_id in official_rows for artifact_id in document["input_artifact_ids"]),
            "candidate_raw_input_artifact",
            path,
        )
        fact_by_id = {row["fact_id"]: row for row in facts}
        require(len(fact_by_id) == len(facts), "candidate_duplicate_fact")
        cited: list[str] = []
        for decision in decisions:
            if decision["disposition"] == "excluded":
                require(decision["fact_ids"] == [] and decision["reason_code"] is not None, "candidate_decision_semantics")
            else:
                require(decision["fact_ids"] and decision["reason_code"] is None, "candidate_decision_semantics")
            cited.extend(decision["fact_ids"])
        require(len(cited) == len(set(cited)) and set(cited) == set(fact_by_id), "candidate_fact_exact_once")
        citing_primitive_by_fact = {
            fact_id: decision["primitive_id"]
            for decision in decisions
            for fact_id in decision["fact_ids"]
        }
        require(facts == sorted(facts, key=lambda row: row["fact_id"]), "candidate_fact_order")
        normalized_in_document = [row for row in facts if row["fact_kind"] == "normalized"]
        for fact in facts:
            require(citing_primitive_by_fact[fact["fact_id"]] in fact["dependency_primitive_ids"], "candidate_fact_dependency")
            if fact["fact_kind"] == "normalized":
                require(fact["record_id"] is not None and fact["record_type"] is not None and fact["scope_key"] is not None and fact["validation_code"] is None and fact["source_row_index"] is not None, "candidate_fact_semantics")
                target_record = records_by_id.get(fact["record_id"])
                require(target_record is not None, "candidate_fact_record_bijection")
                require(_payload_variant(target_record) in family_rule["record_families"], "candidate_attachment_family", f"{path}:{_payload_variant(target_record)}")
            else:
                require(fact["record_id"] is None and fact["record_type"] is None and fact["scope_key"] is None and fact["validation_code"] is not None and fact["source_row_index"] is None, "candidate_fact_semantics")
        for row in document["source_rows"]:
            locator = row["source_locator"]
            require(locator not in raw_source_rows, "candidate_duplicate_locator")
            validate_source_locator(locator)
            attachment, pointer = locator.split("#", 1)
            require(attachment == path, "candidate_locator_attachment")
            index = int(pointer.rsplit("/", 1)[1])
            require(index < len(document["source_rows"]) and document["source_rows"][index] == row, "candidate_locator_dereference")
            raw_source_rows[locator] = row
            raw_source_record_digests[locator] = hashlib.sha256(canonical_json_bytes(row)).hexdigest()
        all_primitive_ids.extend(primitive_ids)
        all_decision_ids.extend(decision_ids)
        all_fact_ids.extend(fact_by_id)
        normalized_facts.extend(row for row in facts if row["fact_kind"] == "normalized")
        require([row["source_row_index"] for row in normalized_in_document] == list(range(len(document["source_rows"]))), "candidate_source_row_fact_order")
        for index, fact in enumerate(normalized_in_document):
            target_record = records_by_id[fact["record_id"]]
            source_row = document["source_rows"][index]
            projection_keys = (
                "record_type", "scope_key", "artifact_id", "source_artifact_id",
                "sha256", "size_bytes", "official_source",
            )
            require(
                {key: source_row[key] for key in projection_keys}
                == {key: target_record[key] for key in projection_keys},
                "candidate_source_row_fact_binding",
            )
        for summary in document["scope_summaries"]:
            require(summary["observed_count"] == summary["included_count"] + summary["excluded_count"], "candidate_scope_equation")
            require(summary["accounted_count"] == summary["observed_count"] and summary["unaccounted_count"] == 0, "candidate_scope_equation")
            all_scope_summaries.append(summary)
    require(len(all_primitive_ids) == len(set(all_primitive_ids)), "candidate_global_primitive_duplicate")
    require(len(all_decision_ids) == len(set(all_decision_ids)), "candidate_global_decision_duplicate")
    require(len(all_fact_ids) == len(set(all_fact_ids)), "candidate_global_fact_duplicate")
    all_primitive_id_set = set(all_primitive_ids)
    for document in raw_documents.values():
        for primitive in document["primitives"]:
            require(
                set(primitive["dependency_primitive_ids"]) <= all_primitive_id_set,
                "candidate_raw_dependency",
            )

    require(len(index_rows) == len(raw_source_rows), "candidate_source_bijection")
    index_by_locator: dict[str, Mapping[str, Any]] = {}
    for row in index_rows:
        validate_schema_value(row, definitions["source_index_row"], definitions, "source-index row")
        locator = row["source_locator"]
        require(locator in raw_source_rows and raw_source_rows[locator] == row, "candidate_source_index_dereference")
        index_by_locator[locator] = row
    normalized_refs: list[tuple[str, Mapping[str, Any]]] = []
    for record in records:
        require(len(record["source_refs"]) == 1, "candidate_source_ref_cardinality", record["record_id"])
        ref = record["source_refs"][0]
        require(ref["bundle_id"] == bundle["bundle_id"], "candidate_source_ref_bundle")
        locator = ref["source_locator"]
        require(locator in index_by_locator, "candidate_source_ref_locator")
        require(ref["source_record_sha256"] == raw_source_record_digests[locator], "candidate_source_record_hash")
        row = index_by_locator[locator]
        projection = {key: record[key] for key in ("record_type", "scope_key", "artifact_id", "source_artifact_id", "sha256", "size_bytes", "official_source")}
        require({key: row[key] for key in projection} == projection, "candidate_source_projection")
        normalized_refs.append((locator, record))
    require(len(normalized_refs) == len({locator for locator, _ in normalized_refs}), "candidate_source_ref_exact_once")
    require({locator for locator, _ in normalized_refs} == set(index_by_locator), "candidate_source_bijection")
    fact_records = [row["record_id"] for row in normalized_facts]
    require(len(fact_records) == len(set(fact_records)) and set(fact_records) == set(ids), "candidate_fact_record_bijection")

    exact_keys(inventory["summary"], {"record_count", "family_counts", "family_memberships"}, "candidate_inventory_summary")
    require(inventory["summary"]["record_count"] == len(records), "candidate_summary_count")
    family_records: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        family_records[_payload_variant(record)].append(record)
    computed_family_counts = [
        {"family": family, "count": len(rows)}
        for family, rows in sorted(family_records.items())
    ]
    computed_memberships = []
    for family, rows in sorted(family_records.items()):
        ordered = sorted(rows, key=lambda row: row["record_id"])
        computed_memberships.append({
            "family": family,
            "count": len(ordered),
            "payloads_sha256": canonical_digest([row["payload"] for row in ordered]),
            "record_ids_sha256": canonical_digest([row["record_id"] for row in ordered]),
        })
    require(inventory["summary"]["family_counts"] == computed_family_counts, "candidate_summary_counts")
    require(inventory["summary"]["family_memberships"] == computed_memberships, "candidate_summary_memberships")

    validate_schema_value(run, definitions["run_evidence"], definitions, "run")
    validate_schema_value(command, definitions["command_evidence"], definitions, "command")
    validate_schema_value(review, definitions["review_evidence"], definitions, "review")
    require(run["schema"] == "g002-run/v1" and command["schema"] == "g002-command/v1" and review["schema"] == "g002-review/v1", "candidate_evidence_schema")
    require(run["bundle_id"] == command["bundle_id"] == review["bundle_id"] == bundle["bundle_id"], "candidate_bundle_crosswire")
    require(run["operator_id"] == command["operator_id"] == bundle["operator_id"], "candidate_operator")
    require(run["status"] == "succeeded" and command["exit_code"] == 0 and review["status"] == "accepted", "candidate_evidence_status")
    require(review["reviewer_id"] != bundle["operator_id"], "candidate_reviewer_independence")
    require(review["inventory_sha256"] == bundle["inventory"]["sha256"] and review["source_index_sha256"] == bundle["source_index"]["sha256"], "candidate_review_hash")
    expected_attachment_hashes = {row["path"]: row["sha256"] for row in raw_descriptors}
    require(review["attachment_sha256s"] == expected_attachment_hashes, "candidate_review_hash")
    chronology = {
        "run_started": run["started_at"],
        "command_started": command["started_at"],
        "command_ended": command["ended_at"],
        "captured": min(captured_times),
        "run_ended": run["ended_at"],
        "generated": inventory["generated_at"],
        "reviewed": review["reviewed_at"],
    }
    validate_chronology(chronology)
    require(all(parse_timestamp(command["ended_at"]) <= parse_timestamp(t) <= parse_timestamp(run["ended_at"]) for t in captured_times), "candidate_capture_chronology")
    return {
        "bundle_id": bundle["bundle_id"],
        "candidate_scope": bundle["candidate_scope"],
        "records": len(records),
        "raw_attachments": len(raw_documents),
        "primitives": len(all_primitive_ids),
        "source_rows": len(index_rows),
        "decision_count": len(all_decision_ids),
        "fact_count": len(all_fact_ids),
        "input_artifact_ids": sorted(all_input_artifact_ids),
        "scope_summaries": all_scope_summaries,
        "raw_obligations": raw_membership_oracle(raw_documents, byte_range_obligations),
        "family_counts": computed_family_counts,
        "family_memberships": computed_memberships,
    }


def _expected_candidate_family_counts(contract: Mapping[str, Any]) -> dict[str, int]:
    fixed = contract["counts"]["fixed_terms"]
    configurations = contract["counts"]["configuration_terms"]
    dex_membership = contract["dex"]["byte_membership_oracles"]
    jni = contract["jni"]["byte_membership_oracles"]
    return {
        "frozen_artifact": fixed["frozen_artifact"],
        "configuration:xapk_archive_entry": configurations["xapk_archive_entry"],
        "configuration:apk_archive_entry": configurations["apk_archive_entry"],
        "configuration:arm32_native_library": configurations["arm32_native_library"],
        "configuration:resource_configuration": configurations["resource_configuration"],
        "configuration:native_library_summary": configurations["native_library_summary"],
        "manifest_node": fixed["manifest_node"],
        "resource": fixed["resource"],
        "asset": fixed["asset"],
        "certificate": fixed["certificate"],
        "android_component": fixed["android_component"],
        "class": fixed["class"],
        "method_family": fixed["method_family"],
        "native_symbol": fixed["native_symbol"],
        "native_export": fixed["native_export"],
        "native_import:undefined_dynsym": contract["counts"]["elf_equations"]["undefined_named_import"],
        "native_import:dt_needed": contract["counts"]["elf_equations"]["dt_needed"],
        "feature": fixed["feature"],
        "reflection_target": sum(row["reflection_target_count"] for row in dex_membership),
        "dynamic_loader": sum(row["dynamic_loader_count"] for row in dex_membership),
        "jni_edge": sum(jni[key] for key in (
            "static_short_edge_count", "static_long_edge_count", "register_natives_edge_count",
            "unresolved_declaration_edge_count", "orphan_java_export_edge_count",
        )),
    }


def validate_candidate_bundle(
    contract: Mapping[str, Any],
    bundle_root: Path,
    official_manifest: Path,
    official_summary: Mapping[str, Any] | None = None,
    component_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Public producer gate: component validation followed by whole completeness."""

    summary = (
        dict(component_summary)
        if component_summary is not None
        else validate_candidate_bundle_components(contract, bundle_root, official_manifest)
    )
    actual_counts = {row["family"]: row["count"] for row in summary["family_counts"]}
    expected_counts = _expected_candidate_family_counts(contract)
    require(summary["candidate_scope"] == "whole_inventory", "candidate_incomplete_record_counts")
    require(actual_counts == expected_counts, "candidate_incomplete_record_counts")
    require(summary["records"] == sum(expected_counts.values()), "candidate_incomplete_record_counts")
    require(summary["primitives"] == summary["decision_count"], "candidate_incomplete_raw_conservation")
    require(summary["source_rows"] == summary["records"], "candidate_incomplete_raw_conservation")
    official_ids = sorted(_load_official_manifest_rows(official_manifest))
    require(summary["input_artifact_ids"] == official_ids, "candidate_incomplete_artifact_inputs")
    scope_counts: Counter[str] = Counter()
    for row in summary["scope_summaries"]:
        scope_counts[row["scope"]] += row["normalized_record_count"]
    require(dict(scope_counts) == expected_counts, "candidate_incomplete_scope_counts")
    require(official_summary is not None, "candidate_official_obligations_required")
    expected_memberships = official_summary.get("candidate_family_memberships")
    require(isinstance(expected_memberships, list), "candidate_official_obligations_required")
    require(summary["family_memberships"] == expected_memberships, "candidate_official_membership")
    expected_raw_obligations = official_summary.get("raw_obligations")
    require(isinstance(expected_raw_obligations, Mapping), "candidate_official_obligations_required")
    compare_raw_obligation_oracles(summary["raw_obligations"], expected_raw_obligations)
    return {
        key: value
        for key, value in summary.items()
        if key not in {"family_counts", "family_memberships", "input_artifact_ids", "scope_summaries", "raw_obligations"}
    }


def decode_mutf8_item(data: bytes, identity: bool) -> tuple[int, ...]:
    pos = 0
    value = 0
    for count in range(5):
        require(pos < len(data), "dex_invalid_mutf8")
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << (7 * count)
        if not (byte & 0x80):
            break
        require(count < 4, "dex_invalid_mutf8")
    else:
        raise ValidationError("dex_invalid_mutf8")
    require(value <= 0xFFFFFFFF, "dex_invalid_mutf8")
    units: list[int] = []
    while True:
        require(pos < len(data), "dex_invalid_mutf8")
        first = data[pos]
        pos += 1
        if first == 0:
            break
        if 0x01 <= first <= 0x7F:
            units.append(first)
        elif first == 0xC0:
            require(pos < len(data) and data[pos] == 0x80, "dex_invalid_mutf8")
            pos += 1
            units.append(0)
        elif 0xC2 <= first <= 0xDF:
            require(pos < len(data) and 0x80 <= data[pos] <= 0xBF, "dex_invalid_mutf8")
            second = data[pos]
            pos += 1
            units.append(((first & 0x1F) << 6) | (second & 0x3F))
        elif 0xE0 <= first <= 0xEF:
            require(pos + 1 < len(data), "dex_invalid_mutf8")
            second, third = data[pos], data[pos + 1]
            require(0x80 <= third <= 0xBF, "dex_invalid_mutf8")
            if first == 0xE0:
                require(0xA0 <= second <= 0xBF, "dex_invalid_mutf8")
            else:
                require(0x80 <= second <= 0xBF, "dex_invalid_mutf8")
            pos += 2
            units.append(((first & 0x0F) << 12) | ((second & 0x3F) << 6) | (third & 0x3F))
        else:
            raise ValidationError("dex_invalid_mutf8")
    require(pos == len(data), "dex_invalid_mutf8")
    require(len(units) == value, "dex_invalid_mutf8")
    if identity:
        index = 0
        while index < len(units):
            unit = units[index]
            if 0xD800 <= unit <= 0xDBFF:
                require(index + 1 < len(units) and 0xDC00 <= units[index + 1] <= 0xDFFF, "dex_identity_surrogate")
                index += 2
                continue
            require(not 0xDC00 <= unit <= 0xDFFF, "dex_identity_surrogate")
            index += 1
    return tuple(units)


def mangle_utf16(text: str) -> str:
    raw = text.encode("utf-16-be", "surrogatepass")
    result: list[str] = []
    for offset in range(0, len(raw), 2):
        unit = int.from_bytes(raw[offset : offset + 2], "big")
        if ord("A") <= unit <= ord("Z") or ord("a") <= unit <= ord("z") or ord("0") <= unit <= ord("9"):
            result.append(chr(unit))
        elif unit == ord("/"):
            result.append("_")
        elif unit == ord("_"):
            result.append("_1")
        elif unit == ord(";"):
            result.append("_2")
        elif unit == ord("["):
            result.append("_3")
        else:
            result.append(f"_0{unit:04x}")
    return "".join(result)


def jni_escape_failed(text: str) -> bool:
    prefix = ""
    for index, char in enumerate(text):
        if char in "0123" and (index == 0 or prefix.endswith("_")):
            return True
        prefix += mangle_utf16(char)
    return False


def _parse_dex_field_type(descriptor: str, offset: int, allow_void: bool = False) -> int:
    require(offset < len(descriptor), "jni_descriptor")
    char = descriptor[offset]
    if char in "ZBSCIJFD" or (allow_void and char == "V"):
        return offset + 1
    if char == "L":
        end = descriptor.find(";", offset + 1)
        require(end > offset + 1, "jni_descriptor")
        body = descriptor[offset + 1 : end]
        require(
            not body.startswith("/")
            and not body.endswith("/")
            and "//" not in body
            and all(c not in ".;[()" and ord(c) != 0 for c in body),
            "jni_descriptor",
        )
        return end + 1
    if char == "[":
        end = offset
        while end < len(descriptor) and descriptor[end] == "[":
            end += 1
        require(end - offset <= 255, "jni_descriptor")
        return _parse_dex_field_type(descriptor, end, False)
    raise ValidationError("jni_descriptor")


def validate_class_descriptor(descriptor: str) -> None:
    require(isinstance(descriptor, str), "jni_descriptor")
    require(_parse_dex_field_type(descriptor, 0, False) == len(descriptor), "jni_descriptor")
    require(descriptor.startswith("L"), "jni_descriptor")


def validate_method_descriptor(descriptor: str) -> tuple[str, str]:
    require(isinstance(descriptor, str) and descriptor.startswith("("), "jni_descriptor")
    offset = 1
    while offset < len(descriptor) and descriptor[offset] != ")":
        offset = _parse_dex_field_type(descriptor, offset, False)
    require(offset < len(descriptor) and descriptor[offset] == ")", "jni_descriptor")
    args = descriptor[1:offset]
    end = _parse_dex_field_type(descriptor, offset + 1, True)
    require(end == len(descriptor), "jni_descriptor")
    return args, descriptor[offset + 1 :]


def jni_names(class_descriptor: str, method: str, descriptor: str) -> tuple[str | None, str | None, bool]:
    validate_class_descriptor(class_descriptor)
    require(isinstance(method, str) and method and all(c not in "./;[()" and ord(c) != 0 for c in method), "jni_descriptor")
    args, _return_type = validate_method_descriptor(descriptor)
    internal = class_descriptor[1:-1]
    class_or_method_failure = jni_escape_failed(internal) or jni_escape_failed(method)
    if class_or_method_failure:
        return None, None, True
    short = "Java_" + mangle_utf16(internal) + "_" + mangle_utf16(method)
    if jni_escape_failed(args):
        return short, None, True
    return short, short + "__" + mangle_utf16(args), False


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def decode_aarch64_instruction(word: int, pc: int) -> dict[str, Any]:
    """Decode the closed proof-relevant AArch64 instruction subset."""

    require(isinstance(word, int) and 0 <= word <= 0xFFFFFFFF and pc % 4 == 0, "jni_aarch64_word")
    if word == 0xD503201F:
        return {"op": "NOP"}
    if word == 0xD503233F:
        return {"op": "PACIASP"}
    if word == 0xD50323BF:
        return {"op": "AUTIASP"}
    if word & 0xFFFFFC1F in {0xD503241F, 0xD503245F, 0xD503249F, 0xD50324DF}:
        return {"op": "BTI"}
    if word & 0xFC000000 == 0x94000000:
        delta = _sign_extend(word & 0x03FFFFFF, 26) << 2
        return {"op": "BL", "target": pc + delta}
    if word & 0xFC000000 == 0x14000000:
        delta = _sign_extend(word & 0x03FFFFFF, 26) << 2
        return {"op": "B", "target": pc + delta}
    if word & 0xFFFFFC1F == 0xD63F0000:
        return {"op": "BLR", "rn": (word >> 5) & 31}
    if word & 0xFFFFFC1F == 0xD61F0000:
        return {"op": "BR", "rn": (word >> 5) & 31}
    if word & 0xFFFFFC1F == 0xD65F0000:
        return {"op": "RET", "rn": (word >> 5) & 31}
    if word & 0xFFC00000 == 0xF9400000:
        return {"op": "LDR_X_unsigned", "rt": word & 31, "rn": (word >> 5) & 31, "offset": ((word >> 10) & 0xFFF) * 8}
    if word & 0xFFC00000 == 0xF9000000:
        return {"op": "STR_X_unsigned", "rt": word & 31, "rn": (word >> 5) & 31, "offset": ((word >> 10) & 0xFFF) * 8}
    if word & 0x9F000000 in {0x10000000, 0x90000000}:
        imm = _sign_extend((((word >> 5) & 0x7FFFF) << 2) | ((word >> 29) & 3), 21)
        if word & 0x80000000:
            return {"op": "ADRP", "rd": word & 31, "value": (pc & ~0xFFF) + (imm << 12)}
        return {"op": "ADR", "rd": word & 31, "value": pc + imm}
    if word & 0x1F000000 == 0x11000000:
        shift = (word >> 22) & 1
        return {
            "op": "SUB_imm" if word & 0x40000000 else "ADD_imm",
            "bits": 64 if word & 0x80000000 else 32,
            "rd": word & 31,
            "rn": (word >> 5) & 31,
            "imm": ((word >> 10) & 0xFFF) << (12 if shift else 0),
        }
    if word & 0x1F800000 in {0x12800000, 0x52800000, 0x72800000}:
        opc = (word >> 29) & 3
        return {"op": {0: "MOVN", 2: "MOVZ", 3: "MOVK"}.get(opc, "MOV_WIDE"), "rd": word & 31, "imm16": (word >> 5) & 0xFFFF, "shift": ((word >> 21) & 3) * 16, "bits": 64 if word & 0x80000000 else 32}
    if word & 0x7E000000 in {0x34000000, 0x35000000}:
        delta = _sign_extend((word >> 5) & 0x7FFFF, 19) << 2
        return {"op": "CBNZ" if word & 0x01000000 else "CBZ", "rt": word & 31, "target": pc + delta}
    if word & 0xFF000010 == 0x54000000:
        delta = _sign_extend((word >> 5) & 0x7FFFF, 19) << 2
        return {"op": "B.cond", "condition": word & 15, "target": pc + delta}
    raise ValidationError("jni_unsupported_opcode", f"pc=0x{pc:x} word=0x{word:08x}")


def analyze_aarch64_register_natives(code: bytes, start_va: int = 0) -> dict[str, Any]:
    """Recognize direct/slot calls without disassembler text or supplied values."""

    require(len(code) % 4 == 0 and len(code) <= 16384 and start_va % 4 == 0, "jni_function_region")
    instructions: list[dict[str, Any]] = []
    unsupported: list[dict[str, int]] = []
    for offset in range(0, len(code), 4):
        word = struct.unpack_from("<I", code, offset)[0]
        try:
            decoded = decode_aarch64_instruction(word, start_va + offset)
        except ValidationError as exc:
            if exc.code != "jni_unsupported_opcode":
                raise
            decoded = {"op": "UNSUPPORTED"}
            unsupported.append({"offset": offset, "word": word})
        instructions.append(decoded)
    table_roots: dict[int, int] = {}
    slot_functions: dict[int, tuple[int, int]] = {}
    calls: list[dict[str, int | str]] = []
    for index, insn in enumerate(instructions):
        if insn["op"] == "LDR_X_unsigned":
            source_root = table_roots.get(insn["rn"])
            table_roots.pop(insn["rt"], None)
            slot_functions.pop(insn["rt"], None)
            if insn["offset"] == 0:
                table_roots[insn["rt"]] = insn["rn"]
            elif insn["offset"] == 1720 and source_root is not None:
                slot_functions[insn["rt"]] = (215, source_root)
        elif insn["op"] == "BLR" and insn["rn"] in slot_functions:
            slot, root = slot_functions[insn["rn"]]
            if root == 0:
                calls.append({"kind": "jni_table_slot", "slot": slot, "call_virtual_address": start_va + index * 4})
        elif insn["op"] == "BL":
            calls.append({"kind": "direct_bl", "target": insn["target"], "call_virtual_address": start_va + index * 4})
    return {"instructions": instructions, "calls": calls, "unsupported": unsupported}


def scan_aarch64_register_natives_raw(data: bytes, artifact_id: str) -> dict[str, Any]:
    """Emit raw-only slot-215 candidates from bounded local executable functions."""

    _header, sections, _programs = _elf_headers(data)
    symbols = parse_elf_symbols(data)["symbols"]
    intervals: set[tuple[int, int, int]] = set()
    rows: list[dict[str, Any]] = []
    unsupported_total = 0
    analyzed_functions = 0
    for symbol in symbols[1:]:
        section_index = symbol["section_index"]
        key = (section_index, symbol["value"], symbol["size_bytes"])
        if (
            symbol["symbol_type"] != "STT_FUNC"
            or not 0 < symbol["size_bytes"] <= 16384
            or symbol["size_bytes"] % 4
            or section_index >= len(sections)
            or not sections[section_index]["flags"] & 0x4
            or key in intervals
        ):
            continue
        intervals.add(key)
        section = sections[section_index]
        file_offset = section["offset"] + symbol["value"] - section["addr"]
        if file_offset < 0 or file_offset % 4 or file_offset + symbol["size_bytes"] > len(data):
            continue
        analyzed_functions += 1
        result = analyze_aarch64_register_natives(
            data[file_offset : file_offset + symbol["size_bytes"]],
            symbol["value"],
        )
        unsupported_total += len(result["unsupported"])
        for call in result["calls"]:
            if call["kind"] != "jni_table_slot":
                continue
            raw_identity = {
                "library_artifact_id": artifact_id,
                "section_index": section_index,
                "function_virtual_address": symbol["value"],
                "function_size_bytes": symbol["size_bytes"],
                "register_natives_call_virtual_address": call["call_virtual_address"],
            }
            reason = (
                "unsupported_opcode_on_reaching_path"
                if result["unsupported"]
                else "unsupported_relocation"
            )
            proofs = {
                "relocation": ({"status": "proven"} if result["unsupported"] else {"status": "excluded", "reason_code": reason}),
                "function": ({"status": "proven"} if result["unsupported"] else {"status": "not_reached"}),
                "cfg": ({"status": "excluded", "reason_code": reason} if result["unsupported"] else {"status": "not_reached"}),
                "abi": {"status": "not_reached"},
                "table": {"status": "not_reached"},
                "class": {"status": "not_reached"},
            }
            rows.append({
                "candidate_id": "JRC-" + hashlib.sha256(canonical_json_bytes(raw_identity)).hexdigest().upper(),
                "raw_evidence": raw_identity,
                "proofs": proofs,
                "proposed_edges": [],
            })
    rows.sort(key=canonical_json_bytes)
    return {
        "analyzed_function_count": analyzed_functions,
        "unsupported_instruction_count": unsupported_total,
        "raw_candidate_rows": rows,
    }


def evaluate_jni_registration_candidates(
    candidates: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Give every bounded candidate exactly one proven or excluded decision."""

    stages = contract["jni"]["registration_evaluator"]["stages"]
    reason_codes = set(contract["reason_codes"]["jni_exclusion_precedence"])
    decisions: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    proven_edges: list[tuple[str, Mapping[str, Any]]] = []
    proven_candidate_count = 0
    candidate_ids: set[str] = set()
    for candidate in sorted(candidates, key=lambda row: row["candidate_id"]):
        validate_schema_value(
            candidate,
            contract["record_model"]["definitions"]["jni_registration_candidate"],
            contract["record_model"]["definitions"],
            "jni registration candidate",
        )
        exact_keys(candidate, {"candidate_id", "raw_evidence", "proofs", "proposed_edges"}, "jni_registration_candidate")
        raw_evidence = candidate["raw_evidence"]
        exact_keys(raw_evidence, {"library_artifact_id", "section_index", "function_virtual_address", "function_size_bytes", "register_natives_call_virtual_address"}, "jni_registration_raw_evidence")
        candidate_id = candidate.get("candidate_id")
        require(isinstance(candidate_id, str) and re.fullmatch(r"JRC-[0-9A-F]{64}", candidate_id) is not None, "jni_registration_candidate")
        require(candidate_id not in candidate_ids, "jni_registration_candidate_duplicate")
        candidate_ids.add(candidate_id)
        proofs = candidate.get("proofs")
        require(isinstance(proofs, Mapping) and list(proofs) == stages, "jni_registration_proofs", candidate_id)
        failed_stage: str | None = None
        reason_code: str | None = None
        reached_exclusion = False
        for stage_index, stage in enumerate(stages):
            proof = proofs[stage]
            require(isinstance(proof, Mapping) and proof.get("status") in {"proven", "excluded", "not_reached"}, "jni_registration_proof", f"{candidate_id}:{stage}")
            status = proof["status"]
            if reached_exclusion:
                require(status == "not_reached" and set(proof) == {"status"}, "jni_registration_proof_order", f"{candidate_id}:{stage}")
                continue
            if status == "proven":
                require(set(proof) == {"status"}, "jni_registration_proof", f"{candidate_id}:{stage}")
                continue
            require(status == "excluded" and set(proof) == {"status", "reason_code"}, "jni_registration_proof", f"{candidate_id}:{stage}")
            require(proof["reason_code"] in reason_codes, "jni_registration_reason", f"{candidate_id}:{stage}")
            failed_stage = stage
            reason_code = proof["reason_code"]
            reached_exclusion = True
        proposed = candidate.get("proposed_edges")
        require(isinstance(proposed, list), "jni_registration_edges", candidate_id)
        edge_ids: list[str] = []
        if reached_exclusion:
            require(not proposed, "jni_registration_excluded_edge", candidate_id)
            exclusion = {"candidate_id": candidate_id, "failed_stage": failed_stage, "reason_code": reason_code}
            exclusions.append(exclusion)
            outcome = "excluded"
        else:
            require(all(proofs[stage]["status"] == "proven" for stage in stages), "jni_registration_proof_incomplete", candidate_id)
            require(proposed, "jni_registration_missing_edge", candidate_id)
            for payload in proposed:
                validate_jni_edge_payload(
                    payload,
                    contract["record_model"]["payload_schemas"]["jni_edge"]["payload"],
                    contract["record_model"]["definitions"],
                    f"registration candidate {candidate_id}",
                )
                require(payload["binding_form"] == "register_natives", "jni_registration_binding", candidate_id)
                edge_id = record_id("jni_edge", payload)
                proven_edges.append((edge_id, payload))
                edge_ids.append(edge_id)
            proven_candidate_count += 1
            outcome = "proven"
        decisions.append({
            "candidate_id": candidate_id,
            "outcome": outcome,
            "failed_stage": failed_stage,
            "reason_code": reason_code,
            "edge_record_ids": sorted(edge_ids),
        })
    proven_edges.sort(key=lambda row: row[0])
    require(len(proven_edges) == len({row[0] for row in proven_edges}), "jni_registration_edge_duplicate")
    require(len(candidates) == proven_candidate_count + len(exclusions) == len(decisions), "jni_registration_conservation")
    return {
        "candidate_count": len(candidates),
        "proven_candidate_count": proven_candidate_count,
        "exclusion_count": len(exclusions),
        "proven_edge_count": len(proven_edges),
        "decisions": decisions,
        "exclusions": exclusions,
        "proven_edges": proven_edges,
        "registration_candidate_decisions_sha256": canonical_digest(decisions),
        "registration_proven_edges_sha256": canonical_digest([[row[0], row[1]] for row in proven_edges]),
        "registration_exclusions_sha256": canonical_digest(exclusions),
    }


def derive_static_jni_membership(
    declarations: Sequence[Mapping[str, Any]],
    java_exports: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    registration_evaluation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive the closed static JNI edge universe from DEX and ELF bytes."""

    exports_by_name: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for endpoint in java_exports:
        exports_by_name[endpoint["name"]].append(endpoint)
    for rows in exports_by_name.values():
        rows.sort(key=lambda row: (row["library_artifact_id"], row["dynamic_symbol_index"]))

    used_exports: set[str] = set()
    registration_edges = list((registration_evaluation or {}).get("proven_edges", []))
    edges: list[tuple[str, dict[str, Any]]] = [(edge_id, dict(payload)) for edge_id, payload in registration_edges]
    binding_counts: Counter[str] = Counter()
    binding_counts["register_natives"] = len(registration_edges)
    registered_declarations = {
        (
            payload["java_declaration"]["dex_artifact_id"],
            payload["java_declaration"]["class_descriptor"],
            payload["java_declaration"]["method_name"],
            payload["java_declaration"]["descriptor"],
        )
        for _edge_id, payload in registration_edges
    }
    declaration_membership: list[dict[str, Any]] = []
    for source in sorted(declarations, key=canonical_json_bytes):
        declaration = {
            "dex_artifact_id": source["dex_artifact_id"],
            "class_descriptor": source["class_descriptor"],
            "method_name": source["method_name"],
            "descriptor": source["descriptor"],
        }
        declaration_membership.append({**declaration, "is_static": source["is_static"]})
        declaration_key = tuple(declaration[key] for key in ("dex_artifact_id", "class_descriptor", "method_name", "descriptor"))
        if declaration_key in registered_declarations:
            continue
        short, long_name, failed = jni_names(
            source["mangle_class_descriptor"],
            source["mangle_method_name"],
            source["mangle_descriptor"],
        )
        matches: Sequence[Mapping[str, Any]] = ()
        binding = "unresolved_declaration"
        if not failed and short and exports_by_name.get(short):
            matches = exports_by_name[short]
            binding = "static_short"
        elif not failed and long_name and exports_by_name.get(long_name):
            matches = exports_by_name[long_name]
            binding = "static_long"
        if matches:
            for endpoint in matches:
                used_exports.add(endpoint["native_export_record_id"])
                payload = {
                    "binding_form": binding,
                    "java_declaration": declaration,
                    "native_endpoint": {
                        "endpoint_kind": "java_export",
                        "library_artifact_id": endpoint["library_artifact_id"],
                        "native_export_record_id": endpoint["native_export_record_id"],
                        "native_symbol_record_id": endpoint["native_symbol_record_id"],
                        "name": endpoint["name"],
                        "version": endpoint["version"],
                        "virtual_address": endpoint["virtual_address"],
                    },
                    "registration_site": None,
                    "resolution_status": "resolved",
                }
                validate_schema_value(
                    payload,
                    contract["record_model"]["payload_schemas"]["jni_edge"]["payload"],
                    contract["record_model"]["definitions"],
                    "official_jni_edge",
                )
                edges.append((record_id("jni_edge", payload), payload))
                binding_counts[binding] += 1
        else:
            payload = {
                "binding_form": "unresolved_declaration",
                "java_declaration": declaration,
                "native_endpoint": {"unresolved_token": "no_static_export_or_proven_register_natives"},
                "registration_site": None,
                "resolution_status": "unresolved",
            }
            validate_schema_value(
                payload,
                contract["record_model"]["payload_schemas"]["jni_edge"]["payload"],
                contract["record_model"]["definitions"],
                "official_jni_edge",
            )
            edges.append((record_id("jni_edge", payload), payload))
            binding_counts["unresolved_declaration"] += 1

    export_membership: list[dict[str, Any]] = []
    for endpoint in sorted(java_exports, key=lambda row: (row["library_artifact_id"], row["dynamic_symbol_index"])):
        export_membership.append({key: endpoint[key] for key in (
            "library_artifact_id", "dynamic_symbol_index", "native_export_record_id",
            "native_symbol_record_id", "name", "version", "virtual_address",
        )})
        if endpoint["native_export_record_id"] in used_exports:
            continue
        payload = {
            "binding_form": "orphan_java_export",
            "java_declaration": {"unresolved_token": "no_matching_dex_native_declaration"},
            "native_endpoint": {
                "endpoint_kind": "java_export",
                "library_artifact_id": endpoint["library_artifact_id"],
                "native_export_record_id": endpoint["native_export_record_id"],
                "native_symbol_record_id": endpoint["native_symbol_record_id"],
                "name": endpoint["name"],
                "version": endpoint["version"],
                "virtual_address": endpoint["virtual_address"],
            },
            "registration_site": None,
            "resolution_status": "orphan",
        }
        validate_schema_value(
            payload,
            contract["record_model"]["payload_schemas"]["jni_edge"]["payload"],
            contract["record_model"]["definitions"],
            "official_jni_edge",
        )
        edges.append((record_id("jni_edge", payload), payload))
        binding_counts["orphan_java_export"] += 1

    edges.sort(key=lambda row: row[0])
    require(len(edges) == len({row[0] for row in edges}), "official_jni_edge_duplicate")
    return {
        "dex_native_declaration_count": len(declaration_membership),
        "java_export_count": len(export_membership),
        "static_short_edge_count": binding_counts["static_short"],
        "static_long_edge_count": binding_counts["static_long"],
        "unresolved_declaration_edge_count": binding_counts["unresolved_declaration"],
        "orphan_java_export_edge_count": binding_counts["orphan_java_export"],
        "register_natives_edge_count": binding_counts["register_natives"],
        "register_natives_declaration_count": len(registered_declarations),
        "declaration_membership_sha256": canonical_digest(declaration_membership),
        "java_export_endpoint_membership_sha256": canonical_digest(export_membership),
        "jni_edge_payloads_sorted_by_record_id_sha256": canonical_digest([row[1] for row in edges]),
        "jni_edge_record_ids_sorted_sha256": canonical_digest([row[0] for row in edges]),
        "normalized_edges": edges,
    }


@dataclass(frozen=True)
class ZipEntry:
    ordinal: int
    path: str
    flags: int
    method: int
    crc32: int
    compressed_size: int
    uncompressed_size: int
    local_offset: int
    central_offset: int


@dataclass(frozen=True)
class ZipDirectory:
    entries: tuple[ZipEntry, ...]
    central_offset: int
    central_size: int
    eocd_offset: int


def _decode_zip_name(raw: bytes, flags: int) -> str:
    try:
        text = raw.decode("utf-8" if flags & 0x800 else "cp437", "strict")
    except UnicodeDecodeError as exc:
        raise ValidationError("zip_name_encoding", str(exc)) from exc
    text = unicodedata.normalize("NFC", text)
    require("\x00" not in text and "\\" not in text, "zip_path")
    require(not text.startswith("/") and re.match(r"^[A-Za-z]:", text) is None, "zip_path")
    parts = text.split("/")
    require(all(part not in {"", ".", ".."} for part in parts), "zip_path")
    return text


def parse_zip_directory_file(path: Path) -> ZipDirectory:
    size = path.stat().st_size
    tail_size = min(size, 65557)
    with path.open("rb") as stream:
        stream.seek(size - tail_size)
        tail = stream.read(tail_size)
        candidates: list[tuple[int, tuple[int, ...]]] = []
        start = 0
        while True:
            index = tail.find(b"PK\x05\x06", start)
            if index < 0:
                break
            absolute = size - tail_size + index
            if index + 22 <= len(tail):
                fields = struct.unpack_from("<IHHHHIIH", tail, index)
                if absolute + 22 + fields[-1] == size:
                    candidates.append((absolute, fields))
            start = index + 1
        require(len(candidates) == 1, "zip_eocd")
        eocd_offset, fields = candidates[0]
        _, disk, cd_disk, disk_count, total_count, cd_size, cd_offset, _comment = fields
        require(disk == cd_disk == 0 and disk_count == total_count, "zip_multidisk")
        require(total_count != 0xFFFF and cd_size != 0xFFFFFFFF and cd_offset != 0xFFFFFFFF, "zip64_unsupported")
        require(cd_offset + cd_size == eocd_offset, "zip_central_range")
        stream.seek(cd_offset)
        central = stream.read(cd_size)
    entries = _parse_central_bytes(central, cd_offset, total_count)
    return ZipDirectory(tuple(entries), cd_offset, cd_size, eocd_offset)


def parse_zip_directory_bytes(data: bytes) -> ZipDirectory:
    candidates: list[tuple[int, tuple[int, ...]]] = []
    start = max(0, len(data) - 65557)
    while True:
        index = data.find(b"PK\x05\x06", start)
        if index < 0:
            break
        if index + 22 <= len(data):
            fields = struct.unpack_from("<IHHHHIIH", data, index)
            if index + 22 + fields[-1] == len(data):
                candidates.append((index, fields))
        start = index + 1
    require(len(candidates) == 1, "zip_eocd")
    eocd_offset, fields = candidates[0]
    _, disk, cd_disk, disk_count, total_count, cd_size, cd_offset, _comment = fields
    require(disk == cd_disk == 0 and disk_count == total_count, "zip_multidisk")
    require(cd_offset + cd_size == eocd_offset, "zip_central_range")
    return ZipDirectory(tuple(_parse_central_bytes(data[cd_offset:eocd_offset], cd_offset, total_count)), cd_offset, cd_size, eocd_offset)


def _parse_central_bytes(central: bytes, absolute_offset: int, expected_count: int) -> list[ZipEntry]:
    entries: list[ZipEntry] = []
    pos = 0
    while pos < len(central):
        require(pos + 46 <= len(central), "zip_central_truncated")
        fields = struct.unpack_from("<IHHHHHHIIIHHHHHII", central, pos)
        require(fields[0] == 0x02014B50, "zip_central_signature")
        flags, method = fields[3], fields[4]
        require(method in {0, 8}, "zip_compression_unsupported")
        require(flags & ~0x080E == 0, "zip_flags_unsupported", f"0x{flags:04x}")
        require(not (method == 0 and flags & 0x0006), "zip_flags_unsupported")
        crc, compressed, uncompressed = fields[7], fields[8], fields[9]
        name_len, extra_len, comment_len = fields[10], fields[11], fields[12]
        disk_start, local_offset = fields[13], fields[16]
        require(disk_start == 0, "zip_multidisk")
        end = pos + 46 + name_len + extra_len + comment_len
        require(end <= len(central), "zip_central_truncated")
        path = _decode_zip_name(central[pos + 46 : pos + 46 + name_len], flags)
        entries.append(
            ZipEntry(
                ordinal=len(entries),
                path=path,
                flags=flags,
                method=method,
                crc32=crc,
                compressed_size=compressed,
                uncompressed_size=uncompressed,
                local_offset=local_offset,
                central_offset=absolute_offset + pos,
            )
        )
        pos = end
    require(pos == len(central) and len(entries) == expected_count, "zip_central_count")
    offsets = [entry.local_offset for entry in entries]
    require(len(offsets) == len(set(offsets)), "zip_local_duplicate_offset")
    require(all(offset < absolute_offset for offset in offsets), "zip_local_range")
    return entries


def extract_zip_entry_bytes(data: bytes, entry: ZipEntry) -> bytes:
    offset = entry.local_offset
    require(offset + 30 <= len(data), "zip_local_truncated")
    fields = struct.unpack_from("<IHHHHHIIIHH", data, offset)
    require(fields[0] == 0x04034B50, "zip_local_signature")
    flags, method, crc, compressed, uncompressed, name_len, extra_len = (
        fields[2],
        fields[3],
        fields[6],
        fields[7],
        fields[8],
        fields[9],
        fields[10],
    )
    raw_name = data[offset + 30 : offset + 30 + name_len]
    require(_decode_zip_name(raw_name, flags) == entry.path, "zip_local_central_mismatch")
    require(flags == entry.flags and method == entry.method, "zip_local_central_mismatch")
    require(method in {0, 8} and flags & ~0x080E == 0, "zip_flags_unsupported")
    if not flags & 0x08:
        require((crc, compressed, uncompressed) == (entry.crc32, entry.compressed_size, entry.uncompressed_size), "zip_local_central_mismatch")
    start = offset + 30 + name_len + extra_len
    end = start + entry.compressed_size
    require(end <= len(data), "zip_data_range")
    compressed_data = data[start:end]
    if flags & 0x08:
        require(end + 12 <= len(data), "zip_descriptor_truncated")
        if data[end : end + 4] == b"PK\x07\x08":
            require(end + 16 <= len(data), "zip_descriptor_truncated")
            dcrc, dcompressed, duncompressed = struct.unpack_from("<III", data, end + 4)
        else:
            dcrc, dcompressed, duncompressed = struct.unpack_from("<III", data, end)
        require((dcrc, dcompressed, duncompressed) == (entry.crc32, entry.compressed_size, entry.uncompressed_size), "zip_descriptor_mismatch")
    if method == 0:
        output = compressed_data
    elif method == 8:
        decoder = zlib.decompressobj(-15)
        output = decoder.decompress(compressed_data) + decoder.flush()
        require(decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, "zip_deflate_termination")
    else:
        raise ValidationError("zip_compression_unsupported")
    require(len(output) == entry.uncompressed_size, "zip_size_mismatch")
    require((binascii.crc32(output) & 0xFFFFFFFF) == entry.crc32, "zip_crc_mismatch")
    return output


def _elf_headers(data: bytes) -> tuple[dict[str, int], list[dict[str, int]], list[dict[str, int]]]:
    require(len(data) >= 64 and data[:4] == b"\x7fELF", "elf_header")
    require(data[4] == 2 and data[5] == 1, "elf_header")
    fields = struct.unpack_from("<16sHHIQQQIHHHHHH", data, 0)
    header = {
        "type": fields[1],
        "machine": fields[2],
        "phoff": fields[5],
        "shoff": fields[6],
        "ehsize": fields[8],
        "phentsize": fields[9],
        "phnum": fields[10],
        "shentsize": fields[11],
        "shnum": fields[12],
        "shstrndx": fields[13],
    }
    require(header["type"] == 3 and header["machine"] == 183 and header["ehsize"] == 64, "elf_header")
    require(header["shentsize"] == 64, "elf_section_table")
    require(header["shoff"] + header["shnum"] * 64 <= len(data), "elf_section_table")
    sections: list[dict[str, int]] = []
    for index in range(header["shnum"]):
        f = struct.unpack_from("<IIQQQQIIQQ", data, header["shoff"] + index * 64)
        section = {
            "index": index,
            "name": f[0],
            "type": f[1],
            "flags": f[2],
            "addr": f[3],
            "offset": f[4],
            "size": f[5],
            "link": f[6],
            "info": f[7],
            "align": f[8],
            "entsize": f[9],
        }
        require(section["offset"] + section["size"] <= len(data) or section["type"] == 8, "elf_section_range")
        sections.append(section)
    programs: list[dict[str, int]] = []
    if header["phnum"]:
        require(header["phentsize"] == 56 and header["phoff"] + header["phnum"] * 56 <= len(data), "elf_program_table")
        for index in range(header["phnum"]):
            f = struct.unpack_from("<IIQQQQQQ", data, header["phoff"] + index * 56)
            programs.append({"type": f[0], "flags": f[1], "offset": f[2], "vaddr": f[3], "filesz": f[5], "memsz": f[6], "align": f[7]})
    return header, sections, programs


def _c_string(data: bytes, base: int, size: int, offset: int, code: str) -> str:
    require(0 <= offset < size, code)
    end = data.find(b"\0", base + offset, base + size)
    require(end >= 0, code)
    try:
        return unicodedata.normalize("NFC", data[base + offset : end].decode("utf-8", "strict"))
    except UnicodeDecodeError as exc:
        raise ValidationError(code, str(exc)) from exc


def parse_elf_symbols(data: bytes) -> dict[str, Any]:
    _header, sections, _programs = _elf_headers(data)
    dynsyms = [s for s in sections if s["type"] == 11]
    require(len(dynsyms) == 1, "elf_dynsym_selection")
    dynsym = dynsyms[0]
    require(dynsym["entsize"] == 24 and dynsym["size"] % 24 == 0, "elf_dynsym_shape")
    require(0 <= dynsym["link"] < len(sections), "elf_dynstr")
    dynstr = sections[dynsym["link"]]
    require(dynstr["type"] == 3, "elf_dynstr")
    count = dynsym["size"] // 24
    symbols: list[dict[str, Any]] = []
    xindex_sections = [s for s in sections if s["type"] == 18 and s["link"] == dynsym["index"]]
    for index in range(count):
        offset = dynsym["offset"] + index * 24
        st_name, st_info, st_other, st_shndx, value, size_bytes = struct.unpack_from("<IBBHQQ", data, offset)
        require(st_other & 0xF8 == 0, "elf_st_other")
        if index == 0:
            require((st_name, st_info, st_other, st_shndx, value, size_bytes) == (0, 0, 0, 0, 0, 0), "elf_reserved_index_zero")
        if st_shndx == 0xFFFF:
            require(len(xindex_sections) == 1, "elf_shn_xindex")
            companion = xindex_sections[0]
            require(companion["entsize"] == 4 and companion["size"] // 4 == count, "elf_shn_xindex")
            section_index = struct.unpack_from("<I", data, companion["offset"] + index * 4)[0]
        else:
            section_index = st_shndx
        if 1 <= section_index < 0xFF00:
            require(section_index < len(sections), "elf_section_index")
        require(section_index != 0xFFF2, "elf_shn_common")
        name = _c_string(data, dynstr["offset"], dynstr["size"], st_name, "elf_symbol_string")
        if not name:
            name = None
        binding_code = st_info >> 4
        type_code = st_info & 0x0F
        visibility_code = st_other & 7
        type_token = {
            0: "STT_NOTYPE",
            1: "STT_OBJECT",
            2: "STT_FUNC",
            3: "STT_SECTION",
            4: "STT_FILE",
            5: "STT_COMMON",
            6: "STT_TLS",
            10: "STT_GNU_IFUNC",
        }.get(type_code)
        if type_token is None:
            if 11 <= type_code <= 12:
                type_token = f"OS:{type_code}"
            elif 13 <= type_code <= 15:
                type_token = f"PROC:{type_code}"
            else:
                type_token = f"UNKNOWN:{type_code}"
        binding_token = {0: "STB_LOCAL", 1: "STB_GLOBAL", 2: "STB_WEAK", 10: "STB_GNU_UNIQUE"}.get(binding_code)
        if binding_token is None:
            if 11 <= binding_code <= 12:
                binding_token = f"OS:{binding_code}"
            elif 13 <= binding_code <= 15:
                binding_token = f"PROC:{binding_code}"
            else:
                binding_token = f"UNKNOWN:{binding_code}"
        visibility_token = {
            0: "STV_DEFAULT",
            1: "STV_INTERNAL",
            2: "STV_HIDDEN",
            3: "STV_PROTECTED",
            4: "STV_EXPORTED",
            5: "STV_SINGLETON",
            6: "STV_ELIMINATE",
            7: "UNKNOWN:7",
        }[visibility_code]
        export = (
            index > 0
            and name is not None
            and section_index != 0
            and binding_token in {"STB_GLOBAL", "STB_WEAK"}
            and visibility_token in {"STV_DEFAULT", "STV_PROTECTED", "STV_EXPORTED", "STV_SINGLETON"}
        )
        undefined_import = index > 0 and name is not None and section_index == 0
        symbols.append(
            {
                "index": index,
                "name": name,
                "value": value,
                "size_bytes": size_bytes,
                "symbol_type": type_token,
                "binding": binding_token,
                "visibility": visibility_token,
                "section_index": section_index,
                "version": None,
                "export": export,
                "undefined_import": undefined_import,
            }
        )
    versions = _parse_elf_versions(data, sections, dynsym, dynstr, symbols)
    for symbol, version in zip(symbols, versions):
        symbol["version"] = version
    return {"count": count, "symbols": symbols}


def _parse_elf_versions(
    data: bytes,
    sections: Sequence[Mapping[str, int]],
    dynsym: Mapping[str, int],
    dynstr: Mapping[str, int],
    symbols: Sequence[Mapping[str, Any]],
) -> list[str | None]:
    versyms = [s for s in sections if s["type"] == 0x6FFFFFFF and s["link"] == dynsym["index"]]
    verdefs = [s for s in sections if s["type"] == 0x6FFFFFFD]
    verneeds = [s for s in sections if s["type"] == 0x6FFFFFFE]
    require(len(versyms) <= 1 and len(verdefs) <= 1 and len(verneeds) <= 1, "elf_version_section")
    if not versyms:
        require(not verdefs and not verneeds, "elf_version_section")
        return [None] * len(symbols)
    section = versyms[0]
    require(section["entsize"] in {0, 2} and section["size"] == len(symbols) * 2, "elf_versym_cardinality")
    raw_versions = struct.unpack_from(f"<{len(symbols)}H", data, section["offset"])
    definitions: dict[int, str] = {}
    requirements: dict[int, str] = {}

    if verdefs:
        current = 0
        seen: set[int] = set()
        sec = verdefs[0]
        while current < sec["size"]:
            require(current not in seen and current + 20 <= sec["size"], "elf_verdef")
            seen.add(current)
            version, _flags, index, count, _hash, aux, nxt = struct.unpack_from("<HHHHIII", data, sec["offset"] + current)
            require(version == 1 and count >= 1 and aux >= 20 and current + aux + 8 <= sec["size"], "elf_verdef")
            name_off, _aux_next = struct.unpack_from("<II", data, sec["offset"] + current + aux)
            name = _c_string(data, dynstr["offset"], dynstr["size"], name_off, "elf_version_string")
            require(index >= 1 and name, "elf_verdef")
            if index >= 2:
                require(index not in definitions, "elf_verdef")
                definitions[index] = name
            if nxt == 0:
                break
            require(nxt % 4 == 0 and current + nxt > current, "elf_verdef")
            current += nxt

    if verneeds:
        current = 0
        seen: set[int] = set()
        sec = verneeds[0]
        while current < sec["size"]:
            require(current not in seen and current + 16 <= sec["size"], "elf_verneed")
            seen.add(current)
            version, count, _file, aux, nxt = struct.unpack_from("<HHIII", data, sec["offset"] + current)
            require(version == 1 and count >= 1 and aux >= 16, "elf_verneed")
            aux_pos = current + aux
            aux_seen: set[int] = set()
            for ordinal in range(count):
                require(aux_pos not in aux_seen and aux_pos + 16 <= sec["size"], "elf_verneed")
                aux_seen.add(aux_pos)
                _hash, _flags, other, name_off, aux_next = struct.unpack_from("<IHHII", data, sec["offset"] + aux_pos)
                index = other & 0x7FFF
                name = _c_string(data, dynstr["offset"], dynstr["size"], name_off, "elf_version_string")
                require(index >= 2 and index not in requirements and name, "elf_verneed")
                requirements[index] = name
                if ordinal + 1 < count:
                    require(aux_next >= 16 and aux_next % 4 == 0, "elf_verneed")
                    aux_pos += aux_next
                else:
                    require(aux_next == 0, "elf_verneed")
            if nxt == 0:
                break
            require(nxt % 4 == 0 and current + nxt > current, "elf_verneed")
            current += nxt

    result: list[str | None] = []
    default_seen: set[tuple[str | None, str]] = set()
    for symbol, raw in zip(symbols, raw_versions):
        index = raw & 0x7FFF
        hidden = bool(raw & 0x8000)
        if index in {0, 1}:
            require(not hidden, "elf_version_reserved")
            result.append(None)
        elif symbol["section_index"] == 0:
            require(not hidden and index in requirements and index not in definitions, "elf_version_reference")
            result.append("@" + requirements[index])
        else:
            require(index in definitions and index not in requirements, "elf_version_definition")
            token = ("@" if hidden else "@@") + definitions[index]
            if not hidden:
                key = (symbol["name"], definitions[index])
                require(key not in default_seen, "elf_version_default_duplicate")
                default_seen.add(key)
            result.append(token)
    return result


def _map_elf_vaddr(programs: Sequence[Mapping[str, int]], address: int, size: int) -> int:
    matches = [
        p
        for p in programs
        if p["type"] == 1
        and p["vaddr"] <= address
        and address + size <= p["vaddr"] + p["filesz"]
    ]
    require(len(matches) == 1, "elf_vaddr_mapping")
    return matches[0]["offset"] + address - matches[0]["vaddr"]


def parse_elf_dynamic(data: bytes) -> dict[str, Any]:
    _header, sections, programs = _elf_headers(data)
    segments = [p for p in programs if p["type"] == 2]
    dynamic_sections = [s for s in sections if s["type"] == 6]
    require(len(segments) == len(dynamic_sections) == 1, "elf_dynamic_authority")
    segment, section = segments[0], dynamic_sections[0]
    require((segment["offset"], segment["filesz"]) == (section["offset"], section["size"]), "elf_dynamic_authority")
    require(segment["filesz"] % 16 == 0, "elf_dynamic_shape")
    entries: list[tuple[int, int]] = []
    for index in range(segment["filesz"] // 16):
        entries.append(struct.unpack_from("<qQ", data, segment["offset"] + index * 16))
    null_indexes = [index for index, (tag, _value) in enumerate(entries) if tag == 0]
    require(null_indexes, "elf_dynamic_terminator")
    first_null = null_indexes[0]
    pre = entries[:first_null]

    def unique_tag(tag: int) -> int:
        values = [value for current, value in pre if current == tag]
        require(len(values) == 1, "elf_dynamic_required_tag", str(tag))
        return values[0]

    strtab_address = unique_tag(5)
    strtab_size = unique_tag(10)
    require(unique_tag(11) == 24, "elf_dynamic_syment")
    unique_tag(6)
    strtab_offset = _map_elf_vaddr(programs, strtab_address, strtab_size)
    decisions: list[list[Any]] = []
    needed: list[tuple[int, str]] = []
    for index, (tag, value) in enumerate(entries):
        if index < first_null:
            if tag == 1:
                decision = "included_dt_needed"
                soname = _c_string(data, strtab_offset, strtab_size, value, "elf_needed_string")
                require(bool(soname), "elf_needed_string")
                needed.append((index, soname))
            else:
                decision = "other_dynamic_tag"
        elif index == first_null:
            decision = "terminator"
        else:
            decision = "after_first_dt_null"
        decisions.append([index, tag, decision])
    return {"entries": entries, "decisions": decisions, "needed": needed}


def _read_uleb(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for count in range(5):
        require(offset < len(data), "dex_uleb")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << (count * 7)
        if not byte & 0x80:
            require(value <= 0xFFFFFFFF, "dex_uleb")
            return value, offset
    raise ValidationError("dex_uleb")


def parse_dex_counts(data: bytes) -> dict[str, int]:
    require(len(data) >= 112 and data[:8] == b"dex\n037\0", "dex_header")
    require(struct.unpack_from("<I", data, 36)[0] == 112, "dex_header")
    require(struct.unpack_from("<I", data, 40)[0] == 0x12345678, "dex_header")
    require(struct.unpack_from("<I", data, 32)[0] == len(data), "dex_header")
    require(hashlib.sha1(data[32:]).digest() == data[12:32], "dex_sha1")
    require((zlib.adler32(data[12:]) & 0xFFFFFFFF) == struct.unpack_from("<I", data, 8)[0], "dex_adler32")
    string_count, string_off = struct.unpack_from("<II", data, 56)
    method_count, method_off = struct.unpack_from("<II", data, 88)
    class_count, class_off = struct.unpack_from("<II", data, 96)
    require(string_off + string_count * 4 <= len(data), "dex_table_range")
    require(method_off + method_count * 8 <= len(data), "dex_table_range")
    require(class_off + class_count * 32 <= len(data), "dex_table_range")
    string_units: list[tuple[int, ...] | None] = [None] * string_count

    def get_string(index: int) -> tuple[int, ...]:
        require(0 <= index < string_count, "dex_string_index")
        cached = string_units[index]
        if cached is not None:
            return cached
        item_offset = struct.unpack_from("<I", data, string_off + index * 4)[0]
        _declared, pos = _read_uleb(data, item_offset)
        end = data.find(b"\0", pos)
        require(end >= 0, "dex_invalid_mutf8")
        prefix = data[item_offset:pos]
        units = decode_mutf8_item(prefix + data[pos : end + 1], identity=True)
        string_units[index] = units
        return units

    method_name_indexes: list[int] = []
    for index in range(method_count):
        _class_idx, _proto_idx, name_idx = struct.unpack_from("<HHI", data, method_off + index * 8)
        require(name_idx < string_count, "dex_method_name")
        method_name_indexes.append(name_idx)
    definitions = 0
    native = 0
    families: set[tuple[int, tuple[int, ...]]] = set()
    for class_index in range(class_count):
        class_idx, _flags, _super, _interfaces, _source, _annotations, class_data_off, _static = struct.unpack_from(
            "<IIIIIIII", data, class_off + class_index * 32
        )
        if class_data_off == 0:
            continue
        offset = class_data_off
        static_fields, offset = _read_uleb(data, offset)
        instance_fields, offset = _read_uleb(data, offset)
        direct_methods, offset = _read_uleb(data, offset)
        virtual_methods, offset = _read_uleb(data, offset)
        for field_total in (static_fields, instance_fields):
            field_idx = 0
            for _ in range(field_total):
                diff, offset = _read_uleb(data, offset)
                _access, offset = _read_uleb(data, offset)
                field_idx += diff
        for method_total in (direct_methods, virtual_methods):
            method_idx = 0
            for _ in range(method_total):
                diff, offset = _read_uleb(data, offset)
                access, offset = _read_uleb(data, offset)
                _code_off, offset = _read_uleb(data, offset)
                method_idx += diff
                require(method_idx < method_count, "dex_method_index")
                definitions += 1
                if access & 0x100:
                    native += 1
                families.add((class_idx, get_string(method_name_indexes[method_idx])))
    return {
        "classes": class_count,
        "defined_methods": definitions,
        "method_families": len(families),
        "native_declarations": native,
    }


def _utf16_units_text(units: Sequence[int], code: str = "dex_identity_surrogate") -> str:
    raw = b"".join(int(unit).to_bytes(2, "little") for unit in units)
    try:
        return unicodedata.normalize("NFC", raw.decode("utf-16-le", "strict"))
    except UnicodeDecodeError as exc:
        raise ValidationError(code, str(exc)) from exc


def _dex_instruction_width(units: Sequence[int], offset: int) -> int:
    require(offset < len(units), "dex_instruction")
    first = units[offset]
    opcode = first & 0xFF
    if opcode == 0 and first:
        # Payload identifiers are only payloads at four-byte-aligned code-unit
        # offsets.  At odd offsets the opcode remains the one-unit NOP form.
        if offset & 1:
            return 1
        ident = first >> 8
        if ident == 1:
            require(offset + 2 <= len(units), "dex_payload")
            return 4 + units[offset + 1] * 2
        if ident == 2:
            require(offset + 2 <= len(units), "dex_payload")
            return 2 + units[offset + 1] * 4
        if ident == 3:
            require(offset + 4 <= len(units), "dex_payload")
            element_width = units[offset + 1]
            size = units[offset + 2] | (units[offset + 3] << 16)
            require(element_width in {1, 2, 4, 8}, "dex_payload")
            return 4 + (element_width * size + 1) // 2
        return 1
    if opcode <= 0x12 or 0x1D <= opcode <= 0x1E or 0x3E <= opcode <= 0x43 or opcode in {0x21, 0x27, 0x28, 0x73, 0x79, 0x7A, 0xEC, 0xF1} or 0x7B <= opcode <= 0x8F or 0xB0 <= opcode <= 0xCF:
        return 1
    if opcode in {0x13, 0x15, 0x16, 0x19, 0x1A, 0x1C, 0x1F, 0x20, 0x22, 0x23, 0x29, 0xEB, 0xED} or 0x2D <= opcode <= 0x3D or 0x44 <= opcode <= 0x6D or 0x90 <= opcode <= 0xAF or 0xD0 <= opcode <= 0xEA or 0xF2 <= opcode <= 0xF7:
        return 2
    if opcode in {0x14, 0x17, 0x1B, 0x24, 0x25, 0x26, 0x2A, 0x2B, 0x2C, 0xEE, 0xEF, 0xF0, 0xF8, 0xF9, 0xFC, 0xFD} or 0x6E <= opcode <= 0x72 or 0x74 <= opcode <= 0x78:
        return 3
    if opcode in {0xFA, 0xFB}:
        return 4
    if opcode in {0xFE, 0xFF}:
        return 2
    if opcode == 0x18:
        return 5
    raise ValidationError("dex_opcode", f"offset={offset} opcode=0x{opcode:02x}")


def _decode_invoke_registers(units: Sequence[int], offset: int) -> list[int]:
    opcode = units[offset] & 0xFF
    if 0x6E <= opcode <= 0x72:
        count = (units[offset] >> 12) & 0xF
        g = (units[offset] >> 8) & 0xF
        packed = units[offset + 2]
        registers = [packed & 0xF, (packed >> 4) & 0xF, (packed >> 8) & 0xF, (packed >> 12) & 0xF, g]
        require(count <= 5, "dex_invoke_registers")
        return registers[:count]
    if 0x74 <= opcode <= 0x78:
        count = (units[offset] >> 8) & 0xFF
        first = units[offset + 2]
        require(first + count <= 65536, "dex_invoke_registers")
        return list(range(first, first + count))
    raise ValidationError("dex_invoke_opcode")


DEX_TOP = ("TOP",)


def _dex_join_value(left: Any, right: Any) -> Any:
    if left == right:
        return left
    if left is None:
        return right
    if right is None:
        return left
    if isinstance(left, tuple) and isinstance(right, tuple) and left[:2] == right[:2] and left and left[0] == "Array":
        cells = tuple(_dex_join_value(a, b) for a, b in zip(left[2], right[2])) if len(left[2]) == len(right[2]) else ()
        return ("Array", left[1], cells) if cells else DEX_TOP
    return DEX_TOP


def _binary_name_to_descriptor(value: str) -> str | None:
    if not value or value.startswith("["):
        try:
            end = _parse_dex_field_type(value, 0, False)
            return value if end == len(value) else None
        except ValidationError:
            return None
    internal = value.replace(".", "/")
    descriptor = f"L{internal};"
    try:
        validate_class_descriptor(descriptor)
    except ValidationError:
        return None
    return descriptor


def _evaluate_target_recipe(
    recipe: str,
    values: list[Any],
    *,
    has_receiver: bool,
) -> dict[str, Any] | None:
    def at(index: int) -> Any:
        return values[index] if index < len(values) else DEX_TOP

    receiver_offset = 0
    args_offset = 1 if has_receiver else 0
    if recipe.startswith("for_name("):
        value = at(args_offset)
        descriptor = _binary_name_to_descriptor(value[1]) if isinstance(value, tuple) and value[0] == "String" else None
        return {"target_kind": "class", "class_descriptor": descriptor} if descriptor else None
    if recipe.startswith(("binary_name(", "slash_binary_name(")):
        value = at(args_offset)
        if isinstance(value, tuple) and value[0] == "String":
            raw = value[1].replace("/", ".") if recipe.startswith("slash_") else value[1]
            descriptor = _binary_name_to_descriptor(raw)
            return {"target_kind": "class", "class_descriptor": descriptor} if descriptor else None
    if recipe.startswith("native_library_name("):
        value = at(args_offset)
        return {"target_kind": "native_library_name", "value": value[1]} if isinstance(value, tuple) and value[0] == "String" else None
    if recipe.startswith(("native_library_path(", "file_path(")):
        value = at(args_offset)
        return {"target_kind": "native_library_path", "value": value[1]} if isinstance(value, tuple) and value[0] == "String" else None
    if recipe.startswith(("dex_path_list(", "single_dex_path(")):
        value = at(args_offset)
        if isinstance(value, tuple) and value[0] == "String":
            values_out = value[1].split(":") if recipe.startswith("dex_path_list") else [value[1]]
            return {"target_kind": "dex_path_list", "values": values_out}
    if recipe.startswith("memory_dex("):
        if "count=1" in recipe:
            return {"target_kind": "memory_dex", "buffer_count": 1}
        value = at(args_offset)
        if isinstance(value, tuple) and value[0] == "Array":
            return {"target_kind": "memory_dex", "buffer_count": len(value[2])}
    if recipe.startswith("jna_interface("):
        value = at(args_offset)
        return {"target_kind": "jna_interface", "class_descriptor": value[1]} if isinstance(value, tuple) and value[0] == "Class" else None
    if recipe.startswith("proxy_interfaces("):
        value = at(args_offset + 1)
        if isinstance(value, tuple) and value[0] == "Array" and all(isinstance(cell, tuple) and cell[0] == "Class" for cell in value[2]):
            return {"target_kind": "proxy_interfaces", "class_descriptors": [cell[1] for cell in value[2]]}
    if recipe.startswith("member_collection("):
        receiver = at(receiver_offset)
        if isinstance(receiver, tuple) and receiver[0] == "Class":
            query = recipe.split(",", 1)[1].rsplit(")", 1)[0]
            return {"target_kind": "member_collection", "class_descriptor": receiver[1], "query": query}
    if recipe.startswith("class_relation("):
        value = at(args_offset)
        if isinstance(value, tuple) and value[0] == "Class":
            relation = recipe.split(",", 1)[1].rsplit(")", 1)[0]
            return {"target_kind": "class_relation", "class_descriptor": value[1], "relation": relation}
    return None


def interpret_dex_code(
    units: Sequence[int],
    registers_size: int,
    strings: Sequence[str],
    types: Sequence[str],
    methods: Sequence[tuple[str, str, str]],
    callsites: Mapping[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    """Mandatory ascending-worklist least fixpoint for the bounded exact domain."""

    starts: list[int] = []
    widths: dict[int, int] = {}
    offset = 0
    while offset < len(units):
        width = _dex_instruction_width(units, offset)
        if offset + width > len(units):
            break
        starts.append(offset)
        widths[offset] = width
        offset += width
    start_set = set(starts)
    if not starts:
        return {}
    entry: dict[int, tuple[tuple[Any, ...], Any, int | None]] = {starts[0]: (tuple(DEX_TOP for _ in range(registers_size)), None, None)}
    worklist = [starts[0]]

    def successors(current: int, opcode: int) -> list[int]:
        nxt = current + widths[current]
        if opcode == 0x28:
            target = current + _sign_extend(units[current] >> 8, 8)
            return [target]
        if opcode == 0x29:
            target = current + _sign_extend(units[current + 1], 16)
            return [target]
        if opcode == 0x2A:
            raw = units[current + 1] | (units[current + 2] << 16)
            return [current + _sign_extend(raw, 32)]
        if 0x32 <= opcode <= 0x3D:
            return sorted({nxt, current + _sign_extend(units[current + 1], 16)})
        if opcode in {0x0E, 0x0F, 0x10, 0x11, 0x27}:
            return []
        return [nxt] if nxt in start_set else []

    while worklist:
        current = min(worklist)
        worklist.remove(current)
        registers, pending, pending_at = entry[current]
        regs = list(registers)
        opcode = units[current] & 0xFF
        produced: Any = None
        if opcode in {0x01, 0x04, 0x07}:
            dst, src = (units[current] >> 8) & 0xF, (units[current] >> 12) & 0xF
            if dst < registers_size and src < registers_size:
                regs[dst] = regs[src]
        elif opcode in {0x02, 0x05, 0x08}:
            dst, src = (units[current] >> 8) & 0xFF, units[current + 1]
            if dst < registers_size and src < registers_size:
                regs[dst] = regs[src]
        elif opcode == 0x12:
            dst = (units[current] >> 8) & 0xF
            if dst < registers_size:
                regs[dst] = ("Int", _sign_extend((units[current] >> 12) & 0xF, 4))
        elif opcode == 0x13:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = ("Int", _sign_extend(units[current + 1], 16))
        elif opcode == 0x14:
            dst = (units[current] >> 8) & 0xFF
            raw = units[current + 1] | (units[current + 2] << 16)
            if dst < registers_size:
                regs[dst] = ("Int", _sign_extend(raw, 32))
        elif opcode == 0x15:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = ("Int", _sign_extend(units[current + 1], 16) << 16)
        elif opcode in {0x1A, 0x1B}:
            dst = (units[current] >> 8) & 0xFF
            index = units[current + 1] if opcode == 0x1A else units[current + 1] | (units[current + 2] << 16)
            if dst < registers_size and index < len(strings):
                regs[dst] = ("String", strings[index])
        elif opcode == 0x1C:
            dst, index = (units[current] >> 8) & 0xFF, units[current + 1]
            if dst < registers_size and index < len(types):
                regs[dst] = ("Class", types[index])
        elif opcode in {0x0A, 0x0B, 0x0C}:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = pending if pending_at is not None and pending_at + widths[pending_at] == current else DEX_TOP
        elif opcode in range(0x6E, 0x73) or opcode in range(0x74, 0x79):
            method_index = units[current + 1]
            try:
                invoke_regs = _decode_invoke_registers(units, current)
            except ValidationError:
                invoke_regs = []
            if method_index < len(methods) and all(reg < registers_size for reg in invoke_regs):
                owner, name, descriptor = methods[method_index]
                family_token = {0x6E: "VIRTUAL", 0x6F: "VIRTUAL_OR_SUPER", 0x70: "DIRECT", 0x71: "STATIC", 0x72: "INTERFACE", 0x74: "VIRTUAL", 0x75: "VIRTUAL_OR_SUPER", 0x76: "DIRECT", 0x77: "STATIC", 0x78: "INTERFACE"}[opcode]
                values = [regs[reg] for reg in invoke_regs]
                for family in ("reflection_target", "dynamic_loader"):
                    matches = [row for row in callsites[family] if (row["owner"], row["name"], row["descriptor"]) == (owner, name, descriptor) and row["opcode_family"] in {family_token, "VIRTUAL_OR_SUPER" if family_token == "VIRTUAL" else family_token}]
                    if len(matches) == 1:
                        target = _evaluate_target_recipe(
                            matches[0]["target_recipe"],
                            values,
                            has_receiver=opcode not in {0x71, 0x77},
                        )
                        if target is not None:
                            produced = (
                                ("Class", target["class_descriptor"])
                                if target.get("target_kind") == "class"
                                else ("Target", target)
                            )
                for reg in invoke_regs:
                    if isinstance(regs[reg], tuple) and regs[reg][0] == "Array":
                        regs[reg] = ("Array", regs[reg][1], tuple(DEX_TOP for _ in regs[reg][2]))
        next_pending = produced
        next_pending_at = current if produced is not None else None
        out_state = (tuple(regs), next_pending, next_pending_at)
        for successor in successors(current, opcode):
            if successor not in start_set:
                continue
            old = entry.get(successor)
            if old is None:
                new = out_state
            else:
                new_regs = tuple(_dex_join_value(a, b) for a, b in zip(old[0], out_state[0]))
                new = (new_regs, _dex_join_value(old[1], out_state[1]), old[2] if old[2] == out_state[2] else None)
            if old != new:
                entry[successor] = new
                if successor not in worklist:
                    worklist.append(successor)

    results: dict[tuple[str, int], dict[str, Any]] = {}
    for current in starts:
        opcode = units[current] & 0xFF
        if opcode not in set(range(0x6E, 0x73)) | set(range(0x74, 0x79)):
            continue
        state = entry.get(current)
        if state is None:
            continue
        method_index = units[current + 1]
        try:
            invoke_regs = _decode_invoke_registers(units, current)
        except ValidationError:
            continue
        if method_index >= len(methods) or not all(reg < registers_size for reg in invoke_regs):
            continue
        owner, name, descriptor = methods[method_index]
        family_token = {0x6E: "VIRTUAL", 0x6F: "VIRTUAL_OR_SUPER", 0x70: "DIRECT", 0x71: "STATIC", 0x72: "INTERFACE", 0x74: "VIRTUAL", 0x75: "VIRTUAL_OR_SUPER", 0x76: "DIRECT", 0x77: "STATIC", 0x78: "INTERFACE"}[opcode]
        values = [state[0][reg] for reg in invoke_regs]
        for family in ("reflection_target", "dynamic_loader"):
            matches = [row for row in callsites[family] if (row["owner"], row["name"], row["descriptor"]) == (owner, name, descriptor) and row["opcode_family"] in {family_token, "VIRTUAL_OR_SUPER" if family_token == "VIRTUAL" else family_token}]
            if len(matches) == 1:
                target = _evaluate_target_recipe(
                    matches[0]["target_recipe"],
                    values,
                    has_receiver=opcode not in {0x71, 0x77},
                )
                if target is not None:
                    results[(family, current)] = target
    return results


def parse_dex_callsites(
    data: bytes,
    artifact_id: str,
    callsites: Mapping[str, Any],
) -> dict[str, Any]:
    """Bounded direct-byte DEX tables/code/invoke membership parser."""

    counts = parse_dex_counts(data)
    string_count, string_off = struct.unpack_from("<II", data, 56)
    type_count, type_off = struct.unpack_from("<II", data, 64)
    proto_count, proto_off = struct.unpack_from("<II", data, 72)
    method_count, method_off = struct.unpack_from("<II", data, 88)
    class_count, class_off = struct.unpack_from("<II", data, 96)
    require(type_off + type_count * 4 <= len(data), "dex_table_range")
    require(proto_off + proto_count * 12 <= len(data), "dex_table_range")
    strings: list[str] = []
    identity_strings: list[str] = []
    for index in range(string_count):
        item_offset = struct.unpack_from("<I", data, string_off + index * 4)[0]
        declared, pos = _read_uleb(data, item_offset)
        end = data.find(b"\0", pos)
        require(end >= 0, "dex_invalid_mutf8")
        units = decode_mutf8_item(data[item_offset:pos] + data[pos : end + 1], identity=False)
        require(len(units) == declared, "dex_invalid_mutf8")
        raw = b"".join(int(unit).to_bytes(2, "little") for unit in units)
        identity_text = raw.decode("utf-16-le", "surrogatepass")
        identity_strings.append(identity_text)
        strings.append(unicodedata.normalize("NFC", identity_text))
    types: list[str] = []
    identity_types: list[str] = []
    for index in range(type_count):
        string_idx = struct.unpack_from("<I", data, type_off + index * 4)[0]
        require(string_idx < string_count, "dex_type_index")
        descriptor = strings[string_idx]
        require(not any(0xD800 <= ord(ch) <= 0xDFFF for ch in descriptor), "dex_identity_surrogate")
        try:
            end = _parse_dex_field_type(descriptor, 0, True)
            require(end == len(descriptor), "dex_descriptor")
        except ValidationError as exc:
            raise ValidationError("dex_descriptor", descriptor) from exc
        types.append(descriptor)
        identity_types.append(identity_strings[string_idx])
    protos: list[str] = []
    identity_protos: list[str] = []
    for index in range(proto_count):
        shorty_idx, return_idx, parameters_off = struct.unpack_from("<III", data, proto_off + index * 12)
        require(shorty_idx < string_count and return_idx < type_count, "dex_proto_index")
        parameters: list[str] = []
        identity_parameters: list[str] = []
        if parameters_off:
            require(parameters_off + 4 <= len(data), "dex_proto_parameters")
            size = struct.unpack_from("<I", data, parameters_off)[0]
            require(parameters_off + 4 + size * 2 <= len(data), "dex_proto_parameters")
            for ordinal in range(size):
                type_idx = struct.unpack_from("<H", data, parameters_off + 4 + ordinal * 2)[0]
                require(type_idx < type_count and types[type_idx] != "V", "dex_proto_parameters")
                parameters.append(types[type_idx])
                identity_parameters.append(identity_types[type_idx])
        descriptor = "(" + "".join(parameters) + ")" + types[return_idx]
        try:
            validate_method_descriptor(descriptor)
        except ValidationError as exc:
            raise ValidationError("dex_descriptor", descriptor) from exc
        protos.append(descriptor)
        identity_protos.append("(" + "".join(identity_parameters) + ")" + identity_types[return_idx])
    methods: list[tuple[str, str, str]] = []
    identity_methods: list[tuple[str, str, str]] = []
    for index in range(method_count):
        class_idx, proto_idx, name_idx = struct.unpack_from("<HHI", data, method_off + index * 8)
        require(class_idx < type_count and proto_idx < proto_count and name_idx < string_count, "dex_method_index")
        owner, name, descriptor = types[class_idx], strings[name_idx], protos[proto_idx]
        require(not any(0xD800 <= ord(ch) <= 0xDFFF for ch in name), "dex_identity_surrogate")
        require(owner != "V" and (owner.startswith("L") or owner.startswith("[")) and name and all(c not in ".;/[()" and ord(c) != 0 for c in name), "dex_method_name", f"{owner}->{name}")
        methods.append((owner, name, descriptor))
        raw_owner = identity_strings[struct.unpack_from("<I", data, type_off + class_idx * 4)[0]]
        raw_name = identity_strings[name_idx]
        identity_methods.append((raw_owner, raw_name, identity_protos[proto_idx]))
    api_maps: dict[str, dict[tuple[str, str, str], list[Mapping[str, Any]]]] = {}
    opcode_family = {0x6E: "VIRTUAL", 0x6F: "VIRTUAL_OR_SUPER", 0x70: "DIRECT", 0x71: "STATIC", 0x72: "INTERFACE", 0x74: "VIRTUAL", 0x75: "VIRTUAL_OR_SUPER", 0x76: "DIRECT", 0x77: "STATIC", 0x78: "INTERFACE"}
    for family in ("reflection_target", "dynamic_loader"):
        mapping: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in callsites[family]:
            mapping[(row["owner"], row["name"], row["descriptor"])].append(row)
        api_maps[family] = mapping
    invoke_rows: list[list[Any]] = []
    admitted: dict[str, list[dict[str, Any]]] = {"reflection_target": [], "dynamic_loader": []}
    native_declarations: list[dict[str, Any]] = []
    class_payloads: list[dict[str, Any]] = []
    method_definitions: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    code_seen: set[int] = set()
    for class_def_index in range(class_count):
        class_idx, class_flags, superclass_idx, interfaces_off, _source, _annotations, class_data_off, _static = struct.unpack_from("<IIIIIIII", data, class_off + class_def_index * 32)
        require(class_idx < len(types) and (superclass_idx == 0xFFFFFFFF or superclass_idx < len(types)), "dex_class_index")
        interfaces: list[str] = []
        if interfaces_off:
            require(interfaces_off + 4 <= len(data), "dex_interfaces")
            interface_count = struct.unpack_from("<I", data, interfaces_off)[0]
            require(interfaces_off + 4 + interface_count * 2 <= len(data), "dex_interfaces")
            for ordinal in range(interface_count):
                interface_idx = struct.unpack_from("<H", data, interfaces_off + 4 + ordinal * 2)[0]
                require(interface_idx < len(types), "dex_interfaces")
                interfaces.append(types[interface_idx])
        class_payloads.append({
            "dex_artifact_id": artifact_id,
            "descriptor": types[class_idx],
            "access_flags": class_flags,
            "superclass": None if superclass_idx == 0xFFFFFFFF else types[superclass_idx],
            "interfaces": sorted(set(interfaces)),
        })
        if not class_data_off:
            continue
        cursor = class_data_off
        static_fields, cursor = _read_uleb(data, cursor)
        instance_fields, cursor = _read_uleb(data, cursor)
        direct_methods, cursor = _read_uleb(data, cursor)
        virtual_methods, cursor = _read_uleb(data, cursor)
        for total in (static_fields, instance_fields):
            idx = 0
            for _ in range(total):
                diff, cursor = _read_uleb(data, cursor)
                _access, cursor = _read_uleb(data, cursor)
                idx += diff
        for total in (direct_methods, virtual_methods):
            method_idx = 0
            for _ in range(total):
                diff, cursor = _read_uleb(data, cursor)
                access, cursor = _read_uleb(data, cursor)
                code_off, cursor = _read_uleb(data, cursor)
                method_idx += diff
                require(method_idx < method_count, "dex_method_index")
                owner, name, descriptor = methods[method_idx]
                method_definitions[(owner, name)].append({"descriptor": descriptor, "access_flags": access})
                if access & 0x100:
                    raw_owner, raw_name, raw_descriptor = identity_methods[method_idx]
                    native_declarations.append({
                        "dex_artifact_id": artifact_id,
                        "class_descriptor": owner,
                        "method_name": name,
                        "descriptor": descriptor,
                        "is_static": bool(access & 0x8),
                        "mangle_class_descriptor": raw_owner,
                        "mangle_method_name": raw_name,
                        "mangle_descriptor": raw_descriptor,
                    })
                if not code_off:
                    continue
                require(code_off not in code_seen, "dex_duplicate_code_item")
                code_seen.add(code_off)
                require(code_off % 4 == 0 and code_off + 16 <= len(data), "dex_code_item")
                registers_size, _ins_size, _outs_size, tries_size, _debug_off, insns_size = struct.unpack_from("<HHHHII", data, code_off)
                require(code_off + 16 + insns_size * 2 <= len(data), "dex_code_item")
                units = struct.unpack_from(f"<{insns_size}H", data, code_off + 16) if insns_size else ()
                try:
                    interpreted_targets = interpret_dex_code(units, registers_size, strings, types, methods, callsites)
                except ValidationError:
                    # Malformed executable structure remains a hard DEX error;
                    # non-executable obfuscator fill is already excluded by the
                    # bounded instruction-start decoder above.
                    raise
                offset = 0
                while offset < len(units):
                    try:
                        width = _dex_instruction_width(units, offset)
                    except ValidationError as exc:
                        raise ValidationError(exc.code, f"code_off={code_off} {exc.detail}") from exc
                    if offset + width > len(units):
                        # Obfuscators may leave non-executable fill units at the
                        # tail of an otherwise valid code item. They are kept in
                        # raw instruction membership but cannot form an invoke.
                        break
                    opcode = units[offset] & 0xFF
                    if opcode in opcode_family:
                        invoked_idx = units[offset + 1]
                        try:
                            registers = _decode_invoke_registers(units, offset)
                        except ValidationError:
                            offset += width
                            continue
                        if invoked_idx >= method_count or not all(reg < registers_size for reg in registers):
                            offset += width
                            continue
                        owner, name, descriptor = methods[invoked_idx]
                        caller_owner, caller_name, caller_descriptor = methods[method_idx]
                        invoke_rows.append([artifact_id, class_def_index, method_idx, offset, opcode, owner, name, descriptor])
                        for family in ("reflection_target", "dynamic_loader"):
                            matches = [row for row in api_maps[family].get((owner, name, descriptor), []) if row["opcode_family"] in {opcode_family[opcode], "VIRTUAL_OR_SUPER" if opcode_family[opcode] == "VIRTUAL" else opcode_family[opcode]}]
                            require(len(matches) <= 1, "dex_api_ambiguous")
                            if matches:
                                admitted[family].append({
                                    "caller": {"dex_artifact_id": artifact_id, "class_descriptor": caller_owner, "method_name": caller_name, "descriptor": caller_descriptor},
                                    "instruction_offset_code_units": offset,
                                    "api": {"class_descriptor": owner, "method_name": name, "descriptor": descriptor},
                                    "target": interpreted_targets.get((family, offset), {"unresolved_token": "not_statically_resolved"}),
                                })
                    offset += width
                if tries_size:
                    tries_start = code_off + 16 + insns_size * 2 + (2 if insns_size & 1 else 0)
                    require(tries_start + tries_size * 8 <= len(data), "dex_try_item")
    for family in admitted:
        admitted[family].sort(key=lambda row: canonical_json_bytes(row))
    class_payloads.sort(key=lambda payload: record_id("class", payload))
    method_family_payloads = []
    for (owner, name), definitions_rows in method_definitions.items():
        definitions_rows.sort(key=canonical_json_bytes)
        require(len(definitions_rows) == len({canonical_json_bytes(row) for row in definitions_rows}), "dex_method_family_duplicate")
        method_family_payloads.append({
            "dex_artifact_id": artifact_id,
            "class_descriptor": owner,
            "method_name": name,
            "definitions": definitions_rows,
        })
    method_family_payloads.sort(key=lambda payload: record_id("method_family", payload))
    require(len(class_payloads) == counts["classes"], "dex_class_payload_count")
    require(len(method_family_payloads) == counts["method_families"], "dex_method_family_payload_count")
    return {
        "counts": counts,
        "physical_invoke_count": len(invoke_rows),
        "physical_invoke_membership_sha256": canonical_digest(invoke_rows),
        "reflection_target_count": len(admitted["reflection_target"]),
        "reflection_target_payloads_sha256": canonical_digest(admitted["reflection_target"]),
        "dynamic_loader_count": len(admitted["dynamic_loader"]),
        "dynamic_loader_payloads_sha256": canonical_digest(admitted["dynamic_loader"]),
        "admitted": admitted,
        "native_declarations": sorted(native_declarations, key=canonical_json_bytes),
        "class_payloads": class_payloads,
        "method_family_payloads": method_family_payloads,
    }


def _decode_utf16_scalar(raw: bytes) -> str:
    try:
        return unicodedata.normalize("NFC", raw.decode("utf-16-le", "strict"))
    except UnicodeDecodeError as exc:
        raise ValidationError("axml_invalid_string", str(exc)) from exc


def _length8(data: bytes, pos: int) -> tuple[int, int]:
    require(pos < len(data), "axml_invalid_string")
    first = data[pos]
    pos += 1
    if first & 0x80:
        require(pos < len(data), "axml_invalid_string")
        return ((first & 0x7F) << 8) | data[pos], pos + 1
    return first, pos


def _length16(data: bytes, pos: int) -> tuple[int, int]:
    require(pos + 2 <= len(data), "axml_invalid_string")
    first = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    if first & 0x8000:
        require(pos + 2 <= len(data), "axml_invalid_string")
        second = struct.unpack_from("<H", data, pos)[0]
        return ((first & 0x7FFF) << 16) | second, pos + 2
    return first, pos


def parse_string_pool(data: bytes, offset: int) -> tuple[list[str], int]:
    require(offset + 28 <= len(data), "axml_string_pool")
    chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
    require(chunk_type == 1 and header_size == 28 and chunk_size >= 28 and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "axml_string_pool")
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from("<IIIII", data, offset + 8)
    require(flags & ~0x101 == 0, "axml_string_pool")
    require(header_size + 4 * (string_count + style_count) <= chunk_size, "axml_string_pool")
    require(strings_start >= header_size + 4 * (string_count + style_count) and strings_start < chunk_size, "axml_string_pool")
    if style_count:
        require(styles_start >= strings_start and styles_start < chunk_size, "axml_string_pool")
    else:
        require(styles_start == 0, "axml_string_pool")
    strings: list[str] = []
    for index in range(string_count):
        relative = struct.unpack_from("<I", data, offset + header_size + index * 4)[0]
        pos = offset + strings_start + relative
        require(pos < offset + chunk_size, "axml_invalid_string")
        if flags & 0x100:
            utf16_len, pos = _length8(data, pos)
            byte_len, pos = _length8(data, pos)
            require(pos + byte_len + 1 <= offset + chunk_size and data[pos + byte_len] == 0, "axml_invalid_string")
            try:
                text = data[pos : pos + byte_len].decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise ValidationError("axml_invalid_string", str(exc)) from exc
            require(len(text.encode("utf-16-le")) // 2 == utf16_len, "axml_invalid_string")
            strings.append(unicodedata.normalize("NFC", text))
        else:
            utf16_len, pos = _length16(data, pos)
            byte_len = utf16_len * 2
            require(pos + byte_len + 2 <= offset + chunk_size and data[pos + byte_len : pos + byte_len + 2] == b"\0\0", "axml_invalid_string")
            strings.append(_decode_utf16_scalar(data[pos : pos + byte_len]))
    return strings, offset + chunk_size


ANDROID_NS = "http://schemas.android.com/apk/res/android"


def parse_axml(data: bytes) -> dict[str, Any]:
    require(len(data) >= 8, "axml_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    require(root_type == 3 and root_header == 8 and root_size == len(data), "axml_root")
    strings, offset = parse_string_pool(data, 8)
    namespace_stack: list[tuple[str, str]] = []
    resource_map: list[int] | None = None
    if offset < len(data):
        require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        if chunk_type == 0x0180:
            require(header_size == 8 and chunk_size >= 8 and chunk_size % 4 == 0, "axml_resource_map")
            resource_map = list(struct.unpack_from(f"<{(chunk_size - 8) // 4}I", data, offset + 8))
            offset += chunk_size
    stack: list[dict[str, Any]] = []
    event_ordinal = 0
    nodes: list[dict[str, Any]] = []
    feature_values: list[dict[str, Any]] = []
    component_declarations: list[tuple[str, str | None, str]] = []
    package_name: str | None = None
    split_id: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    while offset < len(data):
        require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        require(header_size >= 8 and chunk_size >= header_size and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "axml_chunk")
        if chunk_type == 0x0102:
            require(header_size == 16 and offset + 36 <= len(data), "axml_start_element")
            extension = offset + header_size
            ns_idx, name_idx, attr_start, attr_size, attr_count, _id_index, _class_index, _style_index = struct.unpack_from(
                "<IIHHHHHH", data, extension
            )
            require(name_idx < len(strings) and attr_start == 20 and attr_size == 20, "axml_start_element")
            require(ns_idx == 0xFFFFFFFF or ns_idx < len(strings), "axml_string_index")
            namespace = "" if ns_idx == 0xFFFFFFFF else strings[ns_idx]
            local_name = strings[name_idx]
            qname = qname_value(namespace, local_name)
            sibling_counts = stack[-1]["sibling_counts"] if stack else defaultdict(int)
            sibling_counts[qname] += 1
            ordinal = sibling_counts[qname]
            path = (stack[-1]["path"] if stack else "axmlpath:") + f"/{qname}[{ordinal}]"
            attrs: dict[tuple[str, str], dict[str, Any]] = {}
            physical_attrs: list[dict[str, Any]] = []
            attr_offset = extension + attr_start
            for attr_ordinal in range(attr_count):
                base = attr_offset + attr_ordinal * 20
                require(base + 20 <= offset + chunk_size, "axml_attribute")
                ans, aname, raw_value, value_size, res0, data_type, value_data = struct.unpack_from("<IIIHBBI", data, base)
                require(aname < len(strings) and value_size == 8 and res0 == 0, "axml_attribute")
                require(ans == 0xFFFFFFFF or ans < len(strings), "axml_string_index")
                require(raw_value == 0xFFFFFFFF or raw_value < len(strings), "axml_string_index")
                require(data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31}, "axml_value_type")
                ans_text = "" if ans == 0xFFFFFFFF else strings[ans]
                attr_name = strings[aname]
                key = (ans_text, attr_name)
                require(key not in attrs, "axml_duplicate_attribute")
                if data_type == 3:
                    require(value_data < len(strings), "axml_string_index")
                    typed = strings[value_data]
                else:
                    typed = None
                raw_text = None if raw_value == 0xFFFFFFFF else strings[raw_value]
                value = {
                    "namespace": ans_text,
                    "name": attr_name,
                    "attribute_ordinal": attr_ordinal,
                    "qname": qname_value(ans_text, attr_name),
                    "raw": raw_text,
                    "type": data_type,
                    "data": value_data,
                    "typed": typed,
                    "resource_id": (
                        resource_map[aname]
                        if resource_map is not None and aname < len(resource_map) and resource_map[aname] != 0
                        else None
                    ),
                }
                attrs[key] = value
                physical_attrs.append(value)
            node = {
                "event_ordinal": event_ordinal,
                "name": local_name,
                "namespace": namespace,
                "qname": qname,
                "path": path,
                "attrs": attrs,
                "attributes": sorted(
                    [
                        {
                            "attribute_ordinal": item["attribute_ordinal"],
                            "qname": item["qname"],
                            "raw_value": item["raw"],
                            "resource_id": item["resource_id"],
                            "data_type": item["type"],
                            "data": item["data"],
                            "typed_string": item["typed"],
                        }
                        for item in physical_attrs
                    ],
                    key=canonical_json_bytes,
                ),
            }
            nodes.append(node)
            if not stack and local_name == "manifest":
                package_attr = attrs.get(("", "package"))
                split_attr = attrs.get(("", "split"))
                package_name = (package_attr or {}).get("typed") or (package_attr or {}).get("raw")
                split_id = (split_attr or {}).get("typed") or (split_attr or {}).get("raw")
            if len(stack) == 1 and local_name == "uses-sdk":
                min_attr = attrs.get((ANDROID_NS, "minSdkVersion"))
                target_attr = attrs.get((ANDROID_NS, "targetSdkVersion"))
                if min_attr:
                    min_sdk = int(min_attr["data"])
                if target_attr:
                    target_sdk = int(target_attr["data"])
            if len(stack) == 1 and local_name == "uses-feature":
                name_attr = attrs.get((ANDROID_NS, "name"))
                gl_attr = attrs.get((ANDROID_NS, "glEsVersion"))
                req_attr = attrs.get((ANDROID_NS, "required"))
                feature_values.append(
                    {
                        "name": (name_attr or {}).get("typed"),
                        "gl_es_version": int(gl_attr["data"]) if gl_attr else None,
                        "required": bool(req_attr["data"]) if req_attr else True,
                    }
                )
            if local_name in {"application", "activity", "activity-alias", "service", "receiver", "provider"}:
                name_attr = attrs.get((ANDROID_NS, "name"))
                name = (name_attr or {}).get("typed") or (name_attr or {}).get("raw")
                component_declarations.append((local_name, name, path))
            stack.append({"qname": qname, "path": path, "sibling_counts": defaultdict(int)})
        elif chunk_type == 0x0103:
            require(header_size == 16 and stack, "axml_end_element")
            ns_idx, name_idx = struct.unpack_from("<II", data, offset + header_size)
            require(ns_idx == 0xFFFFFFFF or ns_idx < len(strings), "axml_string_index")
            namespace = "" if ns_idx == 0xFFFFFFFF else strings[ns_idx]
            require(name_idx < len(strings), "axml_end_element")
            require(stack[-1]["qname"] == qname_value(namespace, strings[name_idx]), "axml_end_element")
            stack.pop()
        elif chunk_type in {0x0100, 0x0101}:
            require(header_size == 16 and chunk_size == 24, "axml_namespace")
            prefix_idx, uri_idx = struct.unpack_from("<II", data, offset + 16)
            require(prefix_idx < len(strings) and uri_idx < len(strings), "axml_string_index")
            pair = (strings[prefix_idx], strings[uri_idx])
            if chunk_type == 0x0100:
                namespace_stack.append(pair)
            else:
                require(namespace_stack and namespace_stack[-1] == pair, "axml_namespace")
                namespace_stack.pop()
        elif chunk_type == 0x0104:
            require(header_size == 16 and chunk_size == 28, "axml_cdata")
            data_idx, value_size, res0, data_type, value_data = struct.unpack_from("<IHBBI", data, offset + 16)
            require(data_idx < len(strings) and value_size == 8 and res0 == 0, "axml_cdata")
            require(data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31}, "axml_value_type")
            if data_type == 3:
                require(value_data < len(strings), "axml_string_index")
        else:
            raise ValidationError("axml_unknown_chunk")
        event_ordinal += 1
        offset += chunk_size
    require(not stack and not namespace_stack, "axml_stack")
    return {
        "nodes": nodes,
        "features": feature_values,
        "components": component_declarations,
        "package": package_name,
        "split": split_id,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
    }


def pct(value: str) -> str:
    result: list[str] = []
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
    for byte in value.encode("utf-8"):
        if byte in unreserved:
            result.append(chr(byte))
        else:
            result.append(f"%{byte:02X}")
    return "".join(result)


def qname_value(namespace: str, local_name: str) -> str:
    return f"Q{{{pct(namespace)}}}{pct(local_name)}"


def count_arsc(data: bytes, apk_artifact_id: str) -> tuple[int, int, list[dict[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    require(len(data) >= 12, "arsc_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    require(root_type == 2 and root_header == 12 and root_size == len(data), "arsc_root")
    package_count = struct.unpack_from("<I", data, 8)[0]
    logical: set[tuple[str, int, int, int]] = set()
    resource_payloads: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    configuration_payloads: list[dict[str, Any]] = []
    configuration_count = 0
    package_summaries: list[dict[str, int]] = []
    offset = root_header
    global_strings: list[str] | None = None
    package_ordinal = 0
    while offset < len(data):
        require(offset + 8 <= len(data), "arsc_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        require(header_size >= 8 and chunk_size >= header_size and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "arsc_chunk")
        if chunk_type == 0x0200:
            require(header_size in {284, 288}, "arsc_package_header")
            package_id = struct.unpack_from("<I", data, offset + 8)[0]
            require(1 <= package_id <= 255, "arsc_package_id")
            type_id_offset = struct.unpack_from("<I", data, offset + 284)[0] if header_size == 288 else 0
            type_strings_off = struct.unpack_from("<I", data, offset + 268)[0]
            key_strings_off = struct.unpack_from("<I", data, offset + 276)[0]
            require(type_strings_off >= header_size and key_strings_off >= header_size, "arsc_package_string_pool")
            type_strings, _ = parse_string_pool(data, offset + type_strings_off)
            key_strings, _ = parse_string_pool(data, offset + key_strings_off)
            raw_name = data[offset + 12 : offset + 268]
            nul = raw_name.find(b"\0\0")
            if nul < 0:
                nul = len(raw_name)
            if nul & 1:
                nul += 1
            package_name = _decode_utf16_scalar(raw_name[:nul]) if nul else ""
            require(bool(package_name), "arsc_package_name")
            child = offset + header_size
            type_chunks = 0
            type_specs: dict[int, tuple[int, int]] = {}
            type_chunk_counts: Counter[int] = Counter()
            while child < offset + chunk_size:
                ctype, cheader, csize = struct.unpack_from("<HHI", data, child)
                require(cheader >= 8 and csize >= cheader and csize % 4 == 0 and child + csize <= offset + chunk_size, "arsc_package_child")
                if ctype == 0x0202:
                    require(cheader == 16 and csize >= 16, "arsc_type_spec")
                    spec_id = data[child + 8]
                    require(data[child + 9] == 0, "arsc_type_spec")
                    declared_types_count = struct.unpack_from("<H", data, child + 10)[0]
                    spec_count = struct.unpack_from("<I", data, child + 12)[0]
                    require(spec_id not in type_specs and child + 16 + spec_count * 4 == child + csize, "arsc_type_spec")
                    type_specs[spec_id] = (spec_count, declared_types_count)
                elif ctype == 0x0201:
                    require(cheader >= 24, "arsc_type_chunk")
                    raw_type_id = data[child + 8]
                    flags = data[child + 9]
                    reserved = struct.unpack_from("<H", data, child + 10)[0]
                    entry_count = struct.unpack_from("<I", data, child + 12)[0]
                    entries_start = struct.unpack_from("<I", data, child + 16)[0]
                    config_size = struct.unpack_from("<I", data, child + 20)[0]
                    require(reserved == 0 and flags & ~0x03 == 0 and flags != 0x03, "arsc_type_flags")
                    require(config_size >= 4 and config_size % 4 == 0 and cheader == 20 + config_size, "arsc_invalid_config_size")
                    require(cheader <= entries_start <= csize, "arsc_entries_start")
                    effective_type = raw_type_id + type_id_offset
                    require(1 <= raw_type_id <= 255 and 1 <= effective_type <= 255, "arsc_effective_type")
                    index_start = child + cheader
                    require(raw_type_id in type_specs, "arsc_type_spec_missing")
                    spec_entry_count = type_specs[raw_type_id][0]
                    type_chunk_counts[raw_type_id] += 1
                    present_entries: list[tuple[int, int, int]] = []
                    if flags & 0x01:
                        require(index_start + entry_count * 4 <= child + entries_start, "arsc_sparse_range")
                        previous = -1
                        for index in range(entry_count):
                            entry_id, offset_div4 = struct.unpack_from("<HH", data, index_start + index * 4)
                            require(entry_id > previous, "arsc_sparse_order")
                            require(entry_id < spec_entry_count, "arsc_sparse_entry_id")
                            previous = entry_id
                            present_entries.append((index, entry_id, offset_div4 * 4))
                    elif flags & 0x02:
                        require(index_start + entry_count * 2 <= child + entries_start, "arsc_offset16_range")
                        for index in range(entry_count):
                            value = struct.unpack_from("<H", data, index_start + index * 2)[0]
                            if value != 0xFFFF:
                                present_entries.append((index, index, value * 4))
                    else:
                        require(index_start + entry_count * 4 <= child + entries_start, "arsc_dense_range")
                        for index in range(entry_count):
                            value = struct.unpack_from("<I", data, index_start + index * 4)[0]
                            if value != 0xFFFFFFFF:
                                present_entries.append((index, index, value))
                    configuration_count += len(present_entries)
                    entry_offsets = [entry_offset for _ordinal, _entry_id, entry_offset in present_entries]
                    require(len(entry_offsets) == len(set(entry_offsets)), "arsc_entry_offset_duplicate")
                    for entry_ordinal, entry_id, entry_relative in present_entries:
                        require(entry_id <= 0xFFFF, "arsc_entry_id")
                        require(entry_relative % 4 == 0, "arsc_entry_alignment")
                        entry = child + entries_start + entry_relative
                        require(entry + 8 <= child + csize, "arsc_entry_range")
                        entry_size, entry_flags, key_index = struct.unpack_from("<HHI", data, entry)
                        require(entry_flags & ~0x000F == 0 and key_index < len(key_strings), "arsc_entry")
                        require(raw_type_id - 1 < len(type_strings), "arsc_type_name")
                        type_name = type_strings[raw_type_id - 1]
                        entry_name = key_strings[key_index]
                        key = (apk_artifact_id, package_ordinal, effective_type, entry_id)
                        logical.add(key)
                        resource_payload = {
                            "apk_artifact_id": apk_artifact_id,
                            "package_chunk_ordinal": package_ordinal,
                            "package_id": package_id,
                            "package_name": package_name,
                            "raw_type_id": raw_type_id,
                            "type_id_offset": type_id_offset,
                            "type_id": effective_type,
                            "entry_id": entry_id,
                            "resource_id": f"0x{((package_id << 24) | (effective_type << 16) | entry_id):08x}",
                            "type_name": type_name,
                            "entry_name": entry_name,
                        }
                        if key in resource_payloads:
                            require(resource_payloads[key] == resource_payload, "arsc_resource_conflict")
                        else:
                            resource_payloads[key] = resource_payload
                        resource_record_id = record_id("resource", resource_payload)

                        def scalar_value(value_offset: int) -> dict[str, Any]:
                            require(value_offset + 8 <= child + csize, "arsc_value_range")
                            value_size, res0, data_type, value_data = struct.unpack_from("<HBBI", data, value_offset)
                            require(value_size == 8 and res0 == 0, "arsc_value")
                            string_value = None
                            if data_type == 3:
                                require(global_strings is not None and value_data < len(global_strings), "arsc_string_value")
                                string_value = global_strings[value_data]
                            return {"kind": "scalar", "data_type": data_type, "data": value_data, "string_value": string_value}

                        if entry_flags & 0x0008:
                            raise ValidationError("arsc_compact_entry_unsupported")
                        if entry_flags & 0x0001:
                            require(entry_size == 16 and entry + 16 <= child + csize, "arsc_bag_entry")
                            parent_id, item_count = struct.unpack_from("<II", data, entry + 8)
                            items: list[dict[str, Any]] = []
                            map_offset = entry + 16
                            require(map_offset + item_count * 12 <= child + csize, "arsc_bag_entry")
                            for map_ordinal in range(item_count):
                                base = map_offset + map_ordinal * 12
                                name_resource_id = struct.unpack_from("<I", data, base)[0]
                                scalar = scalar_value(base + 4)
                                items.append({"map_ordinal": map_ordinal, "name_resource_id": name_resource_id, "data_type": scalar["data_type"], "data": scalar["data"], "string_value": scalar["string_value"]})
                            normalized_value: dict[str, Any] = {"kind": "bag", "parent_resource_id": parent_id, "items": items}
                        else:
                            require(entry_size == 8, "arsc_scalar_entry")
                            normalized_value = scalar_value(entry + 8)
                        config_bytes = data[child + 20 : child + 20 + config_size]
                        configuration_payloads.append({
                            "configuration_kind": "resource_configuration",
                            "resource_record_id": resource_record_id,
                            "package_chunk_ordinal": package_ordinal,
                            "type_chunk_ordinal": type_chunks,
                            "entry_index_ordinal": entry_ordinal,
                            "entry_id": entry_id,
                            "entry_encoding": "full",
                            "entry_flags": entry_flags,
                            "key_index": key_index,
                            "configuration": {"size_bytes": config_size, "bytes_hex": config_bytes.hex()},
                            "value": normalized_value,
                        })
                    type_chunks += 1
                child += csize
            require(child == offset + chunk_size, "arsc_package_range")
            for raw_id, (_entry_count, declared_types_count) in type_specs.items():
                require(declared_types_count in {0, type_chunk_counts[raw_id]}, "arsc_type_spec_count")
            package_summaries.append(
                {
                    "package_id": package_id,
                    "type_id_offset": type_id_offset,
                    "header_size": header_size,
                    "type_chunks": type_chunks,
                }
            )
            package_ordinal += 1
        elif chunk_type == 1 and global_strings is None:
            global_strings, parsed_end = parse_string_pool(data, offset)
            require(parsed_end == offset + chunk_size, "arsc_global_string_pool")
        offset += chunk_size
    require(offset == len(data) and package_ordinal == package_count, "arsc_package_count")
    require(global_strings is not None, "arsc_global_string_pool")
    resource_rows = sorted(resource_payloads.values(), key=canonical_json_bytes)
    configuration_payloads.sort(key=canonical_json_bytes)
    return len(logical), configuration_count, package_summaries, resource_rows, configuration_payloads


def _lp32(data: bytes, offset: int, end: int) -> tuple[bytes, int]:
    require(offset + 4 <= end, "signing_length")
    size = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    require(offset + size <= end, "signing_length")
    return data[offset : offset + size], offset + size


def count_scheme_certificates(value: bytes, scheme: str) -> int:
    return len(parse_scheme_certificates(value, scheme))


def parse_scheme_certificates(value: bytes, scheme: str) -> list[tuple[int, int, bytes]]:
    signers_blob, end = _lp32(value, 0, len(value))
    require(end == len(value), "signing_length")
    signers_offset = 0
    result: list[tuple[int, int, bytes]] = []
    signer_index = 0
    while signers_offset < len(signers_blob):
        signer, signers_offset = _lp32(signers_blob, signers_offset, len(signers_blob))
        signed_data, pos = _lp32(signer, 0, len(signer))
        if scheme == "v3":
            require(pos + 8 <= len(signer), "signing_v3_sdk")
            pos += 8
        _signatures, pos = _lp32(signer, pos, len(signer))
        _public_key, pos = _lp32(signer, pos, len(signer))
        require(pos == len(signer), "signing_length")
        _digests, sd_pos = _lp32(signed_data, 0, len(signed_data))
        certificates, sd_pos = _lp32(signed_data, sd_pos, len(signed_data))
        cert_pos = 0
        certificate_index = 0
        while cert_pos < len(certificates):
            cert, cert_pos = _lp32(certificates, cert_pos, len(certificates))
            result.append((signer_index, certificate_index, cert))
            certificate_index += 1
        if scheme == "v3":
            require(sd_pos + 8 <= len(signed_data), "signing_v3_sdk")
            sd_pos += 8
        _attrs, sd_pos = _lp32(signed_data, sd_pos, len(signed_data))
        if scheme == "v2":
            require(signed_data[sd_pos:] == b"\0\0\0\0", "signing_v2_suffix")
            sd_pos += 4
        require(sd_pos == len(signed_data), "signing_length")
        signer_index += 1
    return result


def parse_apk_signing_block(path: Path, directory: ZipDirectory) -> tuple[list[int], dict[str, int], dict[str, list[tuple[int, int, bytes]]]]:
    require(directory.central_offset >= 24, "signing_block")
    with path.open("rb") as stream:
        stream.seek(directory.central_offset - 24)
        footer = stream.read(24)
        require(len(footer) == 24 and footer[8:] == b"APK Sig Block 42", "signing_block")
        trailing_size = struct.unpack_from("<Q", footer, 0)[0]
        start = directory.central_offset - (trailing_size + 8)
        require(start >= 0, "signing_block")
        stream.seek(start)
        block = stream.read(directory.central_offset - start)
    require(len(block) >= 32, "signing_block")
    require(struct.unpack_from("<Q", block, 0)[0] == trailing_size, "signing_block")
    pair_end = len(block) - 24
    offset = 8
    ids: list[int] = []
    cert_counts = {"v2": 0, "v3": 0}
    cert_rows: dict[str, list[tuple[int, int, bytes]]] = {"v2": [], "v3": []}
    while offset < pair_end:
        require(offset + 8 <= pair_end, "signing_pair")
        pair_size = struct.unpack_from("<Q", block, offset)[0]
        offset += 8
        require(pair_size >= 4 and offset + pair_size <= pair_end, "signing_pair")
        pair_id = struct.unpack_from("<I", block, offset)[0]
        value = block[offset + 4 : offset + pair_size]
        ids.append(pair_id)
        if pair_id == 0x7109871A:
            cert_rows["v2"] = parse_scheme_certificates(value, "v2")
            cert_counts["v2"] += len(cert_rows["v2"])
        elif pair_id == 0xF05368C0:
            cert_rows["v3"] = parse_scheme_certificates(value, "v3")
            cert_counts["v3"] += len(cert_rows["v3"])
        offset += pair_size
    require(offset == pair_end, "signing_pair")
    require(ids.count(0x7109871A) == 1 and ids.count(0xF05368C0) == 1, "signing_duplicate_scheme")
    return ids, cert_counts, cert_rows


def _der_tlv(data: bytes, offset: int) -> tuple[int, int, int]:
    require(offset + 2 <= len(data), "signing_v1_der")
    tag = data[offset]
    first = data[offset + 1]
    if first < 0x80:
        header = offset + 2
        length = first
    else:
        count = first & 0x7F
        require(1 <= count <= 4 and offset + 2 + count <= len(data), "signing_v1_der")
        length = int.from_bytes(data[offset + 2 : offset + 2 + count], "big")
        require(length >= 0x80, "signing_v1_der")
        header = offset + 2 + count
    end = header + length
    require(end <= len(data), "signing_v1_der")
    return tag, header, end


def parse_pkcs7_certificates(data: bytes) -> list[bytes]:
    """Extract physical CertificateChoices from a DER PKCS#7 SignedData blob."""

    tag, start, end = _der_tlv(data, 0)
    require(tag == 0x30 and end == len(data), "signing_v1_der")
    children: list[tuple[int, int, int, int]] = []
    cursor = start
    while cursor < end:
        ctag, cstart, cend = _der_tlv(data, cursor)
        children.append((ctag, cursor, cstart, cend))
        cursor = cend
    require(len(children) >= 2 and children[1][0] == 0xA0, "signing_v1_der")
    explicit_start, explicit_end = children[1][2], children[1][3]
    stag, signed_start, signed_end = _der_tlv(data, explicit_start)
    require(stag == 0x30 and signed_end == explicit_end, "signing_v1_der")
    cursor = signed_start
    signed_children: list[tuple[int, int, int, int]] = []
    while cursor < signed_end:
        ctag, cstart, cend = _der_tlv(data, cursor)
        signed_children.append((ctag, cursor, cstart, cend))
        cursor = cend
    certificate_container = next((row for row in signed_children[3:] if row[0] == 0xA0), None)
    require(certificate_container is not None, "signing_v1_der")
    cursor = certificate_container[2]
    certificates: list[bytes] = []
    while cursor < certificate_container[3]:
        ctag, _cstart, cend = _der_tlv(data, cursor)
        require(ctag == 0x30, "signing_v1_der")
        certificates.append(data[cursor:cend])
        cursor = cend
    require(certificates, "signing_v1_der")
    return certificates


def _expand_component_name(package: str, name: str) -> str:
    if name.startswith("."):
        return package + name
    if "." not in name:
        return package + "." + name
    return name


def _component_attr(node: Mapping[str, Any], name: str) -> Any:
    item = node["attrs"].get((ANDROID_NS, name))
    if item is None:
        return None
    if item.get("typed") is not None:
        return item["typed"]
    if item.get("raw") is not None:
        return item["raw"]
    if item["type"] == 18:
        return bool(item["data"])
    return item["data"]


def derive_android_component_payloads(
    manifests: Sequence[Mapping[str, Any]],
    effective_target_sdk: int,
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Merge component declarations in physical manifest order under the contract defaults."""

    merged: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    package_name: str | None = None
    for item in manifests:
        axml = item["axml"]
        package = axml["package"]
        require(isinstance(package, str) and package, "android_component_package")
        package_name = package_name or package
        require(package == package_name, "android_component_package")
        nodes_by_path = {node["path"]: node for node in axml["nodes"]}
        for kind_raw, name, path in axml["components"]:
            kind = kind_raw.replace("-", "_")
            if kind == "application":
                identity = package
            else:
                require(isinstance(name, str) and name, "android_component_name")
                identity = _expand_component_name(package, name)
            node = nodes_by_path[path]
            has_filter = any(
                candidate["name"] == "intent-filter" and candidate["path"].startswith(path + "/")
                for candidate in axml["nodes"]
            )
            merged[(kind, identity)].append({"node": node, "has_filter": has_filter, "package": package})
    require(package_name is not None, "android_component_package")

    def explicit(rows: Sequence[Mapping[str, Any]], name: str, default: Any) -> Any:
        values = [_component_attr(row["node"], name) for row in rows]
        values = [value for value in values if value is not None]
        encoded = {canonical_json_bytes(value) for value in values}
        require(len(encoded) <= 1, "android_component_merge_conflict", name)
        return values[0] if values else default

    app_rows = merged.get(("application", package_name), [])
    require(app_rows, "android_component_application")
    app_enabled = bool(explicit(app_rows, "enabled", True))
    app_process = explicit(app_rows, "process", package_name)
    app_permission = explicit(app_rows, "permission", None)
    app_direct = bool(explicit(app_rows, "directBootAware", False))
    payloads: list[dict[str, Any]] = []
    for (kind, identity), rows in merged.items():
        if kind == "application":
            payload = {
                "package": package_name,
                "kind": kind,
                "name": explicit(rows, "name", "android.app.Application"),
                "enabled": app_enabled,
                "exported": None,
                "permission": app_permission,
                "process": app_process,
                "direct_boot_aware": app_direct,
                "foreground_service_type": None,
                "target_activity": None,
                "effective_target_sdk": effective_target_sdk,
            }
        else:
            enabled = app_enabled and bool(explicit(rows, "enabled", True))
            exported_default = effective_target_sdk < 17 if kind == "provider" else any(row["has_filter"] for row in rows)
            permission_default = None if kind == "activity_alias" else app_permission
            payload = {
                "package": package_name,
                "kind": kind,
                "name": identity,
                "enabled": enabled,
                "exported": bool(explicit(rows, "exported", exported_default)),
                "permission": explicit(rows, "permission", permission_default),
                "process": explicit(rows, "process", app_process),
                "direct_boot_aware": bool(explicit(rows, "directBootAware", False)),
                "foreground_service_type": explicit(rows, "foregroundServiceType", 0 if kind == "service" else None),
                "target_activity": (
                    _expand_component_name(package_name, explicit(rows, "targetActivity", ""))
                    if kind == "activity_alias"
                    else None
                ),
                "effective_target_sdk": effective_target_sdk,
            }
        validate_schema_value(
            payload,
            contract["record_model"]["payload_schemas"]["android_component"]["payload"],
            contract["record_model"]["definitions"],
            "official_android_component",
        )
        payloads.append(payload)
    payloads.sort(key=lambda payload: record_id("android_component", payload))
    return payloads


def _fixture_disposition(case: Mapping[str, Any], contract: Mapping[str, Any], fixture_root: Path) -> tuple[str, str]:
    operation = case["operation"]
    value = case["input"]
    try:
        if operation == "canonical_object":
            canonical_json_bytes(value)
        elif operation == "record_identity":
            exact_keys(value, {"record_type", "payload", "record_id"}, "fixture_shape")
            require(record_id(value["record_type"], value["payload"]) == value["record_id"], "record_id_mismatch")
        elif operation == "outer_bytes":
            exact_keys(value, {"family", "sha256", "size_bytes"}, "fixture_shape")
            paired = value["sha256"] is not None and value["size_bytes"] is not None
            empty = value["sha256"] is None and value["size_bytes"] is None
            require(paired or empty, "outer_byte_pair")
            byte_families = set(contract["record_model"]["outer_byte_families"])
            if value["family"] in byte_families:
                require(paired, "outer_byte_policy")
            else:
                require(empty, "outer_byte_policy")
        elif operation == "raw_conservation":
            exact_keys(value, {"primitives", "decisions", "expected_members"}, "fixture_shape")
            for row in value["primitives"] + value["decisions"]:
                exact_keys(row, {"id"}, "raw_schema_extra_key")
            primitive_ids = {row["id"] for row in value["primitives"]}
            expected_ids = set(value["expected_members"])
            require(primitive_ids == expected_ids, "raw_primitive_set_mismatch")
            require({row["id"] for row in value["decisions"]} == primitive_ids, "raw_decision_set_mismatch")
        elif operation == "membership":
            exact_keys(value, {"expected", "actual"}, "fixture_shape")
            require(canonical_digest(sorted(value["expected"])) == canonical_digest(sorted(value["actual"])), "membership_digest_mismatch")
        elif operation == "source_parent":
            exact_keys(value, {"source_artifact_id", "payload_source", "parents", "expected_parents"}, "fixture_shape")
            require(value["source_artifact_id"] == value["payload_source"], "source_parent_crosswire")
            require(len(value["parents"]) == len(set(value["parents"])), "parent_duplicate")
            require(len(value["expected_parents"]) == len(set(value["expected_parents"])), "parent_duplicate")
            require(sorted(value["parents"]) == sorted(value["expected_parents"]), "parent_set_mismatch")
        elif operation == "source_reference":
            exact_keys(value, {"attachment_path", "source_locator"}, "fixture_shape")
            require(value["attachment_path"] == "source-index.json", "source_index_attachment_mismatch")
            validate_source_locator(value["source_locator"])
        elif operation == "chronology":
            validate_chronology(value)
        elif operation == "elf_fixture":
            exact_keys(value, {"path", "physical", "included", "unnamed_sections", "exports", "undefined_imports", "large_sizes"}, "fixture_shape")
            parsed = parse_elf_symbols((fixture_root / value["path"]).read_bytes())
            symbols = parsed["symbols"]
            actual = {
                "physical": parsed["count"],
                "included": len(symbols) - 1,
                "unnamed_sections": sum(x["index"] > 0 and x["name"] is None and x["symbol_type"] == "STT_SECTION" for x in symbols),
                "exports": sum(x["export"] for x in symbols),
                "undefined_imports": sum(x["undefined_import"] for x in symbols),
                "large_sizes": sum(x["export"] and x["size_bytes"] >= 100000 for x in symbols),
            }
            for key, actual_value in actual.items():
                require(actual_value == value[key], "elf_fixture_mismatch", key)
        elif operation == "elf_decision":
            exact_keys(value, {"index", "decision"}, "fixture_shape")
            if value["index"] == 0:
                require(value["decision"] == "reserved_stn_undef", "elf_reserved_index_zero")
        elif operation == "elf_large_rows":
            exact_keys(value, {"expected_count", "included_count"}, "fixture_shape")
            require(value["included_count"] == value["expected_count"], "elf_large_size_regression")
        elif operation == "mutf8":
            allowed = {"hex", "identity", "expected_units"} if "expected_units" in value else {"hex", "identity"}
            exact_keys(value, allowed, "fixture_shape")
            units = decode_mutf8_item(bytes.fromhex(value["hex"]), bool(value["identity"]))
            if "expected_units" in value:
                actual_hex = "".join(f"{unit:04x}" for unit in units)
                require(actual_hex == value["expected_units"], "dex_mutf8_value")
        elif operation == "api_lookup":
            exact_keys(value, {"family", "owner", "name", "descriptor", "opcode", "expected_matches"}, "fixture_shape")
            opcode_families = {
                110: {"VIRTUAL", "VIRTUAL_OR_SUPER"},
                111: {"VIRTUAL_OR_SUPER"},
                112: {"DIRECT"},
                113: {"STATIC"},
                114: {"INTERFACE"},
                116: {"VIRTUAL", "VIRTUAL_OR_SUPER"},
                117: {"VIRTUAL_OR_SUPER"},
                118: {"DIRECT"},
                119: {"STATIC"},
                120: {"INTERFACE"},
            }
            matches = [
                row
                for row in contract["callsites"][value["family"]]
                if (row["owner"], row["name"], row["descriptor"])
                == (value["owner"], value["name"], value["descriptor"])
                and row["opcode_family"] in opcode_families.get(value["opcode"], set())
            ]
            require(len(matches) == value["expected_matches"], "api_lookup_mismatch")
        elif operation == "preserve_list":
            exact_keys(value, {"values", "expected_values"}, "fixture_shape")
            require(value["values"] == value["expected_values"], "list_order_changed")
        elif operation == "dex_paths":
            exact_keys(value, {"value", "expected_values"}, "fixture_shape")
            require(value["value"].split(":") == value["expected_values"], "dex_path_split")
        elif operation == "abstract_join":
            exact_keys(value, {"values", "expected_value"}, "fixture_shape")
            unique = set(value["values"])
            actual = next(iter(unique)) if len(unique) == 1 else {"unresolved_token": "not_statically_resolved"}
            require(actual == value["expected_value"], "abstract_fixpoint")
        elif operation == "jni_mangle":
            expected_keys = {"class", "method", "descriptor", "short", "long"} if "short" in value else {"class", "method", "descriptor", "escape_failed"}
            exact_keys(value, expected_keys, "fixture_shape")
            short, long_name, failed = jni_names(value["class"], value["method"], value["descriptor"])
            if "short" in value:
                require((short, long_name, failed) == (value["short"], value["long"], False), "jni_mangle")
            else:
                require(failed is value["escape_failed"], "jni_escape_failure")
        elif operation == "jni_precedence":
            exact_keys(value, {"registrations", "short_exports", "long_exports", "expected_binding"}, "fixture_shape")
            if value["registrations"]:
                binding = "register_natives"
            elif value["short_exports"]:
                binding = "static_short"
            elif value["long_exports"]:
                binding = "static_long"
            else:
                binding = "unresolved_declaration"
            require(binding == value["expected_binding"], "jni_precedence")
        elif operation == "jni_raw_only":
            exact_keys(value, {"reason", "normalized_rows"}, "fixture_shape")
            require(value["reason"] in contract["reason_codes"]["jni_exclusion_precedence"], "jni_reason")
            require(value["normalized_rows"] == 0, "jni_unsupported_normalized")
        elif operation == "zip_duplicate":
            exact_keys(value, {"path", "member_path", "expected_occurrences", "expected_distinct_ids"}, "fixture_shape")
            data = (fixture_root / value["path"]).read_bytes()
            directory = parse_zip_directory_bytes(data)
            entries = [entry for entry in directory.entries if entry.path == value["member_path"]]
            require(len(entries) == value["expected_occurrences"], "zip_fixture_occurrences")
            asset_ids: set[str] = set()
            for entry in entries:
                content = extract_zip_entry_bytes(data, entry)
                archive_payload = {
                    "configuration_kind": "apk_archive_entry",
                    "container_artifact_id": "fixture-apk",
                    "central_directory_ordinal": entry.ordinal,
                    "path": entry.path,
                    "compression_method": entry.method,
                    "crc32": entry.crc32,
                    "compressed_size_bytes": entry.compressed_size,
                    "uncompressed_size_bytes": entry.uncompressed_size,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                asset_payload = {
                    "apk_artifact_id": "fixture-apk",
                    "archive_entry_record_id": record_id("configuration", archive_payload),
                    "path": entry.path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
                asset_ids.add(record_id("asset", asset_payload))
            require(len(asset_ids) == value["expected_distinct_ids"], "archive_occurrence_identity")
        elif operation == "qname":
            exact_keys(value, {"namespace", "local", "expected"}, "fixture_shape")
            require(qname_value(value["namespace"], value["local"]) == value["expected"], "axml_qname")
        elif operation == "resource_id":
            exact_keys(value, {"package_id", "raw_type_id", "type_id_offset", "entry_id", "expected"}, "fixture_shape")
            effective = value["raw_type_id"] + value["type_id_offset"]
            require(1 <= effective <= 255, "arsc_effective_type")
            actual = f"0x{((value['package_id'] << 24) | (effective << 16) | value['entry_id']):08x}"
            require(actual == value["expected"], "arsc_resource_id")
        elif operation == "feature":
            exact_keys(value, {"name", "gl_es_version"}, "fixture_shape")
            require((value["name"] is None) != (value["gl_es_version"] is None), "feature_attribute_xor")
        elif operation == "component_merge":
            exact_keys(value, {"explicit_values"}, "fixture_shape")
            require(len(set(value["explicit_values"])) <= 1, "android_component_merge_conflict")
        elif operation == "payload_keys":
            exact_keys(value, {"variant", "keys"}, "fixture_shape")
            schema = contract["record_model"]["payload_schemas"][value["variant"]]["payload"]
            require(set(value["keys"]) == set(schema["properties"]), "payload_extra_key")
        elif operation == "integer_domain":
            exact_keys(value, {"value", "minimum", "maximum"}, "fixture_shape")
            candidate = value["value"]
            require(
                isinstance(candidate, int)
                and not isinstance(candidate, bool)
                and value["minimum"] <= candidate <= value["maximum"],
                "integer_domain",
            )
        elif operation == "identity_set":
            exact_keys(value, {"values"}, "fixture_shape")
            normalized = [unicodedata.normalize("NFC", item) for item in value["values"]]
            require(len(normalized) == len(set(normalized)), "post_nfc_identity_collision")
        elif operation == "archive_identity":
            exact_keys(value, {"original", "mutated"}, "fixture_shape")
            require(value["original"] == value["mutated"], "archive_occurrence_identity")
        elif operation == "inventory_abort":
            exact_keys(value, {"required_input_malformed", "emitted_rows"}, "fixture_shape")
            if value["required_input_malformed"]:
                require(value["emitted_rows"] == 0, "partial_success_forbidden")
        else:
            raise ValidationError("fixture_unknown_operation", str(operation))
        return "accept", "ok"
    except ValidationError as exc:
        return "reject", exc.code


def validate_fixtures(contract: Mapping[str, Any], fixture_root: Path) -> dict[str, Any]:
    fixture_contract = contract["hostile_fixtures"]
    actual_files = {p.relative_to(fixture_root).as_posix() for p in fixture_root.rglob("*") if p.is_file()}
    require(actual_files == set(fixture_contract["files"]), "fixture_file_set")
    for name, expected in fixture_contract["files"].items():
        exact_keys(expected, {"sha256", "size_bytes"}, "fixture_file_metadata")
        path = fixture_root / name
        digest, size = sha256_path(path)
        require((digest, size) == (expected["sha256"], expected["size_bytes"]), "fixture_file_hash", name)

    cases = load_canonical_json(fixture_root / fixture_contract["case_file"])
    require(isinstance(cases, list), "fixture_cases_shape")
    manifest_rows = []
    results = []
    for index, case in enumerate(cases):
        exact_keys(case, {"id", "operation", "input", "expected", "code"}, "fixture_case_shape")
        manifest_rows.append({"id": case["id"], "case_index": index, "expected": case["expected"], "code": case["code"]})
        disposition, code = _fixture_disposition(case, contract, fixture_root)
        require((disposition, code) == (case["expected"], case["code"]), "fixture_disposition", case["id"])
        results.append({"id": case["id"], "disposition": disposition, "code": code})
    require(manifest_rows == fixture_contract["cases"], "fixture_manifest_mismatch")

    for test in fixture_contract["file_tests"]:
        path = fixture_root / test["path"]
        try:
            value = parse_json_bytes(path.read_bytes())
            if test["code"] == "json_not_canonical":
                require(path.read_bytes() == canonical_json_bytes(value) + b"\n", "json_not_canonical")
            disposition, code = "accept", "ok"
        except ValidationError as exc:
            disposition, code = "reject", exc.code
        require((disposition, code) == (test["expected"], test["code"]), "fixture_disposition", test["id"])
        results.append({"id": test["id"], "disposition": disposition, "code": code})

    for test in fixture_contract["candidate_bundles"]:
        try:
            validate_candidate_bundle(contract, fixture_root / test["path"], DEFAULT_MANIFEST)
            disposition, code = "accept", "ok"
        except ValidationError as exc:
            disposition, code = "reject", exc.code
        require((disposition, code) == (test["expected"], test["code"]), "fixture_disposition", test["id"])
        results.append({"id": test["id"], "disposition": disposition, "code": code})

    digest = canonical_digest(results)
    return {
        "total": len(results),
        "accepted": sum(row["disposition"] == "accept" for row in results),
        "rejected": sum(row["disposition"] == "reject" for row in results),
        "results_sha256": digest,
        "results": results,
    }


def _manifest_file_path(source: Mapping[str, Any]) -> Path:
    path = Path(source["path"])
    return path if path.is_absolute() else ROOT / path


def _apk_category(path: str) -> str:
    if path == "AndroidManifest.xml":
        return "AndroidManifest.xml"
    if path == "resources.arsc":
        return "resources.arsc"
    if re.fullmatch(r"classes(?:[2-9][0-9]*)?\.dex", path):
        return "dex"
    if path.startswith("lib/arm64-v8a/") and path.endswith(".so"):
        return "arm64"
    if path.startswith("lib/armeabi-v7a/") and path.endswith(".so"):
        return "armeabi-v7a"
    if path.startswith("res/"):
        return "res"
    if path.startswith("assets/"):
        return "assets"
    if path.startswith("META-INF/"):
        return "META-INF"
    return "other"


def validate_official_anchors(
    contract: Mapping[str, Any],
    official_manifest: Path,
    xapk_path: Path,
) -> dict[str, Any]:
    manifest_digest, _manifest_size = sha256_path(official_manifest)
    require(manifest_digest == contract["authority"]["official_manifest_sha256"], "official_manifest_hash")
    manifest = parse_json_bytes(official_manifest.read_bytes())
    exact_keys(
        manifest,
        {"schema_version", "artifact_set_id", "frozen_at", "scope", "package", "expected_counts", "observed_counts_by_kind", "provenance", "artifacts"},
        "official_manifest_schema",
    )
    require(manifest["artifact_set_id"] == contract["authority"]["artifact_set_id"], "official_artifact_set")
    artifacts = manifest["artifacts"]
    require(len(artifacts) == 121, "official_artifact_count")
    require(len({row["artifact_id"] for row in artifacts}) == 121, "official_artifact_ids")

    xapk_digest, xapk_size = sha256_path(xapk_path)
    require(
        (xapk_digest, xapk_size)
        == (contract["authority"]["official_xapk_sha256"], contract["authority"]["official_xapk_size_bytes"]),
        "official_xapk_identity",
    )
    xapk_directory = parse_zip_directory_file(xapk_path)
    require(len(xapk_directory.entries) == 21, "official_xapk_entry_count")
    xapk_names = [entry.path for entry in xapk_directory.entries]
    anchors = contract["android"]["official_anchor_details"]
    require(xapk_names == anchors["xapk_physical_order"], "official_xapk_order")
    archive_occurrence_membership: list[dict[str, Any]] = []
    frozen_artifact_payloads = [row["artifact_id"] for row in artifacts]

    hash_matches = 0
    with zipfile.ZipFile(xapk_path, "r") as archive:
        infos = archive.infolist()
        require(len(infos) == len(xapk_directory.entries), "official_xapk_entry_count")
        require([unicodedata.normalize("NFC", info.filename) for info in infos] == xapk_names, "official_xapk_order")
        by_name: dict[str, list[zipfile.ZipInfo]] = defaultdict(list)
        for info in infos:
            by_name[unicodedata.normalize("NFC", info.filename)].append(info)
        for entry, info in zip(xapk_directory.entries, infos):
            with archive.open(info, "r") as stream:
                member_sha, member_size = sha256_stream(stream)
            require(member_size == entry.uncompressed_size, "official_xapk_member_size")
            archive_occurrence_membership.append({
                "configuration_kind": "xapk_archive_entry",
                "container_artifact_id": "official-xapk",
                "central_directory_ordinal": entry.ordinal,
                "path": entry.path,
                "compression_method": entry.method,
                "crc32": entry.crc32,
                "compressed_size_bytes": entry.compressed_size,
                "uncompressed_size_bytes": entry.uncompressed_size,
                "sha256": member_sha,
            })
        used: Counter[str] = Counter()
        for artifact in artifacts:
            artifact_keys = {"artifact_id", "kind", "sha256", "size_bytes", "source"}
            if artifact["kind"] == "native_library":
                artifact_keys.add("abi")
            exact_keys(artifact, artifact_keys, "official_artifact_row")
            source = artifact["source"]
            if source["type"] == "file":
                exact_keys(source, {"type", "path"}, "official_source_row")
                path = xapk_path if artifact["artifact_id"] == "official-xapk" else _manifest_file_path(source)
                digest, size = sha256_path(path)
            elif source["type"] == "zip_member":
                exact_keys(source, {"type", "container_path", "member_path"}, "official_source_row")
                member = unicodedata.normalize("NFC", source["member_path"])
                ordinal = used[member]
                used[member] += 1
                require(ordinal < len(by_name[member]), "official_zip_member_missing", member)
                with archive.open(by_name[member][ordinal], "r") as stream:
                    digest, size = sha256_stream(stream)
            else:
                raise ValidationError("official_source_type", str(source["type"]))
            require((digest, size) == (artifact["sha256"], artifact["size_bytes"]), "official_artifact_hash", artifact["artifact_id"])
            hash_matches += 1
    require(hash_matches == 121, "official_artifact_hash_count")

    apk_artifacts = [row for row in artifacts if row["kind"] == "apk_member"]
    require(len(apk_artifacts) == 19, "official_apk_count")
    apk_paths: dict[str, Path] = {}
    apk_entry_counts: dict[str, int] = {}
    categories: Counter[str] = Counter()
    manifest_node_count = 0
    feature_rows: list[dict[str, Any]] = []
    feature_payload_membership: list[dict[str, Any]] = []
    component_keys: set[tuple[str, str]] = set()
    component_counts: Counter[str] = Counter()
    resource_count = 0
    resource_configuration_count = 0
    package_summaries: list[dict[str, int]] = []
    resource_payload_membership: list[dict[str, Any]] = []
    resource_configuration_membership: list[dict[str, Any]] = []
    manifest_payload_membership: list[dict[str, Any]] = []
    asset_payload_membership: list[dict[str, Any]] = []
    arm32_payload_membership: list[dict[str, Any]] = []
    certificate_payload_membership: list[dict[str, Any]] = []
    certificate_sizes: dict[str, int] = {}
    component_declarations: list[dict[str, Any]] = []
    signing_v1 = signing_v2 = signing_v3 = 0
    signing_certificate_count = 0
    base_min_sdk: int | None = None
    base_target_sdk: int | None = None
    base_package: str | None = None
    with tempfile.TemporaryDirectory(prefix="g002-neutral-apks-", dir="/tmp") as temp:
        temp_root = Path(temp)
        with zipfile.ZipFile(xapk_path, "r") as outer:
            info_by_name = {info.filename: info for info in outer.infolist()}
            for artifact in apk_artifacts:
                member = artifact["source"]["member_path"]
                destination = temp_root / member
                with outer.open(info_by_name[member], "r") as source_stream, destination.open("wb") as output:
                    while True:
                        chunk = source_stream.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                apk_paths[artifact["artifact_id"]] = destination

        for artifact in apk_artifacts:
            apk_id = artifact["artifact_id"]
            apk_path = apk_paths[apk_id]
            directory = parse_zip_directory_file(apk_path)
            apk_entry_counts[Path(apk_id.split(":", 1)[1]).name] = len(directory.entries)
            for entry in directory.entries:
                categories[_apk_category(entry.path)] += 1
            v1_entries = [
                entry
                for entry in directory.entries
                if re.fullmatch(r"META-INF/[^/]+\.(?:RSA|DSA|EC)", entry.path, flags=re.IGNORECASE)
            ]
            signing_v1 += len(v1_entries)
            pair_ids, cert_counts, scheme_certificates = parse_apk_signing_block(apk_path, directory)
            pair_order = [f"0x{pair_id:08x}" for pair_id in pair_ids]
            expected_pair_order = (
                anchors["base_signing_pair_order"]
                if apk_id == "xapk-apk:com.hikvision.thermalGoogle.apk"
                else anchors["split_signing_pair_order"]
            )
            require(pair_order == expected_pair_order, "official_signing_pair_order", apk_id)
            signing_v2 += pair_ids.count(0x7109871A)
            signing_v3 += pair_ids.count(0xF05368C0)
            signing_certificate_count += len(v1_entries) + cert_counts["v2"] + cert_counts["v3"]
            with zipfile.ZipFile(apk_path, "r") as apk:
                apk_infos = apk.infolist()
                require(len(apk_infos) == len(directory.entries), "official_apk_entry_count")
                for entry, info in zip(directory.entries, apk_infos):
                    require(unicodedata.normalize("NFC", info.filename) == entry.path, "official_apk_entry_order")
                    with apk.open(info, "r") as stream:
                        member_sha, member_size = sha256_stream(stream)
                    require(member_size == entry.uncompressed_size, "official_apk_member_size")
                    archive_occurrence_membership.append({
                        "configuration_kind": "apk_archive_entry",
                        "container_artifact_id": apk_id,
                        "central_directory_ordinal": entry.ordinal,
                        "path": entry.path,
                        "compression_method": entry.method,
                        "crc32": entry.crc32,
                        "compressed_size_bytes": entry.compressed_size,
                        "uncompressed_size_bytes": entry.uncompressed_size,
                        "sha256": member_sha,
                    })
                    archive_payload = archive_occurrence_membership[-1]
                    archive_record_id = record_id("configuration", archive_payload)
                    if entry.path.startswith("assets/"):
                        asset_payload_membership.append({
                            "apk_artifact_id": apk_id,
                            "archive_entry_record_id": archive_record_id,
                            "path": entry.path,
                            "sha256": member_sha,
                            "size_bytes": member_size,
                        })
                    if entry.path.startswith("lib/armeabi-v7a/") and entry.path.endswith(".so"):
                        arm32_payload_membership.append({
                            "configuration_kind": "arm32_native_library",
                            "apk_artifact_id": apk_id,
                            "archive_entry_record_id": archive_record_id,
                            "path": entry.path,
                            "sha256": member_sha,
                            "size_bytes": member_size,
                            "abi": "armeabi-v7a",
                            "soname": entry.path.rsplit("/", 1)[-1],
                        })
                encoded_ordinal = 0
                for scheme, rows in (("v2", scheme_certificates["v2"]), ("v3", scheme_certificates["v3"])):
                    for signer_index, certificate_index, cert in rows:
                        cert_sha256 = hashlib.sha256(cert).hexdigest()
                        certificate_sizes[cert_sha256] = len(cert)
                        certificate_payload_membership.append({
                            "apk_artifact_id": apk_id,
                            "scheme": scheme,
                            "scheme_occurrence_ordinal": 0,
                            "signer_index": signer_index,
                            "certificate_index": certificate_index,
                            "encoded_certificate_ordinal": encoded_ordinal,
                            "der_sha256": cert_sha256,
                        })
                        encoded_ordinal += 1
                for scheme_ordinal, entry in enumerate(v1_entries):
                    certs = parse_pkcs7_certificates(apk.read(entry.path))
                    for certificate_index, cert in enumerate(certs):
                        cert_sha256 = hashlib.sha256(cert).hexdigest()
                        certificate_sizes[cert_sha256] = len(cert)
                        certificate_payload_membership.append({
                            "apk_artifact_id": apk_id,
                            "scheme": "v1",
                            "scheme_occurrence_ordinal": scheme_ordinal,
                            "signer_index": 0,
                            "certificate_index": certificate_index,
                            "encoded_certificate_ordinal": encoded_ordinal,
                            "der_sha256": cert_sha256,
                        })
                        encoded_ordinal += 1
                axml = parse_axml(apk.read("AndroidManifest.xml"))
                manifest_node_count += len(axml["nodes"])
                local_manifest_payloads = []
                manifest_payload_by_path: dict[str, Mapping[str, Any]] = {}
                for node in axml["nodes"]:
                    parent_path = node["path"].rsplit("/", 1)[0]
                    parent_payload = manifest_payload_by_path.get(parent_path)
                    require(
                        (parent_path == "axmlpath:") == (parent_payload is None),
                        "official_manifest_parent",
                        node["path"],
                    )
                    payload = {
                        "apk_artifact_id": apk_id,
                        "event_ordinal": node["event_ordinal"],
                        "qname": node["qname"],
                        "xpath": node["path"],
                        "attributes": node["attributes"],
                        "parent_manifest_node_record_id": (
                            None
                            if parent_payload is None
                            else record_id("manifest_node", parent_payload)
                        ),
                    }
                    local_manifest_payloads.append(payload)
                    manifest_payload_by_path[node["path"]] = payload
                manifest_payload_membership.extend(local_manifest_payloads)
                feature_rows.extend(axml["features"])
                feature_index = 0
                for node, manifest_payload in zip(axml["nodes"], local_manifest_payloads):
                    if node["name"] != "uses-feature":
                        continue
                    feature = axml["features"][feature_index]
                    feature_index += 1
                    feature_payload_membership.append({
                        "apk_artifact_id": apk_id,
                        "declaration_manifest_node_record_id": record_id("manifest_node", manifest_payload),
                        **feature,
                    })
                package = axml["package"]
                require(isinstance(package, str) and bool(package), "official_manifest_package")
                if axml["split"] is None:
                    require(base_package is None, "official_base_manifest")
                    base_package = package
                    base_min_sdk = axml["min_sdk"]
                    base_target_sdk = axml["target_sdk"]
                for kind, name, _path in axml["components"]:
                    if kind == "application":
                        key = ("application", package)
                        if key not in component_keys:
                            component_keys.add(key)
                            component_counts["application"] += 1
                    else:
                        require(isinstance(name, str) and bool(name), "official_component_name")
                        family = "activity" if kind in {"activity", "activity-alias"} else kind
                        key = (family, _expand_component_name(package, name))
                        if key not in component_keys:
                            component_keys.add(key)
                            component_counts[kind.replace("-", "_")] += 1
                component_declarations.append({"apk_artifact_id": apk_id, "axml": axml})
                logical, configurations, summaries, resource_rows, configuration_rows = count_arsc(apk.read("resources.arsc"), apk_id)
                resource_count += logical
                resource_configuration_count += configurations
                package_summaries.extend(summaries)
                resource_payload_membership.extend(resource_rows)
                resource_configuration_membership.extend(configuration_rows)

    require(apk_entry_counts == anchors["apk_entry_counts"], "official_apk_entry_count")
    require(categories == Counter(anchors["archive_categories"]), "official_apk_categories")
    require(manifest_node_count == 188, "official_manifest_node_count")
    require(resource_count == 33431, "official_resource_count")
    require(resource_configuration_count == 36498, "official_resource_configuration_count")
    require(len(feature_rows) == 3, "official_feature_count")
    require(feature_rows == anchors["features"], "official_feature_membership")
    require(len(component_keys) == 32, "official_component_count")
    component_with_zero = {key: component_counts.get(key, 0) for key in anchors["component_counts"]}
    require(component_with_zero == anchors["component_counts"], "official_component_categories")
    require((base_package, base_min_sdk, base_target_sdk) == ("com.hikvision.thermalGoogle", 24, 35), "official_sdk_anchor")
    require(all(row["package_id"] == 127 and row["type_id_offset"] == 0 for row in package_summaries), "official_resource_package_anchor")
    require((signing_v1, signing_v2, signing_v3) == (18, 19, 19), "official_signing_counts")
    require(signing_certificate_count == 56, "official_certificate_count")
    require(len(asset_payload_membership) == 762, "official_asset_count")
    require(len(arm32_payload_membership) == 90, "official_arm32_count")
    require(len(certificate_payload_membership) == 56, "official_certificate_payload_count")
    component_payload_membership = derive_android_component_payloads(
        component_declarations,
        base_target_sdk,
        contract,
    )
    require(len(component_payload_membership) == 32, "official_component_payload_count")
    android_membership = {
        "archive_occurrence_payloads_sha256": canonical_digest(archive_occurrence_membership),
        "manifest_node_payloads_sha256": canonical_digest(sorted(manifest_payload_membership, key=canonical_json_bytes)),
        "resource_payloads_sha256": canonical_digest(sorted(resource_payload_membership, key=canonical_json_bytes)),
        "resource_configuration_payloads_sha256": canonical_digest(sorted(resource_configuration_membership, key=canonical_json_bytes)),
        "feature_payloads_sha256": canonical_digest(sorted(feature_payload_membership, key=canonical_json_bytes)),
    }
    require(android_membership == contract["android"]["normalized_membership_oracles"], "official_android_membership")

    dex_artifacts = [row for row in artifacts if row["kind"] == "dex"]
    require(len(dex_artifacts) == 4, "official_dex_count")
    dex_totals = Counter()
    dex_per_artifact: dict[str, dict[str, int]] = {}
    dex_membership: list[dict[str, Any]] = []
    dex_native_declarations: list[dict[str, Any]] = []
    class_payload_membership: list[dict[str, Any]] = []
    method_family_payload_membership: list[dict[str, Any]] = []
    reflection_payload_membership: list[dict[str, Any]] = []
    loader_payload_membership: list[dict[str, Any]] = []
    for artifact in dex_artifacts:
        parsed_dex = parse_dex_callsites(
            _manifest_file_path(artifact["source"]).read_bytes(),
            artifact["artifact_id"],
            contract["callsites"],
        )
        counts = parsed_dex["counts"]
        dex_native_declarations.extend(parsed_dex["native_declarations"])
        class_payload_membership.extend(parsed_dex["class_payloads"])
        method_family_payload_membership.extend(parsed_dex["method_family_payloads"])
        reflection_payload_membership.extend(parsed_dex["admitted"]["reflection_target"])
        loader_payload_membership.extend(parsed_dex["admitted"]["dynamic_loader"])
        dex_per_artifact[artifact["artifact_id"]] = counts
        dex_totals.update(counts)
        dex_membership.append({key: parsed_dex[key] for key in (
            "physical_invoke_count",
            "physical_invoke_membership_sha256",
            "reflection_target_count",
            "reflection_target_payloads_sha256",
            "dynamic_loader_count",
            "dynamic_loader_payloads_sha256",
        )} | {"artifact_id": artifact["artifact_id"]})
    require(dict(dex_totals) == EXPECTED_DEX_COUNTS, "official_dex_anchors")
    require(
        [{"artifact_id": row["artifact_id"], **dex_per_artifact[row["artifact_id"]]} for row in contract["dex"]["per_artifact_anchors"]]
        == contract["dex"]["per_artifact_anchors"],
        "official_dex_per_artifact",
    )
    require(dex_membership == contract["dex"]["byte_membership_oracles"], "official_dex_membership")

    native_artifacts = [row for row in artifacts if row["kind"] == "native_library"]
    require(len(native_artifacts) == 88, "official_native_count")
    basename_to_ids: dict[str, list[str]] = defaultdict(list)
    for artifact in native_artifacts:
        basename_to_ids[_manifest_file_path(artifact["source"]).name].append(artifact["artifact_id"])
    symbol_decisions: list[list[Any]] = []
    symbol_keys: list[list[Any]] = []
    export_keys: list[list[Any]] = []
    undefined_keys: list[list[Any]] = []
    dynamic_decisions: list[list[Any]] = []
    needed_keys: list[list[Any]] = []
    elf_totals = Counter()
    large_actual: list[dict[str, Any]] = []
    symbol_payload_records: list[tuple[str, str, Mapping[str, Any]]] = []
    export_payload_records: list[tuple[str, str, Mapping[str, Any]]] = []
    import_payload_records: list[tuple[str, str, Mapping[str, Any]]] = []
    summary_payload_records: list[tuple[str, str, Mapping[str, Any]]] = []
    java_export_endpoints: list[dict[str, Any]] = []
    raw_register_natives_rows: list[dict[str, Any]] = []
    aarch64_analyzed_functions = 0
    aarch64_unsupported_instructions = 0
    per_library_rows: list[dict[str, Any]] = []
    for artifact in native_artifacts:
        aid = artifact["artifact_id"]
        data = _manifest_file_path(artifact["source"]).read_bytes()
        parsed = parse_elf_symbols(data)
        dynamic = parse_elf_dynamic(data)
        raw_registration = scan_aarch64_register_natives_raw(data, aid)
        aarch64_analyzed_functions += raw_registration["analyzed_function_count"]
        aarch64_unsupported_instructions += raw_registration["unsupported_instruction_count"]
        raw_register_natives_rows.extend(raw_registration["raw_candidate_rows"])
        symbols = parsed["symbols"]
        elf_totals["physical_dynsym_entries"] += len(symbols)
        elf_totals["reserved_index_zero"] += 1
        elf_totals["included_nonzero_native_symbol"] += len(symbols) - 1
        library_exports = library_undefined = library_java = 0
        for symbol in symbols:
            decision = (
                "excluded_reserved_index_zero"
                if symbol["index"] == 0
                else "included_nonzero_dynamic_symbol"
            )
            symbol_decisions.append([aid, symbol["index"], decision])
            if symbol["index"] == 0:
                continue
            symbol_keys.append([aid, symbol["index"]])
            symbol_payload = {
                "library_artifact_id": aid,
                "dynamic_symbol_index": symbol["index"],
                "name": symbol["name"],
                "version": symbol["version"],
                "value": symbol["value"],
                "size_bytes": symbol["size_bytes"],
                "symbol_type": symbol["symbol_type"],
                "binding": symbol["binding"],
                "visibility": symbol["visibility"],
                "section_index": symbol["section_index"],
            }
            symbol_record_id = record_id("native_symbol", symbol_payload)
            symbol_payload_records.append((symbol_record_id, "native_symbol", symbol_payload))
            if symbol["name"] is None and symbol["symbol_type"] == "STT_SECTION":
                elf_totals["unnamed_nonzero_stt_section"] += 1
            if symbol["export"]:
                elf_totals["defined_global_weak_native_export"] += 1
                library_exports += 1
                export_keys.append([aid, symbol["index"]])
                export_payload = {
                    "library_artifact_id": aid,
                    "dynamic_symbol_index": symbol["index"],
                    "native_symbol_record_id": symbol_record_id,
                    "name": symbol["name"],
                    "version": symbol["version"],
                    "binding": symbol["binding"],
                }
                export_record_id = record_id("native_export", export_payload)
                export_payload_records.append((export_record_id, "native_export", export_payload))
                if symbol["name"].startswith("Java_"):
                    elf_totals["java_export"] += 1
                    library_java += 1
                    java_export_endpoints.append({
                        "library_artifact_id": aid,
                        "dynamic_symbol_index": symbol["index"],
                        "native_export_record_id": export_record_id,
                        "native_symbol_record_id": symbol_record_id,
                        "name": symbol["name"],
                        "version": symbol["version"],
                        "virtual_address": symbol["value"],
                    })
            if symbol["undefined_import"]:
                elf_totals["undefined_named_import"] += 1
                library_undefined += 1
                undefined_keys.append([aid, symbol["index"]])
                import_payload = {
                    "import_kind": "undefined_dynsym",
                    "library_artifact_id": aid,
                    "dynamic_symbol_index": symbol["index"],
                    "native_symbol_record_id": symbol_record_id,
                    "name": symbol["name"],
                    "version": symbol["version"],
                }
                import_payload_records.append((record_id("native_import", import_payload), "native_import", import_payload))
            if symbol["export"] and symbol["size_bytes"] >= 100000:
                large_actual.append(
                    {
                        "library_artifact_id": aid,
                        "dynamic_symbol_index": symbol["index"],
                        "name": symbol["name"],
                        "value": symbol["value"],
                        "size_bytes": symbol["size_bytes"],
                        "symbol_type": symbol["symbol_type"],
                        "binding": symbol["binding"],
                        "visibility": symbol["visibility"],
                        "section_index": symbol["section_index"],
                        "emit_native_export": symbol["export"],
                    }
                )
        for index, tag, decision in dynamic["decisions"]:
            oracle_decision = {
                "other_dynamic_tag": "excluded_other_tag_before_null",
                "included_dt_needed": "included_dt_needed",
                "terminator": "excluded_first_dt_null_terminator",
                "after_first_dt_null": "excluded_after_first_dt_null",
            }[decision]
            dynamic_decisions.append([aid, index, tag, oracle_decision])
        for index, soname in dynamic["needed"]:
            candidates = basename_to_ids[soname.rsplit("/", 1)[-1]]
            target = candidates[0] if len(candidates) == 1 else None
            needed_keys.append([aid, index, soname, target])
            elf_totals["dt_needed"] += 1
            import_payload = {
                "import_kind": "dt_needed",
                "library_artifact_id": aid,
                "dynamic_table_index": index,
                "soname": soname,
                "bundled_target_artifact_id": target,
            }
            import_payload_records.append((record_id("native_import", import_payload), "native_import", import_payload))
        summary_payload = {
            "configuration_kind": "native_library_summary",
            "library_artifact_id": aid,
            "dynamic_symbol_count": len(symbols) - 1,
            "defined_global_weak_export_count": library_exports,
            "undefined_named_import_count": library_undefined,
            "dt_needed_count": len(dynamic["needed"]),
            "java_export_count": library_java,
        }
        summary_id = record_id("configuration", summary_payload)
        summary_payload_records.append((summary_id, "configuration", summary_payload))
        per_library_rows.append({
            "library_artifact_id": aid,
            "physical_dynsym_count": len(symbols),
            **{key: summary_payload[key] for key in ("dynamic_symbol_count", "defined_global_weak_export_count", "undefined_named_import_count", "dt_needed_count", "java_export_count")},
            "symbol_payloads_sha256": canonical_digest([row[2] for row in sorted(symbol_payload_records, key=lambda row: row[0]) if row[2].get("library_artifact_id") == aid]),
            "export_payloads_sha256": canonical_digest([row[2] for row in sorted(export_payload_records, key=lambda row: row[0]) if row[2].get("library_artifact_id") == aid]),
            "import_payloads_sha256": canonical_digest([row[2] for row in sorted(import_payload_records, key=lambda row: row[0]) if row[2].get("library_artifact_id") == aid]),
            "summary_record_id": summary_id,
            "summary_payload_sha256": canonical_digest(summary_payload),
        })
    elf_totals["native_import"] = elf_totals["undefined_named_import"] + elf_totals["dt_needed"]
    require(dict(elf_totals) == EXPECTED_ELF_COUNTS, "official_elf_counts", repr(dict(elf_totals)))
    large_actual.sort(key=lambda row: (row["library_artifact_id"], row["dynamic_symbol_index"]))
    require(large_actual == contract["elf"]["large_size_regression_rows"], "official_elf_large_rows")
    require(per_library_rows == contract["elf"]["per_library_anchors"], "official_elf_per_library")
    direct_oracles = {
        "physical_symbol_decisions_by_manifest_then_index_sha256": canonical_digest(symbol_decisions),
        "normalized_symbol_keys_sorted_sha256": canonical_digest(sorted(symbol_keys)),
        "export_symbol_keys_sorted_sha256": canonical_digest(sorted(export_keys)),
        "undefined_symbol_keys_sorted_sha256": canonical_digest(sorted(undefined_keys)),
        "dynamic_entry_decisions_by_manifest_then_index_sha256": canonical_digest(dynamic_decisions),
        "needed_keys_sorted_sha256": canonical_digest(sorted(needed_keys, key=lambda row: (row[0], row[1]))),
    }
    for name, actual in direct_oracles.items():
        require(actual == contract["membership_oracles"]["digests"][name], "official_elf_membership_oracle", name)
    payload_oracles = {
        "native_symbol_payloads_sorted_by_record_id_sha256": canonical_digest([row[2] for row in sorted(symbol_payload_records)]),
        "native_export_payloads_sorted_by_record_id_sha256": canonical_digest([row[2] for row in sorted(export_payload_records)]),
        "native_import_payloads_sorted_by_record_id_sha256": canonical_digest([row[2] for row in sorted(import_payload_records)]),
        "native_summary_payloads_sorted_by_record_id_sha256": canonical_digest([row[2] for row in sorted(summary_payload_records)]),
    }
    all_records = sorted(symbol_payload_records + export_payload_records + import_payload_records + summary_payload_records)
    payload_oracles["all_elf_record_type_id_payload_sorted_by_record_id_sha256"] = canonical_digest([[row[1], row[0], row[2]] for row in all_records])
    payload_oracles["all_elf_record_ids_sorted_sha256"] = canonical_digest([row[0] for row in all_records])
    for name, actual in payload_oracles.items():
        require(actual == contract["membership_oracles"]["digests"][name], "official_elf_payload_oracle", name)
    direct_oracles.update(payload_oracles)
    raw_register_natives_rows.sort(key=canonical_json_bytes)
    registration_evaluation = evaluate_jni_registration_candidates(raw_register_natives_rows, contract)
    jni_membership = derive_static_jni_membership(
        dex_native_declarations,
        java_export_endpoints,
        contract,
        registration_evaluation,
    )
    jni_edge_rows = jni_membership.pop("normalized_edges")
    jni_membership.update({
        "aarch64_analyzed_function_count": aarch64_analyzed_functions,
        "aarch64_unsupported_instruction_count": aarch64_unsupported_instructions,
        "raw_register_natives_candidate_count": len(raw_register_natives_rows),
        "raw_register_natives_candidates_sha256": canonical_digest(raw_register_natives_rows),
        "registration_candidate_decisions_sha256": registration_evaluation["registration_candidate_decisions_sha256"],
        "registration_proven_edges_sha256": registration_evaluation["registration_proven_edges_sha256"],
        "registration_exclusions_sha256": registration_evaluation["registration_exclusions_sha256"],
    })
    require(
        jni_membership == contract["jni"]["byte_membership_oracles"],
        "official_jni_membership",
        repr(jni_membership),
    )

    family_payloads: dict[str, list[Any]] = {
        "frozen_artifact": frozen_artifact_payloads,
        "configuration:xapk_archive_entry": [row for row in archive_occurrence_membership if row["configuration_kind"] == "xapk_archive_entry"],
        "configuration:apk_archive_entry": [row for row in archive_occurrence_membership if row["configuration_kind"] == "apk_archive_entry"],
        "configuration:arm32_native_library": arm32_payload_membership,
        "configuration:resource_configuration": resource_configuration_membership,
        "configuration:native_library_summary": [row[2] for row in summary_payload_records],
        "manifest_node": manifest_payload_membership,
        "resource": resource_payload_membership,
        "asset": asset_payload_membership,
        "certificate": certificate_payload_membership,
        "android_component": component_payload_membership,
        "class": class_payload_membership,
        "method_family": method_family_payload_membership,
        "reflection_target": reflection_payload_membership,
        "dynamic_loader": loader_payload_membership,
        "native_symbol": [row[2] for row in symbol_payload_records],
        "native_export": [row[2] for row in export_payload_records],
        "native_import:undefined_dynsym": [row[2] for row in import_payload_records if row[2]["import_kind"] == "undefined_dynsym"],
        "native_import:dt_needed": [row[2] for row in import_payload_records if row[2]["import_kind"] == "dt_needed"],
        "jni_edge": [row[1] for row in jni_edge_rows],
        "feature": feature_payload_membership,
    }
    require(set(family_payloads) == set(contract["provenance"]["whole_candidate"]["required_family_variants"]), "official_candidate_family_set")
    candidate_family_memberships = []
    for family, payloads in sorted(family_payloads.items()):
        record_type = contract["record_model"]["payload_schemas"][family]["record_type"]
        rows = sorted(((record_id(record_type, payload), payload) for payload in payloads), key=lambda row: row[0])
        require(len(rows) == len({row[0] for row in rows}), "official_candidate_family_duplicate", family)
        candidate_family_memberships.append({
            "family": family,
            "count": len(rows),
            "payloads_sha256": canonical_digest([row[1] for row in rows]),
            "record_ids_sha256": canonical_digest([row[0] for row in rows]),
        })
    require(
        {row["family"]: row["count"] for row in candidate_family_memberships} == _expected_candidate_family_counts(contract),
        "official_candidate_family_counts",
    )
    require(
        candidate_family_memberships == contract["provenance"]["whole_candidate"]["family_memberships"],
        "official_candidate_family_memberships",
    )

    derivation_groups = {
        "raw/xapk.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"frozen_artifact", "configuration:xapk_archive_entry"}],
            "physical_order": xapk_names,
        },
        "raw/apk-entries.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"configuration:apk_archive_entry", "configuration:arm32_native_library", "asset"}],
            "apk_entry_counts": apk_entry_counts,
            "archive_categories": dict(sorted(categories.items())),
        },
        "raw/manifests.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"manifest_node", "feature", "android_component"}],
            "android_membership": android_membership,
            "component_counts": component_with_zero,
        },
        "raw/resources.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"resource", "configuration:resource_configuration"}],
            "resource_payloads_sha256": android_membership["resource_payloads_sha256"],
            "resource_configuration_payloads_sha256": android_membership["resource_configuration_payloads_sha256"],
        },
        "raw/signing.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] == "certificate"],
            "scheme_counts": {"v1": signing_v1, "v2": signing_v2, "v3": signing_v3},
            "certificate_payloads_sha256": canonical_digest(sorted(certificate_payload_membership, key=canonical_json_bytes)),
        },
        "raw/dex.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"class", "method_family", "reflection_target", "dynamic_loader"}],
            "totals": dict(dex_totals),
            "byte_membership": dex_membership,
            "native_declarations_sha256": canonical_digest(sorted(dex_native_declarations, key=canonical_json_bytes)),
        },
        "raw/elf.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] in {"native_symbol", "native_export", "native_import:undefined_dynsym", "native_import:dt_needed", "configuration:native_library_summary"}],
            "totals": dict(elf_totals),
            "membership": direct_oracles,
        },
        "raw/jni.json": {
            "entries": [row for row in candidate_family_memberships if row["family"] == "jni_edge"],
            "membership": jni_membership,
            "registration_decisions_sha256": registration_evaluation["registration_candidate_decisions_sha256"],
            "registration_proven_edges_sha256": registration_evaluation["registration_proven_edges_sha256"],
            "registration_exclusions_sha256": registration_evaluation["registration_exclusions_sha256"],
        },
    }
    raw_obligations = build_official_raw_obligation_oracle(
        contract, family_payloads, artifacts, derivation_groups, certificate_sizes
    )
    expected_raw_obligations = contract["provenance"]["whole_candidate"].get("raw_obligation_oracle")
    require(raw_obligations == expected_raw_obligations, "official_raw_obligation_oracle")

    return {
        "official_artifacts_rehashed": hash_matches,
        "xapk_entries": len(xapk_directory.entries),
        "apk_entries": sum(apk_entry_counts.values()),
        "apk_categories": dict(sorted(categories.items())),
        "manifest_nodes": manifest_node_count,
        "resources": resource_count,
        "resource_configurations": resource_configuration_count,
        "features": len(feature_rows),
        "android_components": len(component_keys),
        "certificates": signing_certificate_count,
        "android_membership": android_membership,
        "dex": dict(dex_totals),
        "dex_membership": dex_membership,
        "jni_membership": jni_membership,
        "jni_registration_evaluation": {
            key: registration_evaluation[key]
            for key in (
                "candidate_count", "proven_candidate_count", "exclusion_count",
                "proven_edge_count", "decisions", "exclusions",
            )
        },
        "elf": dict(elf_totals),
        "elf_membership_oracles": direct_oracles,
        "large_size_regression_rows": len(large_actual),
        "candidate_family_memberships": candidate_family_memberships,
        "raw_obligations": raw_obligations,
    }


def validate_all(
    contract_path: Path,
    fixture_root: Path,
    official_manifest: Path,
    xapk_path: Path,
    candidate_bundle: Path | None = None,
) -> dict[str, Any]:
    contract_bytes = contract_path.read_bytes()
    contract = load_canonical_json(contract_path)
    contract_summary = validate_contract(contract, contract_bytes)
    fixture_summary = validate_fixtures(contract, fixture_root)
    component_summary = None
    if candidate_bundle is not None:
        component_summary = validate_candidate_bundle_components(contract, candidate_bundle, official_manifest)
        require(component_summary["candidate_scope"] == "whole_inventory", "candidate_incomplete_record_counts")
    official_summary = validate_official_anchors(contract, official_manifest, xapk_path)
    candidate_summary = (
        validate_candidate_bundle(contract, candidate_bundle, official_manifest, official_summary, component_summary)
        if candidate_bundle is not None
        else None
    )
    summary = {
        "schema": "g002-neutral-validator-summary/v1",
        "status": "ok",
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "fixture_set_sha256": canonical_digest(contract["hostile_fixtures"]["files"]),
        "contract": contract_summary,
        "fixtures": {
            "total": fixture_summary["total"],
            "accepted": fixture_summary["accepted"],
            "rejected": fixture_summary["rejected"],
            "results_sha256": fixture_summary["results_sha256"],
        },
        "official": official_summary,
    }
    if candidate_summary is not None:
        summary["candidate"] = candidate_summary
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--official-manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--xapk", type=Path, required=True)
    parser.add_argument(
        "--candidate-bundle",
        type=Path,
        help="directory containing canonical bundle.json, inventory, raw attachments, source index, run, command, and review evidence",
    )
    parser.add_argument("--json", action="store_true", help="emit one canonical machine-readable JSON object")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = validate_all(
            args.contract.resolve(),
            args.fixtures.resolve(),
            args.official_manifest.resolve(),
            args.xapk.resolve(),
            args.candidate_bundle.resolve() if args.candidate_bundle else None,
        )
        output = canonical_json_bytes(summary) + b"\n"
        sys.stdout.buffer.write(output)
        return 0
    except ValidationError as exc:
        failure = {
            "schema": "g002-neutral-validator-summary/v1",
            "status": "error",
            "code": exc.code,
            "detail": exc.detail,
        }
        if args.json:
            sys.stdout.buffer.write(canonical_json_bytes(failure) + b"\n")
        else:
            print(f"{exc.code}: {exc.detail}", file=sys.stderr)
        return 1
    except (OSError, EOFError, UnicodeError, ValueError, KeyError, IndexError, TypeError, struct.error, zlib.error) as exc:
        failure = {
            "schema": "g002-neutral-validator-summary/v1",
            "status": "error",
            "code": "malformed_input",
            "detail": type(exc).__name__,
        }
        if args.json:
            sys.stdout.buffer.write(canonical_json_bytes(failure) + b"\n")
        else:
            print(f"malformed_input: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
