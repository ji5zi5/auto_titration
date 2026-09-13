#!/usr/bin/env python3
"""Extract targeted Androguard evidence for the HIKMICRO Viewer APK.

Outputs are intentionally machine-readable and scoped to G007 parity analysis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger
logger.remove()  # Androguard is extremely verbose at DEBUG by default.

from androguard.misc import AnalyzeAPK  # noqa: E402
import androguard  # noqa: E402

TARGET_EXACT_PREFIXES = (
    "Lcom/hik/viewer/manager/PreviewManagerII",
    "Lg3/",
    "Lh3/",
    "Ld3/",
)
TARGET_SUBSTRINGS = (
    "PreviewInfoDataBean",
    "PreviewStreamInfo",
    "ThermalInfoHelper",
    "ThermalPlayer",
    "org/Thermal/PlayM4/Player",
    "GYUV",
)
PREVIEW_DEP_SUBSTRINGS = (
    "PreviewManagerII",
    "PreviewInfoDataBean",
    "PreviewStreamInfo",
    "ThermalInfoHelper",
    "ThermalPlayer",
    "org/Thermal/PlayM4/Player",
    "GYUV",
)


def jdump(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def sort_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=canonical)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def class_name(obj: Any) -> str:
    return getattr(obj, "name", None) or getattr(obj, "class_name", None) or str(obj)


def method_sig(method_analysis: Any) -> dict[str, Any]:
    method = method_analysis.get_method() if hasattr(method_analysis, "get_method") else method_analysis
    get = lambda name, default=None: getattr(method, name, default)
    def call0(attr: str, default: Any = None) -> Any:
        value = getattr(method, attr, None)
        if callable(value):
            try:
                return value()
            except Exception as exc:  # pragma: no cover - defensive extraction
                return f"<error:{type(exc).__name__}:{exc}>"
        return default
    cls = call0("get_class_name", getattr(method_analysis, "class_name", None))
    name = call0("get_name", getattr(method_analysis, "name", None))
    desc = call0("get_descriptor", getattr(method_analysis, "descriptor", None))
    access = call0("get_access_flags_string", getattr(method_analysis, "access", None))
    code_obj = call0("get_code", None)
    return {
        "class": cls,
        "name": name,
        "descriptor": desc,
        "full_descriptor": f"{cls}->{name}{desc}",
        "access_flags": access,
        "is_external": bool(method_analysis.is_external()) if hasattr(method_analysis, "is_external") else None,
        "length": method_analysis.get_length() if hasattr(method_analysis, "get_length") else None,
        "code_off": call0("get_code_off", None),
        "address": call0("get_address", None),
        "registers_size": getattr(code_obj, "registers_size", None) if code_obj is not None else None,
        "ins_size": getattr(code_obj, "ins_size", None) if code_obj is not None else None,
        "outs_size": getattr(code_obj, "outs_size", None) if code_obj is not None else None,
    }


def xref_tuple_to_record(direction: str, source_method: Any, x: tuple[Any, Any, int]) -> dict[str, Any]:
    x_cls, x_method, offset = x
    return {
        "direction": direction,
        "method": method_sig(source_method),
        "xref_class": class_name(x_cls),
        "xref_method": method_sig(x_method),
        "offset": offset,
    }


def mixed_xref_record(x: Any) -> dict[str, Any]:
    if isinstance(x, tuple):
        row: dict[str, Any] = {"tuple_len": len(x)}
        for idx, item in enumerate(x):
            if hasattr(item, "get_method") or (hasattr(item, "get_class_name") and hasattr(item, "get_descriptor")):
                row[f"item_{idx}"] = method_sig(item)
            elif hasattr(item, "name") or hasattr(item, "class_name"):
                row[f"item_{idx}"] = class_name(item)
            else:
                row[f"item_{idx}"] = item
        return row
    if hasattr(x, "get_method") or (hasattr(x, "get_class_name") and hasattr(x, "get_descriptor")):
        return {"method": method_sig(x)}
    if hasattr(x, "name") or hasattr(x, "class_name"):
        return {"class": class_name(x)}
    return {"value": str(x)}


def method_xrefs(method_analysis: Any) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"to": [], "from": [], "new_instance": [], "const_class": []}
    for x in method_analysis.get_xref_to() if hasattr(method_analysis, "get_xref_to") else []:
        out["to"].append(xref_tuple_to_record("to", method_analysis, x))
    for x in method_analysis.get_xref_from() if hasattr(method_analysis, "get_xref_from") else []:
        out["from"].append(xref_tuple_to_record("from", method_analysis, x))
    for x in method_analysis.get_xref_new_instance() if hasattr(method_analysis, "get_xref_new_instance") else []:
        out["new_instance"].append({"method": method_sig(method_analysis), "xref": mixed_xref_record(x)})
    for x in method_analysis.get_xref_const_class() if hasattr(method_analysis, "get_xref_const_class") else []:
        out["const_class"].append({"method": method_sig(method_analysis), "xref": mixed_xref_record(x)})
    for key in out:
        out[key] = sort_records(out[key])
    return out


def target_match(name: str) -> bool:
    return any(name.startswith(p) for p in TARGET_EXACT_PREFIXES) or any(s in name for s in TARGET_SUBSTRINGS)


def is_callback_name(name: str) -> bool:
    n = (name or "").lower()
    return "callback" in n or "listener" in n


def is_callback_text(text: str) -> bool:
    n = (text or "").lower()
    return "callback" in n or "listener" in n


def is_preview_dependency_name(name: str) -> bool:
    return any(s in (name or "") for s in PREVIEW_DEP_SUBSTRINGS)


def is_preview_dependency_text(text: str) -> bool:
    return any(s in (text or "") for s in PREVIEW_DEP_SUBSTRINGS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    apk_path = args.apk
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    apk, dexes, dx = AnalyzeAPK(str(apk_path))
    classes = list(dx.get_classes())
    class_by_name = {c.name: c for c in classes}
    target_classes = sorted([c for c in classes if target_match(c.name)], key=lambda c: c.name)
    target_names = {c.name for c in target_classes}

    metadata = {
        "tool": "androguard",
        "androguard_version": getattr(androguard, "__version__", "unknown"),
        "apk_path": str(apk_path),
        "apk_sha256": sha256(apk_path),
        "apk_size_bytes": apk_path.stat().st_size,
        "package": apk.get_package(),
        "version_name": apk.get_androidversion_name(),
        "version_code": apk.get_androidversion_code(),
        "dex_count": len(dexes),
        "class_count": len(classes),
        "target_class_count": len(target_classes),
        "target_prefixes": TARGET_EXACT_PREFIXES,
        "target_substrings": TARGET_SUBSTRINGS,
    }
    jdump(out / "apk_metadata.json", metadata)

    all_class_rows: list[dict[str, Any]] = []
    method_rows: list[dict[str, Any]] = []
    call_edges: list[dict[str, Any]] = []
    class_edges: list[dict[str, Any]] = []

    for c in target_classes:
        methods = sorted(list(c.get_methods()), key=lambda m: (m.name, m.descriptor))
        fields = []
        for f in c.get_fields():
            field = getattr(f, "field", f)
            fields.append({
                "name": getattr(field, "name", None),
                "descriptor": getattr(field, "descriptor", None),
                "access_flags": field.get_access_flags_string() if hasattr(field, "get_access_flags_string") else None,
                "is_external": f.is_external() if hasattr(f, "is_external") else None,
            })
        row = {
            "class": c.name,
            "is_external": c.is_external(),
            "extends": c.extends,
            "implements": sorted(list(c.implements or [])),
            "method_count": len(methods),
            "field_count": len(fields),
            "fields": sorted(fields, key=lambda x: (str(x["name"]), str(x["descriptor"]))),
            "methods": [method_sig(m) for m in methods],
            "xref_to_classes": sorted({class_name(x) for x in c.get_xref_to()}),
            "xref_from_classes": sorted({class_name(x) for x in c.get_xref_from()}),
            "xref_new_instance_classes": sort_records([mixed_xref_record(x) for x in c.get_xref_new_instance()]),
            "xref_const_classes": sort_records([mixed_xref_record(x) for x in c.get_xref_const_class()]),
        }
        all_class_rows.append(row)
        for m in methods:
            mx = method_xrefs(m)
            mrow = {"method": method_sig(m), "xrefs": mx}
            method_rows.append(mrow)
            for x in mx["to"]:
                call_edges.append({
                    "caller": x["method"],
                    "callee_class": x["xref_class"],
                    "callee": x["xref_method"],
                    "offset": x["offset"],
                    "edge_scope": "target_method_outbound",
                })
            for x in mx["from"]:
                call_edges.append({
                    "caller_class": x["xref_class"],
                    "caller": x["xref_method"],
                    "callee": x["method"],
                    "offset": x["offset"],
                    "edge_scope": "target_method_inbound",
                })
        for x in c.get_xref_to():
            class_edges.append({"source_class": c.name, "target_class": class_name(x), "edge_scope": "target_class_outbound"})
        for x in c.get_xref_from():
            class_edges.append({"source_class": class_name(x), "target_class": c.name, "edge_scope": "target_class_inbound"})

    jdump(out / "target_classes.json", sort_records(all_class_rows))
    append_jsonl(out / "target_methods.jsonl", sort_records(method_rows))
    append_jsonl(out / "target_call_graph_edges.jsonl", sort_records(call_edges))
    append_jsonl(out / "target_class_xrefs.jsonl", sort_records(class_edges))

    callback_edges: list[dict[str, Any]] = []
    callback_classes: set[str] = set()
    preview_dep_classes: set[str] = set()
    # Direct method call edges where one side mentions callback/listener in the class or
    # exact method descriptor and the other side is in the requested preview/thermal family.
    # This catches callback bean accessors, returned IStreamCallback descriptors, and
    # SurfaceHolder callback registration/removal from PreviewManagerII lifecycle code.
    for c in classes:
        for m in c.get_methods():
            src_sig = method_sig(m)
            src = src_sig["class"]
            src_text = src_sig["full_descriptor"]
            for target_cls, target_method, offset in m.get_xref_to():
                dst_sig = method_sig(target_method)
                dst = class_name(target_cls)
                dst_text = dst_sig["full_descriptor"]
                src_cb = is_callback_name(src) or is_callback_text(src_text)
                dst_cb = is_callback_name(dst) or is_callback_text(dst_text)
                src_prev = is_preview_dependency_name(src) or is_preview_dependency_text(src_text)
                dst_prev = is_preview_dependency_name(dst) or is_preview_dependency_text(dst_text)
                if (src_cb and dst_prev) or (dst_cb and src_prev):
                    callback_classes.update([src] if src_cb else [])
                    callback_classes.update([dst] if dst_cb else [])
                    preview_dep_classes.update([src] if src_prev else [])
                    preview_dep_classes.update([dst] if dst_prev else [])
                    callback_edges.append({
                        "caller": src_sig,
                        "callee": dst_sig,
                        "callee_class": dst,
                        "offset": offset,
                        "relationship": "callback_to_preview" if src_cb and dst_prev else "preview_to_callback",
                    })
    callback_edges = sort_records(callback_edges)
    append_jsonl(out / "callback_to_preview_edges.jsonl", callback_edges)
    jdump(out / "callback_to_preview_summary.json", {
        "callback_edge_count": len(callback_edges),
        "callback_classes": sorted(callback_classes),
        "preview_dependency_classes": sorted(preview_dep_classes),
    })

    # Export compact package/class inventory for requested wildcard packages and missed symbol diagnosis.
    inventory = {
        "matched_target_classes": sorted(target_names),
        "all_classes_matching_requested_names": sorted([name for name in class_by_name if target_match(name)]),
        "requested_name_hits": {needle: sorted([name for name in class_by_name if needle in name]) for needle in TARGET_SUBSTRINGS},
        "requested_prefix_hits": {prefix: sorted([name for name in class_by_name if name.startswith(prefix)]) for prefix in TARGET_EXACT_PREFIXES},
    }
    jdump(out / "target_inventory.json", inventory)

    limits = {
        "limits": [
            "This evidence is DEX/static-analysis only; it does not execute the APK or native libraries.",
            "Androguard 4.1.4 exposes exact DEX class/method descriptors and xrefs, but no reliable Java/Kotlin source decompilation was emitted here.",
            "External Android/framework/library methods and JNI/native implementations are represented as descriptors/xrefs only when referenced by DEX.",
            "Obfuscated classes such as Lg3/*, Lh3/*, and Ld3/* keep original obfuscated names; semantic names are inferred only from descriptors and call relationships.",
            "Call graph edges are direct method-reference xrefs. Reflection, dynamically loaded code, native callbacks, and runtime-dispatched interface edges can be incomplete.",
        ]
    }
    jdump(out / "decompilation_limits.json", limits)
    (out / "README.md").write_text(
        "# G007 Androguard Evidence\n\n"
        "Machine-readable extraction from the supplied official APK. Reproduce with:\n\n"
        "```bash\n"
        ".tools/androguard-venv/bin/python tools/analysis/extract_hikmicro_androguard_evidence.py "
        "--apk .omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/xapk/com.hikvision.thermalGoogle.apk "
        "--out _workspace/hikmicro-parity-20260715/g007-androguard\n"
        "```\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
