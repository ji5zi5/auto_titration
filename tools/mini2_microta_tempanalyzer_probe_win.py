#!/usr/bin/env python3
"""Instantiate MicroTA::TempAnalyzer directly with guessed TempInitParameters.

This is a guarded reverse-engineering probe.  It calls the vendor DLL path
TempAnalyzer(TempInitParameters, RawDataInfo)->calculate(gray).  No Analyzer CSV
is used for conversion.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH, HEIGHT = 256, 192


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


def u32_prefix(buf, n=0x100):
    raw = bytes(buf)
    return [int.from_bytes(raw[i:i+4], "little") for i in range(0, min(n, len(raw)), 4)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--raw-u16", type=Path, required=True)
    ap.add_argument("--algorithm", type=int, required=True)
    ap.add_argument("--variant", choices=["zero", "range_d3", "range_d2"], default="zero")
    ap.add_argument("--out", type=Path, default=Path("data/mini2_microta_tempanalyzer_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroTA_Release_x64.dll"))
    ctor = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"??0TempAnalyzer@MicroSDK@@QEAA@AEBUTempInitParameters@1@AEBURawDataInfo@1@@Z")
    )
    dtor = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(
        get_proc(dll, b"??1TempAnalyzer@MicroSDK@@QEAA@XZ")
    )
    calculate = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint16)(
        get_proc(dll, b"?calculate@TempAnalyzer@MicroSDK@@QEAA_NAEAHG@Z")
    )
    raw_info_get = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?rawDataInfo@TempAnalyzer@MicroSDK@@QEAA_NAEAURawDataInfo@2@@Z")
    )
    temp_table = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(dll, b"?temperatureTable@TempAnalyzer@MicroSDK@@QEAA_NAEAUSharedBlock@2@@Z")
    )
    last_error = ctypes.CFUNCTYPE(ctypes.c_uint32)(
        get_proc(dll, b"?lastError@MicroTA@MicroSDK@@YAIXZ")
    )

    raw_bytes = args.raw_u16.read_bytes()[: WIDTH * HEIGHT * 2]
    raw_vals = list(struct.unpack("<" + "H" * (WIDTH * HEIGHT), raw_bytes))
    raw_buf = ctypes.create_string_buffer(raw_bytes)
    raw_info = ctypes.create_string_buffer(0x100)
    struct.pack_into("<III", raw_info, 0, WIDTH, HEIGHT, 14)
    struct.pack_into("<Q", raw_info, 0x10, ctypes.addressof(raw_buf))
    struct.pack_into("<I", raw_info, 0x20, len(raw_bytes))

    tip = ctypes.create_string_buffer(0x200)
    struct.pack_into("<I", tip, 0, args.algorithm)
    if args.variant == "range_d3":
        struct.pack_into("<ii", tip, 0x08, -102400, 768000)
    elif args.variant == "range_d2":
        struct.pack_into("<ii", tip, 0x08, -10240, 76800)

    analyzer = ctypes.create_string_buffer(0x80)
    report = {
        "raw_u16": str(args.raw_u16),
        "algorithm": args.algorithm,
        "variant": args.variant,
        "temp_init_u32": u32_prefix(tip, 0x80),
        "raw_info_u32": u32_prefix(raw_info, 0x80),
    }
    try:
        rv = ctor(ctypes.byref(analyzer), ctypes.byref(tip), ctypes.byref(raw_info))
        report["ctor_return"] = hex(rv) if rv else None
        report["analyzer_u64_prefix"] = [hex(int.from_bytes(analyzer.raw[i:i+8], "little")) for i in range(0, 0x40, 8)]
        out_raw = ctypes.create_string_buffer(0x100)
        try:
            report["rawDataInfo_ok"] = bool(raw_info_get(ctypes.byref(analyzer), ctypes.byref(out_raw)))
            report["rawDataInfo_u32"] = u32_prefix(out_raw, 0x80)
        except Exception as exc:
            report["rawDataInfo_exception"] = repr(exc)
        samples = []
        ok_count = 0
        for idx in [0, 1, 2, 100, 1000, 10000, 20000, 40000, len(raw_vals)-1]:
            out = ctypes.c_int32(-2147483648)
            try:
                ok = bool(calculate(ctypes.byref(analyzer), ctypes.byref(out), ctypes.c_uint16(raw_vals[idx])))
                ok_count += int(ok)
                samples.append({"idx": idx, "gray": raw_vals[idx], "ok": ok, "out_int": int(out.value), "last_error": int(last_error())})
            except Exception as exc:
                samples.append({"idx": idx, "gray": raw_vals[idx], "exception": repr(exc), "last_error": int(last_error())})
        report["calculate_ok_count"] = ok_count
        report["samples"] = samples
        tbl = ctypes.create_string_buffer(0x100)
        try:
            report["temperatureTable_ok"] = bool(temp_table(ctypes.byref(analyzer), ctypes.byref(tbl)))
            report["temperatureTable_u32"] = u32_prefix(tbl, 0x80)
        except Exception as exc:
            report["temperatureTable_exception"] = repr(exc)
    except Exception as exc:
        report["exception"] = repr(exc)
        report["last_error"] = int(last_error())
    finally:
        try:
            dtor(ctypes.byref(analyzer))
        except Exception as exc:
            report["dtor_exception"] = repr(exc)

    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"algo{args.algorithm}_{args.variant}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
