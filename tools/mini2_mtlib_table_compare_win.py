#!/usr/bin/env python3
"""Compare MT_SubFunction case-1 gray table with Analyzer CSV mapping.

This calls the official DLL table-generation path and only uses CSV to score
how the table bytes should be interpreted.
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
from collections import Counter
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
    encode_type1_value,
    extract_blocks,
    make_desc,
    radiometric_params_from_jpeg,
    radiometric_type1_pairs,
    raw_path_for,
)

PIXELS = WIDTH * HEIGHT


def csv_flat(path: Path) -> list[float]:
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "latin1"):
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        return []
    out = []
    for row in csv.reader(text.splitlines()):
        nums = []
        for c in row:
            try:
                nums.append(float(c.strip()))
            except Exception:
                pass
        if len(nums) >= WIDTH:
            xs = nums[-WIDTH:]
            if max(xs) <= 150:
                out.extend(xs)
    return out


def type1_payload(key: int, value: int) -> bytes:
    return struct.pack("<II", key, value & 0xFFFFFFFF)


def score(raw: list[int], truth: list[float], values: list[float]) -> dict[str, object]:
    n = min(len(raw), len(truth))
    diffs = []
    rd = []
    for i in range(n):
        p = values[raw[i]]
        if math.isfinite(p):
            diffs.append(p - truth[i])
            rd.append(round(p, 1) - truth[i])
    return {
        "count": len(diffs),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "bias": sum(diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "rounded_0p1_mae": sum(abs(d) for d in rd) / len(rd),
        "rounded_0p1_match_rate": sum(1 for d in rd if abs(d) < 1e-9) / len(rd),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--radiometric-profile", choices=["none", "basic", "with_window", "with_expert", "all_known"], default="none")
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_table_compare"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MTlib_OL.dll"))
    dll.MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    dll.MT_Create.restype = ctypes.c_int
    dll.MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    dll.MT_SetConfig.restype = ctypes.c_int
    dll.MT_SubFunction.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    dll.MT_SubFunction.restype = ctypes.c_int

    jpeg = args.jpeg.resolve()
    blocks = extract_blocks(jpeg)
    raw_bytes = raw_path_for(jpeg).read_bytes()
    raw = list(struct.unpack("<" + "H" * PIXELS, raw_bytes))
    truth = csv_flat(jpeg.with_name(jpeg.stem + "_이미지.csv"))
    params = radiometric_params_from_jpeg(jpeg)

    p = ctypes.create_string_buffer(0x20)
    struct.pack_into("<IIII", p, 0, WIDTH, HEIGHT, 1, 1)
    backing, desc, _ = make_desc()
    handle = ctypes.c_void_p()
    cret = dll.MT_Create(ctypes.byref(p), ctypes.byref(desc), ctypes.byref(handle))
    if cret != 0 or not handle.value:
        raise RuntimeError(f"MT_Create failed {cret}")
    keep = [p, backing, desc]
    configs = [
        (6, blocks["tag519"], "tag519"),
        (1, type1_payload(15, struct.unpack_from("<I", blocks["tag519"], 8)[0]), "key15"),
    ]
    for key, value, label in radiometric_type1_pairs(params, args.radiometric_profile):
        configs.append((1, type1_payload(key, encode_type1_value(key, value)), label))
    configs.append((7, raw_bytes + blocks["tag1"], "raw+tag1"))
    set_rets = []
    for typ, payload, label in configs:
        b = buf_from_bytes(payload)
        keep.append(b)
        set_rets.append((label, dll.MT_SetConfig(handle, typ, ctypes.cast(b, ctypes.c_void_p), len(payload))))

    raw_buf = ctypes.create_string_buffer(raw_bytes, len(raw_bytes))
    out_table = ctypes.create_string_buffer(0x20000)
    out_struct = ctypes.create_string_buffer(0x20)
    struct.pack_into("<QQ", out_struct, 0, 0, ctypes.addressof(out_table))
    keep += [raw_buf, out_table, out_struct]
    ret1 = dll.MT_SubFunction(handle, 1, ctypes.cast(raw_buf, ctypes.c_void_p), len(raw_bytes), ctypes.cast(out_struct, ctypes.c_void_p), 0, None)
    tb = out_table.raw
    u16 = list(struct.unpack("<" + "H" * 65536, tb[: 65536 * 2]))
    i16 = list(struct.unpack("<" + "h" * 65536, tb[: 65536 * 2]))
    f32 = list(struct.unpack("<" + "f" * 32768, tb[: 32768 * 4])) + [float("nan")] * 32768
    candidates = {
        "u16_div10": [x / 10.0 for x in u16],
        "u16_div100": [x / 100.0 for x in u16],
        "i16_div10": [x / 10.0 for x in i16],
        "i16_div100": [x / 100.0 for x in i16],
        "f32": f32,
    }
    scores = {name: score(raw, truth, vals) for name, vals in candidates.items()}
    best_name = min(scores, key=lambda k: (scores[k]["rounded_0p1_mae"], scores[k]["mae"]))
    uniq = sorted(set(raw))
    mapping_preview = [
        {
            "gray": g,
            "csv": next(t for rr, t in zip(raw, truth) if rr == g),
            "table_best": candidates[best_name][g],
            "u16": u16[g],
            "i16": i16[g],
            "f32": f32[g],
        }
        for g in uniq[:20]
    ]
    rep = {
        "jpeg": str(jpeg),
        "profile": args.radiometric_profile,
        "ret1": ret1,
        "set_rets": set_rets,
        "scores": scores,
        "best": best_name,
        "mapping_preview": mapping_preview,
        "raw_unique_count": len(uniq),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    op = args.out / f"{jpeg.stem}_{args.radiometric_profile}_table_compare.json"
    op.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(op), "best": best_name, "scores": scores}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
