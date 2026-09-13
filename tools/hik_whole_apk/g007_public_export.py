#!/usr/bin/env python3
"""Build and validate a deterministic, vendor-free G007 public specification ZIP."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


RESEARCH_REL = PurePosixPath(".omx/research/hikmicro-viewer-2.6.0")
G007_INDEX_REL = RESEARCH_REL / "specs/g007/index.json"
G007_STATUS_REL = RESEARCH_REL / "specs/g007/status.json"
G007_README_REL = RESEARCH_REL / "specs/g007/README.md"
FIXTURE_MANIFEST_REL = RESEARCH_REL / "reproduction/g007-fixtures-manifest.json"
OFFICIAL_HASH_MANIFEST_REL = PurePosixPath(
    "mobile/android/app/src/test/evidence/"
    "HIKMICRO_VIEWER_2_6_0_OFFICIAL_ARTIFACT_SHA256.tsv"
)
VALIDATOR_REL = PurePosixPath("tools/hik_whole_apk/g007_spec_validator.py")
PUBLIC_MANIFEST = "PUBLICATION-MANIFEST.json"
PUBLIC_README = "README.md"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = stat.S_IFREG | 0o644
MAX_ENTRY_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_ARCHIVE_FILE_BYTES = MAX_ARCHIVE_BYTES + 8 * 1024 * 1024
EXPECTED_PAYLOAD_FILES = 66
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

AUTHORITY_INDEX_RELS = (
    RESEARCH_REL / "dossiers/index.json",
    RESEARCH_REL / "claims/index.json",
    RESEARCH_REL / "evidence/index.json",
    RESEARCH_REL / "specs/index.json",
    RESEARCH_REL / "reproduction/index.json",
)

NONCLAIMS = [
    "No live F2 execution or hardware result is claimed.",
    "No radiometric or Celsius result is claimed.",
    "No Android application build is included or claimed.",
    "No redistribution authority is granted or claimed.",
]

PUBLIC_README_BYTES = (
    "# G007 public clean-room specification\n"
    "\n"
    "This deterministic archive contains only the minimum source-independent G007 "
    "specification, traceability authorities, and definition-only fixtures required "
    "by the G007 validator.\n"
    "\n"
    "It does not claim live F2 execution or a hardware result. It does not claim a "
    "radiometric or Celsius result. It does not include or claim an Android "
    "application build. It does not grant redistribution authority.\n"
    "\n"
    "The payload remains nonterminal: G008 execution fields are pending. "
    "PUBLICATION-MANIFEST.json records every non-manifest entry by path, byte size, "
    "and SHA-256.\n"
).encode("utf-8")

GUARDED_PATH_PARTS = (
    ("assets", "hikmicro", "official"),
    ("com", "hcusbsdk"),
    ("com", "hik"),
    ("com", "hikmicro"),
    ("hik", "common"),
    ("src", "main", "jniLibs"),
)


class ExportError(RuntimeError):
    pass


class DuplicateKeyError(ValueError):
    pass


def _json_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    normalized: dict[str, str] = {}
    for key, value in pairs:
        normalized_key = unicodedata.normalize("NFC", key)
        if key in result or normalized_key in normalized:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        normalized[normalized_key] = key
        result[key] = value
    return result


def _load_json_bytes(payload: bytes, label: str) -> Any:
    try:
        return json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_json_no_duplicates,
        )
    except (UnicodeError, json.JSONDecodeError, DuplicateKeyError) as exc:
        raise ExportError(f"{label} is invalid JSON: {exc}") from exc


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(raw: Any, label: str, *, research_only: bool = False) -> PurePosixPath:
    if not isinstance(raw, str) or not raw:
        raise ExportError(f"{label} must be a non-empty relative POSIX path")
    if "\\" in raw or "\x00" in raw:
        raise ExportError(f"{label} is unsafe: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ExportError(f"{label} is unsafe: {raw!r}")
    if path.as_posix() != raw:
        raise ExportError(f"{label} is not canonical POSIX form: {raw!r}")
    if research_only and path.parts[: len(RESEARCH_REL.parts)] != RESEARCH_REL.parts:
        raise ExportError(f"{label} is outside the G007 research root: {raw!r}")
    return path


def _reject_symlink_components(path: Path, label: str) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            if current.is_symlink():
                raise ExportError(f"{label} contains a symlinked path component: {current}")
        else:
            break


def _validated_paths(root_arg: str, archive_arg: str, command: str) -> tuple[Path, Path]:
    root = Path(root_arg)
    archive = Path(archive_arg)
    if not root.is_absolute():
        raise ExportError("--root must be an explicit absolute path")
    if not archive.is_absolute():
        raise ExportError("--archive must be an explicit absolute path")
    _reject_symlink_components(root, "--root")
    if not root.is_dir():
        raise ExportError("--root must name an existing directory")
    root = root.resolve()
    _reject_symlink_components(archive.parent, "--archive parent")
    if not archive.parent.is_dir():
        raise ExportError("--archive parent must be an existing directory")
    archive_resolved = archive.resolve(strict=False)
    if archive_resolved == root or root in archive_resolved.parents:
        raise ExportError("--archive must be outside --root to keep the private tree untouched")
    if command == "build" and (archive.exists() or archive.is_symlink()):
        raise ExportError("--archive must not already exist")
    if command == "validate" and (archive.is_symlink() or not archive.is_file()):
        raise ExportError("--archive must name an existing non-symlink regular ZIP file")
    return root, archive


def _read_regular(root: Path, relative: PurePosixPath, label: str) -> bytes:
    relative = _safe_relative(relative.as_posix(), label)
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    current_fd = root_fd
    file_fd: int | None = None
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=current_fd,
            )
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(
            relative.parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=current_fd,
        )
        before = os.fstat(file_fd)
        if not stat.S_ISREG(before.st_mode):
            raise ExportError(f"{label} is not a regular file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(file_fd)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise ExportError(f"{label} changed while being read")
        return b"".join(chunks)
    except OSError as exc:
        raise ExportError(f"secure read failed for {label}: {exc}") from exc
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(current_fd)


def _read_external_regular(path: Path, label: str, maximum_bytes: int) -> bytes:
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ExportError(f"{label} is not a regular file")
        if before.st_size > maximum_bytes:
            raise ExportError(f"{label} exceeds the byte-size limit")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise ExportError(f"{label} exceeds the byte-size limit")
            chunks.append(chunk)
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise ExportError(f"{label} changed while being read")
        return b"".join(chunks)
    except OSError as exc:
        raise ExportError(f"secure read failed for {label}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExportError(f"{label} must be a JSON object")
    return value


def _derive_payload_paths(root: Path) -> tuple[PurePosixPath, ...]:
    index = _require_mapping(
        _load_json_bytes(_read_regular(root, G007_INDEX_REL, str(G007_INDEX_REL)), str(G007_INDEX_REL)),
        "G007 index",
    )
    status = _require_mapping(
        _load_json_bytes(_read_regular(root, G007_STATUS_REL, str(G007_STATUS_REL)), str(G007_STATUS_REL)),
        "G007 status",
    )
    fixtures = _require_mapping(
        _load_json_bytes(
            _read_regular(root, FIXTURE_MANIFEST_REL, str(FIXTURE_MANIFEST_REL)),
            str(FIXTURE_MANIFEST_REL),
        ),
        "G007 fixture manifest",
    )

    paths = {
        *AUTHORITY_INDEX_RELS,
        G007_INDEX_REL,
        G007_STATUS_REL,
        G007_README_REL,
        FIXTURE_MANIFEST_REL,
        _safe_relative(index.get("source_index_path"), "G007 source_index_path", research_only=True),
    }
    paths.update(
        RESEARCH_REL / f"dossiers/D{number:02d}/manifest.json"
        for number in range(1, 14)
    )

    fixture_rows = fixtures.get("fixtures")
    if not isinstance(fixture_rows, list):
        raise ExportError("G007 fixture manifest fixtures must be a list")
    for fixture_number, fixture in enumerate(fixture_rows):
        if not isinstance(fixture, dict) or not isinstance(fixture.get("source_paths"), list):
            raise ExportError(f"G007 fixture {fixture_number} source_paths is malformed")
        for source_number, source in enumerate(fixture["source_paths"]):
            if not isinstance(source, dict):
                raise ExportError(f"G007 fixture source path {fixture_number}/{source_number} is malformed")
            paths.add(
                _safe_relative(
                    source.get("path"),
                    f"G007 fixture source path {fixture_number}/{source_number}",
                    research_only=True,
                )
            )

    hash_rows = status.get("artifact_hashes")
    if not isinstance(hash_rows, list):
        raise ExportError("G007 status artifact_hashes must be a list")
    for number, row in enumerate(hash_rows):
        if not isinstance(row, dict):
            raise ExportError(f"G007 status artifact hash {number} is malformed")
        paths.add(
            _safe_relative(
                row.get("path"),
                f"G007 status artifact path {number}",
                research_only=True,
            )
        )

    ordered = tuple(sorted(paths, key=lambda item: item.as_posix()))
    if len(ordered) != EXPECTED_PAYLOAD_FILES:
        raise ExportError(
            "canonical G007 manifests did not derive the exact 66-file minimum "
            f"publication set (derived {len(ordered)})"
        )
    for relative in ordered:
        _read_regular(root, relative, relative.as_posix())
    return ordered


def _official_hashes(root: Path) -> set[str]:
    payload = _read_regular(
        root,
        OFFICIAL_HASH_MANIFEST_REL,
        OFFICIAL_HASH_MANIFEST_REL.as_posix(),
    )
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ExportError("official artifact hash manifest is not UTF-8") from exc
    hashes: set[str] = set()
    for number, line in enumerate(lines, 1):
        if not line or line.startswith("#"):
            continue
        columns = line.split("\t")
        if len(columns) < 3 or not SHA256_RE.fullmatch(columns[0]):
            raise ExportError(f"official artifact hash manifest row {number} is malformed")
        hashes.add(columns[0])
    if not hashes:
        raise ExportError("official artifact hash manifest contains no hashes")
    return hashes


def _is_guarded_path(path: PurePosixPath) -> bool:
    parts = path.parts
    if parts and parts[0] == "lib":
        return True
    for guarded in GUARDED_PATH_PARTS:
        width = len(guarded)
        if any(parts[offset : offset + width] == guarded for offset in range(len(parts) - width + 1)):
            return True
    return False


def _reject_forbidden_entry(path: PurePosixPath, payload: bytes, official_hashes: set[str]) -> None:
    if _is_guarded_path(path):
        raise ExportError(f"guarded vendor/native path is not public: {path.as_posix()}")
    if _sha256(payload) in official_hashes:
        raise ExportError(f"entry matches official artifact bytes: {path.as_posix()}")


def _run_g007_validator(program_root: Path, subject_root: Path) -> None:
    validator = program_root / Path(VALIDATOR_REL.as_posix())
    if not validator.is_file() or validator.is_symlink():
        raise ExportError(f"required existing G007 validator is unavailable: {validator}")
    completed = subprocess.run(
        [sys.executable, str(validator), "--root", str(subject_root), "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ExportError(f"existing G007 spec validator rejected the publication: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ExportError("existing G007 spec validator returned invalid JSON") from exc
    if result.get("ok") is not True:
        raise ExportError("existing G007 spec validator did not report ok=true")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.create_system = 3
    info.compress_type = zipfile.ZIP_STORED
    info.external_attr = FIXED_MODE << 16
    return info


def _canonical_archive_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_STORED,
        allowZip64=False,
    ) as output:
        for name in sorted(entries):
            output.writestr(_zip_info(name), entries[name])
    return buffer.getvalue()


def _manifest_for(payloads: dict[str, bytes]) -> bytes:
    files = [
        {
            "path": path,
            "sha256": _sha256(payload),
            "size_bytes": len(payload),
        }
        for path, payload in sorted(payloads.items())
    ]
    return _canonical_json(
        {
            "schema": "g007-public-clean-room-publication/v1",
            "schema_version": 1,
            "scope": "Deterministic source-independent G007 specification publication set.",
            "payload_file_count": EXPECTED_PAYLOAD_FILES,
            "nonclaims": NONCLAIMS,
            "files": files,
        }
    )


def build(root: Path, archive: Path) -> None:
    _run_g007_validator(root, root)
    official_hashes = _official_hashes(root)
    payload_paths = _derive_payload_paths(root)
    payloads: dict[str, bytes] = {PUBLIC_README: PUBLIC_README_BYTES}
    for relative in payload_paths:
        payload = _read_regular(root, relative, relative.as_posix())
        _reject_forbidden_entry(relative, payload, official_hashes)
        payloads[relative.as_posix()] = payload
    _reject_forbidden_entry(PurePosixPath(PUBLIC_README), PUBLIC_README_BYTES, official_hashes)
    entries = {**payloads, PUBLIC_MANIFEST: _manifest_for(payloads)}
    archive_bytes = _canonical_archive_bytes(entries)

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{archive.name}.",
            suffix=".tmp",
            dir=archive.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(archive_bytes)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, 0o644)
        if archive.exists() or archive.is_symlink():
            raise ExportError("--archive appeared while the deterministic ZIP was being built")
        os.link(temporary_name, archive)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ExportError(f"could not build archive safely: {exc}") from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def _validate_zip_metadata(infos: list[zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    names = [info.filename for info in infos]
    normalized: set[str] = set()
    by_name: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        path = _safe_relative(info.filename, "archive entry path")
        normalized_name = unicodedata.normalize("NFC", info.filename)
        if info.filename in by_name or normalized_name in normalized:
            raise ExportError(f"duplicate archive entry: {info.filename}")
        normalized.add(normalized_name)
        by_name[info.filename] = info
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise ExportError(f"symlink archive entry is forbidden: {info.filename}")
        if mode != FIXED_MODE:
            raise ExportError(f"archive entry permissions/type are not deterministic: {info.filename}")
        if info.is_dir():
            raise ExportError(f"directory archive entries are forbidden: {info.filename}")
        if info.compress_type != zipfile.ZIP_STORED:
            raise ExportError(f"archive entry is not ZIP_STORED: {info.filename}")
        if info.date_time != FIXED_ZIP_TIME:
            raise ExportError(f"archive entry timestamp is not fixed: {info.filename}")
        if info.create_system != 3:
            raise ExportError(f"archive entry platform metadata is not deterministic: {info.filename}")
        if info.flag_bits & 0x1:
            raise ExportError(f"encrypted archive entry is forbidden: {info.filename}")
        if info.extra or info.comment or info.internal_attr != 0:
            raise ExportError(f"archive entry contains noncanonical metadata: {info.filename}")
        if info.file_size > MAX_ENTRY_BYTES:
            raise ExportError(f"archive entry exceeds size limit: {info.filename}")
        _reject_forbidden_entry(path, b"", set())
    if len(infos) != 68:
        raise ExportError(f"archive entry count is not exact: expected 68, found {len(infos)}")
    if names != sorted(names):
        raise ExportError("archive entries are not sorted")
    if not {PUBLIC_MANIFEST, PUBLIC_README} <= set(by_name):
        raise ExportError("archive lacks top-level PUBLICATION-MANIFEST.json or README.md")
    return by_name


def _validate_manifest(manifest_payload: bytes) -> tuple[dict[str, dict[str, Any]], set[str]]:
    manifest = _require_mapping(
        _load_json_bytes(manifest_payload, PUBLIC_MANIFEST),
        PUBLIC_MANIFEST,
    )
    if _canonical_json(manifest) != manifest_payload:
        raise ExportError("publication manifest is not canonical JSON")
    expected_keys = {
        "schema",
        "schema_version",
        "scope",
        "payload_file_count",
        "nonclaims",
        "files",
    }
    if set(manifest) != expected_keys:
        raise ExportError("publication manifest keys are not exact")
    if (
        manifest.get("schema") != "g007-public-clean-room-publication/v1"
        or manifest.get("schema_version") != 1
        or manifest.get("scope")
        != "Deterministic source-independent G007 specification publication set."
        or manifest.get("payload_file_count") != EXPECTED_PAYLOAD_FILES
        or manifest.get("nonclaims") != NONCLAIMS
    ):
        raise ExportError("publication manifest identity, scope, or nonclaims are invalid")
    rows = manifest.get("files")
    if not isinstance(rows, list) or len(rows) != EXPECTED_PAYLOAD_FILES + 1:
        raise ExportError("publication manifest file coverage is not exact")
    row_paths: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ExportError("publication manifest file rows are malformed")
        row_paths.append(row["path"])
    if row_paths != sorted(row_paths):
        raise ExportError("publication manifest file rows are not sorted")
    files: dict[str, dict[str, Any]] = {}
    for number, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size_bytes"}:
            raise ExportError(f"publication manifest file row {number} is malformed")
        path = _safe_relative(row.get("path"), f"publication manifest file row {number}")
        text = path.as_posix()
        if text == PUBLIC_MANIFEST or text in files:
            raise ExportError(f"duplicate/self-referential publication manifest path: {text}")
        if not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
            raise ExportError(f"publication manifest hash is malformed for {text}")
        size = row.get("size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_ENTRY_BYTES:
            raise ExportError(f"publication manifest size is malformed for {text}")
        files[text] = row
    expected_entries = set(files) | {PUBLIC_MANIFEST}
    return files, expected_entries


def _write_extracted(root: Path, relative: PurePosixPath, payload: bytes) -> None:
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise ExportError(f"safe extraction failed for {relative.as_posix()}: {exc}") from exc
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
    finally:
        os.close(descriptor)


def validate(program_root: Path, archive: Path) -> None:
    official_hashes = _official_hashes(program_root)
    archive_bytes = _read_external_regular(
        archive,
        "public archive",
        MAX_ARCHIVE_FILE_BYTES,
    )
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as source:
            if source.comment:
                raise ExportError("archive comment is forbidden")
            infos = source.infolist()
            by_name = _validate_zip_metadata(infos)
            manifest_payload = source.read(by_name[PUBLIC_MANIFEST])
            files, expected_entries = _validate_manifest(manifest_payload)
            if set(by_name) != expected_entries:
                missing = sorted(expected_entries - set(by_name))
                extra = sorted(set(by_name) - expected_entries)
                raise ExportError(
                    f"publication manifest/archive coverage mismatch: missing={missing}, extra={extra}"
                )
            total_size = 0
            payloads: dict[str, bytes] = {}
            for name in sorted(by_name):
                payload = source.read(by_name[name])
                total_size += len(payload)
                if total_size > MAX_ARCHIVE_BYTES:
                    raise ExportError("archive exceeds total extracted-size limit")
                _reject_forbidden_entry(PurePosixPath(name), payload, official_hashes)
                payloads[name] = payload
            for name, row in files.items():
                payload = payloads[name]
                if len(payload) != row["size_bytes"] or _sha256(payload) != row["sha256"]:
                    raise ExportError(f"manifest hash/size mismatch for {name}")
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        if isinstance(exc, ExportError):
            raise
        raise ExportError(f"invalid ZIP archive: {exc}") from exc

    if payloads[PUBLIC_README] != PUBLIC_README_BYTES:
        raise ExportError("top-level README.md scope/nonclaims text is not exact")

    canonical_paths = _derive_payload_paths(program_root)
    canonical_payloads = {PUBLIC_README: PUBLIC_README_BYTES}
    for relative in canonical_paths:
        name = relative.as_posix()
        canonical_payload = _read_regular(program_root, relative, name)
        if payloads.get(name) != canonical_payload:
            raise ExportError(
                f"archive payload differs from canonical repository bytes: {name}"
            )
        canonical_payloads[name] = canonical_payload
    canonical_entries = {
        **canonical_payloads,
        PUBLIC_MANIFEST: _manifest_for(canonical_payloads),
    }
    if archive_bytes != _canonical_archive_bytes(canonical_entries):
        raise ExportError(
            "archive bytes are not the exact deterministic canonical serialization"
        )

    with tempfile.TemporaryDirectory(prefix="g007-public-validate-") as temporary:
        extracted = Path(temporary)
        for name, payload in payloads.items():
            if name in {PUBLIC_MANIFEST, PUBLIC_README}:
                continue
            _write_extracted(extracted, _safe_relative(name, "payload extraction path"), payload)
        derived = {path.as_posix() for path in _derive_payload_paths(extracted)}
        declared_payload = set(files) - {PUBLIC_README}
        if derived != declared_payload:
            raise ExportError(
                "archive is not the exact canonical 66-file G007 publication set"
            )
        _run_g007_validator(program_root, extracted)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or validate the deterministic vendor-free public G007 specification archive"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("build", "validate"):
        child = subparsers.add_parser(command)
        child.add_argument("--root", required=True, help="explicit absolute repository root")
        child.add_argument("--archive", required=True, help="explicit absolute output/input ZIP path")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root, archive = _validated_paths(args.root, args.archive, args.command)
        if args.command == "build":
            build(root, archive)
            print(
                f"Built deterministic G007 public archive with 68 archive entries: {archive}"
            )
        else:
            validate(root, archive)
            print(
                f"Validated deterministic G007 public archive with 68 archive entries: {archive}"
            )
        return 0
    except ExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
