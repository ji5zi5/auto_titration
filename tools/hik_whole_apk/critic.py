#!/usr/bin/env python3
"""Fail-closed critic for the HIKMICRO Viewer whole-APK mission.

The critic validates evidence that exists; it never treats a missing future
artifact as empty-success and never trusts a producer-written completion flag
as a substitute for the rubric gates.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, Mapping, Sequence


RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
MISSION_ROOT_REL = Path(".omx/goals/autoresearch")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVIDENCE_ID_RE = re.compile(r"^EVB-[A-Z0-9][A-Z0-9._-]*$")
REVIEW_ID_RE = re.compile(r"^REV-[A-Z0-9][A-Z0-9._-]*$")
CLAIM_ID_RE = re.compile(r"^CLM-[A-Z0-9][A-Z0-9._-]*$")
ROW_ID_RE = re.compile(r"^ROW-[A-Z0-9][A-Z0-9._-]*$")
RUN_ID_RE = re.compile(r"^RUN-[A-Z0-9][A-Z0-9._-]*$")
FORWARD_STATES = (
    "unseen",
    "inventoried",
    "static_mapped",
    "dynamically_observed",
    "specified",
    "independently_reproduced",
    "verified",
)
LEDGER_STATES = frozenset((*FORWARD_STATES, "blocked"))
TRANSITION_KINDS = frozenset(("initialize", "advance", "block", "resume", "reopen"))
CLASSIFICATION_STATES = frozenset(("classified", "unknown", "unclassified"))
SOURCE_VARIANTS = frozenset(("untouched", "root-attached", "patched-gadget", "emulated", "reimplementation"))
EVIDENCE_TIERS = ("E1", "E2", "E3", "E4", "E5")
COUNTER_KEYS = frozenset(
    (
        "blocked",
        "missing",
        "nonterminal",
        "public_proprietary_material_leaks",
        "replay_failures",
        "stale_evidence",
        "unclassified",
        "unlabeled_unknown_observations",
        "unresolved_contradictions",
    )
)
FINAL_GATE_KEYS = frozenset(
    (
        "artifact_inventory_converged",
        "component_feature_ledger_converged",
        "dossiers_approved_13_of_13",
        "evidence_replay_passed",
        "f2_first_frame_live_e2e_passed",
        "independent_reproduction_verified",
        "independent_reviews_approved",
        "radiometric_fixture_and_live_gates_passed",
        "source_independent_specification_approved",
        "two_clean_sessions_added_zero_rows",
    )
)
DOSSIER_IDS = frozenset(f"D{index:02d}" for index in range(1, 14))
SCOPE_TYPES = frozenset(
    (
        "artifact",
        "component",
        "class",
        "method_family",
        "resource",
        "native_library",
        "native_symbol",
        "jni_edge",
        "feature",
        "behavior",
        "error_recovery",
    )
)
INVENTORY_RECORD_TYPES = frozenset(
    (
        "xapk_container",
        "xapk_metadata",
        "xapk_icon",
        "apk_member",
        "extracted_apk",
        "dex",
        "native_library",
        "official_fixture",
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
DISCOVERED_INVENTORY_RECORD_TYPES = frozenset(
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
REQUIRED_DISCOVERED_INVENTORY_RECORD_TYPES = frozenset(
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
INVENTORY_SOURCE_RECORD_KEYS = frozenset(
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
G002_FIXED_SCOPE_COUNTS = {
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
    "native_exports": 99399,
    "native_imports": 12627,
    "native_needed_edges": 490,
    "native_symbols": 111628,
    "native_undefined_imports": 12137,
    "per_library_summaries": 88,
    "resource_configurations": 36498,
    "resources": 33431,
    "xapk_entries": 21,
}
G002_VARIABLE_SCOPE_TYPES = {
    "dynamic_loaders": "dynamic_loader",
    "jni_edges": "jni_edge",
    "reflection_targets": "reflection_target",
}
G002_DIRECT_SCOPE_TYPES = {
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
G002_CONSERVATION_SCOPES = frozenset((*G002_FIXED_SCOPE_COUNTS, *G002_VARIABLE_SCOPE_TYPES))
STATIC_GRAPH_RELATIONS = frozenset(
    (
        "binds",
        "calls",
        "communicates_with",
        "contains",
        "depends_on",
        "exports",
        "imports",
        "launches",
        "loads",
        "owns_feature",
        "reads",
        "references",
        "registers_jni",
        "writes",
    )
)
F2_CHECKPOINTS = (
    "usb_attach_permission_descriptor_fd_handoff",
    "libusb_open_configuration_interface_alt_endpoint",
    "transfer_allocation_submission",
    "kernel_libusb_transfer_completion",
    "libuvc_assembly_callback",
    "hcusb_packet_admission_routing_queue",
    "native_callback_invocation",
    "jni_registration_reference_thread_exception",
    "java_callback_entry",
    "packet_acceptance_frame_classification",
    "frame_consumer_preview_counter",
    "radiometric_metadata_celsius_validation",
)
RADIOMETRIC_PROOF_KEYS = frozenset(
    (
        "immutable_artifact_and_converter_identities",
        "live_frame_and_callback_provenance",
        "fixture_official_reimplementation_comparison",
        "live_official_reimplementation_comparison",
        "unit_semantics",
        "calibration_and_environment_inputs",
        "dimensions_and_stride",
        "matrix_frame_correlation",
    )
)
CLAIM_DISPOSITIONS = frozenset(
    ("observation", "inference", "hypothesis", "contradiction", "verified_conclusion")
)


class ContractError(RuntimeError):
    """Raised when observed evidence cannot satisfy a critic contract."""


@dataclass(frozen=True)
class Mission:
    directory: Path
    path: Path
    data: Mapping[str, Any]


@dataclass(frozen=True)
class Gate:
    gate_id: str
    passed: bool
    evidence: tuple[str, ...]
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class StaticInventoryValidation:
    inventory_id: str
    records: list[Mapping[str, Any]]
    canonical: bytes
    method_id: str
    toolchain_family: str
    run_id: str
    evidence_bundle_ids: frozenset[str]
    review_id: str
    operator: str
    producer_script_path: str
    producer_script_sha256: str
    producer_script_source: str
    local_dependency_sha256s: frozenset[str]
    commands: tuple[str, ...]


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _parse_json_text(text: str, label: str) -> Any:
    def reject_non_finite(token: str) -> None:
        raise ValueError(f"non-finite JSON number {token}")

    def reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> Mapping[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            parse_constant=reject_non_finite,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ContractError(f"invalid JSON {label}: {exc}") from exc


def _load_json_value(path: Path) -> Any:
    if not path.is_file():
        raise ContractError(f"missing JSON evidence: {path.as_posix()}")
    try:
        value = _parse_json_text(path.read_text(encoding="utf-8"), path.as_posix())
    except (OSError, UnicodeError) as exc:
        raise ContractError(f"invalid JSON evidence {path.as_posix()}: {exc}") from exc
    return value


def _load_json(path: Path) -> Mapping[str, Any]:
    value = _load_json_value(path)
    if not isinstance(value, dict):
        raise ContractError(f"JSON evidence must be an object: {path.as_posix()}")
    return value


def _mission_from_path(path: Path) -> Mission:
    mission_path = path / "mission.json" if path.is_dir() else path
    data = _load_json(mission_path)
    return Mission(directory=mission_path.parent, path=mission_path, data=data)


def resolve_mission(root: Path, query: str) -> Mission:
    """Resolve a mission path, stored/truncated slug, or full topic slug.

    Autoresearch directory names may be truncated while ``critic_command`` uses
    the complete slugified topic. Exact aliases win; prefix resolution is used
    only when it yields one unambiguous mission.
    """

    root = root.resolve()
    raw_path = Path(query).expanduser()
    for possible in (raw_path, root / raw_path):
        if possible.is_dir() and (possible / "mission.json").is_file():
            return _mission_from_path(possible)
        if possible.is_file() and possible.name == "mission.json":
            return _mission_from_path(possible)

    mission_root = root / MISSION_ROOT_REL
    if not mission_root.is_dir():
        raise ContractError(f"mission root does not exist: {_relative(mission_root, root)}")

    normalized_query = _slugify(query)
    if not normalized_query:
        raise ContractError("mission query normalizes to an empty slug")

    candidates: list[tuple[Mission, set[str]]] = []
    malformed: list[str] = []
    for mission_path in sorted(mission_root.glob("*/mission.json"), key=lambda path: path.as_posix()):
        try:
            mission = _mission_from_path(mission_path)
        except ContractError:
            malformed.append(_relative(mission_path, root))
            continue
        aliases = {
            _slugify(mission.directory.name),
            _slugify(str(mission.data.get("slug", ""))),
            _slugify(str(mission.data.get("topic", ""))),
        }
        aliases.discard("")
        candidates.append((mission, aliases))

    exact = [mission for mission, aliases in candidates if normalized_query in aliases]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        paths = ", ".join(sorted(_relative(item.path, root) for item in exact))
        raise ContractError(f"mission query is ambiguous across exact aliases: {paths}")

    prefix = [
        mission
        for mission, aliases in candidates
        if len(normalized_query) >= 16
        and any(alias.startswith(normalized_query) or normalized_query.startswith(alias) for alias in aliases)
    ]
    unique_prefix = {item.path.resolve(): item for item in prefix}
    if len(unique_prefix) == 1:
        return next(iter(unique_prefix.values()))
    if len(unique_prefix) > 1:
        paths = ", ".join(sorted(_relative(item.path, root) for item in unique_prefix.values()))
        raise ContractError(f"mission query is ambiguous across prefix aliases: {paths}")

    detail = f"; skipped malformed missions: {', '.join(malformed)}" if malformed else ""
    raise ContractError(f"mission not found for query {query!r}{detail}")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash {path.as_posix()}: {exc}") from exc
    return digest.hexdigest()


def _normalize_nfc_json(value: Any, *, label: str = "canonical JSON") -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise ContractError(f"{label} object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise ContractError(f"{label} contains duplicate keys after NFC normalization: {key!r}")
            normalized[key] = _normalize_nfc_json(item, label=label)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_normalize_nfc_json(item, label=label) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError(f"{label} contains a non-finite number")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ContractError(f"{label} contains unsupported value type {type(value).__name__}")


def _canonical_json_text(value: Any) -> str:
    try:
        return json.dumps(
            _normalize_nfc_json(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"cannot encode NFC canonical JSON: {exc}") from exc


def _canonical_json_bytes(value: Any) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _inventory_scope_payload(scope_key: Any, label: str) -> Any:
    if not isinstance(scope_key, str) or not scope_key:
        raise ContractError(f"{label} scope_key must be non-empty NFC canonical JSON")
    payload = _parse_json_text(scope_key, f"{label} scope_key")
    if _canonical_json_text(payload) != scope_key:
        raise ContractError(f"{label} scope_key is not NFC canonical JSON")
    return payload


def _inventory_record_id(record_type: str, scope_payload: Any) -> str:
    return "INV-" + hashlib.sha256(
        _canonical_json_bytes(["g002-record/v1", record_type, scope_payload])
    ).hexdigest().upper()


def _validate_inventory_record_identity(record: Mapping[str, Any], label: str) -> Any:
    record_type = record.get("record_type")
    if record_type not in INVENTORY_RECORD_TYPES:
        raise ContractError(f"{label} has an invalid record_type")
    payload = _inventory_scope_payload(record.get("scope_key"), label)
    expected = _inventory_record_id(str(record_type), payload)
    if record.get("record_id") != expected:
        raise ContractError(f"{label} record_id is not derived from its canonical scope payload")
    return payload


def _resolve_json_pointer(document: Any, pointer: str, label: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ContractError(f"{label} must be an RFC6901 pointer beginning with '/' ")
    current = document
    for raw_token in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", raw_token):
            raise ContractError(f"{label} contains an invalid RFC6901 escape")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ContractError(f"{label} uses a non-canonical array index {token!r}")
            index = int(token)
            if index >= len(current):
                raise ContractError(f"{label} array index is out of range: {token}")
            current = current[index]
        elif isinstance(current, Mapping):
            if token not in current:
                raise ContractError(f"{label} object key does not exist: {token!r}")
            current = current[token]
        else:
            raise ContractError(f"{label} traverses through a scalar value")
    return current


def _split_raw_source_locator(locator: Any, label: str) -> tuple[str, str]:
    if not isinstance(locator, str) or unicodedata.normalize("NFC", locator) != locator:
        raise ContractError(f"{label} must be an NFC raw JSON locator")
    if locator.count("#") != 1:
        raise ContractError(f"{label} must have raw/<attachment>.json#/<RFC6901-pointer> form")
    attachment_path, pointer = locator.split("#", 1)
    pure = PurePosixPath(attachment_path)
    if (
        not attachment_path.startswith("raw/")
        or not attachment_path.endswith(".json")
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in attachment_path.split("/"))
        or "\\" in attachment_path
        or "\x00" in attachment_path
        or not pointer.startswith("/")
    ):
        raise ContractError(f"{label} must have raw/<attachment>.json#/<RFC6901-pointer> form")
    return attachment_path, pointer


def _source_path(root: Path, raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else root / path


def _resolve_local_path(
    root: Path,
    raw: Any,
    label: str,
    *,
    allowed_root: Path | None = None,
    must_exist: bool = True,
) -> Path:
    if not isinstance(raw, str) or not raw or Path(raw).is_absolute():
        raise ContractError(f"{label} must be a non-empty repository-relative path")
    root = root.resolve()
    path = (root / raw).resolve()
    boundary = (root / allowed_root).resolve() if allowed_root is not None else root
    if path != boundary and boundary not in path.parents:
        raise ContractError(f"{label} escapes its permitted root: {raw}")
    if must_exist and not path.is_file():
        raise ContractError(f"{label} is missing: {raw}")
    return path


def _require_finite_number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ContractError(f"{label} must be finite and >= {minimum}")
    return number


def _require_exact_keys(value: Mapping[str, Any], required: set[str] | frozenset[str], label: str) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    extra = sorted(actual - required)
    if missing or extra:
        raise ContractError(f"{label} key mismatch; missing={missing}, extra={extra}")


def _require_string_list(value: Any, label: str, *, nonempty: bool = True, unique: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractError(f"{label} must be {'a non-empty' if nonempty else 'an'} array")
    if any(not isinstance(item, str) or not item for item in value):
        raise ContractError(f"{label} must contain non-empty strings")
    if unique and len(value) != len(set(value)):
        raise ContractError(f"{label} must not contain duplicates")
    return value


def _require_semantic_text(value: Any, label: str) -> str:
    """Reject empty or deliberately content-free contract prose."""

    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be non-empty text")
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    placeholders = {
        "any",
        "anything",
        "dummy",
        "fake",
        "none",
        "pass",
        "placeholder",
        "tbd",
        "todo",
        "true",
        "trust me",
        "unknown",
        "works",
    }
    if normalized in placeholders or len(normalized) < 4:
        raise ContractError(f"{label} is placeholder text, not an observable contract")
    return value


def _resolve_replay_command_target(root: Path, command: Any, label: str) -> Path:
    """Resolve the Python replay implementation without executing arbitrary evidence."""

    _require_semantic_text(command, label)
    try:
        argv = shlex.split(str(command))
    except ValueError as exc:
        raise ContractError(f"{label} is not valid shell syntax") from exc
    if len(argv) < 2 or Path(argv[0]).name not in {"python", "python3"}:
        raise ContractError(f"{label} must invoke a Python replay tool")
    allowed_root = (root / "tools/hik_whole_apk").resolve()
    if argv[1] == "-m":
        if len(argv) < 3 or not argv[2].startswith("tools.hik_whole_apk."):
            raise ContractError(f"{label} module is outside tools.hik_whole_apk")
        target = (root / (argv[2].replace(".", "/") + ".py")).resolve()
    else:
        raw_target = Path(argv[1])
        if raw_target.is_absolute():
            raise ContractError(f"{label} script must be repository-relative")
        target = (root / raw_target).resolve()
    if target != allowed_root and allowed_root not in target.parents:
        raise ContractError(f"{label} target is outside tools/hik_whole_apk")
    if not target.is_file() or target.suffix != ".py" or not target.stem.startswith("replay"):
        raise ContractError(f"{label} target does not resolve to an existing replay tool")
    return target


def _require_timestamp(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"{label} must include an explicit UTC offset")
    return value


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        member_path = Path(member.name)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ContractError(f"unsafe archive member: {member.name}")
        target = (destination / member_path).resolve()
        if target != destination and destination not in target.parents:
            raise ContractError(f"archive member escapes destination: {member.name}")
    try:
        archive.extractall(destination, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise ContractError(f"cannot extract baseline archive: {exc}") from exc


def _verify_baseline_tree(manifest: Mapping[str, Any], tree: Path) -> tuple[int, str]:
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ContractError("implementation baseline file manifest is empty")
    lines: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise ContractError("implementation baseline contains a non-object file row")
        relative = str(item.get("path", ""))
        path = tree / relative
        if not path.is_file():
            raise ContractError(f"reconstructed implementation file is missing: {relative}")
        actual_size = path.stat().st_size
        actual_hash = _sha256_file(path)
        if actual_size != item.get("size_bytes") or actual_hash != item.get("sha256"):
            raise ContractError(f"reconstructed implementation file mismatch: {relative}")
        lines.append(f"{actual_hash}\t{actual_size}\t{relative}\n")
    aggregate = _sha256_bytes("".join(lines).encode("utf-8"))
    if aggregate != manifest.get("aggregate_sha256"):
        raise ContractError(
            f"reconstructed implementation aggregate mismatch: expected {manifest.get('aggregate_sha256')}, got {aggregate}"
        )
    return len(files), aggregate


def reconstruct_implementation_baseline(root: Path, destination: Path) -> tuple[int, str]:
    """Rebuild the frozen implementation in an isolated directory and rehash it."""

    root = root.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ContractError(f"reconstruction destination must be empty: {destination.as_posix()}")
    destination = destination.resolve()
    manifest = _load_json(root / RESEARCH_REL / "governance/current-implementation-baseline.json")
    snapshots = manifest.get("snapshot_artifacts")
    if not isinstance(snapshots, dict):
        raise ContractError("implementation baseline reconstruction artifacts are missing")
    head = snapshots.get("reconstruction_base_git_head")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        raise ContractError("implementation baseline reconstruction HEAD is invalid")
    patch = root / str(snapshots.get("tracked_patch", {}).get("path", ""))
    bundle = root / str(snapshots.get("untracked_files_bundle", {}).get("path", ""))
    if not patch.is_file() or not bundle.is_file():
        raise ContractError("implementation reconstruction patch or bundle is missing")

    with tempfile.NamedTemporaryFile(prefix="g001-head-", suffix=".tar", dir=destination.parent, delete=False) as handle:
        archive_path = Path(handle.name)
    try:
        commands = [
            ["git", "archive", "--format=tar", f"--output={archive_path}", head],
            ["git", "apply", "--check", "--binary", "--unsafe-paths", f"--directory={destination}", str(patch)],
            ["git", "apply", "--binary", "--unsafe-paths", f"--directory={destination}", str(patch)],
        ]
        try:
            subprocess.run(commands[0], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with tarfile.open(archive_path, "r:") as archive:
                _safe_extract(archive, destination)
            subprocess.run(commands[1], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(commands[2], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with tarfile.open(bundle, "r:gz") as archive:
                _safe_extract(archive, destination)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", "replace").strip() if isinstance(exc.stderr, bytes) else str(exc.stderr or "").strip()
            raise ContractError(f"implementation reconstruction command failed: {stderr or exc}") from exc
        except (OSError, tarfile.TarError) as exc:
            raise ContractError(f"implementation reconstruction archive failure: {exc}") from exc
        return _verify_baseline_tree(manifest, destination)
    finally:
        archive_path.unlink(missing_ok=True)


def validate_official_artifact_freeze(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "governance/official-artifacts.json"
    manifest = _load_json(path)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("official artifact manifest has no artifacts")

    seen_ids: set[str] = set()
    seen_sources: set[tuple[str, str, str]] = set()
    kind_counts: dict[str, int] = {}
    file_cache: dict[Path, tuple[int, str]] = {}
    archive_cache: dict[Path, zipfile.ZipFile] = {}
    try:
        for index, item in enumerate(artifacts):
            if not isinstance(item, dict):
                raise ContractError(f"official artifact row {index} is not an object")
            artifact_id = item.get("artifact_id")
            kind = item.get("kind")
            expected_hash = item.get("sha256")
            expected_size = item.get("size_bytes")
            source = item.get("source")
            if not isinstance(artifact_id, str) or not artifact_id:
                raise ContractError(f"official artifact row {index} has no artifact_id")
            if artifact_id in seen_ids:
                raise ContractError(f"duplicate official artifact_id: {artifact_id}")
            seen_ids.add(artifact_id)
            if not isinstance(kind, str) or not kind:
                raise ContractError(f"official artifact {artifact_id} has no kind")
            if not isinstance(expected_hash, str) or not SHA256_RE.fullmatch(expected_hash):
                raise ContractError(f"official artifact {artifact_id} has invalid sha256")
            if not isinstance(expected_size, int) or expected_size < 0:
                raise ContractError(f"official artifact {artifact_id} has invalid size")
            if not isinstance(source, dict):
                raise ContractError(f"official artifact {artifact_id} has invalid source")

            source_type = source.get("type")
            if source_type == "file":
                source_file = _source_path(root, str(source.get("path", "")))
                source_identity = ("file", source_file.resolve().as_posix(), "")
                if source_identity in seen_sources:
                    raise ContractError(f"duplicate official artifact source identity: {source_identity}")
                seen_sources.add(source_identity)
                if source_file not in file_cache:
                    if not source_file.is_file():
                        raise ContractError(f"official artifact file missing: {source_file.as_posix()}")
                    file_cache[source_file] = (source_file.stat().st_size, _sha256_file(source_file))
                actual_size, actual_hash = file_cache[source_file]
            elif source_type == "zip_member":
                container = _source_path(root, str(source.get("container_path", "")))
                member = str(source.get("member_path", ""))
                source_identity = ("zip_member", container.resolve().as_posix(), member)
                if not member or source_identity in seen_sources:
                    raise ContractError(f"duplicate/invalid official artifact source identity: {source_identity}")
                seen_sources.add(source_identity)
                if not container.is_file():
                    raise ContractError(f"official container missing: {container.as_posix()}")
                if container not in archive_cache:
                    try:
                        archive_cache[container] = zipfile.ZipFile(container)
                    except (OSError, zipfile.BadZipFile) as exc:
                        raise ContractError(f"invalid official container {container.as_posix()}: {exc}") from exc
                try:
                    payload = archive_cache[container].read(member)
                except KeyError as exc:
                    raise ContractError(f"official container member missing: {member}") from exc
                actual_size, actual_hash = len(payload), _sha256_bytes(payload)
            else:
                raise ContractError(f"official artifact {artifact_id} has unsupported source type {source_type!r}")

            if (actual_size, actual_hash) != (expected_size, expected_hash):
                raise ContractError(
                    f"official artifact mismatch for {artifact_id}: "
                    f"expected {expected_size}/{expected_hash}, got {actual_size}/{actual_hash}"
                )
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
    finally:
        for archive in archive_cache.values():
            archive.close()

    expected = manifest.get("expected_counts")
    frozen_expected = {
        "apk_members": 19,
        "arm64_native_libraries_in_extracted_base": 88,
        "dex_files_in_extracted_base": 4,
        "known_official_fixtures": 6,
    }
    if expected != frozen_expected:
        raise ContractError("official artifact expected_counts differs from the frozen G001 universe")
    required_counts = {
        "apk_member": expected.get("apk_members"),
        "dex": expected.get("dex_files_in_extracted_base"),
        "native_library": expected.get("arm64_native_libraries_in_extracted_base"),
        "official_fixture": expected.get("known_official_fixtures"),
    }
    for kind, count in required_counts.items():
        if not isinstance(count, int) or kind_counts.get(kind) != count:
            raise ContractError(
                f"official identity count mismatch for {kind}: expected {count}, got {kind_counts.get(kind, 0)}"
            )
    frozen_kind_counts = {
        "apk_member": 19,
        "dex": 4,
        "extracted_apk": 1,
        "native_library": 88,
        "official_fixture": 6,
        "xapk_container": 1,
        "xapk_icon": 1,
        "xapk_metadata": 1,
    }
    if len(artifacts) != 121 or kind_counts != frozen_kind_counts or manifest.get("observed_counts_by_kind") != frozen_kind_counts:
        raise ContractError("official artifact total/kind universe differs from the frozen 121-source baseline")

    by_id = {str(item["artifact_id"]): item for item in artifacts if isinstance(item, dict)}
    base_member = by_id.get("xapk-apk:com.hikvision.thermalGoogle.apk")
    extracted_base = by_id.get("extracted-base-apk")
    if not base_member or not extracted_base or base_member.get("sha256") != extracted_base.get("sha256"):
        raise ContractError("extracted base APK is not hash-identical to the XAPK base member")
    xapk = by_id.get("official-xapk")
    if not isinstance(xapk, dict) or xapk.get("kind") != "xapk_container":
        raise ContractError("official XAPK identity is missing")
    xapk_path = _source_path(root, str(xapk.get("source", {}).get("path", ""))).resolve()
    member_rows = [item for item in artifacts if item.get("source", {}).get("type") == "zip_member"]
    declared_members = [str(item["source"].get("member_path", "")) for item in member_rows]
    declared_containers = {
        _source_path(root, str(item["source"].get("container_path", ""))).resolve()
        for item in member_rows
    }
    try:
        with zipfile.ZipFile(xapk_path) as archive:
            actual_members = archive.namelist()
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContractError(f"cannot enumerate frozen official XAPK: {exc}") from exc
    if (
        declared_containers != {xapk_path}
        or len(actual_members) != 21
        or len(actual_members) != len(set(actual_members))
        or set(declared_members) != set(actual_members)
        or len(declared_members) != len(actual_members)
    ):
        raise ContractError("official XAPK member universe is not exactly the frozen 21 unique entries")

    prior_hash_path = root / str(manifest.get("provenance", {}).get("prior_hash_record", ""))
    prior_hashes = prior_hash_path.read_text(encoding="utf-8") if prior_hash_path.is_file() else ""
    for artifact_id in ("official-xapk", "extracted-base-apk"):
        digest = str(by_id[artifact_id]["sha256"])
        if digest not in prior_hashes:
            raise ContractError(f"prior hash record does not contain {artifact_id} digest")

    return (
        _relative(path, root),
        f"artifact_set_id={manifest.get('artifact_set_id')}",
        f"verified_artifacts={len(artifacts)}",
        "apk_members=19",
        "dex=4",
        "arm64_native_libraries=88",
    )


def validate_implementation_baseline(root: Path, *, verify_current_files: bool = False) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "governance/current-implementation-baseline.json"
    manifest = _load_json(path)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ContractError("implementation baseline file manifest is empty")

    seen: set[str] = set()
    lines: list[str] = []
    for index, item in enumerate(files):
        if not isinstance(item, dict):
            raise ContractError(f"implementation baseline row {index} is not an object")
        rel_path = item.get("path")
        digest = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(rel_path, str) or not rel_path or rel_path in seen:
            raise ContractError(f"implementation baseline row {index} has duplicate/invalid path")
        seen.add(rel_path)
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ContractError(f"implementation baseline {rel_path} has invalid sha256")
        if not isinstance(size, int) or size < 0:
            raise ContractError(f"implementation baseline {rel_path} has invalid size")
        lines.append(f"{digest}\t{size}\t{rel_path}\n")
        if verify_current_files:
            current = root / rel_path
            if not current.is_file():
                raise ContractError(f"current implementation baseline file is missing: {rel_path}")
            if current.stat().st_size != size or _sha256_file(current) != digest:
                raise ContractError(f"current implementation differs from frozen baseline: {rel_path}")

    if len(files) != manifest.get("file_count") or sum(int(item["size_bytes"]) for item in files) != manifest.get("total_size_bytes"):
        raise ContractError("implementation baseline count/size summary is inconsistent")
    aggregate = _sha256_bytes("".join(lines).encode("utf-8"))
    if aggregate != manifest.get("aggregate_sha256"):
        raise ContractError("implementation baseline aggregate sha256 is inconsistent")

    snapshots = manifest.get("snapshot_artifacts")
    if not isinstance(snapshots, dict):
        raise ContractError("implementation baseline reconstruction artifacts are missing")
    for key in ("tracked_patch", "untracked_files_bundle"):
        item = snapshots.get(key)
        if not isinstance(item, dict):
            raise ContractError(f"implementation baseline snapshot {key} is missing")
        snapshot = root / str(item.get("path", ""))
        if not snapshot.is_file():
            raise ContractError(f"implementation baseline snapshot missing: {snapshot.as_posix()}")
        if snapshot.stat().st_size != item.get("size_bytes") or _sha256_file(snapshot) != item.get("sha256"):
            raise ContractError(f"implementation baseline snapshot mismatch: {snapshot.as_posix()}")

    bundle = snapshots["untracked_files_bundle"]
    bundle_path = root / str(bundle["path"])
    try:
        compressed = bundle_path.read_bytes()
        if len(compressed) < 10 or compressed[:3] != b"\x1f\x8b\x08" or compressed[4:8] != b"\x00\x00\x00\x00":
            raise ContractError("untracked baseline bundle does not use a deterministic zero-mtime gzip header")
        with tarfile.open(bundle_path, "r:gz") as archive:
            archive_members = archive.getmembers()
            if any(not member.isfile() for member in archive_members):
                raise ContractError("untracked baseline bundle must contain regular files only")
            member_names = [member.name for member in archive_members]
            if member_names != sorted(member_names) or len(member_names) != len(set(member_names)):
                raise ContractError("untracked baseline bundle members are not unique and lexicographically sorted")
            for member in archive_members:
                if (member.uid, member.gid, member.mtime, member.uname, member.gname) != (0, 0, 0, "", ""):
                    raise ContractError(f"untracked baseline bundle metadata is not normalized: {member.name}")
                if member.mode & 0o777 != 0o644:
                    raise ContractError(f"untracked baseline bundle mode is not deterministic 0644: {member.name}")
            archive_files = {member.name: member for member in archive_members}
            members = member_names
            manifest_by_path = {str(item["path"]): item for item in files if isinstance(item, dict)}
            for member_name, member in archive_files.items():
                expected = manifest_by_path.get(member_name)
                if expected is None:
                    raise ContractError(f"baseline bundle contains a path outside the file manifest: {member_name}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise ContractError(f"cannot read baseline bundle member: {member_name}")
                payload = handle.read()
                if len(payload) != expected["size_bytes"] or _sha256_bytes(payload) != expected["sha256"]:
                    raise ContractError(f"baseline bundle member does not match file manifest: {member_name}")
    except (OSError, tarfile.TarError) as exc:
        raise ContractError(f"invalid untracked baseline bundle: {exc}") from exc
    if members != sorted(str(value) for value in bundle.get("members", [])):
        raise ContractError("untracked baseline bundle member list does not match manifest")
    if bundle.get("file_count") != len(members):
        raise ContractError("untracked baseline bundle file_count does not match archive")

    head = snapshots.get("reconstruction_base_git_head")
    if not isinstance(head, str) or head != manifest.get("git", {}).get("head"):
        raise ContractError("implementation reconstruction HEAD disagrees with the frozen git HEAD")
    try:
        head_listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", head],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise ContractError(f"cannot inspect frozen git HEAD: {exc}") from exc
    head_paths = {item.decode("utf-8") for item in head_listing.split(b"\0") if item}
    required_bundle_members = sorted(str(item["path"]) for item in files if str(item["path"]) not in head_paths)
    if members != required_bundle_members:
        missing = sorted(set(required_bundle_members) - set(members))
        extra = sorted(set(members) - set(required_bundle_members))
        raise ContractError(f"baseline bundle does not cover every manifest-listed non-HEAD file; missing={missing}, extra={extra}")

    status = manifest.get("git", {})
    status_path = root / str(status.get("status_snapshot_path", ""))
    if not status_path.is_file() or _sha256_file(status_path) != status.get("status_snapshot_sha256"):
        raise ContractError("implementation git status snapshot is missing or changed")
    patch_hash = snapshots["tracked_patch"].get("sha256")
    if patch_hash != status.get("tracked_diff_sha256"):
        raise ContractError("tracked patch hash disagrees with recorded tracked diff hash")

    build_artifacts = manifest.get("build_artifacts")
    if not isinstance(build_artifacts, dict):
        raise ContractError("pre-existing implementation APK hashes are missing")
    apk_items = build_artifacts.get("artifacts")
    if not isinstance(apk_items, list) or len(apk_items) != build_artifacts.get("count"):
        raise ContractError("pre-existing implementation APK count is inconsistent")
    for item in apk_items:
        if not isinstance(item, dict):
            raise ContractError("pre-existing implementation APK row is invalid")
        if not isinstance(item.get("path"), str) or not SHA256_RE.fullmatch(str(item.get("sha256", ""))):
            raise ContractError("pre-existing implementation APK path/hash is invalid")
        if not isinstance(item.get("size_bytes"), int) or int(item["size_bytes"]) < 0:
            raise ContractError("pre-existing implementation APK size is invalid")
        if item.get("source_rebuild_verified") is not False:
            raise ContractError("G001 must not claim a fresh source rebuild for pre-existing APKs")
        if verify_current_files:
            apk_path = root / str(item["path"])
            if not apk_path.is_file():
                raise ContractError(f"pre-existing implementation APK is missing: {_relative(apk_path, root)}")
            if apk_path.stat().st_size != item["size_bytes"] or _sha256_file(apk_path) != item["sha256"]:
                raise ContractError(f"pre-existing implementation APK changed: {_relative(apk_path, root)}")

    evidence = [
        _relative(path, root),
        f"baseline_id={manifest.get('baseline_id')}",
        f"frozen_files={len(files)}",
        f"aggregate_sha256={aggregate}",
        "reconstructable_from_git_head_patch_and_untracked_bundle=true",
        f"preexisting_apk_hashes_frozen={len(apk_items)}",
        "preexisting_apk_source_rebuild_claimed=false",
    ]
    if verify_current_files:
        evidence.append("current_files_match_frozen_baseline=true")
        evidence.append("preexisting_apk_files_match_frozen_hashes=true")
        with tempfile.TemporaryDirectory(prefix="g001-reconstruction-", dir="/tmp") as temporary:
            reconstructed_count, reconstructed_aggregate = reconstruct_implementation_baseline(root, Path(temporary) / "tree")
        if reconstructed_count != len(files) or reconstructed_aggregate != aggregate:
            raise ContractError("isolated implementation reconstruction summary disagrees with the baseline manifest")
        evidence.append(f"isolated_reconstruction_files={reconstructed_count}")
        evidence.append(f"isolated_reconstruction_aggregate_sha256={reconstructed_aggregate}")
    return tuple(evidence)


def _validate_g002_phase_claim_index(root: Path) -> int:
    claims_root = root / RESEARCH_REL / "claims"
    index = _load_json(claims_root / "index.json")
    _require_exact_keys(index, {"schema_version", "artifact_set_id", "claims"}, "G002 claim index")
    if index.get("schema_version") != 1 or index.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("G002 claim index identity/artifact set is invalid")
    rows = index.get("claims")
    if not isinstance(rows, list) or not rows:
        raise ContractError("G002 phase requires a non-empty claim index")
    observed_ids: list[str] = []
    claim_keys = {
        "schema_version",
        "claim_id",
        "artifact_set_id",
        "statement",
        "disposition",
        "evidence_tier",
        "evidence_bundle_ids",
        "replay_commands",
        "limitations",
        "contradicts_claim_ids",
        "supersedes_claim_ids",
        "independent_review_ids",
    }
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"G002 claim index row {position} is not an object")
        _require_exact_keys(row, {"claim_id", "path", "sha256", "size_bytes"}, f"G002 claim index row {position}")
        claim_id = row.get("claim_id")
        if (
            not isinstance(claim_id, str)
            or not CLAIM_ID_RE.fullmatch(claim_id)
            or not claim_id.startswith("CLM-G002-")
            or claim_id in observed_ids
        ):
            raise ContractError(f"G002 claim index row {position} has an invalid/duplicate claim_id")
        path = _resolve_local_path(root, row.get("path"), f"G002 claim {claim_id}", allowed_root=RESEARCH_REL / "claims")
        if path.resolve() != (claims_root / f"{claim_id}.json").resolve():
            raise ContractError(f"G002 claim {claim_id} is not at its canonical path")
        if (
            row.get("sha256") != _sha256_file(path)
            or row.get("size_bytes") != path.stat().st_size
            or not SHA256_RE.fullmatch(str(row.get("sha256", "")))
        ):
            raise ContractError(f"G002 claim index hash/size mismatch for {claim_id}")
        claim = _load_json(path)
        _require_exact_keys(claim, claim_keys, f"G002 claim {claim_id}")
        if (
            claim.get("schema_version") != 1
            or claim.get("claim_id") != claim_id
            or claim.get("artifact_set_id") != index["artifact_set_id"]
            or claim.get("evidence_tier") != "E1"
            or claim.get("disposition") not in {"observation", "inference"}
        ):
            raise ContractError(f"G002 claim {claim_id} exceeds the static E1 phase")
        _require_semantic_text(claim.get("statement"), f"G002 claim {claim_id} statement")
        bundle_ids = _require_string_list(claim.get("evidence_bundle_ids"), f"G002 claim {claim_id} evidence_bundle_ids")
        if any(not EVIDENCE_ID_RE.fullmatch(value) or not value.startswith("EVB-G002-") for value in bundle_ids):
            raise ContractError(f"G002 claim {claim_id} has invalid evidence bundle IDs")
        _require_string_list(claim.get("replay_commands"), f"G002 claim {claim_id} replay_commands")
        _require_string_list(claim.get("limitations"), f"G002 claim {claim_id} limitations")
        _require_string_list(claim.get("contradicts_claim_ids"), f"G002 claim {claim_id} contradictions", nonempty=False)
        _require_string_list(claim.get("supersedes_claim_ids"), f"G002 claim {claim_id} supersedes", nonempty=False)
        review_ids = _require_string_list(
            claim.get("independent_review_ids"),
            f"G002 claim {claim_id} independent_review_ids",
        )
        if any(not REVIEW_ID_RE.fullmatch(value) or not value.startswith("REV-G002-") for value in review_ids):
            raise ContractError(f"G002 claim {claim_id} has invalid independent review IDs")
        observed_ids.append(claim_id)
    if observed_ids != sorted(observed_ids):
        raise ContractError("G002 claim index rows are not sorted by claim_id")
    claim_files = sorted(path.stem for path in claims_root.glob("CLM-*.json"))
    if claim_files != observed_ids:
        raise ContractError("G002 claim files and claim index do not have exact set equality")
    return len(observed_ids)


def validate_governance_contracts(root: Path) -> tuple[str, ...]:
    governance = root / RESEARCH_REL / "governance"
    manifest_path = governance / "governance-manifest.json"
    manifest = _load_json(manifest_path)
    expected_schemas = {
        "claim",
        "closure_counters",
        "evidence_bundle",
        "ledger",
        "run_manifest",
    }
    schemas = manifest.get("schemas")
    if not isinstance(schemas, dict) or set(schemas) != expected_schemas:
        raise ContractError("governance manifest does not enumerate the five required schemas")
    for name, rel_path in sorted(schemas.items()):
        schema = _load_json(root / str(rel_path))
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ContractError(f"{name} schema is not pinned to JSON Schema 2020-12")
        if schema.get("type") != "object" or not isinstance(schema.get("required"), list):
            raise ContractError(f"{name} schema lacks object/required contract")

    variants = _load_json(governance / "source-variants.json").get("variants")
    variant_ids = {item.get("id") for item in variants if isinstance(item, dict)} if isinstance(variants, list) else set()
    expected_variants = {"untouched", "root-attached", "patched-gadget", "emulated", "reimplementation"}
    if variant_ids != expected_variants:
        raise ContractError(f"source variant set mismatch: {sorted(variant_ids)}")

    policies = {
        "authorization-scope.md": ("Separate authorization gates", "public distribution"),
        "evidence-tiers.md": ("E0", "E5", "verified_conclusion", "claims/index.json", "captured_events"),
        "clean-room-policy.md": ("Clean implementers", "official method bodies"),
        "no-fake-celsius-policy.md": ("<= 0.1 °C", "<= 0.5 °C", "JSON `null`"),
        "ledger-contract.md": ("unseen -> inventoried", "current_causal_frontier"),
        "closure-contract.md": ("blocked rows", "exactly zero", "`null` means not computed"),
        "review-contract.md": ("producer self-review", "`REV-*`", "`EVB-*`"),
        "rubric-format-disposition.md": ("rubric.md", "rubric.json", "autoresearch-goal"),
        "static-inventory-contract.md": ("SELF-ASSERTED-NO-EVIDENCE", "source_refs", "121-row"),
    }
    manifest_policies = manifest.get("policies")
    if not isinstance(manifest_policies, dict):
        raise ContractError("governance manifest policy map is missing")
    for name, required_fragments in policies.items():
        policy_path = governance / name
        if not policy_path.is_file():
            raise ContractError(f"missing governance policy: {name}")
        text = policy_path.read_text(encoding="utf-8")
        missing = [fragment for fragment in required_fragments if fragment not in text]
        if missing:
            raise ContractError(f"governance policy {name} is missing: {missing}")
        if _relative(policy_path, root) not in manifest_policies.values():
            raise ContractError(f"governance manifest does not reference policy {name}")

    phase_started = manifest.get("g002_inventory_started")
    if type(phase_started) is not bool:
        raise ContractError("governance manifest g002_inventory_started must be boolean")
    current_closure = _load_json(root / RESEARCH_REL / "closure/current.json")
    counters = current_closure.get("counters")
    final_gates = current_closure.get("final_gates")
    if (
        current_closure.get("closure_allowed") is not False
        or current_closure.get("counts_are_complete") is not False
        or current_closure.get("computed_from_ledger") is not None
        or current_closure.get("current_causal_frontier_count") is not None
        or not isinstance(counters, dict)
        or set(counters) != COUNTER_KEYS
        or any(value is not None for value in counters.values())
        or not isinstance(final_gates, dict)
        or set(final_gates) != FINAL_GATE_KEYS
    ):
        raise ContractError("G001/G002 closure must remain incomplete with null counters")
    claims_readme = root / RESEARCH_REL / "claims/README.md"
    claims_index = root / RESEARCH_REL / "claims/index.json"
    canonical_inventories = tuple(
        root / RESEARCH_REL / "static" / name for name in ("inventory-a.json", "inventory-b.json")
    )
    if not claims_readme.is_file():
        raise ContractError("claim path README is missing")

    if not phase_started:
        mixed = (
            current_closure.get("inventory_started") is not False
            or claims_index.exists()
            or any((root / RESEARCH_REL / "claims").glob("CLM-*.json"))
            or any(path.exists() for path in canonical_inventories)
            or any(value is not False for value in final_gates.values())
        )
        if mixed:
            raise ContractError("mixed G001/G002 phase state: pre-G002 forbids claims, canonical inventories, and inventory_started")
        phase_evidence = ("governance_phase=G001", "g002_inventory_started=false")
    else:
        later_gate_values = {
            key: value for key, value in final_gates.items() if key != "artifact_inventory_converged"
        }
        mixed = (
            current_closure.get("inventory_started") is not True
            or not claims_index.is_file()
            or any(not path.is_file() for path in canonical_inventories)
            or type(final_gates.get("artifact_inventory_converged")) is not bool
            or any(value is not False for value in later_gate_values.values())
        )
        if mixed:
            raise ContractError("mixed G001/G002 phase state: G002 requires claims, both canonical inventories, and inventory_started only")
        claim_count = _validate_g002_phase_claim_index(root)
        phase_evidence = ("governance_phase=G002", "g002_inventory_started=true", f"g002_claims={claim_count}")

    return (
        _relative(manifest_path, root),
        "json_schemas=5_with_claim_index_and_normalized_event_defs",
        "source_variants=5",
        "clean_room_boundary=frozen",
        "no_fake_celsius=fail_closed",
        *phase_evidence,
    )


def validate_mission_contract(root: Path, mission: Mission) -> tuple[str, ...]:
    data = mission.data
    required = {
        "schema_version",
        "workflow",
        "slug",
        "topic",
        "rubric",
        "critic_command",
        "status",
        "created_at",
        "updated_at",
        "mission_path",
        "rubric_path",
        "ledger_path",
        "completion_path",
    }
    _require_exact_keys(data, required, "Autoresearch mission")
    if data.get("schema_version") != 1 or data.get("workflow") != "autoresearch-goal":
        raise ContractError("mission schema/workflow is not the approved autoresearch-goal contract")
    if mission.path.resolve() != (mission.directory / "mission.json").resolve():
        raise ContractError("Autoresearch mission file is not mission.json")
    rubric_path = _resolve_local_path(root, data.get("rubric_path"), "mission rubric", allowed_root=MISSION_ROOT_REL)
    if rubric_path.resolve() != (mission.directory / "rubric.md").resolve():
        raise ContractError("mission rubric_path must resolve to the mission-local rubric.md")
    if (mission.directory / "rubric.json").exists():
        raise ContractError("mission has an unauthorized competing rubric.json")
    rubric_text = rubric_path.read_text(encoding="utf-8").strip()
    if rubric_text != str(data.get("rubric", "")).strip():
        raise ContractError("mission JSON rubric and rubric.md differ")
    critic_command = data.get("critic_command")
    if not isinstance(critic_command, str):
        raise ContractError("mission critic_command is missing")
    try:
        argv = shlex.split(critic_command)
        index = argv.index("--mission")
        command_query = argv[index + 1]
    except (ValueError, IndexError) as exc:
        raise ContractError("mission critic_command has no usable --mission argument") from exc
    if "tools/hik_whole_apk/critic.py" not in argv:
        raise ContractError("mission critic_command does not target the executable whole-APK critic")
    command_mission = resolve_mission(root, command_query)
    if command_mission.path.resolve() != mission.path.resolve():
        raise ContractError("mission critic_command resolves to a different mission")
    if data.get("status") not in {"in_progress", "complete"}:
        raise ContractError(f"mission has unsupported status {data.get('status')!r}")
    ledger_path = _resolve_local_path(root, data.get("ledger_path"), "mission ledger", allowed_root=MISSION_ROOT_REL)
    if ledger_path.resolve() != (mission.directory / "ledger.jsonl").resolve():
        raise ContractError("mission ledger_path must resolve to the mission-local ledger.jsonl")
    completion_path = _resolve_local_path(
        root,
        data.get("completion_path"),
        "mission completion",
        allowed_root=MISSION_ROOT_REL,
        must_exist=data.get("status") == "complete",
    )
    if completion_path.resolve() != (mission.directory / "completion.json").resolve():
        raise ContractError("mission completion_path must resolve to the mission-local completion.json")
    disposition = root / RESEARCH_REL / "governance/rubric-format-disposition.md"
    if not disposition.is_file():
        raise ContractError("Autoresearch rubric-format disposition is missing")
    return (
        _relative(mission.path, root),
        _relative(rubric_path, root),
        f"resolved_slug={mission.data.get('slug')}",
        "rubric_format=markdown_per_autoresearch_goal_contract",
        "critic_command_resolves_same_mission=true",
    )


def _missing_files(root: Path, relative_paths: Sequence[Path]) -> list[str]:
    return [_relative(root / path, root) for path in relative_paths if not (root / path).is_file()]


def _official_artifact_set_id(root: Path) -> str:
    value = _load_json(root / RESEARCH_REL / "governance/official-artifacts.json").get("artifact_set_id")
    if not isinstance(value, str) or not value:
        raise ContractError("official artifact_set_id is missing")
    return value


def resolve_claim(root: Path, claim_id: str) -> Path:
    if not CLAIM_ID_RE.fullmatch(claim_id):
        raise ContractError(f"invalid claim ID: {claim_id!r}")
    index_path = root / RESEARCH_REL / "claims/index.json"
    index = _load_json(index_path)
    _require_exact_keys(index, {"schema_version", "artifact_set_id", "claims"}, "claim index")
    if index.get("schema_version") != 1 or index.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("claim index identity/artifact set is invalid")
    rows = index.get("claims")
    if not isinstance(rows, list) or not rows:
        raise ContractError("claim index is empty")
    observed_ids: set[str] = set()
    matches: list[Path] = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"claim index row {position} is not an object")
        _require_exact_keys(row, {"claim_id", "path", "sha256", "size_bytes"}, f"claim index row {position}")
        indexed_id = row.get("claim_id")
        if not isinstance(indexed_id, str) or not CLAIM_ID_RE.fullmatch(indexed_id) or indexed_id in observed_ids:
            raise ContractError(f"claim index row {position} has invalid/duplicate claim_id")
        observed_ids.add(indexed_id)
        path = _resolve_local_path(root, row.get("path"), f"claim {indexed_id}", allowed_root=RESEARCH_REL / "claims")
        canonical_path = (root / RESEARCH_REL / "claims" / f"{indexed_id}.json").resolve()
        if path.resolve() != canonical_path:
            raise ContractError(f"claim {indexed_id} is not at its canonical path")
        if (
            not SHA256_RE.fullmatch(str(row.get("sha256", "")))
            or type(row.get("size_bytes")) is not int
            or row["size_bytes"] < 0
            or path.stat().st_size != row["size_bytes"]
            or _sha256_file(path) != row["sha256"]
        ):
            raise ContractError(f"claim index hash/size mismatch for {indexed_id}")
        if indexed_id == claim_id:
            matches.append(path)
    if [str(row["claim_id"]) for row in rows] != sorted(observed_ids):
        raise ContractError("claim index rows are not sorted by claim_id")
    if len(matches) != 1:
        raise ContractError(f"claim not found or ambiguous for ID {claim_id}")
    return matches[0]


def validate_claim_record(
    root: Path,
    claim_id: str,
    *,
    supporting_bundle_id: str,
    supporting_tier: str,
) -> Mapping[str, Any]:
    claim = _load_json(resolve_claim(root, claim_id))
    required = {
        "schema_version",
        "claim_id",
        "artifact_set_id",
        "statement",
        "disposition",
        "evidence_tier",
        "evidence_bundle_ids",
        "replay_commands",
        "limitations",
        "contradicts_claim_ids",
        "supersedes_claim_ids",
        "independent_review_ids",
    }
    _require_exact_keys(claim, required, f"claim {claim_id}")
    if (
        claim.get("schema_version") != 1
        or claim.get("claim_id") != claim_id
        or claim.get("artifact_set_id") != _official_artifact_set_id(root)
        or not isinstance(claim.get("statement"), str)
        or not claim["statement"]
        or claim.get("disposition") not in CLAIM_DISPOSITIONS
        or claim.get("evidence_tier") not in (*EVIDENCE_TIERS, "E0")
    ):
        raise ContractError(f"claim {claim_id} identity/content is invalid")
    evidence_ids = _require_string_list(claim.get("evidence_bundle_ids"), f"claim {claim_id} evidence_bundle_ids")
    if supporting_bundle_id not in evidence_ids or any(not EVIDENCE_ID_RE.fullmatch(value) for value in evidence_ids):
        raise ContractError(f"claim {claim_id} does not resolve back to supporting bundle {supporting_bundle_id}")
    resolved_bundles: dict[str, Mapping[str, Any]] = {}
    for evidence_id in evidence_ids:
        _, evidence = validate_evidence_bundle(root, evidence_id, resolve_claims=False)
        if claim_id not in evidence["claim_ids"]:
            raise ContractError(f"claim {claim_id} is not cross-linked by evidence bundle {evidence_id}")
        resolved_bundles[evidence_id] = evidence
    maximum_tier = max(
        (str(bundle["evidence_tier"]) for bundle in resolved_bundles.values()),
        key=EVIDENCE_TIERS.index,
    )
    if claim["evidence_tier"] == "E0" or claim["evidence_tier"] != maximum_tier:
        raise ContractError(f"claim {claim_id} tier is not derived from its complete evidence chain")
    replay_commands = _require_string_list(claim.get("replay_commands"), f"claim {claim_id} replay_commands")
    limitations = claim.get("limitations")
    if not isinstance(limitations, list) or any(not isinstance(value, str) or not value for value in limitations):
        raise ContractError(f"claim {claim_id} limitations are invalid")
    for relation in ("contradicts_claim_ids", "supersedes_claim_ids"):
        related = _require_string_list(claim.get(relation), f"claim {claim_id} {relation}", nonempty=False)
        if claim_id in related or any(not CLAIM_ID_RE.fullmatch(value) for value in related):
            raise ContractError(f"claim {claim_id} has invalid {relation}")
        for related_id in related:
            resolve_claim(root, related_id)
    review_ids = _require_string_list(
        claim.get("independent_review_ids"),
        f"claim {claim_id} independent_review_ids",
        nonempty=claim.get("disposition") == "verified_conclusion",
    )
    if any(not REVIEW_ID_RE.fullmatch(value) for value in review_ids):
        raise ContractError(f"claim {claim_id} has invalid independent review IDs")
    if supporting_tier == "E5" and (
        claim.get("evidence_tier") != "E5" or claim.get("disposition") != "verified_conclusion" or not review_ids
    ):
        raise ContractError(f"E5 bundle claim {claim_id} is not a reviewed verified conclusion")
    if claim.get("disposition") == "verified_conclusion" and claim.get("evidence_tier") != "E5":
        raise ContractError(f"claim {claim_id} declares a verified conclusion below E5")
    if claim.get("disposition") == "verified_conclusion":
        observed_tiers = {str(bundle["evidence_tier"]) for bundle in resolved_bundles.values()}
        if not {"E1", "E4", "E5"}.issubset(observed_tiers) or not observed_tiers.intersection({"E2", "E3"}):
            raise ContractError(
                f"verified conclusion claim {claim_id} lacks its E1, dynamic E2/E3, E4, and E5 evidence chain"
            )
    producer_ids = tuple(str(bundle["operator"]) for bundle in resolved_bundles.values())
    for review_id in review_ids:
        validate_review(
            root,
            review_id,
            subject_id=claim_id,
            expected_bundle_ids=evidence_ids,
            producer_ids=producer_ids,
            resolve_claims=False,
        )
    if not set(replay_commands):
        raise ContractError(f"claim {claim_id} lacks replay commands")
    return claim


def validate_claim_graph(root: Path) -> tuple[Mapping[str, Mapping[str, Any]], set[str]]:
    """Validate every indexed claim and derive unresolved contradictions.

    A contradiction is not cleared by omitting it from a dossier or closure
    counter.  It remains active until a reviewed E5 verified conclusion
    explicitly supersedes the contradictory claim.  Verified conclusions that
    contradict older claims must also supersede those exact claims; otherwise
    the relation is still an unresolved disagreement.
    """

    index_path = root / RESEARCH_REL / "claims/index.json"
    index = _load_json(index_path)
    _require_exact_keys(index, {"schema_version", "artifact_set_id", "claims"}, "claim index")
    if index.get("schema_version") != 1 or index.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("claim index identity/artifact set is invalid")
    rows = index.get("claims")
    if not isinstance(rows, list) or not rows:
        raise ContractError("claim index is empty")

    claims: dict[str, Mapping[str, Any]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"claim index row {position} is not an object")
        claim_id = row.get("claim_id")
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id) or claim_id in claims:
            raise ContractError(f"claim index row {position} has invalid/duplicate claim_id")
        path = resolve_claim(root, claim_id)
        claim = _load_json(path)
        evidence_ids = claim.get("evidence_bundle_ids")
        if not isinstance(evidence_ids, list) or not evidence_ids:
            raise ContractError(f"claim {claim_id} has no evidence chain")
        first_bundle_id = evidence_ids[0]
        if not isinstance(first_bundle_id, str):
            raise ContractError(f"claim {claim_id} has an invalid evidence chain")
        _, first_bundle = validate_evidence_bundle(root, first_bundle_id, resolve_claims=False)
        claims[claim_id] = validate_claim_record(
            root,
            claim_id,
            supporting_bundle_id=first_bundle_id,
            supporting_tier=str(first_bundle["evidence_tier"]),
        )

    contradiction_ids: set[str] = set()
    superseded_ids: set[str] = set()
    for claim_id, claim in claims.items():
        contradicts = set(str(value) for value in claim["contradicts_claim_ids"])
        supersedes = set(str(value) for value in claim["supersedes_claim_ids"])
        if claim["disposition"] == "contradiction" and not contradicts:
            raise ContractError(f"contradiction claim {claim_id} does not identify the claim it contradicts")
        if contradicts and claim["disposition"] != "verified_conclusion":
            contradiction_ids.add(claim_id)
        if claim["disposition"] == "verified_conclusion":
            if not contradicts.issubset(supersedes):
                raise ContractError(
                    f"verified conclusion {claim_id} contradicts claims without explicitly superseding them"
                )
            superseded_ids.update(supersedes)
        elif supersedes:
            raise ContractError(f"non-verified claim {claim_id} cannot resolve claims by superseding them")

    unresolved = contradiction_ids - superseded_ids
    return claims, unresolved


def _validate_normalized_event_document(
    path: Path,
    *,
    bundle: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    document = _load_json(path)
    required = {
        "schema_version",
        "schema_id",
        "artifact_set_id",
        "experiment_id",
        "source_variant",
        "events",
        "canonical_sha256",
    }
    _require_exact_keys(document, required, f"normalized event document {path.as_posix()}")
    events = document.get("events")
    if not isinstance(events, list):
        raise ContractError(f"normalized event document {path.as_posix()} events are not an array")
    if (
        document.get("schema_version") != 1
        or document.get("schema_id") != bundle["event_stream"]["schema_id"]
        or document.get("artifact_set_id") != bundle["artifact_set_id"]
        or document.get("experiment_id") != bundle["experiment_id"]
        or document.get("source_variant") != bundle["source_variant"]
    ):
        raise ContractError(f"normalized event document {path.as_posix()} identity is invalid")
    canonical = json.dumps(events, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if document.get("canonical_sha256") != _sha256_bytes(canonical.encode("utf-8")):
        raise ContractError(f"normalized event document {path.as_posix()} canonical hash is invalid")
    event_keys = {
        "event_id",
        "event_type",
        "monotonic_ns",
        "correlation_id",
        "process_id",
        "thread_id",
        "object_id",
        "reference_id",
        "buffer_pointer",
        "buffer_length",
        "endpoint",
        "transfer_id",
        "error_state",
        "claim_ids",
        "observation_id",
        "checkpoint_id",
        "run_id",
        "value",
    }
    event_ids: set[str] = set()
    sort_keys: list[tuple[int, str]] = []
    for position, event in enumerate(events):
        label = f"normalized event {position} in {path.as_posix()}"
        if not isinstance(event, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(event, event_keys, label)
        event_id = event.get("event_id")
        if not isinstance(event_id, str) or not event_id or event_id in event_ids:
            raise ContractError(f"{label} has invalid/duplicate event_id")
        event_ids.add(event_id)
        if not isinstance(event.get("event_type"), str) or not event["event_type"]:
            raise ContractError(f"{label} has no event_type")
        monotonic_ns = event.get("monotonic_ns")
        if type(monotonic_ns) is not int or monotonic_ns < 0:
            raise ContractError(f"{label} has invalid monotonic_ns")
        sort_keys.append((monotonic_ns, event_id))
        correlation_id = event.get("correlation_id")
        if bundle["evidence_tier"] != "E1" and (not isinstance(correlation_id, str) or not correlation_id):
            raise ContractError(f"{label} lacks a correlation_id")
        if correlation_id is not None and not isinstance(correlation_id, str):
            raise ContractError(f"{label} has invalid correlation_id")
        for field in ("process_id", "thread_id"):
            if event.get(field) is not None and (type(event[field]) is not int or event[field] < 0):
                raise ContractError(f"{label} has invalid {field}")
        for field in (
            "object_id",
            "reference_id",
            "buffer_pointer",
            "endpoint",
            "transfer_id",
            "error_state",
            "observation_id",
            "checkpoint_id",
            "run_id",
        ):
            if event.get(field) is not None and (not isinstance(event[field], str) or not event[field]):
                raise ContractError(f"{label} has invalid {field}")
        if event.get("buffer_length") is not None and (
            type(event["buffer_length"]) is not int or event["buffer_length"] < 0
        ):
            raise ContractError(f"{label} has invalid buffer_length")
        event_claims = _require_string_list(event.get("claim_ids"), f"{label} claim_ids")
        if any(not CLAIM_ID_RE.fullmatch(value) for value in event_claims) or not set(event_claims).issubset(
            bundle["claim_ids"]
        ):
            raise ContractError(f"{label} claims are invalid or outside its bundle")
    if sort_keys != sorted(sort_keys):
        raise ContractError(f"normalized events are not deterministically ordered in {path.as_posix()}")
    return events


def resolve_evidence_bundle(root: Path, bundle_id: str) -> Path:
    if not EVIDENCE_ID_RE.fullmatch(bundle_id):
        raise ContractError(f"invalid evidence bundle ID: {bundle_id!r}")
    candidates = [
        root / RESEARCH_REL / category / "evidence" / bundle_id / "manifest.json"
        for category in ("static", "dynamic", "reproduction")
    ]
    observed = [path for path in candidates if path.is_file()]
    if not observed:
        raise ContractError(f"evidence bundle not found for ID {bundle_id}")
    if len(observed) != 1:
        raise ContractError(f"evidence bundle ID {bundle_id} resolves ambiguously: {[path.as_posix() for path in observed]}")
    return observed[0]


def validate_evidence_bundle(
    root: Path,
    bundle_id: str,
    *,
    resolve_claims: bool = True,
) -> tuple[Path, Mapping[str, Any]]:
    path = resolve_evidence_bundle(root, bundle_id)
    data = _load_json(path)
    required = {
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
    _require_exact_keys(data, required, f"evidence bundle {bundle_id}")
    if data.get("schema_version") != 1 or data.get("bundle_id") != bundle_id:
        raise ContractError(f"evidence bundle identity mismatch: {bundle_id}")
    if data.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError(f"evidence bundle {bundle_id} uses the wrong artifact set")
    _require_string_list(data.get("claim_ids"), f"evidence bundle {bundle_id} claim_ids")
    if any(not CLAIM_ID_RE.fullmatch(value) for value in data["claim_ids"]):
        raise ContractError(f"evidence bundle {bundle_id} contains an invalid claim ID")
    _require_timestamp(data.get("captured_at"), f"evidence bundle {bundle_id} captured_at")
    for field in ("experiment_id", "operator"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise ContractError(f"evidence bundle {bundle_id} {field} is missing")
    source_variant = data.get("source_variant")
    tier = data.get("evidence_tier")
    if source_variant not in SOURCE_VARIANTS or tier not in EVIDENCE_TIERS:
        raise ContractError(f"evidence bundle {bundle_id} has invalid source variant/tier")
    if resolve_claims:
        for claim_id in data["claim_ids"]:
            validate_claim_record(
                root,
                claim_id,
                supporting_bundle_id=bundle_id,
                supporting_tier=str(tier),
            )

    delta = data.get("instrumentation_delta")
    delta_keys = {"summary", "hooks", "patches", "root_modules", "debugger", "proxies", "usb_capture_point"}
    if not isinstance(delta, dict):
        raise ContractError(f"evidence bundle {bundle_id} instrumentation_delta is missing")
    _require_exact_keys(delta, delta_keys, f"evidence bundle {bundle_id} instrumentation_delta")
    for field in ("hooks", "patches", "root_modules", "debugger", "proxies"):
        _require_string_list(delta.get(field), f"evidence bundle {bundle_id} instrumentation_delta.{field}", nonempty=False)
    if not isinstance(delta.get("summary"), str) or not delta["summary"]:
        raise ContractError(f"evidence bundle {bundle_id} instrumentation summary is missing")
    if delta.get("usb_capture_point") is not None and (
        not isinstance(delta["usb_capture_point"], str) or not delta["usb_capture_point"]
    ):
        raise ContractError(f"evidence bundle {bundle_id} USB capture point is invalid")
    mutation_items = sum((list(delta[field]) for field in ("hooks", "patches", "root_modules", "debugger", "proxies")), [])
    if source_variant == "untouched" and (mutation_items or delta.get("usb_capture_point") is not None):
        raise ContractError(f"untouched evidence bundle {bundle_id} declares instrumentation")
    if source_variant in {"root-attached", "patched-gadget"} and not mutation_items and delta.get("usb_capture_point") is None:
        raise ContractError(f"instrumented evidence bundle {bundle_id} has no concrete instrumentation delta")

    clock = data.get("clock")
    environment = data.get("environment")
    event_stream = data.get("event_stream")
    if (
        not isinstance(clock, dict)
        or set(clock) != {"basis", "offsets_and_drift_attachment"}
        or not isinstance(clock.get("basis"), str)
        or not clock["basis"]
        or (
            clock.get("offsets_and_drift_attachment") is not None
            and (not isinstance(clock["offsets_and_drift_attachment"], str) or not clock["offsets_and_drift_attachment"])
        )
    ):
        raise ContractError(f"evidence bundle {bundle_id} clock contract is incomplete")
    expected_environment = {"device_fingerprint", "camera_fingerprint", "os_build", "abi", "data_state_snapshot"}
    if (
        not isinstance(environment, dict)
        or set(environment) != expected_environment
        or not isinstance(environment.get("data_state_snapshot"), str)
        or not environment["data_state_snapshot"]
        or any(value is not None and not isinstance(value, str) for key, value in environment.items() if key != "data_state_snapshot")
    ):
        raise ContractError(f"evidence bundle {bundle_id} environment contract is incomplete")
    if tier in {"E2", "E3"} and source_variant in {
        "untouched",
        "root-attached",
        "patched-gadget",
        "reimplementation",
    }:
        for field in ("device_fingerprint", "os_build", "abi"):
            if not environment.get(field):
                raise ContractError(f"evidence bundle {bundle_id} lacks live environment field {field}")
    if (
        not isinstance(data.get("tool_versions"), dict)
        or not data["tool_versions"]
        or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value for key, value in data["tool_versions"].items())
    ):
        raise ContractError(f"evidence bundle {bundle_id} tool versions are missing")
    _require_string_list(data.get("replay_commands"), f"evidence bundle {bundle_id} replay_commands")

    stream_keys = {
        "schema_id",
        "normalized_attachment",
        "emitted_events",
        "captured_events",
        "dropped_events",
        "truncated_events",
    }
    if not isinstance(event_stream, dict):
        raise ContractError(f"evidence bundle {bundle_id} event stream is missing")
    _require_exact_keys(event_stream, stream_keys, f"evidence bundle {bundle_id} event_stream")
    for field in ("schema_id", "normalized_attachment"):
        if not isinstance(event_stream.get(field), str) or not event_stream[field]:
            raise ContractError(f"evidence bundle {bundle_id} event stream {field} is missing")
    for field in ("emitted_events", "captured_events", "dropped_events", "truncated_events"):
        if type(event_stream.get(field)) is not int or event_stream[field] < 0:
            raise ContractError(f"evidence bundle {bundle_id} event count {field} is invalid")
    if event_stream["captured_events"] + event_stream["dropped_events"] != event_stream["emitted_events"]:
        raise ContractError(f"evidence bundle {bundle_id} event loss counters are inconsistent")
    if tier in {"E2", "E3", "E4", "E5"} and event_stream["captured_events"] == 0:
        raise ContractError(f"dynamic/reproduction evidence bundle {bundle_id} captured no events")
    if tier == "E5" and (event_stream["dropped_events"] != 0 or event_stream["truncated_events"] != 0):
        raise ContractError(f"E5 evidence bundle {bundle_id} has dropped/truncated events")

    attachments = data.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        raise ContractError(f"evidence bundle {bundle_id} attachments are missing")
    attachment_paths: set[str] = set()
    bundle_root = path.parent.resolve()
    for index, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            raise ContractError(f"evidence bundle {bundle_id} attachment {index} is invalid")
        _require_exact_keys(attachment, {"path", "sha256", "size_bytes", "media_type"}, f"evidence bundle {bundle_id} attachment")
        relative = attachment.get("path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ContractError(f"evidence bundle {bundle_id} attachment path is unsafe")
        if relative in attachment_paths:
            raise ContractError(f"evidence bundle {bundle_id} attachment path is duplicated: {relative}")
        attachment_paths.add(relative)
        attachment_path = (bundle_root / relative).resolve()
        if bundle_root not in attachment_path.parents:
            raise ContractError(f"evidence bundle {bundle_id} attachment escapes its bundle")
        if not attachment_path.is_file():
            raise ContractError(f"evidence bundle {bundle_id} attachment is missing: {relative}")
        if not SHA256_RE.fullmatch(str(attachment.get("sha256", ""))):
            raise ContractError(f"evidence bundle {bundle_id} attachment hash is invalid: {relative}")
        if type(attachment.get("size_bytes")) is not int or attachment["size_bytes"] < 0:
            raise ContractError(f"evidence bundle {bundle_id} attachment size is invalid: {relative}")
        if not isinstance(attachment.get("media_type"), str) or not attachment["media_type"]:
            raise ContractError(f"evidence bundle {bundle_id} attachment media type is missing: {relative}")
        if attachment_path.stat().st_size != attachment.get("size_bytes") or _sha256_file(attachment_path) != attachment["sha256"]:
            raise ContractError(f"evidence bundle {bundle_id} attachment changed: {relative}")
    if event_stream.get("normalized_attachment") not in attachment_paths:
        raise ContractError(f"evidence bundle {bundle_id} normalized event attachment is not hash-listed")
    if environment.get("data_state_snapshot") not in attachment_paths:
        raise ContractError(f"evidence bundle {bundle_id} data-state snapshot is not hash-listed")
    clock_attachment = clock.get("offsets_and_drift_attachment")
    if clock_attachment is not None and clock_attachment not in attachment_paths:
        raise ContractError(f"evidence bundle {bundle_id} clock attachment is not hash-listed")
    normalized_path = bundle_root / str(event_stream["normalized_attachment"])
    parsed_events = _validate_normalized_event_document(normalized_path, bundle=data)
    if event_stream["captured_events"] != len(parsed_events):
        raise ContractError(
            f"evidence bundle {bundle_id} captured_events is not derived from its normalized event attachment"
        )

    declared_manifest_hash = data.get("manifest_sha256")
    canonical = dict(data)
    canonical.pop("manifest_sha256", None)
    actual_manifest_hash = _sha256_bytes(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    if declared_manifest_hash != actual_manifest_hash:
        raise ContractError(f"evidence bundle {bundle_id} canonical manifest hash mismatch")
    return path, data


def resolve_evidence_attachment(
    root: Path,
    bundle_id: str,
    attachment_path: str,
    *,
    media_type: str | None = None,
) -> tuple[Path, Mapping[str, Any], Mapping[str, Any]]:
    """Resolve a hash-listed evidence attachment without trusting its name."""

    manifest_path, bundle = validate_evidence_bundle(root, bundle_id)
    matches = [
        item
        for item in bundle["attachments"]
        if isinstance(item, dict) and item.get("path") == attachment_path
    ]
    if len(matches) != 1:
        raise ContractError(
            f"evidence bundle {bundle_id} does not uniquely hash-list attachment {attachment_path!r}"
        )
    attachment = matches[0]
    if media_type is not None and attachment.get("media_type") != media_type:
        raise ContractError(
            f"evidence bundle {bundle_id} attachment {attachment_path!r} has the wrong media type"
        )
    path = (manifest_path.parent / attachment_path).resolve()
    if manifest_path.parent.resolve() not in path.parents:
        raise ContractError(f"evidence attachment escapes bundle root: {bundle_id}:{attachment_path}")
    return path, attachment, bundle


def validate_run_manifest(
    root: Path,
    raw_path: str,
    *,
    expected_run_id: str | None = None,
    require_completed: bool = True,
    resolve_pair: bool = True,
) -> tuple[Path, Mapping[str, Any]]:
    path = _resolve_local_path(root, raw_path, "run manifest", allowed_root=RESEARCH_REL / "dynamic")
    data = _load_json(path)
    required = {
        "schema_version",
        "run_id",
        "experiment_id",
        "operator",
        "status",
        "source_variant",
        "artifact_set_id",
        "baseline_id",
        "environment",
        "data_state_snapshot",
        "clock",
        "instrumentation_delta",
        "tool_versions",
        "commands",
        "planned_observations",
        "output_root",
        "paired_comparison",
        "safety",
        "started_at",
        "ended_at",
    }
    _require_exact_keys(data, required, f"run manifest {_relative(path, root)}")
    run_id = data.get("run_id")
    if data.get("schema_version") != 1 or not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ContractError(f"run manifest {_relative(path, root)} has invalid identity")
    if expected_run_id is not None and run_id != expected_run_id:
        raise ContractError(f"run manifest identity mismatch: expected {expected_run_id}, got {run_id}")
    canonical_path = root / RESEARCH_REL / "dynamic/runs" / str(run_id) / "manifest.json"
    if path.resolve() != canonical_path.resolve():
        raise ContractError(f"run manifest {run_id} is not at its canonical run-ID path")
    if data.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError(f"run manifest {run_id} uses the wrong artifact set")
    for field in ("experiment_id", "operator"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise ContractError(f"run manifest {run_id} lacks {field}")
    if data.get("source_variant") not in SOURCE_VARIANTS:
        raise ContractError(f"run manifest {run_id} has an invalid source variant")
    if data.get("status") not in {"planned", "completed", "aborted", "failed"}:
        raise ContractError(f"run manifest {run_id} has an invalid status")
    if require_completed and data.get("status") != "completed":
        raise ContractError(f"run manifest {run_id} is not completed")

    environment = data.get("environment")
    environment_keys = {"device_fingerprint", "camera_fingerprint", "os_build", "abi", "network_profile"}
    if not isinstance(environment, dict):
        raise ContractError(f"run manifest {run_id} environment is missing")
    _require_exact_keys(environment, environment_keys, f"run manifest {run_id} environment")
    if not isinstance(environment.get("network_profile"), str) or not environment["network_profile"]:
        raise ContractError(f"run manifest {run_id} network profile is missing")
    if data["source_variant"] != "emulated":
        for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi"):
            if not isinstance(environment.get(field), str) or not environment[field]:
                raise ContractError(f"run manifest {run_id} live environment lacks {field}")

    clock = data.get("clock")
    if not isinstance(clock, dict):
        raise ContractError(f"run manifest {run_id} clock is missing")
    _require_exact_keys(clock, {"basis", "synchronization_plan"}, f"run manifest {run_id} clock")
    if any(not isinstance(clock.get(field), str) or not clock[field] for field in clock):
        raise ContractError(f"run manifest {run_id} clock is incomplete")

    baseline = _load_json(root / RESEARCH_REL / "governance/current-implementation-baseline.json")
    if data.get("baseline_id") != baseline.get("baseline_id"):
        raise ContractError(f"run manifest {run_id} does not resolve to the frozen implementation baseline")

    delta = data.get("instrumentation_delta")
    if not isinstance(delta, dict):
        raise ContractError(f"run manifest {run_id} instrumentation delta is missing")
    delta_keys = {
        "hooks",
        "patches",
        "root_modules",
        "debugger",
        "proxies",
        "usb_capture_point",
        "expected_perturbation",
        "paired_untouched_run_id",
    }
    _require_exact_keys(delta, delta_keys, f"run manifest {run_id} instrumentation delta")
    delta_items: list[str] = []
    for field in ("hooks", "patches", "root_modules", "debugger", "proxies"):
        delta_items.extend(
            _require_string_list(delta.get(field), f"run manifest {run_id} instrumentation {field}", nonempty=False)
        )
    if delta.get("usb_capture_point") is not None:
        if not isinstance(delta["usb_capture_point"], str) or not delta["usb_capture_point"]:
            raise ContractError(f"run manifest {run_id} instrumentation USB capture point is invalid")
        delta_items.append(delta["usb_capture_point"])
    if not isinstance(delta.get("expected_perturbation"), str) or not delta["expected_perturbation"]:
        raise ContractError(f"run manifest {run_id} expected perturbation is missing")
    if data["source_variant"] == "untouched":
        if delta_items or delta.get("paired_untouched_run_id") is not None or data.get("paired_comparison") is not None:
            raise ContractError(f"untouched run manifest {run_id} declares instrumentation")
    elif data["source_variant"] in {"root-attached", "patched-gadget"}:
        if (
            not delta_items
            or not isinstance(delta.get("paired_untouched_run_id"), str)
            or not delta["paired_untouched_run_id"]
            or not isinstance(data.get("paired_comparison"), dict)
        ):
            raise ContractError(f"instrumented run manifest {run_id} lacks delta or paired untouched run")
    elif data.get("paired_comparison") is not None:
        raise ContractError(f"non-instrumented run manifest {run_id} declares a paired comparison")

    tool_versions = data.get("tool_versions")
    if not isinstance(tool_versions, dict) or not tool_versions or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in tool_versions.items()
    ):
        raise ContractError(f"run manifest {run_id} tool versions are missing")
    _require_string_list(data.get("commands"), f"run manifest {run_id} commands")
    _require_string_list(data.get("planned_observations"), f"run manifest {run_id} planned observations")

    output_root = _resolve_local_path(
        root,
        data.get("output_root"),
        f"run manifest {run_id} output root",
        allowed_root=RESEARCH_REL / "dynamic",
        must_exist=False,
    )
    if require_completed and not output_root.is_dir():
        raise ContractError(f"run manifest {run_id} output root is missing")
    snapshot = data.get("data_state_snapshot")
    if not isinstance(snapshot, dict):
        raise ContractError(f"run manifest {run_id} data-state snapshot hash row is missing")
    snapshot_path = _resolve_hash_row(
        root,
        snapshot,
        f"run manifest {run_id} data-state snapshot",
        allowed_root=RESEARCH_REL / "dynamic",
    )
    if snapshot_path != output_root and output_root not in snapshot_path.parents:
        raise ContractError(f"run manifest {run_id} data-state snapshot is outside its output root")
    safety = data.get("safety")
    if not isinstance(safety, dict):
        raise ContractError(f"run manifest {run_id} safety contract is missing")
    _require_exact_keys(safety, {"destructive_actions", "external_production_actions", "rollback"}, f"run manifest {run_id} safety")
    for field in ("destructive_actions", "external_production_actions"):
        if safety.get(field) != []:
            raise ContractError(f"run manifest {run_id} includes unauthorized {field}")
    if not isinstance(safety.get("rollback"), str) or not safety["rollback"]:
        raise ContractError(f"run manifest {run_id} rollback is missing")

    started = data.get("started_at")
    ended = data.get("ended_at")
    if require_completed and (started is None or ended is None):
        raise ContractError(f"completed run manifest {run_id} lacks start/end timestamps")
    if started is not None:
        _require_timestamp(started, f"run manifest {run_id} started_at")
    if ended is not None:
        _require_timestamp(ended, f"run manifest {run_id} ended_at")
    if started is not None and ended is not None:
        start_time = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
        if end_time < start_time:
            raise ContractError(f"run manifest {run_id} ends before it starts")
    if data["source_variant"] in {"root-attached", "patched-gadget"} and resolve_pair:
        paired_id = str(delta["paired_untouched_run_id"])
        paired_path = root / RESEARCH_REL / "dynamic/runs" / paired_id / "manifest.json"
        if not paired_path.is_file():
            raise ContractError(f"paired untouched run manifest is missing: {paired_id}")
        _, paired = validate_run_manifest(
            root,
            _relative(paired_path, root),
            expected_run_id=paired_id,
            require_completed=True,
            resolve_pair=False,
        )
        if (
            paired.get("source_variant") != "untouched"
            or paired.get("artifact_set_id") != data.get("artifact_set_id")
            or paired.get("baseline_id") != data.get("baseline_id")
            or paired.get("environment") != data.get("environment")
            or paired.get("data_state_snapshot", {}).get("sha256") != snapshot.get("sha256")
        ):
            raise ContractError(f"run manifest {run_id} paired untouched run is not environment/state compatible")
        if datetime.fromisoformat(str(paired["ended_at"]).replace("Z", "+00:00")) > datetime.fromisoformat(
            str(data["started_at"]).replace("Z", "+00:00")
        ):
            raise ContractError(f"run manifest {run_id} paired untouched run is not temporally prior")
        comparison_path = _resolve_hash_row(
            root,
            data["paired_comparison"],
            f"run manifest {run_id} paired comparison",
            allowed_root=RESEARCH_REL / "dynamic",
        )
        if comparison_path != output_root and output_root not in comparison_path.parents:
            raise ContractError(f"run manifest {run_id} paired comparison is outside its output root")
        comparison = _load_json(comparison_path)
        comparison_keys = {
            "schema_version",
            "comparison_id",
            "artifact_set_id",
            "untouched_run_id",
            "instrumented_run_id",
            "compared_event_dimensions",
            "untouched_event_refs",
            "instrumented_event_refs",
            "pre_target_divergence_ids",
            "canonical_sha256",
        }
        _require_exact_keys(comparison, comparison_keys, f"run manifest {run_id} paired comparison")
        canonical_comparison = dict(comparison)
        canonical_comparison.pop("canonical_sha256", None)
        if (
            comparison.get("schema_version") != 1
            or not isinstance(comparison.get("comparison_id"), str)
            or not comparison["comparison_id"]
            or comparison.get("artifact_set_id") != data["artifact_set_id"]
            or comparison.get("untouched_run_id") != paired_id
            or comparison.get("instrumented_run_id") != run_id
            or comparison.get("pre_target_divergence_ids") != []
            or comparison.get("canonical_sha256")
            != _sha256_bytes(
                json.dumps(canonical_comparison, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
        ):
            raise ContractError(f"run manifest {run_id} paired comparison is invalid or divergent")
        compared_dimensions = set(
            _require_string_list(
                comparison.get("compared_event_dimensions"),
                f"run manifest {run_id} paired comparison dimensions",
            )
        )
        event_groups: dict[str, list[Mapping[str, Any]]] = {}
        for lane, expected_run, expected_variant, expected_tier in (
            ("untouched_event_refs", paired, "untouched", "E2"),
            ("instrumented_event_refs", data, data["source_variant"], "E3"),
        ):
            refs = comparison.get(lane)
            if not isinstance(refs, list) or not refs:
                raise ContractError(f"run manifest {run_id} paired comparison lacks {lane}")
            lane_events: list[Mapping[str, Any]] = []
            lane_bundles: set[str] = set()
            for ref_index, event_ref in enumerate(refs):
                bundle_id, bundle, events = _resolve_normalized_event_reference(
                    root,
                    event_ref,
                    label=f"run manifest {run_id} paired comparison {lane} {ref_index}",
                )
                if (
                    bundle.get("evidence_tier") != expected_tier
                    or bundle.get("source_variant") != expected_variant
                    or bundle["event_stream"]["dropped_events"] != 0
                    or bundle["event_stream"]["truncated_events"] != 0
                ):
                    raise ContractError(f"run manifest {run_id} paired comparison {lane} has incompatible evidence")
                _validate_evidence_run_binding(
                    root,
                    bundle_id,
                    bundle,
                    expected_run,
                    label=f"run manifest {run_id} paired comparison {lane}",
                    events=events,
                )
                lane_bundles.add(bundle_id)
                lane_events.extend(events)
            if not lane_bundles or not lane_events:
                raise ContractError(f"run manifest {run_id} paired comparison {lane} is empty")
            event_groups[lane] = lane_events
        untouched_events = event_groups["untouched_event_refs"]
        instrumented_events = event_groups["instrumented_event_refs"]
        derived_dimensions = {str(event["event_type"]) for event in untouched_events}.intersection(
            str(event["event_type"]) for event in instrumented_events
        )
        if compared_dimensions != derived_dimensions:
            raise ContractError(f"run manifest {run_id} paired comparison dimensions are not derived from events")
        untouched_correlations = {str(event["correlation_id"]) for event in untouched_events}
        instrumented_correlations = {str(event["correlation_id"]) for event in instrumented_events}
        if not untouched_correlations.intersection(instrumented_correlations):
            raise ContractError(f"run manifest {run_id} paired comparison events are not correlated")
        def comparison_projection(events: Sequence[Mapping[str, Any]]) -> list[tuple[str, Any, Any]]:
            return sorted(
                (
                    str(event["event_type"]),
                    json.dumps(event.get("value"), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    event.get("error_state"),
                )
                for event in events
                if str(event["event_type"]) in compared_dimensions
            )
        if comparison_projection(untouched_events) != comparison_projection(instrumented_events):
            raise ContractError(f"run manifest {run_id} paired comparison has derived pre-target divergences")
    return path, data


def _validate_evidence_run_binding(
    root: Path,
    bundle_id: str,
    bundle: Mapping[str, Any],
    run: Mapping[str, Any],
    *,
    label: str,
    events: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Bind evidence to its declared run, state, instrumentation, and interval."""

    if (
        bundle.get("experiment_id") != run.get("experiment_id")
        or bundle.get("operator") != run.get("operator")
        or bundle.get("source_variant") != run.get("source_variant")
    ):
        raise ContractError(f"{label} evidence does not belong to its declared run")
    for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi"):
        if bundle["environment"].get(field) != run["environment"].get(field):
            raise ContractError(f"{label} evidence environment mismatch for {field}")
    snapshot_path = str(bundle["environment"].get("data_state_snapshot"))
    _, snapshot_attachment, _ = resolve_evidence_attachment(root, bundle_id, snapshot_path)
    if snapshot_attachment.get("sha256") != run["data_state_snapshot"].get("sha256"):
        raise ContractError(f"{label} evidence data-state snapshot differs from its run")
    evidence_delta = bundle["instrumentation_delta"]
    run_delta = run["instrumentation_delta"]
    delta_fields = ("hooks", "patches", "root_modules", "debugger", "proxies", "usb_capture_point")
    if any(evidence_delta.get(field) != run_delta.get(field) for field in delta_fields):
        raise ContractError(f"{label} evidence instrumentation delta differs from its run")
    captured_at = datetime.fromisoformat(str(bundle["captured_at"]).replace("Z", "+00:00"))
    started_at = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
    ended_at = datetime.fromisoformat(str(run["ended_at"]).replace("Z", "+00:00"))
    if not started_at <= captured_at <= ended_at:
        raise ContractError(f"{label} evidence timestamp falls outside its run")
    run_id = str(run["run_id"])
    if any(event.get("run_id") != run_id for event in events):
        raise ContractError(f"{label} normalized events are not bound to run {run_id}")


