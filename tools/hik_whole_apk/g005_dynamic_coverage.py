#!/usr/bin/env python3
"""G005 dynamic coverage session/convergence CLI.

Stdlib-only helper for bounded, explicit JSON artifacts.  It performs only
passive host readiness probing and delegates final convergence validation to
``critic.validate_dynamic_convergence``.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from tools.hik_whole_apk import critic
from tools.hik_whole_apk import g004_observation_validator as g004

MAX_BYTES = 5 * 1024 * 1024
USB_BUS = Path("/dev/bus/usb")
RESEARCH_REL = Path(".omx/research/hikmicro-viewer-2.6.0")
CONVERGENCE_REL = RESEARCH_REL / "dynamic/exploration-convergence.json"
REQUIRED_TOOLS = ("adb", "frida", "frida-ps")
FINGERPRINT_FIELDS = ("device_fingerprint", "camera_fingerprint", "os_build", "abi")
FAKE_MARKERS = ("synthetic", "emulated", "dry-run", "dry_run")
FORBIDDEN_SOURCE_VARIANTS = {
    "synthetic",
    "emulated",
    "dry-run",
    "dry_run",
    "reimplementation",
    "replay-only",
    "replay_only",
}
PROOF_KEYS = {
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
OBSERVATION_KEYS = {"observation_id", "claim_ids", "ledger_row_ids", "evidence_bundle_ids", "instrumentation_label", "event_refs"}
TEMPERATURE_MARKERS = ("celsius", "temperature", "°c", "degc", "centigrade")
META_KEYS = {
    "schema_version",
    "proof_path",
    "run_manifest",
    "bundle_index",
    "evidence_tier",
    "new_rows",
    "added_row_ids",
    "raw_hashes",
    "ledger_before_sha256",
    "ledger_after_sha256",
    "started_at",
    "ended_at",
    "source_variant",
    "artifact_set_id",
    "paired_untouched_run",
    "paired_untouched_run_id",
    "paired_untouched_run_path",
}


class G005Error(ValueError):
    """User-facing fail-closed validation error."""


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise G005Error(message)


def canonical_json_bytes(value: Any) -> bytes:
    return g004.canonical_json_bytes(value)


def sha256_bytes(data: bytes) -> str:
    return g004.sha256_bytes(data)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def critic_canonical_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _error(field: str, message: str, *, path: str = "<args>") -> dict[str, str]:
    return {"path": path, "field": field, "message": message}


def _rel_parts(path_arg: str) -> tuple[str, ...]:
    return PurePosixPath(path_arg.replace(os.sep, "/")).parts


def resolve_path(path_arg: str, *, root: Path | None, must_exist: bool, allow_dir: bool = False) -> Path:
    if not path_arg:
        raise G005Error("explicit path is required")
    if ".." in _rel_parts(path_arg):
        raise G005Error("path escape is forbidden")
    raw = Path(path_arg)
    boundary = root.resolve() if root is not None else None
    candidate = raw if raw.is_absolute() else ((boundary if boundary else Path.cwd()) / raw)
    try:
        resolved = candidate.resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise G005Error(f"path does not exist: {candidate}") from exc
    except OSError as exc:
        raise G005Error(f"cannot resolve path {candidate}: {exc}") from exc
    if boundary is not None:
        try:
            resolved.relative_to(boundary)
        except ValueError as exc:
            raise G005Error("path is outside declared root") from exc
    if must_exist:
        if allow_dir:
            if not resolved.is_dir():
                raise G005Error("explicit directory path is required")
        elif not resolved.is_file():
            raise G005Error("explicit file path is required; no directory scans")
    return resolved


def read_json(path: Path, checked: list[str], *, max_bytes: int) -> Any:
    if path.stat().st_size > max_bytes:
        raise G005Error(f"file exceeds max size {max_bytes} bytes: {path}")
    try:
        value = g004.load_json_text(path.read_text(encoding="utf-8"))
        canonical_json_bytes(value)
    except Exception as exc:
        if isinstance(exc, G005Error):
            raise
        raise G005Error(f"invalid bounded JSON {path}: {exc}") from exc
    checked.append(str(path))
    return value


def write_json(path: Path, payload: Mapping[str, Any], checked: list[str], *, max_bytes: int) -> str:
    encoded = canonical_json_bytes(payload)
    if len(encoded) > max_bytes:
        raise G005Error(f"output exceeds max size {max_bytes} bytes: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    checked.append(str(path))
    return sha256_bytes(encoded)


def json_hash(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def file_hash(path: Path, *, max_bytes: int = MAX_BYTES) -> str:
    if path.stat().st_size > max_bytes:
        raise G005Error(f"file exceeds max size {max_bytes} bytes: {path}")
    return sha256_bytes(path.read_bytes())


def artifact_set_id(identity: Mapping[str, Any]) -> str:
    value = identity.get("artifact_set_id") or identity.get("official_artifact_set_id") or identity.get("id")
    if not isinstance(value, str) or not value:
        raise G005Error("official identity must contain artifact_set_id, official_artifact_set_id, or id")
    return value


def ledger_rows(ledger: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = ledger.get("rows")
    if not isinstance(rows, list):
        raise G005Error("ledger must contain rows list")
    out: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise G005Error(f"ledger row {index} is not an object")
        row_id = row.get("row_id") or row.get("id")
        if not isinstance(row_id, str) or not row_id:
            raise G005Error(f"ledger row {index} has no row_id/id")
        if row_id in out:
            raise G005Error(f"duplicate ledger row: {row_id}")
        out[row_id] = row
    return out


def _env(mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    value = mapping.get("environment")
    return value if isinstance(value, Mapping) else mapping


def _require_fingerprints(label: str, mapping: Mapping[str, Any]) -> Mapping[str, Any]:
    env = _env(mapping)
    missing = [field for field in FINGERPRINT_FIELDS if not isinstance(env.get(field), str) or not env.get(field)]
    if missing:
        raise G005Error(f"{label} missing fingerprints: {', '.join(missing)}")
    return env


def _require_matching_fingerprints(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> None:
    run_env = _require_fingerprints("run", run)
    for n, bundle in enumerate(bundles):
        bundle_env = _require_fingerprints(f"bundle {n}", bundle)
        mismatched = [field for field in FINGERPRINT_FIELDS if bundle_env.get(field) != run_env.get(field)]
        if mismatched:
            raise G005Error(f"bundle {n} fingerprint mismatch: {', '.join(mismatched)}")


def _source_variant(mapping: Mapping[str, Any]) -> str:
    value = mapping.get("source_variant") or mapping.get("variant")
    return str(value) if value is not None else ""


def _evidence_tier(mapping: Mapping[str, Any]) -> str:
    return str(mapping.get("evidence_tier") or mapping.get("tier") or "").upper()


def _reject_fake_live(label: str, mapping: Mapping[str, Any]) -> None:
    blob = json.dumps(mapping, sort_keys=True, ensure_ascii=False).lower()
    variant = _source_variant(mapping).lower()
    tier = _evidence_tier(mapping)
    if mapping.get("synthetic") is True or variant in FORBIDDEN_SOURCE_VARIANTS or tier == "E1":
        raise G005Error(f"{label} is not acceptable live dynamic evidence")
    for marker in FAKE_MARKERS:
        if marker in blob:
            raise G005Error(f"{label} contains fake-live marker: {marker}")


def _parse_time(label: str, value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise G005Error(f"{label} timestamp is required")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise G005Error(f"{label} timestamp is invalid") from exc


def _time_value(mapping: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _verify_timestamps(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    start_text = _time_value(run, "started_at", "start")
    end_text = _time_value(run, "ended_at", "end")
    start = _parse_time("run started_at", start_text)
    end = _parse_time("run ended_at", end_text)
    if end < start:
        raise G005Error("run ended_at precedes started_at")
    for n, bundle in enumerate(bundles):
        captured_text = _time_value(bundle, "captured_at", "timestamp", "started_at")
        if captured_text:
            captured = _parse_time(f"bundle {n} captured_at", captured_text)
            if not start <= captured <= end:
                raise G005Error(f"bundle {n} timestamp falls outside run interval")
    return start_text, end_text


def _bundle_list(index: Any) -> list[Mapping[str, Any]]:
    if isinstance(index, list):
        items = index
    elif isinstance(index, Mapping):
        raw = index.get("bundles") or index.get("evidence_bundles") or index.get("items")
        items = raw if isinstance(raw, list) else []
    else:
        items = []
    bundles = [item for item in items if isinstance(item, Mapping)]
    if not bundles:
        raise G005Error("bundle index must contain explicit bundles list")
    return bundles


def _bundle_id(bundle: Mapping[str, Any], index: int) -> str:
    value = bundle.get("evidence_bundle_id") or bundle.get("bundle_id") or bundle.get("id")
    if not isinstance(value, str) or not value:
        raise G005Error(f"bundle {index} has no evidence_bundle_id/bundle_id/id")
    return value


def _bundle_ids(bundles: Sequence[Mapping[str, Any]]) -> list[str]:
    return [_bundle_id(bundle, index) for index, bundle in enumerate(bundles)]


def _claim_ids(bundle: Mapping[str, Any]) -> list[str]:
    raw = bundle.get("claim_ids")
    if isinstance(raw, list) and all(isinstance(item, str) and item for item in raw):
        return list(raw)
    claim = bundle.get("claim_id")
    if isinstance(claim, str) and claim:
        return [claim]
    return []


def _event_ref(bundle: Mapping[str, Any], bundle_id: str) -> dict[str, Any]:
    stream = bundle.get("event_stream") if isinstance(bundle.get("event_stream"), Mapping) else {}
    path = bundle.get("normalized_attachment") or stream.get("normalized_attachment") or bundle.get("event_path")
    event_ids = bundle.get("event_ids") or stream.get("event_ids")
    if not isinstance(path, str) or not path:
        raise G005Error(f"bundle {bundle_id} missing explicit normalized event path")
    if not isinstance(event_ids, list) or not event_ids or not all(isinstance(item, str) and item for item in event_ids):
        raise G005Error(f"bundle {bundle_id} missing explicit event_ids")
    return {"bundle_id": bundle_id, "path": path, "event_ids": list(event_ids)}




def _run_id(run: Mapping[str, Any], label: str = "run") -> str:
    value = run.get("run_id") or run.get("id")
    if not isinstance(value, str) or not value:
        raise G005Error(f"{label} requires run_id/id")
    return value


def _artifact_id(mapping: Mapping[str, Any]) -> str:
    value = mapping.get("artifact_set_id")
    return value if isinstance(value, str) else ""


def _require_bundle_run_match(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]], *, tier: str, variant: str) -> None:
    run_artifact = _artifact_id(run)
    if not run_artifact:
        raise G005Error("run artifact_set_id is required")
    run_variant = _source_variant(run)
    run_tier = _evidence_tier(run)
    if run_variant and run_variant != variant:
        raise G005Error("run source_variant disagrees with derived session variant")
    if run_tier and run_tier != tier:
        raise G005Error("run evidence_tier disagrees with derived session tier")
    for index, bundle in enumerate(bundles):
        if _artifact_id(bundle) != run_artifact:
            raise G005Error(f"bundle {index} artifact_set_id mismatch")
        if _source_variant(bundle) != variant:
            raise G005Error(f"bundle {index} source_variant mismatch")
        if _evidence_tier(bundle) != tier:
            raise G005Error(f"bundle {index} evidence_tier mismatch")


def _has_temperature_marker(value: str) -> bool:
    text = value.lower()
    return any(marker in text for marker in TEMPERATURE_MARKERS)


def _empty_temperature_value(value: Any) -> bool:
    return value is None or value is False or value == "" or value == [] or value == {}


def _contains_temperature_claim(value: Any, *, from_temperature_key: bool = False) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_marks_temperature = isinstance(key, str) and _has_temperature_marker(key)
            if key_marks_temperature and _empty_temperature_value(item):
                continue
            if key_marks_temperature or _contains_temperature_claim(item, from_temperature_key=key_marks_temperature):
                return True
        return False
    if isinstance(value, list):
        if from_temperature_key and not value:
            return False
        return any(_contains_temperature_claim(item, from_temperature_key=from_temperature_key) for item in value)
    if isinstance(value, str):
        if from_temperature_key:
            return bool(value)
        return _has_temperature_marker(value)
    return from_temperature_key and value is not None and value is not False


def _reject_unapproved_temperature_claims(label: str, mapping: Mapping[str, Any], *, root: Path) -> None:
    if not _contains_temperature_claim(mapping):
        return
    try:
        critic.validate_radiometric_truthfulness(root)
    except Exception as exc:
        raise G005Error(
            f"{label} contains Celsius/temperature claim without canonical approved radiometric proof"
        ) from exc


def _delta_has_instrumentation(mapping: Mapping[str, Any]) -> bool:
    delta = mapping.get("instrumentation_delta")
    if delta is None:
        return False
    if not isinstance(delta, Mapping):
        raise G005Error("instrumentation_delta must be an object")
    descriptive_keys = {"summary", "expected_perturbation"}
    for key, value in delta.items():
        if key in descriptive_keys:
            continue
        if value not in (None, False, 0, "", [], {}):
            return True
    return False


def _require_untouched_session(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> None:
    if _delta_has_instrumentation(run):
        raise G005Error("untouched E2 run declares instrumentation")
    for index, bundle in enumerate(bundles):
        if _delta_has_instrumentation(bundle):
            raise G005Error(f"untouched E2 bundle {index} declares instrumentation")


def _data_state_identity(run: Mapping[str, Any], *, label: str) -> tuple[str, str]:
    baseline_id = run.get("baseline_id")
    snapshot = run.get("data_state_snapshot")
    if not isinstance(baseline_id, str) or not baseline_id:
        raise G005Error(f"{label} baseline_id is required")
    if not isinstance(snapshot, Mapping):
        raise G005Error(f"{label} data_state_snapshot is required")
    snapshot_hash = snapshot.get("sha256")
    if not _is_sha256(snapshot_hash):
        raise G005Error(f"{label} data_state_snapshot.sha256 is invalid")
    return baseline_id, snapshot_hash


def _require_pair_compatibility(
    untouched: Mapping[str, Any],
    instrumented: Mapping[str, Any],
) -> None:
    if _artifact_id(untouched) != _artifact_id(instrumented):
        raise G005Error("paired E2/E3 artifact_set_id mismatch")
    untouched_env = _require_fingerprints("paired untouched run", untouched)
    instrumented_env = _require_fingerprints("instrumented run", instrumented)
    mismatched = [
        field for field in FINGERPRINT_FIELDS if untouched_env.get(field) != instrumented_env.get(field)
    ]
    for field in ("network_profile",):
        if untouched_env.get(field) != instrumented_env.get(field):
            mismatched.append(field)
    if mismatched:
        raise G005Error(f"paired E2/E3 environment mismatch: {', '.join(mismatched)}")
    if _data_state_identity(untouched, label="paired untouched run") != _data_state_identity(
        instrumented,
        label="instrumented run",
    ):
        raise G005Error("paired E2/E3 baseline or data-state snapshot mismatch")


def _require_unique_event_refs(event_refs: Sequence[Mapping[str, Any]]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for ref in event_refs:
        bundle_id = str(ref.get("bundle_id"))
        path = str(ref.get("path"))
        for event_id in ref.get("event_ids", []):
            key = (bundle_id, path, str(event_id))
            if key in seen:
                raise G005Error(f"event reference reused across observations: {event_id}")
            seen.add(key)

def _primary_tier(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> str:
    run_tier = _evidence_tier(run)
    tiers = [run_tier] if run_tier else []
    tiers.extend(_evidence_tier(bundle) for bundle in bundles if _evidence_tier(bundle))
    if "E3" in tiers:
        return "E3"
    if "E2" in tiers:
        return "E2"
    raise G005Error("session must declare E2 or E3 evidence tier")


def _require_concrete_delta(run: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> None:
    delta = run.get("instrumentation_delta")
    if not isinstance(delta, Mapping) or not delta:
        raise G005Error("instrumented E3 requires concrete instrumentation_delta")
    if not any(value not in (None, False, 0, "", [], {}) for value in delta.values()):
        raise G005Error("instrumented E3 requires non-empty concrete instrumentation_delta")
    if not any(_source_variant(bundle) != "untouched" or bool(bundle.get("instrumentation_delta")) for bundle in bundles):
        raise G005Error("instrumented E3 requires concrete instrumented bundle delta")


def _load_paired_untouched(path_arg: str | None, *, root: Path, checked: list[str], max_bytes: int, run: Mapping[str, Any], run_start: str) -> tuple[str, str]:
    if not path_arg:
        raise G005Error("instrumented E3 requires --paired-untouched-run")
    paired_path = resolve_path(path_arg, root=root, must_exist=True)
    paired = read_json(paired_path, checked, max_bytes=max_bytes)
    if not isinstance(paired, Mapping):
        raise G005Error("paired untouched run must be a JSON object")
    _reject_fake_live("paired untouched run", paired)
    if _source_variant(paired) != "untouched" or _evidence_tier(paired) != "E2":
        raise G005Error("paired immediately-prior run must be untouched E2")
    _require_pair_compatibility(paired, run)
    paired_id = _run_id(paired, "paired untouched run")
    run_delta = run.get("instrumentation_delta")
    declared_pair = run_delta.get("paired_untouched_run_id") if isinstance(run_delta, Mapping) else None
    if declared_pair != paired_id:
        raise G005Error("run instrumentation_delta.paired_untouched_run_id does not match paired untouched run")
    paired_end = _time_value(paired, "ended_at", "end")
    if _parse_time("paired run ended_at", paired_end) > _parse_time("run started_at", run_start):
        raise G005Error("paired untouched E2 run is not temporally prior to instrumented E3")
    return paired_id, _relative_to_root(paired_path, root)


def _relative_to_root(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _proof_meta_path(proof_path: Path) -> Path:
    return proof_path.with_name(proof_path.name + ".meta.json")


def _proof_bundle_id(proof: Mapping[str, Any]) -> str:
    observations = proof.get("observations")
    if isinstance(observations, list):
        for observation in observations:
            if isinstance(observation, Mapping):
                bundles = observation.get("evidence_bundle_ids")
                if isinstance(bundles, list):
                    for bundle_id in bundles:
                        if isinstance(bundle_id, str) and bundle_id:
                            return bundle_id
    raise G005Error("session proof has no evidence bundle IDs")


def cmd_probe(args: argparse.Namespace) -> dict[str, Any]:
    checked: list[str] = []
    output = resolve_path(args.output, root=None, must_exist=False)
    statuses = {name: shutil.which(name) is not None for name in REQUIRED_TOOLS}
    usb_present = USB_BUS.exists()
    ok = all(statuses.values()) and usb_present
    payload = {
        "ok": ok,
        "status": "ready" if ok else "nonterminal_readiness",
        "checked_files": [],
        "passive": True,
        "probes": {"commands": statuses, "usb_bus_exists": usb_present},
        "errors": [] if ok else [_error("prerequisites", "required host tools or USB bus are unavailable")],
    }
    write_json(output, payload, checked, max_bytes=args.max_filesize)
    payload["checked_files"] = checked
    write_json(output, payload, [], max_bytes=args.max_filesize)
    return payload


def cmd_prepare(args: argparse.Namespace) -> dict[str, Any]:
    checked: list[str] = []
    root = resolve_path(args.root, root=None, must_exist=True, allow_dir=True)
    identity_path = resolve_path(args.official_identity, root=root, must_exist=True)
    ledger_path = resolve_path(args.ledger, root=root, must_exist=True)
    out_path = resolve_path(args.out, root=root, must_exist=False)
    identity = read_json(identity_path, checked, max_bytes=args.max_filesize)
    ledger = read_json(ledger_path, checked, max_bytes=args.max_filesize)
    if not isinstance(identity, Mapping) or not isinstance(ledger, Mapping):
        raise G005Error("official identity and ledger must be JSON objects")
    payload = {
        "schema_version": 1,
        "artifact_set_id": artifact_set_id(identity),
        "status": "prepared_not_live_unsigned",
        "live": False,
        "signed": False,
        "official_identity": {"path": str(identity_path), "sha256": file_hash(identity_path, max_bytes=args.max_filesize), "canonical_sha256": json_hash(identity)},
        "ledger": {"path": str(ledger_path), "sha256": file_hash(ledger_path, max_bytes=args.max_filesize), "canonical_sha256": json_hash(ledger)},
    }
    digest = write_json(out_path, payload, checked, max_bytes=args.max_filesize)
    return {"ok": True, "status": "prepared_not_live_unsigned", "checked_files": checked, "output": str(out_path), "sha256": digest, "errors": []}


def cmd_record(args: argparse.Namespace) -> dict[str, Any]:
    checked: list[str] = []
    root = resolve_path(args.root, root=None, must_exist=True, allow_dir=True)
    run_path = resolve_path(args.run, root=root, must_exist=True)
    index_path = resolve_path(args.bundle_index, root=root, must_exist=True)
    before_path = resolve_path(args.ledger_before, root=root, must_exist=True)
    after_path = resolve_path(args.ledger_after, root=root, must_exist=True)
    out_path = resolve_path(args.out, root=root, must_exist=False)
    run = read_json(run_path, checked, max_bytes=args.max_filesize)
    index = read_json(index_path, checked, max_bytes=args.max_filesize)
    before = read_json(before_path, checked, max_bytes=args.max_filesize)
    after = read_json(after_path, checked, max_bytes=args.max_filesize)
    if not all(isinstance(v, Mapping) for v in (run, before, after)):
        raise G005Error("run and ledgers must be JSON objects")
    bundles = _bundle_list(index)
    _reject_fake_live("run", run)
    for n, bundle in enumerate(bundles):
        _reject_fake_live(f"bundle {n}", bundle)
        _reject_unapproved_temperature_claims(f"bundle {n}", bundle, root=root)
    _reject_unapproved_temperature_claims("run", run, root=root)
    _require_matching_fingerprints(run, bundles)
    start_text, end_text = _verify_timestamps(run, bundles)
    tier = _primary_tier(run, bundles)
    variant = _source_variant(run) or ("root-attached" if tier == "E3" else "untouched")
    if tier == "E2" and variant != "untouched":
        raise G005Error("E2 session must be standalone untouched evidence")
    if tier == "E2":
        _require_untouched_session(run, bundles)
    _require_bundle_run_match(run, bundles, tier=tier, variant=variant)
    paired_untouched_run_id = ""
    paired_untouched_run_path = ""
    if tier == "E3":
        if variant == "untouched":
            raise G005Error("E3 session must be instrumented, not untouched")
        _require_concrete_delta(run, bundles)
        paired_untouched_run_id, paired_untouched_run_path = _load_paired_untouched(
            args.paired_untouched_run,
            root=root,
            checked=checked,
            max_bytes=args.max_filesize,
            run=run,
            run_start=start_text,
        )

    before_rows = ledger_rows(before)
    after_rows = ledger_rows(after)
    removed = sorted(set(before_rows) - set(after_rows))
    if removed:
        raise G005Error(f"ledger rows removed: {removed}")
    added = sorted(set(after_rows) - set(before_rows))
    bundle_ids = _bundle_ids(bundles)
    all_claims: list[str] = []
    event_refs: list[dict[str, Any]] = []
    for bundle_id, bundle in zip(bundle_ids, bundles):
        for claim_id in _claim_ids(bundle):
            if claim_id not in all_claims:
                all_claims.append(claim_id)
        event_refs.append(_event_ref(bundle, bundle_id))
    if not all_claims:
        raise G005Error("session requires explicit claim_ids in bundle index")
    _require_unique_event_refs(event_refs)

    observations = [
        {
            "observation_id": f"OBS-{args.session_id}-1",
            "claim_ids": all_claims,
            "ledger_row_ids": added,
            "evidence_bundle_ids": bundle_ids,
            "instrumentation_label": variant,
            "event_refs": event_refs,
        }
    ]
    artifact = run.get("artifact_set_id") or (index.get("artifact_set_id") if isinstance(index, Mapping) else None) or args.artifact_set_id
    if not isinstance(artifact, str) or not artifact:
        raise G005Error("artifact_set_id is required from run, bundle index, or --artifact-set-id")
    proof_base = {
        "schema_version": 1,
        "proof_id": f"DYN-{args.session_id}",
        "artifact_set_id": artifact,
        "run_id": str(run.get("run_id") or run.get("id") or args.session_id),
        "experiment_id": str(run.get("experiment_id") or args.session_id),
        "source_variant": variant,
        "ledger_before": {"bundle_id": bundle_ids[0], "path": _relative_to_root(before_path, root)},
        "ledger_after": {"bundle_id": bundle_ids[-1], "path": _relative_to_root(after_path, root)},
        "observations": observations,
        "instrumented_observations_labeled": True,
        "unexplained_baseline_divergence_ids": [],
    }
    proof = dict(proof_base)
    proof["canonical_sha256"] = critic_canonical_sha256(proof_base)
    digest = write_json(out_path, proof, checked, max_bytes=args.max_filesize)

    meta = {
        "schema_version": 1,
        "proof_path": _relative_to_root(out_path, root),
        "run_manifest": _relative_to_root(run_path, root),
        "bundle_index": _relative_to_root(index_path, root),
        "evidence_tier": tier,
        "new_rows": len(added),
        "added_row_ids": added,
        "raw_hashes": {
            "run": file_hash(run_path, max_bytes=args.max_filesize),
            "bundle_index": file_hash(index_path, max_bytes=args.max_filesize),
            "ledger_before": file_hash(before_path, max_bytes=args.max_filesize),
            "ledger_after": file_hash(after_path, max_bytes=args.max_filesize),
            "proof": file_hash(out_path, max_bytes=args.max_filesize),
        },
        "ledger_before_sha256": file_hash(before_path, max_bytes=args.max_filesize),
        "ledger_after_sha256": file_hash(after_path, max_bytes=args.max_filesize),
        "started_at": start_text,
        "ended_at": end_text,
        "source_variant": variant,
        "artifact_set_id": artifact,
        "paired_untouched_run": args.paired_untouched_run or "",
        "paired_untouched_run_id": paired_untouched_run_id,
        "paired_untouched_run_path": paired_untouched_run_path,
    }
    write_json(_proof_meta_path(out_path), meta, checked, max_bytes=args.max_filesize)
    return {
        "ok": True,
        "status": "session_proof_draft_recorded",
        "checked_files": checked,
        "output": str(out_path),
        "sha256": digest,
        "new_rows": len(added),
        "errors": [],
    }


def _load_proof(path: Path, checked: list[str], *, max_bytes: int) -> Mapping[str, Any]:
    value = read_json(path, checked, max_bytes=max_bytes)
    if not isinstance(value, Mapping):
        raise G005Error("session proof must be a JSON object")
    if set(value) != PROOF_KEYS:
        raise G005Error("session proof is not critic-compatible exact-key shape")
    canonical = dict(value)
    canonical.pop("canonical_sha256", None)
    if value.get("canonical_sha256") != critic_canonical_sha256(canonical):
        raise G005Error("session proof canonical_sha256 mismatch")
    observations = value.get("observations")
    if not isinstance(observations, list) or not observations:
        raise G005Error("session proof observations must be nonempty")
    for index, observation in enumerate(observations):
        if not isinstance(observation, Mapping) or set(observation) != OBSERVATION_KEYS:
            raise G005Error(f"session proof observation {index} is not critic-compatible exact-key shape")
    return value


def _load_meta(path: Path, root: Path, checked: list[str], *, max_bytes: int) -> Mapping[str, Any]:
    meta_path = _proof_meta_path(path)
    meta = read_json(meta_path, checked, max_bytes=max_bytes)
    if not isinstance(meta, Mapping):
        raise G005Error("session proof metadata must be a JSON object")
    if set(meta) != META_KEYS:
        raise G005Error("session proof metadata is not exact-key shape")
    run_manifest = meta.get("run_manifest")
    proof_path = meta.get("proof_path")
    if not isinstance(run_manifest, str) or not run_manifest or not isinstance(proof_path, str) or not proof_path:
        raise G005Error("session proof metadata requires nonempty run_manifest/proof_path")
    if meta.get("schema_version") != 1:
        raise G005Error("session proof metadata schema_version must be 1")
    if type(meta.get("new_rows")) is not int or meta["new_rows"] < 0:
        raise G005Error("session proof metadata new_rows must be a nonnegative integer")
    added_row_ids = meta.get("added_row_ids")
    if not isinstance(added_row_ids, list) or not all(
        isinstance(row_id, str) and row_id for row_id in added_row_ids
    ):
        raise G005Error("session proof metadata added_row_ids must be a string list")
    if len(added_row_ids) != meta["new_rows"] or len(set(added_row_ids)) != len(added_row_ids):
        raise G005Error("session proof metadata new_rows/added_row_ids mismatch")
    if str(meta.get("evidence_tier") or "").upper() not in {"E2", "E3"}:
        raise G005Error("session proof metadata evidence_tier must be E2 or E3")
    for key in (
        "bundle_index",
        "started_at",
        "ended_at",
        "source_variant",
        "artifact_set_id",
        "paired_untouched_run",
        "paired_untouched_run_id",
        "paired_untouched_run_path",
    ):
        if not isinstance(meta.get(key), str):
            raise G005Error(f"session proof metadata {key} must be a string")
    raw_hashes = meta.get("raw_hashes")
    if not isinstance(raw_hashes, Mapping) or set(raw_hashes) != {
        "run",
        "bundle_index",
        "ledger_before",
        "ledger_after",
        "proof",
    }:
        raise G005Error("session proof metadata raw_hashes is not exact-key shape")
    for key, value in raw_hashes.items():
        if not _is_sha256(value):
            raise G005Error(f"session proof metadata raw_hashes.{key} is not SHA-256")
    for key in ("ledger_before_sha256", "ledger_after_sha256"):
        value = meta.get(key)
        if not _is_sha256(value):
            raise G005Error(f"session proof metadata {key} is not SHA-256")
    resolved_proof_path = resolve_path(proof_path, root=root, must_exist=True)
    if resolved_proof_path != path.resolve():
        raise G005Error("session proof metadata proof_path does not match loaded proof")
    resolve_path(run_manifest, root=root, must_exist=True)
    return meta


def _ledger_ref_hash(meta: Mapping[str, Any], name: str) -> str:
    value = meta.get(f"{name}_sha256")
    if not isinstance(value, str) or not value:
        raise G005Error(f"metadata missing {name}_sha256")
    return value


def _interval(meta: Mapping[str, Any]) -> tuple[datetime, datetime]:
    start = str(meta.get("started_at") or "")
    end = str(meta.get("ended_at") or "")
    start_time = _parse_time("session started_at", start)
    end_time = _parse_time("session ended_at", end)
    if end_time < start_time:
        raise G005Error("session proof has inverted time interval")
    return start_time, end_time


def _proof_bundle_ids(proof: Mapping[str, Any]) -> set[str]:
    bundle_ids: set[str] = set()
    for observation in proof["observations"]:
        raw = observation.get("evidence_bundle_ids")
        if isinstance(raw, list):
            bundle_ids.update(str(item) for item in raw if isinstance(item, str) and item)
    if not bundle_ids:
        raise G005Error("session proof has no evidence bundle IDs")
    return bundle_ids




def _assert_raw_hash(label: str, path: Path, raw_hashes: Mapping[str, Any], key: str, *, max_bytes: int, expected: str | None = None) -> None:
    actual = file_hash(path, max_bytes=max_bytes)
    declared = raw_hashes.get(key)
    if not isinstance(declared, str) or declared != actual:
        raise G005Error(f"session proof sidecar {label} raw hash mismatch")
    if expected is not None and expected != actual:
        raise G005Error(f"session proof metadata {label} sha256 mismatch")


def _load_run_for_meta(proof_path: Path, proof: Mapping[str, Any], meta: Mapping[str, Any], root: Path, checked: list[str], *, max_bytes: int) -> Mapping[str, Any]:
    run_path = resolve_path(str(meta["run_manifest"]), root=root, must_exist=True)
    run = read_json(run_path, checked, max_bytes=max_bytes)
    if not isinstance(run, Mapping):
        raise G005Error("referenced run manifest must be a JSON object")
    raw_hashes = meta.get("raw_hashes")
    if not isinstance(raw_hashes, Mapping):
        raise G005Error("session proof metadata requires raw_hashes")
    _assert_raw_hash("run", run_path, raw_hashes, "run", max_bytes=max_bytes)
    _assert_raw_hash("proof", proof_path, raw_hashes, "proof", max_bytes=max_bytes)
    for phase in ("ledger_before", "ledger_after"):
        ref = proof.get(phase)
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str) or not ref["path"]:
            raise G005Error(f"session proof {phase} path is missing")
        ledger_path = resolve_path(str(ref["path"]), root=root, must_exist=True)
        read_json(ledger_path, checked, max_bytes=max_bytes)
        _assert_raw_hash(phase, ledger_path, raw_hashes, phase, max_bytes=max_bytes, expected=meta.get(f"{phase}_sha256") if isinstance(meta.get(f"{phase}_sha256"), str) else None)
    bundle_index = meta.get("bundle_index")
    if isinstance(bundle_index, str) and bundle_index:
        bundle_index_path = resolve_path(bundle_index, root=root, must_exist=True)
        read_json(bundle_index_path, checked, max_bytes=max_bytes)
        _assert_raw_hash("bundle_index", bundle_index_path, raw_hashes, "bundle_index", max_bytes=max_bytes)
    elif isinstance(raw_hashes.get("bundle_index"), str):
        raise G005Error("session proof metadata has bundle_index hash but no bundle_index path")
    if _run_id(run) != proof.get("run_id"):
        raise G005Error("session proof run_id does not match referenced run manifest")
    if str(run.get("experiment_id") or "") != proof.get("experiment_id"):
        raise G005Error("session proof experiment_id does not match referenced run manifest")
    if _source_variant(run) != proof.get("source_variant"):
        raise G005Error("session proof source_variant does not match referenced run manifest")
    if _evidence_tier(run) != str(meta.get("evidence_tier") or "").upper():
        raise G005Error("session proof tier does not match referenced run manifest")
    if _artifact_id(run) and _artifact_id(run) != proof.get("artifact_set_id"):
        raise G005Error("session proof artifact_set_id does not match referenced run manifest")
    start_text, end_text = _verify_timestamps(run, [])
    if start_text != meta.get("started_at") or end_text != meta.get("ended_at"):
        raise G005Error("session proof interval does not match referenced run manifest")
    return run


def _closure_counters_from_ledger(ledger: Mapping[str, Any]) -> tuple[dict[str, int], dict[str, list[str]], int]:
    rows = ledger_rows(ledger)
    unresolved = {
        "blocked": sorted(row_id for row_id, row in rows.items() if row.get("state") == "blocked"),
        "missing": sorted(row_id for row_id, row in rows.items() if row.get("state") == "missing"),
        "nonterminal": sorted(row_id for row_id, row in rows.items() if row.get("state") != "verified"),
        "public_proprietary_material_leaks": sorted(row_id for row_id, row in rows.items() if row.get("public_proprietary_material_leak") is True),
        "replay_failures": sorted(row_id for row_id, row in rows.items() if row.get("replay_status") == "failed"),
        "stale_evidence": sorted(row_id for row_id, row in rows.items() if row.get("evidence_status") == "stale"),
        "unclassified": sorted(row_id for row_id, row in rows.items() if row.get("classification_status") != "classified"),
        "unlabeled_unknown_observations": sorted(row_id for row_id, row in rows.items() if row.get("classification_status") in {"unknown", "unclassified"}),
        "unresolved_contradictions": sorted(row_id for row_id, row in rows.items() if row.get("contradiction_status") == "unresolved"),
    }
    counters = {key: len(value) for key, value in unresolved.items()}
    frontier_count = 1 if ledger.get("current_causal_frontier") is not None else 0
    return counters, unresolved, frontier_count


def _closure_sidecar_payload(
    convergence_path: Path,
    root: Path,
    canonical_ledger: Path,
    canonical_ledger_doc: Mapping[str, Any],
    *,
    max_bytes: int,
) -> dict[str, Any]:
    counters, unresolved, frontier_count = _closure_counters_from_ledger(canonical_ledger_doc)
    return {
        "schema_version": 1,
        "artifact_set_id": str(canonical_ledger_doc.get("artifact_set_id") or ""),
        "convergence_path": _relative_to_root(convergence_path, root),
        "computed_from_ledger": _relative_to_root(canonical_ledger, root),
        "ledger_sha256": file_hash(canonical_ledger, max_bytes=max_bytes),
        "counters": counters,
        "current_causal_frontier_count": frontier_count,
        "unresolved_row_ids": unresolved,
    }


def _write_closure_sidecar(
    convergence_path: Path,
    root: Path,
    canonical_ledger: Path,
    canonical_ledger_doc: Mapping[str, Any],
    checked: list[str],
    *,
    max_bytes: int,
) -> str:
    sidecar = _closure_sidecar_payload(
        convergence_path,
        root,
        canonical_ledger,
        canonical_ledger_doc,
        max_bytes=max_bytes,
    )
    return write_json(convergence_path.with_name(convergence_path.name + ".closure.json"), sidecar, checked, max_bytes=max_bytes)


def _validate_terminal_closure_sidecar(
    convergence_path: Path,
    root: Path,
    checked: list[str],
    *,
    max_bytes: int,
) -> str:
    canonical_ledger = (root / RESEARCH_REL / "static/ledger.json").resolve()
    if not canonical_ledger.is_file():
        raise G005Error("canonical ledger is missing for closure validation")
    ledger_doc = read_json(canonical_ledger, checked, max_bytes=max_bytes)
    if not isinstance(ledger_doc, Mapping):
        raise G005Error("canonical ledger must be a JSON object")
    sidecar_path = convergence_path.with_name(convergence_path.name + ".closure.json")
    sidecar = read_json(sidecar_path, checked, max_bytes=max_bytes)
    if not isinstance(sidecar, Mapping):
        raise G005Error("convergence closure sidecar must be a JSON object")
    expected = _closure_sidecar_payload(
        convergence_path,
        root,
        canonical_ledger,
        ledger_doc,
        max_bytes=max_bytes,
    )
    if sidecar != expected:
        raise G005Error("convergence closure sidecar is not derived from the canonical ledger")
    counters = expected["counters"]
    unresolved = expected["unresolved_row_ids"]
    if any(value != 0 for value in counters.values()) or any(unresolved.values()):
        raise G005Error(f"canonical ledger is not terminal for G005: {counters}")
    return str(sidecar_path)

def cmd_build(args: argparse.Namespace) -> dict[str, Any]:
    checked: list[str] = []
    root = resolve_path(args.root, root=None, must_exist=True, allow_dir=True)
    canonical_ledger = resolve_path(args.canonical_ledger, root=root, must_exist=True)
    out_path = resolve_path(args.out or str(CONVERGENCE_REL), root=root, must_exist=False)
    proof_paths = [resolve_path(value, root=root, must_exist=True) for value in args.session_proof]
    proofs = [_load_proof(path, checked, max_bytes=args.max_filesize) for path in proof_paths]
    metas = [_load_meta(path, root, checked, max_bytes=args.max_filesize) for path in proof_paths]
    if len(proofs) < 4:
        raise G005Error("at least four proofs are required in E2,E3,E2,E2 order")

    runs = [_load_run_for_meta(path, proof, meta, root, checked, max_bytes=args.max_filesize) for path, proof, meta in zip(proof_paths, proofs, metas)]
    tiers = [str(meta.get("evidence_tier") or "").upper() for meta in metas]
    if tiers[:2] != ["E2", "E3"] or tiers[-2:] != ["E2", "E2"]:
        raise G005Error("build requires proofs in E2,E3,E2,E2 order with final two E2 proofs")

    artifact = str(args.artifact_set_id or proofs[0].get("artifact_set_id") or "")
    if not artifact:
        raise G005Error("artifact_set_id is required from proof or --artifact-set-id")
    seen_runs: set[str] = set()
    seen_paths: set[str] = set()
    intervals = [_interval(meta) for meta in metas]
    for index, (proof, meta, run, tier) in enumerate(zip(proofs, metas, runs, tiers)):
        _reject_fake_live("session proof", proof)
        _reject_unapproved_temperature_claims("session proof", proof, root=root)
        if tier == "E1" or tier not in {"E2", "E3"}:
            raise G005Error("session proof metadata must declare E2 or E3")
        if proof.get("artifact_set_id") != artifact:
            raise G005Error("session proof artifact_set_id mismatch")
        if meta.get("artifact_set_id") not in (None, "", artifact):
            raise G005Error("session proof metadata artifact_set_id mismatch")
        if tier == "E2" and proof.get("source_variant") != "untouched":
            raise G005Error("E2 proof must be untouched")
        if tier == "E3" and proof.get("source_variant") == "untouched":
            raise G005Error("E3 proof must be instrumented")
        if tier == "E2":
            _require_untouched_session(run, [])
        run_id = str(proof["run_id"])
        run_path = str(meta["run_manifest"])
        if run_id in seen_runs or run_path in seen_paths:
            raise G005Error("session proofs reuse a run ID or run manifest path")
        seen_runs.add(run_id)
        seen_paths.add(run_path)
        delta = run.get("instrumentation_delta")
        if tier == "E3":
            paired_id = meta.get("paired_untouched_run_id")
            paired_path = meta.get("paired_untouched_run_path") or meta.get("paired_untouched_run")
            if paired_id != proofs[index - 1].get("run_id") or paired_path != metas[index - 1].get("run_manifest"):
                raise G005Error("instrumented E3 paired run reference does not exactly match immediately prior E2 proof")
            _require_pair_compatibility(runs[index - 1], run)
            if not isinstance(delta, Mapping) or delta.get("paired_untouched_run_id") != paired_id:
                raise G005Error("instrumented E3 run instrumentation_delta.paired_untouched_run_id mismatch")
            if intervals[index - 1][1] > intervals[index][0]:
                raise G005Error("paired untouched E2 run is not temporally prior to instrumented E3")

    for prior, current in zip(metas, metas[1:]):
        if _ledger_ref_hash(prior, "ledger_after") != _ledger_ref_hash(current, "ledger_before"):
            raise G005Error("successive session proofs do not form a ledger hash chain")
    for prior, current in zip(intervals, intervals[1:]):
        if current[0] < prior[1]:
            raise G005Error("session proof intervals overlap")

    all_bundle_ids: set[str] = set()
    for proof in proofs:
        bundle_ids = _proof_bundle_ids(proof)
        if all_bundle_ids & bundle_ids:
            raise G005Error("session proofs reuse evidence bundles")
        all_bundle_ids.update(bundle_ids)

    canonical_ledger_doc = read_json(canonical_ledger, checked, max_bytes=args.max_filesize)
    if not isinstance(canonical_ledger_doc, Mapping):
        raise G005Error("canonical ledger must be a JSON object")
    canonical_hash = file_hash(canonical_ledger, max_bytes=args.max_filesize)
    if _ledger_ref_hash(metas[-1], "ledger_after") != canonical_hash:
        raise G005Error("final session ledger raw hash does not match canonical ledger")
    for index, (proof, meta) in enumerate(zip(proofs[-2:], metas[-2:]), start=len(proofs) - 2):
        if proof.get("source_variant") != "untouched" or str(meta.get("evidence_tier")).upper() != "E2" or int(meta.get("new_rows", -1)) != 0:
            raise G005Error(f"final session {index} is not untouched E2 with zero new rows")
    divergence = sum(len(proof.get("unexplained_baseline_divergence_ids") or []) for proof in proofs)
    if divergence != 0:
        raise G005Error("unexplained baseline divergence is nonzero")

    sessions = []
    for proof, meta in zip(proofs, metas):
        sessions.append(
            {
                "run_id": str(proof["run_id"]),
                "source_variant": str(proof["source_variant"]),
                "new_rows": int(meta["new_rows"]),
                "run_manifest": str(meta["run_manifest"]),
                "evidence_bundle_ids": sorted(_proof_bundle_ids(proof)),
                "session_proof": {"bundle_id": _proof_bundle_id(proof), "path": str(meta["proof_path"])},
            }
        )
    payload = {
        "schema_version": 1,
        "artifact_set_id": artifact,
        "sessions": sessions,
        "instrumented_observations_labeled": True,
        "unexplained_baseline_divergences": 0,
    }
    digest = write_json(out_path, payload, checked, max_bytes=args.max_filesize)
    closure_digest = _write_closure_sidecar(out_path, root, canonical_ledger, canonical_ledger_doc, checked, max_bytes=args.max_filesize)
    return {
        "ok": True,
        "status": "convergence_draft_built",
        "checked_files": checked,
        "output": str(out_path),
        "sha256": digest,
        "closure_sidecar": str(out_path.with_name(out_path.name + ".closure.json")),
        "closure_sha256": closure_digest,
        "errors": [],
    }


def cmd_validate(args: argparse.Namespace) -> dict[str, Any]:
    checked: list[str] = []
    root = resolve_path(args.root, root=None, must_exist=True, allow_dir=True)
    convergence = resolve_path(args.convergence, root=root, must_exist=True)
    canonical = (root / CONVERGENCE_REL).resolve(strict=False)
    if convergence != canonical:
        return {"ok": False, "status": "rejected", "checked_files": [str(convergence)], "errors": [_error("convergence", "validate requires canonical dynamic exploration convergence path", path=str(convergence))]}
    try:
        read_json(convergence, checked, max_bytes=args.max_filesize)
        evidence = critic.validate_dynamic_convergence(root)
        closure_sidecar = _validate_terminal_closure_sidecar(
            convergence,
            root,
            checked,
            max_bytes=args.max_filesize,
        )
        return {
            "ok": True,
            "status": "accepted",
            "checked_files": checked,
            "evidence": [*evidence, f"terminal_closure={closure_sidecar}"],
            "errors": [],
        }
    except Exception as exc:
        return {"ok": False, "status": "rejected", "checked_files": checked or [str(convergence)], "errors": [_error("critic.validate_dynamic_convergence", str(exc), path=str(root))]}


def _add_max_filesize(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-filesize", type=g004.parse_filesize, default=MAX_BYTES)


def build_parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(prog="g005_dynamic_coverage", description="G005 dynamic coverage artifact CLI")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=JsonArgumentParser)

    p = sub.add_parser("probe")
    p.add_argument("--output", required=True)
    _add_max_filesize(p)

    p = sub.add_parser("prepare-session")
    p.add_argument("--root", required=True)
    p.add_argument("--official-identity", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--out", required=True)
    _add_max_filesize(p)

    p = sub.add_parser("record-session")
    p.add_argument("--root", required=True)
    p.add_argument("--session-id", required=True, type=g004.parse_session_id)
    p.add_argument("--run", required=True)
    p.add_argument("--bundle-index", required=True)
    p.add_argument("--ledger-before", required=True)
    p.add_argument("--ledger-after", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--artifact-set-id")
    p.add_argument("--paired-untouched-run")
    _add_max_filesize(p)

    p = sub.add_parser("build-convergence")
    p.add_argument("--root", required=True)
    p.add_argument("--session-proof", required=True, action="append")
    p.add_argument("--canonical-ledger", required=True)
    p.add_argument("--out")
    p.add_argument("--artifact-set-id")
    _add_max_filesize(p)

    p = sub.add_parser("validate")
    p.add_argument("--root", required=True)
    p.add_argument("--convergence", required=True)
    _add_max_filesize(p)
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    parser = build_parser()
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            args = parser.parse_args(argv)
        handlers = {
            "probe": cmd_probe,
            "prepare-session": cmd_prepare,
            "record-session": cmd_record,
            "build-convergence": cmd_build,
            "validate": cmd_validate,
        }
        return handlers[args.command](args)
    except G005Error as exc:
        return {"ok": False, "status": "rejected", "checked_files": [], "errors": [_error("input", str(exc))]}
    except (KeyError, OSError, TypeError, ValueError) as exc:
        return {
            "ok": False,
            "status": "rejected",
            "checked_files": [],
            "errors": [_error("input", f"malformed input: {type(exc).__name__}")],
        }


def main(argv: Sequence[str] | None = None) -> int:
    result = run(argv)
    encoded = canonical_json_bytes(result)
    if len(encoded) > MAX_BYTES:
        result = {"ok": False, "status": "rejected", "checked_files": [], "errors": [_error("output", "result exceeds max size")]}
        encoded = canonical_json_bytes(result)
    sys.stdout.buffer.write(encoded)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
