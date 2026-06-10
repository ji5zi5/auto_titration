#!/usr/bin/env python3
"""Probe MTlib_OL MT_SubFunction full-frame conversion path.

The earlier MT_Process probe converts isolated gray values. This script tests
the Analyzer DLL's full-frame API (MT_SubFunction case 2), which can use the
handle's generated gray->temperature tables and raw-frame metadata. No CSV
fitting is performed; CSV is used only as a validation target after the DLL
returns a matrix.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import json
import math
import os
import struct
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mini2_mtlib_api_probe_win import (  # noqa: E402
    DLL_DIR_DEFAULT,
    HEIGHT,
    WIDTH,
    add_dll_dir,
    buf_from_bytes,
    bytes_at,
    extract_blocks,
    inspect_handle,
    make_desc,
    raw_path_for,
    read_f32,
    read_i32,
    read_ptr,
    tag1_internal_reflected_c,
)


PIXELS = WIDTH * HEIGHT


def csv_matrix(path: Path) -> list[float]:
    text = None
    for enc in ["utf-8-sig", "cp949", "euc-kr", "latin1"]:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise RuntimeError(f"could not decode {path}")
    vals: list[float] = []
    for row in csv.reader(text.splitlines()):
        nums = []
        for cell in row:
            try:
                nums.append(float(cell.strip()))
            except Exception:
                pass
        if len(nums) >= WIDTH:
            xs = nums[-WIDTH:]
            if max(xs) <= 150:
                vals.extend(xs)
    return vals


def type1_payload(key: int, encoded_value: int) -> bytes:
    return struct.pack("<II", int(key), int(encoded_value) & 0xFFFFFFFF)


def ptr_summary(addr: int, n: int = 16) -> dict[str, object]:
    if not addr:
        return {"addr": None}
    raw = bytes_at(addr, min(n * 4, 128))
    probes: dict[str, object] = {}
    for idx in [0, 1, 16, 100, 256, 1024, 4096, 8000, 8192, 10000, 12000, 16383]:
        try:
            probes[str(idx)] = {
                "u16": struct.unpack_from("<H", bytes_at(addr + idx * 2, 2), 0)[0],
                "f32": struct.unpack_from("<f", bytes_at(addr + idx * 4, 4), 0)[0],
            }
        except Exception as exc:
            probes[str(idx)] = {"error": repr(exc)}
    return {
        "addr": hex(addr),
        "u16_first": [struct.unpack_from("<H", raw, i)[0] for i in range(0, min(len(raw), 32), 2)],
        "i32_first": [struct.unpack_from("<i", raw, i)[0] for i in range(0, min(len(raw), 64), 4)],
        "f32_first": [struct.unpack_from("<f", raw, i)[0] for i in range(0, min(len(raw), 64), 4)],
        "index_probes": probes,
    }


def metrics(temps: list[float], ref: list[float]) -> dict[str, object]:
    n = min(len(temps), len(ref))
    finite = [i for i in range(n) if math.isfinite(temps[i])]
    diffs = [temps[i] - ref[i] for i in finite]
    rd = [round(temps[i], 1) - ref[i] for i in finite]
    worst = sorted(finite, key=lambda i: abs(temps[i] - ref[i]), reverse=True)[:12]
    return {
        "count": len(finite),
        "temp_min": min(temps[i] for i in finite),
        "temp_max": max(temps[i] for i in finite),
        "temp_mean": sum(temps[i] for i in finite) / len(finite),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "rounded_0p1_match_rate": sum(1 for d in rd if abs(d) < 1e-6) / len(rd),
        "rounded_0p1_mae": sum(abs(d) for d in rd) / len(rd),
        "count_abs_gt_0p05": sum(1 for d in diffs if abs(d) > 0.05),
        "count_abs_gt_0p10": sum(1 for d in diffs if abs(d) > 0.10),
        "sample_pairs": [[i, temps[i], ref[i], temps[i] - ref[i]] for i in [0, WIDTH // 2, PIXELS // 2 + WIDTH // 2, PIXELS - 1]],
        "worst_pairs": [[i, i // WIDTH, i % WIDTH, temps[i], ref[i], temps[i] - ref[i]] for i in worst],
    }


def setup_handle(dll, jpeg: Path):
    MT_GetMemSize = dll.MT_GetMemSize
    MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    MT_GetMemSize.restype = ctypes.c_int
    MT_Create = dll.MT_Create
    MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    MT_Create.restype = ctypes.c_int
    MT_SetConfig = dll.MT_SetConfig
    MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    MT_SetConfig.restype = ctypes.c_int

    blocks = extract_blocks(jpeg)
    raw = raw_path_for(jpeg).read_bytes()
    raw_frame = raw + blocks["tag1"]
    params = ctypes.create_string_buffer(0x20)
    struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
    backing, desc, _desc_info = make_desc()
    _ = MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
    backing, desc, desc_info = make_desc()
    handle = ctypes.c_void_p()
    create_ret = MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
    h = int(handle.value or 0)
    if create_ret != 0 or not h:
        raise RuntimeError(f"MT_Create failed: {create_ret}")

    keep = [backing, desc, params]
    setconfig = []
    calib_param_type = struct.unpack_from("<I", blocks["tag519"], 0x08)[0]
    for typ, data, name in [
        (6, blocks["tag519"], "APP2 tag519 calibration"),
        (1, type1_payload(15, calib_param_type), f"key15 calibration-param-type={calib_param_type}"),
        (7, raw_frame, "raw 256x192 u16 + APP3 tag1 addline"),
    ]:
        buf = buf_from_bytes(data)
        ret = MT_SetConfig(handle, typ, ctypes.cast(buf, ctypes.c_void_p), len(data))
        keep.append(buf)
        setconfig.append({"type": typ, "name": name, "ret": ret})
    return handle, h, keep, blocks, raw, setconfig, desc_info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, default=Path("data/fixtures/mini2/IR_00001.jpeg"))
    ap.add_argument("--table", choices=["auto", "0x148", "0x150", "0x1a8", "0x1b0", "0x1b8", "0x180", "0x188"], default="auto")
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_subfunction_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MTlib_OL.dll"))
    MT_SubFunction = dll.MT_SubFunction
    MT_SubFunction.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
    ]
    MT_SubFunction.restype = ctypes.c_int

    handle, h, keep, blocks, raw, setconfig, desc_info = setup_handle(dll, args.jpeg)
    raw_buf = ctypes.create_string_buffer(raw, len(raw))
    keep.append(raw_buf)

    ptr_offsets = [0x148, 0x150, 0x1A8, 0x1B0, 0x1B8, 0x180, 0x188]
    ptrs = {hex(o): read_ptr(h, o) for o in ptr_offsets}
    table_offsets = [0x150, 0x148, 0x1A8, 0x1B0, 0x1B8, 0x180, 0x188] if args.table == "auto" else [int(args.table, 16)]

    ref_path = args.jpeg.with_name(f"{args.jpeg.stem}_이미지.csv")
    ref = csv_matrix(ref_path) if ref_path.exists() else []
    rep: dict[str, object] = {
        "jpeg": str(args.jpeg),
        "setconfig": setconfig,
        "desc_info": desc_info,
        "tag1_internal_reflected_c": tag1_internal_reflected_c(blocks["tag1"]),
        "handle": inspect_handle(h),
        "handle_scalar_probe": {
            "i32_0x40": read_i32(h, 0x40),
            "i32_0x44": read_i32(h, 0x44),
            "i32_0x48": read_i32(h, 0x48),
            "i32_0x4c": read_i32(h, 0x4C),
            "f32_0x108": read_f32(h, 0x108),
            "f32_0x110": read_f32(h, 0x110),
            "f32_0x118": read_f32(h, 0x118),
        },
        "ptr_summaries": {hex(o): ptr_summary(ptrs[hex(o)]) for o in ptr_offsets},
        "trials": [],
    }

    for off in table_offsets:
        table_ptr = read_ptr(h, off)
        if not table_ptr:
            rep["trials"].append({"table_offset": hex(off), "skipped": "null table pointer"})
            continue
        input_struct = ctypes.create_string_buffer(0x18)
        struct.pack_into(
            "<QQQ",
            input_struct,
            0,
            ctypes.addressof(raw_buf),
            0,
            table_ptr,
        )
        out = ctypes.create_string_buffer(PIXELS * 4)
        ret = MT_SubFunction(
            handle,
            2,
            ctypes.byref(input_struct),
            0x18,
            ctypes.byref(out),
            PIXELS * 4,
            0,
        )
        temps = [struct.unpack_from("<f", out.raw, i * 4)[0] for i in range(PIXELS)]
        trial = {
            "table_offset": hex(off),
            "table_ptr": hex(table_ptr),
            "ret": ret,
            "temps_first16": temps[:16],
            "temps_stats": {
                "min": min(temps),
                "max": max(temps),
                "mean": sum(temps) / len(temps),
            },
        }
        if ref:
            trial["validation_vs_csv"] = metrics(temps, ref)
        rep["trials"].append(trial)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{args.jpeg.stem}_mtlib_subfunction_probe.json"
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": str(args.jpeg),
        "out": str(out_path),
        "trials": [
            {
                "table_offset": t.get("table_offset"),
                "ret": t.get("ret"),
                "stats": t.get("temps_stats"),
                "validation": t.get("validation_vs_csv"),
            }
            for t in rep["trials"]
        ],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:20000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