def resolve_review(root: Path, review_id: str) -> Path:
    if not REVIEW_ID_RE.fullmatch(review_id):
        raise ContractError(f"invalid review ID: {review_id!r}")
    review_root = root / RESEARCH_REL / "reviews"
    observed: list[Path] = []
    for path in sorted(review_root.glob("*.json"), key=lambda item: item.as_posix()):
        try:
            data = _load_json(path)
        except ContractError:
            continue
        if data.get("review_id") == review_id:
            observed.append(path)
    if not observed:
        raise ContractError(f"review not found for ID {review_id}")
    if len(observed) != 1:
        raise ContractError(f"review ID {review_id} resolves ambiguously: {[path.as_posix() for path in observed]}")
    return observed[0]


def validate_review(
    root: Path,
    review_id: str,
    *,
    subject_id: str | None = None,
    expected_subject_ids: Sequence[str] = (),
    expected_bundle_ids: Sequence[str] = (),
    producer_ids: Sequence[str] = (),
    not_before: Sequence[tuple[str, str]] = (),
    resolve_claims: bool = True,
) -> tuple[Path, Mapping[str, Any]]:
    path = resolve_review(root, review_id)
    data = _load_json(path)
    required = {
        "schema_version",
        "review_id",
        "reviewer_id",
        "reviewer_role",
        "independent_from_producers",
        "verdict",
        "passed",
        "subject_ids",
        "evidence_bundle_ids",
        "reviewed_at",
    }
    _require_exact_keys(data, required, f"review {review_id}")
    if data.get("schema_version") != 1 or data.get("review_id") != review_id:
        raise ContractError(f"review identity mismatch: {review_id}")
    if data.get("independent_from_producers") is not True or data.get("passed") is not True:
        raise ContractError(f"review {review_id} is not an independent passing review")
    if str(data.get("verdict", "")).lower() not in {"pass", "approve", "clear"}:
        raise ContractError(f"review {review_id} has a non-passing verdict")
    if not isinstance(data.get("reviewer_id"), str) or not data["reviewer_id"] or not isinstance(data.get("reviewer_role"), str) or not data["reviewer_role"]:
        raise ContractError(f"review {review_id} lacks reviewer identity/role")
    subjects = _require_string_list(data.get("subject_ids"), f"review {review_id} subject_ids")
    if subject_id is not None and subject_id not in subjects:
        raise ContractError(f"review {review_id} does not cover subject {subject_id}")
    if not set(expected_subject_ids).issubset(subjects):
        missing = sorted(set(expected_subject_ids) - set(subjects))
        raise ContractError(f"review {review_id} does not cover required subjects: {missing}")
    review_bundle_ids = _require_string_list(data.get("evidence_bundle_ids"), f"review {review_id} evidence_bundle_ids")
    if not set(expected_bundle_ids).issubset(review_bundle_ids):
        missing = sorted(set(expected_bundle_ids) - set(review_bundle_ids))
        raise ContractError(f"review {review_id} does not cover required evidence bundles: {missing}")
    bundle_operators: set[str] = set()
    bundle_captured_at: list[datetime] = []
    for bundle_id in review_bundle_ids:
        _, bundle = validate_evidence_bundle(root, bundle_id, resolve_claims=resolve_claims)
        bundle_operators.add(str(bundle["operator"]).casefold())
        bundle_captured_at.append(datetime.fromisoformat(str(bundle["captured_at"]).replace("Z", "+00:00")))
    reviewer_id = str(data["reviewer_id"]).casefold()
    disallowed_reviewers = bundle_operators | {str(value).casefold() for value in producer_ids if value}
    if reviewer_id in disallowed_reviewers:
        raise ContractError(f"review {review_id} is producer self-review, not independent")
    reviewed_at = _require_timestamp(data.get("reviewed_at"), f"review {review_id} reviewed_at")
    reviewed_time = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    if any(reviewed_time <= captured_at for captured_at in bundle_captured_at):
        raise ContractError(f"review {review_id} does not strictly postdate evidence it claims to review")
    for chronology_label, timestamp in not_before:
        floor = datetime.fromisoformat(
            _require_timestamp(timestamp, f"review {review_id} {chronology_label}").replace("Z", "+00:00")
        )
        if reviewed_time <= floor:
            raise ContractError(f"review {review_id} does not strictly postdate {chronology_label}")
    return path, data


