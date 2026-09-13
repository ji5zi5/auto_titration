#!/usr/bin/env python3
"""G004 host-only observation artifact validator and CLI.

Stdlib-only, explicit-path, fail-closed utilities for dynamic observation
manifests used by the HIKMICRO whole-APK reverse-engineering work.  The module
intentionally does not touch Android, USB, native libraries, or devices.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_MAX_BYTES = 5 * 1024 * 1024
REQUIRED_COMMANDS = ("validate", "validate-index", "normalize-events", "pair", "emit-hook", "collect-dry-run")
LOG_RE = re.compile(r"(^|/)\.omx/ultragoal/logs/G004-[^/]+\.log$")
SIZE_RE = re.compile(r"([1-9][0-9]*)(B|K|KB|KIB|M|MB|MIB|G|GB|GIB)?", re.IGNORECASE)
SESSION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SIZE_MULTIPLIERS = {
    "": 1,
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024 * 1024,
    "MB": 1024 * 1024,
    "MIB": 1024 * 1024,
    "G": 1024 * 1024 * 1024,
    "GB": 1024 * 1024 * 1024,
    "GIB": 1024 * 1024 * 1024,
}
SELF_FIELDS = {
    "hook": {"id", "hook_manifest_id", "sha256", "manifest_sha256", "hook_manifest_sha256"},
    "event": {"id", "event_id", "sha256", "manifest_sha256", "event_sha256"},
    "run": {"id", "run_manifest_id", "sha256", "manifest_sha256", "run_manifest_sha256"},
    "replay": {"id", "replay_fixture_id", "sha256", "manifest_sha256", "replay_fixture_sha256"},
    "bundle": {"id", "evidence_bundle_id", "sha256", "manifest_sha256", "bundle_sha256", "evidence_bundle_sha256"},
    "unknown": {"id", "unknown_id", "unknown_manifest_id", "sha256", "manifest_sha256", "unknown_manifest_sha256"},
}
DAG_FORBIDDEN = {
    "hook": {"event_id", "event_ids", "run_manifest_id", "run_manifest_ref_id", "run_hash", "run_sha256", "run_path", "replay_fixture_id", "evidence_bundle_id", "validator_result_id"},
    "event": {"run_manifest_id", "run_manifest_ref_id", "run_hash", "run_sha256", "run_path", "replay_fixture_id", "evidence_bundle_id", "validator_result_id"},
    "run": {"replay_fixture_id", "evidence_bundle_id", "validator_result_id"},
    "replay": {"event_id", "event_ids", "evidence_bundle_id", "validator_result_id"},
    "bundle": {"event_id", "event_ids", "hook_manifest_id", "validator_result_id"},
    "unknown": {"run_manifest_id", "event_id", "evidence_bundle_id", "validator_result_id"},
}


class DuplicateKeyError(ValueError):
    pass


class CliArgumentError(ValueError):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CliArgumentError(message)


def _result() -> dict[str, Any]:
    return {"ok": True, "checked_files": [], "errors": [], "manifest_ids": [], "event_count": 0, "synthetic_evidence_count": 0}


def _err(result: dict[str, Any], path: str, field: str, message: str) -> None:
    result["ok"] = False
    result["errors"].append({"path": str(path), "field": str(field), "message": str(message)})


def _checked(result: dict[str, Any], path: Path) -> None:
    s = str(path)
    if s not in result["checked_files"]:
        result["checked_files"].append(s)


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seen_nfc: dict[str, str] = {}
    for key, value in pairs:
        if key in out:
            raise DuplicateKeyError(f"duplicate JSON key {key!r}")
        nkey = unicodedata.normalize("NFC", key)
        if nkey in seen_nfc and seen_nfc[nkey] != key:
            raise DuplicateKeyError(f"post-NFC-colliding JSON keys {seen_nfc[nkey]!r}/{key!r}")
        seen_nfc[nkey] = key
        out[key] = value
    return out


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number {value}")


def _parse_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"non-finite JSON number {value}")
    return parsed


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        seen: dict[str, str] = {}
        for key, item in value.items():
            nkey = unicodedata.normalize("NFC", str(key))
            if nkey in seen and seen[nkey] != key:
                raise ValueError(f"post-NFC-colliding JSON keys {seen[nkey]!r}/{key!r}")
            seen[nkey] = str(key)
            out[nkey] = _normalize(item)
        return out
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Return normalized canonical JSON bytes with one trailing newline."""
    normalized = _normalize(value)
    return (json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> str:
    if path.stat().st_size > max_bytes:
        raise ValueError(f"file exceeds max size {max_bytes} bytes")
    return sha256_bytes(path.read_bytes())


def load_json_text(text: str) -> Any:
    return json.loads(
        text,
        object_pairs_hook=_pairs_no_duplicates,
        parse_constant=_reject_constant,
        parse_float=_parse_float,
    )


def parse_filesize(value: str) -> int:
    """Parse a positive byte count or binary K/M/G size, rejecting all ambiguity."""
    match = SIZE_RE.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "size must be a positive integer optionally followed by B, K, KB, KiB, M, MB, MiB, G, GB, or GiB"
        )
    count = int(match.group(1))
    size = count * SIZE_MULTIPLIERS[(match.group(2) or "").upper()]
    if size > sys.maxsize:
        raise argparse.ArgumentTypeError("size exceeds the platform-supported maximum")
    return size


