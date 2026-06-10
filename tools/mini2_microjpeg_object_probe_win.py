#!/usr/bin/env python3
"""Probe MicroJPEG ImageFactory objects and exported getters.

This tests whether the radiometric JPEG can be opened as MicroRImageV1/V2 and
whether its embedded RawDataInfo / temperature parameter structs can be read.
Run with Windows Python. One factory is attempted per process to avoid losing
all evidence if a C++ parser throws for a wrong block type.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")


class BareBlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("pad", ctypes.c_uint32)]


class Resolution(ctypes.Structure):
    _fields_ = [("width", ctypes.c_int32), ("height", ctypes.c_int32)]


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


def u32_prefix(buf: bytes, n=64):
    return [int.from_bytes(buf[i:i+4], "little") for i in range(0, min(n, len(buf)), 4)]


def qword_prefix(buf: bytes, n=128):
    return [hex(int.from_bytes(buf[i:i+8], "little")) for i in range(0, min(n, len(buf)), 8)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--block", type=Path, help="Use this binary block instead of the full JPEG")
    ap.add_argument("--factory", choices=["createImage", "v1", "v2", "std", "offline"], default="v1")
    ap.add_argument("--filetype", type=int, default=1)
    ap.add_argument("--width", type=int, default=256)
    ap.add_argument("--height", type=int, default=192)
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    data = args.block.read_bytes() if args.block else args.jpeg.read_bytes()
    data_buf, block = make_block(data)

    exports = {
        "createImage": b"?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z",
        "v1": b"?createMicroRImageV1@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z",
        "v2": b"?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z",
        "std": b"?createStandardRImage@ImageFactory@MicroSDK@@SAPEAVStandardRImage@2@AEBUBareBlock@2@@Z",
        "offline": b"?createFromOfflineV1AddInfoRawPtr@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@AEBUmResolution@2@@Z",
    }
    if args.factory == "createImage":
        create = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(get_proc(dll, exports["createImage"]))
        ptr = create(ctypes.byref(block), args.filetype)
    else:
        if args.factory == "offline":
            create = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.POINTER(Resolution))(get_proc(dll, exports[args.factory]))
            res = Resolution(args.width, args.height)
            ptr = create(ctypes.byref(block), ctypes.byref(res))
        else:
            create = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(get_proc(dll, exports[args.factory]))
            ptr = create(ctypes.byref(block))

    report = {"jpeg": str(args.jpeg), "block": str(args.block) if args.block else None, "block_len": len(data), "factory": args.factory, "filetype": args.filetype, "ptr": hex(ptr) if ptr else None}
    if not ptr:
        print(json.dumps(report, indent=2))
        return 2

    # Try exported struct-return methods. MSVC x64 returns non-trivial/large
    # structs through a hidden first pointer: method(ret*, this).
    method_names = {
        "v1_rawDataInfo": b"?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "v2_rawDataInfo": b"?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
        "std_irDataInfo": b"?irDataInfo@StandardRImage@MicroSDK@@QEBAAEBUIRDataInfo@2@XZ",
        "v1_tempDeviceConfigParams": b"?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "v1_tempMeasurementParams": b"?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
        "v2_tempDeviceConfigParams": b"?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
        "v2_tempMeasurementParams": b"?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
    }
    for label, name in method_names.items():
        # Only call method families that plausibly match the chosen object.
        if args.factory == "v1" and not label.startswith("v1_"):
            continue
        if args.factory == "v2" and not label.startswith("v2_"):
            continue
        if args.factory == "std" and not label.startswith("std_"):
            continue
        if args.factory == "createImage":
            # Probe all; createImage may return a derived class.
            pass
        out = ctypes.create_string_buffer(0x800)
        try:
            # Member function ABI: RCX=this, RDX=hidden return/output buffer.
            fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
            rv = fn(ctypes.c_void_p(ptr), ctypes.byref(out))
            report[label] = {
                "return": hex(rv) if rv else None,
                "u32_prefix": u32_prefix(out.raw, 160),
                "qword_prefix": qword_prefix(out.raw, 160),
            }
        except Exception as exc:
            report[label] = {"exception": repr(exc)}

    print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