def validate_ledger_history(
    row: Mapping[str, Any],
    *,
    resolve_references: Callable[[str], Mapping[str, Any]] | None = None,
) -> None:
    row_id = str(row.get("row_id", "<unknown>"))
    history = row.get("history")
    if not isinstance(history, list) or not history:
        raise ContractError(f"ledger row {row_id} history is empty")
    current: str | None = None
    blocked_resume_state: str | None = None
    saw_reopen = False
    latest_reopen_reason: str | None = None
    prior_at: datetime | None = None
    evidence_floor: datetime | None = None
    for index, event in enumerate(history):
        if not isinstance(event, dict):
            raise ContractError(f"ledger row {row_id} history event {index} is not an object")
        required = {"at", "from_state", "to_state", "reason", "evidence_bundle_ids", "transition_kind"}
        _require_exact_keys(event, required, f"ledger row {row_id} history event {index}")
        transition = event.get("transition_kind")
        from_state = event.get("from_state")
        to_state = event.get("to_state")
        reason = event.get("reason")
        if transition not in TRANSITION_KINDS or to_state not in LEDGER_STATES or (from_state is not None and from_state not in LEDGER_STATES):
            raise ContractError(f"ledger row {row_id} history event {index} has an invalid transition/state")
        if from_state != current:
            raise ContractError(f"ledger row {row_id} history event {index} does not continue from the prior state")
        if not isinstance(reason, str) or not reason:
            raise ContractError(f"ledger row {row_id} history event {index} lacks a reason")
        at = _require_timestamp(event.get("at"), f"ledger row {row_id} history event {index} at")
        at_time = datetime.fromisoformat(at.replace("Z", "+00:00"))
        previous_at = prior_at
        if previous_at is not None and at_time < previous_at:
            raise ContractError(f"ledger row {row_id} history timestamps are not monotonic")
        prior_at = at_time
        bundle_ids = _require_string_list(
            event.get("evidence_bundle_ids"),
            f"ledger row {row_id} history event {index} evidence_bundle_ids",
            nonempty=transition != "initialize",
        )
        if any(not EVIDENCE_ID_RE.fullmatch(bundle_id) for bundle_id in bundle_ids):
            raise ContractError(f"ledger row {row_id} history event {index} contains an invalid evidence bundle ID")
        resolved_bundles = [resolve_references(bundle_id) for bundle_id in bundle_ids] if resolve_references is not None else []
        for bundle in resolved_bundles:
            captured = datetime.fromisoformat(str(bundle["captured_at"]).replace("Z", "+00:00"))
            if captured > at_time:
                raise ContractError(
                    f"ledger row {row_id} history event {index} cites evidence captured after its transition"
                )
            if transition in {"block", "reopen"} and previous_at is not None and captured < previous_at:
                raise ContractError(
                    f"ledger row {row_id} history event {index} cites evidence older than its block/reopen boundary"
                )
            if evidence_floor is not None and captured < evidence_floor:
                raise ContractError(
                    f"ledger row {row_id} history event {index} cites evidence stale across a block/reopen boundary"
                )
        if transition == "initialize":
            if index != 0 or from_state is not None or to_state != "unseen":
                raise ContractError(f"ledger row {row_id} must initialize exactly once at unseen")
            if bundle_ids:
                raise ContractError(f"ledger row {row_id} initialization cannot claim evidence")
        elif transition == "advance":
            if from_state not in FORWARD_STATES[:-1]:
                raise ContractError(f"ledger row {row_id} cannot advance from {from_state}")
            expected = FORWARD_STATES[FORWARD_STATES.index(str(from_state)) + 1]
            if to_state != expected:
                raise ContractError(f"ledger row {row_id} skipped prerequisite state: {from_state} -> {to_state}")
            if resolved_bundles:
                tiers = {str(bundle["evidence_tier"]) for bundle in resolved_bundles}
                required_tiers = {
                    "inventoried": {"E1"},
                    "static_mapped": {"E1"},
                    "dynamically_observed": {"E2", "E3"},
                    "specified": {"E2", "E3", "E4"},
                    "independently_reproduced": {"E4"},
                    "verified": {"E5"},
                }[str(to_state)]
                if tiers.isdisjoint(required_tiers):
                    raise ContractError(
                        f"ledger row {row_id} transition to {to_state} lacks required evidence tier {sorted(required_tiers)}"
                    )
        elif transition == "block":
            if from_state not in FORWARD_STATES[:-1] or to_state != "blocked":
                raise ContractError(f"ledger row {row_id} has invalid block transition {from_state} -> {to_state}")
            blocked_resume_state = str(from_state)
            evidence_floor = at_time
        elif transition == "resume":
            if from_state != "blocked" or blocked_resume_state is None or to_state != blocked_resume_state:
                raise ContractError(f"ledger row {row_id} must resume to the exact pre-block state")
            blocked_resume_state = None
        elif transition == "reopen":
            if from_state not in FORWARD_STATES or to_state not in FORWARD_STATES:
                raise ContractError(f"ledger row {row_id} has invalid reopen states")
            if FORWARD_STATES.index(str(to_state)) >= FORWARD_STATES.index(str(from_state)):
                raise ContractError(f"ledger row {row_id} reopen must move to an earlier prerequisite state")
            saw_reopen = True
            latest_reopen_reason = reason
            evidence_floor = at_time
        current = str(to_state)
    if current != row.get("state"):
        raise ContractError(f"ledger row {row_id} state does not match its last history event")
    reopen_reason = row.get("reopen_reason")
    if saw_reopen and (not isinstance(reopen_reason, str) or not reopen_reason):
        raise ContractError(f"ledger row {row_id} reopened without a row-level reopen_reason")
    if saw_reopen and reopen_reason != latest_reopen_reason:
        raise ContractError(f"ledger row {row_id} reopen_reason does not match its latest reopen event")
    if not saw_reopen and reopen_reason is not None:
        raise ContractError(f"ledger row {row_id} has reopen_reason without a reopen transition")


