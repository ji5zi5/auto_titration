#!/usr/bin/env python3
"""Probe MicroJPEG image objects with correct MSVC x64 struct-return ABI.

Previous probes called large by-value C++ member returns as method(this, out).
On MSVC x64 the hidden return buffer is passed first, so the ABI is
method(out, this). This script re-tests RawDataInfo and thermometry parameter
getters without using Analyzer CSV answers.
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


def u32s(buf: bytes, n: int = 256):
    return [int.from_bytes(buf[i:i+4], "little", signed=False) for i in range(0, min(n, len(buf)), 4)]


def i32s(buf: bytes, n: int = 256):
    return [int.from_bytes(buf[i:i+4], "little", signed=True) for i in range(0, min(n, len(buf)), 4)]


def f32s(buf: bytes, n: int = 128):
    out=[]
    for i in range(0, min(n, len(buf)), 4):
        try: out.append(struct.unpack_from('<f', buf, i)[0])
        except Exception: out.append(None)
    return out


def nonzero_u32(buf: bytes, n: int = 1024):
    vals = u32s(buf, n)
    return [{"idx": i, "off": hex(i*4), "value": v, "hex": hex(v)} for i, v in enumerate(vals) if v][:80]


def call_sret(dll, name: bytes, this_ptr: int, size: int = 0x1000):
    out = ctypes.create_string_buffer(size)
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
    rv = fn(ctypes.byref(out), ctypes.c_void_p(this_ptr))
    raw = bytes(out.raw)
    return {
        "return": hex(rv) if rv else None,
        "u32_prefix": u32s(raw, 256),
        "i32_prefix": i32s(raw, 256),
        "f32_prefix": f32s(raw, 128),
        "nonzero_u32": nonzero_u32(raw, 1024),
        "hex_prefix": raw[:256].hex(' '),
    }


def call_ref0(dll, name: bytes, this_ptr: int, size: int = 0x400):
    # For methods whose decorated name indicates returning AEBU/& rather than ?AU by value.
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
    p = fn(ctypes.c_void_p(this_ptr)) or 0
    rec = {"return_ptr": hex(p) if p else None}
    if p:
        try:
            raw = ctypes.string_at(p, size)
            rec.update({
                "u32_prefix": u32s(raw, 256),
                "i32_prefix": i32s(raw, 256),
                "f32_prefix": f32s(raw, 128),
                "nonzero_u32": nonzero_u32(raw, 1024),
                "hex_prefix": raw[:256].hex(' '),
            })
        except Exception as exc:
            rec["read_exception"] = repr(exc)
    return rec


def dump_obj(ptr: int, size: int = 0x300):
    try:
        raw = ctypes.string_at(ptr, size)
        return {"u64_prefix": [hex(int.from_bytes(raw[i:i+8], 'little')) for i in range(0, min(0x100, len(raw)), 8)], "hex_prefix": raw[:256].hex(' ')}
    except Exception as exc:
        return {"exception": repr(exc)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dll-dir', type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg', type=Path, required=True)
    ap.add_argument('--out', type=Path, default=Path('data/mini2_microjpeg_sret_probe'))
    args = ap.parse_args(argv)

    add_dll_dir(args.dll_dir)
    dll = ctypes.WinDLL(str(args.dll_dir / 'MicroJPEG_Release_x64.dll'))
    data_buf, block = make_block(args.jpeg.read_bytes())

    create_funcs = []
    create_funcs.append(('global_auto', ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(get_proc(dll, b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z')), None))
    create_funcs.append(('global_bool_auto', ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(get_proc(dll, b'?createImage@MicroSDK@@YA_NPEAPEAVBaseImage@1@AEBUBareBlock@1@@Z')), 'bool'))
    create_funcs.append(('factory_v2_bool', ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(get_proc(dll, b'?createMicroRImageV2@ImageFactory@MicroSDK@@SA_NPEAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z')), 'bool'))
    create_funcs.append(('factory_v2_ret', ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(get_proc(dll, b'?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z')), None))

    try:
        type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(get_proc(dll, b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    except Exception:
        type_fn = None

    sret_methods = {
        'BaseImage.rawDataInfo': b'?rawDataInfo@BaseImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
        'ThermalImage.rawDataInfo': b'?rawDataInfo@ThermalImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
        'MicroRImageV1.rawDataInfo': b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
        'MicroRImageV2.rawDataInfo': b'?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
        'BaseImage.tempDevice': b'?tempDeviceConfigParams@BaseImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
        'ThermalImage.tempDevice': b'?tempDeviceConfigParams@ThermalImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
        'MicroRImageV1.tempDevice.byval': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
        'MicroRImageV2.tempDevice.byval': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
        'BaseImage.tempMeasure': b'?tempMeasurementParams@BaseImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
        'ThermalImage.tempMeasure': b'?tempMeasurementParams@ThermalImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
        'MicroRImageV1.tempMeasure': b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
        'MicroRImageV2.tempMeasure': b'?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
    }
    ref_methods = {
        'MicroRImageV1.tempDevice.ref': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ',
        'MicroRImageV2.tempDevice.ref': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ',
    }

    attempts=[]
    for label, fn, mode in create_funcs:
        rec={"label": label, "ptr": None, "type": None, "methods": {}, "object": None}
        try:
            if mode == 'bool':
                op=ctypes.c_void_p()
                ok=fn(ctypes.byref(op), ctypes.byref(block))
                ptr=op.value or 0
                rec['ok']=bool(ok)
            else:
                ptr=fn(ctypes.byref(block)) or 0
            rec['ptr']=hex(ptr) if ptr else None
            if ptr:
                rec['object']=dump_obj(ptr)
                if type_fn:
                    try: rec['type']=int(type_fn(ctypes.c_void_p(ptr)))
                    except Exception as exc: rec['type_exception']=repr(exc)
                for mlabel,mname in sret_methods.items():
                    try:
                        rec['methods'][mlabel]=call_sret(dll,mname,ptr)
                    except Exception as exc:
                        rec['methods'][mlabel]={"exception":repr(exc)}
                for mlabel,mname in ref_methods.items():
                    try:
                        rec['methods'][mlabel]=call_ref0(dll,mname,ptr)
                    except Exception as exc:
                        rec['methods'][mlabel]={"exception":repr(exc)}
        except Exception as exc:
            rec['exception']=repr(exc)
        attempts.append(rec)

    report={"jpeg": str(args.jpeg), "attempts": attempts}
    args.out.mkdir(parents=True, exist_ok=True)
    out_path=args.out/f'{args.jpeg.stem}_sret_probe.json'
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2)[:30000])
    print('saved:', out_path)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
