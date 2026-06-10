#!/usr/bin/env python3
"""Probe MicroJPEG objects using the actual MSVC member-return ABI.

This is a reverse-engineering diagnostic for HIKMICRO Mini2 radiometric JPEGs.
It does not read the exported Analyzer CSV answer matrix.  It checks whether
MicroJPEG/MicroJITA expose the same raw->temperature path when member functions
return C++ structs by value.

Important ABI finding:
For these MSVC x64 C++ member functions, decorated as returning a struct by
value (for example `MicroRImageV2::rawDataInfo()`), the arguments are:

    method(this_pointer, hidden_return_buffer)

not the initially-assumed `method(hidden_return_buffer, this_pointer)`.
The disassembly at MicroJPEG_Release_x64.dll!MicroRImageV2::rawDataInfo
loads source from `rcx + 0x518` and destination from `rdx`.
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


def hx(v: int | None) -> str | None:
    return hex(int(v)) if v else None


def f32_list(raw: bytes, n: int = 128) -> list[float]:
    return [struct.unpack_from("<f", raw, i)[0] for i in range(0, min(n, len(raw)), 4)]


def i32_list(raw: bytes, n: int = 128) -> list[int]:
    return [int.from_bytes(raw[i : i + 4], "little", signed=True) for i in range(0, min(n, len(raw)), 4)]


def u32_list(raw: bytes, n: int = 128) -> list[int]:
    return [int.from_bytes(raw[i : i + 4], "little", signed=False) for i in range(0, min(n, len(raw)), 4)]


def nonzero(raw: bytes, n: int = 512) -> list[dict[str, object]]:
    vals = u32_list(raw, n)
    return [
        {"idx": i, "off": hex(i * 4), "u32": v, "i32": int.from_bytes(raw[i*4:i*4+4], "little", signed=True), "f32": struct.unpack_from("<f", raw, i * 4)[0]}
        for i, v in enumerate(vals)
        if v
    ][:80]


def dump_ptr(ptr: int, n: int = 256) -> dict[str, object]:
    if not ptr:
        return {"ptr": None}
    try:
        raw = ctypes.string_at(ptr, n)
        return {
            "ptr": hx(ptr),
            "u64": [hex(int.from_bytes(raw[i:i+8], "little")) for i in range(0, min(n, 128), 8)],
            "u32": u32_list(raw, min(n, 128)),
            "f32": f32_list(raw, min(n, 128)),
            "hex": raw[:128].hex(" "),
        }
    except Exception as exc:
        return {"ptr": hx(ptr), "exception": repr(exc)}


def call_member_sret(dll: ctypes.CDLL, name: bytes, this_ptr: int, size: int = 0x1000) -> dict[str, object]:
    out = ctypes.create_string_buffer(size)
    # Correct for these methods: rcx=this, rdx=hidden return buffer.
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
    rv = fn(ctypes.c_void_p(this_ptr), ctypes.byref(out))
    raw = bytes(out.raw)
    return {
        "return": hx(rv),
        "nonzero_u32": nonzero(raw, 1024),
        "u32_prefix": u32_list(raw, 256),
        "i32_prefix": i32_list(raw, 256),
        "f32_prefix": f32_list(raw, 256),
        "hex_prefix": raw[:256].hex(" "),
    }


def call_member_ref(dll: ctypes.CDLL, name: bytes, this_ptr: int, size: int = 0x400) -> dict[str, object]:
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, name))
    ptr = fn(ctypes.c_void_p(this_ptr)) or 0
    rec = dump_ptr(ptr, size)
    return rec


def try_jita(jita: ctypes.CDLL, ctx: int, gray_values: list[int]) -> dict[str, object]:
    get_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(jita, b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z")
    )
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(
        get_proc(jita, b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z")
    )
    last = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita, b"?lastError@MicroSDK@@YAIXZ"))
    fmt = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(get_proc(jita, b"?format@MicroSDK@@YA?AW4JPEGFormat@1@QEAX@Z"))
    out = ctypes.create_string_buffer(0x400)
    rec: dict[str, object] = {"ctx": hx(ctx)}
    try:
        rec["format"] = int(fmt(ctypes.c_void_p(ctx)))
    except Exception as exc:
        rec["format_exception"] = repr(exc)
    try:
        ok = bool(get_raw(ctypes.byref(out), ctypes.c_void_p(ctx)))
        rec["getRawDataInfo_ok"] = ok
        rec["getRawDataInfo_last"] = int(last())
        rec["rawDataInfo_nonzero"] = nonzero(bytes(out.raw), 512)
    except Exception as exc:
        rec["getRawDataInfo_exception"] = repr(exc)
    temps = []
    for gray in gray_values:
        val = ctypes.c_int32(-999999)
        try:
            ok = bool(gray_to_temp(ctypes.byref(val), ctypes.c_uint16(gray), ctypes.c_void_p(ctx)))
            temps.append({"gray": gray, "ok": ok, "out_int": int(val.value), "last": int(last())})
        except Exception as exc:
            temps.append({"gray": gray, "exception": repr(exc)})
    rec["grayToTemperature"] = temps
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--gray", type=int, nargs="*", default=[5000, 5109, 5338, 5417])
    ap.add_argument("--out", type=Path, default=Path("data/mini2_microjpeg_correct_abi_probe"))
    args = ap.parse_args()

    add_dll_dir(args.dll_dir)
    microjpeg = ctypes.WinDLL(str(args.dll_dir / "MicroJPEG_Release_x64.dll"))
    jita = ctypes.WinDLL(str(args.dll_dir / "MicroJITA_Release_x64.dll"))

    data_buf, block = make_block(args.jpeg.read_bytes())
    create = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(
        get_proc(microjpeg, b"?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    create_bool = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(
        get_proc(microjpeg, b"?createImage@MicroSDK@@YA_NPEAPEAVBaseImage@1@AEBUBareBlock@1@@Z")
    )
    type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(microjpeg, b"?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ")
    )

    attempts: list[dict[str, object]] = []
    for label, mode in [("createImage_ret", "ret"), ("createImage_bool", "bool")]:
        rec: dict[str, object] = {"label": label}
        try:
            if mode == "ret":
                ptr = create(ctypes.byref(block)) or 0
                rec["ok"] = bool(ptr)
            else:
                op = ctypes.c_void_p()
                ok = bool(create_bool(ctypes.byref(op), ctypes.byref(block)))
                ptr = op.value or 0
                rec["ok"] = ok
            rec["ptr"] = hx(ptr)
            if ptr:
                rec["type"] = int(type_fn(ctypes.c_void_p(ptr)))
                rec["object_prefix"] = dump_ptr(ptr, 256)
                # Direct object-region dumps avoid invoking copying methods
                # whose return structs contain STL/shared ownership fields.
                # For MicroRImageV1 disassembly shows:
                #   +0x4b0 thermalJPEG Image
                #   +0x500 RawDataInfo
                #   +0x528 TempDeviceConfigParams
                rec["object_regions"] = {
                    "v1_thermalJPEG_at_0x4b0": dump_ptr(ptr + 0x4B0, 0x180),
                    "v1_rawDataInfo_at_0x500": dump_ptr(ptr + 0x500, 0x120),
                    "v1_tempDevice_at_0x528": dump_ptr(ptr + 0x528, 0x180),
                    "v1_tempMeasurement_at_0x5c0_guess": dump_ptr(ptr + 0x5C0, 0x180),
                }
                rec["methods"] = {}
                for mlabel, mname in {
                    "rawDataInfo_v1": b"?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
                    "tempDevice_v1_byval": b"?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
                    "tempMeasurement_v1": b"?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
                    "thermalJPEG_v1_byval": b"?thermalJPEG@MicroRImageV1@MicroSDK@@UEBA?AUImage@2@XZ",
                    "rawDataInfo_v2": b"?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ",
                    "tempDevice_v2_byval": b"?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ",
                    "tempMeasurement_v2": b"?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ",
                    "thermalJPEG_v2_byval": b"?thermalJPEG@MicroRImageV2@MicroSDK@@UEBA?AUImage@2@XZ",
                }.items():
                    try:
                        rec["methods"][mlabel] = call_member_sret(microjpeg, mname, ptr)
                    except Exception as exc:
                        rec["methods"][mlabel] = {"exception": repr(exc)}
                for mlabel, mname in {
                    "tempDevice_v1_ref": b"?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ",
                    "thermalJPEG_v1_ref": b"?thermalJPEG@MicroRImageV1@MicroSDK@@QEAAAEBUImage@2@XZ",
                    "tempDevice_v2_ref": b"?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ",
                    "thermalJPEG_v2_ref": b"?thermalJPEG@MicroRImageV2@MicroSDK@@QEAAAEBUImage@2@XZ",
                }.items():
                    try:
                        rec["methods"][mlabel] = call_member_ref(microjpeg, mname, ptr)
                    except Exception as exc:
                        rec["methods"][mlabel] = {"exception": repr(exc)}
                rec["jita_contexts"] = {}
                ctxs = {
                    "base_image_ptr": ptr,
                    "thermalJPEG_v1_ref_ptr": int(rec["methods"].get("thermalJPEG_v1_ref", {}).get("ptr") or "0", 16)
                    if isinstance(rec["methods"].get("thermalJPEG_v1_ref", {}), dict) and rec["methods"].get("thermalJPEG_v1_ref", {}).get("ptr")
                    else 0,
                    "thermalJPEG_ref_ptr": int(rec["methods"].get("thermalJPEG_v2_ref", {}).get("ptr") or "0", 16)
                    if isinstance(rec["methods"].get("thermalJPEG_v2_ref", {}), dict) and rec["methods"].get("thermalJPEG_v2_ref", {}).get("ptr")
                    else 0,
                }
                # Also try likely Image.data pointer from the returned/ref Image structs.
                for src in ["thermalJPEG_v1_ref", "thermalJPEG_v1_byval", "thermalJPEG_v2_ref", "thermalJPEG_v2_byval"]:
                    m = rec["methods"].get(src, {})
                    if isinstance(m, dict):
                        u64s = m.get("u64") or []
                        if isinstance(u64s, list) and u64s:
                            try:
                                ctxs[src + "_u64_0"] = int(u64s[0], 16)
                            except Exception:
                                pass
                        up = m.get("u32_prefix") or []
                        # no-op; kept for JSON evidence
                for cname, ctx in ctxs.items():
                    if ctx:
                        rec["jita_contexts"][cname] = try_jita(jita, ctx, args.gray)
        except Exception as exc:
            rec["exception"] = repr(exc)
        attempts.append(rec)

    report = {"jpeg": str(args.jpeg), "attempts": attempts}
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"{args.jpeg.stem}_microjpeg_correct_abi_probe.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:30000])
    print("saved:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
