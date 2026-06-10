#!/usr/bin/env python3
"""Probe ThermalPicMetaTakedMaterial virtual getters via Analyzer DLLs.

Previous probes called ThermalPicInterface base exports directly; for Mini2
JPEGs the parsed object is the subclass ThermalPicMetaTakedMaterial, so the
useful methods are in the vtable override.  This script calls those virtual
functions and dumps their output buffers.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import struct
from pathlib import Path


DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")


class StdString(ctypes.Structure):
    _fields_ = [("buf", ctypes.c_char * 16), ("size", ctypes.c_size_t), ("capacity", ctypes.c_size_t)]


class StdVector(ctypes.Structure):
    _fields_ = [("begin", ctypes.c_void_p), ("end", ctypes.c_void_p), ("cap", ctypes.c_void_p)]


class SharedPtr(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("ctrl", ctypes.c_void_p)]


def add_dll_dir(dll_dir: Path) -> None:
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))
    os.chdir(str(dll_dir))


def make_std_string(text: str):
    data = text.encode("utf-8")
    s = StdString()
    keep = None
    if len(data) < 16:
        ctypes.memmove(ctypes.addressof(s), data, len(data))
        s.buf[len(data)] = 0
        s.size = len(data)
        s.capacity = 15
    else:
        keep = ctypes.create_string_buffer(data + b"\0")
        ptr = ctypes.c_void_p(ctypes.addressof(keep))
        ctypes.memmove(ctypes.addressof(s), ctypes.byref(ptr), ctypes.sizeof(ptr))
        s.size = len(data)
        s.capacity = len(data)
    return s, keep


def get_proc(dll: ctypes.CDLL, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def hx(v: int | None) -> str | None:
    return hex(int(v)) if v else None


def u64(addr: int, off: int = 0) -> int:
    return struct.unpack("<Q", ctypes.string_at(addr + off, 8))[0]


def ptr_rva(ptr: int, base: int) -> str | None:
    return hex(ptr - base) if ptr and base <= ptr < base + 0x4000000 else None


def decode(raw: bytes, n: int = 0x100) -> dict[str, object]:
    raw = raw[:n]
    return {
        "hex": raw.hex(" "),
        "u32": [struct.unpack_from("<I", raw, i)[0] for i in range(0, len(raw) - 3, 4)],
        "i32": [struct.unpack_from("<i", raw, i)[0] for i in range(0, len(raw) - 3, 4)],
        "f32": [struct.unpack_from("<f", raw, i)[0] for i in range(0, len(raw) - 3, 4)],
        "qword": [hex(struct.unpack_from("<Q", raw, i)[0]) for i in range(0, len(raw) - 7, 8)],
    }


def call_bool_vfunc(this_ptr: int, offset: int, out_size: int) -> dict[str, object]:
    vt = u64(this_ptr)
    fn = u64(vt, offset)
    out = ctypes.create_string_buffer(out_size)
    f = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(fn)
    ok = bool(f(ctypes.c_void_p(this_ptr), ctypes.byref(out)))
    rec = {"offset": hex(offset), "fn": hx(fn), "ok": ok, **decode(out.raw, min(out_size, 0x180))}
    # Parse common RawDataInfo shape if present.
    if out_size >= 0x28:
        rec["rawdata_shape_guess"] = {
            "width": struct.unpack_from("<I", out.raw, 0)[0],
            "height": struct.unpack_from("<I", out.raw, 4)[0],
            "bits_byte_at_8": out.raw[8],
            "ptr_at_0x10": hex(struct.unpack_from("<Q", out.raw, 0x10)[0]),
            "len_at_0x20": struct.unpack_from("<Q", out.raw, 0x20)[0],
        }
    return rec


def call_sharedptr_sret_vfunc(this_ptr: int, offset: int) -> dict[str, object]:
    vt = u64(this_ptr)
    fn = u64(vt, offset)
    out = SharedPtr()
    # MSVC x64 returns non-trivial shared_ptr by hidden sret: rcx=out, rdx=this.
    f = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(fn)
    rv = f(ctypes.byref(out), ctypes.c_void_p(this_ptr))
    rec = {
        "offset": hex(offset),
        "fn": hx(fn),
        "rv": hx(rv),
        "ptr": hx(out.ptr),
        "ctrl": hx(out.ctrl),
    }
    if out.ptr:
        try:
            rec["ptr_u32_0_64"] = [struct.unpack_from("<I", ctypes.string_at(out.ptr, 0x40), i)[0] for i in range(0, 0x40, 4)]
            rec["ptr_qword_0_64"] = [hex(struct.unpack_from("<Q", ctypes.string_at(out.ptr, 0x40), i)[0]) for i in range(0, 0x40, 8)]
        except Exception as exc:
            rec["ptr_read_exception"] = repr(exc)
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_tpi_vfunc_state_probe"))
    args = ap.parse_args(argv)

    jpeg_abs = args.jpeg.resolve()
    out_dir = args.out.resolve() if not args.out.is_absolute() else args.out
    add_dll_dir(args.dll_dir)
    ana = ctypes.WinDLL(str(args.dll_dir / "MicroAnalytics_Release_x64.dll"))
    pix = ctypes.WinDLL(str(args.dll_dir / "MicroPixeler_Release_x64.dll"))
    pix_base = int(pix._handle)

    st, keep = make_std_string(str(jpeg_abs))
    vec = StdVector(None, None, None)
    create_typed = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(StdString), ctypes.POINTER(StdVector), ctypes.c_bool)(
        get_proc(ana, b"?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z")
    )
    tpi_raw_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(pix, b"?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ")
    )

    report: dict[str, object] = {"jpeg": str(jpeg_abs), "materials": []}
    for material_type in (3, 4, 0, 1, 2, 5):
        for flag in (False, True):
            rec: dict[str, object] = {"material_type": material_type, "flag": flag}
            try:
                mat = int(create_typed(material_type, ctypes.byref(st), ctypes.byref(vec), flag) or 0)
                rec["mat"] = hx(mat)
                if mat:
                    rec["mat_vptr_rva_pix"] = ptr_rva(u64(mat), pix_base)
                    tpi = int(tpi_raw_ptr(ctypes.c_void_p(mat)) or 0)
                    rec["tpi"] = hx(tpi)
                    if tpi:
                        vt = u64(tpi)
                        rec["tpi_vptr"] = hx(vt)
                        rec["tpi_vptr_rva_pix"] = ptr_rva(vt, pix_base)
                        # Vtable offsets from ThermalPicInterface base order:
                        # +0x010 getGrayToTempTable(shared_ptr return)
                        # +0x060 getRawDataInfo(RawDataInfo&)
                        # +0x130 getMeasureEnvParams(MeasurementEnvParams&)
                        # +0x190 getTempMeasurementParams(TempMeasurementParameters&)
                        rec["rawDataInfo"] = call_bool_vfunc(tpi, 0x060, 0x400)
                        rec["gray_table"] = {"skipped": True}
                        rec["measureEnvParams"] = call_bool_vfunc(tpi, 0x130, 0x400)
                        rec["tempMeasurementParams"] = call_bool_vfunc(tpi, 0x190, 0x800)
            except Exception as exc:
                rec["exception"] = repr(exc)
            report["materials"].append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{jpeg_abs.stem}_tpi_vfunc_state.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": str(jpeg_abs),
        "materials": [
            {
                "type": r.get("material_type"),
                "flag": r.get("flag"),
                "mat": r.get("mat"),
                "mat_vptr": r.get("mat_vptr_rva_pix"),
                "tpi": r.get("tpi"),
                "tpi_vptr": r.get("tpi_vptr_rva_pix"),
                "gray_table": {k: (r.get("gray_table") or {}).get(k) for k in ("ptr", "ctrl", "ptr_u32_0_64")},
                "raw_ok": (r.get("rawDataInfo") or {}).get("ok"),
                "raw_shape": (r.get("rawDataInfo") or {}).get("rawdata_shape_guess"),
                "raw_u32_first24": (r.get("rawDataInfo") or {}).get("u32", [])[:24] if isinstance(r.get("rawDataInfo"), dict) else None,
                "env_ok": (r.get("measureEnvParams") or {}).get("ok"),
                "env_u32_first24": (r.get("measureEnvParams") or {}).get("u32", [])[:24] if isinstance(r.get("measureEnvParams"), dict) else None,
                "tmp_ok": (r.get("tempMeasurementParams") or {}).get("ok"),
                "tmp_u32_first48": (r.get("tempMeasurementParams") or {}).get("u32", [])[:48] if isinstance(r.get("tempMeasurementParams"), dict) else None,
                "error": r.get("exception"),
            }
            for r in report["materials"]
            if r.get("mat") or r.get("exception")
        ],
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2)[:24000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
