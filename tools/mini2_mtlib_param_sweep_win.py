#!/usr/bin/env python3
"""Diagnostic sweep for MTlib_OL full-frame Mini2 conversion parameters.

This does not derive a CSV fitted formula. It calls HIKMICRO's MTlib_OL.dll
for every candidate, then uses Analyzer-exported CSV only as validation.
The purpose is to identify which official MT_SetConfig fields are still
missing from the direct raw->temperature path.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import itertools
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
    encode_type1_value,
    extract_blocks,
    make_desc,
    radiometric_params_from_jpeg,
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
    out: list[float] = []
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


def type1_payload(key: int, encoded_value: int) -> bytes:
    return struct.pack("<II", int(key), int(encoded_value) & 0xFFFFFFFF)


def metric(pred: list[float], truth: list[float]) -> dict[str, float | int]:
    n = min(len(pred), len(truth))
    diffs = [pred[i] - truth[i] for i in range(n) if math.isfinite(pred[i])]
    if not diffs:
        return {"count": 0}
    rd = [round(pred[i], 1) - truth[i] for i in range(n) if math.isfinite(pred[i])]
    return {
        "count": len(diffs),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "rounded_0p1_match_rate": sum(1 for d in rd if abs(d) < 1e-9) / len(rd),
        "rounded_0p1_mae": sum(abs(d) for d in rd) / len(rd),
    }


class MTLib:
    def __init__(self, dll_dir: Path):
        add_dll_dir(dll_dir)
        self.dll = ctypes.WinDLL(str(dll_dir / "MTlib_OL.dll"))
        self.MT_GetMemSize = self.dll.MT_GetMemSize
        self.MT_GetMemSize.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.MT_GetMemSize.restype = ctypes.c_int
        self.MT_Create = self.dll.MT_Create
        self.MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.MT_Create.restype = ctypes.c_int
        self.MT_SetConfig = self.dll.MT_SetConfig
        self.MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.MT_SetConfig.restype = ctypes.c_int
        self.MT_SubFunction = self.dll.MT_SubFunction
        self.MT_SubFunction.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self.MT_SubFunction.restype = ctypes.c_int

    def convert(self, jpeg: Path, key_values: list[tuple[int, int]]) -> tuple[list[float], dict[str, object]]:
        blocks = extract_blocks(jpeg)
        raw = raw_path_for(jpeg).read_bytes()
        raw_frame = raw + blocks["tag1"]
        params = ctypes.create_string_buffer(0x20)
        struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
        backing, desc, desc_info = make_desc()
        self.MT_GetMemSize(ctypes.byref(params), ctypes.byref(desc))
        backing, desc, desc_info = make_desc()
        handle = ctypes.c_void_p()
        cret = self.MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
        if cret != 0 or not handle.value:
            raise RuntimeError(f"MT_Create failed ret={cret} handle={handle.value}")
        keep = [backing, desc, params]
        calib_param_type = struct.unpack_from("<I", blocks["tag519"], 8)[0]
        configs: list[tuple[int, bytes, str]] = [
            (6, blocks["tag519"], "tag519"),
            (1, type1_payload(15, calib_param_type), f"key15={calib_param_type}"),
        ]
        for key, value in key_values:
            configs.append((1, type1_payload(key, value), f"key{key}={value}"))
        configs.append((7, raw_frame, "raw+tag1"))
        set_ret = []
        for typ, payload, label in configs:
            b = buf_from_bytes(payload)
            keep.append(b)
            set_ret.append((label, self.MT_SetConfig(handle, typ, ctypes.cast(b, ctypes.c_void_p), len(payload))))

        raw_buf = ctypes.create_string_buffer(raw, len(raw))
        tag1_buf = ctypes.create_string_buffer(blocks["tag1"], len(blocks["tag1"]))
        out_table = ctypes.create_string_buffer(0x20000)
        out_struct = ctypes.create_string_buffer(0x20)
        struct.pack_into("<QQ", out_struct, 0, 0, ctypes.addressof(out_table))
        keep += [raw_buf, tag1_buf, out_table, out_struct]
        ret1 = self.MT_SubFunction(
            handle,
            1,
            ctypes.cast(raw_buf, ctypes.c_void_p),
            len(raw),
            ctypes.cast(out_struct, ctypes.c_void_p),
            0,
            None,
        )
        in2 = ctypes.create_string_buffer(0xD0)
        struct.pack_into("<Q", in2, 0, ctypes.addressof(raw_buf))
        struct.pack_into("<Q", in2, 8, ctypes.addressof(tag1_buf))
        struct.pack_into("<Q", in2, 0x10, ctypes.addressof(out_table))
        out2 = ctypes.create_string_buffer(PIXELS * 4)
        keep += [in2, out2]
        ret2 = self.MT_SubFunction(
            handle,
            2,
            ctypes.cast(in2, ctypes.c_void_p),
            len(in2),
            ctypes.cast(out2, ctypes.c_void_p),
            PIXELS * 4,
            None,
        )
        vals = list(struct.unpack("<" + "f" * PIXELS, out2.raw[: PIXELS * 4]))
        return vals, {"ret1": ret1, "ret2": ret2, "set_ret": set_ret, "desc_info": desc_info}


def encoded_grid(key: int, values: list[float]) -> list[tuple[float, int]]:
    return [(v, encode_type1_value(key, v)) for v in values]


def frange(start: float, stop: float, step: float) -> list[float]:
    out = []
    x = start
    while x <= stop + 1e-9:
        out.append(round(x, 6))
        x += step
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, action="append", required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_param_sweep"))
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--mode", choices=["coarse", "flags"], default="coarse")
    args = ap.parse_args(argv)

    mt = MTLib(args.dll_dir)
    args.out.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"mode": args.mode, "images": []}

    for jpeg in args.jpeg:
        jpeg = jpeg.resolve()
        truth = csv_flat(jpeg.with_name(jpeg.stem + "_이미지.csv"))
        params = radiometric_params_from_jpeg(jpeg)
        rows: list[dict[str, object]] = []

        candidates: list[tuple[str, list[tuple[int, int]]]] = []
        candidates.append(("default", []))
        candidates.append(
            (
                "radiometric_basic",
                [
                    (5, encode_type1_value(5, params["atmospheric_c"])),
                    (6, encode_type1_value(6, params["humidity_percent"])),
                    (19, encode_type1_value(19, params["emissivity"])),
                    (20, encode_type1_value(20, params["distance_m"])),
                ],
            )
        )

        if args.mode == "coarse":
            key5_vals = sorted(set([20.0, 23.3798828125, 25.0, 27.0, 30.0, 31.47998046875] + frange(20, 35, 1)))
            key34_vals = sorted(set([20.0, 25.0, 30.0, 31.0, 31.5, 32.0, 35.0] + frange(20, 36, 2)))
            emiss_vals = [0.97, float(params["emissivity"])]
            for k5, k34, emiss in itertools.product(key5_vals, key34_vals, emiss_vals):
                candidates.append(
                    (
                        f"k5={k5:g},k34={k34:g},e={emiss:g}",
                        [
                            (5, encode_type1_value(5, k5)),
                            (34, encode_type1_value(34, k34)),
                            (19, encode_type1_value(19, emiss)),
                        ],
                    )
                )
        else:
            # Flag-oriented smoke tests around the feature gates visible in MTlib disassembly.
            flag_sets = [
                [(55, 1)],  # handle+0x1a3
                [(58, 1)],  # handle+0x1a6
                [(61, 1)],  # handle+0x380
                [(63, 1)],  # handle+0x440
                [(78, 1)],  # handle+0x4d2
                [(80, 1)],  # handle+0x4d8
                [(55, 1), (58, 1), (61, 1)],
                [(55, 1), (63, 1), (78, 1)],
            ]
            for fs in flag_sets:
                candidates.append((f"flags:{fs}", fs))

        for label, kv in candidates:
            try:
                pred, meta = mt.convert(jpeg, kv)
                m = metric(pred, truth)
                rows.append({"label": label, "key_values": kv, "metric": m, "meta": meta})
            except Exception as exc:
                rows.append({"label": label, "key_values": kv, "error": repr(exc)})

        ranked = sorted(
            [r for r in rows if "metric" in r and r["metric"].get("count", 0)],
            key=lambda r: (r["metric"]["rounded_0p1_mae"], r["metric"]["mae"], abs(r["metric"]["bias"])),
        )
        image_report = {
            "jpeg": str(jpeg),
            "radiometric_params": params,
            "top": ranked[: args.top],
            "all_count": len(rows),
        }
        report["images"].append(image_report)
        op = args.out / f"{jpeg.stem}_{args.mode}_sweep.json"
        op.write_text(json.dumps(image_report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"jpeg": str(jpeg), "top": ranked[: min(args.top, 5)], "saved": str(op)}, ensure_ascii=False, indent=2))

    (args.out / f"summary_{args.mode}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
