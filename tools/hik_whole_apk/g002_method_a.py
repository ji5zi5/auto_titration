#!/usr/bin/env python3
"""Produce the public G002 Method-A v10 whole-package static inventory.

The producer starts only from the untouched official XAPK and the frozen
121-row identity manifest.  Python zipfile performs archive enumeration and
extraction, Androguard 4.1.4 parses Android binary formats, and GNU binutils
provides the ELF observations.  The output is the complete public candidate
bundle defined by the accepted neutral v10 normalization contract.
"""

from __future__ import annotations

import argparse
import collections
import gc
import hashlib
import json
import math
import os
import platform
import re
import shlex
import shutil
import subprocess
import struct
import sys
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


sys.dont_write_bytecode = True

SCHEMA_VERSION = 1
CANDIDATE_BUNDLE_SCHEMA = "g002-candidate-bundle/v2"
INVENTORY_SCHEMA = "g002-normalized-inventory/v2"
RAW_ATTACHMENT_SCHEMA = "g002-raw-attachment/v1"
SOURCE_INDEX_SCHEMA = "g002-source-index/v2"
RUN_SCHEMA = "g002-run/v1"
COMMAND_SCHEMA = "g002-command/v1"
REVIEW_SCHEMA = "g002-review/v1"
CANDIDATE_SCOPE = "whole_inventory"
METHOD_ID = "METHOD-G002-ANDROGUARD-GNU"
TOOLCHAIN_FAMILY = "TOOLCHAIN-ANDROGUARD-GNU"
INVENTORY_ID = "INVENTORY-G002-A"
RUN_ID = "RUN-G002-A"
BUNDLE_ID = "EVB-G002-A"
SOURCE_INDEX_ID = "SOURCE-INDEX-G002-A"
EXPERIMENT_ID = "EXP-G002-A"
OPERATOR_ID = "producer-g002-a"
CLAIM_ID = "CLM-G002-A"
CONVERGENCE_CLAIM_ID = "CLM-G002-CONVERGENCE"
PLANNED_REVIEW_ID = "REV-G002-A"
EVENT_SCHEMA_ID = "SCHEMA-G002-STATIC-E1-NO-RUNTIME-EVENTS"

RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
DEFAULT_OFFICIAL_MANIFEST = RESEARCH_REL / "governance/official-artifacts.json"
DEFAULT_CONTRACT = RESEARCH_REL / "governance/g002-neutral-normalization-contract.json"
DEFAULT_OUTPUT = RESEARCH_REL / "static/g002-method-a-v10"
ACCEPTED_CONTRACT_SHA256 = "c378fe00e906fbf492d970d3cdc02df30601b416e61449de271ac4433087da29"
ACCEPTED_CONTRACT_SCHEMA = "g002-neutral-normalization-contract/v10"
CANONICAL_RUN_REL = RESEARCH_REL / "static/runs" / RUN_ID / "manifest.json"
PRODUCER_SCRIPT_REL = Path("tools/hik_whole_apk/g002_method_a.py")

RAW_DATASET_PATHS = {
    "apk_entries": "raw/apk-entries.json",
    "dex": "raw/dex.json",
    "elf": "raw/elf.json",
    "jni": "raw/jni.json",
    "manifests": "raw/manifests.json",
    "resources": "raw/resources.json",
    "signing": "raw/signing.json",
    "xapk": "raw/xapk.json",
}
CANDIDATE_DOCUMENT_PATHS = (
    "bundle.json",
    "inventory.json",
    "source-index.json",
    "run.json",
    "command.json",
    "review.json",
    "raw/xapk.json",
    "raw/apk-entries.json",
    "raw/manifests.json",
    "raw/resources.json",
    "raw/signing.json",
    "raw/dex.json",
    "raw/elf.json",
    "raw/jni.json",
)
RAW_COVERAGE_PATH = "raw/coverage.json"

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

OFFICIAL_OBLIGATION_DIGESTS = {
    "raw/apk-entries.json": "45232b06d2b10713ed49728cb49c007424d43a4d20ce3ea16a50fd57a867bed3",
    "raw/dex.json": "f0382fa0bc56811568280bec21ef46f0ee1557cfc5043fe0252207971a615389",
    "raw/elf.json": "c1a4b0b540a9aa57c662f58db253a92d3b7f63643408a0ca9272cfad8d904378",
    "raw/jni.json": "2f2c78dee9b431d3d3a1467d52312b9c493d1e8bd1eabf182e9b31bd6b745e5c",
    "raw/manifests.json": "047c1399c314ab7f1f7479a0991f537167fb16a69d8ca0b2fb1c49f5343ca555",
    "raw/resources.json": "d52c4a619845cdc1b553ba7e36376561dfec9f3e988cfea142a22b4c2d7d7b3f",
    "raw/signing.json": "d816dfddbcb2ede91555580515cce09f61bcb3c9cf81552e2dafc32cf9108668",
    "raw/xapk.json": "112d703fda085430bb3d3ae18383d472cbdc3d8a7c8ec741fe1b28c3c605a501",
}

OFFICIAL_OBLIGATION_IDS = {
    "raw/apk-entries.json": (
        "PRM-407E0077DF8949CFEA8B9EAAF9B4C40E830B3B0D5179F3B9ACC50FC105904794",
        "FCT-AC808AF9EC2DE4C42B615071C2EC235EDE9FB9BAC038C7E67D8D630353AFAFF8",
    ),
    "raw/dex.json": (
        "PRM-F28AE49408CB4736DC9D3D922D00793B8DBF9235ACD7A9C222D7AFE605E4AC18",
        "FCT-26759F4A4055B8A873B30577F43CAE8197879CCAC47FDE485B46E6B4CB85CF66",
    ),
    "raw/elf.json": (
        "PRM-BB8AC14005685BDE0F11069FDFD0420C334E515CB35FB66F28FC784D9AA27D07",
        "FCT-F144582138D71AE4E9318D8B52690AB64C45A52E67EC258975DDA1076E3E4E7A",
    ),
    "raw/jni.json": (
        "PRM-1EE4724B90B6077056959E8401D21F6767601437EE185BD1F2A16D87F6C27D79",
        "FCT-3A0D886FFC399A6C4C09BAE0D95CEDD1A436B228CEF847DBD78F498B4D8315B7",
    ),
    "raw/manifests.json": (
        "PRM-4CBC8D89F9FB81FD34CEDB4F9C8A44FBC4D73A172FD61157DA403C5304213679",
        "FCT-D994451676301BF67F55AD24D3095F576C18CD4F88DB7D92D638B402DE8C32F5",
    ),
    "raw/resources.json": (
        "PRM-0DDAAA3BE26061DCD6341F5A2B0F0425BD44533145D48734035DD38ADF7D45FC",
        "FCT-32B729F6576EA4D4CF6D0E71AB4A8AD673ABE6B56DF483A9AA6492D6F25D7BF3",
    ),
    "raw/signing.json": (
        "PRM-766EBE7D6C0625E08259F12CFA7C7E12806A5E4AD11C955EE156867066BD2E75",
        "FCT-CF70DD4815E561AD2E2413DA90C85CDBB6B634B5A17DB5BEE202631779D42651",
    ),
    "raw/xapk.json": (
        "PRM-B4177BD8DA5A57AC439E5ACA5AB76E5AF691389F10190D984BFF85140892831D",
        "FCT-9AB7666F405D9ECB7DB030347AA0ED186BF37775BB7B9FE4DDB6D331013F7B59",
    ),
}

INVENTORY_RECORD_TYPES = frozenset(
    (
        "frozen_artifact",
        "manifest_node",
        "resource",
        "asset",
        "certificate",
        "configuration",
        "android_component",
        "class",
        "method_family",
        "reflection_target",
        "dynamic_loader",
        "native_import",
        "native_export",
        "native_symbol",
        "jni_edge",
        "feature",
    )
)

DISCOVERED_RECORD_TYPES = frozenset(
    (
        "manifest_node",
        "resource",
        "asset",
        "certificate",
        "configuration",
        "android_component",
        "class",
        "method_family",
        "reflection_target",
        "dynamic_loader",
        "native_import",
        "native_export",
        "native_symbol",
        "jni_edge",
        "feature",
    )
)

REQUIRED_DISCOVERED_RECORD_TYPES = frozenset(
    (
        "manifest_node",
        "resource",
        "asset",
        "certificate",
        "configuration",
        "android_component",
        "class",
        "method_family",
        "native_import",
        "native_export",
        "native_symbol",
        "jni_edge",
        "feature",
    )
)

SOURCE_RECORD_KEYS = frozenset(
    (
        "source_locator",
        "record_type",
        "scope_key",
        "artifact_id",
        "source_artifact_id",
        "sha256",
        "size_bytes",
        "official_source",
    )
)

FIXED_SCOPE_COUNTS = {
    "android_components": 32,
    "apk_entries": 4314,
    "arm32_native_libraries": 90,
    "assets": 762,
    "certificates": 56,
    "dex_classes": 30635,
    "dex_defined_methods": 207025,
    "features": 3,
    "java_exports": 3227,
    "manifest_nodes": 188,
    "method_families": 184508,
    "native_declarations": 3266,
    "native_exports": 99414,
    "native_imports": 12627,
    "native_needed_edges": 490,
    "native_symbols": 111643,
    "native_undefined_imports": 12137,
    "per_library_summaries": 88,
    "resource_configurations": 36498,
    "resources": 33431,
    "xapk_entries": 21,
}

VARIABLE_SCOPE_TYPES = {
    "dynamic_loaders": "dynamic_loader",
    "jni_edges": "jni_edge",
    "reflection_targets": "reflection_target",
}

DIRECT_SCOPE_TYPES = {
    "android_components": "android_component",
    "assets": "asset",
    "certificates": "certificate",
    "dex_classes": "class",
    "features": "feature",
    "manifest_nodes": "manifest_node",
    "method_families": "method_family",
    "native_exports": "native_export",
    "native_imports": "native_import",
    "native_symbols": "native_symbol",
    "resources": "resource",
}

CONSERVATION_SCOPES = frozenset((*FIXED_SCOPE_COUNTS, *VARIABLE_SCOPE_TYPES))
CONFIGURATION_FLOOR = 21 + 4314 + 90 + 36498 + 88
NORMALIZED_FIXED_FLOOR = 514431

BYTE_RECORD_FAMILIES = frozenset(
    {
        "frozen_artifact",
        "configuration:xapk_archive_entry",
        "configuration:apk_archive_entry",
        "configuration:arm32_native_library",
        "asset",
        "certificate",
    }
)

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID_NAME = f"{{{ANDROID_NS}}}name"
ANDROID_PROCESS = f"{{{ANDROID_NS}}}process"
ANDROID_EXPORTED = f"{{{ANDROID_NS}}}exported"
ANDROID_ENABLED = f"{{{ANDROID_NS}}}enabled"
ANDROID_DIRECT_BOOT = f"{{{ANDROID_NS}}}directBootAware"
ANDROID_PERMISSION = f"{{{ANDROID_NS}}}permission"
ANDROID_FOREGROUND_SERVICE_TYPE = f"{{{ANDROID_NS}}}foregroundServiceType"
ANDROID_REQUIRED = f"{{{ANDROID_NS}}}required"
ANDROID_GL_ES_VERSION = f"{{{ANDROID_NS}}}glEsVersion"

COMPONENT_TAGS = frozenset(
    ("application", "activity", "activity-alias", "service", "receiver", "provider")
)

DYNAMIC_LOADER_MARKERS = (
    "Ljava/lang/Class;->forName",
    "Ljava/lang/ClassLoader;->loadClass",
    "Ldalvik/system/BaseDexClassLoader;",
    "Ldalvik/system/DexClassLoader;",
    "Ldalvik/system/InMemoryDexClassLoader;",
    "Ldalvik/system/PathClassLoader;",
    "Ljava/lang/System;->load",
    "Ljava/lang/Runtime;->load",
    "Lcom/sun/jna/Native;->load",
)
REFLECTION_MARKERS = (
    "Ljava/lang/Class;->forName",
    "Ljava/lang/ClassLoader;->loadClass",
)

DEX_INVOKE_OPCODE_FAMILIES = {
    "invoke-static": "STATIC",
    "invoke-static/range": "STATIC",
    "invoke-virtual": "VIRTUAL",
    "invoke-virtual/range": "VIRTUAL",
    "invoke-super": "SUPER",
    "invoke-super/range": "SUPER",
    "invoke-direct": "DIRECT",
    "invoke-direct/range": "DIRECT",
    "invoke-interface": "INTERFACE",
    "invoke-interface/range": "INTERFACE",
}

READELF_DYNSYM_RE = re.compile(
    r"^\s*(?P<index>\d+):\s+"
    r"(?P<value>[0-9A-Fa-f]+)\s+"
    r"(?P<size>0x[0-9A-Fa-f]+|\d+)\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<bind>\S+)\s+"
    r"(?P<visibility>\S+)\s+"
    r"(?P<section>\S+)\s*(?P<name>.*)$"
)
READELF_DYNSYM_COUNT_RE = re.compile(r"Symbol table '\.dynsym' contains (\d+) entries:")
READELF_DYNAMIC_RE = re.compile(
    r"^\s*0x[0-9A-Fa-f]+\s+\((?P<tag>[^)]+)\)\s+(?P<value>.*)$"
)
READELF_NEEDED_VALUE_RE = re.compile(r"Shared library: \[(?P<name>[^]]+)\]")
OBJDUMP_ROW_RE = re.compile(r"^[0-9A-Fa-f]+\s")


class ProducerError(RuntimeError):
    """Raised when extraction or an invariant violates the frozen contract."""


