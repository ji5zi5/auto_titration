#!/usr/bin/env python3
"""Summarize a HIKMICRO Analyzer SDK trace folder.

Use this after collecting a HIKMICRO Analyzer trace. It checks whether the official
Analyzer export actually reached MicroTA/MTlib_OL and lists the captured
configuration payloads needed to reproduce the exact temperature conversion.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def latest_trace(root: Path) -> Path:
    candidates = [p for p in root.glob("*/events.jsonl") if p.is_file()]
    if not candidates:
        raise SystemExit(f"No events.jsonl found under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime).parent


def read_events(trace_dir: Path) -> list[dict]:
    events_path = trace_dir / "events.jsonl"
    if not events_path.exists():
        raise SystemExit(f"Missing {events_path}")
    events = []
    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"event": "decode_error", "raw": line[:300]})
    return events


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trace", nargs="?", type=Path, help="trace folder; default latest under data/analyzer_sdk_trace")
    ap.add_argument("--root", type=Path, default=Path("data/analyzer_sdk_trace"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    trace_dir = args.trace or latest_trace(args.root)
    events = read_events(trace_dir)

    event_counts = Counter(e.get("event", "?") for e in events)
    hooked = [e for e in events if e.get("event") == "hooked"]
    mt_set = [e for e in events if e.get("event") == "MT_SetConfig_enter"]
    mt_proc = [e for e in events if e.get("event") == "MT_Process_leave"]
    mt_create = [e for e in events if e.get("event") == "MT_Create_leave"]
    ta_ctor = [e for e in events if e.get("event") == "TempAnalyzer_ctor_enter"]
    ta_set = [e for e in events if str(e.get("event", "")).startswith("TempAnalyzer_") and str(e.get("event", "")).endswith("_enter")]
    analytics_export = [e for e in events if str(e.get("event", "")).startswith("MicroAnalytics_TempMartixInfoCache")]
    analytics_factory = [e for e in events if str(e.get("event", "")).startswith("MicroAnalytics_FileParseFactory")]
    pixeler_parse = [e for e in events if str(e.get("event", "")).startswith("MicroPixeler_parse") or "MaterialParse" in str(e.get("event", ""))]
    pixeler_analysis = [e for e in events if "TakedMaterialAnalyzControl" in str(e.get("event", ""))]
    pixeler_tables = [e for e in events if "GrayToTempTable" in str(e.get("event", ""))]

    type1 = []
    config_types = Counter()
    for e in mt_set:
        typ = e.get("config_type")
        config_types[str(typ)] += 1
        if typ == 1:
            type1.append({"seq": e.get("seq"), "key": e.get("key"), "value_u32": e.get("value_u32"), "value_i32": e.get("value_i32")})

    blob_events = [e for e in events if e.get("event") == "blob"]
    blob_by_kind = defaultdict(list)
    for e in blob_events:
        blob_by_kind[str(e.get("name"))].append({
            "seq": e.get("seq"),
            "requested_len": e.get("requested_len"),
            "dumped_len": e.get("dumped_len"),
            "blob_path": e.get("blob_path"),
            "config_type": e.get("config_type"),
            "kind": e.get("kind"),
        })

    summary = {
        "trace_dir": str(trace_dir),
        "events_count": len(events),
        "hooked_exports_count": len(hooked),
        "hooked_modules": sorted(set(e.get("module") for e in hooked if e.get("module"))),
        "event_counts_top": event_counts.most_common(30),
        "mt": {
            "create_calls": len(mt_create),
            "setconfig_calls": len(mt_set),
            "setconfig_types": dict(config_types),
            "type1_key_values": type1,
            "process_calls": len(mt_proc),
            "process_samples": mt_proc[:5],
        },
        "microta": {
            "temp_analyzer_ctor_calls": len(ta_ctor),
            "setter_enter_calls": len(ta_set),
            "ctor_samples": ta_ctor[:3],
        },
        "microanalytics": {
            "matrix_export_related_calls": len(analytics_export),
            "samples": analytics_export[:10],
            "file_factory_calls": len(analytics_factory),
            "file_factory_samples": analytics_factory[:10],
        },
        "micropixeler": {
            "parse_calls": len(pixeler_parse),
            "parse_samples": pixeler_parse[:10],
            "analysis_calls": len(pixeler_analysis),
            "analysis_samples": pixeler_analysis[:10],
            "gray_to_temp_table_calls": len(pixeler_tables),
            "gray_to_temp_table_samples": pixeler_tables[:10],
        },
        "payload_groups": {k: v[:10] for k, v in blob_by_kind.items()},
        "status": "has_conversion_calls" if (mt_set or mt_proc or ta_ctor or pixeler_analysis or pixeler_tables) else "hooks_only_no_export_calls",
        "next": (
            "Trace contains conversion calls; inspect payloads and replay MT_SetConfig sequence."
            if (mt_set or mt_proc or ta_ctor or pixeler_analysis or pixeler_tables)
            else "Open a radiometric JPEG in Analyzer and export the temperature matrix while trace is still running."
        ),
    }

    out = args.out or (trace_dir / "summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:20000])
    print(f"saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
