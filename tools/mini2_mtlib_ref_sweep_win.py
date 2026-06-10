#!/usr/bin/env python3
"""Diagnostic reflected-temperature sweep for MTlib_OL.

This is not a final conversion formula and does not build a lookup table. It
uses CSV only to identify which non-CSV metadata field is likely being used as
the Analyzer's reflected/ambient parameter.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import json
import math
import os
import statistics
import struct
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mini2_mtlib_api_probe_win import (  # noqa:E402
    DLL_DIR_DEFAULT,
    HEIGHT,
    POINT_SIZE,
    WIDTH,
    add_dll_dir,
    buf_from_bytes,
    csv_matrix,
    extract_blocks,
    raw_path_for,
    make_desc,
    tag1_internal_reflected_c,
)


PIXELS = WIDTH * HEIGHT


def setup(dll, jpeg: Path):
    blocks = extract_blocks(jpeg)
    raw = raw_path_for(jpeg).read_bytes()
    raw_u16 = list(struct.unpack("<" + "H" * PIXELS, raw))
    params = ctypes.create_string_buffer(0x20)
    struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
    backing, desc, _ = make_desc()
    handle = ctypes.c_void_p()
    ret = dll.MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
    if ret != 0 or not handle.value:
        raise RuntimeError(f"MT_Create failed {ret}")
    keep = [backing, desc, params]
    raw_frame = raw + blocks["tag1"]
    for typ, data in [
        (6, blocks["tag519"]),
        (1, struct.pack("<II", 15, struct.unpack_from("<I", blocks["tag519"], 8)[0])),
        (7, raw_frame),
    ]:
        buf = buf_from_bytes(data)
        keep.append(buf)
        sret = dll.MT_SetConfig(handle, typ, ctypes.cast(buf, ctypes.c_void_p), len(data))
        if sret != 0:
            raise RuntimeError(f"MT_SetConfig {typ} failed {sret}")
    return handle, keep, blocks, raw_u16


def mt_lookup(dll, handle, grays: list[int], reflected_c: float, emissivity: float = 0.97, distance_m: float = 1.0):
    out = {}
    unique = sorted(set(grays))
    # Batch 4 matches the conservative earlier probe.
    for start in range(0, len(unique), 4):
        sub = unique[start : start + 4]
        pts = ctypes.create_string_buffer(len(sub) * POINT_SIZE)
        for j, gray in enumerate(sub):
            off = j * POINT_SIZE
            struct.pack_into("<i", pts, off + 0x04, int(gray))
            struct.pack_into("<f", pts, off + 0x14, float(emissivity))
            struct.pack_into("<f", pts, off + 0x18, float(reflected_c))
            struct.pack_into("<f", pts, off + 0x1C, float(distance_m))
        ret = dll.MT_Process(handle, 0, ctypes.cast(pts, ctypes.c_void_p), len(sub))
        if ret != 0:
            raise RuntimeError(f"MT_Process failed {ret} at ref {reflected_c}")
        for j, gray in enumerate(sub):
            out[gray] = struct.unpack_from("<f", pts.raw, j * POINT_SIZE + 0x10)[0]
    return out


def score(raw_u16: list[int], csv_flat: list[float], lookup: dict[int, float], indices: list[int] | None = None):
    if indices is None:
        indices = list(range(len(raw_u16)))
    diffs = [lookup[raw_u16[i]] - csv_flat[i] for i in indices]
    rd = [round(lookup[raw_u16[i]], 1) - csv_flat[i] for i in indices]
    return {
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "match": sum(1 for d in rd if abs(d) < 1e-9) / len(rd),
        "gt05": sum(1 for d in diffs if abs(d) > 0.05),
        "gt10": sum(1 for d in diffs if abs(d) > 0.10),
    }


def tag1_candidates(block: bytes) -> dict[str, float]:
    vals = struct.unpack("<512H", block)
    out = {
        "avg_row0_0_1_20_25_div50": tag1_internal_reflected_c(block),
        "row0_0_div50": vals[0] / 50.0,
        "row0_1_div50": vals[1] / 50.0,
        "row0_20_div50": vals[20] / 50.0,
        "row0_25_div50": vals[25] / 50.0,
        "row1_8_div1000": vals[256 + 8] / 1000.0,
        "row1_0_div1000": vals[256] / 1000.0,
        "row1_1_div1000": vals[257] / 1000.0,
    }
    # Also include all single tag1 words in plausible Celsius scales.
    for i in range(256):
        for row, base, scale in [("row0", 0, 50.0), ("row1", 256, 1000.0)]:
            val = vals[base + i] / scale
            if -20 <= val <= 80:
                out[f"{row}_{i}_div{int(scale)}"] = val
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--images", nargs="*", default=[f"IR_0000{i}.jpeg" for i in range(1, 6)])
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_ref_sweep"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MTlib_OL.dll"))
    dll.MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    dll.MT_Create.restype = ctypes.c_int
    dll.MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    dll.MT_SetConfig.restype = ctypes.c_int
    dll.MT_Process.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    dll.MT_Process.restype = ctypes.c_int

    args.out.mkdir(parents=True, exist_ok=True)
    report = {"images": []}
    for img in args.images:
        jpeg = Path(img)
        handle, keep, blocks, raw_u16 = setup(dll, jpeg)
        ref_flat = [v for row in csv_matrix(jpeg.with_name(jpeg.stem + "_이미지.csv")) for v in row]

        # 1) non-CSV metadata candidates
        candidates = []
        sample_idx = list(range(0, len(raw_u16), 64))
        sample_raw = [raw_u16[i] for i in sample_idx]
        for name, refc in tag1_candidates(blocks["tag1"]).items():
            lookup = mt_lookup(dll, handle, sample_raw, refc)
            candidates.append({"kind": "tag1_sample64", "name": name, "reflected_c": refc, **score(raw_u16, ref_flat, lookup, sample_idx)})
        candidates.sort(key=lambda r: (-r["match"], r["mae"], r["max_abs"]))
        # Full-score only the strongest metadata candidates.
        candidates_full = []
        seen_ref = set()
        for c in candidates[:20]:
            key = round(c["reflected_c"], 6)
            if key in seen_ref:
                continue
            seen_ref.add(key)
            lookup = mt_lookup(dll, handle, raw_u16, c["reflected_c"])
            candidates_full.append({**c, "kind": "tag1_full_top", **score(raw_u16, ref_flat, lookup)})
        candidates_full.sort(key=lambda r: (-r["match"], r["mae"], r["max_abs"]))

        # 2) continuous diagnostic sweep, for locating which metadata value to inspect.
        grid = []
        for refc in [x / 100.0 for x in range(2000, 4001, 5)]:
            lookup = mt_lookup(dll, handle, sample_raw, refc)
            grid.append({"kind": "grid_sample64", "reflected_c": refc, **score(raw_u16, ref_flat, lookup, sample_idx)})
        grid.sort(key=lambda r: (-r["match"], r["mae"], r["max_abs"]))
        grid_full = []
        seen_ref = set()
        for c in grid[:20]:
            key = round(c["reflected_c"], 6)
            if key in seen_ref:
                continue
            seen_ref.add(key)
            lookup = mt_lookup(dll, handle, raw_u16, c["reflected_c"])
            grid_full.append({**c, "kind": "grid_full_top", **score(raw_u16, ref_flat, lookup)})
        grid_full.sort(key=lambda r: (-r["match"], r["mae"], r["max_abs"]))

        rec = {
            "image": jpeg.stem,
            "tag1_sample_top20": candidates[:20],
            "tag1_full_top20": candidates_full,
            "grid_sample_top20": grid[:20],
            "grid_full_top20": grid_full,
        }
        report["images"].append(rec)
        print(json.dumps({
            "image": jpeg.stem,
            "tag1_best_full": candidates_full[0] if candidates_full else None,
            "grid_best_full": grid_full[0] if grid_full else None,
        }, ensure_ascii=False), flush=True)
    out = args.out / "ref_sweep.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("saved", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
