import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import unicodedata
from collections import Counter
from pathlib import Path
from unittest import mock

from tools.hik_whole_apk import critic


ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / ".omx/research/hikmicro-viewer-2.6.0"
GOVERNANCE = RESEARCH / "governance"
MISSION = ROOT / ".omx/goals/autoresearch/official-hikmicro-viewer-2-6-0-whole-apk-behavio"
FULL_MISSION_SLUG = (
    "official-hikmicro-viewer-2-6-0-whole-apk-behavioral-reconstruction-"
    "and-f2-first-frame-causal-frontier"
)
ARTIFACT_SET_ID = "test-artifact-set"


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def hash_row(root, path):
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size_bytes": path.stat().st_size,
    }


def refresh_claim_index(root):
    claims_root = root / critic.RESEARCH_REL / "claims"
    rows = []
    for path in sorted(claims_root.glob("CLM-*.json"), key=lambda item: item.name):
        rows.append(
            {
                "claim_id": path.stem,
                "path": str(path.relative_to(root)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
        )
    write_json(
        claims_root / "index.json",
        {"schema_version": 1, "artifact_set_id": ARTIFACT_SET_ID, "claims": rows},
    )


def write_claim_record(root, claim_id, bundle_id, tier):
    path = root / critic.RESEARCH_REL / "claims" / f"{claim_id}.json"
    if path.is_file():
        claim = json.loads(path.read_text(encoding="utf-8"))
    else:
        claim = {
            "schema_version": 1,
            "claim_id": claim_id,
            "artifact_set_id": ARTIFACT_SET_ID,
            "statement": f"Synthetic test claim {claim_id}",
            "disposition": "observation",
            "evidence_tier": tier,
            "evidence_bundle_ids": [],
            "replay_commands": ["python3 replay.py"],
            "limitations": ["synthetic unit-test fixture only"],
            "contradicts_claim_ids": [],
            "supersedes_claim_ids": [],
            "independent_review_ids": [],
        }
    if bundle_id not in claim["evidence_bundle_ids"]:
        claim["evidence_bundle_ids"].append(bundle_id)
        claim["evidence_bundle_ids"].sort()
    if critic.EVIDENCE_TIERS.index(tier) > critic.EVIDENCE_TIERS.index(claim["evidence_tier"]):
        claim["evidence_tier"] = tier
    if claim["evidence_tier"] == "E5":
        claim["disposition"] = "verified_conclusion"
        claim["independent_review_ids"] = [f"REV-CLAIM-{claim_id.removeprefix('CLM-')}"]
    write_json(path, claim)
    refresh_claim_index(root)
    if claim["evidence_tier"] == "E5":
        review_id = claim["independent_review_ids"][0]
        write_json(
            root / critic.RESEARCH_REL / "reviews" / f"{review_id.lower()}.json",
            {
                "schema_version": 1,
                "review_id": review_id,
                "reviewer_id": f"claim-reviewer-{claim_id.lower()}",
                "reviewer_role": "claim-verifier",
                "independent_from_producers": True,
                "verdict": "pass",
                "passed": True,
                "subject_ids": [claim_id],
                "evidence_bundle_ids": list(claim["evidence_bundle_ids"]),
                "reviewed_at": "2026-07-20T00:00:00Z",
            },
        )


def make_contract_root(base):
    root = Path(base)
    write_json(
        root / critic.RESEARCH_REL / "governance/official-artifacts.json",
        {"artifact_set_id": ARTIFACT_SET_ID, "artifacts": [{"artifact_id": "official-converter"}]},
    )
    write_json(
        root / critic.RESEARCH_REL / "governance/current-implementation-baseline.json",
        {"baseline_id": "BASELINE-TEST-1"},
    )
    return root


def make_governance_phase_root(base, *, g002_started):
    root = Path(base)
    research = root / critic.RESEARCH_REL
    shutil.copytree(GOVERNANCE, research / "governance")
    for directory in [
        "claims",
        "static",
        "dynamic",
        "dossiers",
        "specs",
        "reproduction",
        "reviews",
        "closure",
    ]:
        (research / directory).mkdir(parents=True, exist_ok=True)
    closure = {
        "schema_version": 1,
        "artifact_set_id": json.loads(
            (research / "governance/official-artifacts.json").read_text(encoding="utf-8")
        )["artifact_set_id"],
        "inventory_started": g002_started,
        "counts_are_complete": False,
        "closure_allowed": False,
        "computed_from_ledger": None,
        "current_causal_frontier_count": None,
        "counters": {key: None for key in critic.COUNTER_KEYS},
        "final_gates": {key: False for key in critic.FINAL_GATE_KEYS},
    }
    write_json(research / "closure/current.json", closure)

    manifest_path = research / "governance/governance-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["g002_inventory_started"] = g002_started
    write_json(manifest_path, manifest)
    (research / "claims").mkdir(parents=True, exist_ok=True)
    (research / "claims/README.md").write_text("# Claims\n", encoding="utf-8")
    (research / "static/README.md").write_text("# Static inventory\n", encoding="utf-8")

    if g002_started:
        artifact_set_id = json.loads(
            (research / "governance/official-artifacts.json").read_text(encoding="utf-8")
        )["artifact_set_id"]
        claim_path = research / "claims/CLM-G002-FIXTURE.json"
        write_json(
            claim_path,
            {
                "schema_version": 1,
                "claim_id": "CLM-G002-FIXTURE",
                "artifact_set_id": artifact_set_id,
                "statement": "Fixture-only G002 static inventory observation.",
                "disposition": "observation",
                "evidence_tier": "E1",
                "evidence_bundle_ids": ["EVB-G002-FIXTURE"],
                "replay_commands": ["python3 tools/hik_whole_apk/g002_fixture.py"],
                "limitations": ["phase fixture only"],
                "contradicts_claim_ids": [],
                "supersedes_claim_ids": [],
                "independent_review_ids": ["REV-G002-FIXTURE"],
            },
        )
        write_json(
            research / "claims/index.json",
            {
                "schema_version": 1,
                "artifact_set_id": artifact_set_id,
                "claims": [
                    {
                        "claim_id": "CLM-G002-FIXTURE",
                        "path": str(claim_path.relative_to(root)),
                        "sha256": sha256_bytes(claim_path.read_bytes()),
                        "size_bytes": claim_path.stat().st_size,
                    }
                ],
            },
        )
        write_json(research / "static/inventory-a.json", {})
        write_json(research / "static/inventory-b.json", {})
    return root


def write_evidence_bundle(
    root,
    bundle_id="EVB-STATIC-1",
    *,
    tier="E1",
    source_variant="untouched",
    operator="producer-1",
    claim_ids=("CLM-TEST-1",),
    live=False,
    experiment_id="EXP-TEST-1",
    captured_at="2026-07-18T00:00:00Z",
):
    category = "static" if tier == "E1" else ("reproduction" if source_variant == "reimplementation" else "dynamic")
    bundle_root = root / critic.RESEARCH_REL / category / "evidence" / bundle_id
    bundle_root.mkdir(parents=True, exist_ok=True)
    for claim_id in claim_ids:
        write_claim_record(root, claim_id, bundle_id, tier)
    events = []
    if tier != "E1":
        events.append(
            {
                "event_id": f"EVT-{bundle_id.removeprefix('EVB-')}-1",
                "event_type": "observed",
                "monotonic_ns": 1,
                "correlation_id": f"CORR-{bundle_id}",
                "process_id": 1,
                "thread_id": 1,
                "object_id": None,
                "reference_id": None,
                "buffer_pointer": None,
                "buffer_length": None,
                "endpoint": None,
                "transfer_id": None,
                "error_state": None,
                "claim_ids": list(claim_ids),
                "observation_id": "OBS-TEST-1",
                "checkpoint_id": None,
                "run_id": None,
                "value": {"observed": True},
            }
        )
    event_document = {
        "schema_version": 1,
        "schema_id": "hik-normalized-events-v1",
        "artifact_set_id": ARTIFACT_SET_ID,
        "experiment_id": experiment_id,
        "source_variant": source_variant,
        "events": events,
        "canonical_sha256": sha256_bytes(
            json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
    }
    event_payload = (json.dumps(event_document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    state_payload = b'{"state":"clean"}\n'
    (bundle_root / "events.json").write_bytes(event_payload)
    (bundle_root / "state.json").write_bytes(state_payload)
    attachments = [
        {
            "path": "events.json",
            "sha256": sha256_bytes(event_payload),
            "size_bytes": len(event_payload),
            "media_type": "application/json",
        },
        {
            "path": "state.json",
            "sha256": sha256_bytes(state_payload),
            "size_bytes": len(state_payload),
            "media_type": "application/json",
        },
    ]
    live_fields = live or tier in {"E2", "E3"}
    manifest = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "claim_ids": list(claim_ids),
        "experiment_id": experiment_id,
        "operator": operator,
        "captured_at": captured_at,
        "clock": {"basis": "monotonic", "offsets_and_drift_attachment": None},
        "artifact_set_id": ARTIFACT_SET_ID,
        "source_variant": source_variant,
        "evidence_tier": tier,
        "instrumentation_delta": {
            "summary": "none" if source_variant in {"untouched", "reimplementation"} else "test hook",
            "hooks": [] if source_variant in {"untouched", "reimplementation"} else ["hook-1"],
            "patches": [],
            "root_modules": [],
            "debugger": [],
            "proxies": [],
            "usb_capture_point": None,
        },
        "environment": {
            "device_fingerprint": "device-1" if live_fields else None,
            "camera_fingerprint": "camera-1" if live_fields else None,
            "os_build": "os-1" if live_fields else None,
            "abi": "arm64-v8a" if live_fields else None,
            "data_state_snapshot": "state.json",
        },
        "tool_versions": {"test-tool": "1.0"},
        "replay_commands": ["python3 replay.py"],
        "event_stream": {
            "schema_id": "hik-normalized-events-v1",
            "normalized_attachment": "events.json",
            "emitted_events": len(events),
            "captured_events": len(events),
            "dropped_events": 0,
            "truncated_events": 0,
        },
        "attachments": attachments,
    }
    manifest["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    write_json(bundle_root / "manifest.json", manifest)
    return bundle_root / "manifest.json"


def add_bundle_json_attachment(root, bundle_id, filename, document):
    manifest_path = critic.resolve_evidence_bundle(root, bundle_id)
    write_json(manifest_path.parent / filename, document)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = (manifest_path.parent / filename).read_bytes()
    manifest["attachments"].append(
        {
            "path": filename,
            "sha256": sha256_bytes(payload),
            "size_bytes": len(payload),
            "media_type": "application/json",
        }
    )
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    write_json(manifest_path, manifest)
    return manifest["attachments"][-1]


def refresh_bundle_attachment(root, bundle_id, filename):
    manifest_path = critic.resolve_evidence_bundle(root, bundle_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    attachment_path = manifest_path.parent / filename
    payload = attachment_path.read_bytes()
    attachment = next(item for item in manifest["attachments"] if item["path"] == filename)
    attachment["sha256"] = sha256_bytes(payload)
    attachment["size_bytes"] = len(payload)
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    write_json(manifest_path, manifest)
    return attachment


def refresh_static_source_index_reference(root, lane):
    lane = lane.upper()
    bundle_id = f"EVB-INVENTORY-{lane}"
    attachment = refresh_bundle_attachment(root, bundle_id, "source-index.json")
    run_path = root / critic.RESEARCH_REL / "static/runs" / f"RUN-INVENTORY-{lane}" / "manifest.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    run["source_index_attachments"][0]["sha256"] = attachment["sha256"]
    run["source_index_attachments"][0]["size_bytes"] = attachment["size_bytes"]
    write_json(run_path, run)


def replace_bundle_events(root, bundle_id, events):
    manifest_path = critic.resolve_evidence_bundle(root, bundle_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event_name = manifest["event_stream"]["normalized_attachment"]
    event_path = manifest_path.parent / event_name
    event_document = json.loads(event_path.read_text(encoding="utf-8"))
    event_document["events"] = events
    event_document["canonical_sha256"] = sha256_bytes(
        json.dumps(events, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    write_json(event_path, event_document)
    payload = event_path.read_bytes()
    attachment = next(item for item in manifest["attachments"] if item["path"] == event_name)
    attachment["sha256"] = sha256_bytes(payload)
    attachment["size_bytes"] = len(payload)
    manifest["event_stream"]["emitted_events"] = len(events)
    manifest["event_stream"]["captured_events"] = len(events)
    manifest["event_stream"]["dropped_events"] = 0
    manifest["event_stream"]["truncated_events"] = 0
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = sha256_bytes(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    write_json(manifest_path, manifest)
    return manifest


def write_review(root, review_id, bundle_ids, *, reviewer_id="reviewer-1", subject_ids=("ROW-TEST-1",)):
    path = root / critic.RESEARCH_REL / "reviews" / f"{review_id.lower()}.json"
    write_json(
        path,
        {
            "schema_version": 1,
            "review_id": review_id,
            "reviewer_id": reviewer_id,
            "reviewer_role": "verifier",
            "independent_from_producers": True,
            "verdict": "pass",
            "passed": True,
            "subject_ids": list(subject_ids),
            "evidence_bundle_ids": list(bundle_ids),
            "reviewed_at": "2026-07-18T00:10:00Z",
        },
    )
    return path


def write_run_manifest(
    root,
    run_id="RUN-TEST-1",
    experiment_id="EXP-TEST-1",
    started_at="2026-07-18T00:00:00Z",
    ended_at="2026-07-18T00:01:00Z",
):
    run_root = root / critic.RESEARCH_REL / "dynamic/runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    state_path = run_root / "state.json"
    state_path.write_text('{"state":"clean"}\n', encoding="utf-8")
    path = run_root / "manifest.json"
    write_json(
        path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "experiment_id": experiment_id,
            "operator": "producer-1",
            "status": "completed",
            "source_variant": "untouched",
            "artifact_set_id": ARTIFACT_SET_ID,
            "baseline_id": "BASELINE-TEST-1",
            "environment": {
                "device_fingerprint": "device-1",
                "camera_fingerprint": "camera-1",
                "os_build": "os-1",
                "abi": "arm64-v8a",
                "network_profile": "offline-test",
            },
            "data_state_snapshot": hash_row(root, state_path),
            "clock": {"basis": "monotonic", "synchronization_plan": "single-device clock"},
            "instrumentation_delta": {
                "hooks": [],
                "patches": [],
                "root_modules": [],
                "debugger": [],
                "proxies": [],
                "usb_capture_point": None,
                "expected_perturbation": "none",
                "paired_untouched_run_id": None,
            },
            "tool_versions": {"runner": "1.0"},
            "commands": ["python3 run.py"],
            "planned_observations": ["clean exploration"],
            "output_root": str(run_root.relative_to(root)),
            "paired_comparison": None,
            "safety": {
                "destructive_actions": [],
                "external_production_actions": [],
                "rollback": "restore snapshot",
            },
            "started_at": started_at,
            "ended_at": ended_at,
        },
    )
    return path


def write_static_inventory_fixture(root, lane, *, include_discovered):
    lane = lane.upper()
    official = json.loads((GOVERNANCE / "official-artifacts.json").read_text(encoding="utf-8"))
    official["artifact_set_id"] = ARTIFACT_SET_ID
    write_json(root / critic.RESEARCH_REL / "governance/official-artifacts.json", official)
    artifacts = sorted(official["artifacts"], key=lambda item: item["artifact_id"])
    artifact_record_ids = {
        artifact["artifact_id"]: critic._inventory_record_id(artifact["kind"], artifact["artifact_id"])
        for artifact in artifacts
    }
    records = [
        {
            "record_id": artifact_record_ids[artifact["artifact_id"]],
            "record_type": artifact["kind"],
            "scope_key": critic._canonical_json_text(artifact["artifact_id"]),
            "artifact_id": artifact["artifact_id"],
            "source_artifact_id": artifact["artifact_id"],
            "sha256": artifact["sha256"],
            "size_bytes": artifact["size_bytes"],
            "official_source": artifact["source"],
            "dossier_id": None,
            "classification_status": "classified",
            "parent_record_ids": [],
            "source_refs": [],
        }
        for artifact in artifacts
    ]
    if include_discovered:
        first_apk = next(item["artifact_id"] for item in artifacts if item["kind"] == "apk_member")
        first_dex = next(item["artifact_id"] for item in artifacts if item["kind"] == "dex")
        first_native = next(item["artifact_id"] for item in artifacts if item["kind"] == "native_library")
        dex_scopes = {"class", "method_family", "reflection_target", "dynamic_loader"}
        native_scopes = {"native_import", "native_export", "native_symbol", "jni_edge"}
        for record_type in sorted(critic.DISCOVERED_INVENTORY_RECORD_TYPES):
            source_artifact_id = (
                first_dex
                if record_type in dex_scopes
                else first_native
                if record_type in native_scopes
                else first_apk
            )
            records.append(
                {
                    "record_id": critic._inventory_record_id(record_type, ["fixture", record_type]),
                    "record_type": record_type,
                    "scope_key": critic._canonical_json_text(["fixture", record_type]),
                    "artifact_id": None,
                    "source_artifact_id": source_artifact_id,
                    "sha256": None,
                    "size_bytes": None,
                    "official_source": None,
                    "dossier_id": None,
                    "classification_status": "classified",
                    "parent_record_ids": [artifact_record_ids[source_artifact_id]],
                    "source_refs": [],
                }
            )
    records.sort(key=lambda item: item["record_id"])

    run_id = f"RUN-INVENTORY-{lane}"
    experiment_id = f"EXP-INVENTORY-{lane}"
    bundle_id = f"EVB-INVENTORY-{lane}"
    method_id = f"METHOD-{lane}"
    toolchain_family = f"TOOLCHAIN-{lane}"
    script_path = root / "tools/hik_whole_apk" / f"fixture_producer_{lane.lower()}.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        f"# independent fixture producer {lane}\nprint('producer-{lane.lower()}')\n",
        encoding="utf-8",
    )
    command = (
        f"python3 {script_path.relative_to(root)} official.xapk "
        f"--output method-{lane.lower()}-source-index.json"
    )
    write_evidence_bundle(
        root,
        bundle_id,
        tier="E1",
        source_variant="untouched",
        operator=f"producer-{lane.lower()}",
        experiment_id=experiment_id,
        captured_at="2026-07-18T00:00:30Z",
    )
    source_records = []
    for index, record in enumerate(records):
        locator = f"raw/records.json#/records/{index}"
        source_record = {
            "source_locator": locator,
            "record_type": record["record_type"],
            "scope_key": record["scope_key"],
            "artifact_id": record["artifact_id"],
            "source_artifact_id": record["source_artifact_id"],
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "official_source": record["official_source"],
        }
        source_records.append(source_record)
        record["source_refs"] = [
            {
                "bundle_id": bundle_id,
                "attachment_path": "source-index.json",
                "source_locator": source_record["source_locator"],
                "source_record_sha256": sha256_bytes(
                    critic._canonical_json_bytes(source_record)
                ),
            }
        ]
    raw_source_records = list(source_records)
    add_bundle_json_attachment(
        root,
        bundle_id,
        "raw/records.json",
        {
            "schema_version": 1,
            "schema_id": "g002-raw-source-rows-v1",
            "records": raw_source_records,
        },
    )
    source_records.sort(key=lambda item: item["source_locator"])
    source_index = {
        "schema_version": 1,
        "index_id": f"SOURCE-INDEX-{lane}",
        "artifact_set_id": ARTIFACT_SET_ID,
        "run_id": run_id,
        "method_id": method_id,
        "records": source_records,
        "canonical_sha256": sha256_bytes(
            critic._canonical_json_bytes(source_records)
        ),
    }
    attachment = add_bundle_json_attachment(root, bundle_id, "source-index.json", source_index)
    run_path = root / critic.RESEARCH_REL / "static/runs" / run_id / "manifest.json"
    write_json(
        run_path,
        {
            "schema_version": 1,
            "run_id": run_id,
            "experiment_id": experiment_id,
            "operator": f"producer-{lane.lower()}",
            "status": "completed",
            "artifact_set_id": ARTIFACT_SET_ID,
            "method_id": method_id,
            "toolchain_family": toolchain_family,
            "commands": [command],
            "command_exit_codes": [0],
            "tool_versions": {f"extractor-{lane.lower()}": "1.0"},
            "input_artifact_ids": sorted(item["artifact_id"] for item in artifacts),
            "evidence_bundle_ids": [bundle_id],
            "source_index_attachments": [
                {
                    "bundle_id": bundle_id,
                    "path": "source-index.json",
                    "sha256": attachment["sha256"],
                    "size_bytes": attachment["size_bytes"],
                }
            ],
            "started_at": "2026-07-18T00:00:00Z",
            "ended_at": "2026-07-18T00:01:00Z",
        },
    )
    inventory_id = f"INVENTORY-{lane}"
    review_id = f"REV-INVENTORY-{lane}"
    write_review(
        root,
        review_id,
        [bundle_id],
        reviewer_id=f"reviewer-{lane.lower()}",
        subject_ids=(inventory_id, "CLM-TEST-1"),
    )
    record_type_counts = Counter(record["record_type"] for record in records)
    discovered_counts = {
        record_type: record_type_counts.get(record_type, 0)
        for record_type in sorted(critic.DISCOVERED_INVENTORY_RECORD_TYPES)
    }
    canonical_records = [
        {key: value for key, value in record.items() if key != "source_refs"}
        for record in records
    ]
    canonical = critic._canonical_json_text(canonical_records)
    conservation = {}
    for scope_name in sorted(critic.G002_CONSERVATION_SCOPES):
        record_type = critic.G002_DIRECT_SCOPE_TYPES.get(scope_name) or critic.G002_VARIABLE_SCOPE_TYPES.get(scope_name)
        count = record_type_counts.get(record_type, 0) if record_type is not None else 0
        conservation[scope_name] = {
            "observed_count": count,
            "accounted_count": count,
            "normalized_record_count": count if record_type is not None else None,
            "unaccounted_count": 0,
            "source_ref": {
                "bundle_id": bundle_id,
                "source_locator": f"raw/coverage.json#/scopes/{scope_name}",
                "source_record_sha256": "0" * 64,
            },
        }
    inventory = {
        "schema_version": 1,
        "inventory_id": inventory_id,
        "artifact_set_id": ARTIFACT_SET_ID,
        "generated_at": "2026-07-18T00:02:00Z",
        "method": {
            "method_id": method_id,
            "toolchain_family": toolchain_family,
            "commands": [command],
            "tool_versions": {f"extractor-{lane.lower()}": "1.0"},
            "producer_script": hash_row(root, script_path),
        },
        "producer_run_id": run_id,
        "producer_run_manifest": str(run_path.relative_to(root)),
        "producer_evidence_bundle_ids": [bundle_id],
        "independent_review_id": review_id,
        "normalized_records": records,
        "coverage": {
            "record_count": len(records),
            "record_type_counts": dict(sorted(record_type_counts.items())),
            "discovered_record_type_counts": discovered_counts,
            "apk_members": record_type_counts.get("apk_member", 0),
            "dex_files": record_type_counts.get("dex", 0),
            "native_libraries": record_type_counts.get("native_library", 0),
            "unclassified": 0,
            "frozen_artifacts_accounted": len(artifacts),
            "all_artifacts_accounted": True,
            "scope_conservation": conservation,
        },
        "canonical_sha256": sha256_bytes(canonical.encode("utf-8")),
    }
    write_json(root / critic.RESEARCH_REL / "static" / f"inventory-{lane.lower()}.json", inventory)
    return inventory


def scope_conservation_fixture(*, jni_edges, reflection_targets=0, dynamic_loaders=0):
    record_type_counts = {
        record_type: critic.G002_FIXED_SCOPE_COUNTS[scope_name]
        for scope_name, record_type in critic.G002_DIRECT_SCOPE_TYPES.items()
    }
    record_type_counts.update(
        {
            "configuration": sum(
                critic.G002_FIXED_SCOPE_COUNTS[name]
                for name in (
                    "xapk_entries",
                    "apk_entries",
                    "arm32_native_libraries",
                    "resource_configurations",
                    "per_library_summaries",
                )
            ),
            "jni_edge": jni_edges,
            "reflection_target": reflection_targets,
            "dynamic_loader": dynamic_loaders,
        }
    )
    conservation = {}
    raw_scopes = {}
    for scope_name in sorted(critic.G002_CONSERVATION_SCOPES):
        if scope_name in critic.G002_FIXED_SCOPE_COUNTS:
            observed_count = critic.G002_FIXED_SCOPE_COUNTS[scope_name]
        else:
            observed_count = record_type_counts[critic.G002_VARIABLE_SCOPE_TYPES[scope_name]]
        direct_type = critic.G002_DIRECT_SCOPE_TYPES.get(scope_name) or critic.G002_VARIABLE_SCOPE_TYPES.get(
            scope_name
        )
        normalized_count = record_type_counts[direct_type] if direct_type is not None else None
        raw_summary = {
            "scope": scope_name,
            "observed_count": observed_count,
            "accounted_count": observed_count,
            "normalized_record_count": normalized_count,
            "unaccounted_count": 0,
        }
        raw_scopes[scope_name] = raw_summary
        conservation[scope_name] = {
            **{key: value for key, value in raw_summary.items() if key != "scope"},
            "source_ref": {
                "bundle_id": "EVB-COVERAGE",
                "source_locator": f"raw/coverage.json#/scopes/{scope_name}",
                "source_record_sha256": sha256_bytes(critic._canonical_json_bytes(raw_summary)),
            },
        }
    raw_documents = {"EVB-COVERAGE": {"raw/coverage.json": {"scopes": raw_scopes}}}
    return conservation, record_type_counts, raw_documents


def history_event(index, from_state, to_state, transition_kind, evidence_ids):
    return {
        "at": f"2026-07-18T00:00:{index:02d}Z",
        "from_state": from_state,
        "to_state": to_state,
        "reason": f"{transition_kind} {to_state}",
        "evidence_bundle_ids": list(evidence_ids),
        "transition_kind": transition_kind,
    }


def full_forward_history(bundle_ids=None):
    bundle_ids = bundle_ids or [
        "EVB-INVENTORY-1",
        "EVB-STATIC-1",
        "EVB-DYNAMIC-1",
        "EVB-SPEC-1",
        "EVB-REPRO-1",
        "EVB-VERIFY-1",
    ]
    states = list(critic.FORWARD_STATES)
    history = [history_event(0, None, "unseen", "initialize", [])]
    for index, (from_state, to_state, bundle_id) in enumerate(zip(states, states[1:], bundle_ids), start=1):
        history.append(history_event(index, from_state, to_state, "advance", [bundle_id]))
    return history


def ledger_row(
    *,
    row_id="ROW-TEST-1",
    dossier_id="D01",
    state="verified",
    history=None,
    reopen_reason=None,
    blocker=None,
    evidence_ids=None,
    verification_ids=None,
):
    history = copy.deepcopy(history if history is not None else full_forward_history())
    history_ids = [bundle_id for event in history for bundle_id in event["evidence_bundle_ids"]]
    evidence_ids = list(evidence_ids if evidence_ids is not None else history_ids)
    verification_ids = list(verification_ids if verification_ids is not None else ([history_ids[-1]] if history_ids else []))
    return {
        "row_id": row_id,
        "scope_type": "behavior",
        "scope_key": row_id.lower(),
        "dossier_id": dossier_id,
        "owner": "producer-1",
        "state": state,
        "classification_status": "classified",
        "claim_ids": ["CLM-TEST-1"],
        "evidence_bundle_ids": evidence_ids,
        "specification_ids": ["SPEC-TEST-1"],
        "reproduction_ids": ["REP-TEST-1"],
        "verification_ids": verification_ids,
        "independent_review_ids": ["REV-TEST-1"],
        "history": history,
        "reopen_reason": reopen_reason,
        "blocker": blocker,
    }


def ledger_document(rows, frontier=None):
    return {
        "schema_version": 1,
        "ledger_id": "LEDGER-TEST-1",
        "artifact_set_id": ARTIFACT_SET_ID,
        "current_causal_frontier": frontier,
        "rows": rows,
    }


def closure_payload(computed_from_ledger):
    return {
        "schema_version": 1,
        "artifact_set_id": ARTIFACT_SET_ID,
        "computed_from_ledger": computed_from_ledger,
        "inventory_started": True,
        "counts_are_complete": True,
        "counters": {key: 0 for key in critic.COUNTER_KEYS},
        "current_causal_frontier_count": 1,
        "final_gates": {key: True for key in critic.FINAL_GATE_KEYS},
        "closure_allowed": True,
        "status": "complete",
        "reason": "all evidence independently validated",
    }


def radiometric_payload():
    proof_claim_ids = {
        key: f"CLM-RAD-{index:02d}"
        for index, key in enumerate(sorted(critic.RADIOMETRIC_PROOF_KEYS), start=1)
    }
    return {
        "schema_version": 1,
        "validation_id": "RAD-TEST-1",
        "artifact_set_id": ARTIFACT_SET_ID,
        "proof_claim_ids": proof_claim_ids,
        "fixture": {
            "passed": True,
            "claim_id": proof_claim_ids["fixture_official_reimplementation_comparison"],
            "evidence_bundle_ids": ["EVB-NOPE-FIXTURE-OFFICIAL", "EVB-NOPE-FIXTURE-REIMPL"],
            "sample_count": 2,
            "mean_error_c": 0.0,
            "max_pixel_error_c": 0.0,
            "comparison_attachment": {"bundle_id": "EVB-NOPE-FIXTURE-REIMPL", "path": "comparison.json"},
        },
        "live": {
            "passed": True,
            "claim_id": proof_claim_ids["live_official_reimplementation_comparison"],
            "evidence_bundle_ids": ["EVB-NOPE-LIVE-OFFICIAL", "EVB-NOPE-LIVE-REIMPL"],
            "sample_count": 2,
            "mean_error_c": 0.0,
            "max_pixel_error_c": 0.0,
            "comparison_attachment": {"bundle_id": "EVB-NOPE-LIVE-REIMPL", "path": "comparison.json"},
        },
        "e5_conclusion_bundle_ids": ["EVB-NOPE-E5"],
        "conclusion_attachment": {"bundle_id": "EVB-NOPE-E5", "path": "conclusion.json"},
        "celsius_publication_allowed": True,
        "independent_review_id": "REV-NOPE-RAD",
    }


class HikWholeApkGovernanceTests(unittest.TestCase):
    def test_approved_research_skeleton_exists_without_g002_inventory_claims(self):
        for directory in [
            "governance",
            "claims",
            "static",
            "dynamic",
            "dossiers",
            "specs",
            "reproduction",
            "reviews",
            "closure",
        ]:
            with self.subTest(directory=directory):
                self.assertTrue((RESEARCH / directory).is_dir())

        governance = json.loads((GOVERNANCE / "governance-manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(governance["g002_inventory_started"])

        with tempfile.TemporaryDirectory(prefix="g001-skeleton-fixture-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=False)
            research = root / critic.RESEARCH_REL
            closure = json.loads((research / "closure/current.json").read_text(encoding="utf-8"))
            self.assertFalse(closure["inventory_started"])
            self.assertFalse(closure["counts_are_complete"])
            self.assertFalse(closure["closure_allowed"])
            self.assertTrue(all(value is None for value in closure["counters"].values()))
            self.assertTrue((research / "static/README.md").is_file())
            self.assertFalse((research / "static/inventory-a.json").exists())
            self.assertFalse((research / "static/inventory-b.json").exists())
            self.assertFalse((research / "dossiers/index.json").exists())

    def test_machine_contracts_encode_strict_ledger_run_and_closure_shapes(self):
        manifest = json.loads((GOVERNANCE / "governance-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {"claim", "closure_counters", "evidence_bundle", "ledger", "run_manifest"},
            set(manifest["schemas"]),
        )
        for name, relative in manifest["schemas"].items():
            with self.subTest(schema=name):
                schema = json.loads((ROOT / relative).read_text(encoding="utf-8"))
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                self.assertEqual("object", schema["type"])
                self.assertTrue(schema["required"])
        claim_schema = json.loads((GOVERNANCE / "schemas/claim.schema.json").read_text(encoding="utf-8"))
        evidence_schema = json.loads((GOVERNANCE / "schemas/evidence-bundle.schema.json").read_text(encoding="utf-8"))
        self.assertIn("claimIndex", claim_schema["$defs"])
        self.assertIn("normalizedEventDocument", evidence_schema["$defs"])

        ledger_schema = json.loads((GOVERNANCE / "schemas/ledger.schema.json").read_text(encoding="utf-8"))
        row = ledger_schema["$defs"]["row"]
        event = ledger_schema["$defs"]["history_event"]
        self.assertEqual(set(critic.LEDGER_STATES), set(row["properties"]["state"]["enum"]))
        self.assertIn("classification_status", row["required"])
        self.assertEqual(set(critic.TRANSITION_KINDS), set(event["properties"]["transition_kind"]["enum"]))
        self.assertIn("transition_kind", event["required"])
        self.assertEqual({None, *critic.LEDGER_STATES}, set(event["properties"]["from_state"]["enum"]))
        self.assertEqual(set(critic.LEDGER_STATES), set(event["properties"]["to_state"]["enum"]))

        closure_schema = json.loads((GOVERNANCE / "schemas/closure-counters.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(set(critic.COUNTER_KEYS), set(closure_schema["properties"]["counters"]["required"]))
        self.assertEqual(set(critic.FINAL_GATE_KEYS), set(closure_schema["$defs"]["gate_vector"]["required"]))
        completed = closure_schema["allOf"][0]["then"]["properties"]["computed_from_ledger"]
        self.assertEqual(".omx/research/hikmicro-viewer-2.6.0/static/ledger.json", completed["const"])

    def test_governance_contracts_pin_variants_tiers_clean_room_celsius_and_reviews(self):
        with tempfile.TemporaryDirectory(prefix="g001-governance-contracts-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=False)
            evidence = critic.validate_governance_contracts(root)
        self.assertIn("source_variants=5", evidence)
        self.assertIn("clean_room_boundary=frozen", evidence)
        self.assertIn("no_fake_celsius=fail_closed", evidence)
        self.assertIn("producer self-review", (GOVERNANCE / "review-contract.md").read_text(encoding="utf-8"))
        policy = (GOVERNANCE / "no-fake-celsius-policy.md").read_text(encoding="utf-8")
        self.assertIn("<= 0.1 °C", policy)
        self.assertIn("<= 0.5 °C", policy)
        self.assertIn("JSON `null`", policy)

    def test_governance_accepts_historical_g001_phase_without_claim_index(self):
        with tempfile.TemporaryDirectory(prefix="g001-phase-fixture-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=False)
            evidence = critic.validate_governance_contracts(root)
            self.assertIn("governance_phase=G001", evidence)

    def test_governance_accepts_g002_phase_with_claim_index_and_incomplete_closure(self):
        with tempfile.TemporaryDirectory(prefix="g002-phase-fixture-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=True)
            evidence = critic.validate_governance_contracts(root)
            self.assertIn("governance_phase=G002", evidence)

    def test_governance_rejects_mixed_g001_and_g002_phase_state(self):
        with tempfile.TemporaryDirectory(prefix="g002-mixed-phase-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=False)
            closure_path = root / critic.RESEARCH_REL / "closure/current.json"
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            closure["inventory_started"] = True
            write_json(closure_path, closure)
            with self.assertRaisesRegex(critic.ContractError, "mixed G001/G002 phase state"):
                critic.validate_governance_contracts(root)

    def test_rubric_markdown_is_the_actual_autoresearch_contract(self):
        mission = json.loads((MISSION / "mission.json").read_text(encoding="utf-8"))
        rubric_path = ROOT / mission["rubric_path"]
        self.assertEqual((MISSION / "rubric.md").resolve(), rubric_path.resolve())
        self.assertEqual(mission["rubric"].strip(), rubric_path.read_text(encoding="utf-8").strip())
        self.assertFalse((MISSION / "rubric.json").exists())
        disposition = (GOVERNANCE / "rubric-format-disposition.md").read_text(encoding="utf-8")
        self.assertIn("autoresearch-goal", disposition)
        self.assertIn("rubric.md", disposition)
        self.assertIn("rubric.json", disposition)
        evidence = critic.validate_mission_contract(ROOT, critic.resolve_mission(ROOT, FULL_MISSION_SLUG))
        self.assertIn("rubric_format=markdown_per_autoresearch_goal_contract", evidence)

    def test_official_identity_freeze_rehashes_xapk_splits_dex_and_all_native_libraries(self):
        evidence = critic.validate_official_artifact_freeze(ROOT)
        self.assertIn("verified_artifacts=121", evidence)
        self.assertIn("apk_members=19", evidence)
        self.assertIn("dex=4", evidence)
        self.assertIn("arm64_native_libraries=88", evidence)

        with tempfile.TemporaryDirectory(prefix="g001-official-duplicate-", dir="/tmp") as temporary:
            root = Path(temporary)
            manifest = json.loads((GOVERNANCE / "official-artifacts.json").read_text(encoding="utf-8"))
            manifest["artifacts"][2]["source"] = copy.deepcopy(manifest["artifacts"][1]["source"])
            write_json(root / critic.RESEARCH_REL / "governance/official-artifacts.json", manifest)
            with self.assertRaisesRegex(critic.ContractError, "duplicate/invalid official artifact source identity"):
                critic.validate_official_artifact_freeze(root)

    def test_frozen_implementation_reconstructs_all_446_files_in_tmp(self):
        manifest_path = GOVERNANCE / "current-implementation-baseline.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        snapshots = manifest["snapshot_artifacts"]
        patch_path = ROOT / snapshots["tracked_patch"]["path"]
        bundle_path = ROOT / snapshots["untracked_files_bundle"]["path"]
        bundle_bytes = bundle_path.read_bytes()
        self.assertEqual(b"\x00\x00\x00\x00", bundle_bytes[4:8])

        with tarfile.open(bundle_path, "r:gz") as archive:
            members = archive.getmembers()
            member_names = [member.name for member in members]
            self.assertEqual(sorted(member_names), member_names)
            self.assertEqual(len(member_names), len(set(member_names)))
            self.assertTrue(all(member.isfile() for member in members))
            self.assertTrue(all((member.uid, member.gid, member.mtime) == (0, 0, 0) for member in members))
            self.assertTrue(all((member.uname, member.gname, member.mode & 0o777) == ("", "", 0o644) for member in members))

        head = snapshots["reconstruction_base_git_head"]
        head_names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "-z", head],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        head_paths = {value.decode("utf-8") for value in head_names.split(b"\0") if value}
        expected_bundle = sorted(item["path"] for item in manifest["files"] if item["path"] not in head_paths)
        self.assertEqual(expected_bundle, member_names)
        self.assertEqual(27, len(member_names))
        self.assertTrue(
            {
                "website/live/thermal.bmp",
                "website/live/thermal.json",
                "website/live/visible.bmp",
            }.issubset(member_names)
        )

        with tempfile.TemporaryDirectory(prefix="g001-reconstruction-test-", dir="/tmp") as temporary:
            temporary_root = Path(temporary)
            reconstructed = temporary_root / "tree"
            reconstructed.mkdir()
            head_archive = temporary_root / "head.tar"
            subprocess.run(
                ["git", "archive", "--format=tar", f"--output={head_archive}", head],
                cwd=ROOT,
                check=True,
                capture_output=True,
            )
            with tarfile.open(head_archive, "r:") as archive:
                archive.extractall(reconstructed, filter="data")
            for check_only in (True, False):
                command = ["git", "apply"]
                if check_only:
                    command.append("--check")
                command.extend(["--binary", "--unsafe-paths", f"--directory={reconstructed}", str(patch_path)])
                subprocess.run(command, cwd=ROOT, check=True, capture_output=True)
            with tarfile.open(bundle_path, "r:gz") as archive:
                archive.extractall(reconstructed, filter="data")

            aggregate_lines = []
            for item in manifest["files"]:
                path = reconstructed / item["path"]
                self.assertTrue(path.is_file(), item["path"])
                payload_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertEqual(item["size_bytes"], path.stat().st_size, item["path"])
                self.assertEqual(item["sha256"], payload_hash, item["path"])
                aggregate_lines.append(f"{payload_hash}\t{path.stat().st_size}\t{item['path']}\n")
            aggregate = sha256_bytes("".join(aggregate_lines).encode("utf-8"))
            self.assertEqual(446, len(manifest["files"]))
            self.assertEqual("09289ad338a118df36601ad5ec4b2771e943c0b5c70679b8e9be96d998b6af01", aggregate)
            self.assertEqual(manifest["aggregate_sha256"], aggregate)

        evidence = critic.validate_implementation_baseline(ROOT, verify_current_files=False)
        self.assertIn("frozen_files=446", evidence)
        self.assertIn("reconstructable_from_git_head_patch_and_untracked_bundle=true", evidence)

    def test_full_command_slug_resolves_truncated_autoresearch_directory(self):
        expected = (MISSION / "mission.json").resolve()
        for query in [
            FULL_MISSION_SLUG,
            MISSION.name,
            MISSION.as_posix(),
            (MISSION / "mission.json").as_posix(),
        ]:
            with self.subTest(query=query):
                self.assertEqual(expected, critic.resolve_mission(ROOT, query).path.resolve())

    def test_ledger_forward_block_resume_and_reopen_transitions_are_executable(self):
        with tempfile.TemporaryDirectory(prefix="g001-ledger-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            valid = ledger_document([ledger_row()])
            rows = critic.validate_ledger_document(root, valid, require_verified=True, resolve_references=False)
            self.assertEqual(1, len(rows))

            skipped = copy.deepcopy(valid)
            skipped["rows"][0]["history"][2]["to_state"] = "dynamically_observed"
            with self.assertRaisesRegex(critic.ContractError, "skipped prerequisite|continue from"):
                critic.validate_ledger_document(root, skipped, require_verified=True, resolve_references=False)

            nonmonotonic = copy.deepcopy(valid)
            nonmonotonic["rows"][0]["history"][2]["at"] = "2026-07-17T00:00:00Z"
            with self.assertRaisesRegex(critic.ContractError, "timestamps are not monotonic"):
                critic.validate_ledger_document(root, nonmonotonic, require_verified=True, resolve_references=False)

            missing_kind = copy.deepcopy(valid)
            del missing_kind["rows"][0]["history"][1]["transition_kind"]
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_ledger_document(root, missing_kind, require_verified=True, resolve_references=False)

            discontinuous = copy.deepcopy(valid)
            discontinuous["rows"][0]["history"][2]["from_state"] = "unseen"
            with self.assertRaisesRegex(critic.ContractError, "does not continue"):
                critic.validate_ledger_document(root, discontinuous, require_verified=True, resolve_references=False)

            unexplained_reopen = copy.deepcopy(valid)
            unexplained_reopen["rows"][0]["reopen_reason"] = "named without a transition"
            with self.assertRaisesRegex(critic.ContractError, "without a reopen transition"):
                critic.validate_ledger_document(root, unexplained_reopen, require_verified=True, resolve_references=False)

            block_history = [
                history_event(0, None, "unseen", "initialize", []),
                history_event(1, "unseen", "inventoried", "advance", ["EVB-INVENTORY-1"]),
                history_event(2, "inventoried", "blocked", "block", ["EVB-BLOCK-1"]),
                history_event(3, "blocked", "inventoried", "resume", ["EVB-RESUME-1"]),
                history_event(4, "inventoried", "static_mapped", "advance", ["EVB-STATIC-1"]),
            ]
            resumed = ledger_row(state="static_mapped", history=block_history, evidence_ids=[], verification_ids=[])
            resumed["claim_ids"] = []
            resumed["specification_ids"] = []
            resumed["reproduction_ids"] = []
            resumed["independent_review_ids"] = []
            critic.validate_ledger_document(root, ledger_document([resumed]), require_verified=False, resolve_references=False)

            wrong_resume = copy.deepcopy(resumed)
            wrong_resume["history"][3]["to_state"] = "unseen"
            with self.assertRaisesRegex(critic.ContractError, "resume to the exact pre-block state"):
                critic.validate_ledger_document(root, ledger_document([wrong_resume]), require_verified=False, resolve_references=False)

            blocked_history = block_history[:3]
            blocked = ledger_row(
                state="blocked",
                history=blocked_history,
                evidence_ids=[],
                verification_ids=[],
                blocker={
                    "reason": "inventory evidence contradicted",
                    "attempted_evidence_ids": ["EVB-BLOCK-1"],
                    "next_experiment": "repeat independent extraction",
                },
            )
            blocked["claim_ids"] = []
            blocked["specification_ids"] = []
            blocked["reproduction_ids"] = []
            blocked["independent_review_ids"] = []
            critic.validate_ledger_document(root, ledger_document([blocked]), require_verified=False, resolve_references=False)

            mismatched_blocker = copy.deepcopy(blocked)
            mismatched_blocker["blocker"]["attempted_evidence_ids"] = ["EVB-DIFFERENT-1"]
            with self.assertRaisesRegex(critic.ContractError, "differs from its block transition"):
                critic.validate_ledger_document(root, ledger_document([mismatched_blocker]), require_verified=False, resolve_references=False)

            block_after_verified_history = full_forward_history()
            block_after_verified_history.append(history_event(7, "verified", "blocked", "block", ["EVB-BLOCK-VERIFIED"]))
            block_after_verified = ledger_row(
                state="blocked",
                history=block_after_verified_history,
                blocker={
                    "reason": "invalid direct block",
                    "attempted_evidence_ids": ["EVB-BLOCK-VERIFIED"],
                    "next_experiment": "reopen first",
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "invalid block transition"):
                critic.validate_ledger_document(root, ledger_document([block_after_verified]), require_verified=False, resolve_references=False)

            reopened_history = full_forward_history()
            reopened_history.append(history_event(7, "verified", "specified", "reopen", ["EVB-REOPEN-1"]))
            reopened_history[-1]["reason"] = "new evidence invalidated reproduction"
            reopened_history.append(history_event(8, "specified", "independently_reproduced", "advance", ["EVB-REPRO-2"]))
            reopened_history.append(history_event(9, "independently_reproduced", "verified", "advance", ["EVB-VERIFY-2"]))
            reopened = ledger_row(
                history=reopened_history,
                reopen_reason="new evidence invalidated reproduction",
                evidence_ids=[bundle for event in reopened_history for bundle in event["evidence_bundle_ids"]],
                verification_ids=["EVB-VERIFY-1", "EVB-VERIFY-2"],
            )
            critic.validate_ledger_document(root, ledger_document([reopened]), require_verified=True, resolve_references=False)

            missing_reopen_reason = copy.deepcopy(reopened)
            missing_reopen_reason["reopen_reason"] = None
            with self.assertRaisesRegex(critic.ContractError, "reopened without"):
                critic.validate_ledger_document(root, ledger_document([missing_reopen_reason]), require_verified=True, resolve_references=False)

            bad_reopen = copy.deepcopy(reopened)
            bad_reopen["history"][7]["to_state"] = "verified"
            with self.assertRaisesRegex(critic.ContractError, "reopen must move to an earlier"):
                critic.validate_ledger_document(root, ledger_document([bad_reopen]), require_verified=True, resolve_references=False)

    def test_ledger_rejects_minimal_verified_rows_nonexistent_evidence_and_e1_only_promotion(self):
        with tempfile.TemporaryDirectory(prefix="g001-ledger-hostile-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            minimal = ledger_document([{"row_id": "ROW-MINIMAL-1", "state": "verified"}])
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_ledger_document(root, minimal, require_verified=True, resolve_references=True)

            full_but_named = ledger_document([ledger_row()])
            with self.assertRaisesRegex(critic.ContractError, "evidence bundle not found"):
                critic.validate_ledger_document(root, full_but_named, require_verified=True, resolve_references=True)

            write_evidence_bundle(root, "EVB-E1-ONLY", tier="E1")
            e1_history = full_forward_history(["EVB-E1-ONLY"] * 6)
            e1_row = ledger_row(
                history=e1_history,
                evidence_ids=["EVB-E1-ONLY"],
                verification_ids=["EVB-E1-ONLY"],
            )
            with self.assertRaisesRegex(critic.ContractError, "transition to dynamically_observed lacks required evidence tier"):
                critic.validate_ledger_document(root, ledger_document([e1_row]), require_verified=True, resolve_references=True)

    def test_ledger_rejects_transition_evidence_captured_after_the_transition(self):
        with tempfile.TemporaryDirectory(prefix="g001-ledger-stale-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            bundle_specs = [
                ("EVB-INVENTORY-1", "E1", "untouched", False),
                ("EVB-STATIC-1", "E1", "untouched", False),
                ("EVB-DYNAMIC-1", "E2", "untouched", True),
                ("EVB-SPEC-1", "E4", "reimplementation", False),
                ("EVB-REPRO-1", "E4", "reimplementation", False),
                ("EVB-VERIFY-1", "E5", "reimplementation", False),
            ]
            for bundle_id, tier, source_variant, live in bundle_specs:
                write_evidence_bundle(
                    root,
                    bundle_id,
                    tier=tier,
                    source_variant=source_variant,
                    live=live,
                    captured_at="2026-07-19T00:00:00Z",
                )
            write_review(
                root,
                "REV-TEST-1",
                [bundle_id for bundle_id, *_ in bundle_specs],
                reviewer_id="reviewer-ledger",
                subject_ids=("ROW-TEST-1",),
            )
            with self.assertRaisesRegex(critic.ContractError, "captured after its transition"):
                critic.validate_ledger_document(
                    root,
                    ledger_document([ledger_row()]),
                    require_verified=True,
                    resolve_references=True,
                )

    def test_evidence_and_review_ids_require_hash_backing_and_real_independence(self):
        with tempfile.TemporaryDirectory(prefix="g001-evidence-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            with self.assertRaisesRegex(critic.ContractError, "evidence bundle not found"):
                critic.validate_evidence_bundle(root, "EVB-NOPE")

            manifest_path = write_evidence_bundle(root)
            path, manifest = critic.validate_evidence_bundle(root, "EVB-STATIC-1")
            self.assertEqual(manifest_path, path)
            self.assertEqual("E1", manifest["evidence_tier"])

            events = manifest_path.parent / "events.json"
            original_events = events.read_bytes()
            events.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(critic.ContractError, "attachment changed"):
                critic.validate_evidence_bundle(root, "EVB-STATIC-1")
            events.write_bytes(original_events)

            malformed = json.loads(manifest_path.read_text(encoding="utf-8"))
            malformed["manifest_sha256"] = "0" * 64
            write_json(manifest_path, malformed)
            with self.assertRaisesRegex(critic.ContractError, "canonical manifest hash mismatch"):
                critic.validate_evidence_bundle(root, "EVB-STATIC-1")
            write_evidence_bundle(root)

            write_review(
                root,
                "REV-SELF-1",
                ["EVB-STATIC-1"],
                reviewer_id="producer-1",
                subject_ids=("ROW-TEST-1",),
            )
            with self.assertRaisesRegex(critic.ContractError, "producer self-review"):
                critic.validate_review(root, "REV-SELF-1", subject_id="ROW-TEST-1")

            write_review(root, "REV-MISSING-EVB", ["EVB-NOPE"], subject_ids=("ROW-TEST-1",))
            with self.assertRaisesRegex(critic.ContractError, "evidence bundle not found"):
                critic.validate_review(root, "REV-MISSING-EVB", subject_id="ROW-TEST-1")

            duplicate = root / critic.RESEARCH_REL / "dynamic/evidence/EVB-STATIC-1/manifest.json"
            duplicate.parent.mkdir(parents=True, exist_ok=True)
            duplicate.write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(critic.ContractError, "resolves ambiguously"):
                critic.resolve_evidence_bundle(root, "EVB-STATIC-1")

    def test_evidence_bundle_derives_event_counts_and_resolves_canonical_claims(self):
        with tempfile.TemporaryDirectory(prefix="g001-evidence-derived-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            manifest_path = write_evidence_bundle(
                root,
                "EVB-DERIVED-1",
                tier="E2",
                source_variant="untouched",
                live=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            event_path = manifest_path.parent / "events.json"
            event_document = json.loads(event_path.read_text(encoding="utf-8"))
            event_document["events"] = []
            event_document["canonical_sha256"] = sha256_bytes(b"[]")
            write_json(event_path, event_document)
            event_attachment = next(item for item in manifest["attachments"] if item["path"] == "events.json")
            event_attachment["sha256"] = hashlib.sha256(event_path.read_bytes()).hexdigest()
            event_attachment["size_bytes"] = event_path.stat().st_size
            manifest.pop("manifest_sha256")
            manifest["manifest_sha256"] = sha256_bytes(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(critic.ContractError, "captured_events is not derived"):
                critic.validate_evidence_bundle(root, "EVB-DERIVED-1")

            manifest_path = write_evidence_bundle(
                root,
                "EVB-DERIVED-1",
                tier="E2",
                source_variant="untouched",
                live=True,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["claim_ids"] = ["CLM-DOES-NOT-EXIST"]
            manifest.pop("manifest_sha256")
            manifest["manifest_sha256"] = sha256_bytes(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(critic.ContractError, "claim not found"):
                critic.validate_evidence_bundle(root, "EVB-DERIVED-1")

    def test_static_inventory_rejects_synthetic_tiny_whole_apk_false_positive(self):
        with tempfile.TemporaryDirectory(prefix="g002-static-tiny-hostile-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=True)
            write_static_inventory_fixture(root, "B", include_discovered=True)
            with self.assertRaisesRegex(critic.ContractError, "real-artifact scope conservation"):
                critic.validate_static_inventory_convergence(root)

    def test_g002_real_artifact_conservation_keeps_jni_and_loader_counts_derived(self):
        for jni_edges in (3266, 4001):
            with self.subTest(jni_edges=jni_edges):
                conservation, record_counts, raw_documents = scope_conservation_fixture(jni_edges=jni_edges)
                critic._validate_inventory_scope_conservation(
                    conservation,
                    record_type_counts=record_counts,
                    raw_documents_by_bundle=raw_documents,
                    label="fixture inventory",
                )
        conservation, record_counts, raw_documents = scope_conservation_fixture(
            jni_edges=3266,
            reflection_targets=0,
            dynamic_loaders=0,
        )
        self.assertEqual(0, conservation["reflection_targets"]["observed_count"])
        self.assertEqual(0, conservation["dynamic_loaders"]["observed_count"])
        critic._validate_inventory_scope_conservation(
            conservation,
            record_type_counts=record_counts,
            raw_documents_by_bundle=raw_documents,
            label="fixture inventory",
        )

    def test_g002_real_artifact_conservation_rejects_missing_per_library_summary(self):
        conservation, record_counts, raw_documents = scope_conservation_fixture(jni_edges=3266)
        conservation["per_library_summaries"]["observed_count"] -= 1
        conservation["per_library_summaries"]["accounted_count"] -= 1
        with self.assertRaisesRegex(critic.ContractError, "per_library_summaries"):
            critic._validate_inventory_scope_conservation(
                conservation,
                record_type_counts=record_counts,
                raw_documents_by_bundle=raw_documents,
                label="fixture inventory",
            )

    def test_g002_record_identity_is_recomputed_from_nfc_canonical_scope_payload(self):
        payload = {"name": "Caf\u00e9", "ordinal": 3, "parents": ["A", "B"]}
        scope_key = critic._canonical_json_text(payload)
        record_id = critic._inventory_record_id("configuration", payload)
        critic._validate_inventory_record_identity(
            {"record_id": record_id, "record_type": "configuration", "scope_key": scope_key},
            "fixture record",
        )

        decomposed = unicodedata.normalize("NFD", "Caf\u00e9")
        noncanonical_scope = json.dumps(
            {"name": decomposed, "ordinal": 3, "parents": ["A", "B"]},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaisesRegex(critic.ContractError, "NFC canonical JSON"):
            critic._validate_inventory_record_identity(
                {"record_id": record_id, "record_type": "configuration", "scope_key": noncanonical_scope},
                "fixture record",
            )

        with self.assertRaisesRegex(critic.ContractError, "record_id is not derived"):
            critic._validate_inventory_record_identity(
                {"record_id": "INV-" + "0" * 64, "record_type": "configuration", "scope_key": scope_key},
                "fixture record",
            )

    def test_g002_rfc6901_pointer_resolution_is_strict(self):
        document = {"records": [{"a/b": {"~key": "resolved"}}]}
        self.assertEqual(
            "resolved",
            critic._resolve_json_pointer(document, "/records/0/a~1b/~0key", "fixture pointer"),
        )
        for pointer in ("records/0", "/records/00", "/records/0/a~2b"):
            with self.subTest(pointer=pointer):
                with self.assertRaises(critic.ContractError):
                    critic._resolve_json_pointer(document, pointer, "fixture pointer")

    def test_g002_source_locator_must_resolve_to_hash_listed_exact_raw_row(self):
        with tempfile.TemporaryDirectory(prefix="g002-source-locator-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=True)
            source_path = (
                root
                / critic.RESEARCH_REL
                / "static/evidence/EVB-INVENTORY-A/source-index.json"
            )
            source_index = json.loads(source_path.read_text(encoding="utf-8"))
            source_index["records"][0]["source_locator"] = "SRC-OPAQUE-NOT-EVIDENCE"
            source_index["canonical_sha256"] = sha256_bytes(
                critic._canonical_json_bytes(source_index["records"])
            )
            write_json(source_path, source_index)
            refresh_static_source_index_reference(root, "A")
            inventory = json.loads(
                (root / critic.RESEARCH_REL / "static/inventory-a.json").read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(critic.ContractError, "raw/<attachment>.json"):
                critic._validate_static_inventory_document(root, inventory, label="inventory A")

    def test_g002_raw_source_row_and_source_index_must_match_exactly(self):
        with tempfile.TemporaryDirectory(prefix="g002-source-mismatch-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=True)
            bundle_root = root / critic.RESEARCH_REL / "static/evidence/EVB-INVENTORY-A"
            raw_path = bundle_root / "raw/records.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            raw["records"][0]["scope_key"] = critic._canonical_json_text(["tampered"])
            write_json(raw_path, raw)
            refresh_bundle_attachment(root, "EVB-INVENTORY-A", "raw/records.json")
            inventory = json.loads(
                (root / critic.RESEARCH_REL / "static/inventory-a.json").read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(critic.ContractError, "does not exactly match its raw JSON row"):
                critic._validate_static_inventory_document(root, inventory, label="inventory A")

    def test_g002_every_record_bearing_raw_object_is_indexed(self):
        with tempfile.TemporaryDirectory(prefix="g002-raw-universe-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=True)
            bundle_root = root / critic.RESEARCH_REL / "static/evidence/EVB-INVENTORY-A"
            raw_path = bundle_root / "raw/records.json"
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            extra = copy.deepcopy(raw["records"][0])
            extra["source_locator"] = f"raw/records.json#/records/{len(raw['records'])}"
            raw["records"].append(extra)
            write_json(raw_path, raw)
            refresh_bundle_attachment(root, "EVB-INVENTORY-A", "raw/records.json")
            inventory = json.loads(
                (root / critic.RESEARCH_REL / "static/inventory-a.json").read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(critic.ContractError, "raw/source-index record universe differs"):
                critic._validate_static_inventory_document(root, inventory, label="inventory A")

    def test_g002_source_index_digest_uses_nfc_canonical_rows(self):
        with tempfile.TemporaryDirectory(prefix="g002-source-digest-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=True)
            source_path = (
                root
                / critic.RESEARCH_REL
                / "static/evidence/EVB-INVENTORY-A/source-index.json"
            )
            source_index = json.loads(source_path.read_text(encoding="utf-8"))
            source_index["canonical_sha256"] = "0" * 64
            write_json(source_path, source_index)
            refresh_static_source_index_reference(root, "A")
            inventory = json.loads(
                (root / critic.RESEARCH_REL / "static/inventory-a.json").read_text(encoding="utf-8")
            )
            with self.assertRaisesRegex(critic.ContractError, "source-index canonical hash is invalid"):
                critic._validate_static_inventory_document(root, inventory, label="inventory A")

    def _independence_pair(self):
        common = {
            "records": [],
            "canonical": b"[]",
            "local_dependency_sha256s": frozenset(),
        }
        first = critic.StaticInventoryValidation(
            inventory_id="INVENTORY-A",
            method_id="METHOD-A",
            toolchain_family="TOOLCHAIN-A",
            run_id="RUN-A",
            evidence_bundle_ids=frozenset({"EVB-A"}),
            review_id="REV-A",
            operator="producer-a",
            producer_script_path="tools/hik_whole_apk/g002_a.py",
            producer_script_sha256="a" * 64,
            producer_script_source="print('a')\n",
            commands=("python3 tools/hik_whole_apk/g002_a.py",),
            **common,
        )
        second = critic.StaticInventoryValidation(
            inventory_id="INVENTORY-B",
            method_id="METHOD-B",
            toolchain_family="TOOLCHAIN-B",
            run_id="RUN-B",
            evidence_bundle_ids=frozenset({"EVB-B"}),
            review_id="REV-B",
            operator="producer-b",
            producer_script_path="tools/hik_whole_apk/g002_b.py",
            producer_script_sha256="b" * 64,
            producer_script_source="print('b')\n",
            commands=("python3 tools/hik_whole_apk/g002_b.py",),
            **common,
        )
        return first, second

    def test_g002_inventory_methods_reject_same_operator_and_script_hash(self):
        first, second = self._independence_pair()
        with self.assertRaisesRegex(critic.ContractError, "operators"):
            critic._validate_inventory_independence(
                first,
                critic.StaticInventoryValidation(
                    **{**second.__dict__, "operator": first.operator}
                ),
            )
        with self.assertRaisesRegex(critic.ContractError, "producer script hashes"):
            critic._validate_inventory_independence(
                first,
                critic.StaticInventoryValidation(
                    **{**second.__dict__, "producer_script_sha256": first.producer_script_sha256}
                ),
            )

    def test_g002_inventory_methods_reject_shared_parser_implementation(self):
        first, second = self._independence_pair()
        shared = frozenset({"c" * 64})
        first = critic.StaticInventoryValidation(**{**first.__dict__, "local_dependency_sha256s": shared})
        second = critic.StaticInventoryValidation(**{**second.__dict__, "local_dependency_sha256s": shared})
        with self.assertRaisesRegex(critic.ContractError, "share a repository-local parser implementation"):
            critic._validate_inventory_independence(first, second)

    def test_g002_inventory_methods_reject_cross_lane_input_paths(self):
        first, second = self._independence_pair()
        first = critic.StaticInventoryValidation(
            **{
                **first.__dict__,
                "producer_script_source": (
                    "from pathlib import Path\n"
                    "Path('static/inventory-b.json').read_text()\n"
                ),
            }
        )
        with self.assertRaisesRegex(critic.ContractError, "cross-lane path/read references"):
            critic._validate_inventory_independence(first, second)

    def test_g002_review_postdates_run_completion_and_inventory_generation(self):
        with tempfile.TemporaryDirectory(prefix="g002-review-chronology-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, captured_at="2026-07-18T00:00:30Z")
            write_review(root, "REV-G002-CHRONOLOGY", ["EVB-STATIC-1"], subject_ids=("INVENTORY-A",))
            with self.assertRaisesRegex(critic.ContractError, "does not strictly postdate producer run completion"):
                critic.validate_review(
                    root,
                    "REV-G002-CHRONOLOGY",
                    subject_id="INVENTORY-A",
                    not_before=(("producer run completion", "2026-07-18T00:11:00Z"),),
                )

    def test_g002_review_equal_to_evidence_capture_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="g002-review-equals-evidence-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, captured_at="2026-07-18T00:10:00Z")
            write_review(root, "REV-G002-EQUAL-EVIDENCE", ["EVB-STATIC-1"], subject_ids=("INVENTORY-A",))
            with self.assertRaisesRegex(critic.ContractError, "does not strictly postdate evidence"):
                critic.validate_review(root, "REV-G002-EQUAL-EVIDENCE", subject_id="INVENTORY-A")

    def test_g002_inventory_generation_equal_to_run_completion_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="g002-generation-equals-run-", dir="/tmp") as temporary:
            root = Path(temporary)
            inventory = write_static_inventory_fixture(root, "A", include_discovered=True)
            run = json.loads((root / inventory["producer_run_manifest"]).read_text(encoding="utf-8"))
            inventory["generated_at"] = run["ended_at"]
            write_json(root / critic.RESEARCH_REL / "static/inventory-a.json", inventory)
            with self.assertRaisesRegex(
                critic.ContractError,
                "inventory generation does not strictly postdate producer run completion",
            ):
                critic._validate_static_inventory_document(root, inventory, label="inventory A")

    def test_g002_review_equal_to_run_completion_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="g002-review-equals-run-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, captured_at="2026-07-18T00:00:30Z")
            write_review(root, "REV-G002-EQUAL-RUN", ["EVB-STATIC-1"], subject_ids=("INVENTORY-A",))
            with self.assertRaisesRegex(critic.ContractError, "does not strictly postdate producer run completion"):
                critic.validate_review(
                    root,
                    "REV-G002-EQUAL-RUN",
                    subject_id="INVENTORY-A",
                    not_before=(("producer run completion", "2026-07-18T00:10:00Z"),),
                )

    def test_g002_review_equal_to_inventory_generation_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="g002-review-equals-generation-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, captured_at="2026-07-18T00:00:30Z")
            write_review(root, "REV-G002-EQUAL-GENERATION", ["EVB-STATIC-1"], subject_ids=("INVENTORY-A",))
            with self.assertRaisesRegex(critic.ContractError, "does not strictly postdate inventory generation"):
                critic.validate_review(
                    root,
                    "REV-G002-EQUAL-GENERATION",
                    subject_id="INVENTORY-A",
                    not_before=(("inventory generation", "2026-07-18T00:10:00Z"),),
                )

    def test_g002_review_covers_inventory_claims_and_every_bundle(self):
        with tempfile.TemporaryDirectory(prefix="g002-review-coverage-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, captured_at="2026-07-18T00:00:30Z")
            write_review(root, "REV-G002-COVERAGE", ["EVB-STATIC-1"], subject_ids=("INVENTORY-A",))
            with self.assertRaisesRegex(critic.ContractError, "does not cover required subjects"):
                critic.validate_review(
                    root,
                    "REV-G002-COVERAGE",
                    subject_id="INVENTORY-A",
                    expected_subject_ids=("CLM-TEST-1",),
                    expected_bundle_ids=("EVB-STATIC-1",),
                )

    def test_static_inventory_rejects_prior_empty_self_attestation_fixture(self):
        with tempfile.TemporaryDirectory(prefix="g001-static-empty-hostile-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            prior_bypass = {
                "schema_version": 1,
                "inventory_id": "INVENTORY-A",
                "artifact_set_id": ARTIFACT_SET_ID,
                "generated_at": "2026-07-18T00:00:00Z",
                "method": {
                    "method_id": "method-a",
                    "toolchain_family": "fake-a",
                    "commands": ["echo did-not-run"],
                    "tool_versions": {"fake": "1"},
                },
                "normalized_records": [{}],
                "coverage": {
                    "apk_members": 19,
                    "dex_files": 4,
                    "native_libraries": 88,
                    "unclassified": 0,
                },
                "canonical_sha256": sha256_bytes(b"[{}]"),
            }
            write_json(root / critic.RESEARCH_REL / "static/inventory-a.json", prior_bypass)
            prior_bypass_b = copy.deepcopy(prior_bypass)
            prior_bypass_b["inventory_id"] = "INVENTORY-B"
            prior_bypass_b["method"]["method_id"] = "method-b"
            prior_bypass_b["method"]["toolchain_family"] = "fake-b"
            write_json(root / critic.RESEARCH_REL / "static/inventory-b.json", prior_bypass_b)
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_static_inventory_convergence(root)

    def test_static_inventory_rejects_hash_backed_copy_of_only_the_frozen_identity_manifest(self):
        with tempfile.TemporaryDirectory(prefix="g001-static-mirror-hostile-", dir="/tmp") as temporary:
            root = Path(temporary)
            write_static_inventory_fixture(root, "A", include_discovered=False)
            write_static_inventory_fixture(root, "B", include_discovered=False)
            with self.assertRaisesRegex(critic.ContractError, "merely replays the frozen artifact manifest"):
                critic.validate_static_inventory_convergence(root)

    def test_dossier_index_rejects_prior_minimal_self_attestation_and_fake_backing(self):
        with tempfile.TemporaryDirectory(prefix="g001-dossiers-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            static = root / critic.RESEARCH_REL / "static"
            dossiers_root = root / critic.RESEARCH_REL / "dossiers"
            write_json(static / "ledger.json", ledger_document([{"row_id": "ROW-MINIMAL-1", "state": "verified"}]))
            write_json(
                dossiers_root / "index.json",
                {
                    "dossiers": [
                        {"dossier_id": f"D{index:02d}", "approved": True, "evidence_bundle_ids": ["EVB-NOPE"]}
                        for index in range(1, 14)
                    ]
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_dossiers_and_ledger(root)

    def test_dossier_static_graph_rejects_hash_backed_semantic_self_attestation(self):
        with tempfile.TemporaryDirectory(prefix="g001-dossier-graph-hostile-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            static = root / critic.RESEARCH_REL / "static"
            dossiers_root = root / critic.RESEARCH_REL / "dossiers"
            graph_path = root / critic.RESEARCH_REL / "dossiers/D01/static-graph.json"
            write_json(
                graph_path,
                {
                    "schema_version": 1,
                    "dossier_id": "D01",
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "scope_row_ids": ["ROW-TEST-1"],
                    "nodes": [{"node_id": "ANYTHING", "scope_row_ids": ["ROW-TEST-1"]}],
                    "edges": [{"from_node": "ANYTHING", "to_node": "ANYTHING", "relation": "trust me"}],
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "node key mismatch"):
                critic._validate_dossier_backing(
                    root,
                    [hash_row(root, graph_path)],
                    dossier_id="D01",
                    scope_row_ids={"ROW-TEST-1"},
                    kind="static_graphs",
                )

            rows = []
            index_rows = []
            manifests = []
            for index in range(1, 14):
                dossier_id = f"D{index:02d}"
                row_id = f"ROW-DOSSIER-{index:02d}"
                row = ledger_row(row_id=row_id, dossier_id=dossier_id)
                row["evidence_bundle_ids"] = ["EVB-NOPE"]
                row["verification_ids"] = ["EVB-NOPE-VERIFY"]
                rows.append(row)
                manifest_path = dossiers_root / dossier_id / "manifest.json"
                graph_path = manifest_path.parent / "static-graph.json"
                state_path = manifest_path.parent / "state-machine.json"
                test_path = manifest_path.parent / "reproduction-tests.json"
                for backing_path in (graph_path, state_path, test_path):
                    write_json(backing_path, {})
                write_json(
                    manifest_path,
                    {
                        "schema_version": 1,
                        "dossier_id": dossier_id,
                        "artifact_set_id": ARTIFACT_SET_ID,
                        "title": dossier_id,
                        "owner": "producer-1",
                        "approved": True,
                        "scope_row_ids": [row_id],
                        "static_graphs": [hash_row(root, graph_path)],
                        "dynamic_trace_bundle_ids": ["EVB-NOPE"],
                        "state_machines": [hash_row(root, state_path)],
                        "evidence_bundle_ids": ["EVB-NOPE", "EVB-NOPE-VERIFY"],
                        "unresolved_contradictions": [],
                        "specification_ids": ["SPEC-TEST-1"],
                        "reproduction_ids": ["REP-TEST-1"],
                        "reproduction_tests": [hash_row(root, test_path)],
                        "independent_review_ids": ["REV-NOPE"],
                    },
                )
                manifests.append((manifest_path, graph_path, state_path, test_path, row_id, dossier_id))
                index_rows.append({"dossier_id": dossier_id, "manifest_path": str(manifest_path.relative_to(root))})
            write_json(
                dossiers_root / "index.json",
                {"schema_version": 1, "artifact_set_id": ARTIFACT_SET_ID, "dossiers": index_rows},
            )
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_dossier_index(root, rows)

            for manifest_path, graph_path, state_path, test_path, row_id, dossier_id in manifests:
                write_json(
                    graph_path,
                    {
                        "schema_version": 1,
                        "dossier_id": dossier_id,
                        "artifact_set_id": ARTIFACT_SET_ID,
                        "scope_row_ids": [row_id],
                        "nodes": [
                            {
                                "node_id": "node-1",
                                "node_type": "behavior",
                                "scope_row_ids": [row_id],
                                "claim_ids": ["CLM-NOPE"],
                                "evidence_bundle_ids": ["EVB-NOPE"],
                                "source_refs": ["INV-NOPE"],
                            }
                        ],
                        "edges": [
                            {
                                "from_node": "node-1",
                                "to_node": "node-1",
                                "relation": "references",
                                "claim_ids": ["CLM-NOPE"],
                                "evidence_bundle_ids": ["EVB-NOPE"],
                                "source_refs": ["INV-NOPE"],
                            }
                        ],
                    },
                )
                write_json(
                    state_path,
                    {
                        "schema_version": 1,
                        "dossier_id": dossier_id,
                        "artifact_set_id": ARTIFACT_SET_ID,
                        "scope_row_ids": [row_id],
                        "states": ["ready"],
                        "transitions": [
                            {
                                "from_state": "ready",
                                "event": "observe",
                                "to_state": "ready",
                                "evidence_bundle_ids": ["EVB-NOPE"],
                            }
                        ],
                    },
                )
                write_json(
                    test_path,
                    {
                        "schema_version": 1,
                        "dossier_id": dossier_id,
                        "artifact_set_id": ARTIFACT_SET_ID,
                        "scope_row_ids": [row_id],
                        "reproduction_ids": ["REP-TEST-1"],
                        "test_ids": ["TEST-1"],
                        "commands": ["python3 -m unittest tests.test_reproduction"],
                        "results": [
                            {"test_id": "TEST-1", "status": "passed", "evidence_bundle_ids": ["EVB-NOPE-VERIFY"]}
                        ],
                    },
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["static_graphs"] = [hash_row(root, graph_path)]
                manifest["state_machines"] = [hash_row(root, state_path)]
                manifest["reproduction_tests"] = [hash_row(root, test_path)]
                write_json(manifest_path, manifest)
            with self.assertRaisesRegex(critic.ContractError, "evidence bundle not found"):
                critic.validate_dossier_index(root, rows)

    def test_radiometric_gate_rejects_nonfinite_metrics_and_named_nonexistent_ids(self):
        with tempfile.TemporaryDirectory(prefix="g001-radiometric-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            path = root / critic.RESEARCH_REL / "reproduction/radiometric-validation.json"
            payload = radiometric_payload()
            write_json(path, payload)
            with self.assertRaisesRegex(critic.ContractError, "evidence bundle not found"):
                critic.validate_radiometric_truthfulness(root)

            for invalid in (True, -0.01, float("nan"), float("inf")):
                hostile = copy.deepcopy(payload["fixture"])
                hostile["mean_error_c"] = invalid
                with self.subTest(metric=repr(invalid)):
                    with self.assertRaises(critic.ContractError):
                        critic._validate_radiometric_comparison(root, "fixture", hostile)

            path.write_text(path.read_text(encoding="utf-8").replace('"mean_error_c": 0.0', '"mean_error_c": NaN', 1), encoding="utf-8")
            with self.assertRaisesRegex(critic.ContractError, "non-finite JSON number"):
                critic.validate_radiometric_truthfulness(root)

    def test_radiometric_gate_derives_metrics_from_strict_comparison_not_generic_events(self):
        with tempfile.TemporaryDirectory(prefix="g001-radiometric-generic-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            payload = radiometric_payload()
            fixture_claim = payload["fixture"]["claim_id"]
            live_claim = payload["live"]["claim_id"]
            proof_claims = tuple(payload["proof_claim_ids"].values())
            write_evidence_bundle(root, "EVB-FIXTURE-OFFICIAL", tier="E1", claim_ids=proof_claims)
            write_evidence_bundle(
                root,
                "EVB-FIXTURE-REIMPL",
                tier="E4",
                source_variant="reimplementation",
                claim_ids=proof_claims,
            )
            write_evidence_bundle(
                root,
                "EVB-LIVE-OFFICIAL",
                tier="E2",
                source_variant="untouched",
                claim_ids=proof_claims,
                live=True,
            )
            write_evidence_bundle(
                root,
                "EVB-LIVE-REIMPL",
                tier="E4",
                source_variant="reimplementation",
                claim_ids=proof_claims,
                live=True,
            )
            write_evidence_bundle(
                root,
                "EVB-RAD-E5",
                tier="E5",
                source_variant="reimplementation",
                claim_ids=proof_claims,
            )
            payload["fixture"]["evidence_bundle_ids"] = ["EVB-FIXTURE-OFFICIAL", "EVB-FIXTURE-REIMPL"]
            payload["fixture"]["comparison_attachment"] = {
                "bundle_id": "EVB-FIXTURE-REIMPL",
                "path": "events.json",
            }
            payload["live"]["evidence_bundle_ids"] = ["EVB-LIVE-OFFICIAL", "EVB-LIVE-REIMPL"]
            payload["live"]["comparison_attachment"] = {
                "bundle_id": "EVB-LIVE-REIMPL",
                "path": "events.json",
            }
            payload["e5_conclusion_bundle_ids"] = ["EVB-RAD-E5"]
            payload["conclusion_attachment"] = {"bundle_id": "EVB-RAD-E5", "path": "events.json"}
            payload["independent_review_id"] = "REV-RAD-GENERIC"
            write_review(
                root,
                "REV-RAD-GENERIC",
                [
                    "EVB-FIXTURE-OFFICIAL",
                    "EVB-FIXTURE-REIMPL",
                    "EVB-LIVE-OFFICIAL",
                    "EVB-LIVE-REIMPL",
                    "EVB-RAD-E5",
                ],
                subject_ids=("RAD-TEST-1",),
            )
            write_json(root / critic.RESEARCH_REL / "reproduction/radiometric-validation.json", payload)
            with self.assertRaisesRegex(critic.ContractError, "comparison attachment key mismatch"):
                critic.validate_radiometric_truthfulness(root)

            write_evidence_bundle(
                root,
                "EVB-SWAPPED-E1",
                tier="E1",
                source_variant="reimplementation",
                claim_ids=(fixture_claim,),
            )
            write_evidence_bundle(
                root,
                "EVB-SWAPPED-E4",
                tier="E4",
                source_variant="untouched",
                claim_ids=(fixture_claim,),
            )
            swapped = copy.deepcopy(payload["fixture"])
            swapped["evidence_bundle_ids"] = ["EVB-SWAPPED-E1", "EVB-SWAPPED-E4"]
            swapped["comparison_attachment"] = {"bundle_id": "EVB-SWAPPED-E4", "path": "events.json"}
            with self.assertRaisesRegex(critic.ContractError, "E1 untouched plus E4 reimplementation"):
                critic._validate_radiometric_comparison(root, "fixture", swapped)

    def test_radiometric_strict_synthetic_contract_accepts_only_derived_thresholds(self):
        with tempfile.TemporaryDirectory(prefix="g001-radiometric-derived-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            payload = radiometric_payload()
            fixture_claim = payload["fixture"]["claim_id"]
            live_claim = payload["live"]["claim_id"]
            proof_claims = tuple(payload["proof_claim_ids"].values())
            write_evidence_bundle(root, "EVB-FIX-OFFICIAL", tier="E1", claim_ids=proof_claims)
            write_evidence_bundle(
                root,
                "EVB-FIX-REIMPL",
                tier="E4",
                source_variant="reimplementation",
                claim_ids=proof_claims,
            )
            write_evidence_bundle(
                root,
                "EVB-LIVE-OFFICIAL-2",
                tier="E2",
                source_variant="untouched",
                claim_ids=proof_claims,
                live=True,
            )
            write_evidence_bundle(
                root,
                "EVB-LIVE-REIMPL-2",
                tier="E4",
                source_variant="reimplementation",
                claim_ids=proof_claims,
                live=True,
            )
            write_evidence_bundle(
                root,
                "EVB-RAD-E5-2",
                tier="E5",
                source_variant="reimplementation",
                claim_ids=proof_claims,
            )

            def comparison_document(kind, claim_id, official_bundle_id, reimplementation_bundle_id, live):
                samples = [
                    {"sample_id": "sample-1", "official_c": 20.0, "reimplementation_c": 20.05},
                    {"sample_id": "sample-2", "official_c": 21.0, "reimplementation_c": 21.10},
                ]
                errors = [abs(item["official_c"] - item["reimplementation_c"]) for item in samples]
                return {
                    "schema_version": 1,
                    "comparison_id": f"CMP-{kind.upper()}-1",
                    "kind": kind,
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "claim_id": claim_id,
                    "official_bundle_id": official_bundle_id,
                    "reimplementation_bundle_id": reimplementation_bundle_id,
                    "official_artifact_ids": ["official-converter"],
                    "converter_identities": {
                        "official_artifact_id": "official-converter",
                        "reimplementation_attachment": {
                            "bundle_id": reimplementation_bundle_id,
                            "path": "state.json",
                        },
                    },
                    "unit": "celsius",
                    "calibration_environment": {
                        "inputs_attachment": {"bundle_id": official_bundle_id, "path": "state.json"},
                        "emissivity": 0.95,
                        "ambient_temperature_c": 20.0,
                        "distance_m": 0.5,
                        "relative_humidity_percent": 50.0,
                    },
                    "dimensions": {"width": 2, "height": 1, "stride": 2},
                    "frame_correlation": {
                        "official_frame_id": "official-frame-1",
                        "reimplementation_frame_id": "reimplementation-frame-1",
                        "correlation_id": f"correlation-{kind}",
                    },
                    "live_provenance": (
                        {
                            "callback_count": 2,
                            "frame_counter": 2,
                            "accepted_frame": True,
                            "preview_updated": True,
                            "camera_fingerprint": "camera-1",
                        }
                        if live
                        else None
                    ),
                    "samples": samples,
                    "computed": {
                        "sample_count": len(samples),
                        "mean_error_c": sum(errors) / len(errors),
                        "max_pixel_error_c": max(errors),
                    },
                }

            fixture_document = comparison_document(
                "fixture", fixture_claim, "EVB-FIX-OFFICIAL", "EVB-FIX-REIMPL", False
            )
            live_document = comparison_document(
                "live", live_claim, "EVB-LIVE-OFFICIAL-2", "EVB-LIVE-REIMPL-2", True
            )
            fixture_attachment = add_bundle_json_attachment(
                root, "EVB-FIX-REIMPL", "fixture-comparison.json", fixture_document
            )
            live_attachment = add_bundle_json_attachment(
                root, "EVB-LIVE-REIMPL-2", "live-comparison.json", live_document
            )
            fixture_errors = [
                abs(item["official_c"] - item["reimplementation_c"])
                for item in fixture_document["samples"]
            ]
            live_errors = [
                abs(item["official_c"] - item["reimplementation_c"])
                for item in live_document["samples"]
            ]
            payload["fixture"].update(
                {
                    "evidence_bundle_ids": ["EVB-FIX-OFFICIAL", "EVB-FIX-REIMPL"],
                    "sample_count": 2,
                    "mean_error_c": sum(fixture_errors) / 2,
                    "max_pixel_error_c": max(fixture_errors),
                    "comparison_attachment": {
                        "bundle_id": "EVB-FIX-REIMPL",
                        "path": "fixture-comparison.json",
                    },
                }
            )
            payload["live"].update(
                {
                    "evidence_bundle_ids": ["EVB-LIVE-OFFICIAL-2", "EVB-LIVE-REIMPL-2"],
                    "sample_count": 2,
                    "mean_error_c": sum(live_errors) / 2,
                    "max_pixel_error_c": max(live_errors),
                    "comparison_attachment": {
                        "bundle_id": "EVB-LIVE-REIMPL-2",
                        "path": "live-comparison.json",
                    },
                }
            )
            conclusion = {
                "schema_version": 1,
                "validation_id": "RAD-TEST-1",
                "artifact_set_id": ARTIFACT_SET_ID,
                "proof_claim_ids": payload["proof_claim_ids"],
                "comparison_records": [
                    {
                        "kind": "fixture",
                        "bundle_id": "EVB-FIX-REIMPL",
                        "path": "fixture-comparison.json",
                        "sha256": fixture_attachment["sha256"],
                    },
                    {
                        "kind": "live",
                        "bundle_id": "EVB-LIVE-REIMPL-2",
                        "path": "live-comparison.json",
                        "sha256": live_attachment["sha256"],
                    },
                ],
                "verdict": "pass",
                "celsius_publication_allowed": True,
            }
            add_bundle_json_attachment(root, "EVB-RAD-E5-2", "conclusion.json", conclusion)
            payload["e5_conclusion_bundle_ids"] = ["EVB-RAD-E5-2"]
            payload["conclusion_attachment"] = {"bundle_id": "EVB-RAD-E5-2", "path": "conclusion.json"}
            payload["independent_review_id"] = "REV-RAD-DERIVED"
            write_review(
                root,
                "REV-RAD-DERIVED",
                [
                    "EVB-FIX-OFFICIAL",
                    "EVB-FIX-REIMPL",
                    "EVB-LIVE-OFFICIAL-2",
                    "EVB-LIVE-REIMPL-2",
                    "EVB-RAD-E5-2",
                ],
                subject_ids=("RAD-TEST-1",),
            )
            write_json(root / critic.RESEARCH_REL / "reproduction/radiometric-validation.json", payload)
            evidence = critic.validate_radiometric_truthfulness(root)
            self.assertIn("publication_proofs=8/8", evidence)

            tampered = json.loads((root / critic.RESEARCH_REL / "reproduction/radiometric-validation.json").read_text())
            tampered["live"]["mean_error_c"] = 0.0
            write_json(root / critic.RESEARCH_REL / "reproduction/radiometric-validation.json", tampered)
            with self.assertRaisesRegex(critic.ContractError, "not derived from measured pairs"):
                critic.validate_radiometric_truthfulness(root)

    def test_closure_rejects_subset_keys_bool_counters_null_or_noncanonical_ledger(self):
        with tempfile.TemporaryDirectory(prefix="g001-closure-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            closure_path = root / critic.RESEARCH_REL / "closure/current.json"

            payload = closure_payload(None)
            write_json(closure_path, payload)
            with self.assertRaisesRegex(critic.ContractError, "repository-relative path"):
                critic.validate_closure(root)

            subset = closure_payload(".omx/research/hikmicro-viewer-2.6.0/static/ledger.json")
            subset["final_gates"] = {"artifact_inventory_converged": True}
            write_json(closure_path, subset)
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_closure(root)

            boolean_counter = closure_payload(".omx/research/hikmicro-viewer-2.6.0/static/ledger.json")
            boolean_counter["counters"]["blocked"] = False
            write_json(closure_path, boolean_counter)
            with self.assertRaisesRegex(critic.ContractError, "not all zero"):
                critic.validate_closure(root)

            outside = closure_payload("../outside-ledger.json")
            write_json(closure_path, outside)
            with self.assertRaisesRegex(critic.ContractError, "escapes|permitted root"):
                critic.validate_closure(root)

            canonical = closure_payload(".omx/research/hikmicro-viewer-2.6.0/static/ledger.json")
            write_json(closure_path, canonical)
            with self.assertRaisesRegex(critic.ContractError, "is missing"):
                critic.validate_closure(root)

            write_json(root / critic.RESEARCH_REL / "static/ledger.json", {})
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_closure(root)

    def test_final_reviews_cannot_approve_deliverables_with_unrelated_evidence(self):
        with tempfile.TemporaryDirectory(prefix="g001-final-reviews-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(root, "EVB-EXPECTED-1")
            write_evidence_bundle(root, "EVB-UNRELATED-1", claim_ids=("CLM-UNRELATED-1",))
            reviews = {
                "official_behavior_dossier": ("REV-DOSSIER-FINAL", "official-behavior-dossier", "reviewer-dossier"),
                "source_independent_specification": (
                    "REV-SPEC-FINAL",
                    "source-independent-specification",
                    "reviewer-spec",
                ),
                "independent_reproduction": (
                    "REV-REPRO-FINAL",
                    "independent-reproduction",
                    "reviewer-reproduction",
                ),
            }
            for review_id, subject, reviewer in reviews.values():
                write_review(
                    root,
                    review_id,
                    ["EVB-UNRELATED-1"],
                    reviewer_id=reviewer,
                    subject_ids=(subject,),
                )
            write_review(
                root,
                "REV-PUBLIC-FINAL",
                ["EVB-UNRELATED-1"],
                reviewer_id="reviewer-public",
                subject_ids=("public-proprietary-material-boundary",),
            )
            write_json(
                root / critic.RESEARCH_REL / "reviews/final-approvals.json",
                {
                    "schema_version": 1,
                    "approval_id": "APPROVAL-TEST-1",
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "deliverable_review_ids": {
                        key: value[0] for key, value in reviews.items()
                    },
                    "public_material_review_id": "REV-PUBLIC-FINAL",
                },
            )
            expected = {
                "official_behavior_dossier": ["EVB-EXPECTED-1"],
                "source_independent_specification": ["EVB-EXPECTED-1"],
                "independent_reproduction": ["EVB-EXPECTED-1"],
            }
            with self.assertRaisesRegex(critic.ContractError, "does not cover required evidence bundles"):
                critic.validate_final_deliverable_reviews(root, expected, {key: [] for key in expected})

    def test_dynamic_convergence_validates_run_manifest_instead_of_file_name(self):
        with tempfile.TemporaryDirectory(prefix="g001-run-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            run_path = root / critic.RESEARCH_REL / "dynamic/runs/run-1/manifest.json"
            write_json(run_path, {})
            convergence = {
                "schema_version": 1,
                "artifact_set_id": ARTIFACT_SET_ID,
                "sessions": [
                    {
                        "run_id": "RUN-TEST-1",
                        "source_variant": "untouched",
                        "new_rows": 0,
                        "run_manifest": str(run_path.relative_to(root)),
                        "evidence_bundle_ids": ["EVB-NOPE-1"],
                        "session_proof": {},
                    },
                    {
                        "run_id": "RUN-TEST-2",
                        "source_variant": "untouched",
                        "new_rows": 0,
                        "run_manifest": str(run_path.relative_to(root)),
                        "evidence_bundle_ids": ["EVB-NOPE-2"],
                        "session_proof": {},
                    },
                ],
                "instrumented_observations_labeled": True,
                "unexplained_baseline_divergences": 0,
            }
            write_json(root / critic.RESEARCH_REL / "dynamic/exploration-convergence.json", convergence)
            with self.assertRaisesRegex(critic.ContractError, "run manifest.*key mismatch"):
                critic.validate_dynamic_convergence(root)

    def test_run_manifest_resolves_baseline_snapshot_and_paired_untouched_run(self):
        with tempfile.TemporaryDirectory(prefix="g001-run-contract-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            run_path = write_run_manifest(root)
            run = json.loads(run_path.read_text(encoding="utf-8"))
            run["baseline_id"] = "BASELINE-DOES-NOT-EXIST"
            write_json(run_path, run)
            with self.assertRaisesRegex(critic.ContractError, "does not resolve to the frozen implementation baseline"):
                critic.validate_run_manifest(root, str(run_path.relative_to(root)))

            run_path = write_run_manifest(root)
            state_path = run_path.parent / "state.json"
            state_path.write_text('{"state":"tampered"}\n', encoding="utf-8")
            with self.assertRaisesRegex(critic.ContractError, "hash/size does not match"):
                critic.validate_run_manifest(root, str(run_path.relative_to(root)))

            instrumented_path = write_run_manifest(
                root,
                "RUN-INSTRUMENTED-1",
                "EXP-INSTRUMENTED-1",
                started_at="2026-07-18T00:02:00Z",
                ended_at="2026-07-18T00:03:00Z",
            )
            comparison_path = instrumented_path.parent / "paired-comparison.json"
            comparison = {
                "schema_version": 1,
                "comparison_id": "CMP-INSTRUMENTED-1",
                "artifact_set_id": ARTIFACT_SET_ID,
                "untouched_run_id": "RUN-DOES-NOT-EXIST",
                "instrumented_run_id": "RUN-INSTRUMENTED-1",
                "compared_event_dimensions": ["lifecycle"],
                "pre_target_divergence_ids": [],
            }
            comparison["canonical_sha256"] = sha256_bytes(
                json.dumps(comparison, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            write_json(comparison_path, comparison)
            instrumented = json.loads(instrumented_path.read_text(encoding="utf-8"))
            instrumented["source_variant"] = "root-attached"
            instrumented["instrumentation_delta"] = {
                "hooks": ["lifecycle-hook"],
                "patches": [],
                "root_modules": [],
                "debugger": [],
                "proxies": [],
                "usb_capture_point": None,
                "expected_perturbation": "lifecycle logging only",
                "paired_untouched_run_id": "RUN-DOES-NOT-EXIST",
            }
            instrumented["paired_comparison"] = hash_row(root, comparison_path)
            write_json(instrumented_path, instrumented)
            with self.assertRaisesRegex(critic.ContractError, "paired untouched run manifest is missing"):
                critic.validate_run_manifest(root, str(instrumented_path.relative_to(root)))

    def test_dynamic_convergence_rejects_one_clean_run_duplicated_as_two_sessions(self):
        with tempfile.TemporaryDirectory(prefix="g001-run-duplicate-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            run_path = write_run_manifest(root)
            write_evidence_bundle(
                root,
                "EVB-RUN-1",
                tier="E2",
                source_variant="untouched",
                live=True,
            )
            session = {
                "run_id": "RUN-TEST-1",
                "source_variant": "untouched",
                "new_rows": 0,
                "run_manifest": str(run_path.relative_to(root)),
                "evidence_bundle_ids": ["EVB-RUN-1"],
                "session_proof": {},
            }
            write_json(
                root / critic.RESEARCH_REL / "dynamic/exploration-convergence.json",
                {
                    "schema_version": 1,
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "sessions": [session, copy.deepcopy(session)],
                    "instrumented_observations_labeled": True,
                    "unexplained_baseline_divergences": 0,
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "reuses a run ID, manifest, or experiment"):
                critic.validate_dynamic_convergence(root)

    def test_dynamic_convergence_rejects_renamed_copies_with_overlapping_intervals(self):
        with tempfile.TemporaryDirectory(prefix="g001-run-overlap-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            run_paths = [
                write_run_manifest(root, "RUN-CLEAN-1", "EXP-CLEAN-1"),
                write_run_manifest(root, "RUN-CLEAN-2", "EXP-CLEAN-2"),
            ]
            for index in (1, 2):
                write_evidence_bundle(
                    root,
                    f"EVB-CLEAN-{index}",
                    tier="E2",
                    source_variant="untouched",
                    live=True,
                    experiment_id=f"EXP-CLEAN-{index}",
                )
            sessions = [
                {
                    "run_id": f"RUN-CLEAN-{index}",
                    "source_variant": "untouched",
                    "new_rows": 0,
                    "run_manifest": str(run_paths[index - 1].relative_to(root)),
                    "evidence_bundle_ids": [f"EVB-CLEAN-{index}"],
                    "session_proof": {},
                }
                for index in (1, 2)
            ]
            write_json(
                root / critic.RESEARCH_REL / "dynamic/exploration-convergence.json",
                {
                    "schema_version": 1,
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "sessions": sessions,
                    "instrumented_observations_labeled": True,
                    "unexplained_baseline_divergences": 0,
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "not successive non-overlapping"):
                critic.validate_dynamic_convergence(root)

    def test_dynamic_convergence_rejects_bare_zero_row_and_labeled_self_attestation(self):
        with tempfile.TemporaryDirectory(prefix="g001-run-self-attested-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            run_paths = [
                write_run_manifest(
                    root,
                    f"RUN-CLEAN-{index}",
                    f"EXP-CLEAN-{index}",
                    started_at=f"2026-07-18T00:0{2 * index}:00Z",
                    ended_at=f"2026-07-18T00:0{2 * index + 1}:00Z",
                )
                for index in (1, 2)
            ]
            sessions = []
            for index, run_path in enumerate(run_paths, start=1):
                bundle_id = f"EVB-CLEAN-{index}"
                write_evidence_bundle(
                    root,
                    bundle_id,
                    tier="E2",
                    source_variant="untouched",
                    live=True,
                    experiment_id=f"EXP-CLEAN-{index}",
                    captured_at=f"2026-07-18T00:0{2 * index}:30Z",
                )
                sessions.append(
                    {
                        "run_id": f"RUN-CLEAN-{index}",
                        "source_variant": "untouched",
                        "new_rows": 0,
                        "run_manifest": str(run_path.relative_to(root)),
                        "evidence_bundle_ids": [bundle_id],
                        "session_proof": {},
                    }
                )
            write_json(
                root / critic.RESEARCH_REL / "dynamic/exploration-convergence.json",
                {
                    "schema_version": 1,
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "sessions": sessions,
                    "instrumented_observations_labeled": True,
                    "unexplained_baseline_divergences": 0,
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "session_proof.*key mismatch"):
                critic.validate_dynamic_convergence(root)

    def test_f2_frontier_rejects_generic_bundle_and_nonexistent_updating_run(self):
        with tempfile.TemporaryDirectory(prefix="g001-f2-frontier-hostile-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_evidence_bundle(
                root,
                "EVB-F2-GENERIC",
                tier="E2",
                source_variant="untouched",
                live=True,
                claim_ids=("CLM-UNRELATED",),
            )
            write_json(
                root / critic.RESEARCH_REL / "dynamic/f2-current-causal-frontier.json",
                {
                    "frontier_id": "F2-first-frame",
                    "owner": "producer-1",
                    "last_proven_checkpoint": critic.F2_CHECKPOINTS[5],
                    "first_missing_checkpoint": critic.F2_CHECKPOINTS[6],
                    "supporting_bundle_ids": ["EVB-F2-GENERIC"],
                    "next_discriminating_experiment": "continue",
                    "updated_by_run_id": "RUN-DOES-NOT-EXIST",
                    "evidence_backed": True,
                    "active_frontier_count": 1,
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "key mismatch.*checkpoint_proof"):
                critic.validate_f2_frontier(root)

    def test_f2_live_rejects_reused_generic_bundles_and_producer_written_results(self):
        with tempfile.TemporaryDirectory(prefix="g001-f2-live-hostile-", dir="/tmp") as temporary:
            root = make_contract_root(temporary)
            write_json(
                root / critic.RESEARCH_REL / "dynamic/f2-live-e2e.json",
                {
                    "schema_version": 1,
                    "validation_id": "F2-LIVE-HOSTILE",
                    "artifact_set_id": ARTIFACT_SET_ID,
                    "passed": True,
                    "checkpoint_bundle_ids": {
                        checkpoint: ["EVB-GENERIC-E2", "EVB-GENERIC-E4"]
                        for checkpoint in critic.F2_CHECKPOINTS
                    },
                    "checkpoint_results": {checkpoint: True for checkpoint in critic.F2_CHECKPOINTS},
                    "callback_count": 1,
                    "frame_counter": 1,
                    "preview_updated": True,
                    "teardown_completed": True,
                    "reconnect_recovered": True,
                    "independent_review_id": "REV-F2-GENERIC",
                },
            )
            with self.assertRaisesRegex(critic.ContractError, "key mismatch"):
                critic.validate_f2_live_e2e(root)

    def _evaluate_isolated_phase(self, root, *, static_passes):
        passing = mock.Mock(return_value=("fixture",))
        failing = mock.Mock(side_effect=critic.ContractError("fixture remains unobserved"))
        mission = critic.Mission(directory=root, path=root / "mission.json", data={})
        with mock.patch.multiple(
            critic,
            validate_mission_contract=passing,
            validate_official_artifact_freeze=passing,
            validate_implementation_baseline=passing,
            validate_static_inventory_convergence=passing if static_passes else failing,
            validate_dossiers_and_ledger=failing,
            validate_dynamic_convergence=failing,
            validate_f2_frontier=failing,
            validate_clean_specs_and_fixtures=failing,
            validate_radiometric_truthfulness=failing,
            validate_closure=failing,
            validate_premortems_and_independent_review=failing,
        ):
            return critic.evaluate(root, mission)

    def test_historical_g001_phase_isolated_exactly_four_of_twelve(self):
        with tempfile.TemporaryDirectory(prefix="g001-gate-vector-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=False)
            result = self._evaluate_isolated_phase(root, static_passes=False)
        gates = {item["gate_id"]: item for item in result["gates"]}
        self.assertFalse(result["passed"])
        self.assertEqual("fail", result["verdict"])
        self.assertEqual({"passed": 4, "failed": 8, "total": 12}, result["gate_counts"])
        for gate_id in (
            "mission_contract",
            "official_artifact_freeze",
            "current_implementation_baseline",
            "governance_and_truthfulness_contracts",
        ):
            self.assertTrue(gates[gate_id]["passed"], gate_id)
        self.assertFalse(gates["independent_static_inventory_convergence"]["passed"])
        self.assertIn("fixture remains unobserved", gates["independent_static_inventory_convergence"]["reasons"][0])
        self.assertEqual([], result["truthfulness"]["unobserved_success_claims"])
        self.assertFalse(result["truthfulness"]["completion_file_is_authoritative"])

    def test_truthful_g002_phase_isolated_exactly_five_of_twelve(self):
        with tempfile.TemporaryDirectory(prefix="g002-gate-vector-", dir="/tmp") as temporary:
            root = make_governance_phase_root(temporary, g002_started=True)
            result = self._evaluate_isolated_phase(root, static_passes=True)
        gates = {item["gate_id"]: item for item in result["gates"]}
        self.assertEqual({"passed": 5, "failed": 7, "total": 12}, result["gate_counts"])
        self.assertTrue(gates["governance_and_truthfulness_contracts"]["passed"])
        self.assertTrue(gates["independent_static_inventory_convergence"]["passed"])
        self.assertTrue(all(not gates[gate_id]["passed"] for gate_id in (
            "ledger_and_13_dossiers_terminal",
            "untouched_instrumented_dynamic_convergence",
            "single_evidence_backed_f2_causal_frontier",
            "source_independent_specs_and_fixtures",
            "radiometric_no_fake_celsius",
            "zero_counters_and_final_gate_vector",
            "three_premortems_and_independent_critic",
        )))

    def test_two_cli_runs_are_byte_deterministic_and_fail_closed(self):
        command = [
            sys.executable,
            "tools/hik_whole_apk/critic.py",
            "--mission",
            FULL_MISSION_SLUG,
            "--verify-current-baseline",
        ]
        first = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        self.assertEqual(1, first.returncode)
        self.assertEqual(1, second.returncode)
        self.assertEqual("", first.stderr)
        self.assertEqual("", second.stderr)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertFalse(payload["passed"])
        self.assertEqual("fail", payload["verdict"])
        self.assertEqual(12, payload["gate_counts"]["total"])
        self.assertEqual(
            payload["gate_counts"]["passed"],
            sum(item["passed"] for item in payload["gates"]),
        )

    def test_cli_resolution_error_is_deterministic_fail_closed_json(self):
        command = [
            sys.executable,
            "tools/hik_whole_apk/critic.py",
            "--mission",
            "definitely-not-a-real-mission",
        ]
        first = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        second = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
        self.assertEqual(2, first.returncode)
        self.assertEqual(first.stdout, second.stdout)
        payload = json.loads(first.stdout)
        self.assertFalse(payload["passed"])
        self.assertEqual("error", payload["verdict"])


if __name__ == "__main__":
    unittest.main()