def parse_session_id(value: str) -> str:
    """Accept a bounded identifier that is safe to embed in deterministic IDs."""
    if SESSION_RE.fullmatch(value) is None:
        raise argparse.ArgumentTypeError(
            "session must be 1-128 ASCII letters, digits, dots, underscores, or hyphens and start with a letter or digit"
        )
    return value


def detect_family(value: Mapping[str, Any]) -> str | None:
    schema = str(value.get("schema", "")).lower()
    schema_matches = {
        family
        for family, markers in (
            ("hook", ("hook",)),
            ("event", ("event",)),
            ("run", ("run",)),
            ("replay", ("replay",)),
            ("bundle", ("evidence", "bundle")),
            ("unknown", ("unknown",)),
        )
        if any(marker in schema for marker in markers)
    }
    if len(schema_matches) == 1:
        return next(iter(schema_matches))
    if len(schema_matches) > 1:
        return None

    # Without a schema, prefer unmistakable own-family IDs over fields that are
    # legal references in a later artifact family.
    if "unknown_manifest_id" in value or "unknown_id" in value:
        return "unknown"
    if "evidence_bundle_id" in value:
        return "bundle"
    if "replay_fixture_id" in value:
        return "replay"
    if "event_id" in value:
        return "event"
    if "run_manifest_id" in value or "event_ids" in value:
        return "run"
    if "hook_manifest_id" in value:
        return "hook"
    return None


def artifact_identifier(value: Mapping[str, Any], family: str | None = None) -> str | None:
    family = family or detect_family(value)
    keys = {
        "hook": ("hook_manifest_id", "id"),
        "event": ("event_id", "id"),
        "run": ("run_manifest_id", "id"),
        "replay": ("replay_fixture_id", "id"),
        "bundle": ("evidence_bundle_id", "id"),
        "unknown": ("unknown_manifest_id", "unknown_id", "id"),
    }.get(family or "", ("id",))
    for key in keys:
        if isinstance(value.get(key), str) and value.get(key):
            return value[key]
    return None


def _without_self(value: Mapping[str, Any], family: str) -> dict[str, Any]:
    excluded = SELF_FIELDS.get(family, {"id", "sha256", "manifest_sha256"})
    return {key: item for key, item in value.items() if key not in excluded}


def content_digest(value: Mapping[str, Any], family: str | None = None) -> str:
    family = family or detect_family(value) or "event"
    return sha256_bytes(canonical_json_bytes(_without_self(value, family)))


def stored_digest(value: Mapping[str, Any], family: str | None = None) -> str | None:
    family = family or detect_family(value)
    candidates = ["sha256", "manifest_sha256"]
    if family == "hook": candidates += ["hook_manifest_sha256"]
    if family == "event": candidates += ["event_sha256"]
    if family == "run": candidates += ["run_manifest_sha256"]
    if family == "replay": candidates += ["replay_fixture_sha256"]
    if family == "bundle": candidates += ["bundle_sha256", "evidence_bundle_sha256"]
    if family == "unknown": candidates += ["unknown_manifest_sha256"]
    for key in candidates:
        v = value.get(key)
        if isinstance(v, str):
            return v
    return None


def _resolve_input(path_arg: str, *, root: Path | None, result: dict[str, Any], field: str = "path", must_exist: bool = True, allow_dir: bool = False) -> Path | None:
    if not path_arg:
        _err(result, path_arg, field, "explicit path is required")
        return None
    raw = Path(path_arg)
    if ".." in PurePosixPath(path_arg.replace(os.sep, "/")).parts:
        _err(result, path_arg, field, "path escape is forbidden")
        return None
    boundary = root.resolve() if root else None
    path = raw if raw.is_absolute() else (boundary / raw if boundary else Path.cwd() / raw)
    try:
        resolved = path.resolve(strict=must_exist)
    except FileNotFoundError:
        _err(result, str(path), field, "path does not exist")
        return None
    except OSError as exc:
        _err(result, str(path), field, f"cannot resolve path: {exc}")
        return None
    if boundary is not None:
        try:
            resolved.relative_to(boundary)
        except ValueError:
            _err(result, str(resolved), field, "path is outside declared root")
            return None
    if must_exist:
        if allow_dir:
            if not resolved.is_dir():
                _err(result, str(resolved), field, "directory is required")
                return None
        elif not resolved.is_file():
            _err(result, str(resolved), field, "explicit file path is required; no directory scans")
            return None
    return resolved


def _read_json_file(path: Path, result: dict[str, Any], *, max_bytes: int) -> Any | None:
    try:
        if path.stat().st_size > max_bytes:
            _err(result, str(path), "size", f"file exceeds max size {max_bytes} bytes")
            return None
        data = path.read_text(encoding="utf-8")
        value = load_json_text(data)
        _normalize(value)
        _checked(result, path)
        return value
    except DuplicateKeyError as exc:
        _err(result, str(path), "json", str(exc))
    except UnicodeDecodeError as exc:
        _err(result, str(path), "encoding", f"not UTF-8 text: {exc}")
    except (json.JSONDecodeError, ValueError) as exc:
        _err(result, str(path), "json", str(exc))
    except OSError as exc:
        _err(result, str(path), "path", str(exc))
    return None


def _contains_key(value: Any, names: set[str]) -> bool:
    if isinstance(value, dict):
        return any(k in names or _contains_key(v, names) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_key(v, names) for v in value)
    return False


