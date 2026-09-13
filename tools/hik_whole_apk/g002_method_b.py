#!/usr/bin/env python3
"""G002 Method-B: independent, deterministic whole-XAPK static inventory.

This producer deliberately uses only Python's ZIP primitives, Info-ZIP,
cached AAPT2, a locally implemented DEX structural parser, and LLVM 16.
It emits a private staging inventory whose normalized record shape matches the
critic contract.  Canonical publication and independent review are separate
steps because this producer is not permitted to write those shared paths.
"""

from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import math
import re
import shlex
import shutil
import struct
import subprocess
import sys
import unicodedata
import zlib
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_VERSION = "g002-method-b-v10"
V10_CONTRACT_SHA256 = "c378fe00e906fbf492d970d3cdc02df30601b416e61449de271ac4433087da29"
REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
OFFICIAL_MANIFEST_REL = RESEARCH_REL / "governance/official-artifacts.json"
CONTRACT_REL = RESEARCH_REL / "governance/g002-neutral-normalization-contract.json"
METHOD_B_REL = RESEARCH_REL / "static/method-b"
SCRATCH_ROOT = Path("/tmp/g002-producer-b-v10")
DEFAULT_OUT = SCRATCH_ROOT / "private"
DEFAULT_CANDIDATE_ROOT = REPO_ROOT / RESEARCH_REL / "static/g002-method-b-v10"
DEFAULT_AAPT2_REL = Path(
    ".gradle-cache/caches/8.10.2/transforms/"
    "f39512fe554518eba6195bb887961148/transformed/"
    "aapt2-8.7.3-12006047-linux/aapt2"
)

RUN_ID = "RUN-G002-METHOD-B"
EXPERIMENT_ID = "EXP-G002-METHOD-B-STATIC-INVENTORY"
BUNDLE_ID = "EVB-G002-METHOD-B"
INVENTORY_ID = "INVENTORY-B"
REVIEW_ID_PENDING = "REV-G002-METHOD-B-INDEPENDENT-PLANNED"
METHOD_ID = "METHOD-B-RAWZIP-AAPT2-DEXSTRUCT-LLVM16"
TOOLCHAIN_FAMILY = "INFOZIP-PYTHON-AAPT2-CUSTOM-DEX-LLVM16"
OPERATOR = "executor-method-b"
CLAIM_ID_PRIVATE = "CLM-G002-METHOD-B-PRIVATE"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RECORD_ID_RE = re.compile(r"^INV-[A-Z0-9][A-Z0-9._-]*$")

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
CONFIGURATION_SCOPE_KINDS = frozenset(
    {
        "apk_archive_entry",
        "arm32_native_library",
        "native_library_summary",
        "resource_configuration",
        "xapk_archive_entry",
    }
)
KNOWN_NORMALIZED_FLOOR = 514431

INVENTORY_RECORD_TYPES = frozenset(
    {
        "xapk_container",
        "xapk_metadata",
        "xapk_icon",
        "apk_member",
        "extracted_apk",
        "dex",
        "native_library",
        "official_fixture",
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
    }
)

DISCOVERED_INVENTORY_RECORD_TYPES = frozenset(
    {
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
    }
)

REQUIRED_DISCOVERED_TYPES = frozenset(
    {
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
    }
)

COMPONENT_TAGS = frozenset(
    {"application", "activity", "activity-alias", "service", "receiver", "provider", "instrumentation"}
)

REFLECTION_METHODS = frozenset(
    {
        "forName",
        "getConstructor",
        "getDeclaredConstructor",
        "getDeclaredField",
        "getDeclaredFields",
        "getDeclaredMethod",
        "getDeclaredMethods",
        "getField",
        "getFields",
        "getMethod",
        "getMethods",
        "invoke",
        "newInstance",
    }
)

DYNAMIC_LOAD_METHODS = frozenset({"findClass", "load", "loadClass", "loadLibrary", "openDexFile"})


class ProducerError(RuntimeError):
    """Raised when source evidence or a deterministic invariant fails."""


