#!/usr/bin/env python3
"""Probe the exact MicroJPEG -> BaseImage vfunc -> MicroTA TempAnalyzer path.

This avoids CSV fitting. It asks HIKMICRO's own MicroJPEG BaseImage object for
its internal RawDataInfo / temperature init structures (the same virtual calls
MicroJITA uses), then feeds those structures into MicroTA::TempAnalyzer.
CSV, when present, is validation only.
"""
from __future__ import annotations

import argparse
import ctypes
import csv
import json
import math
import os
import struct
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192
PIXELS = WIDTH * HEIGHT


class BareBlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


def add_dll_dir(p: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))


def get_proc(dll: ctypes.CDLL, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def ptr_at(addr: int, off: int = 0) -> int:
    if not addr:
        return 0
    return struct.unpack("<Q", ctypes.string_at(addr + off, 8))[0]


def u32s(buf: bytes, n: int = 0x100) -> list[int]:
    return [struct.unpack_from("<I", buf, i)[0] for i in range(0, min(n, len(buf)), 4)]


def i32s(buf: bytes, n: int = 0x100) -> list[int]:
    return [struct.unpack_from("<i", buf, i)[0] for i in range(0, min(n, len(buf)), 4)]


def f32s(buf: bytes, n: int = 0x100) -> list[float]:
    out = []
    for i in range(0, min(n, len(buf)), 4):
        try:
            out.append(struct.unpack_from("<f", buf, i)[0])
        except Exception:
            pass
    return out


def qwords(buf: bytes, n: int = 0x100) -> list[str]:
    return [hex(struct.unpack_from("<Q", buf, i)[0]) for i in range(0, min(n, len(buf)), 8)]


def csv_matrix(path: Path) -> list[float]:
    last = None
    for enc in ["utf-8-sig", "cp949", "euc-kr", "latin1"]:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as exc:
            last = exc
    else:
        raise last or RuntimeError("decode failed")
    vals: list[float] = []
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
                vals.extend(xs)
    return vals


def raw_path_for(jpeg: Path) -> Path:
    candidates = [
        Path("data/mini2_multi_image_formula/raw") / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
        Path(r"C:\Users\Jio\Downloads\auto_titration_20260513-170048\data\mini2_multi_image_formula\raw") / f"{jpeg.stem}_lpld_raw_u16_256x192.bin",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"raw not found for {jpeg}")


def validate(pred: list[float], truth: list[float]) -> dict[str, object]:
    n = min(len(pred), len(truth))
    finite = [i for i in range(n) if math.isfinite(pred[i])]
    if not finite:
        return {"count": 0}
    diffs = [pred[i] - truth[i] for i in finite]
    rdiffs = [round(pred[i], 1) - truth[i] for i in finite]
    worst = sorted(finite, key=lambda i: abs(pred[i] - truth[i]), reverse=True)[:20]
    return {
        "count": len(finite),
        "mae": sum(abs(d) for d in diffs) / len(diffs),
        "max_abs": max(abs(d) for d in diffs),
        "bias": sum(diffs) / len(diffs),
        "rounded_0p1_match_rate": sum(1 for d in rdiffs if abs(d) < 1e-9) / len(rdiffs),
        "rounded_0p1_mae": sum(abs(d) for d in rdiffs) / len(rdiffs),
        "gt0p05": sum(1 for d in diffs if abs(d) > 0.05),
        "gt0p10": sum(1 for d in diffs if abs(d) > 0.10),
        "worst": [[i, i // WIDTH, i % WIDTH, pred[i], truth[i], pred[i] - truth[i]] for i in worst],
    }


def call_vfunc(base_ptr: int, off: int, out_size: int = 0x3000) -> dict[str, object]:
    vt = ptr_at(base_ptr, 0)
    fn_addr = ptr_at(vt, off)
    out = ctypes.create_string_buffer(b"\xCC" * out_size, out_size)
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(fn_addr)
    ret = fn(ctypes.c_void_p(base_ptr), ctypes.byref(out))
    raw = out.raw
    return {
        "offset": hex(off),
        "vtable": hex(vt),
        "fn": hex(fn_addr),
        "ret": hex(ret) if ret else None,
        "out_addr": hex(ctypes.addressof(out)),
        "out_keep": out,
        "hex_0_256": raw[:0x100].hex(" "),
        "u32_0_256": u32s(raw, 0x100),
        "i32_0_256": i32s(raw, 0x100),
        "f32_0_256": f32s(raw, 0x100),
        "qword_0_256": qwords(raw, 0x100),
    }


def public_summary(rec: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in rec.items() if k != "out_keep"}


def infer_scale(ints: list[int], truth: list[float] | None) -> tuple[float, str, dict[str, float]]:
    scales = [(1, "C"), (10, "deci_C"), (100, "centi_C"), (1000, "milli_C"), (10000, "1e4_C")]
    if not truth:
        return 10, "default_deci_C", {}
    n = min(len(ints), len(truth), 10000)
    scores = {}
    for s, name in scales:
        scores[name] = sum(abs((ints[i] / s) - truth[i]) for i in range(n)) / n
    s, name = min(scales, key=lambda x: scores[x[1]])
    return float(s), name, scores


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--csv", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--call-setters", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/mini2_baseimage_vfunc_tempanalyzer_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    mj = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    ta = ctypes.WinDLL(str(args.dll_dir / "MicroTA_Release_x64.dll"))

    create_image = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(mj, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    base_type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(mj, b"?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ")
    )
    ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"??0TempAnalyzer@MicroSDK@@QEAA@AEBUTempInitParameters@1@AEBURawDataInfo@1@@Z")
    )
    dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
        get_proc(ta, b"??1TempAnalyzer@MicroSDK@@QEAA@XZ")
    )
    calculate = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint16)(
        get_proc(ta, b"?calculate@TempAnalyzer@MicroSDK@@QEAA_NAEAHG@Z")
    )
    set_temp_range = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"?setTempRange@TempAnalyzer@MicroSDK@@QEAA_NAEBUTempRange@2@@Z")
    )
    set_model = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"?setModelConfig@TempAnalyzer@MicroSDK@@QEAA_NAEBUMeasureModelParameters@2@@Z")
    )
    temp_table = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"?temperatureTable@TempAnalyzer@MicroSDK@@QEAA_NAEAUSharedBlock@2@@Z")
    )
    raw_info_get = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(ta, b"?rawDataInfo@TempAnalyzer@MicroSDK@@QEAA_NAEAURawDataInfo@2@@Z")
    )
    last_ta = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(ta, b"?lastError@MicroTA@MicroSDK@@YAIXZ"))

    jpg = args.jpeg.read_bytes()
    jpg_buf = ctypes.create_string_buffer(jpg, len(jpg))
    block = BareBlock(ctypes.cast(jpg_buf, ctypes.c_void_p), len(jpg), 0)
    base = int(create_image(ctypes.byref(block)) or 0)
    report: dict[str, object] = {"jpeg": str(args.jpeg), "base_ptr": hex(base) if base else None}
    if not base:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    report["base_type"] = int(base_type_fn(ctypes.c_void_p(base)))
    report["base_type_field_u32_at_8"] = int.from_bytes(ctypes.string_at(base + 8, 4), "little")
    report["vtable"] = hex(ptr_at(base, 0))

    # These offsets are not guessed randomly: MicroJITA disassembly calls them
    # immediately before constructing/configuring MicroTA::TempAnalyzer.
    raw_rec = call_vfunc(base, 0x68)
    meas_rec = call_vfunc(base, 0x88)
    ir_rec = call_vfunc(base, 0x38)
    keep = [jpg_buf, raw_rec["out_keep"], meas_rec["out_keep"], ir_rec["out_keep"]]
    report["vfunc_0x68_rawDataInfo_candidate"] = public_summary(raw_rec)
    report["vfunc_0x88_measurement_or_init_candidate"] = public_summary(meas_rec)
    report["vfunc_0x38_irDataInfo_candidate"] = public_summary(ir_rec)

    raw_info_ptr = int(raw_rec["ret"], 16) if raw_rec.get("ret") else ctypes.addressof(raw_rec["out_keep"])
    init_ptr = int(meas_rec["ret"], 16) if meas_rec.get("ret") else ctypes.addressof(meas_rec["out_keep"])
    analyzer = ctypes.create_string_buffer(0x40)
    keep.append(analyzer)
    report["tempanalyzer"] = {}
    try:
        rv = ctor(ctypes.byref(analyzer), ctypes.c_void_p(init_ptr), ctypes.c_void_p(raw_info_ptr))
        report["tempanalyzer"]["ctor_ret"] = hex(rv) if rv else None
        report["tempanalyzer"]["analyzer_qwords"] = qwords(analyzer.raw, 0x40)
        # Mirror the obvious MicroJITA setter sequence, but keep it optional.
        setter_results = {}
        if args.call_setters:
            try:
                ir_ptr = int(ir_rec["ret"], 16) if ir_rec.get("ret") else ctypes.addressof(ir_rec["out_keep"])
                setter_results["setTempRange_ir_plus_0xf0"] = bool(set_temp_range(ctypes.byref(analyzer), ctypes.c_void_p(ir_ptr + 0xF0)))
                setter_results["last_after_setTempRange"] = int(last_ta())
            except Exception as exc:
                setter_results["setTempRange_exception"] = repr(exc)
            try:
                setter_results["setModel_meas_plus_0x58"] = bool(set_model(ctypes.byref(analyzer), ctypes.c_void_p(init_ptr + 0x58)))
                setter_results["last_after_setModel"] = int(last_ta())
            except Exception as exc:
                setter_results["setModel_exception"] = repr(exc)
        report["tempanalyzer"]["setter_results"] = setter_results
        out_ri = ctypes.create_string_buffer(0x400)
        try:
            report["tempanalyzer"]["rawDataInfo_ok"] = bool(raw_info_get(ctypes.byref(analyzer), ctypes.byref(out_ri)))
            report["tempanalyzer"]["rawDataInfo_last"] = int(last_ta())
            report["tempanalyzer"]["rawDataInfo_u32_0_128"] = u32s(out_ri.raw, 0x80)
            report["tempanalyzer"]["rawDataInfo_qword_0_128"] = qwords(out_ri.raw, 0x80)
        except Exception as exc:
            report["tempanalyzer"]["rawDataInfo_exception"] = repr(exc)
        tbl = ctypes.create_string_buffer(0x100)
        try:
            report["tempanalyzer"]["temperatureTable_ok"] = bool(temp_table(ctypes.byref(analyzer), ctypes.byref(tbl)))
            report["tempanalyzer"]["temperatureTable_last"] = int(last_ta())
            report["tempanalyzer"]["temperatureTable_u32_0_64"] = u32s(tbl.raw, 0x40)
            report["tempanalyzer"]["temperatureTable_qword_0_64"] = qwords(tbl.raw, 0x40)
        except Exception as exc:
            report["tempanalyzer"]["temperatureTable_exception"] = repr(exc)

        raw_file = raw_path_for(args.jpeg)
        rb = raw_file.read_bytes()[: PIXELS * 2]
        grays = list(struct.unpack("<" + "H" * PIXELS, rb))
        n = PIXELS if args.limit <= 0 else min(args.limit, PIXELS)
        outs: list[int] = []
        ok_count = 0
        first_fail = None
        for g in grays[:n]:
            out = ctypes.c_int32(-2147483648)
            try:
                ok = bool(calculate(ctypes.byref(analyzer), ctypes.byref(out), ctypes.c_uint16(g)))
            except Exception as exc:
                ok = False
                if first_fail is None:
                    first_fail = {"gray": int(g), "exception": repr(exc), "last": int(last_ta())}
            if ok:
                ok_count += 1
            elif first_fail is None:
                first_fail = {"gray": int(g), "out": int(out.value), "last": int(last_ta())}
            outs.append(int(out.value))
        report["conversion"] = {
            "raw_file": str(raw_file),
            "count": n,
            "ok_count": ok_count,
            "first_fail": first_fail,
            "out_int_first32": outs[:32],
            "out_int_minmax": [min(outs), max(outs)] if outs else None,
        }
        truth = csv_matrix(args.csv)[:n] if args.csv and args.csv.exists() else None
        scale, scale_name, scale_scores = infer_scale(outs, truth)
        pred = [x / scale if x != -2147483648 else float("nan") for x in outs]
        report["conversion"].update({
            "inferred_scale_validation_only": scale,
            "inferred_scale_name_validation_only": scale_name,
            "scale_scores_validation_only": scale_scores,
            "pred_c_first32": pred[:32],
            "pred_c_minmax": [min([x for x in pred if math.isfinite(x)], default=float("nan")), max([x for x in pred if math.isfinite(x)], default=float("nan"))],
        })
        if truth:
            report["conversion"]["validation_vs_csv"] = validate(pred, truth)
    except Exception as exc:
        report["tempanalyzer_exception"] = repr(exc)
        report["last_ta"] = int(last_ta())
    finally:
        try:
            dtor(ctypes.byref(analyzer))
        except Exception as exc:
            report["dtor_exception"] = repr(exc)

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_baseimage_vfunc_tempanalyzer.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": report.get("jpeg"),
        "base_type": report.get("base_type"),
        "v68_u32_first16": report["vfunc_0x68_rawDataInfo_candidate"]["u32_0_256"][:16],
        "v88_u32_first16": report["vfunc_0x88_measurement_or_init_candidate"]["u32_0_256"][:16],
        "tempanalyzer": report.get("tempanalyzer"),
        "conversion": report.get("conversion"),
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:16000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