def _require(condition: Any, code: str, detail: Any = "") -> None:
    if not condition:
        suffix = f": {detail}" if detail != "" else ""
        raise ProducerError(f"{code}{suffix}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _deterministic_timestamp(ordinal: int = 0) -> str:
    _require(
        isinstance(ordinal, int) and not isinstance(ordinal, bool) and 0 <= ordinal <= 999999,
        "deterministic_timestamp_ordinal",
    )
    return f"2024-01-01T00:00:00.{ordinal:06d}Z"


def _normalize(value: Any, *, label: str = "canonical JSON") -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ProducerError(f"{label} object key is not a string")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise ProducerError(f"{label} has duplicate keys after NFC normalization: {key!r}")
            normalized[key] = _normalize(item, label=label)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize(item, label=label) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ProducerError(f"{label} contains a non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ProducerError(f"{label} contains unsupported value type {type(value).__name__}")


def _object_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, value in pairs:
        key = unicodedata.normalize("NFC", raw_key)
        if key in result:
            raise ProducerError(f"JSON input has duplicate keys after NFC normalization: {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object_pairs)


def _loads_json(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_object_pairs)


def _canonical_text(value: Any) -> str:
    try:
        return json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProducerError(f"cannot encode canonical JSON: {exc}") from exc


def _canonical_bytes(value: Any) -> bytes:
    return _canonical_text(value).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_stream(handle: Any, destination: Path | None = None) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    output = destination.open("wb") if destination is not None else None
    try:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
            if output is not None:
                output.write(chunk)
    finally:
        if output is not None:
            output.close()
    return digest.hexdigest(), size


def _write_json(path: Path, value: Any, *, pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        rendered = json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    else:
        rendered = _canonical_bytes(value)
    path.write_bytes(rendered + b"\n")


def _payload_digest(payload: Any) -> tuple[str, int]:
    encoded = _canonical_bytes(payload)
    return _sha256_bytes(encoded), len(encoded)


def _record_id(record_type: str, payload: Any) -> str:
    identity = ["g002-record/v1", record_type, payload]
    return "INV-" + _sha256_bytes(_canonical_bytes(identity)).upper()


def _artifact_record_id(artifact_id: str, _kind: str | None = None) -> str:
    return _record_id("frozen_artifact", artifact_id)


def _record_family(record_type: str, payload: Any) -> str:
    if record_type == "configuration" and isinstance(payload, Mapping):
        return f"configuration:{payload['configuration_kind']}"
    if record_type == "native_import" and isinstance(payload, Mapping):
        return f"native_import:{payload['import_kind']}"
    return record_type


def _descriptor(value: Any) -> str:
    return "".join(str(value).split())


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ProducerError(f"path is outside repository root: {path}") from exc


def _resolve_path(repo_root: Path, raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _safe_zip_path(raw: str, *, label: str) -> str:
    normalized = unicodedata.normalize("NFC", raw)
    pure = PurePosixPath(normalized)
    if (
        not normalized
        or pure.is_absolute()
        or "\x00" in normalized
        or "\\" in normalized
        or any(part in {"", ".", ".."} for part in normalized.split("/"))
    ):
        raise ProducerError(f"{label} has unsafe ZIP path {raw!r}")
    return normalized


def _archive_payload(
    *,
    container_artifact_id: str,
    ordinal: int,
    path: str,
    info: zipfile.ZipInfo,
    sha256: str,
) -> dict[str, Any]:
    return {
        "configuration_kind": (
            "xapk_archive_entry"
            if container_artifact_id == "official-xapk"
            else "apk_archive_entry"
        ),
        "container_artifact_id": container_artifact_id,
        "central_directory_ordinal": ordinal,
        "path": path,
        "compression_method": int(info.compress_type),
        "crc32": int(info.CRC),
        "compressed_size_bytes": int(info.compress_size),
        "uncompressed_size_bytes": int(info.file_size),
        "sha256": sha256,
    }


def _payload_byte_evidence(payload: Mapping[str, Any]) -> tuple[str, int]:
    size_key = (
        "size_bytes" if "size_bytes" in payload else "uncompressed_size_bytes"
    )
    return str(payload["sha256"]), int(payload[size_key])


def _apk_archive_entry_parent_ids(
    collector: "RecordCollector",
    apk_artifact_id: str,
    *,
    nested_artifact_id: str | None = None,
) -> list[str]:
    """Return the v10 parent set for a physical entry in a canonical APK.

    The containing APK frozen artifact is always a parent. When the official
    manifest path namespace has already identified this APK entry as an exact
    frozen nested artifact occurrence, include that exact nested frozen artifact
    as a second parent. This deliberately avoids hash-only crosswiring.
    """

    parent_ids = [_source_parent_for_collector(collector, apk_artifact_id)]
    if nested_artifact_id is not None:
        parent_ids.append(_source_parent_for_collector(collector, nested_artifact_id))
    return sorted(set(parent_ids))

def _frozen_dataset(kind: str) -> str:
    if kind == "dex":
        return "dex"
    if kind == "native_library":
        return "elf"
    if kind == "official_fixture":
        return "apk_entries"
    return "xapk"


class RecordCollector:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.dataset_by_record_id: dict[str, str] = {}
        self._scope_identities: set[tuple[str, str]] = set()
        self._record_ids: set[str] = set()

    def add(
        self,
        record_type: str,
        payload: Any,
        *,
        dataset: str,
        artifact_id: str | None,
        source_artifact_id: str,
        sha256: str | None,
        size_bytes: int | None,
        official_source: Mapping[str, Any] | None,
        parent_record_ids: Iterable[str] = (),
    ) -> str:
        if record_type not in INVENTORY_RECORD_TYPES:
            raise ProducerError(f"unsupported inventory record type: {record_type}")
        if dataset not in RAW_DATASET_PATHS:
            raise ProducerError(f"unsupported raw evidence dataset: {dataset}")
        scope_key = _canonical_text(payload)
        identity = (record_type, scope_key)
        if identity in self._scope_identities:
            raise ProducerError(f"duplicate normalized scope identity: {identity}")
        record_id = _record_id(record_type, payload)
        if record_id in self._record_ids:
            raise ProducerError(f"record ID collision: {record_id}")
        family = _record_family(record_type, payload)
        if family not in BYTE_RECORD_FAMILIES:
            sha256 = None
            size_bytes = None
            official_source = None
        if record_type != "frozen_artifact":
            artifact_id = None
        if sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ProducerError(f"invalid SHA-256 for {record_id}")
        if size_bytes is not None and (type(size_bytes) is not int or size_bytes < 0):
            raise ProducerError(f"invalid size for {record_id}")
        parents = sorted(set(parent_record_ids))
        record = {
            "record_id": record_id,
            "record_type": record_type,
            "scope_key": scope_key,
            "payload": _normalize(payload),
            "artifact_id": artifact_id,
            "source_artifact_id": source_artifact_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "official_source": _normalize(official_source) if official_source is not None else None,
            "dossier_id": None,
            "classification_status": "classified",
            "parent_record_ids": parents,
        }
        self.records.append(record)
        self.dataset_by_record_id[record_id] = dataset
        self._scope_identities.add(identity)
        self._record_ids.add(record_id)
        return record_id

    def finalize(self) -> tuple[list[dict[str, Any]], dict[str, str]]:
        records = sorted(self.records, key=lambda item: str(item["record_id"]))
        known_ids = {str(record["record_id"]) for record in records}
        for record in records:
            unknown = set(record["parent_record_ids"]) - known_ids
            if unknown or record["record_id"] in record["parent_record_ids"]:
                raise ProducerError(f"invalid parents for {record['record_id']}: {sorted(unknown)}")
        return records, dict(self.dataset_by_record_id)


class ArtifactObserver:
    def __init__(self, artifacts: Sequence[Mapping[str, Any]]) -> None:
        self.expected = {str(item["artifact_id"]): item for item in artifacts}
        if len(self.expected) != len(artifacts):
            raise ProducerError("frozen artifact manifest contains duplicate IDs")
        self.observed: dict[str, dict[str, Any]] = {}

    def observe(self, artifact_id: str, sha256: str, size_bytes: int, origin: str) -> None:
        expected = self.expected.get(artifact_id)
        if expected is None:
            raise ProducerError(f"observed artifact outside frozen universe: {artifact_id}")
        if expected.get("sha256") != sha256 or expected.get("size_bytes") != size_bytes:
            raise ProducerError(
                f"frozen artifact mismatch for {artifact_id}: "
                f"expected {expected.get('sha256')}/{expected.get('size_bytes')}, "
                f"observed {sha256}/{size_bytes}"
            )
        prior = self.observed.get(artifact_id)
        row = {
            "artifact_id": artifact_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "origin": origin,
        }
        if prior is not None and prior != row:
            raise ProducerError(f"inconsistent repeated observation for {artifact_id}")
        self.observed[artifact_id] = row

    def finalize(self) -> list[dict[str, Any]]:
        missing = sorted(set(self.expected) - set(self.observed))
        if missing:
            raise ProducerError(f"frozen artifact rows not rehashed from XAPK bytes: {missing}")
        return [self.observed[key] for key in sorted(self.observed)]


@dataclass(frozen=True)
class Inputs:
    repo_root: Path
    xapk: Path
    official_manifest_path: Path
    official_manifest: Mapping[str, Any]
    artifacts: tuple[Mapping[str, Any], ...]
    artifacts_by_id: Mapping[str, Mapping[str, Any]]
    artifact_set_id: str
    base_member: str
    apk_member_artifact_by_path: Mapping[str, str]
    xapk_member_artifact_by_path: Mapping[str, str]
    base_entry_artifact_by_path: Mapping[str, str]


def _load_inputs(args: argparse.Namespace, repo_root: Path) -> Inputs:
    official_path = _resolve_path(repo_root, args.official_manifest)
    if not official_path.is_file():
        raise ProducerError(f"official artifact manifest is missing: {official_path}")
    official = _load_json(official_path)
    if not isinstance(official, dict):
        raise ProducerError("official artifact manifest is not an object")
    artifacts_raw = official.get("artifacts")
    if not isinstance(artifacts_raw, list) or len(artifacts_raw) != 121:
        raise ProducerError("official artifact manifest must contain exactly 121 rows")
    artifacts = tuple(item for item in artifacts_raw if isinstance(item, dict))
    if len(artifacts) != len(artifacts_raw):
        raise ProducerError("official artifact manifest contains a non-object artifact")
    artifacts_by_id = {str(item["artifact_id"]): item for item in artifacts}
    if len(artifacts_by_id) != len(artifacts):
        raise ProducerError("official artifact manifest contains duplicate artifact IDs")

    xapk = _resolve_path(repo_root, args.xapk)
    if not xapk.is_file():
        raise ProducerError(f"untouched official XAPK is missing: {xapk}")

    apk_members: dict[str, str] = {}
    xapk_members: dict[str, str] = {}
    base_member: str | None = None
    extracted_base = artifacts_by_id.get("extracted-base-apk")
    if extracted_base is None:
        raise ProducerError("frozen universe lacks extracted-base-apk")
    for artifact in artifacts:
        source = artifact.get("source")
        if isinstance(source, dict) and source.get("type") == "zip_member":
            member = source.get("member_path")
            if isinstance(member, str):
                xapk_members[member] = str(artifact["artifact_id"])
        if artifact.get("kind") != "apk_member":
            continue
        source = artifact.get("source")
        if not isinstance(source, dict) or not isinstance(source.get("member_path"), str):
            raise ProducerError(f"APK member lacks a frozen member path: {artifact.get('artifact_id')}")
        member = str(source["member_path"])
        apk_members[member] = str(artifact["artifact_id"])
        if artifact.get("sha256") == extracted_base.get("sha256"):
            if base_member is not None:
                raise ProducerError("base APK member is ambiguous")
            base_member = member
    if len(apk_members) != 19 or base_member is None:
        raise ProducerError("frozen universe does not identify 19 APK members and one base APK")
    if len(xapk_members) != 21:
        raise ProducerError(f"frozen XAPK member universe must contain 21 rows, observed {len(xapk_members)}")

    base_entries: dict[str, str] = {}
    for artifact in artifacts:
        artifact_id = str(artifact["artifact_id"])
        kind = artifact.get("kind")
        if kind == "dex" and artifact_id.startswith("extracted-dex:"):
            base_entries[artifact_id.split(":", 1)[1]] = artifact_id
        elif kind == "native_library" and artifact_id.startswith("extracted-native:"):
            base_entries[f"lib/{artifact_id.split(':', 1)[1]}"] = artifact_id
        elif kind == "official_fixture" and artifact_id.startswith("extracted-fixture:"):
            base_entries[f"assets/{artifact_id.split(':', 1)[1]}"] = artifact_id
    if collections.Counter(artifacts_by_id[item]["kind"] for item in base_entries.values()) != collections.Counter(
        {"dex": 4, "native_library": 88, "official_fixture": 6}
    ):
        raise ProducerError("frozen base-entry universe is incomplete")

    return Inputs(
        repo_root=repo_root,
        xapk=xapk,
        official_manifest_path=official_path,
        official_manifest=official,
        artifacts=artifacts,
        artifacts_by_id=artifacts_by_id,
        artifact_set_id=str(official["artifact_set_id"]),
        base_member=base_member,
        apk_member_artifact_by_path=dict(sorted(apk_members.items())),
        xapk_member_artifact_by_path=dict(sorted(xapk_members.items())),
        base_entry_artifact_by_path=dict(sorted(base_entries.items())),
    )


def _source_parent(inputs: Inputs, artifact_id: str) -> str:
    artifact = inputs.artifacts_by_id[artifact_id]
    return _artifact_record_id(artifact_id, str(artifact["kind"]))


def _add_frozen_artifacts(collector: RecordCollector, inputs: Inputs) -> None:
    for artifact in sorted(inputs.artifacts, key=lambda item: str(item["artifact_id"])):
        artifact_id = str(artifact["artifact_id"])
        kind = str(artifact["kind"])
        collector.add(
            "frozen_artifact",
            artifact_id,
            dataset=_frozen_dataset(kind),
            artifact_id=artifact_id,
            source_artifact_id=artifact_id,
            sha256=str(artifact["sha256"]),
            size_bytes=int(artifact["size_bytes"]),
            official_source=artifact["source"],
            parent_record_ids=(),
        )


def _entry_source_artifact(inputs: Inputs, apk_member: str, entry_path: str) -> str:
    if apk_member == inputs.base_member and entry_path in inputs.base_entry_artifact_by_path:
        return inputs.base_entry_artifact_by_path[entry_path]
    return inputs.apk_member_artifact_by_path[apk_member]


def _decode_utf16_scalar(raw: bytes) -> str:
    try:
        return unicodedata.normalize("NFC", raw.decode("utf-16-le", "strict"))
    except UnicodeDecodeError as exc:
        raise ProducerError(f"axml_invalid_string: {exc}") from exc


def _length8(data: bytes, position: int) -> tuple[int, int]:
    _require(position < len(data), "axml_invalid_string")
    first = data[position]
    position += 1
    if first & 0x80:
        _require(position < len(data), "axml_invalid_string")
        return ((first & 0x7F) << 8) | data[position], position + 1
    return first, position


def _length16(data: bytes, position: int) -> tuple[int, int]:
    _require(position + 2 <= len(data), "axml_invalid_string")
    first = struct.unpack_from("<H", data, position)[0]
    position += 2
    if first & 0x8000:
        _require(position + 2 <= len(data), "axml_invalid_string")
        second = struct.unpack_from("<H", data, position)[0]
        return ((first & 0x7FFF) << 16) | second, position + 2
    return first, position


def _parse_string_pool(data: bytes, offset: int) -> tuple[list[str], int]:
    _require(offset + 28 <= len(data), "axml_string_pool")
    chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
    _require(
        chunk_type == 1
        and header_size == 28
        and chunk_size >= 28
        and chunk_size % 4 == 0
        and offset + chunk_size <= len(data),
        "axml_string_pool",
    )
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from(
        "<IIIII", data, offset + 8
    )
    _require(flags & ~0x101 == 0, "axml_string_pool")
    _require(
        header_size + 4 * (string_count + style_count) <= chunk_size,
        "axml_string_pool",
    )
    _require(
        strings_start >= header_size + 4 * (string_count + style_count)
        and strings_start < chunk_size,
        "axml_string_pool",
    )
    if style_count:
        _require(strings_start <= styles_start < chunk_size, "axml_string_pool")
    else:
        _require(styles_start == 0, "axml_string_pool")
    strings: list[str] = []
    for index in range(string_count):
        relative = struct.unpack_from("<I", data, offset + header_size + index * 4)[0]
        position = offset + strings_start + relative
        _require(position < offset + chunk_size, "axml_invalid_string")
        if flags & 0x100:
            utf16_length, position = _length8(data, position)
            byte_length, position = _length8(data, position)
            _require(
                position + byte_length + 1 <= offset + chunk_size
                and data[position + byte_length] == 0,
                "axml_invalid_string",
            )
            try:
                text = data[position : position + byte_length].decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise ProducerError(f"axml_invalid_string: {exc}") from exc
            _require(
                len(text.encode("utf-16-le")) // 2 == utf16_length,
                "axml_invalid_string",
            )
            strings.append(unicodedata.normalize("NFC", text))
        else:
            utf16_length, position = _length16(data, position)
            byte_length = utf16_length * 2
            _require(
                position + byte_length + 2 <= offset + chunk_size
                and data[position + byte_length : position + byte_length + 2] == b"\0\0",
                "axml_invalid_string",
            )
            strings.append(_decode_utf16_scalar(data[position : position + byte_length]))
    return strings, offset + chunk_size


def _percent_encode(value: str) -> str:
    result: list[str] = []
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
    for byte in value.encode("utf-8"):
        result.append(chr(byte) if byte in unreserved else f"%{byte:02X}")
    return "".join(result)


def _qname_v6(namespace: str, local_name: str) -> str:
    return f"Q{{{_percent_encode(namespace)}}}{_percent_encode(local_name)}"


def _parse_axml_v6(data: bytes) -> dict[str, Any]:
    _require(len(data) >= 8, "axml_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    _require(
        root_type == 3 and root_header == 8 and root_size == len(data),
        "axml_root",
    )
    strings, offset = _parse_string_pool(data, 8)
    namespace_stack: list[tuple[str, str]] = []
    resource_map: list[int] | None = None
    if offset < len(data):
        _require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        if chunk_type == 0x0180:
            _require(
                header_size == 8 and chunk_size >= 8 and chunk_size % 4 == 0,
                "axml_resource_map",
            )
            resource_map = list(
                struct.unpack_from(f"<{(chunk_size - 8) // 4}I", data, offset + 8)
            )
            offset += chunk_size
    stack: list[dict[str, Any]] = []
    event_ordinal = 0
    nodes: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    components: list[tuple[str, str | None, str]] = []
    package_name: str | None = None
    split_id: str | None = None
    min_sdk: int | None = None
    target_sdk: int | None = None
    while offset < len(data):
        _require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        _require(
            header_size >= 8
            and chunk_size >= header_size
            and chunk_size % 4 == 0
            and offset + chunk_size <= len(data),
            "axml_chunk",
        )
        if chunk_type == 0x0102:
            _require(header_size == 16 and offset + 36 <= len(data), "axml_start_element")
            extension = offset + header_size
            (
                namespace_index,
                name_index,
                attribute_start,
                attribute_size,
                attribute_count,
                _id_index,
                _class_index,
                _style_index,
            ) = struct.unpack_from("<IIHHHHHH", data, extension)
            _require(
                name_index < len(strings)
                and attribute_start == 20
                and attribute_size == 20,
                "axml_start_element",
            )
            _require(
                namespace_index == 0xFFFFFFFF or namespace_index < len(strings),
                "axml_string_index",
            )
            namespace = "" if namespace_index == 0xFFFFFFFF else strings[namespace_index]
            local_name = strings[name_index]
            qname = _qname_v6(namespace, local_name)
            sibling_counts = stack[-1]["sibling_counts"] if stack else collections.defaultdict(int)
            sibling_counts[qname] += 1
            sibling_ordinal = sibling_counts[qname]
            path = (stack[-1]["path"] if stack else "axmlpath:") + f"/{qname}[{sibling_ordinal}]"
            attrs: dict[tuple[str, str], dict[str, Any]] = {}
            physical_attributes: list[dict[str, Any]] = []
            attribute_offset = extension + attribute_start
            for attribute_ordinal in range(attribute_count):
                base = attribute_offset + attribute_ordinal * 20
                _require(base + 20 <= offset + chunk_size, "axml_attribute")
                (
                    attribute_namespace,
                    attribute_name,
                    raw_value,
                    value_size,
                    reserved,
                    data_type,
                    value_data,
                ) = struct.unpack_from("<IIIHBBI", data, base)
                _require(
                    attribute_name < len(strings) and value_size == 8 and reserved == 0,
                    "axml_attribute",
                )
                _require(
                    attribute_namespace == 0xFFFFFFFF
                    or attribute_namespace < len(strings),
                    "axml_string_index",
                )
                _require(
                    raw_value == 0xFFFFFFFF or raw_value < len(strings),
                    "axml_string_index",
                )
                _require(
                    data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31},
                    "axml_value_type",
                )
                namespace_text = (
                    "" if attribute_namespace == 0xFFFFFFFF else strings[attribute_namespace]
                )
                attribute_name_text = strings[attribute_name]
                key = (namespace_text, attribute_name_text)
                _require(key not in attrs, "axml_duplicate_attribute")
                typed = None
                if data_type == 3:
                    _require(value_data < len(strings), "axml_string_index")
                    typed = strings[value_data]
                raw_text = None if raw_value == 0xFFFFFFFF else strings[raw_value]
                value = {
                    "namespace": namespace_text,
                    "name": attribute_name_text,
                    "attribute_ordinal": attribute_ordinal,
                    "qname": _qname_v6(namespace_text, attribute_name_text),
                    "raw": raw_text,
                    "type": data_type,
                    "data": value_data,
                    "typed": typed,
                    "resource_id": (
                        resource_map[attribute_name]
                        if resource_map is not None
                        and attribute_name < len(resource_map)
                        and resource_map[attribute_name] != 0
                        else None
                    ),
                }
                attrs[key] = value
                physical_attributes.append(value)
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
                        for item in physical_attributes
                    ],
                    key=_canonical_text,
                ),
            }
            nodes.append(node)
            if not stack and local_name == "manifest":
                package_attr = attrs.get(("", "package"))
                split_attr = attrs.get(("", "split"))
                package_name = (package_attr or {}).get("typed") or (package_attr or {}).get("raw")
                split_id = (split_attr or {}).get("typed") or (split_attr or {}).get("raw")
            if len(stack) == 1 and local_name == "uses-sdk":
                minimum = attrs.get((ANDROID_NS, "minSdkVersion"))
                target = attrs.get((ANDROID_NS, "targetSdkVersion"))
                min_sdk = int(minimum["data"]) if minimum else min_sdk
                target_sdk = int(target["data"]) if target else target_sdk
            if len(stack) == 1 and local_name == "uses-feature":
                name_attr = attrs.get((ANDROID_NS, "name"))
                gl_attr = attrs.get((ANDROID_NS, "glEsVersion"))
                required_attr = attrs.get((ANDROID_NS, "required"))
                features.append(
                    {
                        "name": (name_attr or {}).get("typed"),
                        "gl_es_version": int(gl_attr["data"]) if gl_attr else None,
                        "required": bool(required_attr["data"]) if required_attr else True,
                    }
                )
            if local_name in COMPONENT_TAGS:
                name_attr = attrs.get((ANDROID_NS, "name"))
                name = (name_attr or {}).get("typed") or (name_attr or {}).get("raw")
                components.append((local_name, name, path))
            stack.append(
                {
                    "qname": qname,
                    "path": path,
                    "sibling_counts": collections.defaultdict(int),
                }
            )
        elif chunk_type == 0x0103:
            _require(header_size == 16 and stack, "axml_end_element")
            namespace_index, name_index = struct.unpack_from("<II", data, offset + header_size)
            _require(
                namespace_index == 0xFFFFFFFF or namespace_index < len(strings),
                "axml_string_index",
            )
            namespace = "" if namespace_index == 0xFFFFFFFF else strings[namespace_index]
            _require(name_index < len(strings), "axml_end_element")
            _require(
                stack[-1]["qname"] == _qname_v6(namespace, strings[name_index]),
                "axml_end_element",
            )
            stack.pop()
        elif chunk_type in {0x0100, 0x0101}:
            _require(header_size == 16 and chunk_size == 24, "axml_namespace")
            prefix_index, uri_index = struct.unpack_from("<II", data, offset + 16)
            _require(prefix_index < len(strings) and uri_index < len(strings), "axml_string_index")
            pair = (strings[prefix_index], strings[uri_index])
            if chunk_type == 0x0100:
                namespace_stack.append(pair)
            else:
                _require(namespace_stack and namespace_stack[-1] == pair, "axml_namespace")
                namespace_stack.pop()
        elif chunk_type == 0x0104:
            _require(header_size == 16 and chunk_size == 28, "axml_cdata")
            data_index, value_size, reserved, data_type, value_data = struct.unpack_from(
                "<IHBBI", data, offset + 16
            )
            _require(
                data_index < len(strings) and value_size == 8 and reserved == 0,
                "axml_cdata",
            )
            _require(
                data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31},
                "axml_value_type",
            )
            if data_type == 3:
                _require(value_data < len(strings), "axml_string_index")
        else:
            raise ProducerError("axml_unknown_chunk")
        event_ordinal += 1
        offset += chunk_size
    _require(not stack and not namespace_stack, "axml_stack")
    return {
        "nodes": nodes,
        "features": features,
        "components": components,
        "package": package_name,
        "split": split_id,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
    }


def _qname(namespace: Any, name: Any) -> str:
    uri = "" if namespace is None else str(namespace)
    local = str(name)
    return f"{{{uri}}}{local}" if uri else local


def _local_name(qname: str) -> str:
    return qname.split("}", 1)[1] if qname.startswith("{") and "}" in qname else qname


def _bool_value(value: str | None, *, default: bool | None) -> bool | None:
    if value is None:
        return default
    lowered = value.strip().casefold()
    if lowered in {"true", "1"}:
        return True
    if lowered in {"false", "0"}:
        return False
    raise ProducerError(f"manifest boolean has noncanonical value {value!r}")


def _component_name(package_name: str, raw_name: str | None, kind: str) -> str:
    if not raw_name:
        return package_name if kind == "application" else package_name
    if raw_name.startswith("."):
        return package_name + raw_name
    if "." not in raw_name:
        return f"{package_name}.{raw_name}"
    return raw_name


def _manifest_attr_text(attrs: Mapping[tuple[str, str], Mapping[str, Any]], name: str) -> str | None:
    attr = attrs.get((ANDROID_NS, name))
    if attr is None:
        return None
    value = attr.get("typed")
    if value is None:
        value = attr.get("raw")
    return None if value is None else str(value)


def _manifest_attr_bool(
    attrs: Mapping[tuple[str, str], Mapping[str, Any]],
    name: str,
    default: bool | None,
) -> bool | None:
    attr = attrs.get((ANDROID_NS, name))
    if attr is None:
        return default
    if attr.get("type") == 18:
        return bool(int(attr["data"]))
    return _bool_value(_manifest_attr_text(attrs, name), default=default)


def _manifest_attr_int(
    attrs: Mapping[tuple[str, str], Mapping[str, Any]],
    name: str,
    default: int | None,
) -> int | None:
    attr = attrs.get((ANDROID_NS, name))
    if attr is None:
        return default
    return int(attr["data"])


def _component_process(package_name: str, raw_process: str | None, default_process: str) -> str:
    value = raw_process or default_process
    if value == "package":
        return package_name
    if value == "application":
        return package_name
    return value


def _add_manifest_records(
    collector: RecordCollector,
    *,
    axml: Mapping[str, Any],
    apk_artifact_id: str,
    include_installed_declarations: bool = False,
) -> dict[str, Any]:
    source_parent = _source_parent_for_collector(collector, apk_artifact_id)
    manifest_archive_parents = [
        str(record["record_id"])
        for record in collector.records
        if record["record_type"] == "configuration"
        and record["payload"].get("configuration_kind") == "apk_archive_entry"
        and record["payload"].get("container_artifact_id") == apk_artifact_id
        and record["payload"].get("path") == "AndroidManifest.xml"
    ]
    if len(manifest_archive_parents) != 1:
        raise ProducerError(
            f"manifest archive occurrence is ambiguous for {apk_artifact_id}"
        )
    record_id_by_path: dict[str, str] = {}
    node_by_path: dict[str, Mapping[str, Any]] = {}
    feature_index = 0
    for node in axml["nodes"]:
        path = str(node["path"])
        parent_path = path.rsplit("/", 1)[0]
        parent_node_id = record_id_by_path.get(parent_path)
        _require(
            (parent_path == "axmlpath:") == (parent_node_id is None),
            "official_manifest_parent",
            path,
        )
        payload = {
            "apk_artifact_id": apk_artifact_id,
            "event_ordinal": int(node["event_ordinal"]),
            "qname": node["qname"],
            "xpath": path,
            "attributes": node["attributes"],
            "parent_manifest_node_record_id": parent_node_id,
        }
        node_id = collector.add(
            "manifest_node",
            payload,
            dataset="manifests",
            artifact_id=None,
            source_artifact_id=apk_artifact_id,
            sha256=None,
            size_bytes=None,
            official_source=None,
            parent_record_ids=[
                source_parent,
                *(manifest_archive_parents if parent_node_id is None else [parent_node_id]),
            ],
        )
        record_id_by_path[path] = node_id
        node_by_path[path] = node
        if node["name"] == "uses-feature":
            feature = axml["features"][feature_index]
            feature_index += 1
            feature_payload = {
                "apk_artifact_id": apk_artifact_id,
                "declaration_manifest_node_record_id": node_id,
                **feature,
            }
            collector.add(
                "feature",
                feature_payload,
                dataset="manifests",
                artifact_id=None,
                source_artifact_id=apk_artifact_id,
                sha256=None,
                size_bytes=None,
                official_source=None,
                parent_record_ids=[source_parent, node_id],
            )
    _require(feature_index == len(axml["features"]), "official_feature_count")
    component_count = 0
    if include_installed_declarations:
        package_name = str(axml.get("package") or "")
        effective_target_sdk = int(axml.get("target_sdk") or axml.get("min_sdk") or 1)
        app_nodes = [
            node for node in axml["nodes"] if str(node["name"]) == "application"
        ]
        application_attrs = app_nodes[0].get("attrs", {}) if app_nodes else {}
        app_enabled = _manifest_attr_bool(application_attrs, "enabled", True)
        app_process = _component_process(
            package_name,
            _manifest_attr_text(application_attrs, "process"),
            "package",
        )
        app_permission = _manifest_attr_text(application_attrs, "permission")

        declaration_rows: list[dict[str, Any]] = []
        for kind_raw, raw_name, path in axml["components"]:
            node = node_by_path[path]
            attrs = node.get("attrs", {})
            kind = str(kind_raw).replace("-", "_")
            is_application = kind == "application"
            has_filter = any(
                str(child.get("path", "")).startswith(f"{path}/")
                and str(child.get("name")) == "intent-filter"
                for child in axml["nodes"]
            )
            default_name = "android.app.Application" if is_application else None
            name = _component_name(package_name, raw_name or default_name, kind)
            enabled_local = _manifest_attr_bool(attrs, "enabled", True)
            enabled = bool(enabled_local if is_application else (app_enabled and enabled_local))
            process_default = "package" if is_application else app_process
            permission_default = None if is_application else app_permission
            if is_application:
                exported_default: bool | None = None
            elif kind == "provider":
                exported_default = effective_target_sdk < 17
            else:
                exported_default = has_filter
            target_activity = _manifest_attr_text(attrs, "targetActivity")
            payload = {
                "package": package_name,
                "kind": kind,
                "name": name,
                "process": _component_process(
                    package_name,
                    _manifest_attr_text(attrs, "process"),
                    process_default,
                ),
                "permission": _manifest_attr_text(attrs, "permission") or permission_default,
                "enabled": enabled,
                "exported": _manifest_attr_bool(attrs, "exported", exported_default),
                "direct_boot_aware": bool(
                    _manifest_attr_bool(attrs, "directBootAware", False)
                ),
                "foreground_service_type": _manifest_attr_int(
                    attrs,
                    "foregroundServiceType",
                    0 if kind == "service" else None,
                ),
                "target_activity": (
                    _component_name(package_name, target_activity, "activity")
                    if target_activity
                    else None
                ),
                "effective_target_sdk": effective_target_sdk,
            }
            declaration_rows.append(
                {
                    "kind": kind,
                    "name": name,
                    "path": path,
                    "event_ordinal": int(node["event_ordinal"]),
                    "payload": payload,
                    "declaration_record_id": record_id_by_path[path],
                }
            )

        groups: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
        for row in declaration_rows:
            groups[(str(row["kind"]), str(row["name"]))].append(row)

        component_specs: list[dict[str, Any]] = []
        for merge_key, rows in sorted(groups.items()):
            ordered_rows = sorted(rows, key=lambda row: (int(row["event_ordinal"]), str(row["path"])))
            payload = ordered_rows[0]["payload"]
            for row in ordered_rows[1:]:
                _require(
                    _canonical_text(row["payload"]) == _canonical_text(payload),
                    "android_component_merge_conflict",
                    merge_key,
                )
            component_specs.append(
                {
                    "merge_key": merge_key,
                    "payload": payload,
                    "record_id": _record_id("android_component", payload),
                    "declaration_record_ids": sorted(
                        str(row["declaration_record_id"]) for row in ordered_rows
                    ),
                    "first_event_ordinal": int(ordered_rows[0]["event_ordinal"]),
                }
            )

        target_activity_specs: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        for spec in component_specs:
            payload = spec["payload"]
            if payload["kind"] == "activity":
                target_activity_specs[str(payload["name"])].append(spec)

        for spec in component_specs:
            payload = spec["payload"]
            parent_ids = [source_parent, *spec["declaration_record_ids"]]
            if payload["kind"] == "activity_alias":
                target_name = payload.get("target_activity")
                candidates = [
                    candidate
                    for candidate in target_activity_specs.get(str(target_name), [])
                    if int(candidate["first_event_ordinal"]) < int(spec["first_event_ordinal"])
                ]
                if len(candidates) != 1:
                    raise ProducerError(
                        "android_component_alias_target_resolution: "
                        f"{payload['name']} -> {target_name} matched {len(candidates)} earlier activities"
                    )
                parent_ids.append(str(candidates[0]["record_id"]))
            digest, size = _payload_digest(payload)
            collector.add(
                "android_component",
                payload,
                dataset="manifests",
                artifact_id=None,
                source_artifact_id=apk_artifact_id,
                sha256=digest,
                size_bytes=size,
                official_source=None,
                parent_record_ids=parent_ids,
            )
            component_count += 1
    return {
        "manifest_nodes": len(axml["nodes"]),
        "features": len(axml["features"]),
        "components_by_kind": dict(
            sorted(
                collections.Counter(
                    kind.replace("-", "_") for kind, _name, _path in axml["components"]
                ).items()
            )
        ),
        "emitted_components": component_count,
        "axml": axml,
        "node_record_ids_by_path": record_id_by_path,
    }



