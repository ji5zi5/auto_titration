#!/usr/bin/env python3
"""Fail-closed Mini2 official-vs-ours trace parity harness.

The harness compares evidence snapshots, not thermal success.  Static fixtures can
only demonstrate route compatibility; live parity requires both sides to be
live-device traces with explicit provenance/observation proof.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

VALID_SCOPES = {"static", "fixture", "app_captured", "live_device"}
STATIC_SCOPES = {"static", "fixture"}
ORDER_FIELD = "official_order"
NAME_FIELD = "name"
DEFAULT_STABLE_FIELDS = (
    "stage",
    "command_id",
    "stream_type",
    "vendor_id",
    "product_id",
    "module_type",
    "permission",
    "android_permission",
    "timeout_ms",
    "width",
    "height",
    "fps",
    "video_coding_type",
    "streaming_new",
    "retry_limit",
    "sleep_ms",
    "enable",
    "get_command_id",
    "set_command_id",
    "interval_ms",
    "accepted_packet_gate",
    "decoder_status",
)


@dataclass(frozen=True)
class NormalizedTrace:
    trace_id: str
    evidence_scope: str
    provenance: dict[str, Any]
    metadata: dict[str, Any]
    steps: list[dict[str, Any]]
    raw: dict[str, Any]


class TraceInputError(ValueError):
    """Raised when a trace input cannot be normalized safely."""


def _load_json_or_jsonl(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if not stripped:
        raise TraceInputError(f"empty trace file: {path}")
    if stripped.startswith("{"):
        try:
            loaded = json.loads(text)
        except json.JSONDecodeError:
            loaded = None
        if loaded is not None:
            if not isinstance(loaded, dict):
                raise TraceInputError(f"JSON trace must be an object: {path}")
            return loaded
    events: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    trace_id = path.stem
    evidence_scope: str | None = None
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceInputError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc
        if not isinstance(event, dict):
            raise TraceInputError(f"JSONL events must be objects at {path}:{line_no}")
        kind = event.get("event") or event.get("type")
        if kind in {"metadata", "trace_metadata"}:
            metadata.update({k: v for k, v in event.items() if k not in {"event", "type"}})
            trace_id = str(event.get("trace_id") or trace_id)
            evidence_scope = str(event.get("evidence_scope") or evidence_scope or "") or None
            if isinstance(event.get("provenance"), dict):
                provenance.update(event["provenance"])
            continue
        if kind in {"provenance", "live_provenance"}:
            provenance.update({k: v for k, v in event.items() if k not in {"event", "type"}})
            if isinstance(event.get("provenance"), dict):
                provenance.update(event["provenance"])
            continue
        events.append(event)
        evidence_scope = str(event.get("evidence_scope") or evidence_scope or "") or None
    return {
        "trace_id": trace_id,
        "evidence_scope": evidence_scope or metadata.get("evidence_scope") or "fixture",
        "metadata": metadata,
        "provenance": provenance,
        "steps": events,
    }


def _coerce_step(event: dict[str, Any], index: int) -> dict[str, Any]:
    step = dict(event)
    if "fields" in step and isinstance(step["fields"], dict):
        fields = step.pop("fields")
        for key, value in fields.items():
            step.setdefault(key, value)
    if NAME_FIELD not in step:
        step[NAME_FIELD] = step.get("step") or step.get("event") or step.get("stage")
    if step[NAME_FIELD] is None:
        raise TraceInputError(f"step at index {index} has no name/event/stage")
    if ORDER_FIELD not in step:
        for alias in ("order", "seq", "sequence"):
            if alias in step:
                step[ORDER_FIELD] = step[alias]
                break
    if ORDER_FIELD not in step:
        step[ORDER_FIELD] = index + 1
    try:
        step[ORDER_FIELD] = int(step[ORDER_FIELD])
    except (TypeError, ValueError) as exc:
        raise TraceInputError(f"step {step[NAME_FIELD]!r} has non-integer {ORDER_FIELD}") from exc
    step[NAME_FIELD] = str(step[NAME_FIELD])
    return step


def normalize_trace(data_or_path: dict[str, Any] | str | Path) -> NormalizedTrace:
    raw = _load_json_or_jsonl(Path(data_or_path)) if isinstance(data_or_path, (str, Path)) else dict(data_or_path)
    evidence_scope = str(raw.get("evidence_scope") or "").strip()
    if evidence_scope not in VALID_SCOPES:
        raise TraceInputError(f"evidence_scope must be one of {sorted(VALID_SCOPES)}, got {evidence_scope!r}")
    steps_raw = raw.get("steps") or raw.get("events") or raw.get("trace")
    if not isinstance(steps_raw, list) or not steps_raw:
        raise TraceInputError("trace must contain a non-empty steps/events/trace list")
    steps = [_coerce_step(step, i) for i, step in enumerate(steps_raw) if isinstance(step, dict)]
    if len(steps) != len(steps_raw):
        raise TraceInputError("all steps must be objects")
    steps.sort(key=lambda s: (s[ORDER_FIELD], s[NAME_FIELD]))
    return NormalizedTrace(
        trace_id=str(raw.get("trace_id") or raw.get("id") or "unnamed"),
        evidence_scope=evidence_scope,
        provenance=dict(raw.get("provenance") or {}),
        metadata=dict(raw.get("metadata") or {}),
        steps=steps,
        raw=raw,
    )


def _step_key(step: dict[str, Any]) -> tuple[int, str]:
    return int(step[ORDER_FIELD]), str(step[NAME_FIELD])


def _field_value(step: dict[str, Any], field: str) -> Any:
    return step.get(field)


def compare_traces(
    official: NormalizedTrace | dict[str, Any] | str | Path,
    ours: NormalizedTrace | dict[str, Any] | str | Path,
    stable_fields: Iterable[str] = DEFAULT_STABLE_FIELDS,
) -> dict[str, Any]:
    official_trace = official if isinstance(official, NormalizedTrace) else normalize_trace(official)
    ours_trace = ours if isinstance(ours, NormalizedTrace) else normalize_trace(ours)
    stable_fields = tuple(stable_fields)

    official_keys = [_step_key(step) for step in official_trace.steps]
    ours_keys = [_step_key(step) for step in ours_trace.steps]
    official_map = {_step_key(step): step for step in official_trace.steps}
    ours_map = {_step_key(step): step for step in ours_trace.steps}

    mismatched_fields: list[dict[str, Any]] = []
    missing_steps = [list(key) for key in official_keys if key not in ours_map]
    extra_steps = [list(key) for key in ours_keys if key not in official_map]
    order_mismatch = official_keys != ours_keys
    if order_mismatch:
        mismatched_fields.append(
            {
                "kind": "step_order",
                "field": "ordered_steps",
                "official": [list(key) for key in official_keys],
                "ours": [list(key) for key in ours_keys],
            }
        )

    for key in official_keys:
        if key not in ours_map:
            continue
        official_step = official_map[key]
        ours_step = ours_map[key]
        for field in stable_fields:
            official_has = field in official_step
            ours_has = field in ours_step
            if not official_has and not ours_has:
                continue
            official_value = _field_value(official_step, field)
            ours_value = _field_value(ours_step, field)
            if official_value != ours_value:
                mismatched_fields.append(
                    {
                        "kind": "field",
                        "step": {"official_order": key[0], "name": key[1]},
                        "field": field,
                        "official": official_value,
                        "ours": ours_value,
                    }
                )

    comparison_result = "match" if not mismatched_fields and not missing_steps and not extra_steps else "mismatch"
    scope_result, scope_errors = evaluate_scope(official_trace, ours_trace, comparison_result)
    unsupported_hardware_success = explicit_supported_hardware_success(official_trace, ours_trace)
    verdict = scope_result if comparison_result == "match" and not scope_errors else "fail_closed"

    return {
        "schema_version": 1,
        "comparison_result": comparison_result,
        "scope_result": scope_result,
        "verdict": verdict,
        "official_trace_id": official_trace.trace_id,
        "ours_trace_id": ours_trace.trace_id,
        "official_scope": official_trace.evidence_scope,
        "ours_scope": ours_trace.evidence_scope,
        "compared_steps": len(official_keys),
        "stable_fields": list(stable_fields),
        "mismatched_fields": mismatched_fields,
        "missing_steps": missing_steps,
        "extra_steps": extra_steps,
        "scope_errors": scope_errors,
        "live_parity": verdict == "live_parity",
        "unsupported_hardware_success": unsupported_hardware_success,
        "celsius_promotion_allowed": unsupported_hardware_success,
    }


def has_live_provenance_proof(trace: NormalizedTrace) -> bool:
    if trace.evidence_scope != "live_device":
        return False
    provenance = trace.provenance
    if provenance.get("live_device_observation") is not True:
        return False
    proof = provenance.get("live_observation_proof")
    if not isinstance(proof, dict):
        return False
    required_truthy = ("observation_id", "captured_at", "device_vid_pid")
    return all(bool(proof.get(key)) for key in required_truthy)


def explicit_supported_hardware_success(*traces: NormalizedTrace) -> bool:
    for trace in traces:
        proof = trace.provenance.get("supported_hardware_live_proof")
        if trace.evidence_scope != "live_device" or not has_live_provenance_proof(trace):
            return False
        if not isinstance(proof, dict) or proof.get("supported_hardware_success") is not True:
            return False
        if proof.get("celsius_full_matrix_observed") is not True:
            return False
        if not proof.get("same_scene_official_comparison_id"):
            return False
    return True


def _has_source_reference(trace: NormalizedTrace) -> bool:
    sources = trace.metadata.get("sources") or trace.metadata.get("source") or trace.provenance.get("sources")
    if isinstance(sources, str):
        return bool(sources.strip())
    if isinstance(sources, list):
        return any(bool(str(source).strip()) for source in sources)
    artifact = trace.metadata.get("artifact") or trace.metadata.get("artifact_path") or trace.provenance.get("artifact")
    return bool(str(artifact).strip()) if artifact is not None else False


def has_static_fixture_provenance(trace: NormalizedTrace) -> bool:
    if trace.evidence_scope not in STATIC_SCOPES:
        return False
    marker_keys = ("fixture_only", "static_evidence", "static_fixture", "fixture_evidence")
    has_marker = any(trace.provenance.get(key) is True for key in marker_keys)
    return has_marker and _has_source_reference(trace)


def has_app_captured_provenance(trace: NormalizedTrace) -> bool:
    if trace.evidence_scope != "app_captured":
        return False
    marker = (
        trace.provenance.get("app_captured_snapshot") is True
        or trace.provenance.get("app_captured") is True
        or trace.metadata.get("capture_kind") == "app_captured_static_snapshot"
    )
    capture_id = (
        trace.provenance.get("capture_id")
        or trace.provenance.get("app_capture_id")
        or trace.metadata.get("capture_id")
        or trace.metadata.get("app_capture_id")
        or trace.metadata.get("artifact")
        or trace.metadata.get("artifact_path")
    )
    return bool(marker) and capture_id is not None and bool(str(capture_id).strip())


def evaluate_scope(official: NormalizedTrace, ours: NormalizedTrace, comparison_result: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    scopes = {official.evidence_scope, ours.evidence_scope}
    if official.evidence_scope != ours.evidence_scope:
        errors.append("scope_mismatch")
        return "fail_closed", errors
    if official.evidence_scope in STATIC_SCOPES:
        if not has_static_fixture_provenance(official):
            errors.append("official_missing_static_fixture_provenance")
        if not has_static_fixture_provenance(ours):
            errors.append("ours_missing_static_fixture_provenance")
        return ("fail_closed" if errors else "static_fixture_only"), errors
    if official.evidence_scope == "app_captured":
        if not has_app_captured_provenance(official):
            errors.append("official_missing_app_capture_provenance")
        if not has_app_captured_provenance(ours):
            errors.append("ours_missing_app_capture_provenance")
        return ("fail_closed" if errors else "compatible"), errors
    if official.evidence_scope == "live_device":
        official_proved = has_live_provenance_proof(official)
        ours_proved = has_live_provenance_proof(ours)
        if not official_proved:
            errors.append("official_missing_live_provenance")
        if not ours_proved:
            errors.append("ours_missing_live_provenance")
        if errors:
            return "fail_closed", errors
        return ("live_parity" if comparison_result == "match" else "fail_closed"), errors
    errors.append(f"unsupported_scope:{','.join(sorted(scopes))}")
    return "fail_closed", errors


def deterministic_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Mini2 official-vs-ours trace snapshots fail-closed.")
    parser.add_argument("--official", required=True, type=Path, help="official JSON snapshot or JSONL events")
    parser.add_argument("--ours", required=True, type=Path, help="ours JSON snapshot or JSONL events")
    parser.add_argument("--pretty", action="store_true", help="print indented JSON instead of compact deterministic JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = compare_traces(args.official, args.ours)
    except (OSError, json.JSONDecodeError, TraceInputError) as exc:
        result = {
            "schema_version": 1,
            "comparison_result": "input_error",
            "scope_result": "fail_closed",
            "verdict": "fail_closed",
            "mismatched_fields": [],
            "scope_errors": [str(exc)],
            "live_parity": False,
            "unsupported_hardware_success": False,
            "celsius_promotion_allowed": False,
        }
        print(deterministic_json(result))
        return 2
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(deterministic_json(result))
    return 0 if result["comparison_result"] == "match" and result["verdict"] != "fail_closed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
