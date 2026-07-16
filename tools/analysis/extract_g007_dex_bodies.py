#!/usr/bin/env python3
"""Extract G007 targeted DAD source and DEX instruction bodies from the official APK."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from loguru import logger
logger.remove()

from androguard.misc import AnalyzeAPK  # noqa: E402

PREFIXES = (
    "Lg3/",
    "Lh3/",
    "Ld3/",
    "Li3/",
    "Lk3/",
    "Ll2/",
    "LK2/",
    "LO2/",
    "Lz2/",
    "Lz3/",
    "LU4/",
    "Lcom/hik/viewer/manager/PreviewManagerII",
    "Lcom/hik/f2module/IFR_INFO",
    "Lcom/hik/f1module/hcusbcamerasdk/jna/HCUSBCameraSDKBy",
)
EXACT = {
    "Lf3/g;",
    "Lf3/h;",
    "Lf3/j;",
    "Lcom/hik/viewercommon/data/bean/PreviewInfoDataBean;",
    "Lcom/hik/viewercommon/data/bean/PreviewStreamInfo;",
    "Lcom/hik/viewercommon/data/bean/TempCallbackBean;",
    "Lcom/hik/viewercommon/data/bean/OsdBgCallbackBean;",
    "LL5/d;",
    "Lp2/a;",
    "Lcom/louisgeek/gyuv/GYUV;",
}


def wanted(name: str) -> bool:
    return name in EXACT or any(name.startswith(prefix) for prefix in PREFIXES)


def safe_name(descriptor: str, suffix: str) -> str:
    return descriptor.strip("L;").replace("/", "_").replace("$", "__") + suffix


def method_row(cls: str, method: Any) -> dict[str, Any]:
    code = method.get_code()
    row: dict[str, Any] = {
        "class": cls,
        "name": method.get_name(),
        "descriptor": method.get_descriptor(),
        "access": method.get_access_flags_string(),
        "instructions": [],
    }
    if code is None:
        return row
    row.update({
        "registers_size": code.registers_size,
        "ins_size": code.ins_size,
        "outs_size": code.outs_size,
    })
    offset = 0
    for ins in code.get_bc().get_instructions():
        row["instructions"].append({
            "offset": offset,
            "name": ins.get_name(),
            "output": ins.get_output(),
            "length": ins.get_length(),
        })
        offset += ins.get_length()
    return row


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--apk", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    _, dexes, _ = AnalyzeAPK(str(args.apk))
    inventory: list[dict[str, Any]] = []
    all_methods: list[dict[str, Any]] = []
    for vm in dexes:
        for c in vm.get_classes():
            cls = c.get_name()
            if not wanted(cls):
                continue
            methods = list(c.get_methods())
            fields = list(c.get_fields())
            inventory.append({
                "class": cls,
                "superclass": c.get_superclassname(),
                "interfaces": list(c.get_interfaces()),
                "field_count": len(fields),
                "method_count": len(methods),
                "fields": [f"{f.get_access_flags_string()} {f.get_name()} {f.get_descriptor()}" for f in fields],
                "methods": [f"{m.get_access_flags_string()} {m.get_name()}{m.get_descriptor()}" for m in methods],
            })
            try:
                source = c.get_source()
            except Exception as e:  # pragma: no cover
                source = f"// DAD_SOURCE_ERROR: {type(e).__name__}: {e}\n"
            (args.out / safe_name(cls, ".java")).write_text(source, encoding="utf-8")
            lines = []
            for m in methods:
                row = method_row(cls, m)
                all_methods.append(row)
                lines.append(f"### {row['access']} {row['name']}{row['descriptor']} regs={row.get('registers_size')} ins={row.get('ins_size')} outs={row.get('outs_size')}")
                for ins in row["instructions"]:
                    lines.append(f"{ins['offset']:04x}: {ins['name']:<24} {ins['output']}")
                lines.append("")
            (args.out / safe_name(cls, ".dex.txt")).write_text("\n".join(lines), encoding="utf-8")
    inventory.sort(key=lambda r: r["class"])
    all_methods.sort(key=lambda r: (r["class"], r["name"], r["descriptor"]))
    (args.out / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.out / "methods.jsonl").open("w", encoding="utf-8") as f:
        for row in all_methods:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"classes={len(inventory)} methods={len(all_methods)} out={args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