def validate_ledger_document(
    root: Path,
    ledger: Mapping[str, Any],
    *,
    require_verified: bool,
    resolve_references: bool = True,
) -> list[Mapping[str, Any]]:
    _require_exact_keys(
        ledger,
        {"schema_version", "ledger_id", "artifact_set_id", "current_causal_frontier", "rows"},
        "whole-APK ledger",
    )
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("ledger_id"), str) or not ledger["ledger_id"]:
        raise ContractError("whole-APK ledger identity is invalid")
    if ledger.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("whole-APK ledger uses the wrong artifact set")
    rows = ledger.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ContractError("whole-APK ledger has no scope rows")
    required_row_keys = {
        "row_id",
        "scope_type",
        "scope_key",
        "dossier_id",
        "owner",
        "state",
        "classification_status",
        "claim_ids",
        "evidence_bundle_ids",
        "specification_ids",
        "reproduction_ids",
        "verification_ids",
        "independent_review_ids",
        "history",
        "reopen_reason",
        "blocker",
    }
    seen: set[str] = set()
    result: list[Mapping[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ContractError(f"ledger row {index} is not an object")
        _require_exact_keys(row, required_row_keys, f"ledger row {index}")
        row_id = row.get("row_id")
        if not isinstance(row_id, str) or not ROW_ID_RE.fullmatch(row_id) or row_id in seen:
            raise ContractError(f"ledger row {index} has invalid/duplicate row_id")
        seen.add(row_id)
        if not isinstance(row.get("owner"), str) or not row["owner"]:
            raise ContractError(f"ledger row {row_id} has no owner")
        if row.get("scope_type") not in SCOPE_TYPES or not isinstance(row.get("scope_key"), str) or not row["scope_key"]:
            raise ContractError(f"ledger row {row_id} has invalid scope_type/scope_key")
        if row.get("state") not in LEDGER_STATES or row.get("classification_status") not in CLASSIFICATION_STATES:
            raise ContractError(f"ledger row {row_id} has invalid state/classification")
        if not isinstance(row.get("dossier_id"), str) or not re.fullmatch(r"D(0[1-9]|1[0-3])", row["dossier_id"]):
            raise ContractError(f"ledger row {row_id} has invalid dossier_id")
        claims = _require_string_list(row.get("claim_ids"), f"ledger row {row_id} claim_ids", nonempty=False)
        if any(not CLAIM_ID_RE.fullmatch(value) for value in claims):
            raise ContractError(f"ledger row {row_id} has invalid claim IDs")
        evidence_ids = _require_string_list(row.get("evidence_bundle_ids"), f"ledger row {row_id} evidence_bundle_ids", nonempty=False)
        specification_ids = _require_string_list(row.get("specification_ids"), f"ledger row {row_id} specification_ids", nonempty=False)
        reproduction_ids = _require_string_list(row.get("reproduction_ids"), f"ledger row {row_id} reproduction_ids", nonempty=False)
        verification_ids = _require_string_list(row.get("verification_ids"), f"ledger row {row_id} verification_ids", nonempty=False)
        review_ids = _require_string_list(row.get("independent_review_ids"), f"ledger row {row_id} independent_review_ids", nonempty=False)
        if any(not EVIDENCE_ID_RE.fullmatch(value) for value in (*evidence_ids, *verification_ids)):
            raise ContractError(f"ledger row {row_id} has invalid evidence/verification bundle IDs")
        if any(not REVIEW_ID_RE.fullmatch(value) for value in review_ids):
            raise ContractError(f"ledger row {row_id} has invalid independent review IDs")
        if row.get("state") == "verified":
            if row.get("classification_status") != "classified":
                raise ContractError(f"verified ledger row {row_id} is unknown/unclassified")
            required_lists = (claims, evidence_ids, specification_ids, reproduction_ids, verification_ids, review_ids)
            if any(not values for values in required_lists):
                raise ContractError(f"verified ledger row {row_id} lacks claim/evidence/spec/reproduction/verification/review IDs")
            if row.get("blocker") is not None:
                raise ContractError(f"verified ledger row {row_id} still has a blocker")
        if row.get("state") == "blocked":
            blocker = row.get("blocker")
            if not isinstance(blocker, dict) or set(blocker) != {"reason", "attempted_evidence_ids", "next_experiment"}:
                raise ContractError(f"blocked ledger row {row_id} lacks the blocker contract")
            if not blocker.get("reason") or not blocker.get("next_experiment"):
                raise ContractError(f"blocked ledger row {row_id} has incomplete blocker details")
            attempted_ids = _require_string_list(
                blocker.get("attempted_evidence_ids"),
                f"blocked ledger row {row_id} attempted_evidence_ids",
            )
            if any(not EVIDENCE_ID_RE.fullmatch(value) for value in attempted_ids):
                raise ContractError(f"blocked ledger row {row_id} has invalid attempted evidence IDs")
            if resolve_references:
                for bundle_id in attempted_ids:
                    validate_evidence_bundle(root, bundle_id)
        elif row.get("blocker") is not None:
            raise ContractError(f"non-blocked ledger row {row_id} carries blocker details")

        def resolve_bundle_data(bundle_id: str) -> Mapping[str, Any]:
            return validate_evidence_bundle(root, bundle_id)[1]

        resolver = resolve_bundle_data if resolve_references else None
        validate_ledger_history(row, resolve_references=resolver)
        if row.get("state") == "blocked":
            last_event_ids = set(row["history"][-1]["evidence_bundle_ids"])
            if set(row["blocker"]["attempted_evidence_ids"]) != last_event_ids:
                raise ContractError(f"blocked ledger row {row_id} attempted evidence differs from its block transition")
        history_bundle_ids = {
            bundle_id
            for event in row["history"]
            for bundle_id in event["evidence_bundle_ids"]
        }
        if row.get("state") == "verified" and not history_bundle_ids.issubset({*evidence_ids, *verification_ids}):
            raise ContractError(f"verified ledger row {row_id} omits transition evidence from its evidence index")
        if resolve_references:
            resolved_bundle_data: dict[str, Mapping[str, Any]] = {}
            for bundle_id in (*evidence_ids, *verification_ids):
                resolved_bundle_data[bundle_id] = validate_evidence_bundle(root, bundle_id)[1]
            observed_claims = {
                claim_id
                for bundle in resolved_bundle_data.values()
                for claim_id in bundle["claim_ids"]
            }
            if not set(claims).issubset(observed_claims):
                raise ContractError(f"ledger row {row_id} claims are not backed by its evidence bundles")
            if row.get("state") == "verified" and any(
                resolved_bundle_data[bundle_id].get("evidence_tier") != "E5" for bundle_id in verification_ids
            ):
                raise ContractError(f"verified ledger row {row_id} verification IDs are not E5 bundles")
            terminal_transition_at = datetime.fromisoformat(
                str(row["history"][-1]["at"]).replace("Z", "+00:00")
            )
            for review_id in review_ids:
                _, review = validate_review(
                    root,
                    review_id,
                    subject_id=row_id,
                    expected_bundle_ids=(*evidence_ids, *verification_ids),
                    producer_ids=(str(row["owner"]),),
                )
                reviewed_at = datetime.fromisoformat(str(review["reviewed_at"]).replace("Z", "+00:00"))
                if reviewed_at < terminal_transition_at:
                    raise ContractError(f"ledger row {row_id} review {review_id} predates its terminal transition")
        if require_verified and row.get("state") != "verified":
            raise ContractError(f"whole-APK ledger row is nonterminal: {row_id}={row.get('state')}")
        result.append(row)

    if resolve_references and any(row["claim_ids"] for row in result):
        claims_by_id, unresolved_contradictions = validate_claim_graph(root)
        for row in result:
            if row.get("state") != "verified":
                continue
            row_claim_ids = set(str(value) for value in row["claim_ids"])
            relevant = row_claim_ids & unresolved_contradictions
            relevant.update(
                claim_id
                for claim_id in unresolved_contradictions
                if set(str(value) for value in claims_by_id[claim_id]["contradicts_claim_ids"])
                & row_claim_ids
            )
            if relevant:
                raise ContractError(
                    f"verified ledger row {row['row_id']} has unresolved contradiction claims: {sorted(relevant)}"
                )

    frontier = ledger.get("current_causal_frontier")
    if frontier is not None:
        if not isinstance(frontier, dict):
            raise ContractError("current_causal_frontier must be null or an object")
        required_frontier = {
            "frontier_id",
            "owner",
            "last_proven_checkpoint",
            "first_missing_checkpoint",
            "supporting_bundle_ids",
            "next_discriminating_experiment",
            "updated_by_run_id",
            "checkpoint_proof",
        }
        _require_exact_keys(frontier, required_frontier, "current_causal_frontier")
        if frontier.get("frontier_id") != "F2-first-frame" or not frontier.get("owner"):
            raise ContractError("current_causal_frontier identity/owner is invalid")
        frontier_bundles = _require_string_list(frontier.get("supporting_bundle_ids"), "current_causal_frontier supporting_bundle_ids")
        if resolve_references:
            for bundle_id in frontier_bundles:
                validate_evidence_bundle(root, bundle_id)
    return result


def _canonical_inventory_record(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the method-independent portion compared across inventory lanes."""

    return _normalize_nfc_json({key: value for key, value in record.items() if key != "source_refs"})


def _iter_json_objects(value: Any, pointer: str = "") -> Iterator[tuple[str, Mapping[str, Any]]]:
    if isinstance(value, Mapping):
        yield pointer, value
        for key, item in value.items():
            token = str(key).replace("~", "~0").replace("/", "~1")
            yield from _iter_json_objects(item, f"{pointer}/{token}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_json_objects(item, f"{pointer}/{index}")


def _load_raw_json_documents(
    manifest_path: Path,
    bundle: Mapping[str, Any],
    *,
    label: str,
) -> Mapping[str, Any]:
    documents: dict[str, Any] = {}
    for attachment in bundle["attachments"]:
        relative = str(attachment["path"])
        if not relative.startswith("raw/"):
            continue
        if not relative.endswith(".json") or attachment.get("media_type") != "application/json":
            raise ContractError(f"{label} raw attachment is not hash-listed JSON: {relative}")
        documents[relative] = _load_json_value(manifest_path.parent / relative)
    return documents


def _resolve_raw_source_object(
    raw_documents: Mapping[str, Any],
    locator: Any,
    label: str,
) -> Mapping[str, Any]:
    attachment_path, pointer = _split_raw_source_locator(locator, label)
    if attachment_path not in raw_documents:
        raise ContractError(f"{label} refers to a raw JSON attachment that is not hash-listed")
    resolved = _resolve_json_pointer(raw_documents[attachment_path], pointer, label)
    if not isinstance(resolved, Mapping):
        raise ContractError(f"{label} does not resolve to one JSON object")
    return resolved


def _raw_source_row_locators(raw_documents: Mapping[str, Any], label: str) -> set[str]:
    locators: set[str] = set()
    for attachment_path, document in raw_documents.items():
        for pointer, candidate in _iter_json_objects(document):
            if set(candidate) != INVENTORY_SOURCE_RECORD_KEYS:
                continue
            if not pointer:
                raise ContractError(f"{label} record-bearing raw object must be addressable below the document root")
            locator = f"{attachment_path}#{pointer}"
            if candidate.get("source_locator") != locator:
                raise ContractError(f"{label} record-bearing raw object has a locator that does not identify itself")
            locators.add(locator)
    return locators


def _local_python_dependency_sha256s(root: Path, script_path: Path, label: str) -> frozenset[str]:
    allowed_root = (root / "tools/hik_whole_apk").resolve()
    observed_paths: set[Path] = set()
    pending = [script_path.resolve()]
    while pending:
        current = pending.pop()
        if current in observed_paths:
            continue
        observed_paths.add(current)
        try:
            tree = ast.parse(current.read_text(encoding="utf-8"), filename=current.as_posix())
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ContractError(f"{label} producer script is not parseable Python: {exc}") from exc
        targets: set[Path] = set()
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = current.parent
                    for _ in range(node.level - 1):
                        base = base.parent
                    module_base = base / (node.module or "").replace(".", "/")
                    if node.module:
                        modules.append("@" + module_base.as_posix())
                    else:
                        modules.extend("@" + (module_base / alias.name).as_posix() for alias in node.names)
                elif node.module:
                    modules.append(node.module)
                    if node.module == "tools.hik_whole_apk":
                        modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
            for module in modules:
                if module.startswith("@"):
                    candidate = Path(module[1:]).with_suffix(".py").resolve()
                elif module.startswith("tools.hik_whole_apk."):
                    candidate = (root / (module.replace(".", "/") + ".py")).resolve()
                else:
                    module_paths = (
                        root / module.replace(".", "/"),
                        current.parent / module.replace(".", "/"),
                    )
                    candidates = [
                        possible.resolve()
                        for module_path in module_paths
                        for possible in (module_path.with_suffix(".py"), module_path / "__init__.py")
                        if possible.is_file()
                    ]
                    if not candidates:
                        continue
                    candidate = candidates[0]
                if candidate.is_file() and candidate != script_path.resolve():
                    if candidate != allowed_root and allowed_root not in candidate.parents:
                        raise ContractError(f"{label} imports Python outside its producer implementation root")
                    if candidate.name != "__init__.py":
                        targets.add(candidate)
        pending.extend(sorted(targets, key=lambda item: item.as_posix(), reverse=True))
    observed_paths.discard(script_path.resolve())
    return frozenset(_sha256_file(path) for path in observed_paths if path.name != "__init__.py")


def _validate_producer_script(
    root: Path,
    method: Mapping[str, Any],
    *,
    label: str,
) -> tuple[str, str, str, frozenset[str]]:
    script_path = _resolve_hash_row(
        root,
        method.get("producer_script"),
        f"{label} producer_script",
        allowed_root=Path("tools/hik_whole_apk"),
    )
    if script_path.suffix != ".py" or script_path.name in {"critic.py", "compare_inventories.py"}:
        raise ContractError(f"{label} producer_script is not a dedicated Python producer")
    invoked = False
    for index, command in enumerate(method["commands"]):
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            raise ContractError(f"{label} method command {index} is invalid shell syntax") from exc
        for token in argv:
            candidate = Path(token)
            if candidate.suffix != ".py":
                continue
            resolved = candidate.expanduser().resolve() if candidate.is_absolute() else (root / candidate).resolve()
            if resolved == script_path.resolve():
                invoked = True
    if not invoked:
        raise ContractError(f"{label} commands never invoke the hash-listed producer script")
    source = script_path.read_text(encoding="utf-8")
    dependencies = _local_python_dependency_sha256s(root, script_path, label)
    return _relative(script_path, root), _sha256_file(script_path), source, dependencies


def _validate_inventory_source_index(
    root: Path,
    reference: Mapping[str, Any],
    *,
    expected_run_id: str,
    expected_method_id: str,
    allowed_bundle_ids: set[str],
    raw_documents_by_bundle: Mapping[str, Mapping[str, Any]],
    label: str,
) -> tuple[tuple[str, str], Mapping[str, Mapping[str, Any]]]:
    _require_exact_keys(reference, {"bundle_id", "path", "sha256", "size_bytes"}, label)
    bundle_id = reference.get("bundle_id")
    attachment_path = reference.get("path")
    if bundle_id not in allowed_bundle_ids or not isinstance(attachment_path, str) or not attachment_path:
        raise ContractError(f"{label} does not resolve through the producer evidence set")
    path, attachment, _ = resolve_evidence_attachment(
        root,
        str(bundle_id),
        attachment_path,
        media_type="application/json",
    )
    if reference.get("sha256") != attachment.get("sha256") or reference.get("size_bytes") != attachment.get("size_bytes"):
        raise ContractError(f"{label} hash/size differs from the evidence manifest")
    index = _load_json(path)
    _require_exact_keys(
        index,
        {"schema_version", "index_id", "artifact_set_id", "run_id", "method_id", "records", "canonical_sha256"},
        label,
    )
    if (
        index.get("schema_version") != 1
        or not isinstance(index.get("index_id"), str)
        or not index["index_id"]
        or index.get("artifact_set_id") != _official_artifact_set_id(root)
        or index.get("run_id") != expected_run_id
        or index.get("method_id") != expected_method_id
    ):
        raise ContractError(f"{label} source-index identity is invalid")
    records = index.get("records")
    if not isinstance(records, list) or not records:
        raise ContractError(f"{label} source index is empty")
    by_locator: dict[str, Mapping[str, Any]] = {}
    for position, record in enumerate(records):
        if not isinstance(record, dict):
            raise ContractError(f"{label} source record {position} is not an object")
        _require_exact_keys(record, INVENTORY_SOURCE_RECORD_KEYS, f"{label} source record {position}")
        locator = record.get("source_locator")
        if not isinstance(locator, str) or not locator or locator in by_locator:
            raise ContractError(f"{label} source record {position} has invalid/duplicate locator")
        raw_record = _resolve_raw_source_object(
            raw_documents_by_bundle.get(str(bundle_id), {}),
            locator,
            f"{label} source record {position} locator",
        )
        if raw_record != record:
            raise ContractError(f"{label} source record {position} does not exactly match its raw JSON row")
        by_locator[locator] = record
    if [str(record["source_locator"]) for record in records] != sorted(by_locator):
        raise ContractError(f"{label} source records are not sorted by locator")
    if index.get("canonical_sha256") != _sha256_bytes(_canonical_json_bytes(records)):
        raise ContractError(f"{label} source-index canonical hash is invalid")
    return (str(bundle_id), attachment_path), by_locator


def _validate_static_inventory_run(
    root: Path,
    inventory: Mapping[str, Any],
    *,
    method: Mapping[str, Any],
    official_artifact_ids: set[str],
    label: str,
) -> tuple[
    Mapping[str, Any],
    dict[tuple[str, str], Mapping[str, Mapping[str, Any]]],
    Mapping[str, Mapping[str, Any]],
    frozenset[str],
]:
    run_id = inventory.get("producer_run_id")
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise ContractError(f"{label} producer_run_id is invalid")
    path = _resolve_local_path(
        root,
        inventory.get("producer_run_manifest"),
        f"{label} producer run manifest",
        allowed_root=RESEARCH_REL / "static",
    )
    expected_path = root / RESEARCH_REL / "static" / "runs" / run_id / "manifest.json"
    if path.resolve() != expected_path.resolve():
        raise ContractError(f"{label} producer run manifest is not at its canonical run-ID path")
    run = _load_json(path)
    run_keys = {
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
    }
    _require_exact_keys(run, run_keys, f"{label} producer run")
    if (
        run.get("schema_version") != 1
        or run.get("run_id") != run_id
        or run.get("status") != "completed"
        or run.get("artifact_set_id") != _official_artifact_set_id(root)
        or run.get("method_id") != method["method_id"]
        or run.get("toolchain_family") != method["toolchain_family"]
    ):
        raise ContractError(f"{label} producer run identity/status/method is invalid")
    for field in ("experiment_id", "operator"):
        if not isinstance(run.get(field), str) or not run[field]:
            raise ContractError(f"{label} producer run lacks {field}")
    commands = _require_string_list(run.get("commands"), f"{label} producer run commands")
    if list(commands) != list(method["commands"]):
        raise ContractError(f"{label} producer run commands differ from the declared inventory method")
    exit_codes = run.get("command_exit_codes")
    if (
        not isinstance(exit_codes, list)
        or len(exit_codes) != len(commands)
        or any(type(value) is not int or value != 0 for value in exit_codes)
    ):
        raise ContractError(f"{label} producer run does not prove every declared command exited zero")
    if run.get("tool_versions") != method["tool_versions"]:
        raise ContractError(f"{label} producer run tool versions differ from its declared method")
    input_ids = _require_string_list(run.get("input_artifact_ids"), f"{label} producer run input_artifact_ids")
    if list(input_ids) != sorted(official_artifact_ids) or set(input_ids) != official_artifact_ids:
        raise ContractError(f"{label} producer run does not hash-account for the entire frozen artifact set")
    evidence_ids = _require_string_list(run.get("evidence_bundle_ids"), f"{label} producer run evidence_bundle_ids")
    declared_evidence_ids = _require_string_list(
        inventory.get("producer_evidence_bundle_ids"),
        f"{label} producer_evidence_bundle_ids",
    )
    if list(evidence_ids) != list(declared_evidence_ids) or any(
        not EVIDENCE_ID_RE.fullmatch(bundle_id) for bundle_id in evidence_ids
    ):
        raise ContractError(f"{label} producer evidence IDs are invalid or disagree with its run manifest")
    started_at = _require_timestamp(run.get("started_at"), f"{label} producer run started_at")
    ended_at = _require_timestamp(run.get("ended_at"), f"{label} producer run ended_at")
    started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    ended = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    if ended < started:
        raise ContractError(f"{label} producer run ends before it starts")
    raw_documents_by_bundle: dict[str, Mapping[str, Any]] = {}
    producer_claim_ids: set[str] = set()
    for bundle_id in evidence_ids:
        manifest_path, bundle = validate_evidence_bundle(root, bundle_id)
        captured = datetime.fromisoformat(str(bundle["captured_at"]).replace("Z", "+00:00"))
        if (
            bundle.get("evidence_tier") != "E1"
            or bundle.get("source_variant") != "untouched"
            or bundle.get("experiment_id") != run["experiment_id"]
            or bundle.get("operator") != run["operator"]
            or captured < started
            or captured > ended
        ):
            raise ContractError(f"{label} producer bundle {bundle_id} is not E1 evidence from this completed run")
        if any(bundle["event_stream"].get(field) != 0 for field in (
            "emitted_events",
            "captured_events",
            "dropped_events",
            "truncated_events",
        )):
            raise ContractError(f"{label} static E1 bundle {bundle_id} must have an explicit zero event stream")
        if any(bundle["environment"].get(field) is not None for field in (
            "device_fingerprint",
            "camera_fingerprint",
            "os_build",
            "abi",
        )):
            raise ContractError(f"{label} static E1 bundle {bundle_id} must not claim a live environment")
        producer_claim_ids.update(str(value) for value in bundle["claim_ids"])
        raw_documents_by_bundle[bundle_id] = _load_raw_json_documents(
            manifest_path,
            bundle,
            label=f"{label} producer bundle {bundle_id}",
        )
    references = run.get("source_index_attachments")
    if not isinstance(references, list) or not references:
        raise ContractError(f"{label} producer run has no hash-listed source-index attachments")
    source_indexes: dict[tuple[str, str], Mapping[str, Mapping[str, Any]]] = {}
    for index, reference in enumerate(references):
        if not isinstance(reference, dict):
            raise ContractError(f"{label} source-index reference {index} is invalid")
        key, source_records = _validate_inventory_source_index(
            root,
            reference,
            expected_run_id=run_id,
            expected_method_id=str(method["method_id"]),
            allowed_bundle_ids=set(evidence_ids),
            raw_documents_by_bundle=raw_documents_by_bundle,
            label=f"{label} source-index reference {index}",
        )
        if key in source_indexes:
            raise ContractError(f"{label} duplicates a source-index attachment")
        source_indexes[key] = source_records
    if {bundle_id for bundle_id, _ in source_indexes} != set(evidence_ids):
        raise ContractError(f"{label} does not provide a source index from every producer evidence bundle")
    for bundle_id in evidence_ids:
        indexed_locators = {
            locator
            for (indexed_bundle_id, _), rows in source_indexes.items()
            if indexed_bundle_id == bundle_id
            for locator in rows
        }
        raw_locators = _raw_source_row_locators(
            raw_documents_by_bundle[bundle_id],
            f"{label} producer bundle {bundle_id}",
        )
        if indexed_locators != raw_locators:
            missing = sorted(raw_locators - indexed_locators)
            extra = sorted(indexed_locators - raw_locators)
            raise ContractError(
                f"{label} raw/source-index record universe differs; missing={missing}, extra={extra}"
            )
    return run, source_indexes, raw_documents_by_bundle, frozenset(producer_claim_ids)


def _validate_inventory_scope_conservation(
    conservation: Any,
    *,
    record_type_counts: Mapping[str, int],
    raw_documents_by_bundle: Mapping[str, Mapping[str, Any]],
    label: str,
) -> None:
    prefix = f"{label} real-artifact scope conservation"
    if not isinstance(conservation, dict):
        raise ContractError(f"{prefix} is missing")
    try:
        _require_exact_keys(conservation, G002_CONSERVATION_SCOPES, prefix)
    except ContractError as exc:
        raise ContractError(f"{prefix} is incomplete: {exc}") from exc
    summary_keys = {
        "observed_count",
        "accounted_count",
        "normalized_record_count",
        "unaccounted_count",
        "source_ref",
    }
    raw_summary_keys = {
        "scope",
        "observed_count",
        "accounted_count",
        "normalized_record_count",
        "unaccounted_count",
    }
    source_ref_keys = {"bundle_id", "source_locator", "source_record_sha256"}
    observed_sources: set[tuple[str, str]] = set()
    for scope_name in sorted(G002_CONSERVATION_SCOPES):
        row = conservation[scope_name]
        if not isinstance(row, dict):
            raise ContractError(f"{prefix} row {scope_name} is not an object")
        _require_exact_keys(row, summary_keys, f"{prefix} row {scope_name}")
        for field in ("observed_count", "accounted_count", "unaccounted_count"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ContractError(f"{prefix} row {scope_name} has an invalid {field}")
        normalized_count = row.get("normalized_record_count")
        if normalized_count is not None and (type(normalized_count) is not int or normalized_count < 0):
            raise ContractError(f"{prefix} row {scope_name} has an invalid normalized_record_count")
        if row["accounted_count"] != row["observed_count"] or row["unaccounted_count"] != 0:
            raise ContractError(f"{prefix} row {scope_name} does not conserve its raw universe")
        expected = G002_FIXED_SCOPE_COUNTS.get(scope_name)
        if expected is not None and row["observed_count"] != expected:
            raise ContractError(
                f"{prefix} row {scope_name} is {row['observed_count']}, expected verified count {expected}"
            )
        direct_type = G002_DIRECT_SCOPE_TYPES.get(scope_name) or G002_VARIABLE_SCOPE_TYPES.get(scope_name)
        if direct_type is not None:
            derived_count = int(record_type_counts.get(direct_type, 0))
            if normalized_count != derived_count or row["observed_count"] != derived_count:
                raise ContractError(
                    f"{prefix} row {scope_name} does not match normalized {direct_type} records"
                )
        source_ref = row.get("source_ref")
        if not isinstance(source_ref, dict):
            raise ContractError(f"{prefix} row {scope_name} lacks a raw evidence reference")
        _require_exact_keys(source_ref, source_ref_keys, f"{prefix} row {scope_name} source_ref")
        bundle_id = source_ref.get("bundle_id")
        locator = source_ref.get("source_locator")
        if bundle_id not in raw_documents_by_bundle:
            raise ContractError(f"{prefix} row {scope_name} names a non-producer bundle")
        source_identity = (str(bundle_id), str(locator))
        if source_identity in observed_sources:
            raise ContractError(f"{prefix} reuses one raw summary for multiple scope universes")
        observed_sources.add(source_identity)
        raw_summary = _resolve_raw_source_object(
            raw_documents_by_bundle[str(bundle_id)],
            locator,
            f"{prefix} row {scope_name} source locator",
        )
        expected_raw = {"scope": scope_name, **{key: row[key] for key in summary_keys if key != "source_ref"}}
        if set(raw_summary) != raw_summary_keys or raw_summary != expected_raw:
            raise ContractError(f"{prefix} row {scope_name} does not exactly match its raw summary")
        if source_ref.get("source_record_sha256") != _sha256_bytes(_canonical_json_bytes(raw_summary)):
            raise ContractError(f"{prefix} row {scope_name} raw-summary hash is invalid")

    if (
        conservation["native_undefined_imports"]["observed_count"]
        + conservation["native_needed_edges"]["observed_count"]
        != conservation["native_imports"]["observed_count"]
    ):
        raise ContractError(f"{prefix} does not partition native imports into undefined symbols and DT_NEEDED edges")
    configuration_minimum = sum(
        conservation[name]["observed_count"]
        for name in (
            "xapk_entries",
            "apk_entries",
            "arm32_native_libraries",
            "resource_configurations",
            "per_library_summaries",
        )
    )
    if int(record_type_counts.get("configuration", 0)) < configuration_minimum:
        raise ContractError(f"{prefix} lacks configuration rows for archive/resource/ABI/library universes")
    jni_count = int(record_type_counts.get("jni_edge", 0))
    if jni_count < max(
        G002_FIXED_SCOPE_COUNTS["native_declarations"],
        G002_FIXED_SCOPE_COUNTS["java_exports"],
    ):
        raise ContractError(f"{prefix} does not account for every native declaration and Java_* export")


def _validate_static_inventory_document(
    root: Path,
    inventory: Mapping[str, Any],
    *,
    label: str,
) -> StaticInventoryValidation:
    required = {
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
    }
    _require_exact_keys(inventory, required, label)
    inventory_id = inventory.get("inventory_id")
    if (
        inventory.get("schema_version") != 1
        or not isinstance(inventory_id, str)
        or not re.fullmatch(r"INVENTORY-[A-Z0-9][A-Z0-9._-]*", inventory_id)
        or inventory.get("artifact_set_id") != _official_artifact_set_id(root)
    ):
        raise ContractError(f"{label} identity/artifact set is invalid")
    generated_at = _require_timestamp(inventory.get("generated_at"), f"{label} generated_at")
    method = inventory.get("method")
    if not isinstance(method, dict):
        raise ContractError(f"{label} method contract is missing")
    _require_exact_keys(
        method,
        {"method_id", "toolchain_family", "commands", "tool_versions", "producer_script"},
        f"{label} method",
    )
    for field in ("method_id", "toolchain_family"):
        if not isinstance(method.get(field), str) or not method[field]:
            raise ContractError(f"{label} method lacks {field}")
    _require_string_list(method.get("commands"), f"{label} method commands")
    if not isinstance(method.get("tool_versions"), dict) or not method["tool_versions"] or any(
        not isinstance(key, str) or not key or not isinstance(value, str) or not value
        for key, value in method["tool_versions"].items()
    ):
        raise ContractError(f"{label} method tool versions are missing")
    script_path, script_sha256, script_source, dependency_sha256s = _validate_producer_script(
        root,
        method,
        label=label,
    )

    official_manifest = _load_json(root / RESEARCH_REL / "governance/official-artifacts.json")
    official_artifacts = official_manifest.get("artifacts")
    if not isinstance(official_artifacts, list) or not official_artifacts:
        raise ContractError(f"{label} cannot resolve the frozen official artifact universe")
    official_by_id = {
        str(artifact["artifact_id"]): artifact
        for artifact in official_artifacts
        if isinstance(artifact, dict) and isinstance(artifact.get("artifact_id"), str)
    }
    if len(official_by_id) != len(official_artifacts):
        raise ContractError(f"{label} official artifact universe contains invalid or duplicate identities")
    run, source_indexes, raw_documents_by_bundle, producer_claim_ids = _validate_static_inventory_run(
        root,
        inventory,
        method=method,
        official_artifact_ids=set(official_by_id),
        label=label,
    )
    generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    run_ended_time = datetime.fromisoformat(str(run["ended_at"]).replace("Z", "+00:00"))
    if generated_time <= run_ended_time:
        raise ContractError(f"{label} inventory generation does not strictly postdate producer run completion")

    records = inventory.get("normalized_records")
    if not isinstance(records, list) or not records:
        raise ContractError(f"{label} normalized inventory records are missing")
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
    record_type_counts: dict[str, int] = {}
    source_record_references: set[tuple[str, str, str]] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ContractError(f"{label} record {index} is not an object")
        _require_exact_keys(record, record_keys, f"{label} record {index}")
        record_id = record.get("record_id")
        record_type = record.get("record_type")
        scope_key = record.get("scope_key")
        if not isinstance(record_id, str) or record_id in record_ids:
            raise ContractError(f"{label} record {index} has invalid/duplicate record_id")
        scope_payload = _validate_inventory_record_identity(record, f"{label} record {index}")
        scope_identity = (str(record_type), scope_key)
        if scope_identity in scope_identities:
            raise ContractError(f"{label} duplicates normalized scope identity {scope_identity}")
        record_ids.add(record_id)
        scope_identities.add(scope_identity)
        if record.get("classification_status") != "classified":
            raise ContractError(f"{label} record {record_id} is unclassified")
        if record.get("dossier_id") is not None:
            raise ContractError(f"{label} record {record_id} assigns dossier ownership before G003")
        parents = _require_string_list(
            record.get("parent_record_ids"),
            f"{label} record {record_id} parents",
            nonempty=False,
        )
        if parents != sorted(parents):
            raise ContractError(f"{label} record {record_id} parents are not canonically sorted")
        source_artifact_id = record.get("source_artifact_id")
        if source_artifact_id not in official_by_id:
            raise ContractError(f"{label} record {record_id} is not grounded in a frozen source artifact")
        artifact_id = record.get("artifact_id")
        if artifact_id is None:
            if record_type not in DISCOVERED_INVENTORY_RECORD_TYPES or record.get("official_source") is not None:
                raise ContractError(f"{label} discovered record {record_id} has invalid type/source")
            digest = record.get("sha256")
            size = record.get("size_bytes")
            if digest is not None and not SHA256_RE.fullmatch(str(digest)):
                raise ContractError(f"{label} record {record_id} has invalid optional sha256")
            if size is not None and (type(size) is not int or size < 0):
                raise ContractError(f"{label} record {record_id} has invalid optional size")
        else:
            if (
                not isinstance(artifact_id, str)
                or not artifact_id
                or artifact_id in artifact_records
                or source_artifact_id != artifact_id
            ):
                raise ContractError(f"{label} record {record_id} has invalid/duplicate artifact identity")
            if scope_payload != artifact_id or parents:
                raise ContractError(f"{label} frozen artifact record {record_id} has a noncanonical scope or parents")
            artifact_records[artifact_id] = record
        source_refs = record.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            raise ContractError(f"{label} record {record_id} lacks raw source-index references")
        if source_refs != sorted(source_refs, key=_canonical_json_text):
            raise ContractError(f"{label} record {record_id} source_refs are not canonically sorted")
        for source_index, source_ref in enumerate(source_refs):
            source_label = f"{label} record {record_id} source ref {source_index}"
            if not isinstance(source_ref, dict):
                raise ContractError(f"{source_label} is not an object")
            _require_exact_keys(
                source_ref,
                {"bundle_id", "attachment_path", "source_locator", "source_record_sha256"},
                source_label,
            )
            key = (str(source_ref.get("bundle_id")), str(source_ref.get("attachment_path")))
            locator = source_ref.get("source_locator")
            source_records = source_indexes.get(key)
            if source_records is None or not isinstance(locator, str) or locator not in source_records:
                raise ContractError(f"{source_label} does not resolve to a producer source-index row")
            source_record = source_records[locator]
            source_record_hash = _sha256_bytes(_canonical_json_bytes(source_record))
            if source_ref.get("source_record_sha256") != source_record_hash:
                raise ContractError(f"{source_label} source-record hash is invalid")
            for field in (
                "record_type",
                "scope_key",
                "artifact_id",
                "source_artifact_id",
                "sha256",
                "size_bytes",
                "official_source",
            ):
                if source_record.get(field) != record.get(field):
                    raise ContractError(f"{source_label} does not back normalized field {field}")
            reference_identity = (key[0], key[1], locator)
            if reference_identity in source_record_references:
                raise ContractError(f"{label} reuses one raw source record for multiple normalized rows")
            source_record_references.add(reference_identity)
        record_type_counts[str(record_type)] = record_type_counts.get(str(record_type), 0) + 1
    if [str(record["record_id"]) for record in records] != sorted(record_ids):
        raise ContractError(f"{label} normalized records are not sorted by record_id")
    artifact_record_ids = {artifact_id: str(record["record_id"]) for artifact_id, record in artifact_records.items()}
    for record in records:
        unknown_parents = set(record["parent_record_ids"]) - record_ids
        if unknown_parents or record["record_id"] in record["parent_record_ids"]:
            raise ContractError(f"{label} record {record['record_id']} has invalid parent references")
        source_parent = artifact_record_ids.get(str(record["source_artifact_id"]))
        if record["artifact_id"] is None and (
            source_parent is None or source_parent not in record["parent_record_ids"]
        ):
            raise ContractError(
                f"{label} discovered record {record['record_id']} is not parented to its frozen source artifact"
            )
    expected_source_rows = {
        (bundle_id, attachment_path, locator)
        for (bundle_id, attachment_path), source_records in source_indexes.items()
        for locator in source_records
    }
    if source_record_references != expected_source_rows:
        missing = sorted(expected_source_rows - source_record_references)
        extra = sorted(source_record_references - expected_source_rows)
        raise ContractError(f"{label} normalized/source-index coverage differs; missing={missing}, extra={extra}")

    if set(artifact_records) != set(official_by_id):
        missing = sorted(set(official_by_id) - set(artifact_records))
        extra = sorted(set(artifact_records) - set(official_by_id))
        raise ContractError(f"{label} frozen artifact coverage mismatch; missing={missing}, extra={extra}")
    for artifact_id, artifact in official_by_id.items():
        record = artifact_records[artifact_id]
        if (
            record.get("record_type") != artifact.get("kind")
            or record.get("sha256") != artifact.get("sha256")
            or record.get("size_bytes") != artifact.get("size_bytes")
            or record.get("official_source") != artifact.get("source")
        ):
            raise ContractError(f"{label} frozen artifact record differs from official identity: {artifact_id}")

    discovered_counts = {
        record_type: record_type_counts.get(record_type, 0)
        for record_type in sorted(DISCOVERED_INVENTORY_RECORD_TYPES)
    }
    missing_scopes = sorted(
        record_type
        for record_type in REQUIRED_DISCOVERED_INVENTORY_RECORD_TYPES
        if discovered_counts[record_type] == 0
    )
    if missing_scopes:
        raise ContractError(
            f"{label} merely replays the frozen artifact manifest and lacks extracted inventory scopes: {missing_scopes}"
        )
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
        raise ContractError(f"{label} coverage summary is missing")
    _require_exact_keys(coverage, coverage_keys, f"{label} coverage")
    derived_coverage = {
        "record_count": len(records),
        "record_type_counts": dict(sorted(record_type_counts.items())),
        "discovered_record_type_counts": discovered_counts,
        "apk_members": record_type_counts.get("apk_member", 0),
        "dex_files": record_type_counts.get("dex", 0),
        "native_libraries": record_type_counts.get("native_library", 0),
        "unclassified": 0,
        "frozen_artifacts_accounted": len(artifact_records),
        "all_artifacts_accounted": True,
        "scope_conservation": coverage.get("scope_conservation"),
    }
    if coverage != derived_coverage:
        raise ContractError(f"{label} coverage is self-declared rather than derived from normalized records")
    if (
        derived_coverage["apk_members"] != 19
        or derived_coverage["dex_files"] != 4
        or derived_coverage["native_libraries"] != 88
    ):
        raise ContractError(f"{label} does not cover 19 APK members, four DEX files, and 88 native libraries")
    _validate_inventory_scope_conservation(
        coverage["scope_conservation"],
        record_type_counts=record_type_counts,
        raw_documents_by_bundle=raw_documents_by_bundle,
        label=label,
    )
    canonical_records = [_canonical_inventory_record(record) for record in records]
    canonical = _canonical_json_bytes(canonical_records)
    canonical_hash = _sha256_bytes(canonical)
    if inventory.get("canonical_sha256") != canonical_hash:
        raise ContractError(f"{label} canonical normalized-record hash is invalid")
    review_id = inventory.get("independent_review_id")
    if not isinstance(review_id, str) or not REVIEW_ID_RE.fullmatch(review_id):
        raise ContractError(f"{label} independent review ID is invalid")
    validate_review(
        root,
        review_id,
        subject_id=str(inventory_id),
        expected_subject_ids=tuple(sorted(producer_claim_ids)),
        expected_bundle_ids=tuple(run["evidence_bundle_ids"]),
        producer_ids=(str(run["operator"]),),
        not_before=(
            ("producer run completion", str(run["ended_at"])),
            ("inventory generation", generated_at),
        ),
    )
    return StaticInventoryValidation(
        inventory_id=str(inventory_id),
        records=records,
        canonical=canonical,
        method_id=str(method["method_id"]),
        toolchain_family=str(method["toolchain_family"]),
        run_id=str(run["run_id"]),
        evidence_bundle_ids=frozenset(str(value) for value in run["evidence_bundle_ids"]),
        review_id=review_id,
        operator=str(run["operator"]),
        producer_script_path=script_path,
        producer_script_sha256=script_sha256,
        producer_script_source=script_source,
        local_dependency_sha256s=dependency_sha256s,
        commands=tuple(str(value) for value in method["commands"]),
    )


def _validate_inventory_independence(
    first: StaticInventoryValidation,
    second: StaticInventoryValidation,
) -> None:
    scalar_pairs = {
        "method IDs": (first.method_id, second.method_id),
        "toolchain families": (first.toolchain_family, second.toolchain_family),
        "producer runs": (first.run_id, second.run_id),
        "reviews": (first.review_id, second.review_id),
        "operators": (first.operator.casefold(), second.operator.casefold()),
        "producer script paths": (first.producer_script_path, second.producer_script_path),
        "producer script hashes": (first.producer_script_sha256, second.producer_script_sha256),
    }
    duplicated = sorted(label for label, values in scalar_pairs.items() if values[0] == values[1])
    if duplicated:
        raise ContractError(f"inventory methods are not independent; duplicated {duplicated}")
    if first.evidence_bundle_ids & second.evidence_bundle_ids:
        raise ContractError("inventory methods reuse an evidence bundle")
    if first.commands == second.commands:
        raise ContractError("inventory methods reuse the same producer commands")
    shared_dependencies = first.local_dependency_sha256s & second.local_dependency_sha256s
    if shared_dependencies:
        raise ContractError(
            f"inventory methods share a repository-local parser implementation: {sorted(shared_dependencies)}"
        )

    lanes = (
        (first, second, ("static/inventory-b.json", "static/method-b", "/tmp/g002-b", "inventory-b.json")),
        (second, first, ("static/inventory-a.json", "static/method-a", "/tmp/g002-a", "inventory-a.json")),
    )
    for lane, other, other_lane_paths in lanes:
        haystack = "\n".join((*lane.commands, lane.producer_script_source)).casefold()
        forbidden = {
            other.producer_script_path,
            Path(other.producer_script_path).name,
            other.inventory_id,
            other.method_id,
            other.run_id,
            other.review_id,
            *other.evidence_bundle_ids,
            *other_lane_paths,
        }
        observed = sorted(token for token in forbidden if token and token.casefold() in haystack)
        if observed:
            raise ContractError(
                f"inventory producer {lane.inventory_id} contains cross-lane path/read references: {observed}"
            )


def validate_static_inventory_convergence(root: Path) -> tuple[str, ...]:
    base = RESEARCH_REL / "static"
    paths = [base / "inventory-a.json", base / "inventory-b.json"]
    missing = _missing_files(root, paths)
    if missing:
        raise ContractError(f"G002 inventory evidence is unobserved: {', '.join(missing)}")
    inventories = [_load_json(root / path) for path in paths]
    validated = [
        _validate_static_inventory_document(root, inventory, label=f"inventory {index + 1}")
        for index, inventory in enumerate(inventories)
    ]
    _validate_inventory_independence(validated[0], validated[1])
    records = [item.records for item in validated]
    canonical = [item.canonical for item in validated]
    if canonical[0] != canonical[1]:
        raise ContractError("independent normalized inventories differ")
    return (
        *(_relative(root / path, root) for path in paths),
        f"normalized_records={len(records[0])}",
        f"normalized_sha256={_sha256_bytes(canonical[0])}",
        "native_libraries=88",
    )


def _resolve_hash_row(root: Path, value: Any, label: str, *, allowed_root: Path) -> Path:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be a hash-manifest object")
    _require_exact_keys(value, {"path", "sha256", "size_bytes"}, label)
    path = _resolve_local_path(root, value.get("path"), label, allowed_root=allowed_root)
    if (
        not SHA256_RE.fullmatch(str(value.get("sha256", "")))
        or type(value.get("size_bytes")) is not int
        or value["size_bytes"] < 0
        or path.stat().st_size != value["size_bytes"]
        or _sha256_file(path) != value["sha256"]
    ):
        raise ContractError(f"{label} hash/size does not match: {_relative(path, root)}")
    return path


def _validate_dossier_backing(
    root: Path,
    values: Any,
    *,
    dossier_id: str,
    scope_row_ids: set[str],
    kind: str,
    specification_ids: set[str] | None = None,
) -> tuple[set[str], set[str]]:
    if not isinstance(values, list) or not values:
        raise ContractError(f"dossier {dossier_id} {kind} backing is empty")
    paths: set[Path] = set()
    reproduction_ids: set[str] = set()
    backing_bundle_ids: set[str] = set()
    common = {"schema_version", "dossier_id", "artifact_set_id", "scope_row_ids"}
    kind_keys = {
        "static_graphs": {"nodes", "edges"},
        "state_machines": {"states", "transitions"},
        "reproduction_tests": {"reproduction_ids", "test_ids", "commands", "results"},
    }
    for index, value in enumerate(values):
        label = f"dossier {dossier_id} {kind} item {index}"
        path = _resolve_hash_row(
            root,
            value,
            label,
            allowed_root=RESEARCH_REL / "dossiers" / dossier_id,
        )
        if path in paths:
            raise ContractError(f"dossier {dossier_id} reuses a {kind} backing file")
        paths.add(path)
        document = _load_json(path)
        _require_exact_keys(document, common | kind_keys[kind], label)
        if (
            document.get("schema_version") != 1
            or document.get("dossier_id") != dossier_id
            or document.get("artifact_set_id") != _official_artifact_set_id(root)
        ):
            raise ContractError(f"{label} identity/artifact set is invalid")
        document_scope = set(_require_string_list(document.get("scope_row_ids"), f"{label} scope_row_ids"))
        if document_scope != scope_row_ids:
            raise ContractError(f"{label} scope rows do not exactly match its dossier")

        if kind == "static_graphs":
            nodes = document.get("nodes")
            edges = document.get("edges")
            if not isinstance(nodes, list) or not nodes or not isinstance(edges, list) or not edges:
                raise ContractError(f"{label} must contain non-empty nodes and edges")
            node_ids: set[str] = set()
            covered_rows: set[str] = set()
            graph_source_refs: set[str] = set()

            def validate_graph_evidence(item: Mapping[str, Any], item_label: str) -> None:
                claim_ids = _require_string_list(item.get("claim_ids"), f"{item_label} claim IDs")
                if any(not CLAIM_ID_RE.fullmatch(value) for value in claim_ids):
                    raise ContractError(f"{item_label} has invalid claim IDs")
                bundle_ids = _require_string_list(item.get("evidence_bundle_ids"), f"{item_label} evidence")
                observed_claims: set[str] = set()
                for bundle_id in bundle_ids:
                    _, bundle = validate_evidence_bundle(root, bundle_id)
                    observed_claims.update(bundle["claim_ids"])
                if not set(claim_ids).issubset(observed_claims):
                    raise ContractError(f"{item_label} claims are not backed by its evidence bundles")
                source_refs = _require_string_list(item.get("source_refs"), f"{item_label} source refs")
                if any(not re.fullmatch(r"INV-[A-Z0-9][A-Z0-9._-]*", value) for value in source_refs):
                    raise ContractError(f"{item_label} has invalid normalized inventory source refs")
                graph_source_refs.update(source_refs)
                backing_bundle_ids.update(bundle_ids)

            for node in nodes:
                if not isinstance(node, dict):
                    raise ContractError(f"{label} has a non-object node")
                _require_exact_keys(
                    node,
                    {"node_id", "node_type", "scope_row_ids", "claim_ids", "evidence_bundle_ids", "source_refs"},
                    f"{label} node",
                )
                node_id = node.get("node_id")
                if not isinstance(node_id, str) or not node_id or node_id in node_ids:
                    raise ContractError(f"{label} has an invalid/duplicate node ID")
                if node.get("node_type") not in INVENTORY_RECORD_TYPES | SCOPE_TYPES:
                    raise ContractError(f"{label} node {node_id} has an invalid semantic type")
                node_ids.add(node_id)
                node_rows = set(_require_string_list(node.get("scope_row_ids"), f"{label} node scope rows"))
                if not node_rows.issubset(scope_row_ids):
                    raise ContractError(f"{label} node references rows outside its dossier")
                covered_rows.update(node_rows)
                validate_graph_evidence(node, f"{label} node {node_id}")
            if covered_rows != scope_row_ids:
                raise ContractError(f"{label} nodes do not cover every dossier row")
            for edge in edges:
                if not isinstance(edge, dict):
                    raise ContractError(f"{label} has a non-object edge")
                _require_exact_keys(
                    edge,
                    {"from_node", "to_node", "relation", "claim_ids", "evidence_bundle_ids", "source_refs"},
                    f"{label} edge",
                )
                if edge.get("from_node") not in node_ids or edge.get("to_node") not in node_ids:
                    raise ContractError(f"{label} edge references an unknown node")
                if edge.get("from_node") == edge.get("to_node") or edge.get("relation") not in STATIC_GRAPH_RELATIONS:
                    raise ContractError(f"{label} edge is self-referential or has an unsupported relation")
                validate_graph_evidence(edge, f"{label} edge {edge.get('from_node')}->{edge.get('to_node')}")
            inventory_record_ids: set[str] = set()
            for inventory_name in ("inventory-a.json", "inventory-b.json"):
                inventory = _load_json(root / RESEARCH_REL / "static" / inventory_name)
                inventory_records = inventory.get("normalized_records")
                if not isinstance(inventory_records, list):
                    raise ContractError(f"{label} cannot resolve normalized inventory source refs")
                inventory_record_ids.update(
                    str(record["record_id"])
                    for record in inventory_records
                    if isinstance(record, dict) and isinstance(record.get("record_id"), str)
                )
            if not graph_source_refs.issubset(inventory_record_ids):
                raise ContractError(f"{label} graph source refs do not resolve to normalized inventory rows")
        elif kind == "state_machines":
            states = _require_string_list(document.get("states"), f"{label} states")
            if len(states) < 2:
                raise ContractError(f"{label} must model at least two distinct states")
            transitions = document.get("transitions")
            if not isinstance(transitions, list) or not transitions:
                raise ContractError(f"{label} has no state transitions")
            transition_ids: set[str] = set()
            covered_states: set[str] = set()
            for transition_index, transition in enumerate(transitions):
                if not isinstance(transition, dict):
                    raise ContractError(f"{label} has a non-object transition")
                _require_exact_keys(
                    transition,
                    {
                        "transition_id",
                        "from_state",
                        "event",
                        "to_state",
                        "claim_ids",
                        "evidence_bundle_ids",
                        "event_refs",
                    },
                    f"{label} transition",
                )
                transition_id = transition.get("transition_id")
                if not isinstance(transition_id, str) or not transition_id or transition_id in transition_ids:
                    raise ContractError(f"{label} has an invalid/duplicate transition_id")
                transition_ids.add(transition_id)
                if transition.get("from_state") not in states or transition.get("to_state") not in states:
                    raise ContractError(f"{label} transition references an unknown state")
                event_name = _require_semantic_text(transition.get("event"), f"{label} transition event")
                covered_states.update((str(transition["from_state"]), str(transition["to_state"])))
                claim_ids = set(
                    _require_string_list(transition.get("claim_ids"), f"{label} transition claim IDs")
                )
                if any(not CLAIM_ID_RE.fullmatch(value) for value in claim_ids):
                    raise ContractError(f"{label} transition has invalid claim IDs")
                bundle_ids = set(
                    _require_string_list(
                        transition.get("evidence_bundle_ids"),
                        f"{label} transition evidence",
                    )
                )
                event_refs = transition.get("event_refs")
                if not isinstance(event_refs, list) or not event_refs:
                    raise ContractError(f"{label} transition has no normalized event references")
                referenced_bundle_ids: set[str] = set()
                referenced_event_ids: set[str] = set()
                observed_claim_ids: set[str] = set()
                for ref_index, event_ref in enumerate(event_refs):
                    bundle_id, bundle, events = _resolve_normalized_event_reference(
                        root,
                        event_ref,
                        label=f"{label} transition {transition_id} event ref {ref_index}",
                        allowed_bundle_ids=bundle_ids,
                    )
                    if bundle.get("evidence_tier") not in {"E2", "E3"} or bundle.get("source_variant") == "reimplementation":
                        raise ContractError(f"{label} transition is not backed by official dynamic evidence")
                    event_run_ids = {str(event.get("run_id")) for event in events if event.get("run_id") is not None}
                    if len(event_run_ids) != 1:
                        raise ContractError(f"{label} transition evidence is not bound to one run")
                    run_id = next(iter(event_run_ids))
                    run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
                    _, run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
                    _validate_evidence_run_binding(
                        root,
                        bundle_id,
                        bundle,
                        run,
                        label=f"{label} transition {transition_id}",
                        events=events,
                    )
                    referenced_bundle_ids.add(bundle_id)
                    observed_claim_ids.update(str(value) for value in bundle["claim_ids"])
                    for event in events:
                        value = event.get("value")
                        if (
                            event.get("event_type") != event_name
                            or not claim_ids.issubset(set(event["claim_ids"]))
                            or not isinstance(value, dict)
                            or value.get("from_state") != transition["from_state"]
                            or value.get("to_state") != transition["to_state"]
                            or event["event_id"] in referenced_event_ids
                        ):
                            raise ContractError(f"{label} transition event does not prove its declared state change")
                        referenced_event_ids.add(str(event["event_id"]))
                if referenced_bundle_ids != bundle_ids or not claim_ids.issubset(observed_claim_ids):
                    raise ContractError(f"{label} transition does not consume evidence backing its claims")
                backing_bundle_ids.update(bundle_ids)
            if covered_states != set(states):
                raise ContractError(f"{label} state transitions do not cover every declared state")
        else:
            if not specification_ids:
                raise ContractError(f"dossier {dossier_id} reproduction tests have no clean contract scope")
            reproduction_ids.update(
                _require_string_list(document.get("reproduction_ids"), f"{label} reproduction IDs")
            )
            test_ids = set(_require_string_list(document.get("test_ids"), f"{label} test IDs"))
            commands = set(_require_string_list(document.get("commands"), f"{label} commands"))
            acceptance_tests = _load_clean_acceptance_test_index(root)
            specification = _load_json(root / RESEARCH_REL / "specs/index.json")
            contract_rows = specification.get("contracts")
            if not isinstance(contract_rows, list):
                raise ContractError(f"{label} cannot resolve clean contracts")
            contract_index = {
                str(item.get("contract_id")): item
                for item in contract_rows
                if isinstance(item, dict) and isinstance(item.get("contract_id"), str)
            }
            if not specification_ids.issubset(contract_index):
                raise ContractError(f"{label} dossier contract scope does not resolve")
            expected_test_ids = {
                test_id
                for contract_id in specification_ids
                for test_id in _require_string_list(
                    contract_index[contract_id].get("acceptance_test_ids"),
                    f"{label} clean contract {contract_id} test IDs",
                )
            }
            if test_ids != expected_test_ids:
                raise ContractError(f"{label} test IDs do not exactly cover its dossier clean contracts")
            results = document.get("results")
            if not isinstance(results, list) or not results:
                raise ContractError(f"{label} has no executed test results")
            observed_test_ids: set[str] = set()
            observed_reproduction_ids: set[str] = set()
            observed_commands: set[str] = set()
            covered_contract_ids: set[str] = set()
            for result in results:
                if not isinstance(result, dict):
                    raise ContractError(f"{label} has a non-object test result")
                _require_exact_keys(
                    result,
                    {
                        "test_id",
                        "reproduction_id",
                        "run_id",
                        "command",
                        "exit_code",
                        "result_attachment",
                        "evidence_bundle_ids",
                    },
                    f"{label} test result",
                )
                test_id = result.get("test_id")
                reproduction_id = result.get("reproduction_id")
                if test_id not in test_ids or test_id in observed_test_ids or test_id not in acceptance_tests:
                    raise ContractError(f"{label} test results are missing, duplicate, or non-passing")
                if reproduction_id not in reproduction_ids or reproduction_id in observed_reproduction_ids:
                    raise ContractError(f"{label} test result has an unknown/duplicate reproduction ID")
                acceptance = acceptance_tests[str(test_id)]
                acceptance_contract_ids = set(
                    _require_string_list(
                        acceptance.get("contract_ids"),
                        f"{label} acceptance test {test_id} contract IDs",
                    )
                )
                if not acceptance_contract_ids.issubset(specification_ids):
                    raise ContractError(f"{label} executes an acceptance test from another dossier")
                covered_contract_ids.update(acceptance_contract_ids)
                if reproduction_id != acceptance.get("reproduction_id"):
                    raise ContractError(f"{label} test result uses the wrong reproduction identity")
                command = result.get("command")
                if command != acceptance["command"] or command not in commands:
                    raise ContractError(f"{label} test result did not execute its declared acceptance command")
                if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
                    raise ContractError(f"{label} test result did not exit successfully")
                run_id = result.get("run_id")
                if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
                    raise ContractError(f"{label} test result has an invalid run ID")
                run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
                _, run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
                if run.get("source_variant") != "reimplementation" or command not in run["commands"]:
                    raise ContractError(f"{label} test result is not a reimplementation acceptance run")
                bundle_ids = set(
                    _require_string_list(result.get("evidence_bundle_ids"), f"{label} test result evidence")
                )
                result_reference = result.get("result_attachment")
                result_document, result_bundle_id = _validate_acceptance_result_attachment(
                    root,
                    result_reference,
                    acceptance=acceptance,
                    reproduction_id=str(reproduction_id),
                    run=run,
                    allowed_bundle_ids=bundle_ids,
                    label=f"{label} test result {test_id}",
                )
                if result_document["exit_code"] != result["exit_code"] or result_bundle_id not in bundle_ids:
                    raise ContractError(f"{label} test result summary differs from its result attachment")
                for bundle_id in bundle_ids:
                    _, bundle = validate_evidence_bundle(root, bundle_id)
                    if bundle.get("evidence_tier") not in {"E4", "E5"} or bundle.get("source_variant") != "reimplementation":
                        raise ContractError(f"{label} test result cites non-reimplementation evidence")
                observed_test_ids.add(str(test_id))
                observed_reproduction_ids.add(str(reproduction_id))
                observed_commands.add(str(command))
                backing_bundle_ids.update(bundle_ids)
            if observed_test_ids != test_ids:
                raise ContractError(f"{label} does not contain one passing result per test ID")
            if observed_reproduction_ids != set(reproduction_ids) or observed_commands != commands:
                raise ContractError(f"{label} reproduction IDs/commands are not derived from executed results")
            if covered_contract_ids != specification_ids:
                raise ContractError(f"{label} executed tests do not cover every dossier clean contract")
    return reproduction_ids, backing_bundle_ids


def validate_dossier_index(root: Path, rows: Sequence[Mapping[str, Any]]) -> tuple[Path, int]:
    index_path = root / RESEARCH_REL / "dossiers/index.json"
    index = _load_json(index_path)
    _require_exact_keys(index, {"schema_version", "artifact_set_id", "dossiers"}, "dossier index")
    if index.get("schema_version") != 1 or index.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("dossier index identity/artifact set is invalid")
    dossier_rows = index.get("dossiers")
    if not isinstance(dossier_rows, list) or len(dossier_rows) != len(DOSSIER_IDS):
        raise ContractError("dossier index must contain exactly 13 dossier manifest references")
    by_id: dict[str, Mapping[str, Any]] = {}
    manifest_paths: set[Path] = set()
    for index_number, item in enumerate(dossier_rows):
        if not isinstance(item, dict):
            raise ContractError(f"dossier index row {index_number} is not an object")
        _require_exact_keys(item, {"dossier_id", "manifest_path"}, f"dossier index row {index_number}")
        dossier_id = item.get("dossier_id")
        if dossier_id not in DOSSIER_IDS or dossier_id in by_id:
            raise ContractError(f"dossier index has invalid/duplicate dossier_id: {dossier_id}")
        manifest_path = _resolve_local_path(
            root,
            item.get("manifest_path"),
            f"dossier {dossier_id} manifest",
            allowed_root=RESEARCH_REL / "dossiers",
        )
        canonical_manifest_path = (root / RESEARCH_REL / "dossiers" / str(dossier_id) / "manifest.json").resolve()
        if manifest_path != canonical_manifest_path:
            raise ContractError(f"dossier {dossier_id} manifest is not at its canonical path")
        if manifest_path in manifest_paths:
            raise ContractError(f"dossier manifest path is reused: {_relative(manifest_path, root)}")
        manifest_paths.add(manifest_path)
        by_id[str(dossier_id)] = _load_json(manifest_path)
    if set(by_id) != DOSSIER_IDS:
        raise ContractError("dossier index does not contain exactly D01-D13")

    expected_rows: dict[str, set[str]] = {dossier_id: set() for dossier_id in DOSSIER_IDS}
    rows_by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        row_id = str(row["row_id"])
        dossier_id = str(row["dossier_id"])
        if row_id in rows_by_id:
            raise ContractError(f"duplicate ledger row while mapping dossiers: {row_id}")
        rows_by_id[row_id] = row
        expected_rows[dossier_id].add(row_id)
    if any(not row_ids for row_ids in expected_rows.values()):
        empty = sorted(dossier_id for dossier_id, row_ids in expected_rows.items() if not row_ids)
        raise ContractError(f"dossiers have no ledger scope rows: {empty}")

    manifest_keys = {
        "schema_version",
        "dossier_id",
        "artifact_set_id",
        "title",
        "owner",
        "approved",
        "scope_row_ids",
        "static_graphs",
        "dynamic_trace_bundle_ids",
        "state_machines",
        "evidence_bundle_ids",
        "unresolved_contradictions",
        "specification_ids",
        "reproduction_ids",
        "reproduction_tests",
        "independent_review_ids",
    }
    observed_scope_rows: set[str] = set()
    claim_graph: tuple[Mapping[str, Mapping[str, Any]], set[str]] | None = None
    for dossier_id in sorted(DOSSIER_IDS):
        dossier = by_id[dossier_id]
        _require_exact_keys(dossier, manifest_keys, f"dossier {dossier_id} manifest")
        if (
            dossier.get("schema_version") != 1
            or dossier.get("dossier_id") != dossier_id
            or dossier.get("artifact_set_id") != _official_artifact_set_id(root)
            or dossier.get("approved") is not True
        ):
            raise ContractError(f"dossier {dossier_id} identity/approval is invalid")
        for field in ("title", "owner"):
            if not isinstance(dossier.get(field), str) or not dossier[field]:
                raise ContractError(f"dossier {dossier_id} lacks {field}")
        scope_row_ids = set(_require_string_list(dossier.get("scope_row_ids"), f"dossier {dossier_id} scope_row_ids"))
        if scope_row_ids != expected_rows[dossier_id]:
            raise ContractError(f"dossier {dossier_id} scope rows do not exactly match the ledger")
        if observed_scope_rows & scope_row_ids:
            raise ContractError(f"dossier {dossier_id} duplicates ledger scope ownership")
        observed_scope_rows.update(scope_row_ids)
        specification_ids = set(
            _require_string_list(
                dossier.get("specification_ids"),
                f"dossier {dossier_id} specification IDs",
            )
        )

        _, static_backing_ids = _validate_dossier_backing(
            root,
            dossier.get("static_graphs"),
            dossier_id=dossier_id,
            scope_row_ids=scope_row_ids,
            kind="static_graphs",
        )
        _, state_backing_ids = _validate_dossier_backing(
            root,
            dossier.get("state_machines"),
            dossier_id=dossier_id,
            scope_row_ids=scope_row_ids,
            kind="state_machines",
        )
        backed_reproduction_ids, test_backing_ids = _validate_dossier_backing(
            root,
            dossier.get("reproduction_tests"),
            dossier_id=dossier_id,
            scope_row_ids=scope_row_ids,
            kind="reproduction_tests",
            specification_ids=specification_ids,
        )
        if claim_graph is None:
            claim_graph = validate_claim_graph(root)
        claims_by_id, unresolved_claim_ids = claim_graph
        declared_contradictions = set(
            _require_string_list(
                dossier.get("unresolved_contradictions"),
                f"dossier {dossier_id} unresolved contradictions",
                nonempty=False,
            )
        )
        dossier_claim_ids = {
            str(claim_id)
            for row_id in scope_row_ids
            for claim_id in rows_by_id[row_id]["claim_ids"]
        }
        derived_contradictions = unresolved_claim_ids & dossier_claim_ids
        derived_contradictions.update(
            claim_id
            for claim_id in unresolved_claim_ids
            if set(str(value) for value in claims_by_id[claim_id]["contradicts_claim_ids"])
            & dossier_claim_ids
        )
        if declared_contradictions != derived_contradictions:
            raise ContractError(
                f"dossier {dossier_id} contradiction register is not derived from the canonical claim graph"
            )
        if derived_contradictions:
            raise ContractError(f"approved dossier {dossier_id} has unresolved contradictions")

        dynamic_ids = _require_string_list(dossier.get("dynamic_trace_bundle_ids"), f"dossier {dossier_id} dynamic trace IDs")
        evidence_ids = _require_string_list(dossier.get("evidence_bundle_ids"), f"dossier {dossier_id} evidence bundle IDs")
        all_bundle_ids = list(dict.fromkeys((*evidence_ids, *dynamic_ids)))
        if any(not EVIDENCE_ID_RE.fullmatch(value) for value in all_bundle_ids):
            raise ContractError(f"dossier {dossier_id} contains invalid evidence bundle IDs")
        for bundle_id in all_bundle_ids:
            _, bundle = validate_evidence_bundle(root, bundle_id)
            if bundle_id in dynamic_ids and bundle.get("evidence_tier") not in {"E2", "E3", "E5"}:
                raise ContractError(f"dossier {dossier_id} dynamic trace {bundle_id} is not dynamic evidence")
        reproduction_ids = set(_require_string_list(dossier.get("reproduction_ids"), f"dossier {dossier_id} reproduction IDs"))
        if reproduction_ids != backed_reproduction_ids:
            raise ContractError(f"dossier {dossier_id} reproduction IDs are not backed by its executed tests")
        backing_bundle_ids = static_backing_ids | state_backing_ids | test_backing_ids
        if not backing_bundle_ids.issubset(all_bundle_ids):
            raise ContractError(f"dossier {dossier_id} backing artifacts cite evidence outside its evidence index")
        review_ids = _require_string_list(dossier.get("independent_review_ids"), f"dossier {dossier_id} independent review IDs")
        if any(not REVIEW_ID_RE.fullmatch(value) for value in review_ids):
            raise ContractError(f"dossier {dossier_id} contains invalid review IDs")
        for review_id in review_ids:
            validate_review(
                root,
                review_id,
                subject_id=dossier_id,
                expected_bundle_ids=all_bundle_ids,
                producer_ids=(str(dossier["owner"]),),
            )

        for row_id in scope_row_ids:
            row = rows_by_id[row_id]
            if not set((*row["evidence_bundle_ids"], *row["verification_ids"])).issubset(all_bundle_ids):
                raise ContractError(f"dossier {dossier_id} does not back ledger evidence for {row_id}")
            if not set(row["specification_ids"]).issubset(specification_ids):
                raise ContractError(f"dossier {dossier_id} does not back ledger specifications for {row_id}")
            if not set(row["reproduction_ids"]).issubset(reproduction_ids):
                raise ContractError(f"dossier {dossier_id} does not back ledger reproductions for {row_id}")
    validate_clean_specs_and_fixtures(root)
    specification_index = _load_json(root / RESEARCH_REL / "specs/index.json")
    contract_ids = {
        str(contract.get("contract_id"))
        for contract in specification_index["contracts"]
        if isinstance(contract, dict)
    }
    dossier_specification_ids = {
        specification_id
        for dossier in by_id.values()
        for specification_id in dossier["specification_ids"]
    }
    if not dossier_specification_ids.issubset(contract_ids):
        missing = sorted(dossier_specification_ids - contract_ids)
        raise ContractError(f"dossier specification IDs do not resolve to clean contracts: {missing}")
    if observed_scope_rows != set(rows_by_id):
        raise ContractError("dossier scope coverage differs from the whole-APK ledger")
    return index_path, len(by_id)


def validate_dossiers_and_ledger(root: Path) -> tuple[str, ...]:
    ledger_path = root / RESEARCH_REL / "static/ledger.json"
    dossier_path = root / RESEARCH_REL / "dossiers/index.json"
    missing = [path for path in (ledger_path, dossier_path) if not path.is_file()]
    if missing:
        raise ContractError(f"ledger/dossier evidence is unobserved: {', '.join(_relative(path, root) for path in missing)}")
    ledger = _load_json(ledger_path)
    rows = validate_ledger_document(root, ledger, require_verified=True, resolve_references=True)
    _, dossier_count = validate_dossier_index(root, rows)
    return (
        _relative(ledger_path, root),
        _relative(dossier_path, root),
        f"verified_rows={len(rows)}",
        f"approved_dossiers={dossier_count}",
    )


def _validate_dynamic_session_proof(
    root: Path,
    session: Mapping[str, Any],
    run: Mapping[str, Any],
    bundle_ids: set[str],
    *,
    label: str,
) -> tuple[int, str, str, bool, int]:
    reference = session.get("session_proof")
    if not isinstance(reference, dict):
        raise ContractError(f"{label} session_proof is missing")
    _require_exact_keys(reference, {"bundle_id", "path"}, f"{label} session_proof")
    proof_bundle_id = reference.get("bundle_id")
    proof_path = reference.get("path")
    if proof_bundle_id not in bundle_ids or not isinstance(proof_path, str) or not proof_path:
        raise ContractError(f"{label} session_proof is not backed by this session's evidence")
    proof_file, _, _ = resolve_evidence_attachment(
        root,
        str(proof_bundle_id),
        proof_path,
        media_type="application/json",
    )
    proof = _load_json(proof_file)
    proof_keys = {
        "schema_version",
        "proof_id",
        "artifact_set_id",
        "run_id",
        "experiment_id",
        "source_variant",
        "ledger_before",
        "ledger_after",
        "observations",
        "instrumented_observations_labeled",
        "unexplained_baseline_divergence_ids",
        "canonical_sha256",
    }
    _require_exact_keys(proof, proof_keys, f"{label} session proof")
    if (
        proof.get("schema_version") != 1
        or not isinstance(proof.get("proof_id"), str)
        or not proof["proof_id"]
        or proof.get("artifact_set_id") != _official_artifact_set_id(root)
        or proof.get("run_id") != run["run_id"]
        or proof.get("experiment_id") != run["experiment_id"]
        or proof.get("source_variant") != run["source_variant"]
    ):
        raise ContractError(f"{label} session proof identity is invalid")
    canonical = dict(proof)
    canonical.pop("canonical_sha256", None)
    if proof.get("canonical_sha256") != _sha256_bytes(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ):
        raise ContractError(f"{label} session proof canonical hash is invalid")

    ledger_documents: dict[str, Mapping[str, Any]] = {}
    ledger_hashes: dict[str, str] = {}
    for phase in ("ledger_before", "ledger_after"):
        ledger_reference = proof.get(phase)
        phase_label = f"{label} {phase}"
        if not isinstance(ledger_reference, dict):
            raise ContractError(f"{phase_label} attachment reference is missing")
        _require_exact_keys(ledger_reference, {"bundle_id", "path"}, phase_label)
        ledger_bundle_id = ledger_reference.get("bundle_id")
        ledger_attachment_path = ledger_reference.get("path")
        if ledger_bundle_id not in bundle_ids or not isinstance(ledger_attachment_path, str) or not ledger_attachment_path:
            raise ContractError(f"{phase_label} is outside the session evidence set")
        ledger_file, ledger_attachment, _ = resolve_evidence_attachment(
            root,
            str(ledger_bundle_id),
            ledger_attachment_path,
            media_type="application/json",
        )
        ledger_document = _load_json(ledger_file)
        validate_ledger_document(root, ledger_document, require_verified=False, resolve_references=False)
        ledger_documents[phase] = ledger_document
        ledger_hashes[phase] = str(ledger_attachment["sha256"])
    before_rows = {str(row["row_id"]): row for row in ledger_documents["ledger_before"]["rows"]}
    after_rows = {str(row["row_id"]): row for row in ledger_documents["ledger_after"]["rows"]}
    removed = sorted(set(before_rows) - set(after_rows))
    if removed:
        raise ContractError(f"{label} removes ledger rows during exploration: {removed}")
    added_row_ids = sorted(set(after_rows) - set(before_rows))

    observations = proof.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ContractError(f"{label} session proof has no normalized observations")
    observation_ids: set[str] = set()
    referenced_events: dict[tuple[str, str], set[str]] = {}
    parsed_event_documents: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    all_labels_valid = True
    observation_keys = {
        "observation_id",
        "claim_ids",
        "ledger_row_ids",
        "evidence_bundle_ids",
        "instrumentation_label",
        "event_refs",
    }
    for position, observation in enumerate(observations):
        observation_label = f"{label} observation {position}"
        if not isinstance(observation, dict):
            raise ContractError(f"{observation_label} is not an object")
        _require_exact_keys(observation, observation_keys, observation_label)
        observation_id = observation.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id or observation_id in observation_ids:
            raise ContractError(f"{observation_label} has invalid/duplicate observation_id")
        observation_ids.add(observation_id)
        claim_ids = _require_string_list(observation.get("claim_ids"), f"{observation_label} claim_ids")
        if any(not CLAIM_ID_RE.fullmatch(value) for value in claim_ids):
            raise ContractError(f"{observation_label} has invalid claim IDs")
        row_ids = _require_string_list(observation.get("ledger_row_ids"), f"{observation_label} ledger_row_ids")
        if not set(row_ids).issubset(after_rows):
            raise ContractError(f"{observation_label} does not resolve to the post-run ledger")
        observation_bundle_ids = _require_string_list(
            observation.get("evidence_bundle_ids"),
            f"{observation_label} evidence_bundle_ids",
        )
        if not set(observation_bundle_ids).issubset(bundle_ids):
            raise ContractError(f"{observation_label} cites evidence outside its session")
        backed_claims: set[str] = set()
        for bundle_id in observation_bundle_ids:
            _, bundle = validate_evidence_bundle(root, bundle_id)
            backed_claims.update(bundle["claim_ids"])
        if not set(claim_ids).issubset(backed_claims):
            raise ContractError(f"{observation_label} claims are not backed by its evidence bundles")
        expected_label = str(run["source_variant"])
        if observation.get("instrumentation_label") != expected_label:
            all_labels_valid = False
        event_refs = observation.get("event_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ContractError(f"{observation_label} has no normalized event references")
        observation_event_ids: set[str] = set()
        for ref_index, event_ref in enumerate(event_refs):
            ref_label = f"{observation_label} event ref {ref_index}"
            if not isinstance(event_ref, dict):
                raise ContractError(f"{ref_label} is not an object")
            _require_exact_keys(event_ref, {"bundle_id", "path", "event_ids"}, ref_label)
            event_bundle_id = event_ref.get("bundle_id")
            event_path = event_ref.get("path")
            if event_bundle_id not in observation_bundle_ids or not isinstance(event_path, str) or not event_path:
                raise ContractError(f"{ref_label} is outside the observation evidence set")
            event_ids = _require_string_list(event_ref.get("event_ids"), f"{ref_label} event_ids")
            key = (str(event_bundle_id), event_path)
            if key not in parsed_event_documents:
                event_file, _, event_bundle = resolve_evidence_attachment(
                    root,
                    str(event_bundle_id),
                    event_path,
                    media_type="application/json",
                )
                if event_path != event_bundle["event_stream"]["normalized_attachment"]:
                    raise ContractError(f"{ref_label} is not the bundle's normalized event attachment")
                events = _validate_normalized_event_document(event_file, bundle=event_bundle)
                if (
                    not events
                    or event_bundle["event_stream"]["dropped_events"] != 0
                    or event_bundle["event_stream"]["truncated_events"] != 0
                ):
                    raise ContractError(f"{ref_label} normalized event document/run/loss accounting is invalid")
                event_document = _load_json(event_file)
                parsed_event_documents[key] = (event_document, event_bundle)
            event_document, _ = parsed_event_documents[key]
            events_by_id = {str(event["event_id"]): event for event in event_document["events"]}
            for event_id in event_ids:
                event = events_by_id.get(event_id)
                if event is None or event.get("observation_id") != observation_id:
                    raise ContractError(f"{ref_label} does not resolve event {event_id} to this observation")
                if event_id in observation_event_ids:
                    raise ContractError(f"{observation_label} reuses normalized event {event_id}")
                observation_event_ids.add(event_id)
            referenced_events.setdefault(key, set()).update(event_ids)
    for key, (event_document, _) in parsed_event_documents.items():
        observed_ids = {str(event["event_id"]) for event in event_document["events"]}
        if referenced_events.get(key, set()) != observed_ids:
            raise ContractError(f"{label} leaves normalized events unlabeled or references nonexistent events")
    declared_labeled = proof.get("instrumented_observations_labeled")
    if declared_labeled is not True or not all_labels_valid:
        raise ContractError(f"{label} does not derive complete source/instrumentation labeling")
    divergence_ids = _require_string_list(
        proof.get("unexplained_baseline_divergence_ids"),
        f"{label} unexplained_baseline_divergence_ids",
        nonempty=False,
    )
    return len(added_row_ids), ledger_hashes["ledger_before"], ledger_hashes["ledger_after"], all_labels_valid, len(divergence_ids)


def validate_dynamic_convergence(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "dynamic/exploration-convergence.json"
    data = _load_json(path)
    _require_exact_keys(
        data,
        {
            "schema_version",
            "artifact_set_id",
            "sessions",
            "instrumented_observations_labeled",
            "unexplained_baseline_divergences",
        },
        "dynamic exploration convergence",
    )
    if data.get("schema_version") != 1 or data.get("artifact_set_id") != _official_artifact_set_id(root):
        raise ContractError("dynamic exploration convergence identity/artifact set is invalid")
    sessions = data.get("sessions")
    if not isinstance(sessions, list) or len(sessions) < 2:
        raise ContractError("two clean exploration sessions are not recorded")
    observed_run_ids: set[str] = set()
    observed_manifest_paths: set[Path] = set()
    observed_experiment_ids: set[str] = set()
    session_bundle_sets: list[set[str]] = []
    session_intervals: list[tuple[datetime, datetime]] = []
    validated_sessions: list[tuple[Mapping[str, Any], Mapping[str, Any], set[str]]] = []
    for index, item in enumerate(sessions):
        if not isinstance(item, dict):
            raise ContractError(f"exploration session {index} is not an object")
        _require_exact_keys(
            item,
            {"run_id", "source_variant", "new_rows", "run_manifest", "evidence_bundle_ids", "session_proof"},
            f"exploration session {index}",
        )
        if item.get("source_variant") not in SOURCE_VARIANTS or type(item.get("new_rows")) is not int or item["new_rows"] < 0:
            raise ContractError(f"exploration session {index} has invalid variant/new_rows")
        run_path, run = validate_run_manifest(root, str(item.get("run_manifest", "")), expected_run_id=str(item.get("run_id", "")))
        if item["run_id"] in observed_run_ids or run_path in observed_manifest_paths or run["experiment_id"] in observed_experiment_ids:
            raise ContractError("exploration convergence reuses a run ID, manifest, or experiment")
        observed_run_ids.add(str(item["run_id"]))
        observed_manifest_paths.add(run_path)
        observed_experiment_ids.add(str(run["experiment_id"]))
        run_started_at = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
        run_ended_at = datetime.fromisoformat(str(run["ended_at"]).replace("Z", "+00:00"))
        session_intervals.append((run_started_at, run_ended_at))
        if run.get("source_variant") != item.get("source_variant"):
            raise ContractError(f"exploration session {index} disagrees with its run manifest variant")
        bundle_ids = _require_string_list(item.get("evidence_bundle_ids"), f"exploration session {index} evidence bundle IDs")
        bundle_set = set(bundle_ids)
        session_bundle_sets.append(bundle_set)
        for bundle_id in bundle_ids:
            _, bundle = validate_evidence_bundle(root, bundle_id)
            if bundle.get("source_variant") != item.get("source_variant"):
                raise ContractError(f"exploration session {index} evidence variant mismatch")
            if bundle.get("experiment_id") != run.get("experiment_id") or bundle.get("operator") != run.get("operator"):
                raise ContractError(f"exploration session {index} evidence does not belong to its run")
            for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi"):
                if bundle["environment"].get(field) != run["environment"].get(field):
                    raise ContractError(f"exploration session {index} evidence environment mismatch for {field}")
            bundle_state_path = str(bundle["environment"].get("data_state_snapshot"))
            _, bundle_state_attachment, _ = resolve_evidence_attachment(root, bundle_id, bundle_state_path)
            if bundle_state_attachment.get("sha256") != run["data_state_snapshot"].get("sha256"):
                raise ContractError(f"exploration session {index} evidence data-state snapshot mismatch")
            evidence_delta = bundle["instrumentation_delta"]
            run_delta = run["instrumentation_delta"]
            delta_fields = ("hooks", "patches", "root_modules", "debugger", "proxies", "usb_capture_point")
            if any(evidence_delta.get(field) != run_delta.get(field) for field in delta_fields):
                raise ContractError(f"exploration session {index} evidence instrumentation delta mismatch")
            captured_at = datetime.fromisoformat(str(bundle["captured_at"]).replace("Z", "+00:00"))
            started_at = datetime.fromisoformat(str(run["started_at"]).replace("Z", "+00:00"))
            ended_at = datetime.fromisoformat(str(run["ended_at"]).replace("Z", "+00:00"))
            if not started_at <= captured_at <= ended_at:
                raise ContractError(f"exploration session {index} evidence timestamp falls outside its run")
        validated_sessions.append((item, run, bundle_set))
    for item in sessions[-2:]:
        if item.get("source_variant") != "untouched" or item.get("new_rows") != 0:
            raise ContractError("last two exploration sessions are not untouched zero-new-row runs")
    if session_bundle_sets[-1] & session_bundle_sets[-2]:
        raise ContractError("the two clean exploration sessions reuse evidence bundles")
    for prior, current in zip(session_intervals, session_intervals[1:]):
        if current[0] < prior[1]:
            raise ContractError("clean exploration sessions are not successive non-overlapping runs")
    proofs = [
        _validate_dynamic_session_proof(root, item, run, bundle_ids, label=f"exploration session {index}")
        for index, (item, run, bundle_ids) in enumerate(validated_sessions)
    ]
    for index, ((item, _, _), proof) in enumerate(zip(validated_sessions, proofs)):
        if item["new_rows"] != proof[0]:
            raise ContractError(f"exploration session {index} new_rows is not derived from its ledger snapshots")
    for prior, current in zip(proofs, proofs[1:]):
        if prior[2] != current[1]:
            raise ContractError("successive exploration session ledger snapshots do not form a hash chain")
    canonical_ledger_path = root / RESEARCH_REL / "static/ledger.json"
    if not canonical_ledger_path.is_file() or proofs[-1][2] != _sha256_file(canonical_ledger_path):
        raise ContractError("last exploration session does not resolve to the canonical ledger")
    derived_labeled = all(proof[3] for proof in proofs)
    derived_divergences = sum(proof[4] for proof in proofs)
    if (
        data.get("instrumented_observations_labeled") is not derived_labeled
        or type(data.get("unexplained_baseline_divergences")) is not int
        or data["unexplained_baseline_divergences"] != derived_divergences
        or derived_divergences != 0
    ):
        raise ContractError("untouched/instrumented separation has unresolved divergence")
    return (_relative(path, root), "successive_clean_sessions_with_new_rows=0,0", "unexplained_baseline_divergences=0")


def _resolve_normalized_event_reference(
    root: Path,
    reference: Any,
    *,
    label: str,
    allowed_bundle_ids: set[str] | None = None,
) -> tuple[str, Mapping[str, Any], list[Mapping[str, Any]]]:
    if not isinstance(reference, dict):
        raise ContractError(f"{label} is not an object")
    _require_exact_keys(reference, {"bundle_id", "path", "event_ids"}, label)
    bundle_id = reference.get("bundle_id")
    attachment_path = reference.get("path")
    if (
        not isinstance(bundle_id, str)
        or not EVIDENCE_ID_RE.fullmatch(bundle_id)
        or (allowed_bundle_ids is not None and bundle_id not in allowed_bundle_ids)
        or not isinstance(attachment_path, str)
        or not attachment_path
    ):
        raise ContractError(f"{label} is outside its permitted evidence set")
    event_ids = _require_string_list(reference.get("event_ids"), f"{label} event_ids")
    event_file, _, bundle = resolve_evidence_attachment(
        root,
        bundle_id,
        attachment_path,
        media_type="application/json",
    )
    if attachment_path != bundle["event_stream"]["normalized_attachment"]:
        raise ContractError(f"{label} does not cite the bundle's normalized event attachment")
    events = _validate_normalized_event_document(event_file, bundle=bundle)
    events_by_id = {str(event["event_id"]): event for event in events}
    resolved: list[Mapping[str, Any]] = []
    for event_id in event_ids:
        if event_id not in events_by_id:
            raise ContractError(f"{label} cannot resolve normalized event {event_id}")
        resolved.append(events_by_id[event_id])
    return bundle_id, bundle, resolved


def _validate_f2_checkpoint_proof(
    root: Path,
    reference: Any,
    *,
    allowed_bundle_ids: set[str] | None = None,
    require_terminal: bool,
) -> tuple[Mapping[str, Any], set[str], str, str, str]:
    if not isinstance(reference, dict):
        raise ContractError("F2 checkpoint proof reference is missing")
    _require_exact_keys(reference, {"bundle_id", "path"}, "F2 checkpoint proof reference")
    proof_bundle_id = reference.get("bundle_id")
    proof_path = reference.get("path")
    if (
        not isinstance(proof_bundle_id, str)
        or not EVIDENCE_ID_RE.fullmatch(proof_bundle_id)
        or (allowed_bundle_ids is not None and proof_bundle_id not in allowed_bundle_ids)
        or not isinstance(proof_path, str)
        or not proof_path
    ):
        raise ContractError("F2 checkpoint proof is outside its permitted evidence set")
    proof_file, proof_attachment, proof_bundle = resolve_evidence_attachment(
        root,
        proof_bundle_id,
        proof_path,
        media_type="application/json",
    )
    proof = _load_json(proof_file)
    proof_keys = {
        "schema_version",
        "proof_id",
        "artifact_set_id",
        "updated_by_run_id",
        "checkpoints",
        "canonical_sha256",
    }
    _require_exact_keys(proof, proof_keys, "F2 checkpoint proof")
    checkpoints = proof.get("checkpoints")
    if not isinstance(checkpoints, list) or len(checkpoints) != len(F2_CHECKPOINTS):
        raise ContractError("F2 checkpoint proof must contain exactly 12 ordered checkpoints")
    canonical = dict(proof)
    canonical.pop("canonical_sha256", None)
    if (
        proof.get("schema_version") != 1
        or not isinstance(proof.get("proof_id"), str)
        or not proof["proof_id"]
        or proof.get("artifact_set_id") != _official_artifact_set_id(root)
        or not isinstance(proof.get("updated_by_run_id"), str)
        or not RUN_ID_RE.fullmatch(str(proof["updated_by_run_id"]))
        or proof.get("canonical_sha256")
        != _sha256_bytes(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    ):
        raise ContractError("F2 checkpoint proof identity/hash is invalid")
    checkpoint_keys = {"checkpoint_id", "status", "claim_id", "run_id", "evidence_bundle_ids", "event_refs"}
    all_bundle_ids: set[str] = {proof_bundle_id}
    claim_ids: set[str] = set()
    saw_missing = False
    last_proven = "none"
    first_missing = "none"
    latest_proven_run_id: str | None = None
    for index, checkpoint in enumerate(checkpoints):
        label = f"F2 checkpoint proof row {index}"
        if not isinstance(checkpoint, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(checkpoint, checkpoint_keys, label)
        checkpoint_id = checkpoint.get("checkpoint_id")
        if checkpoint_id != F2_CHECKPOINTS[index] or checkpoint.get("status") not in {"proven", "missing"}:
            raise ContractError(f"{label} identity/status is invalid")
        if checkpoint["status"] == "missing":
            if first_missing == "none":
                first_missing = str(checkpoint_id)
            saw_missing = True
            if (
                checkpoint.get("claim_id") is not None
                or checkpoint.get("run_id") is not None
                or checkpoint.get("evidence_bundle_ids") != []
                or checkpoint.get("event_refs") != []
            ):
                raise ContractError(f"{label} fabricates evidence for an unproven checkpoint")
            continue
        if saw_missing:
            raise ContractError("F2 checkpoint proof skips a missing prerequisite")
        claim_id = checkpoint.get("claim_id")
        run_id = checkpoint.get("run_id")
        if (
            not isinstance(claim_id, str)
            or not CLAIM_ID_RE.fullmatch(claim_id)
            or claim_id in claim_ids
            or not isinstance(run_id, str)
            or not RUN_ID_RE.fullmatch(run_id)
        ):
            raise ContractError(f"{label} lacks a unique checkpoint claim/run identity")
        claim_ids.add(claim_id)
        run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
        if not run_path.is_file():
            raise ContractError(f"F2 checkpoint {checkpoint_id} run manifest is missing: {run_id}")
        _, run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
        if run.get("source_variant") != "untouched":
            raise ContractError(f"{label} is not an official untouched checkpoint run")
        bundle_ids = set(
            _require_string_list(checkpoint.get("evidence_bundle_ids"), f"{label} evidence_bundle_ids")
        )
        if allowed_bundle_ids is not None and not bundle_ids.issubset(allowed_bundle_ids):
            raise ContractError(f"{label} cites evidence outside the F2 evidence index")
        event_refs = checkpoint.get("event_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ContractError(f"{label} lacks checkpoint-specific normalized event references")
        referenced_variants: set[str] = set()
        referenced_bundle_ids: set[str] = set()
        referenced_event_ids: set[str] = set()
        for ref_index, event_ref in enumerate(event_refs):
            event_bundle_id, bundle, events = _resolve_normalized_event_reference(
                root,
                event_ref,
                label=f"{label} event ref {ref_index}",
                allowed_bundle_ids=bundle_ids,
            )
            if (
                bundle.get("evidence_tier") != "E2"
                or bundle.get("source_variant") != "untouched"
                or claim_id not in bundle["claim_ids"]
            ):
                raise ContractError(f"{label} evidence does not belong to its checkpoint run/claim")
            _validate_evidence_run_binding(
                root,
                event_bundle_id,
                bundle,
                run,
                label=label,
                events=events,
            )
            for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi"):
                if not bundle["environment"].get(field):
                    raise ContractError(f"{label} official live evidence lacks {field}")
            referenced_bundle_ids.add(event_bundle_id)
            referenced_variants.add(str(bundle["source_variant"]))
            for event in events:
                if (
                    event.get("checkpoint_id") != checkpoint_id
                    or event.get("run_id") != run_id
                    or claim_id not in event["claim_ids"]
                    or event["event_id"] in referenced_event_ids
                ):
                    raise ContractError(f"{label} event is not unique checkpoint-specific proof")
                referenced_event_ids.add(str(event["event_id"]))
        if referenced_bundle_ids != bundle_ids or not referenced_variants:
            raise ContractError(f"{label} does not consume every declared checkpoint bundle")
        all_bundle_ids.update(bundle_ids)
        last_proven = str(checkpoint_id)
        latest_proven_run_id = run_id
    if require_terminal and (last_proven != F2_CHECKPOINTS[-1] or first_missing != "none"):
        raise ContractError("F2 checkpoint proof is not terminal 12/12")
    if latest_proven_run_id is not None and proof["updated_by_run_id"] != latest_proven_run_id:
        raise ContractError("F2 checkpoint proof updated_by_run_id is not the last proven checkpoint run")
    if latest_proven_run_id is None:
        updated_path = root / RESEARCH_REL / "dynamic/runs" / str(proof["updated_by_run_id"]) / "manifest.json"
        if not updated_path.is_file():
            raise ContractError("F2 checkpoint proof updating run does not resolve")
        validate_run_manifest(root, _relative(updated_path, root), expected_run_id=str(proof["updated_by_run_id"]))
    if (
        proof_bundle.get("evidence_tier") not in {"E2", "E3", "E5"}
        or proof_bundle.get("source_variant") == "reimplementation"
        or not claim_ids.issubset(set(proof_bundle["claim_ids"]))
    ):
        raise ContractError("F2 checkpoint proof attachment does not conclude its checkpoint claims")
    return proof, all_bundle_ids, last_proven, first_missing, str(proof_attachment["sha256"])


def validate_f2_frontier(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "dynamic/f2-current-causal-frontier.json"
    data = _load_json(path)
    required = {
        "frontier_id",
        "owner",
        "last_proven_checkpoint",
        "first_missing_checkpoint",
        "supporting_bundle_ids",
        "next_discriminating_experiment",
        "updated_by_run_id",
        "checkpoint_proof",
        "evidence_backed",
        "active_frontier_count",
    }
    _require_exact_keys(data, required, "F2 causal frontier")
    if data.get("frontier_id") != "F2-first-frame" or any(
        not isinstance(data.get(key), str) or not data[key]
        for key in ("owner", "last_proven_checkpoint", "first_missing_checkpoint", "next_discriminating_experiment", "updated_by_run_id")
    ):
        raise ContractError("F2 causal frontier is incomplete")
    if data.get("evidence_backed") is not True or type(data.get("active_frontier_count")) is not int or data["active_frontier_count"] != 1:
        raise ContractError("F2 causal frontier is not exactly one and evidence-backed")
    last_proven = str(data["last_proven_checkpoint"])
    first_missing = str(data["first_missing_checkpoint"])
    if first_missing not in {*F2_CHECKPOINTS, "none"} or (last_proven != "none" and last_proven not in F2_CHECKPOINTS):
        raise ContractError("F2 causal frontier uses unknown checkpoint identifiers")
    if first_missing == "none":
        if last_proven != F2_CHECKPOINTS[-1]:
            raise ContractError("terminal F2 causal frontier does not prove the final checkpoint")
    elif last_proven == "none":
        if first_missing != F2_CHECKPOINTS[0]:
            raise ContractError("F2 causal frontier skips the first checkpoint")
    elif F2_CHECKPOINTS.index(first_missing) != F2_CHECKPOINTS.index(last_proven) + 1:
        raise ContractError("F2 causal frontier checkpoints are not adjacent")
    supporting_ids = _require_string_list(data.get("supporting_bundle_ids"), "F2 causal frontier supporting bundle IDs")
    for bundle_id in supporting_ids:
        _, bundle = validate_evidence_bundle(root, bundle_id)
        if bundle.get("evidence_tier") not in {"E2", "E3", "E5"}:
            raise ContractError("F2 causal frontier is not backed by dynamic evidence")
    proof, proof_bundle_ids, derived_last, derived_first, _ = _validate_f2_checkpoint_proof(
        root,
        data.get("checkpoint_proof"),
        allowed_bundle_ids=set(supporting_ids),
        require_terminal=False,
    )
    if (
        proof_bundle_ids != set(supporting_ids)
        or derived_last != last_proven
        or derived_first != first_missing
        or proof.get("updated_by_run_id") != data.get("updated_by_run_id")
    ):
        raise ContractError("F2 causal frontier is not derived from its checkpoint proof")

    ledger_path = root / RESEARCH_REL / "static/ledger.json"
    ledger = _load_json(ledger_path)
    validate_ledger_document(root, ledger, require_verified=False, resolve_references=True)
    ledger_frontier = ledger.get("current_causal_frontier")
    if not isinstance(ledger_frontier, dict):
        raise ContractError("canonical ledger has no F2 causal frontier")
    shared_keys = required - {"evidence_backed", "active_frontier_count"}
    if any(data.get(key) != ledger_frontier.get(key) for key in shared_keys):
        raise ContractError("F2 causal frontier disagrees with the canonical ledger")
    return (
        _relative(path, root),
        f"last_proven={data.get('last_proven_checkpoint')}",
        f"first_missing={data.get('first_missing_checkpoint')}",
        "active_frontier_count=1",
    )


def _load_clean_acceptance_test_index(root: Path) -> Mapping[str, Mapping[str, Any]]:
    spec = _load_json(root / RESEARCH_REL / "specs/index.json")
    tests = spec.get("acceptance_tests")
    if not isinstance(tests, list) or not tests:
        raise ContractError("source-independent specification has no executable acceptance tests")
    indexed: dict[str, Mapping[str, Any]] = {}
    for position, item in enumerate(tests):
        if not isinstance(item, dict) or not isinstance(item.get("test_id"), str) or not item["test_id"]:
            raise ContractError(f"source-independent acceptance test {position} has invalid identity")
        if item["test_id"] in indexed:
            raise ContractError(f"duplicate source-independent acceptance test ID: {item['test_id']}")
        indexed[str(item["test_id"])] = item
    return indexed


def _validate_acceptance_result_attachment(
    root: Path,
    reference: Any,
    *,
    acceptance: Mapping[str, Any],
    reproduction_id: str,
    run: Mapping[str, Any],
    allowed_bundle_ids: set[str],
    label: str,
) -> tuple[Mapping[str, Any], str]:
    if not isinstance(reference, dict):
        raise ContractError(f"{label} result attachment reference is missing")
    _require_exact_keys(reference, {"bundle_id", "path"}, f"{label} result attachment reference")
    bundle_id = reference.get("bundle_id")
    attachment_path = reference.get("path")
    if (
        not isinstance(bundle_id, str)
        or bundle_id not in allowed_bundle_ids
        or not isinstance(attachment_path, str)
        or not attachment_path
    ):
        raise ContractError(f"{label} result attachment is outside its declared evidence set")
    result_path, _, result_bundle = resolve_evidence_attachment(
        root,
        bundle_id,
        attachment_path,
        media_type="application/json",
    )
    if result_bundle.get("evidence_tier") not in {"E4", "E5"} or result_bundle.get("source_variant") != "reimplementation":
        raise ContractError(f"{label} result attachment is not independent reimplementation evidence")
    result = _load_json(result_path)
    result_keys = {
        "schema_version",
        "test_id",
        "reproduction_id",
        "run_id",
        "artifact_set_id",
        "command",
        "exit_code",
        "contract_ids",
        "fixture_ids",
        "assertion_results",
        "assertion_event_refs",
        "canonical_sha256",
    }
    _require_exact_keys(result, result_keys, f"{label} result document")
    canonical = dict(result)
    canonical.pop("canonical_sha256", None)
    if (
        result.get("schema_version") != 1
        or result.get("test_id") != acceptance.get("test_id")
        or result.get("reproduction_id") != reproduction_id
        or result.get("run_id") != run.get("run_id")
        or result.get("artifact_set_id") != _official_artifact_set_id(root)
        or result.get("command") != acceptance.get("command")
        or type(result.get("exit_code")) is not int
        or result["exit_code"] != 0
        or result.get("contract_ids") != acceptance.get("contract_ids")
        or result.get("fixture_ids") != acceptance.get("fixture_ids")
        or result.get("canonical_sha256")
        != _sha256_bytes(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    ):
        raise ContractError(f"{label} result identity/derivation/hash is invalid")
    assertion_ids = set(
        _require_string_list(acceptance.get("assertion_ids"), f"{label} acceptance assertion IDs")
    )
    assertion_results = result.get("assertion_results")
    assertion_event_refs = result.get("assertion_event_refs")
    if not isinstance(assertion_results, dict) or not isinstance(assertion_event_refs, dict):
        raise ContractError(f"{label} result lacks assertion outcomes/event proof")
    _require_exact_keys(assertion_results, assertion_ids, f"{label} assertion results")
    _require_exact_keys(assertion_event_refs, assertion_ids, f"{label} assertion event refs")
    if any(value is not True for value in assertion_results.values()):
        raise ContractError(f"{label} has a failed or non-boolean assertion")
    verification_claim_ids = set(
        _require_string_list(
            acceptance.get("verification_claim_ids"),
            f"{label} verification claim IDs",
        )
    )
    if not verification_claim_ids.issubset(set(result_bundle["claim_ids"])):
        raise ContractError(f"{label} result bundle does not carry its verification claims")
    official_bundle_ids = set(
        _require_string_list(
            acceptance.get("official_comparison_bundle_ids"),
            f"{label} official comparison bundle IDs",
        )
    )
    consumed_result_bundle_ids: set[str] = {bundle_id}
    consumed_official_bundle_ids: set[str] = set()
    event_ids: set[str] = set()
    for assertion_id in sorted(assertion_ids):
        comparison = assertion_event_refs[assertion_id]
        if not isinstance(comparison, dict):
            raise ContractError(f"{label} assertion {assertion_id} comparison is not an object")
        _require_exact_keys(
            comparison,
            {"official", "reimplementation", "compared_fields"},
            f"{label} assertion {assertion_id} comparison",
        )
        if comparison.get("compared_fields") != ["error_state", "event_type", "value"]:
            raise ContractError(f"{label} assertion {assertion_id} does not compare the required observables")
        lane_events: dict[str, list[Mapping[str, Any]]] = {}
        for lane, permitted_ids in (
            ("official", official_bundle_ids),
            ("reimplementation", allowed_bundle_ids),
        ):
            refs = comparison.get(lane)
            if not isinstance(refs, list) or not refs:
                raise ContractError(f"{label} assertion {assertion_id} has no {lane} normalized event proof")
            observed_events: list[Mapping[str, Any]] = []
            for ref_index, event_ref in enumerate(refs):
                event_bundle_id, event_bundle, events = _resolve_normalized_event_reference(
                    root,
                    event_ref,
                    label=f"{label} assertion {assertion_id} {lane} event ref {ref_index}",
                    allowed_bundle_ids=permitted_ids,
                )
                if lane == "official":
                    if event_bundle.get("evidence_tier") not in {"E2", "E3"} or event_bundle.get("source_variant") == "reimplementation":
                        raise ContractError(f"{label} assertion official lane is not official dynamic evidence")
                    official_run_ids = {str(event.get("run_id")) for event in events if event.get("run_id") is not None}
                    if len(official_run_ids) != 1:
                        raise ContractError(f"{label} assertion official evidence is not bound to one run")
                    official_run_id = next(iter(official_run_ids))
                    official_run_path = root / RESEARCH_REL / "dynamic/runs" / official_run_id / "manifest.json"
                    _, official_run = validate_run_manifest(
                        root,
                        _relative(official_run_path, root),
                        expected_run_id=official_run_id,
                    )
                    _validate_evidence_run_binding(
                        root,
                        event_bundle_id,
                        event_bundle,
                        official_run,
                        label=f"{label} assertion {assertion_id} official",
                        events=events,
                    )
                    consumed_official_bundle_ids.add(event_bundle_id)
                else:
                    if event_bundle.get("evidence_tier") not in {"E4", "E5"} or event_bundle.get("source_variant") != "reimplementation":
                        raise ContractError(f"{label} assertion is not backed by reimplementation evidence")
                    _validate_evidence_run_binding(
                        root,
                        event_bundle_id,
                        event_bundle,
                        run,
                        label=f"{label} assertion {assertion_id} reimplementation",
                        events=events,
                    )
                    consumed_result_bundle_ids.add(event_bundle_id)
                if not verification_claim_ids.issubset(set(event_bundle["claim_ids"])):
                    raise ContractError(f"{label} assertion evidence does not carry its verification claims")
                for event in events:
                    if (
                        event.get("observation_id") != assertion_id
                        or not verification_claim_ids.issubset(set(event["claim_ids"]))
                        or event["event_id"] in event_ids
                    ):
                        raise ContractError(f"{label} assertion event is not uniquely labeled to its assertion")
                    event_ids.add(str(event["event_id"]))
                    observed_events.append(event)
            lane_events[lane] = observed_events
        official_correlations = {str(event["correlation_id"]) for event in lane_events["official"]}
        reproduction_correlations = {str(event["correlation_id"]) for event in lane_events["reimplementation"]}
        if not official_correlations.intersection(reproduction_correlations):
            raise ContractError(f"{label} assertion official/reimplementation events are not correlated")

        def observable_projection(events: Sequence[Mapping[str, Any]]) -> list[tuple[Any, Any, Any]]:
            return sorted(
                (
                    event.get("error_state"),
                    event.get("event_type"),
                    json.dumps(event.get("value"), sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                )
                for event in events
            )

        if observable_projection(lane_events["official"]) != observable_projection(lane_events["reimplementation"]):
            raise ContractError(f"{label} assertion official/reimplementation observables diverge")
    if consumed_result_bundle_ids != allowed_bundle_ids:
        raise ContractError(f"{label} does not consume every declared result bundle")
    if consumed_official_bundle_ids != official_bundle_ids:
        raise ContractError(f"{label} does not consume every declared official comparison bundle")
    if acceptance.get("command") not in run["commands"] or acceptance.get("command") not in result_bundle["replay_commands"]:
        raise ContractError(f"{label} command is not replayable from both run and result evidence")
    return result, bundle_id


def _validate_contract_descriptor_list(
    value: Any,
    *,
    kind: str,
    contract_id: str,
    contract_claim_ids: set[str],
) -> None:
    descriptor_keys = {
        "observable_inputs": {"input_id", "schema", "required", "constraints", "claim_ids"},
        "observable_outputs": {"output_id", "schema", "nullable", "semantics", "claim_ids"},
        "state_transitions": {"transition_id", "from_state", "event", "to_state", "claim_ids"},
        "timing_lifetime": {"requirement_id", "subject", "constraint", "claim_ids"},
        "errors_recovery": {"error_id", "trigger", "observable_error", "recovery", "claim_ids"},
    }
    id_keys = {
        "observable_inputs": "input_id",
        "observable_outputs": "output_id",
        "state_transitions": "transition_id",
        "timing_lifetime": "requirement_id",
        "errors_recovery": "error_id",
    }
    if not isinstance(value, list) or not value:
        raise ContractError(f"source-independent contract {contract_id} {kind} is empty")
    seen_ids: set[str] = set()
    for position, descriptor in enumerate(value):
        label = f"source-independent contract {contract_id} {kind} row {position}"
        if not isinstance(descriptor, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(descriptor, descriptor_keys[kind], label)
        descriptor_id = descriptor.get(id_keys[kind])
        if not isinstance(descriptor_id, str) or not descriptor_id or descriptor_id in seen_ids:
            raise ContractError(f"{label} has invalid/duplicate identity")
        seen_ids.add(descriptor_id)
        claims = set(_require_string_list(descriptor.get("claim_ids"), f"{label} claim IDs"))
        if not claims.issubset(contract_claim_ids):
            raise ContractError(f"{label} cites claims outside its contract")
        for key, item in descriptor.items():
            if key in {id_keys[kind], "claim_ids"}:
                continue
            if key in {"required", "nullable"}:
                if type(item) is not bool:
                    raise ContractError(f"{label} {key} must be boolean")
            elif key == "schema":
                if not isinstance(item, str) or not item.strip():
                    raise ContractError(f"{label} schema is missing")
            else:
                _require_semantic_text(item, f"{label} {key}")
        serialized = json.dumps(descriptor, ensure_ascii=False, sort_keys=True)
        if re.search(
            r"(?i)(?:\binvoke-(?:virtual|static|direct)\b|\bjadx\b|\bsmali\b|\bdecompil(?:er|ed|ation)\b|\.method\s|\.class\s|package\s+com\.hik)",
            serialized,
        ):
            raise ContractError(f"{label} contains prohibited decompiler/source-body material")


def _validate_clean_specification(
    root: Path,
) -> tuple[Path, Mapping[str, Any], Path, Mapping[str, Mapping[str, Any]], set[str]]:
    spec_path = root / RESEARCH_REL / "specs/index.json"
    spec = _load_json(spec_path)
    required = {
        "schema_version",
        "specification_id",
        "artifact_set_id",
        "author_id",
        "approved",
        "evidence_bundle_ids",
        "clean_room_review_id",
        "contracts",
        "acceptance_tests",
    }
    _require_exact_keys(spec, required, "source-independent specification index")
    if (
        spec.get("schema_version") != 1
        or spec.get("artifact_set_id") != _official_artifact_set_id(root)
        or not isinstance(spec.get("specification_id"), str)
        or not spec["specification_id"]
        or not isinstance(spec.get("author_id"), str)
        or not spec["author_id"]
        or spec.get("approved") is not True
        or not REVIEW_ID_RE.fullmatch(str(spec.get("clean_room_review_id", "")))
    ):
        raise ContractError("source-independent specification lacks clean-room approval")
    spec_bundle_ids = _require_string_list(
        spec.get("evidence_bundle_ids"),
        "source-independent specification evidence bundle IDs",
    )
    bundle_claims: set[str] = set()
    producer_ids: set[str] = {str(spec["author_id"])}
    for bundle_id in spec_bundle_ids:
        _, bundle = validate_evidence_bundle(root, bundle_id)
        bundle_claims.update(str(value) for value in bundle["claim_ids"])
        producer_ids.add(str(bundle["operator"]))
    contracts = spec.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise ContractError("source-independent specification has no contracts")
    contract_ids: set[str] = set()
    contract_test_ids: dict[str, set[str]] = {}
    contract_claim_ids: dict[str, set[str]] = {}
    contract_bundle_ids: dict[str, set[str]] = {}
    for item in contracts:
        if not isinstance(item, dict):
            raise ContractError("source-independent contract is not an object")
        contract_keys = {
            "contract_id",
            "acceptance_test_ids",
            "evidence_claim_ids",
            "evidence_bundle_ids",
            "observable_inputs",
            "observable_outputs",
            "state_transitions",
            "timing_lifetime",
            "errors_recovery",
        }
        _require_exact_keys(item, contract_keys, "source-independent contract")
        contract_id = item.get("contract_id")
        if not isinstance(contract_id, str) or not contract_id or contract_id in contract_ids:
            raise ContractError("source-independent contract has invalid/duplicate contract_id")
        contract_ids.add(contract_id)
        test_ids = set(
            _require_string_list(item.get("acceptance_test_ids"), f"source-independent contract {contract_id} tests")
        )
        contract_test_ids[contract_id] = test_ids
        evidence_ids = set(
            _require_string_list(item.get("evidence_bundle_ids"), f"source-independent contract {contract_id} evidence")
        )
        claim_ids = set(
            _require_string_list(item.get("evidence_claim_ids"), f"source-independent contract {contract_id} claims")
        )
        if not evidence_ids.issubset(set(spec_bundle_ids)):
            raise ContractError("source-independent contract cites evidence outside the specification index")
        if any(not CLAIM_ID_RE.fullmatch(value) for value in claim_ids) or not claim_ids.issubset(bundle_claims):
            raise ContractError("source-independent contract claims are not backed by specification evidence")
        contract_claim_ids[contract_id] = claim_ids
        contract_bundle_ids[contract_id] = evidence_ids
        for kind in (
            "observable_inputs",
            "observable_outputs",
            "state_transitions",
            "timing_lifetime",
            "errors_recovery",
        ):
            _validate_contract_descriptor_list(
                item.get(kind),
                kind=kind,
                contract_id=contract_id,
                contract_claim_ids=claim_ids,
            )

    acceptance_index = _load_clean_acceptance_test_index(root)
    result_bundle_ids: set[str] = set()
    reproduction_ids: set[str] = set()
    for test_id, acceptance in acceptance_index.items():
        label = f"source-independent acceptance test {test_id}"
        test_keys = {
            "test_id",
            "reproduction_id",
            "contract_ids",
            "verification_claim_ids",
            "official_comparison_bundle_ids",
            "fixture_ids",
            "command",
            "assertion_ids",
            "run_id",
            "result_bundle_ids",
            "result_attachment",
        }
        _require_exact_keys(acceptance, test_keys, label)
        reproduction_id = acceptance.get("reproduction_id")
        if not isinstance(reproduction_id, str) or not reproduction_id or reproduction_id in reproduction_ids:
            raise ContractError(f"{label} has invalid/duplicate reproduction_id")
        reproduction_ids.add(reproduction_id)
        referenced_contracts = set(
            _require_string_list(acceptance.get("contract_ids"), f"{label} contract IDs")
        )
        if not referenced_contracts.issubset(contract_ids):
            raise ContractError(f"{label} references an unknown contract")
        for contract_id in referenced_contracts:
            if test_id not in contract_test_ids[contract_id]:
                raise ContractError(f"{label} lacks a reverse mapping from contract {contract_id}")
        verification_claim_ids = set(
            _require_string_list(acceptance.get("verification_claim_ids"), f"{label} verification claims")
        )
        if any(not CLAIM_ID_RE.fullmatch(value) for value in verification_claim_ids):
            raise ContractError(f"{label} contains an invalid verification claim")
        expected_verification_claim_ids = set().union(
            *(contract_claim_ids[contract_id] for contract_id in referenced_contracts)
        )
        if verification_claim_ids != expected_verification_claim_ids:
            raise ContractError(f"{label} verification claims are not derived from its referenced contracts")
        official_comparison_bundle_ids = set(
            _require_string_list(
                acceptance.get("official_comparison_bundle_ids"),
                f"{label} official comparison bundle IDs",
            )
        )
        expected_contract_bundle_ids = set().union(
            *(contract_bundle_ids[contract_id] for contract_id in referenced_contracts)
        )
        if not official_comparison_bundle_ids.issubset(expected_contract_bundle_ids):
            raise ContractError(f"{label} official comparison evidence is outside its referenced contracts")
        for bundle_id in official_comparison_bundle_ids:
            _, official_bundle = validate_evidence_bundle(root, bundle_id)
            if (
                official_bundle.get("evidence_tier") not in {"E2", "E3"}
                or official_bundle.get("source_variant") == "reimplementation"
                or not verification_claim_ids.issubset(set(official_bundle["claim_ids"]))
            ):
                raise ContractError(f"{label} official comparison evidence is not matching dynamic contract evidence")
        _require_string_list(acceptance.get("fixture_ids"), f"{label} fixture IDs")
        _require_semantic_text(acceptance.get("command"), f"{label} command")
        _require_string_list(acceptance.get("assertion_ids"), f"{label} assertion IDs")
        run_id = acceptance.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise ContractError(f"{label} has an invalid run ID")
        run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
        _, run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
        if run.get("source_variant") != "reimplementation" or acceptance["command"] not in run["commands"]:
            raise ContractError(f"{label} is not backed by a completed reimplementation run")
        producer_ids.add(str(run["operator"]))
        bundle_ids = set(
            _require_string_list(acceptance.get("result_bundle_ids"), f"{label} result bundles")
        )
        for bundle_id in bundle_ids:
            _, bundle = validate_evidence_bundle(root, bundle_id)
            if (
                bundle.get("evidence_tier") not in {"E4", "E5"}
                or bundle.get("source_variant") != "reimplementation"
                or not verification_claim_ids.issubset(set(bundle["claim_ids"]))
            ):
                raise ContractError(f"{label} has incompatible result evidence")
            event_path = str(bundle["event_stream"]["normalized_attachment"])
            event_file, _, _ = resolve_evidence_attachment(root, bundle_id, event_path, media_type="application/json")
            events = _validate_normalized_event_document(event_file, bundle=bundle)
            _validate_evidence_run_binding(root, bundle_id, bundle, run, label=label, events=events)
            producer_ids.add(str(bundle["operator"]))
        _validate_acceptance_result_attachment(
            root,
            acceptance.get("result_attachment"),
            acceptance=acceptance,
            reproduction_id=reproduction_id,
            run=run,
            allowed_bundle_ids=bundle_ids,
            label=label,
        )
        result_bundle_ids.update(bundle_ids)
    declared_test_ids = set(acceptance_index)
    if set().union(*contract_test_ids.values()) != declared_test_ids:
        raise ContractError("source-independent contract/test traceability is not exact")
    all_review_bundle_ids = sorted(set(spec_bundle_ids) | result_bundle_ids)
    review_path, _ = validate_review(
        root,
        str(spec["clean_room_review_id"]),
        subject_id=str(spec["specification_id"]),
        expected_bundle_ids=all_review_bundle_ids,
        producer_ids=sorted(producer_ids),
    )
    return spec_path, spec, review_path, acceptance_index, result_bundle_ids


def _validate_fixture_manifest(root: Path) -> tuple[Path, Path, set[str]]:
    validate_official_artifact_freeze(root)
    path = root / RESEARCH_REL / "reproduction/fixtures-manifest.json"
    data = _load_json(path)
    required = {
        "schema_version",
        "fixture_set_id",
        "artifact_set_id",
        "official_fixtures",
        "sanitized_fixtures",
        "evidence_bundle_ids",
        "independent_review_id",
    }
    _require_exact_keys(data, required, "clean fixture manifest")
    fixture_set_id = data.get("fixture_set_id")
    if (
        data.get("schema_version") != 1
        or not isinstance(fixture_set_id, str)
        or not fixture_set_id
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
    ):
        raise ContractError("clean fixture manifest identity/artifact set is invalid")
    official_manifest = _load_json(root / RESEARCH_REL / "governance/official-artifacts.json")
    expected_official = {
        str(item["artifact_id"]): item
        for item in official_manifest["artifacts"]
        if item.get("kind") == "official_fixture"
    }
    official_rows = data.get("official_fixtures")
    if not isinstance(official_rows, list) or len(official_rows) != len(expected_official):
        raise ContractError("clean fixture manifest does not account for exactly all six official fixtures")
    seen_official: set[str] = set()
    for position, row in enumerate(official_rows):
        label = f"official fixture row {position}"
        if not isinstance(row, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(
            row,
            {"fixture_id", "artifact_id", "source_path", "sha256", "size_bytes", "local_only"},
            label,
        )
        artifact_id = row.get("artifact_id")
        expected = expected_official.get(str(artifact_id))
        if expected is None or artifact_id in seen_official:
            raise ContractError(f"{label} has unknown/duplicate official artifact identity")
        seen_official.add(str(artifact_id))
        if (
            not isinstance(row.get("fixture_id"), str)
            or not row["fixture_id"]
            or row.get("source_path") != expected["source"].get("path")
            or row.get("sha256") != expected["sha256"]
            or row.get("size_bytes") != expected["size_bytes"]
            or row.get("local_only") is not True
        ):
            raise ContractError(f"{label} is not derived from the frozen official fixture")
    if seen_official != set(expected_official):
        raise ContractError("clean fixture manifest omits official fixtures")

    evidence_bundle_ids = set(
        _require_string_list(data.get("evidence_bundle_ids"), "clean fixture evidence bundle IDs")
    )
    sanitized_rows = data.get("sanitized_fixtures")
    if not isinstance(sanitized_rows, list) or len(sanitized_rows) != len(expected_official):
        raise ContractError("clean fixture manifest requires one sanitized fixture per official fixture")
    fixture_ids: set[str] = set()
    source_ids: set[str] = set()
    consumed_bundle_ids: set[str] = set()
    producers: set[str] = set()
    attachment_keys: set[tuple[str, str]] = set()
    for position, row in enumerate(sanitized_rows):
        label = f"sanitized fixture row {position}"
        if not isinstance(row, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(
            row,
            {
                "fixture_id",
                "source_artifact_id",
                "bundle_id",
                "path",
                "sha256",
                "size_bytes",
                "media_type",
                "redistribution",
                "provenance_attachment",
            },
            label,
        )
        fixture_id = row.get("fixture_id")
        source_id = row.get("source_artifact_id")
        bundle_id = row.get("bundle_id")
        attachment_key = (str(bundle_id), str(row.get("path", "")))
        if (
            not isinstance(fixture_id, str)
            or not fixture_id
            or fixture_id in fixture_ids
            or source_id not in expected_official
            or source_id in source_ids
            or bundle_id not in evidence_bundle_ids
            or row.get("redistribution") not in {"sanitized", "local-only"}
            or row.get("media_type") == "text/plain"
            or attachment_key in attachment_keys
        ):
            raise ContractError(f"{label} identity/provenance is invalid")
        fixture_path, attachment, bundle = resolve_evidence_attachment(
            root,
            str(bundle_id),
            str(row.get("path", "")),
        )
        if (
            bundle.get("evidence_tier") not in {"E4", "E5"}
            or bundle.get("source_variant") != "reimplementation"
            or row.get("sha256") != attachment["sha256"]
            or row.get("size_bytes") != attachment["size_bytes"]
            or row.get("media_type") != attachment["media_type"]
            or fixture_path.stat().st_size <= 0
        ):
            raise ContractError(f"{label} is not a non-empty hash-backed sanitized fixture")
        provenance_reference = row.get("provenance_attachment")
        if not isinstance(provenance_reference, dict):
            raise ContractError(f"{label} has no transformation provenance attachment")
        _require_exact_keys(
            provenance_reference,
            {"bundle_id", "path"},
            f"{label} provenance attachment",
        )
        if provenance_reference.get("bundle_id") != bundle_id:
            raise ContractError(f"{label} provenance is outside its fixture evidence bundle")
        provenance_path, _, _ = resolve_evidence_attachment(
            root,
            str(bundle_id),
            str(provenance_reference.get("path", "")),
            media_type="application/json",
        )
        provenance = _load_json(provenance_path)
        provenance_keys = {
            "schema_version",
            "provenance_id",
            "fixture_id",
            "source_artifact_id",
            "artifact_set_id",
            "run_id",
            "transformation_command",
            "tool_versions",
            "source_sha256",
            "source_size_bytes",
            "output_path",
            "output_sha256",
            "output_size_bytes",
            "preserved_observables",
            "event_refs",
            "canonical_sha256",
        }
        _require_exact_keys(provenance, provenance_keys, f"{label} provenance document")
        canonical_provenance = dict(provenance)
        canonical_provenance.pop("canonical_sha256", None)
        transformation_command = provenance.get("transformation_command")
        run_id = provenance.get("run_id")
        preserved_observables = set(
            _require_string_list(
                provenance.get("preserved_observables"),
                f"{label} preserved observables",
            )
        )
        for observable in preserved_observables:
            _require_semantic_text(observable, f"{label} preserved observable")
        if (
            provenance.get("schema_version") != 1
            or not isinstance(provenance.get("provenance_id"), str)
            or not provenance["provenance_id"]
            or provenance.get("fixture_id") != fixture_id
            or provenance.get("source_artifact_id") != source_id
            or provenance.get("artifact_set_id") != _official_artifact_set_id(root)
            or not isinstance(run_id, str)
            or not RUN_ID_RE.fullmatch(run_id)
            or provenance.get("source_sha256") != expected_official[str(source_id)]["sha256"]
            or provenance.get("source_size_bytes") != expected_official[str(source_id)]["size_bytes"]
            or provenance.get("output_path") != row.get("path")
            or provenance.get("output_sha256") != row.get("sha256")
            or provenance.get("output_size_bytes") != row.get("size_bytes")
            or provenance.get("canonical_sha256")
            != _sha256_bytes(
                json.dumps(
                    canonical_provenance,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            )
        ):
            raise ContractError(f"{label} transformation provenance identity/hash is invalid")
        _require_semantic_text(transformation_command, f"{label} transformation command")
        if provenance.get("tool_versions") != bundle.get("tool_versions"):
            raise ContractError(f"{label} transformation tool versions differ from its evidence bundle")
        run_path = root / RESEARCH_REL / "dynamic/runs" / str(run_id) / "manifest.json"
        _, fixture_run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=str(run_id))
        if (
            fixture_run.get("source_variant") != "reimplementation"
            or transformation_command not in fixture_run["commands"]
            or transformation_command not in bundle["replay_commands"]
        ):
            raise ContractError(f"{label} transformation was not executed by a replayable clean-room run")
        event_refs = provenance.get("event_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ContractError(f"{label} provenance has no normalized transformation events")
        observed_observables: set[str] = set()
        observed_event_ids: set[str] = set()
        for ref_index, event_ref in enumerate(event_refs):
            event_bundle_id, event_bundle, events = _resolve_normalized_event_reference(
                root,
                event_ref,
                label=f"{label} provenance event ref {ref_index}",
                allowed_bundle_ids={str(bundle_id)},
            )
            _validate_evidence_run_binding(
                root,
                event_bundle_id,
                event_bundle,
                fixture_run,
                label=f"{label} transformation provenance",
                events=events,
            )
            for event in events:
                value = event.get("value")
                observable = event.get("observation_id")
                if (
                    event.get("event_type") != "fixture_sanitization_assertion"
                    or observable not in preserved_observables
                    or observable in observed_observables
                    or event["event_id"] in observed_event_ids
                    or not isinstance(value, dict)
                    or set(value)
                    != {
                        "fixture_id",
                        "source_artifact_id",
                        "source_value_sha256",
                        "output_value_sha256",
                        "matched",
                    }
                    or value.get("fixture_id") != fixture_id
                    or value.get("source_artifact_id") != source_id
                    or not SHA256_RE.fullmatch(str(value.get("source_value_sha256", "")))
                    or value.get("source_value_sha256") != value.get("output_value_sha256")
                    or value.get("matched") is not True
                ):
                    raise ContractError(f"{label} provenance event does not prove a preserved observable")
                observed_observables.add(str(observable))
                observed_event_ids.add(str(event["event_id"]))
        if observed_observables != preserved_observables:
            raise ContractError(f"{label} does not prove every declared preserved observable")
        fixture_ids.add(fixture_id)
        attachment_keys.add(attachment_key)
        source_ids.add(str(source_id))
        consumed_bundle_ids.add(str(bundle_id))
        producers.add(str(bundle["operator"]))
    if source_ids != set(expected_official) or consumed_bundle_ids != evidence_bundle_ids:
        raise ContractError("clean fixture manifest provenance/evidence coverage is not exact")
    review_path, _ = validate_review(
        root,
        str(data.get("independent_review_id", "")),
        subject_id=str(fixture_set_id),
        expected_bundle_ids=sorted(evidence_bundle_ids),
        producer_ids=sorted(producers),
    )
    return path, review_path, fixture_ids


def validate_clean_specs_and_fixtures(root: Path) -> tuple[str, ...]:
    spec_path, spec, spec_review_path, acceptance_index, _ = _validate_clean_specification(root)
    fixture_path, fixture_review_path, fixture_ids = _validate_fixture_manifest(root)
    for test_id, acceptance in acceptance_index.items():
        if not set(acceptance["fixture_ids"]).issubset(fixture_ids):
            raise ContractError(f"source-independent acceptance test {test_id} cites an unknown clean fixture")
    return (
        _relative(spec_path, root),
        _relative(spec_review_path, root),
        _relative(fixture_path, root),
        _relative(fixture_review_path, root),
        f"contracts={len(spec['contracts'])}",
        f"acceptance_tests={len(acceptance_index)}",
        f"sanitized_fixtures={len(fixture_ids)}",
    )


def _validate_radiometric_comparison(
    root: Path,
    name: str,
    item: Any,
) -> tuple[list[str], set[str], dict[str, Any]]:
    if not isinstance(item, dict):
        raise ContractError(f"radiometric {name} validation is missing")
    required = {
        "passed",
        "claim_id",
        "evidence_bundle_ids",
        "sample_count",
        "mean_error_c",
        "max_pixel_error_c",
        "comparison_attachment",
    }
    _require_exact_keys(item, required, f"radiometric {name} validation")
    if item.get("passed") is not True:
        raise ContractError(f"radiometric {name} validation did not pass")
    claim_id = item.get("claim_id")
    if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id):
        raise ContractError(f"radiometric {name} validation has an invalid claim ID")
    if type(item.get("sample_count")) is not int or item["sample_count"] < 2:
        raise ContractError(f"radiometric {name} validation has fewer than two measured samples")
    declared_mean = _require_finite_number(item.get("mean_error_c"), f"radiometric {name} mean_error_c")
    declared_maximum = _require_finite_number(item.get("max_pixel_error_c"), f"radiometric {name} max_pixel_error_c")

    bundle_ids = _require_string_list(item.get("evidence_bundle_ids"), f"radiometric {name} evidence bundle IDs")
    if len(bundle_ids) < 2:
        raise ContractError(f"radiometric {name} comparison lacks separate official/reimplementation evidence")
    bundles: dict[str, Mapping[str, Any]] = {}
    observed_claims: set[str] = set()
    for bundle_id in bundle_ids:
        _, bundle = validate_evidence_bundle(root, bundle_id)
        bundles[bundle_id] = bundle
        observed_claims.update(bundle["claim_ids"])
    if claim_id not in observed_claims:
        raise ContractError(f"radiometric {name} comparison claim is not backed by its bundles")
    expected_official_tier = "E1" if name == "fixture" else "E2"
    official_ids = {
        bundle_id
        for bundle_id, bundle in bundles.items()
        if bundle["source_variant"] == "untouched" and bundle["evidence_tier"] == expected_official_tier
    }
    reimplementation_ids = {
        bundle_id
        for bundle_id, bundle in bundles.items()
        if bundle["source_variant"] == "reimplementation" and bundle["evidence_tier"] == "E4"
    }
    if not official_ids or not reimplementation_ids:
        raise ContractError(
            f"radiometric {name} requires {expected_official_tier} untouched plus E4 reimplementation evidence"
        )
    if name == "live":
        for bundle in bundles.values():
            if bundle["source_variant"] in {"untouched", "reimplementation"}:
                for field in ("device_fingerprint", "camera_fingerprint", "os_build", "abi"):
                    if not bundle["environment"].get(field):
                        raise ContractError(f"radiometric live evidence lacks target {field}")

    attachment = item.get("comparison_attachment")
    if not isinstance(attachment, dict):
        raise ContractError(f"radiometric {name} comparison attachment is missing")
    _require_exact_keys(attachment, {"bundle_id", "path"}, f"radiometric {name} comparison attachment")
    attachment_bundle_id = attachment.get("bundle_id")
    attachment_path = attachment.get("path")
    if attachment_bundle_id not in bundles or not isinstance(attachment_path, str) or not attachment_path:
        raise ContractError(f"radiometric {name} comparison attachment is not bundle-backed")
    attachment_paths = {str(value["path"]) for value in bundles[str(attachment_bundle_id)]["attachments"]}
    if attachment_path not in attachment_paths:
        raise ContractError(f"radiometric {name} comparison attachment is not hash-listed")
    attachment_entry = next(
        value
        for value in bundles[str(attachment_bundle_id)]["attachments"]
        if value["path"] == attachment_path
    )
    attachment_file = resolve_evidence_bundle(root, str(attachment_bundle_id)).parent / str(attachment_path)
    comparison = _load_json(attachment_file)
    comparison_keys = {
        "schema_version",
        "comparison_id",
        "kind",
        "artifact_set_id",
        "claim_id",
        "official_bundle_id",
        "reimplementation_bundle_id",
        "official_artifact_ids",
        "converter_identities",
        "unit",
        "calibration_environment",
        "dimensions",
        "frame_correlation",
        "live_provenance",
        "samples",
        "computed",
    }
    _require_exact_keys(comparison, comparison_keys, f"radiometric {name} comparison attachment")
    if (
        comparison.get("schema_version") != 1
        or not isinstance(comparison.get("comparison_id"), str)
        or not comparison["comparison_id"]
        or comparison.get("kind") != name
        or comparison.get("artifact_set_id") != _official_artifact_set_id(root)
        or comparison.get("claim_id") != claim_id
    ):
        raise ContractError(f"radiometric {name} comparison attachment identity is invalid")
    official_bundle_id = comparison.get("official_bundle_id")
    reimplementation_bundle_id = comparison.get("reimplementation_bundle_id")
    if official_bundle_id not in official_ids or reimplementation_bundle_id not in reimplementation_ids:
        raise ContractError(f"radiometric {name} comparison swaps or mislabels official/reimplementation evidence")

    artifact_manifest = _load_json(root / RESEARCH_REL / "governance/official-artifacts.json")
    known_artifact_ids = {
        str(value.get("artifact_id"))
        for value in artifact_manifest.get("artifacts", [])
        if isinstance(value, dict) and isinstance(value.get("artifact_id"), str)
    }
    comparison_artifact_ids = set(
        _require_string_list(comparison.get("official_artifact_ids"), f"radiometric {name} official artifact IDs")
    )
    if not comparison_artifact_ids.issubset(known_artifact_ids):
        raise ContractError(f"radiometric {name} comparison cites unknown official artifact identities")

    def validate_attachment_reference(reference: Any, label: str) -> tuple[str, str]:
        if not isinstance(reference, dict):
            raise ContractError(f"{label} must be a bundle attachment reference")
        _require_exact_keys(reference, {"bundle_id", "path"}, label)
        reference_bundle_id = reference.get("bundle_id")
        reference_path = reference.get("path")
        if reference_bundle_id not in bundles or not isinstance(reference_path, str) or not reference_path:
            raise ContractError(f"{label} is not part of the comparison evidence set")
        if reference_path not in {str(value["path"]) for value in bundles[str(reference_bundle_id)]["attachments"]}:
            raise ContractError(f"{label} is not hash-listed by its bundle")
        return str(reference_bundle_id), reference_path

    identities = comparison.get("converter_identities")
    if not isinstance(identities, dict):
        raise ContractError(f"radiometric {name} converter identities are missing")
    _require_exact_keys(
        identities,
        {"official_artifact_id", "reimplementation_attachment"},
        f"radiometric {name} converter identities",
    )
    if identities.get("official_artifact_id") not in comparison_artifact_ids:
        raise ContractError(f"radiometric {name} official converter identity is not frozen")
    converter_bundle_id, _ = validate_attachment_reference(
        identities.get("reimplementation_attachment"),
        f"radiometric {name} reimplementation converter identity",
    )
    if converter_bundle_id != reimplementation_bundle_id:
        raise ContractError(f"radiometric {name} reimplementation converter identity uses the wrong bundle")
    if comparison.get("unit") != "celsius":
        raise ContractError(f"radiometric {name} comparison unit is not Celsius")

    calibration = comparison.get("calibration_environment")
    if not isinstance(calibration, dict):
        raise ContractError(f"radiometric {name} calibration/environment record is missing")
    _require_exact_keys(
        calibration,
        {"inputs_attachment", "emissivity", "ambient_temperature_c", "distance_m", "relative_humidity_percent"},
        f"radiometric {name} calibration/environment",
    )
    validate_attachment_reference(calibration.get("inputs_attachment"), f"radiometric {name} calibration inputs")
    emissivity = _require_finite_number(calibration.get("emissivity"), f"radiometric {name} emissivity")
    _require_finite_number(calibration.get("ambient_temperature_c"), f"radiometric {name} ambient temperature", minimum=-273.15)
    _require_finite_number(calibration.get("distance_m"), f"radiometric {name} distance")
    humidity = _require_finite_number(
        calibration.get("relative_humidity_percent"),
        f"radiometric {name} relative humidity",
    )
    if not 0 < emissivity <= 1 or humidity > 100:
        raise ContractError(f"radiometric {name} calibration/environment values are out of range")

    dimensions = comparison.get("dimensions")
    if not isinstance(dimensions, dict):
        raise ContractError(f"radiometric {name} dimensions/stride are missing")
    _require_exact_keys(dimensions, {"width", "height", "stride"}, f"radiometric {name} dimensions")
    if any(type(dimensions.get(field)) is not int or dimensions[field] <= 0 for field in dimensions):
        raise ContractError(f"radiometric {name} dimensions/stride are invalid")
    if dimensions["stride"] < dimensions["width"]:
        raise ContractError(f"radiometric {name} stride is smaller than width")

    correlation = comparison.get("frame_correlation")
    if not isinstance(correlation, dict):
        raise ContractError(f"radiometric {name} frame correlation is missing")
    _require_exact_keys(
        correlation,
        {"official_frame_id", "reimplementation_frame_id", "correlation_id"},
        f"radiometric {name} frame correlation",
    )
    if any(not isinstance(correlation.get(field), str) or not correlation[field] for field in correlation):
        raise ContractError(f"radiometric {name} frame correlation is incomplete")

    live_provenance = comparison.get("live_provenance")
    if name == "fixture":
        if live_provenance is not None:
            raise ContractError("radiometric fixture comparison cannot claim live provenance")
    else:
        if not isinstance(live_provenance, dict):
            raise ContractError("radiometric live comparison lacks callback/frame provenance")
        _require_exact_keys(
            live_provenance,
            {"callback_count", "frame_counter", "accepted_frame", "preview_updated", "camera_fingerprint"},
            "radiometric live provenance",
        )
        for field in ("callback_count", "frame_counter"):
            if type(live_provenance.get(field)) is not int or live_provenance[field] <= 0:
                raise ContractError(f"radiometric live provenance {field} did not advance")
        if live_provenance.get("accepted_frame") is not True or live_provenance.get("preview_updated") is not True:
            raise ContractError("radiometric live provenance lacks accepted frame/preview proof")
        camera_fingerprint = live_provenance.get("camera_fingerprint")
        if not isinstance(camera_fingerprint, str) or not camera_fingerprint:
            raise ContractError("radiometric live provenance lacks camera fingerprint")
        if any(
            bundles[bundle_id]["environment"].get("camera_fingerprint") != camera_fingerprint
            for bundle_id in (str(official_bundle_id), str(reimplementation_bundle_id))
        ):
            raise ContractError("radiometric live provenance camera fingerprint disagrees with evidence")

    samples = comparison.get("samples")
    if not isinstance(samples, list) or len(samples) < 2:
        raise ContractError(f"radiometric {name} comparison has fewer than two measured pairs")
    errors: list[float] = []
    sample_ids: set[str] = set()
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ContractError(f"radiometric {name} sample {index} is not an object")
        _require_exact_keys(sample, {"sample_id", "official_c", "reimplementation_c"}, f"radiometric {name} sample {index}")
        sample_id = sample.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id or sample_id in sample_ids:
            raise ContractError(f"radiometric {name} sample IDs are invalid/duplicated")
        sample_ids.add(sample_id)
        official_c = _require_finite_number(sample.get("official_c"), f"radiometric {name} sample official_c", minimum=-273.15)
        reimplementation_c = _require_finite_number(
            sample.get("reimplementation_c"),
            f"radiometric {name} sample reimplementation_c",
            minimum=-273.15,
        )
        errors.append(abs(official_c - reimplementation_c))
    computed_count = len(errors)
    computed_mean = sum(errors) / computed_count
    computed_maximum = max(errors)
    computed = comparison.get("computed")
    if not isinstance(computed, dict):
        raise ContractError(f"radiometric {name} computed metrics are missing")
    _require_exact_keys(computed, {"sample_count", "mean_error_c", "max_pixel_error_c"}, f"radiometric {name} computed metrics")
    attachment_mean = _require_finite_number(computed.get("mean_error_c"), f"radiometric {name} attachment mean")
    attachment_maximum = _require_finite_number(computed.get("max_pixel_error_c"), f"radiometric {name} attachment maximum")
    if (
        computed.get("sample_count") != computed_count
        or item["sample_count"] != computed_count
        or not math.isclose(attachment_mean, computed_mean, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(attachment_maximum, computed_maximum, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(declared_mean, computed_mean, rel_tol=0.0, abs_tol=1e-12)
        or not math.isclose(declared_maximum, computed_maximum, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ContractError(f"radiometric {name} declared metrics are not derived from measured pairs")
    if computed_mean > 0.1 or computed_maximum > 0.5:
        raise ContractError(f"radiometric {name} tolerances failed: mean={computed_mean}, max={computed_maximum}")
    comparison_record = {
        "kind": name,
        "bundle_id": str(attachment_bundle_id),
        "path": str(attachment_path),
        "sha256": str(attachment_entry["sha256"]),
    }
    return bundle_ids, observed_claims, comparison_record


def validate_radiometric_truthfulness(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "reproduction/radiometric-validation.json"
    data = _load_json(path)
    required = {
        "schema_version",
        "validation_id",
        "artifact_set_id",
        "proof_claim_ids",
        "fixture",
        "live",
        "e5_conclusion_bundle_ids",
        "conclusion_attachment",
        "celsius_publication_allowed",
        "independent_review_id",
    }
    _require_exact_keys(data, required, "radiometric validation")
    validation_id = data.get("validation_id")
    if (
        data.get("schema_version") != 1
        or not isinstance(validation_id, str)
        or not validation_id
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
    ):
        raise ContractError("radiometric validation identity/artifact set is invalid")
    proof_claim_ids = data.get("proof_claim_ids")
    if not isinstance(proof_claim_ids, dict):
        raise ContractError("radiometric validation proof claim map is missing")
    _require_exact_keys(proof_claim_ids, RADIOMETRIC_PROOF_KEYS, "radiometric validation proof claims")
    if any(not isinstance(value, str) or not CLAIM_ID_RE.fullmatch(value) for value in proof_claim_ids.values()):
        raise ContractError("radiometric validation proof claim map contains invalid IDs")
    if len(set(proof_claim_ids.values())) != len(proof_claim_ids):
        raise ContractError("radiometric validation proof claims must be distinct")

    fixture_ids, fixture_claims, fixture_record = _validate_radiometric_comparison(root, "fixture", data.get("fixture"))
    live_ids, live_claims, live_record = _validate_radiometric_comparison(root, "live", data.get("live"))
    if data["fixture"]["claim_id"] != proof_claim_ids["fixture_official_reimplementation_comparison"]:
        raise ContractError("radiometric fixture comparison uses the wrong proof claim")
    if data["live"]["claim_id"] != proof_claim_ids["live_official_reimplementation_comparison"]:
        raise ContractError("radiometric live comparison uses the wrong proof claim")

    conclusion_ids = _require_string_list(data.get("e5_conclusion_bundle_ids"), "radiometric E5 conclusion bundle IDs")
    conclusion_claims: set[str] = set()
    conclusion_bundles: dict[str, Mapping[str, Any]] = {}
    for bundle_id in conclusion_ids:
        _, bundle = validate_evidence_bundle(root, bundle_id)
        if bundle.get("evidence_tier") != "E5":
            raise ContractError(f"radiometric conclusion bundle {bundle_id} is not E5")
        conclusion_bundles[bundle_id] = bundle
        conclusion_claims.update(bundle["claim_ids"])
    required_claims = set(proof_claim_ids.values())
    all_claims = fixture_claims | live_claims | conclusion_claims
    if not required_claims.issubset(all_claims) or not required_claims.issubset(conclusion_claims):
        raise ContractError("radiometric E5 conclusion does not cover all eight publication proofs")
    conclusion_reference = data.get("conclusion_attachment")
    if not isinstance(conclusion_reference, dict):
        raise ContractError("radiometric E5 conclusion attachment is missing")
    _require_exact_keys(conclusion_reference, {"bundle_id", "path"}, "radiometric E5 conclusion attachment")
    conclusion_bundle_id = conclusion_reference.get("bundle_id")
    conclusion_path = conclusion_reference.get("path")
    if conclusion_bundle_id not in conclusion_bundles or not isinstance(conclusion_path, str) or not conclusion_path:
        raise ContractError("radiometric E5 conclusion attachment is not in an E5 conclusion bundle")
    conclusion_entries = {
        str(value["path"]): value for value in conclusion_bundles[str(conclusion_bundle_id)]["attachments"]
    }
    if conclusion_path not in conclusion_entries:
        raise ContractError("radiometric E5 conclusion attachment is not hash-listed")
    conclusion_document = _load_json(resolve_evidence_bundle(root, str(conclusion_bundle_id)).parent / conclusion_path)
    conclusion_keys = {
        "schema_version",
        "validation_id",
        "artifact_set_id",
        "proof_claim_ids",
        "comparison_records",
        "verdict",
        "celsius_publication_allowed",
    }
    _require_exact_keys(conclusion_document, conclusion_keys, "radiometric E5 conclusion document")
    if (
        conclusion_document.get("schema_version") != 1
        or conclusion_document.get("validation_id") != validation_id
        or conclusion_document.get("artifact_set_id") != _official_artifact_set_id(root)
        or conclusion_document.get("proof_claim_ids") != proof_claim_ids
        or conclusion_document.get("verdict") != "pass"
        or conclusion_document.get("celsius_publication_allowed") is not True
    ):
        raise ContractError("radiometric E5 conclusion document is self-inconsistent")
    comparison_records = conclusion_document.get("comparison_records")
    if not isinstance(comparison_records, list) or comparison_records != [fixture_record, live_record]:
        raise ContractError("radiometric E5 conclusion does not hash-link both derived comparisons")
    all_bundle_ids = list(dict.fromkeys((*fixture_ids, *live_ids, *conclusion_ids)))
    if data.get("celsius_publication_allowed") is not True:
        raise ContractError("Celsius publication is not allowed by the radiometric validation")
    review_id = data.get("independent_review_id")
    if not isinstance(review_id, str) or not REVIEW_ID_RE.fullmatch(review_id):
        raise ContractError("Celsius publication lacks a valid independent review ID")
    review_path, _ = validate_review(
        root,
        review_id,
        subject_id=validation_id,
        expected_bundle_ids=all_bundle_ids,
    )
    return (
        _relative(path, root),
        _relative(review_path, root),
        "publication_proofs=8/8",
        "fixture_mean<=0.1C_max<=0.5C",
        "live_mean<=0.1C_max<=0.5C",
        "celsius_publication_allowed=true",
    )


def validate_f2_live_e2e(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "dynamic/f2-live-e2e.json"
    data = _load_json(path)
    required = {
        "schema_version",
        "validation_id",
        "artifact_set_id",
        "passed",
        "checkpoint_bundle_ids",
        "checkpoint_results",
        "callback_count",
        "frame_counter",
        "preview_updated",
        "teardown_completed",
        "reconnect_recovered",
        "checkpoint_proof",
        "result_attachment",
        "independent_review_id",
    }
    _require_exact_keys(data, required, "F2 live E2E validation")
    validation_id = data.get("validation_id")
    if (
        data.get("schema_version") != 1
        or not isinstance(validation_id, str)
        or not validation_id
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
        or data.get("passed") is not True
    ):
        raise ContractError("F2 live E2E validation identity/result is invalid")
    checkpoint_results = data.get("checkpoint_results")
    checkpoint_bundles = data.get("checkpoint_bundle_ids")
    if not isinstance(checkpoint_results, dict) or not isinstance(checkpoint_bundles, dict):
        raise ContractError("F2 live E2E checkpoint maps are missing")
    _require_exact_keys(checkpoint_results, frozenset(F2_CHECKPOINTS), "F2 checkpoint results")
    _require_exact_keys(checkpoint_bundles, frozenset(F2_CHECKPOINTS), "F2 checkpoint evidence")
    declared_checkpoint_bundle_ids = {
        checkpoint: set(
            _require_string_list(checkpoint_bundles[checkpoint], f"F2 checkpoint {checkpoint} evidence")
        )
        for checkpoint in F2_CHECKPOINTS
    }
    declared_bundle_union = set().union(*declared_checkpoint_bundle_ids.values())
    checkpoint_proof_reference = data.get("checkpoint_proof")
    proof_reference_bundle = (
        str(checkpoint_proof_reference.get("bundle_id"))
        if isinstance(checkpoint_proof_reference, dict)
        else ""
    )
    proof, official_bundle_ids, _, _, proof_sha256 = _validate_f2_checkpoint_proof(
        root,
        checkpoint_proof_reference,
        allowed_bundle_ids=declared_bundle_union | {proof_reference_bundle},
        require_terminal=True,
    )
    result_reference = data.get("result_attachment")
    if not isinstance(result_reference, dict):
        raise ContractError("F2 live E2E result attachment is missing")
    _require_exact_keys(result_reference, {"bundle_id", "path"}, "F2 live E2E result attachment")
    result_bundle_id = result_reference.get("bundle_id")
    result_path = result_reference.get("path")
    if not isinstance(result_bundle_id, str) or not isinstance(result_path, str) or not result_path:
        raise ContractError("F2 live E2E result attachment reference is invalid")
    result_file, _, result_bundle = resolve_evidence_attachment(
        root,
        result_bundle_id,
        result_path,
        media_type="application/json",
    )
    if result_bundle.get("evidence_tier") != "E5":
        raise ContractError("F2 live E2E result attachment is not an E5 verified conclusion")
    result = _load_json(result_file)
    result_keys = {
        "schema_version",
        "validation_id",
        "artifact_set_id",
        "checkpoint_proof_sha256",
        "reimplementation_checkpoints",
        "outcomes",
        "verdict",
        "canonical_sha256",
    }
    _require_exact_keys(result, result_keys, "F2 live E2E result document")
    canonical_result = dict(result)
    canonical_result.pop("canonical_sha256", None)
    if (
        result.get("schema_version") != 1
        or result.get("validation_id") != validation_id
        or result.get("artifact_set_id") != _official_artifact_set_id(root)
        or result.get("checkpoint_proof_sha256") != proof_sha256
        or result.get("verdict") != "pass"
        or result.get("canonical_sha256")
        != _sha256_bytes(
            json.dumps(canonical_result, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
    ):
        raise ContractError("F2 live E2E result identity/hash/verdict is invalid")
    reimplementation = result.get("reimplementation_checkpoints")
    if not isinstance(reimplementation, dict):
        raise ContractError("F2 live E2E reimplementation checkpoint map is missing")
    _require_exact_keys(reimplementation, frozenset(F2_CHECKPOINTS), "F2 reimplementation checkpoints")
    all_bundle_ids = set(official_bundle_ids) | {result_bundle_id}
    official_rows = {str(row["checkpoint_id"]): row for row in proof["checkpoints"]}
    checkpoint_claim_ids: set[str] = set()
    reimplementation_run_ids: set[str] = set()
    for checkpoint in F2_CHECKPOINTS:
        item = reimplementation[checkpoint]
        label = f"F2 reimplementation checkpoint {checkpoint}"
        if not isinstance(item, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(item, {"claim_id", "run_id", "evidence_bundle_ids", "event_refs"}, label)
        claim_id = item.get("claim_id")
        run_id = item.get("run_id")
        if claim_id != official_rows[checkpoint]["claim_id"] or claim_id in checkpoint_claim_ids:
            raise ContractError(f"{label} does not use its unique official checkpoint claim")
        checkpoint_claim_ids.add(str(claim_id))
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise ContractError(f"{label} has invalid run_id")
        run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
        if not run_path.is_file():
            raise ContractError(f"{label} run manifest is missing")
        _, run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
        if run.get("source_variant") != "reimplementation":
            raise ContractError(f"{label} is not from a reimplementation run")
        official_run_id = str(official_rows[checkpoint]["run_id"])
        official_run_path = root / RESEARCH_REL / "dynamic/runs" / official_run_id / "manifest.json"
        _, official_run = validate_run_manifest(
            root,
            _relative(official_run_path, root),
            expected_run_id=official_run_id,
        )
        if run.get("environment") != official_run.get("environment"):
            raise ContractError(f"{label} target environment differs from its official checkpoint run")
        reimplementation_run_ids.add(run_id)
        bundle_ids = set(_require_string_list(item.get("evidence_bundle_ids"), f"{label} evidence_bundle_ids"))
        event_refs = item.get("event_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ContractError(f"{label} has no normalized event proof")
        referenced_bundle_ids: set[str] = set()
        referenced_event_ids: set[str] = set()
        reimplementation_correlations: set[str] = set()
        for ref_index, event_ref in enumerate(event_refs):
            bundle_id, bundle, events = _resolve_normalized_event_reference(
                root,
                event_ref,
                label=f"{label} event ref {ref_index}",
                allowed_bundle_ids=bundle_ids,
            )
            if (
                bundle.get("evidence_tier") != "E4"
                or bundle.get("source_variant") != "reimplementation"
                or claim_id not in bundle["claim_ids"]
            ):
                raise ContractError(f"{label} evidence is not E4 proof from its run/claim")
            _validate_evidence_run_binding(
                root,
                bundle_id,
                bundle,
                run,
                label=label,
                events=events,
            )
            referenced_bundle_ids.add(bundle_id)
            for event in events:
                if (
                    event.get("checkpoint_id") != checkpoint
                    or event.get("run_id") != run_id
                    or claim_id not in event["claim_ids"]
                    or event["event_id"] in referenced_event_ids
                ):
                    raise ContractError(f"{label} event is not unique checkpoint-specific proof")
                referenced_event_ids.add(str(event["event_id"]))
                reimplementation_correlations.add(str(event["correlation_id"]))
        if referenced_bundle_ids != bundle_ids:
            raise ContractError(f"{label} does not consume every declared E4 bundle")
        official_checkpoint_ids = set(official_rows[checkpoint]["evidence_bundle_ids"])
        official_correlations: set[str] = set()
        for ref_index, event_ref in enumerate(official_rows[checkpoint]["event_refs"]):
            _, _, events = _resolve_normalized_event_reference(
                root,
                event_ref,
                label=f"F2 official checkpoint {checkpoint} event ref {ref_index}",
                allowed_bundle_ids=official_checkpoint_ids,
            )
            official_correlations.update(str(event["correlation_id"]) for event in events)
        if not official_correlations.intersection(reimplementation_correlations):
            raise ContractError(f"{label} is not correlated to its official checkpoint proof")
        expected_checkpoint_ids = official_checkpoint_ids | bundle_ids
        if declared_checkpoint_bundle_ids[checkpoint] != expected_checkpoint_ids:
            raise ContractError(f"F2 checkpoint {checkpoint} top-level evidence map is not derived")
        all_bundle_ids.update(bundle_ids)
    if any(value is not True for value in checkpoint_results.values()):
        raise ContractError("F2 live E2E has a failed/unobserved checkpoint")

    outcomes = result.get("outcomes")
    outcome_keys = {"callback_count", "frame_counter", "preview_updated", "teardown_completed", "reconnect_recovered"}
    if not isinstance(outcomes, dict):
        raise ContractError("F2 live E2E outcome proofs are missing")
    _require_exact_keys(outcomes, outcome_keys, "F2 live E2E outcome proofs")
    derived_outcomes: dict[str, int | bool] = {}
    outcome_claim_ids: set[str] = set()
    for outcome_name in sorted(outcome_keys):
        outcome = outcomes[outcome_name]
        label = f"F2 live E2E outcome {outcome_name}"
        if not isinstance(outcome, dict):
            raise ContractError(f"{label} is not an object")
        _require_exact_keys(outcome, {"claim_id", "evidence_bundle_ids", "event_refs"}, label)
        claim_id = outcome.get("claim_id")
        if not isinstance(claim_id, str) or not CLAIM_ID_RE.fullmatch(claim_id) or claim_id in outcome_claim_ids:
            raise ContractError(f"{label} has invalid/duplicate claim_id")
        outcome_claim_ids.add(claim_id)
        bundle_ids = set(_require_string_list(outcome.get("evidence_bundle_ids"), f"{label} evidence_bundle_ids"))
        event_refs = outcome.get("event_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ContractError(f"{label} has no normalized event proof")
        values: list[Any] = []
        referenced_bundle_ids: set[str] = set()
        for ref_index, event_ref in enumerate(event_refs):
            bundle_id, bundle, events = _resolve_normalized_event_reference(
                root,
                event_ref,
                label=f"{label} event ref {ref_index}",
                allowed_bundle_ids=bundle_ids,
            )
            if (
                bundle.get("evidence_tier") != "E4"
                or bundle.get("source_variant") != "reimplementation"
                or claim_id not in bundle["claim_ids"]
            ):
                raise ContractError(f"{label} claim is not backed by live E4 reimplementation evidence")
            event_run_ids = {str(event.get("run_id")) for event in events if event.get("run_id") is not None}
            if len(event_run_ids) != 1 or not event_run_ids.issubset(reimplementation_run_ids):
                raise ContractError(f"{label} evidence is not bound to one validated reimplementation run")
            outcome_run_id = next(iter(event_run_ids))
            outcome_run_path = root / RESEARCH_REL / "dynamic/runs" / outcome_run_id / "manifest.json"
            _, outcome_run = validate_run_manifest(
                root,
                _relative(outcome_run_path, root),
                expected_run_id=outcome_run_id,
            )
            _validate_evidence_run_binding(
                root,
                bundle_id,
                bundle,
                outcome_run,
                label=label,
                events=events,
            )
            referenced_bundle_ids.add(bundle_id)
            for event in events:
                if (
                    event.get("event_type") != outcome_name
                    or event.get("run_id") not in reimplementation_run_ids
                    or claim_id not in event["claim_ids"]
                ):
                    raise ContractError(f"{label} cites an unrelated normalized event")
                values.append(event.get("value"))
        if referenced_bundle_ids != bundle_ids or not values:
            raise ContractError(f"{label} does not consume every declared evidence bundle")
        if outcome_name in {"callback_count", "frame_counter"}:
            if (
                len(values) < 2
                or any(type(value) is not int or value < 0 for value in values)
                or max(int(value) for value in values) <= min(int(value) for value in values)
            ):
                raise ContractError(f"{label} does not prove measured counter advancement")
            derived_outcomes[outcome_name] = max(int(value) for value in values)
        else:
            if any(value is not True for value in values):
                raise ContractError(f"{label} has a non-passing measured result")
            derived_outcomes[outcome_name] = True
        all_bundle_ids.update(bundle_ids)
    for field, derived in derived_outcomes.items():
        if data.get(field) != derived:
            raise ContractError(f"F2 live E2E {field} is not derived from normalized events")
    if not (checkpoint_claim_ids | outcome_claim_ids).issubset(set(result_bundle["claim_ids"])):
        raise ContractError("F2 E5 result bundle does not conclude every checkpoint/outcome claim")
    review_path, _ = validate_review(
        root,
        str(data.get("independent_review_id", "")),
        subject_id=validation_id,
        expected_bundle_ids=sorted(all_bundle_ids),
    )
    return (_relative(path, root), _relative(review_path, root), "f2_checkpoints=12/12", "callback_and_frame_counts_advanced=true")


def validate_evidence_replay(root: Path, required_source_bundle_ids: Sequence[str]) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "reproduction/evidence-replay.json"
    data = _load_json(path)
    required = {"schema_version", "replay_id", "artifact_set_id", "passed", "results", "independent_review_id"}
    _require_exact_keys(data, required, "evidence replay result")
    replay_id = data.get("replay_id")
    if (
        data.get("schema_version") != 1
        or not isinstance(replay_id, str)
        or not replay_id
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
        or data.get("passed") is not True
    ):
        raise ContractError("evidence replay identity/result is invalid")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ContractError("evidence replay has no results")
    source_ids: list[str] = []
    all_review_bundle_ids: list[str] = []
    result_ids: set[str] = set()
    output_paths: set[Path] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise ContractError(f"evidence replay result {index} is not an object")
        _require_exact_keys(
            result,
            {
                "source_bundle_id",
                "result_bundle_id",
                "run_id",
                "replay_command",
                "exit_code",
                "output_attachment",
            },
            f"evidence replay result {index}",
        )
        source_id = result.get("source_bundle_id")
        result_id = result.get("result_bundle_id")
        if not isinstance(source_id, str) or not isinstance(result_id, str):
            raise ContractError(f"evidence replay result {index} lacks bundle IDs")
        _, source_bundle = validate_evidence_bundle(root, source_id)
        _, result_bundle = validate_evidence_bundle(root, result_id)
        if (
            result_bundle.get("evidence_tier") != "E4"
            or result_bundle.get("source_variant") != "reimplementation"
            or result_id in result_ids
            or set(result_bundle["claim_ids"]) != set(source_bundle["claim_ids"])
        ):
            raise ContractError(f"evidence replay result {index} is not independent replay evidence")
        result_ids.add(result_id)
        replay_command = result.get("replay_command")
        _resolve_replay_command_target(root, replay_command, f"evidence replay result {index} replay command")
        if replay_command not in source_bundle["replay_commands"] or replay_command not in result_bundle["replay_commands"]:
            raise ContractError(f"evidence replay result {index} did not use a declared replay command")
        run_id = result.get("run_id")
        if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
            raise ContractError(f"evidence replay result {index} has an invalid replay run ID")
        run_path = root / RESEARCH_REL / "dynamic/runs" / run_id / "manifest.json"
        _, replay_run = validate_run_manifest(root, _relative(run_path, root), expected_run_id=run_id)
        if replay_run.get("source_variant") != "reimplementation" or replay_command not in replay_run["commands"]:
            raise ContractError(f"evidence replay result {index} is not backed by a completed replay run")
        if type(result.get("exit_code")) is not int or result["exit_code"] != 0:
            raise ContractError(f"evidence replay result {index} did not exit successfully")
        attachment = result.get("output_attachment")
        if not isinstance(attachment, str) or not attachment:
            raise ContractError(f"evidence replay result {index} output is not hash-backed")
        output_path, _, _ = resolve_evidence_attachment(
            root,
            result_id,
            attachment,
            media_type="application/json",
        )
        if output_path in output_paths:
            raise ContractError(f"evidence replay result {index} reuses another replay output")
        output_paths.add(output_path)

        source_event_path, _, _ = resolve_evidence_attachment(
            root,
            source_id,
            str(source_bundle["event_stream"]["normalized_attachment"]),
            media_type="application/json",
        )
        source_event_document = _load_json(source_event_path)
        source_events = _validate_normalized_event_document(source_event_path, bundle=source_bundle)
        replay_output = _load_json(output_path)
        output_keys = {
            "schema_version",
            "replay_id",
            "artifact_set_id",
            "source_bundle_id",
            "result_bundle_id",
            "run_id",
            "replay_command",
            "exit_code",
            "source_manifest_sha256",
            "source_normalized_sha256",
            "replayed_events",
            "derived_claim_ids",
            "assertions",
            "canonical_sha256",
        }
        _require_exact_keys(replay_output, output_keys, f"evidence replay result {index} output document")
        canonical_output = dict(replay_output)
        canonical_output.pop("canonical_sha256", None)
        assertions = replay_output.get("assertions")
        assertion_keys = {"attachment_hashes_verified", "normalization_deterministic", "claims_derivable"}
        if not isinstance(assertions, dict):
            raise ContractError(f"evidence replay result {index} has no derived assertions")
        _require_exact_keys(assertions, assertion_keys, f"evidence replay result {index} assertions")
        if (
            replay_output.get("schema_version") != 1
            or replay_output.get("replay_id") != replay_id
            or replay_output.get("artifact_set_id") != _official_artifact_set_id(root)
            or replay_output.get("source_bundle_id") != source_id
            or replay_output.get("result_bundle_id") != result_id
            or replay_output.get("run_id") != run_id
            or replay_output.get("replay_command") != replay_command
            or replay_output.get("exit_code") != 0
            or replay_output.get("source_manifest_sha256") != source_bundle["manifest_sha256"]
            or replay_output.get("source_normalized_sha256") != source_event_document["canonical_sha256"]
            or replay_output.get("replayed_events") != source_events
            or replay_output.get("derived_claim_ids") != sorted(source_bundle["claim_ids"])
            or any(value is not True for value in assertions.values())
            or replay_output.get("canonical_sha256")
            != _sha256_bytes(
                json.dumps(canonical_output, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
        ):
            raise ContractError(f"evidence replay result {index} is not derived from its source bundle")
        result_event_path, _, _ = resolve_evidence_attachment(
            root,
            result_id,
            str(result_bundle["event_stream"]["normalized_attachment"]),
            media_type="application/json",
        )
        result_events = _validate_normalized_event_document(result_event_path, bundle=result_bundle)
        _validate_evidence_run_binding(
            root,
            result_id,
            result_bundle,
            replay_run,
            label=f"evidence replay result {index}",
            events=result_events,
        )
        expected_replayed_hash = _sha256_bytes(
            json.dumps(source_events, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        replay_execution_events = [
            event
            for event in result_events
            if event.get("event_type") == "evidence_replay"
            and isinstance(event.get("value"), dict)
            and event["value"].get("source_bundle_id") == source_id
            and event["value"].get("replay_command") == replay_command
            and event["value"].get("exit_code") == 0
            and event["value"].get("replayed_events_sha256") == expected_replayed_hash
            and set(source_bundle["claim_ids"]).issubset(set(event["claim_ids"]))
        ]
        if len(replay_execution_events) != 1 or result_bundle["event_stream"]["dropped_events"] != 0 or result_bundle["event_stream"]["truncated_events"] != 0:
            raise ContractError(f"evidence replay result {index} lacks one loss-free replay execution event")
        source_captured = datetime.fromisoformat(str(source_bundle["captured_at"]).replace("Z", "+00:00"))
        result_captured = datetime.fromisoformat(str(result_bundle["captured_at"]).replace("Z", "+00:00"))
        if result_captured < source_captured:
            raise ContractError(f"evidence replay result {index} predates its source evidence")
        source_ids.append(source_id)
        all_review_bundle_ids.extend((source_id, result_id))
    if set(source_ids) != set(required_source_bundle_ids) or len(source_ids) != len(set(source_ids)):
        raise ContractError("evidence replay source set does not exactly cover the canonical ledger bundles")
    review_path, _ = validate_review(
        root,
        str(data.get("independent_review_id", "")),
        subject_id=replay_id,
        expected_bundle_ids=list(dict.fromkeys(all_review_bundle_ids)),
    )
    return (_relative(path, root), _relative(review_path, root), f"replayed_bundles={len(source_ids)}")


def validate_final_deliverable_reviews(
    root: Path,
    expected_bundle_ids: Mapping[str, Sequence[str]],
    producer_ids: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "reviews/final-approvals.json"
    data = _load_json(path)
    required = {
        "schema_version",
        "approval_id",
        "artifact_set_id",
        "deliverable_review_ids",
        "public_material_review_id",
    }
    _require_exact_keys(data, required, "final deliverable approvals")
    if (
        data.get("schema_version") != 1
        or not isinstance(data.get("approval_id"), str)
        or not data["approval_id"]
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
    ):
        raise ContractError("final deliverable approvals identity/artifact set is invalid")
    review_ids = data.get("deliverable_review_ids")
    subjects = {
        "official_behavior_dossier": "official-behavior-dossier",
        "source_independent_specification": "source-independent-specification",
        "independent_reproduction": "independent-reproduction",
    }
    if not isinstance(review_ids, dict):
        raise ContractError("final deliverable review map is missing")
    _require_exact_keys(review_ids, frozenset(subjects), "final deliverable review map")
    observed_paths: list[str] = []
    observed_review_ids: list[str] = []
    observed_reviewer_ids: list[str] = []
    for deliverable, subject in subjects.items():
        required_bundles = list(expected_bundle_ids.get(deliverable, ()))
        if not required_bundles:
            raise ContractError(f"final approval has no derived evidence set for {deliverable}")
        review_path, review = validate_review(
            root,
            str(review_ids[deliverable]),
            subject_id=subject,
            expected_bundle_ids=required_bundles,
            producer_ids=producer_ids.get(deliverable, ()),
        )
        observed_paths.append(_relative(review_path, root))
        observed_review_ids.append(str(review_ids[deliverable]))
        observed_reviewer_ids.append(str(review["reviewer_id"]).casefold())
    public_review_id = data.get("public_material_review_id")
    all_bundle_ids = sorted({bundle_id for values in expected_bundle_ids.values() for bundle_id in values})
    all_producers = sorted({producer_id for values in producer_ids.values() for producer_id in values})
    public_review_path, public_review = validate_review(
        root,
        str(public_review_id),
        subject_id="public-proprietary-material-boundary",
        expected_bundle_ids=all_bundle_ids,
        producer_ids=all_producers,
    )
    observed_paths.append(_relative(public_review_path, root))
    observed_review_ids.append(str(public_review_id))
    observed_reviewer_ids.append(str(public_review["reviewer_id"]).casefold())
    if len(set(observed_review_ids)) != 4 or len(set(observed_reviewer_ids)) != 4:
        raise ContractError("final deliverables and public-material boundary lack four distinct independent reviews/reviewers")
    return (
        _relative(path, root),
        *observed_paths,
        "independent_deliverable_reviews=3/3",
        "public_material_review=pass",
    )


def validate_closure(root: Path) -> tuple[str, ...]:
    path = root / RESEARCH_REL / "closure/current.json"
    data = _load_json(path)
    required_top = {
        "schema_version",
        "artifact_set_id",
        "computed_from_ledger",
        "inventory_started",
        "counts_are_complete",
        "counters",
        "current_causal_frontier_count",
        "final_gates",
        "closure_allowed",
        "status",
        "reason",
    }
    _require_exact_keys(data, required_top, "whole-APK closure")
    if (
        data.get("schema_version") != 1
        or data.get("artifact_set_id") != _official_artifact_set_id(root)
        or not isinstance(data.get("status"), str)
        or not data["status"]
        or not isinstance(data.get("reason"), str)
        or not data["reason"]
    ):
        raise ContractError("whole-APK closure identity/artifact set is invalid")
    counters = data.get("counters")
    gates = data.get("final_gates")
    if data.get("inventory_started") is not True or data.get("counts_are_complete") is not True:
        raise ContractError("whole-APK closure counts are not complete")
    if not isinstance(counters, dict):
        raise ContractError("whole-APK closure counters are missing")
    _require_exact_keys(counters, COUNTER_KEYS, "whole-APK closure counters")
    if any(type(value) is not int or value != 0 for value in counters.values()):
        raise ContractError(f"whole-APK closure counters are not all zero: {counters}")
    if type(data.get("current_causal_frontier_count")) is not int or data["current_causal_frontier_count"] != 1:
        raise ContractError("closure requires exactly one evidence-backed causal frontier record")
    if not isinstance(gates, dict):
        raise ContractError("whole-APK final gate vector is missing")
    _require_exact_keys(gates, FINAL_GATE_KEYS, "whole-APK final gate vector")
    if any(value is not True for value in gates.values()):
        raise ContractError("whole-APK final gate vector is not entirely true")
    if data.get("closure_allowed") is not True:
        raise ContractError("closure_allowed is false")

    ledger_path = _resolve_local_path(
        root,
        data.get("computed_from_ledger"),
        "closure computed_from_ledger",
        allowed_root=RESEARCH_REL / "static",
    )
    canonical_ledger_path = (root / RESEARCH_REL / "static/ledger.json").resolve()
    if ledger_path != canonical_ledger_path:
        raise ContractError("closure computed_from_ledger does not resolve to the canonical whole-APK ledger")
    ledger = _load_json(ledger_path)
    rows = validate_ledger_document(root, ledger, require_verified=True, resolve_references=True)
    derived = {
        "blocked": sum(row["state"] == "blocked" for row in rows),
        "nonterminal": sum(row["state"] != "verified" for row in rows),
        "unclassified": sum(row["classification_status"] != "classified" for row in rows),
    }
    _, unresolved_claim_ids = validate_claim_graph(root)
    derived["unresolved_contradictions"] = len(unresolved_claim_ids)
    for key, value in derived.items():
        if counters[key] != value:
            raise ContractError(f"closure counter {key} does not match the canonical ledger: {counters[key]} != {value}")
    frontier_count = 1 if ledger.get("current_causal_frontier") is not None else 0
    if data["current_causal_frontier_count"] != frontier_count:
        raise ContractError("closure causal frontier count does not match the canonical ledger")

    validate_static_inventory_convergence(root)
    validate_dossiers_and_ledger(root)
    validate_dynamic_convergence(root)
    validate_f2_frontier(root)
    frontier_data = _load_json(root / RESEARCH_REL / "dynamic/f2-current-causal-frontier.json")
    if (
        frontier_data.get("last_proven_checkpoint") != F2_CHECKPOINTS[-1]
        or frontier_data.get("first_missing_checkpoint") != "none"
    ):
        raise ContractError("closure requires the canonical F2 causal frontier itself to be terminal 12/12")
    terminal_supporting_ids = set(
        _require_string_list(
            frontier_data.get("supporting_bundle_ids"),
            "terminal F2 causal frontier supporting bundle IDs",
        )
    )
    _validate_f2_checkpoint_proof(
        root,
        frontier_data.get("checkpoint_proof"),
        allowed_bundle_ids=terminal_supporting_ids,
        require_terminal=True,
    )
    validate_clean_specs_and_fixtures(root)
    validate_f2_live_e2e(root)
    f2_live_data = _load_json(root / RESEARCH_REL / "dynamic/f2-live-e2e.json")
    if f2_live_data.get("checkpoint_proof") != frontier_data.get("checkpoint_proof"):
        raise ContractError("closure F2 live result is not bound to the canonical terminal frontier proof")
    validate_radiometric_truthfulness(root)
    ledger_bundle_ids = sorted(
        {
            bundle_id
            for row in rows
            for bundle_id in (*row["evidence_bundle_ids"], *row["verification_ids"])
        }
    )
    validate_evidence_replay(root, ledger_bundle_ids)
    validate_premortems_and_independent_review(root)
    specification = _load_json(root / RESEARCH_REL / "specs/index.json")
    radiometric = _load_json(root / RESEARCH_REL / "reproduction/radiometric-validation.json")
    f2_live = _load_json(root / RESEARCH_REL / "dynamic/f2-live-e2e.json")
    replay = _load_json(root / RESEARCH_REL / "reproduction/evidence-replay.json")
    radiometric_bundle_ids = {
        bundle_id
        for section in (radiometric["fixture"], radiometric["live"])
        for bundle_id in section["evidence_bundle_ids"]
    } | set(radiometric["e5_conclusion_bundle_ids"])
    f2_bundle_ids = {
        bundle_id
        for bundle_ids in f2_live["checkpoint_bundle_ids"].values()
        for bundle_id in bundle_ids
    }
    replay_result_bundle_ids = {str(result["result_bundle_id"]) for result in replay["results"]}
    reproduction_bundle_ids = sorted(
        set(ledger_bundle_ids)
        | radiometric_bundle_ids
        | f2_bundle_ids
        | replay_result_bundle_ids
    )
    row_producers = sorted({str(row["owner"]) for row in rows})
    specification_author = str(specification["author_id"])
    validate_final_deliverable_reviews(
        root,
        {
            "official_behavior_dossier": ledger_bundle_ids,
            "source_independent_specification": list(specification["evidence_bundle_ids"]),
            "independent_reproduction": reproduction_bundle_ids,
        },
        {
            "official_behavior_dossier": row_producers,
            "source_independent_specification": [specification_author],
            "independent_reproduction": [*row_producers, specification_author],
        },
    )
    return (
        _relative(path, root),
        _relative(ledger_path, root),
        "all_closure_counters=0",
        f"final_gates_true={len(gates)}",
        "closure_supporting_evidence_validated=true",
        "closure_allowed=true",
    )


def validate_premortems_and_independent_review(root: Path) -> tuple[str, ...]:
    prd_path = root / ".omx/plans/prd-official-hikmicro-whole-apk-reverse-engineering-20260718.md"
    text = prd_path.read_text(encoding="utf-8") if prd_path.is_file() else ""
    match = re.search(r"## 10\. Exactly three pre-mortem scenarios\s+(.*?)(?:\n## 11\.)", text, re.DOTALL)
    if not match:
        raise ContractError("approved PRD pre-mortem section is missing")
    numbered = re.findall(r"(?m)^([1-9][0-9]*)\. \*\*", match.group(1))
    if numbered != ["1", "2", "3"]:
        raise ContractError(f"approved PRD must contain exactly three pre-mortems, got {numbered}")
    review_path = root / RESEARCH_REL / "reviews/independent-critic.json"
    review = _load_json(review_path)
    review_id = review.get("review_id")
    if not isinstance(review_id, str):
        raise ContractError("independent critic review lacks a review ID")
    resolved_review_path, _ = validate_review(root, review_id, subject_id="whole-apk-mission")
    if resolved_review_path.resolve() != review_path.resolve():
        raise ContractError("independent critic review ID resolves to a different file")
    return (_relative(prd_path, root), "premortems=3", _relative(review_path, root), "independent_critic=pass")


def _run_gate(gate_id: str, validator: Callable[[], tuple[str, ...]]) -> Gate:
    try:
        evidence = tuple(str(value) for value in validator())
        return Gate(gate_id=gate_id, passed=True, evidence=evidence, reasons=())
    except (ContractError, OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, IndexError) as exc:
        return Gate(gate_id=gate_id, passed=False, evidence=(), reasons=(str(exc),))


def evaluate(root: Path, mission: Mission, *, verify_current_baseline: bool = False) -> Mapping[str, Any]:
    root = root.resolve()
    gates = [
        _run_gate("mission_contract", lambda: validate_mission_contract(root, mission)),
        _run_gate("official_artifact_freeze", lambda: validate_official_artifact_freeze(root)),
        _run_gate(
            "current_implementation_baseline",
            lambda: validate_implementation_baseline(root, verify_current_files=verify_current_baseline),
        ),
        _run_gate("governance_and_truthfulness_contracts", lambda: validate_governance_contracts(root)),
        _run_gate("independent_static_inventory_convergence", lambda: validate_static_inventory_convergence(root)),
        _run_gate("ledger_and_13_dossiers_terminal", lambda: validate_dossiers_and_ledger(root)),
        _run_gate("untouched_instrumented_dynamic_convergence", lambda: validate_dynamic_convergence(root)),
        _run_gate("single_evidence_backed_f2_causal_frontier", lambda: validate_f2_frontier(root)),
        _run_gate("source_independent_specs_and_fixtures", lambda: validate_clean_specs_and_fixtures(root)),
        _run_gate("radiometric_no_fake_celsius", lambda: validate_radiometric_truthfulness(root)),
        _run_gate("zero_counters_and_final_gate_vector", lambda: validate_closure(root)),
        _run_gate("three_premortems_and_independent_critic", lambda: validate_premortems_and_independent_review(root)),
    ]
    passed_count = sum(gate.passed for gate in gates)
    passed = passed_count == len(gates)
    return {
        "gate_counts": {
            "failed": len(gates) - passed_count,
            "passed": passed_count,
            "total": len(gates),
        },
        "gates": [asdict(gate) for gate in gates],
        "mission": {
            "path": _relative(mission.path, root),
            "reported_status": mission.data.get("status"),
            "resolved_slug": mission.data.get("slug"),
            "topic": mission.data.get("topic"),
        },
        "passed": passed,
        "schema_version": 1,
        "truthfulness": {
            "completion_file_is_authoritative": False,
            "missing_evidence_is_failure": True,
            "success_requires_all_gates": True,
            "unobserved_success_claims": [],
        },
        "verdict": "pass" if passed else "fail",
    }


def _error_result(message: str) -> Mapping[str, Any]:
    return {
        "error": message,
        "passed": False,
        "schema_version": 1,
        "truthfulness": {
            "completion_file_is_authoritative": False,
            "missing_evidence_is_failure": True,
            "success_requires_all_gates": True,
            "unobserved_success_claims": [],
        },
        "verdict": "error",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", required=True, help="Mission path, stored slug, or full slugified topic")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=repository_root(),
        help="Repository root (defaults to the critic's repository)",
    )
    parser.add_argument(
        "--verify-current-baseline",
        action="store_true",
        help="Also require current shipping files to match the frozen G001 baseline",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repo_root.resolve()
    try:
        mission = resolve_mission(root, args.mission)
        result = evaluate(root, mission, verify_current_baseline=args.verify_current_baseline)
        exit_code = 0 if result["passed"] else 1
    except ContractError as exc:
        result = _error_result(str(exc))
        exit_code = 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
