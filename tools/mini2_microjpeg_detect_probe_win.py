#!/usr/bin/env python3
"""Try every obvious MicroJPEG image factory path for Mini2 radiometric JPEGs.

This is deliberately *not* a temperature fitter.  It checks whether the vendor
DLL can parse our IR_0000*.jpeg as a radiometric image object and expose
RawDataInfo / temperature parameter structs.  Run with Windows Python.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")


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


def u32s(buf: bytes, n=64):
    return [int.from_bytes(buf[i : i + 4], "little") for i in range(0, min(n, len(buf)), 4)]


def nonzero_u32(buf: bytes, n=256):
    vals = u32s(buf, n)
    return [{"idx": i, "value": v, "hex": hex(v)} for i, v in enumerate(vals) if v][:40]


def call_struct_method(dll: ctypes.CDLL, name: bytes, ptr: int, size=0x1000):
    out = ctypes.create_string_buffer(size)
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
    rv = fn(ctypes.c_void_p(ptr), ctypes.byref(out))
    return {"return": hex(rv) if rv else None, "u32_prefix": u32s(out.raw, 160), "nonzero_u32": nonzero_u32(out.raw, 512)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_microjpeg_detect_probe"))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    data_buf, block = make_block(args.jpeg.read_bytes())

    create_global_auto = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(dll, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    create_global_ft = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(
        get_proc(dll, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@W4FileType@1@@Z")
    )
    create_factory_ft = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(
        get_proc(dll, b"?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z")
    )
    create_bool_auto = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(
        get_proc(dll, b"?createImage@MicroSDK@@YA_NPEAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(dll, b"?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ")
    )

    methods = {
        "base_rawDataInfo": b"?rawDataInfo@BaseImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "thermal_rawDataInfo": b"?rawDataInfo@ThermalImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "v1_rawDataInfo": b"?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "v2_rawDataInfo": b"?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "base_tempDevice": b"?tempDeviceConfigParams@BaseImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "thermal_tempDevice": b"?tempDeviceConfigParams@ThermalImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "v1_tempDevice": b"?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "v2_tempDevice": b"?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "base_tempMeasure": b"?tempMeasurementParams@BaseImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
        "thermal_tempMeasure": b"?tempMeasurementParams@ThermalImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
        "v1_tempMeasure": b"?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
        "v2_tempMeasure": b"?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
    }

    attempts = []

    def probe(label: str, create_call):
        rec = {"label": label, "ptr": None, "type": None, "methods": {}}
        try:
            ptr = create_call()
            rec["ptr"] = hex(ptr) if ptr else None
            if ptr:
                try:
                    rec["type"] = int(type_fn(ctypes.c_void_p(ptr)))
                except Exception as exc:
                    rec["type_exception"] = repr(exc)
                for mlabel, mname in methods.items():
                    try:
                        rec["methods"][mlabel] = call_struct_method(dll, mname, ptr)
                    except Exception as exc:
                        rec["methods"][mlabel] = {"exception": repr(exc)}
        except Exception as exc:
            rec["exception"] = repr(exc)
        attempts.append(rec)

    probe("global_auto", lambda: create_global_auto(ctypes.byref(block)))
    outptr = ctypes.c_void_p()
    try:
        ok = create_bool_auto(ctypes.byref(outptr), ctypes.byref(block))
        ptrv = outptr.value or 0
        probe(f"global_bool_auto_ok_{int(bool(ok))}", lambda ptrv=ptrv: ptrv)
    except Exception as exc:
        attempts.append({"label": "global_bool_auto", "exception": repr(exc)})

    for ft in range(0, 12):
        probe(f"global_filetype_{ft}", lambda ft=ft: create_global_ft(ctypes.byref(block), ft))
        probe(f"factory_filetype_{ft}", lambda ft=ft: create_factory_ft(ctypes.byref(block), ft))

    report = {"jpeg": str(args.jpeg), "attempts": attempts}
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_microjpeg_detect_probe.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:10000])
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