def _blob(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
    except Exception:
        return str(value).lower()


def _is_synthetic(value: Mapping[str, Any]) -> bool:
    return value.get("synthetic") is True or value.get("source_variant") == "synthetic" or value.get("evidence_source") == "synthetic"


def _validate_artifact(value: Mapping[str, Any], path: str, result: dict[str, Any]) -> None:
    family = detect_family(value)
    if not family:
        _err(result, path, "schema", "unknown artifact family")
        return
    ident = artifact_identifier(value, family)
    if ident and ident not in result["manifest_ids"]:
        result["manifest_ids"].append(ident)
    if family == "event":
        result["event_count"] += 1
    if _is_synthetic(value):
        result["synthetic_evidence_count"] += 1
        tier = value.get("evidence_tier") or value.get("minimum_evidence_tier")
        if tier in {"E2", "E3"}:
            _err(result, path, "evidence_tier", "synthetic artifacts cannot claim E2/E3 evidence")
    blob = _blob(value)
    if _is_synthetic(value) and ("live" in blob or "celsius" in blob or "°c" in blob or "temperature_c" in blob):
        _err(result, path, "synthetic", "synthetic artifacts cannot claim live or Celsius behavior")
    if family == "unknown":
        if value.get("status") not in ("nonterminal", None):
            _err(result, path, "status", "unknown status must remain nonterminal")
        if value.get("closure_effect") in {"verified", "closed", "terminal", "complete"}:
            _err(result, path, "closure_effect", "unknowns must not be promoted to terminal/verified closure")
    if family == "event" and not value.get("event_schema_id"):
        _err(result, path, "event_schema_id", "event records require event_schema_id")
    forbidden = DAG_FORBIDDEN.get(family, set())
    for key in forbidden:
        if _contains_key(value, {key}):
            _err(result, path, key, f"{family} artifact may not reference {key}")
    sd = stored_digest(value, family)
    if sd is not None:
        cd = content_digest(value, family)
        if sd != cd:
            _err(result, path, "sha256", "stored self-hash is stale; recomputed digest excludes self fields")


def _artifact_records(items: list[tuple[Path, Any]], result: dict[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    records: list[tuple[str, Mapping[str, Any]]] = []
    for path, value in items:
        if isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    records.append((f"{path}#{idx}", item))
                else:
                    _err(result, str(path), str(idx), "list entries must be objects")
            continue
        if not isinstance(value, dict):
            _err(result, str(path), "json", "artifact must be a JSON object")
            continue
        records.append((str(path), value))
    return records


def _reference_ids(
    value: Mapping[str, Any],
    path: str,
    result: dict[str, Any],
    *,
    singular: str | None = None,
    plural: str | None = None,
    required: bool = False,
) -> list[str]:
    refs: list[str] = []
    present = False
    if singular and singular in value:
        present = True
        ref = value.get(singular)
        if isinstance(ref, str) and ref:
            refs.append(ref)
        else:
            _err(result, path, singular, f"{singular} must be a non-empty string")
    if plural and plural in value:
        present = True
        listed = value.get(plural)
        if not isinstance(listed, list):
            _err(result, path, plural, f"{plural} must be a list")
        else:
            for idx, ref in enumerate(listed):
                if isinstance(ref, str) and ref:
                    refs.append(ref)
                else:
                    _err(result, path, f"{plural}[{idx}]", "reference ID must be a non-empty string")
    if required and not present:
        field = singular or plural or "reference"
        _err(result, path, field, f"{field} reference is required")
    seen: set[str] = set()
    for ref in refs:
        if ref in seen:
            _err(result, path, plural or singular or "reference", f"duplicate reference {ref}")
        seen.add(ref)
    return refs


def _aliased_reference_id(
    value: Mapping[str, Any],
    path: str,
    result: dict[str, Any],
    fields: Sequence[str],
) -> list[str]:
    present = [(field, value.get(field)) for field in fields if field in value]
    if not present:
        _err(result, path, fields[0], f"{fields[0]} reference is required")
        return []
    invalid = [(field, ref) for field, ref in present if not isinstance(ref, str) or not ref]
    for field, _ in invalid:
        _err(result, path, field, f"{field} must be a non-empty string")
    valid = [(field, ref) for field, ref in present if isinstance(ref, str) and ref]
    unique = {ref for _, ref in valid}
    if len(unique) > 1:
        _err(result, path, fields[0], f"conflicting aliased references across {', '.join(fields)}")
        return []
    return list(unique)


def validate_values(items: list[tuple[Path, Any]], result: dict[str, Any]) -> dict[str, Any]:
    maps: dict[str, dict[str, tuple[str, Mapping[str, Any]]]] = {
        family: {} for family in SELF_FIELDS
    }
    global_ids: dict[str, tuple[str, str]] = {}
    records = _artifact_records(items, result)
    for path, value in records:
        _validate_artifact(value, path, result)
        fam = detect_family(value)
        ident = artifact_identifier(value, fam)
        if fam is None:
            continue
        if not ident:
            _err(result, path, f"{fam}_id", f"{fam} artifact identity is required")
            continue
        previous = global_ids.get(ident)
        if previous is not None:
            previous_family, previous_path = previous
            _err(
                result,
                path,
                f"{fam}_id",
                f"duplicate artifact ID {ident}; first declared as {previous_family} at {previous_path}",
            )
            continue
        global_ids[ident] = (fam, path)
        maps[fam][ident] = (path, value)

    for event_id, (path, event) in maps["event"].items():
        hook_ids = _reference_ids(
            event,
            path,
            result,
            singular="hook_manifest_id",
            required=True,
        )
        for hook_id in hook_ids:
            target = maps["hook"].get(hook_id)
            if target is None:
                _err(result, path, "hook_manifest_id", f"missing referenced hook {hook_id}")
                continue
            _, hook = target
            if event.get("event_schema_id") != hook.get("event_schema_id"):
                _err(
                    result,
                    path,
                    "event_schema_id",
                    f"event schema does not match referenced hook {hook_id}",
                )

    for run_id, (path, run) in maps["run"].items():
        event_ids = _reference_ids(run, path, result, plural="event_ids")
        for event_id in event_ids:
            target = maps["event"].get(event_id)
            if target is None:
                _err(result, path, "event_ids[]", f"missing referenced event {event_id}")
                continue
            event_path, event = target
            if event.get("run_manifest_id") == run_id:
                _err(
                    result,
                    event_path,
                    "event.run_manifest_id -> run.event_ids[]",
                    "event/run reference cycle is forbidden",
                )

    for replay_id, (path, replay) in maps["replay"].items():
        run_ids = _aliased_reference_id(
            replay,
            path,
            result,
            ("run_manifest_id", "run_manifest_ref_id"),
        )
        for run_id in run_ids:
            target = maps["run"].get(run_id)
            if target is None:
                _err(result, path, "run_manifest_id", f"missing referenced run {run_id}")
                continue
            _, run = target
            declared_hash = replay.get("run_manifest_sha256")
            if declared_hash is not None:
                if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
                    _err(result, path, "run_manifest_sha256", "run manifest hash must be 64 hexadecimal characters")
                elif declared_hash.lower() != content_digest(run, "run"):
                    _err(result, path, "run_manifest_sha256", f"incorrect hash for referenced run {run_id}")

    for bundle_id, (path, bundle) in maps["bundle"].items():
        run_ids = _reference_ids(
            bundle,
            path,
            result,
            singular="run_manifest_id",
            plural="run_manifest_ids",
        )
        replay_ids = _reference_ids(
            bundle,
            path,
            result,
            singular="replay_fixture_id",
            plural="replay_fixture_ids",
        )
        for run_id in run_ids:
            if run_id not in maps["run"]:
                _err(result, path, "run_manifest_ids[]", f"missing referenced run {run_id}")
        for replay_id in replay_ids:
            target = maps["replay"].get(replay_id)
            if target is None:
                _err(result, path, "replay_fixture_ids[]", f"missing referenced replay {replay_id}")
                continue
            _, replay = target
            replay_run_id = replay.get("run_manifest_id", replay.get("run_manifest_ref_id"))
            if run_ids and replay_run_id not in run_ids:
                _err(
                    result,
                    path,
                    "replay_fixture_ids[]",
                    f"replay {replay_id} references run {replay_run_id} outside the evidence run set",
                )
    result["checked_files"].sort(); result["manifest_ids"].sort()
    return result


def cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    paths = list(args.manifest or []) + list(args.bundle or [])
    if not paths:
        _err(result, "<args>", "manifest", "validate requires at least one explicit --manifest or --bundle path")
        return result
    items: list[tuple[Path, Any]] = []
    for p in paths:
        path = _resolve_input(p, root=root, result=result)
        if path is None: continue
        val = _read_json_file(path, result, max_bytes=args.max_bytes)
        if val is not None: items.append((path, val))
    validate_values(items, result)
    _write_log(args.log, result)
    return result


def _index_entries(index: Any, index_path: Path, result: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []

    def add_entry(item: Any, field: str) -> None:
        if isinstance(item, str):
            entries.append({"path": item, "metadata": {}, "field": field})
            return
        if not isinstance(item, dict):
            _err(result, str(index_path), field, "index entry must be a path string or object")
            return
        path_fields = [
            item[key]
            for key in ("path", "manifest", "bundle")
            if isinstance(item.get(key), str) and item.get(key)
        ]
        if len(set(path_fields)) != 1:
            _err(result, str(index_path), field, "index entry must declare exactly one unambiguous path")
            return
        entries.append({"path": path_fields[0], "metadata": dict(item), "field": field})

    if isinstance(index, list):
        for idx, item in enumerate(index):
            add_entry(item, f"entries[{idx}]")
    elif isinstance(index, dict):
        for section in ("manifests", "bundles", "files", "entries", "unknowns"):
            values = index.get(section)
            if values is None:
                continue
            if isinstance(values, list):
                for idx, item in enumerate(values):
                    add_entry(item, f"{section}[{idx}]")
            else:
                add_entry(values, section)
        if "entry_count" in index:
            declared_count = index.get("entry_count")
            if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count < 0:
                _err(result, str(index_path), "entry_count", "entry_count must be a non-negative integer")
            elif declared_count != len(entries):
                _err(
                    result,
                    str(index_path),
                    "entry_count",
                    f"entry_count {declared_count} does not match {len(entries)} declared entries",
                )
    else:
        _err(result, str(index_path), "index", "index must be an object or list")
    return entries


def _index_base(
    index: Any,
    index_path: Path,
    cli_root: Path | None,
    result: dict[str, Any],
    *,
    entries: list[dict[str, Any]],
    max_bytes: int,
) -> Path | None:
    declared: Any = None
    if isinstance(index, dict):
        declared = index.get("base_dir", index.get("root"))
    if declared is None:
        if cli_root is not None:
            return cli_root
        if isinstance(index, dict) and index.get("schema") == "g004-index/v1":
            return _package_contract_base(
                index,
                index_path,
                entries,
                result,
                max_bytes=max_bytes,
            )
        return index_path.parent.resolve()
    if not isinstance(declared, str) or not declared:
        _err(result, str(index_path), "base_dir", "index base must be a non-empty relative path")
        return None
    raw = Path(declared)
    if raw.is_absolute() or ".." in PurePosixPath(declared.replace(os.sep, "/")).parts:
        _err(result, str(index_path), "base_dir", "index base must remain contained beside the index")
        return None
    try:
        base = (index_path.parent / raw).resolve(strict=True)
    except OSError as exc:
        _err(result, str(index_path), "base_dir", f"cannot resolve index base: {exc}")
        return None
    if not base.is_dir():
        _err(result, str(base), "base_dir", "index base must be a directory")
        return None
    boundaries = [index_path.parent.resolve()]
    if cli_root is not None:
        boundaries.append(cli_root.resolve())
    for boundary in boundaries:
        try:
            base.relative_to(boundary)
        except ValueError:
            _err(result, str(base), "base_dir", "index base escapes its containment boundary")
            return None
    return base


def _declared_entry_sha256(metadata: Mapping[str, Any], path: str, field: str, result: dict[str, Any]) -> str | None:
    declared = [
        metadata[key]
        for key in ("sha256", "raw_sha256", "file_sha256")
        if key in metadata
    ]
    if not declared:
        return None
    if len(set(str(value) for value in declared)) != 1:
        _err(result, path, f"{field}.sha256", "index entry declares conflicting raw-file hashes")
        return None
    value = declared[0]
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        _err(result, path, f"{field}.sha256", "declared raw-file sha256 must be 64 hexadecimal characters")
        return None
    return value.lower()


def _package_entry_hashes(
    entries: list[dict[str, Any]],
    owner_path: Path,
    result: dict[str, Any],
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for entry in entries:
        raw_path = entry["path"]
        raw = Path(raw_path)
        if raw.is_absolute() or ".." in PurePosixPath(raw_path.replace(os.sep, "/")).parts:
            _err(result, str(owner_path), "package_contract", f"package entry path is not contained: {raw_path}")
            continue
        declared_hash = _declared_entry_sha256(
            entry["metadata"],
            str(owner_path),
            entry["field"],
            result,
        )
        if declared_hash is None:
            if not any(error["field"] == f"{entry['field']}.sha256" for error in result["errors"]):
                _err(result, str(owner_path), "package_contract", f"package entry {raw_path} must declare raw-file sha256")
            continue
        if raw_path in hashes:
            _err(result, str(owner_path), "package_contract", f"duplicate package entry path {raw_path}")
            continue
        hashes[raw_path] = declared_hash
    return hashes


def _package_contract_base(
    index: Mapping[str, Any],
    index_path: Path,
    index_entries: list[dict[str, Any]],
    result: dict[str, Any],
    *,
    max_bytes: int,
) -> Path | None:
    """Resolve g004-index/v1 paths through an explicit sibling package contract."""
    if index_path.parent.name != "indexes":
        _err(
            result,
            str(index_path),
            "package_contract",
            "g004-index/v1 without base_dir must be contained in a package indexes directory",
        )
        return None
    package_path = _resolve_input(
        "package.json",
        root=index_path.parent,
        result=result,
        field="package_contract",
    )
    if package_path is None:
        return None
    package = _read_json_file(package_path, result, max_bytes=max_bytes)
    if not isinstance(package, dict):
        _err(result, str(package_path), "package_contract", "package contract must be a JSON object")
        return None
    if package.get("schema") != "g004-package-index/v1":
        _err(result, str(package_path), "package_contract", "package contract schema must be g004-package-index/v1")
        return None
    if not isinstance(package.get("package_id"), str) or not package.get("package_id"):
        _err(result, str(package_path), "package_contract", "package contract requires package_id")
        return None

    package_root = index_path.parent.parent.resolve()
    try:
        relative_index = index_path.relative_to(package_root).as_posix()
    except ValueError:
        _err(result, str(index_path), "package_contract", "index escapes the package root")
        return None
    families = package.get("families")
    if not isinstance(families, dict):
        _err(result, str(package_path), "package_contract", "package contract requires a families map")
        return None
    family_paths: dict[str, str] = {}
    for family_name, family_path in families.items():
        if not isinstance(family_name, str) or not isinstance(family_path, str) or not family_path:
            _err(result, str(package_path), "package_contract", "package family paths must be named non-empty strings")
            continue
        raw = Path(family_path)
        if raw.is_absolute() or ".." in PurePosixPath(family_path.replace(os.sep, "/")).parts:
            _err(result, str(package_path), "package_contract", f"package family path is not contained: {family_path}")
            continue
        candidate = (package_root / raw).resolve(strict=False)
        try:
            candidate.relative_to(package_root)
        except ValueError:
            _err(result, str(package_path), "package_contract", f"package family path escapes: {family_path}")
            continue
        family_paths[family_name] = family_path
    matching_families = [name for name, path in family_paths.items() if path == relative_index]
    if not matching_families:
        _err(result, str(index_path), "package_contract", "package families map does not explicitly name this index")
        return None

    package_entries = _index_entries(package, package_path, result)
    index_hashes = _package_entry_hashes(index_entries, index_path, result)
    package_hashes = _package_entry_hashes(package_entries, package_path, result)
    for entry_path, entry_hash in index_hashes.items():
        if package_hashes.get(entry_path) != entry_hash:
            _err(
                result,
                str(index_path),
                "package_contract",
                f"index entry {entry_path} is absent from the package contract or has a different sha256",
            )
    if "all_artifacts" in matching_families:
        artifact_count = package.get("artifact_count")
        if isinstance(artifact_count, bool) or not isinstance(artifact_count, int):
            _err(result, str(package_path), "package_contract", "all-artifacts package contract requires artifact_count")
        elif artifact_count != len(index_entries):
            _err(
                result,
                str(package_path),
                "package_contract",
                f"artifact_count {artifact_count} does not match all-artifacts entry count {len(index_entries)}",
            )
    if not result["ok"]:
        return None
    return package_root


INDEX_FAMILY_MEMBERS = {
    "all": set(SELF_FIELDS),
    "hook": {"hook"},
    "event": {"event"},
    "run": {"run"},
    "run-with-events": {"run", "event"},
    "replay": {"replay"},
    "bundle": {"bundle"},
    "evidence": {"bundle"},
    "unknown": {"unknown"},
}


def _validate_index_family(index: Any, items: list[tuple[Path, Any]], index_path: Path, result: dict[str, Any]) -> None:
    if not isinstance(index, dict) or index.get("schema") != "g004-index/v1":
        return
    declared = index.get("family")
    allowed = INDEX_FAMILY_MEMBERS.get(declared) if isinstance(declared, str) else None
    if allowed is None:
        _err(result, str(index_path), "family", f"unsupported or missing g004 index family {declared!r}")
        return
    for path, value in items:
        values = value if isinstance(value, list) else [value]
        for item in values:
            actual = detect_family(item) if isinstance(item, dict) else None
            if actual not in allowed:
                _err(
                    result,
                    str(path),
                    "family",
                    f"artifact family {actual!r} is not allowed by index family {declared!r}",
                )


def cmd_validate_index(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    index_path = _resolve_input(args.index, root=root, result=result)
    if index_path is None: return result
    index = _read_json_file(index_path, result, max_bytes=args.max_bytes)
    if index is None: return result
    entries = _index_entries(index, index_path, result)
    if not entries and result["ok"]:
        _err(result, str(index_path), "index", "index names no files")
    base_root = _index_base(
        index,
        index_path,
        root,
        result,
        entries=entries,
        max_bytes=args.max_bytes,
    )
    if not result["ok"] or base_root is None:
        _write_log(args.log, result)
        return result
    resolved_entries: list[tuple[Path, dict[str, Any]]] = []
    for entry in entries:
        path = _resolve_input(entry["path"], root=base_root, result=result)
        if path is None:
            continue
        declared_hash = _declared_entry_sha256(
            entry["metadata"],
            str(index_path),
            entry["field"],
            result,
        )
        if any(error["field"] == f"{entry['field']}.sha256" for error in result["errors"]):
            continue
        if declared_hash is not None:
            try:
                actual_hash = sha256_file(path, max_bytes=args.max_bytes)
            except (OSError, ValueError) as exc:
                _err(result, str(path), f"{entry['field']}.sha256", str(exc))
                continue
            if actual_hash != declared_hash:
                _err(
                    result,
                    str(path),
                    f"{entry['field']}.sha256",
                    f"raw-file sha256 mismatch: declared {declared_hash}, computed {actual_hash}",
                )
                continue
        resolved_entries.append((path, entry))
    if not result["ok"]:
        _write_log(args.log, result)
        return result
    items: list[tuple[Path, Any]] = []
    for path, entry in resolved_entries:
        val = _read_json_file(path, result, max_bytes=args.max_bytes)
        if val is not None:
            declared_family = entry["metadata"].get("family")
            actual_family = detect_family(val) if isinstance(val, dict) else None
            if declared_family is not None and declared_family != actual_family:
                _err(
                    result,
                    str(path),
                    f"{entry['field']}.family",
                    f"declared family {declared_family!r} does not match {actual_family!r}",
                )
            items.append((path, val))
    _validate_index_family(index, items, index_path, result)
    validate_values(items, result)
    _write_log(args.log, result)
    return result


def _read_jsonl_or_json(path: Path, result: dict[str, Any], *, max_bytes: int) -> list[dict[str, Any]] | None:
    try:
        if path.stat().st_size > max_bytes:
            _err(result, str(path), "size", f"file exceeds max size {max_bytes} bytes")
            return None
        text = path.read_text(encoding="utf-8")
        _checked(result, path)
        stripped = text.strip()
        if not stripped:
            return []
        if stripped[0] == "[":
            value = load_json_text(stripped)
            if not isinstance(value, list):
                _err(result, str(path), "json", "expected JSON array or JSONL")
                return None
            rows = value
        else:
            rows = [load_json_text(line) for line in text.splitlines() if line.strip()]
        bad = [i for i, row in enumerate(rows) if not isinstance(row, dict)]
        if bad:
            _err(result, str(path), "json", "all events must be objects")
            return None
        _normalize(rows)
        return rows  # type: ignore[return-value]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, DuplicateKeyError) as exc:
        _err(result, str(path), "json", str(exc)); return None


def _validate_event_stream(rows: list[dict[str, Any]], source: str, result: dict[str, Any]) -> None:
    ids: set[str] = set(); prev_seq: int | None = None; prev_time: str | None = None
    for idx, ev in enumerate(rows):
        _validate_artifact(ev, f"{source}#{idx}", result)
        eid = ev.get("event_id")
        if not isinstance(eid, str) or not eid:
            _err(result, source, f"events[{idx}].event_id", "event_id is required")
        elif eid in ids:
            _err(result, source, "event_id", f"duplicate event_id {eid}")
        else:
            ids.add(eid)
        seq = ev.get("sequence")
        if not isinstance(seq, int):
            _err(result, source, f"events[{idx}].sequence", "integer sequence is required")
        elif prev_seq is not None and seq < prev_seq and not ev.get("loss_record"):
            _err(result, source, "sequence", "out-of-order sequence requires loss_record")
        if isinstance(seq, int): prev_seq = seq
        ts = ev.get("observed_at")
        if isinstance(ts, str):
            if prev_time is not None and ts < prev_time and not ev.get("loss_record"):
                _err(result, source, "observed_at", "non-monotonic observed_at requires loss_record")
            prev_time = ts


def cmd_normalize_events(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    inp = _resolve_input(args.input, root=root, result=result)
    outp = _resolve_input(args.output, root=root, result=result, must_exist=False)
    if inp is None or outp is None: return result
    rows = _read_jsonl_or_json(inp, result, max_bytes=args.max_bytes)
    if rows is None: return result
    _validate_event_stream(rows, str(inp), result)
    if result["ok"]:
        rows = sorted((_normalize(row) for row in rows), key=lambda r: (r.get("sequence", 0), r.get("observed_at", ""), r.get("event_id", "")))
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))
    result["event_count"] = len(rows)
    _write_log(args.log, result)
    return result


def _event_digest_ok(ev: dict[str, Any], path: str, result: dict[str, Any]) -> None:
    sd = stored_digest(ev, "event")
    if sd is not None and sd != content_digest(ev, "event"):
        _err(result, path, "event_sha256", "stale event hash")


def cmd_pair(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    u_path = _resolve_input(args.untouched, root=root, result=result)
    i_path = _resolve_input(args.instrumented, root=root, result=result)
    outp = _resolve_input(args.output, root=root, result=result, must_exist=False)
    if u_path is None or i_path is None or outp is None: return result
    untouched = _read_jsonl_or_json(u_path, result, max_bytes=args.max_bytes)
    if untouched is None:
        return result
    instr = _read_jsonl_or_json(i_path, result, max_bytes=args.max_bytes)
    if instr is None:
        return result
    umap = {e.get("event_id"): e for e in untouched if isinstance(e.get("event_id"), str)}
    imap = {e.get("event_id"): e for e in instr if isinstance(e.get("event_id"), str)}
    for pfx, rows in ((str(u_path), untouched), (str(i_path), instr)):
        for ev in rows: _event_digest_ok(ev, pfx, result)
    pairs = []
    for eid in sorted(set(umap) | set(imap)):
        u = umap.get(eid); i = imap.get(eid)
        if u and i:
            status = "paired" if content_digest(u, "event") == content_digest(i, "event") else "accounted_divergence" if (i.get("accounted_divergence") or i.get("divergence_reason")) else "unaccounted_divergence"
            if status == "unaccounted_divergence": _err(result, str(i_path), eid, "instrumented event diverges without accounting")
        elif i and not (i.get("accounted_divergence") or i.get("divergence_reason")):
            status = "unaccounted_instrumented_extra"; _err(result, str(i_path), eid, "unaccounted instrumented extra event")
        elif u and not (u.get("loss_record") or u.get("accounted_loss")):
            status = "unaccounted_untouched_loss"; _err(result, str(u_path), eid, "unaccounted untouched loss")
        else:
            status = "accounted_loss_or_extra"
        pairs.append({"event_id": eid, "status": status, "untouched_sha256": content_digest(u, "event") if u else None, "instrumented_sha256": content_digest(i, "event") if i else None})
    ledger = {"schema": "g004-pairing-ledger/v1", "pairs": pairs}
    ledger["ledger_sha256"] = content_digest({"schema": ledger["schema"], "pairs": pairs}, "bundle")
    if result["ok"]:
        outp.parent.mkdir(parents=True, exist_ok=True); outp.write_bytes(canonical_json_bytes(ledger))
    result["event_count"] = len(set(umap) | set(imap))
    _write_log(args.log, result)
    return result


def cmd_emit_hook(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    mpath = _resolve_input(args.hook_manifest, root=root, result=result)
    outp = _resolve_input(args.event_out, root=root, result=result, must_exist=False)
    if mpath is None or outp is None: return result
    manifest = _read_json_file(mpath, result, max_bytes=args.max_bytes)
    if not isinstance(manifest, dict): return result
    _validate_artifact(manifest, str(mpath), result)
    if detect_family(manifest) != "hook": _err(result, str(mpath), "schema", "hook manifest is required")
    payload = {
        "schema": "g004-hook-payload/v1",
        "hook_manifest_id": manifest.get("hook_manifest_id") or manifest.get("id"),
        "event_schema_id": manifest.get("event_schema_id"),
        "immutable_source_refs": copy.deepcopy(manifest.get("immutable_source_refs", manifest.get("source_refs", []))),
        "synthetic": True,
        "evidence_tier": "E1",
    }
    if result["ok"]:
        outp.parent.mkdir(parents=True, exist_ok=True); outp.write_bytes(canonical_json_bytes(payload))
    _write_log(args.log, result)
    return result


def import_unknown_manifests(source_path: Path, output_dir: Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[Path]:
    if source_path.stat().st_size > max_bytes:
        raise ValueError(f"file exceeds max size {max_bytes} bytes")
    closure = load_json_text(source_path.read_text(encoding="utf-8"))
    unknowns = closure.get("nonterminal_unknowns") if isinstance(closure, dict) else None
    if not isinstance(unknowns, list) or len(unknowns) != 29:
        raise ValueError("source nonterminal_unknowns count must be exactly 29")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for idx, unk in enumerate(unknowns, 1):
        if not isinstance(unk, dict):
            raise ValueError("unknown entries must be objects")
        value = copy.deepcopy(unk)
        value["schema"] = "g004-unknown-manifest/v1"
        value["status"] = "nonterminal"
        value.setdefault("unknown_manifest_id", f"G004-{value.get('unknown_id', idx)}")
        value["manifest_sha256"] = content_digest(value, "unknown")
        path = output_dir / f"{idx:02d}-{value.get('unknown_id', 'unknown')}.json"
        path.write_bytes(canonical_json_bytes(value)); written.append(path)
    return written


def cmd_collect_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    result = _result(); root = Path(args.root).resolve() if args.root else None
    if not args.no_auto_start:
        _err(result, "<args>", "no_auto_start", "collect-dry-run requires --no-auto-start")
        return result
    if args.adapter not in {"untouched", "instrumented"}:
        _err(result, "<args>", "adapter", "adapter must be untouched or instrumented")
        return result
    outdir = _resolve_input(args.output_dir, root=root, result=result, must_exist=False, allow_dir=True)
    if outdir is None: return result
    outdir.mkdir(parents=True, exist_ok=True)
    session = args.session
    event = {"schema": "g004-event/v1", "event_id": f"EVT-G004-{session}-{args.adapter}", "event_schema_id": "g004-observation-event/v1", "sequence": 1, "observed_at": "2026-07-23T00:00:00Z", "hook_manifest_id": f"HOOK-G004-{session}", "collection_session_id": session, "run_correlation_id": f"{session}-{args.adapter}", "adapter": args.adapter, "synthetic": True, "evidence_tier": "E1"}
    run = {"schema": "g004-run-manifest/v1", "run_manifest_id": f"RUN-G004-{session}-{args.adapter}", "event_ids": [event["event_id"]], "collection_session_id": session, "adapter": args.adapter, "synthetic": True, "evidence_tier": "E1", "device_touch": False, "auto_start": False}
    replay = {"schema": "g004-replay-fixture/v1", "replay_fixture_id": f"RPL-G004-{session}-{args.adapter}", "run_manifest_id": run["run_manifest_id"], "run_manifest_sha256": content_digest(run, "run"), "collection_session_id": session, "synthetic": True, "evidence_tier": "E1"}
    bundle = {"schema": "g004-evidence-bundle/v1", "evidence_bundle_id": f"EVB-G004-{session}-{args.adapter}", "run_manifest_ids": [run["run_manifest_id"]], "replay_fixture_ids": [replay["replay_fixture_id"]], "collection_session_id": session, "synthetic": True, "evidence_tier": "E1", "device_touch": False}
    for obj, fam, name in ((event, "event", "event.json"), (run, "run", "run.json"), (replay, "replay", "replay.json"), (bundle, "bundle", "bundle.json")):
        obj["manifest_sha256"] = content_digest(obj, fam)
        p = outdir / name; p.write_bytes(canonical_json_bytes(obj)); _checked(result, p)
        result["manifest_ids"].append(artifact_identifier(obj, fam))
    if args.unknown_source:
        sp = _resolve_input(args.unknown_source, root=root, result=result)
        if sp:
            try:
                for p in import_unknown_manifests(sp, outdir / "unknowns", max_bytes=args.max_bytes):
                    _checked(result, p)
            except Exception as exc:
                _err(result, str(sp), "nonterminal_unknowns", str(exc))
    result["event_count"] = 1; result["synthetic_evidence_count"] = 4; result["manifest_ids"].sort()
    _write_log(args.log, result)
    return result


def _write_log(log_path: str | None, result: dict[str, Any]) -> None:
    if not log_path:
        return
    if not LOG_RE.search(log_path):
        _err(result, log_path, "log", "detailed log path must match .omx/ultragoal/logs/G004-*.log")
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--root")
        p.add_argument(
            "--max-filesize",
            "--max-bytes",
            dest="max_bytes",
            type=parse_filesize,
            default=DEFAULT_MAX_BYTES,
        )
        p.add_argument("--log")
    p = sub.add_parser("validate"); common(p); p.add_argument("--manifest", action="append"); p.add_argument("--bundle", action="append"); p.set_defaults(func=cmd_validate)
    p = sub.add_parser("validate-index"); common(p); p.add_argument("--index", required=True); p.set_defaults(func=cmd_validate_index)
    p = sub.add_parser("normalize-events"); common(p); p.add_argument("--input", required=True); p.add_argument("--output", required=True); p.set_defaults(func=cmd_normalize_events)
    p = sub.add_parser("pair"); common(p); p.add_argument("--untouched", required=True); p.add_argument("--instrumented", required=True); p.add_argument("--output", required=True); p.set_defaults(func=cmd_pair)
    p = sub.add_parser("emit-hook"); common(p); p.add_argument("--hook-manifest", "--manifest", dest="hook_manifest", required=True); p.add_argument("--event-out", "--output", dest="event_out", required=True); p.set_defaults(func=cmd_emit_hook)
    p = sub.add_parser("collect-dry-run"); common(p); p.add_argument("--adapter", required=True, choices=("untouched", "instrumented")); p.add_argument("--session", required=True, type=parse_session_id); p.add_argument("--output-dir", required=True); p.add_argument("--no-auto-start", action="store_true"); p.add_argument("--unknown-source"); p.set_defaults(func=cmd_collect_dry_run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CliArgumentError as exc:
        result = _result()
        _err(result, "<args>", "arguments", str(exc)[:1000])
        sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        return 2
    result = args.func(args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