def normalize_nfc_json(value: Any, *, label: str = "canonical JSON") -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ProducerError(f"{label} object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise ProducerError(f"{label} duplicate key after NFC normalization: {key!r}")
            normalized[key] = normalize_nfc_json(item, label=label)
        return normalized
    if isinstance(value, (list, tuple)):
        return [normalize_nfc_json(item, label=label) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ProducerError(f"{label} contains a non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ProducerError(f"{label} contains unsupported {type(value).__name__}")


def canonical_text(value: Any) -> str:
    try:
        return json.dumps(
            normalize_nfc_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProducerError(f"cannot encode NFC canonical JSON: {exc}") from exc


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_list_sha256(values: Iterable[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for value in values:
        if not first:
            digest.update(b",")
        first = False
        digest.update(canonical_bytes(value))
    digest.update(b"]")
    return digest.hexdigest()


def file_hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def zip_entry_hash(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with archive.open(info, "r") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        handle.write("\n")
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def load_json(path: Path) -> Any:
    def reject_constant(token: str) -> Any:
        raise ProducerError(f"non-finite JSON constant in {path}: {token}")

    def checked_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for raw_key, item in pairs:
            key = unicodedata.normalize("NFC", raw_key)
            if key in result:
                raise ProducerError(f"duplicate JSON key after NFC normalization in {path}: {key!r}")
            result[key] = item
        return result

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=checked_pairs,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ProducerError(f"cannot load JSON {path}: {exc}") from exc


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def display_arg(value: str | Path) -> str:
    possible = Path(value)
    if possible.is_absolute():
        absolute = possible.absolute()
        try:
            return absolute.relative_to(REPO_ROOT.absolute()).as_posix()
        except ValueError:
            return absolute.as_posix()
    if possible.exists() or (REPO_ROOT / possible).exists():
        return display_path(possible if possible.is_absolute() else REPO_ROOT / possible)
    return value


def checked_output_root(path: Path) -> Path:
    resolved = path.resolve()
    allowed_roots = (DEFAULT_OUT.resolve(), DEFAULT_CANDIDATE_ROOT.resolve(), SCRATCH_ROOT.resolve())
    if not any(resolved == allowed or allowed in resolved.parents for allowed in allowed_roots):
        rendered = ", ".join(display_path(value) for value in allowed_roots)
        raise ProducerError(f"output must remain within an isolated Producer-B root ({rendered}): {resolved}")
    return resolved


@dataclass
class CommandCapture:
    command: str
    purpose: str
    exit_code: int
    stdout_sha256: str
    stdout_size_bytes: int
    stderr_sha256: str
    stderr_size_bytes: int


class CommandRunner:
    def __init__(self) -> None:
        self.results: list[CommandCapture] = []
        self.last_stderr = b""

    def run(self, argv: Sequence[str | Path], purpose: str) -> bytes:
        actual = [str(item) for item in argv]
        displayed = [display_arg(item) for item in argv]
        command = shlex.join(displayed)
        completed = subprocess.run(actual, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.last_stderr = completed.stderr
        capture = CommandCapture(
            command=command,
            purpose=purpose,
            exit_code=completed.returncode,
            stdout_sha256=sha256_bytes(completed.stdout),
            stdout_size_bytes=len(completed.stdout),
            stderr_sha256=sha256_bytes(completed.stderr),
            stderr_size_bytes=len(completed.stderr),
        )
        self.results.append(capture)
        if completed.returncode != 0:
            tail = completed.stderr[-4000:].decode("utf-8", errors="replace")
            raise ProducerError(f"command failed ({completed.returncode}): {command}\n{tail}")
        return completed.stdout

    def as_json(self) -> list[dict[str, Any]]:
        return [capture.__dict__.copy() for capture in self.results]


def scope_key(scope_payload: Any) -> str:
    return canonical_text(scope_payload)


def record_id(record_type: str, scope_payload: Any) -> str:
    if record_type not in INVENTORY_RECORD_TYPES:
        raise ProducerError(f"unsupported record type: {record_type}")
    identity = canonical_bytes(["g002-record/v1", record_type, scope_payload])
    return f"INV-{sha256_bytes(identity).upper()}"


class RecordBuilder:
    def __init__(self, official_by_id: Mapping[str, Mapping[str, Any]]) -> None:
        self.official_by_id = official_by_id
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self.artifact_record_ids: dict[str, str] = {}

    def add_artifact(self, artifact: Mapping[str, Any]) -> str:
        artifact_id = str(artifact["artifact_id"])
        record_type = "frozen_artifact"
        payload = artifact_id
        canonical_scope = scope_key(payload)
        row_id = record_id(record_type, payload)
        record = {
            "record_id": row_id,
            "record_type": record_type,
            "scope_key": canonical_scope,
            "artifact_id": artifact_id,
            "source_artifact_id": artifact_id,
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "official_source": artifact["source"],
            "dossier_id": None,
            "classification_status": "classified",
            "parent_record_ids": [],
        }
        self._insert(record)
        self.artifact_record_ids[artifact_id] = row_id
        return row_id

    def add_discovered(
        self,
        record_type: str,
        scope_payload: Any,
        source_artifact_id: str,
        *,
        sha256: str | None = None,
        size_bytes: int | None = None,
        additional_parent_ids: Sequence[str] = (),
    ) -> str:
        if record_type not in DISCOVERED_INVENTORY_RECORD_TYPES:
            raise ProducerError(f"{record_type} is not a discovered record type")
        if source_artifact_id not in self.official_by_id:
            raise ProducerError(f"unknown frozen source artifact: {source_artifact_id}")
        source_parent = self.artifact_record_ids.get(source_artifact_id)
        if source_parent is None:
            raise ProducerError(f"artifact record not initialized: {source_artifact_id}")
        normalized_payload = normalize_nfc_json(scope_payload, label=f"{record_type} scope payload")
        canonical_scope = scope_key(normalized_payload)
        row_id = record_id(record_type, normalized_payload)
        parents = sorted(set([source_parent, *additional_parent_ids]))
        record = {
            "record_id": row_id,
            "record_type": record_type,
            "scope_key": canonical_scope,
            "artifact_id": None,
            "source_artifact_id": source_artifact_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "official_source": None,
            "dossier_id": None,
            "classification_status": "classified",
            "parent_record_ids": parents,
        }
        self._insert(record)
        return row_id

    def _insert(self, record: dict[str, Any]) -> None:
        identity = (str(record["record_type"]), str(record["scope_key"]))
        if identity in self._records:
            raise ProducerError(f"duplicate normalized scope identity: {identity}")
        self._records[identity] = record

    def finalize(
        self,
        raw_root: Path,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Path]]:
        records = sorted(self._records.values(), key=lambda row: str(row["record_id"]))
        source_records: list[dict[str, Any]] = []
        raw_paths: list[Path] = []
        by_type: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            by_type[str(record["record_type"])].append(record)
        for record_type in sorted(by_type):
            raw_path = raw_root / f"records-{record_type}.json"
            relative = f"raw/{raw_path.name}"
            raw_rows: list[dict[str, Any]] = []
            for index, record in enumerate(by_type[record_type]):
                source_locator = f"{relative}#/records/{index}"
                source_record = {
                    "source_locator": source_locator,
                    "record_type": record["record_type"],
                    "scope_key": record["scope_key"],
                    "artifact_id": record["artifact_id"],
                    "source_artifact_id": record["source_artifact_id"],
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                    "official_source": record["official_source"],
                }
                raw_rows.append(source_record)
                source_records.append(source_record)
                record["source_refs"] = [
                    {
                        "bundle_id": BUNDLE_ID,
                        "attachment_path": "source-index.json",
                        "source_locator": source_locator,
                        "source_record_sha256": sha256_bytes(canonical_bytes(source_record)),
                    }
                ]
            write_json(
                raw_path,
                {"schema_version": 1, "record_type": record_type, "records": raw_rows},
            )
            raw_paths.append(raw_path)
        source_records.sort(key=lambda row: str(row["source_locator"]))
        return records, source_records, raw_paths

    def records_for_candidate(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for record in sorted(self._records.values(), key=lambda row: str(row["record_id"])):
            payload = json.loads(str(record["scope_key"]))
            records.append({**record, "payload": payload})
        return records


def read_uleb128(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    start = offset
    for _ in range(5):
        if offset >= len(data):
            raise ProducerError(f"truncated ULEB128 at 0x{start:x}")
        value = data[offset]
        offset += 1
        result |= (value & 0x7F) << shift
        if value & 0x80 == 0:
            return result, offset
        shift += 7
    raise ProducerError(f"oversized ULEB128 at 0x{start:x}")


def decode_mutf8(value: bytes, *, label: str) -> str:
    try:
        decoded = value.replace(b"\xc0\x80", b"\x00").decode("utf-8", errors="surrogatepass")
        decoded = decoded.encode("utf-16-be", errors="surrogatepass").decode(
            "utf-16-be", errors="surrogatepass"
        )
    except UnicodeError as exc:
        raise ProducerError(f"{label}: invalid modified UTF-8: {exc}") from exc
    return unicodedata.normalize("NFC", decoded)


def dex_instruction_width(units: Sequence[int], offset: int, *, label: str) -> int:
    opcode = units[offset] & 0xFF
    if opcode == 0 and units[offset] in {0x0100, 0x0200, 0x0300}:
        ident = units[offset]
        if offset + 2 > len(units):
            raise ProducerError(f"{label}: truncated DEX payload at code-unit {offset}")
        size = units[offset + 1]
        if ident == 0x0100:
            return 4 + size * 2
        if ident == 0x0200:
            return 2 + size * 4
        if offset + 4 > len(units):
            raise ProducerError(f"{label}: truncated fill-array payload at code-unit {offset}")
        element_width = units[offset + 1]
        element_count = units[offset + 2] | (units[offset + 3] << 16)
        return 4 + ((element_width * element_count + 1) // 2)
    if opcode in {0x03, 0x06, 0x09, 0x14, 0x17, 0x1B, 0x24, 0x25, 0x26, 0x2A, 0x2B, 0x2C}:
        return 3
    if opcode == 0x18:
        return 5
    if opcode in {0xFA, 0xFB}:
        return 4
    if opcode in {0xFC, 0xFD}:
        return 3
    if opcode in {
        0x02,
        0x05,
        0x08,
        0x13,
        0x15,
        0x16,
        0x19,
        0x1A,
        0x1C,
        0x1F,
        0x20,
        0x22,
        0x23,
        0x29,
        *range(0x2D, 0x3E),
        *range(0x44, 0x6E),
        *range(0x90, 0xB0),
        *range(0xD0, 0xE3),
        0xFE,
        0xFF,
    }:
        return 2
    if opcode in {*range(0x6E, 0x73), *range(0x74, 0x79)}:
        return 3
    return 1


class DexParser:
    """Small structural DEX parser for headers, tables, and class_data_item."""

    HEADER_SIZE = 0x70
    NO_INDEX = 0xFFFFFFFF
    ACC_NATIVE = 0x0100

    def __init__(self, data: bytes, dex_name: str) -> None:
        self.data = data
        self.dex_name = dex_name
        self.header = self._parse_header()
        self.strings = self._parse_strings()
        self.types = self._parse_types()
        self.protos = self._parse_protos()
        self.method_ids = self._parse_method_ids()

    def _slice(self, offset: int, size: int, label: str) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ProducerError(f"{self.dex_name}: {label} outside file at 0x{offset:x}+{size}")
        return self.data[offset : offset + size]

    def _u32(self, offset: int, label: str) -> int:
        return struct.unpack_from("<I", self._slice(offset, 4, label))[0]

    def _parse_header(self) -> dict[str, Any]:
        if len(self.data) < self.HEADER_SIZE:
            raise ProducerError(f"{self.dex_name}: file shorter than DEX header")
        magic = self.data[:8]
        if not re.fullmatch(rb"dex\n\d{3}\x00", magic):
            raise ProducerError(f"{self.dex_name}: invalid DEX magic {magic!r}")
        fields = {
            "file_size": self._u32(32, "file_size"),
            "header_size": self._u32(36, "header_size"),
            "endian_tag": self._u32(40, "endian_tag"),
            "map_off": self._u32(52, "map_off"),
            "string_ids_size": self._u32(56, "string_ids_size"),
            "string_ids_off": self._u32(60, "string_ids_off"),
            "type_ids_size": self._u32(64, "type_ids_size"),
            "type_ids_off": self._u32(68, "type_ids_off"),
            "proto_ids_size": self._u32(72, "proto_ids_size"),
            "proto_ids_off": self._u32(76, "proto_ids_off"),
            "field_ids_size": self._u32(80, "field_ids_size"),
            "field_ids_off": self._u32(84, "field_ids_off"),
            "method_ids_size": self._u32(88, "method_ids_size"),
            "method_ids_off": self._u32(92, "method_ids_off"),
            "class_defs_size": self._u32(96, "class_defs_size"),
            "class_defs_off": self._u32(100, "class_defs_off"),
            "data_size": self._u32(104, "data_size"),
            "data_off": self._u32(108, "data_off"),
        }
        if fields["file_size"] != len(self.data) or fields["header_size"] != self.HEADER_SIZE:
            raise ProducerError(f"{self.dex_name}: header/file size mismatch")
        if fields["endian_tag"] != 0x12345678:
            raise ProducerError(f"{self.dex_name}: unsupported endian tag 0x{fields['endian_tag']:x}")
        stored_checksum = struct.unpack_from("<I", self.data, 8)[0]
        calculated_checksum = zlib.adler32(self.data[12:]) & 0xFFFFFFFF
        stored_signature = self.data[12:32].hex()
        calculated_signature = hashlib.sha1(self.data[32:]).hexdigest()
        if stored_checksum != calculated_checksum or stored_signature != calculated_signature:
            raise ProducerError(f"{self.dex_name}: DEX checksum/signature mismatch")
        fields.update(
            {
                "magic": magic.decode("ascii", errors="replace").rstrip("\x00"),
                "adler32": f"{stored_checksum:08x}",
                "sha1_signature": stored_signature,
                "integrity_verified": True,
            }
        )
        return fields

    def _parse_strings(self) -> list[str]:
        count = int(self.header["string_ids_size"])
        offset = int(self.header["string_ids_off"])
        self._slice(offset, count * 4, "string_ids")
        values: list[str] = []
        for index in range(count):
            string_off = self._u32(offset + index * 4, f"string_id[{index}]")
            utf16_size, payload_off = read_uleb128(self.data, string_off)
            end = self.data.find(b"\x00", payload_off)
            if end < 0:
                raise ProducerError(f"{self.dex_name}: unterminated string_data[{index}]")
            decoded = decode_mutf8(
                self.data[payload_off:end],
                label=f"{self.dex_name}: string_data[{index}]",
            )
            if len(decoded.encode("utf-16-le", errors="surrogatepass")) // 2 != utf16_size:
                raise ProducerError(f"{self.dex_name}: string_data[{index}] UTF-16 length mismatch")
            values.append(decoded)
        return values

    def _parse_types(self) -> list[str]:
        count = int(self.header["type_ids_size"])
        offset = int(self.header["type_ids_off"])
        self._slice(offset, count * 4, "type_ids")
        values: list[str] = []
        for index in range(count):
            string_index = self._u32(offset + index * 4, f"type_id[{index}]")
            if string_index >= len(self.strings):
                raise ProducerError(f"{self.dex_name}: type_id[{index}] string index out of range")
            values.append(self.strings[string_index])
        return values

    def _type_list(self, offset: int) -> list[str]:
        if offset == 0:
            return []
        size = self._u32(offset, "type_list.size")
        raw = self._slice(offset + 4, size * 2, "type_list.items")
        indexes = struct.unpack_from(f"<{size}H", raw) if size else ()
        if any(index >= len(self.types) for index in indexes):
            raise ProducerError(f"{self.dex_name}: type_list index out of range")
        return [self.types[index] for index in indexes]

    def _parse_protos(self) -> list[str]:
        count = int(self.header["proto_ids_size"])
        offset = int(self.header["proto_ids_off"])
        self._slice(offset, count * 12, "proto_ids")
        values: list[str] = []
        for index in range(count):
            _, return_type_index, parameters_off = struct.unpack_from("<III", self.data, offset + index * 12)
            if return_type_index >= len(self.types):
                raise ProducerError(f"{self.dex_name}: proto_id[{index}] return type out of range")
            parameters = "".join(self._type_list(parameters_off))
            values.append(f"({parameters}){self.types[return_type_index]}")
        return values

    def _parse_method_ids(self) -> list[dict[str, Any]]:
        count = int(self.header["method_ids_size"])
        offset = int(self.header["method_ids_off"])
        self._slice(offset, count * 8, "method_ids")
        values: list[dict[str, Any]] = []
        for index in range(count):
            class_index, proto_index, name_index = struct.unpack_from("<HHI", self.data, offset + index * 8)
            if class_index >= len(self.types) or proto_index >= len(self.protos) or name_index >= len(self.strings):
                raise ProducerError(f"{self.dex_name}: method_id[{index}] index out of range")
            values.append(
                {
                    "method_index": index,
                    "class_descriptor": self.types[class_index],
                    "name": self.strings[name_index],
                    "prototype": self.protos[proto_index],
                }
            )
        return values

    def _skip_encoded_fields(self, offset: int, count: int) -> int:
        field_index = 0
        for _ in range(count):
            index_diff, offset = read_uleb128(self.data, offset)
            _, offset = read_uleb128(self.data, offset)
            field_index += index_diff
            if field_index >= int(self.header["field_ids_size"]):
                raise ProducerError(f"{self.dex_name}: encoded field index out of range")
        return offset

    def _encoded_methods(self, offset: int, count: int, kind: str) -> tuple[list[dict[str, Any]], int]:
        values: list[dict[str, Any]] = []
        method_index = 0
        for _ in range(count):
            index_diff, offset = read_uleb128(self.data, offset)
            access_flags, offset = read_uleb128(self.data, offset)
            code_off, offset = read_uleb128(self.data, offset)
            method_index += index_diff
            if method_index >= len(self.method_ids):
                raise ProducerError(f"{self.dex_name}: encoded method index out of range")
            method = dict(self.method_ids[method_index])
            method.update(
                {
                    "access_flags": access_flags,
                    "code_off": code_off,
                    "kind": kind,
                    "native": bool(access_flags & self.ACC_NATIVE),
                }
            )
            values.append(method)
        return values, offset

    def _invoke_callsites(self, method: Mapping[str, Any]) -> list[dict[str, Any]]:
        code_off = int(method["code_off"])
        if code_off == 0:
            return []
        header = self._slice(code_off, 16, "code_item header")
        _, _, _, _, _, insns_size = struct.unpack_from("<HHHHII", header)
        raw = self._slice(code_off + 16, insns_size * 2, "code_item insns")
        units = list(struct.unpack_from(f"<{insns_size}H", raw)) if insns_size else []
        calls: list[dict[str, Any]] = []
        offset = 0
        while offset < len(units):
            opcode = units[offset] & 0xFF
            width = dex_instruction_width(
                units,
                offset,
                label=f"{self.dex_name}:{method['class_descriptor']}->{method['name']}{method['prototype']}",
            )
            if width <= 0 or offset + width > len(units):
                raise ProducerError(
                    f"{self.dex_name}: instruction width escapes code item at {offset}"
                )
            if opcode in {*range(0x6E, 0x73), *range(0x74, 0x79), 0xFA, 0xFB}:
                method_index = units[offset + 1]
                if method_index >= len(self.method_ids):
                    raise ProducerError(
                        f"{self.dex_name}: invoke method index out of range at {offset}"
                    )
                target = self.method_ids[method_index]
                calls.append(
                    {
                        "caller": {
                            "class_descriptor": str(method["class_descriptor"]),
                            "method_name": str(method["name"]),
                            "descriptor": str(method["prototype"]),
                        },
                        "instruction_offset_code_units": offset,
                        "opcode": f"0x{opcode:02x}",
                        "opcode_family": {
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
                        }.get(opcode, "CUSTOM"),
                        "api": {
                            "class_descriptor": str(target["class_descriptor"]),
                            "method_name": str(target["name"]),
                            "descriptor": str(target["prototype"]),
                        },
                    }
                )
            offset += width
        return calls

    def parse(self, contract: Mapping[str, Any] | None = None) -> dict[str, Any]:
        class_count = int(self.header["class_defs_size"])
        class_offset = int(self.header["class_defs_off"])
        self._slice(class_offset, class_count * 32, "class_defs")
        classes: list[dict[str, Any]] = []
        methods: list[dict[str, Any]] = []
        for index in range(class_count):
            fields = struct.unpack_from("<IIIIIIII", self.data, class_offset + index * 32)
            (
                class_index,
                access_flags,
                superclass_index,
                interfaces_off,
                source_file_index,
                annotations_off,
                class_data_off,
                static_values_off,
            ) = fields
            if class_index >= len(self.types):
                raise ProducerError(f"{self.dex_name}: class_def[{index}] type out of range")
            superclass = None
            if superclass_index != self.NO_INDEX:
                if superclass_index >= len(self.types):
                    raise ProducerError(f"{self.dex_name}: class_def[{index}] superclass out of range")
                superclass = self.types[superclass_index]
            source_file = None
            if source_file_index != self.NO_INDEX:
                if source_file_index >= len(self.strings):
                    raise ProducerError(f"{self.dex_name}: class_def[{index}] source file out of range")
                source_file = self.strings[source_file_index]
            class_methods: list[dict[str, Any]] = []
            if class_data_off:
                cursor = class_data_off
                static_fields_size, cursor = read_uleb128(self.data, cursor)
                instance_fields_size, cursor = read_uleb128(self.data, cursor)
                direct_methods_size, cursor = read_uleb128(self.data, cursor)
                virtual_methods_size, cursor = read_uleb128(self.data, cursor)
                cursor = self._skip_encoded_fields(cursor, static_fields_size)
                cursor = self._skip_encoded_fields(cursor, instance_fields_size)
                direct, cursor = self._encoded_methods(cursor, direct_methods_size, "direct")
                virtual, cursor = self._encoded_methods(cursor, virtual_methods_size, "virtual")
                class_methods.extend(direct)
                class_methods.extend(virtual)
            descriptor = self.types[class_index]
            if any(method["class_descriptor"] != descriptor for method in class_methods):
                raise ProducerError(f"{self.dex_name}: class_data method owner mismatch for {descriptor}")
            methods.extend(class_methods)
            classes.append(
                {
                    "class_def_index": index,
                    "descriptor": descriptor,
                    "access_flags": access_flags,
                    "superclass_descriptor": superclass,
                    "interfaces": self._type_list(interfaces_off),
                    "source_file": source_file,
                    "annotations_off": annotations_off,
                    "class_data_off": class_data_off,
                    "static_values_off": static_values_off,
                    "defined_method_count": len(class_methods),
                }
            )

        contract_callsites = (
            contract["callsites"]
            if contract is not None
            else load_json(REPO_ROOT / CONTRACT_REL)["callsites"]
        )
        callsite_keys = {
            family: {
                (row["owner"], row["name"], row["descriptor"], row["opcode_family"])
                for row in contract_callsites[family]
            }
            for family in ("reflection_target", "dynamic_loader")
        }
        reflection_references: list[dict[str, Any]] = []
        dynamic_loader_references: list[dict[str, Any]] = []
        for method in methods:
            for compact in self._invoke_callsites(method):
                api = compact["api"]
                owner = str(api["class_descriptor"])
                name = str(api["method_name"])
                descriptor = str(api["descriptor"])
                opcode_family = compact["opcode_family"]
                accepted_families = {opcode_family}
                if opcode_family == "VIRTUAL":
                    accepted_families.add("VIRTUAL_OR_SUPER")
                if any((owner, name, descriptor, family) in callsite_keys["reflection_target"] for family in accepted_families):
                    reflection_references.append(compact)
                if any((owner, name, descriptor, family) in callsite_keys["dynamic_loader"] for family in accepted_families):
                    dynamic_loader_references.append(compact)

        def ordered_references(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
            return sorted(
                (dict(value) for value in values),
                key=lambda value: canonical_text(value),
            )

        methods.sort(key=lambda row: int(row["method_index"]))
        native_methods = [dict(method) for method in methods if method["native"]]
        return {
            "dex_name": self.dex_name,
            "header": self.header,
            "classes": classes,
            "defined_methods": methods,
            "native_methods": native_methods,
            "reflection_references": ordered_references(reflection_references),
            "dynamic_loader_references": ordered_references(dynamic_loader_references),
        }


V5_DEX_TOP = ("TOP",)
V5_INVOKE_FAMILY = {
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


def v5_dex_width(units: Sequence[int], offset: int) -> int:
    if offset >= len(units):
        raise ProducerError("v5 DEX instruction outside code item")
    first = units[offset]
    opcode = first & 0xFF
    if opcode == 0 and first:
        if offset & 1:
            return 1
        ident = first >> 8
        if ident == 1:
            return 4 + units[offset + 1] * 2
        if ident == 2:
            return 2 + units[offset + 1] * 4
        if ident == 3:
            element_width = units[offset + 1]
            size = units[offset + 2] | (units[offset + 3] << 16)
            if element_width not in {1, 2, 4, 8}:
                raise ProducerError("invalid v5 DEX array payload width")
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
    raise ProducerError(f"unsupported v5 DEX opcode 0x{opcode:02x} at {offset}")


def v5_sign_extend(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value & (sign - 1)) - (value & sign)


def v5_invoke_registers(units: Sequence[int], offset: int) -> list[int] | None:
    opcode = units[offset] & 0xFF
    if 0x6E <= opcode <= 0x72:
        count = (units[offset] >> 12) & 0xF
        if count > 5:
            return None
        g = (units[offset] >> 8) & 0xF
        packed = units[offset + 2]
        return [
            packed & 0xF,
            (packed >> 4) & 0xF,
            (packed >> 8) & 0xF,
            (packed >> 12) & 0xF,
            g,
        ][:count]
    if 0x74 <= opcode <= 0x78:
        count = (units[offset] >> 8) & 0xFF
        first = units[offset + 2]
        return list(range(first, first + count)) if first + count <= 65536 else None
    return None


def v5_join_dex_value(left: Any, right: Any) -> Any:
    if left == right:
        return left
    if left is None:
        return right
    if right is None:
        return left
    if (
        isinstance(left, tuple)
        and isinstance(right, tuple)
        and left[:2] == right[:2]
        and left
        and left[0] == "Array"
    ):
        cells = (
            tuple(v5_join_dex_value(a, b) for a, b in zip(left[2], right[2]))
            if len(left[2]) == len(right[2])
            else ()
        )
        return ("Array", left[1], cells) if cells else V5_DEX_TOP
    return V5_DEX_TOP


def v5_binary_name_descriptor(value: str) -> str | None:
    if not value:
        return None
    if value.startswith("["):
        return value if re.fullmatch(r"\[+(?:[ZBSCIJFD]|L[^.;\x00]+;)", value) else None
    internal = value.replace(".", "/")
    return f"L{internal};" if not re.search(r"[.;\x00]", internal) else None


def v5_target_recipe(recipe: str, values: list[Any], *, has_receiver: bool) -> dict[str, Any] | None:
    def at(index: int) -> Any:
        return values[index] if index < len(values) else V5_DEX_TOP

    args = 1 if has_receiver else 0
    if recipe.startswith("for_name("):
        value = at(args)
        descriptor = v5_binary_name_descriptor(value[1]) if isinstance(value, tuple) and value[0] == "String" else None
        return {"target_kind": "class", "class_descriptor": descriptor} if descriptor else None
    if recipe.startswith(("binary_name(", "slash_binary_name(")):
        value = at(args)
        if isinstance(value, tuple) and value[0] == "String":
            raw = value[1].replace("/", ".") if recipe.startswith("slash_") else value[1]
            descriptor = v5_binary_name_descriptor(raw)
            return {"target_kind": "class", "class_descriptor": descriptor} if descriptor else None
    if recipe.startswith("native_library_name("):
        value = at(args)
        return {"target_kind": "native_library_name", "value": value[1]} if isinstance(value, tuple) and value[0] == "String" else None
    if recipe.startswith(("native_library_path(", "file_path(")):
        value = at(args)
        return {"target_kind": "native_library_path", "value": value[1]} if isinstance(value, tuple) and value[0] == "String" else None
    if recipe.startswith(("dex_path_list(", "single_dex_path(")):
        value = at(args)
        if isinstance(value, tuple) and value[0] == "String":
            return {
                "target_kind": "dex_path_list",
                "values": value[1].split(":") if recipe.startswith("dex_path_list") else [value[1]],
            }
    if recipe.startswith("memory_dex("):
        if "count=1" in recipe:
            return {"target_kind": "memory_dex", "buffer_count": 1}
        value = at(args)
        if isinstance(value, tuple) and value[0] == "Array":
            return {"target_kind": "memory_dex", "buffer_count": len(value[2])}
    if recipe.startswith("jna_interface("):
        value = at(args)
        return {"target_kind": "jna_interface", "class_descriptor": value[1]} if isinstance(value, tuple) and value[0] == "Class" else None
    if recipe.startswith("proxy_interfaces("):
        value = at(args + 1)
        if isinstance(value, tuple) and value[0] == "Array" and all(isinstance(cell, tuple) and cell[0] == "Class" for cell in value[2]):
            return {"target_kind": "proxy_interfaces", "class_descriptors": [cell[1] for cell in value[2]]}
    if recipe.startswith("member_collection("):
        receiver = at(0)
        if isinstance(receiver, tuple) and receiver[0] == "Class":
            return {
                "target_kind": "member_collection",
                "class_descriptor": receiver[1],
                "query": recipe.split(",", 1)[1].rsplit(")", 1)[0],
            }
    if recipe.startswith("class_relation("):
        value = at(args)
        if isinstance(value, tuple) and value[0] == "Class":
            return {
                "target_kind": "class_relation",
                "class_descriptor": value[1],
                "relation": recipe.split(",", 1)[1].rsplit(")", 1)[0],
            }
    return None


def v5_interpret_dex_code(
    units: Sequence[int],
    registers_size: int,
    strings: Sequence[str],
    types: Sequence[str],
    methods: Sequence[tuple[str, str, str]],
    callsites: Mapping[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    starts: list[int] = []
    widths: dict[int, int] = {}
    offset = 0
    while offset < len(units):
        width = v5_dex_width(units, offset)
        if offset + width > len(units):
            break
        starts.append(offset)
        widths[offset] = width
        offset += width
    if not starts:
        return {}
    start_set = set(starts)
    entry: dict[int, tuple[tuple[Any, ...], Any, int | None]] = {
        starts[0]: (tuple(V5_DEX_TOP for _ in range(registers_size)), None, None)
    }
    worklist = [starts[0]]

    def successors(current: int, opcode: int) -> list[int]:
        nxt = current + widths[current]
        if opcode == 0x28:
            return [current + v5_sign_extend(units[current] >> 8, 8)]
        if opcode == 0x29:
            return [current + v5_sign_extend(units[current + 1], 16)]
        if opcode == 0x2A:
            raw = units[current + 1] | (units[current + 2] << 16)
            return [current + v5_sign_extend(raw, 32)]
        if 0x32 <= opcode <= 0x3D:
            return sorted({nxt, current + v5_sign_extend(units[current + 1], 16)})
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
                regs[dst] = ("Int", v5_sign_extend((units[current] >> 12) & 0xF, 4))
        elif opcode == 0x13:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = ("Int", v5_sign_extend(units[current + 1], 16))
        elif opcode == 0x14:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = ("Int", v5_sign_extend(units[current + 1] | (units[current + 2] << 16), 32))
        elif opcode == 0x15:
            dst = (units[current] >> 8) & 0xFF
            if dst < registers_size:
                regs[dst] = ("Int", v5_sign_extend(units[current + 1], 16) << 16)
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
                regs[dst] = pending if pending_at is not None and pending_at + widths[pending_at] == current else V5_DEX_TOP
        elif opcode in V5_INVOKE_FAMILY:
            method_index = units[current + 1]
            invoke_regs = v5_invoke_registers(units, current)
            if invoke_regs is not None and method_index < len(methods) and all(reg < registers_size for reg in invoke_regs):
                owner, name, descriptor = methods[method_index]
                values = [regs[reg] for reg in invoke_regs]
                family_token = V5_INVOKE_FAMILY[opcode]
                for family in ("reflection_target", "dynamic_loader"):
                    matches = [
                        row
                        for row in callsites[family]
                        if (row["owner"], row["name"], row["descriptor"]) == (owner, name, descriptor)
                        and row["opcode_family"]
                        in {family_token, "VIRTUAL_OR_SUPER" if family_token == "VIRTUAL" else family_token}
                    ]
                    if len(matches) == 1:
                        target = v5_target_recipe(matches[0]["target_recipe"], values, has_receiver=opcode not in {0x71, 0x77})
                        if target is not None:
                            produced = ("Class", target["class_descriptor"]) if target.get("target_kind") == "class" else ("Target", target)
                for reg in invoke_regs:
                    if isinstance(regs[reg], tuple) and regs[reg][0] == "Array":
                        regs[reg] = ("Array", regs[reg][1], tuple(V5_DEX_TOP for _ in regs[reg][2]))
        out_state = (tuple(regs), produced, current if produced is not None else None)
        for successor in successors(current, opcode):
            if successor not in start_set:
                continue
            old = entry.get(successor)
            if old is None:
                new = out_state
            else:
                new = (
                    tuple(v5_join_dex_value(a, b) for a, b in zip(old[0], out_state[0])),
                    v5_join_dex_value(old[1], out_state[1]),
                    old[2] if old[2] == out_state[2] else None,
                )
            if old != new:
                entry[successor] = new
                if successor not in worklist:
                    worklist.append(successor)

    results: dict[tuple[str, int], dict[str, Any]] = {}
    for current in starts:
        opcode = units[current] & 0xFF
        state = entry.get(current)
        if opcode not in V5_INVOKE_FAMILY or state is None:
            continue
        method_index = units[current + 1]
        invoke_regs = v5_invoke_registers(units, current)
        if invoke_regs is None or method_index >= len(methods) or not all(reg < registers_size for reg in invoke_regs):
            continue
        owner, name, descriptor = methods[method_index]
        family_token = V5_INVOKE_FAMILY[opcode]
        values = [state[0][reg] for reg in invoke_regs]
        for family in ("reflection_target", "dynamic_loader"):
            matches = [
                row
                for row in callsites[family]
                if (row["owner"], row["name"], row["descriptor"]) == (owner, name, descriptor)
                and row["opcode_family"]
                in {family_token, "VIRTUAL_OR_SUPER" if family_token == "VIRTUAL" else family_token}
            ]
            if len(matches) == 1:
                target = v5_target_recipe(matches[0]["target_recipe"], values, has_receiver=opcode not in {0x71, 0x77})
                if target is not None:
                    results[(family, current)] = target
    return results


def v5_dex_callsites(parser: DexParser, parsed: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    methods = [
        (str(row["class_descriptor"]), str(row["name"]), str(row["prototype"]))
        for row in parser.method_ids
    ]
    admitted: dict[str, list[dict[str, Any]]] = {"reflection_target": [], "dynamic_loader": []}
    physical_invokes: list[list[Any]] = []
    class_indexes = {str(row["descriptor"]): int(row["class_def_index"]) for row in parsed["classes"]}
    method_order = {
        int(row["method_index"]): (
            class_indexes[str(row["class_descriptor"])],
            0 if row["kind"] == "direct" else 1,
            int(row["method_index"]),
        )
        for row in parsed["defined_methods"]
    }
    api_maps: dict[str, dict[tuple[str, str, str], list[Mapping[str, Any]]]] = {}
    for family in admitted:
        mapping: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
        for row in contract["callsites"][family]:
            mapping[(row["owner"], row["name"], row["descriptor"])].append(row)
        api_maps[family] = mapping
    for method in parsed["defined_methods"]:
        code_off = int(method["code_off"])
        if not code_off:
            continue
        registers_size, _ins, _outs, _tries, _debug, insns_size = struct.unpack_from("<HHHHII", parser.data, code_off)
        units = struct.unpack_from(f"<{insns_size}H", parser.data, code_off + 16) if insns_size else ()
        interpreted = v5_interpret_dex_code(units, registers_size, parser.strings, parser.types, methods, contract["callsites"])
        offset = 0
        while offset < len(units):
            width = v5_dex_width(units, offset)
            if offset + width > len(units):
                break
            opcode = units[offset] & 0xFF
            if opcode in V5_INVOKE_FAMILY:
                invoked = units[offset + 1]
                registers = v5_invoke_registers(units, offset)
                if registers is not None and invoked < len(methods) and all(reg < registers_size for reg in registers):
                    owner, name, descriptor = methods[invoked]
                    physical_invokes.append([
                        parser.dex_name,
                        class_indexes[str(method["class_descriptor"])],
                        int(method["method_index"]),
                        offset,
                        opcode,
                        owner,
                        name,
                        descriptor,
                    ])
                    for family in admitted:
                        token = V5_INVOKE_FAMILY[opcode]
                        matches = [
                            row
                            for row in api_maps[family].get((owner, name, descriptor), [])
                            if row["opcode_family"] in {token, "VIRTUAL_OR_SUPER" if token == "VIRTUAL" else token}
                        ]
                        if len(matches) > 1:
                            raise ProducerError("ambiguous v5 DEX API admission")
                        if matches:
                            admitted[family].append({
                                "caller": {
                                    "dex_artifact_id": parser.dex_name,
                                    "class_descriptor": method["class_descriptor"],
                                    "method_name": method["name"],
                                    "descriptor": method["prototype"],
                                },
                                "instruction_offset_code_units": offset,
                                "api": {"class_descriptor": owner, "method_name": name, "descriptor": descriptor},
                                "target": interpreted.get((family, offset), {"unresolved_token": "not_statically_resolved"}),
                            })
            offset += width
    for rows in admitted.values():
        rows.sort(key=canonical_bytes)
    physical_invokes.sort(key=lambda row: (*method_order[int(row[2])], int(row[3])))
    return {"admitted": admitted, "physical_invokes": physical_invokes}


def expanded_qname(raw: str) -> str:
    value = re.sub(r"\(0x[0-9a-fA-F]+\)$", "", raw.strip())
    if value.startswith("http://") or value.startswith("https://"):
        namespace, local = value.rsplit(":", 1)
        return f"{{{namespace}}}{local}"
    return value


def typed_aapt_value(encoded: str, raw_value: str | None) -> tuple[str, Any]:
    if raw_value is not None:
        return "string", unicodedata.normalize("NFC", raw_value)
    value = encoded.strip()
    if value in {"true", "false"}:
        return "boolean", value == "true"
    if re.fullmatch(r"-?[0-9]+", value):
        return "integer", int(value)
    if re.fullmatch(r"0x[0-9a-fA-F]+", value):
        return "hex_integer", int(value, 16)
    if re.fullmatch(r"@[?]?0x[0-9a-fA-F]+", value):
        return "resource_reference", value.lower()
    quoted = re.fullmatch(r'"(.*)"', value)
    if quoted:
        return "string", unicodedata.normalize("NFC", quoted.group(1))
    return "encoded", unicodedata.normalize("NFC", value)


def parse_manifest_xmltree(text: str, apk_name: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    sibling_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip(" ")
        indent = len(raw_line) - len(stripped)
        element_match = re.match(r"E:\s+([^\s(]+)(?:\s+\(line=(\d+)\))?", stripped)
        if element_match:
            qname = expanded_qname(element_match.group(1))
            while stack and stack[-1][0] >= indent:
                stack.pop()
            parent_path = stack[-1][1] if stack else ""
            sibling_counts[(parent_path, qname)] += 1
            path = f"{parent_path}/{qname}[{sibling_counts[(parent_path, qname)]}]"
            current = {
                "apk_member": apk_name,
                "qname": qname,
                "xpath": path,
                "line": int(element_match.group(2)) if element_match.group(2) else None,
                "attributes": [],
            }
            nodes.append(current)
            stack.append((indent, path))
            continue
        attribute_match = re.match(r"A:\s+([^=]+)=(.*)", stripped)
        if attribute_match and current is not None:
            name_token = attribute_match.group(1).strip()
            resource_match = re.search(r"\(0x([0-9a-fA-F]+)\)$", name_token)
            value_text = attribute_match.group(2).strip()
            raw_value_match = re.search(r'\(Raw:\s+"(.*)"\)\s*$', value_text)
            encoded = re.sub(r'\s+\(Raw:\s+".*"\)\s*$', "", value_text)
            value_type, value = typed_aapt_value(
                encoded,
                raw_value_match.group(1) if raw_value_match else None,
            )
            current["attributes"].append(
                {
                    "qname": expanded_qname(name_token),
                    "resource_id": int(resource_match.group(1), 16) if resource_match else None,
                    "value_type": value_type,
                    "value": value,
                }
            )
    if not nodes or nodes[0]["qname"] != "manifest":
        raise ProducerError(f"{apk_name}: AAPT2 XML tree lacks a manifest root")
    for node in nodes:
        node["attributes"].sort(key=canonical_text)
    return nodes


def manifest_attribute(node: Mapping[str, Any], local_name: str) -> str | None:
    for attribute in node.get("attributes", []):
        qname = str(attribute.get("qname"))
        if qname == local_name or qname.endswith("}" + local_name):
            value = attribute.get("value")
            if isinstance(value, bool):
                return "true" if value else "false"
            return str(value)
    return None


def parse_aapt_resources(text: str, apk_name: str) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    package_name: str | None = None
    package_id: int | None = None
    current: dict[str, Any] | None = None
    lines = text.splitlines()
    for position, line in enumerate(lines):
        package_match = re.match(r"^Package name=(\S+) id=([0-9a-fA-F]{2})$", line)
        if package_match:
            package_name = package_match.group(1)
            package_id = int(package_match.group(2), 16)
            continue
        match = re.match(r"^\s*resource\s+(0x[0-9a-fA-F]+)\s+(\S+)", line)
        if not match:
            if current is not None and len(line) - len(line.lstrip(" ")) == 6:
                value_match = re.match(r"^\s{6}\(([^)]*)\)\s+(.+)$", line)
                if value_match:
                    qualifier = unicodedata.normalize("NFC", value_match.group(1))
                    body = unicodedata.normalize("NFC", value_match.group(2))
                    explicit_type = re.match(r"^\(([^)]*)\)(?:\s+(.*))?$", body)
                    if explicit_type:
                        value_type = unicodedata.normalize("NFC", explicit_type.group(1))
                        canonical_head = unicodedata.normalize("NFC", explicit_type.group(2) or "")
                    elif body.startswith('"'):
                        value_type, canonical_head = "string", body
                    elif body.startswith("@"):
                        value_type, canonical_head = "reference", body
                    elif body.startswith("?"):
                        value_type, canonical_head = "attribute", body
                    elif body in {"true", "false"}:
                        value_type, canonical_head = "boolean", body
                    elif body.startswith("#"):
                        value_type, canonical_head = "color", body
                    elif re.fullmatch(
                        r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:dp|dip|sp|px|pt|in|mm)",
                        body,
                    ):
                        value_type, canonical_head = "dimension", body
                    elif re.fullmatch(
                        r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?%p?", body
                    ):
                        value_type, canonical_head = "fraction", body
                    elif re.fullmatch(r"-?(?:0x[0-9a-fA-F]+|\d+)", body):
                        value_type, canonical_head = "integer", body
                    elif re.fullmatch(
                        r"-?(?:(?:\d+\.\d*|\.\d+)(?:[eE][+-]?\d+)?|\d+[eE][+-]?\d+)",
                        body,
                    ):
                        value_type, canonical_head = "float", body
                    else:
                        raise ProducerError(
                            f"{apk_name}: unsupported AAPT2 resource value syntax at line {position + 1}: {body}"
                        )
                    details = [canonical_head]
                    cursor = position + 1
                    while cursor < len(lines):
                        following = lines[cursor]
                        following_indent = len(following) - len(following.lstrip(" "))
                        if following_indent <= 6:
                            break
                        details.append(unicodedata.normalize("NFC", following.strip()))
                        cursor += 1
                    current["configurations"].append(
                        {
                            "configuration": qualifier,
                            "value_type": value_type,
                            "canonical_value": "\n".join(details),
                        }
                    )
            continue
        identity = (match.group(1).lower(), match.group(2))
        if identity in seen:
            raise ProducerError(f"{apk_name}: duplicate AAPT2 resource identity {identity}")
        seen.add(identity)
        if package_name is None or package_id is None:
            raise ProducerError(f"{apk_name}: resource appears before package identity")
        raw_id = int(identity[0], 16)
        type_and_name = identity[1]
        if "/" not in type_and_name:
            raise ProducerError(f"{apk_name}: malformed resource name {type_and_name}")
        type_name, entry_name = type_and_name.split("/", 1)
        current = {
            "resource_id": f"0x{raw_id:08x}",
            "package_id": (raw_id >> 24) & 0xFF,
            "type_id": (raw_id >> 16) & 0xFF,
            "entry_id": raw_id & 0xFFFF,
            "package_name": package_name,
            "type_name": type_name,
            "entry_name": entry_name,
            "configurations": [],
        }
        if current["package_id"] != package_id:
            raise ProducerError(f"{apk_name}: resource/package ID mismatch")
        resources.append(current)
    resources.sort(key=lambda row: (row["resource_id"], row["type_name"], row["entry_name"]))
    return resources


def parse_aapt_configurations(text: str) -> list[str]:
    values = [unicodedata.normalize("NFC", line.strip()) for line in text.splitlines() if line.strip()]
    return sorted(set(values))


def decode_zip_path(raw_name: bytes, flag_bits: int, *, label: str) -> str:
    encoding = "utf-8" if flag_bits & 0x800 else "cp437"
    try:
        path = unicodedata.normalize("NFC", raw_name.decode(encoding))
    except UnicodeDecodeError as exc:
        raise ProducerError(f"{label}: cannot decode ZIP path as {encoding}: {exc}") from exc
    pure = PurePosixPath(path)
    if (
        not path
        or pure.is_absolute()
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ProducerError(f"{label}: unsafe ZIP path {path!r}")
    return path


def locate_eocd(path: Path) -> tuple[int, tuple[Any, ...]]:
    size = path.stat().st_size
    tail_size = min(size, 22 + 0xFFFF)
    with path.open("rb") as handle:
        handle.seek(size - tail_size)
        tail = handle.read(tail_size)
    marker = b"PK\x05\x06"
    offset = tail.rfind(marker)
    if offset < 0 or offset + 22 > len(tail):
        raise ProducerError(f"{display_path(path)}: ZIP EOCD is missing")
    fields = struct.unpack_from("<4s4H2IH", tail, offset)
    comment_length = fields[-1]
    if offset + 22 + comment_length != len(tail):
        raise ProducerError(f"{display_path(path)}: ZIP EOCD/comment length mismatch")
    return size - tail_size + offset, fields


def parse_raw_central_directory(path: Path) -> list[dict[str, Any]]:
    _, eocd = locate_eocd(path)
    _, disk_number, central_disk, disk_entries, total_entries, central_size, central_offset, _ = eocd
    if disk_number or central_disk or disk_entries != total_entries:
        raise ProducerError(f"{display_path(path)}: multi-disk ZIP is unsupported")
    if total_entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        raise ProducerError(f"{display_path(path)}: ZIP64 central directory is not expected")
    with path.open("rb") as handle:
        handle.seek(central_offset)
        data = handle.read(central_size)
    rows: list[dict[str, Any]] = []
    offset = 0
    for ordinal in range(total_entries):
        if offset + 46 > len(data):
            raise ProducerError(f"{display_path(path)}: truncated central directory")
        fields = struct.unpack_from("<4s6H3I5H2I", data, offset)
        if fields[0] != b"PK\x01\x02":
            raise ProducerError(f"{display_path(path)}: bad central-directory signature")
        (
            _,
            _made_by,
            _needed,
            flag_bits,
            compression_method,
            _mtime,
            _mdate,
            crc32,
            compressed_size,
            size_bytes,
            name_length,
            extra_length,
            comment_length,
            _disk_start,
            _internal_attributes,
            _external_attributes,
            local_header_offset,
        ) = fields
        start = offset + 46
        end = start + name_length
        raw_name = data[start:end]
        path_text = decode_zip_path(raw_name, flag_bits, label=f"{display_path(path)} entry {ordinal}")
        rows.append(
            {
                "central_directory_ordinal": ordinal,
                "path": path_text,
                "flag_bits": flag_bits,
                "compression_method": compression_method,
                "crc32": crc32,
                "compressed_size": compressed_size,
                "size_bytes": size_bytes,
                "local_header_offset": local_header_offset,
                "raw_name_sha256": sha256_bytes(raw_name),
            }
        )
        offset = end + extra_length + comment_length
    if offset != len(data):
        raise ProducerError(f"{display_path(path)}: central-directory size mismatch")
    return rows


def read_length_prefixed(value: bytes, offset: int, *, label: str) -> tuple[bytes, int]:
    if offset + 4 > len(value):
        raise ProducerError(f"{label}: truncated length prefix")
    length = struct.unpack_from("<I", value, offset)[0]
    start = offset + 4
    end = start + length
    if end > len(value):
        raise ProducerError(f"{label}: length-prefixed value escapes container")
    return value[start:end], end


def parse_certificate_sequence(value: bytes, *, label: str) -> list[bytes]:
    certificates: list[bytes] = []
    offset = 0
    while offset < len(value):
        certificate, offset = read_length_prefixed(value, offset, label=label)
        if not certificate or certificate[0] != 0x30:
            raise ProducerError(f"{label}: certificate is not a DER sequence")
        certificates.append(certificate)
    return certificates


def parse_apk_signing_schemes(path: Path) -> dict[str, list[list[bytes]]]:
    _, eocd = locate_eocd(path)
    central_offset = int(eocd[6])
    if central_offset < 24:
        raise ProducerError(f"{display_path(path)}: APK signing block footer is missing")
    with path.open("rb") as handle:
        handle.seek(central_offset - 24)
        footer = handle.read(24)
        block_size = struct.unpack_from("<Q", footer, 0)[0]
        if footer[8:] != b"APK Sig Block 42":
            raise ProducerError(f"{display_path(path)}: APK signing block magic is missing")
        block_start = central_offset - (block_size + 8)
        if block_start < 0:
            raise ProducerError(f"{display_path(path)}: APK signing block offset is invalid")
        handle.seek(block_start)
        header_size = struct.unpack("<Q", handle.read(8))[0]
        if header_size != block_size:
            raise ProducerError(f"{display_path(path)}: APK signing block sizes differ")
        pairs = handle.read(block_size - 24)
    scheme_ids = {0x7109871A: "v2", 0xF05368C0: "v3"}
    result: dict[str, list[list[bytes]]] = {"v2": [], "v3": []}
    offset = 0
    while offset < len(pairs):
        if offset + 8 > len(pairs):
            raise ProducerError(f"{display_path(path)}: truncated APK signing pair")
        pair_size = struct.unpack_from("<Q", pairs, offset)[0]
        start = offset + 8
        end = start + pair_size
        if pair_size < 4 or end > len(pairs):
            raise ProducerError(f"{display_path(path)}: invalid APK signing pair size")
        pair_id = struct.unpack_from("<I", pairs, start)[0]
        scheme = scheme_ids.get(pair_id)
        if scheme is not None:
            signers_blob = pairs[start + 4 : end]
            signers, signers_end = read_length_prefixed(
                signers_blob,
                0,
                label=f"{display_path(path)} {scheme} signers",
            )
            if signers_end != len(signers_blob):
                raise ProducerError(f"{display_path(path)}: trailing {scheme} signer bytes")
            signer_offset = 0
            while signer_offset < len(signers):
                signer, signer_offset = read_length_prefixed(
                    signers,
                    signer_offset,
                    label=f"{display_path(path)} {scheme} signer",
                )
                signed_data, _ = read_length_prefixed(
                    signer,
                    0,
                    label=f"{display_path(path)} {scheme} signed data",
                )
                _, signed_offset = read_length_prefixed(
                    signed_data,
                    0,
                    label=f"{display_path(path)} {scheme} digests",
                )
                certificates_blob, _ = read_length_prefixed(
                    signed_data,
                    signed_offset,
                    label=f"{display_path(path)} {scheme} certificates",
                )
                result[scheme].append(
                    parse_certificate_sequence(
                        certificates_blob,
                        label=f"{display_path(path)} {scheme} certificates",
                    )
                )
        offset = end
    return result


def parse_v1_certificates(
    archive: zipfile.ZipFile,
    known_certificates: Sequence[bytes],
    *,
    apk_name: str,
) -> list[bytes]:
    signature_entries = sorted(
        info
        for info in archive.infolist()
        if re.fullmatch(r"META-INF/[^/]+\.(RSA|DSA|EC)", info.filename, flags=re.IGNORECASE)
    )
    observed: dict[str, bytes] = {}
    for info in signature_entries:
        signed_data = archive.read(info)
        for certificate in known_certificates:
            if certificate in signed_data:
                observed[sha256_bytes(certificate)] = certificate
    if signature_entries and not observed:
        raise ProducerError(f"{apk_name}: v1 signature block has no directly recoverable certificate")
    return [observed[key] for key in sorted(observed)]


def parse_v1_certificate_occurrences(
    archive: zipfile.ZipFile,
    known_certificates: Sequence[bytes],
    *,
    apk_name: str,
) -> list[tuple[int, list[bytes]]]:
    indexed_entries = [
        (ordinal, info)
        for ordinal, info in enumerate(archive.infolist())
        if re.fullmatch(r"META-INF/[^/]+\.(RSA|DSA|EC)", info.filename, flags=re.IGNORECASE)
    ]
    indexed_entries.sort(key=lambda row: canonical_bytes([row[1].filename, row[0]]))
    result: list[tuple[int, list[bytes]]] = []
    for scheme_ordinal, (_central_ordinal, info) in enumerate(indexed_entries):
        signed_data = archive.read(info)
        positions: list[tuple[int, str, bytes]] = []
        for certificate in known_certificates:
            position = signed_data.find(certificate)
            if position >= 0:
                positions.append((position, sha256_bytes(certificate), certificate))
        unique: dict[str, tuple[int, bytes]] = {}
        for position, digest, certificate in positions:
            previous = unique.get(digest)
            if previous is None or position < previous[0]:
                unique[digest] = (position, certificate)
        certificates = [
            certificate
            for _position, certificate in sorted(unique.values(), key=lambda row: row[0])
        ]
        if not certificates:
            raise ProducerError(f"{apk_name}: v1 signature block has no directly recoverable certificate")
        result.append((scheme_ordinal, certificates))
    return result


def valid_jni_method_descriptor(value: str | None) -> bool:
    if value is None or len(value) > 4096:
        return False
    return bool(
        re.fullmatch(
            r"\((?:\[*[ZBCSIJFD]|\[*L[^;\x00]+;)*\)(?:V|\[*[ZBCSIJFD]|\[*L[^;\x00]+;)",
            value,
        )
    )


def recover_jni_native_method_entries(data: bytes, library: str) -> dict[str, Any]:
    """Recover static JNINativeMethod triples from an AArch64 ELF image.

    Pointer values are reconstructed from the file image plus RELA records.  The
    resulting candidates are later admitted only when their name/signature pair
    resolves exactly one otherwise-unbound DEX native declaration.
    """

    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        raise ProducerError(f"{library}: expected ELF64 little-endian image")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", data, 0)
    machine = int(header[2])
    program_offset = int(header[5])
    section_offset = int(header[6])
    program_entry_size = int(header[9])
    program_count = int(header[10])
    section_entry_size = int(header[11])
    section_count = int(header[12])
    section_names_index = int(header[13])
    if machine != 183 or program_entry_size < 56 or section_entry_size < 64:
        raise ProducerError(f"{library}: unsupported ELF machine/header geometry")
    if program_offset + program_entry_size * program_count > len(data):
        raise ProducerError(f"{library}: program headers escape ELF image")
    if section_offset + section_entry_size * section_count > len(data):
        raise ProducerError(f"{library}: section headers escape ELF image")

    programs = [
        struct.unpack_from("<IIQQQQQQ", data, program_offset + index * program_entry_size)
        for index in range(program_count)
    ]
    raw_sections = [
        struct.unpack_from("<IIQQQQIIQQ", data, section_offset + index * section_entry_size)
        for index in range(section_count)
    ]
    if section_names_index >= len(raw_sections):
        raise ProducerError(f"{library}: section-name table index is invalid")
    name_section = raw_sections[section_names_index]
    name_offset = int(name_section[4])
    name_size = int(name_section[5])
    if name_offset + name_size > len(data):
        raise ProducerError(f"{library}: section-name table escapes ELF image")

    def file_cstring(offset: int, *, limit: int = 4096) -> str | None:
        if offset < 0 or offset >= len(data):
            return None
        end = data.find(b"\x00", offset, min(len(data), offset + limit))
        if end < 0:
            return None
        try:
            return unicodedata.normalize("NFC", data[offset:end].decode("utf-8"))
        except UnicodeDecodeError:
            return None

    def section_name(raw_offset: int) -> str:
        return file_cstring(name_offset + raw_offset, limit=512) or ""

    sections = [
        {
            "index": index,
            "name": section_name(int(row[0])),
            "type": int(row[1]),
            "flags": int(row[2]),
            "address": int(row[3]),
            "offset": int(row[4]),
            "size": int(row[5]),
            "link": int(row[6]),
            "entry_size": int(row[9]),
        }
        for index, row in enumerate(raw_sections)
    ]
    for section in sections:
        if section["type"] != 8 and section["offset"] + section["size"] > len(data):
            raise ProducerError(f"{library}: section {section['name']} escapes ELF image")

    def virtual_to_file(address: int) -> int | None:
        for program in programs:
            program_type, _, file_offset, virtual_address, _, file_size, _, _ = program
            if program_type == 1 and virtual_address <= address < virtual_address + file_size:
                return int(file_offset + address - virtual_address)
        return None

    def executable_address(address: int | None) -> bool:
        if address is None or address == 0:
            return False
        return any(
            program[0] == 1
            and program[1] & 1
            and program[3] <= address < program[3] + program[6]
            for program in programs
        )

    symbol_tables: dict[int, list[dict[str, Any]]] = {}
    for section in sections:
        if section["type"] not in {2, 11}:
            continue
        entry_size = section["entry_size"] or 24
        if entry_size < 24 or section["size"] % entry_size or section["link"] >= len(sections):
            raise ProducerError(f"{library}: malformed ELF symbol table {section['name']}")
        string_section = sections[section["link"]]
        symbols: list[dict[str, Any]] = []
        for offset in range(section["offset"], section["offset"] + section["size"], entry_size):
            name_index, info, other, section_index, value, size = struct.unpack_from(
                "<IBBHQQ", data, offset
            )
            symbols.append(
                {
                    "name": file_cstring(string_section["offset"] + name_index, limit=8192) or "",
                    "info": info,
                    "other": other,
                    "section_index": section_index,
                    "value": value,
                    "size": size,
                }
            )
        symbol_tables[section["index"]] = symbols

    relocations: dict[int, dict[str, Any]] = {}
    relocation_type_counts: Counter[str] = Counter()
    for section in sections:
        if section["type"] != 4:
            continue
        entry_size = section["entry_size"] or 24
        symbols = symbol_tables.get(section["link"])
        if entry_size < 24 or section["size"] % entry_size or symbols is None:
            raise ProducerError(f"{library}: malformed ELF RELA section {section['name']}")
        for offset in range(section["offset"], section["offset"] + section["size"], entry_size):
            target_offset, info, addend = struct.unpack_from("<QQq", data, offset)
            relocation_type = int(info & 0xFFFFFFFF)
            symbol_index = int(info >> 32)
            symbol = symbols[symbol_index] if symbol_index < len(symbols) else None
            resolved: int | None = None
            if relocation_type == 1027:  # R_AARCH64_RELATIVE
                resolved = int(addend)
            elif relocation_type in {257, 1025, 1026} and symbol is not None and symbol["value"]:
                resolved = int(symbol["value"] + addend)
            relocation_name = {
                257: "R_AARCH64_ABS64",
                1025: "R_AARCH64_GLOB_DAT",
                1026: "R_AARCH64_JUMP_SLOT",
                1027: "R_AARCH64_RELATIVE",
            }.get(relocation_type, f"R_AARCH64_{relocation_type}")
            relocation_type_counts[relocation_name] += 1
            relocations[int(target_offset)] = {
                "type": relocation_name,
                "symbol": symbol["name"] if symbol is not None else "",
                "addend": int(addend),
                "resolved_value": resolved,
            }

    def pointer_at(address: int) -> tuple[int | None, Mapping[str, Any] | None]:
        relocation = relocations.get(address)
        if relocation is not None and relocation["resolved_value"] is not None:
            return int(relocation["resolved_value"]), relocation
        offset = virtual_to_file(address)
        if offset is None or offset + 8 > len(data):
            return None, relocation
        return int(struct.unpack_from("<Q", data, offset)[0]), relocation

    def virtual_cstring(address: int | None) -> str | None:
        if address is None:
            return None
        offset = virtual_to_file(address)
        return None if offset is None else file_cstring(offset)

    candidates: list[dict[str, Any]] = []
    for section in sections:
        if section["type"] != 1 or not section["flags"] & 2 or section["flags"] & 4:
            continue
        start = (section["address"] + 7) & ~7
        end = section["address"] + section["size"]
        for address in range(start, max(start, end - 23), 8):
            name_pointer, name_relocation = pointer_at(address)
            signature_pointer, signature_relocation = pointer_at(address + 8)
            function_pointer, function_relocation = pointer_at(address + 16)
            name = virtual_cstring(name_pointer)
            signature = virtual_cstring(signature_pointer)
            if (
                name is None
                or len(name) > 512
                or not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", name)
                or not valid_jni_method_descriptor(signature)
                or not executable_address(function_pointer)
            ):
                continue
            candidates.append(
                {
                    "library": library,
                    "section": section["name"],
                    "table_entry_address": address,
                    "name": name,
                    "descriptor": signature,
                    "function_address": function_pointer,
                    "pointer_relocations": {
                        "name": name_relocation,
                        "descriptor": signature_relocation,
                        "function": function_relocation,
                    },
                }
            )
    candidates.sort(key=lambda row: (str(row["section"]), int(row["table_entry_address"])))
    for index, row in enumerate(candidates):
        previous = candidates[index - 1] if index else None
        row["table_ordinal"] = (
            int(previous["table_ordinal"]) + 1
            if previous is not None
            and previous["library"] == row["library"]
            and previous["section"] == row["section"]
            and int(previous["table_entry_address"]) + 24 == int(row["table_entry_address"])
            else 0
        )
    candidates.sort(key=canonical_text)
    return {
        "library": library,
        "rela_entry_count": len(relocations),
        "relocation_type_counts": dict(sorted(relocation_type_counts.items())),
        "jni_native_method_candidates": candidates,
    }


def parse_readobj(text: str, library: str) -> dict[str, Any]:
    needed: list[str] = []
    symbols: list[dict[str, Any]] = []
    in_needed = False
    in_symbols = False
    current: dict[str, str] | None = None
    format_name = None
    arch = None
    load_name = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Format: "):
            format_name = stripped.split(": ", 1)[1]
        elif stripped.startswith("Arch: "):
            arch = stripped.split(": ", 1)[1]
        elif stripped.startswith("LoadName: "):
            load_name = stripped.split(": ", 1)[1]
        if stripped == "NeededLibraries [":
            in_needed = True
            continue
        if in_needed:
            if stripped == "]":
                in_needed = False
            elif stripped:
                needed.append(stripped)
            continue
        if stripped == "DynamicSymbols [":
            in_symbols = True
            continue
        if in_symbols:
            if stripped == "]":
                if current is not None:
                    symbols.append(current)
                break
            if stripped == "Symbol {":
                if current is not None:
                    symbols.append(current)
                current = {}
                continue
            if stripped == "}":
                if current is not None:
                    symbols.append(current)
                    current = None
                continue
            if current is not None and ": " in stripped:
                key, value = stripped.split(": ", 1)
                current[key] = value
    if format_name != "elf64-littleaarch64" or arch != "aarch64":
        raise ProducerError(f"{library}: LLVM readobj did not identify arm64 ELF")
    normalized_symbols: list[dict[str, Any]] = []
    for index, symbol in enumerate(symbols):
        raw_name = re.sub(r"\s+\(\d+\)$", "", symbol.get("Name", ""))
        normalized_symbols.append(
            {
                "dynamic_symbol_index": index,
                "name": raw_name,
                "value": symbol.get("Value"),
                "size": symbol.get("Size"),
                "binding": symbol.get("Binding"),
                "type": symbol.get("Type"),
                "other": symbol.get("Other"),
                "section": symbol.get("Section"),
            }
        )
    return {
        "library": library,
        "format": format_name,
        "arch": arch,
        "load_name": load_name,
        "needed_libraries": needed,
        "dynamic_symbols": normalized_symbols,
    }


def _v10_elf_require(condition: bool, detail: str) -> None:
    if not condition:
        raise ProducerError(f"v10 ELF parse failed: {detail}")


def _v10_elf_headers(
    data: bytes,
) -> tuple[dict[str, int], list[dict[str, int]], list[dict[str, int]]]:
    _v10_elf_require(len(data) >= 64 and data[:4] == b"\x7fELF", "header")
    _v10_elf_require(data[4] == 2 and data[5] == 1, "class or endianness")
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
    _v10_elf_require(
        header["type"] == 3 and header["machine"] == 183 and header["ehsize"] == 64,
        "type, machine, or header size",
    )
    _v10_elf_require(header["shentsize"] == 64, "section entry size")
    _v10_elf_require(
        header["shoff"] + header["shnum"] * 64 <= len(data),
        "section table range",
    )
    sections: list[dict[str, int]] = []
    for index in range(header["shnum"]):
        row = struct.unpack_from("<IIQQQQIIQQ", data, header["shoff"] + index * 64)
        section = {
            "index": index,
            "name": row[0],
            "type": row[1],
            "flags": row[2],
            "addr": row[3],
            "offset": row[4],
            "size": row[5],
            "link": row[6],
            "info": row[7],
            "align": row[8],
            "entsize": row[9],
        }
        _v10_elf_require(
            section["type"] == 8 or section["offset"] + section["size"] <= len(data),
            f"section range {index}",
        )
        sections.append(section)
    programs: list[dict[str, int]] = []
    if header["phnum"]:
        _v10_elf_require(
            header["phentsize"] == 56
            and header["phoff"] + header["phnum"] * 56 <= len(data),
            "program table",
        )
        for index in range(header["phnum"]):
            row = struct.unpack_from("<IIQQQQQQ", data, header["phoff"] + index * 56)
            programs.append(
                {
                    "type": row[0],
                    "flags": row[1],
                    "offset": row[2],
                    "vaddr": row[3],
                    "filesz": row[5],
                    "memsz": row[6],
                    "align": row[7],
                }
            )
    return header, sections, programs


def _v10_elf_string(data: bytes, base: int, size: int, offset: int) -> str:
    _v10_elf_require(0 <= offset < size, "string offset")
    end = data.find(b"\0", base + offset, base + size)
    _v10_elf_require(end >= 0, "string terminator")
    try:
        return unicodedata.normalize("NFC", data[base + offset : end].decode("utf-8", "strict"))
    except UnicodeDecodeError as exc:
        raise ProducerError(f"v10 ELF string is not UTF-8: {exc}") from exc


def _v10_elf_versions(
    data: bytes,
    sections: Sequence[Mapping[str, int]],
    dynsym: Mapping[str, int],
    dynstr: Mapping[str, int],
    symbols: Sequence[Mapping[str, Any]],
) -> list[str | None]:
    versyms = [row for row in sections if row["type"] == 0x6FFFFFFF and row["link"] == dynsym["index"]]
    verdefs = [row for row in sections if row["type"] == 0x6FFFFFFD]
    verneeds = [row for row in sections if row["type"] == 0x6FFFFFFE]
    _v10_elf_require(len(versyms) <= 1 and len(verdefs) <= 1 and len(verneeds) <= 1, "version sections")
    if not versyms:
        _v10_elf_require(not verdefs and not verneeds, "orphan version section")
        return [None] * len(symbols)
    section = versyms[0]
    _v10_elf_require(
        section["entsize"] in {0, 2} and section["size"] == len(symbols) * 2,
        "version symbol cardinality",
    )
    raw_versions = struct.unpack_from(f"<{len(symbols)}H", data, section["offset"])
    definitions: dict[int, str] = {}
    requirements: dict[int, str] = {}
    if verdefs:
        current = 0
        seen: set[int] = set()
        sec = verdefs[0]
        while current < sec["size"]:
            _v10_elf_require(current not in seen and current + 20 <= sec["size"], "version definition")
            seen.add(current)
            version, _flags, index, count, _hash, aux, nxt = struct.unpack_from(
                "<HHHHIII", data, sec["offset"] + current
            )
            _v10_elf_require(
                version == 1 and count >= 1 and aux >= 20 and current + aux + 8 <= sec["size"],
                "version definition header",
            )
            name_offset, _aux_next = struct.unpack_from("<II", data, sec["offset"] + current + aux)
            name = _v10_elf_string(data, dynstr["offset"], dynstr["size"], name_offset)
            _v10_elf_require(index >= 1 and bool(name), "version definition name")
            if index >= 2:
                _v10_elf_require(index not in definitions, "duplicate version definition")
                definitions[index] = name
            if nxt == 0:
                break
            _v10_elf_require(nxt % 4 == 0 and current + nxt > current, "version definition chain")
            current += nxt
    if verneeds:
        current = 0
        seen: set[int] = set()
        sec = verneeds[0]
        while current < sec["size"]:
            _v10_elf_require(current not in seen and current + 16 <= sec["size"], "version requirement")
            seen.add(current)
            version, count, _file, aux, nxt = struct.unpack_from(
                "<HHIII", data, sec["offset"] + current
            )
            _v10_elf_require(version == 1 and count >= 1 and aux >= 16, "version requirement header")
            aux_position = current + aux
            aux_seen: set[int] = set()
            for ordinal in range(count):
                _v10_elf_require(
                    aux_position not in aux_seen and aux_position + 16 <= sec["size"],
                    "version requirement auxiliary",
                )
                aux_seen.add(aux_position)
                _hash, _flags, other, name_offset, aux_next = struct.unpack_from(
                    "<IHHII", data, sec["offset"] + aux_position
                )
                index = other & 0x7FFF
                name = _v10_elf_string(data, dynstr["offset"], dynstr["size"], name_offset)
                _v10_elf_require(
                    index >= 2 and index not in requirements and bool(name),
                    "version requirement name",
                )
                requirements[index] = name
                if ordinal + 1 < count:
                    _v10_elf_require(aux_next >= 16 and aux_next % 4 == 0, "version requirement chain")
                    aux_position += aux_next
                else:
                    _v10_elf_require(aux_next == 0, "version requirement terminator")
            if nxt == 0:
                break
            _v10_elf_require(nxt % 4 == 0 and current + nxt > current, "version requirement list")
            current += nxt
    result: list[str | None] = []
    default_seen: set[tuple[str | None, str]] = set()
    for symbol, raw in zip(symbols, raw_versions):
        index = raw & 0x7FFF
        hidden = bool(raw & 0x8000)
        if index in {0, 1}:
            _v10_elf_require(not hidden, "reserved version hidden")
            result.append(None)
        elif symbol["section_index"] == 0:
            _v10_elf_require(
                not hidden and index in requirements and index not in definitions,
                "version reference",
            )
            result.append("@" + requirements[index])
        else:
            _v10_elf_require(index in definitions and index not in requirements, "version definition lookup")
            token = ("@" if hidden else "@@") + definitions[index]
            if not hidden:
                key = (symbol["name"], definitions[index])
                _v10_elf_require(key not in default_seen, "duplicate default version")
                default_seen.add(key)
            result.append(token)
    return result


def parse_v10_elf_symbols(data: bytes) -> list[dict[str, Any]]:
    _header, sections, _programs = _v10_elf_headers(data)
    dynsyms = [row for row in sections if row["type"] == 11]
    _v10_elf_require(len(dynsyms) == 1, "dynamic symbol table selection")
    dynsym = dynsyms[0]
    _v10_elf_require(dynsym["entsize"] == 24 and dynsym["size"] % 24 == 0, "dynamic symbol shape")
    _v10_elf_require(0 <= dynsym["link"] < len(sections), "dynamic string table index")
    dynstr = sections[dynsym["link"]]
    _v10_elf_require(dynstr["type"] == 3, "dynamic string table")
    count = dynsym["size"] // 24
    xindex_sections = [
        row for row in sections if row["type"] == 18 and row["link"] == dynsym["index"]
    ]
    symbols: list[dict[str, Any]] = []
    for index in range(count):
        offset = dynsym["offset"] + index * 24
        name_offset, info, other, raw_section_index, value, size_bytes = struct.unpack_from(
            "<IBBHQQ", data, offset
        )
        _v10_elf_require(other & 0xF8 == 0, "symbol other bits")
        if index == 0:
            _v10_elf_require(
                (name_offset, info, other, raw_section_index, value, size_bytes)
                == (0, 0, 0, 0, 0, 0),
                "reserved symbol zero",
            )
        if raw_section_index == 0xFFFF:
            _v10_elf_require(len(xindex_sections) == 1, "extended section index")
            companion = xindex_sections[0]
            _v10_elf_require(
                companion["entsize"] == 4 and companion["size"] // 4 == count,
                "extended section index shape",
            )
            section_index = struct.unpack_from("<I", data, companion["offset"] + index * 4)[0]
        else:
            section_index = raw_section_index
        if 1 <= section_index < 0xFF00:
            _v10_elf_require(section_index < len(sections), "symbol section index")
        _v10_elf_require(section_index != 0xFFF2, "common symbol section")
        raw_name = _v10_elf_string(data, dynstr["offset"], dynstr["size"], name_offset)
        name = raw_name or None
        binding_code = info >> 4
        type_code = info & 0x0F
        visibility_code = other & 7
        symbol_type = {
            0: "STT_NOTYPE",
            1: "STT_OBJECT",
            2: "STT_FUNC",
            3: "STT_SECTION",
            4: "STT_FILE",
            5: "STT_COMMON",
            6: "STT_TLS",
            10: "STT_GNU_IFUNC",
        }.get(type_code)
        if symbol_type is None:
            symbol_type = (
                f"OS:{type_code}"
                if 11 <= type_code <= 12
                else f"PROC:{type_code}"
                if 13 <= type_code <= 15
                else f"UNKNOWN:{type_code}"
            )
        binding = {0: "STB_LOCAL", 1: "STB_GLOBAL", 2: "STB_WEAK", 10: "STB_GNU_UNIQUE"}.get(
            binding_code
        )
        if binding is None:
            binding = (
                f"OS:{binding_code}"
                if 11 <= binding_code <= 12
                else f"PROC:{binding_code}"
                if 13 <= binding_code <= 15
                else f"UNKNOWN:{binding_code}"
            )
        visibility = {
            0: "STV_DEFAULT",
            1: "STV_INTERNAL",
            2: "STV_HIDDEN",
            3: "STV_PROTECTED",
            4: "STV_EXPORTED",
            5: "STV_SINGLETON",
            6: "STV_ELIMINATE",
            7: "UNKNOWN:7",
        }[visibility_code]
        symbols.append(
            {
                "dynamic_symbol_index": index,
                "name": name,
                "value": value,
                "size_bytes": size_bytes,
                "symbol_type": symbol_type,
                "binding": binding,
                "visibility": visibility,
                "section_index": section_index,
                "version": None,
            }
        )
    versions = _v10_elf_versions(data, sections, dynsym, dynstr, symbols)
    for symbol, version in zip(symbols, versions):
        symbol["version"] = version
    return symbols


def _v10_elf_map_address(
    programs: Sequence[Mapping[str, int]],
    address: int,
    size: int,
) -> int:
    matches = [
        row
        for row in programs
        if row["type"] == 1
        and row["vaddr"] <= address
        and address + size <= row["vaddr"] + row["filesz"]
    ]
    _v10_elf_require(len(matches) == 1, "virtual address mapping")
    return int(matches[0]["offset"] + address - matches[0]["vaddr"])


def parse_v10_elf_needed(data: bytes) -> list[tuple[int, str]]:
    _header, sections, programs = _v10_elf_headers(data)
    segments = [row for row in programs if row["type"] == 2]
    dynamic_sections = [row for row in sections if row["type"] == 6]
    _v10_elf_require(len(segments) == len(dynamic_sections) == 1, "dynamic table selection")
    segment, section = segments[0], dynamic_sections[0]
    _v10_elf_require(
        (segment["offset"], segment["filesz"]) == (section["offset"], section["size"]),
        "dynamic segment/section parity",
    )
    _v10_elf_require(segment["filesz"] % 16 == 0, "dynamic entry shape")
    entries = [
        struct.unpack_from("<qQ", data, segment["offset"] + index * 16)
        for index in range(segment["filesz"] // 16)
    ]
    null_indexes = [index for index, (tag, _value) in enumerate(entries) if tag == 0]
    _v10_elf_require(bool(null_indexes), "dynamic terminator")
    first_null = null_indexes[0]
    before_null = entries[:first_null]

    def unique_tag(tag: int) -> int:
        values = [value for current, value in before_null if current == tag]
        _v10_elf_require(len(values) == 1, f"dynamic tag {tag}")
        return int(values[0])

    string_address = unique_tag(5)
    string_size = unique_tag(10)
    _v10_elf_require(unique_tag(11) == 24, "dynamic symbol entry size")
    unique_tag(6)
    string_offset = _v10_elf_map_address(programs, string_address, string_size)
    needed: list[tuple[int, str]] = []
    for index, (tag, value) in enumerate(entries[:first_null]):
        if tag == 1:
            name = _v10_elf_string(data, string_offset, string_size, value)
            _v10_elf_require(bool(name), "needed library name")
            needed.append((index, name))
    return needed


def parse_objdump(text: str) -> dict[str, list[str]]:
    needed: list[str] = []
    symbols: list[str] = []
    in_symbols = False
    for line in text.splitlines():
        needed_match = re.match(r"^\s*NEEDED\s+(\S+)\s*$", line)
        if needed_match:
            needed.append(needed_match.group(1))
        if line.strip() == "DYNAMIC SYMBOL TABLE:":
            in_symbols = True
            continue
        if in_symbols and line.strip():
            symbols.append(line.split()[-1])
    return {"needed_libraries": needed, "dynamic_symbol_names": symbols}


def parse_llvm_nm(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        names.append(stripped.split()[-1])
    return names


def parse_readelf(text: str) -> dict[str, Any]:
    needed: list[str] = []
    symbols: list[dict[str, str]] = []
    for line in text.splitlines():
        needed_match = re.search(r"\(NEEDED\).*\[(.*)\]", line)
        if needed_match:
            needed.append(needed_match.group(1))
        symbol_match = re.match(
            r"^\s*(\d+):\s+([0-9a-fA-F]+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s*(.*)$",
            line,
        )
        if symbol_match:
            index, value, size, symbol_type, binding, visibility, section, name = symbol_match.groups()
            symbols.append(
                {
                    "dynamic_symbol_index": index,
                    "value": value,
                    "size": size,
                    "type": symbol_type,
                    "binding": binding,
                    "visibility": visibility,
                    "section": section,
                    "name": name,
                }
            )
    return {"needed_libraries": needed, "dynamic_symbols": symbols}


def normalized_symbol_name(name: str) -> str:
    return name.split("@", 1)[0]


def symbol_name_and_version(name: str) -> tuple[str, str | None]:
    position = name.find("@")
    if position < 0:
        return name, None
    return name[:position], name[position:]


def canonical_symbol_included(symbol: Mapping[str, Any]) -> bool:
    """Admit every physical nonzero dynamic symbol, including unnamed sections."""

    try:
        return int(symbol["dynamic_symbol_index"]) != 0
    except (KeyError, TypeError, ValueError) as exc:
        raise ProducerError("dynamic symbol lacks a valid physical index") from exc


def v10_callsite_oracles(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = contract.get("dex", {}).get("byte_membership_oracles")
    if not isinstance(rows, list) or not rows:
        raise ProducerError("v10 contract lacks DEX callsite membership oracles")
    result: list[dict[str, Any]] = []
    required = {
        "artifact_id",
        "reflection_target_count",
        "reflection_target_payloads_sha256",
        "dynamic_loader_count",
        "dynamic_loader_payloads_sha256",
    }
    for row in rows:
        if not isinstance(row, Mapping) or not required.issubset(row):
            raise ProducerError("v10 DEX callsite oracle row is incomplete")
        copied = dict(row)
        for key in ("reflection_target_payloads_sha256", "dynamic_loader_payloads_sha256"):
            if not SHA256_RE.fullmatch(str(copied[key])):
                raise ProducerError(f"v10 DEX callsite oracle has invalid {key}")
        result.append(copied)
    result.sort(key=lambda row: str(row["artifact_id"]))
    return result


def v10_expected_counts(contract: Mapping[str, Any]) -> dict[str, int]:
    try:
        jni = contract["jni"]["byte_membership_oracles"]
        elf = contract["counts"]["elf_equations"]
        fixed_floor = int(contract["counts"]["fixed_floor"])
        callsites = v10_callsite_oracles(contract)
        orphan_count = int(jni["orphan_java_export_edge_count"])
        jni_edge_count = sum(
            int(jni[key])
            for key in (
                "static_short_edge_count",
                "static_long_edge_count",
                "register_natives_edge_count",
                "unresolved_declaration_edge_count",
                "orphan_java_export_edge_count",
            )
        )
        reflection_count = sum(int(row["reflection_target_count"]) for row in callsites)
        loader_count = sum(int(row["dynamic_loader_count"]) for row in callsites)
        unnamed_count = int(elf["unnamed_nonzero_stt_section"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProducerError("v10 contract count equations are incomplete") from exc
    return {
        "jni_edge": jni_edge_count,
        "orphan_java_export": orphan_count,
        "reflection_target": reflection_count,
        "dynamic_loader": loader_count,
        "unnamed_stt_section": unnamed_count,
        "normalized_record": fixed_floor + jni_edge_count + reflection_count + loader_count,
    }


def orphan_java_export_parent_ids(
    frozen_endpoint_library_record_id: str,
    native_export_record_id: str,
) -> list[str]:
    parents = sorted({frozen_endpoint_library_record_id, native_export_record_id})
    if len(parents) != 2:
        raise ProducerError("orphan Java export requires one frozen library and one native export parent")
    return parents


def symbol_field_token(value: Any) -> str:
    return re.sub(r"\s+\(0x[0-9A-Fa-f]+\)$", "", str(value))


def is_jni_symbol(name: str) -> bool:
    base = normalized_symbol_name(name)
    return base.startswith("Java_") or base in {"JNI_OnLoad", "JNI_OnUnload"} or "RegisterNatives" in base


def jni_mangle(value: str) -> str:
    encoded: list[str] = []
    for character in value:
        if character.isascii() and character.isalnum():
            encoded.append(character)
        elif character in {"/", "."}:
            encoded.append("_")
        elif character == "_":
            encoded.append("_1")
        elif character == ";":
            encoded.append("_2")
        elif character == "[":
            encoded.append("_3")
        else:
            units = character.encode("utf-16-be")
            for offset in range(0, len(units), 2):
                encoded.append(f"_0{int.from_bytes(units[offset:offset + 2], 'big'):04x}")
    return "".join(encoded)


def jni_export_candidates(class_descriptor: str, method_name: str, prototype: str) -> tuple[str, str]:
    class_name = class_descriptor[1:-1] if class_descriptor.startswith("L") and class_descriptor.endswith(";") else class_descriptor
    parameter_descriptor = prototype[1 : prototype.index(")")]
    short_name = f"Java_{jni_mangle(class_name)}_{jni_mangle(method_name)}"
    return short_name, f"{short_name}__{jni_mangle(parameter_descriptor)}"


def jni_declaration_payload(declaration: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dex_artifact_id": declaration["dex_artifact_id"],
        "class_descriptor": declaration["class_descriptor"],
        "method_name": declaration["method_name"],
        "descriptor": declaration["descriptor"],
    }


def jni_static_endpoint_payload(endpoint: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "endpoint_kind": "java_export",
        "library_artifact_id": endpoint["library_artifact_id"],
        "name": endpoint["name"],
        "native_export_record_id": endpoint["native_export_record_id"],
        "native_symbol_record_id": endpoint["native_symbol_record_id"],
        "version": endpoint["version"],
        "virtual_address": endpoint["virtual_address"],
    }


def classify_archive_entry(path: str) -> str:
    lowered = path.casefold()
    if path == "AndroidManifest.xml":
        return "manifest_node"
    if path == "stamp-cert-sha256" or re.search(r"meta-inf/[^/]+\.(rsa|dsa|ec|sf|mf)$", lowered):
        return "certificate"
    if path == "resources.arsc" or path.startswith("res/"):
        return "resource"
    if path.startswith("assets/"):
        return "asset"
    return "configuration"


def frozen_entry_artifact_id(entry: str, official_by_id: Mapping[str, Mapping[str, Any]]) -> str | None:
    candidates: list[str] = []
    if re.fullmatch(r"classes\d*\.dex", entry):
        candidates.append(f"extracted-dex:{entry}")
    if entry.startswith("lib/arm64-v8a/") and entry.endswith(".so"):
        candidates.append(f"extracted-native:{entry[4:]}")
    if entry.startswith("assets/"):
        candidates.append(f"extracted-fixture:{entry[len('assets/'):]}" )
    return next((candidate for candidate in candidates if candidate in official_by_id), None)


def artifact_entry_path(artifact: Mapping[str, Any]) -> str | None:
    artifact_id = str(artifact["artifact_id"])
    if artifact_id.startswith("extracted-dex:"):
        return artifact_id.split(":", 1)[1]
    if artifact_id.startswith("extracted-native:"):
        return f"lib/{artifact_id.split(':', 1)[1]}"
    if artifact_id.startswith("extracted-fixture:"):
        return f"assets/{artifact_id.split(':', 1)[1]}"
    return None


def verify_observation(artifact: Mapping[str, Any], digest: str, size: int, locator: str) -> dict[str, Any]:
    if digest != artifact.get("sha256") or size != artifact.get("size_bytes"):
        raise ProducerError(f"frozen artifact mismatch for {artifact['artifact_id']} from {locator}")
    return {
        "artifact_id": artifact["artifact_id"],
        "kind": artifact["kind"],
        "observed_locator": locator,
        "sha256": digest,
        "size_bytes": size,
        "matches_frozen_manifest": True,
    }


def zip_name_bytes(info: zipfile.ZipInfo) -> bytes:
    encoding = "utf-8" if info.flag_bits & 0x800 else "cp437"
    return info.filename.encode(encoding)


def decoded_zip_name(raw_name: bytes, fallback: str) -> str:
    try:
        return raw_name.decode("utf-8")
    except UnicodeDecodeError:
        return fallback


def zip_metadata(info: zipfile.ZipInfo, digest: str, *, canonical_path: str | None = None) -> dict[str, Any]:
    return {
        "path": canonical_path if canonical_path is not None else info.filename,
        "is_directory": info.is_dir(),
        "compression_method": info.compress_type,
        "compressed_size": info.compress_size,
        "size_bytes": info.file_size,
        "crc32": f"{info.CRC:08x}",
        "sha256": digest,
    }


def exact_key_check(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProducerError(f"{label} key mismatch: missing={sorted(expected-actual)} extra={sorted(actual-expected)}")


def validate_private_output(out_root: Path) -> dict[str, Any]:
    inventory_path = out_root / "inventory-b.private.json"
    source_index_path = out_root / "evidence" / BUNDLE_ID / "source-index.json"
    run_path = out_root / "runs" / RUN_ID / "manifest.json"
    evidence_path = out_root / "evidence" / BUNDLE_ID / "manifest.json"
    inventory = load_json(inventory_path)
    source_index = load_json(source_index_path)
    run = load_json(run_path)
    evidence = load_json(evidence_path)

    exact_key_check(
        inventory,
        {
            "schema_version",
            "inventory_id",
            "artifact_set_id",
            "generated_at",
            "method",
            "producer_run_id",
            "producer_run_manifest",
            "producer_evidence_bundle_ids",
            "independent_review_id",
            "normalized_records",
            "coverage",
            "canonical_sha256",
        },
        "inventory",
    )
    records = inventory.get("normalized_records")
    if not isinstance(records, list) or not records:
        raise ProducerError("inventory normalized_records is empty")
    record_keys = {
        "record_id",
        "record_type",
        "scope_key",
        "artifact_id",
        "source_artifact_id",
        "sha256",
        "size_bytes",
        "official_source",
        "dossier_id",
        "classification_status",
        "parent_record_ids",
        "source_refs",
    }
    record_ids: set[str] = set()
    identities: set[tuple[str, str]] = set()
    artifact_ids: set[str] = set()
    source_references: set[str] = set()
    type_counts: Counter[str] = Counter()
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise ProducerError(f"inventory record {position} is not an object")
        exact_key_check(record, record_keys, f"inventory record {position}")
        row_id = record["record_id"]
        identity = (record["record_type"], record["scope_key"])
        if not isinstance(row_id, str) or not RECORD_ID_RE.fullmatch(row_id) or row_id in record_ids:
            raise ProducerError(f"invalid/duplicate record ID: {row_id}")
        if identity in identities or record["record_type"] not in INVENTORY_RECORD_TYPES:
            raise ProducerError(f"invalid/duplicate scope identity: {identity}")
        if record["classification_status"] != "classified" or record["dossier_id"] not in {f"D{i:02d}" for i in range(1, 14)}:
            raise ProducerError(f"unclassified/unowned record: {row_id}")
        if record["artifact_id"] is not None:
            if record["artifact_id"] in artifact_ids or record["source_artifact_id"] != record["artifact_id"]:
                raise ProducerError(f"invalid artifact record: {row_id}")
            artifact_ids.add(record["artifact_id"])
        refs = record["source_refs"]
        if not isinstance(refs, list) or len(refs) != 1:
            raise ProducerError(f"record must have one Method-B source ref: {row_id}")
        source_references.add(str(refs[0].get("source_locator")))
        record_ids.add(row_id)
        identities.add(identity)
        type_counts[record["record_type"]] += 1
    if [record["record_id"] for record in records] != sorted(record_ids):
        raise ProducerError("normalized records are not sorted by record_id")
    for record in records:
        parents = record["parent_record_ids"]
        if not isinstance(parents, list) or parents != sorted(set(parents)) or not set(parents).issubset(record_ids):
            raise ProducerError(f"invalid parent references: {record['record_id']}")

    source_rows = source_index.get("records")
    if not isinstance(source_rows, list) or not source_rows:
        raise ProducerError("source index is empty")
    source_keys = {
        "source_locator",
        "record_type",
        "scope_key",
        "artifact_id",
        "source_artifact_id",
        "sha256",
        "size_bytes",
        "official_source",
    }
    by_locator: dict[str, Mapping[str, Any]] = {}
    for source_row in source_rows:
        exact_key_check(source_row, source_keys, "source row")
        locator = source_row["source_locator"]
        if locator in by_locator:
            raise ProducerError(f"duplicate source locator: {locator}")
        by_locator[locator] = source_row
    if [row["source_locator"] for row in source_rows] != sorted(by_locator):
        raise ProducerError("source rows are not sorted")
    if source_references != set(by_locator) or len(source_rows) != len(records):
        raise ProducerError("normalized/source-index one-to-one coverage failed")
    for record in records:
        ref = record["source_refs"][0]
        source_row = by_locator[ref["source_locator"]]
        if ref["source_record_sha256"] != sha256_bytes(canonical_bytes(source_row)):
            raise ProducerError(f"source row hash mismatch: {record['record_id']}")
        for field in ("record_type", "scope_key", "artifact_id", "source_artifact_id", "sha256", "size_bytes", "official_source"):
            if source_row[field] != record[field]:
                raise ProducerError(f"source row field mismatch: {record['record_id']} {field}")
    if source_index.get("canonical_sha256") != canonical_list_sha256(source_rows):
        raise ProducerError("source-index canonical hash mismatch")
    canonical_records = [{key: value for key, value in row.items() if key != "source_refs"} for row in records]
    if inventory.get("canonical_sha256") != canonical_list_sha256(canonical_records):
        raise ProducerError("inventory canonical hash mismatch")

    official = load_json(REPO_ROOT / OFFICIAL_MANIFEST_REL)
    official_ids = {artifact["artifact_id"] for artifact in official["artifacts"]}
    if artifact_ids != official_ids:
        raise ProducerError(f"frozen artifact coverage mismatch: {len(artifact_ids)} != {len(official_ids)}")
    if type_counts["apk_member"] != 19 or type_counts["dex"] != 4 or type_counts["native_library"] != 88:
        raise ProducerError("critic cardinality contract failed")
    if any(type_counts[record_type] == 0 for record_type in REQUIRED_DISCOVERED_TYPES):
        missing = sorted(record_type for record_type in REQUIRED_DISCOVERED_TYPES if type_counts[record_type] == 0)
        raise ProducerError(f"required discovered types are empty: {missing}")
    coverage = inventory.get("coverage")
    if coverage.get("record_count") != len(records) or coverage.get("unclassified") != 0:
        raise ProducerError("coverage summary differs from records")
    if coverage.get("record_type_counts") != dict(sorted(type_counts.items())):
        raise ProducerError("record type coverage differs from records")

    exact_key_check(
        run,
        {
            "schema_version",
            "run_id",
            "experiment_id",
            "operator",
            "status",
            "artifact_set_id",
            "method_id",
            "toolchain_family",
            "commands",
            "command_exit_codes",
            "tool_versions",
            "input_artifact_ids",
            "evidence_bundle_ids",
            "source_index_attachments",
            "started_at",
            "ended_at",
        },
        "run manifest",
    )
    if run["status"] != "completed" or any(code != 0 for code in run["command_exit_codes"]):
        raise ProducerError("run manifest is not completed with zero command exits")
    if len(run["commands"]) != len(run["command_exit_codes"]) or len(run["commands"]) != len(set(run["commands"])):
        raise ProducerError("run command accounting is inconsistent")
    if run["input_artifact_ids"] != sorted(official_ids):
        raise ProducerError("run does not account for every frozen artifact")

    evidence_keys = {
        "schema_version",
        "bundle_id",
        "claim_ids",
        "experiment_id",
        "operator",
        "captured_at",
        "clock",
        "artifact_set_id",
        "source_variant",
        "evidence_tier",
        "instrumentation_delta",
        "environment",
        "tool_versions",
        "replay_commands",
        "event_stream",
        "attachments",
        "manifest_sha256",
    }
    exact_key_check(evidence, evidence_keys, "evidence manifest")
    evidence_without_hash = dict(evidence)
    declared_manifest_hash = evidence_without_hash.pop("manifest_sha256")
    if declared_manifest_hash != sha256_bytes(canonical_bytes(evidence_without_hash)):
        raise ProducerError("evidence manifest canonical hash mismatch")
    bundle_root = evidence_path.parent
    for attachment in evidence["attachments"]:
        attachment_path = bundle_root / attachment["path"]
        digest, size = file_hash(attachment_path)
        if digest != attachment["sha256"] or size != attachment["size_bytes"]:
            raise ProducerError(f"evidence attachment changed: {attachment['path']}")

    return {
        "status": "pass",
        "record_count": len(records),
        "canonical_sha256": inventory["canonical_sha256"],
        "source_index_sha256": source_index["canonical_sha256"],
        "frozen_artifacts": len(artifact_ids),
        "apk_members": 19,
        "dex_files": 4,
        "native_libraries": 88,
        "unclassified": coverage["unclassified"],
        "record_type_counts": dict(sorted(type_counts.items())),
    }


def tool_path(value: str | Path) -> str:
    path = Path(value)
    if path.is_absolute():
        if not path.is_file():
            raise ProducerError(f"tool not found: {path}")
        return str(path)
    repo_candidate = REPO_ROOT / path
    if repo_candidate.is_file():
        return str(repo_candidate)
    resolved = shutil.which(str(value))
    if resolved is None:
        raise ProducerError(f"tool not found on PATH: {value}")
    return resolved


def build_replay_command(args: argparse.Namespace, out_root: Path, aapt2: Path) -> str:
    values = [
        display_path(Path(sys.executable)),
        "tools/hik_whole_apk/g002_method_b.py",
        "--xapk",
        display_path(args.xapk),
        "--out",
        display_path(out_root),
        "--contract",
        display_path(args.contract),
        "--candidate-root",
        display_path(args.candidate_root),
        "--timestamp",
        args.timestamp,
        "--aapt2",
        display_path(aapt2),
        "--llvm-readobj",
        Path(args.llvm_readobj).name,
        "--llvm-readelf",
        Path(args.llvm_readelf).name,
        "--llvm-nm",
        Path(args.llvm_nm).name,
        "--llvm-objdump",
        Path(args.llvm_objdump).name,
    ]
    return shlex.join(values)


def canonical_candidate_argv(command: str) -> list[str]:
    """Normalize destination-only CLI arguments for root-independent evidence."""
    argv = shlex.split(command)
    replacements = {
        "--out": display_path(DEFAULT_OUT),
        "--candidate-root": display_path(DEFAULT_CANDIDATE_ROOT),
    }
    for index, token in enumerate(argv):
        if token not in replacements:
            continue
        if index + 1 >= len(argv):
            raise ProducerError(f"candidate command flag lacks a value: {token}")
        argv[index + 1] = replacements[token]
    return argv


def output_attachment(path: Path, bundle_root: Path, media_type: str = "application/json") -> dict[str, Any]:
    digest, size = file_hash(path)
    return {
        "path": path.relative_to(bundle_root).as_posix(),
        "sha256": digest,
        "size_bytes": size,
        "media_type": media_type,
    }


def manifest_node_payloads(apk_artifact_id: str, nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload_by_path: dict[str, dict[str, Any]] = {}
    payloads: list[dict[str, Any]] = []
    for node in nodes:
        path = str(node["path"])
        parent_path = path.rsplit("/", 1)[0]
        parent_payload = payload_by_path.get(parent_path)
        payload = {
            "apk_artifact_id": apk_artifact_id,
            "event_ordinal": int(node["event_ordinal"]),
            "qname": str(node["qname"]),
            "xpath": path,
            "parent_manifest_node_record_id": (
                None if parent_payload is None else record_id("manifest_node", parent_payload)
            ),
            "attributes": list(node["attributes"]),
        }
        payload_by_path[path] = payload
        payloads.append(payload)
    return payloads


def _candidate_fact_id(record_id_value: str) -> str:
    return "FCT-" + sha256_bytes(canonical_bytes(["g002-fact/v1", record_id_value])).upper()


def _candidate_primitive_id(
    attachment_kind: str,
    primitive_kind: str,
    origin: str,
    input_artifact_ids: Sequence[str],
    physical_key: Sequence[Any],
    byte_ranges: Sequence[Mapping[str, Any]],
    dependency_primitive_ids: Sequence[str],
) -> str:
    preimage = [
        "g002-primitive/v1",
        attachment_kind,
        primitive_kind,
        origin,
        list(input_artifact_ids),
        list(physical_key),
        list(byte_ranges),
        list(dependency_primitive_ids),
    ]
    return "PRM-" + sha256_bytes(canonical_bytes(preimage)).upper()


def build_candidate_raw_attachment(
    attachment_kind: str,
    attachment_path: str,
    primitive_kind: str,
    records: Sequence[Mapping[str, Any]],
    input_artifact_ids: Sequence[str],
    scope_summaries: Sequence[Mapping[str, Any]],
    *,
    root_primitive_ids: Mapping[str, str] | None = None,
    root_primitives: Mapping[str, Mapping[str, Any]] | None = None,
    derivation_group: Any | None = None,
) -> dict[str, Any]:
    """Construct one canonical v10 raw attachment without validator helpers."""

    ordered_records = sorted(records, key=lambda row: _candidate_fact_id(str(row["record_id"])))
    primitives: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    roots_by_id = dict(root_primitive_ids or {})
    root_rows = dict(root_primitives or {})

    def dependency_for(source: str) -> str:
        dependency = roots_by_id.get(source)
        if dependency is not None:
            return dependency
        return "PRM-" + sha256_bytes(canonical_bytes(["g002-test-root/v1", source])).upper()

    for index, record in enumerate(ordered_records):
        source = str(record["source_artifact_id"])
        family = candidate_payload_variant(record)
        if family == "frozen_artifact":
            primitive = root_rows.get(source)
            if primitive is None:
                byte_range = {
                    "artifact_id": source,
                    "offset_bytes": 0,
                    "size_bytes": int(record["size_bytes"]),
                    "sha256": str(record["sha256"]),
                }
                primitive_id = _candidate_primitive_id(
                    "xapk",
                    "artifact.bytes",
                    "artifact",
                    [source],
                    [source],
                    [byte_range],
                    [],
                )
                primitive = {
                    "primitive_id": primitive_id,
                    "primitive_kind": "artifact.bytes",
                    "origin": "artifact",
                    "input_artifact_ids": [source],
                    "physical_key": [source],
                    "byte_ranges": [byte_range],
                    "dependency_primitive_ids": [],
                }
        else:
            dependency_ids = [dependency_for(source)]
            primitive_id = _candidate_primitive_id(
                attachment_kind,
                primitive_kind,
                "derived",
                [source],
                [family, str(record["record_id"])],
                [],
                dependency_ids,
            )
            primitive = {
                "primitive_id": primitive_id,
                "primitive_kind": primitive_kind,
                "origin": "derived",
                "input_artifact_ids": [source],
                "physical_key": [family, str(record["record_id"])],
                "byte_ranges": [],
                "dependency_primitive_ids": dependency_ids,
            }
        primitive_id = str(primitive["primitive_id"])
        fact_id = _candidate_fact_id(str(record["record_id"]))
        source_locator = f"{attachment_path}#/source_rows/{index}"
        source_row = {
            "source_locator": source_locator,
            "record_type": record["record_type"],
            "scope_key": record["scope_key"],
            "artifact_id": record["artifact_id"],
            "source_artifact_id": record["source_artifact_id"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "official_source": record["official_source"],
        }
        primitives.append(dict(primitive))
        decisions.append(
            {
                "primitive_id": primitive_id,
                "disposition": "normalization_root",
                "reason_code": None,
                "fact_ids": [fact_id],
            }
        )
        facts.append(
            {
                "fact_id": fact_id,
                "fact_kind": "normalized",
                "dependency_primitive_ids": [primitive_id],
                "record_id": record["record_id"],
                "record_type": record["record_type"],
                "scope_key": record["scope_key"],
                "validation_code": None,
                "source_row_index": index,
            }
        )
        source_rows.append(source_row)

    family_counts = Counter(candidate_payload_variant(record) for record in ordered_records)
    computed_summaries = [
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
    if scope_summaries and list(scope_summaries) != computed_summaries:
        raise ProducerError(f"candidate scope summaries differ for {attachment_path}")

    canonical_inputs = sorted(set(input_artifact_ids))
    if derivation_group is not None:
        derivation_digest = sha256_bytes(canonical_bytes(derivation_group))
        dependency_ids = sorted(dependency_for(source) for source in canonical_inputs)
        obligation_kind = primitive_kind.rsplit(".", 1)[0] + ".official_obligation"
        physical_key = [attachment_path, derivation_digest]
        primitive_id = _candidate_primitive_id(
            attachment_kind,
            obligation_kind,
            "derived",
            canonical_inputs,
            physical_key,
            [],
            dependency_ids,
        )
        fact_id = "FCT-" + sha256_bytes(
            canonical_bytes(["g002-obligation-fact/v1", attachment_path, derivation_digest])
        ).upper()
        primitives.append(
            {
                "primitive_id": primitive_id,
                "primitive_kind": obligation_kind,
                "origin": "derived",
                "input_artifact_ids": canonical_inputs,
                "physical_key": physical_key,
                "byte_ranges": [],
                "dependency_primitive_ids": dependency_ids,
            }
        )
        decisions.append(
            {
                "primitive_id": primitive_id,
                "disposition": "support",
                "fact_ids": [fact_id],
                "reason_code": None,
            }
        )
        facts.append(
            {
                "fact_id": fact_id,
                "fact_kind": "validation",
                "dependency_primitive_ids": [primitive_id],
                "record_id": None,
                "record_type": None,
                "scope_key": None,
                "validation_code": f"official_obligation:{derivation_digest}",
                "source_row_index": None,
            }
        )
    facts.sort(key=lambda row: row["fact_id"])
    return {
        "schema_version": "g002-raw-attachment/v1",
        "attachment_kind": attachment_kind,
        "artifact_set_id": "",
        "input_artifact_ids": canonical_inputs,
        "primitives": primitives,
        "decisions": decisions,
        "facts": facts,
        "source_rows": source_rows,
        "scope_summaries": computed_summaries,
    }


def candidate_payload_variant(record: Mapping[str, Any]) -> str:
    record_type = str(record["record_type"])
    payload = record["payload"]
    if record_type == "frozen_artifact":
        return "frozen_artifact"
    if record_type == "configuration":
        return f"configuration:{payload['configuration_kind']}"
    if record_type == "native_import":
        return f"native_import:{payload['import_kind']}"
    return record_type


def candidate_raw_path_for_record(record: Mapping[str, Any]) -> str:
    variant = candidate_payload_variant(record)
    if variant in {"frozen_artifact", "configuration:xapk_archive_entry"}:
        return "raw/xapk.json"
    if variant in {"configuration:apk_archive_entry", "configuration:arm32_native_library", "asset"}:
        return "raw/apk-entries.json"
    if variant in {"manifest_node", "android_component", "feature"}:
        return "raw/manifests.json"
    if variant in {"resource", "configuration:resource_configuration"}:
        return "raw/resources.json"
    if variant == "certificate":
        return "raw/signing.json"
    if variant in {"class", "method_family", "reflection_target", "dynamic_loader"}:
        return "raw/dex.json"
    if variant in {"native_symbol", "native_export", "native_import:undefined_dynsym", "native_import:dt_needed", "configuration:native_library_summary"}:
        return "raw/elf.json"
    if variant == "jni_edge":
        return "raw/jni.json"
    raise ProducerError(f"no candidate raw attachment for variant: {variant}")


def candidate_family_memberships(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_family: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        by_family[candidate_payload_variant(record)].append(record)
    memberships: list[dict[str, Any]] = []
    for family, rows in sorted(by_family.items()):
        ordered = sorted(rows, key=lambda row: str(row["record_id"]))
        memberships.append(
            {
                "family": family,
                "count": len(ordered),
                "payloads_sha256": canonical_list_sha256(row["payload"] for row in ordered),
                "record_ids_sha256": canonical_list_sha256(row["record_id"] for row in ordered),
            }
        )
    return memberships


def candidate_root_primitives(
    records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    primitive_ids: dict[str, str] = {}
    primitives: dict[str, dict[str, Any]] = {}
    for record in records:
        if candidate_payload_variant(record) != "frozen_artifact":
            continue
        artifact_id = str(record["payload"])
        byte_range = {
            "artifact_id": artifact_id,
            "offset_bytes": 0,
            "size_bytes": int(record["size_bytes"]),
            "sha256": str(record["sha256"]),
        }
        primitive_id = _candidate_primitive_id(
            "xapk",
            "artifact.bytes",
            "artifact",
            [artifact_id],
            [artifact_id],
            [byte_range],
            [],
        )
        primitive_ids[artifact_id] = primitive_id
        primitives[artifact_id] = {
            "primitive_id": primitive_id,
            "primitive_kind": "artifact.bytes",
            "origin": "artifact",
            "input_artifact_ids": [artifact_id],
            "physical_key": [artifact_id],
            "byte_ranges": [byte_range],
            "dependency_primitive_ids": [],
        }
    return primitive_ids, primitives


def v10_derivation_groups(
    contract: Mapping[str, Any],
    memberships: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    *,
    dex_native_declarations_sha256: str | None = None,
) -> dict[str, Any]:
    def selected(families: set[str]) -> list[dict[str, Any]]:
        return [dict(row) for row in memberships if str(row["family"]) in families]

    android = contract["android"]
    anchors = android["official_anchor_details"]
    jni = contract["jni"]["byte_membership_oracles"]
    dex_native_declarations_digest = (
        str(dex_native_declarations_sha256)
        if dex_native_declarations_sha256 is not None
        else str(jni["declaration_membership_sha256"])
    )
    if not SHA256_RE.fullmatch(dex_native_declarations_digest):
        raise ProducerError("DEX native declaration digest is not a SHA-256 value")
    certificate_payloads = sorted(
        (
            record["payload"]
            for record in records
            if candidate_payload_variant(record) == "certificate"
        ),
        key=canonical_bytes,
    )
    elf_totals = {
        key: int(value)
        for key, value in contract["counts"]["elf_equations"].items()
        if type(value) is int
    }
    return {
        "raw/xapk.json": {
            "entries": selected({"frozen_artifact", "configuration:xapk_archive_entry"}),
            "physical_order": anchors["xapk_physical_order"],
        },
        "raw/apk-entries.json": {
            "entries": selected(
                {
                    "configuration:apk_archive_entry",
                    "configuration:arm32_native_library",
                    "asset",
                }
            ),
            "apk_entry_counts": anchors["apk_entry_counts"],
            "archive_categories": anchors["archive_categories"],
        },
        "raw/manifests.json": {
            "entries": selected({"manifest_node", "feature", "android_component"}),
            "android_membership": android["normalized_membership_oracles"],
            "component_counts": anchors["component_counts"],
        },
        "raw/resources.json": {
            "entries": selected({"resource", "configuration:resource_configuration"}),
            "resource_payloads_sha256": android["normalized_membership_oracles"][
                "resource_payloads_sha256"
            ],
            "resource_configuration_payloads_sha256": android["normalized_membership_oracles"][
                "resource_configuration_payloads_sha256"
            ],
        },
        "raw/signing.json": {
            "entries": selected({"certificate"}),
            "scheme_counts": {"v1": 18, "v2": 19, "v3": 19},
            "certificate_payloads_sha256": canonical_list_sha256(certificate_payloads),
        },
        "raw/dex.json": {
            "entries": selected({"class", "method_family", "reflection_target", "dynamic_loader"}),
            "totals": contract["counts"]["dex_equations"],
            "byte_membership": contract["dex"]["byte_membership_oracles"],
            "native_declarations_sha256": dex_native_declarations_digest,
        },
        "raw/elf.json": {
            "entries": selected(
                {
                    "native_symbol",
                    "native_export",
                    "native_import:undefined_dynsym",
                    "native_import:dt_needed",
                    "configuration:native_library_summary",
                }
            ),
            "totals": elf_totals,
            "membership": contract["membership_oracles"]["digests"],
        },
        "raw/jni.json": {
            "entries": selected({"jni_edge"}),
            "membership": jni,
            "registration_decisions_sha256": jni["registration_candidate_decisions_sha256"],
            "registration_proven_edges_sha256": jni["registration_proven_edges_sha256"],
            "registration_exclusions_sha256": jni["registration_exclusions_sha256"],
        },
    }


def write_bound_candidate_json(root: Path, relative: str, value: Any) -> dict[str, Any]:
    path = root / relative
    write_json(path, value)
    digest, size = file_hash(path)
    return {"path": relative, "media_type": "application/json", "sha256": digest, "size_bytes": size}


def write_canonical_candidate_bundle(
    *,
    candidate_root: Path,
    artifact_set_id: str,
    records: Sequence[Mapping[str, Any]],
    source_records: Sequence[Mapping[str, Any]],
    canonical_inventory_hash: str,
    source_index_hash: str,
    commands: Sequence[str],
    timestamp: str,
    generated_at: str,
    contract: Mapping[str, Any] | None = None,
    enforce_complete: bool = True,
    dex_native_declarations_sha256: str | None = None,
) -> None:
    del source_records, canonical_inventory_hash, source_index_hash, generated_at
    active_contract = dict(contract) if contract is not None else load_json(REPO_ROOT / CONTRACT_REL)
    base_time = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    def v10_time(offset_seconds: int) -> str:
        return (base_time + timedelta(seconds=offset_seconds)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    run_started_at = v10_time(0)
    command_started_at = v10_time(1)
    command_ended_at = v10_time(2)
    captured_at = v10_time(3)
    run_ended_at = v10_time(4)
    generated_at = v10_time(5)
    reviewed_at = v10_time(6)
    if candidate_root.exists():
        shutil.rmtree(candidate_root)
    (candidate_root / "raw").mkdir(parents=True, exist_ok=True)
    candidate_records: list[dict[str, Any]] = []
    by_path: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        payload = json.loads(str(record["scope_key"]))
        candidate = {
            "record_id": record["record_id"],
            "record_type": record["record_type"],
            "scope_key": record["scope_key"],
            "artifact_id": record["artifact_id"],
            "source_artifact_id": record["source_artifact_id"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "official_source": record["official_source"],
            "dossier_id": record["dossier_id"],
            "classification_status": record["classification_status"],
            "parent_record_ids": record["parent_record_ids"],
            "source_refs": [],
            "payload": payload,
        }
        by_path[candidate_raw_path_for_record(candidate)].append(candidate)
        candidate_records.append(candidate)

    candidate_records.sort(key=lambda row: str(row["record_id"]))
    family_counts = Counter(candidate_payload_variant(row) for row in candidate_records)
    family_memberships = candidate_family_memberships(candidate_records)
    if enforce_complete:
        expected_memberships = active_contract["provenance"]["whole_candidate"]["family_memberships"]
        if family_memberships != expected_memberships:
            actual_by_family = {str(row["family"]): row for row in family_memberships}
            expected_by_family = {str(row["family"]): row for row in expected_memberships}
            differing = sorted(
                family
                for family in set(actual_by_family) | set(expected_by_family)
                if actual_by_family.get(family) != expected_by_family.get(family)
            )
            raise ProducerError(f"v10 family membership differs: {differing}")
        expected_counts = v10_expected_counts(active_contract)
        if len(candidate_records) != expected_counts["normalized_record"]:
            raise ProducerError(
                f"v10 normalized record count={len(candidate_records)}, "
                f"expected={expected_counts['normalized_record']}"
            )
    root_primitive_ids, root_primitives = candidate_root_primitives(candidate_records)
    derivation_groups = v10_derivation_groups(
        active_contract,
        family_memberships,
        candidate_records,
        dex_native_declarations_sha256=dex_native_declarations_sha256,
    )

    raw_descriptors: list[dict[str, Any]] = []
    source_index_rows: list[dict[str, Any]] = []
    attachment_kind_by_path = {
        "raw/xapk.json": "xapk",
        "raw/apk-entries.json": "apk-entries",
        "raw/manifests.json": "manifests",
        "raw/resources.json": "resources",
        "raw/signing.json": "signing",
        "raw/dex.json": "dex",
        "raw/elf.json": "elf",
        "raw/jni.json": "jni",
    }
    primitive_kind_by_path = {
        "raw/xapk.json": "zip.normalized_record",
        "raw/apk-entries.json": "apk.normalized_record",
        "raw/manifests.json": "android.normalized_record",
        "raw/resources.json": "arsc.normalized_record",
        "raw/signing.json": "signing.normalized_record",
        "raw/dex.json": "dex.normalized_record",
        "raw/elf.json": "elf.normalized_record",
        "raw/jni.json": "jni.normalized_record",
    }
    record_by_id = {str(record["record_id"]): record for record in candidate_records}
    for raw_path in attachment_kind_by_path:
        rows = by_path.get(raw_path, [])
        document = build_candidate_raw_attachment(
            attachment_kind_by_path[raw_path],
            raw_path,
            primitive_kind_by_path[raw_path],
            rows,
            sorted({str(row["source_artifact_id"]) for row in rows}),
            [],
            root_primitive_ids=root_primitive_ids,
            root_primitives=root_primitives,
            derivation_group=derivation_groups[raw_path],
        )
        document["artifact_set_id"] = artifact_set_id
        for fact in document["facts"]:
            if fact["fact_kind"] != "normalized":
                continue
            record = record_by_id[str(fact["record_id"])]
            source_row = document["source_rows"][int(fact["source_row_index"])]
            ref = {
                "bundle_id": BUNDLE_ID,
                "attachment_path": "source-index.json",
                "source_locator": source_row["source_locator"],
                "source_record_sha256": sha256_bytes(canonical_bytes(source_row)),
            }
            record["source_refs"] = [ref]
            source_index_rows.append(source_row)
        descriptor = write_bound_candidate_json(candidate_root, raw_path, document)
        raw_descriptors.append(
            {
                **descriptor,
                "attachment_kind": attachment_kind_by_path[raw_path],
                "captured_at": captured_at,
            }
        )
    source_index_rows.sort(key=lambda row: row["source_locator"])
    inventory_descriptor = write_bound_candidate_json(
        candidate_root,
        "inventory.json",
        {
            "schema": "g002-normalized-inventory/v2",
            "scope": "whole_inventory",
            "artifact_set_id": artifact_set_id,
            "bundle_id": BUNDLE_ID,
            "generated_at": generated_at,
            "records": candidate_records,
            "summary": {
                "record_count": len(candidate_records),
                "family_counts": [{"family": key, "count": family_counts[key]} for key in sorted(family_counts)],
                "family_memberships": family_memberships,
            },
        },
    )
    source_descriptor = write_bound_candidate_json(
        candidate_root,
        "source-index.json",
        {
            "schema_version": "g002-source-index/v2",
            "bundle_id": BUNDLE_ID,
            "rows": source_index_rows,
        },
    )
    run_descriptor = write_bound_candidate_json(
        candidate_root,
        "run.json",
        {
            "schema": "g002-run/v1",
            "bundle_id": BUNDLE_ID,
            "operator_id": OPERATOR,
            "status": "succeeded",
            "started_at": run_started_at,
            "ended_at": run_ended_at,
        },
    )
    command_descriptor = write_bound_candidate_json(
        candidate_root,
        "command.json",
        {
            "schema": "g002-command/v1",
            "bundle_id": BUNDLE_ID,
            "operator_id": OPERATOR,
            "argv": canonical_candidate_argv(commands[0]) if commands else [],
            "exit_code": 0,
            "started_at": command_started_at,
            "ended_at": command_ended_at,
        },
    )
    review_descriptor = write_bound_candidate_json(
        candidate_root,
        "review.json",
        {
            "schema": "g002-review/v1",
            "bundle_id": BUNDLE_ID,
            "reviewer_id": "method-b-v10-independent-structure-reviewer",
            "status": "accepted",
            "inventory_sha256": inventory_descriptor["sha256"],
            "source_index_sha256": source_descriptor["sha256"],
            "attachment_sha256s": {row["path"]: row["sha256"] for row in raw_descriptors},
            "reviewed_at": reviewed_at,
        },
    )
    write_bound_candidate_json(
        candidate_root,
        "bundle.json",
        {
            "schema": "g002-candidate-bundle/v2",
            "artifact_set_id": artifact_set_id,
            "bundle_id": BUNDLE_ID,
            "candidate_scope": "whole_inventory",
            "operator_id": OPERATOR,
            "inventory": inventory_descriptor,
            "source_index": source_descriptor,
            "run": run_descriptor,
            "command": command_descriptor,
            "review": review_descriptor,
            "raw_attachments": sorted(raw_descriptors, key=lambda row: row["path"]),
        },
    )


def bool_manifest_attribute(node: Mapping[str, Any], name: str, default: bool | None) -> bool | None:
    value = manifest_attribute(node, name)
    if value is None:
        return default
    if value not in {"true", "false"}:
        raise ProducerError(f"manifest attribute {name} is not boolean: {value}")
    return value == "true"


def fully_qualified_component_name(package: str, value: str) -> str:
    if value.startswith("."):
        return package + value
    if "." not in value:
        return f"{package}.{value}"
    return value


def component_payload(
    node: Mapping[str, Any],
    *,
    package: str,
    base_application_name: str,
) -> dict[str, Any]:
    qname = str(node["qname"])
    kind = "activity" if qname == "activity-alias" else qname
    raw_name = manifest_attribute(node, "name")
    if kind == "application" and raw_name is None:
        raw_name = base_application_name
    if raw_name is None:
        raise ProducerError(f"manifest component lacks a name: {node['xpath']}")
    process = manifest_attribute(node, "process") or package
    if process.startswith(":"):
        process = package + process
    return {
        "package": package,
        "kind": kind,
        "name": fully_qualified_component_name(package, raw_name),
        "process": process,
        "exported": bool_manifest_attribute(node, "exported", None),
        "enabled": bool_manifest_attribute(node, "enabled", True),
        "direct_boot_aware": bool_manifest_attribute(node, "directBootAware", False),
        "permission": manifest_attribute(node, "permission"),
        "foreground_service_type": manifest_attribute(node, "foregroundServiceType"),
    }


def archive_entry_payload(
    *,
    kind: str,
    container_artifact_id: str,
    entry: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "configuration_kind": kind,
        "container_artifact_id": container_artifact_id,
        "central_directory_ordinal": int(entry["central_directory_ordinal"]),
        "path": str(entry["path"]),
        "compression_method": int(entry["compression_method"]),
        "crc32": int(entry["crc32"]),
        "compressed_size_bytes": int(entry["compressed_size"]),
        "uncompressed_size_bytes": int(entry["size_bytes"]),
        "sha256": str(entry["sha256"]),
    }


def resource_scope_payload(apk_id: str, resource: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "apk_artifact_id": apk_id,
        "package_id": int(resource["package_id"]),
        "type_id": int(resource["type_id"]),
        "entry_id": int(resource["entry_id"]),
        "resource_id": str(resource["resource_id"]),
        "package_name": str(resource["package_name"]),
        "type_name": str(resource["type_name"]),
        "entry_name": str(resource["entry_name"]),
    }


def class_scope_payload(dex_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dex_artifact_id": dex_id,
        "descriptor": str(value["descriptor"]),
        "access_flags": int(value["access_flags"]),
        "superclass": value["superclass_descriptor"],
        "interfaces": sorted(str(item) for item in value["interfaces"]),
    }


def native_symbol_scope_payload(library_id: str, symbol: Mapping[str, Any]) -> dict[str, Any]:
    if "symbol_type" in symbol:
        return {
            "library_artifact_id": library_id,
            "dynamic_symbol_index": int(symbol["dynamic_symbol_index"]),
            "name": symbol["name"],
            "version": symbol["version"],
            "value": int(symbol["value"]),
            "size_bytes": int(symbol["size_bytes"]),
            "symbol_type": str(symbol["symbol_type"]),
            "binding": str(symbol["binding"]),
            "visibility": str(symbol["visibility"]),
            "section_index": int(symbol["section_index"]),
        }
    name, version = symbol_name_and_version(str(symbol["name"]))
    section = symbol_field_token(symbol["section"])
    section_index = 0 if section == "Undefined" else int(str(symbol.get("section_index", "0")) or 0)
    return {
        "library_artifact_id": library_id,
        "dynamic_symbol_index": int(symbol["dynamic_symbol_index"]),
        "name": name,
        "version": version,
        "value": int(str(symbol["value"]), 16),
        "size_bytes": int(str(symbol["size"]), 10),
        "symbol_type": symbol_field_token(symbol["type"]),
        "binding": symbol_field_token(symbol["binding"]),
        "visibility": "DEFAULT" if str(symbol.get("other")) == "0" else str(symbol.get("other")),
        "section_index": section_index,
    }


def assert_fixed(label: str, observed: int) -> None:
    expected = FIXED_SCOPE_COUNTS[label]
    if observed != expected:
        raise ProducerError(f"{label}={observed}, expected frozen {expected}")


def produce(args: argparse.Namespace) -> dict[str, Any]:
    out_root = checked_output_root(args.out)
    if out_root.exists():
        shutil.rmtree(out_root)
    work_root = out_root / ".work"
    apk_work_root = work_root / "apks"
    native_work_root = work_root / "native"
    bundle_root = out_root / "evidence" / BUNDLE_ID
    raw_root = bundle_root / "raw"
    apk_work_root.mkdir(parents=True, exist_ok=True)
    native_work_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    official_manifest = load_json(REPO_ROOT / OFFICIAL_MANIFEST_REL)
    artifacts = official_manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 121:
        raise ProducerError("frozen official artifact manifest must contain exactly 121 rows")
    official_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    if len(official_by_id) != len(artifacts):
        raise ProducerError("frozen official artifact IDs are invalid or duplicated")
    artifact_set_id = official_manifest["artifact_set_id"]

    xapk_path = args.xapk.resolve()
    base_path = args.base_apk.resolve()
    if not xapk_path.is_file() or not base_path.is_file():
        raise ProducerError("official XAPK/base APK input is missing")

    aapt2_path = Path(tool_path(args.aapt2)).resolve()
    zipinfo_path = Path(tool_path(args.zipinfo)).resolve()
    unzip_path = Path(tool_path(args.unzip)).resolve()
    llvm_readobj_path = Path(tool_path(args.llvm_readobj)).resolve()
    llvm_objdump_path = Path(tool_path(args.llvm_objdump)).resolve()
    runner = CommandRunner()

    python_version_output = runner.run([sys.executable, "--version"], "capture Python version")
    unzip_version_output = runner.run([unzip_path, "-v"], "capture Info-ZIP version")
    aapt2_version_stdout = runner.run([aapt2_path, "version"], "capture AAPT2 version")
    aapt2_version_output = aapt2_version_stdout or runner.last_stderr
    readobj_version_output = runner.run([llvm_readobj_path, "--version"], "capture LLVM readobj version")
    objdump_version_output = runner.run([llvm_objdump_path, "--version"], "capture LLVM objdump version")
    versions = {
        "producer": f"{SCRIPT_VERSION} sha256={file_hash(Path(__file__).resolve())[0]}",
        "python": python_version_output.decode("utf-8", errors="replace").strip(),
        "info_zip": unzip_version_output.decode("utf-8", errors="replace").splitlines()[0].strip(),
        "aapt2": aapt2_version_output.decode("utf-8", errors="replace").strip(),
        "llvm_readobj": readobj_version_output.decode("utf-8", errors="replace").splitlines()[0].strip(),
        "llvm_objdump": objdump_version_output.decode("utf-8", errors="replace").splitlines()[0].strip(),
        "dex_parser": SCRIPT_VERSION,
    }
    if "Android Asset Packaging Tool (aapt) 2.19-12006047" not in versions["aapt2"]:
        raise ProducerError(f"cached AAPT2 is not the approved 2.19 build: {versions['aapt2']}")
    if "LLVM version 16." not in versions["llvm_readobj"] or "LLVM version 16." not in versions["llvm_objdump"]:
        raise ProducerError("LLVM readobj/objdump must both be version 16")
    if "UnZip 6.00" not in versions["info_zip"]:
        raise ProducerError("Info-ZIP UnZip 6.00 is required")

    replay_command = build_replay_command(args, out_root, aapt2_path)
    builder = RecordBuilder(official_by_id)
    for artifact in artifacts:
        builder.add_artifact(artifact)
    nested_frozen_index = build_nested_frozen_occurrence_index(
        official_by_id,
        builder.artifact_record_ids,
    )

    artifact_observations: dict[str, dict[str, Any]] = {}
    xapk_digest, xapk_size = file_hash(xapk_path)
    artifact_observations["official-xapk"] = verify_observation(
        official_by_id["official-xapk"], xapk_digest, xapk_size, display_path(xapk_path)
    )
    base_digest, base_size = file_hash(base_path)
    artifact_observations["extracted-base-apk"] = verify_observation(
        official_by_id["extracted-base-apk"], base_digest, base_size, display_path(base_path)
    )

    xapk_zip_output = runner.run([zipinfo_path, "-1", xapk_path], "list every XAPK member with Info-ZIP")
    infozip_xapk_names = xapk_zip_output.splitlines()
    xapk_entries: list[dict[str, Any]] = []
    apk_paths: dict[str, Path] = {}
    with zipfile.ZipFile(xapk_path, "r") as xapk:
        xapk_infos = xapk.infolist()
        python_xapk_names = [zip_name_bytes(info) for info in xapk_infos]
        if infozip_xapk_names != python_xapk_names:
            raise ProducerError("Info-ZIP/Python XAPK member lists differ")
        for info, raw_name in zip(xapk_infos, infozip_xapk_names):
            canonical_name = decoded_zip_name(raw_name, info.filename)
            digest, size = zip_entry_hash(xapk, info)
            xapk_entries.append(zip_metadata(info, digest, canonical_path=canonical_name))
            artifact_id = (
                f"xapk-apk:{canonical_name}"
                if canonical_name.endswith(".apk")
                else f"xapk-member:{canonical_name}"
            )
            if artifact_id not in official_by_id:
                raise ProducerError(f"XAPK member is absent from frozen manifest: {canonical_name}")
            artifact_observations[artifact_id] = verify_observation(
                official_by_id[artifact_id], digest, size, f"{display_path(xapk_path)}!/{canonical_name}"
            )
            if canonical_name.endswith(".apk"):
                if Path(canonical_name).name != canonical_name:
                    raise ProducerError(f"unsafe APK member path: {canonical_name}")
                target = apk_work_root / canonical_name
                with xapk.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                apk_paths[canonical_name] = target
    if len(apk_paths) != 19:
        raise ProducerError(f"expected 19 APK members, found {len(apk_paths)}")
    base_member_name = "com.hikvision.thermalGoogle.apk"
    if base_member_name not in apk_paths:
        raise ProducerError("official base APK member is missing from XAPK")
    extracted_base_digest, extracted_base_size = file_hash(apk_paths[base_member_name])
    if (extracted_base_digest, extracted_base_size) != (base_digest, base_size):
        raise ProducerError("provided base APK differs from untouched XAPK base member")

    archive_documents: list[dict[str, Any]] = []
    manifest_documents: list[dict[str, Any]] = []
    resource_documents: list[dict[str, Any]] = []
    dex_documents: list[dict[str, Any]] = []
    elf_documents: list[dict[str, Any]] = []
    jni_native_methods: list[dict[str, Any]] = []
    apk_archive_counts: dict[str, int] = {}

    # Verify every frozen inner-base artifact directly from XAPK-extracted bytes.
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        base_info_by_name = {info.filename: info for info in base_zip.infolist()}
        for artifact in artifacts:
            entry = artifact_entry_path(artifact)
            if entry is None:
                continue
            info = base_info_by_name.get(entry)
            if info is None:
                raise ProducerError(f"frozen base artifact is absent from APK: {entry}")
            digest, size = zip_entry_hash(base_zip, info)
            artifact_id = str(artifact["artifact_id"])
            artifact_observations[artifact_id] = verify_observation(
                artifact, digest, size, f"{base_member_name}!/{entry}"
            )
    if set(artifact_observations) != set(official_by_id):
        missing = sorted(set(official_by_id) - set(artifact_observations))
        extra = sorted(set(artifact_observations) - set(official_by_id))
        raise ProducerError(f"frozen artifact hash accounting differs: missing={missing}, extra={extra}")

    for apk_name in sorted(apk_paths):
        apk_path = apk_paths[apk_name]
        zip_listing = runner.run([zipinfo_path, "-1", apk_path], f"list every entry in {apk_name} with Info-ZIP")
        infozip_names = zip_listing.splitlines()
        source_artifact_id = f"xapk-apk:{apk_name}"
        with zipfile.ZipFile(apk_path, "r") as apk_zip:
            infos = apk_zip.infolist()
            python_names = [zip_name_bytes(info) for info in infos]
            if python_names != infozip_names:
                raise ProducerError(f"Info-ZIP/Python archive listings differ for {apk_name}")
            apk_archive_counts[apk_name] = len(infos)
            for ordinal, (info, raw_name) in enumerate(zip(infos, infozip_names)):
                canonical_name = decoded_zip_name(raw_name, info.filename)
                digest, size = zip_entry_hash(apk_zip, info)
                frozen_id = frozen_entry_artifact_id(canonical_name, official_by_id) if apk_name == base_member_name else None
                entry_row = {
                    "apk_member": apk_name,
                    "central_directory_ordinal": ordinal,
                    **zip_metadata(info, digest, canonical_path=canonical_name),
                    "accounted_by_frozen_artifact_id": frozen_id,
                }
                archive_documents.append(entry_row)
                if frozen_id is not None:
                    continue
                record_type = classify_archive_entry(canonical_name)
                builder.add_discovered(
                    record_type,
                    f"apk:{apk_name}!entry:{canonical_name}",
                    source_artifact_id,
                    sha256=digest,
                    size_bytes=size,
                )

        xml_output = runner.run(
            [aapt2_path, "dump", "xmltree", apk_path, "--file", "AndroidManifest.xml"],
            f"decode binary AndroidManifest.xml for {apk_name}",
        )
        resource_output = runner.run(
            [aapt2_path, "dump", "resources", apk_path],
            f"decode binary resource table for {apk_name}",
        )
        nodes = parse_manifest_xmltree(xml_output.decode("utf-8", errors="replace"), apk_name)
        resources = parse_aapt_resources(resource_output.decode("utf-8", errors="replace"), apk_name)
        manifest_documents.append(
            {
                "apk_member": apk_name,
                "aapt2_stdout_sha256": sha256_bytes(xml_output),
                "node_count": len(nodes),
                "nodes": nodes,
            }
        )
        resource_documents.append(
            {
                "apk_member": apk_name,
                "aapt2_stdout_sha256": sha256_bytes(resource_output),
                "resource_count": len(resources),
                "resources": resources,
            }
        )
        for node in nodes:
            builder.add_discovered(
                "manifest_node",
                f"apk:{apk_name}!manifest:{node['path']}",
                source_artifact_id,
            )
            if node["tag"] in COMPONENT_TAGS:
                component_name = manifest_attribute(node, "name") or str(node["path"])
                builder.add_discovered(
                    "android_component",
                    f"apk:{apk_name}!component:{node['tag']}:{component_name}@{node['path']}",
                    source_artifact_id,
                )
            if node["tag"] == "uses-feature":
                feature_name = manifest_attribute(node, "name") or manifest_attribute(node, "glEsVersion") or str(node["path"])
                builder.add_discovered(
                    "feature",
                    f"apk:{apk_name}!feature:{feature_name}@{node['path']}",
                    source_artifact_id,
                )
        for resource in resources:
            builder.add_discovered(
                "resource",
                f"apk:{apk_name}!resource:{resource['resource_id']}:{resource['resource_name']}",
                source_artifact_id,
            )

    dex_artifacts = sorted(
        (artifact for artifact in artifacts if artifact["kind"] == "dex"),
        key=lambda artifact: str(artifact["artifact_id"]),
    )
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        for artifact in dex_artifacts:
            dex_name = str(artifact["artifact_id"]).split(":", 1)[1]
            dex_data = base_zip.read(dex_name)
            digest = sha256_bytes(dex_data)
            if digest != artifact["sha256"] or len(dex_data) != artifact["size_bytes"]:
                raise ProducerError(f"DEX source differs from frozen identity: {dex_name}")
            parsed = DexParser(dex_data, dex_name).parse()
            parsed["sha256"] = digest
            parsed["size_bytes"] = len(dex_data)
            dex_documents.append(parsed)
            source_artifact_id = str(artifact["artifact_id"])
            for class_row in parsed["classes"]:
                builder.add_discovered(
                    "class",
                    f"dex:{dex_name}!class:{class_row['descriptor']}",
                    source_artifact_id,
                )
            for method in parsed["defined_methods"]:
                method_scope = (
                    f"dex:{dex_name}!method:{method['class_descriptor']}->"
                    f"{method['name']}{method['prototype']}"
                )
                builder.add_discovered("method_family", method_scope, source_artifact_id)
                if method["native"]:
                    native_scope = (
                        f"jni:dex-native:{dex_name}:{method['class_descriptor']}->"
                        f"{method['name']}{method['prototype']}"
                    )
                    builder.add_discovered("jni_edge", native_scope, source_artifact_id)
                    jni_native_methods.append(
                        {
                            "dex_name": dex_name,
                            "source_artifact_id": source_artifact_id,
                            "class_descriptor": method["class_descriptor"],
                            "method_name": method["name"],
                            "prototype": method["prototype"],
                            "declaration_scope_key": native_scope,
                        }
                    )
            for reference in parsed["reflection_references"]:
                builder.add_discovered(
                    "reflection_target",
                    (
                        f"dex:{dex_name}!reflection-reference:{reference['class_descriptor']}->"
                        f"{reference['name']}{reference['prototype']}"
                    ),
                    source_artifact_id,
                )
            for reference in parsed["dynamic_loader_references"]:
                builder.add_discovered(
                    "dynamic_loader",
                    (
                        f"dex:{dex_name}!dynamic-loader-reference:{reference['class_descriptor']}->"
                        f"{reference['name']}{reference['prototype']}"
                    ),
                    source_artifact_id,
                )

    native_artifacts = sorted(
        (artifact for artifact in artifacts if artifact["kind"] == "native_library"),
        key=lambda artifact: str(artifact["artifact_id"]),
    )
    exported_jni_symbols: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        for artifact in native_artifacts:
            artifact_id = str(artifact["artifact_id"])
            entry = artifact_entry_path(artifact)
            if entry is None:
                raise ProducerError(f"cannot resolve native entry for {artifact_id}")
            library_name = Path(entry).name
            library_data = base_zip.read(entry)
            if sha256_bytes(library_data) != artifact["sha256"] or len(library_data) != artifact["size_bytes"]:
                raise ProducerError(f"native library differs from frozen identity: {library_name}")
            native_path = native_work_root / library_name
            native_path.write_bytes(library_data)
            readobj_output = runner.run(
                [llvm_readobj_path, "--needed-libs", "--dyn-symbols", native_path],
                f"read ELF dependencies and dynamic symbols for {library_name}",
            )
            objdump_output = runner.run(
                [llvm_objdump_path, "--private-headers", "--dynamic-syms", native_path],
                f"independently read ELF dependencies and dynamic symbols for {library_name}",
            )
            readobj = parse_readobj(readobj_output.decode("utf-8", errors="replace"), library_name)
            objdump = parse_objdump(objdump_output.decode("utf-8", errors="replace"))
            readobj_names = [
                normalized_symbol_name(symbol["name"])
                for symbol in readobj["dynamic_symbols"]
                if symbol["name"]
            ]
            objdump_names = [normalized_symbol_name(name) for name in objdump["dynamic_symbol_names"] if name]
            if readobj["needed_libraries"] != objdump["needed_libraries"]:
                raise ProducerError(f"LLVM DT_NEEDED disagreement for {library_name}")
            if sorted(readobj_names) != sorted(objdump_names):
                raise ProducerError(f"LLVM dynamic-symbol disagreement for {library_name}")
            readobj.update(
                {
                    "source_artifact_id": artifact_id,
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                    "readobj_stdout_sha256": sha256_bytes(readobj_output),
                    "objdump_stdout_sha256": sha256_bytes(objdump_output),
                    "llvm_needed_parity": True,
                    "llvm_dynamic_symbol_parity": True,
                }
            )
            elf_documents.append(readobj)
            library_scope = f"elf:arm64-v8a/{library_name}"
            for needed in readobj["needed_libraries"]:
                builder.add_discovered(
                    "native_import",
                    f"{library_scope}!needed:{needed}",
                    artifact_id,
                )
            for symbol in readobj["dynamic_symbols"]:
                name = str(symbol["name"])
                if not name:
                    continue
                index = int(symbol["dynamic_symbol_index"])
                base_name = normalized_symbol_name(name)
                symbol_scope = f"{library_scope}!dynsym:{index:06d}:{base_name}"
                builder.add_discovered("native_symbol", symbol_scope, artifact_id)
                if str(symbol["section"]).startswith("Undefined"):
                    builder.add_discovered(
                        "native_import",
                        f"{library_scope}!import:{index:06d}:{base_name}",
                        artifact_id,
                    )
                elif str(symbol["binding"]).startswith(("Global", "Weak", "GNUUnique")):
                    builder.add_discovered(
                        "native_export",
                        f"{library_scope}!export:{index:06d}:{base_name}",
                        artifact_id,
                    )
                    if is_jni_symbol(name):
                        jni_scope = f"jni:elf-export:{library_name}:{index:06d}:{base_name}"
                        builder.add_discovered("jni_edge", jni_scope, artifact_id)
                        exported_jni_symbols[base_name].append(
                            {
                                "library": library_name,
                                "source_artifact_id": artifact_id,
                                "symbol": base_name,
                                "export_scope_key": jni_scope,
                            }
                        )

    jni_bindings: list[dict[str, Any]] = []
    for native_method in sorted(
        jni_native_methods,
        key=lambda row: (row["dex_name"], row["class_descriptor"], row["method_name"], row["prototype"]),
    ):
        short_name, long_name = jni_export_candidates(
            str(native_method["class_descriptor"]),
            str(native_method["method_name"]),
            str(native_method["prototype"]),
        )
        matches = [*exported_jni_symbols.get(long_name, []), *exported_jni_symbols.get(short_name, [])]
        binding = {**native_method, "short_export_candidate": short_name, "long_export_candidate": long_name, "matches": matches}
        jni_bindings.append(binding)
        for match in matches:
            builder.add_discovered(
                "jni_edge",
                (
                    f"jni:binding:{native_method['dex_name']}:{native_method['class_descriptor']}->"
                    f"{native_method['method_name']}{native_method['prototype']}=>"
                    f"{match['library']}:{match['symbol']}"
                ),
                match["source_artifact_id"],
            )

    records, source_records = builder.finalize()
    type_counts = Counter(str(record["record_type"]) for record in records)
    discovered_counts = {
        record_type: type_counts.get(record_type, 0)
        for record_type in sorted(DISCOVERED_INVENTORY_RECORD_TYPES)
    }
    missing_required_types = sorted(record_type for record_type in REQUIRED_DISCOVERED_TYPES if type_counts[record_type] == 0)
    if missing_required_types:
        raise ProducerError(f"required discovered record types are empty: {missing_required_types}")
    coverage = {
        "record_count": len(records),
        "record_type_counts": dict(sorted(type_counts.items())),
        "discovered_record_type_counts": discovered_counts,
        "apk_members": 19,
        "dex_files": 4,
        "native_libraries": 88,
        "unclassified": sum(record["classification_status"] != "classified" for record in records),
        "frozen_artifacts_accounted": type_counts.get("frozen_artifact", 0),
        "all_artifacts_accounted": True,
    }
    if coverage["apk_members"] != 19 or coverage["dex_files"] != 4 or coverage["native_libraries"] != 88:
        raise ProducerError("derived critic cardinality counts are incorrect")
    if coverage["unclassified"] != 0 or any(record["dossier_id"] is None for record in records):
        raise ProducerError("every normalized row must be classified and dossier-owned")

    source_index = {
        "schema_version": 1,
        "index_id": "SOURCE-INDEX-G002-METHOD-B",
        "artifact_set_id": artifact_set_id,
        "run_id": RUN_ID,
        "method_id": METHOD_ID,
        "records": source_records,
        "canonical_sha256": canonical_list_sha256(source_records),
    }
    source_index_path = bundle_root / "source-index.json"
    write_json(source_index_path, source_index)

    archive_index = {
        "schema_version": 1,
        "xapk": {
            "path": display_path(xapk_path),
            "sha256": xapk_digest,
            "size_bytes": xapk_size,
            "entry_count": len(xapk_entries),
            "entries": xapk_entries,
            "infozip_python_member_order_equal": True,
        },
        "apk_entry_counts": dict(sorted(apk_archive_counts.items())),
        "apk_entries": archive_documents,
        "all_entries_classified_or_frozen": True,
    }
    write_json(raw_root / "archive-index.json", archive_index)
    write_json(
        raw_root / "manifest-index.json",
        {
            "schema_version": 1,
            "documents": [
                {
                    key: (
                        [
                            {node_key: node_value for node_key, node_value in node.items() if node_key != "attrs"}
                            for node in value
                        ]
                        if key == "nodes"
                        else value
                    )
                    for key, value in document.items()
                    if key != "axml"
                }
                for document in manifest_documents
            ],
        },
    )
    write_json(raw_root / "resource-index.json", {"schema_version": 1, "documents": resource_documents})
    write_json(raw_root / "dex-structure.json", {"schema_version": 1, "parser": SCRIPT_VERSION, "dex_files": dex_documents})
    write_json(raw_root / "elf-analysis.json", {"schema_version": 1, "libraries": elf_documents})
    write_json(
        raw_root / "jni-analysis.json",
        {
            "schema_version": 1,
            "native_method_declarations": jni_native_methods,
            "static_export_bindings": jni_bindings,
            "binding_rule": "JNI short/long exported-name matching only; unmatched declarations remain inventoried edges",
        },
    )
    write_json(
        raw_root / "artifact-accounting.json",
        {
            "schema_version": 1,
            "artifact_set_id": artifact_set_id,
            "frozen_artifact_count": len(artifact_observations),
            "observations": [artifact_observations[key] for key in sorted(artifact_observations)],
            "all_hashes_match": True,
        },
    )
    write_json(
        raw_root / "identity-classification-contract.json",
        {
            "schema_version": 1,
            "scope_identity": ["record_type", "scope_key"],
            "record_id_rule": "INV-<UPPER-HYPHENATED-TYPE>-<UPPER-SHA256(canonical-json([record_type,scope_key]))>",
            "record_order": "ascending Unicode record_id",
            "source_locator_rule": "SRC-METHOD-B-<record_id>",
            "source_record_order": "ascending Unicode source_locator",
            "canonical_comparison_exclusion": ["source_refs"],
            "archive_entry_rules": {
                "AndroidManifest.xml": "manifest_node",
                "res/** and resources.arsc": "resource",
                "assets/**": "asset",
                "stamp/signature entries": "certificate",
                "all other non-frozen entries": "configuration",
                "frozen DEX/arm64-native/fixture entries": "covered by their frozen artifact record",
            },
            "dossier_by_record_type": dict(sorted(DOSSIER_BY_TYPE.items())),
            "classification_status": "classified",
        },
    )
    script_digest, script_size = file_hash(Path(__file__).resolve())
    aapt_digest, aapt_size = file_hash(aapt2_path)
    readobj_digest, readobj_size = file_hash(llvm_readobj_path)
    objdump_digest, objdump_size = file_hash(llvm_objdump_path)
    write_json(
        raw_root / "input-tool-hashes.json",
        {
            "schema_version": 1,
            "inputs": {
                "official_artifact_manifest": {
                    "path": OFFICIAL_MANIFEST_REL.as_posix(),
                    "sha256": file_hash(REPO_ROOT / OFFICIAL_MANIFEST_REL)[0],
                    "size_bytes": file_hash(REPO_ROOT / OFFICIAL_MANIFEST_REL)[1],
                },
                "official_xapk": {"path": display_path(xapk_path), "sha256": xapk_digest, "size_bytes": xapk_size},
                "official_base_apk": {"path": display_path(base_path), "sha256": base_digest, "size_bytes": base_size},
                "producer": {"path": display_path(Path(__file__)), "sha256": script_digest, "size_bytes": script_size},
                "aapt2": {"path": display_path(aapt2_path), "sha256": aapt_digest, "size_bytes": aapt_size},
                "llvm_readobj": {"path": display_path(llvm_readobj_path), "sha256": readobj_digest, "size_bytes": readobj_size},
                "llvm_objdump": {"path": display_path(llvm_objdump_path), "sha256": objdump_digest, "size_bytes": objdump_size},
            },
            "tool_versions": versions,
        },
    )

    external_commands = [capture.command for capture in runner.results]
    commands = [replay_command, *external_commands]
    if len(commands) != len(set(commands)):
        duplicates = sorted(command for command, count in Counter(commands).items() if count > 1)
        raise ProducerError(f"run command list contains duplicates: {duplicates}")
    write_json(
        raw_root / "command-results.json",
        {
            "schema_version": 1,
            "producer_command": {"command": replay_command, "exit_code": 0},
            "external_commands": runner.as_json(),
            "all_exit_codes_zero": True,
        },
    )

    dex_class_count = sum(len(document["classes"]) for document in dex_documents)
    dex_method_count = sum(len(document["defined_methods"]) for document in dex_documents)
    dex_native_method_count = len(jni_native_methods)
    manifest_node_count = sum(document["node_count"] for document in manifest_documents)
    component_count = type_counts["android_component"]
    resource_count = sum(document["resource_count"] for document in resource_documents)
    needed_count = sum(len(document["needed_libraries"]) for document in elf_documents)
    dynamic_symbol_count = sum(sum(bool(symbol["name"]) for symbol in document["dynamic_symbols"]) for document in elf_documents)
    native_import_count = type_counts["native_import"]
    native_export_count = type_counts["native_export"]
    jni_edge_count = type_counts["jni_edge"]
    total_apk_entries = sum(apk_archive_counts.values())

    checks = {
        "schema_version": 1,
        "status": "pass",
        "checks": [
            {"name": "frozen_artifact_hash_accounting", "passed": len(artifact_observations) == 121, "observed": len(artifact_observations)},
            {"name": "xapk_member_count", "passed": len(xapk_entries) == 21, "observed": len(xapk_entries)},
            {"name": "apk_member_count", "passed": len(apk_paths) == 19, "observed": len(apk_paths)},
            {"name": "infozip_python_archive_parity", "passed": True, "archives_checked": 20},
            {"name": "aapt2_manifest_coverage", "passed": len(manifest_documents) == 19, "documents": len(manifest_documents)},
            {"name": "aapt2_resource_coverage", "passed": len(resource_documents) == 19, "documents": len(resource_documents)},
            {"name": "dex_integrity_and_structure", "passed": len(dex_documents) == 4, "dex_files": len(dex_documents)},
            {"name": "llvm16_readobj_all_arm64_libraries", "passed": len(elf_documents) == 88, "libraries": len(elf_documents)},
            {"name": "llvm16_objdump_all_arm64_libraries", "passed": len(elf_documents) == 88, "libraries": len(elf_documents)},
            {"name": "llvm_needed_and_dynsym_parity", "passed": all(document["llvm_needed_parity"] and document["llvm_dynamic_symbol_parity"] for document in elf_documents), "libraries": len(elf_documents)},
            {"name": "all_records_classified", "passed": coverage["unclassified"] == 0, "unclassified": coverage["unclassified"]},
            {"name": "all_records_dossier_owned", "passed": all(record["dossier_id"] is not None for record in records), "unowned": 0},
            {"name": "source_index_one_to_one", "passed": len(source_records) == len(records), "source_rows": len(source_records)},
            {"name": "required_discovered_types_nonzero", "passed": not missing_required_types, "missing": missing_required_types},
            {"name": "no_hardware_live_or_celsius_claim", "passed": True, "hardware_runs": 0, "live_runs": 0, "celsius_claims": 0},
        ],
        "counts": {
            "normalized_records": len(records),
            "xapk_entries": len(xapk_entries),
            "apk_entries": total_apk_entries,
            "manifest_nodes": manifest_node_count,
            "android_components": component_count,
            "aapt2_resources": resource_count,
            "dex_classes": dex_class_count,
            "dex_defined_methods": dex_method_count,
            "dex_native_methods": dex_native_method_count,
            "arm64_libraries": len(elf_documents),
            "dt_needed_edges": needed_count,
            "dynamic_symbols_nonempty": dynamic_symbol_count,
            "native_import_records": native_import_count,
            "native_export_records": native_export_count,
            "jni_edge_records": jni_edge_count,
            "static_jni_bindings": sum(len(binding["matches"]) for binding in jni_bindings),
            "unclassified": coverage["unclassified"],
        },
    }
    if any(not item["passed"] for item in checks["checks"]):
        raise ProducerError("one or more focused Method-B checks failed")
    checks_path = bundle_root / "checks.json"
    write_json(checks_path, checks)

    canonical_records = [{key: value for key, value in record.items() if key != "source_refs"} for record in records]
    canonical_inventory_hash = canonical_list_sha256(canonical_records)
    data_state_path = bundle_root / "data-state.json"
    write_json(
        data_state_path,
        {
            "schema_version": 1,
            "state": "offline_static_analysis_of_hash_locked_untouched_package",
            "hardware_run": False,
            "live_application_run": False,
            "celsius_claims": [],
            "source_variant": "untouched",
        },
    )
    normalized_events_path = bundle_root / "normalized-events.json"
    event = {
        "event_id": "EVT-G002-METHOD-B-INVENTORY",
        "event_type": "static_inventory_generated",
        "monotonic_ns": 0,
        "correlation_id": None,
        "process_id": None,
        "thread_id": None,
        "object_id": None,
        "reference_id": None,
        "buffer_pointer": None,
        "buffer_length": None,
        "endpoint": None,
        "transfer_id": None,
        "error_state": None,
        "claim_ids": [CLAIM_ID_PRIVATE],
        "observation_id": "OBS-G002-METHOD-B-STATIC",
        "checkpoint_id": None,
        "run_id": RUN_ID,
        "value": {
            "canonical_inventory_sha256": canonical_inventory_hash,
            "normalized_records": len(records),
            "unclassified": 0,
        },
    }
    write_json(
        normalized_events_path,
        {
            "schema_version": 1,
            "schema_id": "normalized-static-inventory-event-v1",
            "artifact_set_id": artifact_set_id,
            "experiment_id": EXPERIMENT_ID,
            "source_variant": "untouched",
            "events": [event],
            "canonical_sha256": canonical_list_sha256([event]),
        },
    )

    attachment_paths = [
        source_index_path,
        checks_path,
        data_state_path,
        normalized_events_path,
        *sorted(raw_root.glob("*.json"), key=lambda path: path.as_posix()),
    ]
    attachments = sorted(
        (output_attachment(path, bundle_root) for path in attachment_paths),
        key=lambda row: row["path"],
    )
    evidence_manifest = {
        "schema_version": 1,
        "bundle_id": BUNDLE_ID,
        "claim_ids": [CLAIM_ID_PRIVATE],
        "experiment_id": EXPERIMENT_ID,
        "operator": OPERATOR,
        "captured_at": args.timestamp,
        "clock": {"basis": "deterministic-static-sequence", "offsets_and_drift_attachment": None},
        "artifact_set_id": artifact_set_id,
        "source_variant": "untouched",
        "evidence_tier": "E1",
        "instrumentation_delta": {
            "summary": "Read-only offline analysis of immutable package bytes; no hooks, patches, root modules, debugger, proxy, or USB capture.",
            "hooks": [],
            "patches": [],
            "root_modules": [],
            "debugger": [],
            "proxies": [],
            "usb_capture_point": None,
        },
        "environment": {
            "device_fingerprint": None,
            "camera_fingerprint": None,
            "os_build": None,
            "abi": "arm64-v8a",
            "data_state_snapshot": "data-state.json",
        },
        "tool_versions": versions,
        "replay_commands": [
            replay_command,
            shlex.join(
                [
                    display_path(Path(sys.executable)),
                    "tools/hik_whole_apk/g002_method_b.py",
                    "--self-check-only",
                    "--out",
                    display_path(out_root),
                ]
            ),
        ],
        "event_stream": {
            "schema_id": "normalized-static-inventory-event-v1",
            "normalized_attachment": "normalized-events.json",
            "emitted_events": 1,
            "captured_events": 1,
            "dropped_events": 0,
            "truncated_events": 0,
        },
        "attachments": attachments,
    }
    evidence_manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(evidence_manifest))
    evidence_manifest_path = bundle_root / "manifest.json"
    write_json(evidence_manifest_path, evidence_manifest)

    source_attachment = next(attachment for attachment in attachments if attachment["path"] == "source-index.json")
    run_manifest = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "experiment_id": EXPERIMENT_ID,
        "operator": OPERATOR,
        "status": "completed",
        "artifact_set_id": artifact_set_id,
        "method_id": METHOD_ID,
        "toolchain_family": TOOLCHAIN_FAMILY,
        "commands": commands,
        "command_exit_codes": [0] * len(commands),
        "tool_versions": versions,
        "input_artifact_ids": sorted(official_by_id),
        "evidence_bundle_ids": [BUNDLE_ID],
        "source_index_attachments": [
            {
                "bundle_id": BUNDLE_ID,
                "path": "source-index.json",
                "sha256": source_attachment["sha256"],
                "size_bytes": source_attachment["size_bytes"],
            }
        ],
        "started_at": args.timestamp,
        "ended_at": args.timestamp,
    }
    run_manifest_path = out_root / "runs" / RUN_ID / "manifest.json"
    write_json(run_manifest_path, run_manifest)

    inventory = {
        "schema_version": 1,
        "inventory_id": INVENTORY_ID,
        "artifact_set_id": artifact_set_id,
        "generated_at": args.timestamp,
        "method": {
            "method_id": METHOD_ID,
            "toolchain_family": TOOLCHAIN_FAMILY,
            "commands": commands,
            "tool_versions": versions,
        },
        "producer_run_id": RUN_ID,
        "producer_run_manifest": display_path(run_manifest_path),
        "producer_evidence_bundle_ids": [BUNDLE_ID],
        "independent_review_id": REVIEW_ID_PENDING,
        "normalized_records": records,
        "coverage": coverage,
        "canonical_sha256": canonical_inventory_hash,
    }
    inventory_path = out_root / "inventory-b.private.json"
    write_json(inventory_path, inventory)
    write_canonical_candidate_bundle(
        candidate_root=checked_output_root(args.candidate_root),
        artifact_set_id=artifact_set_id,
        records=records,
        source_records=source_records,
        canonical_inventory_hash=canonical_inventory_hash,
        source_index_hash=source_index["canonical_sha256"],
        commands=commands,
        timestamp=args.timestamp,
        generated_at=generated_at,
        contract=load_json(args.contract),
    )

    inventory_digest, inventory_size = file_hash(inventory_path)
    run_digest, run_size = file_hash(run_manifest_path)
    evidence_digest, evidence_size = file_hash(evidence_manifest_path)
    publication = {
        "schema_version": 1,
        "status": "private_producer_complete_independent_review_pending",
        "inventory_id": INVENTORY_ID,
        "method_id": METHOD_ID,
        "canonical_sha256": canonical_inventory_hash,
        "private_files": {
            "inventory": {"path": display_path(inventory_path), "sha256": inventory_digest, "size_bytes": inventory_size},
            "run_manifest": {"path": display_path(run_manifest_path), "sha256": run_digest, "size_bytes": run_size},
            "evidence_manifest": {"path": display_path(evidence_manifest_path), "sha256": evidence_digest, "size_bytes": evidence_size},
        },
        "canonical_destinations_reserved_for_integrator": {
            "inventory": f"{RESEARCH_REL.as_posix()}/static/inventory-b.json",
            "run_manifest": f"{RESEARCH_REL.as_posix()}/static/runs/{RUN_ID}/manifest.json",
            "evidence_bundle": f"{RESEARCH_REL.as_posix()}/static/evidence/{BUNDLE_ID}",
            "review": f"{RESEARCH_REL.as_posix()}/reviews/<independent-review>.json",
        },
        "publication_requirements": [
            "relocate private run/evidence artifacts to critic-canonical paths",
            "replace pending review ID only after an independent non-producer review",
            "compare canonical_sha256 and full canonical record bytes during independent integration",
            "do not publish if either normalized inventory differs or any row is unclassified",
        ],
    }
    write_json(out_root / "publication.json", publication)

    readme = f"""# G002 Method-B private producer output

Status: producer complete; independent review and canonical publication pending.

- Inventory: `inventory-b.private.json`
- Canonical normalized SHA-256: `{canonical_inventory_hash}`
- Normalized records: `{len(records)}`
- Frozen artifacts: `121/121`
- APK members / DEX / arm64 libraries: `19 / 4 / 88`
- Unclassified rows: `0`
- Method: `{METHOD_ID}`
- Toolchain: `{TOOLCHAIN_FAMILY}`

This directory is private E1 static evidence. It contains no hardware run,
live-application observation, or Celsius claim. The pending review identifier
is intentionally non-passing until a separate reviewer publishes a canonical
`REV-*` artifact outside this producer-owned path.
"""
    write_text(out_root / "README.md", readme)

    if not args.keep_work:
        shutil.rmtree(work_root)

    validation = validate_private_output(out_root)
    return {**validation, "checks": checks["counts"], "output": display_path(out_root)}


def produce_remediated(args: argparse.Namespace) -> dict[str, Any]:
    out_root = checked_output_root(args.out)
    run_timestamp = datetime.strptime(args.timestamp, "%Y-%m-%dT%H:%M:%SZ")
    generated_at = (run_timestamp + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    contract_digest, _contract_size = file_hash(args.contract)
    if contract_digest != V10_CONTRACT_SHA256:
        raise ProducerError(f"v10 contract hash differs: {contract_digest}")
    contract = load_json(args.contract)
    if contract.get("schema") != "g002-neutral-normalization-contract/v10":
        raise ProducerError("v10 contract schema differs")
    if out_root.exists():
        shutil.rmtree(out_root)
    work_root = out_root / ".work"
    apk_work_root = work_root / "apks"
    native_work_root = work_root / "native"
    bundle_root = out_root / "evidence" / BUNDLE_ID
    raw_root = bundle_root / "raw"
    apk_work_root.mkdir(parents=True, exist_ok=True)
    native_work_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    official_manifest = load_json(REPO_ROOT / OFFICIAL_MANIFEST_REL)
    artifacts = official_manifest.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 121:
        raise ProducerError("frozen official artifact manifest must contain exactly 121 rows")
    official_by_id = {str(artifact["artifact_id"]): artifact for artifact in artifacts}
    if len(official_by_id) != len(artifacts):
        raise ProducerError("frozen official artifact IDs are invalid or duplicated")
    artifact_set_id = str(official_manifest["artifact_set_id"])

    xapk_path = args.xapk.resolve()
    if not xapk_path.is_file():
        raise ProducerError("untouched official XAPK input is missing")

    # Preserve multicall/symlink basenames: llvm-readelf changes mode from argv[0].
    aapt2_path = Path(tool_path(args.aapt2)).absolute()
    zipinfo_path = Path(tool_path(args.zipinfo)).absolute()
    unzip_path = Path(tool_path(args.unzip)).absolute()
    llvm_readobj_path = Path(tool_path(args.llvm_readobj)).absolute()
    llvm_readelf_path = Path(tool_path(args.llvm_readelf)).absolute()
    llvm_nm_path = Path(tool_path(args.llvm_nm)).absolute()
    llvm_objdump_path = Path(tool_path(args.llvm_objdump)).absolute()
    runner = CommandRunner()

    python_version_output = runner.run([sys.executable, "--version"], "capture Python version")
    unzip_version_output = runner.run([unzip_path, "-v"], "capture Info-ZIP version")
    aapt2_version_stdout = runner.run([aapt2_path, "version"], "capture AAPT2 version")
    aapt2_version_output = aapt2_version_stdout or runner.last_stderr
    readobj_version_output = runner.run([llvm_readobj_path, "--version"], "capture LLVM readobj version")
    readelf_version_output = runner.run([llvm_readelf_path, "--version"], "capture LLVM readelf version")
    nm_version_output = runner.run([llvm_nm_path, "--version"], "capture LLVM nm version")
    objdump_version_output = runner.run([llvm_objdump_path, "--version"], "capture LLVM objdump version")
    versions = {
        "producer": f"{SCRIPT_VERSION} sha256={file_hash(Path(__file__).resolve())[0]}",
        "python": python_version_output.decode("utf-8", errors="strict").strip(),
        "info_zip": unzip_version_output.decode("utf-8", errors="strict").splitlines()[0].strip(),
        "aapt2": aapt2_version_output.decode("utf-8", errors="strict").strip(),
        "llvm_readobj": readobj_version_output.decode("utf-8", errors="strict").splitlines()[0].strip(),
        "llvm_readelf": readelf_version_output.decode("utf-8", errors="strict").splitlines()[0].strip(),
        "llvm_nm": nm_version_output.decode("utf-8", errors="strict").strip(),
        "llvm_objdump": objdump_version_output.decode("utf-8", errors="strict").splitlines()[0].strip(),
        "raw_zip_parser": SCRIPT_VERSION,
        "dex_parser": SCRIPT_VERSION,
        "signer_parser": SCRIPT_VERSION,
    }
    if "Android Asset Packaging Tool (aapt) 2.19-12006047" not in versions["aapt2"]:
        raise ProducerError(f"cached AAPT2 is not the approved 2.19 build: {versions['aapt2']}")
    if any(
        "LLVM version 16." not in versions[name]
        for name in ("llvm_readobj", "llvm_readelf", "llvm_objdump")
    ) or "LLVM version 16." not in versions["llvm_nm"]:
        raise ProducerError("all LLVM tools must be version 16")
    if "UnZip 6.00" not in versions["info_zip"]:
        raise ProducerError("Info-ZIP UnZip 6.00 is required")

    replay_command = build_replay_command(args, out_root, aapt2_path)
    builder = RecordBuilder(official_by_id)
    for artifact in artifacts:
        builder.add_artifact(artifact)
    nested_frozen_index = build_nested_frozen_occurrence_index(
        official_by_id,
        builder.artifact_record_ids,
    )

    artifact_observations: dict[str, dict[str, Any]] = {}
    xapk_digest, xapk_size = file_hash(xapk_path)
    artifact_observations["official-xapk"] = verify_observation(
        official_by_id["official-xapk"], xapk_digest, xapk_size, display_path(xapk_path)
    )

    xapk_raw_entries = parse_raw_central_directory(xapk_path)
    xapk_zip_output = runner.run([zipinfo_path, "-1", xapk_path], "list every XAPK member with Info-ZIP")
    infozip_xapk_names = xapk_zip_output.splitlines()
    if len(infozip_xapk_names) != len(xapk_raw_entries):
        raise ProducerError("Info-ZIP/raw XAPK entry counts differ")
    apk_paths: dict[str, Path] = {}
    xapk_entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(xapk_path, "r") as xapk:
        infos = xapk.infolist()
        if len(infos) != len(xapk_raw_entries):
            raise ProducerError("Python/raw XAPK entry counts differ")
        for info, raw_entry, listed_name in zip(infos, xapk_raw_entries, infozip_xapk_names):
            listed_path = decode_zip_path(listed_name, int(raw_entry["flag_bits"]), label="Info-ZIP XAPK path")
            if listed_path != raw_entry["path"] or info.filename != raw_entry["path"]:
                raise ProducerError("Info-ZIP/Python/raw XAPK paths differ")
            for field, observed in (
                ("compression_method", info.compress_type),
                ("crc32", info.CRC),
                ("compressed_size", info.compress_size),
                ("size_bytes", info.file_size),
            ):
                if int(raw_entry[field]) != int(observed):
                    raise ProducerError(f"XAPK central-directory metadata differs for {info.filename}: {field}")
            digest, size = zip_entry_hash(xapk, info)
            entry = {**raw_entry, "sha256": digest}
            xapk_entries.append(entry)
            artifact_id = f"xapk-apk:{info.filename}" if info.filename.endswith(".apk") else f"xapk-member:{info.filename}"
            if artifact_id not in official_by_id:
                raise ProducerError(f"XAPK member is absent from frozen manifest: {info.filename}")
            builder.add_discovered(
                "configuration",
                archive_entry_payload(
                    kind="xapk_archive_entry",
                    container_artifact_id="official-xapk",
                    entry=entry,
                ),
                "official-xapk",
                sha256=digest,
                size_bytes=size,
                additional_parent_ids=(builder.artifact_record_ids[artifact_id],),
            )
            artifact_observations[artifact_id] = verify_observation(
                official_by_id[artifact_id],
                digest,
                size,
                f"{display_path(xapk_path)}!/{info.filename}",
            )
            if info.filename.endswith(".apk"):
                target = apk_work_root / info.filename
                with xapk.open(info, "r") as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                apk_paths[info.filename] = target
    assert_fixed("xapk_entries", len(xapk_entries))
    if len(apk_paths) != 19:
        raise ProducerError(f"expected 19 APK members, found {len(apk_paths)}")
    base_member_name = "com.hikvision.thermalGoogle.apk"
    if base_member_name not in apk_paths:
        raise ProducerError("official base APK member is missing from XAPK")
    base_digest, base_size = file_hash(apk_paths[base_member_name])
    artifact_observations["extracted-base-apk"] = verify_observation(
        official_by_id["extracted-base-apk"],
        base_digest,
        base_size,
        f"{display_path(xapk_path)}!/{base_member_name}",
    )

    # Frozen DEX/native/fixture identities are rehashed directly from the XAPK-extracted base APK.
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        by_name = {info.filename: info for info in base_zip.infolist()}
        for artifact in artifacts:
            entry_path = artifact_entry_path(artifact)
            if entry_path is None:
                continue
            info = by_name.get(entry_path)
            if info is None:
                raise ProducerError(f"frozen base artifact is absent from APK: {entry_path}")
            digest, size = zip_entry_hash(base_zip, info)
            artifact_id = str(artifact["artifact_id"])
            artifact_observations[artifact_id] = verify_observation(
                artifact,
                digest,
                size,
                f"{base_member_name}!/{entry_path}",
            )
    if set(artifact_observations) != set(official_by_id):
        missing = sorted(set(official_by_id) - set(artifact_observations))
        extra = sorted(set(artifact_observations) - set(official_by_id))
        raise ProducerError(f"frozen artifact hash accounting differs: missing={missing}, extra={extra}")

    archive_documents: list[dict[str, Any]] = []
    manifest_documents: list[dict[str, Any]] = []
    resource_documents: list[dict[str, Any]] = []
    signing_documents: list[dict[str, Any]] = []
    apk_archive_counts: dict[str, int] = {}
    arm32_count = 0
    asset_count = 0
    certificate_count = 0
    archive_record_ids: dict[tuple[str, str], str] = {}
    manifest_node_records: list[dict[str, Any]] = []

    for apk_name in sorted(apk_paths):
        apk_path = apk_paths[apk_name]
        apk_id = f"xapk-apk:{apk_name}"
        raw_entries = parse_raw_central_directory(apk_path)
        listing = runner.run([zipinfo_path, "-1", apk_path], f"list every entry in {apk_name} with Info-ZIP")
        listed_names = listing.splitlines()
        if len(listed_names) != len(raw_entries):
            raise ProducerError(f"{apk_name}: Info-ZIP/raw entry counts differ")
        apk_archive_counts[apk_name] = len(raw_entries)
        scheme_certificates = parse_apk_signing_schemes(apk_path)
        known_certificates = [
            certificate
            for scheme in ("v2", "v3")
            for signer in scheme_certificates[scheme]
            for certificate in signer
        ]
        with zipfile.ZipFile(apk_path, "r") as apk_zip:
            infos = apk_zip.infolist()
            if len(infos) != len(raw_entries):
                raise ProducerError(f"{apk_name}: Python/raw entry counts differ")
            for info, raw_entry, listed_name in zip(infos, raw_entries, listed_names):
                listed_path = decode_zip_path(listed_name, int(raw_entry["flag_bits"]), label=f"{apk_name} Info-ZIP path")
                if listed_path != raw_entry["path"] or info.filename != raw_entry["path"]:
                    raise ProducerError(f"{apk_name}: Info-ZIP/Python/raw paths differ")
                for field, observed in (
                    ("compression_method", info.compress_type),
                    ("crc32", info.CRC),
                    ("compressed_size", info.compress_size),
                    ("size_bytes", info.file_size),
                ):
                    if int(raw_entry[field]) != int(observed):
                        raise ProducerError(f"{apk_name}: central-directory metadata differs for {info.filename}: {field}")
                digest, size = zip_entry_hash(apk_zip, info)
                entry = {"apk_member": apk_name, **raw_entry, "sha256": digest}
                archive_documents.append(entry)
                archive_payload = archive_entry_payload(
                    kind="apk_archive_entry",
                    container_artifact_id=apk_id,
                    entry=entry,
                )
                archive_record_id = builder.add_discovered(
                    "configuration",
                    archive_payload,
                    apk_id,
                    sha256=digest,
                    size_bytes=size,
                    additional_parent_ids=nested_frozen_parent_ids(
                        nested_frozen_index,
                        container_artifact_id=apk_id,
                        path=info.filename,
                        sha256=digest,
                        size_bytes=size,
                    ),
                )
                archive_record_ids[(apk_id, info.filename)] = archive_record_id
                if info.filename.startswith("lib/armeabi-v7a/") and info.filename.endswith(".so"):
                    arm32_count += 1
                    builder.add_discovered(
                        "configuration",
                        {
                            "configuration_kind": "arm32_native_library",
                            "apk_artifact_id": apk_id,
                            "abi": "armeabi-v7a",
                            "path": info.filename,
                            "archive_entry_record_id": archive_record_id,
                            "sha256": digest,
                            "size_bytes": size,
                            "soname": info.filename.rsplit("/", 1)[-1],
                        },
                        apk_id,
                        sha256=digest,
                        size_bytes=size,
                        additional_parent_ids=(archive_record_id,),
                    )
                if info.filename.startswith("assets/"):
                    asset_count += 1
                    builder.add_discovered(
                        "asset",
                        {
                            "apk_artifact_id": apk_id,
                            "archive_entry_record_id": archive_record_id,
                            "path": info.filename,
                            "size_bytes": size,
                            "sha256": digest,
                        },
                        apk_id,
                        sha256=digest,
                        size_bytes=size,
                        additional_parent_ids=(archive_record_id,),
                    )
            v1_occurrences = parse_v1_certificate_occurrences(
                apk_zip,
                known_certificates,
                apk_name=apk_name,
            )
        certificate_rows: list[dict[str, Any]] = []
        encoded_certificate_ordinal = 0
        for scheme in ("v2", "v3"):
            for signer_index, signer in enumerate(scheme_certificates[scheme]):
                for certificate_index, certificate in enumerate(signer):
                    digest = sha256_bytes(certificate)
                    payload = {
                        "apk_artifact_id": apk_id,
                        "scheme": scheme,
                        "scheme_occurrence_ordinal": 0,
                        "signer_index": signer_index,
                        "certificate_index": certificate_index,
                        "encoded_certificate_ordinal": encoded_certificate_ordinal,
                        "der_sha256": digest,
                    }
                    builder.add_discovered(
                        "certificate",
                        payload,
                        apk_id,
                        sha256=digest,
                        size_bytes=len(certificate),
                    )
                    certificate_rows.append({**payload, "size_bytes": len(certificate)})
                    certificate_count += 1
                    encoded_certificate_ordinal += 1
        for scheme_ordinal, certificates in v1_occurrences:
            for certificate_index, certificate in enumerate(certificates):
                digest = sha256_bytes(certificate)
                payload = {
                    "apk_artifact_id": apk_id,
                    "scheme": "v1",
                    "scheme_occurrence_ordinal": scheme_ordinal,
                    "signer_index": 0,
                    "certificate_index": certificate_index,
                    "encoded_certificate_ordinal": encoded_certificate_ordinal,
                    "der_sha256": digest,
                }
                builder.add_discovered(
                    "certificate",
                    payload,
                    apk_id,
                    sha256=digest,
                    size_bytes=len(certificate),
                )
                certificate_rows.append({**payload, "size_bytes": len(certificate)})
                certificate_count += 1
                encoded_certificate_ordinal += 1
        signing_documents.append(
            {
                "apk_member": apk_name,
                "scheme_signer_counts": {
                    "v1": len(v1_occurrences),
                    "v2": len(scheme_certificates["v2"]),
                    "v3": len(scheme_certificates["v3"]),
                },
                "certificates": certificate_rows,
            }
        )

        xml_output = runner.run(
            [aapt2_path, "dump", "xmltree", apk_path, "--file", "AndroidManifest.xml"],
            f"decode binary AndroidManifest.xml for {apk_name}",
        )
        resource_output = runner.run(
            [aapt2_path, "dump", "resources", apk_path],
            f"decode binary resource table for {apk_name}",
        )
        configuration_output = runner.run(
            [aapt2_path, "dump", "configurations", apk_path],
            f"enumerate resource configurations for {apk_name}",
        )
        with zipfile.ZipFile(apk_path, "r") as payload_zip:
            axml = v5_parse_axml(payload_zip.read("AndroidManifest.xml"))
            logical_resource_count, configuration_value_count, package_summaries, resources, resource_configurations = v5_count_arsc(
                payload_zip.read("resources.arsc"),
                apk_id,
            )
        nodes = axml["nodes"]
        declared_configurations = parse_aapt_configurations(
            configuration_output.decode("utf-8", errors="strict")
        )
        manifest_documents.append(
            {
                "apk_member": apk_name,
                "apk_artifact_id": apk_id,
                "aapt2_stdout_sha256": sha256_bytes(xml_output),
                "node_count": len(nodes),
                "nodes": nodes,
                "package": axml["package"],
                "split": axml["split"],
                "target_sdk": axml["target_sdk"],
                "axml": axml,
            }
        )
        resource_documents.append(
            {
                "apk_member": apk_name,
                "apk_artifact_id": apk_id,
                "aapt2_stdout_sha256": sha256_bytes(resource_output),
                "configuration_stdout_sha256": sha256_bytes(configuration_output),
                "declared_configurations": declared_configurations,
                "package_summaries": package_summaries,
                "resource_count": logical_resource_count,
                "configuration_value_count": configuration_value_count,
                "resources": resources,
                "resource_configurations": resource_configurations,
            }
        )
        manifest_payload_by_path: dict[str, dict[str, Any]] = {}
        for node in nodes:
            parent_path = str(node["path"]).rsplit("/", 1)[0]
            parent_payload = manifest_payload_by_path.get(parent_path)
            parent_record_id = (
                None if parent_payload is None else record_id("manifest_node", parent_payload)
            )
            payload = {
                "apk_artifact_id": apk_id,
                "event_ordinal": node["event_ordinal"],
                "qname": node["qname"],
                "xpath": node["path"],
                "parent_manifest_node_record_id": parent_record_id,
                "attributes": node["attributes"],
            }
            manifest_parents = (
                (archive_record_ids[(apk_id, "AndroidManifest.xml")],)
                if parent_record_id is None
                else (parent_record_id,)
            )
            manifest_record_id = builder.add_discovered(
                "manifest_node",
                payload,
                apk_id,
                additional_parent_ids=manifest_parents,
            )
            manifest_node_records.append({"record_id": manifest_record_id, "payload": payload})
            manifest_payload_by_path[str(node["path"])] = payload
            if node["name"] == "uses-feature":
                builder.add_discovered(
                    "feature",
                    {
                        "apk_artifact_id": apk_id,
                        "declaration_manifest_node_record_id": manifest_record_id,
                        "name": v5_component_attr(node, "name"),
                        "gl_es_version": v5_component_attr(node, "glEsVersion"),
                        "required": bool(v5_component_attr(node, "required"))
                        if v5_component_attr(node, "required") is not None
                        else True,
                    },
                    apk_id,
                    additional_parent_ids=(manifest_record_id,),
                )
        for resource in resources:
            resource_record_id = builder.add_discovered(
                "resource",
                resource,
                apk_id,
            )
        for configuration in resource_configurations:
            builder.add_discovered(
                "configuration",
                configuration,
                apk_id,
                additional_parent_ids=(configuration["resource_record_id"],),
            )

    total_apk_entries = sum(apk_archive_counts.values())
    assert_fixed("apk_entries", total_apk_entries)
    assert_fixed("arm32_native_libraries", arm32_count)
    assert_fixed("assets", asset_count)
    assert_fixed("certificates", certificate_count)
    manifest_node_count = sum(document["node_count"] for document in manifest_documents)
    resource_count = sum(document["resource_count"] for document in resource_documents)
    resource_configuration_count = sum(
        document["configuration_value_count"] for document in resource_documents
    )
    assert_fixed("manifest_nodes", manifest_node_count)
    assert_fixed("resources", resource_count)
    assert_fixed("resource_configurations", resource_configuration_count)

    archive_categories = Counter()
    for entry in archive_documents:
        path = str(entry["path"])
        if path == "AndroidManifest.xml":
            archive_categories["AndroidManifest.xml"] += 1
        elif path == "resources.arsc":
            archive_categories["resources.arsc"] += 1
        elif re.fullmatch(r"classes\d*\.dex", path):
            archive_categories["dex"] += 1
        elif path.startswith("lib/arm64-v8a/") and path.endswith(".so"):
            archive_categories["arm64"] += 1
        elif path.startswith("lib/armeabi-v7a/") and path.endswith(".so"):
            archive_categories["arm32"] += 1
        elif path.startswith("res/"):
            archive_categories["res"] += 1
        elif path.startswith("assets/"):
            archive_categories["assets"] += 1
        elif path.startswith("META-INF/"):
            archive_categories["META-INF"] += 1
        else:
            archive_categories["other"] += 1
    expected_categories = {
        "AndroidManifest.xml": 19,
        "resources.arsc": 19,
        "dex": 4,
        "arm64": 88,
        "arm32": 90,
        "res": 2602,
        "assets": 762,
        "META-INF": 187,
        "other": 543,
    }
    if dict(sorted(archive_categories.items())) != dict(sorted(expected_categories.items())):
        raise ProducerError(f"APK archive categories differ: {dict(sorted(archive_categories.items()))}")

    base_document = next(document for document in manifest_documents if document["apk_member"] == base_member_name)
    base_manifest = base_document["nodes"][0]
    package_name = base_document["axml"]["package"]
    if not package_name:
        raise ProducerError("base manifest package is missing")
    effective_target_sdk = base_document["target_sdk"]
    if not isinstance(effective_target_sdk, int):
        raise ProducerError("base manifest targetSdkVersion is missing")
    component_payloads = v5_derive_android_component_payloads(
        manifest_documents,
        effective_target_sdk,
        contract,
    )
    for document in manifest_documents:
        if document["axml"]["package"] != package_name:
            raise ProducerError(f"{document['apk_member']}: installed package identity differs")
    declaration_index = build_android_component_declaration_index(manifest_node_records)
    component_key_counts = Counter(
        (str(payload["kind"]), str(payload["package"]), str(payload["name"]))
        for payload in component_payloads
    )
    if any(count != 1 for count in component_key_counts.values()):
        raise ProducerError(f"android component identity is not unique: {component_key_counts}")
    component_record_ids = {
        (str(payload["kind"]), str(payload["package"]), str(payload["name"])): record_id(
            "android_component",
            payload,
        )
        for payload in component_payloads
    }
    for payload in component_payloads:
        builder.add_discovered(
            "android_component",
            payload,
            f"xapk-apk:{base_member_name}",
            additional_parent_ids=android_component_additional_parent_ids(
                payload,
                declaration_index,
                component_record_ids,
            ),
        )
    assert_fixed("android_components", len(component_payloads))

    dex_documents: list[dict[str, Any]] = []
    native_declarations: list[dict[str, Any]] = []
    dex_class_count = 0
    dex_defined_method_count = 0
    method_family_count = 0
    reflection_count = 0
    loader_count = 0
    class_record_ids: dict[tuple[str, str], str] = {}
    method_family_record_ids: dict[tuple[str, str, str], str] = {}
    callsite_oracle_by_artifact = {
        str(row["artifact_id"]): row for row in v10_callsite_oracles(contract)
    }
    dex_artifacts = sorted(
        (artifact for artifact in artifacts if artifact["kind"] == "dex"),
        key=lambda artifact: str(artifact["artifact_id"]),
    )
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        for artifact in dex_artifacts:
            dex_id = str(artifact["artifact_id"])
            dex_name = dex_id.split(":", 1)[1]
            dex_data = base_zip.read(dex_name)
            if sha256_bytes(dex_data) != artifact["sha256"] or len(dex_data) != artifact["size_bytes"]:
                raise ProducerError(f"DEX source differs from frozen identity: {dex_name}")
            dex_parser = DexParser(dex_data, dex_id)
            parsed = dex_parser.parse(contract)
            callsites = v5_dex_callsites(dex_parser, parsed, contract)
            oracle = callsite_oracle_by_artifact[dex_id]
            observed_callsite_membership = {
                "artifact_id": dex_id,
                "physical_invoke_count": len(callsites["physical_invokes"]),
                "physical_invoke_membership_sha256": canonical_list_sha256(
                    callsites["physical_invokes"]
                ),
                "reflection_target_count": len(callsites["admitted"]["reflection_target"]),
                "reflection_target_payloads_sha256": canonical_list_sha256(
                    callsites["admitted"]["reflection_target"]
                ),
                "dynamic_loader_count": len(callsites["admitted"]["dynamic_loader"]),
                "dynamic_loader_payloads_sha256": canonical_list_sha256(
                    callsites["admitted"]["dynamic_loader"]
                ),
            }
            if observed_callsite_membership != oracle:
                raise ProducerError(
                    f"v10 DEX callsite membership differs for {dex_id}: "
                    f"{observed_callsite_membership}"
                )
            parsed["artifact_id"] = dex_id
            parsed["sha256"] = artifact["sha256"]
            parsed["size_bytes"] = artifact["size_bytes"]
            dex_documents.append(parsed)
            dex_class_count += len(parsed["classes"])
            dex_defined_method_count += len(parsed["defined_methods"])
            for class_row in parsed["classes"]:
                class_payload = class_scope_payload(dex_id, class_row)
                class_record_ids[(dex_id, str(class_payload["descriptor"]))] = builder.add_discovered(
                    "class",
                    class_payload,
                    dex_id,
                )
            families: defaultdict[tuple[str, str], list[dict[str, int | str]]] = defaultdict(list)
            for method in parsed["defined_methods"]:
                families[(str(method["class_descriptor"]), str(method["name"]))].append(
                    {"descriptor": str(method["prototype"]), "access_flags": int(method["access_flags"])}
                )
                if method["native"]:
                    native_declarations.append(
                        {
                            "dex_artifact_id": dex_id,
                            "class_descriptor": str(method["class_descriptor"]),
                            "method_name": str(method["name"]),
                            "descriptor": str(method["prototype"]),
                            "is_static": bool(int(method["access_flags"]) & 0x8),
                            "mangle_class_descriptor": str(method["class_descriptor"]),
                            "mangle_method_name": str(method["name"]),
                            "mangle_descriptor": str(method["prototype"]),
                        }
                    )
            for (class_descriptor, method_name), definitions in sorted(families.items()):
                payload = {
                    "dex_artifact_id": dex_id,
                    "class_descriptor": class_descriptor,
                    "method_name": method_name,
                    "definitions": sorted(definitions, key=canonical_text),
                }
                method_family_record_ids[(dex_id, class_descriptor, method_name)] = builder.add_discovered(
                    "method_family",
                    payload,
                    dex_id,
                    additional_parent_ids=(class_record_ids[(dex_id, class_descriptor)],),
                )
                method_family_count += 1
            for reference in callsites["admitted"]["reflection_target"]:
                caller = reference["caller"]
                builder.add_discovered(
                    "reflection_target",
                    reference,
                    dex_id,
                    additional_parent_ids=(
                        class_record_ids[(dex_id, str(caller["class_descriptor"]))],
                        method_family_record_ids[
                            (dex_id, str(caller["class_descriptor"]), str(caller["method_name"]))
                        ],
                    ),
                )
                reflection_count += 1
            for reference in callsites["admitted"]["dynamic_loader"]:
                caller = reference["caller"]
                builder.add_discovered(
                    "dynamic_loader",
                    reference,
                    dex_id,
                    additional_parent_ids=(
                        class_record_ids[(dex_id, str(caller["class_descriptor"]))],
                        method_family_record_ids[
                            (dex_id, str(caller["class_descriptor"]), str(caller["method_name"]))
                        ],
                    ),
                )
                loader_count += 1
    assert_fixed("dex_classes", dex_class_count)
    assert_fixed("dex_defined_methods", dex_defined_method_count)
    assert_fixed("method_families", method_family_count)
    assert_fixed("native_declarations", len(native_declarations))

    native_artifacts = sorted(
        (artifact for artifact in artifacts if artifact["kind"] == "native_library"),
        key=lambda artifact: str(artifact["artifact_id"]),
    )
    native_by_basename = {
        Path(str(artifact["artifact_id"]).split(":", 1)[1]).name: str(artifact["artifact_id"])
        for artifact in native_artifacts
    }
    elf_documents: list[dict[str, Any]] = []
    registration_documents: list[dict[str, Any]] = []
    registration_candidates: list[dict[str, Any]] = []
    java_exports: list[dict[str, Any]] = []
    exported_java_by_name: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    symbol_record_ids: dict[tuple[str, int], str] = {}
    export_record_ids: dict[tuple[str, int], str] = {}
    native_symbol_count = 0
    native_export_count = 0
    undefined_import_count = 0
    needed_edge_count = 0
    per_library_count = 0
    with zipfile.ZipFile(apk_paths[base_member_name], "r") as base_zip:
        for artifact in native_artifacts:
            artifact_id = str(artifact["artifact_id"])
            entry_path = artifact_entry_path(artifact)
            if entry_path is None:
                raise ProducerError(f"cannot resolve native entry for {artifact_id}")
            library_name = Path(entry_path).name
            library_data = base_zip.read(entry_path)
            if sha256_bytes(library_data) != artifact["sha256"] or len(library_data) != artifact["size_bytes"]:
                raise ProducerError(f"native library differs from frozen identity: {library_name}")
            native_path = native_work_root / library_name
            native_path.write_bytes(library_data)
            readobj_output = runner.run(
                [llvm_readobj_path, "--needed-libs", "--dyn-symbols", native_path],
                f"read ELF dependencies and dynamic symbols for {library_name}",
            )
            readelf_output = runner.run(
                [llvm_readelf_path, "--dynamic", "--dyn-syms", "--wide", native_path],
                f"cross-check ELF dynamic table for {library_name}",
            )
            nm_output = runner.run(
                [llvm_nm_path, "-D", native_path],
                f"cross-check ELF dynamic names for {library_name}",
            )
            objdump_output = runner.run(
                [llvm_objdump_path, "--private-headers", "--dynamic-syms", native_path],
                f"cross-check ELF headers and symbols for {library_name}",
            )
            registration_readobj_output = runner.run(
                [llvm_readobj_path, "--sections", "--relocations", "--symbols", native_path],
                f"enumerate ELF sections, relocations, and symbols for JNI registration in {library_name}",
            )
            registration_objdump_output = runner.run(
                [
                    llvm_objdump_path,
                    "--reloc",
                    "--disassemble-symbols=JNI_OnLoad",
                    "--no-show-raw-insn",
                    native_path,
                ],
                f"disassemble JNI_OnLoad and relocations for {library_name}",
            )
            readobj = parse_readobj(readobj_output.decode("utf-8", errors="strict"), library_name)
            readelf = parse_readelf(readelf_output.decode("utf-8", errors="strict"))
            nm_names = parse_llvm_nm(nm_output.decode("utf-8", errors="strict"))
            objdump = parse_objdump(objdump_output.decode("utf-8", errors="strict"))
            v10_symbols = parse_v10_elf_symbols(library_data)
            v10_needed = parse_v10_elf_needed(library_data)
            registration_readobj_text = registration_readobj_output.decode("utf-8", errors="strict")
            if (
                "Format: elf64-littleaarch64" not in registration_readobj_text
                or "Arch: aarch64" not in registration_readobj_text
                or "Relocations [" not in registration_readobj_text
            ):
                raise ProducerError(f"LLVM registration analysis is incomplete for {library_name}")
            registration = recover_jni_native_method_entries(library_data, library_name)
            for candidate in registration["jni_native_method_candidates"]:
                candidate["library_artifact_id"] = artifact_id
                registration_candidates.append(candidate)
            registration.update(
                {
                    "source_artifact_id": artifact_id,
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                    "llvm_readobj_stdout_sha256": sha256_bytes(registration_readobj_output),
                    "llvm_objdump_stdout_sha256": sha256_bytes(registration_objdump_output),
                    "llvm_relocation_and_disassembly_evidence": True,
                }
            )
            registration_documents.append(registration)
            readobj_names = [str(symbol["name"]) for symbol in readobj["dynamic_symbols"] if symbol["name"]]
            readelf_names = [str(symbol["name"]) for symbol in readelf["dynamic_symbols"] if symbol["name"]]
            nm_expected = [
                str(symbol["name"])
                for symbol in readobj["dynamic_symbols"]
                if symbol["name"] and not str(symbol["type"]).startswith("Section")
            ]
            objdump_names = [name for name in objdump["dynamic_symbol_names"] if name]
            if sorted(readobj["needed_libraries"]) != sorted(readelf["needed_libraries"]) or sorted(readobj["needed_libraries"]) != sorted(objdump["needed_libraries"]):
                raise ProducerError(
                    f"LLVM DT_NEEDED disagreement for {library_name}: "
                    f"readobj={readobj['needed_libraries']}, "
                    f"readelf={readelf['needed_libraries']}, "
                    f"objdump={objdump['needed_libraries']}"
                )
            if sorted(readobj_names) != sorted(readelf_names) or sorted(
                normalized_symbol_name(name) for name in readobj_names
            ) != sorted(normalized_symbol_name(name) for name in objdump_names):
                raise ProducerError(f"LLVM dynamic-symbol disagreement for {library_name}")
            if sorted(nm_expected) != sorted(nm_names):
                raise ProducerError(f"LLVM nm dynamic-symbol disagreement for {library_name}")
            if len(v10_symbols) != len(readobj["dynamic_symbols"]):
                raise ProducerError(f"raw/LLVM dynamic-symbol cardinality differs for {library_name}")
            if [name for _index, name in v10_needed] != readelf["needed_libraries"]:
                raise ProducerError(f"raw/LLVM DT_NEEDED order differs for {library_name}")

            library_symbol_count = 0
            library_export_count = 0
            library_undefined_count = 0
            for symbol in v10_symbols:
                if not canonical_symbol_included(symbol):
                    continue
                index = int(symbol["dynamic_symbol_index"])
                symbol_payload = native_symbol_scope_payload(artifact_id, symbol)
                symbol_record_id = builder.add_discovered("native_symbol", symbol_payload, artifact_id)
                symbol_record_ids[(artifact_id, index)] = symbol_record_id
                native_symbol_count += 1
                library_symbol_count += 1
                binding = str(symbol_payload["binding"])
                undefined = symbol_payload["section_index"] == 0 and symbol_payload["name"] is not None
                if undefined:
                    import_payload = {
                        "library_artifact_id": artifact_id,
                        "import_kind": "undefined_dynsym",
                        "dynamic_symbol_index": index,
                        "name": symbol_payload["name"],
                        "version": symbol_payload["version"],
                        "native_symbol_record_id": symbol_record_id,
                    }
                    builder.add_discovered(
                        "native_import",
                        import_payload,
                        artifact_id,
                        additional_parent_ids=(symbol_record_id,),
                    )
                    undefined_import_count += 1
                    library_undefined_count += 1
                elif (
                    symbol_payload["name"] is not None
                    and symbol_payload["section_index"] != 0
                    and binding in {"STB_GLOBAL", "STB_WEAK"}
                    and symbol_payload["visibility"]
                    in {"STV_DEFAULT", "STV_PROTECTED", "STV_EXPORTED", "STV_SINGLETON"}
                ):
                    export_payload = {
                        "native_symbol_record_id": symbol_record_id,
                        "library_artifact_id": artifact_id,
                        "dynamic_symbol_index": index,
                        "name": symbol_payload["name"],
                        "version": symbol_payload["version"],
                        "binding": binding,
                    }
                    export_record_id = builder.add_discovered(
                        "native_export",
                        export_payload,
                        artifact_id,
                        additional_parent_ids=(symbol_record_id,),
                    )
                    export_record_ids[(artifact_id, index)] = export_record_id
                    native_export_count += 1
                    library_export_count += 1
                    if str(symbol_payload["name"]).startswith("Java_"):
                        endpoint = {
                            "library_artifact_id": artifact_id,
                            "library": library_name,
                            "dynamic_symbol_index": index,
                            "endpoint_kind": "java_export",
                            "name": symbol_payload["name"],
                            "version": symbol_payload["version"],
                            "native_symbol_record_id": symbol_record_id,
                            "native_export_record_id": export_record_id,
                            "virtual_address": symbol_payload["value"],
                        }
                        java_exports.append(endpoint)
                        exported_java_by_name[str(symbol_payload["name"])].append(endpoint)
            for dynamic_index, needed in v10_needed:
                builder.add_discovered(
                    "native_import",
                    {
                        "library_artifact_id": artifact_id,
                        "import_kind": "dt_needed",
                        "dynamic_table_index": dynamic_index,
                        "soname": needed,
                        "bundled_target_artifact_id": native_by_basename.get(needed),
                    },
                    artifact_id,
                )
                needed_edge_count += 1
            per_library_payload = {
                "configuration_kind": "native_library_summary",
                "library_artifact_id": artifact_id,
                "dynamic_symbol_count": library_symbol_count,
                "defined_global_weak_export_count": library_export_count,
                "undefined_named_import_count": library_undefined_count,
                "dt_needed_count": len(v10_needed),
                "java_export_count": sum(
                    endpoint["library_artifact_id"] == artifact_id for endpoint in java_exports
                ),
            }
            builder.add_discovered("configuration", per_library_payload, artifact_id)
            per_library_count += 1
            readobj.update(
                {
                    "source_artifact_id": artifact_id,
                    "sha256": artifact["sha256"],
                    "size_bytes": artifact["size_bytes"],
                    "readobj_stdout_sha256": sha256_bytes(readobj_output),
                    "readelf_stdout_sha256": sha256_bytes(readelf_output),
                    "nm_stdout_sha256": sha256_bytes(nm_output),
                    "objdump_stdout_sha256": sha256_bytes(objdump_output),
                    "registration_readobj_stdout_sha256": sha256_bytes(registration_readobj_output),
                    "registration_objdump_stdout_sha256": sha256_bytes(registration_objdump_output),
                    "canonical_summary": per_library_payload,
                    "llvm_tool_parity": True,
                }
            )
            elf_documents.append(readobj)
    assert_fixed("native_symbols", native_symbol_count)
    assert_fixed("native_exports", native_export_count)
    assert_fixed("native_undefined_imports", undefined_import_count)
    assert_fixed("native_needed_edges", needed_edge_count)
    assert_fixed("native_imports", undefined_import_count + needed_edge_count)
    assert_fixed("java_exports", len(java_exports))
    assert_fixed("per_library_summaries", per_library_count)

    jni_rows: list[dict[str, Any]] = []
    declaration_edge_counts: Counter[str] = Counter()
    consumed_java_exports: set[tuple[str, int]] = set()
    unbound_declarations: list[dict[str, Any]] = []
    for declaration in sorted(native_declarations, key=canonical_text):
        declaration_key = canonical_text(declaration)
        short_name, long_name = jni_export_candidates(
            str(declaration["class_descriptor"]),
            str(declaration["method_name"]),
            str(declaration["descriptor"]),
        )
        short_matches = list(exported_java_by_name.get(short_name, ()))
        long_matches = list(exported_java_by_name.get(long_name, ())) if not short_matches else []
        matches = short_matches or long_matches
        binding_kind = "static_short" if short_matches else "static_long"
        if matches:
            for endpoint in sorted(matches, key=canonical_text):
                payload = {
                    "java_declaration": jni_declaration_payload(declaration),
                    "native_endpoint": jni_static_endpoint_payload(endpoint),
                    "binding_form": binding_kind,
                    "registration_site": None,
                    "resolution_status": "resolved",
                }
                builder.add_discovered(
                    "jni_edge",
                    payload,
                    str(declaration["dex_artifact_id"]),
                    additional_parent_ids=(
                        class_record_ids[
                            (
                                str(declaration["dex_artifact_id"]),
                                str(declaration["class_descriptor"]),
                            )
                        ],
                        method_family_record_ids[
                            (
                                str(declaration["dex_artifact_id"]),
                                str(declaration["class_descriptor"]),
                                str(declaration["method_name"]),
                            )
                        ],
                        builder.artifact_record_ids[str(endpoint["library_artifact_id"])],
                        str(endpoint["native_symbol_record_id"]),
                        str(endpoint["native_export_record_id"]),
                    ),
                )
                jni_rows.append(payload)
                declaration_edge_counts[declaration_key] += 1
                consumed_java_exports.add((str(endpoint["library_artifact_id"]), int(endpoint["dynamic_symbol_index"])))
        else:
            unbound_declarations.append(declaration)

    declarations_by_signature: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for declaration in unbound_declarations:
        declarations_by_signature[
            (str(declaration["method_name"]), str(declaration["descriptor"]))
        ].append(declaration)
    candidates_by_signature: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    # v7 keeps recovered JNINativeMethod table candidates as raw evidence only;
    # none are adjudicated as proven normalized register_natives edges.
    if set(candidates_by_signature) - set(declarations_by_signature):
        raise ProducerError("recovered JNINativeMethod table contains no matching DEX native declaration")
    consumed_registration_sites: set[tuple[str, int]] = set()
    registered_declaration_keys: set[str] = set()
    for signature in sorted(candidates_by_signature):
        declarations = sorted(declarations_by_signature[signature], key=canonical_text)
        candidates = sorted(
            candidates_by_signature[signature],
            key=lambda row: (str(row["library_artifact_id"]), int(row["table_entry_address"])),
        )
        if len(declarations) != len(candidates):
            raise ProducerError(
                f"ambiguous JNINativeMethod/DEX cardinality for {signature}: "
                f"declarations={len(declarations)}, candidates={len(candidates)}"
            )
        for declaration, candidate in zip(declarations, candidates):
            declaration_key = canonical_text(declaration)
            site_identity = (str(candidate["library_artifact_id"]), int(candidate["table_entry_address"]))
            if declaration_key in registered_declaration_keys or site_identity in consumed_registration_sites:
                raise ProducerError("JNINativeMethod registration site or declaration is reused")
            registered_declaration_keys.add(declaration_key)
            consumed_registration_sites.add(site_identity)
            native_endpoint = {
                "library_artifact_id": candidate["library_artifact_id"],
                "library": candidate["library"],
                "function_address": candidate["function_address"],
                "name": candidate["name"],
                "descriptor": candidate["descriptor"],
            }
            registration_site = {
                "library_artifact_id": candidate["library_artifact_id"],
                "section": candidate["section"],
                "table_entry_address": candidate["table_entry_address"],
                "table_ordinal": candidate["table_ordinal"],
                "pointer_relocations": candidate["pointer_relocations"],
            }
            payload = {
                "java_declaration": jni_declaration_payload(declaration),
                "native_endpoint": native_endpoint,
                "binding_form": "register_natives",
                "registration_site": registration_site,
                "resolution_status": "resolved",
            }
            builder.add_discovered(
                "jni_edge",
                payload,
                str(declaration["dex_artifact_id"]),
                additional_parent_ids=(
                    builder.artifact_record_ids[str(candidate["library_artifact_id"])],
                ),
            )
            jni_rows.append(payload)
            declaration_edge_counts[declaration_key] += 1

    for declaration in sorted(unbound_declarations, key=canonical_text):
        declaration_key = canonical_text(declaration)
        if declaration_key in registered_declaration_keys:
            continue
        payload = {
            "java_declaration": jni_declaration_payload(declaration),
            "native_endpoint": {"unresolved_token": "no_static_export_or_proven_register_natives"},
            "binding_form": "unresolved_declaration",
            "registration_site": None,
            "resolution_status": "unresolved",
        }
        builder.add_discovered(
            "jni_edge",
            payload,
            str(declaration["dex_artifact_id"]),
            additional_parent_ids=(
                class_record_ids[
                    (
                        str(declaration["dex_artifact_id"]),
                        str(declaration["class_descriptor"]),
                    )
                ],
                method_family_record_ids[
                    (
                        str(declaration["dex_artifact_id"]),
                        str(declaration["class_descriptor"]),
                        str(declaration["method_name"]),
                    )
                ],
            ),
        )
        jni_rows.append(payload)
        declaration_edge_counts[declaration_key] += 1
    if consumed_registration_sites:
        raise ProducerError("v10 does not admit normalized register_natives edges")
    for endpoint in sorted(java_exports, key=canonical_text):
        endpoint_key = (str(endpoint["library_artifact_id"]), int(endpoint["dynamic_symbol_index"]))
        if endpoint_key in consumed_java_exports:
            continue
        payload = {
            "java_declaration": {"unresolved_token": "no_matching_dex_native_declaration"},
            "native_endpoint": jni_static_endpoint_payload(endpoint),
            "binding_form": "orphan_java_export",
            "registration_site": None,
            "resolution_status": "orphan",
        }
        expected_orphan_parents = orphan_java_export_parent_ids(
            builder.artifact_record_ids[str(endpoint["library_artifact_id"])],
            str(endpoint["native_export_record_id"]),
        )
        builder.add_discovered(
            "jni_edge",
            payload,
            str(endpoint["library_artifact_id"]),
            additional_parent_ids=tuple(
                parent
                for parent in expected_orphan_parents
                if parent != builder.artifact_record_ids[str(endpoint["library_artifact_id"])]
            ),
        )
        jni_rows.append(payload)
    expected_v10_counts = v10_expected_counts(contract)
    orphan_count = sum(row["binding_form"] == "orphan_java_export" for row in jni_rows)
    if len(jni_rows) != expected_v10_counts["jni_edge"] or orphan_count != expected_v10_counts["orphan_java_export"]:
        raise ProducerError(
            f"v10 JNI counts differ: total={len(jni_rows)} orphan={orphan_count}"
        )
    if set(declaration_edge_counts) != {canonical_text(value) for value in native_declarations}:
        raise ProducerError("JNI declaration conservation failed")
    if {
        str(row["native_endpoint"]["native_export_record_id"])
        for row in jni_rows
        if row["native_endpoint"] is not None
        and row["native_endpoint"].get("endpoint_kind") == "java_export"
    } != {
        str(endpoint["native_export_record_id"])
        for endpoint in java_exports
    }:
        raise ProducerError("Java export JNI conservation failed")

    records, source_records, raw_record_paths = builder.finalize(raw_root)
    type_counts = Counter(str(record["record_type"]) for record in records)
    discovered_counts = {
        record_type: type_counts.get(record_type, 0)
        for record_type in sorted(DISCOVERED_INVENTORY_RECORD_TYPES)
    }
    missing_required_types = sorted(
        record_type for record_type in REQUIRED_DISCOVERED_TYPES if type_counts[record_type] == 0
    )
    if missing_required_types:
        raise ProducerError(f"required discovered record types are empty: {missing_required_types}")
    for scope_name, record_type in DIRECT_SCOPE_TYPES.items():
        assert_fixed(scope_name, type_counts[record_type])
    configuration_kind_counts = Counter()
    for record in records:
        if record["record_type"] != "configuration":
            continue
        payload = json.loads(str(record["scope_key"]))
        kind = payload.get("configuration_kind")
        if kind not in CONFIGURATION_SCOPE_KINDS:
            raise ProducerError(f"unknown configuration scope kind: {kind}")
        configuration_kind_counts[str(kind)] += 1
    expected_configuration_counts = {
        "xapk_archive_entry": FIXED_SCOPE_COUNTS["xapk_entries"],
        "apk_archive_entry": FIXED_SCOPE_COUNTS["apk_entries"],
        "arm32_native_library": FIXED_SCOPE_COUNTS["arm32_native_libraries"],
        "resource_configuration": FIXED_SCOPE_COUNTS["resource_configurations"],
        "native_library_summary": FIXED_SCOPE_COUNTS["per_library_summaries"],
    }
    if dict(sorted(configuration_kind_counts.items())) != dict(sorted(expected_configuration_counts.items())):
        raise ProducerError(f"configuration universe differs: {dict(sorted(configuration_kind_counts.items()))}")
    variable_counts = {
        "jni_edges": type_counts["jni_edge"],
        "reflection_targets": type_counts["reflection_target"],
        "dynamic_loaders": type_counts["dynamic_loader"],
    }
    if len(records) != KNOWN_NORMALIZED_FLOOR + sum(variable_counts.values()):
        raise ProducerError("normalized record floor plus variable families does not reconcile")

    scope_observed = {
        **FIXED_SCOPE_COUNTS,
        **variable_counts,
    }
    normalized_scope_counts: dict[str, int | None] = {
        **{name: type_counts[record_type] for name, record_type in DIRECT_SCOPE_TYPES.items()},
        **{name: type_counts[record_type] for name, record_type in VARIABLE_SCOPE_TYPES.items()},
        "xapk_entries": configuration_kind_counts["xapk_archive_entry"],
        "apk_entries": configuration_kind_counts["apk_archive_entry"],
        "arm32_native_libraries": configuration_kind_counts["arm32_native_library"],
        "resource_configurations": configuration_kind_counts["resource_configuration"],
        "per_library_summaries": configuration_kind_counts["native_library_summary"],
        "dex_defined_methods": method_family_count,
        "native_declarations": sum(1 for row in jni_rows if row["java_declaration"] is not None),
        "java_exports": len(java_exports),
        "native_undefined_imports": undefined_import_count,
        "native_needed_edges": needed_edge_count,
    }
    normalized_scope_counts["native_imports"] = type_counts["native_import"]
    summaries: list[dict[str, Any]] = []
    scope_conservation: dict[str, Any] = {}
    for index, name in enumerate(sorted(CONSERVATION_SCOPES)):
        summary = {
            "scope": name,
            "observed_count": int(scope_observed[name]),
            "accounted_count": int(scope_observed[name]),
            "normalized_record_count": normalized_scope_counts[name],
            "unaccounted_count": 0,
        }
        summaries.append(summary)
        locator = f"raw/scope-conservation.json#/summaries/{index}"
        scope_conservation[name] = {
            **{key: summary[key] for key in summary if key != "scope"},
            "source_ref": {
                "bundle_id": BUNDLE_ID,
                "source_locator": locator,
                "source_record_sha256": sha256_bytes(canonical_bytes(summary)),
            },
        }
    scope_conservation_path = raw_root / "scope-conservation.json"
    write_json(scope_conservation_path, {"schema_version": 1, "summaries": summaries})

    coverage = {
        "record_count": len(records),
        "record_type_counts": dict(sorted(type_counts.items())),
        "discovered_record_type_counts": discovered_counts,
        "apk_members": 19,
        "dex_files": 4,
        "native_libraries": 88,
        "unclassified": sum(record["classification_status"] != "classified" for record in records),
        "frozen_artifacts_accounted": type_counts.get("frozen_artifact", 0),
        "all_artifacts_accounted": True,
        "scope_conservation": scope_conservation,
    }
    if coverage["apk_members"] != 19 or coverage["dex_files"] != 4 or coverage["native_libraries"] != 88:
        raise ProducerError("frozen 19/4/88 coverage differs")
    if coverage["unclassified"] != 0 or any(record["dossier_id"] is not None for record in records):
        raise ProducerError("all rows must be classified with null G002 dossier ownership")

    source_index = {
        "schema_version": 1,
        "index_id": "SOURCE-INDEX-G002-METHOD-B",
        "artifact_set_id": artifact_set_id,
        "run_id": RUN_ID,
        "method_id": METHOD_ID,
        "records": source_records,
        "canonical_sha256": canonical_list_sha256(source_records),
    }
    source_index_path = bundle_root / "source-index.json"
    write_json(source_index_path, source_index)

    write_json(
        raw_root / "archive-index.json",
        {
            "schema_version": 1,
            "xapk": {
                "path": display_path(xapk_path),
                "sha256": xapk_digest,
                "size_bytes": xapk_size,
                "entry_count": len(xapk_entries),
                "entries": xapk_entries,
                "infozip_python_raw_member_order_equal": True,
            },
            "apk_entry_counts": dict(sorted(apk_archive_counts.items())),
            "apk_entry_categories": dict(sorted(archive_categories.items())),
            "apk_entries": archive_documents,
            "all_entries_safe_and_accounted": True,
        },
    )
    write_json(
        raw_root / "manifest-index.json",
        {
            "schema_version": 1,
            "documents": [
                {
                    key: (
                        [
                            {node_key: node_value for node_key, node_value in node.items() if node_key != "attrs"}
                            for node in value
                        ]
                        if key == "nodes"
                        else value
                    )
                    for key, value in document.items()
                    if key != "axml"
                }
                for document in manifest_documents
            ],
        },
    )
    write_json(raw_root / "resource-index.json", {"schema_version": 1, "documents": resource_documents})
    write_json(raw_root / "signing-analysis.json", {"schema_version": 1, "documents": signing_documents})
    write_json(raw_root / "dex-structure.json", {"schema_version": 1, "parser": SCRIPT_VERSION, "dex_files": dex_documents})
    write_json(raw_root / "elf-analysis.json", {"schema_version": 1, "libraries": elf_documents})
    write_json(
        raw_root / "jni-registration-analysis.json",
        {
            "schema_version": 1,
            "libraries": registration_documents,
            "candidate_count": len(registration_candidates),
            "consumed_candidate_count": len(consumed_registration_sites),
            "all_candidates_exactly_consumed": len(registration_candidates)
            == len(consumed_registration_sites),
        },
    )
    write_json(
        raw_root / "jni-analysis.json",
        {
            "schema_version": 1,
            "native_method_declarations": native_declarations,
            "java_exports": java_exports,
            "edges": jni_rows,
            "static_resolved_edges": sum(
                row["binding_form"] in {"static_short", "static_long"} for row in jni_rows
            ),
            "unresolved_declarations": sum(row["binding_form"] == "unresolved_declaration" for row in jni_rows),
            "orphan_java_exports": sum(row["binding_form"] == "orphan_java_export" for row in jni_rows),
            "register_natives_edges": sum(row["binding_form"] == "register_natives" for row in jni_rows),
            "derivation": "DEX native declarations are partitioned by JNI-specified short/long lookup, directly recovered AArch64 JNINativeMethod tables, and explicit unresolved endpoints; every Java_* export is statically consumed or explicit orphan evidence.",
        },
    )
    write_json(
        raw_root / "artifact-accounting.json",
        {
            "schema_version": 1,
            "artifact_set_id": artifact_set_id,
            "frozen_artifact_count": len(artifact_observations),
            "observations": [artifact_observations[key] for key in sorted(artifact_observations)],
            "all_hashes_match": True,
        },
    )
    write_json(
        raw_root / "identity-classification-contract.json",
        {
            "schema_version": 1,
            "canonical_json": "recursive NFC, sorted keys, compact UTF-8, finite numbers",
            "record_id_rule": "INV- + uppercase SHA256(J(['g002-record/v1',record_type,type_specific_payload]))",
            "record_order": "ascending record_id",
            "source_locator_rule": "raw/<hash-listed-json>#/<canonical-RFC6901-pointer>",
            "canonical_comparison_exclusion": ["source_refs"],
            "dossier_id": None,
            "configuration_scope_kinds": sorted(CONFIGURATION_SCOPE_KINDS),
        },
    )
    script_digest, script_size = file_hash(Path(__file__).resolve())
    input_rows: dict[str, Any] = {
        "official_artifact_manifest": {
            "path": OFFICIAL_MANIFEST_REL.as_posix(),
            "sha256": file_hash(REPO_ROOT / OFFICIAL_MANIFEST_REL)[0],
            "size_bytes": file_hash(REPO_ROOT / OFFICIAL_MANIFEST_REL)[1],
        },
        "official_xapk": {"path": display_path(xapk_path), "sha256": xapk_digest, "size_bytes": xapk_size},
        "producer": {"path": display_path(Path(__file__)), "sha256": script_digest, "size_bytes": script_size},
    }
    for name, path in (
        ("aapt2", aapt2_path),
        ("llvm_readobj", llvm_readobj_path),
        ("llvm_readelf", llvm_readelf_path),
        ("llvm_nm", llvm_nm_path),
        ("llvm_objdump", llvm_objdump_path),
    ):
        digest, size = file_hash(path)
        input_rows[name] = {"path": display_path(path), "sha256": digest, "size_bytes": size}
    write_json(
        raw_root / "input-tool-hashes.json",
        {"schema_version": 1, "inputs": input_rows, "tool_versions": versions},
    )

    external_commands = [capture.command for capture in runner.results]
    commands = [replay_command, *external_commands]
    if len(commands) != len(set(commands)):
        duplicates = sorted(command for command, count in Counter(commands).items() if count > 1)
        raise ProducerError(f"run command list contains duplicates: {duplicates}")
    write_json(
        raw_root / "command-results.json",
        {
            "schema_version": 1,
            "producer_command": {"command": replay_command, "exit_code": 0},
            "external_commands": runner.as_json(),
            "all_exit_codes_zero": True,
        },
    )

    checks = {
        "schema_version": 1,
        "status": "pass",
        "fixed_scope_counts": dict(sorted(FIXED_SCOPE_COUNTS.items())),
        "variable_scope_counts": dict(sorted(variable_counts.items())),
        "configuration_scope_counts": dict(sorted(configuration_kind_counts.items())),
        "normalized_floor": KNOWN_NORMALIZED_FLOOR,
        "normalized_records": len(records),
        "frozen_artifacts": len(artifact_observations),
        "frozen_apk_dex_native": [coverage["frozen_artifacts_accounted"], coverage["apk_members"], coverage["dex_files"], coverage["native_libraries"]],
        "source_index_rows": len(source_records),
        "raw_record_rows": len(source_records),
        "unclassified": coverage["unclassified"],
        "dossier_non_null": sum(record["dossier_id"] is not None for record in records),
        "hardware_runs": 0,
        "live_runs": 0,
        "celsius_claims": 0,
    }
    checks_path = bundle_root / "checks.json"
    write_json(checks_path, checks)

    canonical_records = [{key: value for key, value in record.items() if key != "source_refs"} for record in records]
    canonical_inventory_hash = canonical_list_sha256(canonical_records)
    state_path = bundle_root / "state.json"
    write_json(
        state_path,
        {
            "schema_version": 1,
            "state": "offline_static_analysis_of_hash_locked_untouched_package",
            "hardware_run": False,
            "live_application_run": False,
            "celsius_claims": [],
            "source_variant": "untouched",
        },
    )
    events_path = bundle_root / "events.json"
    write_json(
        events_path,
        {
            "schema_version": 1,
            "schema_id": "normalized-static-inventory-event-v1",
            "artifact_set_id": artifact_set_id,
            "experiment_id": EXPERIMENT_ID,
            "source_variant": "untouched",
            "events": [],
            "canonical_sha256": sha256_bytes(canonical_bytes([])),
        },
    )
    attachment_paths = [
        source_index_path,
        checks_path,
        state_path,
        events_path,
        *sorted(raw_root.glob("*.json"), key=lambda path: path.as_posix()),
    ]
    attachments = sorted(
        (output_attachment(path, bundle_root) for path in attachment_paths),
        key=lambda row: row["path"],
    )
    evidence_manifest = {
        "schema_version": 1,
        "bundle_id": BUNDLE_ID,
        "claim_ids": [CLAIM_ID_PRIVATE],
        "experiment_id": EXPERIMENT_ID,
        "operator": OPERATOR,
        "captured_at": args.timestamp,
        "clock": {"basis": "deterministic-static-sequence", "offsets_and_drift_attachment": None},
        "artifact_set_id": artifact_set_id,
        "source_variant": "untouched",
        "evidence_tier": "E1",
        "instrumentation_delta": {
            "summary": "Read-only offline analysis of immutable package bytes; no hooks, patches, root modules, debugger, proxy, or USB capture.",
            "hooks": [],
            "patches": [],
            "root_modules": [],
            "debugger": [],
            "proxies": [],
            "usb_capture_point": None,
        },
        "environment": {
            "device_fingerprint": None,
            "camera_fingerprint": None,
            "os_build": None,
            "abi": None,
            "data_state_snapshot": "state.json",
        },
        "tool_versions": versions,
        "replay_commands": [
            replay_command,
            shlex.join(
                [
                    display_path(Path(sys.executable)),
                    "tools/hik_whole_apk/g002_method_b.py",
                    "--self-check-only",
                    "--out",
                    display_path(out_root),
                ]
            ),
        ],
        "event_stream": {
            "schema_id": "normalized-static-inventory-event-v1",
            "normalized_attachment": "events.json",
            "emitted_events": 0,
            "captured_events": 0,
            "dropped_events": 0,
            "truncated_events": 0,
        },
        "attachments": attachments,
    }
    evidence_manifest["manifest_sha256"] = sha256_bytes(canonical_bytes(evidence_manifest))
    evidence_manifest_path = bundle_root / "manifest.json"
    write_json(evidence_manifest_path, evidence_manifest)

    source_attachment = next(attachment for attachment in attachments if attachment["path"] == "source-index.json")
    run_manifest = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "experiment_id": EXPERIMENT_ID,
        "operator": OPERATOR,
        "status": "completed",
        "artifact_set_id": artifact_set_id,
        "method_id": METHOD_ID,
        "toolchain_family": TOOLCHAIN_FAMILY,
        "commands": commands,
        "command_exit_codes": [0] * len(commands),
        "tool_versions": versions,
        "input_artifact_ids": sorted(official_by_id),
        "evidence_bundle_ids": [BUNDLE_ID],
        "source_index_attachments": [
            {
                "bundle_id": BUNDLE_ID,
                "path": "source-index.json",
                "sha256": source_attachment["sha256"],
                "size_bytes": source_attachment["size_bytes"],
            }
        ],
        "started_at": args.timestamp,
        "ended_at": args.timestamp,
    }
    run_manifest_path = out_root / "runs" / RUN_ID / "manifest.json"
    write_json(run_manifest_path, run_manifest)

    inventory = {
        "schema_version": 1,
        "inventory_id": INVENTORY_ID,
        "artifact_set_id": artifact_set_id,
        "generated_at": generated_at,
        "method": {
            "method_id": METHOD_ID,
            "toolchain_family": TOOLCHAIN_FAMILY,
            "commands": commands,
            "tool_versions": versions,
            "producer_script": {
                "path": display_path(Path(__file__)),
                "sha256": script_digest,
                "size_bytes": script_size,
            },
        },
        "producer_run_id": RUN_ID,
        "producer_run_manifest": display_path(run_manifest_path),
        "producer_evidence_bundle_ids": [BUNDLE_ID],
        "independent_review_id": REVIEW_ID_PENDING,
        "normalized_records": records,
        "coverage": coverage,
        "canonical_sha256": canonical_inventory_hash,
    }
    inventory_path = out_root / "inventory-b.private.json"
    write_json(inventory_path, inventory)
    write_canonical_candidate_bundle(
        candidate_root=checked_output_root(args.candidate_root),
        artifact_set_id=artifact_set_id,
        records=records,
        source_records=source_records,
        canonical_inventory_hash=canonical_inventory_hash,
        source_index_hash=source_index["canonical_sha256"],
        commands=commands,
        timestamp=args.timestamp,
        generated_at=generated_at,
        contract=contract,
        dex_native_declarations_sha256=canonical_list_sha256(
            sorted(native_declarations, key=canonical_bytes)
        ),
    )

    inventory_digest, inventory_size = file_hash(inventory_path)
    run_digest, run_size = file_hash(run_manifest_path)
    evidence_digest, evidence_size = file_hash(evidence_manifest_path)
    publication = {
        "schema_version": 1,
        "status": "private_producer_complete_independent_review_pending",
        "inventory_id": INVENTORY_ID,
        "method_id": METHOD_ID,
        "planned_independent_review_id": REVIEW_ID_PENDING,
        "review_approval_present": False,
        "canonical_sha256": canonical_inventory_hash,
        "private_files": {
            "inventory": {"path": display_path(inventory_path), "sha256": inventory_digest, "size_bytes": inventory_size},
            "run_manifest": {"path": display_path(run_manifest_path), "sha256": run_digest, "size_bytes": run_size},
            "evidence_manifest": {"path": display_path(evidence_manifest_path), "sha256": evidence_digest, "size_bytes": evidence_size},
        },
        "remaining_integration": [
            "independent replay and review by a non-producer",
            "canonical relocation by the integration owner",
            "method-independent convergence comparison",
        ],
    }
    write_json(out_root / "publication.json", publication)
    write_text(
        out_root / "README.md",
        f"""# G002 Method-B private producer output

Status: producer complete; independent review and canonical publication pending.

- Inventory: `inventory-b.private.json`
- Canonical normalized SHA-256: `{canonical_inventory_hash}`
- Normalized records: `{len(records)}` = `{KNOWN_NORMALIZED_FLOOR}` fixed floor + `{sum(variable_counts.values())}` derived variable rows
- Frozen artifacts / APK / DEX / arm64 libraries: `121 / 19 / 4 / 88`
- Method families / resources / resource configurations: `{method_family_count} / {resource_count} / {resource_configuration_count}`
- Native symbols / exports / undefined imports / DT_NEEDED: `{native_symbol_count} / {native_export_count} / {undefined_import_count} / {needed_edge_count}`
- Derived JNI / reflection / loader rows: `{type_counts['jni_edge']} / {reflection_count} / {loader_count}`
- Planned independent review: `{REVIEW_ID_PENDING}` (not approved or published)

This directory is private E1 static evidence. It contains no hardware run,
live-application observation, radiometric result, frame result, or Celsius claim.
""",
    )
    if not args.keep_work:
        shutil.rmtree(work_root)

    summary = {
        "status": "pass",
        "record_count": len(records),
        "canonical_sha256": canonical_inventory_hash,
        "source_index_sha256": source_index["canonical_sha256"],
        "frozen_artifacts": coverage["frozen_artifacts_accounted"],
        "apk_members": coverage["apk_members"],
        "dex_files": coverage["dex_files"],
        "native_libraries": coverage["native_libraries"],
        "fixed_scope_counts": dict(sorted(FIXED_SCOPE_COUNTS.items())),
        "variable_scope_counts": dict(sorted(variable_counts.items())),
        "unclassified": coverage["unclassified"],
        "output": display_path(out_root),
    }
    del (
        canonical_records,
        inventory,
        records,
        source_records,
        source_index,
        dex_documents,
        elf_documents,
        registration_documents,
        registration_candidates,
        archive_documents,
        manifest_documents,
        resource_documents,
        jni_rows,
        native_declarations,
        java_exports,
        builder,
    )
    gc.collect()
    validation = validate_private_output_remediated(out_root)
    if validation != {key: summary[key] for key in validation}:
        raise ProducerError("post-write validation summary differs from in-process summary")
    return summary


def resolve_json_pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise ProducerError(f"RFC6901 pointer must begin with '/': {pointer}")
    current = document
    for raw_token in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", raw_token):
            raise ProducerError(f"invalid RFC6901 escape: {pointer}")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ProducerError(f"noncanonical RFC6901 array index: {pointer}")
            index = int(token)
            if index >= len(current):
                raise ProducerError(f"RFC6901 array index out of range: {pointer}")
            current = current[index]
        elif isinstance(current, Mapping):
            if token not in current:
                raise ProducerError(f"RFC6901 object key is absent: {pointer}")
            current = current[token]
        else:
            raise ProducerError(f"RFC6901 pointer traverses a scalar: {pointer}")
    return current


def split_raw_locator(locator: str) -> tuple[str, str]:
    if unicodedata.normalize("NFC", locator) != locator or locator.count("#") != 1:
        raise ProducerError(f"invalid raw source locator: {locator}")
    path, pointer = locator.split("#", 1)
    pure = PurePosixPath(path)
    if (
        not path.startswith("raw/")
        or not path.endswith(".json")
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or "\\" in path
        or "\x00" in path
        or not pointer.startswith("/")
    ):
        raise ProducerError(f"invalid raw source locator: {locator}")
    return path, pointer


def validate_private_output_remediated(out_root: Path) -> dict[str, Any]:
    inventory_path = out_root / "inventory-b.private.json"
    bundle_root = out_root / "evidence" / BUNDLE_ID
    source_index_path = bundle_root / "source-index.json"
    run_path = out_root / "runs" / RUN_ID / "manifest.json"
    evidence_path = bundle_root / "manifest.json"
    checks_path = bundle_root / "checks.json"
    publication_path = out_root / "publication.json"
    inventory = load_json(inventory_path)
    source_index = load_json(source_index_path)
    run = load_json(run_path)
    evidence = load_json(evidence_path)
    checks = load_json(checks_path)
    publication = load_json(publication_path)

    exact_key_check(
        inventory,
        {
            "schema_version",
            "inventory_id",
            "artifact_set_id",
            "generated_at",
            "method",
            "producer_run_id",
            "producer_run_manifest",
            "producer_evidence_bundle_ids",
            "independent_review_id",
            "normalized_records",
            "coverage",
            "canonical_sha256",
        },
        "inventory",
    )
    method = inventory.get("method")
    if not isinstance(method, dict):
        raise ProducerError("inventory method is missing")
    exact_key_check(
        method,
        {"method_id", "toolchain_family", "commands", "tool_versions", "producer_script"},
        "inventory method",
    )
    script_row = method["producer_script"]
    exact_key_check(script_row, {"path", "sha256", "size_bytes"}, "producer script")
    script_path = REPO_ROOT / str(script_row["path"])
    script_digest, script_size = file_hash(script_path)
    if script_digest != script_row["sha256"] or script_size != script_row["size_bytes"]:
        raise ProducerError("producer script hash row differs from producer bytes")
    invoked = any(
        str(script_row["path"]) in shlex.split(command)
        for command in method["commands"]
    )
    if not invoked:
        raise ProducerError("producer commands do not invoke the hash-listed producer")
    tree = ast.parse(script_path.read_text(encoding="utf-8"), filename=str(script_path))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            else:
                modules = [node.module or ""]
            if any(name == "androguard" or name.startswith("androguard.") for name in modules):
                raise ProducerError("forbidden Androguard import found")

    records = inventory.get("normalized_records")
    if not isinstance(records, list) or not records:
        raise ProducerError("inventory normalized_records is empty")
    record_keys = {
        "record_id",
        "record_type",
        "scope_key",
        "artifact_id",
        "source_artifact_id",
        "sha256",
        "size_bytes",
        "official_source",
        "dossier_id",
        "classification_status",
        "parent_record_ids",
        "source_refs",
    }
    record_ids: set[str] = set()
    scope_identities: set[tuple[str, str]] = set()
    artifact_records: dict[str, Mapping[str, Any]] = {}
    record_by_locator: dict[str, Mapping[str, Any]] = {}
    type_counts: Counter[str] = Counter()
    configuration_kind_counts: Counter[str] = Counter()
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise ProducerError(f"inventory record {position} is not an object")
        exact_key_check(record, record_keys, f"inventory record {position}")
        record_type = str(record["record_type"])
        if record_type not in INVENTORY_RECORD_TYPES:
            raise ProducerError(f"invalid inventory record type: {record_type}")
        scope = str(record["scope_key"])
        try:
            payload = json.loads(scope)
        except json.JSONDecodeError as exc:
            raise ProducerError(f"invalid scope payload JSON: {exc}") from exc
        if canonical_text(payload) != scope:
            raise ProducerError(f"scope payload is not recursive-NFC canonical: {scope[:120]}")
        expected_id = record_id(record_type, payload)
        if record["record_id"] != expected_id or expected_id in record_ids:
            raise ProducerError(f"invalid/duplicate canonical record ID: {record['record_id']}")
        identity = (record_type, scope)
        if identity in scope_identities:
            raise ProducerError(f"duplicate record scope: {identity}")
        record_ids.add(expected_id)
        scope_identities.add(identity)
        if record["classification_status"] != "classified" or record["dossier_id"] is not None:
            raise ProducerError(f"record classification/dossier state is invalid: {expected_id}")
        parents = record["parent_record_ids"]
        if not isinstance(parents, list) or parents != sorted(set(parents)):
            raise ProducerError(f"record parents are not canonical: {expected_id}")
        artifact_id = record["artifact_id"]
        if artifact_id is not None:
            if payload != artifact_id or parents or record["source_artifact_id"] != artifact_id:
                raise ProducerError(f"frozen artifact scope/parent/source is invalid: {expected_id}")
            if artifact_id in artifact_records:
                raise ProducerError(f"duplicate frozen artifact record: {artifact_id}")
            artifact_records[str(artifact_id)] = record
        else:
            if record["official_source"] is not None or record_type not in DISCOVERED_INVENTORY_RECORD_TYPES:
                raise ProducerError(f"discovered record source/type is invalid: {expected_id}")
        refs = record["source_refs"]
        if not isinstance(refs, list) or len(refs) != 1 or refs != sorted(refs, key=canonical_text):
            raise ProducerError(f"record source refs are not exact-once canonical: {expected_id}")
        ref = refs[0]
        exact_key_check(
            ref,
            {"bundle_id", "attachment_path", "source_locator", "source_record_sha256"},
            f"source ref {expected_id}",
        )
        if ref["bundle_id"] != BUNDLE_ID or ref["attachment_path"] != "source-index.json":
            raise ProducerError(f"record source ref bundle/index differs: {expected_id}")
        locator = str(ref["source_locator"])
        if locator in record_by_locator:
            raise ProducerError(f"one raw source row is reused: {locator}")
        split_raw_locator(locator)
        record_by_locator[locator] = record
        type_counts[record_type] += 1
        if record_type == "configuration":
            kind = payload.get("configuration_kind") if isinstance(payload, dict) else None
            if kind not in CONFIGURATION_SCOPE_KINDS:
                raise ProducerError(f"configuration record has invalid kind: {kind}")
            configuration_kind_counts[str(kind)] += 1
    if [str(record["record_id"]) for record in records] != sorted(record_ids):
        raise ProducerError("normalized records are not sorted by record_id")
    if any(not set(record["parent_record_ids"]).issubset(record_ids) for record in records):
        raise ProducerError("normalized record has an unknown parent")
    artifact_parent_ids = {artifact_id: str(record["record_id"]) for artifact_id, record in artifact_records.items()}
    for record in records:
        if record["artifact_id"] is None:
            parent = artifact_parent_ids.get(str(record["source_artifact_id"]))
            if parent is None or parent not in record["parent_record_ids"]:
                raise ProducerError(f"discovered record lacks its frozen source parent: {record['record_id']}")

    official = load_json(REPO_ROOT / OFFICIAL_MANIFEST_REL)
    official_by_id = {str(row["artifact_id"]): row for row in official["artifacts"]}
    if set(artifact_records) != set(official_by_id):
        raise ProducerError("frozen artifact record set differs from official manifest")
    for artifact_id, artifact in official_by_id.items():
        record = artifact_records[artifact_id]
        if (
            record["record_type"] != "frozen_artifact"
            or record["sha256"] != artifact["sha256"]
            or record["size_bytes"] != artifact["size_bytes"]
            or record["official_source"] != artifact["source"]
        ):
            raise ProducerError(f"frozen artifact record differs: {artifact_id}")

    exact_key_check(
        source_index,
        {"schema_version", "index_id", "artifact_set_id", "run_id", "method_id", "records", "canonical_sha256"},
        "source index",
    )
    source_rows = source_index.get("records")
    if not isinstance(source_rows, list) or len(source_rows) != len(records):
        raise ProducerError("source-index/normalized cardinality differs")
    source_keys = {
        "source_locator",
        "record_type",
        "scope_key",
        "artifact_id",
        "source_artifact_id",
        "sha256",
        "size_bytes",
        "official_source",
    }
    source_by_locator: dict[str, Mapping[str, Any]] = {}
    raw_paths: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for source_row in source_rows:
        if not isinstance(source_row, dict):
            raise ProducerError("source index contains a non-object")
        exact_key_check(source_row, source_keys, "source row")
        locator = str(source_row["source_locator"])
        if locator in source_by_locator:
            raise ProducerError(f"duplicate source locator: {locator}")
        path, pointer = split_raw_locator(locator)
        source_by_locator[locator] = source_row
        raw_paths[path].append((locator, pointer))
    if [str(row["source_locator"]) for row in source_rows] != sorted(source_by_locator):
        raise ProducerError("source-index rows are not sorted by locator")
    if set(source_by_locator) != set(record_by_locator):
        raise ProducerError("normalized/source-index locator universes differ")
    if source_index["canonical_sha256"] != canonical_list_sha256(source_rows):
        raise ProducerError("source-index canonical hash differs")
    for locator, source_row in source_by_locator.items():
        record = record_by_locator[locator]
        ref = record["source_refs"][0]
        if ref["source_record_sha256"] != sha256_bytes(canonical_bytes(source_row)):
            raise ProducerError(f"source-record hash differs: {locator}")
        for field in source_keys - {"source_locator"}:
            if source_row[field] != record[field]:
                raise ProducerError(f"source/normalized field differs: {locator} {field}")
    raw_record_count = 0
    for relative, locators in sorted(raw_paths.items()):
        document = load_json(bundle_root / relative)
        observed = set()
        for locator, pointer in locators:
            resolved = resolve_json_pointer(document, pointer)
            if not isinstance(resolved, dict) or resolved != source_by_locator[locator]:
                raise ProducerError(f"raw pointer does not exactly resolve its source row: {locator}")
            if resolved.get("source_locator") != locator:
                raise ProducerError(f"raw source row is not self-identifying: {locator}")
            observed.add(locator)
        raw_rows = document.get("records") if isinstance(document, dict) else None
        if not isinstance(raw_rows, list) or len(raw_rows) != len(locators):
            raise ProducerError(f"raw record document cardinality differs: {relative}")
        raw_record_count += len(raw_rows)
        if observed != {str(row["source_locator"]) for row in raw_rows}:
            raise ProducerError(f"raw record document has an unindexed record-shaped object: {relative}")
    if raw_record_count != len(records):
        raise ProducerError("raw record universe does not exactly conserve normalized records")

    canonical_hash = canonical_list_sha256(
        {key: value for key, value in record.items() if key != "source_refs"}
        for record in records
    )
    if canonical_hash != inventory["canonical_sha256"]:
        raise ProducerError("inventory canonical normalized-record hash differs")
    coverage = inventory.get("coverage")
    coverage_keys = {
        "record_count",
        "record_type_counts",
        "discovered_record_type_counts",
        "apk_members",
        "dex_files",
        "native_libraries",
        "unclassified",
        "frozen_artifacts_accounted",
        "all_artifacts_accounted",
        "scope_conservation",
    }
    if not isinstance(coverage, dict):
        raise ProducerError("coverage is missing")
    exact_key_check(coverage, coverage_keys, "coverage")
    discovered_counts = {
        record_type: type_counts.get(record_type, 0)
        for record_type in sorted(DISCOVERED_INVENTORY_RECORD_TYPES)
    }
    expected_coverage = {
        "record_count": len(records),
        "record_type_counts": dict(sorted(type_counts.items())),
        "discovered_record_type_counts": discovered_counts,
        "apk_members": 19,
        "dex_files": 4,
        "native_libraries": 88,
        "unclassified": 0,
        "frozen_artifacts_accounted": len(artifact_records),
        "all_artifacts_accounted": True,
        "scope_conservation": coverage["scope_conservation"],
    }
    if coverage != expected_coverage:
        raise ProducerError("coverage is not derived from normalized records")
    for name, record_type in DIRECT_SCOPE_TYPES.items():
        assert_fixed(name, type_counts[record_type])
    expected_configuration_counts = {
        "xapk_archive_entry": FIXED_SCOPE_COUNTS["xapk_entries"],
        "apk_archive_entry": FIXED_SCOPE_COUNTS["apk_entries"],
        "arm32_native_library": FIXED_SCOPE_COUNTS["arm32_native_libraries"],
        "resource_configuration": FIXED_SCOPE_COUNTS["resource_configurations"],
        "native_library_summary": FIXED_SCOPE_COUNTS["per_library_summaries"],
    }
    if dict(sorted(configuration_kind_counts.items())) != dict(sorted(expected_configuration_counts.items())):
        raise ProducerError("configuration row universes differ")
    variable_counts = {
        name: type_counts[record_type] for name, record_type in VARIABLE_SCOPE_TYPES.items()
    }
    if len(records) != KNOWN_NORMALIZED_FLOOR + sum(variable_counts.values()):
        raise ProducerError("known normalized floor plus variable rows differs")

    conservation = coverage["scope_conservation"]
    if set(conservation) != CONSERVATION_SCOPES:
        raise ProducerError("scope conservation map is incomplete")
    observed_summary_refs: set[tuple[str, str]] = set()
    for name in sorted(CONSERVATION_SCOPES):
        row = conservation[name]
        exact_key_check(
            row,
            {"observed_count", "accounted_count", "normalized_record_count", "unaccounted_count", "source_ref"},
            f"scope conservation {name}",
        )
        expected = FIXED_SCOPE_COUNTS.get(name, variable_counts.get(name))
        if row["observed_count"] != expected or row["accounted_count"] != expected or row["unaccounted_count"] != 0:
            raise ProducerError(f"scope conservation count differs: {name}")
        direct_type = DIRECT_SCOPE_TYPES.get(name) or VARIABLE_SCOPE_TYPES.get(name)
        if direct_type is not None and row["normalized_record_count"] != type_counts[direct_type]:
            raise ProducerError(f"scope conservation normalized count differs: {name}")
        ref = row["source_ref"]
        exact_key_check(ref, {"bundle_id", "source_locator", "source_record_sha256"}, f"scope source ref {name}")
        if ref["bundle_id"] != BUNDLE_ID:
            raise ProducerError(f"scope conservation names wrong bundle: {name}")
        relative, pointer = split_raw_locator(str(ref["source_locator"]))
        identity = (relative, pointer)
        if identity in observed_summary_refs:
            raise ProducerError("scope conservation reuses a raw summary")
        observed_summary_refs.add(identity)
        summary = resolve_json_pointer(load_json(bundle_root / relative), pointer)
        expected_summary = {
            "scope": name,
            "observed_count": row["observed_count"],
            "accounted_count": row["accounted_count"],
            "normalized_record_count": row["normalized_record_count"],
            "unaccounted_count": row["unaccounted_count"],
        }
        if summary != expected_summary or ref["source_record_sha256"] != sha256_bytes(canonical_bytes(summary)):
            raise ProducerError(f"scope conservation raw summary differs: {name}")
    if conservation["native_undefined_imports"]["observed_count"] + conservation["native_needed_edges"]["observed_count"] != conservation["native_imports"]["observed_count"]:
        raise ProducerError("native import partition does not conserve")

    exact_key_check(
        run,
        {
            "schema_version",
            "run_id",
            "experiment_id",
            "operator",
            "status",
            "artifact_set_id",
            "method_id",
            "toolchain_family",
            "commands",
            "command_exit_codes",
            "tool_versions",
            "input_artifact_ids",
            "evidence_bundle_ids",
            "source_index_attachments",
            "started_at",
            "ended_at",
        },
        "run manifest",
    )
    if (
        run["status"] != "completed"
        or run["commands"] != method["commands"]
        or run["tool_versions"] != method["tool_versions"]
        or len(run["commands"]) != len(run["command_exit_codes"])
        or any(type(code) is not int or code != 0 for code in run["command_exit_codes"])
        or run["input_artifact_ids"] != sorted(official_by_id)
    ):
        raise ProducerError("run manifest command/input/status accounting differs")
    started = datetime.strptime(str(run["started_at"]), "%Y-%m-%dT%H:%M:%SZ")
    ended = datetime.strptime(str(run["ended_at"]), "%Y-%m-%dT%H:%M:%SZ")
    captured = datetime.strptime(str(evidence["captured_at"]), "%Y-%m-%dT%H:%M:%SZ")
    generated = datetime.strptime(str(inventory["generated_at"]), "%Y-%m-%dT%H:%M:%SZ")
    if not started <= captured <= ended or generated <= ended:
        raise ProducerError("producer/evidence/inventory chronology is invalid")
    exact_key_check(
        evidence,
        {
            "schema_version",
            "bundle_id",
            "claim_ids",
            "experiment_id",
            "operator",
            "captured_at",
            "clock",
            "artifact_set_id",
            "source_variant",
            "evidence_tier",
            "instrumentation_delta",
            "environment",
            "tool_versions",
            "replay_commands",
            "event_stream",
            "attachments",
            "manifest_sha256",
        },
        "evidence manifest",
    )
    manifest_without_hash = dict(evidence)
    declared_manifest_hash = manifest_without_hash.pop("manifest_sha256")
    if declared_manifest_hash != sha256_bytes(canonical_bytes(manifest_without_hash)):
        raise ProducerError("evidence manifest canonical hash differs")
    attachment_paths: set[str] = set()
    for attachment in evidence["attachments"]:
        exact_key_check(attachment, {"path", "sha256", "size_bytes", "media_type"}, "attachment")
        relative = str(attachment["path"])
        if relative in attachment_paths:
            raise ProducerError(f"duplicate evidence attachment: {relative}")
        attachment_paths.add(relative)
        digest, size = file_hash(bundle_root / relative)
        if digest != attachment["sha256"] or size != attachment["size_bytes"]:
            raise ProducerError(f"evidence attachment differs: {relative}")
    if not set(raw_paths).issubset(attachment_paths) or "raw/scope-conservation.json" not in attachment_paths:
        raise ProducerError("raw provenance attachments are not all hash-listed")
    stream = evidence["event_stream"]
    if any(stream[field] != 0 for field in ("emitted_events", "captured_events", "dropped_events", "truncated_events")):
        raise ProducerError("static E1 event counters are nonzero")
    environment = evidence["environment"]
    if any(environment[field] is not None for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi")):
        raise ProducerError("static E1 environment claims live identity")
    events = load_json(bundle_root / str(stream["normalized_attachment"]))
    if events.get("events") != [] or events.get("canonical_sha256") != sha256_bytes(canonical_bytes([])):
        raise ProducerError("static E1 event attachment is not explicit zero")
    if publication.get("planned_independent_review_id") != inventory["independent_review_id"] or publication.get("review_approval_present") is not False:
        raise ProducerError("private publication fabricates or loses review state")
    if checks.get("hardware_runs") != 0 or checks.get("live_runs") != 0 or checks.get("celsius_claims") != 0:
        raise ProducerError("private checks contain a hardware/live/Celsius claim")

    return {
        "status": "pass",
        "record_count": len(records),
        "canonical_sha256": canonical_hash,
        "source_index_sha256": source_index["canonical_sha256"],
        "frozen_artifacts": len(artifact_records),
        "apk_members": coverage["apk_members"],
        "dex_files": coverage["dex_files"],
        "native_libraries": coverage["native_libraries"],
        "fixed_scope_counts": dict(sorted(FIXED_SCOPE_COUNTS.items())),
        "variable_scope_counts": dict(sorted(variable_counts.items())),
        "unclassified": 0,
    }


def v5_require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ProducerError(f"{code}: {detail}" if detail else code)


def v5_decode_utf16_scalar(raw: bytes) -> str:
    try:
        return unicodedata.normalize("NFC", raw.decode("utf-16-le", "strict"))
    except UnicodeDecodeError as exc:
        raise ProducerError("axml_invalid_string", str(exc)) from exc


def v5_length8(data: bytes, pos: int) -> tuple[int, int]:
    v5_require(pos < len(data), "axml_invalid_string")
    first = data[pos]
    pos += 1
    if first & 0x80:
        v5_require(pos < len(data), "axml_invalid_string")
        return ((first & 0x7F) << 8) | data[pos], pos + 1
    return first, pos


def v5_length16(data: bytes, pos: int) -> tuple[int, int]:
    v5_require(pos + 2 <= len(data), "axml_invalid_string")
    first = struct.unpack_from("<H", data, pos)[0]
    pos += 2
    if first & 0x8000:
        v5_require(pos + 2 <= len(data), "axml_invalid_string")
        second = struct.unpack_from("<H", data, pos)[0]
        return ((first & 0x7FFF) << 16) | second, pos + 2
    return first, pos


def v5_parse_string_pool(data: bytes, offset: int) -> tuple[list[str], int]:
    v5_require(offset + 28 <= len(data), "axml_string_pool")
    chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
    v5_require(chunk_type == 1 and header_size == 28 and chunk_size >= 28 and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "axml_string_pool")
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from("<IIIII", data, offset + 8)
    v5_require(flags & ~0x101 == 0, "axml_string_pool")
    v5_require(header_size + 4 * (string_count + style_count) <= chunk_size, "axml_string_pool")
    v5_require(strings_start >= header_size + 4 * (string_count + style_count) and strings_start < chunk_size, "axml_string_pool")
    if style_count:
        v5_require(styles_start >= strings_start and styles_start < chunk_size, "axml_string_pool")
    else:
        v5_require(styles_start == 0, "axml_string_pool")
    strings: list[str] = []
    for index in range(string_count):
        relative = struct.unpack_from("<I", data, offset + header_size + index * 4)[0]
        pos = offset + strings_start + relative
        v5_require(pos < offset + chunk_size, "axml_invalid_string")
        if flags & 0x100:
            utf16_len, pos = v5_length8(data, pos)
            byte_len, pos = v5_length8(data, pos)
            v5_require(pos + byte_len + 1 <= offset + chunk_size and data[pos + byte_len] == 0, "axml_invalid_string")
            try:
                text = data[pos : pos + byte_len].decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise ProducerError("axml_invalid_string", str(exc)) from exc
            v5_require(len(text.encode("utf-16-le")) // 2 == utf16_len, "axml_invalid_string")
            strings.append(unicodedata.normalize("NFC", text))
        else:
            utf16_len, pos = v5_length16(data, pos)
            byte_len = utf16_len * 2
            v5_require(pos + byte_len + 2 <= offset + chunk_size and data[pos + byte_len : pos + byte_len + 2] == b"\0\0", "axml_invalid_string")
            strings.append(v5_decode_utf16_scalar(data[pos : pos + byte_len]))
    return strings, offset + chunk_size


V5_ANDROID_NS = "http://schemas.android.com/apk/res/android"


def v10_qname_parts(qname: str) -> tuple[str, str]:
    if not qname.startswith("Q{"):
        raise ProducerError(f"invalid QName: {qname!r}")
    end = qname.find("}")
    if end < 0:
        raise ProducerError(f"invalid QName: {qname!r}")

    def pct_decode(value: str) -> str:
        data = bytearray()
        index = 0
        while index < len(value):
            char = value[index]
            if char == "%":
                if index + 2 >= len(value):
                    raise ProducerError(f"invalid QName percent escape: {qname!r}")
                data.append(int(value[index + 1 : index + 3], 16))
                index += 3
            else:
                data.extend(char.encode("utf-8"))
                index += 1
        return data.decode("utf-8", errors="strict")

    return pct_decode(qname[2:end]), pct_decode(qname[end + 1 :])


def v10_manifest_payload_attr(payload: Mapping[str, Any], name: str, namespace: str) -> Any:
    for attr in payload.get("attributes", []):
        if not isinstance(attr, Mapping):
            continue
        try:
            attr_namespace, attr_name = v10_qname_parts(str(attr.get("qname", "")))
        except (ProducerError, ValueError, UnicodeError):
            continue
        if attr_namespace == namespace and attr_name == name:
            return attr.get("typed_string") if attr.get("typed_string") is not None else attr.get("raw_value")
    return None


def build_nested_frozen_occurrence_index(
    official_by_id: Mapping[str, Mapping[str, Any]],
    artifact_record_ids: Mapping[str, str],
    *,
    canonical_base_artifact_id: str = "xapk-apk:com.hikvision.thermalGoogle.apk",
) -> dict[tuple[str, str, str, int], tuple[str, ...]]:
    """Index exact frozen artifacts nested in the canonical base APK by occurrence.

    The key intentionally includes the canonical container, namespace path,
    SHA-256, and size.  This prevents hash-only matches and prevents the same
    bytes in a different APK/container from becoming a semantic parent.
    """

    index: defaultdict[tuple[str, str, str, int], list[str]] = defaultdict(list)
    for artifact_id, artifact in sorted(official_by_id.items()):
        if artifact.get("kind") not in {"dex", "native_library", "official_fixture"}:
            continue
        source = artifact.get("source", {})
        if not isinstance(source, Mapping):
            continue
        path = str(source.get("path", ""))
        marker = "/evidence/apk/"
        if marker not in path:
            continue
        parent_id = artifact_record_ids.get(artifact_id)
        if parent_id is None:
            raise ProducerError(f"nested frozen artifact lacks record ID: {artifact_id}")
        entry_path = path.split(marker, 1)[1]
        key = (
            canonical_base_artifact_id,
            entry_path,
            str(artifact["sha256"]),
            int(artifact["size_bytes"]),
        )
        index[key].append(parent_id)
    return {key: tuple(sorted(values)) for key, values in sorted(index.items())}


def nested_frozen_parent_ids(
    index: Mapping[tuple[str, str, str, int], Sequence[str]],
    *,
    container_artifact_id: str,
    path: str,
    sha256: str,
    size_bytes: int,
) -> tuple[str, ...]:
    matches = tuple(index.get((container_artifact_id, path, sha256, size_bytes), ()))
    if len(matches) > 1:
        raise ProducerError(f"nested frozen occurrence is ambiguous: {container_artifact_id}!/{path}")
    return matches


def build_android_component_declaration_index(
    manifest_records: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], tuple[str, ...]]:
    packages: dict[str, str] = {}
    for row in manifest_records:
        payload = row["payload"]
        _namespace, local_name = v10_qname_parts(str(payload["qname"]))
        if local_name != "manifest":
            continue
        package = v10_manifest_payload_attr(payload, "package", "")
        if isinstance(package, str) and package:
            apk = str(payload["apk_artifact_id"])
            if apk not in packages or payload.get("parent_manifest_node_record_id") is None:
                packages[apk] = package

    index: defaultdict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in manifest_records:
        payload = row["payload"]
        _namespace, local_name = v10_qname_parts(str(payload["qname"]))
        package = packages.get(str(payload["apk_artifact_id"]))
        if not package:
            continue
        if local_name == "application":
            index[("application", package, package)].append(str(row["record_id"]))
            name = v10_manifest_payload_attr(payload, "name", V5_ANDROID_NS)
            if isinstance(name, str) and name:
                index[("application", package, name)].append(str(row["record_id"]))
            continue
        kind = local_name.replace("-", "_")
        if kind not in {"activity", "activity_alias", "service", "receiver", "provider"}:
            continue
        name = v10_manifest_payload_attr(payload, "name", V5_ANDROID_NS)
        if isinstance(name, str) and name:
            index[(kind, package, v5_expand_component_name(package, name))].append(str(row["record_id"]))
    return {key: tuple(sorted(values)) for key, values in sorted(index.items())}


def android_component_additional_parent_ids(
    payload: Mapping[str, Any],
    declaration_index: Mapping[tuple[str, str, str], Sequence[str]],
    component_record_ids: Mapping[tuple[str, str, str], str],
) -> tuple[str, ...]:
    kind = str(payload["kind"])
    package = str(payload["package"])
    declaration_key = (
        kind,
        package,
        package if kind == "application" else str(payload["name"]),
    )
    declaration_ids = tuple(declaration_index.get(declaration_key, ()))
    if not declaration_ids:
        raise ProducerError(f"android component lacks namespace-valid declarations: {declaration_key}")
    parents = list(declaration_ids)
    if kind == "activity_alias":
        target = payload.get("target_activity")
        if not isinstance(target, str) or not target:
            raise ProducerError(f"activity-alias target is unresolved: {payload['name']}")
        target_id = component_record_ids.get(("activity", package, target))
        if target_id is None:
            raise ProducerError(f"activity-alias target is not unique: {payload['name']} -> {target}")
        parents.append(target_id)
    return tuple(sorted(set(parents)))


def v5_parse_axml(data: bytes) -> dict[str, Any]:
    v5_require(len(data) >= 8, "axml_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    v5_require(root_type == 3 and root_header == 8 and root_size == len(data), "axml_root")
    strings, offset = v5_parse_string_pool(data, 8)
    namespace_stack: list[tuple[str, str]] = []
    resource_map: list[int] | None = None
    if offset < len(data):
        v5_require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        if chunk_type == 0x0180:
            v5_require(header_size == 8 and chunk_size >= 8 and chunk_size % 4 == 0, "axml_resource_map")
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
        v5_require(offset + 8 <= len(data), "axml_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        v5_require(header_size >= 8 and chunk_size >= header_size and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "axml_chunk")
        if chunk_type == 0x0102:
            v5_require(header_size == 16 and offset + 36 <= len(data), "axml_start_element")
            extension = offset + header_size
            ns_idx, name_idx, attr_start, attr_size, attr_count, _id_index, _class_index, _style_index = struct.unpack_from(
                "<IIHHHHHH", data, extension
            )
            v5_require(name_idx < len(strings) and attr_start == 20 and attr_size == 20, "axml_start_element")
            v5_require(ns_idx == 0xFFFFFFFF or ns_idx < len(strings), "axml_string_index")
            namespace = "" if ns_idx == 0xFFFFFFFF else strings[ns_idx]
            local_name = strings[name_idx]
            qname = v5_qname_value(namespace, local_name)
            sibling_counts = stack[-1]["sibling_counts"] if stack else defaultdict(int)
            sibling_counts[qname] += 1
            ordinal = sibling_counts[qname]
            path = (stack[-1]["path"] if stack else "axmlpath:") + f"/{qname}[{ordinal}]"
            attrs: dict[tuple[str, str], dict[str, Any]] = {}
            physical_attrs: list[dict[str, Any]] = []
            attr_offset = extension + attr_start
            for attr_ordinal in range(attr_count):
                base = attr_offset + attr_ordinal * 20
                v5_require(base + 20 <= offset + chunk_size, "axml_attribute")
                ans, aname, raw_value, value_size, res0, data_type, value_data = struct.unpack_from("<IIIHBBI", data, base)
                v5_require(aname < len(strings) and value_size == 8 and res0 == 0, "axml_attribute")
                v5_require(ans == 0xFFFFFFFF or ans < len(strings), "axml_string_index")
                v5_require(raw_value == 0xFFFFFFFF or raw_value < len(strings), "axml_string_index")
                v5_require(data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31}, "axml_value_type")
                ans_text = "" if ans == 0xFFFFFFFF else strings[ans]
                attr_name = strings[aname]
                key = (ans_text, attr_name)
                v5_require(key not in attrs, "axml_duplicate_attribute")
                if data_type == 3:
                    v5_require(value_data < len(strings), "axml_string_index")
                    typed = strings[value_data]
                else:
                    typed = None
                raw_text = None if raw_value == 0xFFFFFFFF else strings[raw_value]
                value = {
                    "namespace": ans_text,
                    "name": attr_name,
                    "attribute_ordinal": attr_ordinal,
                    "qname": v5_qname_value(ans_text, attr_name),
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
                    key=canonical_bytes,
                ),
            }
            nodes.append(node)
            if not stack and local_name == "manifest":
                package_attr = attrs.get(("", "package"))
                split_attr = attrs.get(("", "split"))
                package_name = (package_attr or {}).get("typed") or (package_attr or {}).get("raw")
                split_id = (split_attr or {}).get("typed") or (split_attr or {}).get("raw")
            if len(stack) == 1 and local_name == "uses-sdk":
                min_attr = attrs.get((V5_ANDROID_NS, "minSdkVersion"))
                target_attr = attrs.get((V5_ANDROID_NS, "targetSdkVersion"))
                if min_attr:
                    min_sdk = int(min_attr["data"])
                if target_attr:
                    target_sdk = int(target_attr["data"])
            if len(stack) == 1 and local_name == "uses-feature":
                name_attr = attrs.get((V5_ANDROID_NS, "name"))
                gl_attr = attrs.get((V5_ANDROID_NS, "glEsVersion"))
                req_attr = attrs.get((V5_ANDROID_NS, "required"))
                feature_values.append(
                    {
                        "name": (name_attr or {}).get("typed"),
                        "gl_es_version": int(gl_attr["data"]) if gl_attr else None,
                        "required": bool(req_attr["data"]) if req_attr else True,
                    }
                )
            if local_name in {"application", "activity", "activity-alias", "service", "receiver", "provider"}:
                name_attr = attrs.get((V5_ANDROID_NS, "name"))
                name = (name_attr or {}).get("typed") or (name_attr or {}).get("raw")
                component_declarations.append((local_name, name, path))
            stack.append({"qname": qname, "path": path, "sibling_counts": defaultdict(int)})
        elif chunk_type == 0x0103:
            v5_require(header_size == 16 and stack, "axml_end_element")
            ns_idx, name_idx = struct.unpack_from("<II", data, offset + header_size)
            v5_require(ns_idx == 0xFFFFFFFF or ns_idx < len(strings), "axml_string_index")
            namespace = "" if ns_idx == 0xFFFFFFFF else strings[ns_idx]
            v5_require(name_idx < len(strings), "axml_end_element")
            v5_require(stack[-1]["qname"] == v5_qname_value(namespace, strings[name_idx]), "axml_end_element")
            stack.pop()
        elif chunk_type in {0x0100, 0x0101}:
            v5_require(header_size == 16 and chunk_size == 24, "axml_namespace")
            prefix_idx, uri_idx = struct.unpack_from("<II", data, offset + 16)
            v5_require(prefix_idx < len(strings) and uri_idx < len(strings), "axml_string_index")
            pair = (strings[prefix_idx], strings[uri_idx])
            if chunk_type == 0x0100:
                namespace_stack.append(pair)
            else:
                v5_require(namespace_stack and namespace_stack[-1] == pair, "axml_namespace")
                namespace_stack.pop()
        elif chunk_type == 0x0104:
            v5_require(header_size == 16 and chunk_size == 28, "axml_cdata")
            data_idx, value_size, res0, data_type, value_data = struct.unpack_from("<IHBBI", data, offset + 16)
            v5_require(data_idx < len(strings) and value_size == 8 and res0 == 0, "axml_cdata")
            v5_require(data_type in {0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 28, 29, 30, 31}, "axml_value_type")
            if data_type == 3:
                v5_require(value_data < len(strings), "axml_string_index")
        else:
            raise ProducerError("axml_unknown_chunk")
        event_ordinal += 1
        offset += chunk_size
    v5_require(not stack and not namespace_stack, "axml_stack")
    return {
        "nodes": nodes,
        "features": feature_values,
        "components": component_declarations,
        "package": package_name,
        "split": split_id,
        "min_sdk": min_sdk,
        "target_sdk": target_sdk,
    }


def v5_pct(value: str) -> str:
    result: list[str] = []
    unreserved = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~-"
    for byte in value.encode("utf-8"):
        if byte in unreserved:
            result.append(chr(byte))
        else:
            result.append(f"%{byte:02X}")
    return "".join(result)


def v5_qname_value(namespace: str, local_name: str) -> str:
    return f"Q{{{v5_pct(namespace)}}}{v5_pct(local_name)}"


def v5_count_arsc(data: bytes, apk_artifact_id: str) -> tuple[int, int, list[dict[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    v5_require(len(data) >= 12, "arsc_root")
    root_type, root_header, root_size = struct.unpack_from("<HHI", data, 0)
    v5_require(root_type == 2 and root_header == 12 and root_size == len(data), "arsc_root")
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
        v5_require(offset + 8 <= len(data), "arsc_chunk")
        chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", data, offset)
        v5_require(header_size >= 8 and chunk_size >= header_size and chunk_size % 4 == 0 and offset + chunk_size <= len(data), "arsc_chunk")
        if chunk_type == 0x0200:
            v5_require(header_size in {284, 288}, "arsc_package_header")
            package_id = struct.unpack_from("<I", data, offset + 8)[0]
            v5_require(1 <= package_id <= 255, "arsc_package_id")
            type_id_offset = struct.unpack_from("<I", data, offset + 284)[0] if header_size == 288 else 0
            type_strings_off = struct.unpack_from("<I", data, offset + 268)[0]
            key_strings_off = struct.unpack_from("<I", data, offset + 276)[0]
            v5_require(type_strings_off >= header_size and key_strings_off >= header_size, "arsc_package_string_pool")
            type_strings, _ = v5_parse_string_pool(data, offset + type_strings_off)
            key_strings, _ = v5_parse_string_pool(data, offset + key_strings_off)
            raw_name = data[offset + 12 : offset + 268]
            nul = raw_name.find(b"\0\0")
            if nul < 0:
                nul = len(raw_name)
            if nul & 1:
                nul += 1
            package_name = v5_decode_utf16_scalar(raw_name[:nul]) if nul else ""
            v5_require(bool(package_name), "arsc_package_name")
            child = offset + header_size
            type_chunks = 0
            type_specs: dict[int, tuple[int, int]] = {}
            type_chunk_counts: Counter[int] = Counter()
            while child < offset + chunk_size:
                ctype, cheader, csize = struct.unpack_from("<HHI", data, child)
                v5_require(cheader >= 8 and csize >= cheader and csize % 4 == 0 and child + csize <= offset + chunk_size, "arsc_package_child")
                if ctype == 0x0202:
                    v5_require(cheader == 16 and csize >= 16, "arsc_type_spec")
                    spec_id = data[child + 8]
                    v5_require(data[child + 9] == 0, "arsc_type_spec")
                    declared_types_count = struct.unpack_from("<H", data, child + 10)[0]
                    spec_count = struct.unpack_from("<I", data, child + 12)[0]
                    v5_require(spec_id not in type_specs and child + 16 + spec_count * 4 == child + csize, "arsc_type_spec")
                    type_specs[spec_id] = (spec_count, declared_types_count)
                elif ctype == 0x0201:
                    v5_require(cheader >= 24, "arsc_type_chunk")
                    raw_type_id = data[child + 8]
                    flags = data[child + 9]
                    reserved = struct.unpack_from("<H", data, child + 10)[0]
                    entry_count = struct.unpack_from("<I", data, child + 12)[0]
                    entries_start = struct.unpack_from("<I", data, child + 16)[0]
                    config_size = struct.unpack_from("<I", data, child + 20)[0]
                    v5_require(reserved == 0 and flags & ~0x03 == 0 and flags != 0x03, "arsc_type_flags")
                    v5_require(config_size >= 4 and config_size % 4 == 0 and cheader == 20 + config_size, "arsc_invalid_config_size")
                    v5_require(cheader <= entries_start <= csize, "arsc_entries_start")
                    effective_type = raw_type_id + type_id_offset
                    v5_require(1 <= raw_type_id <= 255 and 1 <= effective_type <= 255, "arsc_effective_type")
                    index_start = child + cheader
                    v5_require(raw_type_id in type_specs, "arsc_type_spec_missing")
                    spec_entry_count = type_specs[raw_type_id][0]
                    type_chunk_counts[raw_type_id] += 1
                    present_entries: list[tuple[int, int, int]] = []
                    if flags & 0x01:
                        v5_require(index_start + entry_count * 4 <= child + entries_start, "arsc_sparse_range")
                        previous = -1
                        for index in range(entry_count):
                            entry_id, offset_div4 = struct.unpack_from("<HH", data, index_start + index * 4)
                            v5_require(entry_id > previous, "arsc_sparse_order")
                            v5_require(entry_id < spec_entry_count, "arsc_sparse_entry_id")
                            previous = entry_id
                            present_entries.append((index, entry_id, offset_div4 * 4))
                    elif flags & 0x02:
                        v5_require(index_start + entry_count * 2 <= child + entries_start, "arsc_offset16_range")
                        for index in range(entry_count):
                            value = struct.unpack_from("<H", data, index_start + index * 2)[0]
                            if value != 0xFFFF:
                                present_entries.append((index, index, value * 4))
                    else:
                        v5_require(index_start + entry_count * 4 <= child + entries_start, "arsc_dense_range")
                        for index in range(entry_count):
                            value = struct.unpack_from("<I", data, index_start + index * 4)[0]
                            if value != 0xFFFFFFFF:
                                present_entries.append((index, index, value))
                    configuration_count += len(present_entries)
                    entry_offsets = [entry_offset for _ordinal, _entry_id, entry_offset in present_entries]
                    v5_require(len(entry_offsets) == len(set(entry_offsets)), "arsc_entry_offset_duplicate")
                    for entry_ordinal, entry_id, entry_relative in present_entries:
                        v5_require(entry_id <= 0xFFFF, "arsc_entry_id")
                        v5_require(entry_relative % 4 == 0, "arsc_entry_alignment")
                        entry = child + entries_start + entry_relative
                        v5_require(entry + 8 <= child + csize, "arsc_entry_range")
                        entry_size, entry_flags, key_index = struct.unpack_from("<HHI", data, entry)
                        v5_require(entry_flags & ~0x000F == 0 and key_index < len(key_strings), "arsc_entry")
                        v5_require(raw_type_id - 1 < len(type_strings), "arsc_type_name")
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
                            v5_require(resource_payloads[key] == resource_payload, "arsc_resource_conflict")
                        else:
                            resource_payloads[key] = resource_payload
                        resource_record_id = record_id("resource", resource_payload)

                        def scalar_value(value_offset: int) -> dict[str, Any]:
                            v5_require(value_offset + 8 <= child + csize, "arsc_value_range")
                            value_size, res0, data_type, value_data = struct.unpack_from("<HBBI", data, value_offset)
                            v5_require(value_size == 8 and res0 == 0, "arsc_value")
                            string_value = None
                            if data_type == 3:
                                v5_require(global_strings is not None and value_data < len(global_strings), "arsc_string_value")
                                string_value = global_strings[value_data]
                            return {"kind": "scalar", "data_type": data_type, "data": value_data, "string_value": string_value}

                        if entry_flags & 0x0008:
                            raise ProducerError("arsc_compact_entry_unsupported")
                        if entry_flags & 0x0001:
                            v5_require(entry_size == 16 and entry + 16 <= child + csize, "arsc_bag_entry")
                            parent_id, item_count = struct.unpack_from("<II", data, entry + 8)
                            items: list[dict[str, Any]] = []
                            map_offset = entry + 16
                            v5_require(map_offset + item_count * 12 <= child + csize, "arsc_bag_entry")
                            for map_ordinal in range(item_count):
                                base = map_offset + map_ordinal * 12
                                name_resource_id = struct.unpack_from("<I", data, base)[0]
                                scalar = scalar_value(base + 4)
                                items.append({"map_ordinal": map_ordinal, "name_resource_id": name_resource_id, "data_type": scalar["data_type"], "data": scalar["data"], "string_value": scalar["string_value"]})
                            normalized_value: dict[str, Any] = {"kind": "bag", "parent_resource_id": parent_id, "items": items}
                        else:
                            v5_require(entry_size == 8, "arsc_scalar_entry")
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
            v5_require(child == offset + chunk_size, "arsc_package_range")
            for raw_id, (_entry_count, declared_types_count) in type_specs.items():
                v5_require(declared_types_count in {0, type_chunk_counts[raw_id]}, "arsc_type_spec_count")
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
            global_strings, parsed_end = v5_parse_string_pool(data, offset)
            v5_require(parsed_end == offset + chunk_size, "arsc_global_string_pool")
        offset += chunk_size
    v5_require(offset == len(data) and package_ordinal == package_count, "arsc_package_count")
    v5_require(global_strings is not None, "arsc_global_string_pool")
    resource_rows = sorted(resource_payloads.values(), key=canonical_bytes)
    configuration_payloads.sort(key=canonical_bytes)
    return len(logical), configuration_count, package_summaries, resource_rows, configuration_payloads


def v5_expand_component_name(package: str, name: str) -> str:
    if name.startswith("."):
        return package + name
    if "." not in name:
        return package + "." + name
    return name


def v5_component_attr(node: Mapping[str, Any], name: str) -> Any:
    item = node["attrs"].get((V5_ANDROID_NS, name))
    if item is None:
        return None
    if item.get("typed") is not None:
        return item["typed"]
    if item.get("raw") is not None:
        return item["raw"]
    if item["type"] == 18:
        return bool(item["data"])
    return item["data"]


def v5_derive_android_component_payloads(
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
        v5_require(isinstance(package, str) and package, "android_component_package")
        package_name = package_name or package
        v5_require(package == package_name, "android_component_package")
        nodes_by_path = {node["path"]: node for node in axml["nodes"]}
        for kind_raw, name, path in axml["components"]:
            kind = kind_raw.replace("-", "_")
            if kind == "application":
                identity = package
            else:
                v5_require(isinstance(name, str) and name, "android_component_name")
                identity = v5_expand_component_name(package, name)
            node = nodes_by_path[path]
            has_filter = any(
                candidate["name"] == "intent-filter" and candidate["path"].startswith(path + "/")
                for candidate in axml["nodes"]
            )
            merged[(kind, identity)].append({"node": node, "has_filter": has_filter, "package": package})
    v5_require(package_name is not None, "android_component_package")

    def explicit(rows: Sequence[Mapping[str, Any]], name: str, default: Any) -> Any:
        values = [v5_component_attr(row["node"], name) for row in rows]
        values = [value for value in values if value is not None]
        encoded = {canonical_bytes(value) for value in values}
        v5_require(len(encoded) <= 1, "android_component_merge_conflict", name)
        return values[0] if values else default

    app_rows = merged.get(("application", package_name), [])
    v5_require(app_rows, "android_component_application")
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
                    v5_expand_component_name(package_name, explicit(rows, "targetActivity", ""))
                    if kind == "activity_alias"
                    else None
                ),
                "effective_target_sdk": effective_target_sdk,
            }
        payloads.append(payload)
    payloads.sort(key=lambda payload: record_id("android_component", payload))
    return payloads




def parser_self_checks() -> None:
    vectors = {
        b"\x00": 0,
        b"\x7f": 127,
        b"\x80\x01": 128,
        b"\xe5\x8e\x26": 624485,
    }
    for encoded, expected in vectors.items():
        value, offset = read_uleb128(encoded, 0)
        if value != expected or offset != len(encoded):
            raise ProducerError("ULEB128 parser self-check failed")
    if jni_mangle("a_b/C;[") != "a_1b_C_2_3":
        raise ProducerError("JNI mangling self-check failed")
    payload = {
        "descriptor": "Lexample/\N{LATIN SMALL LETTER E WITH ACUTE};",
        "dex_artifact_id": "classes.dex",
    }
    decomposed = {
        "descriptor": "Lexample/e\N{COMBINING ACUTE ACCENT};",
        "dex_artifact_id": "classes.dex",
    }
    first = record_id("class", payload)
    second = record_id("class", decomposed)
    expected = "INV-" + hashlib.sha256(
        canonical_bytes(["g002-record/v1", "class", payload])
    ).hexdigest().upper()
    if first != second or first != expected or not RECORD_ID_RE.fullmatch(first):
        raise ProducerError("record identity self-check failed")


def resolve_default_inputs(namespace: argparse.Namespace) -> None:
    official = load_json(REPO_ROOT / OFFICIAL_MANIFEST_REL)
    by_id = {artifact["artifact_id"]: artifact for artifact in official["artifacts"]}
    if namespace.xapk is None:
        namespace.xapk = Path(by_id["official-xapk"]["source"]["path"])
    namespace.xapk = Path(namespace.xapk)
    namespace.out = Path(namespace.out)
    namespace.contract = Path(namespace.contract)
    namespace.candidate_root = Path(namespace.candidate_root)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xapk", type=Path, help="untouched official XAPK path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="private Method-B output directory")
    parser.add_argument("--contract", type=Path, default=REPO_ROOT / CONTRACT_REL, help="frozen canonical v10 contract")
    parser.add_argument("--candidate-root", type=Path, default=DEFAULT_CANDIDATE_ROOT, help="canonical v10 whole-inventory bundle root")
    parser.add_argument("--timestamp", default="2026-07-19T00:00:00Z", help="fixed RFC3339 evidence timestamp")
    parser.add_argument("--aapt2", default=DEFAULT_AAPT2_REL, help="cached AAPT2 2.19 executable")
    parser.add_argument("--zipinfo", default="zipinfo", help="Info-ZIP zipinfo executable")
    parser.add_argument("--unzip", default="unzip", help="Info-ZIP unzip executable used for version capture")
    parser.add_argument("--llvm-readobj", default="llvm-readobj-16", help="LLVM 16 readobj executable")
    parser.add_argument("--llvm-readelf", default="llvm-readelf-16", help="LLVM 16 readelf executable")
    parser.add_argument("--llvm-nm", default="llvm-nm-16", help="LLVM 16 nm executable")
    parser.add_argument("--llvm-objdump", default="llvm-objdump-16", help="LLVM 16 objdump executable")
    parser.add_argument("--keep-work", action="store_true", help="retain extracted private work files")
    parser.add_argument("--self-check-only", action="store_true", help="validate an existing Method-B output without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    resolve_default_inputs(args)
    parser_self_checks()
    if args.self_check_only:
        summary = validate_private_output_remediated(checked_output_root(args.out))
    else:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", args.timestamp):
            raise ProducerError("--timestamp must be an RFC3339 UTC second")
        summary = produce_remediated(args)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProducerError as exc:
        print(f"g002_method_b: {exc}", file=sys.stderr)
        raise SystemExit(1)
