#!/usr/bin/env python3
"""Sweep MT_Process point-conversion parameters against exported matrices.

The conversion itself is always HIKMICRO MTlib_OL.dll. CSV is used only as a
rounded validation target to identify which non-CSV measurement parameters the
Analyzer appears to use.
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
from collections import Counter
from pathlib import Path

THIS = Path(__file__).resolve()
TOOLS = THIS.parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from mini2_mtlib_api_probe_win import (  # noqa: E402
    DLL_DIR_DEFAULT,
    HEIGHT,
    POINT_SIZE,
    WIDTH,
    add_dll_dir,
    buf_from_bytes,
    encode_type1_value,
    extract_blocks,
    get_sdmp_block,
    make_desc,
    radiometric_params_from_jpeg,
    radiometric_type1_pairs,
    raw_path_for,
    tag1_internal_reflected_c,
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


def type1_payload(key: int, encoded_value: int) -> bytes:
    return struct.pack("<II", int(key), int(encoded_value) & 0xFFFFFFFF)


def frange(start: float, stop: float, step: float) -> list[float]:
    out = []
    x = start
    while x <= stop + 1e-12:
        out.append(round(x, 8))
        x += step
    return out


class ProcessConverter:
    def __init__(self, dll_dir: Path, jpeg: Path, radiometric_profile: str, process_type: int, set_tag50_type12: bool = False):
        add_dll_dir(dll_dir)
        self.dll = ctypes.WinDLL(str(dll_dir / "MTlib_OL.dll"))
        self.dll.MT_Create.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        self.dll.MT_Create.restype = ctypes.c_int
        self.dll.MT_SetConfig.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.dll.MT_SetConfig.restype = ctypes.c_int
        self.dll.MT_Process.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        self.dll.MT_Process.restype = ctypes.c_int
        self.jpeg = jpeg
        self.blocks = extract_blocks(jpeg)
        self.raw = list(struct.unpack("<" + "H" * PIXELS, raw_path_for(jpeg).read_bytes()))
        self.truth = csv_flat(jpeg.with_name(jpeg.stem + "_이미지.csv"))
        self.params = radiometric_params_from_jpeg(jpeg)
        self.radiometric_profile = radiometric_profile
        self.process_type = process_type
        self.set_tag50_type12 = set_tag50_type12
        self.handle, self.keep = self._setup()
        # CSV is a function of raw gray for these Mini2 exports, so score by
        # unique gray with pixel-count weights.
        truth_by_gray: dict[int, float] = {}
        counts = Counter(self.raw)
        for g, t in zip(self.raw, self.truth):
            old = truth_by_gray.get(g)
            if old is not None and old != t:
                raise RuntimeError(f"raw gray {g} maps to both {old} and {t}")
            truth_by_gray[g] = t
        self.unique_grays = sorted(truth_by_gray)
        self.truth_by_gray = truth_by_gray
        self.count_by_gray = counts

    def _setup(self):
        params = ctypes.create_string_buffer(0x20)
        struct.pack_into("<IIII", params, 0, WIDTH, HEIGHT, 1, 1)
        backing, desc, _ = make_desc()
        handle = ctypes.c_void_p()
        ret = self.dll.MT_Create(ctypes.byref(params), ctypes.byref(desc), ctypes.byref(handle))
        if ret != 0 or not handle.value:
            raise RuntimeError(f"MT_Create failed {ret}")
        keep = [backing, desc, params]
        raw_bytes = raw_path_for(self.jpeg).read_bytes()
        raw_frame = raw_bytes + self.blocks["tag1"]
        calib_param_type = struct.unpack_from("<I", self.blocks["tag519"], 8)[0]
        configs: list[tuple[int, bytes, str]] = [
            (6, self.blocks["tag519"], "tag519"),
            (1, type1_payload(15, calib_param_type), f"key15={calib_param_type}"),
        ]
        for key, value, label in radiometric_type1_pairs(self.params, self.radiometric_profile):
            configs.append((1, type1_payload(key, encode_type1_value(key, value)), label))
        if self.set_tag50_type12:
            # APP3 SDMP tag50 is exactly 256 uint32 (1024 bytes).  MT_SetConfig
            # type=12 accepts width*4 bytes and calls an internal row-vector
            # setter, so this is a plausible per-column correction/config table
            # used by Analyzer but absent from the earlier approximate path.
            configs.append((12, get_sdmp_block(self.jpeg, 0xE3, 50), "APP3 tag50 -> MT_SetConfig type12"))
        configs.append((7, raw_frame, "raw+tag1"))
        for typ, payload, _ in configs:
            b = buf_from_bytes(payload)
            keep.append(b)
            sret = self.dll.MT_SetConfig(handle, typ, ctypes.cast(b, ctypes.c_void_p), len(payload))
            if sret != 0:
                raise RuntimeError(f"MT_SetConfig type={typ} failed {sret}")
        return handle, keep

    def lookup(self, emissivity: float, reflected_c: float, distance_m: float, gray_delta: int, batch: int) -> dict[int, float]:
        out: dict[int, float] = {}
        grays = self.unique_grays
        for start in range(0, len(grays), batch):
            sub = grays[start : start + batch]
            pts = ctypes.create_string_buffer(len(sub) * POINT_SIZE)
            for j, gray in enumerate(sub):
                off = j * POINT_SIZE
                adjusted = max(0, min(65535, int(gray) + int(gray_delta)))
                struct.pack_into("<i", pts, off + 0x04, adjusted)
                struct.pack_into("<f", pts, off + 0x14, float(emissivity))
                struct.pack_into("<f", pts, off + 0x18, float(reflected_c))
                struct.pack_into("<f", pts, off + 0x1C, float(distance_m))
            ret = self.dll.MT_Process(self.handle, self.process_type, ctypes.cast(pts, ctypes.c_void_p), len(sub))
            if ret != 0:
                raise RuntimeError(f"MT_Process failed {ret}")
            for j, gray in enumerate(sub):
                out[gray] = struct.unpack_from("<f", pts.raw, j * POINT_SIZE + 0x10)[0]
        return out

    def score(self, lookup: dict[int, float]) -> dict[str, float | int]:
        total = sum(self.count_by_gray.values())
        abs_sum = 0.0
        diff_sum = 0.0
        round_abs_sum = 0.0
        max_abs = 0.0
        match = 0
        match_half_up = 0
        match_floor = 0
        match_ceil = 0
        gt05 = 0
        gt10 = 0
        for g, pred in lookup.items():
            truth = self.truth_by_gray[g]
            n = self.count_by_gray[g]
            diff = pred - truth
            ad = abs(diff)
            rd = round(pred, 1) - truth
            half_up = math.floor(pred * 10.0 + 0.5) / 10.0
            floored = math.floor(pred * 10.0) / 10.0
            ceiled = math.ceil(pred * 10.0) / 10.0
            abs_sum += ad * n
            diff_sum += diff * n
            round_abs_sum += abs(rd) * n
            max_abs = max(max_abs, ad)
            if abs(rd) < 1e-9:
                match += n
            if abs(half_up - truth) < 1e-9:
                match_half_up += n
            if abs(floored - truth) < 1e-9:
                match_floor += n
            if abs(ceiled - truth) < 1e-9:
                match_ceil += n
            if ad > 0.05:
                gt05 += n
            if ad > 0.10:
                gt10 += n
        return {
            "count": total,
            "mae": abs_sum / total,
            "bias": diff_sum / total,
            "max_abs": max_abs,
            "rounded_0p1_mae": round_abs_sum / total,
            "rounded_0p1_match_rate": match / total,
            "half_up_0p1_match_rate": match_half_up / total,
            "floor_0p1_match_rate": match_floor / total,
            "ceil_0p1_match_rate": match_ceil / total,
            "gt0p05": gt05,
            "gt0p10": gt10,
        }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_mtlib_process_param_sweep"))
    ap.add_argument("--radiometric-profile", choices=["none", "basic", "with_window", "with_expert", "all_known"], default="none")
    ap.add_argument("--process-type", type=int, default=0)
    ap.add_argument("--mode", choices=["coarse", "refine"], default="coarse")
    ap.add_argument("--center-ref", type=float, default=None)
    ap.add_argument("--center-emiss", type=float, default=None)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--sweep-gray-delta", action="store_true")
    ap.add_argument("--set-tag50-type12", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args(argv)

    conv = ProcessConverter(args.dll_dir, args.jpeg.resolve(), args.radiometric_profile, args.process_type, args.set_tag50_type12)
    if args.mode == "coarse":
        emiss_values = sorted(set([7946 / 8192, 0.95, 0.96, 0.97, 0.98, 0.99, 1.0] + frange(0.955, 0.99, 0.005)))
        ref_values = sorted(set([tag1_internal_reflected_c(conv.blocks["tag1"]), conv.params["reflected_c"], conv.params["atmospheric_c"]] + frange(28.0, 33.0, 0.1)))
        dist_values = [conv.params["distance_m"]]
        gray_deltas = list(range(-8, 9)) if args.sweep_gray_delta else [0]
    else:
        cref = args.center_ref if args.center_ref is not None else tag1_internal_reflected_c(conv.blocks["tag1"])
        ce = args.center_emiss if args.center_emiss is not None else 7946 / 8192
        emiss_values = frange(ce - 0.01, ce + 0.01, 0.001)
        ref_values = frange(cref - 0.5, cref + 0.5, 0.02)
        dist_values = [conv.params["distance_m"]]
        gray_deltas = list(range(-3, 4)) if args.sweep_gray_delta else [0]

    rows = []
    for emissivity, reflected_c, distance_m, gray_delta in itertools.product(emiss_values, ref_values, dist_values, gray_deltas):
        try:
            lookup = conv.lookup(emissivity, reflected_c, distance_m, gray_delta, max(1, args.batch))
            rows.append(
                {
                    "emissivity": emissivity,
                    "reflected_c": reflected_c,
                    "distance_m": distance_m,
                    "gray_delta": gray_delta,
                    "metric": conv.score(lookup),
                }
            )
        except Exception as exc:
            rows.append({"emissivity": emissivity, "reflected_c": reflected_c, "distance_m": distance_m, "gray_delta": gray_delta, "error": repr(exc)})
    ranked = sorted(
        [r for r in rows if "metric" in r],
        key=lambda r: (-r["metric"]["rounded_0p1_match_rate"], r["metric"]["rounded_0p1_mae"], r["metric"]["mae"], abs(r["metric"]["bias"])),
    )
    report = {
        "jpeg": str(args.jpeg),
        "mode": args.mode,
        "radiometric_profile": args.radiometric_profile,
        "process_type": args.process_type,
        "set_tag50_type12": args.set_tag50_type12,
        "radiometric_params": conv.params,
        "tag1_internal_reflected_c": tag1_internal_reflected_c(conv.blocks["tag1"]),
        "candidate_count": len(rows),
        "top": ranked[: args.top],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    op = args.out / f"{args.jpeg.stem}_{args.radiometric_profile}_{args.mode}.json"
    op.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(op), "top": ranked[: min(args.top, 10)]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
