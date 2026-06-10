#!/usr/bin/env python3
"""Probe HIKMICRO Analyzer's MicroAnalytics FileParseFactory path.

This is reverse-engineering evidence only. It does not fit against exported
CSV matrices; it asks the same installed Analyzer DLLs to parse a Mini2 JPEG
and then probes the resulting MicroPixeler material interfaces.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
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
    st = StdString()
    keep = None
    if len(data) < 16:
        ctypes.memmove(ctypes.addressof(st), data, len(data))
        st.buf[len(data)] = 0
        st.size = len(data)
        st.capacity = 15
    else:
        keep = ctypes.create_string_buffer(data + b"\0")
        ptr = ctypes.c_void_p(ctypes.addressof(keep))
        ctypes.memmove(ctypes.addressof(st), ctypes.byref(ptr), ctypes.sizeof(ptr))
        st.size = len(data)
        st.capacity = len(data)
    return st, keep


def get_proc(dll, name: bytes) -> int:
    k32 = ctypes.windll.kernel32
    k32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype = ctypes.c_void_p
    addr = k32.GetProcAddress(dll._handle, name)
    if not addr:
        raise RuntimeError(f"missing export {name!r}")
    return int(addr)


def hx(value) -> str | None:
    return hex(int(value)) if value else None


def u64(addr: int) -> int:
    return int(ctypes.c_uint64.from_address(int(addr)).value)


def ptr_rva(ptr: int, base: int) -> str | None:
    return hex(int(ptr) - base) if ptr and base <= int(ptr) < base + 0x4000000 else None


def decode_block(buf: ctypes.Array, n: int = 192) -> dict[str, object]:
    raw = bytes(buf.raw[:n])
    return {
        "hex": raw.hex(" "),
        "u32": [int.from_bytes(raw[i : i + 4], "little") for i in range(0, n, 4)],
        "i32": [int.from_bytes(raw[i : i + 4], "little", signed=True) for i in range(0, n, 4)],
        "f32": [ctypes.c_float.from_buffer_copy(raw[i : i + 4]).value for i in range(0, n, 4)],
    }


def call_bool_struct(dll, export: bytes, this_ptr: int, size: int = 0x1000) -> dict[str, object]:
    out = ctypes.create_string_buffer(size)
    fn = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, export))
    ok = bool(fn(ctypes.c_void_p(this_ptr), ctypes.byref(out)))
    return {"ok": ok, **decode_block(out, 256)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll-dir", type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument("--jpeg", type=Path, default=Path("data/fixtures/mini2/IR_00001.jpeg"))
    ap.add_argument("--gray", type=int, default=5338)
    ap.add_argument("--out", type=Path, default=Path("data/mini2_microanalytics_fileparse_probe"))
    args = ap.parse_args(argv)

    orig = Path.cwd()
    jpeg_abs = args.jpeg.resolve()
    out_dir = args.out if args.out.is_absolute() else orig / args.out

    add_dll_dir(args.dll_dir)
    ana = ctypes.WinDLL(str(args.dll_dir / "MicroAnalytics_Release_x64.dll"))
    pix = ctypes.WinDLL(str(args.dll_dir / "MicroPixeler_Release_x64.dll"))
    jita = ctypes.WinDLL(str(args.dll_dir / "MicroJITA_Release_x64.dll"))

    rep: dict[str, object] = {
        "jpeg": str(jpeg_abs),
        "gray": args.gray,
        "dll_dir": str(args.dll_dir),
        "results": [],
    }
    ana_base = int(ana._handle)
    pix_base = int(pix._handle)
    st, keep = make_std_string(str(jpeg_abs))
    vec = StdVector(None, None, None)

    # Common post-parse probes.
    get_jpeg = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(pix, b"?getJPEG@TakedMaterial@MICROPIXELER@@QEBAPEAXXZ")
    )
    get_tpi = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(pix, b"?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ")
    )
    tpi_raw_ptr = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(pix, b"?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ")
    )
    j_format = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(jita, b"?format@MicroSDK@@YA?AW4JPEGFormat@1@QEAX@Z")
    )
    j_last = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita, b"?lastError@MicroSDK@@YAIXZ"))
    j_get_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(jita, b"?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z")
    )
    j_gray = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_void_p)(
        get_proc(jita, b"?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z")
    )

    parsers = []
    try:
        type_of = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(StdString))(
            get_proc(ana, b"?typeOfMaterial@FileParseFactory@MicroAnalytics@@SA?AW4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z")
        )
        rep["typeOfMaterial"] = int(type_of(ctypes.byref(st)))
    except Exception as exc:
        rep["typeOfMaterial_exception"] = repr(exc)

    try:
        fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(StdString), ctypes.POINTER(StdVector))(
            get_proc(ana, b"?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@6@@Z")
        )
        parsers.append(("MicroAnalytics_FileParseFactory_createMaterialQ_auto", lambda fn=fn: fn(ctypes.byref(st), ctypes.byref(vec))))
    except Exception as exc:
        rep["createMaterialQ_auto_setup_exception"] = repr(exc)

    try:
        fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_int32, ctypes.POINTER(StdString), ctypes.POINTER(StdVector), ctypes.c_bool)(
            get_proc(ana, b"?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z")
        )
        for mt in range(0, 16):
            parsers.append((f"MicroAnalytics_FileParseFactory_createMaterialQ_type{mt}_false", lambda mt=mt, fn=fn: fn(mt, ctypes.byref(st), ctypes.byref(vec), False)))
            parsers.append((f"MicroAnalytics_FileParseFactory_createMaterialQ_type{mt}_true", lambda mt=mt, fn=fn: fn(mt, ctypes.byref(st), ctypes.byref(vec), True)))
    except Exception as exc:
        rep["createMaterialQ_typed_setup_exception"] = repr(exc)

    for name, parser in parsers:
        rec: dict[str, object] = {"parser": name}
        try:
            mat = parser()
            rec["mat"] = hx(mat)
            if mat:
                mat_vptr = u64(mat)
                rec["mat_vptr"] = hx(mat_vptr)
                rec["mat_vptr_rva_pix"] = ptr_rva(mat_vptr, pix_base)
                rec["mat_vptr_rva_ana"] = ptr_rva(mat_vptr, ana_base)
                try:
                    jpeg_ctx = get_jpeg(ctypes.c_void_p(mat))
                    rec["getJPEG_ctx"] = hx(jpeg_ctx)
                    if jpeg_ctx:
                        rec["jita_format"] = int(j_format(jpeg_ctx))
                        rb = ctypes.create_string_buffer(0x400)
                        rec["jita_getRaw_ok"] = bool(j_get_raw(ctypes.byref(rb), jpeg_ctx))
                        rec["jita_getRaw_last"] = int(j_last())
                        rec["jita_raw"] = decode_block(rb, 192)
                        out = ctypes.c_int32(-999999)
                        rec["jita_gray_ok"] = bool(j_gray(ctypes.byref(out), ctypes.c_uint16(args.gray), jpeg_ctx))
                        rec["jita_gray_out"] = int(out.value)
                        rec["jita_gray_last"] = int(j_last())
                except Exception as exc:
                    rec["jita_exception"] = repr(exc)
                try:
                    rec["thermalPicInterface_raw"] = hx(tpi_raw_ptr(ctypes.c_void_p(mat)))
                    sp = SharedPtr()
                    get_tpi(ctypes.c_void_p(mat), ctypes.byref(sp))
                    rec["tpi_sp"] = {"ptr": hx(sp.ptr), "ctrl": hx(sp.ctrl)}
                    if sp.ptr:
                        tpi_vptr = u64(sp.ptr)
                        rec["tpi_vptr"] = hx(tpi_vptr)
                        rec["tpi_vptr_rva_pix"] = ptr_rva(tpi_vptr, pix_base)
                        for label, exp in [
                            ("tpi_rawDataInfo", b"?getRawDataInfo@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAURawDataInfo@MicroSDK@@@Z"),
                            ("tpi_measureEnvParams", b"?getMeasureEnvParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUMeasurementEnvParams@MicroSDK@@@Z"),
                            ("tpi_tempMeasurementParams", b"?getTempMeasurementParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUTempMeasurementParameters@MicroSDK@@@Z"),
                            ("tpi_capabilitiesSet", b"?getCapabilitiesSet@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUIRCapabilities@MicroSDK@@@Z"),
                            ("tpi_levelSpanParams", b"?getLevelSpanParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAULevelSpanParams@MicroSDK@@@Z"),
                        ]:
                            try:
                                rec[label] = call_bool_struct(pix, exp, int(sp.ptr))
                            except Exception as exc:
                                rec[label + "_exception"] = repr(exc)
                except Exception as exc:
                    rec["tpi_exception"] = repr(exc)
        except Exception as exc:
            rec["exception"] = repr(exc)
        rep["results"].append(rec)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{jpeg_abs.stem}_microanalytics_fileparse_probe.json"
    out_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    compact = {
        "jpeg": str(jpeg_abs),
        "typeOfMaterial": rep.get("typeOfMaterial"),
        "non_null": [
            {
                "parser": r.get("parser"),
                "mat": r.get("mat"),
                "getJPEG_ctx": r.get("getJPEG_ctx"),
                "jita_getRaw_ok": r.get("jita_getRaw_ok"),
                "jita_getRaw_last": r.get("jita_getRaw_last"),
                "tpi": r.get("tpi_sp"),
                "tpi_raw_ok": (r.get("tpi_rawDataInfo") or {}).get("ok") if isinstance(r.get("tpi_rawDataInfo"), dict) else None,
            }
            for r in rep["results"]
            if r.get("mat")
        ],
        "out": str(out_path),
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
