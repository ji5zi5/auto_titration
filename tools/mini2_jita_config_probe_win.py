#!/usr/bin/env python3
"""Probe whether MicroJITA can convert raw gray after injecting real config.

This tries the honest SDK route: create a JITA context, set RawDataInfo and
TempDeviceConfigParams from Mini2 Radiometric.json/tag metadata, then call
grayToTemperature.  It does not read the Analyzer CSV while converting.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
import zipfile
import io
from pathlib import Path

from mini2_sdk_exact_probe_win import collect_blocks


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH, HEIGHT = 256, 192


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
    return buf, BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)


def radiometric_json(jpeg: Path) -> dict:
    blocks = collect_blocks(jpeg)
    for k, v in blocks.items():
        if k.endswith("tag6_data") and v.startswith(b"PK"):
            return json.loads(zipfile.ZipFile(io.BytesIO(v)).read("Radiometric.json").decode("utf-8"))
    raise RuntimeError("Radiometric.json not found")


def u32_prefix(buf, n=0x100):
    raw = bytes(buf)
    return [int.from_bytes(raw[i:i+4], "little", signed=False) for i in range(0, min(n, len(raw)), 4)]


def i32_at(buf, off, val):
    struct.pack_into("<i", buf, off, int(val))


def u32_at(buf, off, val):
    struct.pack_into("<I", buf, off, int(val))


def build_temp_device(js: dict, variant: str) -> ctypes.Array:
    # Disassembly of MicroJITA::setTempDeviceConfigParams validates:
    # +0x58 atmospheric d3 >= -2237644
    # +0x5c humidity byte <= 100
    # +0x60 optics trans d3 <= 8192
    # +0x64 optics temp d3 >= -2237644
    ta = js["Radiometric"]["TA"]
    env = ta["EnvironmentalParameters"]
    win = ta["IRWindow"]
    buf = ctypes.create_string_buffer(0x400)
    # Try several plausible enum/initialization variants around the verified
    # validation offsets.  This avoids fitting; success/fail is from SDK only.
    if variant in {"with_type", "with_type_range"}:
        u32_at(buf, 0x00, js["Radiometric"]["StaticInfo"].get("TemperatureGear", 1))
    if variant in {"with_range", "with_type_range"}:
        lo, hi = js["Radiometric"]["StaticInfo"]["TemperatureRange"]["Range_d2"]
        # range is d2 in JSON; MicroTA often keeps temp ranges as d3.
        i32_at(buf, 0x08, lo * 10)
        i32_at(buf, 0x0C, hi * 10)
    i32_at(buf, 0x58, env["AtmosphericTemperature"]["d3"])
    # The DLL checks byte at +0x5c; pack humidity into the low byte.
    u32_at(buf, 0x5C, int(env["Humidity"]))
    i32_at(buf, 0x60, win["OpticsTransmittance"]["d3"])
    i32_at(buf, 0x64, win["OpticsTemperature"]["d3"])
    return buf


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--raw-u16", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_jita_config_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroJITA_Release_x64.dll"))
    js = radiometric_json(args.jpeg)
    raw_bytes = args.raw_u16.read_bytes()[: WIDTH * HEIGHT * 2]
    raw_vals = list(struct.unpack("<" + "H" * (WIDTH * HEIGHT), raw_bytes))

    create_empty = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p))(get_proc(dll, b"?createEmptyJPEG@MicroSDK@@YA_NAEAPEAX@Z"))
    destroy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(get_proc(dll, b"?destroy@MicroSDK@@YA_NPEAX@Z"))
    set_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, b"?setRawDataInfo@MicroSDK@@YA_NAEBURawDataInfo@1@PEAX@Z"))
    get_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z"))
    set_dev = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, b"?setTempDeviceConfigParams@MicroSDK@@YA_NAEBUTempDeviceConfigParams@1@PEAX@Z"))
    get_dev = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, b"?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z"))
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(get_proc(dll, b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z"))
    last_error = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(dll, b"?lastError@MicroSDK@@YAIXZ"))

    results = []
    for variant in ["minimal", "with_type", "with_range", "with_type_range"]:
        ctx = ctypes.c_void_p()
        ok_create = bool(create_empty(ctypes.byref(ctx)))
        rec = {"variant": variant, "create_ok": ok_create, "ctx": hex(ctx.value) if ctx.value else None}
        if not ok_create or not ctx.value:
            rec["last_error"] = int(last_error())
            results.append(rec)
            continue
        raw_buf = ctypes.create_string_buffer(raw_bytes)
        raw_info = ctypes.create_string_buffer(0x80)
        struct.pack_into("<III", raw_info, 0, WIDTH, HEIGHT, 14)
        struct.pack_into("<Q", raw_info, 0x10, ctypes.addressof(raw_buf))
        struct.pack_into("<I", raw_info, 0x20, len(raw_bytes))
        try:
            rec["set_raw_ok"] = bool(set_raw(ctypes.byref(raw_info), ctx))
            rec["error_after_set_raw"] = int(last_error())
            dev = build_temp_device(js, variant)
            rec["temp_device_input_u32"] = u32_prefix(dev, 0x80)
            rec["set_device_ok"] = bool(set_dev(ctypes.byref(dev), ctx))
            rec["error_after_set_device"] = int(last_error())
            outdev = ctypes.create_string_buffer(0x400)
            try:
                rec["get_device_ok"] = bool(get_dev(ctypes.byref(outdev), ctx))
                rec["get_device_error"] = int(last_error())
                rec["get_device_u32_prefix"] = u32_prefix(outdev, 0x100)
            except Exception as exc:
                rec["get_device_exception"] = repr(exc)
                rec["get_device_error"] = int(last_error())
            outraw = ctypes.create_string_buffer(0x100)
            rec["get_raw_ok"] = bool(get_raw(ctypes.byref(outraw), ctx))
            rec["get_raw_u32_prefix"] = u32_prefix(outraw, 0x80)
            samples = []
            ok_count = 0
            for idx in [0, 1, 2, 100, 1000, 10000, 20000, 40000, len(raw_vals)-1]:
                out = ctypes.c_int32(-2147483648)
                try:
                    ok = bool(gray_to_temp(ctypes.byref(out), ctypes.c_uint16(raw_vals[idx]), ctx))
                    ok_count += int(ok)
                    samples.append({"idx": idx, "gray": raw_vals[idx], "ok": ok, "out_int": int(out.value), "last_error": int(last_error())})
                except Exception as exc:
                    samples.append({"idx": idx, "gray": raw_vals[idx], "exception": repr(exc), "last_error": int(last_error())})
            rec["gray_sample_ok_count"] = ok_count
            rec["gray_samples"] = samples
        finally:
            try:
                destroy(ctx)
            except Exception:
                pass
        results.append(rec)

    report = {"jpeg": str(args.jpeg), "raw_u16": str(args.raw_u16), "radiometric_static": js["Radiometric"]["StaticInfo"], "results": results}
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_jita_config_probe.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
