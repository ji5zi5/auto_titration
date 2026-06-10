#!/usr/bin/env python3
"""Probe MicroJITA grayToTemperature by giving it a real MicroJPEG BaseImage.

This is a reverse-engineering proof attempt, not CSV fitting.

Why this exists:
- MicroJPEG can parse Mini2 R-JPEGs into a BaseImage/MicroRImageV1 object.
- MicroJITA::grayToTemperature disassembly shows it expects a small wrapper
  context whose first pointer is a BaseImage*, and caches TempAnalyzer pointers
  at +0x08/+0x10.
- MicroJITA::createFromJPEG creates a context for the JPEG but did not expose
  usable temp analysis for the tested Mini2 files. This script creates a
  registered MicroJITA context, replaces only its BaseImage* with MicroJPEG's
  parsed object, clears analyzer caches, then asks JITA to convert gray values.

It never reads Analyzer-exported CSV during conversion. CSV is optional
validation after the SDK call.
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
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT
RAW_DEFAULT_DIR = Path("data/mini2_multi_image_formula/raw")


class BareBlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


def add_dll_dir(dll_dir: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))


def get_proc(dll: ctypes.CDLL, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def make_block(data: bytes):
    buf = ctypes.create_string_buffer(data)
    block = BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)
    return buf, block


def hx(v: int | None) -> str | None:
    return hex(int(v)) if v else None


def read_ptr(addr: int, off: int = 0) -> int:
    return int.from_bytes(ctypes.string_at(addr + off, ctypes.sizeof(ctypes.c_void_p)), "little")


def write_ptr(addr: int, off: int, value: int) -> None:
    ctypes.memmove(addr + off, struct.pack("<Q", int(value) & 0xFFFFFFFFFFFFFFFF), 8)


def ptr_prefix(addr: int, n: int = 0x80) -> dict[str, object]:
    try:
        raw = ctypes.string_at(addr, n)
        return {
            "addr": hx(addr),
            "u64": [hex(int.from_bytes(raw[i:i+8], "little")) for i in range(0, min(n, 0x80), 8)],
            "u32": [int.from_bytes(raw[i:i+4], "little") for i in range(0, min(n, 0x80), 4)],
            "hex": raw[: min(n, 0x80)].hex(" "),
        }
    except Exception as exc:
        return {"addr": hx(addr), "exception": repr(exc)}


def load_csv_matrix(path: Path) -> list[float]:
    last_exc: Exception | None = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            rows = list(csv.reader(path.open("r", encoding=enc, newline="")))
            axis = next((i for i, row in enumerate(rows) if row and row[0].strip() == "축 X/Y"), None)
            if axis is None:
                continue
            vals: list[float] = []
            for row in rows[axis + 1:]:
                if not row or not row[0].strip():
                    continue
                try:
                    int(float(row[0]))
                except ValueError:
                    continue
                vals.extend(float(cell.strip()) for cell in row[1:] if cell.strip())
            if len(vals) == PIXELS:
                return vals
        except UnicodeError as exc:
            last_exc = exc
    raise ValueError(f"could not parse {path}; last={last_exc}")


def raw_path_for(jpeg: Path) -> Path:
    stem = jpeg.stem
    candidates = [
        RAW_DEFAULT_DIR / f"{stem}_lpld_raw_u16_256x192.bin",
        Path(f"data/mini2_internal_uncompress_probe/{stem.lower()}_lpld_uncompressed_raw_u16_256x192.bin"),
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"raw file not found for {jpeg}; tried {candidates}")


def load_raw_u16(path: Path) -> list[int]:
    data = path.read_bytes()
    if len(data) < PIXELS * 2:
        raise ValueError(f"raw too small: {path} {len(data)}")
    return list(struct.unpack("<" + "H" * PIXELS, data[: PIXELS * 2]))


def infer_scale(outputs: list[int], truth: list[float] | None) -> tuple[float, str, dict[str, float]]:
    candidates = [(1.0, "C_integer"), (10.0, "deci_C"), (100.0, "centi_C"), (1000.0, "milli_C"), (10000.0, "1e4_C")]
    if not truth:
        return 100.0, "default_centidegree_no_truth", {}
    limit = min(len(outputs), len(truth), 10000)
    scores = {}
    for s, name in candidates:
        pred = [outputs[i] / s for i in range(limit)]
        scores[name] = sum(abs(pred[i] - truth[i]) for i in range(limit)) / limit
    s, name = min(candidates, key=lambda it: scores[it[1]])
    return s, name, scores


def summarize(pred: list[float], truth: list[float]) -> dict[str, object]:
    err = [p - t for p, t in zip(pred, truth)]
    ae = [abs(x) for x in err]
    return {
        "count": len(pred),
        "mae": sum(ae) / len(ae),
        "rmse": math.sqrt(sum(x*x for x in err) / len(err)),
        "max_abs_error": max(ae),
        "mean_error": sum(err) / len(err),
        "within_0p05": sum(1 for x in ae if x <= 0.0500001),
        "within_0p1": sum(1 for x in ae if x <= 0.1000001),
        "rounded_0p1_match": sum(1 for p, t in zip(pred, truth) if round(p, 1) == round(t, 1)),
        "first_mismatches": [
            {"index": i, "sdk_c": pred[i], "csv_c": truth[i], "err": err[i]}
            for i in range(len(pred)) if round(pred[i], 1) != round(truth[i], 1)
        ][:30],
    }


def make_jita_context(jita: ctypes.CDLL, jpeg_block: BareBlock, mode: str) -> tuple[int, dict[str, object]]:
    create_empty = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p))(
        get_proc(jita, b"?createEmptyJPEG@MicroSDK@@YA_NAEAPEAX@Z")
    )
    create_from = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(
        get_proc(jita, b"?createFromJPEG@MicroSDK@@YA_NAEAPEAXAEBUBareBlock@1@@Z")
    )
    ctx = ctypes.c_void_p()
    if mode == "empty":
        ok = bool(create_empty(ctypes.byref(ctx)))
    elif mode == "fromjpeg":
        ok = bool(create_from(ctypes.byref(ctx), ctypes.byref(jpeg_block)))
    else:
        raise ValueError(mode)
    return int(ctx.value or 0), {"mode": mode, "create_ok": ok, "ctx": hx(ctx.value)}


def run_one(jpeg: Path, csv_path: Path | None, dll_dir: Path, mode: str, limit: int | None, force_base_type: int | None = None) -> dict[str, object]:
    add_dll_dir(dll_dir)
    microjpeg = ctypes.WinDLL(str(dll_dir / "MicroJPEG_Release_x64.dll"))
    jita = ctypes.WinDLL(str(dll_dir / "MicroJITA_Release_x64.dll"))

    mj_create_ret = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(microjpeg, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    mj_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(microjpeg, b"?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ")
    )
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(
        get_proc(jita, b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z")
    )
    get_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(jita, b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z")
    )
    get_temp_device = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(jita, b"?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z")
    )
    get_temp_measure = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(jita, b"?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z")
    )
    fmt = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(jita, b"?format@MicroSDK@@YA?AW4JPEGFormat@1@QEAX@Z")
    )
    last = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita, b"?lastError@MicroSDK@@YAIXZ"))

    jpeg_buf, block = make_block(jpeg.read_bytes())
    base_ptr = int(mj_create_ret(ctypes.byref(block)) or 0)
    if not base_ptr:
        raise RuntimeError("MicroJPEG createImage returned null")
    base_type = int(mj_type(ctypes.c_void_p(base_ptr)))
    original_base_type_u32 = int.from_bytes(ctypes.string_at(base_ptr + 8, 4), "little")
    if force_base_type is not None:
        ctypes.memmove(base_ptr + 8, struct.pack("<I", int(force_base_type) & 0xFFFFFFFF), 4)
    base_type_after_patch = int(mj_type(ctypes.c_void_p(base_ptr)))
    ctx, ctx_rec = make_jita_context(jita, block, mode)
    if not ctx:
        raise RuntimeError(f"MicroJITA context failed: {ctx_rec}")

    before = ptr_prefix(ctx, 0x100)
    original_first = [read_ptr(ctx, off) for off in range(0, 0x20, 8)]

    # Hijack the already-registered JITA wrapper: first field is BaseImage*,
    # +8/+0x10 are TempAnalyzer caches for two modes (per disassembly).
    write_ptr(ctx, 0x00, base_ptr)
    write_ptr(ctx, 0x08, 0)
    write_ptr(ctx, 0x10, 0)
    after = ptr_prefix(ctx, 0x100)

    # Probe JITA-visible metadata after the swap.
    raw_info = ctypes.create_string_buffer(0x800)
    dev = ctypes.create_string_buffer(0x1000)
    meas = ctypes.create_string_buffer(0x2000)
    probes: dict[str, object] = {}
    for name, fn, buf in [
        ("getRawDataInfo", get_raw, raw_info),
        ("getTempDeviceConfigParams", get_temp_device, dev),
        ("getTempMeasurementParams", get_temp_measure, meas),
    ]:
        try:
            ok = bool(fn(ctypes.byref(buf), ctypes.c_void_p(ctx)))
            probes[name] = {
                "ok": ok,
                "last": int(last()),
                "u32_prefix": [int.from_bytes(buf.raw[i:i+4], "little") for i in range(0, 0x80, 4)],
                "hex_prefix": buf.raw[:0x80].hex(" "),
            }
        except Exception as exc:
            probes[name] = {"exception": repr(exc), "last": int(last())}

    raw_path = raw_path_for(jpeg)
    raw = load_raw_u16(raw_path)
    n = len(raw) if not limit or limit <= 0 else min(limit, len(raw))
    outs: list[int] = []
    ok_count = 0
    fail_count = 0
    first_fail = None
    for g in raw[:n]:
        out = ctypes.c_int32(-2147483648)
        try:
            ok = bool(gray_to_temp(ctypes.byref(out), ctypes.c_uint16(g), ctypes.c_void_p(ctx)))
        except Exception as exc:
            first_fail = first_fail or {"gray": int(g), "exception": repr(exc), "last": int(last())}
            ok = False
        if ok:
            ok_count += 1
            outs.append(int(out.value))
        else:
            fail_count += 1
            if first_fail is None:
                first_fail = {"gray": int(g), "out": int(out.value), "last": int(last())}
            outs.append(-2147483648)

    truth = load_csv_matrix(csv_path)[:n] if csv_path else None
    scale, scale_name, scale_scores = infer_scale(outs, truth)
    pred = [x / scale for x in outs]

    report = {
        "jpeg": str(jpeg),
        "csv": str(csv_path) if csv_path else None,
        "mode": mode,
        "dll_dir": str(dll_dir),
        "method": "MicroJPEG createImage -> MicroJITA create context -> overwrite wrapper[0]=BaseImage*, clear wrapper[8]/[0x10], call grayToTemperature",
        "not_answer_fitting": True,
        "base_image_ptr": hx(base_ptr),
        "base_image_type_before_patch": base_type,
        "base_image_type_field_before_patch": original_base_type_u32,
        "force_base_type": force_base_type,
        "base_image_type_after_patch": base_type_after_patch,
        "ctx_create": ctx_rec,
        "ctx_before": before,
        "ctx_original_first_four_ptrs": [hx(x) for x in original_first],
        "ctx_after_hijack": after,
        "format_after": None,
        "format_after_error": None,
        "metadata_probes": probes,
        "raw_path": str(raw_path),
        "converted_count": n,
        "gray_to_temp_ok_count": ok_count,
        "gray_to_temp_fail_count": fail_count,
        "first_fail": first_fail,
        "raw_output_int_minmax": [min(outs), max(outs)] if outs else None,
        "inferred_scale": scale,
        "inferred_scale_name": scale_name,
        "scale_scores_validation_only": scale_scores,
        "temp_c_minmax": [min(pred), max(pred)] if pred else None,
        "temp_c_mean": statistics.fmean(pred) if pred else None,
        "sample_first_32": [
            {"idx": i, "gray": int(raw[i]), "out_int": int(outs[i]), "temp_c": float(pred[i]), "csv_c": truth[i] if truth else None}
            for i in range(min(32, n))
        ],
        "validation": summarize(pred, truth) if truth and ok_count == n else None,
    }
    try:
        report["format_after"] = int(fmt(ctypes.c_void_p(ctx)))
    except Exception as exc:
        report["format_after_error"] = repr(exc)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--mode", choices=["empty", "fromjpeg"], default="empty")
    ap.add_argument("--limit", type=int, default=4096, help="0/negative means all pixels")
    ap.add_argument("--force-base-type", type=int, help="temporarily patch MicroJPEG object type field at +8 before giving it to JITA")
    ap.add_argument("--out", type=Path, default=Path("data/mini2_jita_wrapper_hijack_probe"))
    args = ap.parse_args(argv)
    rep = run_one(args.jpeg, args.csv, args.dll_dir, args.mode, args.limit, args.force_base_type)
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_{args.mode}_limit{args.limit}_jita_wrapper_hijack.json"
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:6000])
    print(f"saved_json: {out_path}")
    if rep["gray_to_temp_ok_count"] != rep["converted_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