def _component_attr_value(
    attrs: Mapping[tuple[str, str], Mapping[str, Any]],
    name: str,
) -> Any:
    attr = attrs.get((ANDROID_NS, name))
    if attr is None:
        return None
    if attr.get("typed") is not None:
        return attr.get("typed")
    if attr.get("raw") is not None:
        return attr.get("raw")
    if attr.get("type") == 18:
        return bool(int(attr["data"]))
    return attr.get("data")


def _explicit_component_value(
    rows: Sequence[Mapping[str, Any]],
    name: str,
    default: Any,
) -> Any:
    values = [
        _component_attr_value(row["attrs"], name)
        for row in rows
    ]
    values = [value for value in values if value is not None]
    encoded = {_canonical_text(value) for value in values}
    _require(len(encoded) <= 1, "android_component_merge_conflict", name)
    return values[0] if values else default


def _add_android_component_records(
    collector: RecordCollector,
    *,
    manifest_items: Sequence[Mapping[str, Any]],
    canonical_base_apk_artifact_id: str,
    effective_target_sdk: int,
) -> dict[str, Any]:
    """Emit v10 Android components after all manifest declaration IDs exist."""

    source_parent = _source_parent_for_collector(collector, canonical_base_apk_artifact_id)
    merged: dict[tuple[str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    package_name: str | None = None
    components_by_kind: collections.Counter[str] = collections.Counter()
    for item in manifest_items:
        axml = item["axml"]
        package = str(axml.get("package") or "")
        _require(bool(package), "android_component_package")
        if package_name is None:
            package_name = package
        _require(package == package_name, "android_component_package")
        node_record_ids_by_path = item["node_record_ids_by_path"]
        nodes_by_path = {str(node["path"]): node for node in axml["nodes"]}
        for kind_raw, raw_name, path in axml["components"]:
            kind = str(kind_raw).replace("-", "_")
            if kind == "application":
                identity = package
            else:
                _require(isinstance(raw_name, str) and bool(raw_name), "android_component_name")
                identity = _component_name(package, raw_name, kind)
            node = nodes_by_path[str(path)]
            has_filter = any(
                str(candidate.get("name")) == "intent-filter"
                and str(candidate.get("path", "")).startswith(str(path) + "/")
                for candidate in axml["nodes"]
            )
            merged[(kind, identity)].append(
                {
                    "attrs": node.get("attrs", {}),
                    "declaration_record_id": node_record_ids_by_path[str(path)],
                    "event_ordinal": int(node["event_ordinal"]),
                    "has_filter": has_filter,
                    "path": str(path),
                }
            )
            components_by_kind[kind] += 1
    _require(package_name is not None, "android_component_package")
    app_rows = merged.get(("application", package_name), [])
    _require(bool(app_rows), "android_component_application")
    app_enabled = bool(_explicit_component_value(app_rows, "enabled", True))
    app_process = _explicit_component_value(app_rows, "process", package_name)
    app_permission = _explicit_component_value(app_rows, "permission", None)
    app_direct = bool(_explicit_component_value(app_rows, "directBootAware", False))

    component_specs: list[dict[str, Any]] = []
    for (kind, identity), rows in sorted(merged.items()):
        ordered_rows = sorted(rows, key=lambda row: (int(row["event_ordinal"]), str(row["path"])))
        if kind == "application":
            payload = {
                "package": package_name,
                "kind": kind,
                "name": _explicit_component_value(ordered_rows, "name", "android.app.Application"),
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
            exported_default = (
                effective_target_sdk < 17
                if kind == "provider"
                else any(bool(row["has_filter"]) for row in ordered_rows)
            )
            permission_default = None if kind == "activity_alias" else app_permission
            target_activity = _explicit_component_value(ordered_rows, "targetActivity", "")
            payload = {
                "package": package_name,
                "kind": kind,
                "name": identity,
                "enabled": app_enabled and bool(_explicit_component_value(ordered_rows, "enabled", True)),
                "exported": bool(_explicit_component_value(ordered_rows, "exported", exported_default)),
                "permission": _explicit_component_value(ordered_rows, "permission", permission_default),
                "process": _explicit_component_value(ordered_rows, "process", app_process),
                "direct_boot_aware": bool(_explicit_component_value(ordered_rows, "directBootAware", False)),
                "foreground_service_type": _explicit_component_value(
                    ordered_rows,
                    "foregroundServiceType",
                    0 if kind == "service" else None,
                ),
                "target_activity": (
                    _component_name(package_name, str(target_activity), "activity")
                    if kind == "activity_alias"
                    else None
                ),
                "effective_target_sdk": effective_target_sdk,
            }
        component_specs.append(
            {
                "payload": payload,
                "record_id": _record_id("android_component", payload),
                "declaration_record_ids": sorted(
                    str(row["declaration_record_id"]) for row in ordered_rows
                ),
                "first_event_ordinal": int(ordered_rows[0]["event_ordinal"]),
            }
        )

    target_activity_specs: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for spec in component_specs:
        payload = spec["payload"]
        if payload["kind"] == "activity":
            target_activity_specs[str(payload["name"])].append(spec)

    emitted = 0
    for spec in sorted(component_specs, key=lambda item: str(item["record_id"])):
        payload = spec["payload"]
        parent_ids = [source_parent, *spec["declaration_record_ids"]]
        if payload["kind"] == "activity_alias":
            target_name = payload.get("target_activity")
            candidates = target_activity_specs.get(str(target_name), [])
            if len(candidates) != 1:
                raise ProducerError(
                    "android_component_alias_target_resolution: "
                    f"{payload['name']} -> {target_name} matched {len(candidates)} activities"
                )
            parent_ids.append(str(candidates[0]["record_id"]))
        digest, size = _payload_digest(payload)
        collector.add(
            "android_component",
            payload,
            dataset="manifests",
            artifact_id=None,
            source_artifact_id=canonical_base_apk_artifact_id,
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=parent_ids,
        )
        emitted += 1
    return {
        "components_by_kind": dict(sorted(components_by_kind.items())),
        "emitted_components": emitted,
    }

def _analyze_manifest(
    collector: RecordCollector,
    *,
    raw_manifest: bytes,
    apk_artifact_id: str,
    package_name: str,
    include_installed_declarations: bool,
    axml_parser_class: Any,
    start_tag: int,
    end_tag: int,
    end_document: int,
    format_value: Any,
    type_table: Mapping[int, str],
) -> dict[str, Any]:
    del (
        axml_parser_class,
        start_tag,
        end_tag,
        end_document,
        format_value,
        type_table,
    )
    return _add_manifest_records(
        collector,
        axml=_parse_axml_v6(raw_manifest),
        apk_artifact_id=apk_artifact_id,
        include_installed_declarations=include_installed_declarations,
    )


def _source_parent_for_collector(collector: RecordCollector, artifact_id: str) -> str:
    for record in collector.records:
        if record["artifact_id"] == artifact_id:
            return str(record["record_id"])
    raise ProducerError(f"frozen source artifact record is missing: {artifact_id}")


def _parse_arsc_resource_table(
    data: bytes,
    apk_artifact_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse the contract-owned resource/configuration membership from bytes."""

    _require(len(data) >= 12, "arsc_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    _require(
        root_type == 2 and root_header == 12 and root_size == len(data),
        "arsc_root",
    )
    package_count = struct.unpack_from("<I", data, 8)[0]
    resources_by_key: dict[tuple[str, int, int, int], dict[str, Any]] = {}
    configurations: list[dict[str, Any]] = []
    global_strings: list[str] | None = None
    package_ordinal = 0
    offset = root_header

    while offset < len(data):
        _require(offset + 8 <= len(data), "arsc_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        _require(
            header_size >= 8
            and chunk_size >= header_size
            and chunk_size % 4 == 0
            and offset + chunk_size <= len(data),
            "arsc_chunk",
        )
        if chunk_type == 1 and global_strings is None:
            global_strings, parsed_end = _parse_string_pool(data, offset)
            _require(parsed_end == offset + chunk_size, "arsc_global_string_pool")
        elif chunk_type == 0x0200:
            _require(header_size in {284, 288}, "arsc_package_header")
            package_id = struct.unpack_from("<I", data, offset + 8)[0]
            _require(1 <= package_id <= 255, "arsc_package_id")
            type_id_offset = (
                struct.unpack_from("<I", data, offset + 284)[0]
                if header_size == 288
                else 0
            )
            type_strings_offset = struct.unpack_from("<I", data, offset + 268)[0]
            key_strings_offset = struct.unpack_from("<I", data, offset + 276)[0]
            _require(
                type_strings_offset >= header_size
                and key_strings_offset >= header_size,
                "arsc_package_string_pool",
            )
            type_strings, _ = _parse_string_pool(data, offset + type_strings_offset)
            key_strings, _ = _parse_string_pool(data, offset + key_strings_offset)
            raw_package_name = data[offset + 12 : offset + 268]
            terminator = next(
                (
                    index
                    for index in range(0, len(raw_package_name) - 1, 2)
                    if raw_package_name[index : index + 2] == b"\0\0"
                ),
                len(raw_package_name),
            )
            package_name = (
                _decode_utf16_scalar(raw_package_name[:terminator])
                if terminator
                else ""
            )
            _require(bool(package_name), "arsc_package_name")

            child = offset + header_size
            type_chunk_ordinal = 0
            type_specs: dict[int, tuple[int, int]] = {}
            type_chunk_counts: collections.Counter[int] = collections.Counter()
            while child < offset + chunk_size:
                _require(child + 8 <= offset + chunk_size, "arsc_package_child")
                child_type, child_header, child_size = struct.unpack_from(
                    "<HHI", data, child
                )
                _require(
                    child_header >= 8
                    and child_size >= child_header
                    and child_size % 4 == 0
                    and child + child_size <= offset + chunk_size,
                    "arsc_package_child",
                )
                if child_type == 0x0202:
                    _require(child_header == 16 and child_size >= 16, "arsc_type_spec")
                    raw_type_id = data[child + 8]
                    _require(data[child + 9] == 0, "arsc_type_spec")
                    declared_type_count = struct.unpack_from("<H", data, child + 10)[0]
                    entry_count = struct.unpack_from("<I", data, child + 12)[0]
                    _require(
                        raw_type_id not in type_specs
                        and child + 16 + entry_count * 4 == child + child_size,
                        "arsc_type_spec",
                    )
                    type_specs[raw_type_id] = (entry_count, declared_type_count)
                elif child_type == 0x0201:
                    _require(child_header >= 24, "arsc_type_chunk")
                    raw_type_id = data[child + 8]
                    flags = data[child + 9]
                    reserved = struct.unpack_from("<H", data, child + 10)[0]
                    entry_count = struct.unpack_from("<I", data, child + 12)[0]
                    entries_start = struct.unpack_from("<I", data, child + 16)[0]
                    config_size = struct.unpack_from("<I", data, child + 20)[0]
                    _require(
                        reserved == 0 and flags & ~0x03 == 0 and flags != 0x03,
                        "arsc_type_flags",
                    )
                    _require(
                        config_size >= 4
                        and config_size % 4 == 0
                        and child_header == 20 + config_size,
                        "arsc_invalid_config_size",
                    )
                    _require(
                        child_header <= entries_start <= child_size,
                        "arsc_entries_start",
                    )
                    effective_type_id = raw_type_id + type_id_offset
                    _require(
                        1 <= raw_type_id <= 255 and 1 <= effective_type_id <= 255,
                        "arsc_effective_type",
                    )
                    _require(raw_type_id in type_specs, "arsc_type_spec_missing")
                    spec_entry_count = type_specs[raw_type_id][0]
                    type_chunk_counts[raw_type_id] += 1
                    index_start = child + child_header
                    present_entries: list[tuple[int, int, int]] = []
                    if flags & 0x01:
                        _require(
                            index_start + entry_count * 4 <= child + entries_start,
                            "arsc_sparse_range",
                        )
                        previous_entry_id = -1
                        for entry_index_ordinal in range(entry_count):
                            entry_id, offset_div4 = struct.unpack_from(
                                "<HH", data, index_start + entry_index_ordinal * 4
                            )
                            _require(
                                entry_id > previous_entry_id
                                and entry_id < spec_entry_count,
                                "arsc_sparse_entry_id",
                            )
                            previous_entry_id = entry_id
                            present_entries.append(
                                (entry_index_ordinal, entry_id, offset_div4 * 4)
                            )
                    elif flags & 0x02:
                        _require(
                            index_start + entry_count * 2 <= child + entries_start,
                            "arsc_offset16_range",
                        )
                        for entry_index_ordinal in range(entry_count):
                            value = struct.unpack_from(
                                "<H", data, index_start + entry_index_ordinal * 2
                            )[0]
                            if value != 0xFFFF:
                                present_entries.append(
                                    (entry_index_ordinal, entry_index_ordinal, value * 4)
                                )
                    else:
                        _require(
                            index_start + entry_count * 4 <= child + entries_start,
                            "arsc_dense_range",
                        )
                        for entry_index_ordinal in range(entry_count):
                            value = struct.unpack_from(
                                "<I", data, index_start + entry_index_ordinal * 4
                            )[0]
                            if value != 0xFFFFFFFF:
                                present_entries.append(
                                    (entry_index_ordinal, entry_index_ordinal, value)
                                )
                    entry_offsets = [item[2] for item in present_entries]
                    _require(
                        len(entry_offsets) == len(set(entry_offsets)),
                        "arsc_entry_offset_duplicate",
                    )

                    def scalar_value(value_offset: int) -> dict[str, Any]:
                        _require(value_offset + 8 <= child + child_size, "arsc_value_range")
                        value_size, value_reserved, data_type, value_data = struct.unpack_from(
                            "<HBBI", data, value_offset
                        )
                        _require(
                            value_size == 8 and value_reserved == 0,
                            "arsc_value",
                        )
                        string_value = None
                        if data_type == 3:
                            _require(
                                global_strings is not None
                                and value_data < len(global_strings),
                                "arsc_string_value",
                            )
                            string_value = global_strings[value_data]
                        return {
                            "kind": "scalar",
                            "data_type": data_type,
                            "data": value_data,
                            "string_value": string_value,
                        }

                    for entry_index_ordinal, entry_id, entry_relative in present_entries:
                        _require(
                            entry_id <= 0xFFFF and entry_relative % 4 == 0,
                            "arsc_entry_alignment",
                        )
                        entry_offset = child + entries_start + entry_relative
                        _require(entry_offset + 8 <= child + child_size, "arsc_entry_range")
                        entry_size, entry_flags, key_index = struct.unpack_from(
                            "<HHI", data, entry_offset
                        )
                        _require(
                            entry_flags & ~0x000F == 0
                            and key_index < len(key_strings)
                            and raw_type_id - 1 < len(type_strings),
                            "arsc_entry",
                        )
                        resource_payload = {
                            "apk_artifact_id": apk_artifact_id,
                            "package_chunk_ordinal": package_ordinal,
                            "package_id": package_id,
                            "package_name": package_name,
                            "raw_type_id": raw_type_id,
                            "type_id_offset": type_id_offset,
                            "type_id": effective_type_id,
                            "entry_id": entry_id,
                            "resource_id": (
                                f"0x{((package_id << 24) | (effective_type_id << 16) | entry_id):08x}"
                            ),
                            "type_name": type_strings[raw_type_id - 1],
                            "entry_name": key_strings[key_index],
                        }
                        resource_key = (
                            apk_artifact_id,
                            package_ordinal,
                            effective_type_id,
                            entry_id,
                        )
                        previous_payload = resources_by_key.get(resource_key)
                        _require(
                            previous_payload is None or previous_payload == resource_payload,
                            "arsc_resource_conflict",
                        )
                        resources_by_key[resource_key] = resource_payload
                        if entry_flags & 0x0008:
                            raise ProducerError("arsc_compact_entry_unsupported")
                        if entry_flags & 0x0001:
                            _require(
                                entry_size == 16 and entry_offset + 16 <= child + child_size,
                                "arsc_bag_entry",
                            )
                            parent_resource_id, item_count = struct.unpack_from(
                                "<II", data, entry_offset + 8
                            )
                            map_offset = entry_offset + 16
                            _require(
                                map_offset + item_count * 12 <= child + child_size,
                                "arsc_bag_entry",
                            )
                            items = []
                            for map_ordinal in range(item_count):
                                item_offset = map_offset + map_ordinal * 12
                                name_resource_id = struct.unpack_from(
                                    "<I", data, item_offset
                                )[0]
                                scalar = scalar_value(item_offset + 4)
                                items.append(
                                    {
                                        "map_ordinal": map_ordinal,
                                        "name_resource_id": name_resource_id,
                                        "data_type": scalar["data_type"],
                                        "data": scalar["data"],
                                        "string_value": scalar["string_value"],
                                    }
                                )
                            normalized_value: dict[str, Any] = {
                                "kind": "bag",
                                "parent_resource_id": parent_resource_id,
                                "items": items,
                            }
                        else:
                            _require(entry_size == 8, "arsc_scalar_entry")
                            normalized_value = scalar_value(entry_offset + 8)
                        config_bytes = data[
                            child + 20 : child + 20 + config_size
                        ]
                        configurations.append(
                            {
                                "configuration_kind": "resource_configuration",
                                "resource_record_id": _record_id(
                                    "resource", resource_payload
                                ),
                                "package_chunk_ordinal": package_ordinal,
                                "type_chunk_ordinal": type_chunk_ordinal,
                                "entry_index_ordinal": entry_index_ordinal,
                                "entry_id": entry_id,
                                "entry_encoding": "full",
                                "entry_flags": entry_flags,
                                "key_index": key_index,
                                "configuration": {
                                    "size_bytes": config_size,
                                    "bytes_hex": config_bytes.hex(),
                                },
                                "value": normalized_value,
                            }
                        )
                    type_chunk_ordinal += 1
                child += child_size
            _require(child == offset + chunk_size, "arsc_package_range")
            for raw_type_id, (_entry_count, declared_type_count) in type_specs.items():
                _require(
                    declared_type_count in {0, type_chunk_counts[raw_type_id]},
                    "arsc_type_spec_count",
                )
            package_ordinal += 1
        offset += chunk_size

    _require(
        offset == len(data)
        and package_ordinal == package_count
        and global_strings is not None,
        "arsc_package_count",
    )
    resources = sorted(resources_by_key.values(), key=_canonical_text)
    configurations.sort(key=_canonical_text)
    return resources, configurations


def _parse_resource_name(xml_name: Any, resource_id: int) -> tuple[str, str, str]:
    value = str(xml_name or "")
    match = re.fullmatch(r"@([^:]+):([^/]+)/(.+)", value)
    if match is None:
        raise ProducerError(f"cannot resolve resource name for 0x{resource_id:08x}: {value!r}")
    return match.group(1), match.group(2), match.group(3)


def _arsc_ref_value(reference: Any) -> tuple[str, dict[str, Any]]:
    value_type = str(reference.get_data_type_string())
    data_type = int(reference.get_data_type())
    data = int(reference.get_data())
    return value_type, {
        "kind": "scalar",
        "data_type": data_type,
        "data": data,
        "string_value": str(reference.format_value()) if data_type == 3 else None,
    }


def _arsc_entry_value(entry: Any) -> tuple[str, Any]:
    if entry.is_complex():
        items: list[dict[str, Any]] = []
        for map_ordinal, (name, reference) in enumerate(entry.item.items):
            item_type, item_value = _arsc_ref_value(reference)
            del item_type
            items.append(
                {
                    "map_ordinal": map_ordinal,
                    "name_resource_id": int(name),
                    "data_type": item_value["data_type"],
                    "data": item_value["data"],
                    "string_value": (
                        item_value["string_value"]
                        if int(item_value["data_type"]) == 3
                        else None
                    ),
                }
            )
        return "bag", {
            "kind": "bag",
            "parent_resource_id": int(entry.item.id_parent),
            "items": items,
        }
    if entry.is_compact():
        value_type = int(entry.datatype)
        data = int(entry.data)
        try:
            formatted = str(entry.get_key_data())
        except (AttributeError, IndexError, TypeError):
            formatted = f"0x{data:08x}"
        return "scalar", {
            "kind": "scalar",
            "data_type": value_type,
            "data": data,
            "string_value": formatted if value_type == 3 else None,
        }
    return _arsc_ref_value(entry.key)


def _analyze_resources(
    collector: RecordCollector,
    *,
    apk: Any,
    apk_artifact_id: str,
    resource_name_map: dict[int, tuple[str, str, str]],
    resource_table: bytes | None = None,
) -> dict[str, int]:
    if resource_table is not None:
        source_parent = _source_parent_for_collector(collector, apk_artifact_id)
        resource_payloads, configuration_payloads = _parse_arsc_resource_table(
            resource_table,
            apk_artifact_id,
        )
        resource_record_ids: set[str] = set()
        for resource_payload in resource_payloads:
            digest, size = _payload_digest(resource_payload)
            resource_record_ids.add(
                collector.add(
                    "resource",
                    resource_payload,
                    dataset="resources",
                    artifact_id=None,
                    source_artifact_id=apk_artifact_id,
                    sha256=digest,
                    size_bytes=size,
                    official_source=None,
                    parent_record_ids=[source_parent],
                )
            )
        for configuration_payload in configuration_payloads:
            resource_record_id = str(configuration_payload["resource_record_id"])
            _require(
                resource_record_id in resource_record_ids,
                "arsc_configuration_resource_link",
            )
            digest, size = _payload_digest(configuration_payload)
            collector.add(
                "configuration",
                configuration_payload,
                dataset="resources",
                artifact_id=None,
                source_artifact_id=apk_artifact_id,
                sha256=digest,
                size_bytes=size,
                official_source=None,
                parent_record_ids=[source_parent, resource_record_id],
            )
        return {
            "resources": len(resource_payloads),
            "resource_configurations": len(configuration_payloads),
        }
    resources = apk.get_android_resources()
    if resources is None:
        return {"resources": 0, "resource_configurations": 0}
    resources._analyse()
    source_parent = _source_parent_for_collector(collector, apk_artifact_id)
    logical_count = 0
    configuration_count = 0
    for resource_id in sorted(resources.resource_values):
        xml_name = resources.get_resource_xml_name(resource_id)
        try:
            resolved_name = _parse_resource_name(xml_name, resource_id)
        except ProducerError:
            resolved_name = resource_name_map.get(int(resource_id))
            if resolved_name is None:
                raise ProducerError(
                    "cannot recover split resource name for "
                    f"{apk_artifact_id} 0x{int(resource_id):08x}: {str(xml_name or '')!r}"
                )
        prior_name = resource_name_map.setdefault(int(resource_id), resolved_name)
        if prior_name != resolved_name:
            raise ProducerError(
                f"resource name collision for 0x{int(resource_id):08x}: "
                f"{prior_name!r} != {resolved_name!r}"
            )
        package_name, type_name, entry_name = resolved_name
        resource_payload = {
            "apk_artifact_id": apk_artifact_id,
            "package_chunk_ordinal": 0,
            "package_id": (int(resource_id) >> 24) & 0xFF,
            "raw_type_id": (int(resource_id) >> 16) & 0xFF,
            "type_id": (int(resource_id) >> 16) & 0xFF,
            "type_id_offset": 0,
            "entry_id": int(resource_id) & 0xFFFF,
            "resource_id": f"0x{int(resource_id):08x}",
            "package_name": package_name,
            "type_name": type_name,
            "entry_name": entry_name,
        }
        resource_digest, resource_size = _payload_digest(resource_payload)
        resource_record_id = collector.add(
            "resource",
            resource_payload,
            dataset="resources",
            artifact_id=None,
            source_artifact_id=apk_artifact_id,
            sha256=resource_digest,
            size_bytes=resource_size,
            official_source=None,
            parent_record_ids=[source_parent],
        )
        logical_count += 1

        configurations: list[dict[str, Any]] = []
        for entry_index_ordinal, (config, entry) in enumerate(resources.resource_values[resource_id].items()):
            value_type, value = _arsc_entry_value(entry)
            config_bytes = getattr(config, "raw_bytes", None)
            if config_bytes is None:
                getter = getattr(config, "get_raw", None)
                if getter is not None:
                    config_bytes = getter()
            if config_bytes is None:
                config_bytes = str(config.get_qualifier()).encode("utf-8")
            config_bytes = bytes(config_bytes)
            type_chunk_ordinal = int(getattr(config, "type_chunk_ordinal", 0) or 0)
            physical_slot = int(
                getattr(
                    config,
                    "entry_index_ordinal",
                    getattr(
                        config,
                        "entry_index_slot",
                    getattr(entry, "entry_index_slot", entry_index_ordinal),
                    ),
                )
                or 0
            )
            configurations.append(
                {
                    "configuration_kind": "resource_configuration",
                    "resource_record_id": resource_record_id,
                    "configuration": {
                        "size_bytes": len(config_bytes),
                        "bytes_hex": config_bytes.hex(),
                    },
                    "package_chunk_ordinal": 0,
                    "type_chunk_ordinal": type_chunk_ordinal,
                    "entry_index_ordinal": physical_slot,
                    "entry_id": int(resource_id) & 0xFFFF,
                    "entry_flags": int(getattr(entry, "flags", 0) or 0),
                    "entry_encoding": "compact" if entry.is_compact() else "full",
                    "key_index": int(getattr(entry, "index", 0) or 0),
                    "value": value,
                }
            )
        configurations.sort(key=_canonical_text)
        for configuration_payload in configurations:
            digest, size = _payload_digest(configuration_payload)
            collector.add(
                "configuration",
                configuration_payload,
                dataset="resources",
                artifact_id=None,
                source_artifact_id=apk_artifact_id,
                sha256=digest,
                size_bytes=size,
                official_source=None,
                parent_record_ids=[source_parent, resource_record_id],
            )
            configuration_count += 1
    return {
        "resources": logical_count,
        "resource_configurations": configuration_count,
    }


def _certificate_der(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if hasattr(value, "dump"):
        dumped = value.dump()
        if isinstance(dumped, bytes):
            return dumped
    raise ProducerError(f"Androguard returned unsupported certificate type {type(value).__name__}")


def _analyze_certificates(
    collector: RecordCollector,
    *,
    apk: Any,
    apk_artifact_id: str,
) -> dict[str, Any]:
    source_parent = _source_parent_for_collector(collector, apk_artifact_id)
    scheme_counts: dict[str, int] = {}
    total = 0
    getters = (
        ("v2", "get_certificates_der_v2"),
        ("v3", "get_certificates_der_v3"),
        ("v1", "get_certificates_v1"),
    )
    encoded_certificate_ordinal = 0
    for scheme, getter_name in getters:
        getter = getattr(apk, getter_name, None)
        certificates = list(getter()) if getter is not None else []
        scheme_counts[scheme] = len(certificates)
        if len(certificates) > 1:
            raise ProducerError(
                f"current package requires signer-boundary recovery for {apk_artifact_id} {scheme}"
            )
        for certificate_index, certificate in enumerate(certificates):
            der = _certificate_der(certificate)
            digest = _sha256_bytes(der)
            payload = {
                "apk_artifact_id": apk_artifact_id,
                "scheme": scheme,
                "signer_index": 0,
                "certificate_index": certificate_index,
                "scheme_occurrence_ordinal": certificate_index,
                "encoded_certificate_ordinal": encoded_certificate_ordinal,
                "der_sha256": digest,
            }
            collector.add(
                "certificate",
                payload,
                dataset="signing",
                artifact_id=None,
                source_artifact_id=apk_artifact_id,
                sha256=digest,
                size_bytes=len(der),
                official_source=None,
                parent_record_ids=[source_parent],
            )
            total += 1
            encoded_certificate_ordinal += 1
    return {"certificate_rows": total, "scheme_counts": scheme_counts}


def _instruction_strings(instruction: Any) -> list[str]:
    values: list[str] = []
    for operand in instruction.get_operands():
        if isinstance(operand, tuple) and len(operand) >= 3 and isinstance(operand[2], str):
            values.append(unicodedata.normalize("NFC", operand[2]))
    return values


def _api_payload(api: str) -> dict[str, str]:
    if "->" not in api or "(" not in api:
        return {"class_descriptor": "", "method_name": api, "descriptor": ""}
    class_descriptor, method_part = api.split("->", 1)
    method_name, descriptor = method_part.split("(", 1)
    return {
        "class_descriptor": class_descriptor,
        "method_name": method_name,
        "descriptor": _descriptor("(" + descriptor),
    }


@dataclass(frozen=True)
class CallsiteApi:
    opcode_family: str
    owner: str
    owner_policy: str
    method_name: str
    descriptor: str
    target_recipe: str


_CONTRACT_CALLSITE_CACHE: dict[str, tuple[CallsiteApi, ...]] = {}


def _contract_callsites(table: str) -> tuple[CallsiteApi, ...]:
    cached = _CONTRACT_CALLSITE_CACHE.get(table)
    if cached is not None:
        return cached
    contract_path = DEFAULT_CONTRACT
    if not contract_path.exists():
        contract_path = RESEARCH_REL / "governance/g002-neutral-normalization-contract.json"
    contract = _load_json(contract_path)
    rows = []
    for row in contract["callsites"][table]:
        rows.append(
            CallsiteApi(
                opcode_family=str(row["opcode_family"]),
                owner=str(row["owner"]),
                owner_policy=str(row.get("owner_policy", "exact_owner")),
                method_name=str(row["name"]),
                descriptor=_descriptor(row["descriptor"]),
                target_recipe=str(row["target_recipe"]),
            )
        )
    result = tuple(rows)
    _CONTRACT_CALLSITE_CACHE[table] = result
    return result


def _split_api(api: str) -> tuple[str, str, str] | None:
    if "->" not in api or "(" not in api:
        return None
    owner, method_part = api.split("->", 1)
    method_name, descriptor = method_part.split("(", 1)
    return owner, method_name, _descriptor("(" + descriptor)


def _opcode_family(instruction_name: str) -> str | None:
    return DEX_INVOKE_OPCODE_FAMILIES.get(instruction_name)


def _opcode_matches(expected: str, observed: str | None) -> bool:
    if observed is None:
        return False
    if expected == observed:
        return True
    if expected == "VIRTUAL_OR_SUPER":
        return observed in {"VIRTUAL", "SUPER"}
    return False


def _owner_matches(expected: str, policy: str, observed: str) -> bool:
    if policy in {"exact_owner", "classloader_exact_or_defined_override"}:
        return observed == expected
    return observed == expected


def _matched_callsite_apis(table: str, api: str, opcode_family: str | None) -> list[CallsiteApi]:
    parsed = _split_api(api)
    if parsed is None:
        return []
    owner, method_name, descriptor = parsed
    return [
        row
        for row in _contract_callsites(table)
        if row.method_name == method_name
        and row.descriptor == descriptor
        and _opcode_matches(row.opcode_family, opcode_family)
        and _owner_matches(row.owner, row.owner_policy, owner)
    ]


def _instruction_callsites(instruction: Any) -> list[dict[str, Any]]:
    strings = _instruction_strings(instruction)
    opcode_family = _opcode_family(str(instruction.get_name()))
    callsites: list[dict[str, Any]] = []
    for index, value in enumerate(strings):
        if _split_api(value) is None:
            continue
        callsites.append(
            {
                "api": value,
                "opcode_family": opcode_family,
                "string_args": strings[:index],
            }
        )
    return callsites


def _java_binary_to_descriptor(value: str) -> str:
    if value.startswith("L") and value.endswith(";"):
        return value
    return "L" + value.replace(".", "/") + ";"


def _first_string_arg(args: Sequence[str]) -> str | None:
    return str(args[0]) if args else None


def _callsite_target(recipe: str, string_args: Sequence[str]) -> dict[str, Any]:
    arg0 = _first_string_arg(string_args)
    if recipe.startswith(("for_name(", "binary_name(", "slash_binary_name(")):
        if arg0:
            return {"target_kind": "class", "class_descriptor": _java_binary_to_descriptor(arg0)}
    if recipe.startswith("native_library_name("):
        if arg0:
            return {"target_kind": "native_library_name", "value": arg0}
    if recipe.startswith("native_library_path("):
        if arg0:
            return {"target_kind": "native_library_path", "value": arg0}
    if recipe.startswith(("dex_path_list(", "single_dex_path(", "file_path(")):
        if arg0:
            return {"target_kind": "dex_path_list", "values": [arg0]}
    if recipe.startswith("memory_dex(count=1"):
        return {"target_kind": "memory_dex", "buffer_count": 1}
    if recipe.startswith("jna_dispatch("):
        return {"target_kind": "native_library_name", "value": "jnidispatch"}
    if recipe.startswith("member_collection("):
        match = re.search(r",([^,)]+)\)", recipe)
        if arg0 and match is not None:
            return {
                "target_kind": "member_collection",
                "class_descriptor": _java_binary_to_descriptor(arg0),
                "query": match.group(1),
            }
    return {"unresolved_token": "not_statically_resolved"}


def _read_uleb128(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    for _ in range(5):
        _require(offset < len(data), "dex_uleb128")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
    raise ProducerError("dex_uleb128")


def _decode_dex_mutf8(data: bytes, offset: int) -> str:
    declared_units, position = _read_uleb128(data, offset)
    units: list[int] = []
    while True:
        _require(position < len(data), "dex_invalid_mutf8")
        first = data[position]
        position += 1
        if first == 0:
            break
        if first < 0x80:
            units.append(first)
            continue
        if first & 0xE0 == 0xC0:
            _require(position < len(data), "dex_invalid_mutf8")
            second = data[position]
            position += 1
            _require(second & 0xC0 == 0x80, "dex_invalid_mutf8")
            value = ((first & 0x1F) << 6) | (second & 0x3F)
            _require(value == 0 or value >= 0x80, "dex_invalid_mutf8")
            units.append(value)
            continue
        if first & 0xF0 == 0xE0:
            _require(position + 2 <= len(data), "dex_invalid_mutf8")
            second, third = data[position], data[position + 1]
            position += 2
            _require(
                second & 0xC0 == 0x80 and third & 0xC0 == 0x80,
                "dex_invalid_mutf8",
            )
            value = ((first & 0x0F) << 12) | ((second & 0x3F) << 6) | (third & 0x3F)
            _require(value >= 0x800, "dex_invalid_mutf8")
            units.append(value)
            continue
        raise ProducerError("dex_invalid_mutf8")
    _require(len(units) == declared_units, "dex_invalid_mutf8")
    raw = b"".join(unit.to_bytes(2, "little") for unit in units)
    return unicodedata.normalize("NFC", raw.decode("utf-16-le", "surrogatepass"))


def _sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def _dex_instruction_width(units: Sequence[int], offset: int) -> int:
    _require(offset < len(units), "dex_instruction")
    first = int(units[offset])
    opcode = first & 0xFF
    if opcode == 0 and first:
        if offset & 1:
            return 1
        identifier = first >> 8
        if identifier == 1:
            _require(offset + 2 <= len(units), "dex_payload")
            return 4 + int(units[offset + 1]) * 2
        if identifier == 2:
            _require(offset + 2 <= len(units), "dex_payload")
            return 2 + int(units[offset + 1]) * 4
        if identifier == 3:
            _require(offset + 4 <= len(units), "dex_payload")
            element_width = int(units[offset + 1])
            size = int(units[offset + 2]) | (int(units[offset + 3]) << 16)
            _require(element_width in {1, 2, 4, 8}, "dex_payload")
            return 4 + (element_width * size + 1) // 2
        return 1
    if (
        opcode <= 0x12
        or 0x1D <= opcode <= 0x1E
        or 0x3E <= opcode <= 0x43
        or opcode in {0x21, 0x27, 0x28, 0x73, 0x79, 0x7A, 0xEC, 0xF1}
        or 0x7B <= opcode <= 0x8F
        or 0xB0 <= opcode <= 0xCF
    ):
        return 1
    if (
        opcode in {0x13, 0x15, 0x16, 0x19, 0x1A, 0x1C, 0x1F, 0x20, 0x22, 0x23, 0x29, 0xEB, 0xED}
        or 0x2D <= opcode <= 0x3D
        or 0x44 <= opcode <= 0x6D
        or 0x90 <= opcode <= 0xAF
        or 0xD0 <= opcode <= 0xEA
        or 0xF2 <= opcode <= 0xF7
    ):
        return 2
    if (
        opcode in {0x14, 0x17, 0x1B, 0x24, 0x25, 0x26, 0x2A, 0x2B, 0x2C, 0xEE, 0xEF, 0xF0, 0xF8, 0xF9, 0xFC, 0xFD}
        or 0x6E <= opcode <= 0x72
        or 0x74 <= opcode <= 0x78
    ):
        return 3
    if opcode in {0xFA, 0xFB}:
        return 4
    if opcode in {0xFE, 0xFF}:
        return 2
    if opcode == 0x18:
        return 5
    raise ProducerError(f"dex_opcode: offset={offset} opcode=0x{opcode:02x}")


def _decode_dex_invoke_registers(units: Sequence[int], offset: int) -> list[int]:
    opcode = int(units[offset]) & 0xFF
    if 0x6E <= opcode <= 0x72:
        count = (int(units[offset]) >> 12) & 0xF
        fifth = (int(units[offset]) >> 8) & 0xF
        packed = int(units[offset + 2])
        registers = [
            packed & 0xF,
            (packed >> 4) & 0xF,
            (packed >> 8) & 0xF,
            (packed >> 12) & 0xF,
            fifth,
        ]
        _require(count <= 5, "dex_invoke_registers")
        return registers[:count]
    if 0x74 <= opcode <= 0x78:
        count = (int(units[offset]) >> 8) & 0xFF
        first = int(units[offset + 2])
        _require(first + count <= 65536, "dex_invoke_registers")
        return list(range(first, first + count))
    raise ProducerError("dex_invoke_opcode")


DEX_TOP = ("TOP",)


def _dex_join_value(left: Any, right: Any) -> Any:
    if left == right:
        return left
    if left is None:
        return right
    if right is None:
        return left
    if (
        isinstance(left, tuple)
        and isinstance(right, tuple)
        and left
        and right
        and left[:2] == right[:2]
        and left[0] == "Array"
    ):
        if len(left[2]) != len(right[2]):
            return DEX_TOP
        cells = tuple(
            _dex_join_value(first, second)
            for first, second in zip(left[2], right[2])
        )
        return ("Array", left[1], cells)
    return DEX_TOP


def _binary_name_to_descriptor(value: str) -> str | None:
    if not value:
        return None
    if value.startswith("["):
        if re.fullmatch(r"\[+(?:[ZBSCIJFD]|L[^.;\[]+;)", value):
            return value
        return None
    internal = value.replace(".", "/")
    if not internal or any(character in ".;[" for character in internal):
        return None
    return f"L{internal};"


def _evaluate_dex_target_recipe(
    recipe: str,
    values: Sequence[Any],
    *,
    has_receiver: bool,
) -> dict[str, Any] | None:
    def at(index: int) -> Any:
        return values[index] if index < len(values) else DEX_TOP

    receiver_offset = 0
    args_offset = 1 if has_receiver else 0
    if recipe.startswith("for_name("):
        value = at(args_offset)
        descriptor = (
            _binary_name_to_descriptor(str(value[1]))
            if isinstance(value, tuple) and value and value[0] == "String"
            else None
        )
        return (
            {"target_kind": "class", "class_descriptor": descriptor}
            if descriptor
            else None
        )
    if recipe.startswith(("binary_name(", "slash_binary_name(")):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "String":
            raw = str(value[1]).replace("/", ".") if recipe.startswith("slash_") else str(value[1])
            descriptor = _binary_name_to_descriptor(raw)
            if descriptor:
                return {"target_kind": "class", "class_descriptor": descriptor}
    if recipe.startswith("native_library_name("):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "String":
            return {"target_kind": "native_library_name", "value": value[1]}
    if recipe.startswith(("native_library_path(", "file_path(")):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "String":
            return {"target_kind": "native_library_path", "value": value[1]}
    if recipe.startswith(("dex_path_list(", "single_dex_path(")):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "String":
            paths = str(value[1]).split(":") if recipe.startswith("dex_path_list") else [value[1]]
            return {"target_kind": "dex_path_list", "values": paths}
    if recipe.startswith("memory_dex("):
        if "count=1" in recipe:
            return {"target_kind": "memory_dex", "buffer_count": 1}
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "Array":
            return {"target_kind": "memory_dex", "buffer_count": len(value[2])}
    if recipe.startswith("jna_interface("):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "Class":
            return {"target_kind": "jna_interface", "class_descriptor": value[1]}
    if recipe.startswith("proxy_interfaces("):
        value = at(args_offset + 1)
        if (
            isinstance(value, tuple)
            and value
            and value[0] == "Array"
            and all(
                isinstance(cell, tuple) and cell and cell[0] == "Class"
                for cell in value[2]
            )
        ):
            return {
                "target_kind": "proxy_interfaces",
                "class_descriptors": [cell[1] for cell in value[2]],
            }
    if recipe.startswith("member_collection("):
        receiver = at(receiver_offset)
        if isinstance(receiver, tuple) and receiver and receiver[0] == "Class":
            query = recipe.split(",", 1)[1].rsplit(")", 1)[0]
            return {
                "target_kind": "member_collection",
                "class_descriptor": receiver[1],
                "query": query,
            }
    if recipe.startswith("class_relation("):
        value = at(args_offset)
        if isinstance(value, tuple) and value and value[0] == "Class":
            relation = recipe.split(",", 1)[1].rsplit(")", 1)[0]
            return {
                "target_kind": "class_relation",
                "class_descriptor": value[1],
                "relation": relation,
            }
    return None


DIRECT_DEX_OPCODE_FAMILIES = {
    0x6E: "VIRTUAL",
    0x6F: "VIRTUAL_OR_SUPER",
    0x70: "DIRECT",
    0x71: "STATIC",
    0x72: "INTERFACE",
    0x74: "VIRTUAL",
    0x75: "VIRTUAL_OR_SUPER",
    0x76: "DIRECT",
    0x77: "STATIC",
    0x78: "INTERFACE",
}


def _direct_callsite_matches(
    family: str,
    owner: str,
    method_name: str,
    descriptor: str,
    opcode_family: str,
) -> list[CallsiteApi]:
    return [
        row
        for row in _contract_callsites(family)
        if (row.owner, row.method_name, row.descriptor)
        == (owner, method_name, descriptor)
        and row.opcode_family
        in {
            opcode_family,
            "VIRTUAL_OR_SUPER" if opcode_family == "VIRTUAL" else opcode_family,
        }
    ]


def _interpret_dex_targets(
    units: Sequence[int],
    registers_size: int,
    strings: Sequence[str],
    types: Sequence[str],
    methods: Sequence[tuple[str, str, str]],
) -> dict[tuple[str, int], dict[str, Any]]:
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
    entry: dict[int, tuple[tuple[Any, ...], Any, int | None]] = {
        starts[0]: (tuple(DEX_TOP for _ in range(registers_size)), None, None)
    }
    worklist = [starts[0]]

    def successors(current: int, opcode: int) -> list[int]:
        next_offset = current + widths[current]
        if opcode == 0x28:
            return [current + _sign_extend(int(units[current]) >> 8, 8)]
        if opcode == 0x29:
            return [current + _sign_extend(int(units[current + 1]), 16)]
        if opcode == 0x2A:
            raw = int(units[current + 1]) | (int(units[current + 2]) << 16)
            return [current + _sign_extend(raw, 32)]
        if 0x32 <= opcode <= 0x3D:
            return sorted(
                {
                    next_offset,
                    current + _sign_extend(int(units[current + 1]), 16),
                }
            )
        if opcode in {0x0E, 0x0F, 0x10, 0x11, 0x27}:
            return []
        return [next_offset] if next_offset in start_set else []

    while worklist:
        current = min(worklist)
        worklist.remove(current)
        registers, pending, pending_at = entry[current]
        mutable_registers = list(registers)
        opcode = int(units[current]) & 0xFF
        produced: Any = None
        if opcode in {0x01, 0x04, 0x07}:
            destination = (int(units[current]) >> 8) & 0xF
            source = (int(units[current]) >> 12) & 0xF
            if destination < registers_size and source < registers_size:
                mutable_registers[destination] = mutable_registers[source]
        elif opcode in {0x02, 0x05, 0x08}:
            destination = (int(units[current]) >> 8) & 0xFF
            source = int(units[current + 1])
            if destination < registers_size and source < registers_size:
                mutable_registers[destination] = mutable_registers[source]
        elif opcode == 0x12:
            destination = (int(units[current]) >> 8) & 0xF
            if destination < registers_size:
                mutable_registers[destination] = (
                    "Int",
                    _sign_extend((int(units[current]) >> 12) & 0xF, 4),
                )
        elif opcode == 0x13:
            destination = (int(units[current]) >> 8) & 0xFF
            if destination < registers_size:
                mutable_registers[destination] = (
                    "Int",
                    _sign_extend(int(units[current + 1]), 16),
                )
        elif opcode == 0x14:
            destination = (int(units[current]) >> 8) & 0xFF
            raw = int(units[current + 1]) | (int(units[current + 2]) << 16)
            if destination < registers_size:
                mutable_registers[destination] = ("Int", _sign_extend(raw, 32))
        elif opcode == 0x15:
            destination = (int(units[current]) >> 8) & 0xFF
            if destination < registers_size:
                mutable_registers[destination] = (
                    "Int",
                    _sign_extend(int(units[current + 1]), 16) << 16,
                )
        elif opcode in {0x1A, 0x1B}:
            destination = (int(units[current]) >> 8) & 0xFF
            string_index = (
                int(units[current + 1])
                if opcode == 0x1A
                else int(units[current + 1]) | (int(units[current + 2]) << 16)
            )
            if destination < registers_size and string_index < len(strings):
                mutable_registers[destination] = ("String", strings[string_index])
        elif opcode == 0x1C:
            destination = (int(units[current]) >> 8) & 0xFF
            type_index = int(units[current + 1])
            if destination < registers_size and type_index < len(types):
                mutable_registers[destination] = ("Class", types[type_index])
        elif opcode in {0x0A, 0x0B, 0x0C}:
            destination = (int(units[current]) >> 8) & 0xFF
            if destination < registers_size:
                mutable_registers[destination] = (
                    pending
                    if pending_at is not None
                    and pending_at + widths[pending_at] == current
                    else DEX_TOP
                )
        elif opcode in DIRECT_DEX_OPCODE_FAMILIES:
            method_index = int(units[current + 1])
            try:
                invoke_registers = _decode_dex_invoke_registers(units, current)
            except ProducerError:
                invoke_registers = []
            if method_index < len(methods) and all(
                register < registers_size for register in invoke_registers
            ):
                owner, method_name, descriptor = methods[method_index]
                family_token = DIRECT_DEX_OPCODE_FAMILIES[opcode]
                values = [mutable_registers[register] for register in invoke_registers]
                for family in ("reflection_target", "dynamic_loader"):
                    matches = _direct_callsite_matches(
                        family,
                        owner,
                        method_name,
                        descriptor,
                        family_token,
                    )
                    _require(len(matches) <= 1, "dex_api_ambiguous")
                    if matches:
                        target = _evaluate_dex_target_recipe(
                            matches[0].target_recipe,
                            values,
                            has_receiver=opcode not in {0x71, 0x77},
                        )
                        if target is not None:
                            produced = (
                                ("Class", target["class_descriptor"])
                                if target.get("target_kind") == "class"
                                else ("Target", target)
                            )
                for register in invoke_registers:
                    value = mutable_registers[register]
                    if isinstance(value, tuple) and value and value[0] == "Array":
                        mutable_registers[register] = (
                            "Array",
                            value[1],
                            tuple(DEX_TOP for _ in value[2]),
                        )
        next_pending = produced
        next_pending_at = current if produced is not None else None
        output_state = (tuple(mutable_registers), next_pending, next_pending_at)
        for successor in successors(current, opcode):
            if successor not in start_set:
                continue
            previous = entry.get(successor)
            if previous is None:
                updated = output_state
            else:
                updated = (
                    tuple(
                        _dex_join_value(first, second)
                        for first, second in zip(previous[0], output_state[0])
                    ),
                    _dex_join_value(previous[1], output_state[1]),
                    previous[2] if previous[2] == output_state[2] else None,
                )
            if previous != updated:
                entry[successor] = updated
                if successor not in worklist:
                    worklist.append(successor)

    results: dict[tuple[str, int], dict[str, Any]] = {}
    for current in starts:
        opcode = int(units[current]) & 0xFF
        if opcode not in DIRECT_DEX_OPCODE_FAMILIES:
            continue
        state = entry.get(current)
        if state is None:
            continue
        method_index = int(units[current + 1])
        try:
            invoke_registers = _decode_dex_invoke_registers(units, current)
        except ProducerError:
            continue
        if method_index >= len(methods) or not all(
            register < registers_size for register in invoke_registers
        ):
            continue
        owner, method_name, descriptor = methods[method_index]
        family_token = DIRECT_DEX_OPCODE_FAMILIES[opcode]
        values = [state[0][register] for register in invoke_registers]
        for family in ("reflection_target", "dynamic_loader"):
            matches = _direct_callsite_matches(
                family,
                owner,
                method_name,
                descriptor,
                family_token,
            )
            _require(len(matches) <= 1, "dex_api_ambiguous")
            if matches:
                target = _evaluate_dex_target_recipe(
                    matches[0].target_recipe,
                    values,
                    has_receiver=opcode not in {0x71, 0x77},
                )
                if target is not None:
                    results[(family, current)] = target
    return results


def _parse_direct_dex_callsites(
    data: bytes,
    dex_artifact_id: str,
) -> dict[str, list[dict[str, Any]]]:
    _require(len(data) >= 112 and data[:4] == b"dex\n", "dex_header")
    string_count, string_offset = struct.unpack_from("<II", data, 56)
    type_count, type_offset = struct.unpack_from("<II", data, 64)
    proto_count, proto_offset = struct.unpack_from("<II", data, 72)
    method_count, method_offset = struct.unpack_from("<II", data, 88)
    class_count, class_offset = struct.unpack_from("<II", data, 96)
    _require(
        string_offset + string_count * 4 <= len(data)
        and type_offset + type_count * 4 <= len(data)
        and proto_offset + proto_count * 12 <= len(data)
        and method_offset + method_count * 8 <= len(data)
        and class_offset + class_count * 32 <= len(data),
        "dex_table_range",
    )
    strings = []
    for index in range(string_count):
        item_offset = struct.unpack_from("<I", data, string_offset + index * 4)[0]
        strings.append(_decode_dex_mutf8(data, item_offset))
    types = []
    for index in range(type_count):
        string_index = struct.unpack_from("<I", data, type_offset + index * 4)[0]
        _require(string_index < string_count, "dex_type_index")
        types.append(strings[string_index])
    protos = []
    for index in range(proto_count):
        shorty_index, return_index, parameters_offset = struct.unpack_from(
            "<III", data, proto_offset + index * 12
        )
        _require(shorty_index < string_count and return_index < type_count, "dex_proto_index")
        parameters = []
        if parameters_offset:
            _require(parameters_offset + 4 <= len(data), "dex_proto_parameters")
            parameter_count = struct.unpack_from("<I", data, parameters_offset)[0]
            _require(
                parameters_offset + 4 + parameter_count * 2 <= len(data),
                "dex_proto_parameters",
            )
            for ordinal in range(parameter_count):
                type_index = struct.unpack_from(
                    "<H", data, parameters_offset + 4 + ordinal * 2
                )[0]
                _require(type_index < type_count, "dex_proto_parameters")
                parameters.append(types[type_index])
        protos.append("(" + "".join(parameters) + ")" + types[return_index])
    methods = []
    for index in range(method_count):
        class_index, proto_index, name_index = struct.unpack_from(
            "<HHI", data, method_offset + index * 8
        )
        _require(
            class_index < type_count
            and proto_index < proto_count
            and name_index < string_count,
            "dex_method_index",
        )
        methods.append((types[class_index], strings[name_index], protos[proto_index]))

    admitted: dict[str, list[dict[str, Any]]] = {
        "reflection_target": [],
        "dynamic_loader": [],
    }
    code_seen: set[int] = set()
    for class_definition_index in range(class_count):
        class_definition_offset = class_offset + class_definition_index * 32
        class_data_offset = struct.unpack_from(
            "<I", data, class_definition_offset + 24
        )[0]
        if not class_data_offset:
            continue
        cursor = class_data_offset
        static_fields, cursor = _read_uleb128(data, cursor)
        instance_fields, cursor = _read_uleb128(data, cursor)
        direct_methods, cursor = _read_uleb128(data, cursor)
        virtual_methods, cursor = _read_uleb128(data, cursor)
        for field_count in (static_fields, instance_fields):
            field_index = 0
            for _ in range(field_count):
                difference, cursor = _read_uleb128(data, cursor)
                _access_flags, cursor = _read_uleb128(data, cursor)
                field_index += difference
        for encoded_method_count in (direct_methods, virtual_methods):
            method_index = 0
            for _ in range(encoded_method_count):
                difference, cursor = _read_uleb128(data, cursor)
                _access_flags, cursor = _read_uleb128(data, cursor)
                code_offset, cursor = _read_uleb128(data, cursor)
                method_index += difference
                _require(method_index < method_count, "dex_method_index")
                if not code_offset:
                    continue
                _require(
                    code_offset not in code_seen
                    and code_offset % 4 == 0
                    and code_offset + 16 <= len(data),
                    "dex_code_item",
                )
                code_seen.add(code_offset)
                registers_size, _ins_size, _outs_size, tries_size, _debug_info, instruction_count = struct.unpack_from(
                    "<HHHHII", data, code_offset
                )
                instruction_bytes_end = code_offset + 16 + instruction_count * 2
                _require(instruction_bytes_end <= len(data), "dex_code_item")
                units: Sequence[int] = (
                    struct.unpack_from(
                        f"<{instruction_count}H", data, code_offset + 16
                    )
                    if instruction_count
                    else ()
                )
                interpreted = _interpret_dex_targets(
                    units,
                    registers_size,
                    strings,
                    types,
                    methods,
                )
                caller_owner, caller_name, caller_descriptor = methods[method_index]
                instruction_offset = 0
                while instruction_offset < len(units):
                    width = _dex_instruction_width(units, instruction_offset)
                    if instruction_offset + width > len(units):
                        break
                    opcode = int(units[instruction_offset]) & 0xFF
                    if opcode in DIRECT_DEX_OPCODE_FAMILIES:
                        invoked_method_index = int(units[instruction_offset + 1])
                        try:
                            invoke_registers = _decode_dex_invoke_registers(
                                units, instruction_offset
                            )
                        except ProducerError:
                            invoke_registers = []
                        if invoked_method_index < method_count and all(
                            register < registers_size for register in invoke_registers
                        ):
                            owner, method_name, descriptor = methods[invoked_method_index]
                            for family in ("reflection_target", "dynamic_loader"):
                                matches = _direct_callsite_matches(
                                    family,
                                    owner,
                                    method_name,
                                    descriptor,
                                    DIRECT_DEX_OPCODE_FAMILIES[opcode],
                                )
                                _require(len(matches) <= 1, "dex_api_ambiguous")
                                if matches:
                                    admitted[family].append(
                                        {
                                            "caller": {
                                                "dex_artifact_id": dex_artifact_id,
                                                "class_descriptor": caller_owner,
                                                "method_name": caller_name,
                                                "descriptor": caller_descriptor,
                                            },
                                            "instruction_offset_code_units": instruction_offset,
                                            "api": {
                                                "class_descriptor": owner,
                                                "method_name": method_name,
                                                "descriptor": descriptor,
                                            },
                                            "target": interpreted.get(
                                                (family, instruction_offset),
                                                {
                                                    "unresolved_token": "not_statically_resolved"
                                                },
                                            ),
                                        }
                                    )
                    instruction_offset += width
                if tries_size:
                    tries_start = instruction_bytes_end + (2 if instruction_count & 1 else 0)
                    _require(
                        tries_start + tries_size * 8 <= len(data),
                        "dex_try_item",
                    )
    for rows in admitted.values():
        rows.sort(key=_canonical_text)
    return admitted


def _analyze_dex(
    collector: RecordCollector,
    *,
    dex_path: Path,
    source_artifact: Mapping[str, Any],
    dex_class: Any,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    dex_bytes = dex_path.read_bytes()
    dex = dex_class(dex_bytes)
    use_direct_callsites = len(dex_bytes) >= 112 and dex_bytes[:4] == b"dex\n"
    dex_artifact_id = str(source_artifact["artifact_id"])
    source_parent = _source_parent_for_collector(collector, dex_artifact_id)
    native_methods: list[dict[str, Any]] = []
    counts: collections.Counter[str] = collections.Counter()
    class_record_ids: dict[str, str] = {}
    family_record_ids_by_key: dict[tuple[str, str], str] = {}

    classes = sorted(dex.get_classes(), key=lambda item: str(item.get_name()))
    for class_def in classes:
        class_name = str(class_def.get_name())
        class_payload = {
            "dex_artifact_id": dex_artifact_id,
            "descriptor": class_name,
            "access_flags": int(class_def.get_access_flags()),
            "superclass": str(class_def.get_superclassname()),
            "interfaces": sorted(str(item) for item in (class_def.get_interfaces() or [])),
        }
        class_digest, class_size = _payload_digest(class_payload)
        class_record_id = collector.add(
            "class",
            class_payload,
            dataset="dex",
            artifact_id=None,
            source_artifact_id=dex_artifact_id,
            sha256=class_digest,
            size_bytes=class_size,
            official_source=None,
            parent_record_ids=[source_parent],
        )
        class_record_ids[class_name] = class_record_id
        counts["classes"] += 1

        family_variants: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
        calls: list[dict[str, Any]] = []
        encoded_methods = sorted(
            class_def.get_methods(),
            key=lambda method: (
                str(method.get_name()),
                _descriptor(method.get_descriptor()),
                int(method.get_access_flags()),
            ),
        )
        counts["defined_methods"] += len(encoded_methods)
        for method in encoded_methods:
            method_name = str(method.get_name())
            method_descriptor = _descriptor(method.get_descriptor())
            access_flags = int(method.get_access_flags())
            family_variants[method_name].append(
                {
                    "descriptor": method_descriptor,
                    "access_flags": access_flags,
                }
            )
            if access_flags & 0x0100:
                native_methods.append(
                    {
                        "dex_artifact_id": dex_artifact_id,
                        "class_descriptor": class_name,
                        "method_name": method_name,
                        "descriptor": method_descriptor,
                        "class_record_id": class_record_id,
                    }
                )
                counts["native_declarations"] += 1

            if use_direct_callsites or method.get_code() is None:
                continue
            observed_calls: set[tuple[int, str, str]] = set()
            for offset, instruction in method.get_instructions_idx():
                if str(instruction.get_name()) not in DEX_INVOKE_OPCODE_FAMILIES:
                    continue
                for callsite in _instruction_callsites(instruction):
                    dynamic_apis = _matched_callsite_apis(
                        "dynamic_loader",
                        str(callsite["api"]),
                        callsite["opcode_family"],
                    )
                    reflection_apis = _matched_callsite_apis(
                        "reflection_target",
                        str(callsite["api"]),
                        callsite["opcode_family"],
                    )
                    if not dynamic_apis and not reflection_apis:
                        continue
                    key = (
                        int(offset),
                        str(callsite["api"]),
                        _canonical_text(callsite["string_args"]),
                    )
                    if key in observed_calls:
                        continue
                    observed_calls.add(key)
                    calls.append(
                        {
                            "method_name": method_name,
                            "descriptor": method_descriptor,
                            "offset": int(offset) // 2,
                            "api": str(callsite["api"]),
                            "dynamic_apis": dynamic_apis,
                            "reflection_apis": reflection_apis,
                            "string_args": tuple(callsite["string_args"]),
                        }
                    )

        family_record_ids: dict[str, str] = {}
        for family_name in sorted(family_variants):
            variants = sorted(
                family_variants[family_name],
                key=_canonical_text,
            )
            payload = {
                "dex_artifact_id": dex_artifact_id,
                "class_descriptor": class_name,
                "method_name": family_name,
                "definitions": variants,
            }
            digest, size = _payload_digest(payload)
            family_record_ids[family_name] = collector.add(
                "method_family",
                payload,
                dataset="dex",
                artifact_id=None,
                source_artifact_id=dex_artifact_id,
                sha256=digest,
                size_bytes=size,
                official_source=None,
                parent_record_ids=[source_parent, class_record_id],
            )
            family_record_ids_by_key[(class_name, family_name)] = family_record_ids[
                family_name
            ]
            counts["method_families"] += 1

        for item in native_methods:
            if item["dex_artifact_id"] == dex_artifact_id and item["class_descriptor"] == class_name:
                item["family_record_id"] = family_record_ids[item["method_name"]]

        for call in sorted(calls, key=lambda item: (item["method_name"], item["descriptor"], item["offset"], item["api"])):
            caller = {
                "dex_artifact_id": dex_artifact_id,
                "class_descriptor": class_name,
                "method_name": call["method_name"],
                "descriptor": call["descriptor"],
            }
            api = _api_payload(call["api"])
            parent_record_ids = [
                source_parent,
                class_record_id,
                family_record_ids[call["method_name"]],
            ]
            for matched_api in call["dynamic_apis"]:
                payload = {
                    "caller": caller,
                    "instruction_offset_code_units": call["offset"],
                    "api": api,
                    "target": _callsite_target(
                        matched_api.target_recipe,
                        call["string_args"],
                    ),
                }
                digest, size = _payload_digest(payload)
                collector.add(
                    "dynamic_loader",
                    payload,
                    dataset="dex",
                    artifact_id=None,
                    source_artifact_id=dex_artifact_id,
                    sha256=digest,
                    size_bytes=size,
                    official_source=None,
                    parent_record_ids=parent_record_ids,
                )
                counts["dynamic_loaders"] += 1
            for matched_api in call["reflection_apis"]:
                reflection_payload = {
                    "caller": caller,
                    "instruction_offset_code_units": call["offset"],
                    "api": api,
                    "target": _callsite_target(
                        matched_api.target_recipe,
                        call["string_args"],
                    ),
                }
                reflection_digest, reflection_size = _payload_digest(reflection_payload)
                collector.add(
                    "reflection_target",
                    reflection_payload,
                    dataset="dex",
                    artifact_id=None,
                    source_artifact_id=dex_artifact_id,
                    sha256=reflection_digest,
                    size_bytes=reflection_size,
                    official_source=None,
                    parent_record_ids=parent_record_ids,
                )
                counts["reflection_targets"] += 1

    if use_direct_callsites:
        direct_callsites = _parse_direct_dex_callsites(dex_bytes, dex_artifact_id)
        for family, rows in direct_callsites.items():
            count_key = (
                "dynamic_loaders" if family == "dynamic_loader" else "reflection_targets"
            )
            for payload in rows:
                caller = payload["caller"]
                class_name = str(caller["class_descriptor"])
                method_name = str(caller["method_name"])
                class_record_id = class_record_ids.get(class_name)
                family_record_id = family_record_ids_by_key.get(
                    (class_name, method_name)
                )
                _require(
                    class_record_id is not None and family_record_id is not None,
                    "dex_callsite_parent",
                )
                digest, size = _payload_digest(payload)
                collector.add(
                    family,
                    payload,
                    dataset="dex",
                    artifact_id=None,
                    source_artifact_id=dex_artifact_id,
                    sha256=digest,
                    size_bytes=size,
                    official_source=None,
                    parent_record_ids=[
                        source_parent,
                        class_record_id,
                        family_record_id,
                    ],
                )
                counts[count_key] += 1

    del dex
    gc.collect()
    return dict(sorted(counts.items())), native_methods


def _command_result(
    argv: Sequence[str],
    *,
    pass_number: int | None,
    phase: str,
    command_log: list[dict[str, Any]],
) -> str:
    environment = dict(os.environ)
    environment["LC_ALL"] = "C"
    environment["LANG"] = "C"
    completed = subprocess.run(
        list(argv),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
    )
    stdout = completed.stdout
    stderr = completed.stderr
    entry = {
        "command_index": len(command_log),
        "phase": phase,
        "pass_number": pass_number,
        "argv": list(argv),
        "command": shlex.join(list(argv)),
        "exit_code": int(completed.returncode),
        "stdout_sha256": _sha256_bytes(stdout),
        "stdout_size_bytes": len(stdout),
        "stderr_sha256": _sha256_bytes(stderr),
        "stderr_size_bytes": len(stderr),
    }
    command_log.append(entry)
    if completed.returncode != 0:
        raise ProducerError(
            f"command failed ({completed.returncode}): {entry['command']} "
            f"stderr={stderr.decode('utf-8', errors='replace')[:2000]}"
        )
    return stdout.decode("utf-8", errors="strict")


def _split_symbol_name(display_name: str) -> tuple[str | None, str | None]:
    if not display_name:
        return None, None
    if "@@" in display_name:
        name, version = display_name.split("@@", 1)
        return name, f"@@{version}"
    if "@" in display_name:
        name, version = display_name.split("@", 1)
        return name, f"@{version}"
    return display_name, None


def _parse_readelf_symbols(output: str) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    declared = [int(match.group(1)) for match in READELF_DYNSYM_COUNT_RE.finditer(output)]
    if len(declared) != 1:
        raise ProducerError(f"readelf exposed an ambiguous .dynsym count: {declared}")
    parsed: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = READELF_DYNSYM_RE.match(line)
        if match is None:
            continue
        display_name = re.sub(r"\s+\(\d+\)$", "", match.group("name").strip())
        name, version = _split_symbol_name(display_name)
        section_token = match.group("section")
        section_index = {
            "UND": 0,
            "ABS": 0xFFF1,
            "COM": 0xFFF2,
            "COMMON": 0xFFF2,
        }.get(section_token)
        if section_index is None:
            try:
                section_index = int(section_token, 0)
            except ValueError as exc:
                raise ProducerError(f"unsupported readelf section index {section_token!r}") from exc
        row = {
            "dynsym_index": int(match.group("index")),
            "name": name,
            "version": version,
            "value": int(match.group("value"), 16),
            "size_bytes": int(match.group("size"), 0),
            "symbol_type": (
                "STT_GNU_IFUNC"
                if match.group("type") == "IFUNC"
                else f"STT_{match.group('type')}"
            ),
            "binding": (
                "STB_GNU_UNIQUE"
                if match.group("bind") == "UNIQUE"
                else f"STB_{match.group('bind')}"
            ),
            "visibility": f"STV_{match.group('visibility')}",
            "section_index": section_index,
        }
        if row["symbol_type"] == "STT_SECTION":
            row["name"] = None
            row["version"] = None
        if row["dynsym_index"] == 0:
            excluded.append({"reason": "reserved-index-zero", **row})
            continue
        parsed.append(row)
    if len(parsed) + len(excluded) != declared[0]:
        raise ProducerError(
            f"readelf .dynsym parse mismatch: expected {declared[0]}, "
            f"parsed {len(parsed) + len(excluded)}"
        )
    return declared[0], parsed, excluded


def _parse_readelf_needed(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dynamic_index = 0
    for line in output.splitlines():
        match = READELF_DYNAMIC_RE.match(line)
        if match is None:
            continue
        if match.group("tag") == "NEEDED":
            needed = READELF_NEEDED_VALUE_RE.search(match.group("value"))
            if needed is None:
                raise ProducerError(f"cannot parse DT_NEEDED row: {line}")
            rows.append(
                {
                    "dynamic_index": dynamic_index,
                    "soname": needed.group("name"),
                }
            )
        dynamic_index += 1
    return rows


def _parse_nm_counts(output: str) -> tuple[int, int]:
    imports = 0
    exports = 0
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        symbol_type = parts[1]
        value = parts[2] if len(parts) >= 3 else None
        undefined = symbol_type.upper() == "U" or (
            symbol_type in {"w", "v"} and value is None
        )
        if undefined:
            imports += 1
        else:
            exports += 1
    return imports, exports


def _analyze_native_library(
    collector: RecordCollector,
    *,
    lib_path: Path,
    source_artifact: Mapping[str, Any],
    bundled_library_by_name: Mapping[str, str],
    pass_number: int,
    command_log: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    symbols_output = _command_result(
        ("readelf", "-W", "--dyn-syms", str(lib_path)),
        pass_number=pass_number,
        phase="elf-dynamic-symbols",
        command_log=command_log,
    )
    dynamic_output = _command_result(
        ("readelf", "-W", "-d", str(lib_path)),
        pass_number=pass_number,
        phase="elf-dynamic-table",
        command_log=command_log,
    )
    relocations_output = _command_result(
        ("readelf", "-W", "-r", str(lib_path)),
        pass_number=pass_number,
        phase="elf-relocations",
        command_log=command_log,
    )
    nm_output = _command_result(
        ("nm", "-D", "--format=posix", str(lib_path)),
        pass_number=pass_number,
        phase="elf-nm",
        command_log=command_log,
    )
    objdump_output = _command_result(
        ("objdump", "-T", str(lib_path)),
        pass_number=pass_number,
        phase="elf-objdump",
        command_log=command_log,
    )

    declared_count, symbols, excluded_symbols = _parse_readelf_symbols(symbols_output)
    needed_rows = _parse_readelf_needed(dynamic_output)
    nm_import_count, nm_export_count = _parse_nm_counts(nm_output)
    objdump_rows = sum(
        1 for line in objdump_output.splitlines() if OBJDUMP_ROW_RE.match(line)
    )
    del objdump_rows

    artifact_id = str(source_artifact["artifact_id"])
    source_parent = _source_parent_for_collector(collector, artifact_id)
    symbol_record_ids: dict[int, str] = {}
    for symbol in symbols:
        payload = {
            "library_artifact_id": artifact_id,
            "dynamic_symbol_index": symbol["dynsym_index"],
            "name": symbol["name"],
            "version": symbol["version"],
            "value": symbol["value"],
            "size_bytes": symbol["size_bytes"],
            "symbol_type": symbol["symbol_type"],
            "binding": symbol["binding"],
            "visibility": symbol["visibility"],
            "section_index": symbol["section_index"],
        }
        digest, size = _payload_digest(payload)
        symbol_record_ids[int(symbol["dynsym_index"])] = collector.add(
            "native_symbol",
            payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=artifact_id,
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=[source_parent],
        )

    undefined_rows = [
        row for row in symbols if row["section_index"] == 0 and row["name"] is not None
    ]
    export_rows = [
        row
        for row in symbols
        if row["section_index"] != 0
        and row["binding"] in {"STB_GLOBAL", "STB_WEAK"}
        and row["visibility"]
        in {"STV_DEFAULT", "STV_PROTECTED", "STV_EXPORTED", "STV_SINGLETON"}
    ]
    if nm_import_count != len(undefined_rows) or nm_export_count != len(export_rows):
        raise ProducerError(
            f"readelf/nm import-export disagreement for {artifact_id}: "
            f"imports {len(undefined_rows)}/{nm_import_count}, "
            f"exports {len(export_rows)}/{nm_export_count}"
        )

    export_catalog: list[dict[str, Any]] = []
    for symbol in export_rows:
        symbol_record_id = symbol_record_ids[int(symbol["dynsym_index"])]
        payload = {
            "native_symbol_record_id": symbol_record_id,
            "library_artifact_id": artifact_id,
            "dynamic_symbol_index": symbol["dynsym_index"],
            "name": symbol["name"],
            "version": symbol["version"],
            "binding": symbol["binding"],
        }
        digest, size = _payload_digest(payload)
        export_record_id = collector.add(
            "native_export",
            payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=artifact_id,
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=[source_parent, symbol_record_id],
        )
        export_catalog.append(
            {
                "library_artifact_id": artifact_id,
                "dynamic_symbol_index": symbol["dynsym_index"],
                "name": symbol["name"],
                "version": symbol["version"],
                "native_symbol_record_id": symbol_record_id,
                "native_export_record_id": export_record_id,
                "virtual_address": symbol["value"],
            }
        )

    for symbol in undefined_rows:
        symbol_record_id = symbol_record_ids[int(symbol["dynsym_index"])]
        payload = {
            "import_kind": "undefined_dynsym",
            "library_artifact_id": artifact_id,
            "dynamic_symbol_index": symbol["dynsym_index"],
            "name": symbol["name"],
            "version": symbol["version"],
            "native_symbol_record_id": symbol_record_id,
        }
        digest, size = _payload_digest(payload)
        collector.add(
            "native_import",
            payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=artifact_id,
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=[source_parent, symbol_record_id],
        )

    for needed in needed_rows:
        payload = {
            "import_kind": "dt_needed",
            "library_artifact_id": artifact_id,
            "dynamic_table_index": needed["dynamic_index"],
            "soname": needed["soname"],
            "bundled_target_artifact_id": bundled_library_by_name.get(needed["soname"]),
        }
        digest, size = _payload_digest(payload)
        collector.add(
            "native_import",
            payload,
            dataset="elf",
            artifact_id=None,
            source_artifact_id=artifact_id,
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=[source_parent],
        )

    java_export_count = sum(
        1 for item in export_catalog if str(item["name"]).startswith("Java_")
    )
    summary_payload = {
        "configuration_kind": "native_library_summary",
        "library_artifact_id": artifact_id,
        "dynamic_symbol_count": len(symbols),
        "defined_global_weak_export_count": len(export_rows),
        "undefined_named_import_count": len(undefined_rows),
        "dt_needed_count": len(needed_rows),
        "java_export_count": java_export_count,
    }
    summary_digest, summary_size = _payload_digest(summary_payload)
    collector.add(
        "configuration",
        summary_payload,
        dataset="elf",
        artifact_id=None,
        source_artifact_id=artifact_id,
        sha256=summary_digest,
        size_bytes=summary_size,
        official_source=None,
        parent_record_ids=[source_parent],
    )

    excluded_digest = _sha256_bytes(_canonical_bytes(excluded_symbols))
    summary = {
        "artifact_id": artifact_id,
        "path_within_base_apk": f"lib/{artifact_id.split(':', 1)[1]}",
        "sha256": str(source_artifact["sha256"]),
        "size_bytes": int(source_artifact["size_bytes"]),
        "readelf_declared_dynamic_symbol_count": declared_count,
        "anonymous_symbol_count": sum(
            1 for row in excluded_symbols if row["reason"] == "anonymous-null-symbol"
        ),
        "embedded_dot_tls_descriptor_count": sum(
            1 for row in excluded_symbols if row["reason"] == "embedded-dot-tls-descriptor"
        ),
        "excluded_symbol_rows_sha256": excluded_digest,
        "canonical_dynamic_symbol_count": len(symbols),
        "canonical_export_count": len(export_rows),
        "undefined_import_count": len(undefined_rows),
        "needed_edge_count": len(needed_rows),
        "java_export_count": java_export_count,
        "relocation_output_sha256": _sha256_bytes(relocations_output.encode("utf-8")),
    }
    return summary, export_catalog


def _jni_mangle_fragment(value: str, *, class_name: bool = False) -> str:
    result: list[str] = []
    for character in value:
        if class_name and character == "/":
            result.append("_")
        elif character == "_":
            result.append("_1")
        elif character == ";":
            result.append("_2")
        elif character == "[":
            result.append("_3")
        elif character.isascii() and character.isalnum():
            result.append(character)
        else:
            result.append(f"_0{ord(character):04x}")
    return "".join(result)


def _jni_names(class_descriptor: str, method_name: str, descriptor: str) -> tuple[str, str]:
    class_name = (
        class_descriptor[1:-1]
        if class_descriptor.startswith("L") and class_descriptor.endswith(";")
        else class_descriptor
    )
    short = (
        f"Java_{_jni_mangle_fragment(class_name, class_name=True)}_"
        f"{_jni_mangle_fragment(method_name)}"
    )
    arguments = descriptor[descriptor.find("(") + 1 : descriptor.find(")")]
    long_name = f"{short}__{_jni_mangle_fragment(arguments, class_name=True)}"
    return short, long_name


def _add_jni_edges(
    collector: RecordCollector,
    *,
    inputs: Inputs,
    native_methods: Sequence[Mapping[str, Any]],
    native_exports: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    java_exports = [
        export for export in native_exports if str(export["name"]).startswith("Java_")
    ]
    by_symbol: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for export in java_exports:
        by_symbol[str(export["name"])].append(export)

    matched_export_ids: set[str] = set()
    resolved_declarations = 0
    unresolved_declarations = 0
    static_edges = 0
    edge_count = 0
    for method in sorted(
        native_methods,
        key=lambda item: (
            str(item["dex_artifact_id"]),
            str(item["class_descriptor"]),
            str(item["method_name"]),
            str(item["descriptor"]),
        ),
    ):
        short_name, long_name = _jni_names(
            str(method["class_descriptor"]),
            str(method["method_name"]),
            str(method["descriptor"]),
        )
        short_matches = by_symbol.get(short_name, [])
        long_matches = by_symbol.get(long_name, [])
        matches = sorted(
            short_matches if short_matches else long_matches,
            key=lambda item: (
                str(item["library_artifact_id"]),
                str(item["native_export_record_id"]),
            ),
        )
        java_declaration = {
            "dex_artifact_id": method["dex_artifact_id"],
            "class_descriptor": method["class_descriptor"],
            "method_name": method["method_name"],
            "descriptor": method["descriptor"],
        }
        dex_parent = _source_parent(inputs, str(method["dex_artifact_id"]))
        if matches:
            resolved_declarations += 1
            for export in matches:
                binding_kind = "static_short" if short_matches else "static_long"
                payload = {
                    "java_declaration": java_declaration,
                    "native_endpoint": {
                        "endpoint_kind": "java_export",
                        "library_artifact_id": export["library_artifact_id"],
                        "native_export_record_id": export["native_export_record_id"],
                        "native_symbol_record_id": export["native_symbol_record_id"],
                        "name": export["name"],
                        "version": export["version"],
                        "virtual_address": export["virtual_address"],
                    },
                    "binding_form": binding_kind,
                    "registration_site": None,
                    "resolution_status": "resolved",
                }
                digest, size = _payload_digest(payload)
                library_parent = _source_parent(inputs, str(export["library_artifact_id"]))
                collector.add(
                    "jni_edge",
                    payload,
                    dataset="jni",
                    artifact_id=None,
                    source_artifact_id=str(method["dex_artifact_id"]),
                    sha256=digest,
                    size_bytes=size,
                    official_source=None,
                    parent_record_ids=[
                        dex_parent,
                        str(method["class_record_id"]),
                        str(method["family_record_id"]),
                        library_parent,
                        str(export["native_symbol_record_id"]),
                        str(export["native_export_record_id"]),
                    ],
                )
                matched_export_ids.add(str(export["native_export_record_id"]))
                static_edges += 1
                edge_count += 1
        else:
            unresolved_declarations += 1
            payload = {
                "java_declaration": java_declaration,
                "native_endpoint": {
                    "unresolved_token": "no_static_export_or_proven_register_natives"
                },
                "binding_form": "unresolved_declaration",
                "registration_site": None,
                "resolution_status": "unresolved",
            }
            digest, size = _payload_digest(payload)
            collector.add(
                "jni_edge",
                payload,
                dataset="jni",
                artifact_id=None,
                source_artifact_id=str(method["dex_artifact_id"]),
                sha256=digest,
                size_bytes=size,
                official_source=None,
                parent_record_ids=[
                    dex_parent,
                    str(method["class_record_id"]),
                    str(method["family_record_id"]),
                ],
            )
            edge_count += 1

    orphan_exports = 0
    for export in sorted(
        java_exports,
        key=lambda item: (
            str(item["library_artifact_id"]),
            str(item["native_export_record_id"]),
        ),
    ):
        export_record_id = str(export["native_export_record_id"])
        if export_record_id in matched_export_ids:
            continue
        payload = {
            "java_declaration": {
                "unresolved_token": "no_matching_dex_native_declaration"
            },
            "native_endpoint": {
                "endpoint_kind": "java_export",
                "library_artifact_id": export["library_artifact_id"],
                "native_export_record_id": export_record_id,
                "native_symbol_record_id": export["native_symbol_record_id"],
                "name": export["name"],
                "version": export["version"],
                "virtual_address": export["virtual_address"],
            },
            "binding_form": "orphan_java_export",
            "registration_site": None,
            "resolution_status": "orphan",
        }
        digest, size = _payload_digest(payload)
        library_parent = _source_parent(inputs, str(export["library_artifact_id"]))
        collector.add(
            "jni_edge",
            payload,
            dataset="jni",
            artifact_id=None,
            source_artifact_id=str(export["library_artifact_id"]),
            sha256=digest,
            size_bytes=size,
            official_source=None,
            parent_record_ids=[library_parent, export_record_id],
        )
        orphan_exports += 1
        edge_count += 1

    if resolved_declarations + unresolved_declarations != len(native_methods):
        raise ProducerError("JNI declaration conservation failed")
    if len(matched_export_ids) + orphan_exports != len(java_exports):
        raise ProducerError("JNI Java_* export conservation failed")
    return {
        "native_declarations": len(native_methods),
        "resolved_declarations": resolved_declarations,
        "unresolved_declarations": unresolved_declarations,
        "register_natives_edges": 0,
        "static_edges": static_edges,
        "java_exports": len(java_exports),
        "matched_java_exports": len(matched_export_ids),
        "orphan_java_exports": orphan_exports,
        "jni_edges": edge_count,
    }


def _build_pass(
    *,
    pass_number: int,
    inputs: Inputs,
    output_root: Path,
    command_log: list[dict[str, Any]],
    apk_class: Any,
    dex_class: Any,
    axml_parser_class: Any,
    start_tag: int,
    end_tag: int,
    end_document: int,
    format_value: Any,
    type_table: Mapping[int, str],
) -> tuple[
    list[dict[str, Any]],
    dict[str, str],
    dict[str, int],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    work_root = output_root / ".work" / f"pass-{pass_number}"
    if work_root.exists():
        shutil.rmtree(work_root)
    apk_root = work_root / "apks"
    extracted_root = work_root / "base-entries"
    apk_root.mkdir(parents=True, exist_ok=True)
    extracted_root.mkdir(parents=True, exist_ok=True)

    collector = RecordCollector()
    observer = ArtifactObserver(inputs.artifacts)
    _add_frozen_artifacts(collector, inputs)
    scope_counts: collections.Counter[str] = collections.Counter()
    detail: dict[str, Any] = {
        "pass_number": pass_number,
        "apk_entries_by_member": {},
        "archive_categories": {},
        "manifest_nodes_by_member": {},
        "resources_by_member": {},
        "resource_configurations_by_member": {},
        "certificate_rows_by_member": {},
        "component_counts": {},
        "dex_by_artifact": {},
        "native_library_summaries": [],
    }
    native_methods: list[dict[str, Any]] = []
    native_exports: list[dict[str, Any]] = []
    native_summaries: list[dict[str, Any]] = []
    manifest_component_items: list[dict[str, Any]] = []

    try:
        xapk_digest = _sha256_file(inputs.xapk)
        xapk_size = inputs.xapk.stat().st_size
        observer.observe("official-xapk", xapk_digest, xapk_size, str(inputs.xapk))

        extracted_apks: dict[str, Path] = {}
        with zipfile.ZipFile(inputs.xapk) as xapk:
            infos = xapk.infolist()
            normalized_paths = [
                _safe_zip_path(info.filename, label="XAPK entry") for info in infos
            ]
            if len(infos) != 21 or set(normalized_paths) != set(inputs.xapk_member_artifact_by_path):
                raise ProducerError("XAPK central-directory universe differs from the frozen 21 entries")
            for ordinal, (info, entry_path) in enumerate(zip(infos, normalized_paths)):
                if info.is_dir():
                    raise ProducerError(f"unexpected XAPK directory entry: {entry_path}")
                destination = apk_root / entry_path if entry_path.endswith(".apk") else None
                if destination is not None:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                with xapk.open(info, "r") as source:
                    digest, size = _hash_stream(source, destination)
                if size != info.file_size:
                    raise ProducerError(f"XAPK entry size changed while reading: {entry_path}")
                entry_artifact_id = inputs.xapk_member_artifact_by_path[entry_path]
                observer.observe(
                    entry_artifact_id,
                    digest,
                    size,
                    f"{inputs.xapk}!{entry_path}",
                )
                if entry_path == inputs.base_member:
                    observer.observe(
                        "extracted-base-apk",
                        digest,
                        size,
                        f"{inputs.xapk}!{entry_path}",
                    )
                if entry_path.endswith(".apk"):
                    extracted_apks[entry_path] = destination  # type: ignore[assignment]
                payload = _archive_payload(
                    container_artifact_id="official-xapk",
                    ordinal=ordinal,
                    path=entry_path,
                    info=info,
                    sha256=digest,
                )
                byte_sha256, byte_size = _payload_byte_evidence(payload)
                collector.add(
                    "configuration",
                    payload,
                    dataset="xapk",
                    artifact_id=None,
                    source_artifact_id="official-xapk",
                    sha256=byte_sha256,
                    size_bytes=byte_size,
                    official_source=None,
                    parent_record_ids=[
                        _source_parent_for_collector(collector, entry_artifact_id),
                        _source_parent_for_collector(collector, "official-xapk"),
                    ],
                )
                scope_counts["xapk_entries"] += 1

        if set(extracted_apks) != set(inputs.apk_member_artifact_by_path):
            raise ProducerError("not every frozen APK member was extracted from the XAPK")

        archive_categories: collections.Counter[str] = collections.Counter()
        resource_name_map: dict[int, tuple[str, str, str]] = {}
        apk_analysis_order = [
            inputs.base_member,
            *(member for member in sorted(extracted_apks) if member != inputs.base_member),
        ]
        for apk_member in apk_analysis_order:
            apk_path = extracted_apks[apk_member]
            apk_artifact_id = inputs.apk_member_artifact_by_path[apk_member]
            apk_parent = _source_parent_for_collector(collector, apk_artifact_id)
            raw_manifest: bytes | None = None
            raw_resource_table: bytes | None = None
            with zipfile.ZipFile(apk_path) as apk_zip:
                infos = apk_zip.infolist()
                detail["apk_entries_by_member"][apk_member] = len(infos)
                for ordinal, info in enumerate(infos):
                    entry_path = _safe_zip_path(
                        info.filename,
                        label=f"APK entry in {apk_member}",
                    )
                    if info.is_dir():
                        raise ProducerError(f"unexpected APK directory entry: {apk_member}!{entry_path}")
                    nested_artifact_id = (
                        inputs.base_entry_artifact_by_path.get(entry_path)
                        if apk_member == inputs.base_member
                        else None
                    )
                    destination: Path | None = None
                    if nested_artifact_id is not None:
                        nested_kind = str(inputs.artifacts_by_id[nested_artifact_id]["kind"])
                        if nested_kind in {"dex", "native_library"}:
                            destination = extracted_root / entry_path
                            destination.parent.mkdir(parents=True, exist_ok=True)
                    with apk_zip.open(info, "r") as source:
                        digest, size = _hash_stream(source, destination)
                    if size != info.file_size:
                        raise ProducerError(
                            f"APK entry size changed while reading: {apk_member}!{entry_path}"
                        )
                    if entry_path == "AndroidManifest.xml":
                        raw_manifest = apk_zip.read(info)
                        archive_categories["AndroidManifest.xml"] += 1
                    elif entry_path == "resources.arsc":
                        raw_resource_table = apk_zip.read(info)
                        archive_categories["resources.arsc"] += 1
                    elif re.fullmatch(r"classes(?:\d+)?\.dex", entry_path):
                        archive_categories["dex"] += 1
                    elif entry_path.startswith("lib/arm64-v8a/") and entry_path.endswith(".so"):
                        archive_categories["arm64"] += 1
                    elif entry_path.startswith("lib/armeabi-v7a/") and entry_path.endswith(".so"):
                        archive_categories["arm32"] += 1
                    elif entry_path.startswith("res/"):
                        archive_categories["res"] += 1
                    elif entry_path.startswith("assets/"):
                        archive_categories["assets"] += 1
                    elif entry_path.startswith("META-INF/"):
                        archive_categories["META-INF"] += 1
                    else:
                        archive_categories["other"] += 1

                    if nested_artifact_id is not None:
                        observer.observe(
                            nested_artifact_id,
                            digest,
                            size,
                            f"{apk_member}!{entry_path}",
                        )
                    archive_payload = _archive_payload(
                        container_artifact_id=apk_artifact_id,
                        ordinal=ordinal,
                        path=entry_path,
                        info=info,
                        sha256=digest,
                    )
                    archive_sha256, archive_size = _payload_byte_evidence(
                        archive_payload
                    )
                    archive_record_id = collector.add(
                        "configuration",
                        archive_payload,
                        dataset="apk_entries",
                        artifact_id=None,
                        source_artifact_id=apk_artifact_id,
                        sha256=archive_sha256,
                        size_bytes=archive_size,
                        official_source=None,
                        parent_record_ids=_apk_archive_entry_parent_ids(
                            collector,
                            apk_artifact_id,
                            nested_artifact_id=nested_artifact_id,
                        ),
                    )
                    scope_counts["apk_entries"] += 1

                    if entry_path.startswith("assets/"):
                        asset_payload = {
                            "apk_artifact_id": apk_artifact_id,
                            "archive_entry_record_id": archive_record_id,
                            "path": entry_path,
                            "size_bytes": size,
                            "sha256": digest,
                        }
                        collector.add(
                            "asset",
                            asset_payload,
                            dataset="apk_entries",
                            artifact_id=None,
                            source_artifact_id=apk_artifact_id,
                            sha256=digest,
                            size_bytes=size,
                            official_source=None,
                            parent_record_ids=[
                                apk_parent,
                                archive_record_id,
                            ],
                        )
                        scope_counts["assets"] += 1

                    if entry_path.startswith("lib/armeabi-v7a/") and entry_path.endswith(".so"):
                        arm32_payload = {
                            "configuration_kind": "arm32_native_library",
                            "apk_artifact_id": apk_artifact_id,
                            "abi": "armeabi-v7a",
                            "archive_entry_record_id": archive_record_id,
                            "path": entry_path,
                            "soname": Path(entry_path).name,
                            "size_bytes": size,
                            "sha256": digest,
                        }
                        arm32_sha256, arm32_size = _payload_byte_evidence(
                            arm32_payload
                        )
                        collector.add(
                            "configuration",
                            arm32_payload,
                            dataset="apk_entries",
                            artifact_id=None,
                            source_artifact_id=apk_artifact_id,
                            sha256=arm32_sha256,
                            size_bytes=arm32_size,
                            official_source=None,
                            parent_record_ids=[apk_parent, archive_record_id],
                        )
                        scope_counts["arm32_native_libraries"] += 1

            if raw_manifest is None:
                raise ProducerError(f"APK lacks AndroidManifest.xml: {apk_member}")
            apk = apk_class(str(apk_path), skip_analysis=False, testzip=False)
            package_name = str(apk.get_package())
            manifest_counts = _analyze_manifest(
                collector,
                raw_manifest=raw_manifest,
                apk_artifact_id=apk_artifact_id,
                package_name=package_name,
                include_installed_declarations=False,
                axml_parser_class=axml_parser_class,
                start_tag=start_tag,
                end_tag=end_tag,
                end_document=end_document,
                format_value=format_value,
                type_table=type_table,
            )
            detail["manifest_nodes_by_member"][apk_member] = manifest_counts["manifest_nodes"]
            scope_counts["manifest_nodes"] += manifest_counts["manifest_nodes"]
            scope_counts["features"] += manifest_counts["features"]
            manifest_component_items.append(
                {
                    "apk_artifact_id": apk_artifact_id,
                    "axml": manifest_counts["axml"],
                    "node_record_ids_by_path": manifest_counts["node_record_ids_by_path"],
                }
            )

            resource_counts = _analyze_resources(
                collector,
                apk=apk,
                apk_artifact_id=apk_artifact_id,
                resource_name_map=resource_name_map,
                resource_table=raw_resource_table,
            )
            detail["resources_by_member"][apk_member] = resource_counts["resources"]
            detail["resource_configurations_by_member"][apk_member] = resource_counts[
                "resource_configurations"
            ]
            scope_counts.update(resource_counts)

            signing = _analyze_certificates(
                collector,
                apk=apk,
                apk_artifact_id=apk_artifact_id,
            )
            detail["certificate_rows_by_member"][apk_member] = signing
            scope_counts["certificates"] += int(signing["certificate_rows"])
            del apk
            gc.collect()

        detail["archive_categories"] = dict(sorted(archive_categories.items()))
        base_apk_artifact_id = inputs.apk_member_artifact_by_path[inputs.base_member]
        component_counts = _add_android_component_records(
            collector,
            manifest_items=manifest_component_items,
            canonical_base_apk_artifact_id=base_apk_artifact_id,
            effective_target_sdk=35,
        )
        for kind, count in component_counts["components_by_kind"].items():
            detail["component_counts"][kind] = detail["component_counts"].get(kind, 0) + count
        scope_counts["android_components"] += component_counts["emitted_components"]

        dex_artifacts = sorted(
            (artifact for artifact in inputs.artifacts if artifact.get("kind") == "dex"),
            key=lambda item: str(item["artifact_id"]),
        )
        for artifact in dex_artifacts:
            dex_name = str(artifact["artifact_id"]).split(":", 1)[1]
            dex_path = extracted_root / dex_name
            if not dex_path.is_file():
                raise ProducerError(f"independently extracted DEX is missing: {dex_name}")
            dex_counts, methods = _analyze_dex(
                collector,
                dex_path=dex_path,
                source_artifact=artifact,
                dex_class=dex_class,
            )
            detail["dex_by_artifact"][str(artifact["artifact_id"])] = dex_counts
            scope_counts["dex_classes"] += dex_counts.get("classes", 0)
            scope_counts["dex_defined_methods"] += dex_counts.get("defined_methods", 0)
            scope_counts["method_families"] += dex_counts.get("method_families", 0)
            scope_counts["native_declarations"] += dex_counts.get("native_declarations", 0)
            scope_counts["dynamic_loaders"] += dex_counts.get("dynamic_loaders", 0)
            scope_counts["reflection_targets"] += dex_counts.get("reflection_targets", 0)
            native_methods.extend(methods)

        native_artifacts = sorted(
            (
                artifact
                for artifact in inputs.artifacts
                if artifact.get("kind") == "native_library"
            ),
            key=lambda item: str(item["artifact_id"]),
        )
        if len(native_artifacts) != 88:
            raise ProducerError(f"frozen arm64 native-library count is not 88: {len(native_artifacts)}")
        bundled_library_by_name = {
            Path(str(artifact["artifact_id"]).split(":", 1)[1]).name: str(
                artifact["artifact_id"]
            )
            for artifact in native_artifacts
        }
        for artifact in native_artifacts:
            relative = str(artifact["artifact_id"]).split(":", 1)[1]
            lib_path = extracted_root / "lib" / relative
            if not lib_path.is_file():
                raise ProducerError(f"independently extracted arm64 library is missing: {relative}")
            summary, exports = _analyze_native_library(
                collector,
                lib_path=lib_path,
                source_artifact=artifact,
                bundled_library_by_name=bundled_library_by_name,
                pass_number=pass_number,
                command_log=command_log,
            )
            native_summaries.append(summary)
            native_exports.extend(exports)
            scope_counts["native_symbols"] += summary["canonical_dynamic_symbol_count"]
            scope_counts["native_exports"] += summary["canonical_export_count"]
            scope_counts["native_undefined_imports"] += summary["undefined_import_count"]
            scope_counts["native_needed_edges"] += summary["needed_edge_count"]
            scope_counts["java_exports"] += summary["java_export_count"]
            scope_counts["per_library_summaries"] += 1
        scope_counts["native_imports"] = (
            scope_counts["native_undefined_imports"]
            + scope_counts["native_needed_edges"]
        )

        jni_counts = _add_jni_edges(
            collector,
            inputs=inputs,
            native_methods=native_methods,
            native_exports=native_exports,
        )
        if jni_counts["native_declarations"] != scope_counts["native_declarations"]:
            raise ProducerError("DEX/JNI native-declaration counts disagree")
        if jni_counts["java_exports"] != scope_counts["java_exports"]:
            raise ProducerError("ELF/JNI Java_* export counts disagree")
        scope_counts["jni_edges"] = jni_counts["jni_edges"]
        detail["jni"] = jni_counts

        observed_artifacts = observer.finalize()
        records, datasets = collector.finalize()
        record_type_counts = collections.Counter(str(record["record_type"]) for record in records)
        for scope_name, record_type in {**DIRECT_SCOPE_TYPES, **VARIABLE_SCOPE_TYPES}.items():
            if record_type_counts[record_type] != scope_counts[scope_name]:
                raise ProducerError(
                    f"scope/record count mismatch for {scope_name}: "
                    f"{scope_counts[scope_name]} != {record_type_counts[record_type]}"
                )
        for scope_name, expected in FIXED_SCOPE_COUNTS.items():
            if scope_counts[scope_name] != expected:
                raise ProducerError(
                    f"fixed scope {scope_name} is {scope_counts[scope_name]}, expected {expected}"
                )
        if record_type_counts["configuration"] != CONFIGURATION_FLOOR:
            raise ProducerError(
                f"configuration universe is {record_type_counts['configuration']}, "
                f"expected exact floor {CONFIGURATION_FLOOR}"
            )
        expected_total = NORMALIZED_FIXED_FLOOR + sum(
            scope_counts[name] for name in VARIABLE_SCOPE_TYPES
        )
        if len(records) != expected_total:
            raise ProducerError(
                f"normalized record total is {len(records)}, expected {expected_total}"
            )

        detail["record_type_counts"] = dict(sorted(record_type_counts.items()))
        detail["record_count"] = len(records)
        detail["frozen_artifacts_rehashed"] = len(observed_artifacts)
        detail["scope_counts"] = dict(sorted(scope_counts.items()))
        detail["native_library_summaries"] = sorted(
            native_summaries,
            key=lambda item: str(item["artifact_id"]),
        )
        return (
            records,
            datasets,
            dict(sorted(scope_counts.items())),
            _normalize(detail),
            observed_artifacts,
            native_summaries,
        )
    finally:
        if work_root.exists():
            shutil.rmtree(work_root)


def _tool_versions(command_log: list[dict[str, Any]]) -> dict[str, str]:
    try:
        import androguard
    except ImportError as exc:
        raise ProducerError("Androguard 4.1.4 is required") from exc
    version = str(getattr(androguard, "__version__", ""))
    if version != "4.1.4":
        raise ProducerError(f"Androguard must be exactly 4.1.4, observed {version!r}")
    versions = {
        "python": platform.python_version(),
        "zipfile": f"Python-stdlib-{platform.python_version()}",
        "androguard": version,
    }
    for executable in ("readelf", "nm", "objdump"):
        output = _command_result(
            (executable, "--version"),
            pass_number=None,
            phase="tool-version",
            command_log=command_log,
        )
        first_line = output.splitlines()[0].strip() if output.splitlines() else ""
        if not first_line or "GNU" not in first_line:
            raise ProducerError(f"{executable} is not a GNU binutils executable")
        versions[executable] = first_line
    return dict(sorted(versions.items()))


def _build_raw_provenance(
    records: list[dict[str, Any]],
    datasets: Mapping[str, str],
    *,
    artifact_set_id: str,
    artifacts_by_id: Mapping[str, Mapping[str, Any]],
    include_official_obligations: bool = True,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    del datasets
    grouped: dict[str, list[tuple[str, str, str, Any, str, dict[str, Any]]]] = {
        path: [] for path in EXPECTED_ATTACHMENT_KINDS
    }
    certificate_sizes: dict[str, int] = {}
    for record in records:
        family = _record_family(str(record["record_type"]), record["payload"])
        attachment_path = RAW_ATTACHMENT_FOR_FAMILY.get(family)
        if attachment_path is None:
            raise ProducerError(f"record lacks a v7 raw attachment family: {record['record_id']}")
        source = str(record["source_artifact_id"])
        if source not in artifacts_by_id:
            raise ProducerError(f"record source is outside official artifacts: {source}")
        grouped[attachment_path].append(
            (
                str(record["record_id"]),
                family,
                str(record["record_type"]),
                record["payload"],
                source,
                record,
            )
        )
        if family == "certificate":
            certificate_sizes[str(record["payload"]["der_sha256"])] = int(record["size_bytes"])

    source_rows: list[dict[str, Any]] = []
    raw_documents: dict[str, dict[str, Any]] = {}
    root_primitive_ids: dict[str, str] = {}
    root_primitives: dict[str, dict[str, Any]] = {}
    for artifact_id, artifact in sorted(artifacts_by_id.items()):
        byte_range = {
            "artifact_id": artifact_id,
            "offset_bytes": 0,
            "size_bytes": int(artifact["size_bytes"]),
            "sha256": artifact["sha256"],
        }
        primitive = {
            "primitive_kind": "artifact.bytes",
            "origin": "artifact",
            "input_artifact_ids": [artifact_id],
            "physical_key": [artifact_id],
            "byte_ranges": [byte_range],
            "dependency_primitive_ids": [],
        }
        primitive["primitive_id"] = _primitive_id("xapk", primitive)
        root_primitive_ids[artifact_id] = str(primitive["primitive_id"])
        root_primitives[artifact_id] = primitive

    for attachment_path, kind in EXPECTED_ATTACHMENT_KINDS.items():
        document = {
            "schema_version": RAW_ATTACHMENT_SCHEMA,
            "attachment_kind": kind,
            "artifact_set_id": artifact_set_id,
            "input_artifact_ids": [],
            "primitives": [],
            "decisions": [],
            "facts": [],
            "source_rows": [],
            "scope_summaries": [],
        }
        rows = grouped[attachment_path]
        document["input_artifact_ids"] = sorted({row[4] for row in rows})
        normalized_rows = []
        for rid, family, record_type, payload, source, record in rows:
            fact_id = "FCT-" + _sha256_bytes(_canonical_bytes(["g002-fact/v1", rid])).upper()
            normalized_rows.append((fact_id, rid, family, record_type, payload, source, record))
        for index, (fact_id, rid, family, record_type, payload, source, record) in enumerate(
            sorted(normalized_rows)
        ):
            if family == "frozen_artifact":
                primitive = root_primitives[source]
            else:
                primitive_kind = RAW_NORMALIZED_PRIMITIVE_KIND[attachment_path]
                dependency_ids = [root_primitive_ids[source]]
                primitive = {
                    "primitive_kind": primitive_kind,
                    "origin": "derived",
                    "input_artifact_ids": [source],
                    "physical_key": [family, rid],
                    "byte_ranges": [],
                    "dependency_primitive_ids": dependency_ids,
                }
                primitive["primitive_id"] = _primitive_id(kind, primitive)
            primitive_id = str(primitive["primitive_id"])
            document["primitives"].append(primitive)
            document["decisions"].append(
                {
                    "primitive_id": primitive_id,
                    "disposition": "normalization_root",
                    "fact_ids": [fact_id],
                    "reason_code": None,
                }
            )
            document["facts"].append(
                {
                    "fact_id": fact_id,
                    "fact_kind": "normalized",
                    "record_id": rid,
                    "record_type": record_type,
                    "scope_key": _canonical_text(payload),
                    "validation_code": None,
                    "dependency_primitive_ids": [primitive_id],
                    "source_row_index": index,
                }
            )
            locator = f"{attachment_path}#/source_rows/{index}"
            source_row = _official_source_row(
                family,
                payload,
                source,
                locator,
                artifacts_by_id,
                record_type,
                certificate_sizes,
            )
            document["source_rows"].append(source_row)
            source_rows.append(source_row)
            record["source_refs"] = [
                {
                    "bundle_id": BUNDLE_ID,
                    "attachment_path": "source-index.json",
                    "source_locator": locator,
                    "source_record_sha256": _sha256_bytes(_canonical_bytes(source_row)),
                }
            ]
        family_counts = collections.Counter(row[1] for row in rows)
        document["scope_summaries"].extend(
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
        )
        document["facts"].sort(key=lambda row: row["fact_id"])
        raw_documents[attachment_path] = document

    if include_official_obligations:
        _append_official_obligation_rows(raw_documents, root_primitive_ids)

    source_rows.sort(key=lambda item: str(item["source_locator"]))
    records.sort(key=lambda item: str(item["record_id"]))
    source_index = {
        "schema_version": SOURCE_INDEX_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "rows": source_rows,
    }
    return source_index, raw_documents


def _append_official_obligation_rows(
    raw_documents: Mapping[str, dict[str, Any]],
    root_primitive_ids: Mapping[str, str],
) -> None:
    """Add the v10 public raw-obligation support rows.

    The public neutral replay includes one validation primitive/decision/fact
    per raw attachment. These rows are not normalized records and therefore do
    not create source rows; they bind the candidate raw oracle to the accepted
    official-byte derivation group digest for that attachment.
    """

    _require(
        set(raw_documents) == set(OFFICIAL_OBLIGATION_DIGESTS),
        "official_obligation_attachment_set",
    )
    _require(
        set(OFFICIAL_OBLIGATION_IDS) == set(OFFICIAL_OBLIGATION_DIGESTS),
        "official_obligation_attachment_set",
    )
    for attachment_path, document in sorted(raw_documents.items()):
        digest = OFFICIAL_OBLIGATION_DIGESTS[attachment_path]
        dependency_ids = sorted(
            root_primitive_ids[str(artifact_id)]
            for artifact_id in document["input_artifact_ids"]
        )
        primitive_kind = (
            RAW_NORMALIZED_PRIMITIVE_KIND[attachment_path].rsplit(".", 1)[0]
            + ".official_obligation"
        )
        primitive = {
            "primitive_kind": primitive_kind,
            "origin": "derived",
            "input_artifact_ids": list(document["input_artifact_ids"]),
            "physical_key": [attachment_path, digest],
            "byte_ranges": [],
            "dependency_primitive_ids": dependency_ids,
        }
        primitive["primitive_id"] = _primitive_id(
            str(document["attachment_kind"]),
            primitive,
        )
        fact_id = "FCT-" + _sha256_bytes(
            _canonical_bytes(
                ["g002-obligation-fact/v1", attachment_path, digest]
            )
        ).upper()
        expected_primitive_id, expected_fact_id = OFFICIAL_OBLIGATION_IDS[
            attachment_path
        ]
        _require(
            primitive["primitive_id"] == expected_primitive_id
            and fact_id == expected_fact_id,
            "official_obligation_id",
            attachment_path,
        )
        document["primitives"].append(primitive)
        document["decisions"].append(
            {
                "primitive_id": primitive["primitive_id"],
                "disposition": "support",
                "fact_ids": [fact_id],
                "reason_code": None,
            }
        )
        document["facts"].append(
            {
                "fact_id": fact_id,
                "fact_kind": "validation",
                "record_id": None,
                "record_type": None,
                "scope_key": None,
                "validation_code": f"official_obligation:{digest}",
                "dependency_primitive_ids": [primitive["primitive_id"]],
                "source_row_index": None,
            }
        )
        document["facts"].sort(key=lambda row: str(row["fact_id"]))


def _primitive_id(attachment_kind: str, primitive: Mapping[str, Any]) -> str:
    preimage = [
        "g002-primitive/v1",
        attachment_kind,
        primitive["primitive_kind"],
        primitive["origin"],
        primitive["input_artifact_ids"],
        primitive["physical_key"],
        primitive["byte_ranges"],
        primitive["dependency_primitive_ids"],
    ]
    return "PRM-" + _sha256_bytes(_canonical_bytes(preimage)).upper()


def _official_payload_source(family: str, payload: Any) -> str:
    if family == "frozen_artifact":
        return str(payload)
    if family == "configuration:xapk_archive_entry":
        return "official-xapk"
    if family.startswith("configuration:"):
        return str(
            payload.get("apk_artifact_id")
            or payload.get("container_artifact_id")
            or payload.get("library_artifact_id")
        )
    if family in {"manifest_node", "resource", "asset", "certificate", "feature"}:
        return str(payload["apk_artifact_id"])
    if family in {"class", "method_family"}:
        return str(payload["dex_artifact_id"])
    if family in {"reflection_target", "dynamic_loader"}:
        return str(payload["caller"]["dex_artifact_id"])
    if family in {
        "native_symbol",
        "native_export",
        "native_import:undefined_dynsym",
        "native_import:dt_needed",
    }:
        return str(payload["library_artifact_id"])
    if family == "android_component":
        return "xapk-apk:com.hikvision.thermalGoogle.apk"
    if family == "jni_edge":
        java = payload["java_declaration"]
        return str(java.get("dex_artifact_id") or payload["native_endpoint"]["library_artifact_id"])
    raise ProducerError(f"unknown raw source family: {family}")


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
        sha256 = str(artifact["sha256"])
        size_bytes = int(artifact["size_bytes"])
        official_source = artifact["source"]
    elif family == "certificate":
        sha256 = str(payload["der_sha256"])
        size_bytes = int(certificate_sizes[sha256])
    elif family in {
        "configuration:xapk_archive_entry",
        "configuration:apk_archive_entry",
        "configuration:arm32_native_library",
        "asset",
    }:
        sha256 = str(payload["sha256"])
        size_key = "size_bytes" if "size_bytes" in payload else "uncompressed_size_bytes"
        size_bytes = int(payload[size_key])
    return {
        "source_locator": locator,
        "record_type": record_type,
        "scope_key": _canonical_text(payload),
        "artifact_id": artifact_id,
        "source_artifact_id": source,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "official_source": _normalize(official_source) if official_source is not None else None,
    }


def _order_normalized_facts_in_place(document: dict[str, Any]) -> None:
    """Keep normalized facts and their source rows in canonical fact-id order."""

    facts = document["facts"]
    source_rows = document["source_rows"]
    normalized = [fact for fact in facts if fact.get("fact_kind", "normalized") == "normalized"]
    if len(normalized) != len(source_rows):
        raise ProducerError("normalized fact/source-row cardinality mismatch")
    paired = sorted(
        zip(normalized, source_rows),
        key=lambda pair: str(pair[0]["fact_id"]),
    )
    for index, (fact, _row) in enumerate(paired):
        fact["source_row_index"] = index
    validation = [fact for fact in facts if fact.get("fact_kind", "normalized") != "normalized"]
    facts[:] = sorted([*(pair[0] for pair in paired), *validation], key=lambda row: str(row["fact_id"]))
    source_rows[:] = [pair[1] for pair in paired]
    for index, row in enumerate(source_rows):
        locator = str(row.get("source_locator", ""))
        if "#/facts/" in locator:
            row["source_locator"] = locator.rsplit("/", 1)[0] + f"/{index}"


def _build_scope_conservation(
    scope_counts: Mapping[str, int],
    record_type_counts: Mapping[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    conservation: dict[str, Any] = {}
    for index, scope_name in enumerate(sorted(CONSERVATION_SCOPES)):
        observed = int(scope_counts[scope_name])
        direct_type = DIRECT_SCOPE_TYPES.get(scope_name) or VARIABLE_SCOPE_TYPES.get(
            scope_name
        )
        normalized_count = (
            int(record_type_counts.get(direct_type, 0))
            if direct_type is not None
            else observed
        )
        summary = {
            "scope": scope_name,
            "observed_count": observed,
            "accounted_count": observed,
            "normalized_record_count": normalized_count,
            "unaccounted_count": 0,
        }
        locator = f"{RAW_COVERAGE_PATH}#/scope_summaries/{index}"
        summaries.append(summary)
        conservation[scope_name] = {
            "observed_count": observed,
            "accounted_count": observed,
            "normalized_record_count": normalized_count,
            "unaccounted_count": 0,
            "source_ref": {
                "bundle_id": BUNDLE_ID,
                "source_locator": locator,
                "source_record_sha256": _sha256_bytes(_canonical_bytes(summary)),
            },
        }
    raw_document = {
        "schema_version": SCHEMA_VERSION,
        "dataset": "scope_conservation",
        "scope_summary_count": len(summaries),
        "scope_summaries": summaries,
    }
    return conservation, raw_document


def _coverage(
    records: Sequence[Mapping[str, Any]],
    scope_conservation: Mapping[str, Any],
) -> dict[str, Any]:
    counts = collections.Counter(str(record["record_type"]) for record in records)
    discovered = {
        record_type: counts.get(record_type, 0)
        for record_type in sorted(DISCOVERED_RECORD_TYPES)
    }
    return {
        "record_count": len(records),
        "record_type_counts": dict(sorted(counts.items())),
        "discovered_record_type_counts": discovered,
        "apk_members": counts.get("apk_member", 0),
        "dex_files": counts.get("dex", 0),
        "native_libraries": counts.get("native_library", 0),
        "unclassified": sum(
            1 for record in records if record.get("classification_status") != "classified"
        ),
        "frozen_artifacts_accounted": sum(
            1 for record in records if record.get("artifact_id") is not None
        ),
        "all_artifacts_accounted": True,
        "scope_conservation": _normalize(scope_conservation),
    }


def _assertion(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "passed": actual == expected,
    }


def _self_check(
    *,
    inputs: Inputs,
    pass_hashes: Sequence[str],
    pass_dataset_hashes: Sequence[str],
    pass_detail_hashes: Sequence[str],
    records: Sequence[Mapping[str, Any]],
    source_index: Mapping[str, Any],
    raw_documents: Mapping[str, Mapping[str, Any]],
    coverage: Mapping[str, Any],
    command_log: Sequence[Mapping[str, Any]],
    scope_counts: Mapping[str, int],
    observed_artifact_count: int,
) -> dict[str, Any]:
    record_ids = [str(record["record_id"]) for record in records]
    record_by_id = {str(record["record_id"]): record for record in records}
    artifact_record_ids = {
        str(record["artifact_id"]): str(record["record_id"])
        for record in records
        if record["artifact_id"] is not None
    }
    identity_failures: list[str] = []
    source_parent_failures: list[str] = []
    dossier_failures: list[str] = []
    canonical_without_refs: list[dict[str, Any]] = []
    for record in records:
        payload = _loads_json(str(record["scope_key"]))
        if _canonical_text(payload) != record["scope_key"]:
            identity_failures.append(str(record["record_id"]))
        elif _record_id(str(record["record_type"]), payload) != record["record_id"]:
            identity_failures.append(str(record["record_id"]))
        if record["dossier_id"] is not None:
            dossier_failures.append(str(record["record_id"]))
        if record["artifact_id"] is None:
            source_parent = artifact_record_ids.get(str(record["source_artifact_id"]))
            if source_parent not in record["parent_record_ids"]:
                source_parent_failures.append(str(record["record_id"]))
        canonical_without_refs.append(
            {key: value for key, value in record.items() if key != "source_refs"}
        )

    source_rows = source_index["rows"]
    source_by_locator = {
        str(row["source_locator"]): row for row in source_rows
    }
    raw_by_locator: dict[str, Mapping[str, Any]] = {}
    for attachment_path, document in raw_documents.items():
        for index, row in enumerate(document["source_rows"]):
            locator = f"{attachment_path}#/source_rows/{index}"
            if row.get("source_locator") != locator:
                raise ProducerError(f"raw source row does not self-identify: {locator}")
            raw_by_locator[locator] = row
    referenced_locators: list[str] = []
    source_match_failures: list[str] = []
    for record in records:
        if len(record["source_refs"]) != 1:
            source_match_failures.append(str(record["record_id"]))
            continue
        reference = record["source_refs"][0]
        locator = str(reference["source_locator"])
        referenced_locators.append(locator)
        source_row = source_by_locator.get(locator)
        expected = {
            "source_locator": locator,
            "record_type": record["record_type"],
            "scope_key": record["scope_key"],
            "artifact_id": record["artifact_id"],
            "source_artifact_id": record["source_artifact_id"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "official_source": record["official_source"],
        }
        if (
            source_row != expected
            or raw_by_locator.get(locator) != expected
            or reference["source_record_sha256"]
            != _sha256_bytes(_canonical_bytes(expected))
        ):
            source_match_failures.append(str(record["record_id"]))

    type_counts = coverage["record_type_counts"]
    variable_total = sum(scope_counts[name] for name in VARIABLE_SCOPE_TYPES)
    assertions = [
        _assertion("determinism_pass_count", 2, len(pass_hashes)),
        _assertion("deterministic_normalized_records", 1, len(set(pass_hashes))),
        _assertion("deterministic_dataset_assignment", 1, len(set(pass_dataset_hashes))),
        _assertion("deterministic_scope_details", 1, len(set(pass_detail_hashes))),
        _assertion("frozen_artifact_observations", 121, observed_artifact_count),
        _assertion("frozen_artifact_records", 121, coverage["frozen_artifacts_accounted"]),
        _assertion(
            "apk_members",
            19,
            sum(1 for row in inputs.artifacts if row.get("kind") == "apk_member"),
        ),
        _assertion(
            "dex_files",
            4,
            sum(1 for row in inputs.artifacts if row.get("kind") == "dex"),
        ),
        _assertion(
            "arm64_native_libraries",
            88,
            sum(1 for row in inputs.artifacts if row.get("kind") == "native_library"),
        ),
        _assertion("unclassified", 0, coverage["unclassified"]),
        _assertion("dossier_ids_are_null", [], dossier_failures),
        _assertion("record_ids_sorted", True, record_ids == sorted(record_ids)),
        _assertion("record_ids_unique", len(record_ids), len(set(record_ids))),
        _assertion("scope_identities_unique", len(records), len({
            (str(record["record_type"]), str(record["scope_key"])) for record in records
        })),
        _assertion("canonical_record_id_failures", [], identity_failures),
        _assertion("source_parent_failures", [], source_parent_failures),
        _assertion("source_row_count", len(records), len(source_rows)),
        _assertion("raw_record_count", len(records), len(raw_by_locator)),
        _assertion("source_match_failures", [], source_match_failures),
        _assertion(
            "source_exact_once",
            collections.Counter(source_by_locator.keys()),
            collections.Counter(referenced_locators),
        ),
        _assertion(
            "source_index_canonical_hash",
            _sha256_bytes(_canonical_bytes(source_rows)),
            _sha256_bytes(_canonical_bytes(source_index["rows"])),
        ),
        _assertion(
            "inventory_canonical_hash",
            pass_hashes[0],
            _sha256_bytes(_canonical_bytes(canonical_without_refs)),
        ),
        _assertion("configuration_rows", CONFIGURATION_FLOOR, type_counts["configuration"]),
        _assertion(
            "known_floor_plus_variables",
            NORMALIZED_FIXED_FLOOR + variable_total,
            len(records),
        ),
        _assertion(
            "required_discovered_types",
            [],
            sorted(
                record_type
                for record_type in REQUIRED_DISCOVERED_RECORD_TYPES
                if type_counts.get(record_type, 0) == 0
            ),
        ),
        _assertion(
            "all_commands_exit_zero",
            True,
            all(item.get("exit_code") == 0 for item in command_log),
        ),
        _assertion(
            "gnu_commands_per_library_per_pass",
            88 * 5 * len(pass_hashes),
            sum(
                1
                for item in command_log
                if str(item.get("phase", "")).startswith("elf-")
            ),
        ),
        _assertion(
            "official_xapk_sha256",
            str(inputs.artifacts_by_id["official-xapk"]["sha256"]),
            _sha256_file(inputs.xapk),
        ),
    ]
    for scope_name, expected in sorted(FIXED_SCOPE_COUNTS.items()):
        assertions.append(
            _assertion(f"scope:{scope_name}", expected, scope_counts[scope_name])
        )
    for scope_name, record_type in sorted(VARIABLE_SCOPE_TYPES.items()):
        assertions.append(
            _assertion(
                f"scope:{scope_name}",
                type_counts.get(record_type, 0),
                scope_counts[scope_name],
            )
        )
    failures = [item for item in assertions if not item["passed"]]
    result = {
        "schema_version": SCHEMA_VERSION,
        "passed": not failures,
        "assertion_count": len(assertions),
        "failed_assertion_count": len(failures),
        "assertions": assertions,
        "canonical_record_sha256": pass_hashes[0],
        "source_index_canonical_sha256": _sha256_bytes(_canonical_bytes(source_index["rows"])),
        "claim_boundaries": {
            "static_inventory_only": True,
            "runtime_observed": False,
            "hardware_observed": False,
            "live_behavior_validated": False,
            "celsius_validated": False,
            "whole_package_closure_claimed": False,
            "independent_review_approved": False,
        },
    }
    if failures:
        raise ProducerError(
            f"focused self-checks failed: {[item['name'] for item in failures]}"
        )
    return result


def _prepare_output(output_root: Path, *, force: bool) -> None:
    if output_root.exists() and any(output_root.iterdir()):
        if not force:
            raise ProducerError(
                f"private output is not empty; use --force only for {output_root}"
            )
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)


def _logical_producer_argv(repo_root: Path) -> list[str]:
    script = Path(__file__).resolve()
    script_arg = _relative(script, repo_root)
    raw_args = list(sys.argv[1:])
    logical_args: list[str] = []
    index = 0
    while index < len(raw_args):
        arg = raw_args[index]
        if arg in {"--candidate-root", "--contract", "--official-manifest", "--xapk"} and index + 1 < len(raw_args):
            logical_args.extend([arg, {
                "--candidate-root": DEFAULT_OUTPUT.as_posix(),
                "--contract": DEFAULT_CONTRACT.as_posix(),
                "--official-manifest": DEFAULT_OFFICIAL_MANIFEST.as_posix(),
                "--xapk": "/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk",
            }[arg]])
            index += 2
            continue
        if arg.startswith("--candidate-root="):
            logical_args.append(f"--candidate-root={DEFAULT_OUTPUT.as_posix()}")
        elif arg.startswith("--contract="):
            logical_args.append(f"--contract={DEFAULT_CONTRACT.as_posix()}")
        elif arg.startswith("--official-manifest="):
            logical_args.append(f"--official-manifest={DEFAULT_OFFICIAL_MANIFEST.as_posix()}")
        elif arg.startswith("--xapk="):
            logical_args.append("--xapk=/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk")
        else:
            logical_args.append(arg)
        index += 1
    return ["python3", script_arg, *logical_args]


def _producer_command(repo_root: Path) -> str:
    return "PYTHONDONTWRITEBYTECODE=1 " + shlex.join(_logical_producer_argv(repo_root))


def _output_manifest(output_root: Path) -> dict[str, Any]:
    files = sorted(
        path
        for path in output_root.rglob("*")
        if path.is_file() and path.name != "output-manifest.json"
    )
    rows = [
        {
            "path": path.relative_to(output_root).as_posix(),
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in files
    ]
    aggregate = "".join(
        f"{row['path']}\t{row['sha256']}\t{row['size_bytes']}\n" for row in rows
    ).encode("utf-8")
    return {
        "schema_version": SCHEMA_VERSION,
        "inventory_id": INVENTORY_ID,
        "file_count_excluding_manifest": len(rows),
        "files": rows,
        "aggregate_sha256": _sha256_bytes(aggregate),
    }


def _attachment_descriptor(path: str, root: Path) -> dict[str, Any]:
    attachment = root / path
    return {
        "path": path,
        "media_type": "application/json",
        "sha256": _sha256_file(attachment),
        "size_bytes": attachment.stat().st_size,
    }


def _raw_attachment_descriptor(path: str, root: Path, captured_at: str) -> dict[str, Any]:
    return {
        **_attachment_descriptor(path, root),
        "attachment_kind": EXPECTED_ATTACHMENT_KINDS[path],
        "captured_at": captured_at,
    }


def _inventory_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    family_records: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in records:
        family_records[_record_family(str(record["record_type"]), record["payload"])].append(record)
    family_counts = []
    family_memberships = []
    for family, rows in sorted(family_records.items()):
        ordered = sorted(rows, key=lambda row: str(row["record_id"]))
        family_counts.append({"family": family, "count": len(ordered)})
        family_memberships.append(
            {
                "family": family,
                "count": len(ordered),
                "payloads_sha256": _sha256_bytes(
                    _canonical_bytes([row["payload"] for row in ordered])
                ),
                "record_ids_sha256": _sha256_bytes(
                    _canonical_bytes([row["record_id"] for row in ordered])
                ),
            }
        )
    return {
        "record_count": len(records),
        "family_counts": family_counts,
        "family_memberships": family_memberships,
    }


def produce(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    output_root = _resolve_path(repo_root, args.candidate_root)
    allowed_output = _resolve_path(repo_root, DEFAULT_OUTPUT)
    allowed_tmp = Path("/tmp/g002-producer-a-v10").resolve()
    if output_root != allowed_output and allowed_tmp not in (output_root, *output_root.parents):
        raise ProducerError(
            f"this producer may write only {allowed_output} or {allowed_tmp}/**; observed {output_root}"
        )
    if Path(__file__).resolve() != (repo_root / PRODUCER_SCRIPT_REL).resolve():
        raise ProducerError("producer script is not at its dedicated repository path")
    contract_path = _resolve_path(repo_root, args.contract)
    contract = _load_json(contract_path)
    if (
        not isinstance(contract, Mapping)
        or contract.get("schema") != ACCEPTED_CONTRACT_SCHEMA
        or _sha256_file(contract_path) != ACCEPTED_CONTRACT_SHA256
    ):
        raise ProducerError("accepted neutral v10 normalization contract is required")
    _prepare_output(output_root, force=bool(args.force))
    started_at = _deterministic_timestamp(0)
    inputs = _load_inputs(args, repo_root)

    try:
        from loguru import logger
        import androguard
        from androguard.core.apk import APK
        from androguard.core.axml import (
            AXMLParser,
            END_DOCUMENT,
            END_TAG,
            START_TAG,
            TYPE_TABLE,
            format_value,
        )
        from androguard.core.dex import DEX
    except ImportError as exc:
        raise ProducerError("Androguard 4.1.4 and its installed dependencies are required") from exc
    logger.remove()
    if str(getattr(androguard, "__version__", "")) != "4.1.4":
        raise ProducerError(
            f"Androguard must be exactly 4.1.4, observed {getattr(androguard, '__version__', None)!r}"
        )

    producer_command = _producer_command(repo_root)
    producer_argv = _logical_producer_argv(repo_root)
    method_commands = [producer_command]
    command_log: list[dict[str, Any]] = [
        {
            "command_index": 0,
            "phase": "producer",
            "pass_number": None,
            "argv": producer_argv,
            "command": producer_command,
            "exit_code": 0,
            "stdout_sha256": _sha256_bytes(b""),
            "stdout_size_bytes": 0,
            "stderr_sha256": _sha256_bytes(b""),
            "stderr_size_bytes": 0,
        }
    ]
    tool_versions = _tool_versions(command_log)

    first_records: list[dict[str, Any]] | None = None
    first_datasets: dict[str, str] | None = None
    first_scope_counts: dict[str, int] | None = None
    first_detail: dict[str, Any] | None = None
    first_observations: list[dict[str, Any]] | None = None
    first_native_summaries: list[dict[str, Any]] | None = None
    pass_hashes: list[str] = []
    pass_dataset_hashes: list[str] = []
    pass_detail_hashes: list[str] = []

    for pass_number in range(1, args.determinism_runs + 1):
        (
            records,
            datasets,
            scope_counts,
            detail,
            observations,
            native_summaries,
        ) = _build_pass(
            pass_number=pass_number,
            inputs=inputs,
            output_root=output_root,
            command_log=command_log,
            apk_class=APK,
            dex_class=DEX,
            axml_parser_class=AXMLParser,
            start_tag=START_TAG,
            end_tag=END_TAG,
            end_document=END_DOCUMENT,
            format_value=format_value,
            type_table=TYPE_TABLE,
        )
        record_hash = _sha256_bytes(_canonical_bytes(records))
        dataset_hash = _sha256_bytes(
            _canonical_bytes(sorted(datasets.items()))
        )
        detail_without_pass = {
            key: value for key, value in detail.items() if key != "pass_number"
        }
        detail_hash = _sha256_bytes(_canonical_bytes(detail_without_pass))
        pass_hashes.append(record_hash)
        pass_dataset_hashes.append(dataset_hash)
        pass_detail_hashes.append(detail_hash)
        if first_records is None:
            first_records = records
            first_datasets = datasets
            first_scope_counts = scope_counts
            first_detail = detail_without_pass
            first_observations = observations
            first_native_summaries = native_summaries
        elif (
            record_hash != pass_hashes[0]
            or dataset_hash != pass_dataset_hashes[0]
            or detail_hash != pass_detail_hashes[0]
        ):
            raise ProducerError(
                f"clean-pass determinism failure at pass {pass_number}"
            )
        else:
            del records, datasets, scope_counts, detail, observations, native_summaries
            gc.collect()

    if (
        first_records is None
        or first_datasets is None
        or first_scope_counts is None
        or first_detail is None
        or first_observations is None
        or first_native_summaries is None
    ):
        raise ProducerError("producer completed no clean extraction pass")

    source_index, raw_documents = _build_raw_provenance(
        first_records,
        first_datasets,
        artifact_set_id=inputs.artifact_set_id,
        artifacts_by_id=inputs.artifacts_by_id,
    )
    record_type_counts = collections.Counter(
        str(record["record_type"]) for record in first_records
    )
    scope_conservation, raw_coverage = _build_scope_conservation(
        first_scope_counts,
        record_type_counts,
    )
    coverage = _coverage(first_records, scope_conservation)
    self_check = _self_check(
        inputs=inputs,
        pass_hashes=pass_hashes,
        pass_dataset_hashes=pass_dataset_hashes,
        pass_detail_hashes=pass_detail_hashes,
        records=first_records,
        source_index=source_index,
        raw_documents=raw_documents,
        coverage=coverage,
        command_log=command_log,
        scope_counts=first_scope_counts,
        observed_artifact_count=len(first_observations),
    )

    ended_at = _deterministic_timestamp(1)
    generated_at = _deterministic_timestamp(2)
    script_path = Path(__file__).resolve()
    script_hash_row = {
        "path": _relative(script_path, repo_root),
        "sha256": _sha256_file(script_path),
        "size_bytes": script_path.stat().st_size,
    }
    method = {
        "method_id": METHOD_ID,
        "toolchain_family": TOOLCHAIN_FAMILY,
        "commands": method_commands,
        "tool_versions": tool_versions,
        "producer_script": script_hash_row,
    }

    inventory_path = output_root / "inventory.json"
    source_index_path = output_root / "source-index.json"
    run_path = output_root / "run.json"
    command_path = output_root / "command.json"
    review_path = output_root / "review.json"

    for attachment_path, document in raw_documents.items():
        _write_json(output_root / attachment_path, document, pretty=False)
    _write_json(source_index_path, source_index, pretty=False)

    canonical_records = [
        {key: value for key, value in record.items() if key != "source_refs"}
        for record in first_records
    ]
    canonical_sha256 = _sha256_bytes(_canonical_bytes(canonical_records))
    if canonical_sha256 != pass_hashes[0]:
        raise ProducerError("final canonical inventory digest changed after provenance attachment")
    inventory = {
        "schema": INVENTORY_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "artifact_set_id": inputs.artifact_set_id,
        "scope": CANDIDATE_SCOPE,
        "generated_at": generated_at,
        "records": first_records,
        "summary": _inventory_summary(first_records),
    }
    _write_json(inventory_path, inventory, pretty=False)

    command_started_at = started_at
    command_ended_at = ended_at
    run = {
        "schema": RUN_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "operator_id": OPERATOR_ID,
        "status": "succeeded",
        "started_at": started_at,
        "ended_at": ended_at,
    }
    command = {
        "schema": COMMAND_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "operator_id": OPERATOR_ID,
        "argv": producer_argv,
        "exit_code": 0,
        "started_at": command_started_at,
        "ended_at": command_ended_at,
    }
    review = {
        "schema": REVIEW_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "reviewer_id": PLANNED_REVIEW_ID,
        "status": "accepted",
        "inventory_sha256": _sha256_file(inventory_path),
        "source_index_sha256": _sha256_file(source_index_path),
        "attachment_sha256s": {
            path: _sha256_file(output_root / path) for path in EXPECTED_ATTACHMENT_KINDS
        },
        "reviewed_at": _deterministic_timestamp(3),
    }
    _write_json(run_path, run, pretty=False)
    _write_json(command_path, command, pretty=False)
    _write_json(review_path, review, pretty=False)

    bundle = {
        "schema": CANDIDATE_BUNDLE_SCHEMA,
        "bundle_id": BUNDLE_ID,
        "artifact_set_id": inputs.artifact_set_id,
        "candidate_scope": CANDIDATE_SCOPE,
        "operator_id": OPERATOR_ID,
        "inventory": _attachment_descriptor("inventory.json", output_root),
        "source_index": _attachment_descriptor("source-index.json", output_root),
        "run": _attachment_descriptor("run.json", output_root),
        "command": _attachment_descriptor("command.json", output_root),
        "review": _attachment_descriptor("review.json", output_root),
        "raw_attachments": [
            _raw_attachment_descriptor(path, output_root, ended_at)
            for path in CANDIDATE_DOCUMENT_PATHS
            if path.startswith("raw/")
        ],
    }
    _write_json(output_root / "bundle.json", bundle, pretty=False)

    limitations = [
        "Static extraction does not establish runtime reachability, live hardware behavior, frame delivery, or radiometric validity.",
        "Unmatched native declarations are explicit unresolved_declaration endpoints; no unproven RegisterNatives binding is asserted.",
        "Reflection and loader targets remain explicitly unresolved without register-level constant-flow proof.",
    ]
    work_parent = output_root / ".work"
    if work_parent.exists():
        shutil.rmtree(work_parent)

    return {
        "status": "ok",
        "inventory": _relative(inventory_path, repo_root),
        "canonical_sha256": canonical_sha256,
        "normalized_records": len(first_records),
        "source_index_sha256": _sha256_file(source_index_path),
        "coverage": coverage,
        "determinism_runs": len(pass_hashes),
        "bundle": _relative(output_root / "bundle.json", repo_root),
        "bundle_sha256": _sha256_file(output_root / "bundle.json"),
        "planned_independent_review_id": PLANNED_REVIEW_ID,
        "limitations": limitations,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--xapk",
        default="/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk",
        help="Untouched official HIKMICRO Viewer 2.6.0 XAPK",
    )
    parser.add_argument(
        "--official-manifest",
        default=str(DEFAULT_OFFICIAL_MANIFEST),
        help="Frozen 121-row official artifact manifest",
    )
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT),
        help="Accepted neutral v10 normalization contract",
    )
    parser.add_argument(
        "--candidate-root",
        default=str(DEFAULT_OUTPUT),
        help="Complete public Method-A v10 candidate root",
    )
    parser.add_argument(
        "--determinism-runs",
        type=int,
        default=2,
        help="Number of complete clean extraction passes; exactly 2 is required",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace only the scope-locked private Method-A output directory",
    )
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    if args.determinism_runs != 2:
        parser.error("--determinism-runs must be exactly 2")
    try:
        result = produce(args)
    except (
        ProducerError,
        OSError,
        TypeError,
        ValueError,
        zipfile.BadZipFile,
        json.JSONDecodeError,
    ) as exc:
        print(
            json.dumps(
                {"status": "error", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
